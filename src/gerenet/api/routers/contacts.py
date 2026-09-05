from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import ContactCreate, ContactOut, ContactUpdate
from gerenet.domain.services import contacts as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"], dependencies=[Depends(require_actor)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[ContactOut])
def listar(
    session: SessionDep, organization_id: int | None = None, include_disabled: bool = False
) -> list:
    return svc.list_contacts(session, organization_id=organization_id, include_disabled=include_disabled)


@router.post("", response_model=ContactOut, status_code=201)
def criar(
    data: ContactCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.create_contact(session, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{contact_id}", response_model=ContactOut)
def detalhar(contact_id: int, session: SessionDep) -> object:
    try:
        return svc.get_contact(session, contact_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{contact_id}", response_model=ContactOut)
def atualizar(
    contact_id: int,
    data: ContactUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_contact(session, contact_id, actor=actor.nome)
        return svc.update_contact(session, contact_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
