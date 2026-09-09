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
    """S6730: `display mpls l2vc` é um bloco por VC (client interface / VC state / VC ID)."""
    linhas = parse_template("l2vc", _real("s6730_display_mpls_l2vc.txt"))
    assert len(linhas) == 4
    assert {"vc_id": "21", "interface": "Vlanif21", "estado": "up"} in linhas
    assert {"vc_id": "627", "interface": "Vlanif627", "estado": "down"} in linhas
    assert {"vc_id": "633", "interface": "Vlanif633", "estado": "up"} in linhas


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
        {"vc_id": 21, "interface": "Vlanif21", "estado": "up"},
        {"vc_id": 627, "interface": "Vlanif627", "estado": "down"},
    ]
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "1000", "interface": None, "estado": "Down"},
    ]}) == [{"vc_id": 1000, "interface": None, "estado": "down"}]


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
