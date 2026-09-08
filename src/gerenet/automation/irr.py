"""Consulta IRR (whois) com cache — upstreams (§7.1) e autorizações de
prefixo (§6, Fase 5): resolve um ASN ou AS-SET para `{"asns": [...],
"prefixos": [...]}`, com cache em `irr_cache` (TTL padrão de 24h).

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
"""
import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import select

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


def _executa_whois(servidor: str, argumentos: list[str]) -> str:
    """`whois -h <servidor> <argumentos...>` — stdout; falha ⇒ `_FalhaRede`."""
    try:
        resultado = subprocess.run(
            ["whois", "-h", servidor, *argumentos],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEG,
            check=False,  # returncode tratado abaixo (≠ 0 = falha de rede)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _FalhaRede(f"whois {argumentos}@{servidor}: {exc}") from exc
    if resultado.returncode != 0:
        raise _FalhaRede(
            f"whois {argumentos}@{servidor}: returncode {resultado.returncode}"
        )
    return resultado.stdout


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
