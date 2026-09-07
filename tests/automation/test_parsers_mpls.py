"""Parsers MPLS — fase 4, spec §8.

parse_template devolve os valores crus do TextFSM (strings, sem normalização);
a normalização de tipos/estado ("up"/"down", peer sem o sufixo `:0`, int) é
contrato do merge (docstring de merge.py) — os testes de parse usam os valores
cru, e os testes de merge usam merge_parsed.
"""
from gerenet.automation.parsers.huawei_vrp.merge import merge_parsed
from gerenet.automation.parsers.huawei_vrp.registry import parse_template


def test_mpls_ldp_peer_vazio() -> None:
    assert parse_template("mpls_ldp_peer", "") == []


def test_mpls_ldp_peer_cheio() -> None:
    saida = """
 Peer LDP ID : 10.255.9.2:0
  State       : Up
 Peer LDP ID : 10.255.9.3:0
  State       : Down
"""
    linhas = parse_template("mpls_ldp_peer", saida)
    # Valores crus: peer_id traz o sufixo `:0` e estado vem como impresso (Up/Down).
    assert {"peer_id": "10.255.9.2:0", "estado": "Up"} in linhas
    assert {"peer_id": "10.255.9.3:0", "estado": "Down"} in linhas


def test_l2vc_vazio_e_cheio() -> None:
    assert parse_template("l2vc", "") == []
    saida = """
 0 : VC-ID : 1000, Interface : 10GE0/0/1, State : Up
 1 : VC-ID : 1001, Interface : 10GE0/0/2, State : Down
"""
    linhas = parse_template("l2vc", saida)
    assert {"vc_id": "1000", "interface": "10GE0/0/1", "estado": "Up"} in linhas
    assert {"vc_id": "1001", "interface": "10GE0/0/2", "estado": "Down"} in linhas


def test_l2vc_sem_indice_derivado() -> None:
    # Derivado (sintético): algumas versões não imprimem o índice inicial
    # ("0 :") — o regex o trata como opcional.
    saida = "VC-ID : 1002, Interface : 10GE0/0/3, State : Up\n"
    assert parse_template("l2vc", saida) == [
        {"vc_id": "1002", "interface": "10GE0/0/3", "estado": "Up"},
    ]


def test_vsi_vazio_e_cheio() -> None:
    assert parse_template("vsi", "") == []
    saida = """
VSI Name : VSI-CLIENTE-ACME-550        VSI ID : 550
  State       : up
"""
    linhas = parse_template("vsi", saida)
    assert {"name": "VSI-CLIENTE-ACME-550", "vsi_id": "550", "estado": "up"} in linhas


def test_merge_normaliza_ldp_l2vc_vsi() -> None:
    """O merge normaliza o que o parse devolve cru (§4.3 tipos + estados)."""
    assert merge_parsed("mpls_ldp_peer", {"display mpls ldp peer": [
        {"peer_id": "10.255.9.2:0", "estado": "Up"},
        {"peer_id": "10.255.9.3:0", "estado": "Down"},
    ]}) == [
        {"peer_id": "10.255.9.2", "estado": "up"},
        {"peer_id": "10.255.9.3", "estado": "down"},
    ]
    assert merge_parsed("l2vc", {"display l2vc": [
        {"vc_id": "1000", "interface": "10GE0/0/1", "estado": "Up"},
        {"vc_id": "1001", "interface": None, "estado": "Down"},
    ]}) == [
        {"vc_id": 1000, "interface": "10GE0/0/1", "estado": "up"},
        {"vc_id": 1001, "interface": None, "estado": "down"},
    ]
    assert merge_parsed("vsi", {"display vsi": [
        {"name": "VSI-CLIENTE-ACME-550", "vsi_id": "550", "estado": "up"},
        {"name": "VSI-SEM-ID", "vsi_id": "", "estado": "down"},
    ]}) == [
        {"name": "VSI-CLIENTE-ACME-550", "vsi_id": 550, "estado": "up"},
        {"name": "VSI-SEM-ID", "vsi_id": None, "estado": "down"},
    ]


def test_merge_vazios_devolvem_lista() -> None:
    assert merge_parsed("mpls_ldp_peer", {}) == []
    assert merge_parsed("l2vc", {}) == []
    assert merge_parsed("vsi", {}) == []
