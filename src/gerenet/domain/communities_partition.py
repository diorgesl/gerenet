"""A partição do plano de communities (spec §5) como contrato verificável.

A partição existe para que um valor novo não precise de reunião para ser
atribuído e para que a validação consiga reprovar um valor no lugar errado. Ela
**não** é porteiro de escrita: valor fora de faixa é exceção legítima e entra no
plano para ser apontado (§14.4). O serviço de catálogo só recusa o que é sempre
erro de digitação — a família na coluna errada.

O padrão de quatro dígitos é `[classe][família][item]`, com família `0` para v4
e `1` para v6, e as exceções da §5 ficam nomeadas aqui em vez de escondidas.
"""

# `instrucao` fica fora de propósito: o código da large-community não é um valor
# de 2 bytes e não pertence a faixa nenhuma.
FAIXAS: dict[str, tuple[int, int]] = {
    "local": (1, 99),
    "especial": (900, 999),
    "transito": (1000, 1999),
    "cliente": (3000, 3999),
    "parceiro": (4000, 4999),
    "conjunto": (5000, 5999),
    "tamanho": (7000, 7999),
}

# §5: `1010` é família-agnóstico (a família viaja na large-community) e `992`/
# `993` põem a família no último dígito. `666`, `11`, `90` e `91` nem chegam ao
# padrão de quatro dígitos.
FAMILIA_AGNOSTICA = frozenset({1010})
FAMILIA_NO_ULTIMO_DIGITO: dict[int, str] = {992: "v4", 993: "v6"}

# §6.2 — os códigos de instrução que o plano conhece. É por esta lista que a
# validação separa "código do plano" de "código órfão" (checagem 3).
CODIGOS_CONHECIDOS: tuple[int, ...] = (1, 2, 3, 4, 6, 100, 666, 6662)

MENSAGENS: dict[str, str] = {
    "fora_da_faixa": "o valor está fora da faixa da banda",
    "familia_incoerente": "o dígito de família do valor não é o da coluna",
    "sem_banda": "a linha tem valor e não declara banda",
    "banda_desconhecida": "a banda não é uma das da partição",
    "valor_em_instrucao": "instrução não carrega community de 2 bytes",
    "instrucao_sem_codigo": "instrução sem código",
    "instrucao_com_valor": "instrução com community de 2 bytes",
    "codigo_sem_instrucao": "código de instrução em linha que não é instrução",
}


def familia_do_digito(valor: int) -> str | None:
    """A família que o próprio valor declara, ou `None` quando ele é exceção.

    `None` não é "está errado": é "o valor não declara família", e é o que a
    §5 chama de exceção nomeada.
    """
    if valor in FAMILIA_AGNOSTICA:
        return None
    if valor in FAMILIA_NO_ULTIMO_DIGITO:
        return FAMILIA_NO_ULTIMO_DIGITO[valor]
    if not 1000 <= valor <= 9999:
        return None
    return {"0": "v4", "1": "v6"}.get(str(valor)[1])


def conferir_valor(banda: str | None, valor: int | None, familia: str) -> str | None:
    """O problema de um valor na coluna `familia`, ou `None` quando conforme.

    `familia` é a coluna em que o valor está (`v4` ou `v6`), e não o que o
    dígito dele diz: a conferência existe justamente para comparar os dois.
    """
    if valor is None:
        return None
    if banda is None:
        return "sem_banda"
    if banda == "instrucao":
        return "valor_em_instrucao"
    if banda not in FAIXAS:
        return "banda_desconhecida"
    minimo, maximo = FAIXAS[banda]
    if not minimo <= valor <= maximo:
        return "fora_da_faixa"
    declarada = familia_do_digito(valor)
    if declarada is not None and declarada != familia:
        return "familia_incoerente"
    return None


def conferir_linha(
    *, banda: str | None, valor_v4: int | None, valor_v6: int | None, codigo: int | None
) -> tuple[str, ...]:
    """Os problemas de uma linha do vocabulário; vazio quando está conforme.

    Cada problema de valor sai com a família no fim (`familia_incoerente:v6`)
    porque a mesma linha tem duas colunas e a mensagem precisa dizer qual delas.
    """
    if banda is None and valor_v4 is None and valor_v6 is None and codigo is None:
        # Nome reconhecido sem valor: `blackhole`, `no-export`, `no-advertise`.
        return ()
    if banda == "instrucao":
        problemas = []
        if codigo is None:
            problemas.append("instrucao_sem_codigo")
        if valor_v4 is not None or valor_v6 is not None:
            problemas.append("instrucao_com_valor")
        return tuple(problemas)
    problemas = []
    if banda is None:
        problemas.append("sem_banda")
    if codigo is not None:
        problemas.append("codigo_sem_instrucao")
    for familia, valor in (("v4", valor_v4), ("v6", valor_v6)):
        problema = conferir_valor(banda, valor, familia)
        if problema is not None:
            problemas.append(f"{problema}:{familia}")
    return tuple(problemas)
