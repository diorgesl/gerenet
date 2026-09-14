"""CLI da descoberta (§13 do design)."""
from pathlib import Path

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
        "interface Eth-Trunk127.6001\n"
        " vlan-type dot1q 6001\n"
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
        "interface Eth-Trunk127.6001\n"
        " vlan-type dot1q 6001\n"
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
