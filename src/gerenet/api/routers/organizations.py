from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import OrganizationCreate, OrganizationOut, OrganizationUpdate
from gerenet.domain.services import organizations as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/organizations", tags=["organizations"],
    dependencies=[Depends(require_actor)],
)

downstreams_router = APIRouter(
    prefix="/api/v1/downstreams", tags=["downstreams"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]


def _atualizar(
    organization_id: int, data: OrganizationUpdate, session: Session, actor: str
) -> object:
    """PATCH único (ruling 1) compartilhado das duas listas de orgs."""
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_organization(session, organization_id, actor=actor)
        return svc.update_organization(session, organization_id, data, actor=actor)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[OrganizationOut])
def listar(
    session: SessionDep,
    include_disabled: bool = False,
    kind: Literal["downstream", "parceiro", "operadora"] | None = None,
) -> list:
    return svc.list_organizations(session, include_disabled=include_disabled, kind=kind)


@router.post("", response_model=OrganizationOut, status_code=201)
def criar(
    data: OrganizationCreate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    try:
        return svc.create_organization(session, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{organization_id}", response_model=OrganizationOut)
def detalhar(organization_id: int, session: SessionDep) -> object:
    try:
        return svc.get_organization(session, organization_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{organization_id}", response_model=OrganizationOut)
def atualizar(
    organization_id: int,
    data: OrganizationUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    return _atualizar(organization_id, data, session, actor.nome)


@downstreams_router.get("", response_model=list[OrganizationOut])
def listar_downstreams(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_organizations(session, include_disabled=include_disabled, kind="downstream")


@downstreams_router.post("", response_model=OrganizationOut, status_code=201)
def criar_downstream(
    data: OrganizationCreate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    """POST de downstream: kind é sempre 'downstream' (ruling 7)."""
    dados = data.model_copy(update={"kind": "downstream"})
    try:
        return svc.create_organization(session, dados, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
