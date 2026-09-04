"""Golden puro por template (spec ciclo B §5.2/§10) — entradas fixas, sem banco."""
from gerenet.automation.render import _render_template


def _render(template: str, **ctx: object) -> str:
    """Renderiza `template`; o parâmetro é renomeado (vs. `nome` do brief) para
    não colidir com a chave de contexto `nome` dos templates de prefix/policy."""
    return _render_template(template, ctx)


def test_subinterface_dual() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.4024", descricao=None, qinq=False, vid=4024,
        enderecos_v4=[{"endereco": "100.110.0.73", "mascara": "255.255.255.252"}],
        enderecos_v6=["2804:194C:1000::1100:73:1/126"],
    ) == "\n".join([
        "interface Eth-Trunk127.4024",
        "vlan-type dot1q vid 4024",
        "ip address 100.110.0.73 255.255.255.252",
        "ipv6 enable",
        "ipv6 address 2804:194C:1000::1100:73:1/126",
    ])


def test_subinterface_v4_descricao_sem_ipv6() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.4023", descricao="Cliente A", qinq=False, vid=4023,
        enderecos_v4=[{"endereco": "100.64.0.1", "mascara": "255.255.255.254"}],
        enderecos_v6=[],
    ) == "\n".join([
        "interface Eth-Trunk127.4023",
        "description Cliente A",
        "vlan-type dot1q vid 4023",
        "ip address 100.64.0.1 255.255.255.254",
    ])


def test_subinterface_qinq_0x88a8() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.100", descricao=None, qinq=True, vid=100,
        enderecos_v4=[], enderecos_v6=["2001:DB8::1/126"],
    ) == "\n".join([
        "interface Eth-Trunk127.100",
        "vlan-type dot1q 0x88a8 vid 100",
        "ipv6 enable",
        "ipv6 address 2001:DB8::1/126",
    ])


def test_prefix_list_v4_e_v6() -> None:
    assert _render(
        "prefix_list",
        nome="IP-PFX-64500-IN-V4", afi="ipv4",
        entradas=[
            {"index": 10, "prefixo": "192.0.2.0/24"},
            {"index": 20, "prefixo": "198.51.100.0/24"},
        ],
    ) == "\n".join([
        "ip ip-prefix IP-PFX-64500-IN-V4 index 10 permit 192.0.2.0/24",
        "ip ip-prefix IP-PFX-64500-IN-V4 index 20 permit 198.51.100.0/24",
    ])
    assert _render(
        "prefix_list", nome="IP-PFX-64500-IN-V6", afi="ipv6",
        entradas=[{"index": 10, "prefixo": "2001:DB8::/32"}],
    ) == "ip ipv6-prefix IP-PFX-64500-IN-V6 index 10 permit 2001:DB8::/32"
    assert _render(
        "prefix_list", nome="IP-PFX-64500-IN-V4", afi="ipv4",
        entradas=[
            {"index": 5, "prefixo": "0.0.0.0/0"},
            {"index": 10, "prefixo": "192.0.2.0/24"},
        ],
    ).startswith("ip ip-prefix IP-PFX-64500-IN-V4 index 5 permit 0.0.0.0/0")


def test_route_policy_import_v4_com_lp_e_v6_sem_lp() -> None:
    assert _render(
        "route_policy_import", nome="RP-64500-IMPORT-V4", afi="ipv4",
        lista="IP-PFX-64500-IN-V4", local_preference=200,
    ) == "\n".join([
        "route-policy RP-64500-IMPORT-V4 permit node 10",
        "if-match ip-prefix IP-PFX-64500-IN-V4",
        "apply local-preference 200",
    ])
    assert _render(
        "route_policy_import", nome="RP-64500-IMPORT-V6", afi="ipv6",
        lista="IP-PFX-64500-IN-V6", local_preference=None,
    ) == "\n".join([
        "route-policy RP-64500-IMPORT-V6 permit node 10",
        "if-match ipv6 address prefix-list IP-PFX-64500-IN-V6",
    ])


def test_route_policy_export_full_sem_condicoes() -> None:
    assert _render(
        "route_policy_export", nome="RP-64500-EXPORT-V4", afi="ipv4", lista=None,
        med=None, prepend=0, asn_local=61785,
    ) == "route-policy RP-64500-EXPORT-V4 permit node 10"


def test_route_policy_export_default_com_med_e_prepend() -> None:
    assert _render(
        "route_policy_export", nome="RP-64500-EXPORT-V6", afi="ipv6",
        lista="IP-PFX-DEFAULT-V6", med=50, prepend=2, asn_local=61785,
    ) == "\n".join([
        "route-policy RP-64500-EXPORT-V6 permit node 10",
        "if-match ipv6 address prefix-list IP-PFX-DEFAULT-V6",
        "apply med 50",
        "apply as-path 61785 61785 additive",
    ])


def test_bgp_peer_v4_completo() -> None:
    assert _render(
        "bgp_peer",
        asn_local=61785, peer="100.110.0.74", asn_remote=270620,
        descricao="Cliente 270620", has_password=True,
        password_path="gerenet/bgp-sessions/1/password",
        keepalive=30, holdtime=90, graceful_restart=True, bfd_enabled=True,
        shutdown=False, afi="ipv4", rp_import="RP-270620-IMPORT-V4",
        rp_export="RP-270620-EXPORT-V4", maximum_prefix=100, maximum_prefix_threshold=80,
    ) == "\n".join([
        "bgp 61785",
        "peer 100.110.0.74 as-number 270620",
        "peer 100.110.0.74 description Cliente 270620",
        "# password no Vault (gerenet/bgp-sessions/1/password)",
        "peer 100.110.0.74 timer keepalive 30 hold 90",
        "peer 100.110.0.74 graceful-restart",
        "peer 100.110.0.74 bfd enable",
        "ipv4-family unicast",
        "  peer 100.110.0.74 enable",
        "  peer 100.110.0.74 import route-policy RP-270620-IMPORT-V4",
        "  peer 100.110.0.74 export route-policy RP-270620-EXPORT-V4",
        "  peer 100.110.0.74 maximum-prefix 100 80",
    ])


def test_bgp_peer_v6_minimo_com_shutdown() -> None:
    assert _render(
        "bgp_peer",
        asn_local=61785, peer="2804:194C:1000::1100:73:2", asn_remote=270620,
        descricao=None, has_password=False, password_path=None,
        keepalive=None, holdtime=None, graceful_restart=False, bfd_enabled=False,
        shutdown=True, afi="ipv6", rp_import=None, rp_export=None,
        maximum_prefix=None, maximum_prefix_threshold=None,
    ) == "\n".join([
        "bgp 61785",
        "peer 2804:194C:1000::1100:73:2 as-number 270620",
        "peer 2804:194C:1000::1100:73:2 shutdown",
        "ipv6-family unicast",
        "  peer 2804:194C:1000::1100:73:2 enable",
    ])
