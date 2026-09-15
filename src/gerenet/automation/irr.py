"""Consultas whois com cache — upstreams (§7.1), autorizações de prefixo
(§6, Fase 5) e identidade de organização por ASN (design da organização por
ASN).

A sigla IRR ficou mais estreita que o conteúdo: são DUAS consultas.

- `consultar`: resolve um ASN ou AS-SET para `{"asns": [...],
  "prefixos": [...]}`, com cache em `irr_cache` (TTL padrão de 24h).
- `identificar_asn`: pergunta ao registro quem é o ASN e quais blocos ele
  tem alocados.

Estratégia fail-soft (§10.4 — a consulta não pode quebrar o filtro): falha de
rede (timeout, returncode != 0, servidor indisponível) ⇒ `log.warning` e o
cache é o refúgio — payload vivo é devolvido mesmo com a rede fora; sem nada
vivo, `IrrError` sobe para o chamador tratar.

Capacidade real dos servidores (sondada ao vivo em 2026-09-08, raw socket
porta 43 — o cliente whois então é irrelevante):

- `whois.radb.net` (irrd v4): **não expande mais conjuntos**. A consulta de um
  AS-SET devolve só o(s) objeto(s) `as-set:` (com `members:`); a de um ASN
  devolve só `aut-num:`. As rotas só vêm da consulta invertida
  `-i origin as<asn>` — `whois -h whois.radb.net -i origin AS13335` devolve
  os objetos `route:`/`route6:` com `origin:` (577.294 linhas na sondagem).
- `whois.altdb.net`: espelho vivo porém sem dados (`% No entries found for
  the selected source(s).` para qualquer consulta) — nada a expandir.
- `whois.lacnic.net`: *joint whois* LACNIC/ARIN — rejeita consultas invertidas
  (`% No match for "-I ORIGIN AS714"... accepts only direct match queries`);
  usa o fallback de consulta simples (e o formato direto dele não é RPSL —
  resultado em `asns`/`prefixos` vazios, sem exceção).

Decisões desta task (controller E1 + review F1):
- `consultar` abre a própria sessão (padrão do repo — `runner.py` usa
  `session_override or SessionLocal()`; aqui a assinatura do plano é
  `consultar(source, key, *, ttl_horas=24)`), commita o upsert e fecha no
  `finally`.
- Source→servidor: `radb`/`altdb`/`lacnic`; source desconhecido ⇒
  `whois.radb.net` (fallback).
- `key` só de dígitos (ASN) ⇒ consulta invertida `-i origin as<asn>`; se o
  servidor não suportar a inversão (marcadores `% No match for "-I ORIGIN..."`
  / `accepts only direct match queries`), cai para a consulta simples (o
  formato clássico do RADB, era irrd v2/v3).
- AS-SET: 1) consulta do conjunto (`members:`); 2) membro numérico (último
  componente `AS?<asn>`, ex.: `AS64512` ou `AS13335:AS-CUSTOMERS` que é um
  conjunto, mas `AS13335:AS132892` é o ASN 132892) ⇒ `-i origin as<asn>`;
  membro com `/` é prefixo (route-set — fora do escopo dos as-set, ignorado);
  membro nome de conjunto ⇒ recursão de 1 nível com guarda de ciclo;
  3) dedup global preservando a ordem.
- `route:`/`route6:` viram `prefixos`; `origin:` (nos objetos de rota) viram
  `asns`. `member-of:`/`aut-num:` NÃO são fonte de rotas (sem regras).
- Vivo (critério simples, E1-1): `expires_at` nulo ou no futuro. Para
  **pular** a rede, porém, só `expires_at` definido e no futuro é suficiente
  — linha sem TTL não dá para saber se está fresca; ela vale como refúgio na
  falha (quem grava `irr_cache` nesta task sempre define `expires_at`).
- Payload dedup preservando a ordem da resposta.
- `identificar_asn` (design da organização por ASN) é a SEGUNDA consulta do
  módulo: o objeto `aut-num` do RADB (consulta direta, `whois -h
  whois.radb.net AS<n>`) para `as-name`/`descr`/`member-of`, e a consulta
  direta no LACNIC para `owner`/`ownerid`/`country`/`inetnum` — o LACNIC
  delega os ASNs brasileiros ao registro.br, então um servidor só resolve o
  caso nacional. Cache em `irr_cache` com `source="registro"` e
  `key=str(asn)`; falha de UMA fonte vira aviso, falha das DUAS sobe
  `IrrError`; resposta parcial é estado normal, não erro.
"""
import ipaddress
import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.db import SessionLocal
from gerenet.domain import models

logger = logging.getLogger(__name__)


class IrrError(Exception):
    """Consulta IRR impossível — falha de rede sem payload vivo no cache."""


class _FalhaRede(Exception):
    """Falha de rede na consulta whois (timeout, returncode ou servidor fora)."""


_SERVIDORES: Final[dict[str, str]] = {
    "radb": "whois.radb.net",
    "altdb": "whois.altdb.net",
    "lacnic": "whois.lacnic.net",
}
_SERVIDOR_PADRAO: Final = "whois.radb.net"
_TIMEOUT_SEG: Final = 20
_PROFUNDIDADE_MAX: Final = 1  # conjuntos aninhados: 1 nível a partir do raiz

_RE_ROUTE = re.compile(r"^route(?:6)?:\s*(\S+)", re.MULTILINE | re.IGNORECASE)
_RE_ORIGIN = re.compile(r"^origin:\s*AS(\d+)", re.MULTILINE | re.IGNORECASE)
_RE_MEMBERS = re.compile(r"^members:\s*(.+)", re.MULTILINE | re.IGNORECASE)
_RE_MEMBRO_ASN = re.compile(r"^(?:AS)?(\d+)$", re.IGNORECASE)
# Marcadores das respostas de servidores que rejeitam consulta invertida
# (sondagem LACNIC 2026-09-08: `% No match for "-I ORIGIN AS714"` +
# "accepts only direct match queries").
_RE_INVERSAO_NAO_SUPORTADA = re.compile(
    r"(?i)no match for\s*[\"']?-i\b|accepts only direct match queries"
)


def _dedup_ordem(itens: list) -> list:
    """Dedup preservando a primeira ocorrência (ordem da resposta whois)."""
    return list(dict.fromkeys(itens))


def _decodifica(bruto: bytes) -> str:
    """Resposta whois em bytes → texto, com queda para latin-1.

    O nic.br responde em latin-1 (sondagem de 2026-09-15: `N?cleo de Inf. e
    Coord. do Ponto BR`), e o RADB pode devolver `descr` acentuado em algum
    objeto. Com `text=True` a decodificação UTF-8 estoura DENTRO do
    `subprocess.run`, e o `UnicodeDecodeError` não é `OSError` nem
    `SubprocessError` — ele escaparia do `except` daqui como 500 em vez de
    virar `_FalhaRede`. Decodificar aqui, com queda, é o que faz as duas
    respostas virarem texto em vez de exceção.
    """
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("latin-1")


def _executa_whois(servidor: str, argumentos: list[str]) -> str:
    """`whois -h <servidor> <argumentos...>` — stdout; falha ⇒ `_FalhaRede`."""
    try:
        resultado = subprocess.run(
            ["whois", "-h", servidor, *argumentos],
            capture_output=True,
            timeout=_TIMEOUT_SEG,
            check=False,  # returncode tratado abaixo (≠ 0 = falha de rede)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _FalhaRede(f"whois {argumentos}@{servidor}: {exc}") from exc
    if resultado.returncode != 0:
        raise _FalhaRede(
            f"whois {argumentos}@{servidor}: returncode {resultado.returncode}"
        )
    return _decodifica(resultado.stdout)


def _parseia_resposta(texto: str) -> tuple[list[int], list[str], list[str]]:
    """Resposta whois → (asns, prefixos, membros_declarados).

    `asns` vêm de `origin:` dos objetos de rota; `prefixos` de `route:`/
    `route6:`; `members:` declara os membros do conjunto (valores separados
    por vírgula na mesma linha, chave repetida por linha — irrd v4).
    """
    asns = [int(n) for n in _RE_ORIGIN.findall(texto)]
    prefixos = _RE_ROUTE.findall(texto)
    membros: list[str] = []
    for linha in _RE_MEMBERS.findall(texto):
        membros.extend(parte.strip() for parte in linha.split(",") if parte.strip())
    return asns, prefixos, membros


def _membro_para_alvo(membro: str) -> tuple[bool, str]:
    """Membro de `members:` → (é_ASN, alvo).

    Último componente numérico ⇒ ASN (`AS64512` e também `AS13335:AS132892` —
    referência qualificada de uma ASN); membro com `/` é prefixo (membro de
    route-set — ignorado); resto é nome de conjunto (a consulta usa o nome
    completo, ex.: `AS13335:AS-CUSTOMERS`).
    """
    if "/" in membro:
        return False, ""
    ultimo = membro.split(":")[-1].strip()
    numero = _RE_MEMBRO_ASN.match(ultimo)
    if numero:
        return True, f"as{int(numero.group(1))}"
    return False, membro.strip()


def _consulta_rotas_do_asn(servidor: str, alvo: str) -> tuple[list[int], list[str]]:
    """Rotas de um ASN via consulta invertida `-i origin <alvo>` (irrd v4).

    Se o servidor não suportar a inversão (marcadores de LACNIC), cai para a
    consulta simples no formato clássico do RADB (era irrd v2/v3, que
    expandia o ASN) — quem sabe devolve rotas naquele formato.
    """
    texto = _executa_whois(servidor, ["-i", "origin", alvo])
    asns, prefixos, _ = _parseia_resposta(texto)
    if not asns and not prefixos and _RE_INVERSAO_NAO_SUPORTADA.search(texto):
        texto = _executa_whois(servidor, [alvo])
        asns, prefixos, _ = _parseia_resposta(texto)
    return asns, prefixos


def _resolve(source: str, key: str) -> dict:
    """Busca whois de um ASN ou AS-SET → payload `{"asns", "prefixos"}`.

    ASN numérico (`key` só de dígitos) ⇒ consulta invertida `-i origin
    as{key}`; AS-SET ⇒ consulta do conjunto, e para cada membro: ASN ⇒
    `-i origin as<n>`, conjunto aninhado ⇒ recursão até `_PROFUNDIDADE_MAX`
    com guarda de ciclo (`visitados`), prefixo (route-set) ⇒ ignorado.
    """
    servidor = _SERVIDORES.get(source, _SERVIDOR_PADRAO)
    asns: list[int] = []
    prefixos: list[str] = []
    visitados: set[str] = set()

    def _coleta_set(alvo: str, profundidade: int) -> None:
        identidade = alvo.lower()
        if identidade in visitados:
            return  # guarda de ciclo: conjunto de novo não é consultado
        visitados.add(identidade)
        texto = _executa_whois(servidor, [alvo])
        _, _, membros = _parseia_resposta(texto)
        alvos_asn: list[str] = []
        for membro in membros:
            eh_asn, alvo_membro = _membro_para_alvo(membro)
            if eh_asn:
                alvos_asn.append(alvo_membro)
            elif alvo_membro and profundidade < _PROFUNDIDADE_MAX:
                _coleta_set(alvo_membro, profundidade + 1)
        for alvo_asn in _dedup_ordem(alvos_asn):
            a, p = _consulta_rotas_do_asn(servidor, alvo_asn)
            asns.extend(a)
            prefixos.extend(p)

    if key.isdigit():
        a, p = _consulta_rotas_do_asn(servidor, f"as{key}")
        asns.extend(a)
        prefixos.extend(p)
    else:
        _coleta_set(key, 0)
    return {"asns": _dedup_ordem(asns), "prefixos": _dedup_ordem(prefixos)}


def _fresca(linha: models.IrrCache, agora: datetime) -> bool:
    """Linha com `expires_at` definido e no futuro — pode pular a rede."""
    return linha.expires_at is not None and linha.expires_at > agora


def _vivo(linha: models.IrrCache, agora: datetime) -> bool:
    """Critério simples (E1-1): `expires_at` nulo ou no futuro."""
    return linha.expires_at is None or linha.expires_at > agora


def consultar(source: str, key: str, *, ttl_horas: int = 24) -> dict:
    """Resolve um ASN (`key` só de dígitos) ou AS-SET no IRR → payload.

    Retorno: `{"asns": [ASN...], "prefixos": ["pref/len"...]}` — ASNs
    encontrados e prefixos `route:`/`route6:`, dedup na ordem da resposta.
    Respostas sem dados (`% No entries found...`/as-set vazio) ⇒ payload
    vazio, sem exceção.

    Fluxo (controle E1): cache em `irr_cache` (única por source+key) — uma
    linha com `expires_at` no futuro responde sem whois; senão consulta a
    rede e faz upsert de `payload`/`queried_at`/`expires_at`. Falha de rede ⇒
    `log.warning` e o payload vivo do cache é o refúgio (mesmo com
    `expires_at` nulo, critério simples); sem payload vivo ⇒ `IrrError`.

    A sessão é própria da função (padrão do repo) e fechada no `finally`.
    """
    agora = datetime.now(UTC)
    session = SessionLocal()
    try:
        linha = session.scalar(
            select(models.IrrCache).where(
                models.IrrCache.source == source,
                models.IrrCache.key == key,
            )
        )
        if linha is not None and _fresca(linha, agora):
            return dict(linha.payload)
        try:
            payload = _resolve(source, key)
        except _FalhaRede as exc:
            logger.warning(
                "Falha de rede na consulta IRR %s (source %s): %s",
                key,
                source,
                exc,
            )
            if linha is not None and _vivo(linha, agora):
                return dict(linha.payload)  # refúgio: última resposta viva
            raise IrrError(
                f"Consulta IRR {key!r} (source {source}) falhou ({exc}) "
                "e não há cache vivo."
            ) from exc
        situacao = agora + timedelta(hours=ttl_horas)
        if linha is None:
            session.add(
                models.IrrCache(
                    source=source,
                    key=key,
                    payload=payload,
                    queried_at=agora,
                    expires_at=situacao,
                )
            )
        else:
            linha.payload = payload
            linha.queried_at = agora
            linha.expires_at = situacao
        session.commit()
        return payload
    finally:
        session.close()


# ---- Registro: identidade e blocos alocados (design da organização por ASN) ----

_FONTE_REGISTRO: Final = "registro"

_RE_AS_NAME = re.compile(r"^as-name:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_RE_DESCR = re.compile(r"^descr:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_RE_MEMBER_OF = re.compile(r"^member-of:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_RE_OWNER = re.compile(r"^owner:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_RE_OWNERID = re.compile(r"^ownerid:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_RE_COUNTRY = re.compile(r"^country:\s*([A-Za-z]{2})\s*$", re.MULTILINE | re.IGNORECASE)
# O registro.br usa `inetnum` para as duas famílias; o RPSL separa `inet6num`.
_RE_INETNUM = re.compile(r"^inet(?:6)?num:\s*(\S+)", re.MULTILINE | re.IGNORECASE)


def _parseia_aut_num(texto: str) -> dict:
    """`aut-num` do RADB → nome, razão social e os AS-SETs declarados.

    `member-of` pode vir múltiplo e auto-referente (AS22548 declara `AS-NIC-BR`
    e `AS-DNS-BR`; AS264289 declara o conjunto do próprio ASN) — a lista sai
    inteira e em ordem, e qual deles vira `irr_as_set` é decisão do operador.
    """
    nomes = [v.strip() for v in _RE_AS_NAME.findall(texto) if v.strip()]
    descricoes = [v.strip() for v in _RE_DESCR.findall(texto) if v.strip()]
    as_sets = [v.strip() for v in _RE_MEMBER_OF.findall(texto) if v.strip()]
    return {
        "nome": nomes[0] if nomes else None,
        # O RADB repete `descr` por linha e a primeira é a razão social na
        # convenção da operação; as demais descrevem o papel do AS.
        "razao_social": descricoes[0] if descricoes else None,
        "as_sets": _dedup_ordem(as_sets),
    }


def _parseia_registro_lacnic(texto: str) -> dict:
    """Resposta do LACNIC/registro.br → identidade e blocos `inetnum`.

    Tudo que não for CIDR interpretável é ignorado e devolvido em `invalidos`
    para o chamador avisar: uma resposta torta não pode derrubar a revisão
    inteira por causa de um bloco.
    """
    owners = [v.strip() for v in _RE_OWNER.findall(texto) if v.strip()]
    ids = [v.strip() for v in _RE_OWNERID.findall(texto) if v.strip()]
    paises = [v.strip().upper() for v in _RE_COUNTRY.findall(texto) if v.strip()]
    blocos: list[dict] = []
    invalidos: list[str] = []
    vistos: set[str] = set()
    for bruto in _RE_INETNUM.findall(texto):
        try:
            # `strict=False` normaliza o desalinhado (`198.51.100.5/24` →
            # `198.51.100.0/24`): a autorização exige alinhamento, e oferecer
            # na tela o que a gravação recusaria é oferecer um 422.
            rede = ipaddress.ip_network(bruto, strict=False)
        except ValueError:
            invalidos.append(bruto)
            continue
        chave = str(rede)
        if chave in vistos:
            continue
        vistos.add(chave)
        blocos.append(
            {"prefix": chave, "family": f"ipv{rede.version}", "fonte": _FONTE_REGISTRO}
        )
    return {
        "razao_social": owners[0] if owners else None,
        "documento": ids[0] if ids else None,
        "pais": paises[0] if paises else None,
        "blocos": blocos,
        "invalidos": invalidos,
    }


def _identifica(asn: int) -> dict:
    """As duas consultas do registro → payload do prefill, com os avisos.

    Falha de UMA fonte vira aviso; falha das DUAS sobe `_FalhaRede`, e é o que
    deixa o chamador distinguir "não há dado" de "não deu para consultar"
    (design §4). Nenhuma das duas levanta por resposta vazia: o RADB devolve
    `% No entries found...` com returncode 0, e o LACNIC devolve um rodapé de
    delegação para um ASN de fora da região.
    """
    avisos: list[str] = []
    falhas: list[str] = []
    texto_radb: str | None = None
    texto_registro: str | None = None
    try:
        texto_radb = _executa_whois(_SERVIDORES["radb"], [f"AS{asn}"])
    except _FalhaRede as exc:
        falhas.append(f"RADB: {exc}")
    try:
        texto_registro = _executa_whois(_SERVIDORES["lacnic"], [f"AS{asn}"])
    except _FalhaRede as exc:
        falhas.append(f"LACNIC: {exc}")
    if texto_radb is None and texto_registro is None:
        raise _FalhaRede("; ".join(falhas))

    dados: dict = {
        "nome": None, "razao_social": None, "documento": None, "pais": None,
        "as_set_sugerido": None, "as_sets": [], "blocos": [], "fontes": {},
    }
    if texto_radb is not None:
        radb = _parseia_aut_num(texto_radb)
        dados["nome"] = radb["nome"]
        dados["razao_social"] = radb["razao_social"]
        dados["as_sets"] = radb["as_sets"]
        dados["as_set_sugerido"] = radb["as_sets"][0] if radb["as_sets"] else None
        for campo in ("nome", "razao_social"):
            if radb[campo] is not None:
                dados["fontes"][campo] = "radb"
        if radb["as_sets"]:
            dados["fontes"]["as_sets"] = "radb"
        if radb["nome"] is None:
            avisos.append(f"O RADB não devolveu `aut-num` para AS{asn}.")
    else:
        avisos.append(f"A consulta ao RADB para AS{asn} falhou: {falhas[0]}.")
    if texto_registro is not None:
        registro = _parseia_registro_lacnic(texto_registro)
        # A razão social do RADB vence: ela é a do objeto do AS, e o `owner` do
        # registro é o dono do PRIMEIRO bloco — que num AS com blocos de
        # titulares diferentes não é o mesmo titular.
        if dados["razao_social"] is None:
            dados["razao_social"] = registro["razao_social"]
            if registro["razao_social"] is not None:
                dados["fontes"]["razao_social"] = "registro"
        dados["documento"] = registro["documento"]
        dados["pais"] = registro["pais"]
        dados["blocos"] = registro["blocos"]
        for campo in ("documento", "pais"):
            if registro[campo] is not None:
                dados["fontes"][campo] = "registro"
        if registro["blocos"]:
            dados["fontes"]["blocos"] = "registro"
        if registro["invalidos"]:
            avisos.append(
                "Blocos do registro fora do formato CIDR, ignorados: "
                + ", ".join(registro["invalidos"]) + "."
            )
        if not registro["blocos"]:
            avisos.append(
                f"O registro não devolveu blocos `inetnum` para AS{asn} — ASN "
                "fora da região do LACNIC, ou sem bloco alocado."
            )
    else:
        avisos.append(
            f"A consulta ao registro para AS{asn} falhou: "
            + (falhas[-1] if falhas else "sem resposta") + "."
        )
    dados["avisos"] = avisos
    return dados


def _dono_do_bloco(
    session: Session, prefixo: str, family: str, *, ativas: list | None = None
) -> str | None:
    """Nome da organização com autorização ATIVA que sobrepõe o bloco (§7).

    Mesma regra da `_organizacao_conflitante` do serviço de autorizações, sem o
    `organization_id` a ignorar: aqui a organização ainda não existe, então
    qualquer autorização ativa em cima do bloco é conflito. O laço é repetido
    em vez de importado porque o serviço importa este módulo, e a volta fecharia
    o ciclo.
    """
    if ativas is None:
        ativas = list(
            session.scalars(
                select(models.BgpPrefixAuthorization).where(
                    models.BgpPrefixAuthorization.admin_status.is_(True)
                )
            )
        )
    rede = ipaddress.ip_network(prefixo)
    for linha in ativas:
        if linha.family != family:
            continue
        if rede.overlaps(ipaddress.ip_network(linha.prefix)):
            org = session.get(models.Organization, linha.organization_id)
            return org.name if org is not None else None
    return None


def _marca_conflitos(session: Session, payload: dict) -> dict:
    """Payload com o `conflito` de cada bloco, numa cópia.

    A cópia é o que impede o `conflito` de entrar no cache: ele é estado da
    SoT, que muda entre uma consulta e outra.
    """
    ativas = list(
        session.scalars(
            select(models.BgpPrefixAuthorization).where(
                models.BgpPrefixAuthorization.admin_status.is_(True)
            )
        )
    )
    return {
        **payload,
        "blocos": [
            {**bloco, "conflito": _dono_do_bloco(
                session, bloco["prefix"], bloco["family"], ativas=ativas)}
            for bloco in payload.get("blocos", [])
        ],
    }


def identificar_asn(asn: int, *, ttl_horas: int = 24) -> dict:
    """Identidade e blocos alocados de um ASN → payload do prefill.

    Duas consultas whois (o `aut-num` do RADB e a consulta direta no LACNIC,
    que delega os ASNs brasileiros ao registro.br), cache em `irr_cache` com
    `source="registro"` e `key=str(asn)`.

    Resposta parcial é estado normal (design §4): ASN estrangeiro devolve
    identidade sem blocos, ASN sem objeto no RADB devolve blocos sem nome, e o
    motivo de cada ausência vai em `avisos`. `IrrError` só quando as DUAS
    consultas falham sem cache vivo — falha de consulta, e não ausência de
    dado. O `conflito` de cada bloco é recalculado a cada chamada (§7) e NÃO é
    cacheado. A sessão é própria da função (padrão do módulo).
    """
    agora = datetime.now(UTC)
    session = SessionLocal()
    try:
        linha = session.scalar(
            select(models.IrrCache).where(
                models.IrrCache.source == _FONTE_REGISTRO,
                models.IrrCache.key == str(asn),
            )
        )
        if linha is not None and _fresca(linha, agora):
            return _marca_conflitos(session, dict(linha.payload))
        try:
            payload = _identifica(asn)
        except _FalhaRede as exc:
            logger.warning("Consulta ao registro para AS%d falhou: %s", asn, exc)
            if linha is not None and _vivo(linha, agora):
                return _marca_conflitos(session, dict(linha.payload))
            raise IrrError(
                f"Consulta ao registro para AS{asn} falhou ({exc}) "
                "e não há cache vivo."
            ) from exc
        situacao = agora + timedelta(hours=ttl_horas)
        if linha is None:
            session.add(
                models.IrrCache(
                    source=_FONTE_REGISTRO,
                    key=str(asn),
                    payload=payload,
                    queried_at=agora,
                    expires_at=situacao,
                )
            )
        else:
            linha.payload = payload
            linha.queried_at = agora
            linha.expires_at = situacao
        session.commit()
        return _marca_conflitos(session, payload)
    finally:
        session.close()
