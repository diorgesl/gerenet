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


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_api_requer_chave(client: TestClient) -> None:
    resp = client.get("/api/v1/devices")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Chave de API ausente ou inválida."}


def test_crud_devices(client: TestClient) -> None:
    resp = client.post("/api/v1/devices", json={"name": "r2", "management_address": "10.0.0.3"}, headers=_auth())
    assert resp.status_code == 201
    dev_id = resp.json()["id"]

    lista = client.get("/api/v1/devices", headers=_auth())
    assert [d["name"] for d in lista.json()] == ["r2"]

    dup = client.post("/api/v1/devices", json={"name": "r2", "management_address": "10.0.0.4"}, headers=_auth())
    assert dup.status_code == 409
    assert "Já existe" in dup.json()["detail"]

    inexistente = client.get("/api/v1/devices/9999", headers=_auth())
    assert inexistente.status_code == 404

    off = client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False
