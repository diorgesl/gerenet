from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.config import get_settings
from gerenet.db import get_db
from gerenet.domain.schemas import (
    BgpSessionCreate,
    BgpSessionOut,
    BgpSessionPasswordIn,
    BgpSessionUpdate,
)
from gerenet.domain.services import bgp_sessions as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.secrets.vault_store import VaultSecretStore

router = APIRouter(prefix="/api/v1/bgp-sessions", tags=["bgp-sessions"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[BgpSessionOut])
def listar(
    session: SessionDep,
    circuit_id: int | None = None,
    device_id: int | None = None,
    include_disabled: bool = False,
) -> list:
    return svc.list_sessions(
        session,
        circuit_id=circuit_id,
        device_id=device_id,
        include_disabled=include_disabled,
    )


@router.post("", response_model=BgpSessionOut, status_code=201)
def criar(data: BgpSessionCreate, session: SessionDep) -> object:
    try:
        return svc.create_session(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{session_id}", response_model=BgpSessionOut)
def detalhar(session_id: int, session: SessionDep) -> object:
    try:
        return svc.get_session(session, session_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{session_id}", response_model=BgpSessionOut)
def atualizar(session_id: int, data: BgpSessionUpdate, session: SessionDep) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_session(session, session_id, actor="api")
        return svc.update_session(session, session_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/password", response_model=BgpSessionOut)
def definir_senha(
    session_id: int, data: BgpSessionPasswordIn, session: SessionDep
) -> object:
    """Grava a senha MD5 no Vault e registra só o path na sessão (spec §8)."""
    try:
        sessao = svc.get_session(session, session_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    caminho = f"gerenet/bgp-sessions/{sessao.id}/password"
    try:
        settings = get_settings()
        store = VaultSecretStore(settings.vault_url, settings.vault_token)
        store.set_secret(caminho, {"password": data.password})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Vault indisponível: {exc}.") from exc
    return svc.set_password(session, sessao.id, actor="api", path=caminho)
