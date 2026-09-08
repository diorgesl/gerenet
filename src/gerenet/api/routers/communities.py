"""Catálogo de communities (§25.6) — list desde o ciclo B; criação (F5)/update/disable (C3)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import CommunityCreate, CommunityOut, CommunityUpdate
from gerenet.domain.services import communities as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/communities", tags=["communities"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[CommunityOut])
def listar(session: SessionDep, tipo: str | None = None, include_disabled: bool = False) -> list:
    try:
        return svc.list_communities(session, tipo=tipo, include_disabled=include_disabled)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=CommunityOut, status_code=201)
def criar(
    data: CommunityCreate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    try:
        return svc.create_community(session, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{community_id}", response_model=CommunityOut)
def atualizar(
    community_id: int,
    data: CommunityUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        # Ruling 1: desativação pura → serviço dedicado (idempotente — Ruling 5);
        # o resto (inclusive reativação pura) → update_* genérico.
        if mudancas == {"admin_status": False}:
            return svc.disable_community(session, community_id, actor=actor.nome)
        return svc.update_community(session, community_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
