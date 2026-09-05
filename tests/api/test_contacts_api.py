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


def _org(client: TestClient, nome: str = "Org Contatos") -> int:
    resp = client.post("/api/v1/organizations", json={"name": nome}, headers=_auth())
    assert resp.status_code == 201
    return resp.json()["id"]


def test_crud_contatos(client: TestClient) -> None:
    org_id = _org(client)
    criado = client.post(
        "/api/v1/contacts",
        json={"organization_id": org_id, "name": "Ana NOC", "email": "ana@example.com", "kind": "noc"},
        headers=_auth(),
    )
    assert criado.status_code == 201, criado.text
    contato_id = criado.json()["id"]

    lista = client.get("/api/v1/contacts", headers=_auth()).json()
    assert [c["name"] for c in lista] == ["Ana NOC"]
    filtrada = client.get(f"/api/v1/contacts?organization_id={org_id}", headers=_auth()).json()
    assert [c["name"] for c in filtrada] == ["Ana NOC"]

    corpo = client.get(f"/api/v1/contacts/{contato_id}", headers=_auth()).json()
    assert corpo["email"] == "ana@example.com"

    inexistente = client.get("/api/v1/contacts/9999", headers=_auth())
    assert inexistente.status_code == 404


def test_contato_email_invalido_da_400_e_org_inexistente_404(client: TestClient) -> None:
    _org(client)  # serviço valida a organização antes do e-mail (ordem do P1)
    ruim = client.post(
        "/api/v1/contacts",
        json={"organization_id": 1, "name": "Ana", "email": "nao-eh-email"},
        headers=_auth(),
    )
    assert ruim.status_code == 400
    assert "E-mail" in ruim.json()["detail"]

    sem_org = client.post(
        "/api/v1/contacts", json={"organization_id": 9999, "name": "Ana"}, headers=_auth()
    )
    assert sem_org.status_code == 404


def test_patch_contato_desativa_e_audita(db_session: Session, client: TestClient) -> None:
    org_id = _org(client)
    criado = client.post(
        "/api/v1/contacts", json={"organization_id": org_id, "name": "Bruno"}, headers=_auth()
    )
    contato_id = criado.json()["id"]

    off = client.patch(f"/api/v1/contacts/{contato_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    renomeado = client.patch(
        f"/api/v1/contacts/{contato_id}", json={"phone": "11-99999"}, headers=_auth()
    )
    assert renomeado.status_code == 200

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["organization.create", "contact.create", "contact.disable", "contact.update"]


def test_lista_nao_inclui_desativados_sem_flag(client: TestClient) -> None:
    org_id = _org(client)
    criado = client.post(
        "/api/v1/contacts",
        json={"organization_id": org_id, "name": "Zé NOC", "kind": "noc"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    cid = criado.json()["id"]
    assert client.patch(f"/api/v1/contacts/{cid}", json={"admin_status": False}, headers=_auth()).status_code == 200

    sem_flag = client.get("/api/v1/contacts", headers=_auth()).json()
    assert [c["name"] for c in sem_flag] == []
    com_flag = client.get("/api/v1/contacts?include_disabled=true", headers=_auth()).json()
    assert [c["name"] for c in com_flag] == ["Zé NOC"]
