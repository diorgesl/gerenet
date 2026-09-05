"""Communities (catálogo read-only) e associações sessão ↔ community (spec §8)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
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


def test_lista_communities_da_sessao(client: TestClient, db_session: Session) -> None:
    sessao_id = _sessao(db_session)
    comunidade = client.get("/api/v1/communities", headers=_auth()).json()[0]  # blackhole
    associada = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities",
        json={"community_id": comunidade["id"]}, headers=_auth(),
    )
    assert associada.status_code == 200

    lista = client.get(f"/api/v1/bgp-sessions/{sessao_id}/communities", headers=_auth())
    assert lista.status_code == 200, lista.text
    assert [c["name"] for c in lista.json()] == ["blackhole"]

    assert client.get("/api/v1/bgp-sessions/9999/communities", headers=_auth()).status_code == 404


def _cria_community(db_session: Session, name: str, notes: str | None = None) -> models.Community:
    com = models.Community(name=name, notes=notes)
    db_session.add(com)
    db_session.commit()
    return com


def test_patch_community_disable_e_update_segundo_ruling_1(
    client: TestClient, db_session: Session
) -> None:
    com = _cria_community(db_session, "api-c3-com")
    try:
        # PATCH puro de desativação → community.disable
        off = client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": False}, headers=_auth())
        assert off.status_code == 200 and off.json()["admin_status"] is False

        # repetição → 200 sem novo evento
        off2 = client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": False}, headers=_auth())
        assert off2.status_code == 200
        tipos = [
            e.type
            for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        ]
        assert tipos.count("community.disable") == 1

        # sem flag: fora da lista; com flag: dentro
        assert com.id not in [c["id"] for c in client.get("/api/v1/communities", headers=_auth()).json()]
        assert com.id in [
            c["id"]
            for c in client.get("/api/v1/communities?include_disabled=true", headers=_auth()).json()
        ]

        # reativação pura → *.update (sem enable_* dedicado, decisão §3.6)
        on = client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": True}, headers=_auth())
        assert on.status_code == 200 and on.json()["admin_status"] is True
        tipos = [
            e.type
            for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        ]
        assert tipos.count("community.update") == 1

        # nome → community.update com antes/depois
        renomear = client.patch(f"/api/v1/communities/{com.id}", json={"name": "api-c3-renomeada"}, headers=_auth())
        assert renomear.status_code == 200 and renomear.json()["name"] == "api-c3-renomeada"
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def test_patch_community_erros(client: TestClient, db_session: Session) -> None:
    com = _cria_community(db_session, "api-c3-err")
    try:
        # admin_status null → 400
        assert client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": None}, headers=_auth()).status_code == 400
        # nome vazio → 400
        assert client.patch(f"/api/v1/communities/{com.id}", json={"name": "  "}, headers=_auth()).status_code == 400
        # 404
        assert client.patch("/api/v1/communities/99999", json={"name": "x"}, headers=_auth()).status_code == 404
        # sem credencial → 401 (require_actor)
        assert client.patch(f"/api/v1/communities/{com.id}", json={"name": "x"}).status_code == 401
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()
