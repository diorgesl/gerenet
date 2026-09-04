from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session) -> dict:
    """Site, org, switch, 2 NE8000 + circuito + 2 sessoes + vlans/prefixos (padrão dos testes BGP)."""
    site = create_site(db_session, SiteCreate(name="pop-dash"), actor="cli")
    env = {
        "site_id": site.id,
        "org_id": create_organization(
            db_session, OrganizationCreate(name="Cliente Dash", asn=64512), actor="cli"
        ).id,
    }
    sw = create_device(
        db_session, DeviceCreate(name="sw-dash", management_address="10.8.2.1"), actor="cli"
    )
    ne1 = create_device(
        db_session, DeviceCreate(name="ne8k-dash1", management_address="10.8.2.2", asn=64600), actor="cli"
    )
    ne2 = create_device(
        db_session, DeviceCreate(name="ne8k-dash2", management_address="10.8.2.3", asn=64601), actor="cli"
    )
    env.update({"sw_id": sw.id, "ne1_id": ne1.id, "ne2_id": ne2.id})
    circ = models.Circuit(
        code="DASH-01",
        organization_id=env["org_id"],
        site_id=env["site_id"],
        access_device_id=sw.id,
        access_port="GE0/0/1",
        edge_device_id=ne1.id,
    )
    db_session.add(circ)
    db_session.flush()
    env["circ_id"] = circ.id
    return env


def test_dashboard_agrega(client: TestClient, db_session) -> None:
    env = _ambiente(db_session)

    r1 = create_device(
        db_session,
        DeviceCreate(name="r1", management_address="10.0.0.1", site_id=env["site_id"]),
        actor="cli",
    )
    r2 = create_device(
        db_session, DeviceCreate(name="r2", management_address="10.0.0.2"), actor="cli"
    )
    r3 = create_device(
        db_session, DeviceCreate(name="r3", management_address="10.0.0.3"), actor="cli"
    )
    r3.comm_status = "fail"

    r1.last_collected_at = datetime.now(UTC)  # uma coleta já feita
    snap = models.DeviceSnapshot(device_id=r1.id, status="success", resources={})
    job = models.JobRun(device_id=r2.id, origin="api", actor="api", kind="collect", status="running")
    sessao_ativa = models.BgpSession(
        circuit_id=env["circ_id"], device_id=env["ne1_id"], afi="ipv4",
        local_address="100.64.1.1", remote_address="100.64.1.2", asn_remote=64512,
    )
    sessao_shutdown = models.BgpSession(
        circuit_id=env["circ_id"], device_id=env["ne2_id"], afi="ipv6",
        local_address="100.64.2.1", remote_address="100.64.2.2", asn_remote=64512,
        shutdown=True,
    )
    db_session.add_all([snap, job, sessao_ativa, sessao_shutdown])
    db_session.add_all([
        models.Vlan(site_id=env["site_id"], vid=100),  # default reservada
        models.Vlan(site_id=env["site_id"], vid=200, status="liberada"),
        models.IpPrefix(network="10.99.1.0/31", site_id=env["site_id"]),  # default reservada
        models.IpPrefix(network="10.99.2.0/31", site_id=env["site_id"], status="liberada"),
    ])
    db_session.commit()

    resp = client.get("/api/v1/dashboard", headers=_auth())
    assert resp.status_code == 200
    dados = resp.json()

    # O ambiente tem 6 devices (sw-dash, ne8k-dash1/2 + r1..r3) — o dashboard
    # agrega TODOS; esperado calibrado ao fixture do _ambiente (T6/revisão).
    assert dados["devices"] == {
        "total": 6, "active": 6, "with_snapshot": 1,
        "by_comm_status": {"unknown": 5, "ok": 0, "fail": 1},
    }
    nomes = [p["name"] for p in dados["per_device"]]
    assert nomes == ["ne8k-dash1", "ne8k-dash2", "r1", "r2", "r3", "sw-dash"]
    p = {d["name"]: d for d in dados["per_device"]}
    assert p["r1"]["latest_snapshot"]["id"] == snap.id
    assert p["r1"]["latest_snapshot"]["status"] == "success"
    assert isinstance(p["r1"]["snapshot_age_seconds"], (int, float))
    assert p["r1"]["site_name"] == "pop-dash"
    assert p["r2"]["active_job"] == {"id": job.id, "status": "running"}
    assert p["r1"]["active_job"] is None
    assert p["r3"]["latest_snapshot"] is None and p["r3"]["active_job"] is None

    assert dados["bgp_sessions"] == {"total": 2, "active": 1, "shutdown": 1}
    assert dados["circuits"] == {"total": 1, "active": 1}
    assert dados["vlans"] == {"reserved": 1, "freed": 1}
    assert dados["ip_prefixes"] == {"reserved": 1, "freed": 1}
    assert 1 <= len(dados["recent_audit"]) <= 20
    assert set(dados["recent_audit"][0]) == {"id", "type", "actor", "details", "created_at"}


def test_dashboard_exige_autenticacao(client: TestClient) -> None:
    assert client.get("/api/v1/dashboard").status_code == 401
