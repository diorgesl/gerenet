# Organização a partir do ASN — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A revisão da adoção preenche o cadastro da organização nova com o que o registro devolve para o ASN do peer — identidade e blocos alocados — e a adoção grava os blocos como autorizações de prefixo na mesma transação.

**Architecture:** Uma leitura nova em `automation/irr.py` (`identificar_asn`) faz as duas consultas whois do módulo que já tem cache: o objeto `aut-num` do RADB (nome, razão social, `member-of`) e a consulta direta no LACNIC, que delega os ASNs brasileiros ao registro.br (razão social, documento, país, blocos `inetnum`). A leitura é fail-soft como o resto do módulo e alimenta `GET /api/v1/organizations/prefill`, que a tela de revisão consome para preencher o formulário; o `POST /discovery/adopt` ganha a lista de blocos e os cria como autorizações de origem `registro` dentro da transação que já existe.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · binário `whois` por `subprocess` · React + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-15-gerenet-organizacao-por-asn-design.md`

## Global Constraints

- **Idioma**: todo artefato, mensagem de erro, docstring, comentário e nome de teste em **português (PT-BR)**.
- **Nada é excluído fisicamente** (§14.1): desativar, nunca apagar.
- **Nenhum comando vai ao equipamento nesta frente.** A leitura é do registro, não do roteador; mudar o roteador continua exigindo change request.
- **A consulta ao registro é consultiva** (§10.4): ela sugere e o operador decide. Nada é autorizado sem o clique humano, que é o aceite do §6.4.
- **Segredos nunca em log, snapshot ou auditoria** (§19). Esta frente não lê nem grava segredo; o caminho do Vault segue sendo o que a SoT guarda.
- **Sem dependência nova**: `whois` é binário já usado desde a F5. `ipaddress` é stdlib.
- **Git no worktree**: o hook de isolamento recusa comandos compostos. Rodar `git add` e `git commit` como comandos **separados**; mensagem de várias linhas vai por arquivo (`git commit -F /tmp/msg.txt`).
- **Banco de teste**: a suíte usa `gerenet_test` e TRUNCATE a cada teste; o alembic lê `GERENET_DATABASE_URL` (não a var de teste). Migrar os dois bancos antes de rodar pytest.
- Suíte: `uv run pytest -q` · lint: `uv run ruff check src tests` · web: `cd web && npm run build && npm run test`.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/gerenet/automation/irr.py` (modificar) | A decodificação do whois, o parser do registro e `identificar_asn`. |
| `src/gerenet/domain/models.py` (modificar) | `organizations.document` e o valor `registro` em `AUTH_ORIGIN`. |
| `src/gerenet/domain/schemas.py` (modificar) | `document` nas três schemas de organização, o `Literal` da origem, `AdocaoAutorizacaoIn` e a resposta do prefill. |
| `src/gerenet/domain/services/prefix_authorizations.py` (modificar) | `create_authorization(commit=False)`, idempotência por prefixo e a mensagem de conflito com as duas organizações. |
| `src/gerenet/domain/services/discovery.py` (modificar) | A guarda da lista e a criação das autorizações na transação da adoção. |
| `src/gerenet/api/routers/organizations.py` (modificar) | `GET /prefill` — declarado antes de `/{organization_id}`. |
| `alembic/versions/c4a8e1f0b7d3_organizacao_document_e_registro.py` (criar) | A coluna e o valor de enum. |
| `web/src/api/types.ts` + `hooks.ts` (modificar) | Tipos do prefill e o hook do botão. |
| `web/src/pages/DiscoveryAdopt.tsx` (modificar) | O botão, a lista de blocos e o payload. |
| `web/src/help.ts` (modificar) | Os textos de ajuda dos três campos novos. |
| `tests/automation/test_irr.py`, `tests/domain/test_prefix_authorizations_irr_rpki.py`, `tests/domain/test_adocao.py`, `tests/api/test_organizations_api.py`, `tests/api/test_discovery_adopt_api.py`, `web/src/pages/Discovery.test.tsx`, `web/e2e/discovery.spec.ts` | Os testes. |
| `docs/wiki/descoberta.md`, `docs/runbook-validacao-ne8000.md`, `CLAUDE.md` | A documentação. |

---

## Task 1: O whois que não derruba na resposta em latin-1

O `_executa_whois` chama `subprocess.run(..., text=True)`. O nic.br responde em latin-1, e a decodificação UTF-8 estoura **dentro do `run`** com `UnicodeDecodeError` — que não é `OSError` nem `SubprocessError`, então escaparia do `except` do módulo como 500 em vez de virar `_FalhaRede` tratada. O conserto é do módulo inteiro, e não só da consulta nova.

**Files:**
- Modify: `src/gerenet/automation/irr.py:98-114`
- Test: `tests/automation/test_irr.py` (helper `_mapa_whois`, linha ~90, e testes novos no fim do arquivo)

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `_executa_whois(servidor: str, argumentos: list[str]) -> str` — assinatura inalterada, agora com decodificação tolerante. Todas as consultas do módulo (`consultar`, `_resolve`, `_consulta_rotas_do_asn`) herdam o conserto sem mudança.

- [ ] **Step 1: Ajustar o helper do mock para devolver bytes**

`_mapa_whois` hoje devolve `stdout` como `str`. Depois do conserto, `_executa_whois` decodifica bytes, e um `str` no mock daria `AttributeError`. Trocar o corpo do `_run` interno (linhas ~90-96) por:

```python
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
```

O outro `CompletedProcess` do arquivo (linha ~409, `returncode=4`) não precisa mudar: o returncode é conferido antes da decodificação, e aquele teste fala justamente da falha de rede.

- [ ] **Step 2: Escrever o teste que falha**

No fim de `tests/automation/test_irr.py`:

```python
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
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest -q tests/automation/test_irr.py::test_consultar_aceita_resposta_em_latin1`
Expected: FAIL com `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xfa in position ...` (o byte da sondagem real).

- [ ] **Step 4: Implementar**

Em `src/gerenet/automation/irr.py`, acrescentar `_decodifica` antes de `_executa_whois` e reescrever a chamada:

```python
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
```

(`text=True` sai; `capture_output=True` sem ele já devolve bytes.)

- [ ] **Step 5: Rodar o arquivo inteiro**

Run: `uv run pytest -q tests/automation/test_irr.py`
Expected: PASS (todos, incluindo os ~20 que já existiam — eles são a prova de que o conserto não mudou o comportamento nas respostas que já decodificavam).

- [ ] **Step 6: Commit**

```
git add src/gerenet/automation/irr.py tests/automation/test_irr.py
git commit -F /tmp/organizacao-asn-t1.txt
```

Mensagem (`/tmp/organizacao-asn-t1.txt`):

```
fix(irr): o whois decodifica em latin-1 quando o UTF-8 não dá

A resposta do nic.br é latin-1 e o `text=True` do `_executa_whois` estourava
UnicodeDecodeError de dentro do `subprocess.run` — exceção que não é OSError
nem SubprocessError, logo fora do except do módulo: um 500 no lugar da falha
de rede tratada. A decodificação passa a ser nossa, com queda para latin-1,
e todas as consultas do módulo herdam o conserto.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Task 2: `identificar_asn` — a leitura do registro

**Files:**
- Modify: `src/gerenet/automation/irr.py` (docstring do módulo, imports, e a seção nova no fim)
- Test: `tests/automation/test_irr.py`

**Interfaces:**
- Consumes: `_executa_whois` e `_FalhaRede` da Task 1; `_dedup_ordem`, `_fresca`, `_vivo`, `IrrError` e `SessionLocal` que já existem no módulo.
- Produces: `identificar_asn(asn: int, *, ttl_horas: int = 24) -> dict` com a forma
  `{"nome": str|None, "razao_social": str|None, "documento": str|None, "pais": str|None, "as_set_sugerido": str|None, "as_sets": list[str], "blocos": [{"prefix": str, "family": "ipv4"|"ipv6", "fonte": "registro", "conflito": str|None}], "fontes": dict[str, str], "avisos": list[str]}`.
  Levanta `IrrError` só quando as duas consultas falham sem cache vivo. Também produz `_parseia_aut_num`, `_parseia_registro_lacnic` e `_dado_do_bloco` (privadas, usadas só aqui).

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/automation/test_irr.py`, antes do bloco da Task 1 (ou depois — a ordem no arquivo não importa):

```python
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
```

No topo do arquivo de teste, a linha do `irr` (hoje `from gerenet.automation.irr import IrrError, consultar`) passa a trazer `identificar_asn`, e as três linhas seguintes são novas:

```python
from gerenet.automation.irr import IrrError, consultar, identificar_asn
from gerenet.domain.schemas import OrganizationCreate, PrefixAuthorizationCreate
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
```

(`select`, `models`, `logging`, `subprocess`, `pytest`, `datetime`, `_linha_cache` e `_fake_falha` já estão lá — os dois helpers são reusados pelos testes novos.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/automation/test_irr.py -k identificar`
Expected: FAIL com `ImportError: cannot import name 'identificar_asn'`.

- [ ] **Step 3: Implementar**

Em `src/gerenet/automation/irr.py`:

1. O docstring do módulo passa a se apresentar como as duas consultas (a sigla IRR ficou mais estreita que o conteúdo). Acrescentar ao fim da lista de decisões:

```
- `identificar_asn` (design da organização por ASN) é a SEGUNDA consulta do
  módulo: o objeto `aut-num` do RADB (consulta direta, `whois -h
  whois.radb.net AS<n>`) para `as-name`/`descr`/`member-of`, e a consulta
  direta no LACNIC para `owner`/`ownerid`/`country`/`inetnum` — o LACNIC
  delega os ASNs brasileiros ao registro.br, então um servidor só resolve o
  caso nacional. Cache em `irr_cache` com `source="registro"` e
  `key=str(asn)`; falha de UMA fonte vira aviso, falha das DUAS sobe
  `IrrError`; resposta parcial é estado normal, não erro.
```

2. Import novo: `import ipaddress` (junto de `logging`/`re`/`subprocess`).

3. No fim do arquivo:

```python
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
```

`Session` vem de `sqlalchemy.orm` — acrescentar o import.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q tests/automation/test_irr.py`
Expected: PASS (os novos e os que já existiam).

- [ ] **Step 5: Commit**

```
git add src/gerenet/automation/irr.py tests/automation/test_irr.py
git commit -F /tmp/organizacao-asn-t2.txt
```

Mensagem:

```
feat(irr): identificar_asn lê a identidade e os blocos alocados

O `aut-num` do RADB dá nome, razão social e `member-of`; a consulta direta no
LACNIC, que delega os ASNs brasileiros ao registro.br, dá `owner`, `ownerid`,
`country` e os blocos `inetnum`. Cache de 24h em `irr_cache` com
`source="registro"`, a mesma política fail-soft do `consultar`: uma fonte fora
vira aviso, as duas fora sem cache vivo sobem IrrError.

O `conflito` de cada bloco é recalculado a cada chamada e fica de fora do
cache — é estado da SoT, e um bloco livre hoje pode estar tomado daqui a uma
hora.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Task 3: `organizations.document` e o valor `registro` no enum

**Files:**
- Modify: `src/gerenet/domain/models.py` (linha ~38 o enum `AUTH_ORIGIN`, linha ~199 a coluna nova), `src/gerenet/domain/schemas.py` (`OrganizationCreate`, `OrganizationUpdate`, `OrganizationOut`, `PrefixAuthorizationCreate.origin`)
- Create: `alembic/versions/c4a8e1f0b7d3_organizacao_document_e_registro.py`
- Test: `tests/api/test_organizations_api.py`

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: a coluna `organizations.document` (`String(32)`, nula) e o valor `"registro"` válido em `auth_origin`. `OrganizationCreate`/`OrganizationUpdate`/`OrganizationOut` carregam `document: str | None`; `PrefixAuthorizationCreate.origin` aceita `"registro"`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/api/test_organizations_api.py`:

```python
def test_cria_organizacao_com_o_documento_do_registro(client: TestClient) -> None:
    """`document` é o `ownerid` do registro: genérico, e não `cnpj`, porque
    operadora estrangeira não tem CNPJ."""
    resp = client.post(
        "/api/v1/organizations",
        json={"name": "Cliente Documento", "asn": 64530, "document": "13.172.064/0001-11"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["document"] == "13.172.064/0001-11"

    corpo = client.patch(
        f"/api/v1/organizations/{resp.json()['id']}",
        json={"document": "13.172.064/0002-22"},
        headers=_auth(),
    ).json()
    assert corpo["document"] == "13.172.064/0002-22"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/api/test_organizations_api.py::test_cria_organizacao_com_o_documento_do_registro`
Expected: FAIL em `resp.json()["document"]` com `KeyError: 'document'` — o `document` do corpo é ignorado pelo Pydantic (o schema ainda não o tem) e não volta na resposta. Se o schema base do projeto usar `extra="forbid"`, a falha vem antes, como 422 no `assert resp.status_code == 201`. Nos dois casos é o schema que falta, e não a coluna.

(O `alembic upgrade head` só roda no Step 5: a migração nasce no Step 4, e migrar antes disso não tem o que aplicar.)

- [ ] **Step 3: Implementar o modelo e as schemas**

`src/gerenet/domain/models.py`, o enum (linha ~38):

```python
AUTH_ORIGIN = ("manual", "irr", "rpki", "registro")
```

e a coluna, em `Organization`, logo depois de `legal_name`:

```python
    # O `ownerid` do registro (CNPJ no Brasil): genérico, e não `cnpj`, porque
    # organização de operadora estrangeira não tem CNPJ.
    document: Mapped[str | None] = mapped_column(String(32))
```

`src/gerenet/domain/schemas.py` — `document` em `OrganizationCreate` (depois de `legal_name`), em `OrganizationUpdate` e em `OrganizationOut`, sempre:

```python
    document: str | None = Field(default=None, max_length=32)
```

(`OrganizationOut` usa `Field(default=None, max_length=32)` também; se a classe tiver `model_config` com `from_attributes`, nada mais muda.)

E `PrefixAuthorizationCreate.origin`:

```python
    origin: Literal["manual", "irr", "rpki", "registro"] = "manual"
```

- [ ] **Step 4: Escrever a migração**

Criar `alembic/versions/c4a8e1f0b7d3_organizacao_document_e_registro.py` (o cabeçalho segue o molde de `767551f719ba_upstreams_f5.py`):

```python
"""organização: o documento do registro e a origem `registro`

Revision ID: c4a8e1f0b7d3
Revises: 39e3d1479c6a
Create Date: 2026-09-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4a8e1f0b7d3'
down_revision: str | Sequence[str] | None = '39e3d1479c6a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("document", sa.String(length=32), nullable=True)
    )
    # Precedente da F5 (767551f719ba). O valor nasce fora dos dois caminhos da
    # revalidação — `revalidar_autorizacoes` filtra `origin.in_(("irr","rpki"))`
    # —, e é exatamente por isso que ele existe: marcar o bloco do registro
    # como `irr` faria a revalidação consultar `-i origin` no RADB, não achar
    # rota nenhuma no caso comum e marcar tudo `diverge` para sempre.
    op.execute("ALTER TYPE auth_origin ADD VALUE IF NOT EXISTS 'registro'")


def downgrade() -> None:
    op.drop_column("organizations", "document")
    # O valor 'registro' permanece no tipo: o Postgres não remove valor de enum,
    # e recriar o tipo com a coluna em uso custaria mais do que a sobra (mesmo
    # downgrade da F5).
```

- [ ] **Step 5: Migrar os dois bancos e rodar**

Run: `uv run alembic upgrade head`
Run: `GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head`
Run: `uv run pytest -q tests/api/test_organizations_api.py`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS. (Se `tests/worker/` cair, ver a nota do fim do plano.)

- [ ] **Step 6: Commit**

```
git add src/gerenet/domain/models.py src/gerenet/domain/schemas.py alembic/versions/c4a8e1f0b7d3_organizacao_document_e_registro.py tests/api/test_organizations_api.py
git commit -F /tmp/organizacao-asn-t3.txt
```

Mensagem:

```
feat(organizacao): o documento do registro e a origem `registro`

A coluna `organizations.document` guarda o `ownerid` do registro — genérica, e
não `cnpj`, porque operadora estrangeira não tem CNPJ. O valor novo do enum
`auth_origin` nasce fora dos dois caminhos da revalidação sem nenhuma linha
nova, e é por isso que ele existe: o bloco do registro não é anunciado, então
marcá-lo como `irr` faria a revalidação marcá-lo `diverge` para sempre.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Task 4: `create_authorization` encadeável, idempotente, e os dois testes que pinam a revalidação

**Files:**
- Modify: `src/gerenet/domain/services/prefix_authorizations.py` (linhas 48-88)
- Test: `tests/domain/test_prefix_authorizations_irr_rpki.py`

**Interfaces:**
- Consumes: `"registro"` no enum e no `Literal` (Task 3).
- Produces: `create_authorization(session, data, *, actor: str, commit: bool = True)`. Com `commit=True` o comportamento é o de hoje; com `commit=False` a escrita fica pendente na transação de quem chamou. Criar um prefixo que a organização já tem ativo devolve a linha existente sem criar nem auditar.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/domain/test_prefix_authorizations_irr_rpki.py`, o helper `_auth` ganha `family` (o default preserva as chamadas que já existem) e os testes novos vão no fim:

```python
def _auth(
    db_session: Session, org_id: int, prefix: str, *,
    origin: str | None = None, family: str = "ipv4",
) -> models.BgpPrefixAuthorization:
    """Cria com `origin` quando informado; sem ele vale o default do schema."""
    dados: dict = {"organization_id": org_id, "family": family, "prefix": prefix}
    if origin is not None:
        dados["origin"] = origin
    return create_authorization(
        db_session, PrefixAuthorizationCreate(**dados), actor="cli"
    )
```

```python
# ---- origem `registro` (design da organização por ASN) ----

def test_create_origin_registro_deixa_a_validacao_nula(db_session: Session) -> None:
    """O bloco do registro não é anunciado: não há contra o que validar, e
    inventar uma comparação contra o próprio `inetnum` seria validar a fonte
    contra ela mesma (design §12)."""
    org = _org(db_session, "Cliente Registro", 264289)
    auth = _auth(db_session, org, "138.121.28.0/22", origin="registro")

    assert auth.origin == "registro"
    assert auth.validacao is None


def test_revalidar_nao_toca_a_origem_registro(db_session: Session, monkeypatch) -> None:
    """`revalidar_autorizacoes` filtra `origin.in_(("irr","rpki"))`, então o
    valor novo fica de fora sem nenhuma linha de código a mais. Este teste
    existe para que ninguém "conserte" isso depois: se o filtro passar a
    incluir `registro`, a revalidação consulta `-i origin` no RADB, não acha
    rota nenhuma e marca o bloco `diverge` para sempre."""
    org = _org(db_session, "Cliente Registro", 264289)
    _auth(db_session, org, "138.121.28.0/22", origin="registro")
    _auth(db_session, org, "200.160.0.0/22", origin="irr")
    payload = {"asns": [264289], "prefixos": ["200.160.0.0/22"]}
    monkeypatch.setattr(
        "gerenet.domain.services.prefix_authorizations.consultar",
        lambda *a, **kw: payload,
    )

    assert revalidar_autorizacoes(db_session) == 1  # só a de origem irr

    por_prefixo = _por_prefixo(db_session)
    assert por_prefixo["200.160.0.0/22"].validacao == "ok"
    assert por_prefixo["138.121.28.0/22"].validacao is None


# ---- §3.2: reexecutar não duplica ----

def test_autorizacao_repetida_devolve_a_existente(db_session: Session) -> None:
    """O `_organizacao_conflitante` ignora a própria organização, então sem
    esta guarda a duplicata passaria calada."""
    org = _org(db_session, "Cliente Idempotente", 64512)
    primeira = _auth(db_session, org, "200.160.0.0/22", origin="registro")
    segunda = _auth(db_session, org, "200.160.0.0/22", origin="registro")

    assert segunda.id == primeira.id
    assert len(_por_prefixo(db_session)) == 1
    tipos = [e.type for e in db_session.scalars(select(models.AuditEvent))]
    assert tipos.count("authorization.create") == 1


def test_autorizacao_sem_commit_nao_persiste_sozinha(db_session: Session) -> None:
    """`commit=False` é o que deixa a adoção encadear tudo numa transação."""
    org = _org(db_session, "Cliente Encadeado", 64512)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org, family="ipv4", prefix="200.160.0.0/22",
            origin="registro",
        ),
        actor="cli",
        commit=False,
    )
    db_session.rollback()

    assert _por_prefixo(db_session) == {}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/domain/test_prefix_authorizations_irr_rpki.py`
Expected: FAIL — `TypeError: create_authorization() got an unexpected keyword argument 'commit'` (e a duplicata criando duas linhas).

- [ ] **Step 3: Implementar**

Em `src/gerenet/domain/services/prefix_authorizations.py`, a assinatura e o corpo de `create_authorization`:

```python
def create_authorization(
    session: Session, data: PrefixAuthorizationCreate, *, actor: str, commit: bool = True
) -> models.BgpPrefixAuthorization:
    """Cria a autorização; `commit=False` é para a adoção encadear a dela."""
    org = get_organization(session, data.organization_id)
    if org.admin_status is False:
        raise ConflictError(f"Organização {org.name} desativada não recebe autorizações.")
    if org.kind == "operadora":
        raise ValidationError(
            "Organização do tipo operadora não recebe autorizações de prefixo de cliente."
        )
    cidr_valido(data.prefix, data.family)  # CIDR alinhado da família certa (mensagens PT)
    # §3.2: reexecutar a mesma operação não duplica. O `_organizacao_conflitante`
    # abaixo ignora a própria organização, então sem esta guarda o prefixo
    # repetido passaria calado — e é a lista da adoção que pode trazer o mesmo
    # bloco duas vezes.
    existente = session.scalars(
        select(models.BgpPrefixAuthorization).where(
            models.BgpPrefixAuthorization.organization_id == data.organization_id,
            models.BgpPrefixAuthorization.family == data.family,
            models.BgpPrefixAuthorization.prefix == data.prefix,
            models.BgpPrefixAuthorization.admin_status.is_(True),
        )
    ).first()
    if existente is not None:
        return existente
    outra = _organizacao_conflitante(
        session, organization_id=data.organization_id, family=data.family, prefix=data.prefix
    )
    if outra is not None:
        # As duas organizações no texto: quem lê o 409 precisa saber de quem é o
        # bloco e quem o pediu (design §7).
        raise ConflictError(
            f"Prefixo {data.prefix} sobrepõe autorização de {outra.name}: "
            f"{org.name} não pode receber este bloco."
        )
    dump = data.model_dump()
    auth = models.BgpPrefixAuthorization(**dump)
    # Origem IRR/RPKI: validação consultiva (§10.4) — nasce não verificada e é
    # recalculada por revalidar_autorizacoes; origem manual e `registro` ficam
    # sem validação (o bloco alocado não é anúncio, não há o que validar).
    if data.origin in ("irr", "rpki"):
        auth.validacao = "nao_verificada"
    session.add(auth)
    try:
        session.flush()  # valida a FK antes da auditoria
        registrar(
            session, tipo="authorization.create", ator=actor, objeto="authorization",
            objeto_id=auth.id, antes=None, depois=dump,
        )
        if commit:
            session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "Não foi possível criar a autorização de prefixo: conflito de integridade."
        ) from exc
    if commit:
        session.refresh(auth)
    return auth
```

O docstring do módulo (linha ~3) passa a dizer também que a origem `registro` é o bloco alocado lido do registro, sem validação.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q tests/domain/test_prefix_authorizations_irr_rpki.py tests/domain/test_prefix_authorizations_service.py tests/api/test_prefix_authorizations_api.py`
Expected: PASS. (O teste de conflito em `test_prefix_authorizations_service.py:82` casa por `match="sobrepõe autorização de Cliente Gama"` — o texto novo preserva esse trecho, então ele continua passando.)

- [ ] **Step 5: Commit**

```
git add src/gerenet/domain/services/prefix_authorizations.py tests/domain/test_prefix_authorizations_irr_rpki.py
git commit -F /tmp/organizacao-asn-t4.txt
```

Mensagem:

```
feat(autorizacao): commit encadeável, idempotência e a origem `registro`

`create_authorization` ganha `commit: bool = True`, como `create_organization`
e `reservar_adocao`, para a adoção encadear na transação dela. O prefixo que a
organização já tem ativo devolve a linha existente sem criar nem auditar
(§3.2), e o 409 do conflito passa a nomear as duas organizações.

Dois testes pinam o que a origem `registro` depende para não virar `diverge`
eterno: ela nasce sem validação e `revalidar_autorizacoes` não a toca.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Task 5: `GET /api/v1/organizations/prefill`

**Files:**
- Modify: `src/gerenet/api/routers/organizations.py`, `src/gerenet/domain/schemas.py`
- Test: `tests/api/test_organizations_api.py`

**Interfaces:**
- Consumes: `identificar_asn` (Task 2), `IrrError`, `asn_valido`.
- Produces: `GET /api/v1/organizations/prefill?asn=N` → `200` com `OrganizationPrefillOut`, `404` sem dado nenhum, `503` quando a consulta falha sem cache, `422` para ASN inválido ou reservado.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/api/test_organizations_api.py`:

```python
# ---- prefill (design §8) ----

PREFILL = {
    "nome": "PROVEINTERLTDA-AS",
    "razao_social": "PROVEINTER LTDA",
    "documento": "13.172.064/0001-11",
    "pais": "BR",
    "as_set_sugerido": "AS-264289",
    "as_sets": ["AS-264289"],
    "blocos": [
        {"prefix": "138.121.28.0/22", "family": "ipv4", "fonte": "registro", "conflito": None},
    ],
    "fontes": {"nome": "radb", "blocos": "registro"},
    "avisos": [],
}


def _stub_prefill(monkeypatch, resultado=None, erro=None) -> None:
    """O whois nunca é chamado num teste de API: o que se testa aqui é o
    contrato da rota, e não a leitura (essa tem os testes dela)."""
    def _fake(asn: int, **kwargs):
        if erro is not None:
            raise erro
        return resultado if resultado is not None else {**PREFILL, "asn": asn}

    monkeypatch.setattr("gerenet.api.routers.organizations.identificar_asn", _fake)


def test_prefill_devolve_o_que_o_registro_deu(client: TestClient, monkeypatch) -> None:
    _stub_prefill(monkeypatch)
    resp = client.get("/api/v1/organizations/prefill?asn=264289", headers=_auth())

    assert resp.status_code == 200, resp.text
    assert resp.json()["asn"] == 264289
    assert resp.json()["documento"] == "13.172.064/0001-11"
    assert resp.json()["blocos"][0]["conflito"] is None


def test_prefill_parcial_e_200(client: TestClient, monkeypatch) -> None:
    """Identidade sem blocos (ASN estrangeiro) é resposta, não erro: confundir
    as duas faz o operador concluir que o ASN não tem dado nenhum."""
    _stub_prefill(monkeypatch, resultado={
        **PREFILL, "documento": None, "pais": None, "blocos": [],
        "avisos": ["O registro não devolveu blocos `inetnum` para AS13335 — ..."],
    })
    resp = client.get("/api/v1/organizations/prefill?asn=13335", headers=_auth())

    assert resp.status_code == 200, resp.text
    assert resp.json()["blocos"] == []
    assert resp.json()["avisos"] != []


def test_prefill_sem_nada_nas_duas_fontes_e_404(client: TestClient, monkeypatch) -> None:
    _stub_prefill(monkeypatch, resultado={
        **PREFILL, "nome": None, "razao_social": None, "documento": None,
        "pais": None, "as_set_sugerido": None, "as_sets": [], "blocos": [],
    })
    resp = client.get("/api/v1/organizations/prefill?asn=64500", headers=_auth())

    assert resp.status_code == 404
    assert "não devolveu nada" in resp.json()["detail"]


def test_prefill_com_a_consulta_fora_e_503(client: TestClient, monkeypatch) -> None:
    """503 é falha de consulta, e não ausência de dado: o operador precisa
    saber que pode tentar de novo."""
    _stub_prefill(monkeypatch, erro=IrrError("sem cache vivo"))
    resp = client.get("/api/v1/organizations/prefill?asn=64500", headers=_auth())

    assert resp.status_code == 503


def test_prefill_recusa_asn_reservado(client: TestClient) -> None:
    """64496-64511 é faixa de documentação (RFC 5398): `asn_valido` recusa."""
    resp = client.get("/api/v1/organizations/prefill?asn=64496", headers=_auth())

    assert resp.status_code == 422


def test_prefill_convive_com_a_rota_de_detalhe(client: TestClient, monkeypatch) -> None:
    """`/prefill` é declarado ANTES de `/{organization_id}`, que o capturaria
    como um id inválido — o FastAPI casa as rotas na ordem de declaração."""
    _stub_prefill(monkeypatch)

    assert client.get("/api/v1/organizations/prefill?asn=64512", headers=_auth()).status_code == 200
    assert client.get("/api/v1/organizations/999999", headers=_auth()).status_code == 404
```

`import` novo: `from gerenet.automation.irr import IrrError`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/api/test_organizations_api.py -k prefill`
Expected: FAIL com 404 em tudo — sem a rota, `/prefill` cai em `/{organization_id}` e o path param inteiro não casa.

- [ ] **Step 3: Implementar**

`src/gerenet/domain/schemas.py`, junto das outras schemas de organização:

```python
class OrganizationPrefillBlocoOut(BaseModel):
    """Um bloco alocado ao AS, na forma que a tela consome."""

    prefix: str
    family: Literal["ipv4", "ipv6"]
    fonte: str
    # Nome da organização que já tem autorização ativa sobre o bloco; nulo no
    # caso comum (design §7).
    conflito: str | None = None


class OrganizationPrefillOut(BaseModel):
    """O cadastro de uma organização lido do registro — nada aqui é gravado.

    Resposta parcial é normal: ASN estrangeiro devolve identidade sem blocos,
    ASN sem objeto no RADB devolve blocos sem nome, e o motivo de cada ausência
    está em `avisos`.
    """

    asn: int
    nome: str | None
    razao_social: str | None
    documento: str | None
    pais: str | None
    as_set_sugerido: str | None
    as_sets: list[str]
    blocos: list[OrganizationPrefillBlocoOut]
    fontes: dict[str, str]
    avisos: list[str]
```

`src/gerenet/api/routers/organizations.py` — os imports:

```python
from gerenet.automation.irr import IrrError, identificar_asn
from gerenet.domain.schemas import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationPrefillOut,
    OrganizationUpdate,
)
from gerenet.domain.validators import asn_valido
```

E a rota, **entre `listar` e `detalhar`** (a ordem no arquivo é o que a faz ser casada antes de `/{organization_id}`):

```python
@router.get("/prefill", response_model=OrganizationPrefillOut)
def prefill(asn: int) -> dict:
    """O cadastro de uma organização lido do registro (design §8).

    Declarada ANTES de `/{organization_id}`: o FastAPI casa as rotas na ordem
    de declaração, e `/{organization_id}` capturaria `/prefill` como um id
    inválido antes de chegar aqui.

    O `asn` vem pela validação do `asn_valido` (a mesma do cadastro) e a falha
    de consulta vira 503 — que é diferente do 404 de "não há dado nenhum".
    """
    if not asn_valido(asn):
        raise HTTPException(status_code=422, detail=f"ASN inválido ou reservado: {asn}.")
    try:
        dados = identificar_asn(asn)
    except IrrError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not any([dados["nome"], dados["razao_social"], dados["blocos"]]):
        raise HTTPException(
            status_code=404, detail=f"O registro não devolveu nada para AS{asn}."
        )
    return {"asn": asn, **dados}
```

O `asn_valido` aqui devolve **422**, e não o 400 que o `POST /organizations` devolve quando o serviço recusa (o `ValidationError` vira 400 no `criar`). Os dois convivem porque são camadas diferentes: lá é o serviço recusando um corpo já formado; aqui é o parâmetro da consulta, que o próprio FastAPI já responde 422 quando não é inteiro. É a decisão da spec §8, e o teste prende o número.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q tests/api/test_organizations_api.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add src/gerenet/api/routers/organizations.py src/gerenet/domain/schemas.py tests/api/test_organizations_api.py
git commit -F /tmp/organizacao-asn-t5.txt
```

Mensagem:

```
feat(api): GET /organizations/prefill lê o cadastro do registro

Leitura e autenticada, no router de organizações e não no de discovery: o que
ela devolve é preenchimento de organização, e a página de organizações pode
usar o mesmo endpoint quando ganhar o botão.

Declarada antes de `/{organization_id}` — o FastAPI casa as rotas na ordem de
declaração e o path param capturaria `/prefill`. 200 parcial é normal; 404 é
"não há dado nenhum" e 503 é "não deu para consultar", que são estados
diferentes e o operador precisa distinguir.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Task 6: A lista de autorizações na transação da adoção

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`AdocaoIn`), `src/gerenet/domain/services/discovery.py` (`adotar_proposta`)
- Test: `tests/domain/test_adocao.py`, `tests/api/test_discovery_adopt_api.py`

**Interfaces:**
- Consumes: `create_authorization(..., commit=False)` (Task 4).
- Produces: `AdocaoAutorizacaoIn{prefix: str, family: Literal["ipv4","ipv6"]}` e `AdocaoIn.autorizacoes: list[AdocaoAutorizacaoIn]` (default vazio). Cada item vira uma `BgpPrefixAuthorization` da organização nova, com `origin="registro"` e nota com o ASN consultado, na mesma transação do circuito.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/domain/test_adocao.py`, os imports do topo passam a ser estes (as cinco linhas novas são `AdocaoAutorizacaoIn`, `OrganizationCreate`, `PrefixAuthorizationCreate` e os dois serviços do fim):

```python
from gerenet.automation.discovery import conferir_fidelidade, listar_propostas
from gerenet.domain import models
from gerenet.domain.schemas import (
    AdocaoAutorizacaoIn,
    AdocaoIn,
    AdocaoSessaoIn,
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import adotar_proposta
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device
```

E o helper `_revisao` ganha o parâmetro `autorizacoes`:

```python
def _revisao(dev, *, vid=1001, ciente=True, edge_trunk="Eth-Trunk127", sessoes=None,
             autorizacoes=None):
    """A revisão do enlace do CLIENTE-ALFA (o vid 1001 da fixture).

    O `ciente` nasce ligado porque este enlace TEM diferença no grupo que muda:
    o peer tem senha no equipamento (`password cipher`, mascarada na conferência)
    e a SoT não a reproduz — o render só comenta que ela está no Vault. Sem o
    aceite explícito, a adoção recusa, e é o que o teste do `ciente` prende. O
    `edge_trunk` é o que o ensaio derivaria do nome da subinterface, e a adoção
    recusa a revisão que não o traga.
    """
    return AdocaoIn(
        device_id=dev.id, vrf=None, subinterface=f"Eth-Trunk127.{vid}",
        circuit_code=f"ADOC-64512-{vid}", access_device_id=dev.id, access_port="GE0/0/1",
        edge_trunk=edge_trunk,
        organizacao_nova={"name": "Cliente Alfa", "kind": "downstream", "asn": 64512},
        sessoes=sessoes if sessoes is not None else [
            AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA),
            AdocaoSessaoIn(afi="ipv6"),
        ],
        autorizacoes=autorizacoes or [],
        ciente=ciente,
    )
```

E, no fim do arquivo:

```python
# ---- as autorizações do registro na transação da adoção (design §6) ----

def _autorizacoes(db_session) -> list[models.BgpPrefixAuthorization]:
    return list(db_session.scalars(
        select(models.BgpPrefixAuthorization).order_by(models.BgpPrefixAuthorization.prefix)
    ))


def test_adota_gravando_as_autorizacoes_do_registro(db_session, tmp_path) -> None:
    """Os blocos entram na MESMA transação da organização e do circuito, com a
    procedência gravada: é o que deixa uma auditoria futura saber quais
    autorizações foram preenchidas pela máquina."""
    site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
        AdocaoAutorizacaoIn(prefix="2804:2594::/32", family="ipv6"),
    ])

    adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao, actor="cli")

    auths = _autorizacoes(db_session)
    assert [a.prefix for a in auths] == ["138.121.28.0/22", "2804:2594::/32"]
    org = db_session.scalars(select(models.Organization)).one()
    assert {a.organization_id for a in auths} == {org.id}
    assert {a.origin for a in auths} == {"registro"}
    assert {a.validacao for a in auths} == {None}
    assert all("AS64512" in a.notes for a in auths)
    assert [e.type for e in db_session.scalars(select(models.AuditEvent))].count(
        "authorization.create"
    ) == 2


def test_bloco_conflitante_desfaz_a_adocao_inteira(db_session, tmp_path) -> None:
    """O conflito de sobreposição é por bloco (§7), e a guarda é de defesa em
    profundidade: se um bloco conflitante chegar pela API, quem recusa é o
    `create_authorization`, com o nome das duas organizações — e a transação
    inteira desfaz, no mesmo estilo das outras guardas da adoção."""
    outra = create_organization(
        db_session, OrganizationCreate(name="Cliente Beta", asn=64513), actor="cli"
    )
    create_authorization(db_session, PrefixAuthorizationCreate(
        organization_id=outra.id, family="ipv4", prefix="138.121.28.0/24"), actor="cli")
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])

    with pytest.raises(ConflictError) as excinfo:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert "Cliente Beta" in str(excinfo.value)
    assert "Cliente Alfa" in str(excinfo.value)
    # Nada ficou: nem a organização, nem a autorização, nem o circuito.
    assert db_session.scalars(select(models.Organization)).all() == [outra]
    assert _autorizacoes(db_session) == []
    assert db_session.scalars(select(models.Circuit)).all() == []


def test_autorizacoes_com_organizacao_existente_sao_recusadas(db_session, tmp_path) -> None:
    """A lista só vale com a organização nova: para uma existente, os blocos
    dela se cadastram na página da organização — e somá-los calado aqui
    autorizaria prefixo que ninguém revisou nesta tela."""
    existente = create_organization(
        db_session, OrganizationCreate(name="Cliente Existente", asn=64514), actor="cli"
    )
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])
    revisao.organizacao_nova = None
    revisao.organizacao_id = existente.id

    with pytest.raises(ValidationError, match="organização nova"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert _autorizacoes(db_session) == []


def test_operadora_nao_recebe_as_autorizacoes_da_adoção(db_session, tmp_path) -> None:
    """Autorização de prefixo é de cliente: o operador tem
    `expected_prefixes_v4`/`v6` no upstream, que são outra coisa. A guarda do
    `create_authorization` continua valendo sem alteração."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])
    revisao.organizacao_nova.kind = "operadora"

    with pytest.raises(ValidationError, match="operadora"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert db_session.scalars(select(models.Organization)).all() == []
    assert _autorizacoes(db_session) == []


def test_adotar_de_novo_nao_cria_nada(db_session, tmp_path) -> None:
    """A segunda tentativa com a mesma revisão esbarra no nome da organização,
    que já existe — e não deixa autorização nem circuito para trás."""
    _site, dev = _ambiente(db_session, tmp_path)
    proposta = _proposta(db_session, dev)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])
    adotar_proposta(db_session, proposta=proposta, revisao=revisao, actor="cli")
    antes = (len(_autorizacoes(db_session)), len(list(db_session.scalars(select(models.Circuit)))))

    with pytest.raises(ConflictError):
        adotar_proposta(db_session, proposta=proposta, revisao=revisao, actor="cli")

    assert (len(_autorizacoes(db_session)),
            len(list(db_session.scalars(select(models.Circuit))))) == antes
```

Em `tests/api/test_discovery_adopt_api.py`, os imports do topo passam a ser estes (as quatro linhas novas são as que o segundo teste precisa):

```python
from gerenet.domain.schemas import (
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device
```

O helper `_payload` (que devolve o corpo do POST) fica como está — a lista entra por `corpo["autorizacoes"] = [...]` em cada teste, e os testes que já existem seguem sem ela, exercitando o default vazio. E os dois testes novos:

```python
def test_adopt_grava_as_autorizacoes_do_registro(client: TestClient, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["autorizacoes"] = [{"prefix": "138.121.28.0/22", "family": "ipv4"}]

    resp = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())

    assert resp.status_code == 201, resp.text
    auths = db_session.scalars(select(models.BgpPrefixAuthorization)).all()
    assert [(a.prefix, a.origin, a.validacao) for a in auths] == [
        ("138.121.28.0/22", "registro", None)
    ]


def test_adopt_recusa_bloco_conflitante(client: TestClient, db_session, tmp_path) -> None:
    outra = create_organization(
        db_session, OrganizationCreate(name="Cliente Beta", asn=64513), actor="cli"
    )
    create_authorization(db_session, PrefixAuthorizationCreate(
        organization_id=outra.id, family="ipv4", prefix="138.121.28.0/24"), actor="cli")
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["autorizacoes"] = [{"prefix": "138.121.28.0/22", "family": "ipv4"}]

    resp = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())

    assert resp.status_code == 409
    assert "Cliente Beta" in resp.json()["detail"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/domain/test_adocao.py -k autoriza`
Expected: FAIL com `TypeError: AdocaoIn.__init__() got an unexpected keyword argument 'autorizacoes'`.

- [ ] **Step 3: Implementar**

`src/gerenet/domain/schemas.py`, antes de `AdocaoIn`:

```python
class AdocaoAutorizacaoIn(BaseModel):
    """Um bloco do registro que entra como autorização da organização nova.

    Só vale junto de `organizacao_nova`: a organização existente já tem as
    autorizações dela, e somá-las por aqui autorizaria prefixo que ninguém
    revisou nesta tela.
    """

    prefix: str = Field(min_length=1, max_length=64)
    family: Literal["ipv4", "ipv6"]
```

e em `AdocaoIn`, depois de `organizacao_nova`:

```python
    autorizacoes: list[AdocaoAutorizacaoIn] = Field(default_factory=list)
```

`src/gerenet/domain/services/discovery.py`:

1. Import novo:

```python
from gerenet.domain.services.prefix_authorizations import create_authorization
```

2. A guarda, junto das outras (depois da que exige organização):

```python
    if revisao.autorizacoes and revisao.organizacao_nova is None:
        raise ValidationError(
            "As autorizações de prefixo só entram com a organização nova: para uma "
            "organização existente, cadastre os blocos na página dela."
        )
```

3. Dentro do `try`, logo depois do bloco da `create_organization`:

```python
        # Os blocos do registro entram na MESMA transação (§6 do design): a
        # organização nova e o que ela pode anunciar nascem juntos, e o clique
        # que aprovou a lista é o aceite humano do §6.4. A procedência fica
        # gravada para uma auditoria futura saber o que veio da máquina.
        for bloco in revisao.autorizacoes:
            create_authorization(
                session,
                schemas.PrefixAuthorizationCreate(
                    organization_id=organizacao_id,
                    family=bloco.family,
                    prefix=bloco.prefix,
                    origin="registro",
                    notes=f"Bloco do registro para AS{asn_remoto}, lido na adoção.",
                ),
                actor=actor,
                commit=False,
            )
```

4. No payload do `registrar(session, tipo="discovery.adopt", ...)`, ao lado de `"perfis"`:

```python
                # A lista que o operador aprovou no clique, para a trilha do
                # aceite (§6.4) — cada autorização tem o `authorization.create`
                # dela, e isto é o que amarra a lista ao que a originou.
                "autorizacoes": [
                    {"prefix": b.prefix, "family": b.family} for b in revisao.autorizacoes
                ],
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q tests/domain/test_adocao.py tests/api/test_discovery_adopt_api.py`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/discovery.py tests/domain/test_adocao.py tests/api/test_discovery_adopt_api.py
git commit -F /tmp/organizacao-asn-t6.txt
```

Mensagem:

```
feat(adocao): os blocos do registro entram na transação do adopt

`AdocaoIn.autorizacoes` só vale com `organizacao_nova` — a existente já tem as
autorizações dela —, e cada item nasce com `origin="registro"` e a nota com o
ASN consultado, para que a auditoria saiba o que foi preenchido pela máquina.

O conflito de sobreposição continua sendo por bloco: um bloco tomado por outra
organização derruba a adoção inteira com o 409 nomeando as duas, no mesmo
estilo das outras guardas.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Task 7: O botão "Buscar no registro" na revisão

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/pages/DiscoveryAdopt.tsx`, `web/src/help.ts`
- Test: `web/src/pages/Discovery.test.tsx`, `web/e2e/discovery.spec.ts`

**Interfaces:**
- Consumes: `GET /api/v1/organizations/prefill` (Task 5), `AdocaoIn.autorizacoes` e `organizacao_nova.document` (Tasks 3 e 6).
- Produces: `OrganizationPrefillOut`/`OrganizationPrefillBlocoOut` em `types.ts`, `document` em `OrganizationOut` e em `OrganizationCreateIn`, `usePrefill()` em `hooks.ts`, os textos de ajuda `adocao.razao_social`/`adocao.documento`/`adocao.as_set` em `help.ts`.

- [ ] **Step 1: Escrever os tipos e o hook**

`web/src/api/types.ts` — `document: string | null;` em `OrganizationOut`, logo depois de `legal_name`, e as duas interfaces novas:

```ts
export interface OrganizationPrefillBlocoOut {
  prefix: string;
  family: "ipv4" | "ipv6";
  fonte: string;
  /** Nome da organização que já tem autorização ativa sobre o bloco. */
  conflito: string | null;
}

/** O cadastro lido do registro — nada aqui é gravado; quem grava é a adoção.
 * Resposta parcial é normal: o ASN estrangeiro não traz blocos, e o motivo
 * está em `avisos`. */
export interface OrganizationPrefillOut {
  asn: number;
  nome: string | null;
  razao_social: string | null;
  documento: string | null;
  pais: string | null;
  as_set_sugerido: string | null;
  as_sets: string[];
  blocos: OrganizationPrefillBlocoOut[];
  fontes: Record<string, string>;
  avisos: string[];
}
```

Em `DiscoveryAdocaoIn`, `organizacao_nova` e a lista nova:

```ts
  organizacao_nova: {
    name: string;
    kind?: string;
    asn: number;
    legal_name?: string | null;
    document?: string | null;
    irr_as_set?: string | null;
  } | null;
  /** Os blocos do registro que viram autorização da organização nova. */
  autorizacoes: { prefix: string; family: string }[];
```

`web/src/api/hooks.ts` — `document?: string | null;` em `OrganizationCreateIn`, e o hook junto dos de organização:

```ts
/** A consulta ao registro é uma AÇÃO, e não um dado de tela: vai por mutation
 * porque o operador a dispara pelo botão e porque o conflito de cada bloco é
 * recalculado a cada chamada — um cache de query serviria um conflito velho. */
export function usePrefill() {
  return useMutation({
    mutationFn: (asn: number) =>
      apiFetch<OrganizationPrefillOut>(`/api/v1/organizations/prefill?asn=${asn}`),
  });
}
```

`web/src/help.ts` — três chaves novas, ao lado das outras `adocao.*`:

```ts
  "adocao.razao_social": "Razão social do cliente, como no registro (opcional).",
  "adocao.documento": "CNPJ/ownerid do registro (até 32 caracteres); é o que a consulta ao registro preenche quando encontra.",
  "adocao.as_set": "AS-SET do IRR (ex.: AS-64512) — o conjunto de onde as rotas do cliente são validadas.",
```

- [ ] **Step 2: Escrever o teste que falha**

Em `web/src/pages/Discovery.test.tsx`:

1. A constante, junto das outras:

```tsx
const PREFILL = {
  asn: 64512,
  nome: "CLIENTEALFA-AS",
  razao_social: "Cliente Alfa Ltda",
  documento: "13.172.064/0001-11",
  pais: "BR",
  as_set_sugerido: "AS-64512",
  as_sets: ["AS-64512"],
  blocos: [
    { prefix: "203.0.113.0/24", family: "ipv4", fonte: "registro", conflito: null },
    { prefix: "198.51.100.0/24", family: "ipv4", fonte: "registro", conflito: "Cliente Beta" },
  ],
  fontes: { nome: "radb", blocos: "registro" },
  avisos: [],
};
```

2. No `mockFetch`, a rota nova **antes** do `startsWith("/api/v1/organizations")` — que captura tudo que começa com o prefixo:

```tsx
      if (url.startsWith("/api/v1/organizations/prefill")) return json(PREFILL);
```

3. Os dois testes, no `describe("Discovery", ...)`:

```tsx
  it("o botão do registro preenche a organização nova e manda só os blocos livres", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");

    await userEvent.click(within(dialog).getByRole("button", { name: "Buscar no registro" }));

    expect(await within(dialog).findByLabelText(/Nome da organização nova/)).toHaveValue(
      "CLIENTEALFA-AS",
    );
    expect(within(dialog).getByLabelText("Documento (CNPJ/ownerid)")).toHaveValue(
      "13.172.064/0001-11",
    );
    // A lista nasce marcada, e o bloco em uso por outra organização nasce
    // desmarcado e desabilitado (§7): o operador vê antes do clique em vez de
    // receber o 409 depois.
    expect(within(dialog).getByLabelText("Incluir 203.0.113.0/24")).toBeChecked();
    const conflitante = within(dialog).getByLabelText("Incluir 198.51.100.0/24");
    expect(conflitante).not.toBeChecked();
    expect(conflitante).toBeDisabled();
    expect(within(dialog).getByText(/em uso por Cliente Beta/)).toBeInTheDocument();

    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    await waitFor(() =>
      expect(corpoDoPost()).toMatchObject({
        organizacao_nova: {
          name: "CLIENTEALFA-AS",
          kind: "downstream",
          asn: 64512,
          document: "13.172.064/0001-11",
          irr_as_set: "AS-64512",
        },
        autorizacoes: [{ prefix: "203.0.113.0/24", family: "ipv4" }],
      }),
    );
  });

  it("desmarcar um bloco do registro tira ele do payload", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Buscar no registro" }));
    await within(dialog).findByLabelText("Incluir 203.0.113.0/24");

    await userEvent.click(within(dialog).getByLabelText("Incluir 203.0.113.0/24"));

    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    await waitFor(() => expect(corpoDoPost().autorizacoes).toEqual([]));
  });
```

4. O teste que confere o corpo inteiro (linha ~695) ganha os campos novos, senão o `toEqual` quebra:

```tsx
        organizacao_nova: {
          name: "CLIENTE-ALFA",
          kind: "downstream",
          asn: 64512,
          legal_name: null,
          document: null,
          irr_as_set: null,
        },
        autorizacoes: [],
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd web && npm run test -- Discovery`
Expected: FAIL — os dois testes novos não acham o botão "Buscar no registro", e o `toEqual` do corpo antigo quebra.

- [ ] **Step 4: Implementar em `DiscoveryAdopt.tsx`**

1. Imports: `usePrefill` na lista de `@/api/hooks`, e `OrganizationPrefillOut` no `import type`.

2. Tipo local, antes do componente:

```tsx
/** Um bloco do registro na lista da revisão: o `marcado` é a escolha do
 * operador e o `conflito` é o estado do bloco na SoT (§7). */
type BlocoDoRegistro = {
  prefix: string;
  family: string;
  conflito: string | null;
  marcado: boolean;
};
```

3. Estado novo, junto dos outros:

```tsx
  const prefill = usePrefill();
  const [razaoSocial, setRazaoSocial] = useState("");
  const [documento, setDocumento] = useState("");
  const [asSet, setAsSet] = useState("");
  const [blocosDoRegistro, setBlocosDoRegistro] = useState<BlocoDoRegistro[]>([]);
  const [avisosDoRegistro, setAvisosDoRegistro] = useState<string[]>([]);
```

4. O handler, antes de `adotarProposta`:

```tsx
  // O que o registro não devolver fica como está: a leitura parcial não apaga o
  // que o operador já tinha digitado.
  const buscarNoRegistro = () => {
    if (asnRemoto === null) return;
    prefill.mutate(asnRemoto, {
      onSuccess: (dados: OrganizationPrefillOut) => {
        const nome = dados.nome ?? dados.razao_social ?? "";
        if (nome !== "") setOrgNome(nome);
        setRazaoSocial(dados.razao_social ?? "");
        setDocumento(dados.documento ?? "");
        setAsSet(dados.as_set_sugerido ?? "");
        setBlocosDoRegistro(
          dados.blocos.map((b) => ({
            prefix: b.prefix,
            family: b.family,
            conflito: b.conflito,
            // O bloco em uso por outra organização nasce desmarcado (§7).
            marcado: b.conflito === null,
          })),
        );
        setAvisosDoRegistro(dados.avisos);
      },
    });
  };
```

5. `organizacaoNova` no `adotarProposta` passa a levar a identidade inteira, e o corpo ganha a lista:

```tsx
      organizacaoNova = {
        name: orgNome.trim(), kind: "downstream", asn: asnRemoto,
        legal_name: razaoSocial.trim() || null,
        document: documento.trim() || null,
        irr_as_set: asSet.trim() || null,
      };
```

e, ao lado de `organizacao_nova` no objeto do `adotar.mutate`:

```tsx
        // Só os blocos livres e marcados: o conflitante a API recusaria, e o
        // desmarcado o operador não quis.
        autorizacoes: criarOrg
          ? blocosDoRegistro
              .filter((b) => b.marcado && b.conflito === null)
              .map((b) => ({ prefix: b.prefix, family: b.family }))
          : [],
```

6. O `organizacaoNova` declarado no topo do handler precisa do tipo novo:

```tsx
    let organizacaoNova: {
      name: string; kind: string; asn: number;
      legal_name: string | null; document: string | null; irr_as_set: string | null;
    } | null = null;
```

7. A tela, dentro do `{criarOrg && (...)}`, logo depois do campo do nome:

```tsx
        <section>
          <button
            type="button"
            onClick={buscarNoRegistro}
            disabled={prefill.isPending || asnRemoto === null}
          >
            {prefill.isPending ? "Consultando o registro…" : "Buscar no registro"}
          </button>
          {/* O que o registro devolve é sugestão: os campos acima seguem
              editáveis, e nada é gravado antes do Adotar. */}
          {prefill.error && (
            <p role="alert">
              {prefill.error instanceof ApiError
                ? prefill.error.message
                : "Falha ao consultar o registro."}
            </p>
          )}
          {avisosDoRegistro.map((aviso, i) => (
            <p key={`aviso-${i}`} role="status">{aviso}</p>
          ))}
        </section>
        <FormField label="Razão social" help={help("adocao.razao_social")}>
          <input value={razaoSocial} onChange={(e) => setRazaoSocial(e.target.value)} />
        </FormField>
        <FormField label="Documento (CNPJ/ownerid)" help={help("adocao.documento")}>
          <input value={documento} onChange={(e) => setDocumento(e.target.value)} />
        </FormField>
        <FormField label="AS-SET (IRR)" help={help("adocao.as_set")}>
          <input value={asSet} onChange={(e) => setAsSet(e.target.value)} />
        </FormField>
        {blocosDoRegistro.length > 0 && (
          <section>
            <h3>Blocos alocados no registro</h3>
            <ul>
              {blocosDoRegistro.map((b, i) => (
                // A chave é a posição: o prefixo é editável, e uma chave que
                // muda a cada tecla remontaria o input e perderia o foco. A
                // lista não reordena.
                <li key={i}>
                  <input
                    type="checkbox"
                    aria-label={`Incluir ${b.prefix}`}
                    checked={b.marcado}
                    disabled={b.conflito !== null}
                    onChange={() =>
                      setBlocosDoRegistro((atual) =>
                        atual.map((x) => (x === b ? { ...x, marcado: !x.marcado } : x)),
                      )
                    }
                  />
                  <input
                    aria-label={`Prefixo do bloco ${i + 1}`}
                    value={b.prefix}
                    disabled={b.conflito !== null}
                    onChange={(e) =>
                      setBlocosDoRegistro((atual) =>
                        atual.map((x) => (x === b ? { ...x, prefix: e.target.value } : x)),
                      )
                    }
                  />
                  <span> ({b.family})</span>
                  {b.conflito !== null && <span> — em uso por {b.conflito}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}
```

O bloco conflitante fica com a caixa **e** o campo desabilitado: um prefixo editável ali deixaria o `conflito` — que é do prefixo que o registro devolveu — dizendo de um texto que já não é o dele.

- [ ] **Step 5: Levar o caminho inteiro ao fumo de adoção**

O fumo da descoberta (`web/e2e/discovery.spec.ts`) adota a proposta do seed e é onde o caminho novo é exercitado de ponta a ponta contra a stack de verdade. O prefill entra **stubado** por `page.route`: o whois não é determinístico no CI, e o que se quer provar aqui não é a leitura (ela tem os testes de unidade e de API), e sim o caminho do botão até a SoT — os campos preenchidos, a lista de blocos, o payload e as autorizações nascendo com o circuito.

Primeira inserção, logo depois das asserções do trunk e do nome sugeridos (que continuam valendo) e **antes** do `Equipamento de acesso *`:

```ts
  // O prefill stubado: o botão, a lista de blocos e o payload são o que o fumo
  // exercita; a leitura do registro tem os testes dela, e o whois real não é
  // determinístico no CI.
  await page.route("**/api/v1/organizations/prefill*", (rota) =>
    rota.fulfill({
      json: {
        asn: 64512,
        nome: "Provedor E2E Registro",
        razao_social: "Provedor E2E Ltda",
        documento: "12.345.678/0001-99",
        pais: "BR",
        as_set_sugerido: "AS-64512",
        as_sets: ["AS-64512"],
        blocos: [
          { prefix: "203.0.113.0/24", family: "ipv4", fonte: "registro", conflito: null },
          { prefix: "198.51.100.0/24", family: "ipv4", fonte: "registro", conflito: null },
        ],
        fontes: { nome: "radb", blocos: "registro" },
        avisos: [],
      },
    }),
  );
  await dialogo.getByRole("button", { name: "Buscar no registro" }).click();
  await expect(dialogo.getByLabel("Nome da organização nova *")).toHaveValue("Provedor E2E Registro");
  await expect(dialogo.getByLabel("Documento (CNPJ/ownerid)")).toHaveValue("12.345.678/0001-99");
  await expect(dialogo.getByLabel("Incluir 203.0.113.0/24")).toBeChecked();
  await expect(dialogo.getByLabel("Incluir 198.51.100.0/24")).toBeChecked();
```

Segunda inserção, no fim do teste, depois das asserções do circuito na lista:

```ts
  // As autorizações do registro nasceram junto com o circuito (§6.4): os dois
  // blocos que o operador deixou marcados estão na lista de autorizações.
  await page.goto("/prefix-authorizations");
  await expect(page.getByText("203.0.113.0/24")).toBeVisible();
  await expect(page.getByText("198.51.100.0/24")).toBeVisible();
```

Dois cuidados que o teste exige: o `page.route` tem de ser registrado **antes** do clique no botão (senão a consulta sai para a rede), e os prefixos do stub não podem sobrepor autorização ativa de outra organização do seed — `203.0.113.0/24` e `198.51.100.0/24` são faixas de documentação (RFC 5737), e uma sobreposição ali apareceria na hora, com o bloco nascendo desmarcado e a asserção do `toBeChecked` falhando.

- [ ] **Step 6: Rodar e ver passar**

Run: `cd web && npm run test`
Expected: PASS.
Run: `cd web && npm run build`
Expected: `tsc -b` limpo e o bundle gerado.
Run: `cd web && npm run test:e2e -- discovery`
Expected: PASS (exige o banco `gerenet_e2e` migrado e a porta 8000 livre — ver a nota do fim do plano).

- [ ] **Step 7: Commit**

```
git add web/src/api/types.ts web/src/api/hooks.ts web/src/help.ts web/src/pages/DiscoveryAdopt.tsx web/src/pages/Discovery.test.tsx web/e2e/discovery.spec.ts
git commit -F /tmp/organizacao-asn-t7.txt
```

Mensagem:

```
feat(web): o botão "Buscar no registro" na revisão da adoção

Ele preenche nome, razão social, documento e AS-SET, e lista os blocos
alocados com o conflito à vista: o que outra organização já tem nasce
desmarcado e desabilitado, para o operador ver antes do clique em vez de
receber o 409 depois. Os avisos da leitura parcial aparecem no bloco, e o que
o registro não devolve fica como estava.

A consulta vai por mutation, e não por query: o operador a dispara pelo botão,
e o conflito de cada bloco é recalculado a cada chamada.

O fumo da descoberta passa a exercitar o caminho inteiro com o prefill stubado
por `page.route` — o whois real não é determinístico no CI, e o que ele prova
é o botão, a lista marcada e as autorizações nascendo com o circuito.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Task 8: Wiki, runbook e o registro no CLAUDE.md

**Files:**
- Modify: `docs/wiki/descoberta.md`, `docs/runbook-validacao-ne8000.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: tudo o que as tasks anteriores entregaram.
- Produces: nada de código.

- [ ] **Step 1: Wiki**

Em `docs/wiki/descoberta.md`, uma seção nova, depois da que explica a adoção:

```markdown
## Preencher a organização pelo ASN

Na revisão de uma proposta sem organização, o botão **Buscar no registro**
consulta o ASN do peer e preenche o cadastro da organização nova.

O que ele traz:

- **Identidade** — do objeto `aut-num` do RADB vêm o nome e a razão social; da
  consulta ao registro (LACNIC, que delega os ASNs brasileiros ao registro.br)
  vêm o documento (`ownerid`, o CNPJ no Brasil) e o país.
- **Blocos** — os `inetnum` alocados ao AS no registro, que entram como
  autorizações de prefixo da organização nova. Eles nascem **todos marcados**;
  desmarcar é decisão do operador, e o que ficar marcado é gravado junto com a
  adoção, como uma aprovação explícita (§6.4).

O que ele **não** traz, e por quê:

- **O que o AS anuncia de verdade.** O `inetnum` é o bloco *alocado*, e não o
  anunciado: um cliente que anuncia um more-specific dentro do bloco maior está
  coberto pela autorização do bloco maior, e um bloco anunciado que não está
  alocado ao AS não aparece.
- **Blocos de ASN estrangeiro.** Fora do LACNIC a consulta não devolve
  `inetnum`. Nesse caso a organização nasce com a identidade e mais nada, e a
  tela diz que os blocos não vieram.
- **Uma escolha de AS-SET.** Quando o `aut-num` declara mais de um `member-of`,
  o primeiro vira sugestão e os demais ficam no campo para troca.

Um bloco que **outra organização já tem autorizado** aparece marcado com o nome
dela, desmarcado e desabilitado. Resolver esse conflito é com quem cuida das
autorizações: a adoção segue com os demais blocos.

O botão só preenche a tela — **nada é gravado antes do Adotar**, e o que o
registro não devolver fica como estava.
```

- [ ] **Step 2: Runbook**

Em `docs/runbook-validacao-ne8000.md`, na seção da descoberta, acrescentar ao checklist:

```markdown
- [ ] **Consulta ao registro**: na revisão de uma proposta sem organização,
      clicar **Buscar no registro** num ASN real da operação e conferir
      - [ ] o nome e a razão social contra o que a operação sabe do cliente;
      - [ ] o documento contra o CNPJ do cadastro;
      - [ ] os blocos listados contra os prefixos que o cliente anuncia;
      - [ ] que um ASN estrangeiro (ex.: o de um provedor de trânsito) devolve
            identidade sem blocos, com o aviso — e não uma tela vazia;
      - [ ] que um bloco já autorizado para outra organização aparece
            desmarcado, com o nome dela.
      Nada disso vai ao equipamento: a leitura é do registro, e o que for
      gravado só entra no Adotar.
```

- [ ] **Step 3: CLAUDE.md**

Na seção "Estado do repositório", um bullet novo depois do da descoberta:

```markdown
- Organização por ASN (2026-09-15): a revisão da adoção ganha o botão **Buscar
  no registro** (`GET /api/v1/organizations/prefill?asn=N`, no router de
  organizações e declarado ANTES de `/{organization_id}` — o FastAPI casa as
  rotas na ordem de declaração). `identificar_asn` (`automation/irr.py`) faz as
  duas consultas whois do módulo: o `aut-num` do RADB (`as-name`/`descr`/
  `member-of`) e a consulta direta no LACNIC, que delega os ASNs brasileiros ao
  registro.br (`owner`/`ownerid`/`country`/`inetnum`), com cache de 24h em
  `irr_cache` sob `source="registro"`; falha de uma fonte vira aviso, das duas
  sem cache vivo vira `IrrError` (503 na API), e resposta parcial é 200. O
  `conflito` de cada bloco é recalculado **fora** do cache — é estado da SoT.
  `_executa_whois` passou a capturar bytes e decodificar com queda para latin-1
  (a resposta do nic.br derrubava a chamada com `UnicodeDecodeError`, que não é
  `OSError` nem `SubprocessError`: um 500 no lugar da falha tratada). Coluna
  nova `organizations.document` (o `ownerid`, genérica e não `cnpj`) e valor
  novo `auth_origin.registro` — que nasce fora dos dois caminhos da revalidação
  sem código novo, e existe para o bloco alocado não ser marcado `diverge`
  eterno (dois testes pinam isso). `AdocaoIn.autorizacoes` só vale com
  `organizacao_nova`, e cada bloco vira autorização `origin="registro"` com a
  nota do ASN, na transação do `POST /adopt`; `create_authorization` ganhou
  `commit=False` e idempotência por prefixo (§3.2). Migração
  `alembic/versions/c4a8e1f0b7d3_organizacao_document_e_registro.py`. Sem CLI
  nesta frente — decisão do usuário em 2026-09-15: a parte visual de importar e
  migrar um peer fica só na web. Dívidas: more-specifics anunciados fora do
  bloco alocado, blocos de ASN estrangeiro, o botão na página de organizações e
  enriquecer organização já cadastrada.
```

- [ ] **Step 4: Conferir a wiki renderiza**

Run: `uv run pytest -q tests/api/test_wiki_api.py`
Expected: PASS (o frontmatter das páginas é validado pela API da wiki — a seção nova não mexe nele).

- [ ] **Step 5: Commit**

```
git add docs/wiki/descoberta.md docs/runbook-validacao-ne8000.md CLAUDE.md
git commit -F /tmp/organizacao-asn-t8.txt
```

Mensagem:

```
docs(descoberta): o botão do registro na wiki, no runbook e no CLAUDE.md

A wiki diz o que o registro dá e o que ele não dá — `inetnum` é bloco alocado e
não anunciado, ASN estrangeiro não traz blocos, `member-of` múltiplo fica para
o operador escolher. O runbook ganha o passo de conferir a consulta num ASN
real. O CLAUDE.md registra a frente inteira, incluindo o conserto do latin-1 e
por que a origem `registro` existe.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Verificação final

- [ ] `uv run pytest -q` — PASS. Se `tests/worker/` cair, não é regressão: o worker da stack divide o Redis DB 0 com os testes (`GERENET_COLLECT_INTERVAL_MINUTES=60` enfileira coleta na mesma fila). Confirmar com `GERENET_REDIS_URL=redis://localhost:6379/9 uv run pytest -q tests/worker/`.
- [ ] `uv run ruff check src tests` — limpo.
- [ ] `cd web && npm run test && npm run build` — limpos.
- [ ] `cd web && npm run test:e2e` — o fumo da descoberta passa. Exige o banco dedicado `gerenet_e2e` criado e migrado (`GERENET_DATABASE_URL=...gerenet_e2e uv run alembic upgrade head`) e a porta 8000 livre: com `reuseExistingServer: false`, porta ocupada é falha dura no boot, não reuso. Sem esses dois, o passo fica para o usuário — mas então diga isso, e não que passou.
- [ ] `uv run alembic heads` — uma única head, `c4a8e1f0b7d3`.
- [ ] `uv run alembic downgrade -1` seguido de `uv run alembic upgrade head` — ida e volta limpas (o valor do enum fica no tipo, como na F5).
- [ ] Nenhum `text=True` sobrou em `automation/irr.py`.

## O que este plano deixa de fora

Registrado na spec §12 e repetido aqui para o revisor não confundir ausência com esquecimento: more-specifics anunciados fora do bloco alocado; blocos de ASN estrangeiro; o botão na página de organizações; enriquecer organização já cadastrada; e CLI — a parte visual de importar e migrar um peer fica só na web.
