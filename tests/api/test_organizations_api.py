import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.automation.irr import IrrError
from gerenet.config import Settings, set_settings
from gerenet.domain import models


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_criar_listar_detalhar(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/organizations",
        json={"name": "Cliente Org API", "asn": 64512, "kind": "downstream"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]
    assert resp.json()["kind"] == "downstream"

    lista = client.get("/api/v1/organizations", headers=_auth()).json()
    assert [o["name"] for o in lista] == ["Cliente Org API"]

    corpo = client.get(f"/api/v1/organizations/{org_id}", headers=_auth()).json()
    assert corpo["asn"] == 64512

    dup = client.post(
        "/api/v1/organizations", json={"name": "Cliente Org API"}, headers=_auth()
    )
    assert dup.status_code == 409

    assert client.get("/api/v1/organizations/9999", headers=_auth()).status_code == 404


def test_rota_requer_chave(client: TestClient) -> None:
    assert client.get("/api/v1/organizations").status_code == 401


def test_asn_reservado_da_400_e_duplicado_da_409(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/organizations", json={"name": "Org Res", "asn": 23456}, headers=_auth()
    )
    assert resp.status_code == 400
    assert "reservado" in resp.json()["detail"]

    client.post("/api/v1/organizations", json={"name": "Org A", "asn": 64520}, headers=_auth())
    dup = client.post(
        "/api/v1/organizations", json={"name": "Org B", "asn": 64520}, headers=_auth()
    )
    assert dup.status_code == 409
    assert "ASN" in dup.json()["detail"]


def test_patch_desativa_e_audita(db_session: Session, client: TestClient) -> None:
    criada = client.post(
        "/api/v1/organizations", json={"name": "Org Patch", "asn": 64521}, headers=_auth()
    )
    assert criada.status_code == 201
    org_id = criada.json()["id"]

    off = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    repetido = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": False}, headers=_auth())
    assert repetido.status_code == 200

    renomeada = client.patch(
        f"/api/v1/organizations/{org_id}", json={"name": "Org Patch 2"}, headers=_auth()
    )
    assert renomeada.status_code == 200

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["organization.create", "organization.disable", "organization.update"]


def test_patch_admin_status_null_da_400(client: TestClient) -> None:
    criada = client.post(
        "/api/v1/organizations", json={"name": "Org Null"}, headers=_auth()
    )
    org_id = criada.json()["id"]
    resp = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": None}, headers=_auth())
    assert resp.status_code == 400


def test_downstreams_forca_kind(client: TestClient) -> None:
    criada = client.post(
        "/api/v1/downstreams",
        json={"name": "Down API", "kind": "parceiro", "asn": 64530},
        headers=_auth(),
    )
    assert criada.status_code == 201, criada.text
    assert criada.json()["kind"] == "downstream"  # ignorado o parceiro enviado

    lista = client.get("/api/v1/downstreams", headers=_auth()).json()
    assert [o["name"] for o in lista] == ["Down API"]

    # organizações comuns não aparecem no downstreams
    client.post("/api/v1/organizations", json={"name": "Parceiro X", "kind": "parceiro"}, headers=_auth())
    assert [o["name"] for o in client.get("/api/v1/downstreams", headers=_auth()).json()] == ["Down API"]


def test_cria_organizacao_com_o_documento_do_registro(client: TestClient) -> None:
    """`document` é o `ownerid` do registro: genérico, e não `cnpj`, porque
    operadora estrangeira não tem CNPJ."""
    resp = client.post(
        "/api/v1/organizations",
        json={"name": "Cliente Documento", "asn": 64530, "document": "13.172.064/0001-11"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["document"] == "13.172.064/0001-11"

    corpo = client.patch(
        f"/api/v1/organizations/{resp.json()['id']}",
        json={"document": "13.172.064/0002-22"},
        headers=_auth(),
    ).json()
    assert corpo["document"] == "13.172.064/0002-22"


# ---- prefill (design §8) ----

PREFILL = {
    "nome": "PROVEINTERLTDA-AS",
    "razao_social": "PROVEINTER LTDA",
    "documento": "13.172.064/0001-11",
    "pais": "BR",
    "as_set_sugerido": "AS-264289",
    "as_sets": ["AS-264289"],
    "blocos": [
        {"prefix": "138.121.28.0/22", "family": "ipv4", "fonte": "registro", "conflito": None},
    ],
    "fontes": {"nome": "radb", "blocos": "registro"},
    "avisos": [],
}


def _stub_prefill(monkeypatch, resultado=None, erro=None) -> None:
    """O whois nunca é chamado num teste de API: o que se testa aqui é o
    contrato da rota, e não a leitura (essa tem os testes dela)."""
    def _fake(asn: int, **kwargs):
        if erro is not None:
            raise erro
        return resultado if resultado is not None else {**PREFILL, "asn": asn}

    monkeypatch.setattr("gerenet.api.routers.organizations.identificar_asn", _fake)


def test_prefill_devolve_o_que_o_registro_deu(client: TestClient, monkeypatch) -> None:
    _stub_prefill(monkeypatch)
    resp = client.get("/api/v1/organizations/prefill?asn=264289", headers=_auth())

    assert resp.status_code == 200, resp.text
    assert resp.json()["asn"] == 264289
    assert resp.json()["documento"] == "13.172.064/0001-11"
    assert resp.json()["blocos"][0]["conflito"] is None


def test_prefill_parcial_e_200(client: TestClient, monkeypatch) -> None:
    """Identidade sem blocos (ASN estrangeiro) é resposta, não erro: confundir
    as duas faz o operador concluir que o ASN não tem dado nenhum."""
    _stub_prefill(monkeypatch, resultado={
        **PREFILL, "documento": None, "pais": None, "blocos": [],
        "avisos": ["O registro não devolveu blocos `inetnum` para AS13335 — ..."],
    })
    resp = client.get("/api/v1/organizations/prefill?asn=13335", headers=_auth())

    assert resp.status_code == 200, resp.text
    assert resp.json()["blocos"] == []
    assert resp.json()["avisos"] != []


def test_prefill_sem_nada_nas_duas_fontes_e_404(client: TestClient, monkeypatch) -> None:
    _stub_prefill(monkeypatch, resultado={
        **PREFILL, "nome": None, "razao_social": None, "documento": None,
        "pais": None, "as_set_sugerido": None, "as_sets": [], "blocos": [],
    })
    resp = client.get("/api/v1/organizations/prefill?asn=64512", headers=_auth())

    assert resp.status_code == 404
    assert "não devolveu nada" in resp.json()["detail"]


def test_prefill_com_a_consulta_fora_e_503(client: TestClient, monkeypatch) -> None:
    """503 é falha de consulta, e não ausência de dado: o operador precisa
    saber que pode tentar de novo."""
    _stub_prefill(monkeypatch, erro=IrrError("sem cache vivo"))
    resp = client.get("/api/v1/organizations/prefill?asn=64512", headers=_auth())

    assert resp.status_code == 503


def test_prefill_recusa_asn_reservado(client: TestClient) -> None:
    """64496-64511 é faixa de documentação (RFC 5398): `asn_valido` recusa."""
    resp = client.get("/api/v1/organizations/prefill?asn=64496", headers=_auth())

    assert resp.status_code == 422


def test_prefill_convive_com_a_rota_de_detalhe(client: TestClient, monkeypatch) -> None:
    """`/prefill` é declarado ANTES de `/{organization_id}`, que o capturaria
    como um id inválido — o FastAPI casa as rotas na ordem de declaração."""
    _stub_prefill(monkeypatch)

    assert client.get("/api/v1/organizations/prefill?asn=64512", headers=_auth()).status_code == 200
    assert client.get("/api/v1/organizations/999999", headers=_auth()).status_code == 404
