"""Usuários e sessões (login local, §17).

Hash de senha: scrypt da stdlib (nenhuma dependência nova). Formato:
``scrypt$N$r$p$salt_hex$key_hex``. Sessões: token opaco no cookie; no banco
só o sha256 hex do token; expirada é apagada lazy na primeira leitura.
Segredos: senha e hash nunca aparecem em log/resposta/trilha (o ``mascarar``
de domain/audit cobre as chaves sensíveis da auditoria).
"""
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_SENHA_MINIMA = 8
_SENHA_MAXIMA = 128

# Hash scrypt de uma senha fake conhecida ("dummy-timing-1") — nenhuma
# credencial real; serve só para o scrypt rodar mesmo quando o usuário não
# existe, uniformizando o tempo do login (sem enumeração por latência).
_DUMMY_HASH = (
    "scrypt$16384$8$1$480dc0f31ea1298cc9d74546c59fe76c"
    "$7bcfd9c1b46bd714bdd98f617932b0be6f6cb1ebb81e27f957d593fa1687e62f"
)


def hash_password(senha: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    chave = hashlib.scrypt(senha.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_BYTES)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${chave.hex()}"


def verify_password(senha: str, armazenado: str) -> bool:
    """Verifica contra o formato scrypt; formato inválido → False (sem exceção)."""
    if not isinstance(armazenado, str):
        return False  # hash envenenado no banco: nunca estourar AttributeError (500)
    try:
        prefixo, n_s, r_s, p_s, salt_hex, chave_hex = armazenado.split("$")
        if prefixo != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        chave = hashlib.scrypt(
            senha.encode(), salt=salt, n=int(n_s), r=int(r_s), p=int(p_s), dklen=_KEY_BYTES
        )
        return hmac.compare_digest(chave.hex(), chave_hex)
    except (ValueError, TypeError):
        return False


def _valida_senha(senha: str) -> None:
    if len(senha) < _SENHA_MINIMA:
        raise ValidationError(f"Senha deve ter pelo menos {_SENHA_MINIMA} caracteres.")
    if len(senha) > _SENHA_MAXIMA:
        raise ValidationError(f"Senha deve ter no máximo {_SENHA_MAXIMA} caracteres.")


def create_user(
    session: Session, *, username: str, password: str, role: str, actor: str = "cli"
) -> models.User:
    if not 1 <= len(username) <= 64:
        raise ValidationError("Username deve ter entre 1 e 64 caracteres.")
    _valida_senha(password)
    if role not in models.USER_ROLES:
        raise ValidationError("Perfil inválido.")
    if session.scalar(select(models.User).where(models.User.username == username)) is not None:
        raise ConflictError("Username já existe.")
    usuario = models.User(username=username, password_hash=hash_password(password), role=role)
    session.add(usuario)
    session.flush()
    registrar(
        session,
        tipo="user.create",
        ator=actor,
        objeto="user",
        objeto_id=usuario.id,
        depois={"username": usuario.username, "role": usuario.role},
    )
    return usuario


def list_users(session: Session, include_disabled: bool = False) -> list[models.User]:
    stmt = select(models.User).order_by(models.User.username)
    if not include_disabled:
        stmt = stmt.where(models.User.is_active.is_(True))
    return list(session.scalars(stmt))


def update_user(
    session: Session,
    user_id: int,
    *,
    username: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    actor: str = "cli",
) -> models.User:
    usuario = session.get(models.User, user_id)
    if usuario is None:
        raise NotFoundError("Usuário não encontrado.")
    antes: dict = {}
    depois: dict = {}
    if username is not None:
        if not 1 <= len(username) <= 64:
            raise ValidationError("Username deve ter entre 1 e 64 caracteres.")
        ocupado = session.scalar(
            select(models.User).where(models.User.username == username, models.User.id != user_id)
        )
        if ocupado is not None:
            raise ConflictError("Username já existe.")
        antes["username"] = usuario.username
        usuario.username = username
        depois["username"] = username
    if role is not None:
        if role not in models.USER_ROLES:
            raise ValidationError("Perfil inválido.")
        antes["role"] = usuario.role
        usuario.role = role
        depois["role"] = role
    if is_active is not None:
        antes["is_active"] = usuario.is_active
        usuario.is_active = is_active
        depois["is_active"] = is_active
    registrar(
        session,
        tipo="user.update",
        ator=actor,
        objeto="user",
        objeto_id=usuario.id,
        antes=antes,
        depois=depois,
    )
    return usuario


def reset_password(session: Session, user_id: int, *, password: str, actor: str = "cli") -> models.User:
    _valida_senha(password)
    usuario = session.get(models.User, user_id)
    if usuario is None:
        raise NotFoundError("Usuário não encontrado.")
    # Segurança: reset invalida todas as sessões do usuário (spec §4.5).
    session.execute(delete(models.UserSession).where(models.UserSession.user_id == user_id))
    usuario.password_hash = hash_password(password)
    registrar(
        session,
        tipo="user.reset_password",
        ator=actor,
        objeto="user",
        objeto_id=usuario.id,
        depois={"password_reset": True},
    )
    return usuario


def autenticar(session: Session, username: str, password: str) -> models.User | None:
    """Valida credenciais; None para usuário inexistente, inativo ou senha errada."""
    usuario = session.scalar(select(models.User).where(models.User.username == username))
    # Timing uniforme: o scrypt roda SEMPRE (mesmo para usuário inexistente ou
    # inativo), evitando enumeração de usernames pela diferença de latência.
    hash_a_testar = usuario.password_hash if usuario else _DUMMY_HASH
    valida = verify_password(password, hash_a_testar)
    if not usuario or not usuario.is_active or not valida:
        return None
    return usuario


def iniciar_sessao(session: Session, usuario: models.User, *, settings: Settings) -> str:
    """Cria a sessão e devolve o token (seu sha256 fica no banco)."""
    token = secrets.token_urlsafe(32)
    expira = datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds)
    session.add(
        models.UserSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=usuario.id, expires_at=expira)
    )
    return token


def validar_sessao(session: Session, token: str) -> models.User | None:
    linha = session.execute(
        select(models.UserSession, models.User)
        .join(models.User, models.UserSession.user_id == models.User.id)
        .where(models.UserSession.token_hash == hashlib.sha256(token.encode()).hexdigest())
    ).first()
    if linha is None:
        return None
    sessao, usuario = linha
    if sessao.expires_at <= datetime.now(UTC):
        session.delete(sessao)
        session.commit()
        return None
    return usuario


def encerrar_sessao(session: Session, token: str) -> models.User | None:
    """Apaga a sessão; devolve o usuário para a auditoria (None se token inválido)."""
    linha = session.execute(
        select(models.UserSession, models.User)
        .join(models.User, models.UserSession.user_id == models.User.id)
        .where(models.UserSession.token_hash == hashlib.sha256(token.encode()).hexdigest())
    ).first()
    if linha is None:
        return None
    sessao, usuario = linha
    session.delete(sessao)
    return usuario
