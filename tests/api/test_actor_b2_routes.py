"""Rotas do B2 (reconciliation, communities) autenticáveis por cookie de sessão."""
import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.services.users import create_user


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _cookie_de_usuario(client, db_session) -> dict:
    """Cria usuário, loga via API e devolve headers com o cookie gerenet_sess."""
    create_user(
        db_session,
        username="admin-spa",
        password="senha-super-8",
        role="administrador",
        actor="cli",
    )
    # create_user só faz flush; o login usa a sessão do request (padrão de
    # test_actor_sessao), que não enxerga transação não commitada da fixture.
    db_session.commit()
    r = client.post("/api/v1/auth/login", json={"username": "admin-spa", "password": "senha-super-8"})
    assert r.status_code == 200, r.text
    return {"Cookie": r.headers.get("set-cookie", "").split(";", 1)[0]}


def test_reconciliation_aceita_cookie(client, db_session):
    headers = _cookie_de_usuario(client, db_session)
    # 404 (rua alcançada com o cookie; device inexistente) prova o cookie autenticou
    r1 = client.get("/api/v1/reconciliation", params={"device_id": 999019}, headers=headers)
    assert r1.status_code == 404
    # sem autenticação continua 401 (mensagem preservada); o jar do TestClient
    # guarda o cookie do login — limpo para a chamada anônima
    client.cookies.clear()
    r2 = client.get("/api/v1/reconciliation", params={"device_id": 999019})
    assert r2.status_code == 401


def test_communities_aceita_cookie(client, db_session):
    headers = _cookie_de_usuario(client, db_session)
    r = client.get("/api/v1/communities", headers=headers)
    assert r.status_code == 200


def test_communities_seguem_com_api_key(client):
    # caminho da chave preservado — smoke com a chave dos fixtures de teste
    r = client.get("/api/v1/communities", headers={"X-Api-Key": "teste-key"})
    assert r.status_code == 200
