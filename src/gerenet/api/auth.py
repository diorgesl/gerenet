"""Autenticação local (spec ciclo C §4.2) — login, logout e sessão atual.

Senha nunca vai a log/resposta; falha de login não distingue usuário
inexistente, inativo ou senha errada (mensagem única).
"""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from gerenet.api import rate_limit
from gerenet.api.deps import SESSION_COOKIE, SessionDep
from gerenet.config import Settings, get_settings
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import UserLoginIn, UserOut
from gerenet.domain.services import users as svc

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _usuario_atual(request: Request, session: SessionDep) -> models.User:
    """Usuário da sessão do cookie para /me (web-only — X-Api-Key não vale aqui)."""
    token = request.cookies.get(SESSION_COOKIE)
    usuario = svc.validar_sessao(session, token) if token else None
    if usuario is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    if not usuario.is_active:
        raise HTTPException(status_code=403, detail="Usuário desativado.")
    return usuario


@router.post("/login", response_model=UserOut)
def login(
    data: UserLoginIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> models.User:
    ip = request.client.host if request.client is not None else "?"
    redis = rate_limit.conectar(settings)
    # Consulta ANTES do scrypt: tentativa bloqueada custa quase nada e a
    # mensagem 429 é genérica (não revela existência de usuário).
    if not rate_limit.permitir(redis, ip, data.username):
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(rate_limit.JANELA_SEGUNDOS)},
            detail="Muitas tentativas de login. Tente novamente em alguns minutos.",
        )
    usuario = svc.autenticar(session, data.username, data.password)
    if usuario is None:
        rate_limit.registrar_falha(redis, ip, data.username)
        registrar(
            session, tipo="auth.login_failed", ator=data.username, objeto="auth", objeto_id=0
        )
        # O HTTPException interrompe a teardown da sessão (rollback): o evento
        # da falha precisa ser gravado antes (trilha imutável — §18).
        session.commit()
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    rate_limit.limpar(redis, ip, data.username)
    token = svc.iniciar_sessao(session, usuario, settings=settings)
    usuario.last_login_at = datetime.now(UTC)
    registrar(
        session, tipo="auth.login", ator=usuario.username, objeto="auth", objeto_id=usuario.id
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return usuario


@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDep) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    usuario = svc.encerrar_sessao(session, token) if token else None
    if usuario is not None:
        registrar(
            session, tipo="auth.logout", ator=usuario.username, objeto="auth", objeto_id=usuario.id
        )
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=UserOut)
def me(request: Request, session: SessionDep) -> models.User:
    return _usuario_atual(request, session)
