"""Runner escopo-aware — CR de L2VC (§5/§7 spec): gate, pré-check e pós-check."""
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from gerenet.automation import l2vc as l2vc_auto
from gerenet.automation.runner import _chaves_incompletas, run_change
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.models import CredentialGroup
from gerenet.domain.schemas import (
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.sites import create_site


class VaultFake:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _ambiente_l2vc(db_session: Session):
    site = create_site(db_session, SiteCreate(name="pop-l2vc-run"), actor="cli")
    grupo = CredentialGroup(
        name="automacao-l2vc", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao-l2vc"
    )
    db_session.add(grupo)
    db_session.commit()
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.0.0.91", credential_group_id=grupo.id,
        site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.0.0.92", credential_group_id=grupo.id,
        site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-run"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.7.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.7.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="run-l2vc", vc_id=600,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=401),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=402),
        ],
    ), actor="cli")
    return d1, d2, svc


def _par_loopback(db_session, svc, dev) -> str:
    outros = [m for m in svc.domain.members if m.device_id != dev.id]
    return outros[0].loopback_address


def _recursos_l2vc_vazios(db_session, dev, svc, *, peer_up: bool = True) -> dict:
    """Encontrado sem o AC — re-diff aplica tudo; LDP UP passa no pré-check."""
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [], "l2vc": [],
        "mpls_ldp_peer": ([{"peer_id": _par_loopback(db_session, svc, dev), "estado": "up"}]
                          if peer_up else []),
        "config_backup": {"backup": True},
    }


def _subs_do_render(_db_session, dev, svc) -> list[str]:
    """Nomes dos ACs no encontrado — AC untag: a própria interface (porta/Eth-Trunk L3)."""
    return [ep.interface for ep in svc.endpoints if ep.device_id == dev.id]


def _recursos_l2vc_aplicados(db_session, dev, svc, *, estado: str = "up") -> dict:
    nomes = _subs_do_render(db_session, dev, svc)
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [{"nome": n, "phy": "up", "protocolo": "up",
                        "enderecos_v4": [], "enderecos_v6": [], "vpn": None} for n in nomes],
        "l2vc": [{"vc_id": svc.vc_id, "interface": n, "estado": estado} for n in nomes],
        "mpls_ldp_peer": [{"peer_id": _par_loopback(db_session, svc, dev), "estado": "up"}],
        "config_backup": {"backup": True},
    }


def _cr_l2vc_aprovada(db_session, d1, d2, svc) -> models.ChangeRequest:
    plano = l2vc_auto.plan_provision_l2vc(db_session, svc)
    cr = models.ChangeRequest(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", criticidade="media",
        motivo="Ativação L2VC.", status="aprovado",
    )
    db_session.add(cr)
    db_session.flush()
    for item in plano:
        db_session.add(models.ChangeStep(
            change_request_id=cr.id, device_id=item.device_id, status="pendente",
            plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
            aviso=item.aviso,
        ))
    db_session.commit()
    db_session.refresh(cr)
    return cr


def _fakes_de_mudanca(
    monkeypatch, db_session, dev, colas: list[dict], aplica: Callable | None = None,
):
    """Orquestra as fakes: cola retorna uma coleção por chamada (pré → pós).

    `aplica` (opcional) substitui o echo padrão da aplicação — espelho do
    `aplicacoes` do ciclo D (test_runner_change.py), aqui um callable.
    """
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    ultimo: list[dict | None] = [None]

    def _coleta(session, device, cred, settings, base):
        recursos = colas.pop(0) if colas else ultimo[0]
        ultimo[0] = recursos
        return dict(recursos), {}, {}

    def _aplica_padrao(device, username, password, commands, settings):
        return {"config": ("\n".join(commands) + "\n")}

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr("gerenet.automation.runner._conectar_e_aplicar", aplica or _aplica_padrao)


def test_run_change_l2vc_fluxo_ok(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_l2vc_vazios(db_session, d1, svc), _recursos_l2vc_aplicados(db_session, d1, svc),
        _recursos_l2vc_vazios(db_session, d2, svc), _recursos_l2vc_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert cr.status == "aplicado"
    assert {s.status for s in cr.steps} == {"aplicado"}
    for step in cr.steps:
        assert step.post_check_json and "items" in step.post_check_json
        assert all(i["severidade"] != "critica" for i in step.post_check_json["items"])


def test_run_change_l2vc_pre_check_ldp_down_aborta(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [_recursos_l2vc_vazios(db_session, d1, svc, peer_up=False)] * 4
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    assert "LDP" in (cr.steps[0].erro or "")


def test_run_change_l2vc_pos_down_vira_com_divergencia(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_l2vc_vazios(db_session, d1, svc), _recursos_l2vc_aplicados(db_session, d1, svc, estado="down"),
        _recursos_l2vc_vazios(db_session, d2, svc), _recursos_l2vc_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "com_divergencia"
    db_session.refresh(cr)
    assert cr.status == "com_divergencia"
    step_a = next(s for s in cr.steps if s.device_id == d1.id)
    assert any(i["tipo"] == "l2vc.estado" and i["severidade"] == "critica"
               for i in step_a.post_check_json["items"])


def test_run_change_l2vc_bloco_ja_presente_marca_pulado(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_l2vc_aplicados(db_session, d1, svc), _recursos_l2vc_aplicados(db_session, d1, svc),
        _recursos_l2vc_aplicados(db_session, d2, svc), _recursos_l2vc_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert {s.status for s in cr.steps} == {"pulado"}


def test_run_change_l2vc_falha_so_no_device_b_vira_parcial(
    db_session: Session, tmp_path: Path, monkeypatch,
) -> None:
    """Step do device B falha na aplicação ⇒ CR parcial (A aplicado, B falhou)."""
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_l2vc_vazios(db_session, d1, svc), _recursos_l2vc_aplicados(db_session, d1, svc),
        _recursos_l2vc_vazios(db_session, d2, svc),
    ]
    def _aplica(device, username, password, commands, settings):
        if device.name == d2.name:
            raise ValueError("falha crítica do VRP no device B")
        return {"config": ("\n".join(commands) + "\n")}

    _fakes_de_mudanca(monkeypatch, db_session, d1, colas, aplica=_aplica)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "parcial"
    db_session.refresh(cr)
    assert cr.status == "parcial"
    assert {
        next(s for s in cr.steps if s.device_id == dev.id).status for dev in (d1, d2)
    } == {"aplicado", "falhou"}


def test_chaves_incompletas_por_escopo() -> None:
    # gate do circuito continua exigindo bgp_peers; l2vc não exige (switch sem BGP)
    assert _chaves_incompletas({}, {}, escopo="circuito") == ["interfaces", "bgp_peers", "config_backup"]
    assert _chaves_incompletas({}, {}, escopo="l2vc") == ["interfaces", "l2vc", "config_backup"]
    # coleta de circuito com "l2vc" ausente não bloqueia
    assert "l2vc" not in _chaves_incompletas(
        {"interfaces": [], "bgp_peers": [], "config_backup": {}}, {}, escopo="circuito")
