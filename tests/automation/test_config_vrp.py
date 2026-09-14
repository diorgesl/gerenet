"""Parser da árvore do `display current-configuration` do VRP."""
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.config_vrp import parse_config_vrp

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _por_endereco(config, endereco: str):
    return next(p for p in config.peers if p.address == endereco)


def test_golden_da_captura_derivada() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    assert len(config.peers) == 6
    assert {p.address for p in config.peers} == {
        "10.0.0.9", "100.64.10.1", "100.64.10.4", "100.64.10.3",
        "2804:194C:1000::1100:73:2", "10.99.0.1",
    }


def test_peer_do_downstream_completo() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    alfa = _por_endereco(config, "100.64.10.1")
    assert alfa.afi == "ipv4"
    assert alfa.vrf is None
    assert alfa.asn_local == 65001
    assert alfa.asn_remote == 64512
    assert alfa.descricao == "CLIENTE-ALFA"
    assert alfa.tem_password is True
    assert alfa.import_route_policy == "RP-64512-IMPORT-V4"
    assert alfa.export_route_policy == "IP-PFX-64512-EXPORT-V4"
    assert alfa.import_prefix_list == "IP-PFX-64512-IN-V4"
    assert alfa.keepalive == 30
    assert alfa.holdtime == 90
    assert alfa.maximum_prefix == 100
    assert alfa.maximum_prefix_threshold == 80
    assert alfa.habilitado is True


def test_peer_ipv6_tem_afi_do_endereco() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    alfa_v6 = _por_endereco(config, "2804:194C:1000::1100:73:2")
    assert alfa_v6.afi == "ipv6"
    assert alfa_v6.asn_remote == 64512
    assert alfa_v6.maximum_prefix == 50


def test_peer_interno_e_peer_desligado() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    assert _por_endereco(config, "10.0.0.9").asn_remote == 65001
    beta = _por_endereco(config, "100.64.10.4")
    assert beta.shutdown is True
    assert beta.habilitado is True


def test_peer_de_upstream_com_bfd_e_graceful_restart() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    gama = _por_endereco(config, "100.64.10.3")
    assert gama.bfd is True
    assert gama.graceful_restart is True


def test_peer_de_vrf_carrega_o_nome_da_vrf() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    vrf = _por_endereco(config, "10.99.0.1")
    assert vrf.vrf == "VPNA"
    assert vrf.asn_remote == 64513
    assert vrf.habilitado is True


def test_subinterfaces_com_vlan_e_enderecos() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    por_nome = {s.nome: s for s in config.subinterfaces}
    alfa = por_nome["Eth-Trunk127.1001"]
    assert alfa.vid == 1001
    assert alfa.qinq is False
    assert alfa.descricao == "CLIENTE-ALFA"
    assert alfa.enderecos_v4 == (("100.64.10.0", "255.255.255.254"),)
    assert alfa.enderecos_v6 == (("2804:194C:1000::1100:73:1", 126),)
    # A interface principal aparece, mas sem VLAN.
    assert por_nome["Eth-Trunk127"].vid is None
    assert por_nome["Eth-Trunk127"].enderecos_v4 == ()


def test_qinq_e_mtu() -> None:
    texto = (
        "interface Eth-Trunk127.3001\n"
        " vlan-type qinq 3001\n"
        " mtu 9214\n"
        " ip address 100.64.10.2 255.255.255.254\n"
    )
    (sub,) = parse_config_vrp(texto).subinterfaces
    assert sub.qinq is True
    assert sub.mtu == 9214


def test_o_valor_da_senha_nunca_aparece_no_resultado() -> None:
    """Mascaramento (§19): o parser registra que há senha, nunca o valor."""
    texto = "bgp 65001\n peer 100.64.10.1 as-number 64512\n peer 100.64.10.1 password cipher SEGREDO-XYZ\n"
    config = parse_config_vrp(texto)
    (peer,) = config.peers
    assert peer.tem_password is True
    assert "SEGREDO-XYZ" not in repr(config)


def test_config_vazia_nao_quebra() -> None:
    config = parse_config_vrp("")
    assert config.peers == ()
    assert config.subinterfaces == ()
