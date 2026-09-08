"""API de upstreams (§7) — CRUD, vínculo de circuitos e communities de operadora.

Modelo dos outros routers (circuits.py): SessionDep, require_actor e o
try/except que mapeia ConflictError→409, NotFoundError→404 e
ValidationError→400. O detalhe monta `circuitos` (papel/ordem), `sessoes`
(sessões ativas dos circuitos vinculados) e `comunidades` (A4) — o
UpstreamDetailOut (A2) é populado aqui (produces do plano).
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionOut,
    UpstreamCircuitIn,
    UpstreamCircuitOut,
    UpstreamCommunityCreate,
    UpstreamCommunityOut,
    UpstreamCreate,
    UpstreamDetailOut,
    UpstreamOut,
    UpstreamUpdate,
)
from gerenet.domain.services import upstream_communities
from gerenet.domain.services import upstreams as svc
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/upstreams", tags=["upstreams"], dependencies=[Depends(require_actor)])

SessionDep = Annotated[Session, Depends(get_db)]


def _org_kind_nome(up: models.Upstream) -> dict[str, str | None]:
    org = up.organization  # lazy: organizações por upstream são poucas e o identity-map deduplica
    return {"organization_kind": org.kind if org else None, "organization_name": org.name if org else None}


def _out_upstream(up: models.Upstream) -> UpstreamOut:
    return UpstreamOut.model_validate(up).model_copy(update=_org_kind_nome(up))


def _out_sessao(session: Session, sessao: models.BgpSession) -> BgpSessionOut:
    circ = session.get(models.Circuit, sessao.circuit_id)
    org = circ.organization if circ else None
    return BgpSessionOut.model_validate(sessao).model_copy(
        update={"organization_kind": org.kind if org else None}
    )


def _detalhe(session: Session, up: models.Upstream) -> UpstreamDetailOut:
    sessoes = [
        _out_sessao(session, s)
        for vinculo in up.circuitos
        for s in list_sessions(session, circuit_id=vinculo.circuit_id, include_disabled=False)
    ]
    comunidades = [
        UpstreamCommunityOut.model_validate(c)
        for c in upstream_communities.list_upstream_communities(session, up.id)
    ]
    valores = {
        **_org_kind_nome(up),
        "circuitos": [UpstreamCircuitOut.model_validate(v) for v in up.circuitos],
        "sessoes": sessoes,
        "comunidades": comunidades,
    }
    return UpstreamDetailOut.model_validate(up).model_copy(update=valores)


@router.get("", response_model=list[UpstreamOut])
def listar(
    session: SessionDep,
    organization_id: int | None = None,
    include_disabled: bool = False,
) -> list:
    return [
        _out_upstream(up)
        for up in svc.list_upstreams(
            session, organization_id=organization_id, include_disabled=include_disabled
        )
    ]


@router.post("", response_model=UpstreamOut, status_code=201)
def criar(
    data: UpstreamCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return _out_upstream(svc.create_upstream(session, data, actor=actor.nome))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{upstream_id}", response_model=UpstreamDetailOut)
def detalhar(upstream_id: int, session: SessionDep) -> object:
    try:
        return _detalhe(session, svc.get_upstream(session, upstream_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{upstream_id}", response_model=UpstreamOut)
def atualizar(
    upstream_id: int,
    data: UpstreamUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            up = svc.disable_upstream(session, upstream_id, actor=actor.nome)
        else:
            up = svc.update_upstream(session, upstream_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out_upstream(up)


@router.post("/{upstream_id}/circuits", response_model=UpstreamDetailOut)
def vincular_circuito(
    upstream_id: int,
    data: UpstreamCircuitIn,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    """Vincula um circuito (§7) — os defaults caem nas sessões aqui (serviço)."""
    try:
        svc.vincular_circuito(
            session, upstream_id, data.circuit_id, papel=data.papel, ordem=data.ordem, actor=actor.nome
        )
        return _detalhe(session, svc.get_upstream(session, upstream_id))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{upstream_id}/circuits/{circuit_id}", status_code=204)
def desvincular_circuito(
    upstream_id: int, circuit_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> None:
    """Remove o vínculo (linha deletável; trilha na auditoria)."""
    try:
        svc.desvincular_circuito(session, upstream_id, circuit_id, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{upstream_id}/communities", response_model=UpstreamCommunityOut, status_code=201)
def add_community(
    upstream_id: int,
    data: UpstreamCommunityCreate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    """Cadastra community de operadora com valor concreto (§7.1)."""
    try:
        return upstream_communities.add_upstream_community(session, upstream_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{upstream_id}/communities/{community_id}", status_code=204)
def remove_community(
    upstream_id: int, community_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> None:
    """Remove community de operadora (evento upstream_community.remove)."""
    try:
        upstream_communities.remove_upstream_community(
            session, upstream_id, community_id, actor=actor.nome
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
