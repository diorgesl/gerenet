"""O plano de communities como dado e as oito checagens da §8.

Função pura de propósito: o `PlanoLido` vem da SoT depois da adoção **ou** da
proposta antes dela, e `validar` roda igual nos dois casos. É isso que faz a
validação valer antes de o plano existir no banco — que é o ponto da §8.

A comparação de "quem aplica" contra "quem testa" é por **valor literal**
(`61785:3001` ≠ `65000:3001`), e não pela classe do código: as duas grafias são
a mesma classe e namespaces diferentes, e é justamente a troca de namespace
entre o filtro que aplica e o portão que testa que produz o achado principal da
§8.1. O rótulo do achado vem da classe do código, para o relatório falar a
língua do operador.
"""
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from gerenet.automation.parsers.huawei_vrp.communities_vrp import (
    LeituraCommunities,
    UsoCommunity,
)
from gerenet.domain.communities_partition import (
    CODIGOS_CONHECIDOS,
    FAIXAS,
    conferir_linha,
    familia_do_digito,
)

SEVERIDADES = ("critico", "atencao", "informativo")

# §6.2: o prepend guarda o **nível** (1, 2, 3) e a posição onde ele é aplicado
# troca a grafia — na borda o código é o nível vezes 11, e no virtual system é o
# próprio nível, que já está em `CODIGOS_CONHECIDOS`. Quem lê a configuração
# encontra as duas, e sem esta tupla o prepend de borda em uso na captura real
# (`61785:11:14840`) sairia como código órfão.
CODIGOS_DE_BORDA: tuple[int, ...] = (11, 22, 33)


@dataclass(frozen=True)
class Achado:
    """Um problema encontrado na comparação, com o endereço dele no equipamento."""

    codigo: str
    severidade: str
    descricao: str
    valor: str | None = None
    filtro: str | None = None
    linha: int | None = None
    acao: str | None = None


@dataclass(frozen=True)
class ClassePlano:
    nome: str
    # `banda` sem valor é estado legítimo da partição ("a linha tem valor e não
    # declara banda"), e o plano recém-lido tem esse caso: a classe entra com o
    # que o equipamento deu e a checagem 2 aponta o que falta.
    banda: str | None = None
    tipo: str = "tag_produto"
    valor_v4: int | None = None
    valor_v6: int | None = None
    id: int | None = None
    notas: str | None = None


@dataclass(frozen=True)
class InstrucaoPlano:
    nome: str
    codigo: int | None
    tipo: str = "informacao"
    id: int | None = None
    notas: str | None = None


@dataclass(frozen=True)
class PortaoPlano:
    nome: str
    papel: str
    afi: str
    padrao: str = "recusar"
    aceitas: tuple[str, ...] = ()
    recusadas: tuple[str, ...] = ()
    id: int | None = None


@dataclass(frozen=True)
class AlvoPlano:
    nome: str
    papel: str
    codigo_v4: int | None = None
    codigo_v6: int | None = None
    gate_nome: str | None = None
    classe_import: str | None = None
    upstream_id: int | None = None
    organization_id: int | None = None
    parametros: dict = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True)
class RegraImportPlano:
    papel: str
    afi: str
    classe: str
    condicao: dict = field(default_factory=dict)
    notas: str | None = None


@dataclass(frozen=True)
class PlanoLido:
    asn_principal: int | None = None
    asns_anunciados: tuple[dict, ...] = ()
    classes: tuple[ClassePlano, ...] = ()
    instrucoes: tuple[InstrucaoPlano, ...] = ()
    portoes: tuple[PortaoPlano, ...] = ()
    alvos: tuple[AlvoPlano, ...] = ()
    regras_import: tuple[RegraImportPlano, ...] = ()
    snapshot_id: int | None = None
    observacoes: str | None = None


# A §6.1 transcrita: a referência que permite rotular um valor antes de o plano
# existir no banco. `nome` é o nome no namespace clássico quando ele existe; o
# nome do XPL vai em `notas`, porque o índice único de `valor_v4` não deixa as
# duas grafias virarem duas linhas (Regra 1 do plano).
VOCABULARIO: tuple[ClassePlano, ...] = (
    ClassePlano("com-TECMAIS-v4", "cliente", "tag_produto", 3001, 3101,
                notas="namespace XPL: com-EXPORT-UPSTREAM-v4 (61785:3001)"),
    ClassePlano("com-PARCEIROS_CDN-v4", "parceiro", "tag_produto", 4001, 4101,
                notas="namespace XPL: com-EXPORT-CDN-v4 (61785:4001)"),
    ClassePlano("com-TRANSITO-FULL", "transito", "tag_produto", 1010, 1010),
    ClassePlano("com-ONLY-CDN", "especial", "tag_produto", 991, 991),
    ClassePlano("com-TROCA-v4", "especial", "tag_produto", 992, 993),
    ClassePlano("com-CLIENTES_PARCEIROS-CDN", "conjunto", "tag_produto", 5001, None),
    ClassePlano("com-IX-LOCAL-TECMAIS-v4", "local", "tag_produto", 90, 91),
    ClassePlano("com-PTT_SP", "local", "tag_produto", 11, None),
    ClassePlano("com-TAMANHO-1", "tamanho", "tag_produto", 7001, 7101),
    ClassePlano("com-TAMANHO-2", "tamanho", "tag_produto", 7002, 7102),
    ClassePlano("com-TAMANHO-3", "tamanho", "tag_produto", 7003, 7103),
)

# A §6.2 transcrita. O prepend guarda o **nível**; o código da borda é o nível
# vezes 11 e o do virtual system é o próprio nível (§6.2), e quem resolve isso
# é o render da F4.
VOCABULARIO_INSTRUCOES: tuple[InstrucaoPlano, ...] = (
    InstrucaoPlano("com-PROVENIENCIA-V4", 4, "informacao"),
    InstrucaoPlano("com-PROVENIENCIA-V6", 6, "informacao"),
    InstrucaoPlano("com-BLACKHOLE-DENY", 666, "acao_blackhole"),
    InstrucaoPlano("com-CLIENTE-MARCADO", 100, "informacao"),
    InstrucaoPlano("com-ERTEL", 3, "informacao", notas="mesmo código do prepend nível 3 no VS (§6.2)"),
    InstrucaoPlano("com-BLACKHOLE-2", 6662, "acao_blackhole"),
    InstrucaoPlano("com-PREPEND-1", 1, "acao_prepend", notas="na borda o código é 11"),
    InstrucaoPlano("com-PREPEND-2", 2, "acao_prepend", notas="na borda o código é 22"),
    InstrucaoPlano("com-PREPEND-3", 3, "acao_prepend", notas="na borda o código é 33"),
)


def _codigo_do_valor(valor: str) -> int | None:
    """O código de um valor, lido da **posição**: o segundo campo.

    Posicional e não "semântico" de propósito: numa large-community invertida
    (`61785:14840:4`) o segundo campo é o alvo, e quem sabe disso é a checagem 4
    (`_ordem_do_valor`), que troca os dois antes de usá-los.
    """
    partes = valor.split(":")
    if len(partes) < 2:
        return None
    try:
        return int(partes[1])
    except ValueError:
        return None


def _alvo_do_valor(valor: str) -> int | None:
    partes = valor.split(":")
    if len(partes) != 3:
        return None
    try:
        return int(partes[2])
    except ValueError:
        return None


def _e_codigo_conhecido(codigo: int) -> bool:
    """Se o código tem linha no vocabulário — na borda ou no virtual system.

    Quem compara o **terceiro** campo de uma large-community (`61785:11:14840`)
    precisa reconhecer as duas grafias do prepend (§6.2): a do virtual system, que
    já está em `CODIGOS_CONHECIDOS`, e a da borda, que é o nível vezes 11.

    Este predicado é só do lado que lê a configuração. `_e_valor_de_classe` fica
    de fora dele de propósito: ali a tupla desqualifica valor de 2 bytes, e o
    `11` é a classe `com-PTT_SP` em v4 (§6.1) — pôr o código de borda naquela
    conta trocaria um `codigo_orfao` falso por uma classe sumida.
    """
    return codigo in CODIGOS_CONHECIDOS or codigo in CODIGOS_DE_BORDA


def classe_do_valor(plano: PlanoLido, valor: str) -> ClassePlano | None:
    """A classe a que um valor de 2 bytes pertence, por código (namespace-agnóstico)."""
    if valor.count(":") != 1:
        return None
    codigo = _codigo_do_valor(valor)
    if codigo is None:
        return None
    for classe in plano.classes:
        if codigo in (classe.valor_v4, classe.valor_v6):
            return classe
    return None


def _e_valor_de_classe(valor: str) -> bool:
    """Se o valor de 2 bytes pode ser uma classe do plano.

    Os códigos do vocabulário de instruções (`CODIGOS_CONHECIDOS`) não viram
    classe: `8167:666` e `65001:666` são marcas de blackhole de outros ASNs e o
    666 é o `com-BLACKHOLE-DENY` (§6.2). Sem esta guarda, cada marca dessas
    viraria uma linha de classe na adoção e a checagem 1 acusaria "aplicada e
    não testada" para elas — que é assunto da checagem 3, não da 1.
    """
    return valor.count(":") == 1 and _codigo_do_valor(valor) not in CODIGOS_CONHECIDOS


def _ordem_do_valor(valor: str) -> str | None:
    """A ordem da large-community: `codigo:alvo` ou `alvo:codigo` (§8, checagem 4)."""
    partes = valor.split(":")
    if len(partes) != 3:
        return None
    try:
        meio, fim = int(partes[1]), int(partes[2])
    except ValueError:
        return None
    if _e_codigo_conhecido(fim) and not _e_codigo_conhecido(meio):
        return "alvo:codigo"
    if _e_codigo_conhecido(meio):
        return "codigo:alvo"
    return None


# A família no nome do filtro tem três formas: a palavra (`BGP-IPV4-CUSTOMER`), o
# sufixo separado (`rm-PARCEIROS_CDN-v6-in`, `XPL-GGC-V4-EXPORT`) e a forma colada
# (`RouteExportCheckV6`, o portão v6 da §4.4), em que só a caixa separa o `V6` do
# resto do nome. Depois de minúsculas, a colada é um `v4`/`v6` com letra ou
# dígito antes, e o `(?![0-9])` evita ler um `v6` de `v64` como família.
_RE_FAMILIA_COLADA = re.compile(r"(?:^|[a-z0-9])v([46])(?![0-9])")


def _familia_do_nome(filtro: str) -> str | None:
    """A família que o **nome** do filtro declara, ou `None` quando ele não declara."""
    minusculo = filtro.lower()
    if "ipv6" in minusculo or "-v6" in minusculo or "_v6" in minusculo or "v6-" in minusculo:
        return "v6"
    if "ipv4" in minusculo or "-v4" in minusculo or "_v4" in minusculo or "v4-" in minusculo:
        return "v4"
    colada = _RE_FAMILIA_COLADA.search(minusculo)
    return None if colada is None else f"v{colada.group(1)}"


def _afi_do_filtro(filtro: str, valores: Sequence[str]) -> str | None:
    """A família de um filtro: o nome primeiro, os valores como desempate.

    O nome é o sinal forte (`BGP-IPV4-CUSTOMER`, `RouteExportCheckV6`). Sem ele,
    o dígito de família do valor decide quando todos concordam; sem os dois,
    `None` — e a checagem de família não roda, porque apontar sem evidência seria
    inventar.

    O retorno é a **família** (`"v4"`/`"v6"`), na mesma grafia de
    `familia_do_digito`, e não o AFI (`"ipv4"`): a checagem 2 compara este
    resultado com o dígito do valor, e duas grafias do mesmo lado fariam a
    comparação nunca casar, apontando todo valor coerente como incoerente.
    """
    do_nome = _familia_do_nome(filtro)
    if do_nome is not None:
        return do_nome
    familias = {
        familia
        for familia in (familia_do_digito(_codigo_do_valor(v) or 0) for v in valores)
        if familia
    }
    if len(familias) == 1:
        return familias.pop()
    return None


def _aplicados_e_testados(
    leituras: Sequence[LeituraCommunities],
) -> tuple[list[UsoCommunity], list[UsoCommunity]]:
    """Os usos que aplicam e os que testam, com o corpus citado já resolvido.

    `apply community com-EXPORT-UPSTREAM-v4` aplica o **corpo** da lista, não o
    nome dela. Sem resolver, o `61785:3001` que o filtro aplica não existiria
    para a checagem 1 e o achado principal da §8.1 sairia pela metade: é a
    comparação dele com o `65000:3001` que o portão testa que aponta o problema.
    """
    por_nome = {d.nome: d.valores for leitura in leituras for d in leitura.definicoes}
    usos = [
        replace(uso, valores=por_nome.get(uso.corpus, ()))
        if uso.corpus and not uso.valores
        else uso
        for leitura in leituras
        for uso in leitura.usos
    ]
    aplicados = [u for u in usos if u.operacao.startswith("aplica")]
    testados = [u for u in usos if u.operacao.startswith("testa")]
    return aplicados, testados


def _com_valores(usos: Sequence[UsoCommunity]) -> list[UsoCommunity]:
    """Só os usos que chegam com valor: corpus sem definição não aplica nada."""
    return [uso for uso in usos if uso.valores]


def _conferir_vocabulario(plano: PlanoLido) -> list[Achado]:
    """Checagem 2: conformidade com a partição.

    Classes e instruções entram na mesma checagem com campos diferentes (a classe
    tem `valor_v4`/`valor_v6`, a instrução tem `codigo`), então a lista abaixo
    achata as duas formas em linhas de cinco campos antes de chamar
    `conferir_linha` — em vez de um laço que mistura os dois tipos e precisa de
    `getattr` para atravessar a diferença.
    """
    achados: list[Achado] = []
    linhas: list[tuple[str, str | None, int | None, int | None, int | None]] = [
        (classe.nome, classe.banda, classe.valor_v4, classe.valor_v6, None)
        for classe in plano.classes
    ]
    linhas += [
        (instrucao.nome, "instrucao", None, None, instrucao.codigo)
        for instrucao in plano.instrucoes
    ]
    for nome, banda, valor_v4, valor_v6, codigo in linhas:
        problemas = conferir_linha(
            banda=banda, valor_v4=valor_v4, valor_v6=valor_v6, codigo=codigo
        )
        if problemas:
            achados.append(
                Achado(
                    codigo="valor_fora_da_particao",
                    severidade="atencao",
                    descricao=f"{nome}: {', '.join(problemas)}",
                    valor=nome,
                    acao="ajustar a banda, o valor ou registrar a exceção na partição",
                )
            )
    vistos_v4: dict[int, str] = {}
    vistos_v6: dict[int, str] = {}
    for classe in plano.classes:
        for valor, vistos in ((classe.valor_v4, vistos_v4), (classe.valor_v6, vistos_v6)):
            if valor is None:
                continue
            if valor in vistos:
                achados.append(
                    Achado(
                        codigo="valor_duplicado",
                        severidade="critico",
                        descricao=f"{valor} em {vistos} e em {classe.nome}",
                        valor=str(valor),
                        acao="um valor é uma classe: desativar a linha repetida",
                    )
                )
            vistos[valor] = classe.nome
    return achados


def _conferir_familia(leituras: Sequence[LeituraCommunities]) -> list[Achado]:
    """Checagem 2 do lado da leitura: o dígito de família contra o AFI do filtro.

    A família vem do nome do filtro (`BGP-IPV4-CUSTOMER`, `RouteExportCheckV6`) e,
    sem ele, do consenso dos valores (`_afi_do_filtro`). Sem as duas evidências a
    checagem não roda: o `65000:7101` aplicado em rota v4 (§8.1) só é defeito
    porque o nome do filtro diz v4 — o mesmo valor num filtro v6 é o normal, e
    num filtro sem família declarada não há com o que contradizer.

    Só o valor **literal** é conferido. Num `apply community <corpus>`, quem
    aplica é o corpo da lista, e o corpo não pertence a filtro nenhum: o nome de
    quem o cita não é evidência do AFI onde o valor vai parar.
    """
    por_filtro: dict[str, list[str]] = {}
    for leitura in leituras:
        for uso in leitura.usos:
            por_filtro.setdefault(uso.filtro, []).extend(
                valor for valor in uso.valores if valor.count(":") == 1
            )
    achados: list[Achado] = []
    for leitura in leituras:
        for uso in leitura.usos:
            familia = _afi_do_filtro(uso.filtro, por_filtro.get(uso.filtro, ()))
            if familia is None:
                continue
            for valor in uso.valores:
                if valor.count(":") != 1:
                    continue
                codigo = _codigo_do_valor(valor)
                # Os dois lados da comparação falam a língua de
                # `familia_do_digito` (`v4`/`v6`): a do valor, que vem de lá, e a
                # do filtro, que o `_afi_do_filtro` devolve na mesma grafia.
                declarada = familia_do_digito(codigo) if codigo is not None else None
                if declarada is None or declarada == familia:
                    continue
                achados.append(
                    Achado(
                        codigo="familia_incoerente",
                        severidade="atencao",
                        descricao=(
                            f"{valor} é um valor de {declarada} em {uso.filtro}, "
                            f"que é {familia}"
                        ),
                        valor=valor, filtro=uso.filtro, linha=uso.linha,
                        acao="corrigir o valor ou o filtro, por change request",
                    )
                )
    return achados


def _conferir_quem_aplica_e_quem_testa(
    plano: PlanoLido, leituras: Sequence[LeituraCommunities]
) -> list[Achado]:
    """Checagem 1: a que dá valor imediato à adoção (§8.1)."""
    achados: list[Achado] = []
    aplicados, testados = _aplicados_e_testados(leituras)
    valores_aplicados = {v for uso in _com_valores(aplicados) for v in uso.valores if _e_valor_de_classe(v)}
    valores_testados = {v for uso in _com_valores(testados) for v in uso.valores if _e_valor_de_classe(v)}

    for uso in _com_valores(aplicados):
        for valor in uso.valores:
            if not _e_valor_de_classe(valor) or valor in valores_testados:
                continue
            classe = classe_do_valor(plano, valor)
            rotulo = classe.nome if classe else "sem classe no vocabulário"
            achados.append(
                Achado(
                    codigo="classe_aplicada_nao_testada",
                    severidade="critico",
                    descricao=f"{valor} ({rotulo}) é aplicado e nenhum portão o testa",
                    valor=valor, filtro=uso.filtro, linha=uso.linha,
                    acao="incluir a classe no portão do papel, com a grafia que o filtro aplica",
                )
            )
    for uso in _com_valores(testados):
        for valor in uso.valores:
            if not _e_valor_de_classe(valor) or valor in valores_aplicados:
                continue
            achados.append(
                Achado(
                    codigo="classe_testada_nao_aplicada",
                    severidade="atencao",
                    descricao=f"{valor} é testado por {uso.filtro} e nenhum filtro o aplica",
                    valor=valor, filtro=uso.filtro, linha=uso.linha,
                    acao="remover do portão ou passar a aplicar a classe na entrada",
                )
            )
    valores_large_testados = {v for uso in _com_valores(testados) for v in uso.valores if v.count(":") == 2}
    for uso in _com_valores(aplicados):
        for valor in uso.valores:
            if valor.count(":") != 2 or valor in valores_large_testados:
                continue
            if _codigo_do_valor(valor) not in CODIGOS_CONHECIDOS:
                continue  # código órfão é assunto da checagem 3
            achados.append(
                Achado(
                    codigo="instrucao_aplicada_nao_testada",
                    severidade="atencao",
                    descricao=f"a instrução {valor} é aplicada e nenhum filtro a testa",
                    valor=valor, filtro=uso.filtro, linha=uso.linha,
                    acao="verificar se a instrução deveria ter um ramo que a consuma",
                )
            )
    return achados


def _conferir_instrucoes(
    plano: PlanoLido, leituras: Sequence[LeituraCommunities]
) -> list[Achado]:
    """Checagens 3 e 4: código órfão, alvo sem `community_targets` e ordem invertida."""
    achados: list[Achado] = []
    codigos_do_plano = {i.codigo for i in plano.instrucoes}
    alvos_do_plano = {a.codigo_v4 for a in plano.alvos} | {a.codigo_v6 for a in plano.alvos}
    ordens: dict[tuple[int, int], dict[str, UsoCommunity]] = {}
    for leitura in leituras:
        for uso in leitura.usos:
            for valor in uso.valores:
                if valor.count(":") != 2:
                    continue
                codigo, alvo_numero = _codigo_do_valor(valor), _alvo_do_valor(valor)
                if codigo is None or alvo_numero is None:
                    continue
                ordem = _ordem_do_valor(valor)
                if ordem == "alvo:codigo":
                    # Ordem invertida: o campo do meio é o alvo e o último é o
                    # código, o contrário do que os nomes dizem. Sem a troca, o
                    # alvo (14840) passaria por código e viraria `codigo_orfao`,
                    # e a inversão — que é o achado da §8.1 — não sairia.
                    codigo, alvo_numero = alvo_numero, codigo
                if not _e_codigo_conhecido(codigo):
                    achados.append(
                        Achado(
                            codigo="codigo_orfao", severidade="atencao",
                            descricao=f"o código {codigo} de {valor} não tem linha no vocabulário",
                            valor=valor, filtro=uso.filtro, linha=uso.linha,
                            acao="cadastrar a instrução no vocabulário ou corrigir o código",
                        )
                    )
                if alvo_numero not in alvos_do_plano and codigo in codigos_do_plano:
                    achados.append(
                        Achado(
                            codigo="alvo_sem_target", severidade="informativo",
                            descricao=f"o alvo {alvo_numero} de {valor} não tem linha em community_targets",
                            valor=valor, filtro=uso.filtro, linha=uso.linha,
                            acao="cadastrar o alvo no plano quando ele for um peer gerenciado",
                        )
                    )
                if ordem is not None and _e_codigo_conhecido(codigo):
                    # Depois da troca os dois nomes valem nos dois sentidos, então
                    # a chave é sempre (código, alvo) — é o que faz o import e o
                    # export do mesmo par caírem na mesma entrada de `ordens`. O
                    # uso viaja junto porque é dele o filtro e a linha que o
                    # achado precisa para apontar onde a ordem está invertida.
                    ordens.setdefault((codigo, alvo_numero), {}).setdefault(ordem, uso)
    for (codigo, alvo_numero), vistas in ordens.items():
        if "alvo:codigo" in vistas:
            uso = vistas["alvo:codigo"]
            invertido = f"61785:{alvo_numero}:{codigo}"
            achados.append(
                Achado(
                    codigo="ordem_invertida", severidade="critico",
                    descricao=(
                        f"{invertido} está na ordem `alvo:código`; o vocabulário fixa "
                        f"`61785:<código>:<alvo>` (`61785:{codigo}:{alvo_numero}`)"
                    ),
                    valor=invertido, filtro=uso.filtro, linha=uso.linha,
                    acao="corrigir a ordem no equipamento por change request (§14.5)",
                )
            )
    return achados


def _conferir_namespaces(leituras: Sequence[LeituraCommunities]) -> list[Achado]:
    """Checagem 5: o mesmo 2 bytes com dois nomes de significados diferentes."""
    por_valor: dict[str, set[str]] = {}
    for leitura in leituras:
        for definicao in leitura.definicoes:
            if definicao.classe != "community":
                continue
            for valor in definicao.valores:
                if valor.count(":") == 1:
                    por_valor.setdefault(valor, set()).add(definicao.nome)
    achados: list[Achado] = []
    for valor, nomes in por_valor.items():
        if len(nomes) > 1:
            achados.append(
                Achado(
                    codigo="colisao_namespace", severidade="critico",
                    descricao=f"{valor} está definido como {' e '.join(sorted(nomes))}",
                    valor=valor,
                    acao="decidir qual sentido fica e migrar o outro (§14.2)",
                )
            )
    return achados


def _conferir_additive(
    leituras: Sequence[LeituraCommunities], direcoes: Mapping[str, str]
) -> list[Achado]:
    """Checagem 6: `apply community` sem `additive` numa regra de import.

    A direção não se adivinha pelo nome do filtro (Regra 4): ela vem do vínculo
    `peer ... route-policy <nome> import`, que o `config_vrp` já lê.
    """
    achados: list[Achado] = []
    for leitura in leituras:
        for uso in leitura.usos:
            if uso.operacao != "aplica" or uso.additive:
                continue
            if direcoes.get(uso.filtro) != "import":
                continue
            achados.append(
                Achado(
                    codigo="community_sem_additive", severidade="critico",
                    descricao=(
                        f"`apply community` sem `additive` em {uso.filtro} apaga as "
                        "communities que o par mandou"
                    ),
                    valor=",".join(uso.valores) or uso.corpus,
                    filtro=uso.filtro, linha=uso.linha,
                    acao="acrescentar `additive` ao comando, por change request",
                )
            )
    return achados


def _conferir_referencias(
    plano: PlanoLido, leituras: Sequence[LeituraCommunities]
) -> list[Achado]:
    """Checagem 8: nome citado e não definido.

    Todo uso que nomeia um corpus é uma referência, e não só o `cita`:
    `if community matches-within com-BLACKHOLE` referencia a lista do mesmo
    jeito que `ip route-destination in MEU-PREFIXOS` referencia a prefix-list, e
    sem definição não há o que casar. O achado sai um por uso — filtro e linha
    dizem onde, e é isso que o operador precisa para corrigir cada ponto.
    """
    achados: list[Achado] = []
    definidos: dict[str, set[str]] = {}
    for leitura in leituras:
        for definicao in leitura.definicoes:
            definidos.setdefault(definicao.classe, set()).add(definicao.nome)
    nomes_do_plano = {c.nome for c in plano.classes} | {i.nome for i in plano.instrucoes}
    for leitura in leituras:
        for uso in leitura.usos:
            if not uso.corpus:
                continue
            classe = uso.corpus_classe or "community"
            if uso.corpus in nomes_do_plano or uso.corpus in definidos.get(classe, set()):
                continue
            if uso.corpus in definidos.get("community", set()):
                continue  # definido, ainda que em outra forma
            achados.append(
                Achado(
                    codigo="nome_nao_definido", severidade="critico",
                    descricao=(
                        f"{uso.corpus} é citado em {uso.filtro} e não tem definição "
                        f"na configuração nem linha no plano"
                    ),
                    valor=uso.corpus, filtro=uso.filtro, linha=uso.linha,
                    acao="definir a lista no equipamento ou remover a referência (§14.3)",
                )
            )
    return achados


def _conferir_alvos(plano: PlanoLido, estados_alvo: Mapping[str, str]) -> list[Achado]:
    """Checagem 7: alvo do plano cujo peer não está Established."""
    achados: list[Achado] = []
    for alvo in plano.alvos:
        estado = estados_alvo.get(alvo.nome, "ausente")
        if estado == "established":
            continue
        achados.append(
            Achado(
                codigo="alvo_sem_sessao", severidade="atencao",
                descricao=f"{alvo.nome} está no plano e a sessão está {estado}",
                valor=alvo.nome,
                acao="confirmar se o alvo continua em uso ou desativá-lo no plano",
            )
        )
    return achados


def validar(
    plano: PlanoLido,
    leituras: Sequence[LeituraCommunities],
    *,
    direcoes: Mapping[str, str] | None = None,
    estados_alvo: Mapping[str, str] | None = None,
) -> tuple[Achado, ...]:
    """As oito checagens da §8, na ordem em que elas aparecem na spec.

    `direcoes` é o mapa filtro → `import`/`export` (checagem 6) e `estados_alvo`
    é o mapa alvo → `established`/`parado`/`ausente` (checagem 7): os dois são
    **observação** da SoT e do equipamento, não veredito, e por isso entram como
    parâmetro em vez de o motor consultar o banco.
    """
    achados: list[Achado] = []
    achados.extend(_conferir_vocabulario(plano))
    achados.extend(_conferir_familia(leituras))
    achados.extend(_conferir_quem_aplica_e_quem_testa(plano, leituras))
    achados.extend(_conferir_instrucoes(plano, leituras))
    achados.extend(_conferir_namespaces(leituras))
    achados.extend(_conferir_additive(leituras, direcoes or {}))
    achados.extend(_conferir_alvos(plano, estados_alvo or {}))
    achados.extend(_conferir_referencias(plano, leituras))
    return tuple(achados)


@dataclass(frozen=True)
class PropostaPlano:
    plano: PlanoLido
    divergencias: tuple[Achado, ...] = ()
    parados: tuple[str, ...] = ()
    avisos: tuple[str, ...] = ()


@dataclass(frozen=True)
class _EvidenciaDaClasse:
    nome: str
    valor_v4: int | None = None
    valor_v6: int | None = None
    codigo: int | None = None
    banda: str | None = None


# Papel do alvo pelo nome do grupo, quando a SoT não tem o ASN (Regra 5).
_PAPEL_PELO_NOME = (
    ("GGC", "cdn"), ("NFLX", "cdn"), ("NETFLIX", "cdn"), ("OCA", "cdn"), ("CDN", "cdn"),
    ("PARCEIRO", "parceiro"),
    ("PTT", "ix"), ("PEERING", "ix"), ("IX", "ix"),
)

# Palavra do nome da definição → banda que ela sugere. Serve só para achar a
# discordância entre o nome e a faixa (§14.2), não para decidir a banda.
_PALAVRA_DA_BANDA = (
    ("CLIENTES_PARCEIROS", "conjunto"),
    ("CUSTOMER", "cliente"), ("CLIENTE", "cliente"),
    ("PARCEIRO", "parceiro"),
    ("TRANSITO", "transito"),
    ("TAMANHO", "tamanho"),
    ("IX", "local"), ("PTT", "local"),
    ("ONLY-CDN", "especial"), ("TROCA", "especial"),
)


def _banda_da_faixa(valor: int | None) -> str | None:
    """A banda que a faixa do valor declara (§5): é ela que o plano adota."""
    if valor is None:
        return None
    for banda, (minimo, maximo) in FAIXAS.items():
        if minimo <= valor <= maximo:
            return banda
    return None


def _papel_do_nome(nome: str) -> str | None:
    maiusculo = nome.upper()
    for marca, papel in _PAPEL_PELO_NOME:
        if marca in maiusculo:
            return papel
    return None


def _banda_do_nome(nome: str) -> str | None:
    maiusculo = nome.upper()
    for marca, banda in _PALAVRA_DA_BANDA:
        if marca in maiusculo:
            return banda
    return None


# A família do leitor (`v4`/`v6`, a grafia de `familia_do_digito`) como AFI do
# plano (`ipv4`/`ipv6`, o vocabulário do §4.1, que é o que a SoT grava). A
# conversão mora **aqui**, num lugar só: duas grafias do mesmo lado foi o defeito
# que custou uma rodada de fix na T4, e duas respostas para a mesma pergunta é o
# mesmo defeito com outra roupa.
_AFI_DA_FAMILIA = {"v4": "ipv4", "v6": "ipv6"}

# Sem evidência de família o AFI sai por convenção, e é o de v4: é o que a
# operação mostra — o portão gêmeo v6 carrega a família no próprio nome.
_AFI_POR_CONVENCAO = "ipv4"


def afi_da_familia(familia: str | None) -> str:
    """A família do leitor (`v4`/`v6`) como AFI do plano (`ipv4`/`ipv6`).

    `None` é "sem evidência", e não "v4": quem chama decide se o silêncio vale a
    convenção, e esta função só não deixa a conversão ter duas respostas.
    """
    return _AFI_DA_FAMILIA.get(familia or "", _AFI_POR_CONVENCAO)


def _afi_do_portao(filtro: str, valores: Sequence[str]) -> str:
    """O AFI de um portão pela **mesma** cadeia de evidência que o leitor usa.

    Nome do filtro (com as guardas da forma colada) → unanimidade dos dígitos de
    família dos valores → convenção. Uma segunda heurística de nome aqui
    (`"V6" in filtro.upper()`) faria o plano e a validação discordarem sobre o
    mesmo filtro: o detector guardado recusa `RouteExportCheckV64` como família e
    o `in` o leria como v6.

    Só o valor de 2 bytes entra no consenso, como na checagem 2: num
    `61785:7001:14840` o campo do meio é o código, e não um dígito de família.
    """
    return afi_da_familia(
        _afi_do_filtro(filtro, [v for v in valores if v.count(":") == 1])
    )


def propor_plano(
    leituras: Sequence[LeituraCommunities],
    *,
    asn_principal: int | None = None,
    estados_alvo: Mapping[str, str] | None = None,
    papeis_da_sot: Mapping[int, str] | None = None,
) -> PropostaPlano:
    """Monta o plano que a adoção gravaria, com a poda e as divergências.

    A banda de cada classe vem da **faixa** do valor (§5), não do nome: o nome é
    evidência do operador e a faixa é o contrato. Quando os dois discordam, a
    divergência sai para o operador decidir (§14.2).
    """
    estados_alvo = estados_alvo or {}
    papeis_da_sot = papeis_da_sot or {}
    divergencias: list[Achado] = []
    avisos: list[str] = []

    # 1. As classes: os valores de 2 bytes definidos ou aplicados, um por código.
    evidencias: dict[int, _EvidenciaDaClasse] = {}
    for leitura in leituras:
        avisos.extend(leitura.avisos)
        for definicao in leitura.definicoes:
            if definicao.classe != "community":
                continue
            for valor in definicao.valores:
                codigo = _codigo_do_valor(valor)
                if codigo is None or not _e_valor_de_classe(valor):
                    continue
                registro = evidencias.setdefault(
                    codigo, _EvidenciaDaClasse(nome=definicao.nome, banda=_banda_da_faixa(codigo))
                )
                if definicao.nome.startswith("com-") and not registro.nome.startswith("com-"):
                    registro.nome = definicao.nome  # o nome do vocabulário vence o numerado
    for leitura in leituras:
        for uso in leitura.usos:
            if uso.operacao != "aplica" or uso.valores:
                continue
            for valor in leitura.valores_do_corpus(uso.corpus) if uso.corpus else ():
                codigo = _codigo_do_valor(valor)
                if codigo is None or not _e_valor_de_classe(valor) or codigo in evidencias:
                    continue
                evidencias[codigo] = _EvidenciaDaClasse(
                    nome=f"com-{codigo}", banda=_banda_da_faixa(codigo)
                )

    classes: list[ClassePlano] = []
    # A referência é indexada pelos **dois** códigos do par: `com-TAMANHO-1` é
    # (7001, 7101) e a evidência pode chegar por qualquer um deles. Indexada só
    # por `valor_v4`, o `65000:7101` do `-v6` cairia no ramo sintético e viraria
    # uma segunda classe com um código v6 escrito na coluna v4 — uma linha que a
    # própria checagem 2 reprova depois de adotada.
    conhecidas: dict[int, ClassePlano] = {}
    for classe in VOCABULARIO:
        for valor in (classe.valor_v4, classe.valor_v6):
            if valor is not None:
                conhecidas.setdefault(valor, classe)
    vistas: set[tuple[int | None, int | None]] = set()
    for codigo in sorted(evidencias):
        evidencia = evidencias[codigo]
        da_referencia = conhecidas.get(codigo)
        entrada: ClassePlano | None
        if da_referencia is not None:
            chave = (da_referencia.valor_v4, da_referencia.valor_v6)
            entrada = None if chave in vistas else da_referencia
            vistas.add(chave)  # os dois códigos do par viram uma linha só
        else:
            # Código sem linha na referência (o `8167` do `com-AS8167`): a coluna
            # é a que o dígito declara, e não sempre a v4.
            coluna = "valor_v6" if familia_do_digito(codigo) == "v6" else "valor_v4"
            entrada = ClassePlano(
                nome=evidencia.nome, banda=evidencia.banda, tipo="tag_produto",
                **{coluna: codigo},
            )
        if entrada is not None:
            classes.append(entrada)
        # A divergência é do **nome contra a faixa**, então ela sai por código
        # encontrado, mesmo quando os dois códigos do par já viraram uma classe só.
        banda_do_nome = _banda_do_nome(evidencia.nome)
        if banda_do_nome is not None and banda_do_nome != evidencia.banda:
            divergencias.append(
                Achado(
                    codigo="nome_e_faixa_discordam", severidade="critico",
                    valor=evidencia.nome,
                    descricao=(
                        f"{evidencia.nome} é {codigo}, que a faixa da §5 chama de "
                        f"`{evidencia.banda}`; o nome diz `{banda_do_nome}`"
                    ),
                    acao="decidir qual sentido fica e migrar o outro (§14.2)",
                )
            )

    # 2. As instruções: os códigos de large-community que os filtros usam.
    codigos_vistos: set[int] = set()
    for leitura in leituras:
        for uso in leitura.usos:
            for valor in uso.valores:
                if valor.count(":") == 2:
                    codigo = _codigo_do_valor(valor)
                    if codigo in CODIGOS_CONHECIDOS:
                        codigos_vistos.add(codigo)
    instrucoes = tuple(i for i in VOCABULARIO_INSTRUCOES if i.codigo in codigos_vistos)
    do_codigo: dict[int, list[InstrucaoPlano]] = {}
    for instrucao in VOCABULARIO_INSTRUCOES:
        do_codigo.setdefault(instrucao.codigo or -1, []).append(instrucao)
    for codigo in sorted(codigos_vistos):
        candidatas = do_codigo.get(codigo, [])
        if len(candidatas) > 1:
            divergencias.append(
                Achado(
                    codigo="codigo_ambiguo", severidade="critico", valor=str(codigo),
                    descricao=(
                        f"o código {codigo} é "
                        + " e ".join(f"`{c.nome}`" for c in candidatas)
                        + "; o índice único de `codigo` não deixa as duas linhas existirem"
                    ),
                    acao="decidir qual sentido o código tem neste plano",
                )
            )

    # 3. Os portões: o que cada `RouteExportCheck*` aceita e recusa.
    portoes: list[PortaoPlano] = []
    for leitura in leituras:
        por_filtro: dict[str, list[UsoCommunity]] = {}
        for uso in leitura.usos:
            if uso.operacao == "testa":
                por_filtro.setdefault(uso.filtro, []).append(uso)
        for filtro, testes in por_filtro.items():
            if not filtro.startswith("RouteExportCheck"):
                continue
            aceitas = [v for uso in testes if uso.negado for v in uso.valores]
            recusadas = [v for uso in testes if not uso.negado for v in uso.valores]
            papel, evidencia = _papel_do_portao(filtro, aceitas)
            if evidencia is None:
                divergencias.append(
                    Achado(
                        codigo="portao_sem_evidencia", severidade="atencao", valor=filtro,
                        descricao=f"{filtro}: o nome não diz o papel e a lista de aceitas não decide",
                        acao="confirmar o papel do portão depois da adoção",
                    )
                )
            portoes.append(
                PortaoPlano(
                    nome=filtro, papel=papel, afi=_afi_do_portao(filtro, [*aceitas, *recusadas]),
                    padrao="recusar",
                    aceitas=tuple(_nome_do_valor(classes, v) for v in aceitas),
                    recusadas=tuple(_nome_do_valor(classes, v) for v in recusadas),
                )
            )

    # 4. Os alvos: grupos de peer, com a poda de sessão parada (§9.3).
    alvos: list[AlvoPlano] = []
    parados: list[str] = []
    for leitura in leituras:
        for alvo_lido in leitura.alvos:
            estado = estados_alvo.get(alvo_lido.nome, "ausente")
            if estado != "established":
                parados.append(alvo_lido.nome)
                continue
            da_sot = papeis_da_sot.get(alvo_lido.asn or -1)
            do_nome = _papel_do_nome(alvo_lido.nome)
            papel = da_sot or do_nome or "transito"
            if da_sot is not None and do_nome is not None and da_sot != do_nome:
                divergencias.append(
                    Achado(
                        codigo="papel_duvidoso", severidade="atencao", valor=alvo_lido.nome,
                        descricao=(
                            f"{alvo_lido.nome}: a SoT diz `{da_sot}` (AS{alvo_lido.asn}) e o "
                            f"nome do grupo diz `{do_nome}`"
                        ),
                        acao="confirmar o papel do alvo (§6.3)",
                    )
                )
            alvos.append(
                AlvoPlano(
                    nome=alvo_lido.nome, papel=papel,
                    codigo_v4=alvo_lido.asn, codigo_v6=alvo_lido.asn,
                    gate_nome=_portao_do_papel(portoes, papel),
                    classe_import=_classe_da_importacao(papel, classes),
                    parametros=_parametros_do_alvo(leituras, alvo_lido.nome),
                )
            )

    regras = _regras_de_importacao(classes)
    plano = PlanoLido(
        asn_principal=asn_principal,
        asns_anunciados=({"asn": asn_principal, "papel": "principal"},) if asn_principal else (),
        classes=tuple(classes), instrucoes=instrucoes, portoes=tuple(portoes), alvos=tuple(alvos),
        regras_import=regras,
    )
    return PropostaPlano(
        plano=plano, divergencias=tuple(divergencias), parados=tuple(sorted(set(parados))),
        avisos=tuple(avisos),
    )


def _nome_do_valor(classes: Sequence[ClassePlano], valor: str) -> str:
    """O nome de um valor: as classes da proposta primeiro, o vocabulário depois.

    O portão testa valor que pode não ser classe de ninguém — o `65000:991` da
    borda não é classe de linha nenhuma. Sem a segunda passada, o rótulo sairia
    como o literal e o operador leria `65000:991` onde o §7 diz `com-ONLY-CDN`.
    """
    codigo = _codigo_do_valor(valor)
    for classe in (*classes, *VOCABULARIO):
        if codigo in (classe.valor_v4, classe.valor_v6):
            return classe.nome
    return valor


# O código de `com-ONLY-CDN` (§6.1), lido da própria referência para os dois não
# saírem de sincronia.
_CODIGO_ONLY_CDN = next(c.valor_v4 for c in VOCABULARIO if c.nome == "com-ONLY-CDN")


def _papel_do_portao(filtro: str, aceitas: Sequence[str]) -> tuple[str, str | None]:
    """O papel do portão (Regra 6): o nome decide o óbvio, o que ele aceita decide o resto.

    `com-ONLY-CDN` é a classe "só CDN": o portão que a aceita é o portão do CDN,
    e é essa a diferença entre ele e o portão do upstream (§7) — a mesma classe
    passa no CDN e é recusada no upstream. Sem nenhuma das duas evidências o
    papel sai como `upstream` **com pendência**: palpite declarado se revisa,
    palpite silencioso não.
    """
    if "PARCEIROS" in filtro.upper():
        return "parceiro", "nome"
    if _CODIGO_ONLY_CDN in {_codigo_do_valor(valor) for valor in aceitas}:
        return "cdn", "aceitas"
    return "upstream", None


def _portao_do_papel(portoes: Sequence[PortaoPlano], papel: str) -> str | None:
    for portao in portoes:
        if portao.papel == papel and portao.afi == "ipv4":
            return portao.nome
    return portoes[0].nome if portoes else None


def _classe_da_importacao(papel: str, classes: Sequence[ClassePlano]) -> str | None:
    """§7: o cliente recebe a classe do cliente, o parceiro a do parceiro."""
    da_banda = {"cliente": "cliente", "parceiro": "parceiro"}.get(papel)
    if da_banda is None:
        return None
    for classe in classes:
        if classe.banda == da_banda:
            return classe.nome
    return None


def _parametros_do_alvo(leituras: Sequence[LeituraCommunities], nome: str) -> dict:
    """O que é específico do alvo: as exceções por prefixo (§6.3, §8.1).

    O filtro de CDN guarda um bloco de exceção (`100.64.0.0 10 le 24` levando a
    community da própria CDN) que é parâmetro do alvo, não classe do plano.
    """
    excecoes: list[dict] = []
    for leitura in leituras:
        for uso in leitura.usos:
            if uso.operacao != "aplica" or not uso.condicao or "route-destination" not in uso.condicao:
                continue
            excecoes.append({"condicao": uso.condicao, "communities": list(uso.valores)})
    return {"excecoes": excecoes} if excecoes else {}


def _regras_de_importacao(classes: Sequence[ClassePlano]) -> tuple[RegraImportPlano, ...]:
    """§4.5/§7: um papel por classe, com a condição que a produção usa."""
    regras: list[RegraImportPlano] = []
    for papel in ("cliente", "parceiro", "transito"):
        classe = next((c for c in classes if c.banda == papel), None)
        if classe is None:
            continue
        regras.append(
            RegraImportPlano(
                papel=papel, afi="ipv4", classe=classe.nome,
                condicao={"tamanho_max": 23} if papel == "cliente" else {},
            )
        )
    return tuple(regras)
