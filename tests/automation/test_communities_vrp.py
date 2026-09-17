"""O leitor das communities na configuração (spec §9)."""
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.communities_vrp import (
    parse_communities_vrp,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _leitura(nome: str):
    return parse_communities_vrp((FIXTURES / nome).read_text())


def test_le_as_definicoes_dos_dois_formatos() -> None:
    leitura = _leitura("comunidades_edge.txt")
    por_nome = {d.nome: d for d in leitura.definicoes}

    assert por_nome["com-TRANSITO-FULL"].valores == ("65000:1010",)
    assert por_nome["com-TRANSITO-FULL"].classe == "community"
    assert por_nome["com-TRANSITO-FULL"].sintaxe == "ip-community-filter-advanced"
    # A community-list do XPL: várias linhas, vírgula no fim, `end-list` fechando.
    assert por_nome["com-BLACKHOLE"].valores == ("61785:666", "65001:666", "37468:666")
    assert por_nome["com-BLACKHOLE"].sintaxe == "xpl-community-list"
    # A forma numerada não perde o nome por não ter a palavra `advanced`.
    assert por_nome["2"].valores == ("888",)


def test_le_quem_aplica_e_quem_testa() -> None:
    leitura = _leitura("comunidades_edge.txt")
    aplica_upstream = [
        u for u in leitura.usos
        if u.filtro == "CUSTOMER-BGP-v4" and u.operacao == "aplica" and not u.corpus
    ]
    # `apply community com-EXPORT-UPSTREAM-v4 additive` cita o corpus, não o valor.
    assert aplica_upstream == []
    cita = {u.corpus for u in leitura.usos if u.filtro == "CUSTOMER-BGP-v4" and u.operacao == "aplica"}
    assert cita == {"COMM-SET-BLACKHOLE-OI", "com-EXPORT-UPSTREAM-v4", "com-EXPORT-CDN-v4"}

    portao = [u for u in leitura.usos if u.filtro == "RouteExportCheck" and u.operacao == "testa"]
    negados = [u for u in portao if u.negado]
    assert negados[0].valores == ("61785:7002", "61785:7102", "65000:3001", "65000:4001")
    assert [u.valores for u in portao if not u.negado] == [("65000:991",)]


def test_le_condicao_do_bloco_e_ordem_da_large_community() -> None:
    leitura = _leitura("comunidades_vs.txt")
    ggc = [
        u for u in leitura.usos
        if u.filtro == "XPL-GGC-V4-EXPORT" and u.operacao == "aplica"
    ]
    assert ggc[0].valores == ("15169:12000",)
    assert ggc[0].condicao.startswith("if ip route-destination in {100.64.0.0")

    # A linha 1207 do VS: as duas ordens de large-community no mesmo `apply`.
    erteis = [u for u in leitura.usos if u.operacao == "aplica-large" and u.filtro == "rm-CUSTOMER-AS268061-V4-IN"]
    assert erteis[0].valores == ("61785:14840:4", "61785:666:14840")
    assert erteis[0].additive is True


def test_le_additive_ausente() -> None:
    leitura = _leitura("comunidades_vs.txt")
    v4 = [u for u in leitura.usos if u.filtro == "rm-PARCEIROS_CDN-v4-in" and u.operacao == "aplica"]
    v6 = [u for u in leitura.usos if u.filtro == "rm-PARCEIROS_CDN-v6-in" and u.operacao == "aplica"]
    assert v4[0].additive is True
    assert v6[0].additive is False


def test_le_citacao_sem_definicao() -> None:
    leitura = _leitura("comunidades_edge.txt")
    citados = {u.corpus for u in leitura.usos if u.operacao == "cita"}
    assert "MEU-PREFIXOS" in citados
    definidos = {d.nome for d in leitura.definicoes}
    assert "MEU-PREFIXOS" not in definidos


def test_le_os_grupos_de_peer_e_os_membros() -> None:
    leitura = _leitura("comunidades_vs.txt")
    por_nome = {a.nome: a for a in leitura.alvos}
    assert por_nome["IX-CG"].asn == 26162
    assert por_nome["IX-CG"].membros == ("45.227.2.253",)
    assert por_nome["EQUINIX_SP"].membros == ("64.191.232.250",)


def test_le_o_asn_do_bloco_bgp() -> None:
    assert _leitura("comunidades_edge.txt").asn_local == 61785
    assert _leitura("comunidades_vs.txt").asn_local == 61785


def test_texto_vazio_nao_estoura() -> None:
    leitura = parse_communities_vrp("")
    assert leitura.asn_local is None
    assert leitura.definicoes == () and leitura.usos == () and leitura.alvos == ()
