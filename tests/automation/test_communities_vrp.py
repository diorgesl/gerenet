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


def test_le_citacao_com_digito_no_nome() -> None:
    """§8.1: `pl-CUSTOMER-AS268061-AS61587-V4` é citado e não tem definição.

    O dígito dentro do nome não pode fazer o nome passar por valor: o que decide
    se o resto da linha é valor é a chave inline, não a presença de número.
    """
    leitura = _leitura("comunidades_vs.txt")
    citados = [u for u in leitura.usos if u.operacao == "cita"]
    assert [u.corpus for u in citados] == ["pl-CUSTOMER-AS268061-AS61587-V4"]
    assert citados[0].filtro == "rm-CUSTOMER-AS268061-V4-IN"
    assert citados[0].corpus_classe == "prefix"
    definidos = {d.nome for d in leitura.definicoes}
    assert "pl-CUSTOMER-AS268061-AS61587-V4" not in definidos


def test_le_o_ultimo_corpus_do_mesmo_nome_vence() -> None:
    """`com-BLACKHOLE` existe nos dois formatos, e o consumidor lê último-vence.

    O helper tem de dar a mesma resposta que o mapa por nome que a task seguinte
    monta, senão o valor aplicado e o valor testado saem de definições diferentes.
    """
    leitura = _leitura("comunidades_edge.txt")
    por_nome = {d.nome: d for d in leitura.definicoes}
    assert leitura.valores_do_corpus("com-BLACKHOLE") == por_nome["com-BLACKHOLE"].valores
    assert leitura.valores_do_corpus("com-BLACKHOLE") == ("61785:666", "65001:666", "37468:666")
    assert leitura.valores_do_corpus("com-EXPORT-UPSTREAM-v4") == ("61785:3001",)
    assert leitura.valores_do_corpus("nao-existe") == ()


def test_le_o_nome_da_prefix_list_de_ipv6() -> None:
    """`if-match ipv6 address prefix-list X`: `address` é palavra da linha, não nome."""
    leitura = parse_communities_vrp(
        "xpl route-filter F\n"
        " if-match ipv6 address prefix-list CYMRU_BOGONS_v6-out\n"
        " end-filter\n"
    )
    assert [u.corpus for u in leitura.usos if u.operacao == "cita"] == ["CYMRU_BOGONS_v6-out"]


def test_le_o_nome_sem_o_parentese_do_if() -> None:
    """O `)` que fecha o `if ( ... )` não é parte do nome citado."""
    leitura = parse_communities_vrp(
        "xpl route-filter F\n"
        " if (ip route-destination in AS264130-PREFIX-v4) then\n"
        "  refuse\n"
        " endif\n"
        " end-filter\n"
    )
    assert [u.corpus for u in leitura.usos if u.operacao == "cita"] == ["AS264130-PREFIX-v4"]


def test_le_as_definicoes_do_xpl_de_prefixo_e_de_as_path() -> None:
    """As duas listas do XPL definem nome como as demais formas.

    Sem elas, a checagem de "citado e não definido" acusaria órfão um nome que o
    equipamento define.
    """
    leitura = parse_communities_vrp(
        "xpl ip-prefix-list BOGONS-v4\n"
        " 0.0.0.0 8,\n"
        " end-list\n"
        "xpl as-path-list PREFIXOS-CLIENTE-v4\n"
        " ^$,\n"
        " end-list\n"
        "xpl route-filter F\n"
        " if ip route-destination in BOGONS-v4 then\n"
        "  refuse\n"
        " endif\n"
        " if as-path in PREFIXOS-CLIENTE-v4 then\n"
        "  refuse\n"
        " endif\n"
        " end-filter\n"
    )
    por_nome = {d.nome: d for d in leitura.definicoes}
    assert por_nome["BOGONS-v4"].sintaxe == "xpl-ip-prefix-list"
    assert por_nome["BOGONS-v4"].classe == "prefix"
    assert por_nome["PREFIXOS-CLIENTE-v4"].sintaxe == "xpl-as-path-list"
    assert por_nome["PREFIXOS-CLIENTE-v4"].classe == "as-path"
    citados = {u.corpus for u in leitura.usos if u.operacao == "cita"}
    assert citados == {"BOGONS-v4", "PREFIXOS-CLIENTE-v4"}
    assert not (citados - set(por_nome))


def test_a_verificacao_de_rpki_nao_vira_citacao() -> None:
    """`if-match rpki origin-as-validation invalid` não referencia corpus nenhum.

    A linha inteira fica fora: o veredito é da validação, e não há nome a citar.
    """
    leitura = parse_communities_vrp(
        "xpl route-filter F\n"
        " if-match rpki origin-as-validation invalid\n"
        " end-filter\n"
    )
    assert leitura.usos == ()


def test_le_o_nome_do_large_community_filter() -> None:
    """`if-match large-community-filter X` cita X, não a palavra da linha."""
    leitura = parse_communities_vrp(
        "ip large-community-filter advanced ARSOFT index 10 permit 61785:100:267702\n"
        "xpl route-filter F\n"
        " if-match large-community-filter ARSOFT\n"
        " end-filter\n"
    )
    citados = [u for u in leitura.usos if u.operacao == "cita"]
    assert [u.corpus for u in citados] == ["ARSOFT"]
    assert citados[0].corpus_classe == "large-community"
    definidos = {d.nome for d in leitura.definicoes}
    assert "ARSOFT" in definidos


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
