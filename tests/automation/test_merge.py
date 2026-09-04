from gerenet.automation.parsers.huawei_vrp.merge import (
    merge_bgp_peers,
    merge_bgp_peers_detalhes,
    merge_interfaces,
    merge_parsed,
)

LINHA_INT = {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up"}
LINHA_IP = {
    "nome": "Eth-Trunk127.4024", "endereco": "100.110.0.73/30",
    "phy": "up", "protocolo": "up", "vpn": "--",
}


def test_interfaces_combina_tres_comandos_por_nome() -> None:
    por_comando = {
        "display interface brief": [LINHA_INT],
        "display ip interface brief": [LINHA_IP],
        "display ipv6 interface brief": [
            {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
             "vpn": "--", "endereco_v6": "2001:DB8:1000::1100:73:1/126"},
            # residual do flush de EOF (Filldown persiste): endereco vazio -> descartado
            {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
             "vpn": "--", "endereco_v6": ""},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
        "enderecos_v4": ["100.110.0.73/30"],
        "enderecos_v6": ["2001:DB8:1000::1100:73:1/126"],
        "vpn": None,
    }]


def test_interfaces_remove_sufixo_de_velocidade_do_nome() -> None:
    # O ipv6 interface brief omite o sufixo (10G) que o interface brief traz:
    # sem o nome canônico a mesma subinterface viraria duas entradas.
    por_comando = {
        "display interface brief": [
            {"nome": "GigabitEthernet0/1/0.1003(10G)", "phy": "down", "protocolo": "down"},
        ],
        "display ip interface brief": [
            {"nome": "GigabitEthernet0/1/0.1003(10G)", "endereco": "10.254.101.29/30",
             "phy": "down", "protocolo": "down", "vpn": "--"},
        ],
        "display ipv6 interface brief": [
            {"nome": "GigabitEthernet0/1/0.1003", "phy": "down", "protocolo": "down",
             "vpn": "--", "endereco_v6": "2001:DB8:1111::51/126"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "GigabitEthernet0/1/0.1003", "phy": "down", "protocolo": "down",
        "enderecos_v4": ["10.254.101.29/30"], "enderecos_v6": ["2001:DB8:1111::51/126"],
        "vpn": None,
    }]


def test_interfaces_descarta_sentinelas_de_vazio() -> None:
    por_comando = {
        "display interface brief": [LINHA_INT],
        "display ip interface brief": [
            {"nome": "Eth-Trunk127.4024", "endereco": "unassigned",
             "phy": "up", "protocolo": "down", "vpn": "--"},
        ],
        "display ipv6 interface brief": [
            {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "down",
             "vpn": "--", "endereco_v6": "Unassigned"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
        "enderecos_v4": [], "enderecos_v6": [], "vpn": None,
    }]


def test_interfaces_prioriza_interface_brief_e_vpn_nomeada() -> None:
    # phy/protocolo da primeira fonte na ordem dos comandos; vpn nomeada preservada.
    por_comando = {
        "display interface brief": [LINHA_INT],
        "display ip interface brief": [
            {"nome": "Eth-Trunk127.4024", "endereco": "unassigned",
             "phy": "down", "protocolo": "down", "vpn": "l3vpn"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
        "enderecos_v4": [], "enderecos_v6": [], "vpn": "l3vpn",
    }]


def test_interfaces_interface_so_no_ipv6_usa_dados_do_grupo() -> None:
    por_comando = {
        "display ipv6 interface brief": [
            {"nome": "Virtual-Ethernet0/1/101.100", "phy": "up", "protocolo": "up",
             "vpn": "--", "endereco_v6": "2001:DB8:F190::1/126"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Virtual-Ethernet0/1/101.100", "phy": "up", "protocolo": "up",
        "enderecos_v4": [], "enderecos_v6": ["2001:DB8:F190::1/126"], "vpn": None,
    }]


def test_bgp_peers_combina_familias_com_afi_e_tipos() -> None:
    por_comando = {
        "display bgp peer": [
            {"peer": "10.30.70.1", "asn": "64526", "estado": "Idle(Admin)",
             "pref_rcv": "0", "up_down": "0655h07m"},
        ],
        "display bgp ipv6 peer": [
            {"peer": "2001:DB8::3", "asn": "64512", "estado": "Established",
             "pref_rcv": "13", "up_down": "0655h06m"},
        ],
    }
    assert merge_bgp_peers(por_comando) == [
        {"afi": "ipv4", "peer": "10.30.70.1", "asn": 64526, "estado": "Idle(Admin)",
         "pref_rcv": 0, "up_down": "0655h07m"},
        {"afi": "ipv6", "peer": "2001:DB8::3", "asn": 64512, "estado": "Established",
         "pref_rcv": 13, "up_down": "0655h06m"},
    ]


def test_bgp_peers_vazio_devolve_lista_vazia() -> None:
    assert merge_bgp_peers({}) == []
    assert merge_bgp_peers({"display bgp peer": []}) == []


def test_detalhes_none_para_campos_ausentes_e_afi_do_comando() -> None:
    por_comando = {
        "display bgp peer 198.51.100.254 verbose": [
            {"peer": "198.51.100.254", "asn": "64531", "descricao": "UPSTREAM-FNA",
             "estado": "Established", "filtro_import": "ASN64531-V4-IMPORT",
             "filtro_export": "XPL-UPSTREAM-AS64531-V4-EXPORT"},
        ],
        "display bgp ipv6 peer 10.99.0.1 verbose": [
            {"peer": "10.99.0.1", "asn": "64530", "descricao": "",
             "estado": "Idle(Admin)", "filtro_import": "", "filtro_export": ""},
        ],
    }
    assert merge_bgp_peers_detalhes(por_comando) == [
        {"afi": "ipv4", "peer": "198.51.100.254", "descricao": "UPSTREAM-FNA",
         "filtro_import": "ASN64531-V4-IMPORT", "filtro_export": "XPL-UPSTREAM-AS64531-V4-EXPORT"},
        {"afi": "ipv6", "peer": "10.99.0.1", "descricao": None,
         "filtro_import": None, "filtro_export": None},
    ]


def test_merge_parsed_despacha_e_rejeita_desconhecido() -> None:
    import pytest

    assert merge_parsed("bgp_peers", {"display bgp peer": []}) == []
    with pytest.raises(KeyError, match="nao-existe"):
        merge_parsed("nao-existe", {})
