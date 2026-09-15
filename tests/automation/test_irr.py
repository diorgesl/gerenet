"""Consulta IRR com cache (spec §7.1/§6, Fase 5): whois mockado em
`subprocess.run` (monkeypatch, respostas por chamada — irrd v4) e persistência
em `irr_cache` no banco de teste do conftest. Molde:
`tests/automation/test_upstream_automation.py`.

Formato simulado = capacidade real do RADB (irrd v4) sondada ao vivo em
2026-09-08: consulta de AS-SET devolve só `as-set:` + `members:`; rotas só
respondem à consulta invertida `-i origin as<n>` (`route:`/`route6:` +
`origin:`)."""
import logging
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from gerenet.automation.irr import IrrError, consultar, identificar_asn
from gerenet.domain import models
from gerenet.domain.schemas import OrganizationCreate, PrefixAuthorizationCreate
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization

# ---- respostas whois (formato irrd v4; case do plano: route 180.10.0.0/16) ----

RESPOSTA_SET_PAI = """as-set:         AS-CLIENTE-F5
descr:          Cliente F5 — exemplo do plano
members:        AS64512,AS64513,AS-SET-ANINHADO
mnt-by:         MNT-F5
source:         RADB
"""

RESPOSTA_SET_FILHO = """as-set:         AS-SET-ANINHADO
descr:          Subconjunto do cliente
members:        AS64514
source:         RADB
"""

RESPOSTA_ROTAS_64512 = """route:          180.10.0.0/16
descr:          bloco primário do cliente
origin:         AS64512
source:         RADB

route:          180.10.0.0/16
origin:         AS64512
source:         RADB

route6:         2001:db8:1::/48
origin:         AS64512
source:         RADB
"""

RESPOSTA_ROTAS_64513 = """route:          180.20.0.0/16
origin:         AS64513
source:         RADB
"""

RESPOSTA_ROTAS_64514 = """route:          180.40.0.0/16
origin:         AS64514
source:         RADB
"""

RESPOSTA_ROTAS_64512_V2 = """route:          180.99.0.0/16
descr:          resposta renovada (2ª coleta)
origin:         AS64512
source:         RADB
"""

RESPOSTA_SET_VAZIO = """as-set:         AS-VAZIO
descr:          Conjunto sem membros cadastrados
source:         RADB
"""

RESPOSTA_ENTRADA_VAZIA = """%  No entries found for the selected source(s).

>>> Last update of whois database: 2026-09-08T19:56:34Z <<<
"""

RESPOSTA_LACNIC_SEM_INVERSAO = """% IP Client: 2804:22e8:a2b:fd00:59f6:a3fc:273e:4871

% Joint Whois - whois.lacnic.net
%  This server accepts single ASN, IPv4 or IPv6 queries

% No match for "-I ORIGIN AS714"

% whois.lacnic.net accepts only direct match queries.
% Types of queries are: POCs, ownerid, CIDR blocks, IP
% and AS numbers.
"""

# ---- mocks de subprocess.run ----

def _mapa_whois(chamadas: list[list[str]], respostas: dict[tuple[str, ...], str | bytes]):
    def _run(comando, **kwargs):
        chamadas.append(comando)
        chave = tuple(comando)
        if chave not in respostas:
            raise AssertionError(f"consulta whois não prevista no mock: {comando}")
        resposta = respostas[chave]
        # `str` vira bytes UTF-8, como o whois devolveria; `bytes` passa direto —
        # é assim que um teste entrega uma resposta em latin-1 de verdade.
        bruto = resposta if isinstance(resposta, bytes) else resposta.encode("utf-8")
        return subprocess.CompletedProcess(comando, 0, stdout=bruto, stderr=b"")

    return _run


def _cmd(*argumentos: str) -> tuple[str, ...]:
    return ("whois", "-h", "whois.radb.net", *argumentos)


def _fake_falha(falha: Exception):
    def _run(comando, **kwargs):
        raise falha

    return _run


def _linha_cache(session, source: str, key: str) -> models.IrrCache | None:
    return session.scalar(
        select(models.IrrCache).where(
            models.IrrCache.source == source, models.IrrCache.key == key
        )
    )


# ---- casos por cenário ----

def test_consultar_as_set_expande_asns_e_consulta_rotas(session, monkeypatch):
    """Caso do plano (RADB irrd v4): conjunto com 2 ASNs + 1 aninhado; o
    aninhado ainda tem membro ASN (1 nível), dedup preserva a ordem."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("AS-CLIENTE-F5"): RESPOSTA_SET_PAI,
        _cmd("AS-SET-ANINHADO"): RESPOSTA_SET_FILHO,
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512,
        _cmd("-i", "origin", "as64513"): RESPOSTA_ROTAS_64513,
        _cmd("-i", "origin", "as64514"): RESPOSTA_ROTAS_64514,
    }))

    payload = consultar("radb", "AS-CLIENTE-F5")

    # rotas: aninhado é consultado no meio do loop de membros; ASNs depois,
    # na ordem de aparição (dedup preserva a ordem de consulta)
    assert payload["asns"] == [64514, 64512, 64513]
    assert payload["prefixos"] == [
        "180.40.0.0/16",
        "180.10.0.0/16",  # `route` duplicado na resposta provam o dedup
        "2001:db8:1::/48",
        "180.20.0.0/16",
    ]
    assert [c[-1] for c in chamadas] == [
        "AS-CLIENTE-F5",
        "AS-SET-ANINHADO",
        "as64514",
        "as64512",
        "as64513",
    ]
    assert chamadas[0][:4] == ["whois", "-h", "whois.radb.net", "AS-CLIENTE-F5"]

    linha = _linha_cache(session, "radb", "AS-CLIENTE-F5")
    assert linha is not None
    assert linha.payload == payload
    assert linha.expires_at is not None and linha.expires_at > datetime.now(UTC)
    assert linha.expires_at - linha.queried_at == timedelta(hours=24)


def test_consultar_asn_sem_as_na_chave_usa_inversao_i_origin(session, monkeypatch):
    """key só de dígitos ⇒ quem responde é `whois -i origin as<n>` (irrd v4)."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512,
    }))

    payload = consultar("radb", "64512")

    assert payload == {
        "asns": [64512],
        "prefixos": ["180.10.0.0/16", "2001:db8:1::/48"],
    }
    assert chamadas == [["whois", "-h", "whois.radb.net", "-i", "origin", "as64512"]]


def test_consultar_source_desconhecido_faz_fallback_radb(session, monkeypatch):
    """Source fora de radb/altdb/lacnic ⇒ whois.radb.net (E1-2)."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512,
    }))

    payload = consultar("fonte-nova", "64512")

    assert payload["asns"] == [64512]
    assert chamadas[0][1:] == ["-h", "whois.radb.net", "-i", "origin", "as64512"]


def test_consultar_cache_vivo_nao_refaz_whois(session, monkeypatch):
    """2ª chamada com linha viva (expires_at no futuro) responde do cache —
    `subprocess.run` não é chamado de novo."""
    respostas = {
        _cmd("AS-CLIENTE-F5"): RESPOSTA_SET_PAI,
        _cmd("AS-SET-ANINHADO"): RESPOSTA_SET_FILHO,
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512,
        _cmd("-i", "origin", "as64513"): RESPOSTA_ROTAS_64513,
        _cmd("-i", "origin", "as64514"): RESPOSTA_ROTAS_64514,
    }
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _mapa_whois(chamadas, respostas))

    primeiro = consultar("radb", "AS-CLIENTE-F5")
    segundo = consultar("radb", "AS-CLIENTE-F5")

    assert len(chamadas) == 5  # 2ª chamada com cache vivo: nenhum whois a mais
    assert segundo == primeiro


def test_consultar_cache_expirado_reescreve_a_mesma_chave(session, monkeypatch):
    """F2: linha expirada é re-consultada e o ramo UPDATE do upsert reescreve
    a MESMA chave (payload novo + queried_at/expires_at novos, sem linha dupla)."""
    chamadas: list[list[str]] = []
    respostas_primeira = {
        _cmd("AS-CLIENTE-F5"): RESPOSTA_SET_PAI,
        _cmd("AS-SET-ANINHADO"): RESPOSTA_SET_FILHO,
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512,
        _cmd("-i", "origin", "as64513"): RESPOSTA_ROTAS_64513,
        _cmd("-i", "origin", "as64514"): RESPOSTA_ROTAS_64514,
    }
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run", _mapa_whois(chamadas, respostas_primeira)
    )
    consultar("radb", "AS-CLIENTE-F5")

    linha = _linha_cache(session, "radb", "AS-CLIENTE-F5")
    linha.expires_at = datetime.now(UTC) - timedelta(hours=1)
    session.commit()
    querida_antiga = linha.queried_at

    chamadas.clear()
    respostas_segunda = {
        _cmd("AS-CLIENTE-F5"): RESPOSTA_SET_PAI,
        _cmd("AS-SET-ANINHADO"): RESPOSTA_SET_FILHO,
        # resposta renovada para o ASN membro: prova o UPDATE, não o INSERT
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512_V2,
        _cmd("-i", "origin", "as64513"): RESPOSTA_ROTAS_64513,
        _cmd("-i", "origin", "as64514"): RESPOSTA_ROTAS_64514,
    }
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run", _mapa_whois(chamadas, respostas_segunda)
    )

    payload = consultar("radb", "AS-CLIENTE-F5")

    assert "180.99.0.0/16" in payload["prefixos"]  # payload vindo da nova consulta
    session.expire_all()  # a sessão do teste tem o objeto velho no identity map
    linha2 = _linha_cache(session, "radb", "AS-CLIENTE-F5")
    assert linha2 is not None
    assert linha2.payload == payload
    assert linha2.queried_at > querida_antiga
    assert linha2.expires_at is not None and linha2.expires_at > datetime.now(UTC)
    # única linha para a chave (od insert não duplicou)
    linhas = session.scalars(
        select(models.IrrCache).where(models.IrrCache.key == "AS-CLIENTE-F5")
    ).all()
    assert len(linhas) == 1
    assert len(chamadas) > 0  # reconsultou a rede (linha viva não era)


def test_consultar_set_sem_membros_payload_vazio(session, monkeypatch):
    """M1: as-set sem `members:` ⇒ payload vazio, sem exceção."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("AS-VAZIO"): RESPOSTA_SET_VAZIO,
    }))

    payload = consultar("radb", "AS-VAZIO")

    assert payload == {"asns": [], "prefixos": []}
    assert len(chamadas) == 1


def test_consultar_no_entries_found_payload_vazio(session, monkeypatch):
    """M1: "% No entries found" (exit 0 — consulta válida sem dados) ⇒
    payload vazio, sem exceção (indistinguível de set sem membros)."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("-i", "origin", "as999999"): RESPOSTA_ENTRADA_VAZIA,
    }))

    payload = consultar("radb", "999999")

    assert payload == {"asns": [], "prefixos": []}
    assert len(chamadas) == 1


def test_consultar_servidor_sem_inversao_faz_fallback_simples(session, monkeypatch):
    """F1: servidor que rejeita `-i origin` (LACNIC) cai na consulta simples
    — o formato clássico do RADB, que ainda pode devolver rotas."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        ("whois", "-h", "whois.lacnic.net", "-i", "origin", "as714"): RESPOSTA_LACNIC_SEM_INVERSAO,
        ("whois", "-h", "whois.lacnic.net", "as714"): RESPOSTA_ROTAS_64512,
    }))

    payload = consultar("lacnic", "714")

    assert payload["asns"] == [64512]
    assert payload["prefixos"] == ["180.10.0.0/16", "2001:db8:1::/48"]
    assert [c[-1] for c in chamadas] == ["as714", "as714"]  # invertida falhou, simples seguiu
    assert chamadas[1] == ["whois", "-h", "whois.lacnic.net", "as714"]


def test_consultar_membros_asn_duplicados_nao_repetem_whois(session, monkeypatch):
    """Dedup dos membros ASN: `members:` repetidos ⇒ uma única consulta `-i
    origin` por ASN."""
    set_com_repetidos = """as-set:         AS-CLIENTE-F5
members:        AS64512,AS64512,AS64513
source:         RADB
"""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("AS-CLIENTE-F5"): set_com_repetidos,
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512,
        _cmd("-i", "origin", "as64513"): RESPOSTA_ROTAS_64513,
    }))

    payload = consultar("radb", "AS-CLIENTE-F5")

    assert payload["asns"] == [64512, 64513]
    assert [c[-1] for c in chamadas] == ["AS-CLIENTE-F5", "as64512", "as64513"]


def test_consultar_set_aninhado_com_guardao_de_ciclo(session, monkeypatch):
    """Ciclo A→B→A: o conjunto A não é reconsultado, mas as rotas dos ASNs
    membros do primeiro também não se repetem (guarda por `visitados`)."""
    respostas = {
        _cmd("AS-CICLO-A"): "as-set: AS-CICLO-A\nmembers: AS-SET-CICLO-B\nsource: RADB\n",
        _cmd("AS-SET-CICLO-B"): "as-set: AS-SET-CICLO-B\nmembers: AS-CICLO-A,AS64514\nsource: RADB\n",
        _cmd("-i", "origin", "as64514"): RESPOSTA_ROTAS_64514,
    }
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _mapa_whois(chamadas, respostas))

    payload = consultar("radb", "AS-CICLO-A")

    assert payload["asns"] == [64514]
    assert payload["prefixos"] == ["180.40.0.0/16"]
    assert [c[-1] for c in chamadas] == ["AS-CICLO-A", "AS-SET-CICLO-B", "as64514"]


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
        _fake_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)),
    )

    with caplog.at_level(logging.WARNING, logger="gerenet.automation.irr"):
        payload = consultar("radb", "AS-CLIENTE-F5")

    assert payload == {"asns": [64512], "prefixos": ["180.10.0.0/16"]}
    assert "Falha de rede na consulta IRR AS-CLIENTE-F5" in caplog.text


def test_consultar_falha_rede_sem_cache_levanta_irr_error(session, monkeypatch):
    """Sem nada vivo no cache ⇒ `IrrError` para o chamador tratar."""
    monkeypatch.setattr(
        "gerenet.automation.irr.subprocess.run",
        _fake_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)),
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
        _fake_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)),
    )

    with pytest.raises(IrrError, match="não há cache vivo"):
        consultar("radb", "64512")


def test_consultar_returncode_nao_zero_e_falha_rede(session, monkeypatch):
    """whois terminou com returncode != 0 ⇒ falha de rede (mesmo com stdout)."""
    def _run(comando, **kwargs):
        return subprocess.CompletedProcess(comando, 4, stdout=RESPOSTA_ROTAS_64512, stderr="")

    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _run)

    with pytest.raises(IrrError, match="returncode 4"):
        consultar("radb", "64512")


def test_consultar_membro_qualificado_vira_asn_do_ultimo_componente(session, monkeypatch):
    """m-1 (re-revisão T21): membro `AS13335:AS132892` (referência qualificada)
    é ASN do último componente ⇒ `-i origin as132892`, sem consultar o nome
    composto como conjunto."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("AS-CUSTOMERS"): "as-set: AS-CUSTOMERS\nmembers: AS13335:AS132892\nsource: RADB\n",
        _cmd("-i", "origin", "as132892"):
            "route: 185.10.0.0/16\norigin: AS132892\nsource: RADB\n",
    }))

    payload = consultar("radb", "AS-CUSTOMERS")

    assert payload["asns"] == [132892]
    assert payload["prefixos"] == ["185.10.0.0/16"]
    assert [c[-1] for c in chamadas] == ["AS-CUSTOMERS", "as132892"]


def test_consultar_membro_prefixo_de_route_set_e_ignorado(session, monkeypatch):
    """m-2 (re-revisão T21): membro com `/` (route-set) é ignorado — nenhuma
    consulta para o prefixo, sem exceção, payload segue dos ASNs membros."""
    chamadas: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(chamadas, {
        _cmd("AS-CUSTOMERS"):
            "as-set: AS-CUSTOMERS\nmembers: AS64512,203.0.113.0/24\nsource: RADB\n",
        _cmd("-i", "origin", "as64512"): RESPOSTA_ROTAS_64512,
    }))

    payload = consultar("radb", "AS-CUSTOMERS")

    assert payload == {
        "asns": [64512],
        "prefixos": ["180.10.0.0/16", "2001:db8:1::/48"],
    }
    assert [c[-1] for c in chamadas] == ["AS-CUSTOMERS", "as64512"]


# ---- decodificação: a resposta do nic.br é latin-1 (design §3) ----

RESPOSTA_LATIN1 = (
    "% owner: Núcleo de Inf. e Coord. do Ponto BR\n"
    "route:          180.10.0.0/16\n"
    "origin:         AS64512\n"
).encode("latin-1")


def _run_fiel(comando, **kwargs):
    """`subprocess.run` de mentira com o comportamento que importa: com
    `text=True` ele decodifica em UTF-8, como o real, e é aí que a resposta
    latin-1 do nic.br derruba a chamada."""
    if kwargs.get("text"):
        # O real levantaria UnicodeDecodeError aqui dentro.
        return subprocess.CompletedProcess(
            comando, 0, stdout=RESPOSTA_LATIN1.decode("utf-8"), stderr=""
        )
    return subprocess.CompletedProcess(comando, 0, stdout=RESPOSTA_LATIN1, stderr=b"")


def test_consultar_aceita_resposta_em_latin1(monkeypatch):
    """O nic.br responde em latin-1, e com `text=True` a decodificação UTF-8
    estourava DENTRO do `subprocess.run` — um `UnicodeDecodeError` que não é
    `OSError` nem `SubprocessError`, logo fora do `except` do módulo: 500 no
    lugar da falha de rede tratada."""
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _run_fiel)

    assert consultar("lacnic", "64512")["prefixos"] == ["180.10.0.0/16"]


# ---- identificar_asn: identidade e blocos alocados (design §4) ----

RESPOSTA_AUT_NUM = """aut-num:        AS264289
as-name:        PROVEINTERLTDA-AS
descr:          PROVEINTER LTDA
member-of:      AS-264289
import:         from AS-ANY accept ANY
export:         to AS-ANY announce AS-264289
source:         RADB
"""

RESPOSTA_AUT_NUM_SEM_MEMBER = """aut-num:        AS13335
as-name:        CLOUDFLARENET
descr:          Cloudflare, Inc.
source:         RADB
"""

RESPOSTA_AUT_NUM_TRES_SETS = """aut-num:        AS22548
as-name:        NIC-BR-AS
descr:          Núcleo de Inf. e Coord. do Ponto BR
member-of:      AS-NIC-BR
member-of:      AS-DNS-BR
member-of:      AS-22548
source:         RADB
"""

RESPOSTA_REGISTRO = """% Joint Whois - whois.lacnic.net
% Delegated to: registro.br
inetnum:     138.121.28.0/22
aut-num:     AS264289
owner:       PROVEINTER TELECOMUNICAÇÕES LTDA
ownerid:     13.172.064/0001-11
responsible: Núcleo de Inf. e Coord. do Ponto BR
country:     BR

inetnum:     2804:2594::/32
owner:       PROVEINTER TELECOMUNICAÇÕES LTDA
ownerid:     13.172.064/0001-11
country:     BR
"""

# ASN fora do LACNIC: o registro responde com o rodapé de delegação e nenhum
# `inetnum` — o dado existe pela metade, e a leitura tem de dizer isso.
RESPOSTA_REGISTRO_ESTRANGEIRO = """% Joint Whois - whois.lacnic.net
% Delegated to: ARIN
% No match for AS13335
"""


def _cmd_direto(servidor: str, asn: int) -> tuple[str, ...]:
    return ("whois", "-h", servidor, f"AS{asn}")


def _mapa_do_registro(
    asn: int, *, radb: str | bytes | None = None, registro: str | bytes | None = None
) -> dict[tuple[str, ...], str | bytes]:
    respostas: dict[tuple[str, ...], str | bytes] = {}
    if radb is not None:
        respostas[_cmd_direto("whois.radb.net", asn)] = radb
    if registro is not None:
        respostas[_cmd_direto("whois.lacnic.net", asn)] = registro
    return respostas


def test_identificar_asn_le_as_duas_fontes(session, monkeypatch):
    """O `aut-num` do RADB dá a identidade; o registro dá o documento e os
    blocos alocados — as duas fontes, cada uma com o que ela tem."""
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            264289, radb=RESPOSTA_AUT_NUM, registro=RESPOSTA_REGISTRO)))

    payload = identificar_asn(264289)

    assert payload["nome"] == "PROVEINTERLTDA-AS"
    assert payload["razao_social"] == "PROVEINTER LTDA"  # o RADB vence o registro
    assert payload["documento"] == "13.172.064/0001-11"
    assert payload["pais"] == "BR"
    assert payload["as_set_sugerido"] == "AS-264289"
    assert payload["as_sets"] == ["AS-264289"]
    assert payload["blocos"] == [
        {"prefix": "138.121.28.0/22", "family": "ipv4", "fonte": "registro", "conflito": None},
        {"prefix": "2804:2594::/32", "family": "ipv6", "fonte": "registro", "conflito": None},
    ]
    assert payload["fontes"]["blocos"] == "registro"
    assert payload["avisos"] == []


def test_identificar_asn_le_a_resposta_latin1_do_registro(session, monkeypatch):
    """A resposta do nic.br vem em latin-1, e o acento do `owner` chega
    inteiro: é a decodificação da Task 1 vista pela ponta que a motivou."""
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            264289, radb=RESPOSTA_AUT_NUM,
            registro=RESPOSTA_REGISTRO.encode("latin-1"))))

    payload = identificar_asn(264289)

    assert payload["razao_social"] == "PROVEINTER LTDA"
    assert payload["documento"] == "13.172.064/0001-11"


def test_identificar_asn_estrangeiro_devolve_identidade_sem_blocos(session, monkeypatch):
    """Fora do LACNIC não vem `owner` nem `inetnum`: sobra a identidade do RADB,
    e a ausência tem de estar dita — não confundida com "não há dado nenhum"."""
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            13335, radb=RESPOSTA_AUT_NUM_SEM_MEMBER,
            registro=RESPOSTA_REGISTRO_ESTRANGEIRO)))

    payload = identificar_asn(13335)

    assert payload["nome"] == "CLOUDFLARENET"
    assert payload["blocos"] == []
    assert payload["documento"] is None
    assert any("inetnum" in aviso for aviso in payload["avisos"])


def test_identificar_asn_sem_member_of_devolve_as_set_nulo(session, monkeypatch):
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            13335, radb=RESPOSTA_AUT_NUM_SEM_MEMBER,
            registro=RESPOSTA_REGISTRO_ESTRANGEIRO)))

    payload = identificar_asn(13335)

    assert payload["as_set_sugerido"] is None
    assert payload["as_sets"] == []


def test_identificar_asn_com_member_of_multiplo_sugere_o_primeiro(session, monkeypatch):
    """`member-of` pode vir múltiplo (e auto-referente): o primeiro vira
    sugestão e todos ficam visíveis, porque a escolha é do operador."""
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            22548, radb=RESPOSTA_AUT_NUM_TRES_SETS,
            registro=RESPOSTA_REGISTRO_ESTRANGEIRO)))

    payload = identificar_asn(22548)

    assert payload["as_set_sugerido"] == "AS-NIC-BR"
    assert payload["as_sets"] == ["AS-NIC-BR", "AS-DNS-BR", "AS-22548"]


def test_identificar_asn_com_uma_fonte_fora_ainda_responde(session, monkeypatch, caplog):
    """Falha de UMA consulta não derruba o prefill: a outra responde e o motivo
    vai em `avisos`. Só as duas juntas são falha de consulta."""
    respostas = _mapa_do_registro(264289, registro=RESPOSTA_REGISTRO)

    def _run(comando, **kwargs):
        chave = tuple(comando)
        if chave not in respostas:
            raise subprocess.TimeoutExpired("whois", 20)
        return subprocess.CompletedProcess(comando, 0, stdout=respostas[chave].encode("utf-8"), stderr=b"")

    monkeypatch.setattr("gerenet.automation.irr.subprocess.run", _run)

    with caplog.at_level(logging.WARNING, logger="gerenet.automation.irr"):
        payload = identificar_asn(264289)

    assert payload["documento"] == "13.172.064/0001-11"
    assert payload["nome"] is None
    assert any("RADB" in aviso for aviso in payload["avisos"])


def test_identificar_asn_com_as_duas_fontes_fora_levanta_irr_error(session, monkeypatch):
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _fake_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)))

    with pytest.raises(IrrError, match="não há cache vivo"):
        identificar_asn(264289)


def test_identificar_asn_com_uma_fonte_fora_usa_o_cache_como_refugio(session, monkeypatch):
    session.add(models.IrrCache(
        source="registro", key="264289",
        payload={"nome": "PROVEINTERLTDA-AS", "razao_social": "PROVEINTER LTDA",
                 "documento": None, "pais": None, "as_set_sugerido": None,
                 "as_sets": [], "blocos": [], "fontes": {}, "avisos": []},
        queried_at=datetime.now(UTC),
        # expires_at nulo: sem TTL, a linha nunca expira (critério simples E1-1)
    ))
    session.commit()
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _fake_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)))

    assert identificar_asn(264289)["nome"] == "PROVEINTERLTDA-AS"


def test_identificar_asn_nao_serve_cache_com_forma_de_fora(session, monkeypatch):
    """Payload de outro formato na chave do prefill é cache MISS.

    O `gerenet irr query` aceita `--source` de texto livre e grava em
    `irr_cache` sob a MESMA chave daqui (`source="registro"`, `key=str(asn)`):
    um payload do `consultar` (`{"asns", "prefixos"}`) gravado ali seria
    servido por 24 h como se fosse a resposta do registro — um ASN sem nome e
    sem bloco nenhum, em cima de blocos que existem. A linha está fresca de
    propósito: sem a guarda ela venceria a consulta.
    """
    session.add(models.IrrCache(
        source="registro", key="264289",
        payload={"asns": [264289], "prefixos": ["138.121.28.0/22"]},
        queried_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    ))
    session.commit()
    disparos: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(disparos, _mapa_do_registro(
            264289, radb=RESPOSTA_AUT_NUM, registro=RESPOSTA_REGISTRO)))

    payload = identificar_asn(264289)

    assert len(disparos) == 2  # as duas consultas do registro aconteceram
    assert [b["prefix"] for b in payload["blocos"]] == [
        "138.121.28.0/22", "2804:2594::/32"
    ]
    assert "asns" not in payload


def test_identificar_asn_refugio_nao_devolve_cache_de_outra_forma(session, monkeypatch):
    """A outra ponta da guarda: com a rede fora, o payload torto — vivo, sem
    TTL — não é o refúgio. `IrrError` diz que não há cache vivo, em vez de o
    operador receber a resposta de outro formato."""
    session.add(models.IrrCache(
        source="registro", key="264289",
        payload={"asns": [264289], "prefixos": []},
        queried_at=datetime.now(UTC),
        expires_at=None,  # vivo (critério simples E1-1)
    ))
    session.commit()
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _fake_falha(subprocess.TimeoutExpired("whois -h whois.radb.net", 20)))

    with pytest.raises(IrrError, match="não há cache vivo"):
        identificar_asn(264289)


def test_identificar_asn_dentro_do_ttl_nao_refaz_o_whois(session, monkeypatch):
    """O mock levanta em QUALQUER consulta depois da primeira: a segunda
    chamada só pode ter vindo do cache."""
    disparos: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois(disparos, _mapa_do_registro(
            264289, radb=RESPOSTA_AUT_NUM, registro=RESPOSTA_REGISTRO)))

    primeira = identificar_asn(264289)
    session.expire_all()
    linha = _linha_cache(session, "registro", "264289")

    assert linha is not None
    assert [b["prefix"] for b in linha.payload["blocos"]] == [
        b["prefix"] for b in primeira["blocos"]
    ]
    # Nenhum `conflito` no cache: ele é estado da SoT e muda entre consultas, e
    # é por isso que a comparação acima é por prefixo — o payload cacheado não
    # tem a chave, e o devolvido tem.
    assert all("conflito" not in bloco for bloco in linha.payload["blocos"])

    segunda = identificar_asn(264289)
    assert len(disparos) == 2  # só as duas da primeira chamada
    assert segunda["blocos"] == primeira["blocos"]


def test_identificar_asn_marca_o_bloco_conflitante(session, monkeypatch):
    """O bloco que sobrepõe autorização ativa de OUTRA organização sai marcado
    com o nome dela; o livre sai nulo (design §7)."""
    org_id = create_organization(
        session, OrganizationCreate(name="Cliente Beta", asn=64512), actor="cli"
    ).id
    create_authorization(session, PrefixAuthorizationCreate(
        organization_id=org_id, family="ipv4", prefix="138.121.28.0/24"), actor="cli")
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            264289, radb=RESPOSTA_AUT_NUM, registro=RESPOSTA_REGISTRO)))

    payload = identificar_asn(264289)

    assert payload["blocos"][0]["conflito"] == "Cliente Beta"
    assert payload["blocos"][1]["conflito"] is None


def test_identificar_asn_nao_cacheia_o_conflito(session, monkeypatch):
    """Um bloco livre pode estar tomado daqui a uma hora: o conflito é
    recalculado a cada chamada, inclusive na que vem do cache."""
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            264289, radb=RESPOSTA_AUT_NUM, registro=RESPOSTA_REGISTRO)))
    assert identificar_asn(264289)["blocos"][0]["conflito"] is None  # enche o cache

    org_id = create_organization(
        session, OrganizationCreate(name="Cliente Gama", asn=64513), actor="cli"
    ).id
    create_authorization(session, PrefixAuthorizationCreate(
        organization_id=org_id, family="ipv4", prefix="138.121.28.0/24"), actor="cli")

    # Sem whois novo: o mock já não cobre nenhuma consulta.
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _fake_falha(AssertionError("o cache não foi usado")))
    assert identificar_asn(264289)["blocos"][0]["conflito"] == "Cliente Gama"


def test_identificar_asn_bloco_torto_vira_aviso(session, monkeypatch):
    """O registro às vezes devolve o `inetnum` fora do CIDR: o bloco é
    ignorado com o motivo dito, e o que é CIDR desalinhado é normalizado (a
    autorização exige alinhamento — oferecer o desalinhado seria oferecer um
    422)."""
    resposta = RESPOSTA_REGISTRO + (
        "\ninetnum:     200.57.128/22\n"
        "inetnum:     198.51.100.5/24\n"
    )
    monkeypatch.setattr("gerenet.automation.irr.subprocess.run",
        _mapa_whois([], _mapa_do_registro(
            264289, radb=RESPOSTA_AUT_NUM, registro=resposta)))

    payload = identificar_asn(264289)

    assert [b["prefix"] for b in payload["blocos"]] == [
        "138.121.28.0/22", "2804:2594::/32", "198.51.100.0/24"
    ]
    assert any("200.57.128/22" in aviso for aviso in payload["avisos"])
