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


def test_criar_listar_detalhar(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/organizations",
        json={"name": "Cliente Org API", "asn": 64512, "kind": "downstream"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]
    assert resp.json()["kind"] == "downstream"

    lista = client.get("/api/v1/organizations", headers=_auth()).json()
    assert [o["name"] for o in lista] == ["Cliente Org API"]

    corpo = client.get(f"/api/v1/organizations/{org_id}", headers=_auth()).json()
    assert corpo["asn"] == 64512

    dup = client.post(
        "/api/v1/organizations", json={"name": "Cliente Org API"}, headers=_auth()
    )
    assert dup.status_code == 409

    assert client.get("/api/v1/organizations/9999", headers=_auth()).status_code == 404


def test_rota_requer_chave(client: TestClient) -> None:
    assert client.get("/api/v1/organizations").status_code == 401


def test_asn_reservado_da_400_e_duplicado_da_409(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/organizations", json={"name": "Org Res", "asn": 23456}, headers=_auth()
    )
    assert resp.status_code == 400
    assert "reservado" in resp.json()["detail"]

    client.post("/api/v1/organizations", json={"name": "Org A", "asn": 64520}, headers=_auth())
    dup = client.post(
        "/api/v1/organizations", json={"name": "Org B", "asn": 64520}, headers=_auth()
    )
    assert dup.status_code == 409
    assert "ASN" in dup.json()["detail"]


def test_patch_desativa_e_audita(db_session: Session, client: TestClient) -> None:
    criada = client.post(
        "/api/v1/organizations", json={"name": "Org Patch", "asn": 64521}, headers=_auth()
    )
    assert criada.status_code == 201
    org_id = criada.json()["id"]

    off = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    repetido = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": False}, headers=_auth())
    assert repetido.status_code == 200

    renomeada = client.patch(
        f"/api/v1/organizations/{org_id}", json={"name": "Org Patch 2"}, headers=_auth()
    )
    assert renomeada.status_code == 200

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["organization.create", "organization.disable", "organization.update"]


def test_patch_admin_status_null_da_400(client: TestClient) -> None:
    criada = client.post(
        "/api/v1/organizations", json={"name": "Org Null"}, headers=_auth()
    )
    org_id = criada.json()["id"]
    resp = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": None}, headers=_auth())
    assert resp.status_code == 400


def test_downstreams_forca_kind(client: TestClient) -> None:
    criada = client.post(
        "/api/v1/downstreams",
        json={"name": "Down API", "kind": "parceiro", "asn": 64530},
        headers=_auth(),
    )
    assert criada.status_code == 201, criada.text
    assert criada.json()["kind"] == "downstream"  # ignorado o parceiro enviado

    lista = client.get("/api/v1/downstreams", headers=_auth()).json()
    assert [o["name"] for o in lista] == ["Down API"]

    # organizações comuns não aparecem no downstreams
    client.post("/api/v1/organizations", json={"name": "Parceiro X", "kind": "parceiro"}, headers=_auth())
    assert [o["name"] for o in client.get("/api/v1/downstreams", headers=_auth()).json()] == ["Down API"]
