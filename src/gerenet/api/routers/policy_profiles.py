from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import PolicyProfileOut, PolicyProfileUpdate
from gerenet.domain.services import policy_profiles as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/policy-profiles",
    tags=["policy-profiles"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[PolicyProfileOut])
def listar(
    session: SessionDep, direction: str | None = None, include_disabled: bool = False
) -> list:
    """Catálogo read-only de produtos de roteamento (§6.5/§25.5).

    Sem `direction`, lista os 6 produtos de exportação; o perfil
    `somente-autorizadas` (importação), criado pelo seed do ciclo B (§8),
    aparece com `direction=import`. A query `direction` aceita
    export|import e filtra a listagem; nada neste endpoint altera o
    equipamento.
    """
    try:
        return svc.list_policy_profiles(
            session, direction=direction, include_disabled=include_disabled
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{profile_id}", response_model=PolicyProfileOut)
def atualizar(
    profile_id: int,
    data: PolicyProfileUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        # Ruling 1: desativação pura → serviço dedicado (idempotente — Ruling 5).
        if mudancas == {"admin_status": False}:
            return svc.disable_policy_profile(session, profile_id, actor=actor.nome)
        return svc.update_policy_profile(session, profile_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
