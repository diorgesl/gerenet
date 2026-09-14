"""API da descoberta (spec §13). Somente leitura, mais a lista de ignorados."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session, tmp_path: Path) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-desc-api",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc-api",
                                                 management_address="10.0.0.1", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return {"dev": dev, "site": site}


def test_lista_propostas(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    resposta = client.get(f"/api/v1/discovery?device_id={ambiente['dev'].id}", headers=_auth())
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["device_id"] == ambiente["dev"].id
    assert corpo["aviso"] is None
    # A fixture tem também o peer da `vpn-instance VPNA`, que não tem enlace:
    # ele vem como proposta órfã (`vid=None`) e não cabe no índice por VID.
    orfa = next(p for p in corpo["propostas"] if p["vid"] is None)
    assert orfa["vrf"] == "VPNA"
    assert orfa["veredito"] == "nao_adotavel"
    por_vid = {p["vid"]: p for p in corpo["propostas"] if p["vid"] is not None}
    assert set(por_vid) == {1001, 2001, 3001}
    alfa = por_vid[1001]
    assert alfa["veredito"] == "adotavel_com_pendencias"
    assert alfa["stack"] == "dual"
    assert alfa["qinq"] is False  # o enlace da fixture não é empilhado
    assert {p["tipo"] for p in alfa["pendencias"]} >= {
        "organizacao_ausente", "acesso_desconhecido", "senha_nao_legivel",
    }
    assert alfa["organizacao_sugerida"] == "CLIENTE-ALFA"


def test_device_sem_coleta_devolve_aviso(client, db_session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-sem-coleta"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-sem-coleta",
                                                 management_address="10.0.0.9", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    resposta = client.get(f"/api/v1/discovery?device_id={dev.id}", headers=_auth())
    assert resposta.status_code == 200
    assert resposta.json()["aviso"] is not None
    assert resposta.json()["propostas"] == []


def test_device_inexistente_e_404(client) -> None:
    resposta = client.get("/api/v1/discovery?device_id=9999", headers=_auth())
    assert resposta.status_code == 404
    # A mensagem é do domínio: sem ela o teste passaria também com a rota
    # ausente (o 404 genérico do roteador), que é o estado anterior à API.
    assert "Equipamento 9999" in resposta.json()["detail"]
    assert client.get("/api/v1/discovery/ignore?device_id=9999",
                      headers=_auth()).status_code == 404


def test_escrita_com_equipamento_inexistente_e_404(client) -> None:
    """Os dois caminhos de escrita conferem o equipamento antes de escrever —
    e é o router que converte `NotFoundError` (o app não tem handler dos erros
    de domínio): sem a conversão isto seria um 500, não um 404."""
    corpo = {"device_id": 9999, "afi": "ipv4", "remote_address": "100.64.10.3"}
    assert client.post("/api/v1/discovery/ignore", json=corpo,
                       headers=_auth()).status_code == 404
    assert client.delete(
        "/api/v1/discovery/ignore?device_id=9999&afi=ipv4&remote_address=100.64.10.3",
        headers=_auth(),
    ).status_code == 404


def test_familia_invalida_e_422(client, db_session, tmp_path) -> None:
    """`afi` fora de ipv4/ipv6 é recusado antes de chegar ao Postgres: a coluna
    é um enum, e o valor inválido voltaria como `DataError` — um 500 nos dois
    caminhos de escrita, com a sessão quebrada."""
    ambiente = _ambiente(db_session, tmp_path)
    dev_id = ambiente["dev"].id
    assert client.post("/api/v1/discovery/ignore", headers=_auth(), json={
        "device_id": dev_id, "afi": "lixo", "remote_address": "100.64.10.3",
    }).status_code == 422
    assert client.delete(
        f"/api/v1/discovery/ignore?device_id={dev_id}&afi=lixo&remote_address=100.64.10.3",
        headers=_auth(),
    ).status_code == 422


def test_conflito_ao_ignorar_e_409(client, db_session, tmp_path, monkeypatch) -> None:
    """A corrida que o `get_device` não pega (equipamento apagado entre a
    conferência e o insert) chega ao cliente como 409, e não como 500.

    A corrida não se reproduz de dentro do teste, então o que se fixa aqui é a
    conversão do router: o serviço levanta `ConflictError` e o router é quem o
    traduz (mesmo desenho de `sites.py`), do mesmo jeito que o
    `test_collect_202_tem_job_id` fixa o contrato do 202 com um stub.
    """
    from gerenet.domain.services.errors import ConflictError

    ambiente = _ambiente(db_session, tmp_path)

    def _estoura(*args, **kwargs):
        raise ConflictError("O equipamento não existe mais.")

    monkeypatch.setattr("gerenet.api.routers.discovery.ignorar_candidato", _estoura)
    resposta = client.post("/api/v1/discovery/ignore", headers=_auth(), json={
        "device_id": ambiente["dev"].id, "afi": "ipv4", "remote_address": "100.64.10.3",
    })
    assert resposta.status_code == 409
    assert "não existe mais" in resposta.json()["detail"]


def test_sem_autenticacao_e_401(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    assert client.get(f"/api/v1/discovery?device_id={ambiente['dev'].id}").status_code == 401


def test_ignorar_esquecer_e_relistar(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    dev_id = ambiente["dev"].id
    corpo = {"device_id": dev_id, "afi": "ipv4", "remote_address": "100.64.10.3",
             "motivo": "trânsito já cadastrado"}
    criado = client.post("/api/v1/discovery/ignore", json=corpo, headers=_auth())
    assert criado.status_code == 201
    assert criado.json()["autor"] == "api"

    listados = client.get(f"/api/v1/discovery/ignore?device_id={dev_id}", headers=_auth()).json()
    assert [i["remote_address"] for i in listados] == ["100.64.10.3"]

    sem_ele = client.get(f"/api/v1/discovery?device_id={dev_id}", headers=_auth()).json()
    assert "100.64.10.3" not in {s["remote_address"] for p in sem_ele["propostas"]
                                 for s in p["candidatos"]}

    apagado = client.delete(
        f"/api/v1/discovery/ignore?device_id={dev_id}&afi=ipv4&remote_address=100.64.10.3",
        headers=_auth(),
    )
    assert apagado.status_code == 204
    assert client.get(f"/api/v1/discovery/ignore?device_id={dev_id}",
                      headers=_auth()).json() == []
