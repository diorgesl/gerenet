"""Consulta IRR (whois) com cache — upstreams (§7.1) e autorizações de
prefixo (§6, Fase 5): resolve um ASN ou AS-SET para `{"asns": [...],
"prefixos": [...]}`, com cache em `irr_cache` (TTL padrão de 24h).

Estratégia fail-soft (§10.4 — a consulta não pode quebrar o filtro): falha de
rede (timeout, returncode != 0, servidor indisponível) ⇒ `log.warning` e o
cache é o refúgio — payload vivo é devolvido mesmo com a rede fora; sem nada
vivo, `IrrError` sobe para o chamador tratar.

Decisões desta task (controller E1):
- `consultar` abre a própria sessão (padrão do repo — `runner.py` usa
  `session_override or SessionLocal()`; aqui a assinatura do plano é
  `consultar(source, key, *, ttl_horas=24)`), commita o upsert e fecha no
  `finally`.
- Source→servidor: `radb`/`altdb`/`lacnic`; source desconhecido ⇒
  `whois.radb.net` (fallback).
- `key` só de dígitos ⇒ alvo `as{key}`; senão o próprio AS-SET vai na linha
  de comando.
- Vivo (critério simples, E1-1): `expires_at` nulo ou no futuro. Para
  **pular** a rede, porém, só `expires_at` definido e no futuro é suficiente
  — linha sem TTL não dá para saber se está fresca; ela vale como refúgio na
  falha (quem grava `irr_cache` nesta task sempre define `expires_at`).
- AS-SET: a consulta do conjunto devolve os registros dos membros
  (sinalizados pelo `member-of:` do conjunto) — `route:`/`route6:` viram
  `prefixos` e `origin:`/`as-number:` viram `asns`; o atributo `members:` do
  objeto de conjunto expande membros declarados (ASNs numéricos + conjuntos
  aninhados com profundidade 1 e guarda de ciclo).
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

_RE_ROUTE = re.compile(r"^route(?:6)?:\s*(\S+)", re.MULTILINE)
_RE_ORIGIN = re.compile(r"^origin:\s*AS(\d+)", re.MULTILINE | re.IGNORECASE)
_RE_AS_NUMBER = re.compile(r"^as-number:\s*AS(\d+)", re.MULTILINE | re.IGNORECASE)
_RE_MEMBERS = re.compile(r"^members:\s*(.+)", re.MULTILINE)
_RE_ASN = re.compile(r"^AS(\d+)$", re.IGNORECASE)


def _dedup_ordem(itens: list) -> list:
    """Dedup preservando a primeira ocorrência (ordem da resposta whois)."""
    return list(dict.fromkeys(itens))


def _executa_whois(servidor: str, alvo: str) -> str:
    """`whois -h <servidor> <alvo>` — retorna o stdout; falha ⇒ `_FalhaRede`."""
    try:
        resultado = subprocess.run(
            ["whois", "-h", servidor, alvo],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEG,
            check=False,  # returncode tratado abaixo (≠ 0 = falha de rede)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _FalhaRede(f"whois {alvo}@{servidor}: {exc}") from exc
    if resultado.returncode != 0:
        raise _FalhaRede(f"whois {alvo}@{servidor}: returncode {resultado.returncode}")
    return resultado.stdout


def _parseia_resposta(texto: str) -> tuple[list[int], list[str], list[str]]:
    """Resposta whois → (asns, prefixos, membros_declarados).

    `asns` vêm de `origin:`/`as-number:` dos registros; `prefixos` de
    `route:`/`route6:`; `members:` declara os membros do conjunto (valores
    separados por vírgula na mesma linha).
    """
    asns = [int(n) for n in _RE_ORIGIN.findall(texto)]
    asns += [int(n) for n in _RE_AS_NUMBER.findall(texto)]
    prefixos = _RE_ROUTE.findall(texto)
    membros: list[str] = []
    for linha in _RE_MEMBERS.findall(texto):
        membros.extend(parte.strip() for parte in linha.split(",") if parte.strip())
    return asns, prefixos, membros


def _resolve(source: str, key: str) -> dict:
    """Busca whois de um ASN ou AS-SET → payload `{"asns", "prefixos"}`.

    ASN numérico (`key` só de dígitos) ⇒ alvo `as{key}`; AS-SET ⇒ o próprio
    nome. Conjuntos aninhados expandem até `_PROFUNDIDADE_MAX` com guarda de
    ciclo (`visitados`) para não repetir consultas nem entrar em loop.
    """
    servidor = _SERVIDORES.get(source, _SERVIDOR_PADRAO)
    asns: list[int] = []
    prefixos: list[str] = []
    visitados: set[str] = set()

    def _consulta_alvo(alvo: str, profundidade: int) -> None:
        identidade = alvo.lower()
        if identidade in visitados:
            return  # guarda de ciclo: conjunto de novo não é consultado
        visitados.add(identidade)
        texto = _executa_whois(servidor, alvo)
        encontrados, rotas, membros = _parseia_resposta(texto)
        asns.extend(encontrados)
        prefixos.extend(rotas)
        if profundidade >= _PROFUNDIDADE_MAX:
            return
        for membro in membros:
            numero = _RE_ASN.match(membro)
            if numero:
                asns.append(int(numero.group(1)))
            else:
                _consulta_alvo(membro, profundidade + 1)

    _consulta_alvo(f"as{key}" if key.isdigit() else key, 0)
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
