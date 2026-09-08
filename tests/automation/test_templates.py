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
    ) == "interface Eth-Trunk127.4024\nvlan-type dot1q vid 4024\nip address 100.110.0.73 255.255.255.252\nipv6 enable\nipv6 address 2804:194C:1000::1100:73:1/126"


def test_subinterface_v4_descricao_sem_ipv6() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.4023", descricao="Cliente A", qinq=False, vid=4023,
        enderecos_v4=[{"endereco": "100.64.0.1", "mascara": "255.255.255.254"}],
        enderecos_v6=[],
    ) == "interface Eth-Trunk127.4023\ndescription Cliente A\nvlan-type dot1q vid 4023\nip address 100.64.0.1 255.255.255.254"


def test_subinterface_qinq_0x88a8() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.100", descricao=None, qinq=True, vid=100,
        enderecos_v4=[], enderecos_v6=["2001:DB8::1/126"],
    ) == "interface Eth-Trunk127.100\nvlan-type dot1q 0x88a8 vid 100\n# second-dot1q: encapsulamento interno duplo — dívida do ciclo C\nipv6 enable\nipv6 address 2001:DB8::1/126"


def test_prefix_list_v4_e_v6() -> None:
    assert _render(
        "prefix_list",
        nome="IP-PFX-64500-IN-V4", afi="ipv4",
        entradas=[
            {"index": 10, "prefixo": "192.0.2.0/24"},
            {"index": 20, "prefixo": "198.51.100.0/24"},
        ],
    ) == "ip ip-prefix IP-PFX-64500-IN-V4 index 10 permit 192.0.2.0/24\nip ip-prefix IP-PFX-64500-IN-V4 index 20 permit 198.51.100.0/24"
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
    ) == "route-policy RP-64500-IMPORT-V4 permit node 10\nif-match ip-prefix IP-PFX-64500-IN-V4\napply local-preference 200"
    assert _render(
        "route_policy_import", nome="RP-64500-IMPORT-V6", afi="ipv6",
        lista="IP-PFX-64500-IN-V6", local_preference=None,
    ) == "route-policy RP-64500-IMPORT-V6 permit node 10\nif-match ipv6 address prefix-list IP-PFX-64500-IN-V6"


def test_community_filter() -> None:
    assert _render(
        "community_filter", nome="CF-64512-BLK-1", valor="65530:666:0",
    ) == "ip community-filter CF-64512-BLK-1 permit 65530:666:0"


def test_route_policy_import_up_full() -> None:
    assert _render(
        "route_policy_import", nome="RP-64512-IMPORT-V4", afi="ipv4",
        lista="IP-PFX-64512-IN-V4", local_preference=120, produto="up-full",
        deny_communities=["CF-64512-BLK-1"], fail_safe=False,
    ) == (
        "# up-full: accept-all do provedor, exceto as proteções — deny em nós separados (if-match no mesmo nó é E, não OU)\n"
        "route-policy RP-64512-IMPORT-V4 deny node 10\n"
        "if-match ip-prefix IP-PFX-64512-IN-V4\n"
        "route-policy RP-64512-IMPORT-V4 deny node 20\n"
        "if-match community-filter CF-64512-BLK-1\n"
        "route-policy RP-64512-IMPORT-V4 permit node 100\n"
        "apply local-preference 120"
    )


def test_route_policy_import_up_full_v6_sem_lp() -> None:
    assert _render(
        "route_policy_import", nome="RP-64512-IMPORT-V6", afi="ipv6",
        lista="IP-PFX-64512-IN-V6", local_preference=None, produto="up-full",
        deny_communities=["CF-64512-BLK-1"], fail_safe=False,
    ) == (
        "# up-full: accept-all do provedor, exceto as proteções — deny em nós separados (if-match no mesmo nó é E, não OU)\n"
        "route-policy RP-64512-IMPORT-V6 deny node 10\n"
        "if-match ipv6 address prefix-list IP-PFX-64512-IN-V6\n"
        "route-policy RP-64512-IMPORT-V6 deny node 20\n"
        "if-match community-filter CF-64512-BLK-1\n"
        "route-policy RP-64512-IMPORT-V6 permit node 100"
    )


def test_route_policy_import_sem_perfil_fail_safe() -> None:
    texto = _render(
        "route_policy_import", nome="RP-64512-IMPORT-V4", afi="ipv4", lista=None,
        local_preference=None, produto=None, deny_communities=[], fail_safe=True,
    )
    assert texto == (
        "# fail-safe: sessão de upstream sem perfil de import — deny-all (nunca accept-all)\n"
        "route-policy RP-64512-IMPORT-V4 deny node 10"
    )
    assert "permit" not in texto


def test_route_policy_import_up_parcial() -> None:
    assert _render(
        "route_policy_import", nome="RP-64512-IMPORT-V4", afi="ipv4",
        lista="IP-PFX-DEFAULT-V4", local_preference=200, produto="up-parcial",
        deny_communities=["CF-64512-PART-1"], fail_safe=False,
    ) == (
        '# up-parcial: somente rota default + rotas com a community de "parcial" '
        '(lista chega em deny_communities — aqui são nós de aceite)\n'
        "route-policy RP-64512-IMPORT-V4 permit node 10\n"
        "if-match ip-prefix IP-PFX-DEFAULT-V4\n"
        "apply local-preference 200\n"
        "route-policy RP-64512-IMPORT-V4 permit node 20\n"
        "if-match community-filter CF-64512-PART-1\n"
        "apply local-preference 200"
    )


def test_route_policy_import_up_default() -> None:
    assert _render(
        "route_policy_import", nome="RP-64512-IMPORT-V4", afi="ipv4",
        lista="IP-PFX-DEFAULT-V4", local_preference=150, produto="up-default",
        deny_communities=[], fail_safe=False,
    ) == (
        "# up-default: somente a rota default do provedor\n"
        "route-policy RP-64512-IMPORT-V4 permit node 10\n"
        "if-match ip-prefix IP-PFX-DEFAULT-V4\n"
        "apply local-preference 150"
    )


def test_route_policy_export_upstream_aplicacoes() -> None:
    assert _render(
        "route_policy_export", nome="RP-64512-EXPORT-V4", afi="ipv4",
        lista="IP-PFX-INTERNAS-V4", med=None, prepend=0, asn_local=61785,
        aplicacoes=[
            {"tipo": "prepend", "valor": "65530:20:2", "regiao": "SP"},
            {"tipo": "blackhole", "valor": "65530:666:0", "regiao": None},
            {"tipo": "lp", "valor": "65530:70:150", "regiao": None},
        ],
    ) == (
        "route-policy RP-64512-EXPORT-V4 permit node 10\n"
        "if-match ip-prefix IP-PFX-INTERNAS-V4\n"
        "# aplicação prepend por região (SP): if-match regional fica na camada de render (fase 5)\n"
        "apply community 65530:20:2\n"
        "apply community 65530:666:0\n"
        "apply community 65530:70:150"
    )


def test_route_policy_export_full_sem_condicoes() -> None:
    assert _render(
        "route_policy_export", nome="RP-64500-EXPORT-V4", afi="ipv4", lista=None,
        med=None, prepend=0, asn_local=61785,
    ) == "route-policy RP-64500-EXPORT-V4 permit node 10"


def test_route_policy_export_default_com_med_e_prepend() -> None:
    assert _render(
        "route_policy_export", nome="RP-64500-EXPORT-V6", afi="ipv6",
        lista="IP-PFX-DEFAULT-V6", med=50, prepend=2, asn_local=61785,
    ) == "route-policy RP-64500-EXPORT-V6 permit node 10\nif-match ipv6 address prefix-list IP-PFX-DEFAULT-V6\napply med 50\napply as-path 61785 61785 additive"


def test_bgp_peer_v4_completo() -> None:
    assert _render(
        "bgp_peer",
        asn_local=61785, peer="100.110.0.74", asn_remote=270620,
        descricao="Cliente 270620", has_password=True,
        password_path="gerenet/bgp-sessions/1/password",
        keepalive=30, holdtime=90, graceful_restart=True, bfd_enabled=True,
        shutdown=False, afi="ipv4", rp_import="RP-270620-IMPORT-V4",
        rp_export="RP-270620-EXPORT-V4", maximum_prefix=100, maximum_prefix_threshold=80,
    ) == "bgp 61785\npeer 100.110.0.74 as-number 270620\npeer 100.110.0.74 description Cliente 270620\n# password no Vault (gerenet/bgp-sessions/1/password)\npeer 100.110.0.74 timer keepalive 30 hold 90\npeer 100.110.0.74 graceful-restart\npeer 100.110.0.74 bfd enable\nipv4-family unicast\n  peer 100.110.0.74 enable\n  peer 100.110.0.74 import route-policy RP-270620-IMPORT-V4\n  peer 100.110.0.74 export route-policy RP-270620-EXPORT-V4\n  peer 100.110.0.74 maximum-prefix 100 80"


def test_bgp_peer_v6_minimo_com_shutdown() -> None:
    assert _render(
        "bgp_peer",
        asn_local=61785, peer="2804:194C:1000::1100:73:2", asn_remote=270620,
        descricao=None, has_password=False, password_path=None,
        keepalive=None, holdtime=None, graceful_restart=False, bfd_enabled=False,
        shutdown=True, afi="ipv6", rp_import=None, rp_export=None,
        maximum_prefix=None, maximum_prefix_threshold=None,
    ) == "bgp 61785\npeer 2804:194C:1000::1100:73:2 as-number 270620\npeer 2804:194C:1000::1100:73:2 shutdown\nipv6-family unicast\n  peer 2804:194C:1000::1100:73:2 enable"


def test_l2vc_ac_porta_fisica_untag() -> None:
    assert _render(
        "l2vc_ac",
        interface="10GE0/0/1", vid=101, inner_vlan=None, encapsulation="dot1q",
        vc_id=1000, remote_loopback="10.255.9.2", control_word=False,
        flow_label=False, mtu=1500, vlanif=False,
    ) == "interface 10GE0/0/1\nundo portswitch\nmtu 1500\nmpls l2vc 10.255.9.2 1000"


def test_l2vc_ac_trunk_flow_label_control_word() -> None:
    assert _render(
        "l2vc_ac",
        interface="Eth-Trunk43", vid=500, inner_vlan=None, encapsulation="dot1q",
        vc_id=1000, remote_loopback="10.255.9.2", control_word=True,
        flow_label=True, mtu=1600, vlanif=False,
    ) == (
        "interface Eth-Trunk43\nundo portswitch\nmtu 1600\n"
        "mpls l2vc 10.255.9.2 1000 control-word\nmpls l2vpn flow-label both"
    )
