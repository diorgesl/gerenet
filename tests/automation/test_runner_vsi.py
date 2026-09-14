"""Runner escopo-aware — CR de VSI (§5/§9.3 spec): gate, pré-check e re-diff."""
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from gerenet.automation import vsi as vsi_auto
from gerenet.automation.runner import _CHAVES_POR_ESCOPO, _chaves_incompletas, run_change
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.models import CredentialGroup
from gerenet.domain.schemas import (
    DeviceCreate,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
    VsiEndpointIn,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_vsi
from gerenet.domain.services.sites import create_site


class VaultFake:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _ambiente_vsi(db_session: Session):
    site = create_site(db_session, SiteCreate(name="pop-vsi-run"), actor="cli")
    grupo = CredentialGroup(
        name="automacao-vsi", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao-vsi"
    )
    db_session.add(grupo)
    db_session.commit()
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.0.0.93", credential_group_id=grupo.id,
        site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.0.0.94", credential_group_id=grupo.id,
        site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-run-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.8.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.8.2"), actor="cli")
    svc = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="run-vsi", vsi_id=900, mtu=1500,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=900),
                   VsiEndpointIn(device_id=d2.id, vid=900)],
    ), actor="cli")
    return d1, d2, svc


def _par_loopback(db_session, svc, dev) -> str:
    outros = [m for m in svc.domain.members if m.device_id != dev.id]
    return outros[0].loopback_address


def _recursos_vsi_vazios(db_session, dev, svc, *, peer_up: bool = True) -> dict:
    """Encontrado sem o VSI — re-diff aplica tudo; LDP UP passa no pré-check."""
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [], "vsi": [],
        "mpls_ldp_peer": ([{"peer_id": _par_loopback(db_session, svc, dev), "estado": "up"}]
                          if peer_up else []),
        "config_backup": {"backup": True},
    }


def _recursos_vsi_aplicados(db_session, dev, svc, *, estado: str = "up") -> dict:
    """Encontrado com o VSI e a Vlanif da ponta — os dois blocos constam (skip §5.1)."""
    ep = next(e for e in svc.endpoints if e.device_id == dev.id)
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [{"nome": ep.interface, "phy": "up", "protocolo": "up",
                        "enderecos_v4": [], "enderecos_v6": [], "vpn": None}],
        "vsi": [{"name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": estado, "mtu": svc.mtu,
                 "peers": [{"peer": _par_loopback(db_session, svc, dev), "estado": "up"}],
                 "acs": [{"interface": ep.interface, "estado": "up"}]}],
        "mpls_ldp_peer": [{"peer_id": _par_loopback(db_session, svc, dev), "estado": "up"}],
        "config_backup": {"backup": True},
    }


def _cr_vsi_aprovada(db_session, d1, d2, svc) -> models.ChangeRequest:
    plano = vsi_auto.plan_provision_vsi(db_session, svc)
    cr = models.ChangeRequest(
        escopo="vsi", vsi_id=svc.id, acao="provision", criticidade="media",
        motivo="Ativação do VSI.", status="aprovado",
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


def _fakes_de_mudanca(monkeypatch, colas: list[dict], aplica: Callable | None = None):
    """Orquestra as fakes: cola retorna uma coleção por chamada (pré → pós)."""
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)

    def _coleta(session, device, cred, settings, base):
        recursos = colas.pop(0) if colas else {}
        return dict(recursos), {}, {}

    def _aplica_padrao(device, username, password, commands, settings):
        return {"config": ("\n".join(commands) + "\n")}

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr("gerenet.automation.runner._conectar_e_aplicar", aplica or _aplica_padrao)


def test_gate_de_recursos_do_escopo_vsi() -> None:
    assert _CHAVES_POR_ESCOPO["vsi"] == ("interfaces", "vsi", "config_backup")
    assert _chaves_incompletas({"interfaces": [], "config_backup": ""}, {}, "vsi") == ["vsi"]


def test_run_change_vsi_pre_check_ldp_bloqueia(
    db_session: Session, tmp_path: Path, monkeypatch,
) -> None:
    """Sem o par LDP listado na coleta o step falha ANTES de tocar o equipamento."""
    d1, d2, svc = _ambiente_vsi(db_session)
    cr = _cr_vsi_aprovada(db_session, d1, d2, svc)
    colas = [_recursos_vsi_vazios(db_session, d1, svc, peer_up=False)] * 4
    _fakes_de_mudanca(monkeypatch, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    assert "LDP" in (cr.steps[0].erro or "")


def test_run_change_vsi_pos_down_vira_com_divergencia(
    db_session: Session, tmp_path: Path, monkeypatch,
) -> None:
    """VSI que subiu fora de UP no pós-check (§13) ⇒ CR com_divergencia."""
    d1, d2, svc = _ambiente_vsi(db_session)
    cr = _cr_vsi_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_vsi_vazios(db_session, d1, svc), _recursos_vsi_aplicados(db_session, d1, svc, estado="down"),
        _recursos_vsi_vazios(db_session, d2, svc), _recursos_vsi_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "com_divergencia"
    db_session.refresh(cr)
    assert cr.status == "com_divergencia"
    step_a = next(s for s in cr.steps if s.device_id == d1.id)
    assert any(i["tipo"] == "vsi.estado" and i["severidade"] == "critica"
               for i in step_a.post_check_json["items"])


def test_run_change_vsi_blocos_ja_presentes_marcam_pulado(
    db_session: Session, tmp_path: Path, monkeypatch,
) -> None:
    """Re-diff §5.3 reconhece os blocos do VSI: presente ⇒ pula, não reaplica."""
    d1, d2, svc = _ambiente_vsi(db_session)
    cr = _cr_vsi_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_vsi_aplicados(db_session, d1, svc), _recursos_vsi_aplicados(db_session, d1, svc),
        _recursos_vsi_aplicados(db_session, d2, svc), _recursos_vsi_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert {s.status for s in cr.steps} == {"pulado"}


def test_run_change_vsi_falha_so_no_pe_b_vira_parcial(
    db_session: Session, tmp_path: Path, monkeypatch,
) -> None:
    """Step do PE B falha na aplicação ⇒ CR parcial (A aplicado, B falhou).

    É o caso do §9.3 que manda reconciliar: o serviço fica parcialmente
    provisionado, com uma ponta de pé e a outra não.
    """
    d1, d2, svc = _ambiente_vsi(db_session)
    cr = _cr_vsi_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_vsi_vazios(db_session, d1, svc), _recursos_vsi_aplicados(db_session, d1, svc),
        _recursos_vsi_vazios(db_session, d2, svc),
    ]

    def _aplica(device, username, password, commands, settings):
        if device.name == d2.name:
            raise ValueError("falha crítica do VRP no PE B")
        return {"config": ("\n".join(commands) + "\n")}

    _fakes_de_mudanca(monkeypatch, colas, aplica=_aplica)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "parcial"
    db_session.refresh(cr)
    assert cr.status == "parcial"
    assert {
        next(s for s in cr.steps if s.device_id == dev.id).status for dev in (d1, d2)
    } == {"aplicado", "falhou"}
