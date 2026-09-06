import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from gerenet.config import Settings, get_settings
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.services import users as svc

SESSION_COOKIE = "gerenet_sess"

SessionDep = Annotated[Session, Depends(get_db)]

SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class Actor:
    """Quem faz a chamada: usuário de sessão web ou a chave de API (nome 'api')."""

    usuario: models.User | None
    nome: str


def require_actor(request: Request, session: SessionDep, settings: SettingsDep) -> Actor:
    """Auth dual: cookie de sessão (web) OU X-Api-Key (CLI/automações).

    Perfil Visualizador é somente leitura (spec §4.3): métodos de escrita → 403.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if token is not None:
        usuario = svc.validar_sessao(session, token)
        if usuario is None:
            raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.")
        if not usuario.is_active:
            raise HTTPException(status_code=403, detail="Usuário desativado.")
        if usuario.role == "visualizador" and request.method not in ("GET", "HEAD", "OPTIONS"):
            raise HTTPException(status_code=403, detail="Perfil Visualizador permite apenas leitura.")
        return Actor(usuario=usuario, nome=usuario.username)
    x_api_key = request.headers.get("x-api-key")
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.")
    return Actor(usuario=None, nome="api")


def require_admin(actor: Annotated[Actor, Depends(require_actor)]) -> Actor:
    """Somente Administrador (usuário autenticado por sessão, §4.4)."""
    if actor.usuario is None or actor.usuario.role != "administrador":
        raise HTTPException(status_code=403, detail="Somente administradores.")
    return actor


def require_papel(*papeis: str):
    """Fábrica de dependência: exige usuário de SESSÃO com um dos papéis.

    Diferente de require_actor, chave de API não passa (o nome 'api' não tem
    papel) — aprovação/execução exigem pessoa (spec §3.3/§8).
    """

    def _checa_papel(actor: Annotated[Actor, Depends(require_actor)]) -> Actor:
        if actor.usuario is None or actor.usuario.role not in papeis:
            raise HTTPException(status_code=403, detail=f"Perfil sem permissão: {', '.join(papeis)}.")
        return actor

    return _checa_papel
