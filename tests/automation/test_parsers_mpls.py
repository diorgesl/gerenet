"""Parsers MPLS — fase 4, spec §8, ajustados ao output real da família S (2026-09-08).

O VRP do S6730 imprime formatos diferentes dos assumidos na fase 4:
`display mpls ldp peer` vem como tabela SEM estado, `display mpls l2vc` em
blocos por VC e `display vsi verbose` em blocos por VSI (VSI State antes do
VSI ID). Fixtures reais (sanitizadas) em `tests/fixtures/huawei_vrp/s6730_*`.

`parse_template` devolve os valores crus do TextFSM (strings, sem normalização);
a normalização de tipos/estado ("up"/"down", peer sem o sufixo `:0`, int,
estado `None` quando o comando não o imprime) é contrato do merge (docstring de
merge.py) — os testes de parse usam os valores crus, e os testes de merge usam
merge_parsed.
"""
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.merge import merge_parsed
from gerenet.automation.parsers.huawei_vrp.registry import parse_template

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "huawei_vrp"


def _real(nome_arquivo: str) -> str:
    """Lê uma fixture real (saída do switch sem o prompt do hostname)."""
    return (_FIXTURES / nome_arquivo).read_text(encoding="utf-8")


def test_mpls_ldp_peer_vazio() -> None:
    assert parse_template("mpls_ldp_peer", "") == []


def test_mpls_ldp_peer_tabela_real_sem_estado() -> None:
    """S6730: tabela PeerID/TransportAddress/DiscoverySource, sem coluna de estado.

    Estado do peer não existe nesse comando — o merge devolve `estado: None`
    (desconhecido), nunca "down".
    """
    linhas = parse_template("mpls_ldp_peer", _real("s6730_display_mpls_ldp_peer.txt"))
    assert len(linhas) == 8  # cabeçalho e linhas de continuação não viram peer
    assert {"peer_id": "100.127.90.251:0", "transport": "100.127.90.251",
            "discovery": "Eth-Trunk9"} in linhas
    assert {"peer_id": "100.127.90.255:0", "transport": "100.127.90.255",
            "discovery": "Remote Peer : 100.127.90.255"} in linhas
    assert all("estado" not in linha for linha in linhas)


def test_l2vc_vazio() -> None:
    assert parse_template("l2vc", "") == []


def test_l2vc_blocos_reais() -> None:
    """S6730: bloco por VC com AC status e MTU local/remoto (fixture real)."""
    linhas = parse_template("l2vc", _real("s6730_display_mpls_l2vc.txt"))
    assert len(linhas) == 4
    assert {"vc_id": "21", "interface": "Vlanif21", "estado": "up", "ac_status": "up",
            "mtu_local": "9216", "mtu_remoto": "9216"} in linhas
    assert {"vc_id": "627", "interface": "Vlanif627", "estado": "down", "ac_status": "up",
            "mtu_local": "9216", "mtu_remoto": "0"} in linhas


def test_merge_l2vc_extrai_ac_e_mtu() -> None:
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "21", "interface": "Vlanif21", "estado": "up", "ac_status": "up",
         "mtu_local": "9216", "mtu_remoto": "9216"},
    ]}) == [{"vc_id": 21, "interface": "Vlanif21", "estado": "up",
             "ac_status": "up", "mtu_local": 9216, "mtu_remoto": 9216}]


def test_merge_l2vc_sem_mtu_fica_none() -> None:
    """Bloco sem as linhas de MTU/AC não inventa valor."""
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "1000", "interface": None, "estado": "Down"},
    ]}) == [{"vc_id": 1000, "interface": None, "estado": "down",
             "ac_status": None, "mtu_local": None, "mtu_remoto": None}]


def test_merge_l2vc_vc_id_vazio_descarta_linha() -> None:
    """`vc_id` vazio (sentinel do TextFSM, não None) descarta a linha, sem estourar.

    Com o Record na linha do MTU, um bloco que imprima o MTU sem o `VC ID`
    fecha registro com `vc_id` em `''` (o TextFSM nunca devolve None) — o guard
    é de vazio, não de None.
    """
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "", "interface": None, "estado": "Up",
         "ac_status": None, "mtu_local": None, "mtu_remoto": None},
    ]}) == []


def test_vsi_vazio() -> None:
    assert parse_template("vsi", "") == []


def test_vsi_verbose_tres_niveis() -> None:
    """S6730: o bloco traz VSI, peer e AC — o parse devolve uma linha por nível."""
    linhas = parse_template("vsi", _real("s6730_display_vsi_verbose.txt"))
    assert {"name": "IntechCDN", "estado": "up", "vsi_id": "2827", "mtu": "1500",
            "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""} in linhas
    assert {"name": "IntechCDN", "peer": "100.127.90.255", "peer_estado": "up",
            "vsi_id": "", "ac_if": "", "estado": "", "mtu": "",
            "ac_estado": ""} in linhas
    assert {"name": "IntechCDN", "ac_if": "Vlanif2827", "ac_estado": "up",
            "vsi_id": "", "peer": "", "estado": "", "mtu": "",
            "peer_estado": ""} in linhas


def test_merge_ldp_tabela_sem_estado_vira_none() -> None:
    """Tabela da família S não imprime estado: None — nunca "down" (não confundir desconhecido com down)."""
    assert merge_parsed("mpls_ldp_peer", {"display mpls ldp peer": [
        {"peer_id": "100.127.90.251:0", "transport": "100.127.90.251", "discovery": "Eth-Trunk9"},
    ]}) == [{"peer_id": "100.127.90.251", "estado": None}]


def test_merge_ldp_normaliza_estado_impresso() -> None:
    """Estado impresso (Up/Down) continua normalizado quando a fonte o tiver."""
    assert merge_parsed("mpls_ldp_peer", {"display mpls ldp peer": [
        {"peer_id": "10.255.9.2:0", "estado": "Up"},
        {"peer_id": "10.255.9.3:0", "estado": "Down"},
    ]}) == [
        {"peer_id": "10.255.9.2", "estado": "up"},
        {"peer_id": "10.255.9.3", "estado": "down"},
    ]


def test_merge_l2vc_normaliza_blocos() -> None:
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "21", "interface": "Vlanif21", "estado": "up"},
        {"vc_id": "627", "interface": "Vlanif627", "estado": "down"},
    ]}) == [
        {"vc_id": 21, "interface": "Vlanif21", "estado": "up",
         "ac_status": None, "mtu_local": None, "mtu_remoto": None},
        {"vc_id": 627, "interface": "Vlanif627", "estado": "down",
         "ac_status": None, "mtu_local": None, "mtu_remoto": None},
    ]
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "1000", "interface": None, "estado": "Down"},
    ]}) == [{"vc_id": 1000, "interface": None, "estado": "down",
             "ac_status": None, "mtu_local": None, "mtu_remoto": None}]


def test_merge_vsi_agrupa_por_nome() -> None:
    assert merge_parsed("vsi", {"display vsi verbose": [
        {"name": "IntechCDN", "estado": "up", "vsi_id": "2827", "mtu": "1500",
         "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""},
        {"name": "IntechCDN", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "100.127.90.255", "peer_estado": "up", "ac_if": "", "ac_estado": ""},
        {"name": "IntechCDN", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "Vlanif2827", "ac_estado": "up"},
    ]}) == [{
        "name": "IntechCDN", "vsi_id": 2827, "estado": "up", "mtu": 1500,
        "peers": [{"peer": "100.127.90.255", "estado": "up"}],
        "acs": [{"interface": "Vlanif2827", "estado": "up"}],
    }]


def test_merge_vsi_fixture_real() -> None:
    """Nove VSIs com ID; o bloco quebrado (nome sem ID) não entra, nem o AC dele."""
    linhas = merge_parsed("vsi", {
        "display vsi verbose": parse_template("vsi", _real("s6730_display_vsi_verbose.txt")),
    })
    assert len(linhas) == 9
    por_nome = {l["name"]: l for l in linhas}
    assert por_nome["IntechCDN"]["peers"] == [{"peer": "100.127.90.255", "estado": "up"}]
    assert por_nome["IntechCDN"]["acs"] == [{"interface": "Vlanif2827", "estado": "up"}]
    assert por_nome["VLAN4030"]["estado"] == "down"
    assert por_nome["VLAN4030"]["peers"] == [{"peer": "100.127.90.247", "estado": "down"}]
    assert por_nome["VLAN4004"]["mtu"] == 9216
    assert not any(l["name"].endswith("]") for l in linhas)


def test_merge_vsi_bloco_sem_id_descarta_o_ac_junto() -> None:
    """Bloco truncado com AC não pode herdar o VSI anterior (o nome é o único filldown)."""
    assert merge_parsed("vsi", {"display vsi verbose": [
        {"name": "BOM", "estado": "up", "vsi_id": "10", "mtu": "9100",
         "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""},
        {"name": "BOM", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "Vlanif10", "ac_estado": "up"},
        {"name": "ORFAO]", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "Vlanif99", "ac_estado": "up"},
    ]}) == [{
        "name": "BOM", "vsi_id": 10, "estado": "up", "mtu": 9100,
        "peers": [], "acs": [{"interface": "Vlanif10", "estado": "up"}],
    }]


def test_merge_vsi_estado_desconhecido_fica_none() -> None:
    """`VSI ID` sem estado reconhecível não vira "down" por omissão.

    Linha de `VSI State` ausente ou com sentinela (`--`) é desconhecido — o
    enum de `operational_status` tem `unknown` exatamente para isso, e quem
    grava (o sync) é que decide o que fazer com o None.
    """
    assert merge_parsed("vsi", {"display vsi verbose": [
        {"name": "SEM-ESTADO", "estado": "", "vsi_id": "10", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""},
        {"name": "SENTINELA", "estado": "--", "vsi_id": "11", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""},
    ]}) == [
        {"name": "SEM-ESTADO", "vsi_id": 10, "estado": None, "mtu": None,
         "peers": [], "acs": []},
        {"name": "SENTINELA", "vsi_id": 11, "estado": None, "mtu": None,
         "peers": [], "acs": []},
    ]


def test_merge_vsi_peer_e_ac_sem_estado_ficam_none() -> None:
    """Peer e AC sem a linha de estado no grupo continuam com `estado=None`.

    O `display vsi verbose` imprime o estado do peer (`Session`) e do AC
    (`Interface State`) em linhas próprias: quando elas não vêm — bloco
    truncado no meio —, o item permanece no grupo como desconhecido, nunca
    virando "down" por omissão (mesma regra do estado do VSI). O pós-check
    trata o None como crítico, então o item precisa existir para ser acusado.
    """
    assert merge_parsed("vsi", {"display vsi verbose": [
        {"name": "SEM-ESTADOS", "estado": "up", "vsi_id": "10", "mtu": "1500",
         "peer": "", "peer_estado": "", "ac_if": "", "ac_estado": ""},
        {"name": "SEM-ESTADOS", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "10.255.9.2", "peer_estado": "", "ac_if": "", "ac_estado": ""},
        {"name": "SEM-ESTADOS", "estado": "", "vsi_id": "", "mtu": "",
         "peer": "", "peer_estado": "", "ac_if": "Vlanif10", "ac_estado": ""},
    ]}) == [{
        "name": "SEM-ESTADOS", "vsi_id": 10, "estado": "up", "mtu": 1500,
        "peers": [{"peer": "10.255.9.2", "estado": None}],
        "acs": [{"interface": "Vlanif10", "estado": None}],
    }]


def test_merge_vazios_devolvem_lista() -> None:
    assert merge_parsed("mpls_ldp_peer", {}) == []
    assert merge_parsed("l2vc", {}) == []
    assert merge_parsed("vsi", {}) == []


def test_mpls_ldp_session_vazio() -> None:
    assert parse_template("mpls_ldp_session", "") == []


def test_mpls_ldp_session_real() -> None:
    """S6730: tabela PeerID/Status/LAM/SsnRole/SsnAge/KASent-Rcv, 8 sessões."""
    linhas = parse_template("mpls_ldp_session", _real("s6730_display_mpls_ldp_session.txt"))
    assert len(linhas) == 8
    assert {"peer_id": "100.127.90.251:0", "status": "Operational"} in linhas
    assert {"peer_id": "100.127.90.10:0", "status": "Operational"} in linhas


def test_mpls_ldp_session_sessao_em_remocao() -> None:
    """O `*` de sessão em deleção não entra no peer_id."""
    saida = (
        " PeerID             Status      LAM  SsnRole  SsnAge      KASent/Rcv\n"
        "*10.255.9.2:0       Operational DU   Passive  0000:00:02  5/5\n"
    )
    assert parse_template("mpls_ldp_session", saida) == [
        {"peer_id": "10.255.9.2:0", "status": "Operational"},
    ]


def test_merge_ldp_cruza_peer_e_sessao() -> None:
    """Sessão Operational ⇒ up; outro status ⇒ down; peer sem linha ⇒ None."""
    assert merge_parsed("mpls_ldp_peer", {
        "display mpls ldp peer": [
            {"peer_id": "100.127.90.251:0", "transport": "100.127.90.251", "discovery": "Eth-Trunk9"},
            {"peer_id": "100.127.90.253:0", "transport": "100.127.90.253", "discovery": "Remote Peer"},
            {"peer_id": "100.127.90.254:0", "transport": "100.127.90.254", "discovery": "Vlanif10"},
        ],
        "display mpls ldp session": [
            {"peer_id": "100.127.90.251:0", "status": "Operational"},
            {"peer_id": "100.127.90.253:0", "status": "Initialized"},
        ],
    }) == [
        {"peer_id": "100.127.90.251", "estado": "up"},
        {"peer_id": "100.127.90.253", "estado": "down"},
        {"peer_id": "100.127.90.254", "estado": None},
    ]


def test_merge_ldp_fixtures_reais_casam_por_peer() -> None:
    """As duas fixtures reais do S6730 têm os mesmos 8 peers, todos Operational."""
    linhas = merge_parsed("mpls_ldp_peer", {
        "display mpls ldp peer": parse_template("mpls_ldp_peer", _real("s6730_display_mpls_ldp_peer.txt")),
        "display mpls ldp session": parse_template("mpls_ldp_session", _real("s6730_display_mpls_ldp_session.txt")),
    })
    assert len(linhas) == 8
    assert {l["estado"] for l in linhas} == {"up"}
    assert {l["peer_id"] for l in linhas} == {
        "100.127.90.251", "100.127.90.253", "100.127.90.254", "100.127.90.255",
        "100.127.90.2", "100.127.90.3", "100.127.90.5", "100.127.90.10",
    }


def test_merge_ldp_sessao_sem_peer_na_tabela_e_ignorada() -> None:
    assert merge_parsed("mpls_ldp_peer", {
        "display mpls ldp peer": [
            {"peer_id": "10.255.9.2:0", "transport": "10.255.9.2", "discovery": "Vlanif10"},
        ],
        "display mpls ldp session": [
            {"peer_id": "10.255.9.2:0", "status": "Operational"},
            {"peer_id": "10.255.9.9:0", "status": "Operational"},
        ],
    }) == [{"peer_id": "10.255.9.2", "estado": "up"}]
