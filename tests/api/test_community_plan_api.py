"""API do plano de communities (spec §13): consulta, validação e adoção."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _device_com_snapshot(nome: str, fixture: str, *, recursos: dict | None = None) -> int:
    from gerenet.db import SessionLocal

    with SessionLocal() as session:
        device = create_device(
            session, DeviceCreate(name=nome, management_address="10.0.0.8", asn=61785), actor="teste"
        )
        session.add(
            models.DeviceSnapshot(
                device_id=device.id, status="success",
                # O caminho da fixture, não o texto dela: é o caminho que o
                # snapshot guarda e o leitor lê o arquivo do disco a partir dele
                # (a convenção da casa — `tests/api/test_discovery_api.py:37`).
                raw_files={"config_backup": [str(FIXTURES / fixture)]},
                resources=recursos,
            )
        )
        session.commit()
        return device.id


def _device_com_config(tmp_path: Path, nome: str, texto: str, *, asn: int | None) -> int:
    """Equipamento com a coleta de um texto de configuração qualquer.

    Existe para os casos que fixture nenhuma cobre: o plano de outro ASN
    principal (409) e o equipamento sem ASN (422).
    """
    from gerenet.db import SessionLocal

    arquivo = tmp_path / f"{nome}.txt"
    arquivo.write_text(texto, encoding="utf-8")
    with SessionLocal() as session:
        device = create_device(
            session,
            DeviceCreate(name=nome, management_address="10.0.0.9", asn=asn),
            actor="teste",
        )
        session.add(
            models.DeviceSnapshot(
                device_id=device.id, status="success",
                raw_files={"config_backup": [str(arquivo)]},
            )
        )
        session.commit()
        return device.id


def _adotar(client: TestClient, device_id: int):
    return client.post(
        "/api/v1/communities/plan/adopt", json={"device_id": device_id}, headers=_auth()
    )


def test_plano_vazio_devolve_200_sem_blocos(client: TestClient) -> None:
    resposta = client.get("/api/v1/communities/plan", headers=_auth())
    assert resposta.status_code == 200
    assert resposta.json()["classes"] == []
    assert resposta.json()["asn_principal"] is None


def test_posso_adotar_e_depois_consultar(client: TestClient) -> None:
    device_id = _device_com_snapshot("ne-api-plano-01", "comunidades_edge.txt")
    adocao = client.post(
        "/api/v1/communities/plan/adopt", json={"device_id": device_id}, headers=_auth()
    )
    assert adocao.status_code == 201
    assert adocao.json()["asn_principal"] == 61785
    assert adocao.json()["classes"] > 0

    consulta = client.get("/api/v1/communities/plan", headers=_auth()).json()
    assert consulta["asn_principal"] == 61785
    nomes = {c["nome"] for c in consulta["classes"]}
    assert "com-TRANSITO-FULL" in nomes


def test_equipamento_sem_coleta_e_404(client: TestClient) -> None:
    from gerenet.db import SessionLocal

    with SessionLocal() as session:
        device = create_device(
            session, DeviceCreate(name="ne-api-plano-02", management_address="10.0.0.7", asn=61785),
            actor="teste",
        )
        device_id = device.id
    resposta = client.post(
        "/api/v1/communities/plan/adopt", json={"device_id": device_id}, headers=_auth()
    )
    assert resposta.status_code == 404


def test_validacao_devolve_os_achados(client: TestClient) -> None:
    device_id = _device_com_snapshot("ne-api-plano-03", "comunidades_edge.txt")
    client.post("/api/v1/communities/plan/adopt", json={"device_id": device_id}, headers=_auth())

    resposta = client.get(
        f"/api/v1/communities/plan/validacao?device_id={device_id}", headers=_auth()
    )
    assert resposta.status_code == 200
    codigos = {a["codigo"] for a in resposta.json()}
    assert "classe_aplicada_nao_testada" in codigos


def test_aplicam_e_testam_saem_da_leitura(client: TestClient) -> None:
    """O "quem aplica" da página é o mesmo que a validação considera aplicado (§11).

    No recorte da borda a classe `com-TECMAIS-v4` é aplicada por **corpus**
    (`apply community com-EXPORT-UPSTREAM-v4 additive`, cujo corpo é o
    `61785:3001`): sem resolver o corpus, a tabela de classes diria "ninguém" e a
    validação — que resolve — acusaria `CUSTOMER-BGP-v4` aplicando a mesma
    classe. As duas superfícies se contradiriam sobre o mesmo plano.
    """
    device_id = _device_com_snapshot("ne-api-plano-04", "comunidades_edge.txt")
    assert _adotar(client, device_id).status_code == 201

    consulta = client.get("/api/v1/communities/plan", headers=_auth()).json()
    classes = {c["nome"]: c for c in consulta["classes"]}
    tecmais = classes["com-TECMAIS-v4"]
    assert tecmais["aplicam"] == ["CUSTOMER-BGP-v4"]
    assert tecmais["testam"] == ["RouteExportCheck", "RouteExportCheckV6"]
    # A classe que só é citada (`if-match community-filter com-TRANSITO-FULL`)
    # não é aplicada nem testada por ninguém: a citação não é uso.
    assert classes["com-TRANSITO-FULL"]["aplicam"] == []
    assert classes["com-TRANSITO-FULL"]["testam"] == []


def test_plano_de_outro_asn_principal_e_409(client: TestClient, tmp_path: Path) -> None:
    """R28: os filhos não têm recorte por plano ativo, então substituir recusa."""
    primeiro = _device_com_snapshot("ne-api-plano-05", "comunidades_edge.txt")
    assert _adotar(client, primeiro).status_code == 201

    outro = _device_com_config(
        tmp_path, "ne-api-plano-06",
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n"
        "bgp 65001\n",
        asn=65001,
    )
    resposta = _adotar(client, outro)
    assert resposta.status_code == 409

    # A recusa é antes de qualquer escrita: o plano ativo continua o primeiro.
    assert client.get("/api/v1/communities/plan", headers=_auth()).json()["asn_principal"] == 61785


def test_equipamento_sem_asn_e_422(client: TestClient, tmp_path: Path) -> None:
    """R31: sem ASN principal o cabeçalho do plano não tem o que gravar.

    O equipamento não tem `devices.asn` e a configuração não declara `bgp <asn>`,
    então a proposta sai sem ASN principal — e o `ValidationError` do serviço
    vira 422 antes de qualquer escrita (o `INSERT` do cabeçalho estouraria o
    NOT NULL do banco).
    """
    device_id = _device_com_config(
        tmp_path, "ne-api-plano-07",
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n",
        asn=None,
    )
    resposta = _adotar(client, device_id)
    assert resposta.status_code == 422


def test_sem_api_key_e_401(client: TestClient) -> None:
    assert client.get("/api/v1/communities/plan").status_code == 401


def test_alvo_estabelecido_sai_com_estado_e_nao_para(client: TestClient) -> None:
    """O `bgp_peers` da coleta é o que dá estado ao alvo, e o que o tira de `parados`.

    Sem o recurso, todo alvo é `ausente` para a leitura e a poda do §9.3 leva
    todos: o `GET /plan` sai sem alvo nenhum. Com o recurso, o alvo de pé entra
    no plano com o estado coletado (`estado` do `AlvoPlanoOut`) e só quem a
    coleta não viu é que para.
    """
    device_id = _device_com_snapshot(
        "ne-api-plano-08", "comunidades_edge.txt",
        recursos={"bgp_peers": [{"peer": "100.127.190.5", "estado": "established"}]},
    )
    adocao = _adotar(client, device_id)
    assert adocao.status_code == 201
    assert adocao.json()["parados"] == ["MSD-CDN-v4"]

    consulta = client.get("/api/v1/communities/plan", headers=_auth()).json()
    alvos = {a["nome"]: a for a in consulta["alvos"]}
    assert alvos["PARCEIROS_CDN"]["estado"] == "established"
    # O alvo sem membro conhecido na coleta não chega a ser gravado (§9.3).
    assert "MSD-CDN-v4" not in alvos


def test_readocao_de_mesmo_asn_conta_o_plano_em_vigor(
    client: TestClient, tmp_path: Path
) -> None:
    """R40: o `201` descreve o plano em vigor e diz se gravou.

    Readotar o plano de **outro** equipamento com o mesmo ASN principal não
    escreve nada (o serviço devolve o existente). Se o corpo contasse a proposta
    do equipamento B, a página leria os números de uma proposta contra um plano
    que continua o de antes, sem saber que nada foi gravado.
    """
    primeiro = _device_com_snapshot("ne-api-plano-09", "comunidades_edge.txt")
    primeira = _adotar(client, primeiro)
    assert primeira.status_code == 201
    corpo_a = primeira.json()

    outro = _device_com_config(
        tmp_path, "ne-api-plano-10",
        "ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010\n"
        "ip community-filter advanced com-AS8167 index 10 permit 61785:8167\n"
        "bgp 61785\n",
        asn=61785,
    )
    segunda = _adotar(client, outro)
    assert segunda.status_code == 201
    corpo_b = segunda.json()

    # Os três números são os do plano em vigor, iguais aos da primeira adoção:
    # a proposta B tem menos classes, nenhum portão e nenhum alvo.
    for campo in ("classes", "portoes", "alvos"):
        assert corpo_b[campo] == corpo_a[campo]
    consulta = client.get("/api/v1/communities/plan", headers=_auth()).json()
    assert corpo_b["classes"] == len(consulta["classes"])
    assert corpo_b["portoes"] == len(consulta["portoes"])
    assert corpo_b["alvos"] == len(consulta["alvos"])

    # Quem diz se houve escrita é o `ja_existia`: a primeira gravou, a segunda
    # devolveu o plano que já estava (mesmo ASN principal não transiciona nada).
    assert corpo_a["ja_existia"] is False
    assert corpo_b["ja_existia"] is True
    assert corpo_b["plano_id"] == corpo_a["plano_id"]

    # Já as divergências e os parados descrevem a configuração **deste**
    # equipamento, e não a escrita: o B não tem portão nem alvo nenhum.
    assert corpo_b["divergencias"] == []
    assert corpo_b["parados"] == []
    assert corpo_a["divergencias"] != []
