# Default route, adoção de upstream e política importada — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir o sentido do `Default Route` da sessão BGP (passa a anunciar a default ao downstream), dar ao modal de adoção o `kind` da organização e a cadeia do upstream, levar acesso e tipo de policy ao cadastro do upstream, e permitir importar o nome da route-policy lida no equipamento.

**Architecture:** O render resolve o nome da route-policy num lugar só (`_nome_rp_import`/`_nome_rp_export`): a coluna nova manda quando preenchida, o §25.4 continua valendo quando é nula. O `kind` e o vínculo de upstream andam juntos na adoção, porque o render despacha o enlace pelo vínculo (`upstream_do_circuito`) enquanto `_autorizadas_clientes` filtra pelo `kind` — a organização operadora sem vínculo é o único estado em que os dois critérios discordam. Toda a escrita da adoção continua numa transação só (`commit=False` em cada serviço), agora com o upstream e o vínculo dentro dela.

**Tech Stack:** Python 3 + FastAPI + SQLAlchemy/Alembic + Typer + Jinja2 + pytest/ruff; React + Vite + TypeScript + Vitest/Playwright.

**Spec:** `docs/superpowers/specs/2026-09-16-gerenet-adocao-upstream-e-politicas-design.md`

## Global Constraints

- Idioma dos artefatos: **português (PT-BR)** — código, docstrings, mensagens de erro, testes, commits.
- Comandos de verificação: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build && npm run test`.
- Nenhuma implementação na `main`: a execução acontece em **worktree isolada** (`superpowers:using-git-worktrees`) antes do primeiro commit. O merge/push no checkout principal é do usuário.
- Nomes VRP ≤ **63 caracteres** (§25.4). O nome da route-policy pode deixar de derivar do ASN do par (§4.1) — exceção registrada; as demais regras seguem.
- Segredos nunca em log, snapshot, auditoria ou template (§19). O valor da senha do peer só existe no Vault.
- Migração: `down_revision = 'f2b7d4a91c3e'` (head atual). Confirmar com `uv run alembic heads` antes de escrever a revisão.
- `automation/discovery.py` e `domain/services/discovery.py` se importam mutuamente: **import tardio dentro da função** é a forma do repositório, não import no topo.
- `upstreams.py` importa `bgp_sessions`; a guarda de escopo de §3.5 entra em `bgp_sessions` por **import tardio dentro da função**.
- A conferência de fidelidade compara linhas como **conjunto** (`_normaliza_linhas`), então a posição da linha nova dentro do bloco não afeta o diff.

---

## Mapa de arquivos

| Arquivo | Responsabilidade | Tasks |
| --- | --- | --- |
| `alembic/versions/a3d1c7e5b9f2_adocao_upstream_e_politicas.py` | Quatro colunas + o `UPDATE` de §3.2 | 1 |
| `src/gerenet/domain/models.py` | Colunas novas em `BgpSession` e `Upstream` | 1 |
| `src/gerenet/automation/render.py` | `_nome_rp_import`/`_nome_rp_export`; `_bloco_import` sem a default; `_bloco_peer` com o campo novo | 2 |
| `src/gerenet/automation/templates/huawei_vrp/bgp_peer.j2` | `peer {{ peer }} default-route-advertise` | 2 |
| `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py` | Chave e ramo do `default-route-advertise` | 3 |
| `src/gerenet/domain/schemas.py` | Três campos na sessão; `upstream_id` no out; `AdocaoSessaoIn`, `AdocaoUpstreamIn`, `UpstreamCircuitoIn`, `UpstreamCreateIn`; `produto_import` | 4, 6, 8, 9 |
| `src/gerenet/domain/services/bgp_sessions.py` | Guarda de escopo de §3.5 | 4 |
| `src/gerenet/api/routers/bgp_sessions.py` | `upstream_id` na resposta | 4 |
| `src/gerenet/automation/discovery.py` | `_sessao_de`; texto de `politica_fora_do_padrao`; `politica_compartilhada`; upstream no ensaio | 5, 8 |
| `src/gerenet/domain/services/discovery.py` | `_DO_OPERADOR`; coerência §5.1; bloco do upstream; ordem §5.3; `bloco_do_upstream` | 6, 8 |
| `src/gerenet/domain/services/upstreams.py` | `produto_import`, `_CAMPOS_PROPAGACAO`, `commit=False`, `criar_com_circuito` | 7, 9 |
| `src/gerenet/api/routers/upstreams.py` | Corpo com o bloco `circuito` | 9 |
| `src/gerenet/api/routers/discovery.py` | Bloco do upstream no `fidelidade` | 9 |
| `src/gerenet/cli/bgp_sessions.py` | Três flags no `add` | 10 |
| `src/gerenet/cli/upstreams.py` | `--produto-import` e as opções de circuito | 10 |
| `web/src/api/types.ts`, `web/src/api/hooks.ts` | Campos novos e o bloco no `useFidelidade` | 11, 12, 13 |
| `web/src/pages/BgpSessions.tsx` | Checkbox por escopo | 11 |
| `web/src/pages/DiscoveryAdopt.tsx` | Select de `kind`, bloco do upstream, nomes por família | 12 |
| `web/src/pages/Upstreams.tsx`, `web/src/pages/UpstreamDetail.tsx` | Seção de acesso e `produto_import` | 13 |
| `web/src/help.ts` | Chaves novas | 11, 12, 13 |
| `docs/wiki/descoberta.md`, `docs/wiki/upstreams.md`, `CLAUDE.md` | O que o operador lê | 14 |

---

### Task 1: Migração, colunas e o `UPDATE` da cópia

**Files:**
- Create: `alembic/versions/a3d1c7e5b9f2_adocao_upstream_e_politicas.py`
- Modify: `src/gerenet/domain/models.py` (`BgpSession`, perto da linha 425; `Upstream`, perto da linha 821)
- Test: `tests/domain/test_bgp_models.py`

**Interfaces:**
- Consumes: nada.
- Produces: `models.BgpSession.default_route_advertise: bool`, `.import_route_policy: str | None`, `.export_route_policy: str | None`; `models.Upstream.produto_import: str | None`.

- [ ] **Step 1: Escrever o teste que falha**

No fim de `tests/domain/test_bgp_models.py`:

```python
def test_colunas_novas_da_politica_e_do_default(db_session: Session) -> None:
    """As quatro colunas da frente nascem no default (§3.1/§4.1/§7).

    `default_route_advertise` é o anúncio ao downstream e nasce falso; os dois
    nomes de política nascem nulos, que é o estado em que o render volta ao
    §25.4; `produto_import` nulo mantém o produto saindo do tipo do upstream.
    """
    env = _ambiente(db_session)
    sessao = models.BgpSession(
        circuit_id=env["circuit_id"], device_id=env["ne_id"], afi="ipv4",
        local_address="100.64.0.1", remote_address="100.64.0.2",
        asn_local=64600, asn_remote=64512,
    )
    db_session.add(sessao)
    db_session.commit()
    assert sessao.default_route_advertise is False
    assert sessao.import_route_policy is None
    assert sessao.export_route_policy is None

    up = models.Upstream(
        name="rt-up", tipo="transito", organization_id=env["org_id"], admin_status=True,
    )
    db_session.add(up)
    db_session.commit()
    assert up.produto_import is None
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run pytest -q tests/domain/test_bgp_models.py::test_colunas_novas_da_politica_e_do_default`
Expected: FAIL — `TypeError: 'default_route_advertise' is an invalid keyword argument for BgpSession`.

- [ ] **Step 3: Escrever a migração**

`alembic/versions/a3d1c7e5b9f2_adocao_upstream_e_politicas.py`:

```python
"""default route anunciado, política importada e produto do upstream

Revision ID: a3d1c7e5b9f2
Revises: f2b7d4a91c3e
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3d1c7e5b9f2'
down_revision: str | Sequence[str] | None = 'f2b7d4a91c3e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# §3.2: a cópia preserva a intenção de quem marcou "Default Route" — o efeito
# errado era o do render, e o anúncio só chega ao equipamento numa CR. As
# sessões de upstream ficam intactas: nelas o campo sempre significou aceitar a
# default do provedor. `circuit_id` é NOT NULL e único em `upstream_circuits`,
# então o `NOT IN` não tem o caso do NULL que engoliria a lista inteira.
_CAMINHO_DE_CLIENTE = """
UPDATE bgp_sessions
   SET default_route_advertise = allow_default_route,
       allow_default_route = false
 WHERE circuit_id NOT IN (SELECT circuit_id FROM upstream_circuits)
"""

_CAMINHO_DE_VOLTA = """
UPDATE bgp_sessions
   SET allow_default_route = default_route_advertise,
       default_route_advertise = false
 WHERE circuit_id NOT IN (SELECT circuit_id FROM upstream_circuits)
"""


def upgrade() -> None:
    """As colunas da frente e a cópia do default route (§3/§4/§7 do design)."""
    op.add_column(
        "bgp_sessions",
        sa.Column("default_route_advertise", sa.Boolean(),
                  server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "bgp_sessions", sa.Column("import_route_policy", sa.String(length=63), nullable=True)
    )
    op.add_column(
        "bgp_sessions", sa.Column("export_route_policy", sa.String(length=63), nullable=True)
    )
    op.add_column(
        "upstreams", sa.Column("produto_import", sa.String(length=16), nullable=True)
    )
    op.execute(_CAMINHO_DE_CLIENTE)


def downgrade() -> None:
    """A volta perde o que foi marcado em `default_route_advertise` depois da
    migração: é o esperado para uma coluna recém-criada (§3.2)."""
    op.execute(_CAMINHO_DE_VOLTA)
    op.drop_column("upstreams", "produto_import")
    op.drop_column("bgp_sessions", "export_route_policy")
    op.drop_column("bgp_sessions", "import_route_policy")
    op.drop_column("bgp_sessions", "default_route_advertise")
```

- [ ] **Step 4: Ligar as colunas nos modelos**

Em `src/gerenet/domain/models.py`, na `BgpSession`, logo depois de
`allow_default_route` (linha 425):

```python
    # §3.1: o anúncio da default ao peer, o inverso do `allow_default_route`. O
    # nome antigo fica: ele continua verdadeiro onde vale (a sessão de upstream
    # aceitando a default do provedor) e renomear custaria migração de dados e
    # de todo chamador sem trocar o que o campo faz.
    default_route_advertise: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # §4.1: o nome da route-policy lido no equipamento. Nulo ⇒ o render volta ao
    # nome do §25.4; preenchido ⇒ é o nome efetivo, e a definição sai sob ele.
    import_route_policy: Mapped[str | None] = mapped_column(String(63), nullable=True)
    export_route_policy: Mapped[str | None] = mapped_column(String(63), nullable=True)
```

Na `Upstream`, antes de `admin_status` (perto da linha 821):

```python
    # §7: o tipo de rota que a operadora envia (full, parcial, default). A
    # operadora não tem prefix-list própria: o que a descreve é o produto.
    # Nulo ⇒ o produto continua saindo de PRODUTO_IMPORT_POR_TIPO[up.tipo].
    produto_import: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `uv run pytest -q tests/domain/test_bgp_models.py`
Expected: PASS. (O `conftest` roda as migrações no banco de teste; sem o `alembic upgrade` da coluna o teste estoura em `UndefinedColumn`.)

- [ ] **Step 6: Conferir a cópia do `UPDATE` num banco descartável**

Este é o teste da migração de dados do §9 — o `UPDATE` não tem teste automatizado
no repositório, e a verificação é esta, à mão, num banco que não é o de dev:

```bash
createdb gerenet_mig_check
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_mig_check \
  uv run alembic upgrade f2b7d4a91c3e
psql gerenet_mig_check -c "
  insert into sites (name, p2p_ipv4_block) values ('s-mig', '100.64.0.0/10');
  insert into organizations (name, kind) values ('org-mig', 'downstream');
  insert into circuits (code, organization_id, site_id, access_port, stack, vlan_mode, qinq, admin_status)
    select 'C-MIG', o.id, s.id, 'GE0/0/1', 'ipv4', 'unica', false, true
      from organizations o, sites s where o.name='org-mig' and s.name='s-mig';
  insert into bgp_sessions (circuit_id, device_id, afi, local_address, remote_address,
                            asn_local, asn_remote, allow_default_route, admin_status)
    select c.id, 1, 'ipv4', '100.64.0.1', '100.64.0.2', 64600, 64512, true, true
      from circuits c where c.code='C-MIG';
"
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_mig_check \
  uv run alembic upgrade head
psql gerenet_mig_check -c "select default_route_advertise, allow_default_route from bgp_sessions;"
```

Expected: uma linha `t | f` — o cliente copiou o valor e zerou o antigo.
(O `device_id` é `1` porque o banco está vazio; se a FK recusar, insira um
`devices` antes. O ponto do passo é a linha final, não o seed.)

Depois: `dropdb gerenet_mig_check`.

- [ ] **Step 7: Rodar a suíte e o lint**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: PASS e `All checks passed`.

- [ ] **Step 8: Commit**

```bash
git add alembic/versions/a3d1c7e5b9f2_adocao_upstream_e_politicas.py \
        src/gerenet/domain/models.py tests/domain/test_bgp_models.py
git commit -m "feat(db): default route anunciado, política importada e produto do upstream"
```

---

### Task 2: O render — o anúncio da default e o nome importado

**Files:**
- Modify: `src/gerenet/automation/render.py` (`_bloco_import` 246-251, `_bloco_export` 314, `_bloco_import_upstream` 499, `_bloco_export_upstream` 634, `_bloco_peer` 673-695)
- Modify: `src/gerenet/automation/templates/huawei_vrp/bgp_peer.j2` (entre as linhas 26 e 27)
- Test: `tests/automation/test_rendering.py`

**Interfaces:**
- Consumes: `models.BgpSession.default_route_advertise`, `.import_route_policy`, `.export_route_policy` (Task 1).
- Produces: `_nome_rp_import(sessao: models.BgpSession) -> str` e `_nome_rp_export(sessao: models.BgpSession) -> str` (helpers de módulo).

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/automation/test_rendering.py`:

```python
def test_default_route_advertise_anuncia_e_nao_aceita(db_session: Session) -> None:
    """§3.3: o campo novo emite o comando na família da sessão, e o antigo não
    toca mais na prefix-list de importação do cliente."""
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-DRA")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", default_route_advertise=True)

    render = render_desejado(db_session, env["ne_id"])
    blocos = [b for b in render.blocos if b.objeto == "session"]
    comandos = [linha for b in blocos for linha in b.comandos]
    assert "  peer 100.64.0.2 default-route-advertise" in comandos

    # A prefix-list de importação do cliente segue sem a entrada de índice 5,
    # com o campo antigo marcado ou não: quem insere a default ali é o
    # `allow_default_route`, e ele não tem mais esse caminho.
    prefix = next(b for b in render.blocos if b.tipo == "prefix_list")
    assert " rule 5 permit source 0.0.0.0 0" not in prefix.comandos


def test_allow_default_route_nao_toca_no_cliente_mas_segue_no_upstream(db_session: Session) -> None:
    """§2: o campo antigo continua decidindo a proteção do up-full e nada mais."""
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-ADR")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", allow_default_route=True)
    render = render_desejado(db_session, env["ne_id"])
    prefix = next(b for b in render.blocos if b.tipo == "prefix_list")
    assert " rule 5 permit source 0.0.0.0 0" not in prefix.comandos


def test_nome_importado_da_politica_manda_no_render(db_session: Session) -> None:
    """§4.1: o cabeçalho da definição e a referência do peer usam o nome lido;
    a prefix-list interna continua com o nome do gerenet."""
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-RP")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4",
            import_route_policy="RP-DO-EQUIPAMENTO-IN")

    render = render_desejado(db_session, env["ne_id"])
    comandos = [linha for b in render.blocos for linha in b.comandos]
    assert "route-policy RP-DO-EQUIPAMENTO-IN permit node 10" in comandos
    assert "  peer 100.64.0.2 import route-policy RP-DO-EQUIPAMENTO-IN" in comandos
    # O nome do §25.4 não sobra em lugar nenhum, e o da prefix-list é o do gerenet.
    assert not any("RP-64512-IMPORT-V4" in linha for linha in comandos)
    assert any("IP-PFX-64512-IN-V4" in linha for linha in comandos)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/automation/test_rendering.py -k "default_route or nome_importado"`
Expected: FAIL — `TypeError: 'default_route_advertise' is an invalid keyword argument for BgpSessionCreate` e, no terceiro, `route-policy RP-64512-IMPORT-V4 ...`.

- [ ] **Step 3: Os dois helpers de nome**

Em `src/gerenet/automation/render.py`, logo antes de `_bloco_import`:

```python
def _nome_rp_import(sessao: models.BgpSession) -> str:
    """O nome efetivo da route-policy de importação (§4.1).

    A coluna importada manda quando preenchida: o nome lido no equipamento é o
    que o render emite, e a exceção ao §25.4 está registrada no design. Nula, o
    nome volta a derivar do ASN do par, como sempre foi.
    """
    return sessao.import_route_policy or naming.rp_import(sessao.asn_remote, sessao.afi)


def _nome_rp_export(sessao: models.BgpSession) -> str:
    """O nome efetivo da route-policy de exportação (§4.1) — mesma regra do import."""
    return sessao.export_route_policy or naming.rp_export(sessao.asn_remote, sessao.afi)
```

- [ ] **Step 4: Trocar os quatro pontos de naming**

Em `render.py`:

- `_bloco_import`, linha 245: `nome_rp = naming.rp_import(asn_par, afi)` →
  `nome_rp = _nome_rp_import(sessao)`
- `_bloco_export`, linha 314: `nome_rp = naming.rp_export(sessao.asn_remote, afi)` →
  `nome_rp = _nome_rp_export(sessao)`
- `_bloco_import_upstream`, linha 499: `nome_rp = naming.rp_import(asn_par, afi)` →
  `nome_rp = _nome_rp_import(sessao)` (o `asn_par` continua usado no `nome_pfx` e
  nos community-filters logo abaixo — não remova a variável)
- `_bloco_export_upstream`, linha 634: `nome_rp = naming.rp_export(sessao.asn_remote, afi)` →
  `nome_rp = _nome_rp_export(sessao)`

- [ ] **Step 5: Tirar a default da prefix-list de importação do cliente**

Em `_bloco_import`, apagar as duas linhas do `if` e deixar a lista começar pelas
autorizações:

```python
    entradas: list[dict] = [
        {"index": 10 * (i + 1), "prefixo": a.prefix} for i, a in enumerate(autorizadas)
    ]
```

- [ ] **Step 6: O campo novo no contexto do peer e a linha no template**

Em `_bloco_peer`, dentro do dicionário do contexto:

```python
            "shutdown": sessao.shutdown,
            # §3.3: o comando é emitido sempre que o campo está marcado, nos dois
            # caminhos; a guarda de escopo (sessão de upstream não anuncia) vive
            # no serviço, não aqui.
            "default_route_advertise": sessao.default_route_advertise,
```

Em `bgp_peer.j2`, entre `peer {{ peer }} enable` e o bloco do `rp_import`:

```jinja
  peer {{ peer }} enable
{% if default_route_advertise %}
  peer {{ peer }} default-route-advertise
{% endif %}
```

- [ ] **Step 7: Rodar os testes novos e a suíte de render**

Run: `uv run pytest -q tests/automation/`
Expected: PASS. Se um golden de `test_templates.py` quebrar, é porque ele espera
a prefix-list com a entrada de índice 5 — atualize o golden e registre no commit
que a entrada saiu do caminho de cliente (§3.3).

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/automation/render.py src/gerenet/automation/templates/huawei_vrp/bgp_peer.j2 \
        tests/automation/test_rendering.py tests/automation/test_templates.py
git commit -m "feat(render): o anúncio da default ao downstream e o nome importado da política"
```

---

### Task 3: O parser lê o `default-route-advertise`

**Files:**
- Modify: `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py` (`PeerConfig` 24-44, `_novo_peer` 67-87, `_aplica_peer` 104-148)
- Modify: `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt`
- Test: `tests/automation/test_config_vrp.py`

**Interfaces:**
- Consumes: nada (a dataclass é autônoma).
- Produces: `PeerConfig.default_route_advertise: bool`.

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/automation/test_config_vrp.py`:

```python
def test_le_o_default_route_advertise_do_peer() -> None:
    """§3.4: a linha marca a chave; ela não é política de importação."""
    config = parse_config_vrp(
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        "  peer 100.64.10.1 default-route-advertise\n"
    )
    (peer,) = config.peers
    assert peer.default_route_advertise is True
    assert peer.import_route_policy is None
    assert config.avisos == ()


def test_default_route_advertise_com_politica_acoplada_vira_aviso() -> None:
    """§3.4: o VRP aceita `default-route-advertise route-policy <nome>`, e o
    ramo da política de importação engoliria esse resto se viesse antes. O nome
    acoplado não é modelado — vira aviso, e a chave do anúncio fica marcada."""
    config = parse_config_vrp(
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        "  peer 100.64.10.1 default-route-advertise route-policy RP-X\n"
    )
    (peer,) = config.peers
    assert peer.default_route_advertise is True
    assert peer.import_route_policy is None
    assert any("default-route-advertise" in aviso for aviso in config.avisos)


def test_import_route_policy_segue_no_ramo_da_importacao() -> None:
    """Regressão da ordem dos ramos (§3.4): a linha da política não pode cair no
    ramo novo."""
    config = parse_config_vrp(
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " peer 100.64.10.1 route-policy RP-Y import\n"
    )
    (peer,) = config.peers
    assert peer.import_route_policy == "RP-Y"
    assert peer.default_route_advertise is False


def test_a_fixture_do_ne8000_marca_o_anuncio_da_default() -> None:
    """O peer CLIENTE-BETA da fixture passa a anunciar a default (Task 3)."""
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    assert _por_endereco(config, "100.64.10.4").default_route_advertise is True
    assert _por_endereco(config, "100.64.10.1").default_route_advertise is False
    assert config.avisos == ()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/automation/test_config_vrp.py -k "default_route_advertise or import_route_policy_segue or fixture_do_ne8000_marca"`
Expected: FAIL — `AttributeError: 'PeerConfig' object has no attribute 'default_route_advertise'`.

- [ ] **Step 3: A chave na dataclass e no registro**

Em `config_vrp.py`, na `PeerConfig`, depois de `shutdown`:

```python
    default_route_advertise: bool = False
```

Em `_novo_peer`, no dicionário de retorno, junto dos outros booleanos:

```python
        "shutdown": False,
        "default_route_advertise": False,
```

- [ ] **Step 4: O ramo novo, ANTES do de `route-policy`**

Em `_aplica_peer`, imediatamente antes do `elif "route-policy" in resto and ...`:

```python
    elif "default-route-advertise" in resto:
        # ANTES do ramo do `route-policy`: o VRP aceita
        # `peer X default-route-advertise route-policy <nome>`, e esse `resto`
        # tem `route-policy` na lista — na ordem antiga ele cairia no ramo da
        # importação e gravaria como import uma política que não é a de
        # importação. O nome acoplado não é modelado (§11 do design): o que
        # resta dele vira aviso, e o anúncio fica marcado.
        reg["default_route_advertise"] = True
        if len(resto) > resto.index("default-route-advertise") + 1:
            avisos.append(
                f"linha {linha!r}: o parâmetro depois de `default-route-advertise` "
                "não é gerenciado por este sistema (importado como aviso)."
            )
```

- [ ] **Step 5: Estender a fixture**

No bloco do peer `100.64.10.4` (CLIENTE-BETA, o desligado), em
`ne8000_display_current_configuration.txt`, adicionar a linha da família ao lado
do `enable` que já existe:

```text
 ipv4-family unicast
  undo synchronization
  peer 10.0.0.9 enable
  peer 100.64.10.1 enable
  peer 100.64.10.1 maximum-prefix 100 80
  peer 100.64.10.4 enable
  peer 100.64.10.4 default-route-advertise
  peer 100.64.10.3 enable
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -q tests/automation/test_config_vrp.py tests/automation/test_discovery.py tests/domain/test_adocao.py`
Expected: PASS. A fixture é a mesma que a descoberta e a adoção usam — é por isso
que a suíte delas entra aqui, e não só a do parser: a linha nova no peer
`100.64.10.4` não pode mudar proposta, veredito nem conferência dos outros testes
(o peer 100.64.10.4 é o desligado, fora dos enlaces propostos).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/automation/parsers/huawei_vrp/config_vrp.py \
        tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt \
        tests/automation/test_config_vrp.py
git commit -m "feat(parser): o default-route-advertise do peer, com o ramo antes do de route-policy"
```

---

### Task 4: Os schemas da sessão, a guarda de escopo e o `upstream_id`

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`NOME_DE_POLITICA_RE` antes de `BgpSessionCreate`; `BgpSessionCreate` 235-261; `BgpSessionUpdate` 264-289; `BgpSessionOut` 371-399)
- Modify: `src/gerenet/domain/services/bgp_sessions.py` (`create_session` 96-170, `update_session` 215-290)
- Modify: `src/gerenet/api/routers/bgp_sessions.py` (`_com_kind` 27-33 e os cinco usos)
- Test: `tests/domain/test_bgp_sessions_service.py`, `tests/api/test_bgp_sessions_api.py`

**Interfaces:**
- Consumes: colunas de Task 1.
- Produces: `schemas.BgpSessionCreate.default_route_advertise`/`.import_route_policy`/`.export_route_policy`; `schemas.BgpSessionUpdate` idem; `schemas.BgpSessionOut.upstream_id: int | None`; `schemas.NOME_DE_POLITICA_RE: str`.

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/domain/test_bgp_sessions_service.py`. Os imports novos que os
testes abaixo usam vão no topo do arquivo:

```python
from gerenet.domain.schemas import UpstreamCreate
from gerenet.domain.services.upstreams import create_upstream, vincular_circuito
```


```python
def test_sessao_de_circuito_com_upstream_nao_anuncia_a_default(db_session: Session) -> None:
    """§3.5: o anúncio é do caminho de cliente. O render despacha pelo vínculo,
    e numa sessão de upstream o comando significaria anunciar a default à
    operadora — o inverso do que o campo quer dizer ali."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-DRA", edge_id=env["ne1_id"])
    operadora = create_organization(
        db_session, OrganizationCreate(name="Operadora DRA", asn=64501, kind="operadora"),
        actor="cli",
    )
    up = create_upstream(
        db_session, UpstreamCreate(name="up-dra", tipo="transito", organization_id=operadora.id),
        actor="cli",
    )
    vincular_circuito(db_session, up.id, circ_id, papel="principal", ordem=1, actor="cli")

    with pytest.raises(ValidationError, match="default-route-advertise"):
        create_session(
            db_session,
            _sessao_data(env, circ_id, env["ne1_id"], default_route_advertise=True),
            actor="cli",
        )
    # E o caminho de cliente continua aceitando o anúncio.
    sessao_id = create_session(
        db_session,
        _sessao_data(env, _circuito(db_session, env, code="CIRC-DRA-OK", edge_id=env["ne1_id"]),
                     env["ne1_id"], default_route_advertise=True),
        actor="cli",
    ).id
    assert db_session.get(models.BgpSession, sessao_id).default_route_advertise is True


def test_nao_anuncia_default_em_upstream_nem_pelo_update(db_session: Session) -> None:
    """A guarda vale para o PATCH também: o caminho de volta é desmarcar antes."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-DRA-UP", edge_id=env["ne1_id"])
    sessao_id = create_session(
        db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli"
    ).id
    operadora = create_organization(
        db_session, OrganizationCreate(name="Operadora DRA2", asn=64502, kind="operadora"),
        actor="cli",
    )
    up = create_upstream(
        db_session, UpstreamCreate(name="up-dra2", tipo="transito", organization_id=operadora.id),
        actor="cli",
    )
    vincular_circuito(db_session, up.id, circ_id, papel="principal", ordem=1, actor="cli")

    with pytest.raises(ValidationError, match="default-route-advertise"):
        update_session(
            db_session, sessao_id, BgpSessionUpdate(default_route_advertise=True), actor="cli"
        )


def test_updates_de_default_route_e_politica(db_session: Session) -> None:
    """§3.6/§4.3: os três campos entram pelo PATCH, e `null` explícito limpa o
    nome importado (a revisão da adoção conta com isso para voltar ao §25.4)."""
    env = _ambiente(db_session)
    sessao_id = create_session(
        db_session,
        _sessao_data(env, _circuito(db_session, env, code="CIRC-POL", edge_id=env["ne1_id"]),
                     env["ne1_id"]),
        actor="cli",
    ).id

    update_session(
        db_session, sessao_id,
        BgpSessionUpdate(import_route_policy="RP-LIDO", export_route_policy="RP-LIDO-OUT"),
        actor="cli",
    )
    sessao = db_session.get(models.BgpSession, sessao_id)
    assert (sessao.import_route_policy, sessao.export_route_policy) == ("RP-LIDO", "RP-LIDO-OUT")

    update_session(db_session, sessao_id, BgpSessionUpdate(import_route_policy=None), actor="cli")
    assert db_session.get(models.BgpSession, sessao_id).import_route_policy is None


def test_o_nome_de_politica_recusa_o_que_o_vrp_nao_aceita(db_session: Session) -> None:
    """§4.5: o limite de 63 e a grafia são validados no schema."""
    env = _ambiente(db_session)
    for invalido in ("RP-COM-ESPAÇO", "X" * 64, "RP/INVALIDA"):
        with pytest.raises(Exception):
            _sessao_data(
                env, _circuito(db_session, env, code=f"CIRC-{len(invalido)}",
                               edge_id=env["ne1_id"]),
                env["ne1_id"], import_route_policy=invalido,
            )
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/domain/test_bgp_sessions_service.py -k "default ou politica"`
Expected: FAIL — `ValidationError` não é levantada / campo inválido.

- [ ] **Step 3: O padrão de nome e os campos nos schemas**

Em `schemas.py`, imediatamente antes de `class BgpSessionCreate`:

```python
# §4.5: o limite é o do VRP e o conjunto de caracteres é o que o parser lê de
# volta sem ambiguidade. O nome pode deixar de derivar do ASN do par (exceção
# registrada ao §25.4), mas o tamanho e a grafia não mudam.
NOME_DE_POLITICA_RE = r"^[A-Za-z0-9_.\-]{1,63}$"
```

Em `BgpSessionCreate`, depois de `allow_default_route`:

```python
    default_route_advertise: bool = False
    import_route_policy: str | None = Field(default=None, pattern=NOME_DE_POLITICA_RE)
    export_route_policy: str | None = Field(default=None, pattern=NOME_DE_POLITICA_RE)
```

Em `BgpSessionUpdate`, depois de `allow_default_route`:

```python
    default_route_advertise: bool | None = None
    import_route_policy: str | None = Field(default=None, pattern=NOME_DE_POLITICA_RE)
    export_route_policy: str | None = Field(default=None, pattern=NOME_DE_POLITICA_RE)
```

Em `BgpSessionOut`, depois de `allow_default_route`:

```python
    default_route_advertise: bool
    import_route_policy: str | None = None
    export_route_policy: str | None = None
    # §3.6: o vínculo do circuito, e não o `kind` da organização: é por ele que
    # o render despacha, e uma operadora sem vínculo cai no caminho de cliente.
    upstream_id: int | None = None
```

- [ ] **Step 4: A guarda de escopo no serviço**

Em `bgp_sessions.py`, antes de `create_session`:

```python
def _recusa_anuncio_em_upstream(session: Session, circuit_id: int, anunciar: bool) -> None:
    """§3.5: o anúncio da default é do caminho de cliente.

    Import tardio: `upstreams.py` importa este módulo, e no topo o ciclo derruba
    quem importar primeiro — a mesma forma que `adotar_proposta` usa com
    `automation.discovery`.
    """
    if not anunciar:
        return
    from gerenet.domain.services.upstreams import upstream_do_circuito

    up = upstream_do_circuito(session, circuit_id)
    if up is not None:
        raise ValidationError(
            f"O circuito está vinculado ao upstream {up.name}: a sessão de upstream "
            "aceita a default do provedor por `allow_default_route`, e não a anuncia. "
            "`default-route-advertise` é do caminho de cliente."
        )
```

Chamada em `create_session`, logo depois do `circ.admin_status` (antes de
qualquer outra validação):

```python
    _recusa_anuncio_em_upstream(session, data.circuit_id, data.default_route_advertise)
```

E em `update_session`, depois de `circ = get_circuit(session, circ_id)`:

```python
    _recusa_anuncio_em_upstream(
        session, circ_id, bool(mudancas.get("default_route_advertise", sessao.default_route_advertise))
    )
```

O `model_dump()` de `create_session` já carrega os três campos novos para o
modelo; o de `update_session` também, via `exclude_unset`.

- [ ] **Step 5: O `upstream_id` na resposta da API**

Em `api/routers/bgp_sessions.py`, renomear `_com_kind` e ampliá-lo (o nome
antigo passa a mentir: agora são dois campos derivados do circuito):

```python
def _extras_do_circuito(session: Session, sessao: models.BgpSession) -> dict[str, object]:
    """Campos da resposta que saem do circuito da sessão (fase 5 e §3.6).

    `organization_kind` é o `kind` da organização; `upstream_id` é o vínculo do
    circuito, que é por onde o render despacha. Os dois andam juntos na adoção
    (§5.1) — e é `upstream_id` que a página usa para escolher o checkbox do
    escopo.
    """
    circ = session.get(models.Circuit, sessao.circuit_id)
    org = circ.organization if circ else None
    up = upstream_do_circuito(session, sessao.circuit_id)
    return {
        "organization_kind": org.kind if org else None,
        "upstream_id": up.id if up is not None else None,
    }
```

O `upstream_do_circuito` é o mesmo helper que o render usa para despachar
(`services/upstreams.py:232`): reaproveitá-lo em vez de repetir o join mantém
uma definição só de "o circuito tem upstream". O import vai no topo do router,
junto dos outros serviços:

```python
from gerenet.domain.services.upstreams import upstream_do_circuito
```

Renomeie os cinco usos de `_com_kind` (linhas 43, 67, 76, 100, 123).

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -q tests/domain/test_bgp_sessions_service.py tests/api/test_bgp_sessions_api.py tests/automation/test_rendering.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/bgp_sessions.py \
        src/gerenet/api/routers/bgp_sessions.py tests/domain/test_bgp_sessions_service.py \
        tests/api/test_bgp_sessions_api.py
git commit -m "feat(bgp): a guarda de escopo do default route e o upstream_id na resposta"
```

---

### Task 5: A descoberta — os campos lidos e o nome repetido

**Files:**
- Modify: `src/gerenet/automation/discovery.py` (`_sessao_de` 328-353, `_pendencia_de_politica` 392-396, `_politicas_em_uso`/`_conflitos_de_politica` novos, `listar_propostas` 674-786)
- Test: `tests/automation/test_discovery.py`

**Interfaces:**
- Consumes: `PeerConfig.default_route_advertise`, `.import_route_policy`, `.export_route_policy` (Task 3); `models.BgpSession.import_route_policy`/`.export_route_policy` (Task 1).
- Produces: `_sessao_de` devolve três chaves novas; `_politicas_em_uso(session, device_id) -> dict[str, str]`; `_conflitos_de_politica(peer, *, em_uso, vistos, descricao) -> list[Conflito]`; tipo de conflito `politica_compartilhada`.

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/automation/test_discovery.py`:

O arquivo já tem os helpers `_ambiente(db_session, *, asn=65001)` (devolve o
`dev`), `_com_texto(db_session, dev, tmp_path, texto)` e `_circuito_tomado`.
Acrescente ao topo: `from gerenet.domain.schemas import PrefixAuthorizationCreate`
(se ainda não houver) e, para o primeiro teste, nada além disso.

```python
_CONFIG_COM_POLITICA = (
    "interface Eth-Trunk127.601\n"
    " vlan-type dot1q 601\n"
    " ip address 100.64.10.0 255.255.255.254\n"
    "bgp 65001\n"
    " peer 100.64.10.1 as-number 64512\n"
    " peer 100.64.10.1 route-policy RP-LIDA-IMPORT import\n"
    " peer 100.64.10.1 export route-policy RP-LIDA-EXPORT\n"
    " ipv4-family unicast\n"
    "  peer 100.64.10.1 enable\n"
    "  peer 100.64.10.1 default-route-advertise\n"
)


def test_a_sessao_da_proposta_carrega_o_anuncio_e_os_nomes(db_session, tmp_path) -> None:
    """§4.3: `_sessao_de` devolve os três campos novos, e o dump da proposta é o
    que a revisão sugere ao operador (que pode limpar os nomes)."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, _CONFIG_COM_POLITICA)

    proposta = _propostas(db_session, dev)[601]
    (sessao,) = proposta.sessoes
    assert sessao["default_route_advertise"] is True
    assert sessao["import_route_policy"] == "RP-LIDA-IMPORT"
    assert sessao["export_route_policy"] == "RP-LIDA-EXPORT"


def test_politica_ja_em_uso_no_equipamento_vira_conflito(db_session, tmp_path) -> None:
    """§4.4: dois peers do mesmo equipamento com o mesmo nome conviveriam sob um
    cabeçalho só. A proposta fica inadaptável e o caminho de saída é renomear."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, _CONFIG_COM_POLITICA)
    # A sessão que já tem o nome nasceu pela SoT, num circuito de outro par: o
    # candidato da fixture (100.64.10.1) fica livre para a proposta.
    outro = _circuito_tomado(db_session, dev, code="CIRC-DONO-DO-NOME")
    db_session.add(models.BgpSession(
        circuit_id=outro.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.20", remote_address="100.64.10.21",
        asn_local=65001, asn_remote=64999, import_route_policy="RP-LIDA-IMPORT",
    ))
    db_session.commit()

    proposta = next(p for p in listar_propostas(db_session, dev.id).propostas if p.vid == 601)
    assert any(c.tipo == "politica_compartilhada" for c in proposta.conflitos)
    assert proposta.veredito == "nao_adotavel"


def test_politica_repetida_entre_as_duas_familias_vira_conflito(db_session, tmp_path) -> None:
    """O dual stack do mesmo enlace também não pode compartilhar o nome: os dois
    blocos sairiam sob o mesmo cabeçalho."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, (
        "interface Eth-Trunk127.601\n"
        " vlan-type dot1q 601\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        " ipv6 enable\n"
        " ipv6 address 2804:194C:1000::1100:73:1 126\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " peer 100.64.10.1 route-policy RP-UNICA import\n"
        " peer 2804:194C:1000::1100:73:2 as-number 64512\n"
        " peer 2804:194C:1000::1100:73:2 route-policy RP-UNICA import\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        " ipv6-family unicast\n"
        "  peer 2804:194C:1000::1100:73:2 enable\n"
    ))

    proposta = next(p for p in listar_propostas(db_session, dev.id).propostas if p.vid == 601)
    conflito = next(c for c in proposta.conflitos if c.tipo == "politica_compartilhada")
    assert "RP-UNICA" in conflito.descricao


def test_o_texto_da_politica_fora_do_padrao_diz_o_que_a_importacao_faz(db_session, tmp_path) -> None:
    """§4.2: importar o nome significa gerenciar o corpo sob ele."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, _CONFIG_COM_POLITICA)

    proposta = next(p for p in listar_propostas(db_session, dev.id).propostas if p.vid == 601)
    pendencia = next(p for p in proposta.pendencias if p.tipo == "politica_fora_do_padrao")
    assert "gerenciar o corpo" in pendencia.descricao
    assert "RP-LIDA-IMPORT" in pendencia.descricao
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/automation/test_discovery.py -k "carrega_o_anuncio or politica"`
Expected: FAIL — `KeyError: 'default_route_advertise'`, e nenhum conflito `politica_compartilhada`.

- [ ] **Step 3: Os três campos em `_sessao_de`**

```python
        "shutdown": peer.shutdown,
        # §4.3: o que o equipamento tem vira sugestão na revisão — quem decide
        # entre manter, limpar ou renomear é o operador.
        "default_route_advertise": peer.default_route_advertise,
        "import_route_policy": peer.import_route_policy,
        "export_route_policy": peer.export_route_policy,
```

- [ ] **Step 4: O texto da pendência (§4.2)**

Substituir o `return` de `politica_fora_do_padrao`:

```python
    return Pendencia(
        "politica_fora_do_padrao",
        f"A política {nomes[0]} não segue o padrão de nome deste sistema: o nome "
        "pode ser importado na revisão, e o gerenet passa a gerenciar o corpo da "
        "política sob ele — o que a SoT tiver de diferente do que está no "
        "equipamento muda na primeira mudança aprovada. Sem importar o nome, o "
        "render emite nomes novos.",
    )
```

- [ ] **Step 5: O dono do nome e o conflito**

Logo depois de `_pendencia_de_politica`:

```python
def _politicas_em_uso(session: Session, device_id: int) -> dict[str, str]:
    """Os nomes de route-policy importada que já têm dono no equipamento (§4.4).

    A chave é o nome, o valor é quem o usa hoje, para a mensagem dizer onde está
    o dono. Sessão DESATIVADA fica de fora: ela não é renderizada, e o nome
    volta a estar livre.
    """
    em_uso: dict[str, str] = {}
    for sessao in list_sessions(session, device_id=device_id, include_disabled=False):
        for nome in (sessao.import_route_policy, sessao.export_route_policy):
            if nome:
                em_uso.setdefault(nome, f"sessão {sessao.id} ({sessao.remote_address})")
    return em_uso


def _conflitos_de_politica(
    peer: PeerConfig, *, em_uso: dict[str, str], vistos: dict[str, str], descricao: str
) -> list[Conflito]:
    """§4.4 — o nome importado não pode ter dois donos no mesmo equipamento.

    Dois peers com o mesmo nome e corpos diferentes sairiam sob um cabeçalho só
    (`_apensa_definicao` deduplica por (tipo, nome) e guarda os textos num
    conjunto: os dois blocos convivem). Não há modelo para a política
    compartilhada — a adoção recusa, e o caminho de saída é renomear. O nome
    visto nesta mesma leitura também conta, inclusive entre as duas famílias do
    mesmo enlace.
    """
    conflitos: list[Conflito] = []
    for nome in (peer.import_route_policy, peer.export_route_policy):
        if not nome:
            continue
        dono = em_uso.get(nome) or vistos.get(nome)
        if dono is not None:
            conflitos.append(Conflito(
                "politica_compartilhada",
                f"A política {nome} já tem dono no mesmo equipamento ({dono}): dois "
                "peers com o mesmo nome de política conviveriam sob um cabeçalho só. "
                "Adote sem importar o nome, ou cadastre a política compartilhada à mão.",
            ))
        else:
            vistos[nome] = descricao
    return conflitos
```

- [ ] **Step 6: Ligar na montagem da proposta**

Em `listar_propostas`, logo depois de `config = parse_config_vrp(texto_backup(snap))`:

```python
    # O índice do §4.4 é do equipamento inteiro: montado uma vez, ele responde
    # por todas as propostas da leitura.
    em_uso = _politicas_em_uso(session, device.id)
    # O que esta leitura já viu, para o mesmo nome não entrar duas vezes por dois
    # enlaces diferentes (inclusive as duas famílias do mesmo enlace).
    vistos: dict[str, str] = {}
```

E dentro do laço, logo depois de `_acrescenta(proposta.conflitos, _conflitos_da_leitura(...))`:

```python
        _acrescenta(proposta.conflitos, _conflitos_de_politica(
            peer, em_uso=em_uso, vistos=vistos,
            descricao=f"o peer {candidato.remote_address} desta mesma leitura",
        ))
```

- [ ] **Step 7: Rodar e ver passar**

Run: `uv run pytest -q tests/automation/test_discovery.py tests/api/test_discovery_api.py`
Expected: PASS. Os testes antigos que montam propostas sem nome de política
continuam sem conflito: o índice só tem nome quando a coluna está preenchida.

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/automation/discovery.py tests/automation/test_discovery.py
git commit -m "feat(descoberta): a sessão lida carrega o anúncio e os nomes, e o nome repetido vira conflito"
```

---

### Task 6: A revisão leva os nomes por família

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`AdocaoSessaoIn` 1121-1129)
- Modify: `src/gerenet/domain/services/discovery.py` (`_DO_OPERADOR` 121-123, `_sessao_da_proposta` 126-154)
- Test: `tests/domain/test_adocao.py`

**Interfaces:**
- Consumes: `schemas.NOME_DE_POLITICA_RE` (Task 4); as chaves novas de `_sessao_de` (Task 5).
- Produces: `AdocaoSessaoIn.import_route_policy`/`.export_route_policy`; `_DO_OPERADOR` com os dois nomes.

- [ ] **Step 1: Escrever o teste que falha**

No fim de `tests/domain/test_adocao.py`, junto dos testes de política que já
existem:

```python
def test_a_revisao_importa_o_nome_lido_e_o_limpa_quando_quiser(db_session, tmp_path) -> None:
    """§4.3: o valor da proposta é sugestão; quem decide é o operador. Limpar os
    dois devolve os nomes do §25.4, e o ensaio enxerga a mesma coisa que a
    escrita vai gravar."""
    _site, dev = _ambiente(db_session, tmp_path)
    proposta = _proposta(db_session, dev)
    assert proposta.sessoes[0]["import_route_policy"] is None  # a fixture não tem

    revisao = _revisao(dev, sessoes=[
        AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA,
                       import_route_policy="RP-LIDO-IN", export_route_policy="RP-LIDO-OUT"),
        AdocaoSessaoIn(afi="ipv6"),
    ])
    circ_id = adotar_proposta(db_session, proposta=proposta, revisao=revisao, actor="cli")
    v4 = db_session.scalar(select(models.BgpSession).where(
        models.BgpSession.circuit_id == circ_id, models.BgpSession.afi == "ipv4"
    ))
    v6 = db_session.scalar(select(models.BgpSession).where(
        models.BgpSession.circuit_id == circ_id, models.BgpSession.afi == "ipv6"
    ))
    assert (v4.import_route_policy, v4.export_route_policy) == ("RP-LIDO-IN", "RP-LIDO-OUT")
    assert (v6.import_route_policy, v6.export_route_policy) == (None, None)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/domain/test_adocao.py -k importa_o_nome`
Expected: FAIL — `AdocaoSessaoIn` recusa as chaves (`extra="forbid"`).

- [ ] **Step 3: Os campos no `AdocaoSessaoIn`**

```python
    afi: Literal["ipv4", "ipv6"]
    import_profile_id: int | None = None
    export_profile_id: int | None = None
    password_ref: str | None = Field(default=None, max_length=255)
    # §4.3: o nome lido no equipamento, importado quando o operador quiser. Em
    # `_DO_OPERADOR` porque é ele que decide entre manter e limpar — o valor da
    # proposta é sugestão, e limpar devolve os nomes do §25.4.
    import_route_policy: str | None = Field(default=None, pattern=NOME_DE_POLITICA_RE)
    export_route_policy: str | None = Field(default=None, pattern=NOME_DE_POLITICA_RE)
```

- [ ] **Step 4: `_DO_OPERADOR` e o construtor**

```python
_DO_OPERADOR = (
    "circuit_id", "device_id", "import_profile_id", "export_profile_id", "password_ref",
    "import_route_policy", "export_route_policy",
)
```

Em `_sessao_da_proposta`, completar a chamada:

```python
    return schemas.BgpSessionCreate(
        **base,
        circuit_id=circuit_id,
        device_id=device_id,
        import_profile_id=overrides.import_profile_id,
        export_profile_id=overrides.export_profile_id,
        password_ref=overrides.password_ref,
        import_route_policy=overrides.import_route_policy,
        export_route_policy=overrides.export_route_policy,
    )
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest -q tests/domain/test_adocao.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/discovery.py \
        tests/domain/test_adocao.py
git commit -m "feat(adoção): a revisão importa o nome da política lido no equipamento"
```

---

### Task 7: O produto da operadora e o `commit=False` do upstream

**Files:**
- Modify: `src/gerenet/domain/services/upstreams.py` (`_CAMPOS_PROPAGACAO` 19-27, `create_upstream` 70-86, `vincular_circuito` 168-206, `propagar_defaults` 271-274)
- Modify: `src/gerenet/domain/schemas.py` (`UpstreamCreate` 901-921, `UpstreamUpdate` 924-946, `UpstreamOut` 988-1010)
- Test: `tests/domain/test_upstreams_service.py`

**Interfaces:**
- Consumes: `models.Upstream.produto_import` (Task 1).
- Produces: `create_upstream(session, data, *, actor, commit=True)`; `vincular_circuito(session, upstream_id, circuit_id, *, papel, ordem, actor, commit=True)`; `PERFIL_DO_PRODUTO: dict[str, str]`; `propagar_defaults` resolve o perfil por `PERFIL_DO_PRODUTO[up.produto_import]` quando a coluna está preenchida, e por `PRODUTO_IMPORT_POR_TIPO[up.tipo]` quando não.

> **Desvio registrado do spec.** O §5.3/§8 lista `propagar_defaults` entre as
> funções que "ganham `commit=False`". Ela **nunca commitou** e não recebe
> `commit` em lugar nenhum: ganhar o parâmetro seria inócuo (`if False: commit`)
> ou mudaria a fronteira de transação de `update_upstream`, que chama a
> propagação no meio e só commita no fim (upstreams.py:110-112). A propagação
> fica como está — ela só muta —, e a adoção deixa o `commit` único dela
> persistir o resultado. Os dois serviços que de fato commitam ganham o
> parâmetro.

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/domain/test_upstreams_service.py`:

O arquivo usa o fixture `session` e o alias `svc`, e já tem `org_operadora`,
`circuito_up` e `edge_device` no `conftest`. Os testes novos:

```python
def _perfil_import(session, nome: str) -> int:
    """O id do perfil de importação do catálogo seedado."""
    return session.scalar(select(models.PolicyProfile.id).where(
        models.PolicyProfile.name == nome,
        models.PolicyProfile.direction == "import",
    ))


def _sessao_sem_perfil(session, circuito_up, edge_device):
    """A sessão do circuito de upstream sem perfil de importação: é o estado em
    que `propagar_defaults` decide — sessão que já tem perfil vence e não é mexida."""
    sessao = models.BgpSession(
        circuit_id=circuito_up.id, device_id=edge_device.id, afi="ipv4",
        local_address="100.64.10.1", remote_address="100.64.10.2",
        asn_local=65001, asn_remote=64501,
    )
    session.add(sessao)
    session.commit()
    return sessao


def test_o_produto_da_coluna_vence_o_do_tipo(session, org_operadora, circuito_up,
                                             edge_device) -> None:
    """§7: `produto_import` é a fonte quando preenchida, mesmo contra o que o
    tipo daria — `pni` sozinho daria `up-parcial`."""
    sessao = _sessao_sem_perfil(session, circuito_up, edge_device)

    up = svc.create_upstream(session, UpstreamCreate(
        name="up-pni-cheio", tipo="pni", organization_id=org_operadora.id,
        produto_import="full",
    ), actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1,
                          actor="cli")

    assert session.get(models.BgpSession, sessao.id).import_profile_id == \
        _perfil_import(session, "up-full")


def test_sem_produto_o_tipo_decide(session, org_operadora, circuito_up, edge_device) -> None:
    """A coluna nula mantém o comportamento antigo — é o que garante que nenhum
    upstream existente mude de produto ao migrar."""
    sessao = _sessao_sem_perfil(session, circuito_up, edge_device)

    up = svc.create_upstream(session, UpstreamCreate(
        name="up-pni-vazio", tipo="pni", organization_id=org_operadora.id,
    ), actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1,
                          actor="cli")

    assert session.get(models.BgpSession, sessao.id).import_profile_id == \
        _perfil_import(session, "up-parcial")


def test_mudar_o_produto_repropaga(session, org_operadora, circuito_up, edge_device) -> None:
    """`produto_import` entra em `_CAMPOS_PROPAGACAO`: mudou o produto, as
    sessões sem perfil repropagam."""
    sessao = _sessao_sem_perfil(session, circuito_up, edge_device)
    up = svc.create_upstream(session, UpstreamCreate(
        name="up-muda-produto", tipo="pni", organization_id=org_operadora.id,
        produto_import="full",
    ), actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1,
                          actor="cli")
    assert session.get(models.BgpSession, sessao.id).import_profile_id == \
        _perfil_import(session, "up-full")

    svc.update_upstream(session, up.id, UpstreamUpdate(produto_import="parcial"), actor="cli")

    assert session.get(models.BgpSession, sessao.id).import_profile_id == \
        _perfil_import(session, "up-parcial")


def test_create_upstream_com_commit_false_nao_grava(session, org_operadora) -> None:
    """§5.3: a adoção encadeia o upstream na transação dela, e um só commit
    persiste a cadeia inteira. Sem o commit, nada fica."""
    svc.create_upstream(session, UpstreamCreate(
        name="up-nao-gravado", tipo="ix", organization_id=org_operadora.id,
    ), actor="cli", commit=False)
    session.rollback()
    assert session.scalar(select(models.Upstream).where(
        models.Upstream.name == "up-nao-gravado"
    )) is None


def test_vincular_com_commit_false_nao_grava(session, org_operadora, circuito_up,
                                             edge_device) -> None:
    """O vínculo também espera o commit de quem chamou (é o passo 5 do §5.3)."""
    _sessao_sem_perfil(session, circuito_up, edge_device)
    up = svc.create_upstream(session, UpstreamCreate(
        name="up-vinculo-pendente", tipo="ix", organization_id=org_operadora.id,
    ), actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1,
                          actor="cli", commit=False)
    session.rollback()
    assert session.scalars(select(models.UpstreamCircuit)).all() == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/domain/test_upstreams_service.py -k "produto_da_coluna or repropaga or commit_false"`
Expected: FAIL — `TypeError: create_upstream() got an unexpected keyword argument 'commit'` / `produto_import` inválido.

- [ ] **Step 3: Os campos nos schemas do upstream**

Em `UpstreamCreate`, depois de `rpki_enabled`:

```python
    # §7: o tipo de rota que a operadora envia. Nulo ⇒ o produto sai do tipo.
    produto_import: Literal["full", "parcial", "default"] | None = None
```

Em `UpstreamUpdate`, junto dos campos de propagação:

```python
    produto_import: Literal["full", "parcial", "default"] | None = None
```

Em `UpstreamOut`, depois de `rpki_enabled`:

```python
    produto_import: str | None
```

- [ ] **Step 4: O produto na propagação e no gatilho**

Em `upstreams.py`, `_CAMPOS_PROPAGACAO`:

```python
_CAMPOS_PROPAGACAO = frozenset((
    "tipo", "expected_prefixes_v4", "expected_prefixes_v6", "max_prefix_margin_pct",
    "entrada_local_preference", "contingencia_local_preference", "contingencia_prepend",
    "produto_import",
))
```

Em `propagar_defaults`, a linha 271-274. **Atenção:** o §7 do spec escreve esta
troca como `up.produto_import or PRODUTO_IMPORT_POR_TIPO[up.tipo]`, e copiada
assim ela **não funciona**: `PRODUTO_IMPORT_POR_TIPO` mapeia tipo → **nome do
perfil** (`"pni" → "up-parcial"`), enquanto `produto_import` guarda o valor do
produto (`"parcial"`), e `_perfil_import` procura por nome. Passar `"parcial"`
faz o `scalar(...)` não achar nada, devolver `None` e a propagação não fazer
nada — calada, sem erro. O produto precisa do próprio mapa:

```python
# O nome do perfil de importação de cada produto (§7). São vocabulários
# diferentes: `produto_import` guarda "full"/"parcial"/"default" e o catálogo
# chama os perfis de "up-full"/"up-parcial"/"up-default".
PERFIL_DO_PRODUTO = {"full": "up-full", "parcial": "up-parcial",
                     "default": "up-default"}
```

e a linha vira:

```python
            if sessao.import_profile_id is None:
                nome_perfil = (
                    PERFIL_DO_PRODUTO[up.produto_import] if up.produto_import
                    else PRODUTO_IMPORT_POR_TIPO[up.tipo]
                )
                perfil = _perfil_import(session, nome_perfil)
```

- [ ] **Step 5: O `commit=False` nos dois serviços**

`create_upstream` (o `DataError` do `IntegrityError` continua
**incondicional**: um rollback dentro de `commit=False` levaria o trabalho
pendente da adoção junto, mas o efeito final é o mesmo — a adoção também
desfaz tudo o que é dela —, e é o padrão que `create_circuit` já segue):

```python
def create_upstream(session: Session, data: UpstreamCreate, *, actor: str,
                    commit: bool = True) -> models.Upstream:
    """Cadastra o upstream; `commit=False` é para a adoção encadear a cadeia
    inteira numa transação (design §5.3)."""
    _validar_org_operadora(session, data.organization_id)
    _valida_nomes(data.name)
    dump = data.model_dump()
    up = models.Upstream(**dump)
    session.add(up)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(session, tipo="upstream.create", ator=actor, objeto="upstream",
                  objeto_id=up.id, antes=None, depois=dump)
        if commit:
            session.commit()  # propagação às sessões ocorre no vínculo de circuitos
            # (vincular_circuito/update_upstream chamam propagar_defaults — §3.1)
    except IntegrityError:
        session.rollback()
        raise ConflictError(f"Já existe um upstream com o nome {data.name}.") from None
    if commit:
        session.refresh(up)
    return up
```

`vincular_circuito` — assinatura e as duas linhas do fim:

```python
def vincular_circuito(session: Session, upstream_id: int, circuit_id: int, *, papel: str,
                      ordem: int, actor: str, commit: bool = True) -> models.Upstream:
```

```python
        propagar_defaults(session, up)
        if commit:
            session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("Circuito já vinculado a um upstream.") from None
    if commit:
        session.refresh(up)
    return up
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -q tests/domain/test_upstreams_service.py tests/api/test_upstreams_router.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/services/upstreams.py src/gerenet/domain/schemas.py \
        tests/domain/test_upstreams_service.py
git commit -m "feat(upstream): o produto da operadora e o commit=False da adoção"
```

---

### Task 8: O bloco do upstream na adoção e no ensaio

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`AdocaoUpstreamIn` novo antes de `AdocaoIn`; `AdocaoIn` ganha `upstream`)
- Modify: `src/gerenet/domain/services/discovery.py` (`bloco_do_upstream` novo; `adotar_proposta` 173-409)
- Modify: `src/gerenet/automation/discovery.py` (`_ensaio` 1026-1176; `conferir_fidelidade` 1202-1380)
- Test: `tests/domain/test_adocao.py`, `tests/automation/test_discovery.py`

**Interfaces:**
- Consumes: `create_upstream`/`vincular_circuito` com `commit=False` e `propagar_defaults` (Task 7); `_politicas_em_uso` (Task 5); `NOME_DE_POLITICA_RE` (Task 4).
- Produces: `schemas.AdocaoUpstreamIn`; `schemas.AdocaoIn.upstream: AdocaoUpstreamIn | None`; `services.discovery.bloco_do_upstream(...) -> dict | None`; `_ensaio(..., upstream: dict | None = None)`; `conferir_fidelidade(..., upstream: dict | None = None)`.

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/domain/test_adocao.py`. Os imports novos vão nos blocos que já
existem no topo do arquivo: `AdocaoUpstreamIn` no `from gerenet.domain.schemas
import (...)`, e `from gerenet.domain.schemas import CircuitCreate` mais
`from gerenet.domain.services.circuits import create_circuit` (os dois testes que
preparam um circuito à mão precisam deles).

```python
def test_operadora_sem_bloco_de_upstream_e_recusada(db_session, tmp_path) -> None:
    """§5.1: o render despacha pelo vínculo e `_autorizadas_clientes` filtra pelo
    `kind`. Operadora sem vínculo é o único estado em que os dois discordam."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova.kind = "operadora"
    with pytest.raises(ValidationError, match="bloco `upstream`"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")
    assert db_session.scalars(select(models.Organization)).all() == []


def test_bloco_de_upstream_com_organizacao_downstream_e_recusado(db_session, tmp_path) -> None:
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.upstream = AdocaoUpstreamIn(name="up-x", tipo="transito")
    with pytest.raises(ValidationError, match="operadora"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")


def test_adota_o_enlace_de_upstream_com_a_cadeia_inteira(db_session, tmp_path) -> None:
    """§5.3: organização, upstream, circuito, vínculo e sessões numa transação,
    e a sessão nasce com o perfil do produto."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, sessoes=[
        AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA),
        AdocaoSessaoIn(afi="ipv6"),
    ])
    revisao.organizacao_nova.kind = "operadora"
    # O produto vai de propósito contra o tipo: `pni` sozinho daria `up-parcial`
    # (§7, `PRODUTO_IMPORT_POR_TIPO`), e o que o teste prende é o campo vencer.
    revisao.upstream = AdocaoUpstreamIn(
        name="up-adoc", tipo="pni", produto_import="full", papel="principal",
    )
    circ_id = adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                              actor="cli")

    org = db_session.scalar(select(models.Organization).where(
        models.Organization.name == "Cliente Alfa"
    ))
    up = db_session.scalar(select(models.Upstream).where(models.Upstream.name == "up-adoc"))
    assert (up.organization_id, up.produto_import, up.tipo) == (org.id, "full", "pni")
    vinculo = db_session.scalar(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.circuit_id == circ_id
    ))
    assert (vinculo.upstream_id, vinculo.papel, vinculo.ordem) == (up.id, "principal", 1)
    # A propagação rodou DENTRO da adoção (passo 8 do §5.3) e leu o produto da
    # revisão: `up-full` só sai daqui se o campo venceu o tipo.
    full = db_session.scalar(select(models.PolicyProfile.id).where(
        models.PolicyProfile.name == "up-full",
        models.PolicyProfile.direction == "import",
    ))
    assert all(s.import_profile_id == full for s in db_session.scalars(
        select(models.BgpSession).where(models.BgpSession.circuit_id == circ_id)
    ))
    evento = db_session.scalar(select(models.AuditEvent).where(
        models.AuditEvent.type == "discovery.adopt"
    ))
    assert evento.depois["upstream"] == {
        "upstream_id": up.id, "papel": "principal", "ordem": 1,
        "criado": True, "tipo": "pni", "produto_import": "full",
    }


def test_o_upstream_novo_nao_sobrevive_a_recusa_da_transacao(db_session, tmp_path) -> None:
    """A transação única vale para o upstream também: o circuito de código já
    usado derruba a adoção inteira e o upstream não fica órfão."""
    _site, dev = _ambiente(db_session, tmp_path)
    # O código que `_revisao` gera ("ADOC-64512-1001") já está em uso: a recusa
    # acontece no passo 4, DEPOIS do upstream ter sido criado no passo 3 — que é
    # exatamente o que este teste quer derrubar junto.
    site = db_session.scalar(select(models.Site))
    org = create_organization(db_session, OrganizationCreate(name="Dono do Código", asn=64998),
                              actor="cli")
    create_circuit(db_session, CircuitCreate(
        code="ADOC-64512-1001", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")

    revisao = _revisao(dev)
    revisao.organizacao_nova.kind = "operadora"
    revisao.upstream = AdocaoUpstreamIn(name="up-orfao", tipo="transito")

    with pytest.raises(ConflictError):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")
    assert db_session.scalars(select(models.Upstream).where(
        models.Upstream.name == "up-orfao"
    )).all() == []
    assert "discovery.adopt" not in _tipos_auditados(db_session)


def test_o_maximum_prefix_lido_sobrevive_sem_esperado(db_session, tmp_path) -> None:
    """§5.3: sem `expected_prefixes` a propagação não inventa número — o que o
    equipamento tem é o que a SoT grava. A fixture traz 100 no peer do ALFA."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova.kind = "operadora"
    revisao.upstream = AdocaoUpstreamIn(name="up-sem-esperado", tipo="transito")

    circ_id = adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                              actor="cli")
    v4 = db_session.scalar(select(models.BgpSession).where(
        models.BgpSession.circuit_id == circ_id, models.BgpSession.afi == "ipv4"
    ))
    v6 = db_session.scalar(select(models.BgpSession).where(
        models.BgpSession.circuit_id == circ_id, models.BgpSession.afi == "ipv6"
    ))
    assert (v4.maximum_prefix, v4.maximum_prefix_threshold) == (100, 80)
    assert (v6.maximum_prefix, v6.maximum_prefix_threshold) == (50, 80)


def test_com_esperado_a_adocao_recalcula_o_maximum_prefix(db_session, tmp_path) -> None:
    """O outro lado: com `expected_prefixes_v4` o número do equipamento é
    substituído por esperado × (1 + margem) — a mesma conta do vínculo manual."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova.kind = "operadora"
    revisao.upstream = AdocaoUpstreamIn(
        name="up-com-esperado", tipo="transito",
        expected_prefixes_v4=1000, max_prefix_margin_pct=10,
    )

    circ_id = adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                              actor="cli")
    v4 = db_session.scalar(select(models.BgpSession).where(
        models.BgpSession.circuit_id == circ_id, models.BgpSession.afi == "ipv4"
    ))
    assert v4.maximum_prefix == 1100


def test_nome_de_politica_repetido_recusa_a_adocao(db_session, tmp_path) -> None:
    """§4.4 no lado da escrita: a revisão pode editar o nome, e o que ela
    trouxer tem de valer contra o mesmo índice que a proposta consultou."""
    _site, dev = _ambiente(db_session, tmp_path)
    site = db_session.scalar(select(models.Site))
    org = create_organization(db_session, OrganizationCreate(name="Dono do Nome", asn=64997),
                              actor="cli")
    outro = create_circuit(db_session, CircuitCreate(
        code="CIRC-DONO-DO-NOME-ADOC", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/8", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=outro.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.30", remote_address="100.64.10.31",
        asn_local=65001, asn_remote=64997, import_route_policy="RP-EM-USO",
    ))
    db_session.commit()

    revisao = _revisao(dev, sessoes=[
        AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA,
                       import_route_policy="RP-EM-USO"),
        AdocaoSessaoIn(afi="ipv6"),
    ])
    with pytest.raises(ConflictError, match="mesmo nome de política"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")


def test_o_mesmo_nome_nas_duas_familias_recusa_a_adocao(db_session, tmp_path) -> None:
    """A repetição dentro da própria revisão também é recusada."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, sessoes=[
        AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA,
                       import_route_policy="RP-DUAS-VEZES"),
        AdocaoSessaoIn(afi="ipv6", import_route_policy="RP-DUAS-VEZES"),
    ])
    with pytest.raises(ConflictError, match="mesmo nome de política"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")
```

E, em `tests/automation/test_discovery.py`:

```python
BLOCO_UPSTREAM = {
    "tipo": "transito", "produto": "full", "papel": "principal",
    "expected_prefixes_v4": None, "expected_prefixes_v6": None,
    "max_prefix_margin_pct": 20, "entrada_local_preference": None,
    "contingencia_local_preference": None, "contingencia_prepend": None,
}


def test_a_conferencia_do_enlace_de_operadora_monta_o_vinculo(db_session, tmp_path) -> None:
    """§5.4: o bloco muda o que a conferência compara.

    O que este teste prende é o `upstream` ser consumido: sem ele o ensaio
    renderiza o enlace pelo caminho de cliente (o despacho do render é o
    vínculo, e sem vínculo não há outro caminho), e o grupo do peer sai de
    outras definições. Se o parâmetro fosse ignorado em silêncio, as duas
    conferências devolveriam a mesma lista. A afirmação mais forte — que o
    enlace de upstream sai SEM diferença que exija `ciente` — pede uma
    configuração reproduzível inteira do caminho de upstream, e quem a tem é
    `tests/automation/test_render_upstream.py`; repeti-la aqui seria uma
    segunda cópia da mesma fixture.
    """
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    proposta = next(iter(_propostas(db_session, dev).values()))
    perfis = {"ipv4": {"import_profile_id": None, "export_profile_id": None},
              "ipv6": {"import_profile_id": None, "export_profile_id": None}}

    sem_bloco = conferir_fidelidade(db_session, proposta, perfis=perfis)
    com_bloco = conferir_fidelidade(db_session, proposta, perfis=perfis,
                                    upstream=BLOCO_UPSTREAM)

    assert com_bloco != sem_bloco
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/domain/test_adocao.py -k "bloco_de_upstream or enlace_de_upstream"`
Expected: FAIL — `AdocaoUpstreamIn` não existe / `KindError`.

- [ ] **Step 3: O schema do bloco**

Em `schemas.py`, antes de `AdocaoIn`:

```python
class AdocaoUpstreamIn(BaseModel):
    """O bloco do upstream da revisão (design §5.2), em duas formas.

    Por vínculo (`upstream_id`) ou por criação (o resto dos campos, com `name` e
    `tipo` obrigatórios). `extra="forbid"` como os irmãos: o corpo vem de um
    `--json` e a chave digitada errado passaria calada. `produto_import` entra
    aqui porque a operadora não tem prefix-list própria (§7): o que a descreve é
    o produto, e é ele que o ensaio da conferência precisa ter em mãos.
    """

    model_config = ConfigDict(extra="forbid")

    upstream_id: int | None = None
    name: str | None = Field(default=None, min_length=2, max_length=128)
    tipo: Literal["transito", "ix", "pni", "contingencia"] | None = None
    capacity: str | None = Field(default=None, max_length=32)
    priority: int | None = None
    cost: str | None = Field(default=None, max_length=32)
    expected_prefixes_v4: int | None = None
    expected_prefixes_v6: int | None = None
    max_prefix_margin_pct: int = Field(default=20, ge=0, le=100)
    rpki_enabled: bool = True
    entrada_local_preference: int | None = None
    produto_import: Literal["full", "parcial", "default"] | None = None
    # `contingencia_*` não estão na lista do §5.2 e entram por uma razão só: sem
    # eles, o ensaio de um upstream NOVO com papel de contingência não teria o LP
    # e o prepend que a escrita vai gravar e acusaria diferença que não existe.
    contingencia_local_preference: int | None = None
    contingencia_prepend: int | None = Field(default=None, ge=0, le=10)
    papel: Literal["principal", "contingencia"] = "principal"
    ordem: int = 1

    @model_validator(mode="after")
    def _uma_das_formas(self) -> "AdocaoUpstreamIn":
        """Ou o vínculo, ou a criação — não os dois e não nenhum."""
        criacao = self.name is not None or self.tipo is not None
        if self.upstream_id is not None:
            if criacao:
                raise ValueError(
                    "O bloco do upstream é por vínculo (upstream_id) ou por criação "
                    "(name e tipo), não os dois."
                )
            return self
        if self.name is None or self.tipo is None:
            raise ValueError(
                "Informe o `upstream_id` ou os campos de criação do upstream "
                "(`name` e `tipo`)."
            )
        return self
```

Em `AdocaoIn`:

```python
    autorizacoes: list[AdocaoAutorizacaoIn] = Field(default_factory=list)
    sessoes: list[AdocaoSessaoIn] = Field(default_factory=list)
    # §5.1: organização operadora e bloco de upstream andam juntos.
    upstream: AdocaoUpstreamIn | None = None
    ciente: bool = False
```

- [ ] **Step 4: O bloco na forma do ensaio**

Em `domain/services/discovery.py`, antes de `adotar_proposta` (o import tardio
de `upstreams` é o mesmo motivo do de `automation.discovery`):

```python
def bloco_do_upstream(
    session: Session, *, upstream_id: int | None = None, tipo: str | None = None,
    produto_import: str | None = None, papel: str = "principal",
    expected_prefixes_v4: int | None = None, expected_prefixes_v6: int | None = None,
    max_prefix_margin_pct: int = 20,
    entrada_local_preference: int | None = None,
    contingencia_local_preference: int | None = None,
    contingencia_prepend: int | None = None,
) -> dict | None:
    """O bloco do upstream na forma que o ensaio lê (design §5.4).

    Com `upstream_id` os valores saem do upstream da SoT — é ele que o vínculo
    vai usar, e um ensaio com outros valores compararia outra coisa. Sem id,
    saem dos argumentos, que é a criação da revisão. Sem tipo e sem id não há
    bloco: o enlace é de cliente.
    """
    if upstream_id is not None:
        from gerenet.domain.services.upstreams import get_upstream

        up = get_upstream(session, upstream_id)
        return {
            "tipo": up.tipo, "produto": up.produto_import, "papel": papel,
            "expected_prefixes_v4": up.expected_prefixes_v4,
            "expected_prefixes_v6": up.expected_prefixes_v6,
            "max_prefix_margin_pct": up.max_prefix_margin_pct,
            "entrada_local_preference": up.entrada_local_preference,
            "contingencia_local_preference": up.contingencia_local_preference,
            "contingencia_prepend": up.contingencia_prepend,
        }
    if tipo is None:
        return None
    return {
        "tipo": tipo, "produto": produto_import, "papel": papel,
        "expected_prefixes_v4": expected_prefixes_v4,
        "expected_prefixes_v6": expected_prefixes_v6,
        "max_prefix_margin_pct": max_prefix_margin_pct,
        "entrada_local_preference": entrada_local_preference,
        "contingencia_local_preference": contingencia_local_preference,
        "contingencia_prepend": contingencia_prepend,
    }
```

- [ ] **Step 5: O upstream no ensaio**

Em `automation/discovery.py`, a assinatura de `_ensaio` ganha:

```python
    upstream: dict | None = None,
```

(depois de `velocidade_mbps`, ainda nas keyword-only) e, no docstring:

```python
    `upstream` é o bloco do §5.4 — tipo, produto e papel, mais os números de que
    `propagar_defaults` precisa. Sem ele o ensaio de um enlace de operadora
    renderiza pelo caminho de cliente (o despacho do render é o vínculo) e acusa
    diferença em tudo. Com ele, o ensaio monta o upstream descartável, vincula o
    circuito e roda a mesma propagação que a escrita roda no passo 8 — é ela que
    preenche o perfil de importação pelo produto e recalcula o maximum-prefix, e
    um ensaio que não a rodasse compararia um estado que a escrita não produz.
```

No corpo, depois do laço das VLANs e prefixos e **antes** do laço das sessões:

```python
    up_ensaio: models.Upstream | None = None
    if upstream is not None:
        up_ensaio = models.Upstream(
            # Nome de descartável, como o da organização: o upstream real da
            # revisão ainda não existe (ou é outro, quando a revisão vinculou um
            # existente, e aí o ensaio não pode tocar nele).
            name=f"ENSAIO-UP-{device.name}-{proposta.vid}",
            organization_id=org_id, tipo=upstream["tipo"],
            produto_import=upstream.get("produto"),
            expected_prefixes_v4=upstream.get("expected_prefixes_v4"),
            expected_prefixes_v6=upstream.get("expected_prefixes_v6"),
            max_prefix_margin_pct=upstream.get("max_prefix_margin_pct", 20),
            entrada_local_preference=upstream.get("entrada_local_preference"),
            contingencia_local_preference=upstream.get("contingencia_local_preference"),
            contingencia_prepend=upstream.get("contingencia_prepend"),
            admin_status=True,
        )
        session.add(up_ensaio)
        session.flush()
        session.add(models.UpstreamCircuit(
            upstream_id=up_ensaio.id, circuit_id=circ.id,
            papel=upstream.get("papel", "principal"), ordem=1,
        ))
        session.flush()
```

E, depois do laço das sessões e do `session.flush()` dele:

```python
    if up_ensaio is not None:
        # A MESMA propagação que a escrita roda no passo 8 (§5.3), e não uma
        # reimplementação: sem ela o ensaio deixa o perfil de importação nulo (o
        # render cai no fail-safe deny-all) e o maximum-prefix como veio do
        # equipamento — nos dois casos, um estado que a escrita não produz.
        session.refresh(up_ensaio, ["circuitos"])
        propagar_defaults(session, up_ensaio)
        session.flush()
```

Import no topo de `automation/discovery.py`:

```python
from gerenet.domain.services.upstreams import propagar_defaults
```

Verifique o ciclo antes de commitar: `upstreams.py` importa
`bgp_sessions`, `circuits`, `devices`, `organizations` — nenhum deles importa
`automation.discovery`. Se `uv run pytest -q tests/automation/test_discovery.py`
estourar com `ImportError: cannot import name`, o import vai para dentro de
`_ensaio` (mesma forma do resto do arquivo).

- [ ] **Step 6: O parâmetro na conferência e o `kind` da revisão**

`conferir_fidelidade` ganha `upstream: dict | None = None` na lista de
keyword-only, repassa para `_ensaio`:

```python
            criados = _ensaio(
                session, proposta, perfis, edge_trunk,
                circuit_code=circuit_code, organizacao_id=organizacao_id,
                organizacao_nome=organizacao_nome, organizacao_kind=organizacao_kind,
                autorizacoes=autorizacoes, velocidade_mbps=velocidade_mbps,
                upstream=upstream,
            )
```

- [ ] **Step 7: A coerência, o bloco e a ordem na escrita**

Em `adotar_proposta`, acrescentar `get_organization` ao import de
`gerenet.domain.services.organizations` no topo e, logo depois do bloco do
`_confere_nome_livre` (linha ~246) — **antes** da conferência, pela mesma razão
dos outros guardas: a primeira mensagem tem de ser a que diz o que corrigir:

```python
    # §5.1: o `kind` e o bloco do upstream andam juntos. O render despacha o
    # enlace pelo vínculo (`upstream_do_circuito`) e `_autorizadas_clientes`
    # filtra pelo `kind`: organização operadora sem vínculo é o único estado em
    # que os dois critérios discordam, e ele não deve nascer pela adoção.
    kind = _kind_da_revisao(session, revisao)
    if kind is not None and (kind == "operadora") != (revisao.upstream is not None):
        if kind == "operadora":
            raise ValidationError(
                "A organização é operadora e a revisão não traz o bloco `upstream`: "
                "sem o vínculo o render trata o enlace como cliente e o conjunto de "
                "autorizações sai de outro caminho. Vincule um upstream existente ou "
                "crie o novo no bloco `upstream`."
            )
        raise ValidationError(
            f"O bloco `upstream` exige organização operadora, e a revisão traz "
            f"{kind}: o enlace de upstream tem o conjunto de autorizações da "
            "operadora, e essa organização não. Escolha uma operadora ou retire o "
            "bloco."
        )
```

Com o helper, no fim do arquivo (antes de `adotar_proposta`):

```python
def _kind_da_revisao(session: Session, revisao: schemas.AdocaoIn) -> str | None:
    """O `kind` que a organização da revisão tem ou terá (a nova vence).

    `None` quando a revisão não traz organização nenhuma: aí quem recusa é a
    guarda do "Informe a organização", mais adiante, e a coerência do §5.1 não
    tem com o que comparar.
    """
    if revisao.organizacao_nova is not None:
        return revisao.organizacao_nova.kind
    if revisao.organizacao_id is not None:
        return get_organization(session, revisao.organizacao_id).kind
    return None


def _recusa_nome_de_politica_repetido(
    session: Session, revisao: schemas.AdocaoIn, from_discovery
) -> None:
    """§4.4 no lado da escrita: a revisão pode editar os nomes, e o que ela
    trouxer tem de valer contra o mesmo índice que a proposta consultou."""
    nomes: dict[str, list[str]] = {}
    for s in revisao.sessoes:
        for nome in (s.import_route_policy, s.export_route_policy):
            if nome:
                nomes.setdefault(nome, []).append(s.afi)
    em_uso = from_discovery._politicas_em_uso(session, revisao.device_id)
    repetidos = sorted(n for n, afis in nomes.items() if len(afis) > 1 or n in em_uso)
    if not repetidos:
        return
    onde = "; ".join(
        f"{n} ({'duas famílias da revisão' if len(nomes[n]) > 1 else em_uso[n]})"
        for n in repetidos
    )
    raise ConflictError(
        f"A política {onde} já tem dono no mesmo equipamento: dois peers com o mesmo "
        "nome de política conviveriam sob um cabeçalho só. Adote sem importar o nome, "
        "ou cadastre a política compartilhada à mão."
    )
```

O `from_discovery` é o módulo, que `adotar_proposta` já importa tardiamente —
estenda o import:

```python
    from gerenet.automation import discovery as from_discovery
    from gerenet.automation.discovery import (
        _trunk_da_subinterface, conferir_fidelidade,
    )
```

e chame a guarda logo depois da de autorizações (linha ~257):

```python
    _recusa_nome_de_politica_repetido(session, revisao, from_discovery)
```

Depois, a conferência ganha o bloco:

```python
    bloco_up = bloco_do_upstream(
        session,
        upstream_id=revisao.upstream.upstream_id if revisao.upstream else None,
        tipo=revisao.upstream.tipo if revisao.upstream else None,
        produto_import=revisao.upstream.produto_import if revisao.upstream else None,
        papel=revisao.upstream.papel if revisao.upstream else "principal",
        expected_prefixes_v4=revisao.upstream.expected_prefixes_v4 if revisao.upstream else None,
        expected_prefixes_v6=revisao.upstream.expected_prefixes_v6 if revisao.upstream else None,
        max_prefix_margin_pct=(
            revisao.upstream.max_prefix_margin_pct if revisao.upstream else 20
        ),
        entrada_local_preference=(
            revisao.upstream.entrada_local_preference if revisao.upstream else None
        ),
        contingencia_local_preference=(
            revisao.upstream.contingencia_local_preference if revisao.upstream else None
        ),
        contingencia_prepend=(
            revisao.upstream.contingencia_prepend if revisao.upstream else None
        ),
    )
    difs = conferir_fidelidade(
        session, proposta, perfis=perfis, edge_trunk=revisao.edge_trunk,
        circuit_code=revisao.circuit_code, organizacao_id=revisao.organizacao_id,
        organizacao_nome=revisao.organizacao_nova.name if revisao.organizacao_nova else None,
        organizacao_kind=revisao.organizacao_nova.kind if revisao.organizacao_nova else None,
        autorizacoes=[(b.prefix, b.family) for b in revisao.autorizacoes],
        velocidade_mbps=revisao.velocidade_mbps,
        upstream=bloco_up,
    )
```

E a transação, com o upstream no lugar que o §5.3 manda (passo 3, depois das
autorizações e antes do circuito):

```python
        up: models.Upstream | None = None
        if revisao.upstream is not None:
            if revisao.upstream.upstream_id is not None:
                up = get_upstream(session, revisao.upstream.upstream_id)
                if up.organization_id != organizacao_id:
                    raise ValidationError(
                        f"O upstream {up.name} é de outra organização: vincule um "
                        "upstream da operadora da revisão, ou crie o novo no bloco."
                    )
                if up.admin_status is False:
                    raise ConflictError(
                        f"O upstream {up.name} está desativado: reative antes de adotar."
                    )
                # Vinculado é vinculado: os campos de criação não se aplicam, e o
                # upstream não muda — a revisão só escolheu qual é. O vínculo sai
                # no bloco de baixo, junto com o do caminho de criação.
            else:
                up = create_upstream(
                    session,
                    schemas.UpstreamCreate(
                        name=revisao.upstream.name, tipo=revisao.upstream.tipo,
                        organization_id=organizacao_id,
                        capacity=revisao.upstream.capacity,
                        priority=revisao.upstream.priority,
                        cost=revisao.upstream.cost,
                        expected_prefixes_v4=revisao.upstream.expected_prefixes_v4,
                        expected_prefixes_v6=revisao.upstream.expected_prefixes_v6,
                        max_prefix_margin_pct=revisao.upstream.max_prefix_margin_pct,
                        rpki_enabled=revisao.upstream.rpki_enabled,
                        entrada_local_preference=revisao.upstream.entrada_local_preference,
                        contingencia_local_preference=(
                            revisao.upstream.contingencia_local_preference
                        ),
                        contingencia_prepend=revisao.upstream.contingencia_prepend,
                        produto_import=revisao.upstream.produto_import,
                    ),
                    actor=actor, commit=False,
                )
```

A ordem importa e é sutil, então leia antes de colar: o bloco acima **só resolve
o `up`** (busca o existente com as duas validações, ou cria o novo) — ele não
vincula. `vincular_circuito` precisa do `circuito`, que ainda não existe nesse
ponto do §5.3 (o upstream é o passo 3, o circuito é o 4). Ponha o bloco acima
**antes** do `create_circuit`, e o vínculo **depois** da `reservar_adocao`, com
os dois caminhos num lugar só:

```python
        # Passo 5 do §5.3: o vínculo é depois do circuito, pelos dois caminhos —
        # o `up` já veio resolvido do passo 3 (buscado ou criado).
        if up is not None:
            vincular_circuito(
                session, up.id, circuito.id, papel=revisao.upstream.papel,
                ordem=revisao.upstream.ordem, actor=actor, commit=False,
            )
```

Depois das sessões e antes do `registrar` (passo 8 do §5.3):

```python
        if up is not None:
            propagar_defaults(session, up)
```

Import no topo de `domain/services/discovery.py`:

```python
from gerenet.domain.services.upstreams import (
    create_upstream, get_upstream, propagar_defaults, vincular_circuito,
)
```

Se o ciclo estourar, mova para dentro de `adotar_proposta`.

E o evento ganha o bloco:

```python
                "upstream": (
                    {
                        "upstream_id": up.id,
                        "papel": revisao.upstream.papel,
                        "ordem": revisao.upstream.ordem,
                        "criado": revisao.upstream.upstream_id is None,
                        "tipo": up.tipo,
                        "produto_import": up.produto_import,
                    }
                    if up is not None else None
                ),
```

- [ ] **Step 8: Atualizar o teste da operadora que já existia**

`test_operadora_nao_recebe_as_autorizacoes_da_adoção` passava pela guarda do
`create_authorization`; com o §5.1 ele é barrado antes, pela coerência. Dê a
revisão dele um bloco de upstream, para que ele volte a exercitar o que o teste
nomeia:

```python
    revisao.organizacao_nova.kind = "operadora"
    revisao.upstream = AdocaoUpstreamIn(name="up-do-teste", tipo="transito")
```

- [ ] **Step 9: Rodar e ver passar**

Run: `uv run pytest -q tests/domain/test_adocao.py tests/automation/test_discovery.py tests/api/test_discovery_adopt_api.py`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/discovery.py \
        src/gerenet/automation/discovery.py tests/domain/test_adocao.py \
        tests/automation/test_discovery.py
git commit -m "feat(adoção): o bloco do upstream na revisão, no ensaio e na transação"
```

---

### Task 9: As rotas — o bloco `circuito` no upstream e o upstream no `fidelidade`

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`UpstreamCircuitoIn`, `UpstreamCreateIn`)
- Modify: `src/gerenet/domain/services/upstreams.py` (`criar_com_circuito` novo)
- Modify: `src/gerenet/api/routers/upstreams.py` (`criar`)
- Modify: `src/gerenet/api/routers/discovery.py` (`fidelidade` 180-261)
- Test: `tests/api/test_upstreams_router.py`, `tests/api/test_discovery_adopt_api.py`

**Interfaces:**
- Consumes: `create_upstream`/`vincular_circuito` com `commit` (Task 7); `bloco_do_upstream` (Task 8).
- Produces: `schemas.UpstreamCircuitoIn`; `schemas.UpstreamCreateIn`; `services.upstreams.criar_com_circuito(session, data, circuito, *, actor, commit=True) -> models.Upstream`.

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/api/test_upstreams_router.py`. O arquivo já tem o fixture
`client`, o helper `_auth()` e o `_ambiente(db_session)` que devolve
`{"org_id", "site_id", "sw_id", "ne_id"}`. Acrescente `from sqlalchemy import
select` ao topo (o arquivo ainda não o importa).

```python
def _corpo_com_acesso(env: dict, *, nome: str, code: str) -> dict:
    return {
        "name": nome, "tipo": "transito", "organization_id": env["org_id"],
        "produto_import": "full",
        "circuito": {
            "code": code, "site_id": env["site_id"], "edge_device_id": env["ne_id"],
            "edge_trunk": "Eth-Trunk127", "access_device_id": env["sw_id"],
            "access_port": "GE0/0/1", "velocidade_mbps": 1024,
        },
    }


def test_post_com_bloco_de_circuito_cria_e_vincula(client: TestClient, db_session: Session) -> None:
    """§6: o acesso entra no cadastro do upstream e o circuito nasce vinculado
    como principal, na mesma chamada."""
    env = _ambiente(db_session)
    resp = client.post("/api/v1/upstreams", headers=_auth(),
                       json=_corpo_com_acesso(env, nome="up-com-acesso", code="CIRC-ACESSO"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["produto_import"] == "full"

    circ = db_session.scalar(select(models.Circuit).where(models.Circuit.code == "CIRC-ACESSO"))
    assert (circ.velocidade_mbps, circ.edge_trunk) == (1024, "Eth-Trunk127")
    assert circ.organization_id == env["org_id"]
    vinculo = db_session.scalar(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.circuit_id == circ.id
    ))
    assert (vinculo.upstream_id, vinculo.papel, vinculo.ordem) == (resp.json()["id"], "principal", 1)


def test_o_bloco_de_circuito_que_falha_nao_deixa_upstream(client: TestClient,
                                                          db_session: Session) -> None:
    """A transação é uma só: o mesmo código de circuito na segunda chamada
    derruba os dois, e o upstream não fica órfão."""
    env = _ambiente(db_session)
    primeira = client.post("/api/v1/upstreams", headers=_auth(),
                           json=_corpo_com_acesso(env, nome="up-primeiro", code="CIRC-REPETIDO"))
    assert primeira.status_code == 201, primeira.text

    segunda = client.post("/api/v1/upstreams", headers=_auth(),
                          json=_corpo_com_acesso(env, nome="up-sem-circuito", code="CIRC-REPETIDO"))
    assert segunda.status_code in (409, 422), segunda.text
    assert db_session.scalars(select(models.Upstream).where(
        models.Upstream.name == "up-sem-circuito"
    )).all() == []


def test_o_bloco_de_circuito_recusa_organization_id(client: TestClient, db_session: Session) -> None:
    """`extra="forbid"` no bloco: a organização do circuito é a do upstream, e um
    campo a mais passaria calado."""
    env = _ambiente(db_session)
    corpo = _corpo_com_acesso(env, nome="up-com-org-no-bloco", code="CIRC-ORG")
    corpo["circuito"]["organization_id"] = env["org_id"]
    resp = client.post("/api/v1/upstreams", headers=_auth(), json=corpo)
    assert resp.status_code == 422, resp.text


def test_o_post_sem_bloco_continua_igual(client: TestClient, db_session: Session) -> None:
    """O contrato de hoje não muda: os campos do upstream na raiz do corpo."""
    env = _ambiente(db_session)
    resp = client.post("/api/v1/upstreams", headers=_auth(), json={
        "name": "up-sem-acesso", "tipo": "ix", "organization_id": env["org_id"],
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["produto_import"] is None
    assert db_session.scalars(select(models.UpstreamCircuit)).all() == []
```

E em `tests/api/test_discovery_adopt_api.py`, no fim:

```python
def test_a_conferencia_de_upstream_recebe_o_bloco_por_query(client: TestClient, db_session,
                                                            tmp_path: Path) -> None:
    """§5.4: sem o bloco o diff de um enlace de operadora acusa tudo; com ele, a
    rota monta o ensaio pelo caminho de upstream."""
    from gerenet.domain.schemas import UpstreamCreate
    from gerenet.domain.services.upstreams import create_upstream

    ambiente = _ambiente(db_session, tmp_path)
    operadora = create_organization(
        db_session,
        OrganizationCreate(name="Operadora Conf", asn=64533, kind="operadora"),
        actor="cli",
    )
    up = create_upstream(db_session, UpstreamCreate(
        name="up-conf", tipo="transito", organization_id=operadora.id,
    ), actor="cli")

    url = (f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}"
           "&subinterface=Eth-Trunk127.1001")
    sem_bloco = client.get(url, headers=_auth())
    com_bloco = client.get(f"{url}&upstream_id={up.id}", headers=_auth())
    assert sem_bloco.status_code == com_bloco.status_code == 200
    # O bloco muda o que a conferência compara: o ensaio passa a montar o vínculo
    # e a renderizar pelo caminho de upstream. Sem ele o render trata o enlace
    # como cliente (prefix-list de importação pelas autorizações, export pelo
    # produto), e o grupo do peer sai de outro caminho — as duas respostas não
    # podem ser iguais.
    assert com_bloco.json()["diferencas"] != sem_bloco.json()["diferencas"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/api/test_upstreams_router.py -k bloco_de_circuito`
Expected: FAIL — o campo `circuito` é ignorado e o circuito não nasce.

- [ ] **Step 3: Os schemas do corpo**

Em `schemas.py`, depois de `UpstreamUpdate`:

```python
class UpstreamCircuitoIn(BaseModel):
    """O circuito de acesso do cadastro do upstream (§6).

    Só identidade e acesso: a reserva de VLAN e de endereços continua na página
    do circuito, que já tem o assistente, e o vínculo não exige reserva. A
    organização do circuito é a do upstream — não há campo para ela aqui, e é
    por isso que um `organization_id` a mais seria recusado.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    site_id: int
    edge_device_id: int
    edge_trunk: str | None = Field(default=None, max_length=64)
    access_device_id: int
    access_port: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9/\-]+$")
    velocidade_mbps: int | None = Field(default=None, gt=0, le=100000)


class UpstreamCreateIn(UpstreamCreate):
    """O corpo do `POST /api/v1/upstreams`: o upstream e, opcional, o acesso (§6).

    Herda os campos do `UpstreamCreate` em vez de aninhá-los, para o contrato de
    hoje (os campos do upstream na raiz do corpo) seguir valendo — quem já
    postava sem o bloco não muda nada.
    """

    circuito: UpstreamCircuitoIn | None = None
```

- [ ] **Step 4: O serviço que faz os dois numa transação**

Em `upstreams.py`, depois de `create_upstream`:

```python
def criar_com_circuito(
    session: Session, data: schemas.UpstreamCreate,
    circuito: schemas.UpstreamCircuitoIn | None = None, *, actor: str, commit: bool = True,
) -> models.Upstream:
    """Cadastra o upstream e, com o bloco de acesso, o circuito vinculado (§6).

    Uma transação: o upstream, o circuito e o vínculo principal nascem juntos,
    ou nada nasce. O circuito nasce sem reserva — quem reserva VLAN e endereços é
    a página do circuito.
    """
    up = create_upstream(session, data, actor=actor, commit=False)
    if circuito is None:
        if commit:
            session.commit()
            session.refresh(up)
        return up
    try:
        circ = create_circuit(
            session,
            schemas.CircuitCreate(
                code=circuito.code, organization_id=data.organization_id,
                site_id=circuito.site_id, access_device_id=circuito.access_device_id,
                access_port=circuito.access_port, edge_device_id=circuito.edge_device_id,
                edge_trunk=circuito.edge_trunk, velocidade_mbps=circuito.velocidade_mbps,
            ),
            actor=actor, commit=False,
        )
        vincular_circuito(session, up.id, circ.id, papel="principal", ordem=1,
                          actor=actor, commit=False)
        if commit:
            session.commit()
            session.refresh(up)
    except Exception:
        # Qualquer recusa depois do upstream desfaz o que já foi gravado: sem
        # isto o upstream ficaria pendente na transação de quem chamou. O
        # `if commit` é o que impede esta limpeza de levar junto a transação de
        # um chamador que compôs com `commit=False` — a mesma fronteira dos
        # outros serviços.
        if commit:
            session.rollback()
        raise
    return up
```

Imports que faltam em `upstreams.py`: `from gerenet.domain import schemas` e
`from gerenet.domain.services.circuits import create_circuit`.

- [ ] **Step 5: A rota**

Em `api/routers/upstreams.py`, no `criar`:

```python
@router.post("", response_model=UpstreamOut, status_code=201)
def criar(
    data: schemas.UpstreamCreateIn,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    """Cadastra o upstream — e, com o bloco `circuito`, o acesso já vinculado (§6)."""
    # O `UpstreamCreate` é reconstruído sem o bloco: o `model_dump()` do serviço
    # vira `models.Upstream(**dump)`, e uma chave a mais estoura o construtor.
    dados = schemas.UpstreamCreate(**data.model_dump(exclude={"circuito"}))
    try:
        up = svc.criar_com_circuito(session, dados, data.circuito, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _com_organizacao(session, up)
```

(preserve o helper e os códigos de status que o `criar` já usa hoje — o
`_com_organizacao` é o que o arquivo já tiver para preencher `organization_kind`
/`organization_name`.)

- [ ] **Step 6: O bloco do upstream no `fidelidade`**

Em `api/routers/discovery.py`, na assinatura de `fidelidade`, depois de
`velocidade_mbps`:

```python
    organizacao_kind: str | None = None,
    upstream_id: int | None = None,
    upstream_tipo: str | None = None,
    upstream_produto: str | None = None,
    upstream_papel: str = "principal",
    upstream_expected_v4: int | None = None,
    upstream_expected_v6: int | None = None,
    upstream_margem: int = 20,
```

e, na chamada:

```python
            organizacao_kind=organizacao_kind,
            upstream=bloco_do_upstream(
                session, upstream_id=upstream_id, tipo=upstream_tipo,
                produto_import=upstream_produto, papel=upstream_papel,
                expected_prefixes_v4=upstream_expected_v4,
                expected_prefixes_v6=upstream_expected_v6,
                max_prefix_margin_pct=upstream_margem,
            ),
```

com `from gerenet.domain.services.discovery import bloco_do_upstream` no topo do
router.

O `organizacao_kind` é o sexto parâmetro de identidade e faltava na rota: o
`_ensaio` já o aceita e o `conferir_fidelidade` já o repassa (`_ensaio` cai em
`"downstream"` quando ele não vem), mas a rota não o declarava, então TODA
conferência de preview rodava com a organização descartável como cliente. Sem o
§5.1 isso passava despercebido; com ele o preview de uma operadora acusaria as
diferenças do caminho de cliente que a adoção não vai criar — e o operador
marcaria `ciente` por uma linha que nunca muda. A página passa o kind que o
select escolheu (Task 12).

- [ ] **Step 7: Rodar e ver passar**

Run: `uv run pytest -q tests/api/`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/upstreams.py \
        src/gerenet/api/routers/upstreams.py src/gerenet/api/routers/discovery.py \
        tests/api/test_upstreams_router.py tests/api/test_discovery_adopt_api.py
git commit -m "feat(api): o acesso no cadastro do upstream e o bloco do upstream na conferência"
```

---

### Task 10: O CLI

**Files:**
- Modify: `src/gerenet/cli/bgp_sessions.py` (`add`, perto da linha 100)
- Modify: `src/gerenet/cli/upstreams.py` (`add`, linha 45)
- Test: `tests/cli/test_bgp_sessions_cli.py`, `tests/cli/test_upstreams_cli.py`

**Interfaces:**
- Consumes: `BgpSessionCreate` com os três campos (Task 4); `UpstreamCreate` com `produto_import` (Task 7); `UpstreamCircuitoIn` e `criar_com_circuito` (Task 9).
- Produces: flags de CLI.

> **Desvio registrado do spec.** O §8 escreve `bgp-sessions add/update
> --default-route-advertise ...`. O CLI **não tem** o comando `update` (tem
> `add`, `list`, `disable`, `password set` e `community add/remove`), e criar um
> não é desta frente: o `PATCH /api/v1/bgp-sessions/{id}` e a página da web já
> edição. As três flags entram no `add`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/cli/test_bgp_sessions_cli.py`:

```python
def test_add_com_anuncio_e_nomes_de_politica(runner, db_session) -> None:
    result = runner.invoke(app, [
        "add", "--circuit-id", str(circ_id), "--device-id", str(ne_id),
        "--afi", "ipv4", "--local-address", "100.64.0.1", "--remote-address", "100.64.0.2",
        "--default-route-advertise",
        "--import-route-policy", "RP-LIDO-IN",
        "--export-route-policy", "RP-LIDO-OUT",
    ])
    assert result.exit_code == 0
    sessao = db_session.scalar(select(models.BgpSession))
    assert sessao.default_route_advertise is True
    assert sessao.import_route_policy == "RP-LIDO-IN"
```

Em `tests/cli/test_upstreams_cli.py`:

```python
def test_add_com_produto_e_circuito(runner, db_session) -> None:
    result = runner.invoke(app, [
        "add", "--name", "up-cli", "--tipo", "transito",
        "--organization-id", str(org_id), "--produto-import", "parcial",
        "--circuito-codigo", "CIRC-CLI", "--site", str(site_id),
        "--edge-device", str(ne_id), "--access-device", str(sw_id),
        "--access-port", "GE0/0/2", "--velocidade-mbps", "1024",
    ])
    assert result.exit_code == 0
    up = db_session.scalar(select(models.Upstream).where(models.Upstream.name == "up-cli"))
    assert up.produto_import == "parcial"
    circ = db_session.scalar(select(models.Circuit).where(models.Circuit.code == "CIRC-CLI"))
    vinculo = db_session.scalar(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.circuit_id == circ.id
    ))
    assert vinculo.upstream_id == up.id


def test_circuito_sem_site_ou_edge_recusa(runner, db_session) -> None:
    result = runner.invoke(app, [
        "add", "--name", "up-cli-2", "--tipo", "ix",
        "--organization-id", str(org_id), "--circuito-codigo", "CIRC-CLI-2",
    ])
    assert result.exit_code != 0
    assert "--site" in result.output
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/cli/ -k "anuncio_e_nomes or produto_e_circuito"`
Expected: FAIL — `no such option: --default-route-advertise`.

- [ ] **Step 3: As flags do `bgp-sessions add`**

No fim da assinatura de `add`, depois de `allow_default_route`:

```python
    default_route_advertise: bool = typer.Option(
        False, "--default-route-advertise",
        help="Anuncia a rota default ao peer (caminho de cliente).",
    ),
    import_route_policy: str | None = typer.Option(
        None, "--import-route-policy",
        help="Nome da route-policy de importação lido no equipamento (o render passa a emiti-lo).",
    ),
    export_route_policy: str | None = typer.Option(
        None, "--export-route-policy",
        help="Nome da route-policy de exportação lido no equipamento.",
    ),
```

e na construção do `BgpSessionCreate`:

```python
                    allow_default_route=allow_default_route,
                    default_route_advertise=default_route_advertise,
                    import_route_policy=import_route_policy,
                    export_route_policy=export_route_policy,
```

- [ ] **Step 4: As opções do `upstreams add`**

Na assinatura de `add`, depois de `contingencia_notes`:

```python
    produto_import: str | None = typer.Option(
        None, "--produto-import", help="Tipo de rota da operadora: full, parcial ou default."
    ),
    circuito_codigo: str | None = typer.Option(
        None, "--circuito-codigo", help="Código do circuito de acesso a criar e vincular (§6)."
    ),
    site: int | None = typer.Option(None, "--site", help="ID do site do circuito (§6)."),
    edge_device: int | None = typer.Option(
        None, "--edge-device", help="ID do roteador de borda do circuito (§6)."
    ),
    edge_trunk: str | None = typer.Option(None, "--edge-trunk", help="Eth-Trunk de borda."),
    access_device: int | None = typer.Option(
        None, "--access-device", help="ID do switch de acesso (default: o próprio edge)."
    ),
    access_port: str | None = typer.Option(
        None, "--access-port", help="Porta de acesso (default GE0/0/1)."
    ),
    velocidade_mbps: int | None = typer.Option(
        None, "--velocidade-mbps", help="Velocidade contratada em Mbps."
    ),
```

E a chamada passa a montar o bloco e usar o serviço novo:

```python
    if circuito_codigo is not None and (site is None or edge_device is None):
        typer.echo(
            "Erro: --circuito-codigo exige --site e --edge-device.", err=True
        )
        raise typer.Exit(1)
    bloco = (
        UpstreamCircuitoIn(
            code=circuito_codigo, site_id=site, edge_device_id=edge_device,
            edge_trunk=edge_trunk, access_device_id=access_device or edge_device,
            access_port=access_port or "GE0/0/1", velocidade_mbps=velocidade_mbps,
        )
        if circuito_codigo is not None else None
    )
```

E a chamada que hoje é `svc.create_upstream(session, UpstreamCreate(...), actor="cli")`
(linhas 73-90) passa a ser, com `produto_import` acrescentado ao `UpstreamCreate`
que já está lá:

```python
            up = svc.criar_com_circuito(
                session,
                UpstreamCreate(
                    name=name,
                    tipo=tipo,
                    organization_id=organization_id,
                    capacity=capacity,
                    priority=priority,
                    cost=cost,
                    expected_prefixes_v4=expected_prefixes_v4,
                    expected_prefixes_v6=expected_prefixes_v6,
                    max_prefix_margin_pct=max_prefix_margin_pct,
                    rpki_enabled=rpki_enabled,
                    entrada_local_preference=entrada_local_preference,
                    contingencia_local_preference=contingencia_local_preference,
                    contingencia_prepend=contingencia_prepend,
                    contingencia_notes=contingencia_notes,
                    produto_import=produto_import,
                ),
                bloco,
                actor="cli",
            )
```

O `UpstreamCircuitoIn` entra no import do topo do arquivo, junto dos outros
schemas (linha 7: `from gerenet.domain.schemas import UpstreamCommunityCreate,
UpstreamCreate, UpstreamUpdate` → acrescente `UpstreamCircuitoIn`).

(`produto_import: str | None` na flag e `Literal` no schema: o
`SchemaValidationError` já é capturado pelo `except` do comando e sai como
mensagem em PT-BR.)

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest -q tests/cli/ && uv run ruff check src tests`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/cli/bgp_sessions.py src/gerenet/cli/upstreams.py \
        tests/cli/test_bgp_sessions_cli.py tests/cli/test_upstreams_cli.py
git commit -m "feat(cli): o anúncio e os nomes na sessão, o produto e o acesso no upstream"
```

---

### Task 11: Web — o checkbox por escopo

**Files:**
- Modify: `web/src/api/types.ts` (`BgpSessionOut` 123-150)
- Modify: `web/src/help.ts` (linha 88 e uma chave nova)
- Modify: `web/src/pages/BgpSessions.tsx` (`FORM_VAZIO` 25-50, `abrirEdicao` 129-156, `salvarEdicao` 158-192, `onSubmit` 194-226, os dois blocos de checkbox ~312-334 e ~481-510)
- Test: `web/src/pages/BgpSessions.test.tsx`

**Interfaces:**
- Consumes: `BgpSessionOut.upstream_id`, `.default_route_advertise`, `.import_route_policy`, `.export_route_policy` (Task 4); `BgpSessionCreateIn`/`useBgpSessionCriar`/`useBgpSessionAtualizar` existentes.
- Produces: nada consumido por outra task.

- [ ] **Step 1: Escrever o teste que falha**

Em `web/src/pages/BgpSessions.test.tsx` (siga o padrão de mock de `useBgpSessions`
que o arquivo já usa):

O arquivo tem um `sessao` de módulo que o `fetch` stubbado devolve na listagem;
os dois testes o mutam antes do `render`. Escreva os dois no mesmo `describe` dos
testes de sessão que já existem:

```tsx
it("mostra o anúncio ao cliente e não o do provedor, na sessão sem vínculo", async () => {
  sessao.upstream_id = null;
  render(<BgpSessions />);
  await userEvent.click(screen.getAllByRole("button", { name: /editar/i })[0]);
  expect(screen.getByLabelText("Anunciar rota default ao cliente")).toBeInTheDocument();
  expect(screen.queryByLabelText("Aceitar rota default do provedor")).not.toBeInTheDocument();
});

it("mostra o aceite do provedor e não o anúncio, na sessão de upstream", async () => {
  sessao.upstream_id = 7;
  render(<BgpSessions />);
  await userEvent.click(screen.getAllByRole("button", { name: /editar/i })[0]);
  expect(screen.getByLabelText("Aceitar rota default do provedor")).toBeInTheDocument();
  expect(screen.queryByLabelText("Anunciar rota default ao cliente")).not.toBeInTheDocument();
});
```

Se o `render` do arquivo já é embrulhado num helper (`QueryClientProvider` +
`MemoryRouter` + `AuthProvider`), use-o em vez do `render` cru — e, se a
listagem montar mais de uma linha, troque o `[0]` pelo índice da linha que o
`sessao` mutado produz.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && npm run test -- BgpSessions`
Expected: FAIL — o rótulo "Default route" é o mesmo nos dois casos.

- [ ] **Step 3: Os campos no tipo**

Em `web/src/api/types.ts`, no `BgpSessionOut`:

```ts
  default_route_advertise: boolean;
  import_route_policy: string | null;
  export_route_policy: string | null;
  upstream_id: number | null;
```

- [ ] **Step 4: Os textos de ajuda**

Em `web/src/help.ts`, trocar a linha 88 e acrescentar as duas chaves:

```ts
  "bgp.allow_default_route": "Sessão de upstream: aceita a rota default (0.0.0.0/0 ou ::/0) que o provedor anuncia. Só aparece na sessão de upstream.",
  "bgp.default_route_advertise": "Sessão de cliente: anuncia a rota default (0.0.0.0/0 ou ::/0) AO cliente (`peer X default-route-advertise`). Só aparece na sessão de cliente.",
  "bgp.import_route_policy": "Nome da route-policy de importação como está no equipamento. Preenchido, o gerenet emite a definição sob esse nome — e passa a gerenciar o corpo dela. Vazio, o nome volta ao padrão do gerenet (RP-<ASN>-IMPORT-<AFI>).",
  "bgp.export_route_policy": "Idem para a route-policy de exportação (RP-<ASN>-EXPORT-<AFI> quando vazio).",
```

- [ ] **Step 5: O formulário por escopo**

Em `BgpSessions.tsx`, `FORM_VAZIO` ganha:

```ts
  default_route_advertise: false,
  import_route_policy: "",
  export_route_policy: "",
```

`abrirEdicao` passa a levar os campos (`default_route_advertise`,
`import_route_policy ?? ""`, `export_route_policy ?? ""`) e a guardar
`upstream_id` no estado do formulário; `salvarEdicao`/`onSubmit` devolvem
`import_route_policy: form.import_route_policy.trim() || null` (idem export) —
o `null` explícito é o que limpa a coluna no PATCH.

Nos dois blocos de checkbox, trocar o bloco único por dois, escolhidos por
`upstream_id`:

```tsx
{form.upstream_id === null ? (
  <FormField label="Anunciar rota default ao cliente" help={help("bgp.default_route_advertise")}>
    <input
      type="checkbox"
      checked={form.default_route_advertise}
      onChange={(e) => set("default_route_advertise", e.target.checked)}
    />
  </FormField>
) : (
  <FormField label="Aceitar rota default do provedor" help={help("bgp.allow_default_route")}>
    <input
      type="checkbox"
      checked={form.allow_default_route}
      onChange={(e) => set("allow_default_route", e.target.checked)}
    />
  </FormField>
)}
```

Acrescente também os dois campos de nome (texto, com o `help` novo) no bloco do
formulário, ao lado dos perfis — o `FormField` com `<input type="text">` é o
padrão do arquivo.

- [ ] **Step 6: Rodar e ver passar**

Run: `cd web && npm run build && npm run test`
Expected: PASS — o `npm run build` valida as chaves do `help.ts`.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/types.ts web/src/help.ts web/src/pages/BgpSessions.tsx \
        web/src/pages/BgpSessions.test.tsx
git commit -m "feat(web): o checkbox de default route por escopo da sessão"
```

---

### Task 12: Web — a revisão da adoção

**Files:**
- Modify: `web/src/api/types.ts` (`DiscoveryAdocaoIn` 682-712, `DiscoveryPropostaOut` 618-643)
- Modify: `web/src/api/hooks.ts` (`IdentidadeDaConferencia` 857-876, `useFidelidade` 878-917)
- Modify: `web/src/pages/DiscoveryAdopt.tsx` (constantes 34-63, validações e `podeAdotar` 206-264, `adotarProposta` 295-356, JSX da organização 432-455, o laço de sessões 526-564)
- Modify: `web/src/help.ts` (bloco `adocao.*` 148-157)
- Test: `web/src/pages/Discovery.test.tsx`

> **O teste é na `Discovery.test.tsx`, não numa `DiscoveryAdopt.test.tsx`.** O
> diálogo é o componente `AdocaoDialog` exportado por `DiscoveryAdopt.tsx`, e
> quem o monta é a página `Discovery.tsx` (`import { AdocaoDialog } from
> "./DiscoveryAdopt"`, linha 16) no clique do "Adotar" da linha. O arquivo de
> teste da revisão é o `Discovery.test.tsx` (1228 linhas, a revisão inteira já
> é exercitada lá). **Não crie um arquivo novo**: ele teria de remontar o
> `PROPOSTA`/`DISCOVERY`, o `mockFetch` e o `renderDiscovery` que aquele arquivo
> já tem, e as duas cópias divergiriam na primeira mudança de contrato.

**Interfaces:**
- Consumes: `AdocaoUpstreamIn` e o bloco `upstream` do `AdocaoIn` (Task 8); os parâmetros `upstream_*` do `fidelidade` (Task 9); os campos de política do `BgpSessionOut` (Task 11).
- Produces: nada consumido por outra task.

- [ ] **Step 1: Escrever os testes que falham**

No mesmo bloco `describe` das revisões que já existem. O caminho é sempre o
mesmo: mockar, `renderDiscovery("/discovery?device_id=1")`, clicar o "Adotar" da
linha e trabalhar dentro do `dialog`.

```tsx
/** A proposta com o nome da política lido no equipamento, em cada família. */
function propostaComPolitica(importRoutePolicy: string) {
  return {
    ...PROPOSTA,
    sessoes: [{ ...PROPOSTA.sessoes[0], import_route_policy: importRoutePolicy }],
  };
}

it("deixa escolher o kind da organização", async () => {
  mockFetch({});
  renderDiscovery("/discovery?device_id=1");
  await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
  const dialog = screen.getByRole("dialog");

  // O select abre no palpite do `_classificar` (a proposta sem organização
  // sai como "downstream") e é o operador quem decide.
  const kind = within(dialog).getByRole("combobox", { name: /Tipo de organização/ });
  expect(kind).toHaveValue("downstream");
  await userEvent.selectOptions(kind, "operadora");
  expect(within(dialog).getByText(/Upstream/)).toBeInTheDocument();
});

it("mostra o nome da política lido em cada família", async () => {
  mockFetch({
    descoberta: { ...DISCOVERY, propostas: [propostaComPolitica("RP-LIDA-IMPORT")] },
  });
  renderDiscovery("/discovery?device_id=1");
  await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
  const dialog = screen.getByRole("dialog");

  expect(await within(dialog).findByDisplayValue("RP-LIDA-IMPORT")).toBeInTheDocument();
});

it("recusa adotar operadora sem o bloco de upstream", async () => {
  mockFetch({});
  renderDiscovery("/discovery?device_id=1");
  await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
  const dialog = screen.getByRole("dialog");

  // Preenche o que a adoção exige ANTES de escolher a operadora: sem isto o
  // botão já estaria barrado pelo acesso em falta, e o teste não diria nada
  // sobre a guarda do §5.1.
  await preencheAcesso(dialog);
  await waitFor(() =>
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
  );

  await userEvent.selectOptions(
    within(dialog).getByRole("combobox", { name: /Tipo de organização/ }),
    "operadora",
  );
  expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled();
  expect(within(dialog).getByText(/bloco de upstream/i)).toBeInTheDocument();
});
```

Os nomes que os `getByRole(...)` usam saem dos `label` do `FormField` — confira o
nome acessível real ao rodar, e ajuste a regex se o rótulo do JSX (passo 5) sair
diferente do que está aqui.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && npm run test -- Discovery`
Expected: FAIL — não há select de `kind`, nem bloco de upstream.

- [ ] **Step 3: Os tipos**

Em `types.ts`, no `DiscoveryAdocaoIn`, o `organizacao_nova.kind` passa a
`"downstream" | "parceiro" | "operadora"`, `sessoes` ganha
`import_route_policy?: string | null; export_route_policy?: string | null;` e o
corpo ganha:

```ts
  upstream?: {
    upstream_id?: number | null;
    name?: string;
    tipo?: "transito" | "ix" | "pni" | "contingencia";
    capacity?: string | null;
    priority?: number | null;
    cost?: string | null;
    expected_prefixes_v4?: number | null;
    expected_prefixes_v6?: number | null;
    max_prefix_margin_pct?: number;
    rpki_enabled?: boolean;
    entrada_local_preference?: number | null;
    produto_import?: "full" | "parcial" | "default" | null;
    papel?: "principal" | "contingencia";
    ordem?: number;
  } | null;
```

E o `DiscoveryPropostaOut.sessoes` ganha os três campos opcionais
(`default_route_advertise?: boolean; import_route_policy?: string | null;
export_route_policy?: string | null;`).

- [ ] **Step 4: O bloco no `useFidelidade`**

`IdentidadeDaConferencia` ganha:

```ts
  // O tipo é o do `blocoDoUpstream` do passo 5 — é ele que a identidade recebe,
  // e um tipo mais estreito do que o que o helper devolve não compila.
  upstream?:
    | { upstream_id: number; papel: string }
    | { name: string; tipo: string; produto_import: string | null; papel: string };
```

`IdentidadeDaConferencia` ganha também `organizacaoKind?: "downstream" |
"parceiro" | "operadora"` — é o parâmetro novo da rota (Task 9, passo 6), e sem
ele o ensaio da conferência monta a organização descartável como `downstream`,
qualquer que seja a escolha do select.

E o `useFidelidade`, no `qs`:

```ts
  if (identidade.organizacaoKind) {
    qs.append("organizacao_kind", identidade.organizacaoKind);
  }
  const up = identidade.upstream;
  if (up && "upstream_id" in up) {
    qs.append("upstream_id", String(up.upstream_id));
    qs.append("upstream_papel", up.papel);
  } else if (up) {
    qs.append("upstream_tipo", up.tipo);
    if (up.produto_import) qs.append("upstream_produto", up.produto_import);
    qs.append("upstream_papel", up.papel);
  }
```

(o `useFidelidade` já tem de incluir `identidade` inteira na chave de dependência
— mantenha o padrão que o hook usa hoje. O `upstream_papel` sai nos dois ramos:
no modo vincular o papel é escolha da revisão, e não o do vínculo atual.)

- [ ] **Step 5: O `kind`, o bloco e os nomes no formulário**

Em `DiscoveryAdopt.tsx`:

1. no estado, `kind` e o bloco do upstream
   (`upstreamModo: "nenhum" | "vincular" | "criar"`, `upstreamId`, `upstreamNome`,
   `upstreamTipo`, `upstreamProduto`, `upstreamPapel`); no estado das sessões,
   `importRoutePolicy`/`exportRoutePolicy` por família, semeados do
   `proposta.sessoes` no `useEffect` que já monta as sessões. O `kind` também é
   semeado ali, da **classificação da proposta** (§5.5): `proposta.classificacao
   === "upstream"` abre o select em `"operadora"`, qualquer outro valor abre em
   `"downstream"`. A classificação continua sendo o palpite do `_classificar`
   (pelo `kind` da organização do ASN, ou `"downstream"` quando não há
   organização) — o que o §5.5 muda é que quem decide passou a ser o operador, e
   o palpite vira só o valor inicial do select. Nenhuma guarda nova no serviço
   compara os dois: a escolha da revisão é que vale;
2. `adotarProposta` deixa de fixar `kind: "downstream"` e passa
   `kind: form.kind`. O bloco do upstream sai de um helper único, que os dois
   caminhos (o corpo do `adotarProposta` e a `identidadeDaConferencia`) usam —
   montá-lo duas vezes é como os dois divergem:

```ts
/** O bloco `upstream` da revisão, ou `undefined` quando não há bloco.
 *
 * Nos dois modos: vincular manda só o `upstream_id` (o resto é o upstream da
 * SoT, e o serviço recusa os campos de criação junto com ele); criar manda os
 * campos digitados. `nenhum` não manda nada — é o enlace de cliente. */
function blocoDoUpstream(form: FormRevisao) {
  if (form.upstreamModo === "vincular") {
    return { upstream_id: Number(form.upstreamId), papel: form.upstreamPapel };
  }
  if (form.upstreamModo === "criar") {
    return {
      name: form.upstreamNome,
      tipo: form.upstreamTipo,
      produto_import: form.upstreamProduto || null,
      papel: form.upstreamPapel,
    };
  }
  return undefined;
}
```

   e, na chamada, `organization`/`kind`/`upstream` saem do mesmo `form`:
   `kind: form.kind, upstream: blocoDoUpstream(form)`;
3. `podeAdotar` recusa `kind === "operadora"` sem bloco de upstream, e recusa
   bloco com `kind !== "operadora"` — com a mensagem na tela, o mesmo par de
   frases do serviço (o backend é quem manda, isto é a cortesia da tela). Use
   exatamente estas duas, sem crase em volta do `upstream` (o teste do passo 1
   casa `/bloco de upstream/i`, e o texto com crase não casaria):
   `"A organização é operadora e a revisão não traz o bloco de upstream."` e
   `"O bloco de upstream exige organização operadora."`;
4. a `identidadeDaConferencia` passa a levar o `upstream` (o `upstream_id` no
   modo vincular, o bloco digitado no modo criar), para o diff sair do caminho
   certo;
5. o JSX: um `<FormField label="Tipo de organização">` com o `<select>` de
   `kind` no bloco da organização (ao lado do ASN) e o `help("adocao.kind")`; um
   `<fieldset>` com legenda **Upstream**, só com `kind === "operadora"`
   (vincular por id ou criar com nome/tipo/produto/papel — o papel e o produto
   com os mesmos rótulos do formulário de upstream: "Papel" e "Tipo de policy");
   e, em cada família, dois campos de texto com o nome lido
   (`<FormField label="Route-policy de importação">` e
   `<FormField label="Route-policy de exportação">`) e um botão de limpar ao lado
   de cada um.

- [ ] **Step 6: Os textos de ajuda**

Em `help.ts`, no bloco `adocao.*`:

```ts
  "adocao.kind": "downstream (cliente), parceiro ou operadora. Operadora exige o bloco de upstream: o render trata o enlace pelo vínculo, e sem ele a sessão sai pelo caminho de cliente.",
  "adocao.upstream": "Vincular um upstream existente ou criar o novo. O circuito nasce vinculado como principal, na mesma transação.",
  "adocao.produto_import": "Tipo de rota que a operadora envia: full, parcial ou default. É o que descreve o enlace de upstream — a operadora não tem prefix-list própria.",
  "adocao.politica_import": "Nome da route-policy de importação como está no equipamento. Importar significa que o gerenet passa a gerenciar o corpo dela sob esse nome; limpar devolve o nome padrão do gerenet.",
  "adocao.politica_export": "Idem para a route-policy de exportação.",
```

- [ ] **Step 7: Rodar e ver passar**

Run: `cd web && npm run build && npm run test`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add web/src/api/types.ts web/src/api/hooks.ts web/src/pages/DiscoveryAdopt.tsx \
        web/src/pages/DiscoveryAdopt.test.tsx web/src/help.ts
git commit -m "feat(web): o kind, o upstream e as políticas lidas na revisão da adoção"
```

---

### Task 13: Web — o acesso e o produto no cadastro do upstream

**Files:**
- Modify: `web/src/api/types.ts` (`UpstreamOut` 515-591, `UpstreamCreateIn`)
- Modify: `web/src/pages/Upstreams.tsx` (`FormUpstream` 23-31, `FORM_VAZIO` 33-50, `paraPayload` 52-78, `CamposUpstream` 80-170, `abrirEdicao` 206-229, `salvarEdicao` 231-238)
- Modify: `web/src/pages/UpstreamDetail.tsx` (tabela 128-145)
- Modify: `web/src/help.ts` (bloco `upstream.*` 110-124)
- Test: `web/src/pages/Upstreams.test.tsx`

**Interfaces:**
- Consumes: `produto_import` (Task 7) e o bloco `circuito` do `POST` (Task 9).
- Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

```tsx
it("manda o bloco de acesso junto do upstream", async () => {
  render(<Upstreams />);
  await userEvent.click(screen.getByRole("button", { name: /novo upstream/i }));
  await userEvent.type(screen.getByLabelText("Nome"), "up-web");
  await userEvent.selectOptions(screen.getByLabelText("Tipo"), "transito");
  await userEvent.selectOptions(screen.getByLabelText("Tipo de policy"), "parcial");
  await userEvent.click(screen.getByText("Acesso"));
  await userEvent.type(screen.getByLabelText("Código do circuito"), "CIRC-WEB");
  await userEvent.click(screen.getByRole("button", { name: /salvar/i }));
  await waitFor(() => expect(criarMock).toHaveBeenCalledWith(expect.objectContaining({
    produto_import: "parcial",
    circuito: expect.objectContaining({ code: "CIRC-WEB" }),
  })));
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && npm run test -- Upstreams`
Expected: FAIL — não há "Tipo de policy" nem a seção "Acesso".

- [ ] **Step 3: Os tipos**

Em `types.ts`: `UpstreamOut` e `UpstreamUpdateIn` ganham
`produto_import: "full" | "parcial" | "default" | null`, e o `UpstreamCreateIn`
ganha

```ts
  produto_import?: "full" | "parcial" | "default" | null;
  circuito?: {
    code: string;
    site_id: number;
    edge_device_id: number;
    edge_trunk?: string | null;
    access_device_id: number;
    access_port: string;
    velocidade_mbps?: number | null;
  } | null;
```

(O bloco `circuito` é o `CircuitoDoUpstreamIn` do backend — Task 9, passo 5 —
com os campos opcionais que o schema já trata como opcionais.)

- [ ] **Step 4: O formulário**

Em `Upstreams.tsx`:

1. `FORM_VAZIO` ganha `produto_import: ""` e o sub-objeto do acesso
   (`acesso: false, circuito_code: "", site_id: "", edge_device_id: "",
   edge_trunk: "", access_device_id: "", access_port: "", velocidade_mbps: ""`);
2. `CamposUpstream` ganha um `<FormField label="Tipo de policy">` com
   `<select>` de `full`/`parcial`/`default` e a opção vazia "—" (que vai como
   `null`), com o `help("upstream.produto_import")`;
3. `paraPayload` passa a devolver `produto_import: form.produto_import || null` e,
   só na criação e só com `acesso` marcado, o bloco `circuito` com os números
   convertidos (`Number(...)`) e os vazios como `null`;
4. a seção **Acesso** (um `<fieldset>` com os campos acima) aparece só no
   diálogo de criação — o vínculo de circuito continua sendo o formulário da
   página de detalhe (`UpstreamDetail.tsx`, 200-232) para um upstream que já
   existe;
5. `abrirEdicao`/`salvarEdicao` levam o `produto_import` (a edição não manda o
   bloco `circuito`).

- [ ] **Step 5: O detalhe e a ajuda**

`UpstreamDetail.tsx`: a tabela read-only ganha a linha **Tipo de policy** com o
rótulo em português de `full`/`parcial`/`default` (ou "—").

`help.ts`, no bloco `upstream.*`:

```ts
  "upstream.produto_import": "Tipo de rota que a operadora envia: full, parcial ou default. Preenchido, é ele que decide o produto da importação; vazio, o produto sai do tipo do upstream (trânsito/IX → full, PNI → parcial, contingência → default).",
  "upstream.acesso": "Equipamento e porta por onde a operadora chega. Preenchido, o circuito nasce junto com o upstream e fica vinculado como principal. A reserva de VLAN e de endereços continua na página do circuito.",
```

- [ ] **Step 6: Rodar e ver passar**

Run: `cd web && npm run build && npm run test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/types.ts web/src/pages/Upstreams.tsx web/src/pages/UpstreamDetail.tsx \
        web/src/pages/Upstreams.test.tsx web/src/help.ts
git commit -m "feat(web): o acesso e o tipo de policy no cadastro do upstream"
```

---

### Task 14: Wiki e CLAUDE.md

**Files:**
- Modify: `docs/wiki/descoberta.md`, `docs/wiki/upstreams.md`
- Modify: `CLAUDE.md` (o bullet da frente, no fim da seção "Estado do repositório")
- Test: `tests/api/test_wiki.py` (só roda; nenhuma mudança é esperada nele)

**Interfaces:**
- Consumes: tudo o que as tasks 1-13 entregaram.
- Produces: a documentação que o operador lê.

- [ ] **Step 1: `/wiki/descoberta`**

Acrescentar à página, em PT-BR, o que o operador precisa saber:

- o select de **tipo de organização** e a regra de coerência (operadora exige o
  bloco de upstream; o bloco exige operadora), com a razão em uma frase — o
  render trata o enlace pelo vínculo, e a autorização de cliente é filtrada pelo
  `kind`;
- o bloco de **upstream** na revisão (vincular existente ou criar o novo com
  tipo e produto), e que o circuito nasce vinculado como principal;
- os **nomes de política lidos**: onde aparecem, o que significa importar (o
  gerenet passa a gerenciar o corpo sob aquele nome, e a primeira mudança
  aprovada pode alterar o que está no equipamento), o que significa limpar
  (volta o nome padrão), e que o nome repetido no mesmo equipamento é recusado.

- [ ] **Step 2: `/wiki/upstreams`**

Acrescentar: a seção **Acesso** do cadastro (equipamento, porta, trunk,
velocidade) e que ela cria o circuito vinculado na mesma chamada, com a reserva
ficando na página do circuito; o **tipo de policy** (full/parcial/default), o que
ele decide e o que acontece quando fica vazio; e a linha do detalhe que o mostra.

- [ ] **Step 3: `CLAUDE.md`**

No fim da seção "Estado do repositório", um bullet no formato dos anteriores,
resumindo: as duas colunas de default route e a migração de dados, o `kind` e a
cadeia de upstream na adoção, o nome de política importado (e a exceção ao
§25.4), o acesso e o `produto_import` no upstream, **e os dois desvios
registrados** (o `propagar_defaults` que não ganha `commit`, e as flags do CLI
que entram só no `add` porque não existe `update`). O bullet termina com a
dívida do §11 que interessa a quem vier depois: não há modelo para a política
compartilhada entre dois peers do mesmo equipamento.

- [ ] **Step 4: Rodar a suíte inteira e o lint**

Run: `uv run pytest -q && uv run ruff check src tests && cd web && npm run build && npm run test`
Expected: tudo PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/wiki/descoberta.md docs/wiki/upstreams.md CLAUDE.md
git commit -m "docs: o default route, a adoção de upstream e as políticas importadas"
```

---

## Desvios registrados do spec

1. **`propagar_defaults` não ganha `commit`** (§5.3/§8 pedem o parâmetro). Ela
   nunca commitou e não tem o parâmetro: recebê-lo seria inócuo ou mudaria a
   fronteira de transação de `update_upstream`, que propaga no meio e commita no
   fim. Os dois serviços que de fato commitam (`create_upstream`,
   `vincular_circuito`) ganham `commit=False`, e a adoção deixa o `commit` único
   dela persistir a propagação.
2. **As três flags do CLI entram no `add`**, e não em `add/update` (§8): o
   comando `update` não existe no CLI. Criá-lo não é desta frente — o
   `PATCH /api/v1/bgp-sessions/{id}` e a página cobrem a edição.
3. **`AdocaoUpstreamIn` ganha `produto_import` e os dois `contingencia_*`** além
   dos campos que o §5.2 lista. O produto é o que descreve o enlace de operadora
   (item 5 do pedido, §7) e os dois `contingencia_*` evitam que o ensaio de um
   upstream novo com papel de contingência acuse diferença que a escrita não
   cria.
4. **O `GET /discovery/fidelidade` ganha oito parâmetros de query**: os sete do
   bloco do upstream e o `organizacao_kind`. É o preço de a conferência ser GET
   e o bloco ter de viajar até ela; o `adotar` não precisa de nada disso, porque
   o bloco já vai no corpo. O `organizacao_kind` é uma correção que a frente
   expôs: o `conferir_fidelidade` já o aceitava e o `_ensaio` já o usava, mas a
   rota nunca o passava, então todo preview rodava com a organização do ensaio
   como `downstream` — inofensivo antes do §5.1, errado depois dele.
5. **O produto vira nome de perfil por um mapa próprio** (`PERFIL_DO_PRODUTO`),
   e não pela expressão literal do §7 (`up.produto_import or
   PRODUTO_IMPORT_POR_TIPO[up.tipo]`). As duas fontes falam vocabulários
   diferentes — `produto_import` guarda `"full"`, `PRODUTO_IMPORT_POR_TIPO`
   guarda `"up-full"` — e a expressão literal do spec não acha perfil nenhum e
   deixa a propagação sem efeito, calada. O comportamento que o §7 descreve
   (campo vence, tipo decide quando nulo) é o que o mapa entrega.

## Dívidas que esta frente deixa (do §11 do spec)

- `peer X ip-prefix <lista> import` continua lido e não usado pelo render.
- `peer X default-route-advertise route-policy <nome>` é lido como aviso.
- Não há modelo para uma route-policy compartilhada por dois peers do mesmo
  equipamento: a adoção recusa, e o render continua emitindo os dois blocos sob
  o mesmo nome quando o caso chega por outro caminho.
- A prefix-list interna da política importada continua com o nome do gerenet.
- A reconciliação contínua não confere `default-route-advertise` (o
  `display bgp peer verbose` não traz o campo); quem o vê é a conferência de
  configuração do `discovery show`.
