"""Consulta IRR com cache (spec §7.1/§6, Fase 5): whois mockado em
`subprocess.run` (monkeypatch) e persistência em `irr_cache` no banco de
teste do conftest (`session`). Molde: `tests/automation/test_upstream_automation.py`."""
import logging
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from gerenet.automation.irr import IrrError, consultar
from gerenet.domain import models

# Resposta whois "real de exemplo" (roteiro do plano: `route: 180.10.0.0/16`,
# `origin: AS64512`) — o `route` repetido prova o dedup preservando ordem.
RESPOSTA_AS_SET = """as-set: AS-CLIENTE-F5
descr: Exemplo do plano — cliente F5
members: AS64512, AS64513

route: 180.10.0.0/16
descr: bloco primário do cliente
origin: AS64512
member-of: AS-CLIENTE-F5

route: 180.10.0.0/16
origin: AS64512
member-of: AS-CLIENTE-F5

route: 180.20.0.0/16
origin: AS64513
member-of: AS-CLIENTE-F5

route6: 2001:db8:1::/48
origin: AS64512
member-of: AS-CLIENTE-F5
"""

RESPOSTA_ASN = """route: 180.10.0.0/16
origin: AS64512
member-of: AS-CLIENTE-F5

route: 180.30.0.0/16
origin: AS64512
"""

RESPOSTA_SET_PAI = """as-set: AS-CLIENTE-F5
members: AS64512, AS-SET-ANINHADO

route: 180.10.0.0/16
origin: AS64512
member-of: AS-CLIENTE-F5
"""

RESPOSTA_SET_FILHO = """as-set: AS-SET-ANINHADO
members: AS64514, AS-CLIENTE-F5

route: 180.40.0.0/16
origin: AS64514
member-of: AS-SET-ANINHADO

route6: 2001:db8:2::/48
origin: AS64514
member-of: AS-SET-ANINHADO
"""


def _fake_run(chamadas: list, resposta: str):
    def _run(comando, **kwargs):
        chamadas.append(comando)
        return subprocess.CompletedProcess(comando, 0, stdout=resposta, stderr="")

    return _run


def _fake_run_por_alvo(chamadas: list, respostas: dict[str, str]):
    def _run(comando, **kwargs):
        chamadas.append(comando)
        return subprocess.CompletedProcess(
            comando, 0, stdout=respostas[comando[-1]], stderr=""
        )

    return _run


def _fake_run_que_falha(falha: Exception):
    def _run(comando, **kwargs):
        raise falha

    return _run


def _linha_cache(session, source: str, key: str) -> models.IrrCache | None:
    return session.scalar(
        select(models.IrrCache).where(
            models.IrrCache.source == source, models.IrrCache.key == key
        )
    )


def test_consultar_as_set_retorna_asns_e_prefixos(session, monkeypatch):
    """Caso do plano — AS-SET com 2-3 rotas; dedup preserva a ordem e grava o
    cache com `queried_at`/`expires_at = +ttl_horas`."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _fake_run(chamadas, RESPOSTA_AS_SET))

    payload = consultar("radb", "AS-CLIENTE-F5")

    assert payload == {
        "asns": [64512, 64513],
        "prefixos": ["180.10.0.0/16", "180.20.0.0/16", "2001:db8:1::/48"],
    }
    assert chamadas == [["whois", "-h", "whois.radb.net", "AS-CLIENTE-F5"]]

    linha = _linha_cache(session, "radb", "AS-CLIENTE-F5")
    assert linha is not None
    assert linha.payload == payload
    assert linha.expires_at is not None and linha.expires_at > datetime.now(UTC)
    assert linha.expires_at - linha.queried_at == timedelta(hours=24)


def test_consultar_asn_sem_as_na_chave_busca_as_n(session, monkeypatch):
    """key só de dígitos ⇒ alvo `as{n}` (sem prefixo AS na chave)."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _fake_run(chamadas, RESPOSTA_ASN))

    payload = consultar("radb", "64512")

    assert payload == {"asns": [64512], "prefixos": ["180.10.0.0/16", "180.30.0.0/16"]}
    assert chamadas == [["whois", "-h", "whois.radb.net", "as64512"]]


def test_consultar_source_desconhecido_faz_fallback_radb(session, monkeypatch):
    """Source fora de radb/altdb/lacnic ⇒ whois.radb.net (E1-2)."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _fake_run(chamadas, RESPOSTA_ASN))

    payload = consultar("fonte-nova", "64512")

    assert payload["asns"] == [64512]
    assert chamadas[0][1:] == ["-h", "whois.radb.net", "as64512"]


def test_consultar_cache_vivo_nao_refaz_whois(session, monkeypatch):
    """2ª chamada com linha viva (expires_at no futuro) responde do cache —
    `subprocess.run` não é chamado de novo."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _fake_run(chamadas, RESPOSTA_AS_SET))

    consultar("radb", "AS-CLIENTE-F5")
    segundo = consultar("radb", "AS-CLIENTE-F5")

    assert len(chamadas) == 1
    assert segundo == {
        "asns": [64512, 64513],
        "prefixos": ["180.10.0.0/16", "180.20.0.0/16", "2001:db8:1::/48"],
    }


def test_consultar_cache_expirado_refaz_whois(session, monkeypatch):
    """Linha com expires_at no passado não serve — nova consulta de rede e
    upsert do payload novo."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _fake_run(chamadas, RESPOSTA_AS_SET))
    consultar("radb", "AS-CLIENTE-F5")

    linha = _linha_cache(session, "radb", "AS-CLIENTE-F5")
    linha.expires_at = datetime.now(UTC) - timedelta(hours=1)
    session.commit()

    chamadas_fake_novo: list[list[str]] = []
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run", _fake_run(chamadas_fake_novo, RESPOSTA_ASN)
    )
    payload = consultar("radb", "64512")

    assert payload == {"asns": [64512], "prefixos": ["180.10.0.0/16", "180.30.0.0/16"]}
    assert [c[-1] for c in chamadas_fake_novo] == ["as64512"]


def test_consultar_falha_rede_com_cache_vivo_devolve_payload(session, monkeypatch, caplog):
    """Falha de rede com linha viva (expires_at nulo — critério simples E1-1)
    ⇒ warning + refúgio: payload do cache devolvido sem exceção."""
    session.add(
        models.IrrCache(
            source="radb",
            key="AS-CLIENTE-F5",
            payload={"asns": [64512], "prefixos": ["180.10.0.0/16"]},
            queried_at=datetime.now(UTC),
            # expires_at nulo: sem TTL, a linha nunca expira (critério simples)
        )
    )
    session.commit()
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run",
        _fake_run_que_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)),
    )

    with caplog.at_level(logging.WARNING, logger="gerenet.automation.irr"):
        payload = consultar("radb", "AS-CLIENTE-F5")

    assert payload == {"asns": [64512], "prefixos": ["180.10.0.0/16"]}
    assert "Falha de rede na consulta IRR AS-CLIENTE-F5" in caplog.text


def test_consultar_falha_rede_sem_cache_levanta_irr_error(session, monkeypatch):
    """Sem nada vivo no cache ⇒ `IrrError` para o chamador tratar."""
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run",
        _fake_run_que_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)),
    )

    with pytest.raises(IrrError, match="não há cache vivo"):
        consultar("radb", "AS-CLIENTE-F5")


def test_consultar_falha_rede_com_cache_expirado_levanta_irr_error(session, monkeypatch):
    """Linha existente mas expirada não é refúgio (critério E1-1: só vivo)."""
    session.add(
        models.IrrCache(
            source="radb",
            key="64512",
            payload={"asns": [64512], "prefixos": ["180.10.0.0/16"]},
            queried_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    session.commit()
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run",
        _fake_run_que_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)),
    )

    with pytest.raises(IrrError, match="não há cache vivo"):
        consultar("radb", "64512")


def test_consultar_returncode_nao_zero_e_falha_rede(session, monkeypatch):
    """whois terminou com returncode != 0 ⇒ falha de rede (mesmo com stdout)."""
    def _run(comando, **kwargs):
        return subprocess.CompletedProcess(comando, 4, stdout=RESPOSTA_ASN, stderr="")

    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _run)

    with pytest.raises(IrrError, match="returncode 4"):
        consultar("radb", "64512")


def test_consultar_as_set_aninhado_expande_um_nivel_com_guarda(monkeypatch):
    """`members:` com ASN numérico e conjunto aninhado: 1 nível de expansão e
    guarda de ciclo (AS-CLIENTE-F5 re-aparece no filho e não é reconsultado)."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run",
        _fake_run_por_alvo(chamadas, {
            "AS-CLIENTE-F5": RESPOSTA_SET_PAI,
            "AS-SET-ANINHADO": RESPOSTA_SET_FILHO,
        }),
    )

    payload = consultar("radb", "AS-CLIENTE-F5")

    assert payload == {
        "asns": [64512, 64514],
        "prefixos": ["180.10.0.0/16", "180.40.0.0/16", "2001:db8:2::/48"],
    }
    assert [c[-1] for c in chamadas] == ["AS-CLIENTE-F5", "AS-SET-ANINHADO"]
