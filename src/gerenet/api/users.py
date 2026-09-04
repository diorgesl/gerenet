from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from gerenet.api.deps import Actor, SessionDep, require_admin
from gerenet.domain.schemas import UserCreateIn, UserOut, UserPasswordIn, UserUpdateIn
from gerenet.domain.services import users as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/users", tags=["users"])

AdminDep = Annotated[Actor, Depends(require_admin)]


@router.get("", response_model=list[UserOut])
def listar(
    actor: AdminDep,
    session: SessionDep,
    include_disabled: bool = False,
) -> list:
    return svc.list_users(session, include_disabled=include_disabled)


@router.post("", response_model=UserOut, status_code=201)
def criar(data: UserCreateIn, actor: AdminDep, session: SessionDep) -> object:
    try:
        return svc.create_user(
            session, username=data.username, password=data.password, role=data.role, actor=actor.nome
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserOut)
def atualizar(data: UserUpdateIn, user_id: int, actor: AdminDep, session: SessionDep) -> object:
    if actor.usuario is not None and actor.usuario.id == user_id and (data.role is not None or data.is_active is not None):
        raise HTTPException(status_code=403, detail="Não é possível alterar a própria conta.")
    try:
        return svc.update_user(
            session,
            user_id,
            username=data.username,
            role=data.role,
            is_active=data.is_active,
            actor=actor.nome,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{user_id}/password", status_code=204)
def resetar_senha(data: UserPasswordIn, user_id: int, actor: AdminDep, session: SessionDep) -> None:
    try:
        svc.reset_password(session, user_id, password=data.password, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
