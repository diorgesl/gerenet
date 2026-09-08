"""CR de escopo upstream (fase 5, §7) — plano na criação, rollback e reconciliação.

Espelhos de `test_change_requests.py` (circuito) e `test_change_requests_l2vc.py`:
o upstream nasce `rascunho` com steps por device; a reconciliação recomputa os
steps não aplicados; o rollback gera CR inversa com `rollback_de` usando a
agregação por device dos circuitos vinculados.
"""
import pytest
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.schemas import ChangeRequestCreate
from gerenet.domain.services.change_requests import (
    create_change_request,
    gerar_rollback,
    list_change_requests,
    reconciliar,
)
from gerenet.domain.services.errors import ConflictError, PlanoVazio, ValidationError


def _cr_upstream(db_session, up, *, acao="provision"):
    return create_change_request(
        db_session,
        ChangeRequestCreate(
            escopo="upstream", upstream_id=up.id, acao=acao,
            motivo="subir trânsito", criticidade="alta",
        ),
        ator_id=None,
    )


def _snapshot_peers_up(db_session, dev, peers):
    """Snapshot success do edge com recursos mínimos (interfaces vazias; §5.1)."""
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success",
        resources={"interfaces": [], "bgp_peers": peers},
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def test_create_cr_upstream_plano_na_criacao(db_session, up_com_2_circuitos):
    up = up_com_2_circuitos
    cr = _cr_upstream(db_session, up)
    assert cr.escopo == "upstream"
    assert cr.upstream_id == up.id
    assert cr.circuit_id is None
    assert cr.status == "rascunho"
    assert cr.steps and all(s.plano_json for s in cr.steps)


def test_create_cr_upstream_sem_circuitos_eh_plano_vazio(db_session, up):
    """Upstream sem vínculos/sessões ativas ⇒ PlanoVazio antes do planner na criação."""
    antes = len(list_change_requests(db_session))
    with pytest.raises(PlanoVazio, match="sem circuitos/sessões ativas"):
        _cr_upstream(db_session, up)
    # sem CR órfã: o PlanoVazio sobe antes do add/commit
    assert len(list_change_requests(db_session)) == antes


def test_create_cr_upstream_desativado_conflita(db_session, up_com_2_circuitos):
    up = up_com_2_circuitos
    up.admin_status = False
    db_session.commit()
    with pytest.raises(ConflictError, match="desativado não recebe mudanças"):
        _cr_upstream(db_session, up)


def test_reconciliar_cr_upstream_de_parcial_recomputa_steps(
    db_session, up_com_2_circuitos, edge_device
):
    up = up_com_2_circuitos
    cr = _cr_upstream(db_session, up)
    cr.steps[0].status = "falhou"
    cr.steps[0].erro = "VRP: % Error"
    cr.status = "parcial"
    db_session.commit()
    cr_final = reconciliar(db_session, cr.id, actor="operador")
    assert cr_final.status == "aguardando_aprovacao"
    assert cr_final.steps[0].status == "pendente"
    assert cr_final.steps[0].erro is None
    assert cr_final.steps[0].plano_json  # recomputado do desejado (não vazio)
    tipo = db_session.scalar(
        select(models.AuditEvent.type)
        .where(models.AuditEvent.type == "change.reconciled")
        .order_by(models.AuditEvent.id.desc())
        .limit(1)
    )
    assert tipo == "change.reconciled"


def test_rollback_cr_upstream_provision_gera_filho_remove(
    db_session, up_com_2_circuitos, edge_device
):
    """Provision aplicado ⇒ filho remove com undo agregado dos circuitos vinculados (§5.2)."""
    up = up_com_2_circuitos
    peers = [
        {"afi": "ipv4", "peer": "100.64.10.2", "asn": 64501},
        {"afi": "ipv4", "peer": "100.64.10.6", "asn": 64501},
    ]
    _snapshot_peers_up(db_session, edge_device, peers)
    cr = _cr_upstream(db_session, up)
    cr.status = "aplicado"
    cr.steps[0].status = "aplicado"
    db_session.commit()
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="executor")
    assert filho.rollback_de == cr.id
    assert filho.escopo == "upstream"
    assert filho.upstream_id == up.id
    assert filho.circuit_id is None
    assert filho.acao == "remove"
    assert filho.status == "aguardando_aprovacao"
    assert filho.motivo == f"Rollback do CR #{cr.id}"
    assert filho.steps and all(s.plano_json for s in filho.steps)
    assert all(
        any(b["acao"] == "delete" for b in s.plano_json) for s in filho.steps
    )


def test_reconciliar_cr_l2vc_mantem_indisponivel(db_session):
    """Regressão (mínimo): o guard por escopo real continua bloqueando l2vc."""
    cr = models.ChangeRequest(
        circuit_id=None, l2vc_id=None, escopo="l2vc", acao="provision",
        criticidade="media", motivo="regressão guard", status="rascunho",
    )
    db_session.add(cr)
    db_session.commit()
    with pytest.raises(ValidationError, match="l2vc"):
        reconciliar(db_session, cr.id, actor="operador")
