# Ciclo B2 — Render da intenção + divergência (gerenet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o ciclo B2 do gerenet: derivador de nomes VRP §25.4, templates Jinja2 + orquestrador `render_desejado`, divergência `reconciliar_device` (desejado × encontrado, read-only), coluna `circuits.edge_trunk`, seed de importação `somente-autorizadas` e exposição API/CLI (communities, associações, reconciliation, desired-config, render-config).

**Architecture:** Render é orquestrador que decide QUAIS blocos (com quais nomes §25.4) e delega o texto a templates Jinja2 atômicos em `automation/templates/huawei_vrp/`; senha nunca é emitida — só o comentário com `password_ref`. Divergência é serviço on-demand sem tabela nova: renderiza o desejado do device e compara com o snapshot mais recente (`device_snapshots.resources`), devolvendo itens tipados `{tipo, severidade, esperado, encontrado, acao}` em PT-BR. Migration única (schema `edge_trunk` + seed de importação no padrão dos seeds do ciclo A). API/CLI seguem o padrão P3.

**Tech Stack:** Python 3, SQLAlchemy 2, Alembic, **Jinja2 ≥ 3.1 (nova dependência via `uv add jinja2`)**, FastAPI, Typer, pytest, ruff.

**Spec:** [docs/superpowers/specs/2026-09-03-gerenet-ciclo-b-render-divergencia-design.md](../specs/2026-09-03-gerenet-ciclo-b-render-divergencia-design.md) — autoridade vinculante; o plano argumenta a partir dela e registra rulings próprios. Complementam: ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md §6.3–6.5/§8/§10/§14/§25.4/§25.5/§25.8/§25.18 e a spec do ciclo B1 (shapes dos resources).

## Global Constraints

Toda task herda esta seção:

- **Idioma**: mensagens de erro/CLI/API/help em PT-BR (padrão do repo: `ipam.py`, `runner.py`); identificadores de código em EN, exceto nomes literalmente fixados pela spec (`reconciliar_device`) e o padrão PT dos serviços (`reservar_circuito`). Mensagens de commit em PT-BR no padrão do repo (`feat(SoT): …`).
- **Segredos**: senha nunca em banco/logs/templates/snapshot/auditoria/render — banco guarda só `password_ref` (path `gerenet/bgp-sessions/<id>/password`); `has_password` é propriedade derivada; o render emite, quando `password_ref` existe, **apenas** o comentário `# password no Vault (<password_ref>)`; API nunca expõe `password_ref`/`password`. Captura bruta do NE8000 fica fora do git (`data/`, ignorado); fixtures são sanitizadas.
- **Nomes VRP** (§25.4/§8): ≤ 63 chars, maiúsculas, separador `-`, base = ASN do par em decimal **sem padding**: `RP-<ASN>-IMPORT-<AFI>`, `RP-<ASN>-EXPORT-<AFI>`, `IP-PFX-<ASN>-IN-<AFI>`. Prefixo de lista por produto (não derivado do ASN): `IP-PFX-DEFAULT-<AFI>`, `IP-PFX-<NOME-PERFIL-UPPER>-<AFI>`. `description` do peer só quando a sessão tem o campo próprio preenchido.
- **Render idempotente por construção** (deriva sempre do SoT; duas chamadas = mesmo texto). Route-policy **clássico**; XPL é só capacidade (fora do B).
- **Divergência read-only**: sem tabela nova, sem efeitos no equipamento; snapshot ausente ⇒ `snapshot_id=None` + campo `aviso`, sem erro. O **conteúdo interno** de route-policies/prefix-lists não é comparado (corte 3) — só presença/estado/asn/filtros-aplicados/pontas/subinterface.
- **Tipos de item e severidades** (spec §6): `peer.ausente` crítica · `peer.shutdown_admin` atenção · `peer.estado` atenção · `peer.asn` crítica · `peer.filtros` crítica · `peer.orfaos` atenção · `subinterface.ausente` crítica · `subinterface.estado` atenção · `circuito.sem_trunk` aviso · `ponta.v4`/`ponta.v6` crítica. Cada item `{tipo, severidade, esperado, encontrado, acao}`.
- **Shapes de snapshot (contrato B1)**: `resources` chaves `version`, `config_backup`, `interfaces` (lista `{nome, phy, protocolo, enderecos_v4[], enderecos_v6[], vpn}`), `bgp_peers` (lista `{afi, peer, asn, estado, pref_rcv, up_down}`), `bgp_peers_verbose` (lista `{afi, peer, descricao, filtro_import, filtro_export}`); endereços **com** `/len` (ex.: `100.64.0.0/31`). O nome `bgp_peers_detalhes` é só o merge interno — o recurso em `resources` chama-se `bgp_peers_verbose`.
- **Catálogos read-only**: `bgp_policy_profiles` e `communities` são seedados e fora do TRUNCATE do conftest; `list_policy_profiles(direction=None)` lista **ambas** as direções ordenado por name — o seed de importação altera listagens default (quebra 3 arquivos de teste; a T2 corrige).
- **Reserva IPAM (determinística em teste)**: site sem override usa `Settings` (`p2p_ipv4_block="100.64.0.0/10"`, `p2p_ipv6_base="2804:194C:1000::/48"`); 1ª reserva no site ⇒ v4 `100.64.0.0/31` (pontas locais `100.64.0.0`/remota `.1`, máscara `255.255.255.254`) e v6 `2804:194C:1000::6400:0/126` (pontas `…6400:1`/`…6400:2`, caixa `194C` preservada); VID livre ≥ 2 ⇒ `2`; `Vlan.family` `None` (unica) ou `ipv4`/`ipv6` (separada, sempre 2 linhas); `IpPrefix.kind="p2p"` com o CIDR da rede; **`circuits.p2p_v4_len` é coluna do modelo** (`Integer`, default 31 — L226; o IPAM a usa ao reservar em `ipam.py:182`) — o `/len` da ponta deriva do CIDR reservado (via `ipaddress`); `CircuitCreate`/`CircuitUpdate` expõem `Literal[30,31]` / `Literal[30,31] | None`.
- **API**: padrão P3 — `SessionDep = Annotated[Session, Depends(get_db)]`, `dependencies=[Depends(require_api_key)]`, try/except `NotFoundError→404`, `ConflictError→409`, `ValidationError→400`; fixtures de teste de API por arquivo (`client` + `_auth()` locais).
- **CLI**: Typer, `with get_session() as session`, `except (GerenetError, SchemaValidationError)` → `typer.echo(f"Erro: {exc}", err=True)` + `Exit(1)`; registros de apps no `cli/main.py`; help PT-BR.
- **Testes**: `uv run pytest -q` ao fim de cada task; `uv run ruff check` no fim (suíte verde + lint). Nunca rodar contra banco dev — só `gerenet_test` (conftest aborta caso contrário).
- **Commits**: trailer `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

## Rulings (conflitos/ambiguidades resolvidos — a spec é a autoridade)

1. **Módulos**: `src/gerenet/automation/naming.py` (funções puras de nomes), `automation/render.py` (orquestrador + `BlocoRender`/`RenderResult`), `automation/reconcile.py` (`reconciliar_device` + itens), templates em `automation/templates/huawei_vrp/`. O render muda a **intenção em texto VRP** e consome shapes de snapshot — casa com `automation/` (ao lado de `parsers/`, `collectors.py`, `runner.py`); não é CRUD do SoT, logo não pertence a `domain/services/`.
2. **Blocos**: `BlocoRender{tipo, objeto, objeto_id, comandos}` com `.texto = "\n".join(comandos)`; `RenderResult{device_id, blocos, texto}` com `.texto = "\n".join(b.texto…)`. Ordem de aplicação (spec §5.2): `subinterface` 10 → `prefix_list` 20 → `route_policy_import` 30 → `route_policy_export` 40 → `bgp_peer` 50 → `comentario` 60; `TIPO_ORDEM` aplicado com sort estável ao final.
3. **Escopo do render**: device → sessões com `admin_status=True` (inclui `shutdown=True`: o bloco emite `peer … shutdown`); subinterface por circuito dessas sessões **só quando** `circuit.edge_trunk` está preenchido **e** o device é `edge_device_id` ou `backup_edge_device_id` do circuito **e** há reserva (linhas `Vlan`). Circuito reservado com sessão ativa e **sem** `edge_trunk` não gera subinterface — a divergência acusa `circuito.sem_trunk`. Stack `ipv6`: o par v4 interno de derivação **não** vira endereço de interface.
4. **Importação** (spec §6.4): route-policy de importação é derivada das **autorizações ativas da organização do circuito**, independente do `import_profile_id` (o seed `somente-autorizadas` só destrava o campo). Com `allow_default_route=True` a prefix-list de entrada ganha `index 5 permit 0.0.0.0/0` (v4) / `::/0` (v6) **antes** das autorizações (índices 10, 20, …). Sem autorizações da família ⇒ sem bloco nenhum de importação (e a divergência não compara filtro de importação dessa sessão).
5. **Exportação por produto** (§6.5/§25.5; nada preexistente — goldens travam): `full` → RP `permit node 10` sem `if-match` (+ `apply med`/`as-path` da sessão); `default` → RP `if-match` contra `IP-PFX-DEFAULT-<AFI>` (entrada única `0.0.0.0/0` v4 / `::/0` v6 — bloco **deduplicado por device**); `cdn`/`personalizado` → `IP-PFX-<NOME-PERFIL-UPPER>-<AFI>` com `perfil.prefixes` (sem prefixes ⇒ bloco `comentario` de dívida); `default_internas`/`parcial` → bloco `comentario` de dívida (sem RP). Sessão sem `export_profile_id` ⇒ sem exportação. `local_preference` da sessão vira `apply local-preference` no RP de importação; `med`/`prepend` da sessão vão para o RP de exportação (`prepend` repete o **`asn_local` da sessão**, resolvido pelo serviço = `device.asn` quando não informado).
6. **QinQ**: subinterface com `circuito.qinq` emite `vlan-type dot1q 0x88a8 vid <vid>` (s_vlan). O `second-dot1q` (encapsulamento interno duplo) depende de captura QinQ real e fica como dívida do ciclo C — nota comentada no template.
7. **Divergência — o que comparar**: presença do peer por (afi, remote) para toda sessão ativa; `asn`; `estado` (sessão `shutdown=false` espera `Established`; `shutdown=true` espera **não** Established ⇒ `peer.shutdown_admin`); filtros in/out **só quando** o render emitiu o respectivo bloco para a sessão **e** há linha verbose do peer; órfãos = peer no snapshot sem sessão ativa (afi, remote); subinterface esperada **derivada dos blocos renderizados** (parse das linhas `interface X` / `ip address A M` / `ipv6 enable` / `ipv6 address X`); pontas esperadas = as linhas renderizadas (v4 `A/<len de M>`; v6 como renderizada, `/126`). Recurso ausente do snapshot (`interfaces`/`bgp_peers`/`bgp_peers_verbose` sem chave) ⇒ aviso único por recurso e **pula-se** aquele grupo — nunca comparar contra lista vazia implícita.
8. **`snapshot_id` explícito**: snapshot inexistente → `NotFoundError`; snapshot de outro device com `device_id` informado → `ValidationError`; `device_id=None` + snapshot ⇒ device derivado do snapshot; sem `snapshot_id` ⇒ snapshot mais recente do device (`ORDER BY id DESC`).
9. **API**: `GET /api/v1/reconciliation` exige **exatamente um** de `device_id`/`snapshot_id` (nenhum/ambos ⇒ 400). `GET /api/v1/devices/{device_id}/desired-config` → 200 sempre que o device existe (blocos vazios ok); 404 device inexistente. `GET /api/v1/communities` read-only (padrão policy-profiles; listagem default inclui as desativadas? **não** — default = ativas; `include_disabled` via query). Associação: `POST /api/v1/bgp-sessions/{id}/communities` `{community_id}` → **200** `{session_id, community_id}` (idempotente); `DELETE …/communities/{community_id}` → **204** (idempotente); sessão/community inexistentes ⇒ 404. `BgpSessionOut` **não** ganha campo novo (evita quebrar contratos existentes).
10. **CLI**: `gerenet communities list` (novo app); `gerenet bgp-sessions community add|remove <session_id> <community>` (comunidade por id **ou** nome); `gerenet render-config <device>` e `gerenet reconcile <device>` (device por id|nome) como **comandos top-level** registrados com `app.command(name=…)(fn)` no `cli/main.py`. Circuitos: o comando CLI `add` ganha `--edge-trunk` (não existe comando CLI de update; update é via API PATCH).
11. **Seed**: migration única com `op.add_column('circuits', sa.Column('edge_trunk', sa.String(length=64), nullable=True))` + `insert into bgp_policy_profiles (name, label, direction, kind, admin_status) values ('somente-autorizadas', 'Somente rotas autorizadas', 'import', 'produto', true) on conflict do nothing` (padrão `b1a71e5e129b`). `down_revision = 'b1a71e5e129b'` (head). Downgrade: drop column + delete do seed.
12. **Testes existentes quebrados pelo seed** (listagem default passa a ter 7 perfis): `tests/domain/test_policy_profiles_service.py`, `tests/api/test_policy_profiles_api.py::test_lista_catalogo_so_leitura`, `tests/cli/test_cli_smoke.py::test_cli_policy_profiles_lista` — corrigidos na T2 com código exato dado. **E** `tests/domain/test_bgp_models.py::test_seeds_dos_catalogos_presentes` (4º arquivo; conjunto exato de 6 nomes + `all(d == "export")`) — corrigido na T2: set passa a incluir `somente-autorizadas` e a asserção de direções vira `set(...) == {"export", "import"}` (contrato de presença exata preservado).
13. **`comentario` (dívida)**: linhas `# <texto>`; texto PT-BR citando produto/motivo (ex.: `# produto 'default_internas': rotas internas ainda não renderizáveis (ciclo C/F5)`); `objeto="session"`, `objeto_id=0`.

## File Structure

| Arquivo | Situação | Responsabilidade |
|---|---|---|
| `src/gerenet/automation/naming.py` | **Criar (T1)** | Funções puras de nomes §25.4 |
| `tests/automation/test_naming.py` | **Criar (T1)** | Goldens por função |
| `src/gerenet/domain/models.py` | **Modificar (T2)** | `Circuit.edge_trunk` após `notes` (L228) |
| `src/gerenet/domain/schemas.py` | **Modificar (T2/T6)** | `edge_trunk` em `CircuitCreate/Update/Out` (após `notes`); T6: `BgpSessionCommunityIn`, `CommunityOut`, `BlocoOut`, `DesiredConfigOut`, `ReconcileItemOut`, `ReconcileOut` |
| `src/gerenet/domain/services/circuits.py` | **Modificar (T2)** | conferir que create/update usam `data.model_dump()` (padrão do repo) |
| `src/gerenet/cli/circuits.py` | **Modificar (T2)** | `--edge-trunk` no `add` |
| `alembic/versions/<rev>_edge_trunk_import_seed.py` | **Criar (T2)** | coluna + seed `somente-autorizadas` |
| `tests/domain/test_circuits_service.py` | **Modificar (T2)** | `edge_trunk` no cadastro/update |
| `tests/api/test_circuits_api.py` | **Modificar (T2)** | POST/PATCH com `edge_trunk` |
| `tests/domain/test_policy_profiles_service.py` | **Modificar (T2)** | atualiza catálogo (7 nomes) |
| `tests/api/test_policy_profiles_api.py` | **Modificar (T2)** | idem API |
| `tests/cli/test_cli_smoke.py` | **Modificar (T2/T7)** | `--edge-trunk`, catálogo, comandos novos |
| `tests/domain/test_bgp_sessions_service.py` | **Modificar (T2)** | sessão aceita perfil import seedado |
| `src/gerenet/automation/templates/huawei_vrp/*.j2` | **Criar (T3)** | 5 templates atômicos |
| `src/gerenet/automation/render.py` | **Criar (T3/T4)** | T3: loader; T4: orquestrador |
| `tests/automation/test_templates.py` | **Criar (T3)** | goldens puros por template |
| `tests/automation/test_rendering.py` | **Criar (T4)** | orquestrador end-to-end |
| `src/gerenet/automation/reconcile.py` | **Criar (T5)** | `reconciliar_device` + itens |
| `tests/automation/test_reconcile.py` | **Criar (T5)** | um teste por tipo de item do §6 |
| `src/gerenet/api/routers/communities.py` | **Criar (T6)** | `GET /api/v1/communities` |
| `src/gerenet/api/routers/bgp_sessions.py` | **Modificar (T6)** | POST/DELETE `/…/communities` |
| `src/gerenet/api/routers/reconciliation.py` | **Criar (T6)** | `router` + `config_router` |
| `src/gerenet/api/main.py` | **Modificar (T6)** | include_router |
| `tests/api/test_communities_api.py` | **Criar (T6)** | list + associação |
| `tests/api/test_reconciliation_api.py` | **Criar (T6)** | reconciliation + desired-config |
| `src/gerenet/cli/communities.py` | **Criar (T7)** | `communities list` |
| `src/gerenet/cli/bgp_sessions.py` | **Modificar (T7)** | sub-app `community` add/remove |
| `src/gerenet/cli/reconcile.py` | **Criar (T7)** | `render_config`/`reconcile` (funções Typer) |
| `src/gerenet/cli/main.py` | **Modificar (T7)** | registros dos novos comandos |

---

### Task 1: Derivador de nomes VRP §25.4 (funções puras + goldens)

**Files:**
- Create: `src/gerenet/automation/naming.py`
- Test: `tests/automation/test_naming.py`

**Interfaces:**
- Consumes: só a spec §5.1/§25.4 (nenhuma task anterior).
- Produces: `rp_import(asn: int, afi: str) -> str`, `rp_export(asn, afi)`, `pfx_in(asn, afi)`, `pfx_produto(produto: str, afi: str)`, `subinterface(trunk: str, vid: int) -> str` — consumidos por T4/T5.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/automation/test_naming.py`:

```python
"""Golden do derivador de nomes §25.4/§8 — nomes ≤ 63 chars, maiúsculas, base = ASN do par."""
import pytest

from gerenet.automation.naming import pfx_in, pfx_produto, rp_export, rp_import, subinterface
from gerenet.domain.services.errors import ValidationError


def test_rp_import_export_pfx_por_afi() -> None:
    assert rp_import(64500, "ipv4") == "RP-64500-IMPORT-V4"
    assert rp_import(64500, "ipv6") == "RP-64500-IMPORT-V6"
    assert rp_export(64500, "ipv4") == "RP-64500-EXPORT-V4"
    assert rp_export(64500, "ipv6") == "RP-64500-EXPORT-V6"
    assert pfx_in(64500, "ipv4") == "IP-PFX-64500-IN-V4"
    assert pfx_in(64500, "ipv6") == "IP-PFX-64500-IN-V6"


def test_pfx_produto_e_subinterface() -> None:
    assert pfx_produto("default", "ipv4") == "IP-PFX-DEFAULT-V4"
    assert pfx_produto("cdn", "ipv6") == "IP-PFX-CDN-V6"
    assert subinterface("Eth-Trunk127", 4024) == "Eth-Trunk127.4024"
    assert subinterface("GE0/0/1", 100) == "GE0/0/1.100"


def test_asn_sem_padding_e_limites_de_tamanho() -> None:
    # §25.4: decimal sem padding; 32 bits sem sinal; nenhum nome passa de 63 chars.
    assert rp_import(1, "ipv4") == "RP-1-IMPORT-V4"
    assert rp_import(4294967295, "ipv4") == "RP-4294967295-IMPORT-V4"
    for nome in (
        rp_import(4294967295, "ipv6"),
        rp_export(4294967295, "ipv6"),
        pfx_in(4294967295, "ipv6"),
    ):
        assert len(nome) <= 63


@pytest.mark.parametrize("asn", [0, -1, 4294967296])
def test_asn_invalido_rejeitado(asn: int) -> None:
    with pytest.raises(ValidationError, match="ASN"):
        rp_import(asn, "ipv4")


@pytest.mark.parametrize("afi", ["foo", "ipv3", ""])
def test_afi_invalida_rejeitada(afi: str) -> None:
    with pytest.raises(ValidationError, match="Família inválida"):
        rp_import(64500, afi)
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_naming.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'gerenet.automation.naming'`.

- [ ] **Step 3: Implementação mínima**

Criar `src/gerenet/automation/naming.py`:

```python
"""Derivador de nomes VRP §25.4 (spec ciclo B, §5.1).

Nomes ≤ 63 chars, maiúsculas, separador '-', base = ASN do par em decimal
sem padding. Ex.: rp_import(64500, "ipv4") -> "RP-64500-IMPORT-V4".
Prefix-list por produto (IP-PFX-DEFAULT-V4 etc.) usada em T4/T5.
"""
from gerenet.domain.services.errors import ValidationError

_AFIS = ("ipv4", "ipv6")


def _asn_valido(asn: int) -> str:
    if not 1 <= asn <= 4294967295:
        raise ValidationError(f"ASN inválido para nome VRP: {asn}.")
    return str(asn)


def _afi_valida(afi: str) -> str:
    if afi not in _AFIS:
        raise ValidationError(f"Família inválida: {afi} (esperado ipv4 ou ipv6).")
    return "V4" if afi == "ipv4" else "V6"


def rp_import(asn: int, afi: str) -> str:
    """Route-policy de importação: RP-<ASN>-IMPORT-<AFI>."""
    return f"RP-{_asn_valido(asn)}-IMPORT-{_afi_valida(afi)}"


def rp_export(asn: int, afi: str) -> str:
    """Route-policy de exportação: RP-<ASN>-EXPORT-<AFI>."""
    return f"RP-{_asn_valido(asn)}-EXPORT-{_afi_valida(afi)}"


def pfx_in(asn: int, afi: str) -> str:
    """Prefix-list de entrada (autorizações): IP-PFX-<ASN>-IN-<AFI>."""
    return f"IP-PFX-{_asn_valido(asn)}-IN-{_afi_valida(afi)}"


def pfx_produto(produto: str, afi: str) -> str:
    """Prefix-list de produto de exportação: IP-PFX-<PRODUTO>-<AFI>."""
    base = produto.upper().replace(" ", "-")
    if len(base) > 20:  # folga para o nome completo ficar ≤ 63
        raise ValidationError(f"Produto longo demais para nome VRP: {produto}.")
    return f"IP-PFX-{base}-{_afi_valida(afi)}"


def subinterface(trunk: str, vid: int) -> str:
    """Nome de subinterface dot1q: <trunk>.<vid>."""
    return f"{trunk}.{vid}"
```

- [ ] **Step 4: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_naming.py -v`
Expected: PASS (6 testes).

- [ ] **Step 5: Suíte inteira**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/naming.py tests/automation/test_naming.py
git commit -m "feat(SoT): derivador de nomes VRP do ASN do par (§25.4)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: `circuits.edge_trunk` + seed `somente-autorizadas` (+ correção dos 3 arquivos de catálogo)

**Files:**
- Modify: `src/gerenet/domain/models.py` (inserir após `notes` L228, antes de `admin_status` L229)
- Modify: `src/gerenet/domain/schemas.py` (`CircuitCreate` após `notes`; `CircuitUpdate` idem; `CircuitOut` idem)
- Modify: `src/gerenet/domain/services/circuits.py` (conferir `data.model_dump()`; acrescentar `edge_trunk` se houver lista explícita)
- Modify: `src/gerenet/cli/circuits.py` (option `--edge-trunk` no comando `add`)
- Create: `alembic/versions/<rev>_edge_trunk_import_seed.py` (`alembic revision -m "circuits_edge_trunk_import_seed"`; `down_revision='b1a71e5e129b'`)
- Modify: `tests/domain/test_circuits_service.py`, `tests/api/test_circuits_api.py`, `tests/domain/test_bgp_sessions_service.py`, `tests/domain/test_policy_profiles_service.py`, `tests/api/test_policy_profiles_api.py`, `tests/cli/test_cli_smoke.py`

**Interfaces:**
- Consumes: padrão do seed no `alembic/versions/b1a71e5e129b_bgp_sot.py` (`bind = op.get_bind(); bind.execute(sa.text(...), [dicts])`); helpers `_ambiente(db_session)` (5-tupla `org_id, site_id, sw_id, ne_id, ne8k2_id`) e `_circuito(site_id, org_id, sw_id, ne_id, *, code=..., **extra) -> CircuitCreate` em `tests/domain/test_circuits_service.py`; `_ambiente`/`_corpo` em `tests/api/test_circuits_api.py`; `_ambiente_bgp`/`_circuito_cli` em `tests/cli/test_cli_smoke.py`.
- Produces: coluna `circuits.edge_trunk` (model+schema+migration) e perfil `somente-autorizadas` (id 7, direção import) — consumidos por T4/T5/T6/T7.

- [ ] **Step 1: Teste de serviço que falha**

Adicionar ao fim de `tests/domain/test_circuits_service.py` (imports já presentes: `CircuitUpdate`, `models`, `select`, `Session`):

```python
def test_circuito_edge_trunk_no_cadastro_e_no_update(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    circ = create_circuit(
        db_session, _circuito(site_id, org_id, sw_id, ne_id, code="CIRC-EDGE"),
        actor="cli",
    )
    assert circ.edge_trunk is None
    atual = update_circuit(db_session, circ.id, CircuitUpdate(edge_trunk="Eth-Trunk127"), actor="cli")
    assert atual.edge_trunk == "Eth-Trunk127"

    eventos = [
        e for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        if e.type.startswith("circuit.")
    ]
    assert [e.type for e in eventos] == ["circuit.create", "circuit.update"]
    assert eventos[-1].details["depois"].get("edge_trunk") == "Eth-Trunk127"
```

Run: `uv run pytest tests/domain/test_circuits_service.py::test_circuito_edge_trunk_no_cadastro_e_no_update -v`
Expected: FAIL — `CircuitUpdate` rejeita `edge_trunk` (`extra_forbidden`).

- [ ] **Step 2: Modelo + schemas + migration**

1. `src/gerenet/domain/models.py`, após a linha `notes` (L228), antes de `admin_status` (L229):

```python
    edge_trunk: Mapped[str | None] = mapped_column(String(64))  # trunk do edge com as subinterfaces (§25.18)
```

2. `src/gerenet/domain/schemas.py` — após o campo `notes` em `CircuitCreate`, `CircuitUpdate` e `CircuitOut`:

```python
    edge_trunk: str | None = None
```

(sem validação especial além do tipo; `CircuitOut` idem.)

3. `src/gerenet/domain/services/circuits.py`: **nenhuma alteração** — `create_circuit` faz `models.Circuit(**data.model_dump())` e `update_circuit` usa `model_dump(exclude_unset=True)`; `edge_trunk` entra sozinho no cadastro e no patch (não há validação específica a somar).

4. Gerar e preencher a migration:

```bash
uv run alembic revision -m "circuits_edge_trunk_import_seed"
```

No arquivo gerado:

```python
def upgrade() -> None:
    """circuits.edge_trunk (§25.18) + seed do perfil de importação (spec §3.6)."""
    op.add_column('circuits', sa.Column('edge_trunk', sa.String(length=64), nullable=True))

    # Seed do catálogo de importação: destrava import_profile_id (spec decisão 6).
    # on conflict do nothing torna o upgrade reexecutável (idempotência §3.2).
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "insert into bgp_policy_profiles (name, label, direction, kind, admin_status) "
            "values (:name, :label, 'import', 'produto', true) on conflict do nothing"
        ),
        [{"name": "somente-autorizadas", "label": "Somente rotas autorizadas"}],
    )


def downgrade() -> None:
    """Reversão: remove a coluna e o seed de importação."""
    op.drop_column('circuits', 'edge_trunk')
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "delete from bgp_policy_profiles "
            "where name = 'somente-autorizadas' and direction = 'import'"
        )
    )
```

Validar upgrade/downgrade em `gerenet_test` (se o alembic não resolver a URL sozinho, usar a mesma variável/injeção do conftest apontando para `gerenet_test`):

```bash
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: sem erros; volta ao head com a coluna e o seed presentes.

- [ ] **Step 3: Corrigir os 3 arquivos de teste quebrados pelo seed**

A listagem default (`direction=None`) passa a devolver **7** nomes (order by name: `cdn, default, default_internas, full, parcial, personalizado, somente-autorizadas`); `direction="export"` → 6; `direction="import"` → 1.

1. `tests/domain/test_policy_profiles_service.py` — substituir o teste do catálogo e o de filtro (usar os nomes de função existentes no arquivo; o conteúdo abaixo é o novo):

```python
def test_catalogo_tem_seis_export_e_um_import(db_session: Session) -> None:
    assert [p.name for p in list_policy_profiles(db_session)] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
        "somente-autorizadas",
    ]
    assert [p.name for p in list_policy_profiles(db_session, direction="export")] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]


def test_lista_filtra_direction(db_session: Session) -> None:
    assert [p.name for p in list_policy_profiles(db_session, direction="import")] == [
        "somente-autorizadas",
    ]
    assert [p.name for p in list_policy_profiles(db_session, direction="export")] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]
    assert all(p.direction == "import" for p in list_policy_profiles(db_session, direction="import"))
    assert all(p.label for p in list_policy_profiles(db_session))  # label PT-BR em todos
```

2. `tests/api/test_policy_profiles_api.py` — substituir `test_lista_catalogo_so_leitura`:

```python
def test_lista_catalogo_so_leitura(client: TestClient) -> None:
    lista = client.get("/api/v1/policy-profiles", headers=_auth()).json()
    assert [p["name"] for p in lista] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
        "somente-autorizadas",
    ]
    so_export = client.get("/api/v1/policy-profiles?direction=export", headers=_auth()).json()
    assert len(so_export) == 6 and all(p["direction"] == "export" for p in so_export)
    so_import = client.get("/api/v1/policy-profiles?direction=import", headers=_auth()).json()
    assert [p["name"] for p in so_import] == ["somente-autorizadas"]
    assert client.post("/api/v1/policy-profiles", json={}, headers=_auth()).status_code == 405
```

3. `tests/cli/test_cli_smoke.py` — substituir `test_cli_policy_profiles_lista`:

```python
def test_cli_policy_profiles_lista(db_session: Session) -> None:
    lista = runner.invoke(app, ["policy-profiles", "list"])
    assert lista.exit_code == 0
    linhas = lista.output.strip().splitlines()
    assert len(linhas) == 7  # 6 export + somente-autorizadas (import, ciclo B)
    assert any("somente-autorizadas" in linha for linha in linhas)

    so_export = runner.invoke(app, ["policy-profiles", "list", "--direction", "export"])
    assert so_export.exit_code == 0
    assert len(so_export.output.strip().splitlines()) == 6

    so_import = runner.invoke(app, ["policy-profiles", "list", "--direction", "import"])
    assert so_import.exit_code == 0
    assert "somente-autorizadas" in so_import.output
    assert "cdn" not in so_import.output

    invalida = runner.invoke(app, ["policy-profiles", "list", "--direction", "foo"])
    assert invalida.exit_code == 1
    assert "Erro:" in invalida.output
```

Run: `uv run pytest tests/domain/test_policy_profiles_service.py tests/api/test_policy_profiles_api.py tests/cli/test_cli_smoke.py::test_cli_policy_profiles_lista -q`
Expected: PASS. Conferir os nomes de função originais do arquivo de domínio antes de substituir (se os originais tinham outro nome, manter o nome e trocar só o corpo — os asserts acima são o contrato).

- [ ] **Step 4: API e CLI de `edge_trunk`**

Em `tests/api/test_circuits_api.py` (helpers `client`/`_auth()`/`_ambiente`/`_corpo` já existem):

```python
def test_edge_trunk_aceito_no_post_e_patch(client: TestClient, db_session: Session) -> None:
    env = _ambiente(db_session)
    corpo = _corpo(env, "CIRC-TRUNK-API")
    corpo["edge_trunk"] = "Eth-Trunk127"
    criado = client.post("/api/v1/circuits", json=corpo, headers=_auth())
    assert criado.status_code == 201, criado.text
    assert criado.json()["edge_trunk"] == "Eth-Trunk127"

    get_id = criado.json()["id"]
    assert client.get(f"/api/v1/circuits/{get_id}", headers=_auth()).json()["edge_trunk"] == "Eth-Trunk127"

    patch = client.patch(
        f"/api/v1/circuits/{get_id}", json={"edge_trunk": "Eth-Trunk128"}, headers=_auth()
    )
    assert patch.status_code == 200
    assert patch.json()["edge_trunk"] == "Eth-Trunk128"
```

Em `tests/cli/test_cli_smoke.py`, novo teste (helpers `create_site`/`create_organization`/`create_device`/`link_device` já importados no arquivo — conferir e acrescentar se faltar):

```python
def test_cli_circuits_add_edge_trunk(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-cli-trunk"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Org Circulo Trunk", asn=64515), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-trunk", management_address="10.8.3.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-trunk", management_address="10.8.3.1", asn=64605), actor="cli"
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")

    add = runner.invoke(
        app,
        [
            "circuits", "add",
            "--code", "CIRC-TRUNK-CLI", "--organization-id", str(org.id),
            "--site-id", str(site.id), "--access-device-id", str(sw.id),
            "--access-port", "GE0/0/1", "--edge-device-id", str(ne.id),
            "--edge-trunk", "Eth-Trunk127",
        ],
    )
    assert add.exit_code == 0, add.output
    circ_db = db_session.scalar(select(models.Circuit).where(models.Circuit.code == "CIRC-TRUNK-CLI"))
    assert circ_db is not None and circ_db.edge_trunk == "Eth-Trunk127"
```

No `src/gerenet/cli/circuits.py`, no comando `add`, após a option `--backup-edge-device-id`:

```python
    edge_trunk: str | None = typer.Option(
        None, "--edge-trunk", help="Trunk do edge que carrega as subinterfaces (ex.: Eth-Trunk127)."
    ),
```

e passar `edge_trunk=edge_trunk` na construção do `CircuitCreate(...)`.

Run: `uv run pytest tests/api/test_circuits_api.py::test_edge_trunk_aceito_no_post_e_patch tests/cli/test_cli_smoke.py::test_cli_circuits_add_edge_trunk -v`
Expected: PASS.

- [ ] **Step 5: Sessão aceita o perfil de importação seedado**

Adicionar ao fim de `tests/domain/test_bgp_sessions_service.py` (helpers existentes verificados: `_ambiente(db_session) -> dict` com chaves `org_id`/`site_id`/`sw_id`/`ne1_id`/`ne2_id`; `_circuito(db_session, env, *, code, edge_id, vrf=None) -> int`; `_sessao_data(env, circuit_id, edge_id, *, afi="ipv4", local, remote, **extra) -> BgpSessionCreate`):

```python
def test_sessao_aceita_perfil_de_importacao_seedado(db_session: Session) -> None:
    from gerenet.domain.services.policy_profiles import list_policy_profiles

    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-IMP-SEED", edge_id=env["ne1_id"])
    perfil_import = list_policy_profiles(db_session, direction="import")[0]
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], import_profile_id=perfil_import.id),
        actor="cli",
    )
    assert sessao.import_profile_id == perfil_import.id
```

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py::test_sessao_aceita_perfil_de_importacao_seedado -v`
Expected: PASS (sem o seed falharia; o teste valida o ruling 4).

- [ ] **Step 6: Suíte inteira**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions src/gerenet/domain/models.py src/gerenet/domain/schemas.py src/gerenet/domain/services/circuits.py src/gerenet/cli/circuits.py tests/
git commit -m "feat(SoT): circuits.edge_trunk (§25.18) e perfil de importação somente-autorizadas

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Dependência Jinja2 + 5 templates atômicos (goldens puros)

**Files:**
- Create: `src/gerenet/automation/render.py` (só loader nesta task; T4 acrescenta o orquestrador)
- Create: `src/gerenet/automation/templates/huawei_vrp/subinterface.j2`, `prefix_list.j2`, `route_policy_import.j2`, `route_policy_export.j2`, `bgp_peer.j2`
- Test: `tests/automation/test_templates.py`

**Interfaces:**
- Consumes: spec §5.2/§10; rulings 2, 5, 6.
- Produces: `_render_template(nome: str, contexto: dict) -> str` (sem `\n` final) — usado por T4/T5.

**Contrato de texto dos templates:** tags `{% … %}` sempre sozinhas na linha; `trim_blocks=True` + `lstrip_blocks=True` (linhas de tag não emitem nada); comandos em coluna 0, exceto os filhos de address-family do peer (2 espaços). O bloco termina com `\n`; `_render_template` faz `.rstrip("\n")`.

- [ ] **Step 1: Adicionar a dependência**

```bash
uv add jinja2
```

Run: `uv run pytest -q`
Expected: PASS (suíte segue verde).

- [ ] **Step 2: Escrever os templates**

`subinterface.j2`:

```jinja
interface {{ interface }}
{% if descricao %}
description {{ descricao }}
{% endif %}
{% if qinq %}
vlan-type dot1q 0x88a8 vid {{ vid }}
{% else %}
vlan-type dot1q vid {{ vid }}
{% endif %}
{% for v4 in enderecos_v4 %}
ip address {{ v4.endereco }} {{ v4.mascara }}
{% endfor %}
{% if enderecos_v6 %}
ipv6 enable
{% endif %}
{% for v6 in enderecos_v6 %}
ipv6 address {{ v6 }}
{% endfor %}
```

`prefix_list.j2`:

```jinja
{% set cmd = 'ip ipv6-prefix' if afi == 'ipv6' else 'ip ip-prefix' %}
{% for entrada in entradas %}
{{ cmd }} {{ nome }} index {{ entrada.index }} permit {{ entrada.prefixo }}
{% endfor %}
```

`route_policy_import.j2`:

```jinja
route-policy {{ nome }} permit node 10
{% if afi == 'ipv6' %}
if-match ipv6 address prefix-list {{ lista }}
{% else %}
if-match ip-prefix {{ lista }}
{% endif %}
{% if local_preference %}
apply local-preference {{ local_preference }}
{% endif %}
```

`route_policy_export.j2`:

```jinja
route-policy {{ nome }} permit node 10
{% if lista %}
{% if afi == 'ipv6' %}
if-match ipv6 address prefix-list {{ lista }}
{% else %}
if-match ip-prefix {{ lista }}
{% endif %}
{% endif %}
{% if med %}
apply med {{ med }}
{% endif %}
{% if prepend %}
apply as-path{% for _ in range(prepend) %} {{ asn_local }}{% endfor %} additive
{% endif %}
```

`bgp_peer.j2`:

```jinja
bgp {{ asn_local }}
peer {{ peer }} as-number {{ asn_remote }}
{% if descricao %}
peer {{ peer }} description {{ descricao }}
{% endif %}
{% if has_password %}
# password no Vault ({{ password_path }})
{% endif %}
{% if keepalive and holdtime %}
peer {{ peer }} timer keepalive {{ keepalive }} hold {{ holdtime }}
{% endif %}
{% if graceful_restart %}
peer {{ peer }} graceful-restart
{% endif %}
{% if bfd_enabled %}
peer {{ peer }} bfd enable
{% endif %}
{% if shutdown %}
peer {{ peer }} shutdown
{% endif %}
{% if afi == 'ipv6' %}
ipv6-family unicast
{% else %}
ipv4-family unicast
{% endif %}
  peer {{ peer }} enable
{% if rp_import %}
  peer {{ peer }} import route-policy {{ rp_import }}
{% endif %}
{% if rp_export %}
  peer {{ peer }} export route-policy {{ rp_export }}
{% endif %}
{% if maximum_prefix %}
  peer {{ peer }} maximum-prefix {{ maximum_prefix }}{% if maximum_prefix_threshold %} {{ maximum_prefix_threshold }}{% endif %}
{% endif %}
```

Nota (ruling 6): a linha `vlan-type dot1q 0x88a8 vid` do QinQ é a versão MVP; o `second-dot1q` é dívida do ciclo C.

- [ ] **Step 3: Loader + testes que falham**

`src/gerenet/automation/render.py` (T3 — a T4 substitui este arquivo pela versão completa, preservando estas funções):

```python
"""Render da intenção em comandos VRP (spec ciclo B §5)."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent / "templates" / "huawei_vrp"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def _render_template(nome: str, contexto: dict) -> str:
    """Renderiza o template `nome` (sem sufixo) com `contexto`; sem `\n` final."""
    return _env.get_template(nome + ".j2").render(**contexto).rstrip("\n")
```

Criar `tests/automation/test_templates.py`:

```python
"""Golden puro por template (spec ciclo B §5.2/§10) — entradas fixas, sem banco."""
from gerenet.automation.render import _render_template


def _render(template: str, **ctx: object) -> str:
    return _render_template(template, ctx)


def test_subinterface_dual() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.4024", descricao=None, qinq=False, vid=4024,
        enderecos_v4=[{"endereco": "100.110.0.73", "mascara": "255.255.255.252"}],
        enderecos_v6=["2804:194C:1000::1100:73:1/126"],
    ) == "\n".join([
        "interface Eth-Trunk127.4024",
        "vlan-type dot1q vid 4024",
        "ip address 100.110.0.73 255.255.255.252",
        "ipv6 enable",
        "ipv6 address 2804:194C:1000::1100:73:1/126",
    ])


def test_subinterface_v4_descricao_sem_ipv6() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.4023", descricao="Cliente A", qinq=False, vid=4023,
        enderecos_v4=[{"endereco": "100.64.0.1", "mascara": "255.255.255.254"}],
        enderecos_v6=[],
    ) == "\n".join([
        "interface Eth-Trunk127.4023",
        "description Cliente A",
        "vlan-type dot1q vid 4023",
        "ip address 100.64.0.1 255.255.255.254",
    ])


def test_subinterface_qinq_0x88a8() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.100", descricao=None, qinq=True, vid=100,
        enderecos_v4=[], enderecos_v6=["2001:DB8::1/126"],
    ) == "\n".join([
        "interface Eth-Trunk127.100",
        "vlan-type dot1q 0x88a8 vid 100",
        "ipv6 enable",
        "ipv6 address 2001:DB8::1/126",
    ])


def test_prefix_list_v4_e_v6() -> None:
    assert _render(
        "prefix_list",
        nome="IP-PFX-64500-IN-V4", afi="ipv4",
        entradas=[
            {"index": 10, "prefixo": "192.0.2.0/24"},
            {"index": 20, "prefixo": "198.51.100.0/24"},
        ],
    ) == "\n".join([
        "ip ip-prefix IP-PFX-64500-IN-V4 index 10 permit 192.0.2.0/24",
        "ip ip-prefix IP-PFX-64500-IN-V4 index 20 permit 198.51.100.0/24",
    ])
    assert _render(
        "prefix_list", nome="IP-PFX-64500-IN-V6", afi="ipv6",
        entradas=[{"index": 10, "prefixo": "2001:DB8::/32"}],
    ) == "ip ipv6-prefix IP-PFX-64500-IN-V6 index 10 permit 2001:DB8::/32"
    assert _render(
        "prefix_list", nome="IP-PFX-64500-IN-V4", afi="ipv4",
        entradas=[
            {"index": 5, "prefixo": "0.0.0.0/0"},
            {"index": 10, "prefixo": "192.0.2.0/24"},
        ],
    ).startswith("ip ip-prefix IP-PFX-64500-IN-V4 index 5 permit 0.0.0.0/0")


def test_route_policy_import_v4_com_lp_e_v6_sem_lp() -> None:
    assert _render(
        "route_policy_import", nome="RP-64500-IMPORT-V4", afi="ipv4",
        lista="IP-PFX-64500-IN-V4", local_preference=200,
    ) == "\n".join([
        "route-policy RP-64500-IMPORT-V4 permit node 10",
        "if-match ip-prefix IP-PFX-64500-IN-V4",
        "apply local-preference 200",
    ])
    assert _render(
        "route_policy_import", nome="RP-64500-IMPORT-V6", afi="ipv6",
        lista="IP-PFX-64500-IN-V6", local_preference=None,
    ) == "\n".join([
        "route-policy RP-64500-IMPORT-V6 permit node 10",
        "if-match ipv6 address prefix-list IP-PFX-64500-IN-V6",
    ])


def test_route_policy_export_full_sem_condicoes() -> None:
    assert _render(
        "route_policy_export", nome="RP-64500-EXPORT-V4", afi="ipv4", lista=None,
        med=None, prepend=0, asn_local=61785,
    ) == "route-policy RP-64500-EXPORT-V4 permit node 10"


def test_route_policy_export_default_com_med_e_prepend() -> None:
    assert _render(
        "route_policy_export", nome="RP-64500-EXPORT-V6", afi="ipv6",
        lista="IP-PFX-DEFAULT-V6", med=50, prepend=2, asn_local=61785,
    ) == "\n".join([
        "route-policy RP-64500-EXPORT-V6 permit node 10",
        "if-match ipv6 address prefix-list IP-PFX-DEFAULT-V6",
        "apply med 50",
        "apply as-path 61785 61785 additive",
    ])


def test_bgp_peer_v4_completo() -> None:
    assert _render(
        "bgp_peer",
        asn_local=61785, peer="100.110.0.74", asn_remote=270620,
        descricao="Cliente 270620", has_password=True,
        password_path="gerenet/bgp-sessions/1/password",
        keepalive=30, holdtime=90, graceful_restart=True, bfd_enabled=True,
        shutdown=False, afi="ipv4", rp_import="RP-270620-IMPORT-V4",
        rp_export="RP-270620-EXPORT-V4", maximum_prefix=100, maximum_prefix_threshold=80,
    ) == "\n".join([
        "bgp 61785",
        "peer 100.110.0.74 as-number 270620",
        "peer 100.110.0.74 description Cliente 270620",
        "# password no Vault (gerenet/bgp-sessions/1/password)",
        "peer 100.110.0.74 timer keepalive 30 hold 90",
        "peer 100.110.0.74 graceful-restart",
        "peer 100.110.0.74 bfd enable",
        "ipv4-family unicast",
        "  peer 100.110.0.74 enable",
        "  peer 100.110.0.74 import route-policy RP-270620-IMPORT-V4",
        "  peer 100.110.0.74 export route-policy RP-270620-EXPORT-V4",
        "  peer 100.110.0.74 maximum-prefix 100 80",
    ])


def test_bgp_peer_v6_minimo_com_shutdown() -> None:
    assert _render(
        "bgp_peer",
        asn_local=61785, peer="2804:194C:1000::1100:73:2", asn_remote=270620,
        descricao=None, has_password=False, password_path=None,
        keepalive=None, holdtime=None, graceful_restart=False, bfd_enabled=False,
        shutdown=True, afi="ipv6", rp_import=None, rp_export=None,
        maximum_prefix=None, maximum_prefix_threshold=None,
    ) == "\n".join([
        "bgp 61785",
        "peer 2804:194C:1000::1100:73:2 as-number 270620",
        "peer 2804:194C:1000::1100:73:2 shutdown",
        "ipv6-family unicast",
        "  peer 2804:194C:1000::1100:73:2 enable",
    ])
```

- [ ] **Step 4: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_templates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.automation.render'` (criar o loader na ordem do Step 3 e só então o teste passa; se quiser ver o FAIL de template, escrever o teste antes do loader).

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_templates.py -v`
Expected: PASS (8 testes). Se um golden divergir, o template acima é o contrato de texto — ajustar aquilo que o executor tiver escrito de forma diferente até casar exatamente.

- [ ] **Step 6: Suíte inteira + commit**

Run: `uv run pytest -q` — PASS.

```bash
git add pyproject.toml uv.lock src/gerenet/automation/render.py src/gerenet/automation/templates/huawei_vrp/ tests/automation/test_templates.py
git commit -m "feat(SoT): templates Jinja2 atômicos do render BGP (spec ciclo B §5.2)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Orquestrador `render_desejado` (blocos ordenados por device)

**Files:**
- Modify: `src/gerenet/automation/render.py` (versão completa — substitui a de T3 preservando o loader)
- Test: `tests/automation/test_rendering.py`

**Interfaces:**
- Consumes: `naming.py` (T1), `_render_template` (T3), `ipam.pontas_v4/pontas_v6` (existentes), `get_device` (services/devices.py), `list_sessions` (services/bgp_sessions.py), `get_policy_profile` (services/policy_profiles.py), `list_authorizations(session, organization_id=…)` (services/prefix_authorizations.py).
- Produces: `render_desejado(session, device_id: int) -> RenderResult` (`RenderResult.device_id/.blocos/.texto`), `BlocoRender(tipo, objeto, objeto_id, comandos)` com `.texto`; `TIPO_ORDEM` dict; `_render_template` — usados por T5/T6.

- [ ] **Step 1: Testes que falham**

Criar `tests/automation/test_rendering.py` (a importação local de `render_desejado` dentro de cada teste é padrão do repo em testes de orquestração — manter para clareza):

```python
"""Orquestrador render_desejado — blocos completos por device (spec ciclo B §5.2)."""
import ipaddress

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services import bgp_sessions as sessoes_svc
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import NotFoundError
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> dict:
    """Site default + org ASN 64512 + switch + NE8000 ASN 64600 no site."""
    site = create_site(db_session, SiteCreate(name="pop-render-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Render", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-render", management_address="10.30.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-render", management_address="10.30.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _circuito_reservado(db_session: Session, env: dict, *, code: str, **extra) -> int:
    """Circuito no edge do ambiente com edge_trunk, reservado; devolve o id."""
    base: dict = {
        "code": code, "organization_id": env["org_id"], "site_id": env["site_id"],
        "access_device_id": env["sw_id"], "access_port": "GE0/0/1",
        "edge_device_id": env["ne_id"], "edge_trunk": "Eth-Trunk127",
    }
    base.update(extra)
    circ_id = create_circuit(db_session, CircuitCreate(**base), actor="cli").id
    reservar_circuito(db_session, circ_id, actor="cli")
    return circ_id


def _pontas(db_session: Session, circ_id: int) -> dict:
    """Pontas locais/remotas v4/v6 do circuito reservado (via IPAM)."""
    redes = {
        ipaddress.ip_network(l.n).version: l.n
        for l in db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    }
    v4_l, v4_r = pontas_v4(redes[4])
    if 6 in redes:
        v6_l, v6_r = pontas_v6(redes[6])  # "address/126"
        return {"v4_l": v4_l, "v4_r": v4_r, "v6_l": v6_l[:-4], "v6_r": v6_r[:-4]}
    return {"v4_l": v4_l, "v4_r": v4_r, "v6_l": None, "v6_r": None}


def _sessao(db_session: Session, env: dict, circ_id: int, *, afi: str, **extra) -> int:
    p = _pontas(db_session, circ_id)
    dados: dict = {
        "afi": afi,
        "local_address": p["v4_l"] if afi == "ipv4" else p["v6_l"],
        "remote_address": p["v4_r"] if afi == "ipv4" else p["v6_r"],
    }
    dados.update(extra)
    return sessoes_svc.create_session(
        db_session, BgpSessionCreate(circuit_id=circ_id, device_id=env["ne_id"], **dados), actor="cli"
    ).id
```

Testes (segue o arquivo na íntegra):

```python
def test_render_dual_completo_ordenado(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    full_id = next(p.id for p in list_policy_profiles(db_session, direction="export") if p.name == "full")
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-1")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv6", prefix="2001:DB8::/32",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=full_id)
    _sessao(db_session, env, circ_id, afi="ipv6", export_profile_id=full_id)

    resultado = render_desejado(db_session, env["ne_id"])
    assert [b.tipo for b in resultado.blocos] == [
        "subinterface",
        "prefix_list", "route_policy_import", "route_policy_export", "bgp_peer",
        "prefix_list", "route_policy_import", "route_policy_export", "bgp_peer",
    ]
    # anotação do objeto SoT que originou cada bloco (ciclo C mapeia diff/rollback)
    assert resultado.blocos[0].objeto == "circuit"
    assert resultado.blocos[0].objeto_id == circ_id
    assert all(b.objeto == "session" for b in resultado.blocos[1:])

    sub = resultado.blocos[0]
    assert sub.comandos[0] == "interface Eth-Trunk127.2"
    assert sub.comandos[1] == "vlan-type dot1q vid 2"
    assert "ip address 100.64.0.0 255.255.255.254" in sub.comandos
    assert "ipv6 enable" in sub.comandos
    assert "ipv6 address 2804:194C:1000::6400:1/126" in sub.comandos

    assert resultado.texto == "\n".join(b.texto for b in resultado.blocos)


def test_render_v4_sem_autorizacao_so_peer(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-2", stack="ipv4", vlan_mode="separada")
    _sessao(db_session, env, circ_id, afi="ipv4")

    resultado = render_desejado(db_session, env["ne_id"])
    # sem autorizações ⇒ sem prefix_list/RP import; sem perfil ⇒ sem export
    assert [b.tipo for b in resultado.blocos] == ["subinterface", "bgp_peer"]
    assert resultado.blocos[0].comandos[0].startswith("interface Eth-Trunk127.")
    assert not any("ipv6" in linha for linha in resultado.blocos[0].comandos)
    texto = resultado.texto
    assert "peer 100.64.0.1 as-number 64512" in texto  # org = ASN do par (default)
    assert "import route-policy" not in texto
    assert "export route-policy" not in texto


def test_render_sem_edge_trunk_nao_gera_subinterface(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    base: dict = {
        "code": "CIRC-R-3", "organization_id": env["org_id"], "site_id": env["site_id"],
        "access_device_id": env["sw_id"], "access_port": "GE0/0/1",
        "edge_device_id": env["ne_id"],
    }
    circ_id = create_circuit(db_session, CircuitCreate(**base), actor="cli").id
    reservar_circuito(db_session, circ_id, actor="cli")
    _sessao(db_session, env, circ_id, afi="ipv4")

    resultado = render_desejado(db_session, env["ne_id"])
    assert [b.tipo for b in resultado.blocos] == ["bgp_peer"]


def test_render_export_default_med_prepend_e_dividas(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    perfis = {p.name: p.id for p in list_policy_profiles(db_session, direction="export")}
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-4", stack="ipv4")
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=perfis["default"], med=50, prepend=2)

    texto = render_desejado(db_session, env["ne_id"]).texto
    assert "ip ip-prefix IP-PFX-DEFAULT-V4 index 10 permit 0.0.0.0/0" in texto
    assert "route-policy RP-64512-EXPORT-V4 permit node 10" in texto
    assert "if-match ip-prefix IP-PFX-DEFAULT-V4" in texto
    assert "apply med 50" in texto
    assert "apply as-path 64600 64600 additive" in texto  # asn_local = ASN do device

    circ_d = _circuito_reservado(db_session, env, code="CIRC-R-5", stack="ipv4")
    _sessao(db_session, env, circ_d, afi="ipv4", export_profile_id=perfis["default_internas"])
    texto2 = render_desejado(db_session, env["ne_id"]).texto
    assert "# produto 'default_internas'" in texto2  # dívida documentada (ruling 13)


def test_render_import_com_default_autorizada(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-6", stack="ipv4")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", allow_default_route=True)

    texto = render_desejado(db_session, env["ne_id"]).texto
    assert "index 5 permit 0.0.0.0/0" in texto
    assert "index 10 permit 192.0.2.0/24" in texto
    assert "if-match ip-prefix IP-PFX-64512-IN-V4" in texto


def test_render_sessao_shutdown_emite_peer_shutdown(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-7", stack="ipv4")
    _sessao(db_session, env, circ_id, afi="ipv4", shutdown=True)
    texto = render_desejado(db_session, env["ne_id"]).texto.replace("\n", "|")
    assert "peer 100.64.0.1 shutdown" in texto


def test_render_senha_vira_so_comentario(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-8", stack="ipv4")
    sessao_id = _sessao(db_session, env, circ_id, afi="ipv4")
    sessoes_svc.set_password(db_session, sessao_id, actor="cli", path="gerenet/bgp-sessions/1/password")
    texto = render_desejado(db_session, env["ne_id"]).texto
    assert texto.count("password") == 1  # só o comentário; o valor nunca é emitido
    assert "# password no Vault (gerenet/bgp-sessions/1/password)" in texto


def test_render_idempotente(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-9", stack="ipv4")
    _sessao(db_session, env, circ_id, afi="ipv4")
    assert render_desejado(db_session, env["ne_id"]).texto == render_desejado(
        db_session, env["ne_id"]
    ).texto


def test_render_device_inexistente(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    with pytest.raises(NotFoundError):
        render_desejado(db_session, 9999)
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_rendering.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_desejado'`.

- [ ] **Step 3: Implementar o orquestrador (versão final do render.py)**

Substituir o conteúdo de `src/gerenet/automation/render.py` pela versão completa abaixo (preserva `TEMPLATES_DIR`/`_env`/`_render_template`):

```python
"""Render da intenção em comandos VRP (spec ciclo B §5.2).

Orquestrador puro: decide QUAIS blocos (com quais nomes §25.4) por device e
delega o texto ao template Jinja2 atômico correspondente. Render é idempotente
por construção: deriva sempre do Source of Truth.
"""
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import naming
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.ipam import pontas_v4, pontas_v6
from gerenet.domain.services.policy_profiles import get_policy_profile
from gerenet.domain.services.prefix_authorizations import list_authorizations

TEMPLATES_DIR = Path(__file__).parent / "templates" / "huawei_vrp"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)

TIPO_ORDEM = {
    "subinterface": 10,
    "prefix_list": 20,
    "route_policy_import": 30,
    "route_policy_export": 40,
    "bgp_peer": 50,
    "comentario": 60,
}


def _render_template(nome: str, contexto: dict) -> str:
    """Renderiza o template `nome` (sem sufixo) com `contexto`; sem `\n` final."""
    return _env.get_template(nome + ".j2").render(**contexto).rstrip("\n")


@dataclass
class BlocoRender:
    """Bloco de comandos VRP anotado com o objeto SoT que o originou (ciclo C)."""

    tipo: str
    objeto: str  # "circuit" | "session"
    objeto_id: int
    comandos: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n".join(self.comandos)


@dataclass
class RenderResult:
    device_id: int
    blocos: list[BlocoRender]
    texto: str


def _reserva(session: Session, circuito: models.Circuit) -> dict[str, dict]:
    """Endereços locais da reserva do circuito por família.

    Devolve {"ipv4": {"vid", "endereco", "mascara"}, "ipv6": {"vid", "endereco"}}
    das pontas LOCAIS (IPAM §25.8). O par v4 interno de stack=ipv6 não vira
    endereço de interface (ruling 3). VLAN family None (unica) serve às duas
    famílias. O /len deriva do CIDR reservado (o IPAM respeita
    circuit.p2p_v4_len).
    """
    vlans = list(session.scalars(
        select(models.Vlan).where(models.Vlan.circuit_id == circuito.id).order_by(models.Vlan.vid)
    ))
    prefixos = list(session.scalars(
        select(models.IpPrefix).where(models.IpPrefix.circuit_id == circuito.id)
    ))
    por_versao: dict[int, str] = {
        ipaddress.ip_network(p.n).version: p.n for p in prefixos
    }
    local_v4: tuple[str, str] | None = None
    local_v6: str | None = None
    if 4 in por_versao:
        rede = ipaddress.ip_network(por_versao[4])
        ponta_local, _ = pontas_v4(por_versao[4])
        local_v4 = (ponta_local, str(rede.netmask))
    if 6 in por_versao:
        local_v6 = pontas_v6(por_versao[6])[0]  # "address/126" (ponta local)

    familias: dict[str | None, int] = {}
    for vlan in vlans:
        for fam in [None] if vlan.family is None else [vlan.family]:
            familias.setdefault(fam, vlan.vid)

    saida: dict[str, dict] = {}
    for fam, vid in familias.items():
        if fam is None:
            if local_v4 is not None:
                saida["ipv4"] = {"vid": vid, "endereco": local_v4[0], "mascara": local_v4[1]}
            if local_v6 is not None:
                saida["ipv6"] = {"vid": vid, "endereco": local_v6}
        elif fam == "ipv4" and local_v4 is not None:
            saida["ipv4"] = {"vid": vid, "endereco": local_v4[0], "mascara": local_v4[1]}
        elif fam == "ipv6" and local_v6 is not None:
            saida["ipv6"] = {"vid": vid, "endereco": local_v6}
    return saida


def _comandos_sub(
    trunk: str, vid: int, qinq: bool, *, v4: dict | None, v6: str | None
) -> list[str]:
    """Linhas de comando da subinterface (description só via session no B — §5.1)."""
    contexto: dict = {
        "interface": naming.subinterface(trunk, vid),
        "descricao": None,
        "qinq": qinq,
        "vid": vid,
        "enderecos_v4": [v4] if v4 else [],
        "enderecos_v6": [v6] if v6 else [],
    }
    return _render_template("subinterface", contexto).splitlines()


def _bloco_sub(session: Session, circuito: models.Circuit, device_id: int) -> list[BlocoRender]:
    """Blocos de subinterface do circuito (unica: 1; separada: 1 por família).

    Só quando o device é o edge (ou backup) do circuito, com edge_trunk e
    reserva (ruling 3). Sem esses pré-requisitos, devolve lista vazia — a
    divergência acusa circuito.sem_trunk quando só falta o trunk.
    """
    if circuito.edge_device_id != device_id and circuito.backup_edge_device_id != device_id:
        return []
    if not circuito.edge_trunk:
        return []
    fams = _reserva(session, circuito)
    if not fams:
        return []
    if circuito.vlan_mode == "unica":
        vid = fams["ipv4"]["vid"] if "ipv4" in fams else fams["ipv6"]["vid"]
        comandos = _comandos_sub(
            circuito.edge_trunk, vid, circuito.qinq,
            v4=fams.get("ipv4"), v6=fams.get("ipv6", {}).get("endereco"),
        )
        return [BlocoRender("subinterface", "circuit", circuito.id, comandos)]
    blocos: list[BlocoRender] = []
    for fam in ("ipv4", "ipv6"):
        if fam not in fams:
            continue
        comandos = _comandos_sub(
            circuito.edge_trunk, fams[fam]["vid"], circuito.qinq,
            v4=fams[fam] if fam == "ipv4" else None,
            v6=fams[fam]["endereco"] if fam == "ipv6" else None,
        )
        blocos.append(BlocoRender("subinterface", "circuit", circuito.id, comandos))
    return blocos


def _bloco_import(
    session: Session, circuito: models.Circuit, sessao: models.BgpSession, emitidas: set[str]
) -> list[BlocoRender]:
    """Prefix-list + RP de importação a partir das autorizações da org (§6.4).

    Só quando há autorização ativa da família; sem autorização, a sessão não
    tem filtro de importação para renderizar (ruling 4).
    """
    autorizadas = [
        a for a in list_authorizations(session, organization_id=circuito.organization_id)
        if a.family == sessao.afi
    ]
    if not autorizadas:
        return []
    afi = sessao.afi
    asn_par = sessao.asn_remote
    nome_pfx = naming.pfx_in(asn_par, afi)
    nome_rp = naming.rp_import(asn_par, afi)
    blocos: list[BlocoRender] = []
    if nome_pfx not in emitidas:
        emitidas.add(nome_pfx)
        entradas: list[dict] = []
        if sessao.allow_default_route:
            entradas.append({"index": 5, "prefixo": "0.0.0.0/0" if afi == "ipv4" else "::/0"})
        entradas += [
            {"index": 10 * (i + 1), "prefixo": a.prefix} for i, a in enumerate(autorizadas)
        ]
        comandos = _render_template(
            "prefix_list", {"nome": nome_pfx, "afi": afi, "entradas": entradas}
        ).splitlines()
        blocos.append(BlocoRender("prefix_list", "session", sessao.id, comandos))
    comandos = _render_template(
        "route_policy_import",
        {"nome": nome_rp, "afi": afi, "lista": nome_pfx, "local_preference": sessao.local_preference},
    ).splitlines()
    blocos.append(BlocoRender("route_policy_import", "session", sessao.id, comandos))
    return blocos


def _bloco_rp_export(sessao: models.BgpSession, nome_rp: str, afi: str, lista: str | None) -> BlocoRender:
    comandos = _render_template(
        "route_policy_export",
        {
            "nome": nome_rp, "afi": afi, "lista": lista,
            "med": sessao.med, "prepend": sessao.prepend or 0,
            "asn_local": sessao.asn_local,
        },
    ).splitlines()
    return BlocoRender("route_policy_export", "session", sessao.id, comandos)


def _bloco_divida(texto: str) -> BlocoRender:
    """Comentário ao operador (sem comando executável) — ruling 13."""
    return BlocoRender("comentario", "session", 0, [f"# {texto}"])


def _bloco_export(
    session: Session, sessao: models.BgpSession, emitidas: set[str]
) -> list[BlocoRender]:
    """RP de exportação pelo produto §6.5/§25.5 (ruling 5); dívidas viram comentário."""
    if sessao.export_profile_id is None:
        return []
    perfil = get_policy_profile(session, sessao.export_profile_id)
    afi = sessao.afi
    nome_rp = naming.rp_export(sessao.asn_remote, afi)
    produto = perfil.name
    if produto == "full":
        return [_bloco_rp_export(sessao, nome_rp, afi, None)]
    if produto == "default":
        lista = naming.pfx_produto("default", afi)
        if lista not in emitidas:
            emitidas.add(lista)
            prefixo = "0.0.0.0/0" if afi == "ipv4" else "::/0"
            comandos = _render_template(
                "prefix_list", {"nome": lista, "afi": afi, "entradas": [{"index": 10, "prefixo": prefixo}]}
            ).splitlines()
            return [
                BlocoRender("prefix_list", "session", sessao.id, comandos),
                _bloco_rp_export(sessao, nome_rp, afi, lista),
            ]
        return [_bloco_rp_export(sessao, nome_rp, afi, lista)]
    if produto in ("cdn", "personalizado"):
        if not perfil.prefixes:
            return [_bloco_divida(
                f"produto '{produto}': sem prefixos cadastrados para montar a lista de anúncio."
            )]
        lista = naming.pfx_produto(produto, afi)
        if lista not in emitidas:
            emitidas.add(lista)
            entradas = [
                {"index": 10 * (i + 1), "prefixo": p} for i, p in enumerate(perfil.prefixes)
            ]
            comandos = _render_template(
                "prefix_list", {"nome": lista, "afi": afi, "entradas": entradas}
            ).splitlines()
            return [
                BlocoRender("prefix_list", "session", sessao.id, comandos),
                _bloco_rp_export(sessao, nome_rp, afi, lista),
            ]
        return [_bloco_rp_export(sessao, nome_rp, afi, lista)]
    # default_internas / parcial
    return [_bloco_divida(
        f"produto '{produto}': rotas internas ainda não renderizáveis (ciclo C/F5)."
    )]


def _bloco_peer(sessao: models.BgpSession, rp_import: str | None, rp_export: str | None) -> BlocoRender:
    comandos = _render_template(
        "bgp_peer",
        {
            "asn_local": sessao.asn_local,
            "peer": sessao.remote_address,
            "asn_remote": sessao.asn_remote,
            "descricao": sessao.description,
            "has_password": sessao.has_password,
            "password_path": sessao.password_ref,
            "keepalive": sessao.keepalive if sessao.keepalive and sessao.holdtime else None,
            "holdtime": sessao.holdtime if sessao.keepalive and sessao.holdtime else None,
            "graceful_restart": sessao.graceful_restart,
            "bfd_enabled": sessao.bfd_enabled,
            "shutdown": sessao.shutdown,
            "afi": sessao.afi,
            "rp_import": rp_import,
            "rp_export": rp_export,
            "maximum_prefix": sessao.maximum_prefix,
            "maximum_prefix_threshold": sessao.maximum_prefix_threshold,
        },
    ).splitlines()
    return BlocoRender("bgp_peer", "session", sessao.id, comandos)


def render_desejado(session: Session, device_id: int) -> RenderResult:
    """Blocos VRP desejados do device (sessões ativas; §5.2). Idempotente."""
    device = get_device(session, device_id)
    circuitos: dict[int, models.Circuit] = {}
    for sessao in list_sessions(session, device_id=device_id):
        if sessao.circuit_id not in circuitos:
            circ = session.get(models.Circuit, sessao.circuit_id)
            if circ is not None:
                circuitos[sessao.circuit_id] = circ

    blocos: list[BlocoRender] = []
    emitidas: set[str] = set()
    for circ_id in sorted(circuitos):
        circuito = circuitos[circ_id]
        blocos.extend(_bloco_sub(session, circuito, device_id))
        for sessao in sorted(
            list_sessions(session, circuit_id=circ_id, device_id=device_id),
            key=lambda s: (s.afi, s.remote_address),
        ):
            import_blocos = _bloco_import(session, circuito, sessao, emitidas)
            export_blocos = _bloco_export(session, sessao, emitidas)
            blocos.extend(import_blocos)
            blocos.extend(export_blocos)
            rp_import = next(
                (b.comandos[0].removeprefix("route-policy ").split()[0] for b in import_blocos
                 if b.tipo == "route_policy_import"),
                None,
            )
            rp_export = next(
                (b.comandos[0].removeprefix("route-policy ").split()[0] for b in export_blocos
                 if b.tipo == "route_policy_export"),
                None,
            )
            blocos.append(_bloco_peer(sessao, rp_import, rp_export))
    blocos.sort(key=lambda b: TIPO_ORDEM[b.tipo])  # estável: preserva ordem intra-tipo
    texto = "\n".join(b.texto for b in blocos)
    return RenderResult(device_id=device.id, blocos=blocos, texto=texto)
```

- [ ] **Step 4: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_rendering.py -v`
Expected: PASS (9 testes). Se algum golden divergir, conferir ordem/literais contra os contratos acima (templates T3 e helpers deste arquivo).

- [ ] **Step 5: Suíte inteira**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/render.py tests/automation/test_rendering.py
git commit -m "feat(SoT): orquestrador render_desejado — blocos VRP por device (ciclo B §5.2)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Divergência `reconciliar_device` (desejado × encontrado, read-only)

**Files:**
- Create: `src/gerenet/automation/reconcile.py`
- Test: `tests/automation/test_reconcile.py`

**Interfaces:**
- Consumes: `render_desejado`/`BlocoRender`/`RenderResult` (T4); `get_device` (services/devices.py); `list_sessions` (services/bgp_sessions.py); `DeviceSnapshot` (models); `NotFoundError`/`ValidationError` (services/errors.py); shapes de resources (contrato B1).
- Produces: `reconciliar_device(session, device_id: int | None = None, *, snapshot_id: int | None = None) -> ReconcileResult` com `ReconcileResult{device_id, snapshot_id: int | None, aviso: str | None, items: list[ReconcileItem]}`; `ReconcileItem{tipo, severidade, esperado, encontrado, acao}` — consumidos por T6.

**Semântica (ruling 7):**
- Sessões esperadas = `admin_status=True` do device (inclui shutdown). Peers encontrados = `resources["bgp_peers"]` por (afi, peer), com peer = `remote_address`.
- Por sessão: ausente → `peer.ausente` (crítica, esperado = remote_address); `shutdown=true` e estado `Established` → `peer.shutdown_admin` (atenção, esperado "não Established"); `shutdown=false` e estado ≠ `Established` → `peer.estado` (atenção, esperado "Established"); `asn` divergente → `peer.asn` (crítica); filtros (crítica) quando o render emitiu `route_policy_import`/`route_policy_export` para a sessão **e** há linha verbose (afi, peer) — esperado = nome do RP (1ª linha do bloco), encontrado = `filtro_import`/`filtro_export`.
- Órfãos: peer do snapshot sem sessão ativa (afi, remote) → `peer.orfaos` (atenção).
- Subinterfaces esperadas = blocos `subinterface` (parse de `interface X`, `ip address A M`, `ipv6 enable`); ausente → crítica; phy ≠ "up" ou protocolo ≠ "up" → `subinterface.estado` (atenção; encontrado = `phy/protocolo`); endereço v4 ausente → `ponta.v4` (crítica; esperado = `A/<len>`, encontrado = "…" da lista ou "—"); v6 idem (`ponta.v6`, encontrado como renderizado `/126`).
- Circuito reservado + sessão ativa sem `edge_trunk` → `circuito.sem_trunk` (aviso).
- Recurso sem chave no snapshot → aviso único e grupo pulado. Sem snapshot → aviso de coleta, items vazios, `snapshot_id=None`.

- [ ] **Step 1: Testes que falham**

Criar `tests/automation/test_reconcile.py`:

```python
"""Divergência desejado × encontrado (spec ciclo B §6) — snapshot sintético."""
import ipaddress

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services import bgp_sessions as sessoes_svc
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import NotFoundError, ValidationError
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> dict:
    """Site default + org ASN 64512 + switch + NE8000 ASN 64600 no site."""
    site = create_site(db_session, SiteCreate(name="pop-rec-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Reconcilia", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-rec", management_address="10.31.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-rec", management_address="10.31.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _circuito_completo(db_session: Session, env: dict, *, code: str = "CIRC-REC-1") -> int:
    """Circuito dual reservado com edge_trunk; devolve o id."""
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne_id"], edge_trunk="Eth-Trunk127",
        ),
        actor="cli",
    ).id
    reservar_circuito(db_session, circ_id, actor="cli")
    return circ_id


def _circuito_sem_trunk(db_session: Session, env: dict) -> int:
    """Circuito dual reservado SEM edge_trunk; devolve o id."""
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-REC-NT", organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne_id"],
        ),
        actor="cli",
    ).id
    reservar_circuito(db_session, circ_id, actor="cli")
    return circ_id


def _pontas(db_session: Session, circ_id: int) -> dict:
    redes = {
        ipaddress.ip_network(l.n).version: l.n
        for l in db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    }
    v4_l, v4_r = pontas_v4(redes[4])
    v4_len = ipaddress.ip_network(redes[4]).prefixlen
    v6_l, v6_r = pontas_v6(redes[6])  # "address/126"
    return {
        "v4_l": v4_l, "v4_r": v4_r, "v4_len": v4_len,
        "v6_l": v6_l, "v6_r": v6_r,
        "v4_sub": f"{v4_l}/{v4_len}",
    }


def _sessao(db_session: Session, env: dict, circ_id: int, *, afi: str, **extra) -> int:
    p = _pontas(db_session, circ_id)
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ_id, device_id=env["ne_id"], afi=afi,
            local_address=p["v4_l"] if afi == "ipv4" else p["v6_l"].removesuffix("/126"),
            remote_address=p["v4_r"] if afi == "ipv4" else p["v6_r"].removesuffix("/126"),
            **extra,
        ),
        actor="cli",
    ).id


def _autoriza(db_session: Session, env: dict, *, v6: bool = False) -> None:
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=env["org_id"],
            family="ipv6" if v6 else "ipv4",
            prefix="2001:DB8::/32" if v6 else "192.0.2.0/24",
        ),
        actor="cli",
    )


def _perfil_export(db_session: Session, nome: str) -> int:
    return next(p.id for p in list_policy_profiles(db_session, direction="export") if p.name == nome)


def _snapshot(
    db_session: Session, env: dict, *, status: str = "success",
    interfaces: list[dict] | None = None,
    peers: list[dict] | None = None,
    verbose: list[dict] | None = None,
    sem: tuple[str, ...] = (),
) -> int:
    """Snapshot sintético do device; devolve o id. `sem` omite chaves de resources."""
    recursos: dict = {
        "version": {"version": "8.210"},
        "interfaces": interfaces if interfaces is not None else [],
        "bgp_peers": peers if peers is not None else [],
        "bgp_peers_verbose": verbose if verbose is not None else [],
    }
    for chave in sem:
        recursos.pop(chave, None)
    snap = models.DeviceSnapshot(
        device_id=env["ne_id"], status=status, resources=recursos,
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap.id


def _recursos_perfeitos(db_session: Session, env: dict) -> dict:
    """interfaces/peers/verbose perfeitamente conformes (para _ambiente_dual)."""
    p = _pontas(db_session, _circ_id(db_session, env))
    return {
        "interfaces": [{
            "nome": "Eth-Trunk127.2", "phy": "up", "protocolo": "up",
            "enderecos_v4": [p["v4_sub"]],
            "enderecos_v6": [p["v6_l"]], "vpn": None,
        }],
        "bgp_peers": [
            {"afi": "ipv4", "peer": p["v4_r"], "asn": 64512, "estado": "Established",
             "pref_rcv": 2, "up_down": "1d02h"},
            {"afi": "ipv6", "peer": p["v6_r"].removesuffix("/126"), "asn": 64512,
             "estado": "Established", "pref_rcv": 0, "up_down": "1d02h"},
        ],
        "bgp_peers_verbose": [
            {"afi": "ipv4", "peer": p["v4_r"], "descricao": None,
             "filtro_import": "RP-64512-IMPORT-V4", "filtro_export": "RP-64512-EXPORT-V4"},
            {"afi": "ipv6", "peer": p["v6_r"].removesuffix("/126"), "descricao": None,
             "filtro_import": "RP-64512-IMPORT-V6", "filtro_export": "RP-64512-EXPORT-V6"},
        ],
    }


def _circ_id(db_session: Session, env: dict) -> int:
    circ = db_session.scalar(
        select(models.Circuit).where(
            models.Circuit.edge_device_id == env["ne_id"], models.Circuit.code == "CIRC-REC-1"
        )
    )
    return circ.id


def _ambiente_dual(db_session: Session) -> tuple[dict, dict]:
    """Env completo (circuito dual + autorizações v4/v6 + sessões com perfil full).

    Devolve (env, p) — p são as pontas locais/remotas do circuito, usadas
    pelos esperados dos itens de divergência.
    """
    env = _ambiente(db_session)
    circ_id = _circuito_completo(db_session, env)
    _autoriza(db_session, env)
    _autoriza(db_session, env, v6=True)
    full = _perfil_export(db_session, "full")
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=full)
    _sessao(db_session, env, circ_id, afi="ipv6", export_profile_id=full)
    p = _pontas(db_session, circ_id)
    return env, p
```

Testes:

```python
def test_conformidade_silenciosa(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    _snapshot(db_session, env, **_recursos_perfeitos(db_session, env))
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert resultado.items == []
    assert resultado.aviso is None
    assert resultado.snapshot_id is not None


def test_sem_snapshot_devolve_aviso(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert resultado.snapshot_id is None
    assert resultado.items == []
    assert resultado.aviso is not None and "snapshot" in resultado.aviso.lower()


def test_peer_ausente_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, p = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"] = [linha for linha in perfeito["bgp_peers"] if linha["afi"] != "ipv6"]
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.ausente"]
    assert itens[0].severidade == "critica"
    assert itens[0].esperado == p["v6_r"].removesuffix("/126")


def test_peer_estado_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"][0]["estado"] = "Active"
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.estado"]
    assert itens[0].esperado == "Established"
    assert itens[0].encontrado == "Active"


def test_peer_shutdown_admin_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env = _ambiente(db_session)
    circ_id = _circuito_completo(db_session, env, code="CIRC-REC-SD")
    _sessao(db_session, env, circ_id, afi="ipv4", shutdown=True)
    p = _pontas(db_session, circ_id)
    _snapshot(
        db_session, env, sem=("interfaces",),
        peers=[{"afi": "ipv4", "peer": p["v4_r"], "asn": 64512, "estado": "Established",
                "pref_rcv": 1, "up_down": "1d02h"}],
    )
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.shutdown_admin"]
    assert itens[0].encontrado == "Established"
```

Continuam os demais testes no mesmo arquivo:

```python
def test_peer_asn_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"][0]["asn"] = 64599
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.asn"]
    assert itens[0].esperado == "64512"
    assert itens[0].encontrado == "64599"


def test_peer_filtros_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers_verbose"][0]["filtro_import"] = "ASN64512-V4-IMPORT"  # legado em produção
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.filtros"]
    assert itens[0].esperado == "RP-64512-IMPORT-V4"
    assert itens[0].encontrado == "ASN64512-V4-IMPORT"


def test_peer_orfao_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"].append({
        "afi": "ipv4", "peer": "203.0.113.9", "asn": 64512,
        "estado": "Established", "pref_rcv": 1, "up_down": "1d02h",
    })
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.orfaos"]
    assert itens[0].encontrado == "203.0.113.9"


def test_subinterface_ausente_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["interfaces"] = []
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["subinterface.ausente"]
    assert itens[0].esperado == "Eth-Trunk127.2"


def test_subinterface_estado_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["interfaces"][0]["phy"] = "*down"
    perfeito["interfaces"][0]["protocolo"] = "down"
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["subinterface.estado"]
    assert itens[0].esperado == "up"
    assert itens[0].encontrado == "*down/down"


def test_pontas_v4_e_v6_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, p = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["interfaces"][0]["enderecos_v4"] = []
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["ponta.v4"]
    assert itens[0].esperado == p["v4_sub"]

    perfeito2 = _recursos_perfeitos(db_session, env)
    perfeito2["interfaces"][0]["enderecos_v6"] = []
    _snapshot(db_session, env, **perfeito2)
    itens2 = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens2] == ["ponta.v6"]
    assert itens2[0].esperado == p["v6_l"]


def test_circuito_sem_trunk_vira_aviso(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env = _ambiente(db_session)
    circ_id = _circuito_sem_trunk(db_session, env)
    _sessao(db_session, env, circ_id, afi="ipv4")
    p = _pontas(db_session, circ_id)
    _snapshot(
        db_session, env,
        peers=[{"afi": "ipv4", "peer": p["v4_r"], "asn": 64512, "estado": "Established",
                "pref_rcv": 1, "up_down": "1d02h"}],
    )
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["circuito.sem_trunk"]
    assert itens[0].severidade == "aviso"


def test_sessao_desativada_nao_gera_peer_ausente(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device
    from gerenet.domain.services.bgp_sessions import disable_session

    env = _ambiente(db_session)
    circ_id = _circuito_completo(db_session, env)
    sessao_id = _sessao(db_session, env, circ_id, afi="ipv4")
    disable_session(db_session, sessao_id, actor="cli")
    _snapshot(db_session, env)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert itens == []  # sem sessões ativas, nada a comparar


def test_snapshot_parcial_omite_recurso_e_avisa(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    _snapshot(db_session, env, status="partial", sem=("interfaces",), **perfeito)
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert resultado.aviso is not None and "interfaces" in resultado.aviso
    assert not any(i.tipo.startswith("subinterface") or i.tipo.startswith("ponta") for i in resultado.items)


def test_snapshot_de_outro_device_rejeitado(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    snap_id = _snapshot(db_session, env)
    outro = _ambiente(db_session)
    with pytest.raises(ValidationError, match="pertence ao device"):
        reconciliar_device(db_session, outro["ne_id"], snapshot_id=snap_id)
    with pytest.raises(NotFoundError):
        reconciliar_device(db_session, env["ne_id"], snapshot_id=9999)
    # só snapshot_id: device derivado do snapshot
    assert reconciliar_device(db_session, None, snapshot_id=snap_id).device_id == env["ne_id"]


def test_reconciliar_usa_o_snapshot_mais_recente(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    _snapshot(db_session, env, **perfeito)  # perfeito
    ruim = dict(perfeito)
    ruim["bgp_peers"] = [linha for linha in perfeito["bgp_peers"] if linha["afi"] == "ipv4"]
    _snapshot(db_session, env, **ruim)  # mais recente: sem o peer v6
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.ausente"]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.automation.reconcile'`.

- [ ] **Step 3: Implementar `reconciliar_device`**

Criar `src/gerenet/automation/reconcile.py`:

```python
"""Divergência desejado × encontrado, read-only (spec ciclo B §6).

Renderiza o desejado do device (render_desejado) e compara com o snapshot
mais recente (ou o snapshot_id pedido). Sem tabela nova; sem efeitos no
equipamento. Itens tipados {tipo, severidade, esperado, encontrado, acao}.
"""
import ipaddress
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation.render import BlocoRender, render_desejado
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import NotFoundError, ValidationError

ESTABLISHED = "Established"


@dataclass
class ReconcileItem:
    tipo: str
    severidade: str  # critica | atencao | aviso
    esperado: str
    encontrado: str
    acao: str


@dataclass
class ReconcileResult:
    device_id: int
    snapshot_id: int | None
    aviso: str | None
    items: list[ReconcileItem] = field(default_factory=list)


def _item(tipo: str, severidade: str, esperado: str, encontrado: str, acao: str) -> ReconcileItem:
    return ReconcileItem(
        tipo=tipo, severidade=severidade, esperado=esperado,
        encontrado=encontrado, acao=acao,
    )


def _esperado_subinterfaces(blocos: list[BlocoRender]) -> dict[str, dict[str, list[str]]]:
    """Subinterfaces esperadas a partir dos blocos renderizados (ruling 7).

    Devolve {nome: {"v4": [addr/len], "v6": [addr/126]}} — parse dos padrões de
    linha que o próprio render emite (contrato T3/T4).
    """
    esperadas: dict[str, dict[str, list[str]]] = {}
    for bloco in blocos:
        if bloco.tipo != "subinterface" or not bloco.comandos:
            continue
        nome = bloco.comandos[0].removeprefix("interface ")
        registro = esperadas.setdefault(nome, {"v4": [], "v6": []})
        for linha in bloco.comandos[1:]:
            if linha.startswith("ip address "):
                endereco, mascara = linha.removeprefix("ip address ").split()
                prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{mascara}").prefixlen
                registro["v4"].append(f"{endereco}/{prefixlen}")
            elif linha.startswith("ipv6 address "):
                registro["v6"].append(linha.removeprefix("ipv6 address "))
    return esperadas


def reconciliar_device(
    session: Session, device_id: int | None = None, *, snapshot_id: int | None = None
) -> ReconcileResult:
    """Compara o desejado renderizado do device com o snapshot (spec §6)."""
    if snapshot_id is not None:
        snap = session.get(models.DeviceSnapshot, snapshot_id)
        if snap is None:
            raise NotFoundError(f"Snapshot {snapshot_id} não encontrado.")
        if device_id is None:
            device_id = snap.device_id
        elif snap.device_id != device_id:
            raise ValidationError(f"Snapshot {snapshot_id} não pertence ao device {device_id}.")
    if device_id is None:
        raise ValidationError("Informe device_id ou snapshot_id para reconciliar.")
    get_device(session, device_id)  # NotFoundError propaga (404 na API)

    if snapshot_id is None:
        snap = (
            session.query(models.DeviceSnapshot)
            .filter_by(device_id=device_id)
            .order_by(models.DeviceSnapshot.id.desc())
            .first()
        )
    recursos = snap.resources if snap is not None else {}
    render = render_desejado(session, device_id)
    items: list[ReconcileItem] = []
    avisos: list[str] = []

    if snap is None:
        avisos.append("Sem snapshot para comparar — colete o device antes (gerenet collect).")
    else:
        for recurso in ("interfaces", "bgp_peers", "bgp_peers_verbose"):
            if recurso not in recursos:
                avisos.append(f"Snapshot {snap.id} sem o recurso '{recurso}' — comparação parcial.")

    tem_interfaces = "interfaces" in recursos
    tem_peers = "bgp_peers" in recursos
    tem_verbose = "bgp_peers_verbose" in recursos

    por_peer_verbose = (
        {(linha["afi"], linha["peer"]): linha for linha in recursos.get("bgp_peers_verbose", [])}
        if snap is not None and tem_verbose else {}
    )
    por_peer_encontrado = (
        {(linha["afi"], linha["peer"]): linha for linha in recursos.get("bgp_peers", [])}
        if snap is not None and tem_peers else {}
    )

    # nomes de RP por sessão (esperados nos filtros): 1ª linha dos blocos
    rp_por_sessao: dict[int, dict[str, str]] = {}
    for bloco in render.blocos:
        if bloco.tipo in ("route_policy_import", "route_policy_export") and bloco.comandos:
            rp_por_sessao.setdefault(bloco.objeto_id, {})[bloco.tipo] = (
                bloco.comandos[0].removeprefix("route-policy ").split()[0]
            )

    # ---- subinterfaces e pontas (só com o recurso presente) ----
    if snap is not None and tem_interfaces:
        por_nome_interface = {i["nome"]: i for i in recursos.get("interfaces", [])}
        for nome, enderecos in sorted(_esperado_subinterfaces(render.blocos).items()):
            achada = por_nome_interface.get(nome)
            if achada is None:
                items.append(_item(
                    "subinterface.ausente", "critica", nome, "não listada",
                    "Recriar/verificar a subinterface no equipamento.",
                ))
                continue
            estado = f"{achada.get('phy')}/{achada.get('protocolo')}"
            if achada.get("phy") != "up" or achada.get("protocolo") != "up":
                items.append(_item(
                    "subinterface.estado", "atencao", "up", estado,
                    "Verificar o estado físico/protocolo da subinterface.",
                ))
            for ponta in enderecos["v4"]:
                if ponta not in achada.get("enderecos_v4", []):
                    items.append(_item(
                        "ponta.v4", "critica", ponta,
                        ", ".join(achada.get("enderecos_v4", []) or ["—"]),
                        "Endereço local v4 ausente na subinterface.",
                    ))
            for ponta in enderecos["v6"]:
                if ponta not in achada.get("enderecos_v6", []):
                    items.append(_item(
                        "ponta.v6", "critica", ponta,
                        ", ".join(achada.get("enderecos_v6", []) or ["—"]),
                        "Endereço local v6 ausente na subinterface.",
                    ))

    # ---- peers ----
    if snap is not None and tem_peers:
        circuitos_reservados: dict[int, models.Circuit] = {}
        for sessao in list_sessions(session, device_id=device_id):
            esperado = por_peer_encontrado.get((sessao.afi, sessao.remote_address))
            if esperado is None:
                items.append(_item(
                    "peer.ausente", "critica", sessao.remote_address, "não listado",
                    "Sessão ativa no SoT sem peer configurado/estabelecido no equipamento.",
                ))
                continue
            if esperado.get("asn") != sessao.asn_remote:
                items.append(_item(
                    "peer.asn", "critica", str(sessao.asn_remote), str(esperado.get("asn")),
                    "ASN do peer diverge do cadastrado.",
                ))
            estado = str(esperado.get("estado", ""))
            if sessao.shutdown:
                if estado == ESTABLISHED:
                    items.append(_item(
                        "peer.shutdown_admin", "atencao", "não Established", estado,
                        "Sessão em shutdown admin não deveria estar Established.",
                    ))
            elif estado != ESTABLISHED:
                items.append(_item(
                    "peer.estado", "atencao", ESTABLISHED, estado,
                    "Peer fora de Established — conferir se é transitório.",
                ))
            verbose = por_peer_verbose.get((sessao.afi, sessao.remote_address))
            rps = rp_por_sessao.get(sessao.id, {})
            if verbose is not None:
                for tipo_rp, campo in (
                    ("route_policy_import", "filtro_import"),
                    ("route_policy_export", "filtro_export"),
                ):
                    if tipo_rp in rps and verbose.get(campo) != rps[tipo_rp]:
                        items.append(_item(
                            "peer.filtros", "critica", rps[tipo_rp],
                            str(verbose.get(campo) or "—"),
                            "Filtro aplicado no equipamento diverge do renderizado (nomes §25.4).",
                        ))
            circ = session.get(models.Circuit, sessao.circuit_id)
            if circ is not None:
                circuitos_reservados.setdefault(circ.id, circ)

        # circuito.sem_trunk: reservado (tem Vlan) + sessão ativa, sem edge_trunk
        if tem_interfaces:
            for circ in circuitos_reservados.values():
                tem_vlan = session.scalars(
                    select(models.Vlan.id).where(models.Vlan.circuit_id == circ.id).limit(1)
                ).first() is not None
                if circ.edge_trunk is None and tem_vlan:
                    items.append(_item(
                        "circuito.sem_trunk", "aviso", f"edge_trunk de {circ.code}",
                        "não cadastrado",
                        "Cadastrar circuits.edge_trunk para comparar a subinterface.",
                    ))

        # órfãos: peer no snapshot sem sessão ativa (afi, remote)
        ativos = {(s.afi, s.remote_address) for s in list_sessions(session, device_id=device_id)}
        for (afi, peer), linha in sorted(por_peer_encontrado.items()):
            if (afi, peer) not in ativos:
                items.append(_item(
                    "peer.orfaos", "atencao", "sessão no SoT", f"{afi} {peer}",
                    "Peer coletado sem sessão ativa cadastrada — órfão ou cadastro incompleto.",
                ))

    itens = sorted(items, key=lambda i: (i.tipo, i.esperado))
    return ReconcileResult(
        device_id=device_id,
        snapshot_id=snap.id if snap is not None else None,
        aviso="; ".join(avisos) if avisos else None,
        items=itens,
    )
```

> Observação de execução: o `if snap is not None and tem_peers:` garante que, sem snapshot, nenhum `peer.ausente` é emitido (só o aviso) — contrato de `test_sem_snapshot_devolve_aviso`. O loop de `circuito.sem_trunk` e o de órfãos vivem **dentro** deste `if`, nas mesmas condições de `tem_interfaces`/`tem_peers` mostradas acima.

- [ ] **Step 4: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_reconcile.py -v`
Expected: PASS (13 testes). Se algum tipo de item sobrar/faltar, conferir esperados contra os literais dos testes.

- [ ] **Step 5: Suíte inteira**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/reconcile.py tests/automation/test_reconcile.py
git commit -m "feat(SoT): divergência read-only reconciliar_device (spec ciclo B §6)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: API — communities, associações, reconciliation, desired-config

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (novos schemas ao fim do arquivo; `datetime` já importado)
- Create: `src/gerenet/api/routers/communities.py`
- Modify: `src/gerenet/api/routers/bgp_sessions.py` (importer `models` se ausente; rotas de associação)
- Create: `src/gerenet/api/routers/reconciliation.py`
- Modify: `src/gerenet/api/main.py` (include_router)
- Create: `tests/api/test_communities_api.py`, `tests/api/test_reconciliation_api.py`

**Interfaces:**
- Consumes: `list_communities`/`get_community` (services/communities.py — já existem); `get_session`/`add_community(session, session_id, community_id, *, actor)`/`remove_community(...)` (services/bgp_sessions.py — já existem e são idempotentes); `reconciliar_device` (T5); `render_desejado` (T4); schemas de circuito (T2).
- Produces: schemas e rotas do ruling 9 — consumidos por T7 (CLI usa os mesmos serviços, não estes routers).

- [ ] **Step 1: Schemas**

Ao fim de `src/gerenet/domain/schemas.py`:

```python
class BgpSessionCommunityIn(BaseModel):
    community_id: int


class CommunityOut(BaseModel):
    id: int
    name: str
    notes: str | None = None


class BlocoOut(BaseModel):
    tipo: str
    objeto: str
    objeto_id: int
    comandos: list[str]


class DesiredConfigOut(BaseModel):
    device_id: int
    gerado_em: datetime
    texto: str
    blocos: list[BlocoOut]


class ReconcileItemOut(BaseModel):
    tipo: str
    severidade: str
    esperado: str
    encontrado: str
    acao: str


class ReconcileOut(BaseModel):
    device_id: int
    snapshot_id: int | None
    aviso: str | None
    gerado_em: datetime
    items: list[ReconcileItemOut]
```

- [ ] **Step 2: Testes de API que falham**

Criar `tests/api/test_communities_api.py`:

```python
"""Communities (catálogo read-only) e associações sessão ↔ community (spec §8)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.schemas import (
    BgpSessionCreate, CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate,
)
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _sessao(db_session: Session) -> int:
    site = create_site(db_session, SiteCreate(name="pop-com-api"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Com API", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-com-api", management_address="10.40.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-com-api", management_address="10.40.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-COM-API", organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id,
        ),
        actor="cli",
    ).id
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ_id, device_id=ne.id, afi="ipv4",
            local_address="100.64.40.1", remote_address="100.64.40.2",
        ),
        actor="cli",
    ).id


def test_lista_communities_read_only(client: TestClient, db_session: Session) -> None:
    lista = client.get("/api/v1/communities", headers=_auth())
    assert lista.status_code == 200
    assert [c["name"] for c in lista.json()] == ["blackhole", "no-advertise", "no-export"]
    assert client.post("/api/v1/communities", json={}, headers=_auth()).status_code == 405
    assert client.delete("/api/v1/communities/1", headers=_auth()).status_code == 405


def test_associa_e_desassocia_community(client: TestClient, db_session: Session) -> None:
    sessao_id = _sessao(db_session)
    comunidade = client.get("/api/v1/communities", headers=_auth()).json()[0]  # blackhole

    post = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities",
        json={"community_id": comunidade["id"]}, headers=_auth(),
    )
    assert post.status_code == 200, post.text
    assert post.json() == {"session_id": sessao_id, "community_id": comunidade["id"]}

    repete = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities",
        json={"community_id": comunidade["id"]}, headers=_auth(),
    )
    assert repete.status_code == 200  # idempotente

    remove = client.delete(
        f"/api/v1/bgp-sessions/{sessao_id}/communities/{comunidade['id']}", headers=_auth()
    )
    assert remove.status_code == 204
    remove2 = client.delete(
        f"/api/v1/bgp-sessions/{sessao_id}/communities/{comunidade['id']}", headers=_auth()
    )
    assert remove2.status_code == 204  # no-op idempotente


def test_associacao_inexistente_da_404(client: TestClient, db_session: Session) -> None:
    sessao_id = _sessao(db_session)
    assert client.post(
        "/api/v1/bgp-sessions/9999/communities", json={"community_id": 1}, headers=_auth()
    ).status_code == 404
    assert client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities", json={"community_id": 9999},
        headers=_auth(),
    ).status_code == 404
    assert client.delete(
        f"/api/v1/bgp-sessions/{sessao_id}/communities/9999", headers=_auth()
    ).status_code == 404
```

Criar `tests/api/test_reconciliation_api.py` (imports completos no topo: `ipaddress`, `select`, `models`, `pontas_v4`, `pontas_v6`, `reservar_circuito`, `list_policy_profiles`, `create_authorization`, `PrefixAuthorizationCreate`, além dos de `_sessao`):

```python
"""Reconciliation (GET /reconciliation) e desired-config (spec §8)."""
import ipaddress

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate, CircuitCreate, DeviceCreate, OrganizationCreate,
    PrefixAuthorizationCreate, SiteCreate,
)
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente_dual(db_session: Session) -> dict:
    """Circuito reservado dual + autorizações v4/v6 + sessões com perfil full."""
    site = create_site(db_session, SiteCreate(name="pop-rec-api"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Rec API", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-rec-api", management_address="10.41.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-rec-api", management_address="10.41.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-REC-API", organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id,
            edge_trunk="Eth-Trunk127",
        ),
        actor="cli",
    ).id
    reservar_circuito(db_session, circ_id, actor="cli")
    for familia, prefixo in (("ipv4", "192.0.2.0/24"), ("ipv6", "2001:DB8::/32")):
        create_authorization(
            db_session, PrefixAuthorizationCreate(
                organization_id=org.id, family=familia, prefix=prefixo,
            ), actor="cli",
        )
    full = next(p.id for p in list_policy_profiles(db_session, direction="export") if p.name == "full")
    redes = {
        int(ipaddress.ip_network(l.n).version): l.n
        for l in db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    }
    for afi in ("ipv4", "ipv6"):
        local, remota = pontas_v4(redes[4]) if afi == "ipv4" else pontas_v6(redes[6])
        create_session(
            db_session,
            BgpSessionCreate(
                circuit_id=circ_id, device_id=ne.id, afi=afi,
                local_address=local.removesuffix("/126"),
                remote_address=remota.removesuffix("/126"),
                export_profile_id=full,
            ),
            actor="cli",
        )
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _snapshot_vazio(db_session: Session, ne_id: int) -> int:
    snap = models.DeviceSnapshot(
        device_id=ne_id, status="success",
        resources={
            "version": {"version": "8.210"},
            "interfaces": [], "bgp_peers": [], "bgp_peers_verbose": [],
        },
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap.id


def test_reconciliation_200_com_aviso(client: TestClient, db_session: Session) -> None:
    env = _ambiente_dual(db_session)
    resp = client.get(f"/api/v1/reconciliation?device_id={env['ne_id']}", headers=_auth())
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["device_id"] == env["ne_id"]
    assert corpo["snapshot_id"] is None
    assert corpo["aviso"] and corpo["gerado_em"]
    assert corpo["items"] == []  # sem snapshot: só aviso (spec §6)


def test_reconciliation_por_snapshot_id(client: TestClient, db_session: Session) -> None:
    env = _ambiente_dual(db_session)
    snap_id = _snapshot_vazio(db_session, env["ne_id"])
    resp = client.get(f"/api/v1/reconciliation?snapshot_id={snap_id}", headers=_auth())
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["snapshot_id"] == snap_id
    tipos = [i["tipo"] for i in corpo["items"]]
    assert "peer.ausente" in tipos  # sessões ativas vs. snapshot vazio
    assert "subinterface.ausente" in tipos
    assert all(i["acao"] for i in corpo["items"])

    sem_filtro = client.get("/api/v1/reconciliation", headers=_auth())
    assert sem_filtro.status_code == 400
    ambos = client.get(
        f"/api/v1/reconciliation?device_id=1&snapshot_id={snap_id}", headers=_auth()
    )
    assert ambos.status_code == 400  # filtros excludentes (ruling 9)


def test_reconciliation_404s(client: TestClient, db_session: Session) -> None:
    assert client.get("/api/v1/reconciliation?device_id=9999", headers=_auth()).status_code == 404
    assert client.get("/api/v1/reconciliation?snapshot_id=9999", headers=_auth()).status_code == 404


def test_desired_config(client: TestClient, db_session: Session) -> None:
    env = _ambiente_dual(db_session)
    resp = client.get(f"/api/v1/devices/{env['ne_id']}/desired-config", headers=_auth())
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["device_id"] == env["ne_id"]
    assert corpo["texto"]
    tipos = [b["tipo"] for b in corpo["blocos"]]
    assert tipos[0:4] == ["subinterface", "prefix_list", "route_policy_import", "route_policy_export"]
    assert any(b["objeto"] == "circuit" for b in corpo["blocos"])
    assert "password" not in resp.text  # regra global: senha nunca no payload

    assert client.get("/api/v1/devices/9999/desired-config", headers=_auth()).status_code == 404
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/api/test_communities_api.py tests/api/test_reconciliation_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.api.routers.communities'` / `…reconciliation`.

- [ ] **Step 4: Implementar routers e registrar no main**

`src/gerenet/api/routers/communities.py`:

```python
"""Catálogo de communities (§25.6) — read-only no ciclo B (spec §8)."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import CommunityOut
from gerenet.domain.services import communities as svc

router = APIRouter(
    prefix="/api/v1/communities", tags=["communities"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[CommunityOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_communities(session, include_disabled=include_disabled)
```

Rotas de associação — adicionar ao fim de `src/gerenet/api/routers/bgp_sessions.py` (o arquivo já importa `HTTPException`, `NotFoundError`/`ConflictError`/`ValidationError` e o alias `svc`; **acrescentar** `from gerenet.domain import models` e `BgpSessionCommunityIn` ao import de `gerenet.domain.schemas` — confirmados como ausentes hoje):

```python
@router.post("/{session_id}/communities", status_code=200)
def associar_community(
    session_id: int, data: BgpSessionCommunityIn, session: SessionDep
) -> dict[str, int]:
    """Associa uma community à sessão — idempotente (P2; spec §8)."""
    try:
        svc.get_session(session, session_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session.get(models.Community, data.community_id) is None:
        raise HTTPException(status_code=404, detail=f"Community {data.community_id} não encontrada.")
    svc.add_community(session, session_id, data.community_id, actor="api")
    return {"session_id": session_id, "community_id": data.community_id}


@router.delete("/{session_id}/communities/{community_id}", status_code=204)
def desassociar_community(session_id: int, community_id: int, session: SessionDep) -> None:
    """Desassocia uma community — idempotente (P2; spec §8)."""
    try:
        svc.get_session(session, session_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session.get(models.Community, community_id) is None:
        raise HTTPException(status_code=404, detail=f"Community {community_id} não encontrada.")
    svc.remove_community(session, session_id, community_id, actor="api")
```

> A rota retorna `dict[str, int]` (não `BgpSessionOut`) — ruling 9. O FastAPI dita 200 no POST (contrato do teste) e 204 sem corpo no DELETE.

`src/gerenet/api/routers/reconciliation.py`:

```python
"""Reconciliation (divergência read-only) e desired-config (spec §8)."""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.automation.reconcile import reconciliar_device
from gerenet.automation.render import render_desejado
from gerenet.db import get_db
from gerenet.domain.schemas import BlocoOut, DesiredConfigOut, ReconcileItemOut, ReconcileOut
from gerenet.domain.services.errors import NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/reconciliation", tags=["reconciliation"],
    dependencies=[Depends(require_api_key)],
)
config_router = APIRouter(
    prefix="/api/v1/devices", tags=["devices"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ReconcileOut)
def reconciliar(
    session: SessionDep, device_id: int | None = None, snapshot_id: int | None = None
) -> ReconcileOut:
    """Divergência desejado × encontrado; exatamente um filtro (ruling 9)."""
    if (device_id is None) == (snapshot_id is None):
        raise HTTPException(
            status_code=400, detail="Informe exatamente um de device_id ou snapshot_id."
        )
    try:
        resultado = reconciliar_device(session, device_id, snapshot_id=snapshot_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReconcileOut(
        device_id=resultado.device_id,
        snapshot_id=resultado.snapshot_id,
        aviso=resultado.aviso,
        gerado_em=datetime.now(UTC),
        items=[ReconcileItemOut(**vars(i)) for i in resultado.items],
    )


@config_router.get("/{device_id}/desired-config", response_model=DesiredConfigOut)
def config_desejada(device_id: int, session: SessionDep) -> DesiredConfigOut:
    """Blocos de configuração desejada do device (render puro, read-only)."""
    try:
        resultado = render_desejado(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DesiredConfigOut(
        device_id=resultado.device_id,
        gerado_em=datetime.now(UTC),
        texto=resultado.texto,
        blocos=[BlocoOut(tipo=b.tipo, objeto=b.objeto, objeto_id=b.objeto_id, comandos=b.comandos)
                for b in resultado.blocos],
    )
```

Em `src/gerenet/api/main.py`: acrescentar ao import e aos `include_router`:

```python
    communities,
    reconciliation,
```
```python
    app.include_router(communities.router)
    app.include_router(reconciliation.router)
    app.include_router(reconciliation.config_router)
```

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/api/test_communities_api.py tests/api/test_reconciliation_api.py -v`
Expected: PASS.

- [ ] **Step 6: Suíte inteira**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/api/routers/ tests/api/
git commit -m "feat(SoT): API de communities, associações, reconciliation e desired-config (ciclo B §8)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: CLI — communities, community add/remove, render-config e reconcile

**Files:**
- Create: `src/gerenet/cli/communities.py`
- Modify: `src/gerenet/cli/bgp_sessions.py` (imports + sub-app `community`)
- Create: `src/gerenet/cli/reconcile.py` (funções Typer `render_config`/`reconcile`)
- Modify: `src/gerenet/cli/main.py` (`app.command(name=…)(fn)`)
- Modify: `tests/cli/test_cli_smoke.py` (novos testes; `models`/`select`/schemas já importados no topo do arquivo — verificados)

**Interfaces:**
- Consumes: `list_communities`/`get_community`; `get_session`/`add_community`/`remove_community` (services existentes); `render_desejado` (T4); `reconciliar_device` (T5); `get_device`/`list_devices` (services/devices.py).
- Produces: comandos smoke-testáveis (ids sequenciais "1" por teste via TRUNCATE RESTART IDENTITY).

- [ ] **Step 1: Testes que falham**

Adicionar ao fim de `tests/cli/test_cli_smoke.py`:

```python
def test_cli_communities_lista(db_session: Session) -> None:
    lista = runner.invoke(app, ["communities", "list"])
    assert lista.exit_code == 0, lista.output
    assert "blackhole" in lista.output
    assert "no-export" in lista.output


def test_cli_bgp_sessions_community_add_remove(db_session: Session) -> None:
    from gerenet.domain import models
    from sqlalchemy import select

    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-COM")
    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.13.1", "--remote-address", "100.64.13.2",
        ],
    )
    assert add.exit_code == 0, add.output

    comunidade = db_session.scalar(
        select(models.Community).where(models.Community.name == "blackhole")
    )
    assert comunidade is not None

    associa = runner.invoke(app, ["bgp-sessions", "community", "add", "1", str(comunidade.id)])
    assert associa.exit_code == 0, associa.output
    assert "associada" in associa.output
    vinculo = db_session.scalar(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == 1,
            models.BgpSessionCommunity.community_id == comunidade.id,
        )
    )
    assert vinculo is not None

    remove = runner.invoke(app, ["bgp-sessions", "community", "remove", "1", comunidade.name])
    assert remove.exit_code == 0, remove.output
    assert "desassociada" in remove.output
    assert db_session.scalar(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == 1,
            models.BgpSessionCommunity.community_id == comunidade.id,
        )
    ) is None


def test_cli_render_config_e_reconcile(db_session: Session) -> None:
    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-REC")
    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.14.1", "--remote-address", "100.64.14.2",
        ],
    )
    assert add.exit_code == 0, add.output

    render = runner.invoke(app, ["render-config", "ne-bgp-cli"])
    assert render.exit_code == 0, render.output
    assert "bgp 64610" in render.output  # asn do device do _ambiente_bgp
    assert "peer 100.64.14.2 as-number 64513" in render.output  # org = ASN do par

    rec = runner.invoke(app, ["reconcile", "ne-bgp-cli"])
    assert rec.exit_code == 0, rec.output
    assert "snapshot" in rec.output.lower()  # aviso orientando coleta

    faltante = runner.invoke(app, ["render-config", "nao-existe"])
    assert faltante.exit_code == 1
    assert "não encontrado" in faltante.output
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/cli/test_cli_smoke.py -k "communities or community or render_config or reconcile" -v`
Expected: FAIL — `No such command 'communities'` etc.

- [ ] **Step 3: Implementar**

`src/gerenet/cli/communities.py`:

```python
"""Communities (catálogo somente leitura) — spec ciclo B §8."""
import typer

from gerenet.db import get_session
from gerenet.domain.services import communities as svc

app = typer.Typer(help="Communities BGP (catálogo somente leitura).")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista o catálogo de communities."""
    with get_session() as session:
        for com in svc.list_communities(session, include_disabled=include_disabled):
            typer.echo(f"{com.id:>3}  {com.name:<16} {com.notes or ''}")
```

Em `src/gerenet/cli/bgp_sessions.py` — acrescentar imports e o sub-app (o arquivo já importa `svc` e `GerenetError`):

```python
from gerenet.domain.services import communities as com_svc
from gerenet.domain.services.errors import GerenetError, NotFoundError
```
```python
community = typer.Typer(help="Associa/desassocia community de uma sessão BGP.")
app.add_typer(community, name="community")


def _resolver_community(session, comunidade: str):
    """Community por ID ou nome; None se não existir."""
    if comunidade.isdigit():
        try:
            return com_svc.get_community(session, int(comunidade))
        except NotFoundError:
            return None
    return next((c for c in com_svc.list_communities(session) if c.name == comunidade), None)


@community.command("add")
def associar(
    session_id: int = typer.Argument(..., help="ID da sessão BGP."),
    community: str = typer.Argument(..., help="ID ou nome da community."),
) -> None:
    """Associa uma community à sessão (idempotente)."""
    with get_session() as session:
        try:
            sessao = svc.get_session(session, session_id)
            com = _resolver_community(session, community)
            if com is None:
                typer.echo(f"Community {community} não encontrada.", err=True)
                raise typer.Exit(1)
            svc.add_community(session, sessao.id, com.id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Community {com.name} associada à sessão BGP {session_id}.")


@community.command("remove")
def desassociar(
    session_id: int = typer.Argument(..., help="ID da sessão BGP."),
    community: str = typer.Argument(..., help="ID ou nome da community."),
) -> None:
    """Desassocia uma community da sessão (idempotente)."""
    with get_session() as session:
        try:
            sessao = svc.get_session(session, session_id)
            com = _resolver_community(session, community)
            if com is None:
                typer.echo(f"Community {community} não encontrada.", err=True)
                raise typer.Exit(1)
            svc.remove_community(session, sessao.id, com.id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Community {com.name} desassociada da sessão BGP {session_id}.")
```

`src/gerenet/cli/reconcile.py`:

```python
"""Render da configuração desejada e divergência (somente leitura) — spec §8."""
from sqlalchemy.orm import Session

import typer

from gerenet.automation.reconcile import reconciliar_device
from gerenet.automation.render import render_desejado
from gerenet.db import get_session
from gerenet.domain.services import devices as dev_svc
from gerenet.domain.services.errors import GerenetError, NotFoundError


def _device(session: Session, device: str):
    """Device por ID ou nome; None se não existir."""
    if device.isdigit():
        try:
            return dev_svc.get_device(session, int(device))
        except NotFoundError:
            return None
    return next(
        (d for d in dev_svc.list_devices(session, include_disabled=True) if d.name == device),
        None,
    )


def _resolve(session: Session, device: str):
    encontrado = _device(session, device)
    if encontrado is None:
        typer.echo("Equipamento não encontrado.", err=True)
        raise typer.Exit(1)
    return encontrado


def render_config(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Mostra os blocos de configuração desejada do device."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = render_desejado(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    if not resultado.blocos:
        typer.echo(f"{encontrado.name}: nada a renderizar.")
        return
    for i, bloco in enumerate(resultado.blocos, start=1):
        typer.echo(f"# bloco {i}: {bloco.tipo} ({bloco.objeto} {bloco.objeto_id})")
        for linha in bloco.comandos:
            typer.echo(linha)


def reconcile(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Compara o desejado renderizado com o snapshot (divergência read-only)."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = reconciliar_device(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Equipamento {encontrado.name}:")
    if resultado.aviso:
        typer.echo(f"Aviso: {resultado.aviso}")
    if not resultado.items:
        typer.echo("Sem divergências.")
        return
    for item in resultado.items:
        typer.echo(
            f"[{item.severidade.upper()}] {item.tipo}: esperado {item.esperado} "
            f"| encontrado {item.encontrado} — {item.acao}"
        )
```

Em `src/gerenet/cli/main.py` — imports e registros:

```python
    communities,
    reconcile,
```
```python
app.add_typer(communities.app, name="communities", help="Communities BGP.")
app.command(name="render-config")(reconcile.render_config)
app.command(name="reconcile")(reconcile.reconcile)
```

> `app.command(name=…)(fn)` é o uso funcional do decorator Typer — registra `render-config`/`reconcile` como comandos top-level do app (exatamente `gerenet render-config <device>` / `gerenet reconcile <device>`), distintos de grupos (`add_typer`). O Typer usa a docstring da função como help.

- [ ] **Step 4: Rodar para ver passar**

Run: `uv run pytest tests/cli/test_cli_smoke.py -k "communities or community or render_config or reconcile" -v`
Expected: PASS.

- [ ] **Step 5: Suíte inteira**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/cli/ tests/cli/test_cli_smoke.py
git commit -m "feat(SoT): CLI de communities, community add/remove, render-config e reconcile (ciclo B §8)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Varredura final — cobertura da spec, suíte verde, lint

**Files:**
- Nenhum arquivo novo; revisão + corrida final (corrigir inline o que falhar).

- [ ] **Step 1: Varredura de cobertura da spec** (cada linha aponta a entrega)

| Especificação | Onde está |
|---|---|
| §5.1 derivador de nomes (golden ASN 64500, bordas 1/2³²-1, ≤63) | T1 `test_naming.py` |
| §5.2 5 templates atômicos | T3 `test_templates.py` (8 goldens) |
| §5.2 entrada completa, saída ordenada (§5.2 TIPO_ORDEM) e anotada | T4 `test_render_dual_completo_ordenado` |
| §5.2 senha nunca emitida (só comentário com path) | T3 golden do peer + T4 `test_render_senha_vira_so_comentario` |
| §5.2 idempotência (render 2×) | T4 `test_render_idempotente` |
| §6 divergência read-only sem tabela nova | T5 `test_reconcile.py` (13 testes; um por tipo do §6 + sem-snapshot + desativada + parcial + outro device + mais recente) |
| §6 snapshot ausente → aviso, sem erro | T5 + T6 (`test_reconciliation_200_com_aviso`) |
| §6 itens `{tipo, severidade, esperado, encontrado, acao}` PT-BR | T5 dataclass + T6 `ReconcileItemOut` |
| §7 migration única (edge_trunk nullable + seed import) | T2 (migration + upgrade/downgrade) |
| §7 seed `somente-autorizadas` destrava `import_profile_id` | T2 `test_sessao_aceita_perfil_de_importacao_seedado` |
| §8 `GET /reconciliation` (um filtro; 404/400) | T6 |
| §8 `GET /devices/{id}/desired-config` | T6 `test_desired_config` |
| §8 communities read-only + associações idempotentes com 404 | T6 `test_communities_api.py` |
| §8 policy-profiles com `direction=import` (seed visível) | T2 (3 arquivos de catálogo) |
| §8 circuits `edge_trunk` no cadastro/atualização (POST/PATCH/CLI) | T2 |
| §8 CLI `reconcile`/`render-config`/`communities list`/`community add|remove` | T7 smoke |
| §10 unit render/divergência com golden e snapshot sintético | T3/T4/T5 |
| §10 migration upgrade/downgrade limpos | T2 Step 2 |
| Regra de segredos no payload | T6 `test_desired_config` (`"password" not in resp.text`) |

- [ ] **Step 2: Placeholder scan**

Varrer o diff por `...`, `TODO`, `NotImplementedError`, funções sem uso, imports mortos, asserts triviais (`or True`), lambdas atribuídas e números duros de testes. Corrigir inline.

- [ ] **Step 3: Suíte completa + lint + smoke de help**

Run: `uv run pytest -q`
Expected: PASS.

```bash
uv run ruff check .
```

Expected: limpo.

```bash
uv run gerenet render-config --help
uv run gerenet reconcile --help
uv run gerenet communities list --help
uv run gerenet bgp-sessions community --help
```

Expected: quatro ajudas com os comandos criados, help em PT-BR.

- [ ] **Step 4: graphify update + commit final**

```bash
graphify update .
git add -A
git commit -m "chore(SoT): ciclo B2 — render da intenção e divergência desejado × encontrado

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

> Se `graphify update` falhar ou demorar, pular sem erro e registrar no commit message do report.

---

## Referências rápidas (para o executor)

- **Chain alembic**: `4b9aa889400e → a8acda79738d → 4132192e9f3b → d8458305ab7e → b1a71e5e129b` (head); `down_revision` da nova migration = `b1a71e5e129b`.
- **Banco de teste**: `gerenet_test` (conftest aborta se o nome não contém "test"); TRUNCATE não atinge `bgp_policy_profiles`/`communities` — seeds sobrevivem por teste.
- **Goldens de IPAM** (defaults `Settings`): 1ª reserva no site → v4 `100.64.0.0/31` (local `100.64.0.0`, mascara `255.255.255.254`, remota `.1`), v6 `2804:194C:1000::6400:0/126` (local `…6400:1`, remota `…6400:2`), VID `2`, subinterface `Eth-Trunk127.2`.
- **Nomes reais nos testes**: import `IP-PFX-<asn>-IN-<AFI>`/`RP-<asn>-IMPORT-<AFI>` com asn do par (org 64512 nos testes T4/T5; 64513 no CLI smoke); export `RP-<asn>-EXPORT-<AFI>`; produto default `IP-PFX-DEFAULT-<AFI>`.
- **`asn_local`** é coluna do modelo (`BigInteger`, default = `device.asn` no serviço) — o render e o `apply as-path` usam `sessao.asn_local`.
