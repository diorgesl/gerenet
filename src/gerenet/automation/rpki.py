"""Sincronização de ROAs do rpki-client e validação consultiva de origem (§7.5).

O arquivo esperado é o JSON do rpki-client (`rpki-client -j`), no formato:

    {"roas": [{"prefix": "213.171.192.0/18", "maxLength": 24,
               "asn": "AS8365", "validUntil": "2026-09-09T00:00:00Z"}, ...],
     "metadata": {...}}

A tabela `roas` é um espelho do lote (source `rpki-client`): a sincronização
é idempotente — upsert pela chave (prefix, origin_asn, max_length) — e remove
as linhas do lote anterior que ficaram órfãs, preservando intactas linhas de
outras sources. O arquivo é validado por inteiro **antes** de qualquer
escrita: JSON inválido não deixa rastros (sem meia-sincronização).

`validar_origem` é consultiva: devolve `ok` quando existe ROA cobrindo o
prefixo com o ASN de origem correto e comprimento dentro do limite (semântica
RPKI — `maxLength` autoriza more-specifics até o limite, não o prefixo inteiro
do ROA); `diverge` quando há cobertura mas ASN ou comprimento estouram;
`desconhecida` quando nenhuma ROA cobre o prefixo.

Ao final da sincronização, as autorizações ativas de origem IRR/RPKI são
revalidadas de forma consultiva (§6.4/§10.4) por
`revalidar_autorizacoes` — o espelho de ROAs e a validação das autorizações
andam juntos (E2/E3).
"""
import ipaddress
import json
import logging
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models

logger = logging.getLogger(__name__)

_FONTE_RPKI_CLIENT: Final = "rpki-client"
_RESULT_OK: Final = "ok"
_RESULT_DIVERGE: Final = "diverge"
_RESULT_DESCONHECIDA: Final = "desconhecida"


def _asn_para_int(valor: int | str) -> int:
    """ASN do JSON do rpki-client → `int` (`"AS8365"`, `"8365"` ou `8365`).

    Inválido (vazio, não numérico, negativo) ⇒ `ValueError` com mensagem PT-BR.
    """
    texto = str(valor).strip().upper().removeprefix("AS")
    if not texto or not texto.isdigit():
        # m-3 (revisão T22): a mensagem é usada também por validar_origem,
        # onde o ASN vem do chamador — sem "nos ROAs" vira engano.
        raise ValueError(f"ASN inválido: {valor!r}")
    return int(texto)


def _rede(prefixo: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """`"180.10.0.0/16"` → rede; não parseia ⇒ `ValueError` com mensagem PT-BR."""
    try:
        return ipaddress.ip_network(prefixo)
    except ValueError as exc:
        raise ValueError(f"prefixo inválido: {prefixo!r} ({exc})") from exc


def _data_utc(valor: str | None) -> datetime | None:
    """`validUntil` ISO 8601 → tz-aware em UTC; ausente/sem data ⇒ `None`."""
    if valor is None:
        return None
    try:
        instante = datetime.fromisoformat(str(valor))  # "Z" ok no Python 3.11+
    except ValueError as exc:
        raise ValueError(f"validUntil inválido nos ROAs: {valor!r} ({exc})") from exc
    if instante.tzinfo is None:  # ISO sem fuso: assume UTC (padrão do rpki-client)
        instante = instante.replace(tzinfo=UTC)
    return instante.astimezone(UTC)


def _le_roas(caminho: str) -> list[dict]:
    """JSON do rpki-client → lote normalizado de ROAs, sem tocar o banco.

    Erro de leitura, estrutura ou valor (incluindo JSON malformado) ⇒
    `ValueError` com mensagem PT-BR — o arquivo é validado por inteiro antes
    de qualquer escrita.
    """
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            conteudo = json.load(arquivo)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"arquivo de ROAs '{caminho}' inválido: JSON malformado "
            f"(linha {exc.lineno}, coluna {exc.colno}): {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ValueError(f"arquivo de ROAs '{caminho}' ilegível: {exc}") from exc
    if not isinstance(conteudo, dict) or not isinstance(conteudo.get("roas"), list):
        raise TypeError(
            f"arquivo de ROAs '{caminho}' inválido: esperado objeto JSON "
            'com a chave "roas" (lista)'
        )
    lote: list[dict] = []
    for indice, item in enumerate(conteudo["roas"]):
        try:
            if not isinstance(item, dict) or not item.get("prefix"):
                raise ValueError("prefixo obrigatório")
            if "asn" not in item:
                raise ValueError("asn obrigatório")
            max_length = item.get("maxLength")
            lote.append(
                {
                    "prefix": str(_rede(item["prefix"])),
                    "origin_asn": _asn_para_int(item["asn"]),
                    "max_length": int(max_length) if max_length is not None else None,
                    "valid_until": _data_utc(item.get("validUntil")),
                }
            )
        except ValueError as exc:
            raise ValueError(
                f"ROA de índice {indice} inválida no arquivo '{caminho}': {exc}"
            ) from exc
    # m-2 (revisão T22): ROA repetida no MESMO lote (mesma chave) quebraria o
    # UniqueConstraint no commit — dedup preservando a primeira ocorrência.
    unicas: dict[tuple, dict] = {}
    for roa in lote:
        unicas.setdefault((roa["prefix"], roa["origin_asn"], roa["max_length"]), roa)
    return list(unicas.values())


def sincronizar_roas(session: Session, caminho: str) -> int:
    """Espelha o lote do rpki-client na tabela `roas` (uma única transação).

    Parse do arquivo inteiro ANTES de tocar o banco (JSON inválido não deixa
    rastros). Em seguida, na mesma transação:

    1. upsert por (prefix, origin_asn, max_length) com source `rpki-client` —
       linha existente ganha `valid_until`/`imported_at` novos; ausente vira
       insert;
    2. remove as linhas `source == "rpki-client"` ausentes do lote novo
       (órfãs); linhas de outras sources são preservadas intactas.

    Depois do commit, revalida as autorizações ativas de origem IRR/RPKI
    (E3 — consultivo §10.4; import diferido para quebrar o ciclo com
    `domain.services.prefix_authorizations`, que importa este módulo).

    Retorna o número de ROAs do lote (o parse pode ter apontado zero ROAs).
    """
    lote = _le_roas(caminho)
    chaves_lote = {
        (roa["prefix"], roa["origin_asn"], roa["max_length"]) for roa in lote
    }
    agora = datetime.now(UTC)
    try:
        existentes = session.scalars(
            select(models.Roa).where(models.Roa.source == _FONTE_RPKI_CLIENT)
        ).all()
        por_chave = {
            (linha.prefix, linha.origin_asn, linha.max_length): linha
            for linha in existentes
        }
        for roa in lote:
            chave = (roa["prefix"], roa["origin_asn"], roa["max_length"])
            linha = por_chave.get(chave)
            if linha is None:
                session.add(
                    models.Roa(
                        prefix=roa["prefix"],
                        origin_asn=roa["origin_asn"],
                        max_length=roa["max_length"],
                        source=_FONTE_RPKI_CLIENT,
                        valid_until=roa["valid_until"],
                        imported_at=agora,
                    )
                )
            else:
                linha.valid_until = roa["valid_until"]
                linha.imported_at = agora
        for chave, linha in por_chave.items():
            if chave not in chaves_lote:
                session.delete(linha)  # órfã: saiu do lote do rpki-client
        session.commit()
    except Exception:
        session.rollback()
        raise
    # E3: revalidação consultiva das autorizações ativas (import diferido —
    # o serviço importa este módulo; o hook emenda o ciclo).
    from gerenet.domain.services.prefix_authorizations import (
        revalidar_autorizacoes,
    )

    revalidar_autorizacoes(session)
    return len(lote)


# ROA já parseada no índice: (rede, origin_asn, max_length) — a rede com
# `ip_network` resolvida UMA vez (usar `linha.prefix`/ORM por autorização era
# O(M×N) no lote do `rpki sync` — revisão final I-1/T22 C1).
RoaEstruturada = tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, int, int | None]
IndiceRoas = dict[int, list[RoaEstruturada]]


def indice_roas(session: Session) -> IndiceRoas:
    """ROAs da SoT indexadas por versão de IP — uma passada no banco, parse único.

    Cada ROA vira `(rede, origin_asn, max_length)` com o `ip_network`
    parseado uma única vez; os objetos ORM não são retidos. Prefixo que não
    parseia é ignorado com `log.warning` (mesma tolerância de
    `validar_origem`/`avaliar_origem`).
    """
    indice: IndiceRoas = {4: [], 6: []}
    for linha in session.scalars(select(models.Roa)).all():
        try:
            rede = ipaddress.ip_network(linha.prefix)
        except ValueError:
            logger.warning(
                "ROA %s ignorada na validação: prefixo não parseia: %r",
                linha.id,
                linha.prefix,
            )
            continue
        indice[rede.version].append((rede, linha.origin_asn, linha.max_length))
    return indice


def avaliar_origem(prefixo: str, asn: int | str, indice: IndiceRoas) -> str:
    """Núcleo consultivo da validação (§7.5) contra um índice de ROAs carregado.

    Mesma semântica de `validar_origem` — `ok` | `diverge` | `desconhecida`,
    `valid_until` ignorado (frescura é do sync, E3-3). O índice é o
    `indice_roas` (uma passada no banco por lote); `validar_origem` embala a
    chamada unitária.
    """
    alvo = _rede(prefixo)
    asn_origem = _asn_para_int(asn)
    cobrim = [
        (rede, origin_asn, max_length)
        for rede, origin_asn, max_length in indice.get(alvo.version, [])
        if alvo.subnet_of(rede)
    ]
    if not cobrim:
        return _RESULT_DESCONHECIDA
    for rede, origin_asn, max_length in cobrim:
        limite = rede.prefixlen if max_length is None else max_length
        if origin_asn == asn_origem and alvo.prefixlen <= limite:
            return _RESULT_OK
    return _RESULT_DIVERGE


def validar_origem(session: Session, prefixo: str, asn: int | str) -> str:
    """Validação consultiva de origem (§7.5) → `ok` | `diverge` | `desconhecida`.

    Cobrem o prefixo as ROAs cuja rede contém o prefixo consultado (prefixo
    alvo ∈ ROA.prefix; mesma versão de IP). Com cobertura:

    - `ok`: alguma ROA com `origin_asn == asn` e comprimento do alvo dentro do
      limite — `maxLength` quando presente (autoriza more-specifics até ele);
      sem `maxLength` vale o comprimento do próprio prefixo da ROA;
    - `diverge`: nos demais casos (ASN errado ou comprimento maior que o
      limite).

    Sem cobertura ⇒ `desconhecida`. Prefixo que não parseia ⇒ `ValueError`
    com mensagem PT-BR.

    ROAs vencidas ainda contam como cobertura — a frescura dos dados é
    responsabilidade do sync (`sincronizar_roas`, que renova o lote a cada
    execução; validação consultiva, §10.4).

    Chamadas unitárias usam este wrapper (carrega o índice do banco a cada
    chamada); o lote em `revalidar_autorizacoes` carrega o índice UMA vez e
    usa `avaliar_origem` (I-1/T22 C1 — sem isso o `rpki sync` degenera em
    O(M×N) com o lote real do rpki-client).
    """
    return avaliar_origem(prefixo, asn, indice_roas(session))
