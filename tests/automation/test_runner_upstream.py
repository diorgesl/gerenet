"""Runner escopo-aware — CR de upstream (§7 spec): gate, pré-check e pós-check.

Espelho de test_runner_l2vc.py: numa CR de escopo `upstream` o circuit_id é
None — o setup do runner que chamasse get_circuit abortaria a execução por
NotFoundError. O upstream consome os MESMOS recursos do circuito
(`interfaces`/`bgp_peers`/`config_backup`) e o pré-check passa
`include_disabled=(cr.acao == "remove")` (R-22: remoção com 100% das sessões
desativadas não pode abortar).
"""
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from gerenet.automation import upstream as up_auto
from gerenet.automation.runner import _chaves_incompletas, run_change
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.models import CredentialGroup
from gerenet.domain.services.bgp_sessions import list_sessions


class VaultFake:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _grupo_credential(db_session: Session, dev) -> None:
    """Grupo no edge (o fixture `edge_device` não tem: sem credencial o step falharia)."""
    grupo = CredentialGroup(
        name="automacao-up", kind="tacacs_password",
        vault_path="gerenet/credential-groups/automacao-up",
    )
    db_session.add(grupo)
    db_session.commit()
    dev.credential_group_id = grupo.id
    db_session.commit()


def _peers_aplicados(db_session: Session, up, *, pref_rcv: int = 1000,
                     estado: str = "Established") -> list[dict]:
    """`bgp_peers` no shape real do parser (merge.py) para as sessões do upstream."""
    sessoes = [s for vin in up.circuitos for s in list_sessions(db_session, circuit_id=vin.circuit_id)]
    return [{"afi": s.afi, "peer": s.remote_address, "asn": s.asn_remote,
             "estado": estado, "pref_rcv": pref_rcv, "up_down": "1d02h"} for s in sessoes]


def _recursos_up_vazios(peers: list[dict] | None = None) -> dict:
    """Encontrado sem nada do upstream — re-diff aplica tudo; peers ao contrário."""
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [], "bgp_peers": peers or [],
        "bgp_peers_verbose": [], "config_backup": {"backup": True},
    }


def _snapshot_com_peers(db_session: Session, dev, peers: list[dict]) -> models.DeviceSnapshot:
    """Snapshot success pré-remoção (exigência §5.2 para planejar o inverso)."""
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success",
        resources={"interfaces": [], "bgp_peers": peers, "bgp_peers_verbose": [],
                   "config_backup": {"backup": True}},
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _cr_up_aprovada(db_session: Session, up, *, acao: str = "provision") -> models.ChangeRequest:
    """CR de upstream aprovada direto, com o plano real (provision/remoção agregado)."""
    plano = (
        up_auto.plan_provision_upstream(db_session, up)
        if acao == "provision"
        else up_auto.plan_remocao_upstream(db_session, up)
    )
    cr = models.ChangeRequest(
        escopo="upstream", upstream_id=up.id, acao=acao, criticidade="media",
        motivo="Mudança no upstream.", status="aprovado",
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
    """Espelho de test_runner_l2vc: coleção por chamada (pré → pós) + echo na aplicação."""
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


def test_run_change_upstream_fluxo_ok(
    db_session: Session, tmp_path: Path, monkeypatch, edge_device, up_com_2_circuitos,
) -> None:
    """Setup via upstream (circuit_id é None), gate do circuito e pré/pós-check OK."""
    _grupo_credential(db_session, edge_device)
    cr = _cr_up_aprovada(db_session, up_com_2_circuitos)
    colas = [
        _recursos_up_vazios(peers=[]),
        _recursos_up_vazios(peers=_peers_aplicados(db_session, up_com_2_circuitos)),
    ]
    _fakes_de_mudanca(monkeypatch, db_session, edge_device, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert cr.status == "aplicado"
    assert {s.status for s in cr.steps} == {"aplicado"}
    for step in cr.steps:
        assert step.post_check_json and "items" in step.post_check_json
        assert all(i["severidade"] != "critica" for i in step.post_check_json["items"])


def test_run_change_upstream_grava_prefixos_antes_depois(
    db_session: Session, tmp_path: Path, monkeypatch, edge_device, up_com_2_circuitos,
) -> None:
    """§7.1/design §5 (G1/I-3): o step grava `prefixos_antes`/`prefixos_depois`
    no post_check_json — soma `pref_rcv` por família no recurso pré e no pós.

    CR de REMOÇÃO (o cenário com antes reais): o encontrado pré-mudança ainda
    lista os peers (2 × 1350) e o plano de delete os remove — no pós não há
    mais linha do upstream ⇒ depois {}. (Provision com peers já presentes
    abortaria no re-diff §5.3: bindings do plano exigem `bgp_peers_verbose` e
    os blocos route-policy constam como ausentes — o passo serve ao registro.)
    """
    _grupo_credential(db_session, edge_device)
    _snapshot_com_peers(db_session, edge_device,
                        _peers_aplicados(db_session, up_com_2_circuitos))
    cr = _cr_up_aprovada(db_session, up_com_2_circuitos, acao="remove")

    def _linhas(pref_rcv: int) -> list[dict]:
        """Duas linhas `bgp_peers` no shape real do parser, com a contagem dada."""
        return [
            {"afi": "ipv4", "peer": "100.64.10.2", "asn": 64501, "estado": "Established",
             "pref_rcv": pref_rcv, "up_down": "1d02h"},
            {"afi": "ipv4", "peer": "100.64.10.6", "asn": 64501, "estado": "Established",
             "pref_rcv": pref_rcv, "up_down": "1d02h"},
        ]

    colas = [
        _recursos_up_vazios(peers=_linhas(1350)),  # pré: peers ainda no ar (2 × 1350)
        _recursos_up_vazios(peers=[]),              # pós: sessões do upstream removidas
    ]
    _fakes_de_mudanca(monkeypatch, db_session, edge_device, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    step = next(s for s in cr.steps if s.device_id == edge_device.id)
    assert step.status == "aplicado"
    assert step.post_check_json["prefixos_antes"] == {"ipv4": 2700}
    assert step.post_check_json["prefixos_depois"] == {}


def test_run_change_upstream_pre_check_erro_aborta(
    db_session: Session, tmp_path: Path, monkeypatch, edge_device, up_com_2_circuitos,
) -> None:
    """Pré-check devolve erro ⇒ ValueError no runner ⇒ step falhou e CR em erro."""
    _grupo_credential(db_session, edge_device)
    cr = _cr_up_aprovada(db_session, up_com_2_circuitos)
    chamadas: list[dict] = []

    def _falha(session, up, device, recursos, *, include_disabled=False):
        chamadas.append({"include_disabled": include_disabled})
        return (
            "Peer 100.64.10.2 (ipv4) já consta com ASN 64599 (esperado 64501) "
            "— configuração conflitante, revalide o circuito."
        )

    monkeypatch.setattr("gerenet.automation.upstream.valida_pre_upstream", _falha)
    _fakes_de_mudanca(monkeypatch, db_session, edge_device, [_recursos_up_vazios()])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "erro"
    # provision passa include_disabled=False (só a remoção aceita desativadas, R-22)
    assert chamadas == [{"include_disabled": False}]
    db_session.refresh(cr)
    assert cr.status == "erro"
    assert cr.steps[0].status == "falhou"
    assert "ASN 64599" in (cr.steps[0].erro or "")


def test_run_change_upstream_remove_include_disabled_chega(
    db_session: Session, tmp_path: Path, monkeypatch, edge_device, up_com_2_circuitos,
) -> None:
    """CR de remoção passa include_disabled=True ao pré-check (R-22) e não aborta."""
    _grupo_credential(db_session, edge_device)
    _snapshot_com_peers(db_session, edge_device, _peers_aplicados(db_session, up_com_2_circuitos))
    cr = _cr_up_aprovada(db_session, up_com_2_circuitos, acao="remove")
    chamadas: list[dict] = []

    def _ok(session, up, device, recursos, *, include_disabled=False):
        chamadas.append({"include_disabled": include_disabled})

    monkeypatch.setattr("gerenet.automation.upstream.valida_pre_upstream", _ok)
    colas = [_recursos_up_vazios(), _recursos_up_vazios()]
    _fakes_de_mudanca(monkeypatch, db_session, edge_device, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert chamadas == [{"include_disabled": True}]
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert {s.status for s in cr.steps} == {"pulado"}


def test_run_change_upstream_pos_critica_vira_com_divergencia(
    db_session: Session, tmp_path: Path, monkeypatch, edge_device, up_com_2_circuitos,
) -> None:
    """Pós-check: sessões do upstream ausentes/fora do esperado ⇒ com_divergencia."""
    _grupo_credential(db_session, edge_device)
    cr = _cr_up_aprovada(db_session, up_com_2_circuitos)
    colas = [_recursos_up_vazios(), _recursos_up_vazios()]  # aplicado, mas pos sem peers
    _fakes_de_mudanca(monkeypatch, db_session, edge_device, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "com_divergencia"
    db_session.refresh(cr)
    assert cr.status == "com_divergencia"
    step = next(s for s in cr.steps if s.device_id == edge_device.id)
    assert step.status == "aplicado"
    assert any(i["severidade"] == "critica" for i in step.post_check_json["items"])
    assert any(
        i["tipo"] == "upstream.peer_ausente" and i["severidade"] == "critica"
        for i in step.post_check_json["items"]
    )


def test_chaves_incompletas_por_escopo_upstream() -> None:
    """Escopo upstream reusa o gate do circuito (peers BGP no edge NE8000)."""
    assert _chaves_incompletas({}, {}, escopo="upstream") == ["interfaces", "bgp_peers", "config_backup"]
    # coleta com "bgp_peers" presente não bloqueia mesmo sem os recursos do l2vc
    assert "l2vc" not in _chaves_incompletas(
        {"interfaces": [], "bgp_peers": [], "config_backup": {}}, {}, escopo="upstream")
