"""API MPLS — fase 4, spec §9: domínios, L2VC e VSI via REST."""
import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _criar_site_devs_dominio(client, headers):
    site = client.post("/api/v1/sites", headers=headers, json={"name": "pop-api-mpls"}).json()
    # site_id em ambos: a reserva de VLAN de AC (T3) exige equipamento com site.
    d1 = client.post("/api/v1/devices", headers=headers,
                     json={"name": "sw-api-1", "management_address": "10.0.0.91",
                           "site_id": site["id"]}).json()
    d2 = client.post("/api/v1/devices", headers=headers,
                     json={"name": "sw-api-2", "management_address": "10.0.0.92",
                           "site_id": site["id"]}).json()
    dom = client.post("/api/v1/mpls/domains", headers=headers, json={"name": "dom-api"}).json()
    for dev, lp in ((d1, "10.255.7.1"), (d2, "10.255.7.2")):
        client.post(f"/api/v1/mpls/domains/{dom['id']}/members", headers=headers,
                    json={"device_id": dev["id"], "loopback_address": lp, "role": "pe"})
    return site, d1, d2, dom


def test_domains_crud_e_membros(client):
    headers = _auth()
    _site, _d1, _d2, dom = _criar_site_devs_dominio(client, headers)
    assert client.get("/api/v1/mpls/domains", headers=headers).json()[0]["name"] == "dom-api"
    detalhe = client.get(f"/api/v1/mpls/domains/{dom['id']}", headers=headers).json()
    assert len(detalhe["members"]) == 2
    ok = client.patch(f"/api/v1/mpls/domains/{dom['id']}", headers=headers, json={"admin_status": False})
    assert ok.status_code == 200 and ok.json()["admin_status"] is False
    dup = client.post("/api/v1/mpls/domains", headers=headers, json={"name": "dom-api"})
    assert dup.status_code == 409
    naive = client.get("/api/v1/mpls/domains", headers=headers)
    assert len(naive.json()) == 0  # default exclude disabled


def test_l2vc_criar_com_409_e_plano(client):
    headers = _auth()
    _site, d1, d2, dom = _criar_site_devs_dominio(client, headers)

    def _l2vc():
        return client.post("/api/v1/mpls/l2vc", headers=headers, json={
            "domain_id": dom["id"], "name": "api-l2vc", "vc_id": 800,
            "endpoints": [
                {"device_id": d1["id"], "interface": "10GE0/0/1", "encapsulation": "dot1q", "vid": 401},
                {"device_id": d2["id"], "interface": "10GE0/0/2", "encapsulation": "dot1q", "vid": 402},
            ]})
    criada = _l2vc()
    assert criada.status_code == 201
    svc = criada.json()
    assert svc["vc_id"] == 800 and len(svc["endpoints"]) == 2
    dupe = _l2vc()
    assert dupe.status_code == 409
    plano = client.get(f"/api/v1/mpls/l2vc/{svc['id']}/plano", headers=headers)
    assert plano.status_code == 200
    plano_data = plano.json()
    assert len(plano_data) == 2  # um por ponta (blocos com aviso sem coleta)
    assert all(set(item) == {"device_id", "blocos", "aviso", "baseline_snapshot_id"} for item in plano_data)
    descon = client.patch(f"/api/v1/mpls/l2vc/{svc['id']}/status", headers=headers, json={"admin_status": False})
    assert descon.json()["admin_status"] is False
    assert client.get("/api/v1/mpls/l2vc", headers=headers).json() == []


def test_vsi_criar_e_consultar(client):
    headers = _auth()
    _site, d1, d2, dom = _criar_site_devs_dominio(client, headers)
    criado = client.post("/api/v1/mpls/vsi", headers=headers, json={
        "domain_id": dom["id"], "name": "vsi api", "vsi_id": 550,
        "members": [d1["id"], d2["id"]],
    })
    assert criado.status_code == 201
    vsi = criado.json()
    assert vsi["vrp_name"] == "VSI-VSI-API-550"
    assert len(vsi["members"]) == 2
    assert client.get(f"/api/v1/mpls/vsi/{vsi['id']}", headers=headers).json()["vsi_id"] == 550


def test_change_request_l2vc(client):
    headers = _auth()
    _site, d1, d2, dom = _criar_site_devs_dominio(client, headers)
    svc = client.post("/api/v1/mpls/l2vc", headers=headers, json={
        "domain_id": dom["id"], "name": "cr-api", "vc_id": 801,
        "endpoints": [
            {"device_id": d1["id"], "interface": "10GE0/0/1", "encapsulation": "dot1q", "vid": 411},
            {"device_id": d2["id"], "interface": "10GE0/0/2", "encapsulation": "dot1q", "vid": 412},
        ]}).json()
    cr = client.post("/api/v1/change-requests", headers=headers, json={
        "escopo": "l2vc", "l2vc_id": svc["id"], "acao": "provision", "motivo": "ativar", "criticidade": "baixa",
    })
    assert cr.status_code == 201
    body = cr.json()
    assert body["escopo"] == "l2vc" and len(body["steps"]) == 2
    sem_id = client.post("/api/v1/change-requests", headers=headers, json={
        "escopo": "l2vc", "acao": "provision", "motivo": "sem id",
    })
    assert sem_id.status_code == 422
