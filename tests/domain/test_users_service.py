"""Mapeamento de User/UserSession + migration (T1)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from gerenet.domain import models


def test_user_model_grava_e_le(db_session) -> None:
    u = models.User(username="ana-teste", password_hash="scrypt$16384$8$1$00$00", role="operador")
    db_session.add(u)
    db_session.commit()

    achado = db_session.scalar(select(models.User).where(models.User.username == "ana-teste"))
    assert achado is not None
    assert achado.role == "operador"
    assert achado.is_active is True
    assert achado.id == 1


def test_user_session_model(db_session) -> None:
    u = models.User(username="carol", password_hash="x", role="operador")
    db_session.add(u)
    db_session.commit()

    s = models.UserSession(
        token_hash="a" * 64,
        user_id=u.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(s)
    db_session.commit()

    linha = db_session.scalar(
        select(models.UserSession).where(models.UserSession.token_hash == "a" * 64)
    )
    assert linha is not None and linha.user_id == u.id

"""Serviço de usuários — hash scrypt, CRUD, autenticação e sessões."""

import pytest
from sqlalchemy.orm import Session

from gerenet.config import Settings
from gerenet.domain.services import users as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


def test_verify_password_nao_string_retorna_false() -> None:
    assert svc.verify_password("qualquer", None) is False
    assert svc.verify_password("qualquer", 123) is False
    assert svc.verify_password("qualquer", "rotulo-quebrado") is False
    assert svc.verify_password("qualquer", "md5$ajs8db") is False  # prefixo errado


def test_senha_acima_de_128_rejeitada_no_servico(db_session) -> None:
    with pytest.raises(ValidationError):
        svc.create_user(
            db_session, username="user-longo", password="x" * 129, role="visualizador", actor="cli"
        )


def test_hash_password_formato_salt_unico() -> None:
    h1 = svc.hash_password("senha-super-8")
    h2 = svc.hash_password("senha-super-8")
    assert h1 != h2  # salt aleatório
    assert h1.startswith("scrypt$16384$8$1$") and len(h1.split("$")) == 6


def test_verify_password_ok_e_falha_corrompido() -> None:
    h = svc.hash_password("senha-super-8")
    assert svc.verify_password("senha-super-8", h) is True
    assert svc.verify_password("outra-senha", h) is False
    assert svc.verify_password("qualquer", "lixo") is False
    assert svc.verify_password("qualquer", "scrypt$16384$8$1$zz$zz") is False


def test_create_user_valida_e_audita(db_session) -> None:
    u = svc.create_user(db_session, username="op1", password="senha-super-8", role="operador", actor="cli")
    assert u.id == 1 and u.is_active is True
    assert u.password_hash != "senha-super-8" and u.password_hash.startswith("scrypt$")

    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "user.create")
    )
    assert evento is not None and evento.actor == "cli"
    assert "password" not in db_session.query(models.AuditEvent).filter(
        models.AuditEvent.type == "user.create"
    ).one().details.get("depois", {})

    with pytest.raises(ConflictError):
        svc.create_user(db_session, username="op1", password="senha-super-8", role="operador")
    with pytest.raises(ValidationError):
        svc.create_user(db_session, username="curto", password="123", role="operador")
    with pytest.raises(ValidationError):
        svc.create_user(db_session, username="nao-existe-role-x", password="senha-super-8", role="root")


def test_list_users_sem_inativos(db_session) -> None:
    u = svc.create_user(db_session, username="ops", password="senha-super-8", role="operador")
    svc.create_user(db_session, username="vis", password="senha-super-8", role="visualizador")
    svc.update_user(db_session, u.id, is_active=False, actor="cli")

    assert [u.username for u in svc.list_users(db_session)] == ["vis"]
    assert {u.username for u in svc.list_users(db_session, include_disabled=True)} == {"ops", "vis"}


def test_update_user_audita_e_protege_duplicidade(db_session) -> None:
    svc.create_user(db_session, username="ana", password="senha-super-8", role="operador")
    svc.create_user(db_session, username="bruno", password="senha-super-8", role="operador")
    ana = svc.list_users(db_session)[0]

    atualizado = svc.update_user(db_session, ana.id, role="aprovador", actor="cli")
    assert atualizado.role == "aprovador"

    with pytest.raises(NotFoundError):
        svc.update_user(db_session, 9999, username="x")
    with pytest.raises(ConflictError):
        svc.update_user(db_session, ana.id, username="bruno")
    with pytest.raises(ValidationError):
        svc.update_user(db_session, ana.id, role="super")

    trilha = db_session.scalar(
        select(models.AuditEvent).where(
            models.AuditEvent.type == "user.update", models.AuditEvent.actor == "cli"
        )
    )
    assert trilha.details["antes"]["role"] == "operador"
    assert trilha.details["depois"] == {"role": "aprovador"}


def test_reset_password_invalida_sessoes(db_session) -> None:
    u = svc.create_user(db_session, username="mario", password="senha-super-8", role="operador")
    settings = Settings(session_ttl_seconds=3600, _env_file=None)
    token = svc.iniciar_sessao(db_session, u, settings=settings)
    assert svc.validar_sessao(db_session, token) is not None

    svc.reset_password(db_session, u.id, password="outra-super-8", actor="cli")
    old = svc.validar_sessao(db_session, token)
    assert old is None and svc.verify_password("outra-super-8", u.password_hash)


def test_autenticar_inativos_e_senha_errada(db_session) -> None:
    u = svc.create_user(db_session, username="ze", password="senha-super-8", role="operador")
    assert svc.autenticar(db_session, "ze", "senha-super-8") is not None
    assert svc.autenticar(db_session, "ze", "errada-8") is None
    svc.update_user(db_session, u.id, is_active=False, actor="cli")
    assert svc.autenticar(db_session, "ze", "senha-super-8") is None


def test_sessoes_validar_encerrar_e_expirada(db_session) -> None:
    u = svc.create_user(db_session, username="ana2", password="senha-super-8", role="operador")
    settings = Settings(session_ttl_seconds=3600, _env_file=None)
    token = svc.iniciar_sessao(db_session, u, settings=settings)

    assert svc.validar_sessao(db_session, token) == u
    assert svc.validar_sessao(db_session, "token-inventado") is None

    usuario = svc.encerrar_sessao(db_session, token)
    assert usuario is not None and usuario.username == "ana2"
    assert svc.validar_sessao(db_session, token) is None

    t2 = svc.iniciar_sessao(db_session, u, settings=settings)
    sess = db_session.scalar(select(models.UserSession))
    sess.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    assert svc.validar_sessao(db_session, t2) is None  # expirada → None (e apagada lazy)
    assert db_session.scalar(select(models.UserSession)) is None


def test_disable_user_invalida_sessoes_e_audita(db_session: Session) -> None:
    from gerenet.config import Settings

    usuario = svc.create_user(
        db_session, username="boss", password="senha-super-8", role="administrador", actor="cli"
    )
    svc.iniciar_sessao(db_session, usuario, settings=Settings(_env_file=None))
    db_session.commit()

    desativado = svc.disable_user(db_session, usuario.id, actor="admin")
    assert desativado is usuario
    assert usuario.is_active is False
    # Sessões apagadas (mesmo padrão do reset de senha).
    linhas = db_session.scalar(select(models.UserSession).where(models.UserSession.user_id == usuario.id))
    assert linhas is None
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "user.disable")
    )
    assert evento is not None and evento.actor == "admin"


def test_disable_user_idempotente_nao_audita_de_novo(db_session: Session) -> None:
    usuario = svc.create_user(
        db_session, username="op2", password="senha-super-8", role="operador", actor="cli"
    )
    db_session.commit()
    svc.disable_user(db_session, usuario.id, actor="cli")
    db_session.commit()
    svc.disable_user(db_session, usuario.id, actor="cli")  # repetição: sem transição (Ruling 5)
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "user.disable")
    ).all()
    assert len(eventos) == 1
