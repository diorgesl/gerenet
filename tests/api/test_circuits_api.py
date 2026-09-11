import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import pontas_v4, pontas_v6
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session: Session) -> dict:
    """Org, site e devices vinculados — espelho do helper de domínio."""
    site = create_site(db_session, SiteCreate(name="POP-CIRC-API"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Circ API", asn=64512), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-circ-api", management_address="10.9.0.2"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-circ-api", management_address="10.9.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _corpo(env: dict, code: str = "CIRC-API-1") -> dict:
    return {
        "code": code,
        "organization_id": env["org_id"],
        "site_id": env["site_id"],
        "access_device_id": env["sw_id"],
        "access_port": "GE0/0/1",
        "edge_device_id": env["ne_id"],
    }


def test_crud_circuitos(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    criado = client.post("/api/v1/circuits", json=_corpo(env), headers=_auth())
    assert criado.status_code == 201, criado.text
    circ_id = criado.json()["id"]
    assert criado.json()["stack"] == "dual"

    lista = client.get(f"/api/v1/circuits?site_id={env['site_id']}", headers=_auth()).json()
    assert [c["code"] for c in lista] == ["CIRC-API-1"]
    assert "ipv4_local" not in lista[0]  # lista é CircuitOut simples

    corpo = client.get(f"/api/v1/circuits/{circ_id}", headers=_auth()).json()
    assert corpo["ipv4_local"] is None  # ainda não reservado

    dup = client.post("/api/v1/circuits", json=_corpo(env), headers=_auth())
    assert dup.status_code == 409
    assert client.get("/api/v1/circuits/9999", headers=_auth()).status_code == 404


def test_reserva_expoe_pontas_derivadas(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-DUAL"), headers=_auth()
    ).json()["id"]

    reserva = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert reserva.status_code == 200, reserva.text
    corpo = reserva.json()

    linhas = {
        linha.network
        for linha in db_session.scalars(
            select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id)
        )
    }
    rede_v4 = next(n for n in linhas if ":" not in n)
    rede_v6 = next(n for n in linhas if ":" in n)
    assert (corpo["ipv4_local"], corpo["ipv4_remote"]) == pontas_v4(rede_v4)
    assert (corpo["ipv6_local"], corpo["ipv6_remote"]) == pontas_v6(rede_v6)

    # o mesmo detalhe sai no GET
    detalhe = client.get(f"/api/v1/circuits/{circ_id}", headers=_auth()).json()
    assert detalhe["ipv4_local"] == corpo["ipv4_local"]

    # idempotente: segunda reserva 200 sem linhas novas
    antes = len(list(db_session.scalars(select(models.IpPrefix))))
    repetida = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert repetida.status_code == 200
    assert len(list(db_session.scalars(select(models.IpPrefix)))) == antes


def test_reserva_repetida_audita_noop(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-AUDIT"), headers=_auth()
    ).json()["id"]
    for _ in range(2):
        resp = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
        assert resp.status_code == 200

    # _ambiente audita também site/org/devices — filtro espelha o padrão dos
    # testes de domínio (só eventos do circuito).
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        if e.type.startswith("circuit.")
    ]
    assert tipos == ["circuit.create", "circuit.reserve", "circuit.reserve"]


def test_reserva_ipv6_nao_expoe_par_v4_interno(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    corpo = _corpo(env, "CIRC-V6")
    corpo["stack"] = "ipv6"
    circ_id = client.post("/api/v1/circuits", json=corpo, headers=_auth()).json()["id"]

    resp = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert resp.status_code == 200
    corpo_resp = resp.json()
    assert corpo_resp["ipv4_local"] is None
    assert corpo_resp["ipv6_local"] is not None
    assert corpo_resp["ipv6_local"].endswith("/126")


def test_patch_circuito_desativa_e_audita(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-PATCH"), headers=_auth()
    ).json()["id"]

    off = client.patch(f"/api/v1/circuits/{circ_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    mtu = client.patch(f"/api/v1/circuits/{circ_id}", json={"mtu": 9000}, headers=_auth())
    assert mtu.status_code == 200

    # filtro espelha o padrão dos testes de domínio (só eventos do circuito).
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        if e.type.startswith("circuit.")
    ]
    assert tipos == ["circuit.create", "circuit.disable", "circuit.update"]


def test_reserva_com_sufixo_v6_excedente_da_400(client: TestClient, db_session: Session) -> None:
    """Bloco p2p com octetos 2-4 somando >8 dígitos (172.168.200.128) estoura o
    sufixo de 2 hextets do §25.8 — derivar_v6 levanta ValidationError → 400."""
    env = _ambiente(db_session)
    site_db = db_session.get(models.Site, env["site_id"])
    site_db.p2p_ipv4_block = "172.168.200.128/25"
    db_session.commit()
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-V6BIG"), headers=_auth()
    ).json()["id"]

    resp = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert resp.status_code == 400
    assert "excede 8 dígitos" in resp.json()["detail"]


def test_reserva_de_circuito_desativado_da_409(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-OFF"), headers=_auth()
    ).json()["id"]
    client.patch(f"/api/v1/circuits/{circ_id}", json={"admin_status": False}, headers=_auth())

    resp = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert resp.status_code == 409
    assert "desativado" in resp.json()["detail"]

    assert client.post("/api/v1/circuits/9999/reserve", headers=_auth()).status_code == 404


def test_unreserve_libera_e_expoe_pontas_vazias(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-FREE"), headers=_auth()
    ).json()["id"]
    client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())

    resp = client.post(f"/api/v1/circuits/{circ_id}/unreserve", headers=_auth())
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["ipv4_local"] is None and corpo["ipv6_local"] is None

    linhas = list(
        db_session.scalars(
            select(models.Vlan).where(models.Vlan.circuit_id == circ_id)
        )
    ) + list(
        db_session.scalars(
            select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id)
        )
    )
    assert linhas and all(l.status == "liberada" for l in linhas)
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        if e.type.startswith("circuit.")
    ]
    assert tipos == ["circuit.create", "circuit.reserve", "circuit.unreserve"]


def test_unreserve_sem_reservas_audita_noop(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-FREE-NOOP"), headers=_auth()
    ).json()["id"]

    resp = client.post(f"/api/v1/circuits/{circ_id}/unreserve", headers=_auth())
    assert resp.status_code == 200
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "circuit.unreserve")
    )
    assert evento is not None
    assert evento.details["depois"] == {"repetida": True}


def test_unreserve_bloqueia_com_sessao_bgp_409(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-FREE-409"), headers=_auth()
    ).json()["id"]
    client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    db_session.add(
        models.BgpSession(
            circuit_id=circ_id, device_id=env["ne_id"], afi="ipv4",
            local_address="100.64.0.1", remote_address="100.64.0.2", asn_remote=64512,
        )
    )
    db_session.commit()

    resp = client.post(f"/api/v1/circuits/{circ_id}/unreserve", headers=_auth())
    assert resp.status_code == 409
    assert "sess" in resp.json()["detail"]
    vlans = list(
        db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id))
    )
    assert all(v.status == "reservada" for v in vlans)  # nada foi liberado

    assert client.post("/api/v1/circuits/9999/unreserve", headers=_auth()).status_code == 404


def test_unreserve_permite_com_sessao_bgp_desativada(
    client: TestClient, db_session: Session
) -> None:
    """Fluxo do operador: desativar a sessão pela API e então liberar os recursos."""
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-FREE-OFF"), headers=_auth()
    ).json()["id"]
    client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    sessao = models.BgpSession(
        circuit_id=circ_id, device_id=env["ne_id"], afi="ipv4",
        local_address="100.64.0.1", remote_address="100.64.0.2", asn_remote=64512,
    )
    db_session.add(sessao)
    db_session.commit()

    desativa = client.patch(
        f"/api/v1/bgp-sessions/{sessao.id}", json={"admin_status": False}, headers=_auth()
    )
    assert desativa.status_code == 200, desativa.text

    resp = client.post(f"/api/v1/circuits/{circ_id}/unreserve", headers=_auth())
    assert resp.status_code == 200, resp.text
    assert resp.json()["ipv4_local"] is None
    vlans = list(
        db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id))
    )
    assert vlans and all(v.status == "liberada" for v in vlans)


def test_edge_trunk_aceito_no_post_e_patch(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    corpo = _corpo(env, "CIRC-TRUNK-API")
    corpo["edge_trunk"] = "Eth-Trunk127"
    criado = client.post("/api/v1/circuits", json=corpo, headers=_auth())
    assert criado.status_code == 201, criado.text
    assert criado.json()["edge_trunk"] == "Eth-Trunk127"

    get_id = criado.json()["id"]
    assert client.get(f"/api/v1/circuits/{get_id}", headers=_auth()).json()["edge_trunk"] == "Eth-Trunk127"

    patch = client.patch(
        f"/api/v1/circuits/{get_id}", json={"edge_trunk": "Eth-Trunk128"}, headers=_auth()
    )
    assert patch.status_code == 200
    assert patch.json()["edge_trunk"] == "Eth-Trunk128"


def test_edge_trunk_maior_que_64_da_422(client: TestClient, db_session: Session) -> None:
    """Limite do VRP (§8): >64 chars é rejeitado na validação (422, não 500)."""
    env = _ambiente(db_session)
    corpo = _corpo(env, "CIRC-TRUNK-LONGO")
    corpo["edge_trunk"] = "Eth-Trunk" + "9" * 56  # 65 chars no total
    resp = client.post("/api/v1/circuits", json=corpo, headers=_auth())
    assert resp.status_code == 422
