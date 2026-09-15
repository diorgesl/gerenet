"""CLI da descoberta (§13 do design)."""
import json
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from gerenet.cli.main import app as cli_app
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import listar_ignorados
from gerenet.domain.services.errors import ConflictError
from gerenet.domain.services.sites import create_site, link_device

runner = CliRunner()
FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _ambiente(db_session, tmp_path: Path) -> models.Device:
    site = create_site(db_session, SiteCreate(name="pop-desc-cli",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc-cli",
                                                 management_address="10.0.0.1", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return dev


def test_list_mostra_veredito_e_classificacao(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "1001" in r.output
    assert "adotavel_com_pendencias" in r.output
    assert "100.64.10.1" in r.output
    assert "interno" in r.output  # o peer com o próprio ASN aparece na lista separada


def test_show_detalha_pendencias_e_conflitos(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "100.64.10.1"])
    assert r.exit_code == 0, r.output
    assert "organizacao_ausente" in r.output
    assert "senha_nao_legivel" in r.output
    # A descrição da subinterface deixou de ser "não gerenciada": a SoT passou a
    # emiti-la (§4), então o que o equipamento tem de diferente é diferença de
    # verdade — ela continua na tela, agora no bloco das que exigem ciente.
    assert "falta no render: description CLIENTE-ALFA" in r.output


def test_show_imprime_a_explicacao_do_ensaio(db_session, tmp_path) -> None:
    """O que o operador vem buscar no `show` é por que a adoção está barrada: a
    explicação do `ensaio` mora fora de `sobrando`/`faltando` (§6 do design) e
    tem de sair na tela — sem ela sobrava o cabeçalho do contexto e nada mais.

    A asserção é pela frase que só a explicação tem: o conflito
    `vrf_nao_renderizavel` da proposta cita a mesma VRF e a mesma instância, e
    uma asserção por "VPNA" passaria sem o bloco da fidelidade."""
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "10.99.0.1"])
    assert r.exit_code == 0, r.output
    assert "fidelidade ensaio:" in r.output
    assert "a comparação não é confiável para uma sessão em VRF" in r.output


def test_ignore_e_unignore(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, [
        "discovery", "ignore", dev.name, "100.64.10.4", "--motivo", "cliente saiu",
    ])
    assert r.exit_code == 0, r.output
    assert "100.64.10.4" not in runner.invoke(cli_app, ["discovery", "list", dev.name]).output

    r = runner.invoke(cli_app, ["discovery", "unignore", dev.name, "100.64.10.4"])
    assert r.exit_code == 0, r.output
    assert "100.64.10.4" in runner.invoke(cli_app, ["discovery", "list", dev.name]).output


def test_unignore_acha_o_endereco_em_outra_caixa(db_session, tmp_path) -> None:
    """O IPv6 vem do equipamento em maiúsculas e o operador digita minúsculo: é
    o mesmo peer, e o `unignore` tem de tirá-lo da lista de verdade."""
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, [
        "discovery", "ignore", dev.name, "2804:194C:1000::1100:73:2", "--afi", "ipv6",
    ])
    assert r.exit_code == 0, r.output
    lista = runner.invoke(cli_app, ["discovery", "list", dev.name]).output
    assert "2804:194c:1000::1100:73:2" not in lista

    r = runner.invoke(cli_app, [
        "discovery", "unignore", dev.name, "2804:194c:1000::1100:73:2", "--afi", "ipv6",
    ])
    assert r.exit_code == 0, r.output
    assert "2804:194c:1000::1100:73:2" in runner.invoke(
        cli_app, ["discovery", "list", dev.name]).output


def test_show_acha_o_peer_em_outra_caixa(db_session, tmp_path) -> None:
    """O endereço como o equipamento o escreve (`2804:194C:...`) acha a proposta
    do mesmo jeito: sem isso o `show` respondia que o peer não era candidato."""
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "2804:194C:1000::1100:73:2"])
    assert r.exit_code == 0, r.output
    assert "2804:194c:1000::1100:73:2" in r.output


def test_unignore_do_que_nao_foi_ignorado_avisa(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "unignore", dev.name, "100.64.10.4"])
    assert r.exit_code == 0, r.output
    assert "não estava na lista" in r.output


def test_afi_invalido_e_erro_de_cli(db_session, tmp_path) -> None:
    """`--afi ipv44` para antes de qualquer escrita: sem o check o valor chegaria
    ao Postgres, que o recusa com `DataError` (o enum deixa a string passar no
    bind) — um traceback no operador."""
    dev = _ambiente(db_session, tmp_path)
    for comando in ("ignore", "unignore"):
        r = runner.invoke(cli_app, [
            "discovery", comando, dev.name, "100.64.10.4", "--afi", "ipv44",
        ])
        assert r.exit_code == 1, r.output
        assert "Família inválida" in r.output
    assert listar_ignorados(db_session, dev.id) == []


def test_conflito_do_servico_vira_mensagem(db_session, tmp_path, monkeypatch) -> None:
    """O `ConflictError` do serviço (corrida: o equipamento apagado entre a
    conferência e o insert) não é traceback: sai mensagem e exit 1. Só é
    alcançável por corrida, e é por isso que o teste força o serviço."""
    dev = _ambiente(db_session, tmp_path)

    def _estoura(*args, **kwargs):
        raise ConflictError("a linha acabou de ser criada por outra requisição")

    for comando, alvo in (
        ("ignore", "gerenet.cli.discovery.ignorar_candidato"),
        ("unignore", "gerenet.cli.discovery.esquecer_ignorado"),
    ):
        monkeypatch.setattr(alvo, _estoura)
        r = runner.invoke(cli_app, ["discovery", comando, dev.name, "100.64.10.4"])
        assert r.exit_code == 1, r.output
        assert "Erro: a linha acabou de ser criada" in r.output
        # `SystemExit` e não `ConflictError`: é o que separa mensagem de traceback.
        assert isinstance(r.exception, SystemExit)


def test_leitura_parcial_ainda_lista_propostas(db_session, tmp_path) -> None:
    """`aviso` carrega dois estados, e o teste do equipamento sem coleta cobre um
    só. Leitura parcial (cabeçalho de família fora do escopo) não pode zerar a
    lista: quem manda parar é a ausência de coleta, não o aviso."""
    site = create_site(db_session, SiteCreate(name="pop-cli-parcial",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-parcial",
                                                 management_address="10.0.0.6", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "parcial.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.2601\n"
        " vlan-type dot1q 2601\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        " ipv4-family multicast\n"
        "  peer 10.0.0.9 enable\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()

    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "Aviso:" in r.output
    assert "100.64.10.1" in r.output
    assert "adotavel_com_pendencias" in r.output


def test_aviso_nao_vira_conclusao_de_lista_vazia(db_session) -> None:
    """Sem coleta o `list` não afirma "Nenhum peer fora da SoT.": a lista vazia
    não é prova de borda sem peer, é falta de leitura (§4 do design)."""
    site = create_site(db_session, SiteCreate(name="pop-cli-sem-conclusao"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-sem-conclusao",
                                                 management_address="10.0.0.8", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "Aviso:" in r.output
    assert "Nenhum peer fora da SoT." not in r.output


def test_show_sem_coleta_avisa_antes_de_nao_encontrar(db_session) -> None:
    """Sem coleta o `show` diz que falta coletar, em vez de "não está entre os
    candidatos" — que faria o operador procurar o que ninguém leu."""
    site = create_site(db_session, SiteCreate(name="pop-cli-show-sem-coleta"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-show-sem-coleta",
                                                 management_address="10.0.0.7", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "100.64.10.1"])
    assert r.exit_code == 1, r.output
    assert "Colete antes" in r.output
    # A leitura não aconteceu: "não está entre os candidatos" concluiria o que
    # nenhuma leitura sustenta.
    assert "Peer não está entre os candidatos." not in r.output


def test_show_com_leitura_parcial_nao_conclui(db_session, tmp_path) -> None:
    """A leitura parcial cala a conclusão pelo mesmo motivo da sem coleta: o
    cabeçalho fora do escopo deixa peers de fora, e o aviso é quem responde. É a
    regra do `list` (que só conclui com `aviso is None`) e da página."""
    site = create_site(db_session, SiteCreate(name="pop-cli-show-parcial",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-show-parcial",
                                                 management_address="10.0.0.4", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "parcial.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.2601\n"
        " vlan-type dot1q 2601\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        " ipv4-family multicast\n"
        "  peer 10.0.0.9 enable\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()

    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "10.0.0.9"])

    assert r.exit_code == 1, r.output
    assert "Aviso:" in r.output
    assert "Peer não está entre os candidatos." not in r.output


def test_list_nao_conclui_lista_vazia_com_internos(db_session, tmp_path) -> None:
    """Todo peer da configuração é iBGP: a lista de fora da SoT fica vazia e o
    bloco dos internos mostra o peer — que está fora da SoT por definição. A
    frase "Nenhum peer fora da SoT." contradiria a linha seguinte."""
    site = create_site(db_session, SiteCreate(name="pop-cli-internos",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-internos",
                                                 management_address="10.0.0.5", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "internos.txt"
    arquivo.write_text(
        "bgp 65001\n"
        " peer 10.0.0.9 as-number 65001\n"
        " peer 10.0.0.9 description RR-INTERNO\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()

    r = runner.invoke(cli_app, ["discovery", "list", dev.name])

    assert r.exit_code == 0, r.output
    assert "Nenhum peer fora da SoT." not in r.output
    assert "Internos (iBGP), 1:" in r.output


def test_show_de_peer_ignorado_diz_que_esta_ignorado(db_session, tmp_path) -> None:
    """O peer na lista de ignorados sai da lista de candidatos, e o `show` do
    endereço dele respondia "não está entre os candidatos": a resposta honesta
    é que ele está ignorado, e desfazer é o `unignore`."""
    dev = _ambiente(db_session, tmp_path)
    assert runner.invoke(cli_app, [
        "discovery", "ignore", dev.name, "100.64.10.4", "--motivo", "cliente saiu",
    ]).exit_code == 0

    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "100.64.10.4"])
    assert r.exit_code == 1, r.output
    assert "está na lista de ignorados" in r.output
    assert "Peer não está entre os candidatos." not in r.output


def test_device_sem_coleta_avisa(db_session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-cli-sem-coleta"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-sem-coleta",
                                                 management_address="10.0.0.9", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "Colete antes" in r.output


def test_adopt_com_json_grava_o_circuito(db_session, tmp_path) -> None:
    """O caminho de quem prefere resolver as pendências num arquivo a abrir a tela."""
    dev = _ambiente(db_session, tmp_path)  # helper do próprio arquivo
    json_revisao = tmp_path / "revisao.json"
    json_revisao.write_text(json.dumps({
        "device_id": dev.id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-CLI-1001", "access_device_id": dev.id, "access_port": "GE0/0/1",
        "edge_trunk": "Eth-Trunk127",
        "organizacao_nova": {"name": "Cliente CLI", "kind": "downstream", "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": True,
    }), encoding="utf-8")
    r = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                "--json", str(json_revisao)])
    assert r.exit_code == 0, r.output
    assert "ADOC-CLI-1001" in r.output
    # O código da mensagem vem do próprio arquivo: sem a consulta à SoT uma
    # adoção que só ecoasse o JSON deixaria o teste verde.
    circuito = db_session.scalar(
        select(models.Circuit).where(models.Circuit.code == "ADOC-CLI-1001")
    )
    assert circuito is not None
    assert circuito.access_port == "GE0/0/1"
    assert circuito.edge_device_id == dev.id


def test_adopt_recusa_revisao_de_outro_equipamento(db_session, tmp_path) -> None:
    """A revisão carrega a identidade de quem a escreveu, e o serviço confere
    contra a proposta. Sem isso o arquivo de um equipamento adota no outro, com
    o `ciente` dele liberando o gate das diferenças que o operador não viu."""
    site = create_site(db_session, SiteCreate(name="pop-cli-revisao-alheia",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    devs = []
    for nome, mgmt in (("ne-cli-revisao-a", "10.0.0.1"), ("ne-cli-revisao-b", "10.0.0.2")):
        outro = create_device(db_session, DeviceCreate(name=nome, management_address=mgmt,
                                                       asn=65001), actor="cli")
        link_device(db_session, site.id, outro.id, actor="cli")
        db_session.add(models.DeviceSnapshot(
            device_id=outro.id, status="success",
            raw_files={"config_backup": [str(arquivo)]},
        ))
        devs.append(outro)
    db_session.commit()
    dev_a, dev_b = devs

    json_revisao = tmp_path / "revisao-a.json"
    json_revisao.write_text(json.dumps({
        "device_id": dev_a.id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-CLI-DE-OUTRO", "access_device_id": dev_a.id,
        "access_port": "GE0/0/1", "edge_trunk": "Eth-Trunk127",
        "organizacao_nova": {"name": "Cliente De Outro", "kind": "downstream", "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": True,
    }), encoding="utf-8")

    # O peer é o mesmo nos dois equipamentos: a proposta de B existe, e é ela que
    # a revisão de A encontaria sem a guarda da identidade.
    r = runner.invoke(cli_app, ["discovery", "adopt", dev_b.name, "100.64.10.1",
                                "--json", str(json_revisao)])
    assert r.exit_code == 1, r.output
    assert "device_id" in r.output
    assert isinstance(r.exception, SystemExit)
    assert db_session.scalar(
        select(models.Circuit).where(models.Circuit.code == "ADOC-CLI-DE-OUTRO")
    ) is None


def test_adopt_com_ciente_na_linha_de_comando(db_session, tmp_path) -> None:
    """O `--ciente` do terminal marca o aceite sem editar o arquivo, que é o
    caminho do runbook: o operador revisa e aceita na mesma sessão.

    E o aceite assume LINHAS, que o terminal tem de mostrar: o diff sai antes da
    escrita, com os mesmos perfis e trunk que a adoção grava. Sem ele a
    auditoria registrava um "estou ciente" sobre um diff que a tela não mostrou
    — vê-lo exigia um `show` à parte, que nada pedia.
    """
    dev = _ambiente(db_session, tmp_path)
    json_revisao = tmp_path / "revisao.json"
    json_revisao.write_text(json.dumps({
        "device_id": dev.id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-CLI-CIENTE-FLAG", "access_device_id": dev.id,
        "access_port": "GE0/0/1", "edge_trunk": "Eth-Trunk127",
        "organizacao_nova": {"name": "Cliente Ciente Flag", "kind": "downstream",
                             "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": False,
    }), encoding="utf-8")

    sem_flag = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                       "--json", str(json_revisao)])
    assert sem_flag.exit_code == 1, sem_flag.output
    # A recusa é a mesma de antes (o aceite que falta), e agora vem precedida do
    # que o operador tem de assumir.
    assert "confirme o ciente" in sem_flag.output
    assert "password [mascarado]" in sem_flag.output

    com_flag = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                       "--json", str(json_revisao), "--ciente"])
    assert com_flag.exit_code == 0, com_flag.output
    assert "ADOC-CLI-CIENTE-FLAG" in com_flag.output
    # As linhas que o `ciente` assumiu, impressas ANTES da escrita (e antes do
    # relato do circuito): é a leitura e o aceite na mesma tela.
    assert "fidelidade peer:" in com_flag.output
    assert "    falta no render: peer 100.64.10.1 password [mascarado]" in com_flag.output
    assert com_flag.output.index("password [mascarado]") < com_flag.output.index("Circuito ")


def test_adopt_com_arquivo_fora_de_utf8_nao_estoura(db_session, tmp_path) -> None:
    """Revisão com acento regravada em latin-1 por um editor antigo: o
    `UnicodeDecodeError` é `ValueError` e não `OSError`, então sem tratamento
    próprio chegava ao terminal como pilha."""
    dev = _ambiente(db_session, tmp_path)
    json_revisao = tmp_path / "revisao-latin1.json"
    json_revisao.write_bytes(json.dumps({
        "device_id": dev.id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-CLI-LATIN1", "access_device_id": dev.id,
        "access_port": "GE0/0/1", "edge_trunk": "Eth-Trunk127",
        "organizacao_nova": {"name": "Cliente São Paulo", "kind": "downstream",
                             "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": True,
    }, ensure_ascii=False).encode("latin-1"))

    r = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                "--json", str(json_revisao)])
    assert r.exit_code == 1, r.output
    # O exit code 1 sozinho não prova nada: o `CliRunner` devolve 1 para qualquer
    # exceção, e a pilha continuaria no lugar da mensagem.
    assert isinstance(r.exception, SystemExit)
    assert "UTF-8" in r.output


def test_adopt_com_leitura_parcial_avisa(db_session, tmp_path) -> None:
    """A leitura sinalizada aparece mesmo quando a proposta é achada: o comando
    escreve na SoT, e gravar a partir de uma leitura que a ferramenta marca sem
    nenhum sinal é o que mais custa (a regra do `list` e do `show`)."""
    site = create_site(db_session, SiteCreate(name="pop-cli-adopt-parcial",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-adopt-parcial",
                                                 management_address="10.0.0.3", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "parcial.txt"
    # O `ipv4-family multicast` é o cabeçalho fora do escopo que faz a leitura
    # sair sinalizada; a VLAN fica na faixa que a adoção aceita (2–4094), senão
    # quem recusaria seria o IDAM e o teste não chegaria ao aviso.
    arquivo.write_text(
        "interface Eth-Trunk127.2001\n"
        " vlan-type dot1q 2001\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        " ipv4-family multicast\n"
        "  peer 10.0.0.9 enable\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()

    json_revisao = tmp_path / "revisao.json"
    json_revisao.write_text(json.dumps({
        "device_id": dev.id, "vrf": None, "subinterface": "Eth-Trunk127.2001",
        "circuit_code": "ADOC-CLI-PARCIAL", "access_device_id": dev.id,
        "access_port": "GE0/0/1", "edge_trunk": "Eth-Trunk127",
        "organizacao_nova": {"name": "Cliente Parcial", "kind": "downstream", "asn": 64512},
        "sessoes": [{"afi": "ipv4"}],
        "ciente": True,
    }), encoding="utf-8")

    r = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                "--json", str(json_revisao)])
    assert r.exit_code == 0, r.output
    assert "ADOC-CLI-PARCIAL" in r.output
    assert "Aviso:" in r.output


def test_adopt_sem_ciente_onde_exige_sai_com_erro(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    json_revisao = tmp_path / "revisao.json"
    json_revisao.write_text(json.dumps({
        "device_id": dev.id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-CLI-SEM-CIENTE", "access_device_id": dev.id,
        "access_port": "GE0/0/1",
        "edge_trunk": "Eth-Trunk127",
        "organizacao_nova": {"name": "Cliente CLI Sem Ciente", "kind": "downstream",
                             "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": False,
    }), encoding="utf-8")
    r = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                "--json", str(json_revisao)])
    assert r.exit_code == 1
    assert "ciente" in r.output
