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
    """A conferência de UMA proposta, sob demanda, com os parâmetros que a revisão
    escolheu: a lista não a traz embutida, porque cada conferência roda um ensaio
    do render inteiro."""
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
    # A descrição passou a ser gerenciada (§7), então ela aparece nos DOIS lados
    # quando o ensaio vai sem identidade: a do `ENSAIO-...` sobra no render e a do
    # equipamento falta nele. É essa diferença que exige o ciente.
    assert any("description CLIENTE-ALFA" in linha for linha in sub["faltando"])
    assert any("description ENSAIO-" in linha for linha in sub["sobrando"])
    # O grupo que não gateia é só o `mtu` desde a frente da velocidade, e esta
    # subinterface não tem nenhum: ele sai vazio, e não com a descrição dentro.
    assert sub["nao_gerenciado"] == []
    # O gate do aceite viaja na resposta: é ele que a tela usa para exigir o ciente.
    assert any(d["exige_ciente"] for d in corpo["diferencas"])

    # Sem o trunk a conferência deriva o da subinterface, e o nome do bloco bate
    # dos dois lados; com OUTRO trunk o bloco que nasceria é outro, e o nome
    # divergente aparece dos dois lados. É o parâmetro que a tela manda junto.
    revisado = client.get(f"{url}&edge_trunk=Eth-Trunk9", headers=_auth()).json()
    sub9 = next(d for d in revisado["diferencas"] if d["contexto"] == "subinterface")
    assert "interface Eth-Trunk9.1001" in sub9["sobrando"]
    assert "interface Eth-Trunk127.1001" in sub9["faltando"]
    assert "interface Eth-Trunk127.1001" not in sub["sobrando"] + sub["faltando"]

    # A velocidade da revisão entra na conta do QoS (§5): o equipamento tem
    # `qos car cir 1024000` nas duas direções (a fixture os traz) e o ensaio sem
    # ela não emite taxa nenhuma. Com ela, a dobra do `equivalencia_vrp` casa a
    # forma curta do render com a longa do VRP e as duas somem do diff.
    assert "qos car cir 1024000 inbound" in sub["faltando"]
    com_taxa = client.get(f"{url}&velocidade_mbps=1024", headers=_auth()).json()
    sub_taxa = next(d for d in com_taxa["diferencas"] if d["contexto"] == "subinterface")
    assert not any("qos car" in linha
                   for linha in sub_taxa["sobrando"] + sub_taxa["faltando"])

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


def test_fidelidade_leva_a_identidade_da_revisao(client, db_session, tmp_path) -> None:
    """O resto da identidade que o GET carrega: o código, a organização escolhida
    na lista e o nome da organização nova.

    Cada um deles muda a `description` que o ensaio emite (§4), e é por isso que
    a conferência os recebe: a rota que perdesse um deles devolveria a descrição
    do `ENSAIO-...` — a comparação de um circuito que a revisão não vai gravar.
    (`edge_trunk` e `velocidade_mbps` já estão no `test_fidelidade_sob_demanda`.)
    """
    ambiente = _ambiente(db_session, tmp_path)
    org = create_organization(
        db_session, OrganizationCreate(name="Org Da Rota", asn=64999), actor="cli"
    )
    url = (f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}"
           "&subinterface=Eth-Trunk127.1001")

    def _sub(query: str) -> dict:
        corpo = client.get(f"{url}{query}", headers=_auth()).json()
        return next(d for d in corpo["diferencas"] if d["contexto"] == "subinterface")

    # Sem parâmetro nenhum o ensaio monta o circuito descartável, e a descrição
    # sai do `ENSAIO-...`: é a referência das três asserções seguintes.
    assert any("description ENSAIO-" in linha for linha in _sub("")["sobrando"])

    # O código da revisão nomeia a descrição...
    com_codigo = _sub("&circuit_code=ADOC-API-1001")
    assert any("description ADOC-API-1001 ENSAIO-" in linha
               for linha in com_codigo["sobrando"])
    # ...e o nome da organização nova entra com ele.
    com_nome = _sub("&circuit_code=ADOC-API-1001&organizacao_nome=Cliente API")
    assert any("description ADOC-API-1001 CLIENTE API" in linha
               for linha in com_nome["sobrando"])

    # A organização JÁ cadastrada entra por id e o nome dela é o que o render
    # escreve: é o caminho de quem escolhe na lista da tela.
    com_org = _sub(f"&circuit_code=ADOC-API-1001&organizacao_id={org.id}")
    assert any("description ADOC-API-1001 ORG DA ROTA" in linha
               for linha in com_org["sobrando"])


def test_fidelidade_leva_os_blocos_da_revisao(client, db_session, tmp_path) -> None:
    """Os blocos marcados na revisão chegam à conferência pela query, um por
    entrada, na forma `família:prefixo` (item 14).

    É a autorização da organização que faz o `_bloco_import` emitir o filtro e a
    route-policy (§6.4): sem os blocos, o ensaio renderiza um peer SEM o
    `import route-policy` que o equipamento tem, e a prévia ao vivo acusa como
    faltando a linha que a própria adoção escreve — a tela pedia `ciente` por
    uma diferença que ela cria. A adoção já mandava os blocos (o POST os tem
    desde a Task 7); o que faltava era o GET.

    A sonda que expôs o problema fica registrada no relatório: a assinatura
    `list[str] | None = None`, sem `Annotated[... Query()]`, chega sempre vazia
    nesta versão do FastAPI, e a conferência seguiria sem os blocos sem nada
    acusar.
    """
    ambiente = _ambiente(db_session, tmp_path)
    url = (f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}"
           "&subinterface=Eth-Trunk127.1001"
           "&circuit_code=ADOC-API-1001&organizacao_nome=Cliente API")

    def _corpo(query: str) -> dict:
        resposta = client.get(f"{url}{query}", headers=_auth())
        assert resposta.status_code == 200, resposta.text
        return resposta.json()

    def _linhas_de_peer(corpo: dict) -> set[str]:
        return {linha for d in corpo["diferencas"] if d["contexto"] == "peer"
                for linha in d["sobrando"] + d["faltando"]}

    # A linha do RENDER é o que o ensaio ganha com o bloco: sem autorização
    # nenhuma o laço do `_bloco_import` não tem o que emitir, e o peer sai sem o
    # filtro de importação que a adoção cria. A asserção é sobre a grafia do
    # render (`bgp_peer.j2` escreve `import route-policy`) e não sobre a da
    # fixture de propósito — veja a nota das duas grafias no fim do teste.
    importacao = "peer 100.64.10.1 import route-policy RP-64512-IMPORT-V4"

    def _contextos(corpo: dict) -> set[str]:
        return {d["contexto"] for d in corpo["diferencas"]}

    sem_blocos = _corpo("")
    assert importacao not in _linhas_de_peer(sem_blocos)
    # O outro lado da mesma ausência: sem autorização não há definição nenhuma
    # para a sessão referenciar, e o contexto `definicao` não existe.
    assert "definicao" not in _contextos(sem_blocos)

    com_bloco = _corpo("&autorizacoes=ipv4:138.121.28.0/22")
    assert importacao in _linhas_de_peer(com_bloco)
    # E o que a linha referencia entra na conferência junto: o corpo da
    # prefix-list e o da route-policy, que é o que distingue o produto que a
    # revisão escolheu (§6.5) — sem os blocos, os dois ficariam de fora.
    definicoes = [d for d in com_bloco["diferencas"] if d["contexto"] == "definicao"]
    assert any("route-policy RP-64512-IMPORT-V4 permit node 10" in linha
               for d in definicoes for linha in d["sobrando"])

    # O prefixo de IPv6 é cheio de dois-pontos e o corte é no PRIMEIRO: a família
    # sai de antes dele e o resto é o prefixo. Cortar no último daria 422, e o
    # nome do filtro na saída é o que prova qual família o render leu.
    v6 = _corpo("&autorizacoes=ipv6:2804:2594::/32")
    assert any("IP-PFX-64512-IN-V6 index 10 permit 2804:2594::/32" in linha
               for d in v6["diferencas"] for linha in d["sobrando"])

    # Nota das duas grafias, para o vermelho futuro não enganar: a fixture lê a
    # forma CLÁSSICA (`peer X route-policy N import`) e o render escreve a outra
    # (`peer X import route-policy N`), então a linha do equipamento continua em
    # `faltando` mesmo com o bloco marcado — o mesmo laço de sempre casando duas
    # grafias do mesmo comando. É a assunção 7 do checklist do
    # `docs/runbook-validacao-ne8000.md`, ainda sem captura real que a confirme, e
    # por isso ela é dívida registrada, não conserto deste item: aqui só entra o
    # que o item move, que é o ensaio passar a emitir a linha e as definições.

    # Fora da forma é 422 desta rota: um bloco torto não tem o que fazer no
    # ensaio, e deixá-lo virar diferença acusaria o operador por um erro que é da
    # própria tela.
    for torto in ("ipv4", "v4:138.121.28.0/22", "ipv4:"):
        recusa = client.get(f"{url}&autorizacoes={torto}", headers=_auth())
        assert recusa.status_code == 422, torto
        assert "família" in recusa.json()["detail"]


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


def test_chave_desconhecida_na_revisao_e_422(client, db_session, tmp_path) -> None:
    """A chave digitada errado no `--json` do CLI não some calada.

    O corpo da adoção vem de um arquivo escrito à mão: com o `extra="ignore"`
    do Pydantic v2 o `documment` era descartado e a API respondia 201 — o
    operador acreditava que o CNPJ entrou. O 422 chega na validação do corpo,
    antes do serviço, então nada é gravado; e o mesmo payload com as chaves
    certas segue, porque a recusa é da chave, não do corpo.
    """
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)

    # Na raiz da revisão.
    corpo["documment"] = "12.345.678/0001-99"
    extra = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert extra.status_code == 422
    assert "documment" in extra.text  # o 422 nomeia a chave que sobrou
    del corpo["documment"]

    # E nos dois filhos: o config é por modelo, e um payload torto de `sessoes`
    # ou `autorizacoes` passaria calado se só o pai o tivesse.
    corpo["sessoes"] = [{"afi": "ipv4", "perfil_import": 1}]
    assert client.post("/api/v1/discovery/adopt", json=corpo,
                       headers=_auth()).status_code == 422
    corpo["sessoes"] = [{"afi": "ipv4"}, {"afi": "ipv6"}]

    corpo["autorizacoes"] = [{"prefix": "138.121.28.0/22", "famly": "ipv4"}]
    assert client.post("/api/v1/discovery/adopt", json=corpo,
                       headers=_auth()).status_code == 422
    corpo["autorizacoes"] = []

    assert db_session.query(models.Circuit).count() == 0  # nenhuma recusa gravou
    ok = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert ok.status_code == 201, ok.text


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
