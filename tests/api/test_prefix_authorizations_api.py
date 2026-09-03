import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import OrganizationCreate
from gerenet.domain.services.organizations import create_organization


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _orgs(db_session: Session) -> tuple[int, int]:
    a = create_organization(db_session, OrganizationCreate(name="Down A", asn=64521), actor="cli")
    b = create_organization(db_session, OrganizationCreate(name="Down B", asn=64522), actor="cli")
    return a.id, b.id


def test_exige_chave(client: TestClient) -> None:
    assert client.get("/api/v1/prefix-authorizations").status_code == 401
    assert client.post("/api/v1/prefix-authorizations", json={}).status_code == 401
    assert client.get("/api/v1/policy-profiles").status_code == 401


def test_cria_lista_detalha(client: TestClient, db_session: Session) -> None:
    org_a, org_b = _orgs(db_session)
    resp = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "203.0.113.0/24"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    corpo = resp.json()
    assert corpo["origin"] == "manual"
    assert corpo["admin_status"] is True

    # bloco contíguo na MESMA organização: permitido (spec §4)
    vizinho = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "203.0.113.128/25"},
        headers=_auth(),
    )
    assert vizinho.status_code == 201

    # sobreposição com OUTRA organização ativa: 409
    outro = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_b, "family": "ipv4", "prefix": "203.0.113.0/25"},
        headers=_auth(),
    )
    assert outro.status_code == 409
    assert "sobrepõe" in outro.json()["detail"]

    # CIDR da família errada: 400 (mensagens PT do serviço)
    errado = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "2001:db8::/32"},
        headers=_auth(),
    )
    assert errado.status_code == 400

    lista = client.get("/api/v1/prefix-authorizations", headers=_auth()).json()
    assert len(lista) == 2
    assert lista[0]["prefix"] == "203.0.113.0/24"  # order by family, prefix

    assert client.get("/api/v1/prefix-authorizations?family=ipv6", headers=_auth()).json() == []
    det = client.get(f"/api/v1/prefix-authorizations/{corpo['id']}", headers=_auth())
    assert det.status_code == 200 and det.json()["prefix"] == "203.0.113.0/24"
    assert client.get("/api/v1/prefix-authorizations/9999", headers=_auth()).status_code == 404


def test_patch_so_desativa(client: TestClient, db_session: Session) -> None:
    org_a, _ = _orgs(db_session)
    auth = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "198.51.100.0/24"},
        headers=_auth(),
    ).json()

    off = client.patch(
        f"/api/v1/prefix-authorizations/{auth['id']}",
        json={"admin_status": False},
        headers=_auth(),
    )
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    ativos = client.get("/api/v1/prefix-authorizations", headers=_auth()).json()
    assert ativos == []
    com_desativadas = client.get(
        "/api/v1/prefix-authorizations?include_disabled=true", headers=_auth()
    ).json()
    assert [p["prefix"] for p in com_desativadas] == ["198.51.100.0/24"]

    # reativar ou mudar conteúdo não existe: 422 (schema Literal[False] + extra forbid)
    reativar = client.patch(
        f"/api/v1/prefix-authorizations/{auth['id']}",
        json={"admin_status": True},
        headers=_auth(),
    )
    assert reativar.status_code == 422
    mudar = client.patch(
        f"/api/v1/prefix-authorizations/{auth['id']}",
        json={"prefix": "198.51.100.0/25"},
        headers=_auth(),
    )
    assert mudar.status_code == 422

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent))
        if e.type.startswith("authorization")
    ]
    assert tipos == ["authorization.create", "authorization.disable"]
