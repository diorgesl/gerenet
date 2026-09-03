from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.registry import parse_template

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_version.txt")
FIXTURES = Path("tests/fixtures/huawei_vrp")


def test_parse_version_contra_captura_real() -> None:
    saida = FIXTURE.read_text(encoding="utf-8")
    linhas = parse_template("version", saida)
    assert len(linhas) == 1
    assert linhas[0]["version"]  # versão VRP identificada
    assert linhas[0]["uptime"]


def test_parse_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("int_brief", saida)
    assert len(linhas) == 30
    assert linhas[0] == {"nome": "100GE0/1/53(100M)", "phy": "up", "protocolo": "down"}
    por_nome = {linha["nome"]: linha for linha in linhas}
    assert por_nome["Eth-Trunk127"]["phy"] == "up"
    assert por_nome["Eth-Trunk127"]["protocolo"] == "down"
    assert por_nome["40GE0/1/48"] == {"nome": "40GE0/1/48", "phy": "up", "protocolo": "up"}
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["LoopBack0"]["protocolo"] == "up(s)"
    assert por_nome["Nve1"]["phy"] == "up"
    assert "GigabitEthernet0/1/0.1003(10G)" in por_nome


def test_parse_interface_brief_standby_derivado() -> None:
    # Derivado (sintético, spec §10): variante ^down (standby) ausente da captura real.
    saida = (
        "Interface                   PHY   Protocol  InUti OutUti   inErrors  outErrors\n"
        "Eth-Trunk127.900            ^down down         0%     0%          0          0\n"
    )
    assert parse_template("int_brief", saida) == [
        {"nome": "Eth-Trunk127.900", "phy": "^down", "protocolo": "down"},
    ]

def test_parse_ip_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_ip_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("ip_int_brief", saida)
    assert len(linhas) == 19
    por_nome = {linha["nome"]: linha for linha in linhas}
    assert por_nome["Eth-Trunk127.4024"] == {
        "nome": "Eth-Trunk127.4024", "endereco": "100.110.0.73/30",
        "phy": "up", "protocolo": "up", "vpn": "--",
    }
    assert por_nome["LoopBack0"]["endereco"] == "203.0.113.1/32"
    assert por_nome["GigabitEthernet0/0/0"]["vpn"] == "l3vpn"
    assert por_nome["GigabitEthernet0/0/0"]["endereco"] == "192.168.0.1/24"
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["100GE0/1/53(100M)"]["endereco"] == "unassigned"
    assert por_nome["Eth-Trunk127.1500"]["endereco"] == "198.51.100.17/31"
def test_parse_ipv6_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_ipv6_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("ipv6_int_brief", saida)
    # 14 registros: 13 interfaces reais + 1 residual do flush de EOF (Filldown persiste
    # e o TextFSM emite o último grupo com endereco_v6 vazio). O merge descarta o residual.
    assert len(linhas) == 14
    esperados = {
        "Eth-Trunk127.401": "2001:DB8:1000::155:F0CA:A/127",
        "Eth-Trunk127.582": "FC00::2B7/127",
        "Eth-Trunk127.624": "Unassigned",
        "Eth-Trunk127.625": "2001:DB8:1000::1100:0:1/126",
        "Eth-Trunk127.629": "2001:DB8:1000::1100:1:1/126",
        "Eth-Trunk127.642": "Unassigned",
        "Eth-Trunk127.2003": "2001:DB8:F247:FFF3::2/64",
        "Eth-Trunk127.3899": "2001:DB8:1111::A/126",
        "Eth-Trunk127.4024": "2001:DB8:1000::1100:73:1/126",
        "GigabitEthernet0/1/0.1003": "2001:DB8:1111::51/126",
        "LoopBack0": "2001:DB8::1/128",
        "LoopBack1": "Unassigned",
        "Virtual-Ethernet0/1/101.100": "2001:DB8:F190::1/126",
    }
    por_nome: dict[str, list[dict]] = {}
    for linha in linhas:
        por_nome.setdefault(linha["nome"], []).append(linha)
    assert set(por_nome) == set(esperados)
    for nome, endereco in esperados.items():
        assert endereco in [linha["endereco_v6"] for linha in por_nome[nome]]
    assert por_nome["Eth-Trunk127.582"][0]["phy"] == "*down"
    assert linhas[-1] == {
        "nome": "Virtual-Ethernet0/1/101.100", "phy": "up", "protocolo": "up",
        "vpn": "--", "endereco_v6": "",
    }
    assert len([linha for linha in linhas if linha["endereco_v6"]]) == 13


def test_parse_ipv6_interface_brief_multiplos_enderecos_derivado() -> None:
    # Derivado (sintético, spec §10): mais de um endereço por interface — a captura
    # real traz um por grupo. ([TENTATIVE] é variante real, presente na fixture.)
    saida = (
        "Interface                    Physical              Protocol VPN\n"
        "Eth-Trunk127.625             up                    up       --\n"
        "[IPv6 Address/Prefix Length] 2001:DB8:1000::1100:0:1/126\n"
        "[IPv6 Address/Prefix Length] 2001:DB8:1000::1100:0:2/126  [TENTATIVE]\n"
        "LoopBack0                    up                    up(s)    --\n"
        "[IPv6 Address/Prefix Length] 2001:DB8::1/128\n"
    )
    linhas = parse_template("ipv6_int_brief", saida)
    assert [linha["endereco_v6"] for linha in linhas if linha["nome"] == "Eth-Trunk127.625"] == [
        "2001:DB8:1000::1100:0:1/126", "2001:DB8:1000::1100:0:2/126",
    ]
    assert linhas[-1] == {"nome": "LoopBack0", "phy": "up", "protocolo": "up(s)",
                          "vpn": "--", "endereco_v6": ""}  # flush de EOF
def test_parse_bgp_peer_v4_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_bgp_peer.txt").read_text(encoding="utf-8")
    linhas = parse_template("bgp_peer", saida)
    assert [(l["peer"], l["asn"], l["estado"], l["pref_rcv"], l["up_down"]) for l in linhas] == [
        ("10.30.70.1", "64526", "Idle(Admin)", "0", "0655h07m"),
        ("10.247.3.1", "64515", "Established", "37", "0490h58m"),
        ("10.255.255.0", "64512", "Established", "3", "0655h06m"),
        ("38.229.6.20", "64533", "Connect", "0", "0655h07m"),
        ("100.110.0.14", "64520", "Active", "0", "0655h07m"),
        ("100.110.0.66", "64535", "Idle", "0", "21:48:20"),
        ("100.110.0.74", "64520", "Established", "1", "0655h06m"),
        ("100.110.0.78", "64520", "Established", "6", "0655h06m"),
        ("100.110.0.82", "64525", "Established", "2", "0655h06m"),
        ("172.25.2.68", "64544", "Idle(Admin)", "0", "0655h07m"),
        ("198.51.100.254", "64531", "Established", "1090707", "0356h52m"),
        ("198.19.255.250", "64522", "Established", "1093942", "0244h53m"),
    ]


def test_parse_bgp_peer_v6_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_bgp_ipv6_peer.txt").read_text(encoding="utf-8")
    linhas = parse_template("bgp_peer", saida)
    assert [(l["peer"], l["asn"], l["estado"]) for l in linhas] == [
        ("100.110.0.110", "64540", "Connect"),
        ("2001:DB8:F247:FFF3::1", "64515", "Established"),
        ("2001:DB8:8000:0:198:51:100:254", "64531", "Established"),
        ("2001:DB8::3", "64512", "Established"),
        ("2001:DB8:1000::155:177:2", "64525", "Established"),
        ("2001:DB8:1000::1100:73:2", "64520", "Established"),
        ("2001:DB8:1000::1100:77:2", "64520", "Established"),
        ("2001:DB8::250", "64522", "Established"),
        ("FC00::2B6", "64544", "Idle(Admin)"),
        ("FDFF::198:18:255:0", "64528", "Active"),
    ]
    assert linhas[2]["pref_rcv"] == "253052"  # contagem larga (6 dígitos; v4 chega a 7)


def test_parse_bgp_peer_estado_transitorio_openconfirm_derivado() -> None:
    # Derivado (sintético, spec §10): a captura real só tem os estados estáveis.
    saida = (
        " BGP local router ID : 203.0.113.1\n"
        " Local AS number : 64512\n"
        "\n"
        "  Peer                             V          AS  MsgRcvd  MsgSent  OutQ  Up/Down       State  PrefRcv\n"
        "  10.99.0.1                       4      64530      101      102     0 0655h07m   OpenConfirm        0\n"
    )
    assert parse_template("bgp_peer", saida) == [
        {"peer": "10.99.0.1", "asn": "64530", "estado": "OpenConfirm",
         "pref_rcv": "0", "up_down": "0655h07m"},
    ]
