import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.schemas import (
    ContactCreate,
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.contacts import create_contact
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _popula_trilha(db_session: Session) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-audit"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Down Audit", asn=64531), actor="cli"
    )
    dev = create_device(
        db_session, DeviceCreate(name="ne-audit", management_address="10.8.3.1"), actor="cli"
    )
    create_contact(
        db_session,
        ContactCreate(organization_id=org.id, name="Ana", kind="noc"),
        actor="cli",
    )
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org.id, family="ipv4", prefix="203.0.113.0/24"
        ),
        actor="cli",
    )
    # device.disable registra "antes" do admin_status para o teste de limit/ordem
    from gerenet.domain.services.devices import disable_device

    disable_device(db_session, dev.id, actor="cli")
    return {"site_id": site.id, "org_id": org.id, "device_id": dev.id, "auth_id": auth.id}


def test_exige_chave_e_somente_get(client: TestClient) -> None:
    assert client.get("/api/v1/audit-events").status_code == 401
    rotas = create_app().openapi()["paths"]["/api/v1/audit-events"]
    assert set(rotas) == {"get"}  # trilha imutável: sem post/patch/delete
    for verbo in ("post", "patch", "delete"):
        assert client.request(verbo, "/api/v1/audit-events", headers=_auth()).status_code == 405


def test_lista_ordem_desc_e_filtros(client: TestClient, db_session: Session) -> None:
    refs = _popula_trilha(db_session)
    lista = client.get("/api/v1/audit-events", headers=_auth()).json()
    assert len(lista) == 6
    ids = [e["id"] for e in lista]
    assert ids == sorted(ids, reverse=True)
    tipos = [e["type"] for e in lista]
    assert tipos == [
        "device.disable", "authorization.create", "contact.create", "device.create",
        "organization.create", "site.create",
    ]
    primeiro = lista[0]
    assert set(primeiro) == {"id", "type", "actor", "details", "created_at"}
    assert primeiro["actor"] == "cli"
    assert primeiro["details"]["objeto"] == "device"
    assert primeiro["details"]["depois"]["admin_status"] is False
    assert primeiro["details"]["antes"]["admin_status"] is True

    so_site = client.get("/api/v1/audit-events?tipo=site.create", headers=_auth()).json()
    assert [e["type"] for e in so_site] == ["site.create"]
    assert so_site[0]["details"]["objeto_id"] == refs["site_id"]

    so_device = client.get("/api/v1/audit-events?objeto=device", headers=_auth()).json()
    assert [e["type"] for e in so_device] == ["device.disable", "device.create"]

    so_auth = client.get(
        f"/api/v1/audit-events?objeto=authorization&objeto_id={refs['auth_id']}",
        headers=_auth(),
    ).json()
    assert [e["type"] for e in so_auth] == ["authorization.create"]

    # negativo: objeto_id sem correspondência devolve vazio. Não usar refs["org_id"]:
    # no fixture todos os ids valem 1 (sequências próprias + RESTART IDENTITY) e
    # organization.create carrega objeto_id=org.id — 9999 não existe em evento algum.
    assert client.get("/api/v1/audit-events?objeto_id=9999", headers=_auth()).json() == []


def test_limit_clamp(client: TestClient, db_session: Session) -> None:
    _popula_trilha(db_session)
    dois = client.get("/api/v1/audit-events?limit=2", headers=_auth()).json()
    assert len(dois) == 2
    for fora in ("0", "1001"):
        assert client.get(f"/api/v1/audit-events?limit={fora}", headers=_auth()).status_code == 422
