# Ciclo A — Plano 3: API REST e CLI da SoT de downstreams

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor a Source of Truth do ciclo A por **API REST `/api/v1`** e **CLI Typer** — sites, organizations (+ `downstreams`), contacts, circuits (com reserva idempotente e pontas derivadas), sessões BGP (com `has_password` e `password set` via Vault), autorizações de prefixo, catálogo de produtos de roteamento e eventos de auditoria — seguindo o padrão F1 (auth `X-API-Key`, erros 201/404/409/400, PT-BR), sem nova migração e sem tocar no CRUD de devices da F1 (Decisão 11 da spec).

**Architecture:** Camada de transporte pura sobre os serviços do P1/P2 — routers FastAPI por objeto em `api/routers/` (espelho do router de `devices` da F1, que chama `svc.*` com `actor="api"` e mapeia `ConflictError`→409, `NotFoundError`→404, `ValidationError`→400), módulos Typer por objeto em `cli/` (espelho de `cli/devices.py`, com `get_session()`, `actor="cli"`, `GerenetError`→`Erro: …` + `Exit(1)`), e **schemas de saída (`*Out`, `from_attributes=True`)** novos em `domain/schemas.py` — os serviços do ciclo A hoje retornam modelos ORM e nenhum `Out` existe para eles. Desativação na API segue o padrão F1 de PATCH único: os `XUpdate` do ciclo A ganham `admin_status` e o router roteia desativação pura para o `disable_*` do serviço (idempotente, Ruling 5 do P1). Duas extensões pontuais de serviço: `set_password`/guarda de `asn_remote` em `bgp_sessions.py` (rulings diferidos do P2) e escrita genérica no `VaultSecretStore`.

**Tech Stack:** Python 3.12, FastAPI + Pydantic v2, SQLAlchemy 2, Typer, pytest com banco real truncado por teste (`tests/conftest.py`), `uv` para comandos.

**Spec:** [docs/superpowers/specs/2026-09-02-gerenet-ciclo-a-sot-downstreams-design.md](../specs/2026-09-02-gerenet-ciclo-a-sot-downstreams-design.md) — o plano argumenta a partir da spec; o executor lê ambas (spec §7 auditoria, §8 segredos, §9 API/CLI, §10 testes, §11 fronteiras). O ciclo A foi fatiado em 3 planos: Plano 1 (núcleo + IPAM + auditoria — **concluído**), Plano 2 (sessões BGP, prefixos autorizados, produtos, communities — **concluído**), **este** (API REST nova + CLI nova). Modelos, migração com seeds e serviços já existem e estão testados — este plano **não cria migração** e só toca serviços/`models.py`/`vault_store.py` nos pontos declarados nas rulings 6 e 11.

## Global Constraints

- Idioma dos artefatos: **PT-BR**; código (identificadores, nomes de tabelas/colunas, valores de enum) em **inglês** — padrão F1/P1/P2. Mensagens de erro de domínio PT-BR via exceções de `gerenet.domain.services.errors`; mensagens de rota/CLI PT-BR.
- **Nunca** credencial/segredo em banco, YAML, Git, logs, snapshots ou auditoria — só Vault. O valor do password BGP trafega apenas no corpo do request (API) ou no prompt (CLI) e na ida ao Vault; `password_ref` (path) é o único vestígio no banco; `has_password` é derivado; nada disso sai em `*Out`, logs ou auditoria (o `registrar` mascara campos sensíveis por garantia).
- Soft-delete via `admin_status` em todas as entidades; desativar nunca exclui (§14.1). **Catálogos** (`bgp_policy_profiles`, `communities`) continuam fora do TRUNCATE do conftest e **sem rota/CLI de escrita**; communities e associações de community **não são expostos** neste plano (decisão do usuário: fiel à spec §9 — ficam para o ciclo B). `audit_events` segue imutável: nenhuma rota de escrita (UPDATE/DELETE), só leitura.
- **Antes de ler código-fonte, rodar `graphify query "<assunto>"`** — regra do repositório (vale para subagentes).
- Rodar a suíte com o compose dev de pé (`docker compose up -d`): postgres com `gerenet` e `gerenet_test` migrados até `b1a71e5e129b` (head atual do P2), redis e **vault** (o Vault dev do compose é usado pelos testes de segredo — padrão de `tests/test_secrets.py`, sem skip). Suíte completa com `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q` (nunca matar o worker dev do Redis db 0).
- TDD: teste falha → implementação mínima → teste passa → **commit por task** com `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- Comandos: `uv run pytest <arquivo> -v` (um arquivo), `uv run ruff check <arquivos>` (gate: `ruff check` — NÃO usar `ruff format --check` como gate, sem paridade com o baseline; line-length 100). Não há migration nova neste plano: `alembic current` deve permanecer `b1a71e5e129b` nos 2 bancos.
- Auditoria: os serviços já registram `site.create|update|disable|link_device`, `organization.*`, `contact.*`, `circuit.create|update|disable|reserve`, `device.*`, `bgp_session.create|update|disable|add_community|remove_community`, `authorization.create|disable`. Este plano acrescenta o tipo `bgp_session.password_set` (ruling 6). A rota `audit-events` só filtra/lista esses eventos; nunca os cria.
- `tests/conftest.py` TRUNCATE por teste já cobre todas as tabelas dinâmicas (`audit_events, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations RESTART IDENTITY CASCADE`) — **nenhuma alteração de conftest neste plano**. Catálogos não são truncados.
- O banco de teste é escolhido no topo do `conftest.py` (`GERENET_TEST_DATABASE_URL` ou default `.../gerenet_test`, com guarda de nome "test"). A CLI, sob teste, usa o MESMO banco: o `engine` de `gerenet/db.py` é criado no import com a URL do ambiente, que o conftest já apontou para `gerenet_test`.
- Padrão de fixtures de teste de API por arquivo (copiar de `tests/api/test_devices_api.py`):
```python
@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())

def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}
```
- Regras de lint implícitas (sem runner): código no estilo do repo (aspas simples, type hints, imports do `select`, alias `from gerenet.domain.services import bgp_sessions as svc` etc. — o `get_session` do serviço colide com o `get_session` do `db`; nos routers/CLI importar o serviço como `svc`).
- Ledger do SDD (execução): `.superpowers/sdd/2026-09-03-gerenet-ciclo-a-plano-3-api-cli/progress.md`.

## Decisões deste plano (rulings sobre a spec — registrar no ledger do SDD)

1. **Desativação/reativação na API = PATCH único (padrão F1, Decisão 11)**. Os schemas `SiteUpdate`, `OrganizationUpdate`, `ContactUpdate`, `CircuitUpdate`, `BgpSessionUpdate` ganham `admin_status: bool | None = None` (hoje só `DeviceUpdate` tem). Em cada router, o PATCH faz `mudancas = data.model_dump(exclude_unset=True)` e: `admin_status` explícito `None` ⇒ 400 `"admin_status não aceita null."`; `mudancas == {"admin_status": False}` ⇒ chama o `disable_*` do serviço (idempotente: 2ª desativação = no-op **sem evento**, Ruling 5 do P1; 404 se não existe); qualquer outro corpo (incluindo `{"admin_status": True}` puro e combinados com campos) ⇒ `update_*` (evento `.update`, sem efeitos colaterais além dos campos — Decisão 11: quem planejou o P3 não deve "restaurar" reset de `comm_status`; serviços do ciclo A não têm esse efeito). **Não** existem rotas `POST /{id}/disable` nem `enable_*`. O router de `devices` da F1 **não é tocado** (Decisão 11). Os serviços `update_*` já aceitam `admin_status` genericamente (setattr por campo do dump) — só o schema estava sem o campo.
2. **Autorizações de prefixo**: sem update de conteúdo (Ruling 3 do P2 — mudar = desativar + recriar). PATCH aceita **somente** `{"admin_status": false}` via schema dedicado `PrefixAuthorizationDisable` (`admin_status: Literal[False]`, `extra="forbid"` ⇒ qualquer outro corpo dá 422) e chama `disable_authorization`. `GET /{id}` entra por paridade com os demais objetos (o serviço `get_authorization` já existe). O CLI fica verbatim §9 (`add|list`, sem disable — desativação pela API).
3. **Pontas derivadas** (`GET /circuits/{id}` e `POST /circuits/{id}/reserve`): schema `CircuitDetailOut` = campos de `CircuitOut` + `ipv4_local`, `ipv4_remote`, `ipv6_local`, `ipv6_remote` (`str | None`, default `None`). Preenchidas a partir das linhas `ip_prefixes` do circuito com `status="reservada"`, **só para as famílias do `stack`** — o par v4 interno de derivação de circuito `stack=ipv6` (§6 da spec) NÃO é exposto; v4 sem `/máscara`, v6 com `/126` (formato verbatim de `pontas_v4`/`pontas_v6`, fiel ao golden §25.8 que imprime `…:1/126`). Circuito sem reserva ⇒ campos `null`. `GET /circuits` (lista) continua `CircuitOut` simples.
4. **`has_password`**: `BgpSession` ganha `@property has_password -> bool` (`password_ref is not None`) em `domain/models.py` — consumida pelo `BgpSessionOut` (via `from_attributes`) e pelo CLI. `password_ref` **nunca** aparece em schema de saída.
5. **Fidelidade da superfície (§9)**: rotas/CLI **apenas** para o que a spec lista — sem communities, sem associações de community, sem CRUD de catálogo. `policy-profiles` expõe só `GET` list (API) e `policy-profiles list` (CLI), com filtro opcional `direction` (o serviço já filtra). `audit-events` só `GET` list com filtros `tipo`/`objeto`/`objeto_id` + `limit`; nenhuma rota de escrita (teste de imutabilidade via `app.openapi()`). `sites link-device` existe **só no CLI** (a spec §9 não lista rota de link na API; o vínculo por API acontece no `POST /devices` com `site_id`, que já existe na F1).
6. **`password set` (spec §8)**:
   - `VaultSecretStore` ganha escrita/leitura genérica KV v2: `set_secret(path, dados: dict[str, str])` e `get_secret(path) -> dict[str, str]` (o `get_credential` atual vira delegação a `get_secret`; `seed_dev` continua). Caminho da senha BGP: `gerenet/bgp-sessions/<session_id>/password`, shape `{"password": <valor>}`.
   - Novo `bgp_sessions.set_password(session, session_id, *, actor, path) -> models.BgpSession` **no domínio**: valida sessão (404), seta `password_ref = path`, registra evento `bgp_session.password_set` com `antes={"has_password": bool_anterior}` e `depois={"has_password": True}`, commita. Repetir o `set` (trocar a senha) é transição real ⇒ sempre audita. **Não há remoção de password neste ciclo** (a coluna fica; remover = ciclo B).
   - Ordem no chamador (CLI e API): (1) resolve a sessão (404 cedo), (2) grava no Vault (`set_secret`) — falha ⇒ erro claro "Vault indisponível…" (RuntimeError), (3) chama `set_password` do domínio. Se o passo 3 falhar após o 2, fica valor órfão no Vault — inofensivo: o path é por `session_id` e a próxima gravação sobrescreve (idempotente); documentado, não tratado.
   - API: `POST /api/v1/bgp-sessions/{id}/password`, corpo `{"password": str (1–128)}` (schema `BgpSessionPasswordIn`), resposta 200 `BgpSessionOut` (com `has_password: true`). Falha de Vault ⇒ 503 `"Vault indisponível: <msg>."`. CLI: `gerenet bgp-sessions password set <id>` — valor via `typer.Option(..., prompt=True, hide_input=True)` (padrão `vault seed`).
7. **Downstreams**: router próprio em `api/routers/organizations.py` com dois prefixos (padrão F1 de `devices.py`, que exporta `router` + `snap_router`): `router` (`/api/v1/organizations`) e `downstreams_router` (`/api/v1/downstreams`). `GET /downstreams` ⇒ `list_organizations(kind="downstream")`; `POST /downstreams` ⇒ `create_organization` com `kind` **forçado** a `"downstream"` (o corpo usa o schema `OrganizationCreate`, mas o router sobrescreve o `kind` recebido). Não há CLI `downstreams` (§9).
8. **`asn_remote` no update de sessão (ruling diferido da revisão final do P2)** — guarda nova em `update_session`: quando `circuit_id` está na mudança e a organização do **novo** circuito não tem ASN, exigir `asn_remote` explícito na mesma chamada (`ValidationError("Organização {name} não possui ASN; informe asn_remote.")` — mesma mensagem do `create_session`) — sem isso, o `asn_remote` da organização antiga vazaria silenciosamente. Quando a nova organização tem ASN, a regra de igualdade do estado mesclado já vale. O update continua aceitando `asn_remote` junto (schema já tem o campo).
9. **CLI — comandos**: verbatim §9 **+ paridade de contacts aprovada pelo usuário** (`contacts add|list|disable`). `sites add|list|disable|link-device` · `organizations add|list|disable` · `contacts add|list|disable` · `circuits add|list|reserve|disable` · `bgp-sessions add|list|disable|password set` · `prefix-authorizations add|list` · `policy-profiles list`. `audit-events` e communities não têm CLI (§9). Resolução `<id|nome>` onde há nome único (site `name`, organização `name`, circuito `code`, equipamento `name`, perfil `name`); demais (contact, sessão, autorização) por **id numérico**. Todos os comandos: `with get_session() as session`, `actor="cli"`, `except GerenetError` ⇒ `typer.echo(f"Erro: {exc}", err=True)` + `raise typer.Exit(1)`, não encontrado ⇒ mensagem própria `err=True` + `Exit(1)`; sucesso ⇒ `typer.echo` curto; listagens ⇒ linhas formatadas `f"{…:>4}  {…:<…}"` como `cli/devices.py listar`; `--all` liga `include_disabled` nos `list`.
10. **Smoke de CLI automatizado (spec §10)**: novo padrão `tests/cli/test_cli_smoke.py` com `typer.testing.CliRunner` contra o banco de teste real (mesma URL do conftest; a CLI abre sessões próprias via `get_session()`). Cada task de CLI acrescenta o(s) teste(s) do seu grupo; a task roda só `-k` do(s) teste(s) novo(s) (o arquivo referenciará comandos de tasks futuras; a suíte completa roda na última task). Asserts: `result.exit_code == 0`/`== 1`, substrings de saída e, quando útil, linhas no banco via fixture `db_session`. Os comandos que interagem (prompt de senha) são exercitados com `runner.invoke(..., input=...)`.
11. **Estrutura**: um arquivo de router por objeto e um módulo CLI por objeto, registrados nos respectivos `main.py` pelas próprias tasks. Schemas de saída (`*Out`) e as extensões de `XUpdate`/`PrefixAuthorizationDisable` nascem numa Task 1 única (camada de contrato) antes dos routers. Ordem das tasks: contrato → sites → organizations/downstreams/contacts → circuits → serviço de senha (domínio+Vault) → bgp-sessions → autorizações/catálogo → audit-events → smoke final.

## Estrutura de arquivos

**Cria** (routers e CLIs novos, um por objeto):
- `src/gerenet/api/routers/sites.py` — `router` `/api/v1/sites` (list/create/get/patch)
- `src/gerenet/api/routers/organizations.py` — `router` `/api/v1/organizations` + `downstreams_router` `/api/v1/downstreams`
- `src/gerenet/api/routers/contacts.py` — `router` `/api/v1/contacts`
- `src/gerenet/api/routers/circuits.py` — `router` `/api/v1/circuits` (+ `POST /{id}/reserve`, `CircuitDetailOut`)
- `src/gerenet/api/routers/bgp_sessions.py` — `router` `/api/v1/bgp-sessions` (+ `POST /{id}/password`)
- `src/gerenet/api/routers/prefix_authorizations.py` — `router` `/api/v1/prefix-authorizations`
- `src/gerenet/api/routers/policy_profiles.py` — `router` `/api/v1/policy-profiles` (GET list)
- `src/gerenet/api/routers/audit_events.py` — `router` `/api/v1/audit-events` (GET list)
- `src/gerenet/cli/sites.py`, `organizations.py`, `contacts.py`, `circuits.py`, `bgp_sessions.py`, `prefix_authorizations.py`, `policy_profiles.py`
- `tests/api/test_sites_api.py`, `test_organizations_api.py` (cobre downstreams), `test_contacts_api.py`, `test_circuits_api.py`, `test_bgp_sessions_api.py`, `test_prefix_authorizations_api.py`, `test_policy_profiles_api.py`, `test_audit_events_api.py`
- `tests/cli/test_cli_smoke.py` — cresce a cada task de CLI
- `tests/domain/test_schemas_out.py` (Task 1)

**Modifica** (pontos declarados nas rulings):
- `src/gerenet/domain/schemas.py` — `*Out` (site/org/contact/circuit/CircuitDetailOut/session/autorização/perfil/audit), `admin_status` nos 5 `XUpdate`, `PrefixAuthorizationDisable`, `BgpSessionPasswordIn`
- `src/gerenet/domain/models.py` — propriedade `BgpSession.has_password` (ruling 4)
- `src/gerenet/domain/services/bgp_sessions.py` — `set_password` (ruling 6) e guarda de `asn_remote` no `update_session` (ruling 8)
- `src/gerenet/secrets/vault_store.py` — `set_secret`/`get_secret` (ruling 6)
- `src/gerenet/api/main.py` — `include_router` de cada router novo (na task que o cria)
- `src/gerenet/cli/main.py` — `add_typer` de cada grupo novo (na task que o cria)
- `tests/domain/test_bgp_sessions_service.py` (guarda ruling 8 + `set_password`), `tests/domain/test_models.py` (property `has_password`), `tests/test_secrets.py` (`set_secret`/`get_secret` roundtrip)

**Não toca**: `tests/conftest.py`, migrations (head `b1a71e5e129b`), `api/routers/devices.py`, `cli/devices.py`/`collect.py`/`snapshot.py`/`hostkey.py`/`vault.py`, catálogos `communities`/`bgp_policy_profiles` (seed) e os demais serviços do P1/P2.

---

### Task 1: Contrato de saída — `*Out`, `admin_status` nos updates, `has_password`

**Files:**
- Modify: `src/gerenet/domain/schemas.py` — adicionar `admin_status: bool | None = None` como **último campo** de `SiteUpdate`, `OrganizationUpdate`, `ContactUpdate`, `CircuitUpdate`, `BgpSessionUpdate` (texto exato abaixo); anexar no fim do arquivo `SiteOut`, `OrganizationOut`, `ContactOut`, `CircuitOut`, `CircuitDetailOut`, `BgpSessionOut`, `PrefixAuthorizationOut`, `PolicyProfileOut`, `AuditEventOut`, `PrefixAuthorizationDisable`, `BgpSessionPasswordIn` (código abaixo).
- Modify: `src/gerenet/domain/models.py` — propriedade `has_password` em `BgpSession` (código abaixo).
- Create: `tests/domain/test_schemas_out.py` (código abaixo).

**Interfaces:**
- Consumes: modelos ORM de `gerenet.domain.models` (colunas em `models.py:135-419`); padrão `DeviceOut` (`model_config = ConfigDict(from_attributes=True)`).
- Produces (usado por T2–T8): `SiteOut`, `OrganizationOut`, `ContactOut`, `CircuitOut`, `CircuitDetailOut`, `BgpSessionOut`, `PrefixAuthorizationOut`, `PolicyProfileOut`, `AuditEventOut` (todas `from_attributes=True`, sem `created_at`/`updated_at` — espelho do `DeviceOut`); `PrefixAuthorizationDisable`; `BgpSessionPasswordIn`; updates do ciclo A com `admin_status: bool | None = None`; `BgpSession.has_password -> bool`.

- [ ] **Step 1: Write the failing test**

`tests/domain/test_schemas_out.py`:

```python
import pytest
from pydantic import ValidationError

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionOut,
    BgpSessionPasswordIn,
    CircuitDetailOut,
    CircuitOut,
    ContactUpdate,
    OrganizationOut,
    PrefixAuthorizationDisable,
    SiteOut,
)


def _site() -> models.Site:
    site = models.Site(name="POP-SP", city="São Paulo", uf="SP", admin_status=True)
    site.id = 1
    return site


def _sessao() -> models.BgpSession:
    sessao = models.BgpSession(
        circuit_id=1, device_id=1, afi="ipv4",
        local_address="100.64.0.1", remote_address="100.64.0.2",
        asn_local=64600, asn_remote=64512, bfd_enabled=False,
        graceful_restart=False, shutdown=False, allow_default_route=False,
    )
    sessao.id = 1
    return sessao


def test_site_out_serializa_a_partir_do_modelo() -> None:
    dump = SiteOut.model_validate(_site()).model_dump()
    assert dump == {
        "id": 1, "name": "POP-SP", "city": "São Paulo", "uf": "SP",
        "p2p_ipv4_block": None, "p2p_ipv6_base": None, "admin_status": True,
    }


def test_organization_out_campos_minimos() -> None:
    org = models.Organization(name="Cliente X", asn=64500, kind="downstream")
    org.id = 2
    dump = OrganizationOut.model_validate(org).model_dump()
    assert dump["name"] == "Cliente X"
    assert dump["asn"] == 64500
    assert dump["kind"] == "downstream"
    assert "created_at" not in dump


def test_circuit_detail_out_pontas_default_none() -> None:
    circ = models.Circuit(
        code="CIRC-1", organization_id=1, site_id=1, access_device_id=1,
        access_port="GE0/0/1", edge_device_id=2,
    )
    circ.id = 3
    dump = CircuitDetailOut.model_validate(circ).model_dump()
    for campo in ("ipv4_local", "ipv4_remote", "ipv6_local", "ipv6_remote"):
        assert dump[campo] is None
    # a lista (CircuitOut) não tem as pontas
    assert "ipv4_local" not in CircuitOut.model_validate(circ).model_dump()


def test_has_password_em_bgp_session_out() -> None:
    assert BgpSessionOut.model_validate(_sessao()).model_dump()["has_password"] is False
    sessao = _sessao()
    sessao.password_ref = "gerenet/bgp-sessions/1/password"
    assert BgpSessionOut.model_validate(sessao).model_dump()["has_password"] is True
    # password_ref nunca sai no schema de saída
    assert "password_ref" not in BgpSessionOut.model_validate(sessao).model_dump()


def test_updates_tem_admin_status_opcional() -> None:
    assert ContactUpdate().admin_status is None
    assert ContactUpdate(admin_status=False).admin_status is False


def test_prefix_authorization_disable_somente_false() -> None:
    assert PrefixAuthorizationDisable(admin_status=False).admin_status is False
    with pytest.raises(ValidationError):
        PrefixAuthorizationDisable(admin_status=True)
    with pytest.raises(ValidationError):
        PrefixAuthorizationDisable(admin_status=None)
    with pytest.raises(ValidationError):
        PrefixAuthorizationDisable(admin_status=False, notas="extra")  # extra="forbid"


def test_bgp_session_password_in_limites() -> None:
    assert BgpSessionPasswordIn(password="s").password == "s"
    with pytest.raises(ValidationError):
        BgpSessionPasswordIn(password="")
    with pytest.raises(ValidationError):
        BgpSessionPasswordIn(password="x" * 129)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_schemas_out.py -v`
Expected: FAIL — `ImportError`/`AttributeError` (classes e property inexistentes).

- [ ] **Step 3: Write minimal implementation**

Em `src/gerenet/domain/models.py`, na classe `BgpSession` (logo após o campo `password_ref`, `models.py:371`):

```python
    @property
    def has_password(self) -> bool:
        """Senha definida? (valor só no Vault — password_ref guarda o path)."""
        return self.password_ref is not None
```

Nos updates do ciclo A — `SiteUpdate`, `OrganizationUpdate`, `ContactUpdate`, `CircuitUpdate`, `BgpSessionUpdate` — adicionar como último campo da classe:

```python
    admin_status: bool | None = None
```

Em `src/gerenet/domain/schemas.py`, anexar no fim do arquivo:

```python
class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str | None
    uf: str | None
    p2p_ipv4_block: str | None
    p2p_ipv6_base: str | None
    admin_status: bool


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    legal_name: str | None
    kind: str
    asn: int | None
    irr_as_set: str | None
    notes: str | None
    admin_status: bool


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    email: str | None
    phone: str | None
    kind: str
    admin_status: bool


class CircuitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    organization_id: int
    site_id: int
    access_device_id: int
    access_port: str
    edge_device_id: int
    backup_edge_device_id: int | None
    stack: str
    vlan_mode: str
    qinq: bool
    vrf: str | None
    mtu: int | None
    bandwidth: str | None
    bfd: bool
    p2p_v4_len: int
    description: str | None
    notes: str | None
    admin_status: bool


class CircuitDetailOut(CircuitOut):
    """Circuito reservado: pontas derivadas dos enlaces p2p (ruling 4).

    v4 sem máscara (pontas_v4); v6 com '/126' (pontas_v6). Linhas internas
    de derivação (stack=ipv6) não são expostas.
    """

    ipv4_local: str | None = None
    ipv4_remote: str | None = None
    ipv6_local: str | None = None
    ipv6_remote: str | None = None


class BgpSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    circuit_id: int
    device_id: int
    afi: str
    local_address: str
    remote_address: str
    source_address: str | None
    asn_local: int | None
    asn_remote: int | None
    description: str | None
    import_profile_id: int | None
    export_profile_id: int | None
    maximum_prefix: int | None
    maximum_prefix_threshold: int | None
    local_preference: int | None
    med: int | None
    prepend: int | None
    keepalive: int | None
    holdtime: int | None
    bfd_enabled: bool
    graceful_restart: bool
    shutdown: bool
    allow_default_route: bool
    has_password: bool  # property do modelo — o valor nunca trafega aqui
    admin_status: bool


class PrefixAuthorizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    family: str
    prefix: str
    origin: str
    notes: str | None
    admin_status: bool


class PolicyProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    label: str
    direction: str
    kind: str
    prefixes: list | None
    notes: str | None
    admin_status: bool


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    actor: str
    details: dict
    created_at: datetime


class PrefixAuthorizationDisable(BaseModel):
    """PATCH de autorização aceita só {"admin_status": false} (ruling 2)."""

    model_config = ConfigDict(extra="forbid")

    admin_status: Literal[False]


class BgpSessionPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_schemas_out.py -v`
Expected: PASS (7 testes).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/models.py tests/domain/test_schemas_out.py
git commit -m "feat(SoT): schemas de saída do ciclo A + has_password e admin_status nos updates"
```

---

### Task 2: Sites — router, CLI e testes

**Files:**
- Create: `src/gerenet/api/routers/sites.py`, `src/gerenet/cli/sites.py`, `tests/api/test_sites_api.py`
- Modify: `src/gerenet/api/main.py` (import + include), `src/gerenet/cli/main.py` (import + add_typer)
- Test: `tests/cli/test_cli_smoke.py` (criar o arquivo com as fixtures e os testes de sites)

**Interfaces:**
- Consumes: `svc.create_site/get_site/list_sites(include_disabled)/update_site/disable_site` e `link_device(session, site_id, device_id, *, actor)` (`domain/services/sites.py`); schemas `SiteCreate/SiteUpdate/SiteOut` (T1); `resolver` de `gerenet.cli.devices`; `get_session` de `gerenet.db`.
- Produces: rotas `/api/v1/sites` GET(list)/POST(201)/GET{id}/PATCH; CLI `sites add|list|disable|link-device`; grupos registrados nos `main.py` da API e da CLI.

- [ ] **Step 1: Write the failing API test**

`tests/api/test_sites_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _cria_site(client: TestClient, nome: str, **extra: object) -> int:
    corpo: dict[str, object] = {"name": nome, "city": "São Paulo", "uf": "SP", **extra}
    resp = client.post("/api/v1/sites", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_rota_requer_chave(client: TestClient) -> None:
    assert client.get("/api/v1/sites").status_code == 401


def test_criar_listar_detalhar(client: TestClient) -> None:
    sid = _cria_site(client, "POP-API-1")
    corpo = client.get(f"/api/v1/sites/{sid}", headers=_auth()).json()
    assert corpo["name"] == "POP-API-1"
    assert corpo["uf"] == "SP"
    assert corpo["admin_status"] is True

    lista = client.get("/api/v1/sites", headers=_auth()).json()
    assert [s["name"] for s in lista] == ["POP-API-1"]

    dup = client.post("/api/v1/sites", json={"name": "POP-API-1"}, headers=_auth())
    assert dup.status_code == 409
    assert "Já existe" in dup.json()["detail"]

    assert client.get("/api/v1/sites/9999", headers=_auth()).status_code == 404


def test_bloco_p2p_invalido_da_400(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/sites",
        json={"name": "POP-BAD", "p2p_ipv4_block": "999.1.1.0/24"},
        headers=_auth(),
    )
    assert resp.status_code == 400


def test_patch_desativa_reativa_e_null(client: TestClient) -> None:
    sid = _cria_site(client, "POP-PATCH")
    off = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    again = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": False}, headers=_auth())
    assert again.status_code == 200

    on = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": True}, headers=_auth())
    assert on.status_code == 200
    assert on.json()["admin_status"] is True

    nul = client.patch(f"/api/v1/sites/{sid}", json={"admin_status": None}, headers=_auth())
    assert nul.status_code == 400
    assert "null" in nul.json()["detail"]


def test_patch_audita_eventos(db_session: Session, client: TestClient) -> None:
    sid = _cria_site(client, "POP-AUDIT")
    client.patch(f"/api/v1/sites/{sid}", json={"admin_status": False}, headers=_auth())
    client.patch(f"/api/v1/sites/{sid}", json={"city": "Campinas"}, headers=_auth())

    eventos = list(db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id)))
    assert [e.type for e in eventos] == ["site.create", "site.disable", "site.update"]
    assert all(e.actor == "api" for e in eventos)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_sites_api.py -v`
Expected: FAIL — rotas inexistentes (404).

- [ ] **Step 3: Write minimal implementation (router + wiring)**

`src/gerenet/api/routers/sites.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import SiteCreate, SiteOut, SiteUpdate
from gerenet.domain.services import sites as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/sites", tags=["sites"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[SiteOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_sites(session, include_disabled=include_disabled)


@router.post("", response_model=SiteOut, status_code=201)
def criar(data: SiteCreate, session: SessionDep) -> object:
    try:
        return svc.create_site(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{site_id}", response_model=SiteOut)
def detalhar(site_id: int, session: SessionDep) -> object:
    try:
        return svc.get_site(session, site_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{site_id}", response_model=SiteOut)
def atualizar(site_id: int, data: SiteUpdate, session: SessionDep) -> object:
    """PATCH único (ruling 1): desativação pura vira site.disable; o resto vira update."""
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_site(session, site_id, actor="api")
        return svc.update_site(session, site_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Em `src/gerenet/api/main.py`:

```python
from gerenet.api.routers import devices, sites
...
    app.include_router(devices.router)
    app.include_router(devices.snap_router)
    app.include_router(sites.router)
```

- [ ] **Step 4: Run API test to verify it passes**

Run: `uv run pytest tests/api/test_sites_api.py -v`
Expected: PASS (5 testes).

- [ ] **Step 5: Write the failing CLI smoke test**

`tests/cli/test_cli_smoke.py` (arquivo novo — cresce nas tasks seguintes; cada task roda o arquivo inteiro):

```python
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models

runner = CliRunner()


def test_cli_sites_add_list_disable() -> None:
    r = runner.invoke(app, ["sites", "add", "--name", "POP-CLI", "--city", "Campinas", "--uf", "SP"])
    assert r.exit_code == 0, r.output
    assert "POP-CLI" in r.output

    assert "POP-CLI" in runner.invoke(app, ["sites", "list"]).output

    off = runner.invoke(app, ["sites", "disable", "POP-CLI"])
    assert off.exit_code == 0
    assert "desativado" in off.output

    oculto = runner.invoke(app, ["sites", "list"])
    assert "POP-CLI" not in oculto.output
    com_tudo = runner.invoke(app, ["sites", "list", "--all"])
    assert "POP-CLI" in com_tudo.output


def test_cli_sites_erros() -> None:
    assert runner.invoke(app, ["sites", "add", "--name", "POP-CLI-ERR"]).exit_code == 0
    segundo = runner.invoke(app, ["sites", "add", "--name", "POP-CLI-ERR"])
    assert segundo.exit_code == 1
    assert "Erro:" in segundo.output

    faltante = runner.invoke(app, ["sites", "disable", "nao-existe"])
    assert faltante.exit_code == 1
    assert "não encontrado" in faltante.output


def test_cli_sites_link_device(db_session: Session) -> None:
    site = runner.invoke(app, ["sites", "add", "--name", "POP-LINK"])
    assert site.exit_code == 0, site.output
    dev = runner.invoke(app, ["devices", "add", "--name", "ne-cli", "--address", "10.20.0.1"])
    assert dev.exit_code == 0, dev.output
    vinculo = runner.invoke(app, ["sites", "link-device", "POP-LINK", "ne-cli"])
    assert vinculo.exit_code == 0, vinculo.output

    dev_db = db_session.scalar(select(models.Device).where(models.Device.name == "ne-cli"))
    site_db = db_session.scalar(select(models.Site).where(models.Site.name == "POP-LINK"))
    assert dev_db is not None and dev_db.site_id == site_db.id
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: FAIL — comando `sites` inexistente.

- [ ] **Step 7: Write minimal implementation (CLI + wiring)**

`src/gerenet/cli/sites.py`:

```python
import typer

from gerenet.cli.devices import resolver as resolver_device
from gerenet.db import get_session
from gerenet.domain.schemas import SiteCreate
from gerenet.domain.services import sites as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Sites/POPs.")


def resolver(session, site: str):
    """Devolve o site (ativo ou não) por ID ou nome; None se não existir."""
    if site.isdigit():
        try:
            return svc.get_site(session, int(site))
        except NotFoundError:
            return None
    return next(
        (s for s in svc.list_sites(session, include_disabled=True) if s.name == site), None
    )


@app.command("add")
def add(
    name: str = typer.Option(..., help="Nome único do site/POP."),
    city: str | None = typer.Option(None, help="Cidade."),
    uf: str | None = typer.Option(None, help="UF (2 letras)."),
    p2p_ipv4_block: str | None = typer.Option(
        None, "--p2p-ipv4-block", help="Bloco p2p v4 do site (CIDR)."
    ),
    p2p_ipv6_base: str | None = typer.Option(
        None, "--p2p-ipv6-base", help="Base p2p v6 do site (CIDR)."
    ),
) -> None:
    """Cadastra um site/POP."""
    with get_session() as session:
        try:
            site = svc.create_site(
                session,
                SiteCreate(
                    name=name,
                    city=city,
                    uf=uf,
                    p2p_ipv4_block=p2p_ipv4_block,
                    p2p_ipv6_base=p2p_ipv6_base,
                ),
                actor="cli",
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Site {site.id} criado: {site.name}")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista sites/POPs."""
    with get_session() as session:
        for site in svc.list_sites(session, include_disabled=include_disabled):
            typer.echo(f"{site.id:>4}  {site.name:<24} {site.city or '-':<20} {site.uf or '-'}")


@app.command("disable")
def disable(site: str = typer.Argument(..., help="ID ou nome do site.")) -> None:
    """Desativa um site (mantém histórico e registro)."""
    with get_session() as session:
        encontrado = resolver(session, site)
        if encontrado is None:
            typer.echo("Site não encontrado.", err=True)
            raise typer.Exit(1)
        svc.disable_site(session, encontrado.id, actor="cli")
    typer.echo(f"Site {encontrado.name} desativado.")


@app.command("link-device")
def link_device(
    site: str = typer.Argument(..., help="ID ou nome do site."),
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
) -> None:
    """Vincula um equipamento ao site."""
    with get_session() as session:
        encontrado = resolver(session, site)
        if encontrado is None:
            typer.echo("Site não encontrado.", err=True)
            raise typer.Exit(1)
        dev = resolver_device(session, device)
        if dev is None:
            typer.echo("Equipamento não encontrado.", err=True)
            raise typer.Exit(1)
        svc.link_device(session, encontrado.id, dev.id, actor="cli")
    typer.echo(f"Equipamento {dev.name} vinculado ao site {encontrado.name}.")
```

Em `src/gerenet/cli/main.py`:

```python
from gerenet.cli import collect, devices, hostkey, sites, snapshot, vault
...
app.add_typer(devices.app, name="devices", help="Cadastro e consulta de equipamentos.")
app.add_typer(sites.app, name="sites", help="Sites/POPs.")
```

- [ ] **Step 8: Run CLI test to verify it passes**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: PASS (3 testes).

- [ ] **Step 9: Gate + commit**

```bash
uv run ruff check src/gerenet/api/routers/sites.py src/gerenet/cli/sites.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_sites_api.py tests/cli/test_cli_smoke.py
uv run pytest tests/api/test_sites_api.py tests/cli/test_cli_smoke.py -v
git add src/gerenet/api/routers/sites.py src/gerenet/cli/sites.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_sites_api.py tests/cli/test_cli_smoke.py
git commit -m "feat(SoT): API e CLI de sites (list/create/get/patch/disable) + link-device"
```

---

### Task 3: Organizations + downstreams e Contacts — routers, CLIs e testes

**Files:**
- Create: `src/gerenet/api/routers/organizations.py` (router + `downstreams_router` — padrão de `devices.py` com 2 prefixos), `src/gerenet/api/routers/contacts.py`, `src/gerenet/cli/organizations.py`, `src/gerenet/cli/contacts.py`, `tests/api/test_organizations_api.py`, `tests/api/test_contacts_api.py`
- Modify: `src/gerenet/api/main.py`, `src/gerenet/cli/main.py`
- Test: `tests/cli/test_cli_smoke.py` (anexar testes de organizations/contacts)

**Interfaces:**
- Consumes: `create_organization/get_organization/list_organizations(include_disabled, kind)/update_organization/disable_organization` (`domain/services/organizations.py`); `create_contact/get_contact/list_contacts(organization_id=None)/update_contact/disable_contact` (`domain/services/contacts.py`); schemas `OrganizationCreate/Update/Out`, `ContactCreate/Update/Out` (T1). `list_contacts` **não tem** `include_disabled` — CLI `contacts list` sem `--all` (sem mudança de serviço).
- Produces: rotas `/api/v1/organizations` (list/create/get/patch) e `/api/v1/downstreams` (GET list + POST que **força** `kind="downstream"`); rotas `/api/v1/contacts` (list com `organization_id`, create, get, patch); CLI `organizations add|list|disable` e `contacts add|list|disable`.

- [ ] **Step 1: Write the failing API tests**

`tests/api/test_organizations_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_criar_listar_detalhar(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/organizations",
        json={"name": "Cliente Org API", "asn": 64511, "kind": "downstream"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]
    assert resp.json()["kind"] == "downstream"

    lista = client.get("/api/v1/organizations", headers=_auth()).json()
    assert [o["name"] for o in lista] == ["Cliente Org API"]

    corpo = client.get(f"/api/v1/organizations/{org_id}", headers=_auth()).json()
    assert corpo["asn"] == 64511

    dup = client.post(
        "/api/v1/organizations", json={"name": "Cliente Org API"}, headers=_auth()
    )
    assert dup.status_code == 409

    assert client.get("/api/v1/organizations/9999", headers=_auth()).status_code == 404


def test_rota_requer_chave(client: TestClient) -> None:
    assert client.get("/api/v1/organizations").status_code == 401


def test_asn_reservado_da_400_e_duplicado_da_409(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/organizations", json={"name": "Org Res", "asn": 23456}, headers=_auth()
    )
    assert resp.status_code == 400
    assert "reservado" in resp.json()["detail"]

    client.post("/api/v1/organizations", json={"name": "Org A", "asn": 64520}, headers=_auth())
    dup = client.post(
        "/api/v1/organizations", json={"name": "Org B", "asn": 64520}, headers=_auth()
    )
    assert dup.status_code == 409
    assert "ASN" in dup.json()["detail"]


def test_patch_desativa_e_audita(db_session: Session, client: TestClient) -> None:
    criada = client.post(
        "/api/v1/organizations", json={"name": "Org Patch", "asn": 64521}, headers=_auth()
    )
    assert criada.status_code == 201
    org_id = criada.json()["id"]

    off = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    repetido = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": False}, headers=_auth())
    assert repetido.status_code == 200

    renomeada = client.patch(
        f"/api/v1/organizations/{org_id}", json={"name": "Org Patch 2"}, headers=_auth()
    )
    assert renomeada.status_code == 200

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["organization.create", "organization.disable", "organization.update"]


def test_patch_admin_status_null_da_400(client: TestClient) -> None:
    criada = client.post(
        "/api/v1/organizations", json={"name": "Org Null"}, headers=_auth()
    )
    org_id = criada.json()["id"]
    resp = client.patch(f"/api/v1/organizations/{org_id}", json={"admin_status": None}, headers=_auth())
    assert resp.status_code == 400


def test_downstreams_forca_kind(client: TestClient) -> None:
    criada = client.post(
        "/api/v1/downstreams",
        json={"name": "Down API", "kind": "parceiro", "asn": 64530},
        headers=_auth(),
    )
    assert criada.status_code == 201, criada.text
    assert criada.json()["kind"] == "downstream"  # ignorado o parceiro enviado

    lista = client.get("/api/v1/downstreams", headers=_auth()).json()
    assert [o["name"] for o in lista] == ["Down API"]

    # organizações comuns não aparecem no downstreams
    client.post("/api/v1/organizations", json={"name": "Parceiro X", "kind": "parceiro"}, headers=_auth())
    assert [o["name"] for o in client.get("/api/v1/downstreams", headers=_auth()).json()] == ["Down API"]
```

`tests/api/test_contacts_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _org(client: TestClient, nome: str = "Org Contatos") -> int:
    resp = client.post("/api/v1/organizations", json={"name": nome}, headers=_auth())
    assert resp.status_code == 201
    return resp.json()["id"]


def test_crud_contatos(client: TestClient) -> None:
    org_id = _org(client)
    criado = client.post(
        "/api/v1/contacts",
        json={"organization_id": org_id, "name": "Ana NOC", "email": "ana@example.com", "kind": "noc"},
        headers=_auth(),
    )
    assert criado.status_code == 201, criado.text
    contato_id = criado.json()["id"]

    lista = client.get("/api/v1/contacts", headers=_auth()).json()
    assert [c["name"] for c in lista] == ["Ana NOC"]
    filtrada = client.get(f"/api/v1/contacts?organization_id={org_id}", headers=_auth()).json()
    assert [c["name"] for c in filtrada] == ["Ana NOC"]

    corpo = client.get(f"/api/v1/contacts/{contato_id}", headers=_auth()).json()
    assert corpo["email"] == "ana@example.com"

    inexistente = client.get("/api/v1/contacts/9999", headers=_auth())
    assert inexistente.status_code == 404


def test_contato_email_invalido_da_400_e_org_inexistente_404(client: TestClient) -> None:
    ruim = client.post(
        "/api/v1/contacts",
        json={"organization_id": 1, "name": "Ana", "email": "nao-eh-email"},
        headers=_auth(),
    )
    assert ruim.status_code == 400
    assert "E-mail" in ruim.json()["detail"]

    sem_org = client.post(
        "/api/v1/contacts", json={"organization_id": 9999, "name": "Ana"}, headers=_auth()
    )
    assert sem_org.status_code == 404


def test_patch_contato_desativa_e_audita(db_session: Session, client: TestClient) -> None:
    org_id = _org(client)
    criado = client.post(
        "/api/v1/contacts", json={"organization_id": org_id, "name": "Bruno"}, headers=_auth()
    )
    contato_id = criado.json()["id"]

    off = client.patch(f"/api/v1/contacts/{contato_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    renomeado = client.patch(
        f"/api/v1/contacts/{contato_id}", json={"phone": "11-99999"}, headers=_auth()
    )
    assert renomeado.status_code == 200

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["organization.create", "contact.create", "contact.disable", "contact.update"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_organizations_api.py tests/api/test_contacts_api.py -v`
Expected: FAIL — rotas inexistentes.

- [ ] **Step 3: Write minimal implementation (routers + wiring)**

`src/gerenet/api/routers/organizations.py`:

```python
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import OrganizationCreate, OrganizationOut, OrganizationUpdate
from gerenet.domain.services import organizations as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/organizations", tags=["organizations"],
    dependencies=[Depends(require_api_key)],
)

downstreams_router = APIRouter(
    prefix="/api/v1/downstreams", tags=["downstreams"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


def _atualizar(organization_id: int, data: OrganizationUpdate, session: Session) -> object:
    """PATCH único (ruling 1) compartilhado das duas listas de orgs."""
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_organization(session, organization_id, actor="api")
        return svc.update_organization(session, organization_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[OrganizationOut])
def listar(
    session: SessionDep,
    include_disabled: bool = False,
    kind: Literal["downstream", "parceiro"] | None = None,
) -> list:
    return svc.list_organizations(session, include_disabled=include_disabled, kind=kind)


@router.post("", response_model=OrganizationOut, status_code=201)
def criar(data: OrganizationCreate, session: SessionDep) -> object:
    try:
        return svc.create_organization(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{organization_id}", response_model=OrganizationOut)
def detalhar(organization_id: int, session: SessionDep) -> object:
    try:
        return svc.get_organization(session, organization_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{organization_id}", response_model=OrganizationOut)
def atualizar(organization_id: int, data: OrganizationUpdate, session: SessionDep) -> object:
    return _atualizar(organization_id, data, session)


@downstreams_router.get("", response_model=list[OrganizationOut])
def listar_downstreams(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_organizations(session, include_disabled=include_disabled, kind="downstream")


@downstreams_router.post("", response_model=OrganizationOut, status_code=201)
def criar_downstream(data: OrganizationCreate, session: SessionDep) -> object:
    """POST de downstream: kind é sempre 'downstream' (ruling 7)."""
    dados = data.model_copy(update={"kind": "downstream"})
    try:
        return svc.create_organization(session, dados, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

`src/gerenet/api/routers/contacts.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import ContactCreate, ContactOut, ContactUpdate
from gerenet.domain.services import contacts as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[ContactOut])
def listar(session: SessionDep, organization_id: int | None = None) -> list:
    return svc.list_contacts(session, organization_id=organization_id)


@router.post("", response_model=ContactOut, status_code=201)
def criar(data: ContactCreate, session: SessionDep) -> object:
    try:
        return svc.create_contact(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{contact_id}", response_model=ContactOut)
def detalhar(contact_id: int, session: SessionDep) -> object:
    try:
        return svc.get_contact(session, contact_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{contact_id}", response_model=ContactOut)
def atualizar(contact_id: int, data: ContactUpdate, session: SessionDep) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_contact(session, contact_id, actor="api")
        return svc.update_contact(session, contact_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Em `src/gerenet/api/main.py`:

```python
from gerenet.api.routers import contacts, devices, organizations, sites
...
    app.include_router(sites.router)
    app.include_router(organizations.router)
    app.include_router(organizations.downstreams_router)
    app.include_router(contacts.router)
```

- [ ] **Step 4: Run API test to verify it passes**

Run: `uv run pytest tests/api/test_organizations_api.py tests/api/test_contacts_api.py -v`
Expected: PASS (6 + 3 testes).

- [ ] **Step 5: Write the failing CLI smoke tests (anexar a `tests/cli/test_cli_smoke.py`)**

```python
def test_cli_organizations_add_list_disable() -> None:
    r = runner.invoke(
        app, ["organizations", "add", "--name", "Cliente CLI", "--asn", "64577"]
    )
    assert r.exit_code == 0, r.output
    assert "Cliente CLI" in r.output

    lista = runner.invoke(app, ["organizations", "list"])
    assert lista.exit_code == 0
    assert "Cliente CLI" in lista.output

    off = runner.invoke(app, ["organizations", "disable", "Cliente CLI"])
    assert off.exit_code == 0
    assert "desativado" in off.output

    oculto = runner.invoke(app, ["organizations", "list"])
    assert "Cliente CLI" not in oculto.output
    assert "Cliente CLI" in runner.invoke(app, ["organizations", "list", "--all"]).output


def test_cli_contacts_add_list_disable(db_session: Session) -> None:
    org = runner.invoke(
        app, ["organizations", "add", "--name", "Org CLI Contatos"]
    )
    assert org.exit_code == 0, org.output
    org_id = db_session.scalar(
        select(models.Organization.id).where(models.Organization.name == "Org CLI Contatos")
    )

    add = runner.invoke(
        app,
        [
            "contacts", "add",
            "--organization-id", str(org_id),
            "--name", "Ana NOC",
            "--email", "ana@example.com",
            "--kind", "noc",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "Ana NOC" in add.output

    assert "Ana NOC" in runner.invoke(app, ["contacts", "list"]).output
    filtrada = runner.invoke(app, ["contacts", "list", "--organization-id", str(org_id)])
    assert "Ana NOC" in filtrada.output

    off = runner.invoke(app, ["contacts", "disable", str(1)])
    assert off.exit_code == 0
    assert "Ana NOC" not in runner.invoke(app, ["contacts", "list"]).output
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: FAIL — comandos `organizations`/`contacts` inexistentes.

- [ ] **Step 7: Write minimal implementation (CLIs + wiring)**

`src/gerenet/cli/organizations.py`:

```python
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import OrganizationCreate
from gerenet.domain.services import organizations as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Organizações (downstreams e parceiros).")


def resolver(session, organization: str):
    """Devolve a organização (ativa ou não) por ID ou nome; None se não existir."""
    if organization.isdigit():
        try:
            return svc.get_organization(session, int(organization))
        except NotFoundError:
            return None
    todas = svc.list_organizations(session, include_disabled=True)
    return next((o for o in todas if o.name == organization), None)


@app.command("add")
def add(
    name: str = typer.Option(..., help="Nome único da organização."),
    legal_name: str | None = typer.Option(None, "--legal-name", help="Razão social."),
    kind: str = typer.Option(
        "downstream", help="Tipo: downstream ou parceiro."
    ),
    asn: int | None = typer.Option(None, min=1, max=4294967295, help="ASN da organização."),
    irr_as_set: str | None = typer.Option(None, "--irr-as-set", help="IRR AS-SET."),
    notes: str | None = typer.Option(None, help="Observações."),
) -> None:
    """Cadastra uma organização."""
    with get_session() as session:
        try:
            org = svc.create_organization(
                session,
                OrganizationCreate(
                    name=name, legal_name=legal_name, kind=kind,
                    asn=asn, irr_as_set=irr_as_set, notes=notes,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Organização {org.id} criada: {org.name} ({org.kind})")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista organizações."""
    with get_session() as session:
        for org in svc.list_organizations(session, include_disabled=include_disabled):
            asn = str(org.asn) if org.asn is not None else "-"
            typer.echo(f"{org.id:>4}  {org.name:<28} {asn:<10} {org.kind}")


@app.command("disable")
def disable(organization: str = typer.Argument(..., help="ID ou nome da organização.")) -> None:
    """Desativa uma organização (mantém histórico e registro)."""
    with get_session() as session:
        encontrada = resolver(session, organization)
        if encontrada is None:
            typer.echo("Organização não encontrada.", err=True)
            raise typer.Exit(1)
        svc.disable_organization(session, encontrada.id, actor="cli")
    typer.echo(f"Organização {encontrada.name} desativada.")
```

`src/gerenet/cli/contacts.py`:

```python
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import ContactCreate
from gerenet.domain.services import contacts as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Contatos de organizações.")


@app.command("add")
def add(
    organization_id: int = typer.Option(..., "--organization-id", help="ID da organização."),
    name: str = typer.Option(..., help="Nome do contato."),
    email: str | None = typer.Option(None, help="E-mail."),
    phone: str | None = typer.Option(None, help="Telefone."),
    kind: str = typer.Option("tecnico", help="Tipo: tecnico, noc ou admin."),
) -> None:
    """Cadastra um contato."""
    with get_session() as session:
        try:
            contato = svc.create_contact(
                session,
                ContactCreate(
                    organization_id=organization_id,
                    name=name,
                    email=email,
                    phone=phone,
                    kind=kind,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Contato {contato.id} criado: {contato.name}")


@app.command("list")
def listar(organization_id: int | None = typer.Option(None, "--organization-id", help="Filtra por organização.")) -> None:
    """Lista contatos ativos."""
    with get_session() as session:
        for contato in svc.list_contacts(session, organization_id=organization_id):
            typer.echo(
                f"{contato.id:>4}  {contato.name:<28} {contato.kind:<8} "
                f"{contato.email or '-':<32} {contato.phone or '-'}"
            )


@app.command("disable")
def disable(contact_id: int = typer.Argument(..., help="ID do contato.")) -> None:
    """Desativa um contato (mantém histórico e registro)."""
    with get_session() as session:
        try:
            svc.disable_contact(session, contact_id, actor="cli")
        except NotFoundError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Contato {contact_id} desativado.")
```

Em `src/gerenet/cli/main.py`:

```python
from gerenet.cli import collect, contacts, devices, hostkey, organizations, sites, snapshot, vault
...
app.add_typer(sites.app, name="sites", help="Sites/POPs.")
app.add_typer(organizations.app, name="organizations", help="Organizações.")
app.add_typer(contacts.app, name="contacts", help="Contatos de organizações.")
```

- [ ] **Step 8: Run CLI test to verify it passes**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: PASS (5 testes — inclui os 3 de sites).

- [ ] **Step 9: Gate + commit**

```bash
uv run ruff check src/gerenet/api/routers/organizations.py src/gerenet/api/routers/contacts.py src/gerenet/cli/organizations.py src/gerenet/cli/contacts.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_organizations_api.py tests/api/test_contacts_api.py tests/cli/test_cli_smoke.py
uv run pytest tests/api/test_organizations_api.py tests/api/test_contacts_api.py tests/cli/test_cli_smoke.py -v
git add src/gerenet/api/routers/organizations.py src/gerenet/api/routers/contacts.py src/gerenet/cli/organizations.py src/gerenet/cli/contacts.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_organizations_api.py tests/api/test_contacts_api.py tests/cli/test_cli_smoke.py
git commit -m "feat(SoT): API/CLI de organizações (com rota downstreams) e contatos"
```

---

### Task 4: Circuits — router com detalhe (pontas) + reserve, CLI e testes

**Files:**
- Create: `src/gerenet/api/routers/circuits.py`, `src/gerenet/cli/circuits.py`, `tests/api/test_circuits_api.py`
- Modify: `src/gerenet/api/main.py`, `src/gerenet/cli/main.py`
- Test: `tests/cli/test_cli_smoke.py` (anexar testes de circuits)

**Interfaces:**
- Consumes: `create_circuit/get_circuit/list_circuits(organization_id, site_id, include_disabled)/update_circuit/disable_circuit` (`domain/services/circuits.py`); `reservar_circuito(session, circuit_id, *, actor)` e `pontas_v4(network) -> tuple[str, str]` / `pontas_v6(network) -> tuple[str, str]` (`domain/services/ipam.py` — v4 sem máscara, v6 com `/126`); schemas `CircuitCreate/Update/Out/CircuitDetailOut` (T1); linhas `IpPrefix` com `status="reservada"` por `circuit_id` (models.py:268-292).
- Produces: rotas `/api/v1/circuits` GET(list filtros organization_id/site_id)/POST(201)/GET{id} (CircuitDetailOut com pontas)/PATCH; `POST /{id}/reserve` → 200 CircuitDetailOut (idempotente); CLI `circuits add|list|reserve|disable` com resolução id|code.

- [ ] **Step 1: Write the failing API tests**

`tests/api/test_circuits_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import pontas_v4, pontas_v6
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session: Session) -> dict:
    """Org, site e devices vinculados — espelho do helper de domínio."""
    site = create_site(db_session, SiteCreate(name="POP-CIRC-API"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Circ API", asn=64502), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-circ-api", management_address="10.9.0.2"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-circ-api", management_address="10.9.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _corpo(env: dict, code: str = "CIRC-API-1") -> dict:
    return {
        "code": code,
        "organization_id": env["org_id"],
        "site_id": env["site_id"],
        "access_device_id": env["sw_id"],
        "access_port": "GE0/0/1",
        "edge_device_id": env["ne_id"],
    }


def test_crud_circuitos(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    criado = client.post("/api/v1/circuits", json=_corpo(env), headers=_auth())
    assert criado.status_code == 201, criado.text
    circ_id = criado.json()["id"]
    assert criado.json()["stack"] == "dual"

    lista = client.get(f"/api/v1/circuits?site_id={env['site_id']}", headers=_auth()).json()
    assert [c["code"] for c in lista] == ["CIRC-API-1"]
    assert "ipv4_local" not in lista[0]  # lista é CircuitOut simples

    corpo = client.get(f"/api/v1/circuits/{circ_id}", headers=_auth()).json()
    assert corpo["ipv4_local"] is None  # ainda não reservado

    dup = client.post("/api/v1/circuits", json=_corpo(env), headers=_auth())
    assert dup.status_code == 409
    assert client.get("/api/v1/circuits/9999", headers=_auth()).status_code == 404


def test_reserva_expoe_pontas_derivadas(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-DUAL"), headers=_auth()
    ).json()["id"]

    reserva = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert reserva.status_code == 200, reserva.text
    corpo = reserva.json()

    linhas = {
        linha.network
        for linha in db_session.scalars(
            select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id)
        )
    }
    rede_v4 = next(n for n in linhas if ":" not in n)
    rede_v6 = next(n for n in linhas if ":" in n)
    assert (corpo["ipv4_local"], corpo["ipv4_remote"]) == pontas_v4(rede_v4)
    assert (corpo["ipv6_local"], corpo["ipv6_remote"]) == pontas_v6(rede_v6)

    # o mesmo detalhe sai no GET
    detalhe = client.get(f"/api/v1/circuits/{circ_id}", headers=_auth()).json()
    assert detalhe["ipv4_local"] == corpo["ipv4_local"]

    # idempotente: segunda reserva 200 sem linhas novas
    antes = len(list(db_session.scalars(select(models.IpPrefix))))
    repetida = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert repetida.status_code == 200
    assert len(list(db_session.scalars(select(models.IpPrefix)))) == antes


def test_reserva_repetida_audita_noop(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-AUDIT"), headers=_auth()
    ).json()["id"]
    for _ in range(2):
        resp = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
        assert resp.status_code == 200

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["circuit.create", "circuit.reserve", "circuit.reserve"]


def test_reserva_ipv6_nao_expoe_par_v4_interno(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    corpo = _corpo(env, "CIRC-V6")
    corpo["stack"] = "ipv6"
    circ_id = client.post("/api/v1/circuits", json=corpo, headers=_auth()).json()["id"]

    resp = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert resp.status_code == 200
    corpo_resp = resp.json()
    assert corpo_resp["ipv4_local"] is None
    assert corpo_resp["ipv6_local"] is not None
    assert corpo_resp["ipv6_local"].endswith("/126")


def test_patch_circuito_desativa_e_audita(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-PATCH"), headers=_auth()
    ).json()["id"]

    off = client.patch(f"/api/v1/circuits/{circ_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    mtu = client.patch(f"/api/v1/circuits/{circ_id}", json={"mtu": 9000}, headers=_auth())
    assert mtu.status_code == 200

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["circuit.create", "circuit.disable", "circuit.update"]


def test_reserva_de_circuito_desativado_da_409(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = client.post(
        "/api/v1/circuits", json=_corpo(env, "CIRC-OFF"), headers=_auth()
    ).json()["id"]
    client.patch(f"/api/v1/circuits/{circ_id}", json={"admin_status": False}, headers=_auth())

    resp = client.post(f"/api/v1/circuits/{circ_id}/reserve", headers=_auth())
    assert resp.status_code == 409
    assert "desativado" in resp.json()["detail"]

    assert client.post("/api/v1/circuits/9999/reserve", headers=_auth()).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_circuits_api.py -v`
Expected: FAIL — rotas inexistentes.

- [ ] **Step 3: Write minimal implementation (router + wiring)**

`src/gerenet/api/routers/circuits.py`:

```python
import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, CircuitDetailOut, CircuitOut, CircuitUpdate
from gerenet.domain.services import circuits as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito

router = APIRouter(prefix="/api/v1/circuits", tags=["circuits"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


def _detalhe(session: Session, circ: models.Circuit) -> CircuitDetailOut:
    """CircuitDetailOut com as pontas derivadas dos enlaces reservados (ruling 4).

    Só famílias do stack: o par v4 interno de derivação (stack=ipv6) não sai.
    """
    linhas = list(
        session.scalars(
            select(models.IpPrefix).where(
                models.IpPrefix.circuit_id == circ.id,
                models.IpPrefix.status == "reservada",
            )
        )
    )
    por_versao = {ipaddress.ip_network(linha.network).version: linha.network for linha in linhas}
    pontas: dict[str, str | None] = {
        "ipv4_local": None,
        "ipv4_remote": None,
        "ipv6_local": None,
        "ipv6_remote": None,
    }
    if circ.stack in ("ipv4", "dual") and 4 in por_versao:
        pontas["ipv4_local"], pontas["ipv4_remote"] = pontas_v4(por_versao[4])
    if circ.stack in ("ipv6", "dual") and 6 in por_versao:
        pontas["ipv6_local"], pontas["ipv6_remote"] = pontas_v6(por_versao[6])
    return CircuitDetailOut.model_validate(circ).model_copy(update=pontas)


@router.get("", response_model=list[CircuitOut])
def listar(
    session: SessionDep,
    organization_id: int | None = None,
    site_id: int | None = None,
    include_disabled: bool = False,
) -> list:
    return svc.list_circuits(
        session,
        organization_id=organization_id,
        site_id=site_id,
        include_disabled=include_disabled,
    )


@router.post("", response_model=CircuitOut, status_code=201)
def criar(data: CircuitCreate, session: SessionDep) -> object:
    try:
        return svc.create_circuit(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{circuit_id}", response_model=CircuitDetailOut)
def detalhar(circuit_id: int, session: SessionDep) -> object:
    try:
        return _detalhe(session, svc.get_circuit(session, circuit_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{circuit_id}", response_model=CircuitOut)
def atualizar(circuit_id: int, data: CircuitUpdate, session: SessionDep) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_circuit(session, circuit_id, actor="api")
        return svc.update_circuit(session, circuit_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{circuit_id}/reserve", response_model=CircuitDetailOut)
def reservar(circuit_id: int, session: SessionDep) -> object:
    """Reserva VLAN/enlaces p2p — idempotente (spec §9): repetida devolve o estado."""
    try:
        circ = svc.get_circuit(session, circuit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        reservar_circuito(session, circuit_id, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _detalhe(session, circ)
```

Em `src/gerenet/api/main.py`:

```python
from gerenet.api.routers import circuits, contacts, devices, organizations, sites
...
    app.include_router(contacts.router)
    app.include_router(circuits.router)
```

- [ ] **Step 4: Run API test to verify it passes**

Run: `uv run pytest tests/api/test_circuits_api.py -v`
Expected: PASS (6 testes).

- [ ] **Step 5: Write the failing CLI smoke tests (anexar a `tests/cli/test_cli_smoke.py`; imports novos no topo do arquivo: `from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate`, `from gerenet.domain.services.devices import create_device`, `from gerenet.domain.services.organizations import create_organization`, `from gerenet.domain.services.sites import create_site, link_device`)**

```python
def test_cli_circuits_add_reserve_disable(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="POP-CIRC-CLI"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Org Circ CLI", asn=64503), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-circ-cli", management_address="10.9.1.2"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-circ-cli", management_address="10.9.1.1", asn=64601),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")

    add = runner.invoke(
        app,
        [
            "circuits", "add", "--code", "CIRC-CLI-1",
            "--organization-id", str(org.id), "--site-id", str(site.id),
            "--access-device-id", str(sw.id), "--access-port", "GE0/0/1",
            "--edge-device-id", str(ne.id),
        ],
    )
    assert add.exit_code == 0, add.output
    assert "CIRC-CLI-1" in add.output
    assert "CIRC-CLI-1" in runner.invoke(app, ["circuits", "list"]).output

    reserva = runner.invoke(app, ["circuits", "reserve", "CIRC-CLI-1"])
    assert reserva.exit_code == 0, reserva.output

    circ_db = db_session.scalar(select(models.Circuit).where(models.Circuit.code == "CIRC-CLI-1"))
    assert circ_db is not None
    assert db_session.scalar(
        select(models.Vlan).where(models.Vlan.circuit_id == circ_db.id)
    ) is not None

    repetida = runner.invoke(app, ["circuits", "reserve", "CIRC-CLI-1"])
    assert repetida.exit_code == 0
    vlans = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_db.id)))
    assert len(vlans) == 1

    off = runner.invoke(app, ["circuits", "disable", "CIRC-CLI-1"])
    assert off.exit_code == 0
    assert "CIRC-CLI-1" not in runner.invoke(app, ["circuits", "list"]).output

    faltante = runner.invoke(app, ["circuits", "reserve", "nao-existe"])
    assert faltante.exit_code == 1
    assert "não encontrado" in faltante.output
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: FAIL — comando `circuits` inexistente.

- [ ] **Step 7: Write minimal implementation (CLI + wiring)**

`src/gerenet/cli/circuits.py`:

```python
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import CircuitCreate
from gerenet.domain.services import circuits as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError
from gerenet.domain.services.ipam import reservar_circuito

app = typer.Typer(help="Circuitos de acesso de downstreams.")


def resolver(session, circuito: str):
    """Devolve o circuito (ativo ou não) por ID ou código; None se não existir."""
    if circuito.isdigit():
        try:
            return svc.get_circuit(session, int(circuito))
        except NotFoundError:
            return None
    return next(
        (c for c in svc.list_circuits(session, include_disabled=True) if c.code == circuito),
        None,
    )


@app.command("add")
def add(
    code: str = typer.Option(..., help="Código único do circuito."),
    organization_id: int = typer.Option(..., "--organization-id", help="ID da organização."),
    site_id: int = typer.Option(..., "--site-id", help="ID do site/POP."),
    access_device_id: int = typer.Option(..., "--access-device-id", help="ID do switch de acesso."),
    access_port: str = typer.Option(..., "--access-port", help="Porta de acesso (ex.: GE0/0/1)."),
    edge_device_id: int = typer.Option(..., "--edge-device-id", help="ID do edge (NE8000)."),
    backup_edge_device_id: int | None = typer.Option(
        None, "--backup-edge-device-id", help="ID do edge de contingência."
    ),
    stack: str = typer.Option("dual", help="ipv4, ipv6 ou dual."),
    vlan_mode: str = typer.Option("unica", "--vlan-mode", help="unica ou separada."),
    qinq: bool = typer.Option(False, "--qinq", help="Habilita QinQ."),
    vrf: str | None = typer.Option(None, help="VRF (default: instância pública)."),
    mtu: int | None = typer.Option(None, min=576, max=9600, help="MTU."),
    bandwidth: str | None = typer.Option(None, help="Banda (ex.: 1Gbps)."),
    bfd: bool = typer.Option(False, "--bfd", help="Habilita BFD."),
    p2p_v4_len: int = typer.Option(
        31, "--p2p-v4-len", min=30, max=31, help="Máscara p2p v4 (30 ou 31)."
    ),
    description: str | None = typer.Option(None, help="Descrição."),
) -> None:
    """Cadastra um circuito de acesso."""
    with get_session() as session:
        try:
            circ = svc.create_circuit(
                session,
                CircuitCreate(
                    code=code,
                    organization_id=organization_id,
                    site_id=site_id,
                    access_device_id=access_device_id,
                    access_port=access_port,
                    edge_device_id=edge_device_id,
                    backup_edge_device_id=backup_edge_device_id,
                    stack=stack,
                    vlan_mode=vlan_mode,
                    qinq=qinq,
                    vrf=vrf,
                    mtu=mtu,
                    bandwidth=bandwidth,
                    bfd=bfd,
                    p2p_v4_len=p2p_v4_len,
                    description=description,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {circ.id} criado: {circ.code}")


@app.command("list")
def listar(
    organization_id: int | None = typer.Option(None, "--organization-id", help="Filtra por organização."),
    site_id: int | None = typer.Option(None, "--site-id", help="Filtra por site."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista circuitos."""
    with get_session() as session:
        for circ in svc.list_circuits(
            session, organization_id=organization_id, site_id=site_id,
            include_disabled=include_disabled,
        ):
            vrf = circ.vrf or "-"
            typer.echo(
                f"{circ.id:>4}  {circ.code:<14} org {circ.organization_id:>4} "
                f"site {circ.site_id:>3} stack {circ.stack:<5} vrf {vrf}"
            )


@app.command("reserve")
def reserve(circuito: str = typer.Argument(..., help="ID ou código do circuito.")) -> None:
    """Reserva VLAN e enlaces p2p do circuito (idempotente)."""
    with get_session() as session:
        encontrado = resolver(session, circuito)
        if encontrado is None:
            typer.echo("Circuito não encontrado.", err=True)
            raise typer.Exit(1)
        reservar_circuito(session, encontrado.id, actor="cli")
    typer.echo(f"Circuito {encontrado.code} reservado (idempotente).")


@app.command("disable")
def disable(circuito: str = typer.Argument(..., help="ID ou código do circuito.")) -> None:
    """Desativa um circuito (mantém histórico e registro)."""
    with get_session() as session:
        encontrado = resolver(session, circuito)
        if encontrado is None:
            typer.echo("Circuito não encontrado.", err=True)
            raise typer.Exit(1)
        svc.disable_circuit(session, encontrado.id, actor="cli")
    typer.echo(f"Circuito {encontrado.code} desativado.")
```

Em `src/gerenet/cli/main.py`:

```python
from gerenet.cli import circuits, collect, contacts, devices, hostkey, organizations, sites, snapshot, vault
...
app.add_typer(contacts.app, name="contacts", help="Contatos de organizações.")
app.add_typer(circuits.app, name="circuits", help="Circuitos de acesso.")
```

- [ ] **Step 8: Run CLI test to verify it passes**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: PASS (6 testes).

- [ ] **Step 9: Gate + commit**

```bash
uv run ruff check src/gerenet/api/routers/circuits.py src/gerenet/cli/circuits.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_circuits_api.py tests/cli/test_cli_smoke.py
uv run pytest tests/api/test_circuits_api.py tests/cli/test_cli_smoke.py -v
git add src/gerenet/api/routers/circuits.py src/gerenet/cli/circuits.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_circuits_api.py tests/cli/test_cli_smoke.py
git commit -m "feat(SoT): API e CLI de circuitos com reserva idempotente e pontas derivadas"
```

---

### Task 5: Serviço de senha BGP (`set_password`), guarda de `asn_remote` e Vault genérico

**Files:**
- Modify: `src/gerenet/domain/services/bgp_sessions.py` — guarda nova em `update_session` (ruling 8) e função `set_password` (ruling 6)
- Modify: `src/gerenet/secrets/vault_store.py` — `set_secret`/`get_secret` genéricos; `get_credential` passa a delegar (ruling 6)
- Test: `tests/domain/test_bgp_sessions_service.py` (anexar 4 testes + import de `set_password`), `tests/test_secrets.py` (anexar 2 testes)

**Interfaces:**
- Consumes: `update_session` (body em `bgp_sessions.py:194-266`, ponto de inserção após `org = get_organization(session, circ.organization_id)` na linha 223); `registrar` de `domain/audit.py` (mascara campos sensíveis); `get_session` do serviço; `VaultSecretStore(url, token)` com `is_authenticated` no `__init__` (RuntimeError).
- Produces: `bgp_sessions.set_password(session, session_id, *, actor, path) -> models.BgpSession` (audita `bgp_session.password_set` com antes/depois = `{"has_password": ...}`); guarda de `asn_remote` em `update_session` (`ValidationError` com a mesma mensagem do `create_session`); `VaultSecretStore.get_secret(path) -> dict[str, str]` e `.set_secret(path, dados) -> None` (falhas de hvac viraram `RuntimeError`).

- [ ] **Step 1: Write the failing domain tests**

Anexar a `tests/domain/test_bgp_sessions_service.py` (e adicionar `set_password` ao bloco de import do módulo, em ordem alfabética: entre `remove_community` e `update_session`):

```python
def test_update_muda_para_org_sem_asn_exige_asn_remote(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-A", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")

    org_sem_asn = create_organization(
        db_session, OrganizationCreate(name="Cliente Sem ASN"), actor="cli"
    )
    circ2 = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-B",
            organization_id=org_sem_asn.id,
            site_id=env["site_id"],
            access_device_id=env["sw_id"],
            access_port="GE0/0/2",
            edge_device_id=env["ne1_id"],
        ),
        actor="cli",
    )
    with pytest.raises(ValidationError, match="não possui ASN; informe asn_remote"):
        update_session(db_session, sessao.id, BgpSessionUpdate(circuit_id=circ2), actor="cli")
    # com asn_remote explícito a troca passa
    atualizada = update_session(
        db_session,
        sessao.id,
        BgpSessionUpdate(circuit_id=circ2, asn_remote=64530),
        actor="cli",
    )
    assert atualizada.circuit_id == circ2
    assert atualizada.asn_remote == 64530


def test_set_password_registra_ref_e_audita(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-PW", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    assert sessao.has_password is False
    caminho = f"gerenet/bgp-sessions/{sessao.id}/password"

    atualizada = set_password(db_session, sessao.id, actor="cli", path=caminho)
    assert atualizada.password_ref == caminho
    assert atualizada.has_password is True

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["bgp_session.create", "bgp_session.password_set"]


def test_set_password_troca_audita_novamente(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-PW2", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    caminho = f"gerenet/bgp-sessions/{sessao.id}/password"
    set_password(db_session, sessao.id, actor="cli", path=caminho)
    set_password(db_session, sessao.id, actor="cli", path=caminho)
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == [
        "bgp_session.create", "bgp_session.password_set", "bgp_session.password_set",
    ]


def test_set_password_sessao_inexistente_da_404(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="não encontrada"):
        set_password(db_session, 9999, actor="cli", path="gerenet/bgp-sessions/9999/password")
```

Anexar a `tests/test_secrets.py`:

```python
CAMINHO_BGP = "gerenet/bgp-sessions/1/password"


def test_set_e_get_secret_roundtrip() -> None:
    s = Settings(_env_file=None)
    store = VaultSecretStore(s.vault_url, s.vault_token)
    store.set_secret(CAMINHO_BGP, {"password": "md5-segredo"})
    assert store.get_secret(CAMINHO_BGP) == {"password": "md5-segredo"}


def test_set_secret_sobrescreve_valor() -> None:
    s = Settings(_env_file=None)
    store = VaultSecretStore(s.vault_url, s.vault_token)
    store.set_secret(CAMINHO_BGP, {"password": "md5-primeiro"})
    store.set_secret(CAMINHO_BGP, {"password": "md5-segundo"})
    assert store.get_secret(CAMINHO_BGP) == {"password": "md5-segundo"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -k "sem_asn or set_password" -v && uv run pytest tests/test_secrets.py -k "secret" -v`
Expected: FAIL — `set_password` inexistente (ImportError) e a guarda ausente deixa a troca passar.

- [ ] **Step 3: Write minimal implementation**

Em `src/gerenet/domain/services/bgp_sessions.py`, na `update_session`, imediatamente após a linha `org = get_organization(session, circ.organization_id)`:

```python
    if "circuit_id" in mudancas and org.asn is None and "asn_remote" not in mudancas:
        # nova organização sem ASN: o asn_remote da sessão antiga não pode vazar
        raise ValidationError(f"Organização {org.name} não possui ASN; informe asn_remote.")
```

Anexar ao fim do mesmo arquivo:

```python
def set_password(
    session: Session, session_id: int, *, actor: str, path: str
) -> models.BgpSession:
    """Registra a senha MD5 da sessão — valor já gravado no Vault pelo chamador.

    O banco guarda só o path (password_ref); trocar a senha é transição real e
    sempre audita antes/depois como has_password. Uma gravação órfã no Vault
    (falha de commit depois do passo 2) é inofensiva: o path é por session_id e
    a próxima chamada sobrescreve o valor.
    """
    sessao = get_session(session, session_id)
    antes = {"has_password": sessao.has_password}
    sessao.password_ref = path
    registrar(
        session, tipo="bgp_session.password_set", ator=actor, objeto="bgp_session",
        objeto_id=sessao.id, antes=antes, depois={"has_password": True},
    )
    session.commit()
    session.refresh(sessao)
    return sessao
```

Em `src/gerenet/secrets/vault_store.py`, substituir o corpo de `get_credential` e anexar os dois métodos:

```python
    def get_credential(self, vault_path: str) -> dict[str, str]:
        dados = self.get_secret(vault_path)
        return {"username": dados["username"], "password": dados["password"]}

    def get_secret(self, path: str) -> dict[str, str]:
        """Lê o conteúdo de um caminho KV v2 (falha vira RuntimeError)."""
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(path=path)
        except Exception as exc:  # conexão, token, permissão, caminho inexistente
            raise RuntimeError(f"Falha ao ler o segredo {path}: {exc}") from exc
        return dict(resp["data"]["data"])

    def set_secret(self, path: str, dados: dict[str, str]) -> None:
        """Grava/substitui o segredo no caminho KV v2 (idempotente; falha vira RuntimeError)."""
        try:
            self._client.secrets.kv.v2.create_or_update_secret(path=path, secret=dados)
        except Exception as exc:
            raise RuntimeError(f"Falha ao gravar o segredo {path}: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -k "sem_asn or set_password" -v`
Expected: PASS (4 testes).
Run: `uv run pytest tests/test_secrets.py -v`
Expected: PASS (3 testes — roundtrip antigo incluído).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src/gerenet/domain/services/bgp_sessions.py src/gerenet/secrets/vault_store.py tests/domain/test_bgp_sessions_service.py tests/test_secrets.py
git add src/gerenet/domain/services/bgp_sessions.py src/gerenet/secrets/vault_store.py tests/domain/test_bgp_sessions_service.py tests/test_secrets.py
git commit -m "feat(SoT): set_password em sessões BGP (Vault genérico) + guarda de asn_remote no update"
```

---

### Task 6: Sessões BGP — router, CLI (add|list|disable|password set) e testes

**Files:**
- Create: `src/gerenet/api/routers/bgp_sessions.py`, `src/gerenet/cli/bgp_sessions.py`, `tests/api/test_bgp_sessions_api.py`
- Modify: `src/gerenet/api/main.py`, `src/gerenet/cli/main.py`
- Test: `tests/cli/test_cli_smoke.py` (anexar testes de sessões)

**Interfaces:**
- Consumes: `svc.create_session/get_session/list_sessions(circuit_id, device_id, include_disabled)/update_session/disable_session/set_password` (`domain/services/bgp_sessions.py`); `VaultSecretStore.get_secret/set_secret` + `RuntimeError` em falha (T5); `BgpSessionCreate/Update/Out/BgpSessionPasswordIn` (T1); `get_settings` de `gerenet.config`.
- Produces: rotas `/api/v1/bgp-sessions` GET(list filtros circuit_id/device_id)/POST(201)/GET{id}/PATCH e `POST /{id}/password` (200 `BgpSessionOut`, 404, 503 Vault fora do ar); CLI `bgp-sessions add|list|disable|password set` (senha por prompt `hide_input` com confirmação).

- [ ] **Step 1: Write the failing API tests**

`tests/api/test_bgp_sessions_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session: Session) -> dict:
    """Org (ASN 64512), site, switch e 2 NE8000 (ASNs 64600/64601) no site."""
    site = create_site(db_session, SiteCreate(name="pop-bgp-api"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP API", asn=64512), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-bgp-api", management_address="10.8.1.2"), actor="cli"
    )
    ne1 = create_device(
        db_session,
        DeviceCreate(name="ne8k-bgp-api1", management_address="10.8.1.1", asn=64600),
        actor="cli",
    )
    ne2 = create_device(
        db_session,
        DeviceCreate(name="ne8k-bgp-api2", management_address="10.8.1.3", asn=64601),
        actor="cli",
    )
    for dev in (sw, ne1, ne2):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne1_id": ne1.id, "ne2_id": ne2.id}


def _corpo_circuito(env: dict, code: str, *, edge: int | None = None) -> dict:
    return {
        "code": code,
        "organization_id": env["org_id"],
        "site_id": env["site_id"],
        "access_device_id": env["sw_id"],
        "access_port": "GE0/0/1",
        "edge_device_id": env["ne1_id"] if edge is None else edge,
    }


def _circuito(client: TestClient, env: dict, code: str, **extra: object) -> int:
    corpo = {**_corpo_circuito(env, code), **extra}
    resp = client.post("/api/v1/circuits", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _sessao(
    client: TestClient, env: dict, circ_id: int,
    *, afi: str = "ipv4", local: str = "100.64.1.1", remote: str = "100.64.1.2",
    **extra: object,
) -> dict:
    corpo: dict[str, object] = {
        "circuit_id": circ_id,
        "device_id": env["ne1_id"],
        "afi": afi,
        "local_address": local,
        "remote_address": remote,
        **extra,
    }
    resp = client.post("/api/v1/bgp-sessions", json=corpo, headers=_auth())
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_cria_sessao_com_defaults_de_asn(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1001")
    corpo = _sessao(client, env, circ)
    assert corpo["asn_local"] == 64600  # default device.asn
    assert corpo["asn_remote"] == 64512  # default organization.asn
    assert corpo["has_password"] is False
    assert "password_ref" not in corpo

    corpo_v6 = _sessao(
        client, env, circ, afi="ipv6",
        local="2804:194C:1::1", remote="2804:194C:1::2",
        maximum_prefix=1000, shutdown=True,
    )
    assert corpo_v6["maximum_prefix"] == 1000


def test_cria_com_perfil_e_valida_direcao(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    export = list_policy_profiles(db_session, direction="export")[0]
    circ = _circuito(client, env, "CIRC-1002")
    corpo = _sessao(client, env, circ, export_profile_id=export.id)
    assert corpo["export_profile_id"] == export.id

    errado = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ, "device_id": env["ne1_id"], "afi": "ipv4",
            "local_address": "100.64.2.1", "remote_address": "100.64.2.2",
            "import_profile_id": export.id,  # direção errada
        },
        headers=_auth(),
    )
    assert errado.status_code == 400
    assert "direção" in errado.json()["detail"] or "direcao" in errado.json()["detail"]


def test_erros_de_criacao(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1003")
    _sessao(client, env, circ, local="100.64.3.1", remote="100.64.3.2")

    # mesmo (device, VRF, afi): 409
    dup = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ, "device_id": env["ne1_id"], "afi": "ipv4",
            "local_address": "100.64.3.3", "remote_address": "100.64.3.4",
        },
        headers=_auth(),
    )
    assert dup.status_code == 409

    # device fora do circuito: 400
    circ2 = _circuito(client, env, "CIRC-1004", edge=env["ne2_id"])
    fora = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ2, "device_id": env["ne1_id"], "afi": "ipv4",
            "local_address": "100.64.4.1", "remote_address": "100.64.4.2",
        },
        headers=_auth(),
    )
    assert fora.status_code == 400
    assert "edge/backup_edge" in fora.json()["detail"]

    # endereço da família errada: 400
    ruim = client.post(
        "/api/v1/bgp-sessions",
        json={
            "circuit_id": circ2, "device_id": env["ne2_id"], "afi": "ipv4",
            "local_address": "2804::1", "remote_address": "100.64.4.2",
        },
        headers=_auth(),
    )
    assert ruim.status_code == 400

    assert client.get("/api/v1/bgp-sessions/9999", headers=_auth()).status_code == 404


def test_lista_filtra_por_circuito_e_device(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1005")
    _sessao(client, env, circ)
    lista = client.get(f"/api/v1/bgp-sessions?circuit_id={circ}", headers=_auth()).json()
    assert len(lista) == 1
    assert client.get(f"/api/v1/bgp-sessions?device_id={env['ne2_id']}", headers=_auth()).json() == []


def test_patch_desativa_e_guarda_asn_remote(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1006")
    corpo = _sessao(client, env, circ)
    sessao_id = corpo["id"]

    off = client.patch(f"/api/v1/bgp-sessions/{sessao_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False
    assert off.json()["has_password"] is False

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["circuit.create", "bgp_session.create", "bgp_session.disable"]

    # trocar para organização sem ASN sem asn_remote: 400 (ruling 8)
    org_sem = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP Sem ASN"), actor="cli"
    )
    circ2 = _circuito(client, env, "CIRC-1007", organization_id=org_sem.id)
    sem_asn = client.patch(
        f"/api/v1/bgp-sessions/{sessao_id}", json={"circuit_id": circ2}, headers=_auth()
    )
    assert sem_asn.status_code == 400
    assert "asn_remote" in sem_asn.json()["detail"]

    com_asn = client.patch(
        f"/api/v1/bgp-sessions/{sessao_id}",
        json={"circuit_id": circ2, "asn_remote": 64530},
        headers=_auth(),
    )
    assert com_asn.status_code == 200
    assert com_asn.json()["asn_remote"] == 64530


def test_password_set_grava_vault_e_audita(client: TestClient, db_session: Session) -> None:
    from gerenet.config import Settings
    from gerenet.secrets.vault_store import VaultSecretStore

    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1008")
    sessao_id = _sessao(client, env, circ)["id"]

    resp = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/password",
        json={"password": "md5-api-segredo"},
        headers=_auth(),
    )
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["has_password"] is True
    assert "password_ref" not in corpo

    sessao_db = db_session.get(models.BgpSession, sessao_id)
    assert sessao_db is not None
    caminho = sessao_db.password_ref
    assert caminho == f"gerenet/bgp-sessions/{sessao_id}/password"

    settings = Settings(_env_file=None)
    store = VaultSecretStore(settings.vault_url, settings.vault_token)
    assert store.get_secret(caminho) == {"password": "md5-api-segredo"}

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["circuit.create", "bgp_session.create", "bgp_session.password_set"]
    # nenhum evento carrega o valor da senha
    for evento in db_session.scalars(select(models.AuditEvent)):
        assert "md5-api-segredo" not in str(evento.details)


def test_password_set_vault_fora_do_ar_da_503(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gerenet.api.routers import bgp_sessions as modulo

    env = _ambiente(db_session)
    circ = _circuito(client, env, "CIRC-1009")
    sessao_id = _sessao(client, env, circ)["id"]

    def _falha(*args: object, **kwargs: object) -> None:
        raise RuntimeError("conexão recusada")

    monkeypatch.setattr(modulo, "VaultSecretStore", _falha)
    resp = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/password",
        json={"password": "md5-x"},
        headers=_auth(),
    )
    assert resp.status_code == 503
    assert "Vault indisponível" in resp.json()["detail"]

    assert client.post(
        "/api/v1/bgp-sessions/9999/password", json={"password": "md5-x"}, headers=_auth()
    ).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_bgp_sessions_api.py -v`
Expected: FAIL — rotas inexistentes.

- [ ] **Step 3: Write minimal implementation (router + wiring)**

`src/gerenet/api/routers/bgp_sessions.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.config import get_settings
from gerenet.db import get_db
from gerenet.domain.schemas import (
    BgpSessionCreate,
    BgpSessionOut,
    BgpSessionPasswordIn,
    BgpSessionUpdate,
)
from gerenet.domain.services import bgp_sessions as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.secrets.vault_store import VaultSecretStore

router = APIRouter(prefix="/api/v1/bgp-sessions", tags=["bgp-sessions"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[BgpSessionOut])
def listar(
    session: SessionDep,
    circuit_id: int | None = None,
    device_id: int | None = None,
    include_disabled: bool = False,
) -> list:
    return svc.list_sessions(
        session,
        circuit_id=circuit_id,
        device_id=device_id,
        include_disabled=include_disabled,
    )


@router.post("", response_model=BgpSessionOut, status_code=201)
def criar(data: BgpSessionCreate, session: SessionDep) -> object:
    try:
        return svc.create_session(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{session_id}", response_model=BgpSessionOut)
def detalhar(session_id: int, session: SessionDep) -> object:
    try:
        return svc.get_session(session, session_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{session_id}", response_model=BgpSessionOut)
def atualizar(session_id: int, data: BgpSessionUpdate, session: SessionDep) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_session(session, session_id, actor="api")
        return svc.update_session(session, session_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/password", response_model=BgpSessionOut)
def definir_senha(
    session_id: int, data: BgpSessionPasswordIn, session: SessionDep
) -> object:
    """Grava a senha MD5 no Vault e registra só o path na sessão (spec §8)."""
    try:
        sessao = svc.get_session(session, session_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    caminho = f"gerenet/bgp-sessions/{sessao.id}/password"
    try:
        settings = get_settings()
        store = VaultSecretStore(settings.vault_url, settings.vault_token)
        store.set_secret(caminho, {"password": data.password})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Vault indisponível: {exc}.") from exc
    return svc.set_password(session, sessao.id, actor="api", path=caminho)
```

Em `src/gerenet/api/main.py`:

```python
from gerenet.api.routers import bgp_sessions, circuits, contacts, devices, organizations, sites
...
    app.include_router(circuits.router)
    app.include_router(bgp_sessions.router)
```

- [ ] **Step 4: Run API test to verify it passes**

Run: `uv run pytest tests/api/test_bgp_sessions_api.py -v`
Expected: PASS (7 testes). Obs.: o teste de password usa o Vault real do compose (padrão de `tests/test_secrets.py`).

- [ ] **Step 5: Write the failing CLI smoke tests (anexar a `tests/cli/test_cli_smoke.py`; import novo no topo: `from gerenet.config import Settings`, `from gerenet.secrets.vault_store import VaultSecretStore`, `from gerenet.cli import bgp_sessions as cli_bgp`)**

```python
def _ambiente_bgp(db_session: Session) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-bgp-cli"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP CLI", asn=64513), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-bgp-cli", management_address="10.8.2.2"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-bgp-cli", management_address="10.8.2.1", asn=64610),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _circuito_cli(db_session: Session, env: dict, code: str) -> int:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    return create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne_id"],
        ),
        actor="cli",
    ).id


def test_cli_bgp_sessions_add_list_disable(db_session: Session) -> None:
    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-CLI")

    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.10.1", "--remote-address", "100.64.10.2",
            "--asn-remote", "64513", "--maximum-prefix", "500",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "criada" in add.output

    lista = runner.invoke(app, ["bgp-sessions", "list"])
    assert lista.exit_code == 0
    assert "100.64.10.1" in lista.output

    off = runner.invoke(app, ["bgp-sessions", "disable", "1"])
    assert off.exit_code == 0
    assert "100.64.10.1" not in runner.invoke(app, ["bgp-sessions", "list"]).output
    assert "100.64.10.1" in runner.invoke(app, ["bgp-sessions", "list", "--all"]).output


def test_cli_bgp_sessions_password_set(db_session: Session) -> None:
    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-PW")
    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.11.1", "--remote-address", "100.64.11.2",
        ],
    )
    assert add.exit_code == 0, add.output

    setar = runner.invoke(
        app, ["bgp-sessions", "password", "set", "1"], input="md5-cli-segredo\nmd5-cli-segredo\n"
    )
    assert setar.exit_code == 0, setar.output
    assert "Vault" in setar.output

    sessao = db_session.scalar(select(models.BgpSession).where(models.BgpSession.id == 1))
    assert sessao is not None and sessao.password_ref == "gerenet/bgp-sessions/1/password"

    settings = Settings(_env_file=None)
    store = VaultSecretStore(settings.vault_url, settings.vault_token)
    assert store.get_secret(sessao.password_ref) == {"password": "md5-cli-segredo"}


def test_cli_bgp_sessions_password_vault_fora_do_ar(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-PW-ERR")
    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.12.1", "--remote-address", "100.64.12.2",
        ],
    )
    assert add.exit_code == 0, add.output

    def _falha(*args: object, **kwargs: object) -> None:
        raise RuntimeError("conexão recusada")

    monkeypatch.setattr(cli_bgp, "VaultSecretStore", _falha)
    setar = runner.invoke(
        app, ["bgp-sessions", "password", "set", "1"], input="md5-x\nmd5-x\n"
    )
    assert setar.exit_code == 1
    assert "Vault indisponível" in setar.output
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: FAIL — comando `bgp-sessions` inexistente.

- [ ] **Step 7: Write minimal implementation (CLI + wiring)**

`src/gerenet/cli/bgp_sessions.py`:

```python
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.config import get_settings
from gerenet.db import get_session
from gerenet.domain.schemas import BgpSessionCreate
from gerenet.domain.services import bgp_sessions as svc
from gerenet.domain.services.errors import GerenetError
from gerenet.secrets.vault_store import VaultSecretStore

app = typer.Typer(help="Sessões BGP por família.")
password = typer.Typer(help="Senha MD5 do peer (valor só no Vault).")
app.add_typer(password, name="password")


@app.command("add")
def add(
    circuit_id: int = typer.Option(..., "--circuit-id", help="ID do circuito."),
    device_id: int = typer.Option(..., "--device-id", help="ID do edge (NE8000)."),
    afi: str = typer.Option(..., help="ipv4 ou ipv6."),
    local_address: str = typer.Option(..., "--local-address", help="Endereço local."),
    remote_address: str = typer.Option(..., "--remote-address", help="Endereço remoto."),
    source_address: str | None = typer.Option(None, "--source-address", help="Source address (opcional)."),
    asn_local: int | None = typer.Option(
        None, "--asn-local", min=1, max=4294967295,
        help="ASN local (default: ASN do equipamento).",
    ),
    asn_remote: int | None = typer.Option(
        None, "--asn-remote", min=1, max=4294967295,
        help="ASN remoto (default: ASN da organização).",
    ),
    description: str | None = typer.Option(None, help="Descrição."),
    import_profile_id: int | None = typer.Option(None, "--import-profile-id", help="Perfil de importação."),
    export_profile_id: int | None = typer.Option(None, "--export-profile-id", help="Perfil de exportação."),
    maximum_prefix: int | None = typer.Option(None, "--maximum-prefix", help="Limite de prefixos."),
    maximum_prefix_threshold: int | None = typer.Option(
        None, "--maximum-prefix-threshold", min=0, max=100, help="Limiar em % (0-100)."
    ),
    local_preference: int | None = typer.Option(None, "--local-preference", help="Local preference."),
    med: int | None = typer.Option(None, help="MED."),
    prepend: int | None = typer.Option(None, min=0, max=10, help="Prepend (0-10)."),
    keepalive: int | None = typer.Option(None, help="Timer keepalive (s)."),
    holdtime: int | None = typer.Option(None, help="Timer holdtime (s)."),
    bfd_enabled: bool = typer.Option(False, "--bfd-enabled", help="Habilita BFD."),
    graceful_restart: bool = typer.Option(False, "--graceful-restart", help="Graceful restart."),
    shutdown: bool = typer.Option(False, "--shutdown", help="Admin shutdown."),
    allow_default_route: bool = typer.Option(False, "--allow-default-route", help="Aceita rota default."),
) -> None:
    """Cadastra uma sessão BGP."""
    with get_session() as session:
        try:
            sessao = svc.create_session(
                session,
                BgpSessionCreate(
                    circuit_id=circuit_id,
                    device_id=device_id,
                    afi=afi,
                    local_address=local_address,
                    remote_address=remote_address,
                    source_address=source_address,
                    asn_local=asn_local,
                    asn_remote=asn_remote,
                    description=description,
                    import_profile_id=import_profile_id,
                    export_profile_id=export_profile_id,
                    maximum_prefix=maximum_prefix,
                    maximum_prefix_threshold=maximum_prefix_threshold,
                    local_preference=local_preference,
                    med=med,
                    prepend=prepend,
                    keepalive=keepalive,
                    holdtime=holdtime,
                    bfd_enabled=bfd_enabled,
                    graceful_restart=graceful_restart,
                    shutdown=shutdown,
                    allow_default_route=allow_default_route,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Sessão BGP {sessao.id} criada: {sessao.afi} {sessao.local_address} → {sessao.remote_address}")


@app.command("list")
def listar(
    circuit_id: int | None = typer.Option(None, "--circuit-id", help="Filtra por circuito."),
    device_id: int | None = typer.Option(None, "--device-id", help="Filtra por equipamento."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista sessões BGP."""
    with get_session() as session:
        for sessao in svc.list_sessions(
            session, circuit_id=circuit_id, device_id=device_id,
            include_disabled=include_disabled,
        ):
            typer.echo(
                f"{sessao.id:>4}  {sessao.afi:<4} {sessao.local_address:<16} → "
                f"{sessao.remote_address:<16} circ {sessao.circuit_id:>4}"
            )


@app.command("disable")
def disable(session_id: int = typer.Argument(..., help="ID da sessão BGP.")) -> None:
    """Desativa uma sessão (mantém histórico e registro)."""
    with get_session() as session:
        try:
            svc.disable_session(session, session_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Sessão BGP {session_id} desativada.")


@password.command("set")
def definir_senha(
    session_id: int = typer.Argument(..., help="ID da sessão BGP."),
    password: str = typer.Option(
        ...,
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Senha MD5 do peer (valor só no Vault).",
    ),
) -> None:
    """Define/troca a senha MD5 da sessão — o valor fica apenas no Vault."""
    with get_session() as session:
        try:
            sessao = svc.get_session(session, session_id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        caminho = f"gerenet/bgp-sessions/{sessao.id}/password"
        try:
            settings = get_settings()
            store = VaultSecretStore(settings.vault_url, settings.vault_token)
            store.set_secret(caminho, {"password": password})
        except RuntimeError as exc:
            typer.echo(f"Erro: Vault indisponível: {exc}", err=True)
            raise typer.Exit(1) from exc
        svc.set_password(session, sessao.id, actor="cli", path=caminho)
    typer.echo(f"Senha definida para a sessão BGP {sessao.id} (armazenada no Vault).")
```

Em `src/gerenet/cli/main.py`:

```python
from gerenet.cli import (
    bgp_sessions, circuits, collect, contacts, devices, hostkey, organizations, sites,
    snapshot, vault,
)
...
app.add_typer(circuits.app, name="circuits", help="Circuitos de acesso.")
app.add_typer(bgp_sessions.app, name="bgp-sessions", help="Sessões BGP.")
```

- [ ] **Step 8: Run CLI test to verify it passes**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: PASS (9 testes).

- [ ] **Step 9: Gate + commit**

```bash
uv run ruff check src/gerenet/api/routers/bgp_sessions.py src/gerenet/cli/bgp_sessions.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_bgp_sessions_api.py tests/cli/test_cli_smoke.py
uv run pytest tests/api/test_bgp_sessions_api.py tests/cli/test_cli_smoke.py -v
git add src/gerenet/api/routers/bgp_sessions.py src/gerenet/cli/bgp_sessions.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_bgp_sessions_api.py tests/cli/test_cli_smoke.py
git commit -m "feat(SoT): API e CLI de sessões BGP com password set via Vault"
```

---

### Task 7: Autorizações de prefixo + catálogo de policy-profiles (API e CLI)

**Files:**
- Create: `src/gerenet/api/routers/prefix_authorizations.py`, `src/gerenet/api/routers/policy_profiles.py`, `src/gerenet/cli/prefix_authorizations.py`, `src/gerenet/cli/policy_profiles.py`, `tests/api/test_prefix_authorizations_api.py`, `tests/api/test_policy_profiles_api.py`
- Modify: `src/gerenet/api/main.py`, `src/gerenet/cli/main.py`
- Test: `tests/cli/test_cli_smoke.py` (anexar testes)

**Interfaces:**
- Consumes: `svc.create_authorization(data, *, actor)` (audita `authorization.create`), `list_authorizations(organization_id, family, include_disabled)`, `get_authorization`, `disable_authorization(authorization_id, *, actor)` (`domain/services/prefix_authorizations.py` — ordem por family, prefix); `list_policy_profiles(session, direction, include_disabled)` (`domain/services/policy_profiles.py`); schemas `PrefixAuthorizationCreate/Out/Disable`, `PolicyProfileOut` (T1). Modelo: `BgpPrefixAuthorization` (organization_id, family, prefix, origin `"manual"`, notes, admin_status), `PolicyProfile` (name, label PT-BR, direction, kind, prefixes, notes, admin_status).
- Produces: rotas `/api/v1/prefix-authorizations` GET(list)/POST(201)/GET{id}/PATCH (só desativa — `PrefixAuthorizationDisable`; 422 em qualquer outro corpo via `extra="forbid"` + `Literal[False]`); `/api/v1/policy-profiles` GET list (somente leitura — ruling 9, sem GET por id); CLI `prefix-authorizations add|list|disable` e `policy-profiles list [--direction] [--all]`.

- [ ] **Step 1: Write the failing API tests**

`tests/api/test_prefix_authorizations_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import OrganizationCreate
from gerenet.domain.services.organizations import create_organization


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _orgs(db_session: Session) -> tuple[int, int]:
    a = create_organization(db_session, OrganizationCreate(name="Down A", asn=64521), actor="cli")
    b = create_organization(db_session, OrganizationCreate(name="Down B", asn=64522), actor="cli")
    return a.id, b.id


def test_exige_chave(client: TestClient) -> None:
    assert client.get("/api/v1/prefix-authorizations").status_code == 401
    assert client.post("/api/v1/prefix-authorizations", json={}).status_code == 401
    assert client.get("/api/v1/policy-profiles").status_code == 401


def test_cria_lista_detalha(client: TestClient, db_session: Session) -> None:
    org_a, org_b = _orgs(db_session)
    resp = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "203.0.113.0/24"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    corpo = resp.json()
    assert corpo["origin"] == "manual"
    assert corpo["admin_status"] is True

    # bloco contíguo na MESMA organização: permitido (spec §4)
    vizinho = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "203.0.113.128/25"},
        headers=_auth(),
    )
    assert vizinho.status_code == 201

    # sobreposição com OUTRA organização ativa: 409
    outro = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_b, "family": "ipv4", "prefix": "203.0.113.0/25"},
        headers=_auth(),
    )
    assert outro.status_code == 409
    assert "sobrepõe" in outro.json()["detail"]

    # CIDR da família errada: 400 (mensagens PT do serviço)
    errado = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "2001:db8::/32"},
        headers=_auth(),
    )
    assert errado.status_code == 400

    lista = client.get("/api/v1/prefix-authorizations", headers=_auth()).json()
    assert len(lista) == 2
    assert lista[0]["prefix"] == "203.0.113.0/24"  # order by family, prefix

    assert client.get("/api/v1/prefix-authorizations?family=ipv6", headers=_auth()).json() == []
    det = client.get(f"/api/v1/prefix-authorizations/{corpo['id']}", headers=_auth())
    assert det.status_code == 200 and det.json()["prefix"] == "203.0.113.0/24"
    assert client.get("/api/v1/prefix-authorizations/9999", headers=_auth()).status_code == 404


def test_patch_so_desativa(client: TestClient, db_session: Session) -> None:
    org_a, _ = _orgs(db_session)
    auth = client.post(
        "/api/v1/prefix-authorizations",
        json={"organization_id": org_a, "family": "ipv4", "prefix": "198.51.100.0/24"},
        headers=_auth(),
    ).json()

    off = client.patch(
        f"/api/v1/prefix-authorizations/{auth['id']}",
        json={"admin_status": False},
        headers=_auth(),
    )
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    ativos = client.get("/api/v1/prefix-authorizations", headers=_auth()).json()
    assert ativos == []
    com_desativadas = client.get(
        "/api/v1/prefix-authorizations?include_disabled=true", headers=_auth()
    ).json()
    assert [p["prefix"] for p in com_desativadas] == ["198.51.100.0/24"]

    # reativar ou mudar conteúdo não existe: 422 (schema Literal[False] + extra forbid)
    reativar = client.patch(
        f"/api/v1/prefix-authorizations/{auth['id']}",
        json={"admin_status": True},
        headers=_auth(),
    )
    assert reativar.status_code == 422
    mudar = client.patch(
        f"/api/v1/prefix-authorizations/{auth['id']}",
        json={"prefix": "198.51.100.0/25"},
        headers=_auth(),
    )
    assert mudar.status_code == 422

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent))
        if e.type.startswith("authorization")
    ]
    assert tipos == ["authorization.create", "authorization.disable"]
```

`tests/api/test_policy_profiles_api.py` (mesmo fixture `client`/`_auth` do padrão):

```python
import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_lista_catalogo_so_leitura(client: TestClient) -> None:
    lista = client.get("/api/v1/policy-profiles", headers=_auth()).json()
    assert len(lista) == 6  # seeds de exportação do §25.5
    assert all(p["direction"] == "export" for p in lista)
    assert [p["name"] for p in lista] == sorted(p["name"] for p in lista)
    assert any(p["label"] for p in lista)  # label PT-BR presente

    assert client.get(
        "/api/v1/policy-profiles?direction=export", headers=_auth()
    ).json() == lista
    assert client.get("/api/v1/policy-profiles?direction=import", headers=_auth()).json() == []
    assert client.post("/api/v1/policy-profiles", json={}, headers=_auth()).status_code == 405
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_prefix_authorizations_api.py tests/api/test_policy_profiles_api.py -v`
Expected: FAIL — rotas inexistentes.

- [ ] **Step 3: Write minimal implementation (routers + wiring)**

`src/gerenet/api/routers/prefix_authorizations.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import (
    PrefixAuthorizationCreate,
    PrefixAuthorizationDisable,
    PrefixAuthorizationOut,
)
from gerenet.domain.services import prefix_authorizations as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/prefix-authorizations",
    tags=["prefix-authorizations"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[PrefixAuthorizationOut])
def listar(
    session: SessionDep,
    organization_id: int | None = None,
    family: str | None = None,
    include_disabled: bool = False,
) -> list:
    return svc.list_authorizations(
        session,
        organization_id=organization_id,
        family=family,
        include_disabled=include_disabled,
    )


@router.post("", response_model=PrefixAuthorizationOut, status_code=201)
def criar(data: PrefixAuthorizationCreate, session: SessionDep) -> object:
    try:
        return svc.create_authorization(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{authorization_id}", response_model=PrefixAuthorizationOut)
def detalhar(authorization_id: int, session: SessionDep) -> object:
    try:
        return svc.get_authorization(session, authorization_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{authorization_id}", response_model=PrefixAuthorizationOut)
def desativar(
    authorization_id: int, data: PrefixAuthorizationDisable, session: SessionDep
) -> object:
    """Único PATCH possível: desativar. Mudar prefixo = desativar + criar (ruling 2)."""
    try:
        return svc.disable_authorization(session, authorization_id, actor="api")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

`src/gerenet/api/routers/policy_profiles.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import PolicyProfileOut
from gerenet.domain.services import policy_profiles as svc

router = APIRouter(
    prefix="/api/v1/policy-profiles",
    tags=["policy-profiles"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[PolicyProfileOut])
def listar(
    session: SessionDep, direction: str | None = None, include_disabled: bool = False
) -> list:
    """Catálogo de produtos de roteamento — somente leitura (§6.5/§25.5)."""
    return svc.list_policy_profiles(
        session, direction=direction, include_disabled=include_disabled
    )
```

Em `src/gerenet/api/main.py`:

```python
from gerenet.api.routers import (
    bgp_sessions, circuits, contacts, devices, organizations, policy_profiles,
    prefix_authorizations, sites,
)
...
    app.include_router(policy_profiles.router)
    app.include_router(prefix_authorizations.router)
```

- [ ] **Step 4: Run API test to verify it passes**

Run: `uv run pytest tests/api/test_prefix_authorizations_api.py tests/api/test_policy_profiles_api.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Write the failing CLI smoke tests (anexar a `tests/cli/test_cli_smoke.py`)**

```python
def test_cli_autorizacoes_ciclo_de_vida(db_session: Session) -> None:
    org = create_organization(
        db_session, OrganizationCreate(name="Down CLI A", asn=64523), actor="cli"
    )
    add = runner.invoke(
        app,
        [
            "prefix-authorizations", "add",
            "--organization-id", str(org.id), "--family", "ipv4",
            "--prefix", "203.0.113.0/24",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "criada" in add.output

    lista = runner.invoke(app, ["prefix-authorizations", "list"])
    assert lista.exit_code == 0
    assert "203.0.113.0/24" in lista.output

    off = runner.invoke(app, ["prefix-authorizations", "disable", "1"])
    assert off.exit_code == 0
    assert "203.0.113.0/24" not in runner.invoke(app, ["prefix-authorizations", "list"]).output
    assert (
        "203.0.113.0/24"
        in runner.invoke(app, ["prefix-authorizations", "list", "--all"]).output
    )


def test_cli_policy_profiles_lista(db_session: Session) -> None:
    lista = runner.invoke(app, ["policy-profiles", "list"])
    assert lista.exit_code == 0
    assert len(lista.output.strip().splitlines()) == 6  # seeds de exportação

    so_export = runner.invoke(app, ["policy-profiles", "list", "--direction", "export"])
    assert so_export.exit_code == 0
    assert so_export.output == lista.output

    so_import = runner.invoke(app, ["policy-profiles", "list", "--direction", "import"])
    assert so_import.exit_code == 0
    assert so_import.output.strip() == ""
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: FAIL — comandos `prefix-authorizations`/`policy-profiles` inexistentes.

- [ ] **Step 7: Write minimal implementation (CLI + wiring)**

`src/gerenet/cli/prefix_authorizations.py` (catch duplo `(GerenetError, SchemaValidationError)` — `family` é Literal validada pelo pydantic):

```python
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import PrefixAuthorizationCreate
from gerenet.domain.services import prefix_authorizations as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Prefixos autorizados por organização (origem manual).")


@app.command("add")
def add(
    organization_id: int = typer.Option(..., "--organization-id", help="ID da organização."),
    family: str = typer.Option(..., help="ipv4 ou ipv6."),
    prefix: str = typer.Option(..., help="CIDR alinhado (ex.: 203.0.113.0/24)."),
    notes: str | None = typer.Option(None, help="Observações."),
) -> None:
    """Autoriza um prefixo para um downstream."""
    with get_session() as session:
        try:
            auth = svc.create_authorization(
                session,
                PrefixAuthorizationCreate(
                    organization_id=organization_id, family=family, prefix=prefix, notes=notes
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Autorização {auth.id} criada: {auth.family} {auth.prefix}")


@app.command("list")
def listar(
    organization_id: int | None = typer.Option(None, "--organization-id", help="Filtra por organização."),
    family: str | None = typer.Option(None, help="Filtra por família (ipv4/ipv6)."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista autorizações de prefixo."""
    with get_session() as session:
        for auth in svc.list_authorizations(
            session,
            organization_id=organization_id,
            family=family,
            include_disabled=include_disabled,
        ):
            typer.echo(f"{auth.id:>4}  {auth.family:<4} {auth.prefix:<20} org {auth.organization_id}")


@app.command("disable")
def disable(authorization_id: int = typer.Argument(..., help="ID da autorização.")) -> None:
    """Desativa uma autorização (sem excluir). Mudar prefixo = desativar + criar."""
    with get_session() as session:
        try:
            svc.disable_authorization(session, authorization_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Autorização de prefixo {authorization_id} desativada.")
```

`src/gerenet/cli/policy_profiles.py`:

```python
import typer

from gerenet.db import get_session
from gerenet.domain.services import policy_profiles as svc

app = typer.Typer(help="Produtos de roteamento (catálogo somente leitura).")


@app.command("list")
def listar(
    direction: str | None = typer.Option(None, "--direction", help="Filtra por direção (export)."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista o catálogo de policy-profiles."""
    with get_session() as session:
        for perfil in svc.list_policy_profiles(
            session, direction=direction, include_disabled=include_disabled
        ):
            typer.echo(f"{perfil.id:>3}  {perfil.name:<16} {perfil.direction:<7} {perfil.label}")
```

Em `src/gerenet/cli/main.py`:

```python
from gerenet.cli import (
    bgp_sessions, circuits, collect, contacts, devices, hostkey, organizations,
    policy_profiles, prefix_authorizations, sites, snapshot, vault,
)
...
app.add_typer(prefix_authorizations.app, name="prefix-authorizations", help="Autorizações de prefixo.")
app.add_typer(policy_profiles.app, name="policy-profiles", help="Produtos de roteamento.")
```

- [ ] **Step 8: Run CLI test to verify it passes**

Run: `uv run pytest tests/cli/test_cli_smoke.py -v`
Expected: PASS (11 testes).

- [ ] **Step 9: Gate + commit**

```bash
uv run ruff check src/gerenet/api/routers/prefix_authorizations.py src/gerenet/api/routers/policy_profiles.py src/gerenet/cli/prefix_authorizations.py src/gerenet/cli/policy_profiles.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_prefix_authorizations_api.py tests/api/test_policy_profiles_api.py tests/cli/test_cli_smoke.py
uv run pytest tests/api/test_prefix_authorizations_api.py tests/api/test_policy_profiles_api.py tests/cli/test_cli_smoke.py -v
git add src/gerenet/api/routers/prefix_authorizations.py src/gerenet/api/routers/policy_profiles.py src/gerenet/cli/prefix_authorizations.py src/gerenet/cli/policy_profiles.py src/gerenet/api/main.py src/gerenet/cli/main.py tests/api/test_prefix_authorizations_api.py tests/api/test_policy_profiles_api.py tests/cli/test_cli_smoke.py
git commit -m "feat(SoT): API/CLI de autorizações de prefixo e catálogo de policy-profiles"
```

---

### Task 8: Auditoria — router GET /audit-events (trilha imutável)

**Files:**
- Create: `src/gerenet/api/routers/audit_events.py`, `tests/api/test_audit_events_api.py`
- Modify: `src/gerenet/api/main.py`

**Interfaces:**
- Consumes: `models.AuditEvent` (colunas `type` String(64), `actor` String(64), `details` JSON com chaves `objeto`/`objeto_id`/`antes`/`depois`, `created_at`); `AuditEventOut` (T1: id, type, actor, details: dict, created_at).
- Produces: rota `GET /api/v1/audit-events` (somente leitura — ruling 9): query params `tipo` (coluna `type`), `objeto`/`objeto_id` (filtros dentro de `details`, via `astext`), `limit` default 100 com `ge=1, le=1000`; resposta ordenada por `id desc`. Sem CLI (trilha só pela API; CLI de auditoria fica para o fluxo de change no ciclo B). Nenhuma outra rota (POST/PATCH/DELETE inexistentes — aberto no `openapi`, sem serviço novo: query direta no modelo, caminho read-only).

- [ ] **Step 1: Write the failing API test**

`tests/api/test_audit_events_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.schemas import (
    ContactCreate,
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.contacts import create_contact
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _popula_trilha(db_session: Session) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-audit"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Down Audit", asn=64531), actor="cli"
    )
    dev = create_device(
        db_session, DeviceCreate(name="ne-audit", management_address="10.8.3.1"), actor="cli"
    )
    create_contact(
        db_session,
        ContactCreate(organization_id=org.id, name="Ana", kind="noc"),
        actor="cli",
    )
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org.id, family="ipv4", prefix="203.0.113.0/24"
        ),
        actor="cli",
    )
    # device.disable registra "antes" do admin_status para o teste de limit/ordem
    from gerenet.domain.services.devices import disable_device

    disable_device(db_session, dev.id, actor="cli")
    return {"site_id": site.id, "org_id": org.id, "device_id": dev.id, "auth_id": auth.id}


def test_exige_chave_e_somente_get(client: TestClient) -> None:
    assert client.get("/api/v1/audit-events").status_code == 401
    rotas = create_app().openapi()["paths"]["/api/v1/audit-events"]
    assert set(rotas) == {"get"}  # trilha imutável: sem post/patch/delete
    for verbo in ("post", "patch", "delete"):
        assert client.request(verbo, "/api/v1/audit-events", headers=_auth()).status_code == 405


def test_lista_ordem_desc_e_filtros(client: TestClient, db_session: Session) -> None:
    refs = _popula_trilha(db_session)
    lista = client.get("/api/v1/audit-events", headers=_auth()).json()
    assert len(lista) == 6
    ids = [e["id"] for e in lista]
    assert ids == sorted(ids, reverse=True)
    tipos = [e["type"] for e in lista]
    assert tipos == [
        "device.disable", "authorization.create", "contact.create", "device.create",
        "organization.create", "site.create",
    ]
    primeiro = lista[0]
    assert set(primeiro) == {"id", "type", "actor", "details", "created_at"}
    assert primeiro["actor"] == "cli"
    assert primeiro["details"]["objeto"] == "device"
    assert primeiro["details"]["depois"]["admin_status"] is False
    assert primeiro["details"]["antes"]["admin_status"] is True

    so_site = client.get("/api/v1/audit-events?tipo=site.create", headers=_auth()).json()
    assert [e["type"] for e in so_site] == ["site.create"]
    assert so_site[0]["details"]["objeto_id"] == refs["site_id"]

    so_device = client.get("/api/v1/audit-events?objeto=device", headers=_auth()).json()
    assert [e["type"] for e in so_device] == ["device.disable", "device.create"]

    so_auth = client.get(
        f"/api/v1/audit-events?objeto=authorization&objeto_id={refs['auth_id']}",
        headers=_auth(),
    ).json()
    assert [e["type"] for e in so_auth] == ["authorization.create"]

    assert client.get(f"/api/v1/audit-events?objeto_id={refs['org_id']}", headers=_auth()).json() == []


def test_limit_clamp(client: TestClient, db_session: Session) -> None:
    _popula_trilha(db_session)
    dois = client.get("/api/v1/audit-events?limit=2", headers=_auth()).json()
    assert len(dois) == 2
    for fora in ("0", "1001"):
        assert client.get(f"/api/v1/audit-events?limit={fora}", headers=_auth()).status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_audit_events_api.py -v`
Expected: FAIL — rota inexistente (e 404/405 fora do esperado).

- [ ] **Step 3: Write minimal implementation (router + wiring)**

`src/gerenet/api/routers/audit_events.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, cast, select
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.schemas import AuditEventOut

router = APIRouter(
    prefix="/api/v1/audit-events",
    tags=["audit-events"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[AuditEventOut])
def listar(
    session: SessionDep,
    tipo: str | None = None,
    objeto: str | None = None,
    objeto_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list:
    """Trilha de auditoria (§18) — somente leitura, mais recentes primeiro."""
    stmt = select(models.AuditEvent).order_by(models.AuditEvent.id.desc()).limit(limit)
    if tipo is not None:
        stmt = stmt.where(models.AuditEvent.type == tipo)
    if objeto is not None:
        stmt = stmt.where(models.AuditEvent.details["objeto"].astext == objeto)
    if objeto_id is not None:
        stmt = stmt.where(cast(models.AuditEvent.details["objeto_id"].astext, Integer) == objeto_id)
    return list(session.scalars(stmt))
```

Nota: `details` é coluna JSON; o acesso `details["objeto"].astext` renderiza `details ->> 'objeto'` (texto) e o `cast(..., type(objeto_id))` converte para inteiro antes de comparar — padrão que roda no PostgreSQL do compose (o mesmo teste roda no CI/test DB real).

Em `src/gerenet/api/main.py`:

```python
from gerenet.api.routers import (
    audit_events, bgp_sessions, circuits, contacts, devices, organizations,
    policy_profiles, prefix_authorizations, sites,
)
...
    app.include_router(audit_events.router)
```

- [ ] **Step 4: Run API test to verify it passes**

Run: `uv run pytest tests/api/test_audit_events_api.py -v`
Expected: PASS (3 testes). Se o `astext`/cast do passo 3 variar de sintaxe no SQLAlchemy instalado, ajuste para `sqlalchemy.text()` com bind params — o contrato (filtros, ordem, clamp) não muda.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src/gerenet/api/routers/audit_events.py src/gerenet/api/main.py tests/api/test_audit_events_api.py
uv run pytest tests/api/test_audit_events_api.py -v
git add src/gerenet/api/routers/audit_events.py src/gerenet/api/main.py tests/api/test_audit_events_api.py
git commit -m "feat(SoT): API de auditoria GET /audit-events (trilha imutável, filtros e limite)"
```

---

### Task 9: Verificação final do ciclo (sem alteração de código)

Rodar como lote único — se algo falhar aqui, corrigir **antes** do fechamento e re-rodar.

- [ ] **Step 1: Suíte completa**

```bash
GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q
```

Expected: PASS (suíte inteira — domain, API, CLI smoke, automation, secrets).

- [ ] **Step 2: Ruff em todo o código**

```bash
uv run ruff check src tests
```

Expected: sem erros (line length 100; NÃO rodar `ruff format` — o repo não usa).

- [ ] **Step 3: Migração e árvore limpas**

```bash
uv run alembic current
git status --short
```

Expected: `b1a71e5e129b` (sem migração nova no P3 — só schema) e árvore limpa após o commit da Task 8.

- [ ] **Step 4: Fechamento do ciclo**

- Conferir que nenhum segredo entrou em código/auditoria (grep rápido por `md5-` nos `git show` dos commits do plano e nos arquivos `src/`, deve aparecer apenas em testes e nas fixtures de teste).
- `graphify update .` para manter o grafo do repo atualizado (o hook do SessionStart cobra isso após mudanças).
- Atualizar `.superpowers/sdd/2026-09-03-gerenet-ciclo-a-plano-3-api-cli/progress.md` com o resultado final (todos os checkboxes, data/hora, saída do `pytest -q`).
- Reportar o fechamento com a contagem total de testes e a lista de commits do ciclo.

Não há commit nesta task — o estado final já foi commitado nas tasks anteriores.

---

## Verificação de cobertura da spec §9 (checklist do plano)

| Spec §9 pede | Onde |
|---|---|
| API REST `/api/v1/...` para os objetos do P1/P2 | Tasks 2–8 (rotas list/criar/detalhar/atualizar/desativar por objeto) |
| CLI paritária (`add`/`list`/`disable`; + `password set`, `link-device`, `reserve`) | Tasks 2–7 |
| Segredos fora do banco/auditoria/log (Vault genérico, `has_password`, path por session_id) | Task 1 (schema), Tasks 5–6 |
| `policy-profiles` somente leitura | Task 7 |
| Auditoria imutável, só leitura, filtros | Task 8 |
| Erros mapeados 400/404/409 (nunca 500 em conflito de negócio) | Todas as rotas |
| Comunities e associação sessão↔community **fora** do P3 | decisão do usuário — ciclo B |
| Sem migração nova; schemas Out sem timestamps (padrão F1 `DeviceOut`) | T1 + Global Constraints |

## Regras executadas neste plano (resumo para o executor)

- Cada PATCH segue o padrão: `admin_status: false` puro → `disable_*`; caso contrário → `update_*`; `admin_status: null` explícito → 400 "admin_status não aceita null." (ruling 1). Exceção: `PrefixAuthorizationDisable` (só `{"admin_status": false}`, 422 no resto — ruling 2).
- Erros de negócio: `ConflictError`→409, `NotFoundError`→404, `ValidationError`→400; autenticação por `X-API-Key` (401).
- CLI com campos Literal (kind, afi, family, stack): sempre `except (GerenetError, SchemaValidationError)`.
- Auditoria nunca carrega valor de senha; `password_ref` (path Vault) jamais aparece nos Out schemas.
- Vault indisponível: API 503 "Vault indisponível: ...", CLI exit 1 (o store lança `RuntimeError` — Task 5).
- Testes de API usam o Vault real do compose (padrão `tests/test_secrets.py`); testes truncam o banco real de teste a cada teste (conftest existente — não tocar).
