"""A validação do plano (spec §8) sobre as leituras das duas capturas."""
from dataclasses import replace
from pathlib import Path

from gerenet.automation.community_plan import (
    Achado,
    AlvoPlano,
    ClassePlano,
    InstrucaoPlano,
    PlanoLido,
    PortaoPlano,
    validar,
)
from gerenet.automation.parsers.huawei_vrp.communities_vrp import parse_communities_vrp

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _leitura(nome: str):
    return parse_communities_vrp((FIXTURES / nome).read_text())


def _plano() -> PlanoLido:
    """O vocabulário da §6.1, com os nomes que o plano teria depois da adoção."""
    return PlanoLido(
        asn_principal=61785,
        classes=(
            ClassePlano(nome="com-TECMAIS-v4", banda="cliente", tipo="tag_produto", valor_v4=3001, valor_v6=3101),
            ClassePlano(nome="com-PARCEIROS_CDN-v4", banda="parceiro", tipo="tag_produto", valor_v4=4001, valor_v6=4101),
            ClassePlano(nome="com-TRANSITO-FULL", banda="transito", tipo="tag_produto", valor_v4=1010, valor_v6=1010),
            ClassePlano(nome="com-ONLY-CDN", banda="especial", tipo="tag_produto", valor_v4=991, valor_v6=991),
            ClassePlano(nome="com-TAMANHO-2", banda="tamanho", tipo="tag_produto", valor_v4=7002, valor_v6=7102),
            ClassePlano(nome="com-TAMANHO-1", banda="tamanho", tipo="tag_produto", valor_v4=7001, valor_v6=7101),
        ),
        instrucoes=(
            InstrucaoPlano(nome="com-BLACKHOLE-DENY", codigo=666),
        ),
        portoes=(
            PortaoPlano(nome="RouteExportCheck", papel="upstream", afi="ipv4", padrao="recusar",
                        aceitas=("com-TAMANHO-2", "com-TECMAIS-v4"), recusadas=("com-ONLY-CDN",)),
        ),
        alvos=(AlvoPlano(nome="MSD-CDN-v4", papel="cdn", codigo_v4=53062),),
    )


def _codigos(achados: tuple[Achado, ...]) -> dict[str, list[Achado]]:
    saida: dict[str, list[Achado]] = {}
    for achado in achados:
        saida.setdefault(achado.codigo, []).append(achado)
    return saida


def test_achado_da_secao_8_1_classe_aplicada_e_nao_testada() -> None:
    """§8.1: o portão testa o que ninguém aplica, e o filtro aplica o que o portão
    não testa — as classes novas (`61785:3001`, `61785:4001`) não estão em portão
    nenhum, e o upstream recusaria toda rota de cliente em silêncio."""
    achados = validar(_plano(), [_leitura("comunidades_edge.txt")])
    por_codigo = _codigos(achados)

    nao_testadas = {a.valor for a in por_codigo["classe_aplicada_nao_testada"]}
    assert "61785:3001" in nao_testadas
    assert "61785:4001" in nao_testadas
    assert all(a.severidade == "critico" for a in por_codigo["classe_aplicada_nao_testada"])


def test_achado_da_secao_8_1_ordem_da_large_community() -> None:
    """§8.1: as duas ordens na mesma linha do VS (`apply large-community
    61785:14840:4 61785:666:14840 additive`), e a inversa é apontada uma vez."""
    achados = validar(_plano(), [_leitura("comunidades_vs.txt")])
    invertidas = [
        a for a in achados if a.codigo == "ordem_invertida" and a.valor == "61785:14840:4"
    ]
    assert len(invertidas) == 1
    assert invertidas[0].filtro == "rm-CUSTOMER-AS268061-V4-IN"
    assert invertidas[0].linha is not None  # a linha da fixture, que é um recorte


def test_achado_da_secao_8_1_nome_citado_e_nao_definido() -> None:
    """§8.1: `MEU-PREFIXOS` é citado em `UPSTREAM-V4-IMPORT` e não existe."""
    achados = validar(_plano(), [_leitura("comunidades_edge.txt")])
    orfaos = [a for a in achados if a.codigo == "nome_nao_definido"]
    assert [a.valor for a in orfaos] == ["MEU-PREFIXOS"]
    assert orfaos[0].filtro == "UPSTREAM-V4-IMPORT"


def test_achado_da_secao_8_1_familia_trocada_na_marca_de_tamanho() -> None:
    """§8.1: `BGP-IPV4-CUSTOMER` aplica valores v6 em rota v4."""
    texto = """
xpl route-filter BGP-IPV4-CUSTOMER
 if (ip route-destination in {0.0.0.0 0 le 22}) then
  apply community 61785:7001 additive
  approve
 endif
 if (ip route-destination in {0.0.0.0 0 le 23}) then
  apply community 65000:7101 additive
  approve
 endif
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    trocadas = [a for a in achados if a.codigo == "familia_incoerente" and a.valor == "65000:7101"]
    assert len(trocadas) == 1 and trocadas[0].filtro == "BGP-IPV4-CUSTOMER"


def test_valor_coerente_com_a_familia_do_filtro_nao_vira_achado() -> None:
    """§8, checagem 2: o dígito do valor e a família do filtro concordam.

    `65000:4001` é dígito v4 num filtro `-v4-`, e é o caso comum da captura: o
    `rm-PARCEIROS_CDN-v4-in` aplica exatamente ele. Se a família do valor e a do
    filtro forem comparadas em grafias diferentes, o caso conforme sai como
    `familia_incoerente` e o painel da §11 enche de falso positivo.
    """
    texto = """
xpl route-filter rm-PARCEIROS_CDN-v4-in
 apply community 65000:4001 additive
 end-filter
xpl route-filter rm-PARCEIROS_CDN-v6-in
 apply community 65000:4101 additive
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    assert [a for a in achados if a.codigo == "familia_incoerente"] == []


def test_valor_incoerente_e_um_achado_so_com_filtro_e_linha() -> None:
    """§8, checagem 2: o incoerente sai, e sai sozinho.

    O filtro aplica dois valores, `61785:7001` (dígito v4 em filtro v4) e
    `65000:7101` (dígito v6 no mesmo filtro). Só o segundo é defeito; o achado
    do primeiro é o falso positivo que a comparação em duas grafias produzia.
    """
    texto = """
xpl route-filter BGP-IPV4-CUSTOMER
 apply community 61785:7001 additive
 apply community 65000:7101 additive
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    trocadas = [a for a in achados if a.codigo == "familia_incoerente"]
    assert len(trocadas) == 1
    assert trocadas[0].valor == "65000:7101"
    assert trocadas[0].filtro == "BGP-IPV4-CUSTOMER"
    assert trocadas[0].linha is not None
    assert trocadas[0].descricao == (
        "65000:7101 é um valor de v6 em BGP-IPV4-CUSTOMER, que é v4"
    )


def test_portao_com_a_familia_colada_no_nome() -> None:
    """§4.4: o portão v6 da casa se chama `RouteExportCheckV6`, com o `V6` colado.

    Reconhecer só as formas separadas (`ipv6`, `-v6`, `_v6`, `v6-`) deixa este
    portão cair no consenso dos valores, que falha num portão de duas famílias
    (`61785:7012` com `61785:7112`). O `61785:7012` é dígito v4 dentro de portão
    v6 e está na lista que a §6.1 manda migrar, então é achado que a §8 pede e
    que não sai enquanto o nome colado não for reconhecido.
    """
    texto = """
xpl route-filter RouteExportCheckV6
 if not community matches-any {61785:7012, 61785:7112, 65000:3101, 65000:4101} then
  refuse
 endif
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    trocadas = [a for a in achados if a.codigo == "familia_incoerente"]
    assert [a.valor for a in trocadas] == ["61785:7012"]
    assert trocadas[0].filtro == "RouteExportCheckV6"
    assert trocadas[0].descricao == (
        "61785:7012 é um valor de v4 em RouteExportCheckV6, que é v6"
    )


def test_achado_da_secao_8_1_apply_sem_additive() -> None:
    """§8.1: o mesmo par, a mesma classe, `additive` no v4 e não no v6 — e as
    seis linhas de import de cliente do VS, que aplicam a classe sem ele."""
    direcoes = {
        "rm-PARCEIROS_CDN-v4-in": "import",
        "rm-PARCEIROS_CDN-v6-in": "import",
        "rm-CUSTOMER-AS268061-V4-IN": "import",
    }
    achados = validar(_plano(), [_leitura("comunidades_vs.txt")], direcoes=direcoes)
    sem_additive = [a for a in achados if a.codigo == "community_sem_additive"]
    filtros = {a.filtro for a in sem_additive}
    assert "rm-PARCEIROS_CDN-v6-in" in filtros
    assert "rm-PARCEIROS_CDN-v4-in" not in filtros
    # `rm-CUSTOMER-AS268061-V4-IN` aplica `65000:4001` sem `additive` e é uma
    # das seis linhas de import de cliente da §8.1 (1207 da captura): o achado
    # sai para ele também.
    assert "rm-CUSTOMER-AS268061-V4-IN" in filtros


def test_achado_da_secao_8_1_instrucao_sem_portao() -> None:
    """§8.1: `com-TRANSITO-FULL` é aplicada no import e nenhum portão a considera."""
    texto = """
xpl route-filter ASN6762-V4-IMPORT($preference)
 apply community 65000:1010 additive
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    por_codigo = _codigos(achados)
    sem_portao = {a.valor for a in por_codigo.get("classe_aplicada_nao_testada", [])}
    assert "65000:1010" in sem_portao


def test_plano_conforme_nao_produz_achado_critico() -> None:
    texto = """
xpl route-filter CLASSIFICA-V4
 apply community 61785:3001 additive
 end-filter
xpl route-filter RouteExportCheck
 if not community matches-any {61785:3001} then
  refuse
 endif
 end-filter
"""
    plano = PlanoLido(
        asn_principal=61785,
        classes=(ClassePlano(nome="com-TECMAIS-v4", banda="cliente", tipo="tag_produto", valor_v4=3001),),
    )
    achados = validar(plano, [parse_communities_vrp(texto)])
    assert [a for a in achados if a.severidade == "critico"] == []


def test_alvo_sem_sessao_e_codigo_orfao() -> None:
    texto = """
xpl route-filter QUALQUER
 apply large-community 61785:9999:14840 additive
 end-filter
"""
    achados = validar(
        _plano(),
        [parse_communities_vrp(texto)],
        estados_alvo={"MSD-CDN-v4": "parado"},
    )
    por_codigo = _codigos(achados)
    assert [a.valor for a in por_codigo["codigo_orfao"]] == ["61785:9999:14840"]
    assert [a.valor for a in por_codigo["alvo_sem_sessao"]] == ["MSD-CDN-v4"]


def test_alvo_sem_linha_em_community_targets() -> None:
    """§8, checagem 3, segunda metade: o alvo de uma instrução do plano sem linha em
    `community_targets`.

    `61785:666:14840` é uma instrução do plano (666) apontada para o AS14840, que
    não tem linha de alvo; `61785:14840:4` é a mesma linha na ordem invertida, e a
    segunda metade da checagem **não** fala dela: o código 4 não é instrução
    deste plano recortado, então não há alvo de instrução para conferir.
    """
    achados = validar(_plano(), [_leitura("comunidades_vs.txt")])
    por_codigo = _codigos(achados)
    sem_linha = [a.valor for a in por_codigo.get("alvo_sem_target", [])]
    assert sem_linha == ["61785:666:14840"]
    assert por_codigo["alvo_sem_target"][0].severidade == "informativo"


def test_plano_sem_codigo_de_alvo_avisa_uma_vez() -> None:
    """R58: sem nenhum código de alvo declarado, a segunda metade da checagem 3 não
    pode conferir o alvo das instruções — e diz isso **uma vez**, não uma por valor
    da configuração.

    Um código nulo não pode virar `alvos_do_plano = {None}`: aí o `not in` casaria
    com todo alvo e a checagem acusaria em falso, que é o defeito que esta pinagem
    fecha.
    """
    plano = replace(_plano(), alvos=(AlvoPlano(nome="MSD-CDN-v4", papel="cdn"),))
    achados = validar(plano, [_leitura("comunidades_vs.txt")])
    de_plano = [a for a in achados if a.codigo == "alvo_sem_target"]
    assert len(de_plano) == 1
    assert de_plano[0].valor is None
    assert "não declara código de alvo" in de_plano[0].descricao


def test_codigo_de_borda_testado_nao_e_orfao() -> None:
    """§6.2: o prepend de borda vale `nível × 11` (`11`/`22`/`33`).

    A captura real o testa em `if large-community matches-all {61785:11:14840}`
    (TECMAIS 4744). Sem os códigos de borda no vocabulário, a checagem 3
    chamaria de órfão um código que o plano tem — e são três achados falsos na
    configuração real.
    """
    texto = """
xpl route-filter RouteExportCheck-BORDA
 if large-community matches-all {61785:11:14840} then
  refuse
 endif
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    assert [a for a in achados if a.codigo == "codigo_orfao"] == []


def test_ordem_invertida_com_codigo_de_borda() -> None:
    """§8, checagem 4: o código de borda invertido é apontado como os demais.

    `61785:14840:11` põe o alvo no campo do meio e o código no último, o
    contrário do que o vocabulário fixa — o mesmo defeito da §8.1, num código
    que só existe do lado da borda.
    """
    texto = """
xpl route-filter XPL-GGC-V4-EXPORT
 if large-community matches-any {61785:14840:11} then
  refuse
 endif
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    invertidas = [a for a in achados if a.codigo == "ordem_invertida"]
    assert [a.valor for a in invertidas] == ["61785:14840:11"]
    assert invertidas[0].filtro == "XPL-GGC-V4-EXPORT"


def test_colisao_entre_namespaces() -> None:
    """O mesmo 2 bytes com dois nomes de significado diferente (§8, checagem 5)."""
    texto = """
ip community-filter advanced com-CUSTOMER-CLIENTE-v4 index 10 permit 65000:7001
ip community-filter advanced com-TAMANHO-1-v4 index 10 permit 65000:7001
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    colisoes = [a for a in achados if a.codigo == "colisao_namespace"]
    assert [a.valor for a in colisoes] == ["65000:7001"]


def test_vocabulario_fora_da_particao_e_apontado() -> None:
    plano = PlanoLido(
        asn_principal=61785,
        classes=(
            ClassePlano(nome="com-ERRADA", banda="cliente", tipo="tag_produto", valor_v4=7103),
            ClassePlano(nome="com-SEM-BANDA", tipo="tag_produto", valor_v4=3002),
        ),
    )
    achados = validar(plano, [])
    problemas = {a.valor for a in achados if a.codigo == "valor_fora_da_particao"}
    assert problemas == {"com-ERRADA", "com-SEM-BANDA"}
