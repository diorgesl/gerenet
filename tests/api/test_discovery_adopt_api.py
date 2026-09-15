"""A API da adoção (design §7)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import (
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")
# Dois peers na mesma VRF, nenhum deles em subinterface: são duas propostas órfãs
# com `subinterface=None` e `vrf="VPNA"`, a identidade que o par não distingue.
_CONFIG_DUAS_ORFAS = (
    "sysname NE8000-DUAS\n"
    "#\n"
    "interface Eth-Trunk127.601\n"
    " vlan-type dot1q 601\n"
    " ip address 100.64.10.0 255.255.255.254\n"
    "#\n"
    "bgp 65001\n"
    " ipv4-family vpn-instance VPNA\n"
    "  peer 10.99.0.1 as-number 64513\n"
    "  peer 10.99.0.1 enable\n"
    "  peer 10.99.0.2 as-number 64516\n"
    "  peer 10.99.0.2 enable\n"
)


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session, tmp_path: Path, *, texto: str | None = None) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-adoc-api", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-adoc-api",
                                                 management_address="10.0.0.1", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(texto or FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return {"dev": dev, "site": site}


def _payload(ambiente) -> dict:
    """A revisão do enlace do ALFA (o vid 1001 da fixture).

    O `edge_trunk` não é enfeite: sem ele a adoção recusa a revisão (`ValidationError`)
    porque o ensaio deriva o trunk do nome da subinterface e a escrita grava o da
    revisão — o circuito nasceria sem o bloco que a conferência comparou.
    """
    return {
        "device_id": ambiente["dev"].id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-API-1001", "access_device_id": ambiente["dev"].id,
        "access_port": "GE0/0/1", "edge_trunk": "Eth-Trunk127",
        "organizacao_nova": {"name": "Cliente API", "kind": "downstream", "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": True,
    }


def test_fidelidade_sob_demanda(client, db_session, tmp_path) -> None:
    """A conferência de UMA proposta, sob demanda, com os perfis e o trunk que a
    revisão escolheu: a lista não a traz embutida, porque cada conferência roda um
    ensaio do render inteiro."""
    ambiente = _ambiente(db_session, tmp_path)
    url = (f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}"
           "&subinterface=Eth-Trunk127.1001")
    resposta = client.get(url, headers=_auth())
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["device_id"] == ambiente["dev"].id
    assert corpo["subinterface"] == "Eth-Trunk127.1001"
    assert isinstance(corpo["diferencas"], list)
    assert all({"contexto", "sobrando", "faltando", "nao_gerenciado"} <= set(d)
               for d in corpo["diferencas"])
    # A lista vazia é o outro jeito de este teste passar sem conferir nada: é a
    # descrição da subinterface do ALFA que diz que a proposta comparada é a 1001.
    assert {"peer", "subinterface"} <= {d["contexto"] for d in corpo["diferencas"]}
    sub = next(d for d in corpo["diferencas"] if d["contexto"] == "subinterface")
    assert any("description CLIENTE-ALFA" in linha for linha in sub["nao_gerenciado"])
    # O gate do aceite viaja na resposta: é ele que a tela usa para exigir o ciente.
    assert any(d["exige_ciente"] for d in corpo["diferencas"])

    # Sem o trunk a conferência deriva o da subinterface (o diff acima sai limpo no
    # contexto da interface); com OUTRO trunk o bloco que nasceria é outro, e a
    # diferença tem de aparecer. É o parâmetro que a tela manda junto da revisão.
    revisado = client.get(f"{url}&edge_trunk=Eth-Trunk9", headers=_auth()).json()
    sub9 = next(d for d in revisado["diferencas"] if d["contexto"] == "subinterface")
    assert sub9["exige_ciente"] is True
    assert sub["exige_ciente"] is False

    # Sem perfil nenhum o ensaio não emite o corpo da política de exportação; com o
    # produto que o operador escolheu na tela, o corpo entra na comparação — e a
    # consulta leva os perfis justamente para a conferência valer sobre eles.
    assert "definicao" not in {d["contexto"] for d in corpo["diferencas"]}
    full = db_session.scalar(select(models.PolicyProfile).where(
        models.PolicyProfile.name == "full", models.PolicyProfile.direction == "export"))
    com_perfil = client.get(f"{url}&export_ipv4={full.id}", headers=_auth()).json()
    definicao = next(d for d in com_perfil["diferencas"] if d["contexto"] == "definicao")
    assert any("RP-64512-EXPORT-V4" in linha for linha in definicao["sobrando"])
    assert definicao["exige_ciente"] is True


def test_a_lista_traz_os_internos_e_a_idade_da_coleta(client, db_session, tmp_path) -> None:
    """Os dois campos novos da listagem, preenchidos: com o schema de um lado e a
    rota do outro, um campo que ninguém preenche chega vazio para sempre — e o
    resto da suíte continuaria verde."""
    ambiente = _ambiente(db_session, tmp_path)
    resposta = client.get(f"/api/v1/discovery?device_id={ambiente['dev'].id}", headers=_auth())
    assert resposta.status_code == 200
    corpo = resposta.json()
    # O peer iBGP da fixture (`RR-INTERNO`) não tem proposta: fora do `propostas`.
    assert [c["remote_address"] for c in corpo["internos"]] == ["10.0.0.9"]
    assert corpo["internos"][0]["classificacao"] == "interno"
    # A idade do texto lido, que a Task 3 fez o motor calcular para o operador.
    assert corpo["snapshot_age_seconds"] is not None
    assert corpo["snapshot_age_seconds"] >= 0


def test_adota_e_devolve_o_circuito(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    resposta = client.post("/api/v1/discovery/adopt", json=_payload(ambiente), headers=_auth())
    assert resposta.status_code == 201, resposta.text
    circ_id = resposta.json()["circuit_id"]
    assert db_session.get(models.Circuit, circ_id).code == "ADOC-API-1001"


def test_proposta_com_conflito_e_409(client, db_session, tmp_path) -> None:
    """A proposta da VRF é a única da fixture com conflito (`nao_adotavel`): o
    router traduz o `ConflictError` do serviço, em vez de deixá-lo virar 500."""
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["subinterface"] = None
    corpo["vrf"] = "VPNA"
    resposta = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert resposta.status_code == 409
    # A mensagem é do domínio: sem ela o teste passaria com qualquer 409, inclusive
    # um que recusasse a proposta certa pelo motivo errado.
    assert "conflito" in resposta.json()["detail"]
    assert db_session.query(models.Circuit).count() == 0


def test_sem_ciente_onde_exige_e_422(client, db_session, tmp_path) -> None:
    """A proposta da fixture tem diferença de política, que muda o equipamento."""
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["ciente"] = False
    resposta = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert resposta.status_code == 422
    # A revisão sem trunk também é 422, e é antes desta guarda: sem o motivo na
    # asserção o teste passaria recusando pelo trunk, não pelo ciente.
    assert "ciente" in resposta.json()["detail"]
    assert db_session.query(models.Circuit).count() == 0


def test_proposta_inexistente_e_404(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["subinterface"] = "Eth-Trunk127.9999"
    resposta = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert resposta.status_code == 404
    # A rota ausente também devolve 404 (`{"detail": "Not Found"}`): a mensagem é
    # o que separa "não achei a proposta" do caminho que ainda não existe.
    assert "não encontrada" in resposta.json()["detail"]


def test_identidade_ambigua_e_409(client, db_session, tmp_path) -> None:
    """Duas propostas sem subinterface na mesma VRF: o par (subinterface, VRF) não
    diz qual delas é a revisada.

    A órfã é o peer em sub-rede compartilhada ou alcançado por rota, e o NE8000
    real tem dezenas delas; escolher a primeira das duas entregaria o diff de um
    peer e o conflito de outro, com a cara do que o operador abriu.
    """
    ambiente = _ambiente(db_session, tmp_path, texto=_CONFIG_DUAS_ORFAS)
    lista = client.get(f"/api/v1/discovery?device_id={ambiente['dev'].id}",
                       headers=_auth()).json()
    # A premissa do teste, na resposta da lista: as duas órfãs da mesma VRF.
    assert [p["subinterface"] for p in lista["propostas"]
            if p["vrf"] == "VPNA"] == [None, None]

    diff = client.get(f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}&vrf=VPNA",
                      headers=_auth())
    assert diff.status_code == 409
    assert "ambígua" in diff.json()["detail"]

    corpo = _payload(ambiente)
    corpo["subinterface"] = None
    corpo["vrf"] = "VPNA"
    adotar = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert adotar.status_code == 409
    assert "ambígua" in adotar.json()["detail"]
    assert db_session.query(models.Circuit).count() == 0


def test_sem_coleta_o_404_diz_o_motivo(client, db_session) -> None:
    """Sem coleta com a configuração não há proposta nenhuma, e o 404 dizia que
    alguém tinha adotado antes: afirmava o que não aconteceu."""
    site = create_site(db_session, SiteCreate(name="pop-adoc-sem-coleta"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-adoc-sem-coleta",
                                                 management_address="10.0.0.8", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")

    resposta = client.post("/api/v1/discovery/adopt", json=_payload({"dev": dev}),
                           headers=_auth())
    assert resposta.status_code == 404
    assert "coleta" in resposta.json()["detail"]
    assert "adotada" not in resposta.json()["detail"]

    diff = client.get(f"/api/v1/discovery/fidelidade?device_id={dev.id}"
                      "&subinterface=Eth-Trunk127.1001", headers=_auth())
    assert diff.status_code == 404
    assert "coleta" in diff.json()["detail"]


def test_erro_de_dominio_na_conferencia_e_404(client, db_session, tmp_path, monkeypatch) -> None:
    """O `try` do GET cobre a conferência inteira, e não só a busca: o ensaio lê o
    equipamento de dentro dela, e o equipamento apagado entre a listagem e o
    render viraria 500.

    A corrida não se reproduz de dentro do teste, então o que se fixa aqui é a
    conversão (mesmo desenho do `test_conflito_ao_ignorar_e_409`): o serviço
    levanta o erro de domínio e o router é quem o traduz.
    """
    from gerenet.domain.services.errors import NotFoundError

    ambiente = _ambiente(db_session, tmp_path)

    def _estoura(*args, **kwargs):
        raise NotFoundError("O equipamento não existe mais.")

    monkeypatch.setattr("gerenet.api.routers.discovery.conferir_fidelidade", _estoura)
    resposta = client.get(
        f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}"
        "&subinterface=Eth-Trunk127.1001",
        headers=_auth(),
    )
    assert resposta.status_code == 404
    assert "não existe mais" in resposta.json()["detail"]


def test_adopt_grava_as_autorizacoes_do_registro(client: TestClient, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["autorizacoes"] = [{"prefix": "138.121.28.0/22", "family": "ipv4"}]

    resp = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())

    assert resp.status_code == 201, resp.text
    auths = db_session.scalars(select(models.BgpPrefixAuthorization)).all()
    assert [(a.prefix, a.origin, a.validacao) for a in auths] == [
        ("138.121.28.0/22", "registro", None)
    ]


def test_adopt_recusa_bloco_conflitante(client: TestClient, db_session, tmp_path) -> None:
    outra = create_organization(
        db_session, OrganizationCreate(name="Cliente Beta", asn=64513), actor="cli"
    )
    create_authorization(db_session, PrefixAuthorizationCreate(
        organization_id=outra.id, family="ipv4", prefix="138.121.28.0/24"), actor="cli")
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["autorizacoes"] = [{"prefix": "138.121.28.0/22", "family": "ipv4"}]

    resp = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())

    assert resp.status_code == 409
    assert "Cliente Beta" in resp.json()["detail"]
