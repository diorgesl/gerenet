import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_lista_catalogo_so_leitura(client: TestClient) -> None:
    lista = client.get("/api/v1/policy-profiles", headers=_auth()).json()
    assert len(lista) == 6  # seeds de exportação do §25.5
    assert all(p["direction"] == "export" for p in lista)
    assert [p["name"] for p in lista] == sorted(p["name"] for p in lista)
    assert any(p["label"] for p in lista)  # label PT-BR presente

    assert client.get(
        "/api/v1/policy-profiles?direction=export", headers=_auth()
    ).json() == lista
    assert client.get("/api/v1/policy-profiles?direction=import", headers=_auth()).json() == []
    assert client.post("/api/v1/policy-profiles", json={}, headers=_auth()).status_code == 405


def test_direction_invalida_da_400(client: TestClient) -> None:
    resp = client.get("/api/v1/policy-profiles?direction=foo", headers=_auth())
    assert resp.status_code == 400
    assert "Direção inválida" in resp.json()["detail"]
