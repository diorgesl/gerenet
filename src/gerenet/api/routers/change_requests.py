"""API do fluxo de mudança controlada (spec ciclo D §4–§8).

Papéis por rota (a API decide papel; o serviço não — fronteira do ciclo):
criar/enviar/cancelar/rollback/reconciliar são ações de OPERADOR (qualquer
pessoa ou chave de API autenticada — o Visualizador já é bloqueado pelo
require_actor); approvar e executar exigem pessoa com o papel certo.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from gerenet.api.deps import Actor, SessionDep, require_actor, require_papel
from gerenet.domain.schemas import ApprovalIn, ChangeRequestCreate, ChangeRequestOut
from gerenet.domain.services import change_requests as svc
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/change-requests",
    tags=["change-requests"],
    dependencies=[Depends(require_actor)],
)

ApproverDep = Annotated[Actor, Depends(require_papel("aprovador", "administrador"))]
ExecutorDep = Annotated[Actor, Depends(require_papel("executor", "administrador"))]

_MSG_SEM_SESSOES = (
    "Circuito sem sessões ativas — colete as sessões do circuito "
    "antes de planejar a criação."
)
_MSG_SEM_BASELINE = (
    "Sem steps aplicados com baseline — rollback automático indisponível; "
    "faça manualmente."
)


@router.post("", response_model=ChangeRequestOut, status_code=201)
def criar(
    data: ChangeRequestCreate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    """Cria a CR já planejada (nasce `rascunho`). Nota T3: CR sem steps é
    inexplicável — circuito sem sessões ativas ⇒ 422, sem órfão no banco."""
    try:
        if data.acao == "provision":
            circ = svc.get_circuit(session, data.circuit_id)
            if not list_sessions(session, circuit_id=circ.id):
                raise HTTPException(status_code=422, detail=_MSG_SEM_SESSOES)
        return svc.create_change_request(
            session,
            data,
            ator_id=actor.usuario.id if actor.usuario is not None else None,
            actor=actor.nome,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[ChangeRequestOut])
def listar(
    session: SessionDep,
    status: str | None = None,
    solicitante_id: int | None = None,
    circuit_id: int | None = None,
) -> list:
    return svc.list_change_requests(
        session, status=status, solicitante_id=solicitante_id, circuit_id=circuit_id
    )


@router.get("/{cr_id}", response_model=ChangeRequestOut)
def detalhar(cr_id: int, session: SessionDep) -> object:
    try:
        return svc.get_change_request(session, cr_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{cr_id}/enviar", response_model=ChangeRequestOut)
def enviar(cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        return svc.enviar_para_aprovacao(session, cr_id, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/approve", response_model=ChangeRequestOut)
def aprovar(cr_id: int, data: ApprovalIn, session: SessionDep, approver: ApproverDep) -> object:
    """Papel aprovador/admin; aprovador ≠ solicitante (spec §3.3)."""
    try:
        return svc.aprovar(
            session,
            cr_id,
            ator_id=approver.usuario.id,
            actor=approver.nome,
            decisao=data.decisao,
            comentario=data.comentario,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/cancelar", response_model=ChangeRequestOut)
def cancelar(cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        return svc.cancelar(session, cr_id, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/executar", response_model=ChangeRequestOut)
def executar(cr_id: int, session: SessionDep, executor: ExecutorDep) -> object:
    """Papel executor/admin. T7 pluga aqui o enqueue (fila gerenet-change)."""
    try:
        return svc.marcar_executando(session, cr_id, actor=executor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/rollback", response_model=ChangeRequestOut)
def rollback(cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    """Novo CR inverso em aguardando_aprovacao. Nota T4 review: filho sem steps
    (nenhum step aplicado com baseline) ≠ rollback automático — 422, sem
    inventar comandos (§5.2)."""
    try:
        filho = svc.gerar_rollback(
            session,
            cr_id,
            ator_id=actor.usuario.id if actor.usuario is not None else None,
            actor=actor.nome,
        )
        if not filho.steps:
            raise HTTPException(status_code=422, detail=_MSG_SEM_BASELINE)
        return filho
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/reconciliar", response_model=ChangeRequestOut)
def reconciliar(
    cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.reconciliar(session, cr_id, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
