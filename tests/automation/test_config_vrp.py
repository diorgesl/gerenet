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


def test_qinq_do_render_com_0x88a8() -> None:
    """A linha de QinQ é a que o próprio render emite (`subinterface.j2`)."""
    texto = "interface Eth-Trunk127.100\n vlan-type dot1q 0x88a8 vid 100\n ipv6 enable\n"
    (sub,) = parse_config_vrp(texto).subinterfaces
    assert sub.vid == 100
    assert sub.qinq is True


def test_ipv6_com_barra_do_render() -> None:
    """A grafia com barra é a que o render emite (golden de `test_templates.py`)."""
    texto = "interface Eth-Trunk127.4024\n ipv6 address 2804:194C:1000::1100:73:1/126\n"
    (sub,) = parse_config_vrp(texto).subinterfaces
    assert sub.enderecos_v6 == (("2804:194C:1000::1100:73:1", 126),)


def test_linhas_que_nao_sao_endereco_sao_ignoradas_derivado() -> None:
    """Derivado: `unnumbered`, `auto link-local` e `eui-64` não vêm do render.

    São linhas que existem numa configuração de equipamento e que não são par de
    endereço: elas ficam de fora sem derrubar a leitura dos endereços de verdade.
    """
    texto = (
        "interface Eth-Trunk127.1001\n"
        " ip address unnumbered interface LoopBack0\n"
        " ipv6 address auto link-local\n"
        " ipv6 address eui-64 2001:DB8::/64\n"
        " ipv6 address 2001:DB8::9/129\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        " ipv6 address 2804:194C:1000::1100:73:1 126\n"
    )
    (sub,) = parse_config_vrp(texto).subinterfaces
    assert sub.enderecos_v4 == (("100.64.10.0", "255.255.255.254"),)
    assert sub.enderecos_v6 == (("2804:194C:1000::1100:73:1", 126),)


def test_secao_de_familia_desconhecida_nao_cria_peer_fantasma_derivado() -> None:
    """Derivado: `ipv4-family multicast` não vem do render.

    Seção que não é a pública nem uma VRF não pertence a nenhum peer; o peer de
    lá não pode aparecer como se fosse da VRF da seção anterior.
    """
    texto = (
        "bgp 65001\n"
        " ipv4-family vpn-instance VPNA\n"
        "  peer 10.99.0.1 as-number 64513\n"
        " ipv4-family multicast\n"
        "  peer 10.0.0.9 enable\n"
    )
    config = parse_config_vrp(texto)
    assert [(p.address, p.vrf) for p in config.peers] == [("10.99.0.1", "VPNA")]
    assert any("multicast" in aviso for aviso in config.avisos)


def test_secao_de_familia_desconhecida_nao_sobrescreve_o_publico_derivado() -> None:
    """O peer da instância pública não perde atributo para a seção ignorada."""
    texto = (
        "bgp 65001\n"
        " peer 10.0.0.9 as-number 65001\n"
        " ipv4-family unicast\n"
        "  peer 10.0.0.9 enable\n"
        "  peer 10.0.0.9 route-policy RP-UNICAST import\n"
        "  peer 10.0.0.9 maximum-prefix 100 80\n"
        " ipv4-family multicast\n"
        "  peer 10.0.0.9 enable\n"
        "  peer 10.0.0.9 route-policy RP-MULTICAST import\n"
        "  peer 10.0.0.9 maximum-prefix 5\n"
    )
    config = parse_config_vrp(texto)
    (publico,) = config.peers
    assert publico.vrf is None
    assert publico.import_route_policy == "RP-UNICAST"
    assert publico.maximum_prefix == 100
    assert publico.maximum_prefix_threshold == 80


def test_secao_l2vpn_nao_herda_a_vrf_anterior_derivado() -> None:
    """Derivado: `l2vpn-family evpn` fica no mesmo lugar e não é sessão unicast.

    A seção não é `ipvN-family`, mas cai na mesma regra: peer de lá não é peer
    desta instância.
    """
    texto = (
        "bgp 65001\n"
        " ipv4-family vpn-instance VPNA\n"
        "  peer 10.99.0.1 as-number 64513\n"
        " l2vpn-family evpn\n"
        "  peer 10.0.0.9 enable\n"
    )
    config = parse_config_vrp(texto)
    assert [(p.address, p.vrf) for p in config.peers] == [("10.99.0.1", "VPNA")]
    assert any("l2vpn-family" in aviso for aviso in config.avisos)


def test_aviso_quando_a_captura_nao_tem_bloco_bgp_derivado() -> None:
    """Captura sem `bgp` avisa; o texto vazio e a fixture boa não avisam."""
    sem_bgp = parse_config_vrp(
        "sysname NE8000-SPO\ninterface LoopBack0\n ip address 10.0.0.1 255.255.255.255\n"
    )
    assert sem_bgp.peers == ()
    assert any("bgp" in aviso for aviso in sem_bgp.avisos)
    assert parse_config_vrp("").avisos == ()
    assert parse_config_vrp(FIXTURE.read_text(encoding="utf-8")).avisos == ()


def test_vid_e_o_primeiro_numero_depois_do_dot1q_derivado() -> None:
    """Derivado: o `second-dot1q` é dívida registrada do template QinQ.

    O VID é o primeiro número depois do `dot1q`. O último número da linha é o
    CE-VLAN interno, e um token final não numérico não derruba mais a leitura.
    """
    texto = (
        "interface Eth-Trunk127.100\n"
        " vlan-type dot1q 0x88a8 vid 100 second-dot1q 200\n"
        "interface Eth-Trunk127.101\n"
        " vlan-type dot1q 0x88a8 vid 101 second-dot1q any\n"
    )
    por_nome = {s.nome: s for s in parse_config_vrp(texto).subinterfaces}
    assert por_nome["Eth-Trunk127.100"].vid == 100
    assert por_nome["Eth-Trunk127.100"].qinq is True
    assert por_nome["Eth-Trunk127.101"].vid == 101


def test_valor_que_nao_converte_vira_aviso_derivado() -> None:
    """Derivado: asdot e valor torto não vêm do render.

    O que não converte vira aviso e o campo fica vazio; o que converte na mesma
    linha entra, e o resto da captura segue sendo lido.
    """
    texto = (
        "interface Eth-Trunk127.100\n"
        " vlan-type dot1q vid\n"
        " mtu 9214\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 65535.100\n"
        " peer 100.64.10.1 maximum-prefix 100 200x\n"
        " peer 100.64.10.2 as-number 64512\n"
        " peer 100.64.10.2 shutdown\n"
    )
    config = parse_config_vrp(texto)
    (sub,) = config.subinterfaces
    assert sub.vid is None
    assert sub.mtu == 9214
    assert sub.enderecos_v4 == (("100.64.10.0", "255.255.255.254"),)
    alfa = _por_endereco(config, "100.64.10.1")
    assert alfa.asn_remote is None
    assert alfa.maximum_prefix == 100
    assert alfa.maximum_prefix_threshold is None
    beta = _por_endereco(config, "100.64.10.2")
    assert beta.asn_remote == 64512
    assert beta.shutdown is True
    assert len(config.avisos) == 3


def test_comentario_com_texto_nao_fecha_o_bloco_derivado() -> None:
    """O render deste projeto emite comentário com texto na coluna 0 dentro do
    bloco (`# password no Vault ...` no `bgp`, `# second-dot1q ...` na
    `interface`). Tratado como bloco de topo, ele fechava o bloco ali mesmo: os
    peers e os endereços escritos depois dele saíam da leitura."""
    texto = (
        "interface Eth-Trunk127.1001\n"
        " vlan-type dot1q 1001\n"
        "# second-dot1q: encapsulamento interno duplo — dívida do ciclo C\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 10.0.0.9 as-number 65001\n"
        "# password no Vault (secret/ne8000/peer-100.64.10.1)\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
    )
    config = parse_config_vrp(texto)
    (sub,) = config.subinterfaces
    assert sub.enderecos_v4 == (("100.64.10.0", "255.255.255.254"),)
    assert {p.address for p in config.peers} == {"10.0.0.9", "100.64.10.1"}
    assert _por_endereco(config, "100.64.10.1").habilitado is True
    assert config.avisos == ()


def test_le_o_qos_car_da_subinterface() -> None:
    """O `cir` é a taxa que o equipamento aplica; a revisão da adoção a sugere
    como velocidade do circuito (§7)."""
    config = parse_config_vrp(
        "interface Eth-Trunk127.626\n"
        " vlan-type dot1q 626\n"
        " description CIRC-626 NETMAC [1G]\n"
        " statistic enable\n"
        " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
        " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
    )
    (sub,) = config.subinterfaces
    assert sub.qos_cir == 1024000


def test_qos_car_com_cir_diferente_nas_direcoes_nao_tem_cir() -> None:
    """M1 — `cir` diferente nas duas direções não dá taxa para sugerir.

    A sugestão da revisão grava a taxa no circuito e o render passa a emitir
    esse número nas DUAS direções: uma delas sem lastro no equipamento. É a
    mesma recusa dos outros dois casos que não inventam número (o `cir` não
    múltiplo de 1000 e o acima do teto). O caso comum — as duas linhas do
    render com o mesmo valor — continua sugerindo aquele valor.
    """
    def _config(cir_in: str, cir_out: str) -> str:
        return (
            "interface Eth-Trunk127.626\n"
            " vlan-type dot1q 626\n"
            f" qos car cir {cir_in} cbs 18700000 green pass red discard inbound\n"
            f" qos car cir {cir_out} cbs 18700000 green pass red discard outbound\n"
        )

    (divergente,) = parse_config_vrp(_config("1024000", "2000000")).subinterfaces
    assert divergente.qos_cir is None

    (igual,) = parse_config_vrp(_config("1024000", "1024000")).subinterfaces
    assert igual.qos_cir == 1024000


def test_subinterface_sem_qos_nao_tem_cir() -> None:
    config = parse_config_vrp(
        "interface Eth-Trunk127.100\n vlan-type dot1q 100\n statistic enable\n"
    )
    (sub,) = config.subinterfaces
    assert sub.qos_cir is None


def test_qos_car_com_valor_torto_vira_aviso() -> None:
    """A mesma tolerância do `mtu`: a leitura avisa e segue, em vez de estourar
    na configuração inteira por causa de uma linha."""
    config = parse_config_vrp(
        "interface Eth-Trunk127.100\n vlan-type dot1q 100\n qos car cir xyz inbound\n"
    )
    (sub,) = config.subinterfaces
    assert sub.qos_cir is None
    assert any("qos car" in a for a in config.avisos)


def test_le_o_default_route_advertise_do_peer() -> None:
    """§3.4: a linha marca a chave; ela não é política de importação."""
    config = parse_config_vrp(
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        "  peer 100.64.10.1 default-route-advertise\n"
    )
    (peer,) = config.peers
    assert peer.default_route_advertise is True
    assert peer.import_route_policy is None
    assert config.avisos == ()


def test_default_route_advertise_com_politica_acoplada_vira_aviso() -> None:
    """§3.4: o VRP aceita `default-route-advertise route-policy <nome>`, e o
    ramo da política de importação engoliria esse resto se viesse antes. O nome
    acoplado não é modelado — vira aviso, e a chave do anúncio fica marcada."""
    config = parse_config_vrp(
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        "  peer 100.64.10.1 default-route-advertise route-policy RP-X\n"
    )
    (peer,) = config.peers
    assert peer.default_route_advertise is True
    assert peer.import_route_policy is None
    assert any("default-route-advertise" in aviso for aviso in config.avisos)


def test_import_route_policy_segue_no_ramo_da_importacao() -> None:
    """Regressão da ordem dos ramos (§3.4): a linha da política não pode cair no
    ramo novo."""
    config = parse_config_vrp(
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " peer 100.64.10.1 route-policy RP-Y import\n"
    )
    (peer,) = config.peers
    assert peer.import_route_policy == "RP-Y"
    assert peer.default_route_advertise is False


def test_a_fixture_do_ne8000_marca_o_anuncio_da_default() -> None:
    """O peer CLIENTE-BETA da fixture passa a anunciar a default (Task 3)."""
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    assert _por_endereco(config, "100.64.10.4").default_route_advertise is True
    assert _por_endereco(config, "100.64.10.1").default_route_advertise is False
    assert config.avisos == ()
