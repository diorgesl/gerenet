import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from gerenet.api.main import create_app
from gerenet.automation.hostkeys import HostKeyScanError
from gerenet.config import Settings, set_settings
from gerenet.domain import models


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _cria_device(client: TestClient, nome: str = "r1-hk") -> int:
    resp = client.post(
        "/api/v1/devices", json={"name": nome, "management_address": "10.0.0.9"}, headers=_auth()
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_scan_retorna_fingerprint(client: TestClient, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    dev_id = _cria_device(client)
    monkeypatch.setattr(
        "gerenet.api.routers.devices.fingerprint_ssh",
        lambda host, port, timeout: "sha256:AbCdEf",
    )
    resp = client.post(f"/api/v1/devices/{dev_id}/hostkey/scan", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"fingerprint": "sha256:AbCdEf"}


def test_scan_device_inexistente_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gerenet.api.routers.devices.fingerprint_ssh", lambda *a: "sha256:x")
    resp = client.post("/api/v1/devices/9999/hostkey/scan", headers=_auth())
    assert resp.status_code == 404


def test_scan_inalcancavel_502(client: TestClient, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    dev_id = _cria_device(client, "r1-scan-fail")

    def falha(host, port, timeout):
        raise HostKeyScanError("timeout")

    monkeypatch.setattr("gerenet.api.routers.devices.fingerprint_ssh", falha)
    resp = client.post(f"/api/v1/devices/{dev_id}/hostkey/scan", headers=_auth())
    assert resp.status_code == 502


def test_register_grava_normaliza_e_audita(client: TestClient, db_session) -> None:
    dev_id = _cria_device(client, "r1-reg")
    resp = client.post(
        f"/api/v1/devices/{dev_id}/hostkey", json={"fingerprint": " SHA256:AbCdEf==" }, headers=_auth()
    )
    assert resp.status_code == 200
    assert resp.json()["host_key_fingerprint"] == "sha256:AbCdEf"
    dev = db_session.get(models.Device, dev_id)
    assert dev.host_key_fingerprint == "sha256:AbCdEf"
    evento = db_session.execute(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).scalars().first()
    assert evento.type == "hostkey.register"
    assert evento.actor == "api"
    assert evento.details["objeto_id"] == dev_id
    assert evento.details["depois"]["fingerprint"] == "sha256:AbCdEf"


def test_register_esquema_invalido_400(client: TestClient, db_session) -> None:
    dev_id = _cria_device(client, "r1-bad")
    resp = client.post(
        f"/api/v1/devices/{dev_id}/hostkey", json={"fingerprint": "md5:abcdef"}, headers=_auth()
    )
    assert resp.status_code == 400


def test_register_fingerprint_vazio_422(client: TestClient, db_session) -> None:
    dev_id = _cria_device(client, "r1-vazio")
    resp = client.post(f"/api/v1/devices/{dev_id}/hostkey", json={"fingerprint": ""}, headers=_auth())
    assert resp.status_code == 422


def test_register_device_inexistente_404(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/devices/9999/hostkey", json={"fingerprint": "sha256:abc"}, headers=_auth()
    )
    assert resp.status_code == 404
