"""Reconciliation (GET /reconciliation) e desired-config (spec §8)."""
import ipaddress

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
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente_dual(db_session: Session) -> dict:
    """Circuito reservado dual + autorizações v4/v6 + sessões com perfil full."""
    site = create_site(db_session, SiteCreate(name="pop-rec-api"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Rec API", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-rec-api", management_address="10.41.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-rec-api", management_address="10.41.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-REC-API", organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id,
            edge_trunk="Eth-Trunk127",
        ),
        actor="cli",
    ).id
    reservar_circuito(db_session, circ_id, actor="cli")
    for familia, prefixo in (("ipv4", "192.0.2.0/24"), ("ipv6", "2001:DB8::/32")):
        create_authorization(
            db_session, PrefixAuthorizationCreate(
                organization_id=org.id, family=familia, prefix=prefixo,
            ), actor="cli",
        )
    full = next(p.id for p in list_policy_profiles(db_session, direction="export") if p.name == "full")
    redes = {
        int(ipaddress.ip_network(l.network).version): l.network
        for l in db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    }
    for afi in ("ipv4", "ipv6"):
        local, remota = pontas_v4(redes[4]) if afi == "ipv4" else pontas_v6(redes[6])
        create_session(
            db_session,
            BgpSessionCreate(
                circuit_id=circ_id, device_id=ne.id, afi=afi,
                local_address=local.removesuffix("/126"),
                remote_address=remota.removesuffix("/126"),
                export_profile_id=full,
            ),
            actor="cli",
        )
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _snapshot_vazio(db_session: Session, ne_id: int) -> int:
    snap = models.DeviceSnapshot(
        device_id=ne_id, status="success",
        resources={
            "version": {"version": "8.210"},
            "interfaces": [], "bgp_peers": [], "bgp_peers_verbose": [],
        },
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap.id


def test_reconciliation_200_com_aviso(client: TestClient, db_session: Session) -> None:
    env = _ambiente_dual(db_session)
    resp = client.get(f"/api/v1/reconciliation?device_id={env['ne_id']}", headers=_auth())
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["device_id"] == env["ne_id"]
    assert corpo["snapshot_id"] is None
    assert corpo["aviso"] and corpo["gerado_em"]
    assert corpo["items"] == []  # sem snapshot: só aviso (spec §6)


def test_reconciliation_por_snapshot_id(client: TestClient, db_session: Session) -> None:
    env = _ambiente_dual(db_session)
    snap_id = _snapshot_vazio(db_session, env["ne_id"])
    resp = client.get(f"/api/v1/reconciliation?snapshot_id={snap_id}", headers=_auth())
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["snapshot_id"] == snap_id
    tipos = [i["tipo"] for i in corpo["items"]]
    assert "peer.ausente" in tipos  # sessões ativas vs. snapshot vazio
    assert "subinterface.ausente" in tipos
    assert all(i["acao"] for i in corpo["items"])

    sem_filtro = client.get("/api/v1/reconciliation", headers=_auth())
    assert sem_filtro.status_code == 400
    ambos = client.get(
        f"/api/v1/reconciliation?device_id=1&snapshot_id={snap_id}", headers=_auth()
    )
    assert ambos.status_code == 400  # filtros excludentes (ruling 9)


def test_reconciliation_404s(client: TestClient, db_session: Session) -> None:
    assert client.get("/api/v1/reconciliation?device_id=9999", headers=_auth()).status_code == 404
    assert client.get("/api/v1/reconciliation?snapshot_id=9999", headers=_auth()).status_code == 404


def test_desired_config(client: TestClient, db_session: Session) -> None:
    env = _ambiente_dual(db_session)
    resp = client.get(f"/api/v1/devices/{env['ne_id']}/desired-config", headers=_auth())
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["device_id"] == env["ne_id"]
    assert corpo["texto"]
    tipos = [b["tipo"] for b in corpo["blocos"]]
    # dual stack: uma definição por família — o render agrupa por tipo (TIPO_ORDEM)
    assert tipos[0:4] == ["subinterface", "prefix_list", "prefix_list", "route_policy_import"]
    assert any(b["objeto"] == "circuit" for b in corpo["blocos"])
    assert "password" not in resp.text  # regra global: senha nunca no payload

    assert client.get("/api/v1/devices/9999/desired-config", headers=_auth()).status_code == 404
