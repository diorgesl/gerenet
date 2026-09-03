from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import SiteCreate, SiteOut, SiteUpdate
from gerenet.domain.services import sites as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/sites", tags=["sites"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[SiteOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_sites(session, include_disabled=include_disabled)


@router.post("", response_model=SiteOut, status_code=201)
def criar(data: SiteCreate, session: SessionDep) -> object:
    try:
        return svc.create_site(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{site_id}", response_model=SiteOut)
def detalhar(site_id: int, session: SessionDep) -> object:
    try:
        return svc.get_site(session, site_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{site_id}", response_model=SiteOut)
def atualizar(site_id: int, data: SiteUpdate, session: SessionDep) -> object:
    """PATCH único (ruling 1): desativação pura vira site.disable; o resto vira update."""
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_site(session, site_id, actor="api")
        return svc.update_site(session, site_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
