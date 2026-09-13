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


def test_vsi_vazio() -> None:
    assert parse_template("vsi", "") == []


def test_vsi_verbose_real() -> None:
    """S6730: `display vsi verbose` é um bloco por VSI (***VSI Name / VSI State / VSI ID).

    Há um VSI órfão na rede (VLAN653_INTECH]) sem VSI ID nem peer — sem ID não
    casa com a SoT e o bloco não fecha Registro, então o parse o descarta.
    """
    linhas = parse_template("vsi", _real("s6730_display_vsi_verbose.txt"))
    assert len(linhas) == 9
    assert {"name": "IntechCDN", "vsi_id": "2827", "estado": "up"} in linhas
    assert {"name": "VLAN4030", "vsi_id": "4030", "estado": "down"} in linhas
    assert not any(l.get("name") == "VLAN653_INTECH]" for l in linhas)


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


def test_merge_vsi_normaliza_verbose() -> None:
    assert merge_parsed("vsi", {"display vsi verbose": [
        {"name": "IntechCDN", "vsi_id": "2827", "estado": "up"},
        {"name": "VSI-SEM-ID", "vsi_id": "", "estado": "down"},
    ]}) == [
        {"name": "IntechCDN", "vsi_id": 2827, "estado": "up"},
        {"name": "VSI-SEM-ID", "vsi_id": None, "estado": "down"},
    ]


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
