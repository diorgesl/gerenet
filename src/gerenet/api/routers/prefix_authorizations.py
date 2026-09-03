from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import (
    PrefixAuthorizationCreate,
    PrefixAuthorizationDisable,
    PrefixAuthorizationOut,
)
from gerenet.domain.services import prefix_authorizations as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/prefix-authorizations",
    tags=["prefix-authorizations"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[PrefixAuthorizationOut])
def listar(
    session: SessionDep,
    organization_id: int | None = None,
    family: str | None = None,
    include_disabled: bool = False,
) -> list:
    return svc.list_authorizations(
        session,
        organization_id=organization_id,
        family=family,
        include_disabled=include_disabled,
    )


@router.post("", response_model=PrefixAuthorizationOut, status_code=201)
def criar(data: PrefixAuthorizationCreate, session: SessionDep) -> object:
    try:
        return svc.create_authorization(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{authorization_id}", response_model=PrefixAuthorizationOut)
def detalhar(authorization_id: int, session: SessionDep) -> object:
    try:
        return svc.get_authorization(session, authorization_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{authorization_id}", response_model=PrefixAuthorizationOut)
def desativar(
    authorization_id: int, data: PrefixAuthorizationDisable, session: SessionDep
) -> object:
    """Único PATCH possível: desativar. Mudar prefixo = desativar + criar (ruling 2)."""
    try:
        return svc.disable_authorization(session, authorization_id, actor="api")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
