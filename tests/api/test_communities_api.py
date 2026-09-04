"""Communities (catálogo read-only) e associações sessão ↔ community (spec §8)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _sessao(db_session: Session) -> int:
    site = create_site(db_session, SiteCreate(name="pop-com-api"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Com API", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-com-api", management_address="10.40.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-com-api", management_address="10.40.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-COM-API", organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id,
        ),
        actor="cli",
    ).id
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ_id, device_id=ne.id, afi="ipv4",
            local_address="100.64.40.1", remote_address="100.64.40.2",
        ),
        actor="cli",
    ).id


def test_lista_communities_read_only(client: TestClient, db_session: Session) -> None:
    lista = client.get("/api/v1/communities", headers=_auth())
    assert lista.status_code == 200
    assert [c["name"] for c in lista.json()] == ["blackhole", "no-advertise", "no-export"]
    assert client.post("/api/v1/communities", json={}, headers=_auth()).status_code == 405
    # caminho exato do catálogo: 405; subcaminho sem rota (ex.: /communities/1) → 404
    assert client.delete("/api/v1/communities", headers=_auth()).status_code == 405


def test_associa_e_desassocia_community(client: TestClient, db_session: Session) -> None:
    sessao_id = _sessao(db_session)
    comunidade = client.get("/api/v1/communities", headers=_auth()).json()[0]  # blackhole

    post = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities",
        json={"community_id": comunidade["id"]}, headers=_auth(),
    )
    assert post.status_code == 200, post.text
    assert post.json() == {"session_id": sessao_id, "community_id": comunidade["id"]}

    repete = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities",
        json={"community_id": comunidade["id"]}, headers=_auth(),
    )
    assert repete.status_code == 200  # idempotente

    remove = client.delete(
        f"/api/v1/bgp-sessions/{sessao_id}/communities/{comunidade['id']}", headers=_auth()
    )
    assert remove.status_code == 204
    remove2 = client.delete(
        f"/api/v1/bgp-sessions/{sessao_id}/communities/{comunidade['id']}", headers=_auth()
    )
    assert remove2.status_code == 204  # no-op idempotente


def test_associacao_inexistente_da_404(client: TestClient, db_session: Session) -> None:
    sessao_id = _sessao(db_session)
    assert client.post(
        "/api/v1/bgp-sessions/9999/communities", json={"community_id": 1}, headers=_auth()
    ).status_code == 404
    assert client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities", json={"community_id": 9999},
        headers=_auth(),
    ).status_code == 404
    assert client.delete(
        f"/api/v1/bgp-sessions/{sessao_id}/communities/9999", headers=_auth()
    ).status_code == 404
