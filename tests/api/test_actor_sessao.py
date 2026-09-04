"""Sessão web (cookie) nos routers: require_actor aceita cookie OU X-Api-Key.

Escrita via usuário grava o username na trilha (ator real); via chave, "api".
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.services import users as svc


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _cria_e_loga(client: TestClient, db_session, username="operador1", role="operador") -> None:
    # create_user só faz flush; a fixture commita para a sessão do request
    # (conexão própria) enxergar o usuário no login (mesmo motivo de test_auth_api).
    svc.create_user(db_session, username=username, password="senha-super-8", role=role, actor="cli")
    db_session.commit()
    client.post("/api/v1/auth/login", json={"username": username, "password": "senha-super-8"})


def test_get_por_cookie_sem_chave(client: TestClient, db_session) -> None:
    _cria_e_loga(client, db_session)
    resp = client.get("/api/v1/devices")  # sem X-API-Key
    assert resp.status_code == 200


def test_escrita_por_cookie_audita_usuario(client: TestClient, db_session) -> None:
    _cria_e_loga(client, db_session, username="dona")
    resp = client.post("/api/v1/sites", json={"name": "POP-WEB", "city": "Recife", "uf": "PE"})
    assert resp.status_code == 201
    trilha = client.get("/api/v1/audit-events?tipo=site.create").json()
    assert trilha[0]["actor"] == "dona"


def test_visualizador_nao_escreve(client: TestClient, db_session) -> None:
    _cria_e_loga(client, db_session, username="v1", role="visualizador")
    assert client.get("/api/v1/devices").status_code == 200
    resp = client.post("/api/v1/sites", json={"name": "POP-N", "city": "Niterói", "uf": "RJ"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Perfil Visualizador permite apenas leitura."}


def test_chave_de_api_continua_escrevendo_como_api(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/sites",
        json={"name": "POP-KEY", "city": "Brasília", "uf": "DF"},
        headers={"X-API-Key": "teste-key"},
    )
    assert resp.status_code == 201
    trilha = client.get(
        "/api/v1/audit-events?tipo=site.create", headers={"X-API-Key": "teste-key"}
    ).json()
    assert trilha[0]["actor"] == "api"


def test_sessao_expirada_e_apagada_lazy(client: TestClient, db_session) -> None:
    _cria_e_loga(client, db_session, username="contora")
    token = client.cookies.get("gerenet_sess")
    assert token is not None

    u = db_session.scalar(select(models.User).where(models.User.username == "contora"))
    sessao = db_session.scalar(select(models.UserSession).where(models.UserSession.user_id == u.id))
    sessao.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    resp = client.get("/api/v1/devices")  # sem X-Api-Key — só o cookie expirado
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Chave de API ausente ou inválida."}
    assert db_session.scalar(select(models.UserSession)) is None  # apagada na leitura (lazy)
