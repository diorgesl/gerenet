"""API de upstreams (F5/A5) — routers de upstreams e exposição de campos derivados.

- upstreams: CRUD + vínculo de circuitos + communities de operadora.
- ajustes dos routers existentes: organization_kind (circuits/bgp-sessions),
  kind 'operadora' no cadastro de organizações, validacao/prefix-authorizations
  e upstream_id/upstream_name nas change requests.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session: Session) -> dict:
    """Org operadora, site e devices vinculados — circuito de upstream por API."""
    site = create_site(db_session, SiteCreate(name="POP-UP-API"), actor="cli")
    org = create_organization(
        db_session,
        OrganizationCreate(name="Operadora API", asn=64530, kind="operadora"),
        actor="cli",
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-up-api", management_address="10.9.0.2"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-up-api", management_address="10.9.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


# ---- upstreams: CRUD -----------------------------------------------------


def test_cria_upstream_router(client: TestClient, org_operadora: models.Organization) -> None:
    resp = client.post(
        "/api/v1/upstreams",
        json={"name": "transito-fb", "tipo": "transito", "organization_id": org_operadora.id},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "transito-fb"
    assert data["tipo"] == "transito"
    assert data["max_prefix_margin_pct"] == 20  # default do schema
    assert data["organization_kind"] == "operadora"
    assert data["organization_name"] == "Operadora F5"


def test_lista_upstreams_ordena_e_filtra(client: TestClient, org_operadora: models.Organization) -> None:
    for nome, tipo in (("pnz-nordeste", "pni"), ("ix-sp", "ix")):
        resp = client.post(
            "/api/v1/upstreams",
            json={"name": nome, "tipo": tipo, "organization_id": org_operadora.id},
            headers=_auth(),
        )
        assert resp.status_code == 201, resp.text
    lista = client.get("/api/v1/upstreams", headers=_auth()).json()
    assert [u["name"] for u in lista] == ["ix-sp", "pnz-nordeste"]
    assert lista[0]["organization_kind"] == "operadora"


def test_cria_upstream_org_nao_operadora_da_400(
    client: TestClient, org_downstream: models.Organization
) -> None:
    resp = client.post(
        "/api/v1/upstreams",
        json={"name": "up-invalido", "tipo": "transito", "organization_id": org_downstream.id},
        headers=_auth(),
    )
    assert resp.status_code == 400
    assert "não é operadora" in resp.json()["detail"]


def test_cria_upstream_duplicado_da_409(client: TestClient, org_operadora: models.Organization) -> None:
    corpo = {"name": "transito-duplicado", "tipo": "transito", "organization_id": org_operadora.id}
    assert client.post("/api/v1/upstreams", json=corpo, headers=_auth()).status_code == 201
    dup = client.post("/api/v1/upstreams", json=corpo, headers=_auth())
    assert dup.status_code == 409
    assert "nome" in dup.json()["detail"]


def test_upstream_nao_encontrado_da_404(client: TestClient) -> None:
    assert client.get("/api/v1/upstreams/9999", headers=_auth()).status_code == 404
    assert client.patch("/api/v1/upstreams/9999", json={"name": "x"}, headers=_auth()).status_code == 404


def test_rota_requer_chave(client: TestClient) -> None:
    assert client.get("/api/v1/upstreams").status_code == 401


def test_patch_atualiza_client_e_admin_status_null_da_400(
    client: TestClient, org_operadora: models.Organization
) -> None:
    created = client.post(
        "/api/v1/upstreams",
        json={"name": "transito-patch", "tipo": "transito", "organization_id": org_operadora.id},
        headers=_auth(),
    ).json()

    nome = client.patch(f"/api/v1/upstreams/{created['id']}", json={"name": "transito-patch-2"}, headers=_auth())
    assert nome.status_code == 200
    assert nome.json()["name"] == "transito-patch-2"

    off = client.patch(
        f"/api/v1/upstreams/{created['id']}", json={"admin_status": False}, headers=_auth()
    )
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    # PATCH puro de disable é idempotente
    repetido = client.patch(
        f"/api/v1/upstreams/{created['id']}", json={"admin_status": False}, headers=_auth()
    )
    assert repetido.status_code == 200

    null = client.patch(
        f"/api/v1/upstreams/{created['id']}", json={"admin_status": None}, headers=_auth()
    )
    assert null.status_code == 400


# ---- vínculo de circuitos -------------------------------------------------


def _cria_up(corpo: dict, client: TestClient) -> int:
    resp = client.post("/api/v1/upstreams", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _cria_transito(client: TestClient, org_operadora: models.Organization) -> int:
    return _cria_up(
        {"name": "transito-vincular", "tipo": "transito", "organization_id": org_operadora.id}, client
    )


def test_vincular_desvincular_circuito(client: TestClient, org_operadora: models.Organization,
                                       circuito_up: models.Circuit) -> None:
    up_id = _cria_transito(client, org_operadora)

    vinc = client.post(
        f"/api/v1/upstreams/{up_id}/circuits",
        json={"circuit_id": circuito_up.id, "papel": "principal", "ordem": 1},
        headers=_auth(),
    )
    assert vinc.status_code == 200, vinc.text
    assert vinc.json()["circuitos"][0]["papel"] == "principal"
    assert vinc.json()["circuitos"][0]["circuit_id"] == circuito_up.id

    # circuito já vinculado a um upstream → 409
    dup = client.post(
        f"/api/v1/upstreams/{up_id}/circuits",
        json={"circuit_id": circuito_up.id, "papel": "principal"},
        headers=_auth(),
    )
    assert dup.status_code == 409

    desv = client.delete(f"/api/v1/upstreams/{up_id}/circuits/{circuito_up.id}", headers=_auth())
    assert desv.status_code == 204

    detalhe = client.get(f"/api/v1/upstreams/{up_id}", headers=_auth()).json()
    assert detalhe["circuitos"] == []


def test_upstream_detail_traz_circuitos(client: TestClient, up_com_circuito: models.Upstream) -> None:
    resp = client.get(f"/api/v1/upstreams/{up_com_circuito.id}", headers=_auth())
    assert resp.status_code == 200
    data = resp.json()
    assert data["circuitos"][0]["papel"] == "principal"
    assert data["circuitos"][0]["circuit_id"] == up_com_circuito.circuitos[0].circuit_id
    assert data["sessoes"] == []
    assert data["comunidades"] == []
    assert data["organization_name"] == "Operadora F5"


def test_upstream_detail_traz_sessoes_dos_circuitos(
    client: TestClient, up_com_sessao_upfull: models.Upstream
) -> None:
    data = client.get(f"/api/v1/upstreams/{up_com_sessao_upfull.id}", headers=_auth()).json()
    assert len(data["sessoes"]) == 1
    assert data["sessoes"][0]["organization_kind"] == "operadora"


def test_desvincular_so_principal_restante_da_400(
    client: TestClient, up_com_2_circuitos: models.Upstream
) -> None:
    up_id = up_com_2_circuitos.id
    circuitos = {v.circuit_id: v.papel for v in up_com_2_circuitos.circuitos}
    principal_id = next(c for c, p in circuitos.items() if p == "principal")

    resp = client.delete(f"/api/v1/upstreams/{up_id}/circuits/{principal_id}", headers=_auth())
    assert resp.status_code == 400
    assert "principal" in resp.json()["detail"]

    cont_id = next(c for c, p in circuitos.items() if p == "contingencia")
    assert client.delete(f"/api/v1/upstreams/{up_id}/circuits/{cont_id}", headers=_auth()).status_code == 204
    # reesboço: desativar o principal órfão exige outro principal — vínculo novo
    novo = client.post(
        f"/api/v1/upstreams/{up_id}/circuits",
        json={"circuit_id": cont_id, "papel": "principal"},
        headers=_auth(),
    )
    assert novo.status_code == 200


def test_upstream_desativado_nao_recebe_circuito(
    client: TestClient, org_operadora: models.Organization, circuito_up: models.Circuit
) -> None:
    up_id = _cria_transito(client, org_operadora)
    client.patch(f"/api/v1/upstreams/{up_id}", json={"admin_status": False}, headers=_auth())
    resp = client.post(
        f"/api/v1/upstreams/{up_id}/circuits",
        json={"circuit_id": circuito_up.id, "papel": "principal"},
        headers=_auth(),
    )
    assert resp.status_code == 409
    assert "desativado" in resp.json()["detail"]


# ---- communities de operadora ---------------------------------------------


def test_add_list_remove_community(client: TestClient, up: models.Upstream) -> None:
    corpo = {"purpose": "blackhole", "value": "65530:20:0", "regiao": "SP"}
    resp = client.post(f"/api/v1/upstreams/{up.id}/communities", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    comunidade = resp.json()
    assert comunidade["value"] == "65530:20:0"
    assert comunidade["direcao"] == "ambos"

    # duplicada (purpose/value/regiao) → 409
    dup = client.post(f"/api/v1/upstreams/{up.id}/communities", json=corpo, headers=_auth())
    assert dup.status_code == 409

    data = client.get(f"/api/v1/upstreams/{up.id}", headers=_auth()).json()
    assert [c["value"] for c in data["comunidades"]] == ["65530:20:0"]

    resp = client.delete(f"/api/v1/upstreams/{up.id}/communities/{comunidade['id']}", headers=_auth())
    assert resp.status_code == 204

    assert client.get(f"/api/v1/upstreams/{up.id}", headers=_auth()).json()["comunidades"] == []
    again = client.delete(f"/api/v1/upstreams/{up.id}/communities/{comunidade['id']}", headers=_auth())
    assert again.status_code == 404


# ---- ajustes dos routers existentes ----------------------------------------


def test_organizations_aceita_kind_operadora(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/organizations", json={"name": "Operadora API", "kind": "operadora"}, headers=_auth()
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]
    assert resp.json()["kind"] == "operadora"

    filtra = client.get("/api/v1/organizations?kind=operadora", headers=_auth()).json()
    assert [o["name"] for o in filtra] == ["Operadora API"]

    # PATCH aceita o kind operadora (troca para parceiro — updateLiteral)
    patched = client.patch(
        f"/api/v1/organizations/{org_id}", json={"kind": "parceiro"}, headers=_auth()
    )
    assert patched.status_code == 200
    assert patched.json()["kind"] == "parceiro"


def test_lista_circuitos_expoe_organization_kind(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    criado = client.post(
        "/api/v1/circuits",
        json={
            "code": "CIRC-UP-API",
            "organization_id": env["org_id"],
            "site_id": env["site_id"],
            "access_device_id": env["sw_id"],
            "access_port": "GE0/0/0",
            "edge_device_id": env["ne_id"],
        },
        headers=_auth(),
    )
    assert criado.status_code == 201, criado.text
    circ_id = criado.json()["id"]

    lista = client.get("/api/v1/circuits", headers=_auth()).json()
    assert [c["organization_kind"] for c in lista] == ["operadora"]
    assert client.get(f"/api/v1/circuits/{circ_id}", headers=_auth()).json()["organization_kind"] == "operadora"


def test_lista_bgp_sessions_expoe_organization_kind(
    client: TestClient, bgp_session_principal: models.BgpSession
) -> None:
    lista = client.get("/api/v1/bgp-sessions", headers=_auth()).json()
    assert [s["organization_kind"] for s in lista] == ["operadora"]
    detalhe = client.get(f"/api/v1/bgp-sessions/{bgp_session_principal.id}", headers=_auth()).json()
    assert detalhe["organization_kind"] == "operadora"


def test_autorizacao_expoe_origin_e_validacao(
    client: TestClient, db_session: Session, org_operadora: models.Organization
) -> None:
    autorizacao = models.BgpPrefixAuthorization(
        organization_id=org_operadora.id, family="ipv4", prefix="203.0.113.0/24",
        origin="irr", validacao="ok",
    )
    db_session.add(autorizacao)
    db_session.commit()

    data = client.get(f"/api/v1/prefix-authorizations/{autorizacao.id}", headers=_auth()).json()
    assert data["origin"] == "irr"
    assert data["validacao"] == "ok"

    lista = client.get("/api/v1/prefix-authorizations", headers=_auth()).json()
    assert lista[0]["origin"] == "irr"
    assert lista[0]["validacao"] == "ok"


def test_change_request_expoe_upstream_id_e_nome(
    client: TestClient, db_session: Session, up: models.Upstream
) -> None:
    cr = models.ChangeRequest(
        escopo="upstream", upstream_id=up.id, acao="provision",
        criticidade="media", motivo="Solicitação de provision via API.",
    )
    db_session.add(cr)
    db_session.commit()

    data = client.get(f"/api/v1/change-requests/{cr.id}", headers=_auth()).json()
    assert data["escopo"] == "upstream"
    assert data["upstream_id"] == up.id
    assert data["upstream_name"] == "transito-f5"

    lista = client.get("/api/v1/change-requests", headers=_auth()).json()
    assert [r["upstream_name"] for r in lista] == ["transito-f5"]
