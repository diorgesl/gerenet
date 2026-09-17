"""As communities da configuração do VRP (spec §9).

O `config_vrp.py` lê peer e subinterface e ignora de propósito o que não modela
— inclusive `peer <nome-de-grupo>`, que não é endereço (linha 359 de lá). O
plano precisa exatamente do que ele descarta: as definições de community, quem
aplica, quem testa, quem é citado sem definição e os grupos de peer. As duas
leituras do mesmo arquivo convivem porque cada uma responde uma pergunta, e
nenhuma das duas precisa da outra.

Tolerância igual à do `config_vrp`: linha que não casa com nenhum ramo é
ignorada, e o que a leitura não entendeu sai em `avisos`, para "não entendi o
formato" não ficar idêntico a "o equipamento não tem community".

Este módulo não lê linha de peer de sessão — só `peer <nome> as-number` (grupo)
e `peer <ip> group <nome>` (membro) —, então `password cipher` não passa por
aqui (§19).
"""
import ipaddress
import re
from dataclasses import dataclass

_CLASSES = ("community", "large-community", "as-path", "prefix")

# `888`, `65000:3001`, `61785:666:14840`: o formato do valor é o filtro.
_RE_VALOR = re.compile(r"\d+(?::\d+){0,2}")

# Palavras que aparecem na linha e não são nome de corpus.
_PALAVRAS = frozenset(
    {
        "if", "then", "endif", "else", "or", "and", "not", "in", "apply", "additive",
        "overwrite", "delete", "community", "large-community", "matches-any",
        "matches-within", "matches-all", "as-path", "ip", "ipv6", "route-destination",
        "ip-prefix", "prefix-list", "regular", "as-path-filter", "community-filter",
        "next-hop", "local-preference", "med", "prepend", "finish", "approve", "refuse",
    }
)

# As definições que a checagem 8 ("nome citado e não definido") conhece,
# agrupadas pela classe semântica do corpus.
_DEFINICOES = (
    ("ip community-filter advanced ", "community", "ip-community-filter-advanced"),
    ("ip community-filter ", "community", "ip-community-filter"),
    ("ip large-community-filter ", "large-community", "ip-large-community-filter"),
    ("ip as-path-filter ", "as-path", "ip-as-path-filter"),
    ("ip ip-prefix ", "prefix", "ip-ip-prefix"),
    ("ip ipv6-prefix ", "prefix", "ip-ipv6-prefix"),
)


@dataclass(frozen=True)
class DefinicaoCorpus:
    nome: str
    classe: str                    # "community" | "large-community" | "as-path" | "prefix"
    sintaxe: str                   # a forma exata no VRP, para o relatório
    valores: tuple[str, ...]
    linhas: tuple[int, ...]


@dataclass(frozen=True)
class UsoCommunity:
    """Uma linha que toca em community, dentro de um filtro.

    `negado` distingue os dois sentidos de um teste: em `if not community
    matches-any {A} then refuse`, a lista A é o que **sobrevive** ao portão (as
    aceitas); em `if community matches-any {A} then refuse`, A é o que ele
    recusa à parte. Cada cláusula de um `if` encadeado por `or` vira um uso
    próprio, porque as cláusulas têm sentidos diferentes.
    """

    filtro: str                    # o route-policy / route-filter / prefix-list que contém a linha
    operacao: str                  # "aplica" | "aplica-large" | "testa" | "testa-large" | "cita"
    valores: tuple[str, ...]
    corpus: str | None             # nome citado em vez de valor literal
    corpus_classe: str | None
    negado: bool                   # `not ... matches-any`: a lista dos aceitos (§4.4)
    additive: bool | None
    condicao: str | None           # o `if ...` que guarda a linha, quando houver
    linha: int


@dataclass(frozen=True)
class AlvoLido:
    nome: str
    asn: int | None
    membros: tuple[str, ...]
    linha: int


@dataclass(frozen=True)
class LeituraCommunities:
    asn_local: int | None = None
    definicoes: tuple[DefinicaoCorpus, ...] = ()
    usos: tuple[UsoCommunity, ...] = ()
    alvos: tuple[AlvoLido, ...] = ()
    avisos: tuple[str, ...] = ()

    def valores_do_corpus(self, nome: str) -> tuple[str, ...]:
        """Os valores de uma definição pelo nome; vazio quando ela não existe.

        É o que resolve `apply community com-EXPORT-UPSTREAM-v4`: sem isso, a
        validação veria um filtro que aplica corpus e não aplica valor nenhum, e
        o achado principal da §8.1 (o portão testa `65000:3001` e o filtro
        aplica `61785:3001`) não sairia.

        Nome repetido: vence a última definição do arquivo, que é o mesmo que o
        mapa por nome do consumidor faz. O empate é real porque o mesmo nome vive
        em dois espaços (`ip community-filter advanced com-BLACKHOLE` e `xpl
        community-list com-BLACKHOLE`), e escolher pelo espaço exigiria saber
        quem cita, o que este módulo não lê.
        """
        for definicao in reversed(self.definicoes):
            if definicao.nome == nome:
                return definicao.valores
        return ()


def _valores(texto: str) -> tuple[str, ...]:
    """Os valores de community de um trecho.

    `{a, b}` e `{a b}` dão a mesma coisa e um `apply community 65000:4001` sem
    chaves dá um valor só. O que não é valor fica fora porque o filtro é o
    formato: número, `asn:x` ou `asn:x:y`.
    """
    return tuple(_RE_VALOR.findall(texto))


def _corpus(tokens: list[str]) -> str | None:
    """O primeiro token que não é valor nem palavra-chave da linha."""
    for token in tokens:
        limpo = token.strip("{},")
        if not limpo or limpo in _PALAVRAS or _RE_VALOR.fullmatch(limpo):
            continue
        return limpo
    return None


def _fecha_chaves(linha: str) -> bool:
    return linha.count("{") == linha.count("}")


def _asn_do_bloco(linha: str) -> int | None:
    partes = linha.split()
    if len(partes) < 2:
        return None
    try:
        return int(partes[1])
    except ValueError:
        return None


def _e_endereco(token: str) -> bool:
    try:
        ipaddress.ip_address(token)
        return True
    except ValueError:
        return False


def _definicao(
    linha: str, numero: int, prefixo: str, classe: str, sintaxe: str
) -> DefinicaoCorpus | None:
    """Uma definição numa linha só: `<prefixo> <nome> [index N permit|deny] <valores>`.

    A forma numerada (`ip community-filter 2 index 10 permit 888`) tem o nome
    onde a avançada tem `advanced`, e o resto é igual: o nome é o primeiro token
    depois do prefixo, com `advanced` pulado quando existe.
    """
    resto = linha[len(prefixo):].split()
    if not resto:
        return None
    if resto[0] == "advanced":
        resto = resto[1:]
    if not resto:
        return None
    nome = resto[0]
    # O valor pode vir depois de `permit`/`deny`; sem eles, a linha inteira já é
    # nome + valor.
    corpo = linha.split(" permit ", 1)[-1] if " permit " in linha else linha
    corpo = corpo.split(" deny ", 1)[-1] if " deny " in linha else corpo
    if corpo == linha:  # nem permit nem deny: o corpo começa depois do nome
        corpo = linha.split(nome, 1)[-1]
    return DefinicaoCorpus(
        nome=nome, classe=classe, sintaxe=sintaxe, valores=_valores(corpo), linhas=(numero,)
    )


def _uso_de_teste(clausula: str, *, numero: int, filtro: str) -> UsoCommunity:
    """Um teste a partir de uma cláusula de `matches-*`, com o sentido dela.

    O `negado` sai da cláusula e não da linha: numa cadeia `or`, só a primeira
    carrega o `not` do `if`, e cada cláusula tem o seu próprio sentido.
    """
    partes = clausula.split()
    grande = "large-community" in partes
    if "{" in clausula:
        valores = _valores(clausula[clausula.index("{") + 1:clausula.index("}")])
        corpus = None
    else:
        marca = next((p for p in partes if p.startswith("matches-")), None)
        resto = partes[partes.index(marca) + 1:] if marca else []
        corpus = _corpus(resto)  # pelo mesmo motivo do `apply`: nome antes do valor
        valores = () if corpus else _valores(" ".join(resto))
    return UsoCommunity(
        filtro=filtro,
        operacao="testa-large" if grande else "testa",
        valores=valores,
        corpus=corpus,
        corpus_classe="large-community" if grande else "community",
        negado="not" in partes,
        additive=None,
        condicao=None,
        linha=numero,
    )


def _aplica_linha_de_filtro(
    linha: str, numero: int, filtro: str, condicao: str | None, avisos: list[str]
) -> tuple[UsoCommunity, ...]:
    """As linhas de community dentro de um filtro: aplicação, teste ou citação."""
    if not _fecha_chaves(linha):
        avisos.append(
            f"linha {numero}: chaves não fechadas na mesma linha, uso ignorado: {linha!r}"
        )
        return ()
    negado = linha.startswith("if not ") or " not " in linha
    partes = linha.split()

    # `apply community X` / `apply large-community X`
    if partes[0] == "apply" and len(partes) >= 2 and partes[1] in ("community", "large-community"):
        grande = partes[1] == "large-community"
        resto = partes[2:]
        # O corpus é procurado ANTES do valor: nome de community termina em
        # dígito (`com-EXPORT-UPSTREAM-v4`) e o `_valores` casaria o `4` de
        # dentro do nome, deixando a citação sem corpus para a §8.1 resolver.
        corpus = _corpus(resto)
        valores = () if corpus else _valores(" ".join(resto))
        return (
            UsoCommunity(
                filtro=filtro,
                operacao="aplica-large" if grande else "aplica",
                valores=valores,
                corpus=corpus,
                corpus_classe="large-community" if grande else "community",
                negado=False,
                additive="additive" in partes[2:],
                condicao=condicao,
                linha=numero,
            ),
        )

    # `if ... community matches-any/matches-within/matches-all {...}` / `... X`
    if "matches-" in linha:
        # O `or` de um `if` encadeado separa cláusulas com sentidos diferentes:
        # `if not community matches-any {A} or community matches-any {B} then
        # refuse` recusa quem não está em A **e** quem está em B. Lendo as duas
        # como uma lista só, o `{65000:991}` da borda desapareceria — e ele é
        # justamente a diferença entre o portão do CDN e o do upstream (§7).
        clausulas = [c for c in linha.split(" or ") if "matches-" in c]
        return tuple(
            _uso_de_teste(clausula, numero=numero, filtro=filtro) for clausula in clausulas
        )

    # Citação de corpus sem valor: `if as-path in X`, `if ip route-destination in X`,
    # `if-match community-filter X`, `if-match ip-prefix X`. O que separa valor de
    # nome é a chave inline no começo do resto, não a presença de dígito: nome de
    # prefix-list da casa tem ASN dentro (`pl-CUSTOMER-AS268061-AS61587-V4`) e era
    # justamente ele que a checagem de "citado e não definido" perdia.
    if " in " in linha or linha.startswith("if-match "):
        resto = linha.split(" in ", 1)[1].split() if " in " in linha else partes[1:]
        if resto and not resto[0].startswith("{"):
            nome = _corpus(resto)
            if nome:
                return (
                    UsoCommunity(
                        filtro=filtro, operacao="cita", valores=(), corpus=nome,
                        corpus_classe=_classe_da_citacao(linha), negado=negado,
                        additive=None, condicao=None, linha=numero,
                    ),
                )
    return ()


def _classe_da_citacao(linha: str) -> str:
    if "large-community" in linha:
        return "large-community"
    if "as-path" in linha:
        return "as-path"
    if "route-destination" in linha or "ip-prefix" in linha or "prefix-list" in linha:
        return "prefix"
    return "community"


def parse_communities_vrp(texto: str) -> LeituraCommunities:
    """Lê definições, usos, citações e grupos de peer da configuração inteira."""
    definicoes: list[DefinicaoCorpus] = []
    usos: list[UsoCommunity] = []
    avisos: list[str] = []
    grupos: dict[str, dict] = {}
    membros: dict[str, list[str]] = {}
    asn_local: int | None = None
    filtro: str | None = None
    condicao: str | None = None
    lista_xpl: str | None = None
    valores_lista: list[str] = []
    linhas_lista: list[int] = []

    for numero, bruta in enumerate(texto.splitlines(), 1):
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue

        # Grupo de peer e membro: aparecem indentados (dentro do `bgp`) e soltos
        # na captura, então a indentação não decide nada aqui.
        if linha.startswith("peer "):
            partes = linha.split()
            if len(partes) >= 4 and partes[2] == "group":
                membros.setdefault(partes[3], []).append(partes[1])
            elif len(partes) >= 3 and partes[2] == "as-number" and not _e_endereco(partes[1]):
                registro = grupos.setdefault(
                    partes[1], {"nome": partes[1], "asn": None, "linha": numero}
                )
                # `as-number 26162`: o ASN é o segundo token, como no `bgp <asn>`.
                registro["asn"] = _asn_do_bloco(" ".join(partes[2:]))
            continue

        if lista_xpl is not None:
            if linha.startswith("end-list"):
                definicoes.append(
                    DefinicaoCorpus(
                        nome=lista_xpl, classe="community", sintaxe="xpl-community-list",
                        valores=tuple(valores_lista), linhas=tuple(linhas_lista),
                    )
                )
                lista_xpl, valores_lista, linhas_lista = None, [], []
                continue
            encontrados = _valores(linha)
            if encontrados:
                valores_lista.extend(encontrados)
                linhas_lista.append(numero)
            else:
                avisos.append(f"linha {numero}: valor não reconhecido em `{lista_xpl}`: {linha!r}")
            continue

        if linha.startswith("end-filter"):
            filtro, condicao = None, None
            continue

        indentado = bruta[:1] in (" ", "\t")

        if not indentado:
            filtro, condicao = None, None
            if linha.startswith("bgp "):
                asn_local = _asn_do_bloco(linha) or asn_local
            elif linha.startswith("xpl community-list "):
                lista_xpl = linha.split()[2]
            elif linha.startswith("route-policy "):
                filtro = linha.split()[1]
            elif linha.startswith("xpl route-filter "):
                filtro = linha.split()[2].split("(")[0]
            else:
                for prefixo, classe, sintaxe in _DEFINICOES:
                    if linha.startswith(prefixo):
                        definicao = _definicao(linha, numero, prefixo, classe, sintaxe)
                        if definicao is not None:
                            definicoes.append(definicao)
                        break
            continue

        if filtro is None:
            continue
        if linha.startswith("if ") and linha.endswith(" then"):
            condicao = linha
            # O `if` também pode ser o teste de community e trazer a condição.
            usos.extend(_aplica_linha_de_filtro(linha, numero, filtro, None, avisos))
            continue
        usos.extend(_aplica_linha_de_filtro(linha, numero, filtro, condicao, avisos))

    alvos = tuple(
        AlvoLido(
            nome=registro["nome"], asn=registro["asn"],
            membros=tuple(sorted(membros.get(registro["nome"], []))), linha=registro["linha"],
        )
        for registro in grupos.values()
    )
    return LeituraCommunities(
        asn_local=asn_local,
        definicoes=tuple(definicoes),
        usos=tuple(usos),
        alvos=alvos,
        avisos=tuple(avisos),
    )
