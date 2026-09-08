"""Fluxo de mudança controlada (spec §4/§7): estados, aprovação, rollback.

Regras (spec ciclo D): criar já planeja (nasce `rascunho` com steps + diff);
aprovação única com papel aprovador/admin e aprovador ≠ solicitante;
transições inválidas ⇒ ValidationError; rollback = novo CR inverso em
`aguardando_aprovacao` com `rollback_de`; reconciliação de `erro|parcial`
recomputa só os steps não aplicados.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gerenet.automation import changes, removal
from gerenet.domain import models, schemas
from gerenet.domain.audit import registrar
from gerenet.domain.services.circuits import get_circuit
from gerenet.domain.services.errors import (
    ConflictError,
    PlanoRollbackVazio,
    PlanoVazio,
    ValidationError,
)

TRANSICOES: dict[str, set[str]] = {
    "rascunho": {"aguardando_aprovacao", "cancelado"},
    "aguardando_aprovacao": {"aprovado", "rejeitado", "cancelado"},
    "aprovado": {"executando", "cancelado"},
    "executando": {"aplicado", "com_divergencia", "parcial", "erro"},
    "erro": {"aguardando_aprovacao"},  # via reconciliar
    "parcial": {"aguardando_aprovacao"},
    "aplicado": set(),
    "com_divergencia": set(),
    "rejeitado": set(),
    "cancelado": set(),
}

_ATUAIS = ("aplicado", "com_divergencia", "parcial", "erro")

# Escopos SEM reconciliação/rollback automáticos (mensagem por escopo real §5):
# o l2vc é reagendado por CR de remoção/provision nova (o re-diff aplica só a
# ponta ausente — runbook §3.3); o vsi é multiponto em fase posterior.
_RECONCILIA_INDISPONIVEL = {
    "l2vc": (
        "Reconciliação automática indisponível para CR de escopo l2vc. "
        "Crie uma CR de remoção (--acao remove) ou uma CR de provision nova (o re-diff "
        "aplica só a ponta ausente) — runbook §3.3."
    ),
    "vsi": (
        "Reconciliação automática indisponível para CR de escopo vsi — "
        "provisionamento multiponto em fase posterior."
    ),
}
_ROLLBACK_INDISPONIVEL = {
    "l2vc": (
        "Rollback automático indisponível para CR de escopo l2vc. "
        "Crie uma CR de remoção (--acao remove) ou reverta manualmente — runbook §3.3."
    ),
    "vsi": (
        "Rollback automático indisponível para CR de escopo vsi — "
        "provisionamento multiponto em fase posterior."
    ),
}


def _transita(
    session: Session, cr: models.ChangeRequest, novo: str, *, ator: str, tipo: str,
) -> None:
    if novo not in TRANSICOES[cr.status]:
        raise ValidationError(f"Transição inválida: {cr.status} → {novo}.")
    antes = cr.status
    cr.status = novo
    registrar(
        session, tipo=tipo, ator=ator, objeto="change_request",
        objeto_id=cr.id, antes={"status": antes}, depois={"status": novo},
    )


def _cria_steps(session: Session, cr: models.ChangeRequest, plano: list[changes.PlanoDevice]) -> None:
    for item in plano:
        session.add(models.ChangeStep(
            change_request_id=cr.id, device_id=item.device_id, status="pendente",
            plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
            aviso=item.aviso,
        ))


def create_change_request(
    session: Session, data: schemas.ChangeRequestCreate, *, ator_id: int | None = None, actor: str = "cli",
) -> models.ChangeRequest:
    """Cria a CR já planejada (rascunho com steps), por escopo (§5 fase 4).

    O schema validou a coerência do escopo (circuit_id/l2vc_id/upstream_id
    conforme o caso); o fluxo de circuito do ciclo D permanece intacto abaixo.
    """
    if data.escopo == "l2vc":
        return _create_l2vc(session, data, ator_id=ator_id, actor=actor)
    if data.escopo == "upstream":
        return _create_upstream(session, data, ator_id=ator_id, actor=actor)
    circ = get_circuit(session, data.circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe mudanças.")
    if data.acao == "provision":
        plano = changes.plan_provision(session, circ)
    else:
        plano = changes.plan_remocao(session, circ)  # ValidationError sem snapshot ok (§5.2)
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao=data.acao, criticidade=data.criticidade,
        motivo=data.motivo, ticket=data.ticket, solicitante_id=ator_id,
        status="rascunho",
    )
    session.add(cr)
    session.flush()
    _cria_steps(session, cr, plano)
    if not cr.steps:
        raise PlanoVazio(
            "Circuito sem sessões ativas — cadastre sessões do circuito antes de planejar."
        )
    registrar(
        session, tipo="change.created", ator=actor, objeto="change_request",
        objeto_id=cr.id, antes=None,
        depois={"circuit_id": circ.id, "acao": cr.acao, "criticidade": cr.criticidade,
                "steps": len(cr.steps), "blocos": sum(len(s.plano_json) for s in cr.steps)},
    )
    session.commit()
    session.refresh(cr)
    return cr


def _create_l2vc(
    session: Session, data: schemas.ChangeRequestCreate, *, ator_id: int | None = None, actor: str = "cli",
) -> models.ChangeRequest:
    """CR de serviço L2VC — mesmo ciclo do circuito (§5 fase 4): plano na
    criação, validações de estado do serviço, PlanoVazio sem pontas."""
    from gerenet.automation import l2vc as l2vc_auto
    from gerenet.domain.services.mpls import get_l2vc

    servico = get_l2vc(session, data.l2vc_id)  # NotFoundError propaga (404)
    if not servico.admin_status:
        raise ConflictError("Serviço L2VC desativado não recebe mudanças.")
    dom = servico.domain
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe mudanças.")
    plano = (
        l2vc_auto.plan_provision_l2vc(session, servico)
        if data.acao == "provision"
        else l2vc_auto.plan_remocao_l2vc(session, servico)
    )
    cr = models.ChangeRequest(
        circuit_id=None, l2vc_id=servico.id, acao=data.acao, criticidade=data.criticidade,
        motivo=data.motivo, ticket=data.ticket, solicitante_id=ator_id, status="rascunho",
        escopo="l2vc",
    )
    session.add(cr)
    session.flush()
    _cria_steps(session, cr, plano)
    if not cr.steps:
        raise PlanoVazio("Serviço L2VC sem pontas ativas — revalide antes de planejar.")
    registrar(
        session, tipo="change.created", ator=actor, objeto="change_request",
        objeto_id=cr.id, antes=None,
        depois={"l2vc_id": servico.id, "acao": cr.acao, "criticidade": cr.criticidade,
                "steps": len(cr.steps), "blocos": sum(len(s.plano_json) for s in cr.steps)},
    )
    session.commit()
    session.refresh(cr)
    return cr


def _create_upstream(
    session: Session, data: schemas.ChangeRequestCreate, *, ator_id: int | None = None, actor: str = "cli",
) -> models.ChangeRequest:
    """CR de upstream (fase 5, §7) — mesmo ciclo do circuito (§5): plano na
    criação agregado por device, validações de estado do upstream e PlanoVazio
    sem sessões ativas sobre os vínculos."""
    from gerenet.automation import upstream as up_auto
    from gerenet.domain.services.bgp_sessions import list_sessions
    from gerenet.domain.services.upstreams import get_upstream

    up = get_upstream(session, data.upstream_id)  # NotFoundError propaga (404)
    if not up.admin_status:
        raise ConflictError(f"Upstream {up.name} desativado não recebe mudanças.")
    # R-20: `plan_*_upstream` sinaliza upstream sem sessões ativas como
    # ValidationError — o PlanoVazio (422, sem CR órfã) sai ANTES do planner;
    # as ValidationError informativas dele (ex.: sem snapshot na remoção §5.2)
    # continuam propagando.
    if not any(
        list_sessions(session, circuit_id=vin.circuit_id,
                      include_disabled=(data.acao == "remove"))
        for vin in up.circuitos
    ):
        raise PlanoVazio(
            f"Upstream {up.name} sem circuitos/sessões ativas — cadastre antes de planejar."
        )
    plano = (
        up_auto.plan_provision_upstream(session, up)
        if data.acao == "provision"
        else up_auto.plan_remocao_upstream(session, up)
    )
    cr = models.ChangeRequest(
        circuit_id=None, upstream_id=up.id, escopo="upstream", acao=data.acao,
        criticidade=data.criticidade, motivo=data.motivo, ticket=data.ticket,
        solicitante_id=ator_id, status="rascunho",
    )
    session.add(cr)
    session.flush()
    _cria_steps(session, cr, plano)
    if not cr.steps:
        raise PlanoVazio(
            "Upstream sem circuitos/sessões ativas — cadastre antes de planejar."
        )
    registrar(
        session, tipo="change.created", ator=actor, objeto="change_request",
        objeto_id=cr.id, antes=None,
        depois={"upstream_id": up.id, "acao": cr.acao, "criticidade": cr.criticidade,
                "steps": len(cr.steps), "blocos": sum(len(s.plano_json) for s in cr.steps)},
    )
    session.commit()
    session.refresh(cr)
    return cr


def get_change_request(session: Session, cr_id: int) -> models.ChangeRequest:
    cr = session.get(
        models.ChangeRequest, cr_id,
        options=[selectinload(models.ChangeRequest.l2vc)],
    )
    if cr is None:
        from gerenet.domain.services.errors import NotFoundError
        raise NotFoundError(f"Change request {cr_id} não encontrada.")
    return cr


def list_change_requests(
    session: Session, *, status: str | None = None,
    solicitante_id: int | None = None, circuit_id: int | None = None,
    escopo: str | None = None,
) -> list[models.ChangeRequest]:
    stmt = (
        select(models.ChangeRequest)
        .options(selectinload(models.ChangeRequest.l2vc))
        .order_by(models.ChangeRequest.id.desc())
    )
    if status is not None:
        stmt = stmt.where(models.ChangeRequest.status == status)
    if solicitante_id is not None:
        stmt = stmt.where(models.ChangeRequest.solicitante_id == solicitante_id)
    if circuit_id is not None:
        stmt = stmt.where(models.ChangeRequest.circuit_id == circuit_id)
    if escopo is not None:
        stmt = stmt.where(models.ChangeRequest.escopo == escopo)
    return list(session.scalars(stmt))


def enviar_para_aprovacao(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    _transita(session, cr, "aguardando_aprovacao", ator=actor, tipo="change.sent_for_approval")
    session.commit()
    return cr


def _ciclo_novo(session: Session, cr_id: int) -> bool:
    """CR reaberta por `reconciliar` (ciclo novo de aprovação, §4.1)?

    O último evento entre as decisões da CR (approved/rejected/reconciled)
    decide: reconciliação depois de uma decisão abre ciclo novo — a
    duplicidade (§4.3) vale por ciclo; sem esse evento, nenhuma decisão existe.
    """
    ultimo = session.scalar(
        select(models.AuditEvent.type)
        .where(
            models.AuditEvent.type.in_(("change.approved", "change.rejected", "change.reconciled")),
            models.AuditEvent.details["objeto"].as_string() == "change_request",
            models.AuditEvent.details["objeto_id"].as_integer() == cr_id,
        )
        .order_by(models.AuditEvent.id.desc())
        .limit(1)
    )
    return ultimo == "change.reconciled"


def aprovar(
    session: Session, cr_id: int, *, ator_id: int | None = None, actor: str,
    decisao: str, comentario: str | None = None,
) -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    if cr.approvals and not _ciclo_novo(session, cr_id):
        raise ValidationError("Change request já decidida — aprovação é única (spec §4.3).")
    if ator_id is None:
        raise ValidationError("Aprovador não informado.")
    if decisao not in ("aprovar", "rejeitar"):
        raise ValidationError(f"Decisão inválida: {decisao!r} — use \"aprovar\" ou \"rejeitar\".")
    if ator_id is not None and cr.solicitante_id is not None and cr.solicitante_id == ator_id:
        raise ValidationError("Aprovador não pode ser o próprio solicitante (spec §3.3).")
    _transita(session, cr, "aprovado" if decisao == "aprovar" else "rejeitado",
              ator=actor, tipo="change.approved" if decisao == "aprovar" else "change.rejected")
    session.add(models.Approval(
        change_request_id=cr.id, user_id=ator_id, decisao=decisao, comentario=comentario,
    ))
    session.commit()
    session.refresh(cr)
    return cr


def cancelar(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    _transita(session, cr, "cancelado", ator=actor, tipo="change.cancelled")
    session.commit()
    return cr


def marcar_executando(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    """Transição aprovado → executando; idempotente quando já executando.

    O WORKER é o transitor autoritativo (T7): re-chamadas do endpoint ao
    enfileirar de novo não devem falhar com transição inválida — o enqueue
    já validou aprovado e segurou o lock de CR.
    """
    cr = get_change_request(session, cr_id)
    if cr.status == "executando":
        return cr
    _transita(session, cr, "executando", ator=actor, tipo="change.executing")
    session.commit()
    return cr


def _replaneja(session: Session, cr: models.ChangeRequest, device_id: int) -> changes.PlanoDevice:
    if cr.escopo == "upstream":
        from gerenet.automation import upstream as up_auto
        from gerenet.domain.services.upstreams import get_upstream

        up = get_upstream(session, cr.upstream_id)
        plano = (
            up_auto.plan_provision_upstream(session, up)
            if cr.acao == "provision"
            else up_auto.plan_remocao_upstream(session, up)
        )
        for item in plano:
            if item.device_id == device_id:
                return item
        return changes.PlanoDevice(device_id=device_id, blocos=[], baseline_snapshot_id=None)
    circ = get_circuit(session, cr.circuit_id)
    if cr.acao == "provision":
        plano = changes.plan_provision(session, circ)
    else:
        plano = changes.plan_remocao(session, circ)
    for item in plano:
        if item.device_id == device_id:
            return item
    return changes.PlanoDevice(device_id=device_id, blocos=[], baseline_snapshot_id=None)


def reconciliar(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    if cr.escopo in _RECONCILIA_INDISPONIVEL:
        raise ValidationError(_RECONCILIA_INDISPONIVEL[cr.escopo])
    if cr.status not in ("erro", "parcial"):
        raise ValidationError(f"Reconciliar só de erro|parcial (atual: {cr.status}).")
    pendentes = [s for s in cr.steps if s.status in ("pendente", "falhou")]
    if not pendentes:
        raise ValidationError("Nenhum step não aplicado a recomputar.")
    for step in pendentes:
        item = _replaneja(session, cr, step.device_id)
        step.plano_json = item.blocos
        step.baseline_snapshot_id = item.baseline_snapshot_id
        step.aviso = item.aviso
        step.status = "pendente"
        step.erro = None
    _transita(session, cr, "aguardando_aprovacao", ator=actor, tipo="change.reconciled")
    session.commit()
    session.refresh(cr)
    return cr


def gerar_rollback(
    session: Session, cr_id: int, *, ator_id: int | None = None, actor: str = "cli",
) -> models.ChangeRequest:
    """Novo CR inverso em aguardando_aprovacao (§7), com rollback_de.

    provision → remove com plano derivado do BASELINE de cada step aplicado
    (o que a mudança adicionou, visto do snapshot pré-mudança);
    remove → provision re-renderizado do desejado (SoT atual). No escopo
    upstream a mecânica é a mesma: o undo do filho remove agrega os circuitos
    vinculados por device (na ordem dos vínculos), como o plano de provision.
    """
    cr = get_change_request(session, cr_id)
    if cr.escopo in _ROLLBACK_INDISPONIVEL:
        raise ValidationError(_ROLLBACK_INDISPONIVEL[cr.escopo])
    if cr.status not in ("aplicado", "com_divergencia", "parcial") or not any(
        s.status == "aplicado" for s in cr.steps
    ):
        raise ValidationError("Rollback só de aplicado/com_divergencia/parcial com steps aplicados.")
    if cr.escopo == "upstream":
        from gerenet.domain.services.upstreams import get_upstream

        up = get_upstream(session, cr.upstream_id)
        filho = models.ChangeRequest(
            circuit_id=None, upstream_id=up.id, escopo="upstream",
            acao="remove" if cr.acao == "provision" else "provision",
            criticidade=cr.criticidade, motivo=f"Rollback do CR #{cr.id}",
            solicitante_id=ator_id, status="aguardando_aprovacao", rollback_de=cr.id,
        )
    else:
        circ = get_circuit(session, cr.circuit_id)
        filho = models.ChangeRequest(
            circuit_id=cr.circuit_id, acao="remove" if cr.acao == "provision" else "provision",
            criticidade=cr.criticidade, motivo=f"Rollback do CR #{cr.id}",
            solicitante_id=ator_id, status="aguardando_aprovacao", rollback_de=cr.id,
        )
    session.add(filho)
    session.flush()
    for step in cr.steps:
        if step.status != "aplicado":
            continue
        if cr.acao == "provision":
            if step.baseline_snapshot_id is None:
                continue  # sem baseline: sem evidência do encontrado — não inventa (§5.2)
            snap = session.get(models.DeviceSnapshot, step.baseline_snapshot_id)
            if snap is None:
                continue
            if cr.escopo == "upstream":
                # agregação por device: undo de cada circuito vinculado no
                # mesmo step do filho (na ordem dos vínculos, `ordem`)
                blocos = [
                    b for vin in up.circuitos
                    for b in removal.blocos_remocao(session, vin.circuito, step.device_id, snapshot=snap)
                ]
            else:
                blocos = removal.blocos_remocao(session, circ, step.device_id, snapshot=snap)
            session.add(models.ChangeStep(
                change_request_id=filho.id, device_id=step.device_id, status="pendente",
                plano_json=blocos, baseline_snapshot_id=snap.id,
            ))
        else:
            item = _replaneja(session, cr, step.device_id)
            session.add(models.ChangeStep(
                change_request_id=filho.id, device_id=step.device_id, status="pendente",
                plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
                aviso=item.aviso,
            ))
    if not filho.steps:
        # Tudo pulado por baseline ausente (§5.2): NADA persiste — sem CR
        # órfã (a sessão descartada pelo get_db descarta o filho non-commitado).
        raise PlanoRollbackVazio(
            "Sem steps aplicados com baseline — rollback automático indisponível; "
            "faça manualmente."
        )
    registrar(
        session, tipo="change.rollback_created", ator=actor, objeto="change_request",
        objeto_id=cr.id, depois={"filho": filho.id, "acao": filho.acao},
    )
    session.commit()
    session.refresh(filho)
    return filho
