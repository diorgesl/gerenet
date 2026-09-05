import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models


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


def test_post_e_patch_desativar_auditam(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r2-aud", "management_address": "10.0.0.5"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]
    desativado = client.patch(
        f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()
    )
    assert desativado.status_code == 200

    tipos = [
        e.type
        for e in db_session.scalars(
            select(models.AuditEvent).order_by(models.AuditEvent.id)
        )
    ]
    assert tipos == ["device.create", "device.disable"]
    assert all(e.actor == "api" for e in db_session.scalars(select(models.AuditEvent)))


def test_desativar_duas_vezes_nao_audita_de_novo(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r2-aud-2x", "management_address": "10.0.0.6"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]
    primeiro = client.patch(
        f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()
    )
    assert primeiro.status_code == 200
    repetido = client.patch(
        f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()
    )
    assert repetido.status_code == 200

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.disable"]


def test_patch_update_audita_tipo_update(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r2-upd", "management_address": "10.0.0.7"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]
    resp = client.patch(
        f"/api/v1/devices/{dev_id}", json={"name": "r2-renomeado"}, headers=_auth()
    )
    assert resp.status_code == 200

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.update"]


def test_post_asn_reservado_da_400(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/devices",
        json={"name": "r3-asn", "management_address": "10.0.0.9", "asn": 23456},
        headers=_auth(),
    )
    assert resp.status_code == 400
    assert "reservado" in resp.json()["detail"]


def test_patch_asn_reservado_da_400(client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r4-asn", "management_address": "10.0.0.10"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    resp = client.patch(
        f"/api/v1/devices/{criado.json()['id']}", json={"asn": 23456}, headers=_auth()
    )
    assert resp.status_code == 400
    assert "reservado" in resp.json()["detail"]


def test_patch_reativar_usa_enable_device(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r5-en", "management_address": "10.0.0.11"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]

    assert client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()).status_code == 200
    resp = client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": True}, headers=_auth())
    assert resp.status_code == 200 and resp.json()["admin_status"] is True

    # repetição (já ativo) → 200 sem novo evento (Ruling 5)
    repetido = client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": True}, headers=_auth())
    assert repetido.status_code == 200 and repetido.json()["admin_status"] is True

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.disable", "device.enable"]


def test_patch_reativar_misto_continua_update(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r6-mix", "management_address": "10.0.0.12"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]
    assert client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()).status_code == 200
    # admin_status true + outro campo → caminho genérico (device.update)
    resp = client.patch(
        f"/api/v1/devices/{dev_id}", json={"admin_status": True, "role": "edge"}, headers=_auth()
    )
    assert resp.status_code == 200 and resp.json()["role"] == "edge"
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.disable", "device.update"]
