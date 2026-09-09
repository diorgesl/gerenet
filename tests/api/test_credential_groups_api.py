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


def _grupo(client: TestClient, nome: str = "automacao") -> dict:
    resp = client.post(
        "/api/v1/credential-groups",
        json={"name": nome, "vault_path": f"gerenet/credential-groups/{nome}"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_crud_grupos(client: TestClient) -> None:
    grupo = _grupo(client, "automacao")
    assert grupo["name"] == "automacao"
    assert grupo["kind"] == "tacacs_password"
    assert grupo["admin_status"] is True

    lista = client.get("/api/v1/credential-groups", headers=_auth()).json()
    assert [g["name"] for g in lista] == ["automacao"]

    corpo = client.get(f"/api/v1/credential-groups/{grupo['id']}", headers=_auth()).json()
    assert corpo["vault_path"] == "gerenet/credential-groups/automacao"

    inexistente = client.get("/api/v1/credential-groups/9999", headers=_auth())
    assert inexistente.status_code == 404


def test_grupo_duplicado_da_409_e_sem_nome_422(client: TestClient) -> None:
    _grupo(client, "automacao")
    duplicado = client.post(
        "/api/v1/credential-groups",
        json={"name": "automacao", "vault_path": "outro/caminho"},
        headers=_auth(),
    )
    assert duplicado.status_code == 409

    sem_nome = client.post(
        "/api/v1/credential-groups", json={"name": "", "vault_path": "x"}, headers=_auth()
    )
    assert sem_nome.status_code == 422


def test_patch_grupo_edita_desativa_reativa_e_audita(db_session: Session, client: TestClient) -> None:
    grupo = _grupo(client, "automacao")

    editado = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}",
        json={"vault_path": "gerenet/credential-groups/auto2"},
        headers=_auth(),
    )
    assert editado.status_code == 200
    assert editado.json()["vault_path"] == "gerenet/credential-groups/auto2"

    off = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}", json={"admin_status": False}, headers=_auth()
    )
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    sem_flag = client.get("/api/v1/credential-groups", headers=_auth()).json()
    assert [g["name"] for g in sem_flag] == []
    com_flag = client.get(
        "/api/v1/credential-groups?include_disabled=true", headers=_auth()
    ).json()
    assert [g["name"] for g in com_flag] == ["automacao"]

    on = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}", json={"admin_status": True}, headers=_auth()
    )
    assert on.status_code == 200

    null = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}", json={"admin_status": None}, headers=_auth()
    )
    assert null.status_code == 400

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == [
        "credential_group.create",
        "credential_group.update",
        "credential_group.disable",
        "credential_group.enable",
    ]
