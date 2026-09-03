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


def _cria_site(client: TestClient, nome: str, **extra: object) -> int:
    corpo: dict[str, object] = {"name": nome, "city": "São Paulo", "uf": "SP", **extra}
    resp = client.post("/api/v1/sites", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_rota_requer_chave(client: TestClient) -> None:
    assert client.get("/api/v1/sites").status_code == 401


def test_criar_listar_detalhar(client: TestClient) -> None:
    sid = _cria_site(client, "POP-API-1")
    corpo = client.get(f"/api/v1/sites/{sid}", headers=_auth()).json()
    assert corpo["name"] == "POP-API-1"
    assert corpo["uf"] == "SP"
    assert corpo["admin_status"] is True

    lista = client.get("/api/v1/sites", headers=_auth()).json()
    assert [s["name"] for s in lista] == ["POP-API-1"]

    dup = client.post("/api/v1/sites", json={"name": "POP-API-1"}, headers=_auth())
    assert dup.status_code == 409
    assert "Já existe" in dup.json()["detail"]

    assert client.get("/api/v1/sites/9999", headers=_auth()).status_code == 404


def test_bloco_p2p_invalido_da_400(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/sites",
        json={"name": "POP-BAD", "p2p_ipv4_block": "999.1.1.0/24"},
        headers=_auth(),
    )
    assert resp.status_code == 400


def test_patch_desativa_reativa_e_null(client: TestClient) -> None:
    sid = _cria_site(client, "POP-PATCH")
    off = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    again = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": False}, headers=_auth())
    assert again.status_code == 200

    on = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": True}, headers=_auth())
    assert on.status_code == 200
    assert on.json()["admin_status"] is True

    nul = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": None}, headers=_auth())
    assert nul.status_code == 400
    assert "null" in nul.json()["detail"]


def test_patch_audita_eventos(db_session: Session, client: TestClient) -> None:
    sid = _cria_site(client, "POP-AUDIT")
    client.patch(f"/api/v1/sites/{sid}", json={"admin_status": False}, headers=_auth())
    client.patch(f"/api/v1/sites/{sid}", json={"city": "Campinas"}, headers=_auth())

    eventos = list(db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id)))
    assert [e.type for e in eventos] == ["site.create", "site.disable", "site.update"]
    assert all(e.actor == "api" for e in eventos)
