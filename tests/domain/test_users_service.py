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
