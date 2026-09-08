import os

# A suíte TRUNCATE o banco a cada teste: nunca rodar contra o banco dev.
# GERENET_DATABASE_URL do shell não vale aqui — override explícito via
# GERENET_TEST_DATABASE_URL (para CI), default gerenet_test.
_TEST_DATABASE_URL = os.environ.get("GERENET_TEST_DATABASE_URL") or (
    "postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test"
)
if "test" not in _TEST_DATABASE_URL.rsplit("/", 1)[-1]:
    raise SystemExit(
        "GERENET_TEST_DATABASE_URL deve apontar para um banco de teste "
        "(ex.: .../gerenet_test); a suíte TRUNCATE o banco a cada teste."
    )
os.environ["GERENET_DATABASE_URL"] = _TEST_DATABASE_URL

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gerenet.config import Settings, set_settings
from gerenet.db import SessionLocal
from gerenet.domain import models


@pytest.fixture()
def db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _limpa_tabelas(db_session: Session) -> None:
    yield
    # Catálogos (bgp_policy_profiles, communities) ficam de fora de propósito:
    # são seedados pela migration e imutáveis no ciclo A (ruling 2 do Plano 2).
    db_session.execute(
        text(
            "TRUNCATE approvals, change_steps, change_requests, audit_events, user_sessions, users, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations, vsi_members, vsi_services, service_endpoints, l2vc_services, mpls_domain_members, mpls_domains, upstreams, upstream_circuits, upstream_communities, roas, irr_cache RESTART IDENTITY CASCADE"
        )
    )
    db_session.commit()


@pytest.fixture(autouse=True)
def _reseta_settings() -> None:
    yield
    set_settings(Settings())


# ---- Fase 5 (upstreams): fixtures compartilhadas — testes usam `session`. ----

@pytest.fixture
def session(db_session) -> Session:
    yield db_session


@pytest.fixture
def org_operadora(db_session: Session) -> models.Organization:
    org = models.Organization(name="Operadora F5", asn=64501, kind="operadora")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def org_downstream(db_session: Session) -> models.Organization:
    org = models.Organization(name="Cliente F5", asn=64512, kind="downstream")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def site_f5(db_session: Session) -> models.Site:
    site = models.Site(name="pop-spo-f5", p2p_ipv4_block="100.64.10.0/24")
    db_session.add(site)
    db_session.commit()
    return site


@pytest.fixture
def edge_device(db_session: Session, site_f5: models.Site) -> models.Device:
    dev = models.Device(name="edge-f5", management_address="10.99.0.1",
                        site_id=site_f5.id, asn=65001)
    db_session.add(dev)
    db_session.commit()
    return dev


@pytest.fixture
def circuito_up(db_session: Session, org_operadora: models.Organization,
                site_f5: models.Site, edge_device: models.Device) -> models.Circuit:
    circ = models.Circuit(
        code="CIRC-UP-0001", organization_id=org_operadora.id, site_id=site_f5.id,
        access_device_id=None, access_port="GE0/0/0", edge_device_id=edge_device.id,
        vlan_mode="none", bandwidth="10 Gbps", mtu=9214,
    )
    db_session.add(circ)
    db_session.commit()
    return circ


@pytest.fixture
def circuito_com_p2p(db_session: Session, org_downstream: models.Organization,
                     site_f5: models.Site, edge_device: models.Device) -> models.Circuit:
    circ = models.Circuit(
        code="CIRC-DN-0001", organization_id=org_downstream.id, site_id=site_f5.id,
        access_device_id=edge_device.id, access_port="GE0/0/1", edge_device_id=edge_device.id,
    )
    db_session.add(circ)
    db_session.flush()
    db_session.add(models.IpPrefix(site_id=site_f5.id, network="100.64.10.0/31",
                                   circuit_id=circ.id))
    db_session.commit()
    return circ


@pytest.fixture
def up(db_session: Session, org_operadora: models.Organization) -> models.Upstream:
    up = models.Upstream(name="transito-f5", tipo="transito", organization_id=org_operadora.id,
                         expected_prefixes_v4=1000, expected_prefixes_v6=200,
                         entrada_local_preference=100, contingencia_local_preference=60,
                         contingencia_prepend=3, max_prefix_margin_pct=10)
    db_session.add(up)
    db_session.commit()
    return up


@pytest.fixture
def up2(db_session: Session, org_operadora: models.Organization) -> models.Upstream:
    up = models.Upstream(name="ix-f5", tipo="ix", organization_id=org_operadora.id)
    db_session.add(up)
    db_session.commit()
    return up


@pytest.fixture
def bgp_session_principal(db_session: Session, circuito_up: models.Circuit,
                          edge_device: models.Device) -> models.BgpSession:
    """Sessão V4 do circuito de upstream (perfil import up-full do seed)."""
    perfil = db_session.scalar(select(models.PolicyProfile).where(
        models.PolicyProfile.name == "up-full",
        models.PolicyProfile.direction == "import"))
    sessao = models.BgpSession(
        circuit_id=circuito_up.id, device_id=edge_device.id, afi="ipv4",
        local_address="100.64.10.1", remote_address="100.64.10.2",
        asn_local=65001, asn_remote=64501,
        import_profile_id=perfil.id if perfil else None)
    db_session.add(sessao)
    db_session.commit()
    return sessao


@pytest.fixture
def up_com_circuito(db_session, up: models.Upstream, circuito_up: models.Circuit) -> models.Upstream:
    db_session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=circuito_up.id,
                                          papel="principal", ordem=1))
    db_session.commit()
    return up


@pytest.fixture
def up_com_sessao_upfull(db_session, up_com_circuito: models.Upstream,
                         bgp_session_principal: models.BgpSession) -> models.Upstream:
    return up_com_circuito


@pytest.fixture
def up_com_2_circuitos(db_session, up: models.Upstream, org_operadora: models.Organization,
                       site_f5: models.Site, edge_device: models.Device) -> models.Upstream:
    c1 = models.Circuit(code="CIRC-UP-0002", organization_id=org_operadora.id,
                        site_id=site_f5.id, access_device_id=None, access_port="GE0/0/1",
                        edge_device_id=edge_device.id, vlan_mode="none")
    c2 = models.Circuit(code="CIRC-UP-0003", organization_id=org_operadora.id,
                        site_id=site_f5.id, access_device_id=None, access_port="GE0/0/2",
                        edge_device_id=edge_device.id, vlan_mode="none")
    db_session.add_all([c1, c2])
    db_session.flush()
    s1 = models.BgpSession(circuit_id=c1.id, device_id=edge_device.id, afi="ipv4",
                           local_address="100.64.10.1", remote_address="100.64.10.2",
                           asn_local=65001, asn_remote=64501)
    s2 = models.BgpSession(circuit_id=c2.id, device_id=edge_device.id, afi="ipv4",
                           local_address="100.64.10.5", remote_address="100.64.10.6",
                           asn_local=65001, asn_remote=64501)
    db_session.add_all([s1, s2])
    db_session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=c1.id,
                                          papel="principal", ordem=1))
    db_session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=c2.id,
                                          papel="contingencia", ordem=2))
    db_session.commit()
    return up


@pytest.fixture
def snapshot_bgp_ok(db_session: Session, edge_device: models.Device) -> models.DeviceSnapshot:
    snap = models.DeviceSnapshot(
        device_id=edge_device.id, status="success",
        resources={"interfaces": [], "bgp_peers": [
            {"peer": "100.64.10.2", "asn": 64501, "estado": "established", "prefixos": 1000},
        ]})
    db_session.add(snap)
    db_session.commit()
    return snap
