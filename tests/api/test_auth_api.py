import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.services import users as svc


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", session_ttl_seconds=3600, _env_file=None))
    return TestClient(create_app())


def _cria_usuario(db_session, username="op1", role="operador") -> models.User:
    usuario = svc.create_user(
        db_session, username=username, password="senha-super-8", role=role, actor="cli"
    )
    db_session.commit()
    return usuario


def test_login_ok_seta_cookie_e_audita(client: TestClient, db_session) -> None:
    _cria_usuario(db_session)
    resp = client.post("/api/v1/auth/login", json={"username": "op1", "password": "senha-super-8"})
    assert resp.status_code == 200
    corpo = resp.json()
    assert set(corpo) == {"id", "username", "role", "is_active", "last_login_at", "created_at"}
    assert corpo["role"] == "operador"
    cookie = resp.headers.get("set-cookie", "")
    assert "gerenet_sess=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie

    trilha = db_session.scalar(select(models.AuditEvent).where(models.AuditEvent.type == "auth.login"))
    assert trilha is not None and trilha.actor == "op1"


def test_login_falha_mensagem_unica_e_audita(client: TestClient, db_session) -> None:
    _cria_usuario(db_session)
    for payload in ({"username": "op1", "password": "errada-8"}, {"username": "fantasma", "password": "senha-super-8"}):
        resp = client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Usuário ou senha inválidos."}

    falhas = db_session.query(models.AuditEvent).filter(models.AuditEvent.type == "auth.login_failed").all()
    assert len(falhas) == 2
    assert {e.actor for e in falhas} == {"op1", "fantasma"}


def test_me_com_sessao_e_sem(client: TestClient, db_session) -> None:
    _cria_usuario(db_session)
    client.post("/api/v1/auth/login", json={"username": "op1", "password": "senha-super-8"})
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200 and resp.json()["username"] == "op1"

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    # /me é web-only: X-Api-Key não vale aqui (mensagem "Não autenticado.")
    resp_key = client.get("/api/v1/auth/me", headers={"X-API-Key": "teste-key"})
    assert resp_key.status_code == 401 and resp_key.json() == {"detail": "Não autenticado."}
