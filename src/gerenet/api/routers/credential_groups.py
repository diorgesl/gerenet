from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import CredentialGroupCreate, CredentialGroupOut, CredentialGroupUpdate
from gerenet.domain.services import credential_groups as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/credential-groups",
    tags=["credential-groups"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[CredentialGroupOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_credential_groups(session, include_disabled=include_disabled)


@router.post("", response_model=CredentialGroupOut, status_code=201)
def criar(
    data: CredentialGroupCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.create_credential_group(
            session, name=data.name, vault_path=data.vault_path, kind=data.kind, actor=actor.nome
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{group_id}", response_model=CredentialGroupOut)
def detalhar(group_id: int, session: SessionDep) -> object:
    try:
        return svc.get_credential_group(session, group_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{group_id}", response_model=CredentialGroupOut)
def atualizar(
    group_id: int,
    data: CredentialGroupUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_credential_group(session, group_id, actor=actor.nome)
        if mudancas == {"admin_status": True}:
            return svc.enable_credential_group(session, group_id, actor=actor.nome)
        return svc.update_credential_group(session, group_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
