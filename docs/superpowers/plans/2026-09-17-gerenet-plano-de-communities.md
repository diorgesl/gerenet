# Plano de communities central do gerenet — implementação (fatia F1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** colocar o plano de communities na SoT como dado — vocabulário, partição, alvos e portões — com a leitura da configuração já coletada, a validação de conformidade e a página de consulta no frontend.

**Architecture:** quatro tabelas novas e a `communities` estendida guardam o plano; um leitor novo (`automation/parsers/huawei_vrp/communities_vrp.py`) lê as definições, os usos e os grupos de peer do `display current-configuration` já gravado no snapshot, porque o `config_vrp.py` descarta de propósito as linhas que este plano precisa; o motor puro `automation/community_plan.py` propõe o plano e roda as oito checagens sem tocar no banco; o serviço escreve numa transação só com auditoria, no mesmo formato da adoção de peer da descoberta. O render não muda nesta fatia.

**Tech Stack:** Python 3.12 + SQLAlchemy 2 + Alembic + PostgreSQL, FastAPI `/api/v1`, Typer, pytest + ruff, React + Vite + TanStack Query + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-gerenet-plano-de-communities-design.md` — este plano implementa a fatia **F1** da §12. A spec viaja junto com o plano: as referências `§n` abaixo são dela.

## Global Constraints

- **Idioma:** todo artefato em PT-BR — docstrings, mensagens de erro, comentários, nomes de teste, mensagens de commit.
- **Verificação por task:** `uv run pytest -q` e `uv run ruff check src tests` verdes antes de cada commit. Rode sempre com `GERENET_TEST_DATABASE_URL` apontando para `gerenet_test` (o default do `tests/conftest.py`), **nunca** contra o banco de desenvolvimento `gerenet`: a suíte TRUNCATE o banco.
- **Migrações:** `DO $do$ BEGIN CREATE TYPE ...; EXCEPTION WHEN duplicate_object THEN NULL; END $do$` para os tipos novos e `postgresql.ENUM(..., create_type=False)` nas colunas. `down_revision = "a3d1c7e5b9f2"` (head atual).
- **O render não muda:** `src/gerenet/automation/render.py` e `automation/naming.py` ficam intocados nesta fatia (§3, §10).
- **Nada escreve em equipamento.** O único caminho de leitura é o snapshot já coletado; esta frente não enfileira job nem muda CR.
- **Segredo:** nenhum valor de `password cipher`, hash de usuário local ou endereço de gestão entra em fixture, teste, docstring ou log. As fixtures desta frente são compostas a partir das duas capturas reais, com os trechos copiados literalmente — os trechos copiados não têm segredo.
- **Auditoria:** toda escrita grava `registrar(...)` na mesma transação (`domain/audit.py`), com o padrão `origem` + `origem_snapshot_id` que `bgp_prefix_authorizations.origem` já usa (§9.1).
- **Idempotência:** adotar duas vezes o mesmo snapshot não duplica linha nem evento de auditoria (§13).
- **Commits:** um por task, mensagem em PT-BR no padrão do repositório, terminada com a linha `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

## Regras de implementação

A spec deixa pontos que precisam de decisão para virar código. São estas, e cada uma tem o porquê:

1. **Uma linha de vocabulário por valor de classe, não por nome no namespace.** O índice único parcial em `valor_v4` (§4.1) não admite duas linhas com o mesmo valor, e `com-TECMAIS-v4` (`65000:3001`) e `com-EXPORT-UPSTREAM-v4` (`61785:3001`) são a **mesma** classe com duas grafias. Então `valor_v4`/`valor_v6` guardam o **código** (`3001`, `3101`) e os nomes alternativos vão em `notes`. O "quem aplica" e o "quem testa" das checagens são comparados por **valor literal** (`61785:3001` ≠ `65000:3001`) e rotulados pela classe do código — é essa comparação que produz o achado principal da §8.1, que o código puro não produziria.
2. **Só a família incoerente é recusada na escrita.** Um valor na coluna da outra família é erro de digitação e o serviço responde 422; valor fora de faixa, sem banda ou em ordem invertida é **exceção legítima** (§14.4: `61785:53062`, `61785:8167`, `65000:0:262611`) e entra no plano para a validação apontar. A partição é contrato verificável (§2.2), não porteiro de escrita.
3. **Código de instrução ambíguo sai como divergência.** O código `3` é "marca ERTEL" na borda e "prepend nível 3" no VS (§6.2). O índice único em `codigo` não deixa as duas linhas existirem, então a adoção propõe a primeira que encontra e emite a divergência `codigo_ambiguo` para o operador decidir. A adoção não escolhe sozinha (§9).
4. **A direção de um filtro não se adivinha pelo nome: vem do `peer`.** `CUSTOMER-BGP-v4` é um filtro de import que não diz "in" no nome. A checagem 6 ("`apply community` sem `additive`", §8) usa o vínculo real — `peer <ip> route-policy <nome> import|export`, que o `config_vrp.py` já lê em `PeerConfig.import_route_policy`/`export_route_policy`.
5. **O papel do alvo: a SoT vence o nome.** Quando o ASN do grupo casa um `upstreams` da SoT, o papel é o `tipo` dele; quando não casa, o papel vem do nome do grupo (`CDN`/`GGC`/`NFLX` → `cdn`, `PARCEIRO` → `parceiro`, `IX`/`PTT`/`PEERING` → `ix`, resto → `transito`). Discordância entre os dois vira divergência `papel_duvidoso` — é o caso do `MSD-CDN-v4`, que tem nome de CDN e papel de trânsito (§6.3).
6. **O papel do portão `RouteExportCheck` vem do que ele aceita.** É o único portão que aceita a classe "só CDN" (`com-ONLY-CDN`, `65000:991`) e essa é exatamente a diferença entre o portão do CDN e o do upstream (§7). Nome com `V6` → `afi=ipv6`; `-PARCEIROS` → `parceiro`. Sem evidência para decidir, o portão sai com pendência em vez de um palpite.
7. **A partição vive no código, e a tabela de referência da §6 também.** `VOCABULARIO` em `automation/community_plan.py` é a §6.1/§6.2 transcrita como dado; a leitura usa essa referência para saber a que classe um valor pertence antes de o plano existir no banco. Sem ela, a primeira adoção não teria como rotular nada.

---

## File Structure

**Cria:**

| Arquivo | Responsabilidade |
|---|---|
| `src/gerenet/domain/communities_partition.py` | a partição da §5 como código puro: faixas, exceções de família, `conferir_linha` |
| `src/gerenet/automation/parsers/huawei_vrp/communities_vrp.py` | leitor das definições, usos, referências e grupos de peer da configuração |
| `src/gerenet/automation/community_plan.py` | motor puro: `VOCABULARIO`, `PlanoLido`, `propor_plano`, `validar` (as 8 checagens) |
| `src/gerenet/domain/services/community_plan.py` | `obter_plano`, `propor_adocao`, `validar_plano`, `adotar_plano` — sessão, transação única e auditoria |
| `src/gerenet/api/routers/community_plan.py` | `/api/v1/communities/plan` (GET, GET `/validacao`, POST `/adopt`) |
| `src/gerenet/cli/community_plan.py` | `gerenet communities plan show\|validar\|adotar` |
| `web/src/pages/CommunitiesPlan.tsx` | página `Comunidades · Plano` (§11) |
| `tests/domain/test_communities_partition.py` | partição e exceções |
| `tests/automation/test_communities_vrp.py` | o leitor, com fixtures das duas capturas |
| `tests/automation/test_community_plan.py` | proposta e validação (os achados da §8.1) |
| `tests/domain/test_community_plan_service.py` | adoção: transação única, idempotência, auditoria |
| `tests/api/test_community_plan_api.py` | os três endpoints e os códigos de erro |
| `tests/cli/test_community_plan_cli.py` | o grupo `communities plan` |
| `web/src/pages/CommunitiesPlan.test.tsx` | matriz, selo e painel de divergências |
| `alembic/versions/<hash>_plano_de_communities.py` | as quatro tabelas e as cinco colunas de `communities` |
| `tests/fixtures/huawei_vrp/comunidades_edge.txt` | trecho da captura da borda, sem segredo |
| `tests/fixtures/huawei_vrp/comunidades_vs.txt` | trecho da captura do virtual system, sem segredo |

**Modifica:**

| Arquivo | O quê |
|---|---|
| `src/gerenet/domain/models.py` | enums novos, cinco colunas em `Community`, quatro modelos novos |
| `src/gerenet/domain/schemas.py` | `CommunityCreate/Update/Out` ganham valor, código e banda; schemas do plano |
| `src/gerenet/domain/services/communities.py` | guarda de família na criação e no update (Regra 2) |
| `src/gerenet/api/main.py` | registra o router do plano (depois de `communities.router`) |
| `src/gerenet/cli/main.py` | registra o sub-Typer `plan` dentro de `communities` |
| `src/gerenet/cli/communities.py` | `list` ganha valor e banda |
| `tests/conftest.py` | TRUNCATE das quatro tabelas novas + limpeza das `communities` adotadas |
| `web/src/api/types.ts` | tipos do plano e os campos novos de `CommunityOut` |
| `web/src/api/hooks.ts` | `usePlano`, `usePlanoValidacao` |
| `web/src/pages/Communities.tsx` | colunas de valor e banda (§11) |
| `web/src/components/Layout.tsx` | item `Comunidades · Plano` no grupo Roteamento |
| `web/src/App.tsx` | rota `/communities/plan` |
| `web/src/help.ts` | textos dos campos novos (o `npm run build` valida as chaves) |
| `docs/wiki/roteamento.md` | seção do plano de communities |
| `CLAUDE.md` | bullet da frente em "Estado do repositório" |

---

### Task 1: Vocabulário e tabelas do plano

Fecha a estrutura de dados da §4. O `Community` ganha o valor, o código e a banda; nascem `community_plans`, `community_targets`, `community_gates` e `community_import_rules`. Ao fim, uma linha do vocabulário e um plano persistem e voltam tipados do banco.

**Files:**
- Create: `alembic/versions/<hash>_plano_de_communities.py` (o hash sai do `alembic revision`)
- Modify: `src/gerenet/domain/models.py`
- Modify: `tests/conftest.py:35-45` (lista do TRUNCATE)
- Test: `tests/domain/test_community_plan_models.py`

**Interfaces:**
- Consumes: nada.
- Produces: `models.COMMUNITY_BANDA`, `models.COMMUNITY_ORIGEM`, `models.TARGET_PAPEL`, `models.GATE_PAPEL`, `models.GATE_PADRAO`, `models.IMPORT_RULE_PAPEL`; `models.Community.valor_v4|valor_v6|codigo|banda|origem|origem_snapshot_id`; `models.CommunityPlan`, `models.CommunityTarget`, `models.CommunityGate`, `models.CommunityImportRule`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/domain/test_community_plan_models.py`:

```python
"""Modelos do plano de communities (spec §4) — o vocabulário e as quatro tabelas."""
from sqlalchemy.orm import Session

from gerenet.domain import models


def test_vocabulario_guarda_valor_codigo_e_banda(session: Session) -> None:
    com = models.Community(
        name="com-TECMAIS-v4", tipo="tag_produto", banda="cliente",
        valor_v4=3001, valor_v6=3101,
        notes="namespace XPL: com-EXPORT-UPSTREAM-v4 (61785:3001)",
    )
    session.add(com)
    session.commit()

    lido = session.get(models.Community, com.id)
    assert lido is not None
    assert (lido.valor_v4, lido.valor_v6, lido.banda) == (3001, 3101, "cliente")
    assert lido.origem == "manual"
    assert lido.origem_snapshot_id is None
    assert lido.codigo is None


def test_plano_cabeçalho_com_alvos_e_portoes(session: Session) -> None:
    import json

    classe = models.Community(name="com-EXPORT-UPSTREAM-v4", tipo="tag_produto", banda="cliente", valor_v4=3001)
    session.add(classe)
    session.flush()
    plano = models.CommunityPlan(
        asn_principal=61785,
        asns_anunciados=[{"asn": 61785, "papel": "principal"}],
        origem="adotado",
        observacoes="leitura da borda",
    )
    session.add(plano)
    session.flush()
    session.add(
        models.CommunityGate(
            nome="RouteExportCheck", papel="upstream", afi="ipv4", padrao="recusar",
            aceitas=[classe.id], recusadas=[], origem="adotado",
        )
    )
    session.add(
        models.CommunityTarget(
            nome="MSD-CDN-v4", papel="cdn", codigo_v4=53062, gate_nome="RouteExportCheck",
            classe_import_id=classe.id, parametros={"tamanho_max_v4": 24}, origem="adotado",
        )
    )
    session.add(
        models.CommunityImportRule(papel="cliente", afi="ipv4", classe_id=classe.id, condicao={"tamanho_max": 24})
    )
    session.commit()

    assert plano.id is not None
    assert json.loads(json.dumps(plano.asns_anunciados))[0]["asn"] == 61785
    portao = session.query(models.CommunityGate).one()
    assert portao.aceitas == [classe.id] and portao.padrao == "recusar"
    alvo = session.query(models.CommunityTarget).one()
    assert alvo.parametros["tamanho_max_v4"] == 24
    assert session.query(models.CommunityImportRule).one().condicao["tamanho_max"] == 24
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run pytest tests/domain/test_community_plan_models.py -q
```

Esperado: erro de import (`AttributeError`/`ImportError`) em `models.CommunityPlan`. A tabela ainda não existe, então mesmo que o import passasse o `INSERT` falharia com `UndefinedTable`.

- [ ] **Step 3: Criar a migração**

```bash
uv run alembic revision -m "plano de communities"
```

Renomeie o arquivo gerado para `alembic/versions/<hash>_plano_de_communities.py` (o `<hash>` é o que o Alembic deu) e preencha:

```python
"""plano de communities: vocabulário, alvos, portões e regras de import (spec F1 §4)

Revision ID: <hash>
Revises: a3d1c7e5b9f2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "<hash>"
down_revision = "a3d1c7e5b9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tipos novos: o DO/EXCEPTION é o idioma do repositório (migração 767551f719ba).
    for nome, valores in (
        ("community_banda", ("local", "transito", "cliente", "parceiro", "conjunto", "tamanho", "especial", "instrucao")),
        ("community_origem", ("manual", "adotado")),
        ("community_plan_origem", ("manual", "adotado")),
        ("community_target_papel", ("transito", "ix", "pni", "cdn", "parceiro")),
        ("community_gate_papel", ("upstream", "cdn", "parceiro", "ix")),
        ("community_gate_padrao", ("recusar", "permitir")),
        ("community_import_papel", ("cliente", "parceiro", "transito")),
    ):
        op.execute(
            f"DO $do$ BEGIN CREATE TYPE {nome} AS ENUM "
            f"({', '.join(repr(v) for v in valores)}); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $do$"
        )

    op.add_column("communities", sa.Column("valor_v4", sa.Integer(), nullable=True))
    op.add_column("communities", sa.Column("valor_v6", sa.Integer(), nullable=True))
    op.add_column("communities", sa.Column("codigo", sa.Integer(), nullable=True))
    op.add_column(
        "communities",
        sa.Column("banda", postgresql.ENUM(name="community_banda", create_type=False), nullable=True),
    )
    op.add_column(
        "communities",
        sa.Column(
            "origem", postgresql.ENUM(name="community_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
    )
    op.add_column("communities", sa.Column("origem_snapshot_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_communities_origem_snapshot", "communities", "device_snapshots",
        ["origem_snapshot_id"], ["id"],
    )
    # Nulos não colidem: um vocabulário de classes convive com o de instruções.
    op.create_index(
        "uq_communities_valor_v4", "communities", ["valor_v4"], unique=True,
        postgresql_where=sa.text("valor_v4 IS NOT NULL"),
    )
    op.create_index(
        "uq_communities_valor_v6", "communities", ["valor_v6"], unique=True,
        postgresql_where=sa.text("valor_v6 IS NOT NULL"),
    )
    op.create_index(
        "uq_communities_codigo", "communities", ["codigo"], unique=True,
        postgresql_where=sa.text("codigo IS NOT NULL AND banda = 'instrucao'"),
    )

    op.create_table(
        "community_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asn_principal", sa.Integer(), nullable=False),
        sa.Column("asns_anunciados", sa.JSON(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Uma linha ativa: o plano é um só (§4.2).
    op.create_index(
        "uq_community_plans_ativa", "community_plans", ["admin_status"], unique=True,
        postgresql_where=sa.text("admin_status"),
    )

    op.create_table(
        "community_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "papel", postgresql.ENUM(name="community_target_papel", create_type=False),
            nullable=False, server_default="transito",
        ),
        sa.Column("codigo_v4", sa.Integer(), nullable=True),
        sa.Column("codigo_v6", sa.Integer(), nullable=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("upstream_id", sa.Integer(), sa.ForeignKey("upstreams.id"), nullable=True),
        sa.Column("classe_import_id", sa.Integer(), sa.ForeignKey("communities.id"), nullable=True),
        sa.Column("gate_nome", sa.String(128), nullable=True),
        sa.Column("parametros", sa.JSON(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "community_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(128), nullable=False),
        sa.Column(
            "papel", postgresql.ENUM(name="community_gate_papel", create_type=False),
            nullable=False, server_default="upstream",
        ),
        sa.Column("afi", sa.String(8), nullable=False, server_default="ipv4"),
        sa.Column(
            "padrao", postgresql.ENUM(name="community_gate_padrao", create_type=False),
            nullable=False, server_default="recusar",
        ),
        sa.Column("aceitas", sa.JSON(), nullable=True),
        sa.Column("recusadas", sa.JSON(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("nome", "papel", "afi", name="uq_community_gates_nome_papel_afi"),
    )

    op.create_table(
        "community_import_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "papel", postgresql.ENUM(name="community_import_papel", create_type=False), nullable=False,
        ),
        sa.Column("afi", sa.String(8), nullable=False, server_default="ipv4"),
        sa.Column("classe_id", sa.Integer(), sa.ForeignKey("communities.id"), nullable=False),
        sa.Column("condicao", sa.JSON(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column(
            "origem", postgresql.ENUM(name="community_plan_origem", create_type=False),
            nullable=False, server_default="manual",
        ),
        sa.Column("origem_snapshot_id", sa.Integer(), sa.ForeignKey("device_snapshots.id"), nullable=True),
        sa.UniqueConstraint("papel", "afi", name="uq_community_import_rules_papel_afi"),
    )


def downgrade() -> None:
    op.drop_table("community_import_rules")
    op.drop_table("community_gates")
    op.drop_table("community_targets")
    op.drop_index("uq_community_plans_ativa", table_name="community_plans")
    op.drop_table("community_plans")
    op.drop_index("uq_communities_codigo", table_name="communities")
    op.drop_index("uq_communities_valor_v6", table_name="communities")
    op.drop_index("uq_communities_valor_v4", table_name="communities")
    op.drop_constraint("fk_communities_origem_snapshot", "communities", type_="foreignkey")
    for coluna in ("origem_snapshot_id", "origem", "banda", "codigo", "valor_v6", "valor_v4"):
        op.drop_column("communities", coluna)
    for nome in (
        "community_import_papel", "community_gate_padrao", "community_gate_papel",
        "community_target_papel", "community_plan_origem", "community_origem", "community_banda",
    ):
        op.execute(f"DROP TYPE IF EXISTS {nome}")
```

- [ ] **Step 4: Aplicar a migração e estender os modelos**

```bash
uv run alembic upgrade head
```

Em `src/gerenet/domain/models.py`, logo abaixo de `COMMUNITY_TIPO` (linha 57):

```python
# Partição do plano de communities (spec §5): a banda é o que torna o valor
# verificável, e `instrucao` é o código da large-community `61785:<código>:<alvo>`.
COMMUNITY_BANDA = (
    "local", "transito", "cliente", "parceiro", "conjunto", "tamanho", "especial", "instrucao",
)
COMMUNITY_ORIGEM = ("manual", "adotado")
TARGET_PAPEL = ("transito", "ix", "pni", "cdn", "parceiro")
GATE_PAPEL = ("upstream", "cdn", "parceiro", "ix")
GATE_PADRAO = ("recusar", "permitir")
IMPORT_RULE_PAPEL = ("cliente", "parceiro", "transito")
```

Nas colunas de `Community`, entre `notes` e `admin_status`:

```python
    valor_v4: Mapped[int | None] = mapped_column(Integer())  # o código de 2 bytes da família v4
    valor_v6: Mapped[int | None] = mapped_column(Integer())
    codigo: Mapped[int | None] = mapped_column(Integer())  # o meio de `61785:<código>:<alvo>`
    banda: Mapped[str | None] = mapped_column(Enum(*COMMUNITY_BANDA, name="community_banda"))
    origem: Mapped[str] = mapped_column(
        Enum(*COMMUNITY_ORIGEM, name="community_origem"), default="manual", nullable=False
    )
    origem_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))
```

E, depois de `Community` (antes de `BgpSession`), os quatro modelos novos, com os timestamps copiados do `Community`:

```python
class CommunityPlan(Base):
    """O cabeçalho do plano de communities (spec §4.2) — uma linha ativa."""

    __tablename__ = "community_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asn_principal: Mapped[int] = mapped_column(Integer, nullable=False)
    asns_anunciados: Mapped[list | None] = mapped_column(JSON)
    origem: Mapped[str] = mapped_column(
        Enum(*COMMUNITY_ORIGEM, name="community_plan_origem"), default="manual", nullable=False
    )
    origem_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))
    observacoes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CommunityTarget(Base):
    """Para quem eu anuncio e sob qual código (spec §4.3)."""

    __tablename__ = "community_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    papel: Mapped[str] = mapped_column(
        Enum(*TARGET_PAPEL, name="community_target_papel"), default="transito", nullable=False
    )
    codigo_v4: Mapped[int | None] = mapped_column(Integer())
    codigo_v6: Mapped[int | None] = mapped_column(Integer())
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    upstream_id: Mapped[int | None] = mapped_column(ForeignKey("upstreams.id"))
    classe_import_id: Mapped[int | None] = mapped_column(ForeignKey("communities.id"))
    gate_nome: Mapped[str | None] = mapped_column(String(128))
    parametros: Mapped[dict | None] = mapped_column(JSON)
    origem: Mapped[str] = mapped_column(
        Enum(*COMMUNITY_ORIGEM, name="community_plan_origem"), default="manual", nullable=False
    )
    origem_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CommunityGate(Base):
    """Quais classes podem sair por este papel (spec §4.4) — a matriz classe × papel."""

    __tablename__ = "community_gates"
    __table_args__ = (UniqueConstraint("nome", "papel", "afi", name="uq_community_gates_nome_papel_afi"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(128), nullable=False)
    papel: Mapped[str] = mapped_column(
        Enum(*GATE_PAPEL, name="community_gate_papel"), default="upstream", nullable=False
    )
    afi: Mapped[str] = mapped_column(String(8), default="ipv4", nullable=False)
    padrao: Mapped[str] = mapped_column(
        Enum(*GATE_PADRAO, name="community_gate_padrao"), default="recusar", nullable=False
    )
    # Lista de ids de `communities`: o id sobrevive ao rename (§4.4).
    aceitas: Mapped[list | None] = mapped_column(JSON)
    recusadas: Mapped[list | None] = mapped_column(JSON)
    origem: Mapped[str] = mapped_column(
        Enum(*COMMUNITY_ORIGEM, name="community_plan_origem"), default="manual", nullable=False
    )
    origem_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CommunityImportRule(Base):
    """A classificação na entrada, por papel (spec §4.5) — o render consome em F2."""

    __tablename__ = "community_import_rules"
    __table_args__ = (UniqueConstraint("papel", "afi", name="uq_community_import_rules_papel_afi"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    papel: Mapped[str] = mapped_column(
        Enum(*IMPORT_RULE_PAPEL, name="community_import_papel"), nullable=False
    )
    afi: Mapped[str] = mapped_column(String(8), default="ipv4", nullable=False)
    classe_id: Mapped[int] = mapped_column(ForeignKey("communities.id"), nullable=False)
    condicao: Mapped[dict | None] = mapped_column(JSON)
    notas: Mapped[str | None] = mapped_column(Text())
    origem: Mapped[str] = mapped_column(
        Enum(*COMMUNITY_ORIGEM, name="community_plan_origem"), default="manual", nullable=False
    )
    origem_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))
```

- [ ] **Step 5: Ajustar o TRUNCATE do conftest**

Em `tests/conftest.py`, no `_limpa_tabelas` (linha 35), acrescente as quatro tabelas novas ao `TRUNCATE` e, **depois** dele, a limpeza das communities adotadas — `communities` continua fora do TRUNCATE porque as três linhas semeadas pela migration são pinadas pelos testes de catálogo:

```python
    db_session.execute(
        text(
            "TRUNCATE approvals, change_steps, change_requests, audit_events, user_sessions, users, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations, discovery_ignored_peers, vsi_members, vsi_services, service_endpoints, l2vc_services, mpls_domain_members, mpls_domains, upstreams, upstream_circuits, upstream_communities, roas, irr_cache, community_import_rules, community_gates, community_targets, community_plans RESTART IDENTITY CASCADE"
        )
    )
    # `communities` fica fora do TRUNCATE (as três semeadas são pinadas), mas o
    # vocabulário adotado é dado de teste e não pode vazar para o teste seguinte.
    db_session.execute(text("DELETE FROM communities WHERE origem = 'adotado'"))
    db_session.commit()
```

- [ ] **Step 6: Rodar e ver passar**

```bash
uv run pytest tests/domain/test_community_plan_models.py -q
uv run ruff check src tests
```

Esperado: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions src/gerenet/domain/models.py tests/conftest.py tests/domain/test_community_plan_models.py
git commit -m "feat(communities): o vocabulário e as tabelas do plano"
```

---

### Task 2: A partição como código

A §5 vira funções puras: faixas, exceções nomeadas e a conferência de uma linha do vocabulário. É o que a validação usa na checagem 2 e o que o serviço de catálogo usa para recusar valor na família errada (Regra 2).

**Files:**
- Create: `src/gerenet/domain/communities_partition.py`
- Modify: `src/gerenet/domain/services/communities.py:28-49` (`create_community`) e `:65-94` (`update_community`)
- Test: `tests/domain/test_communities_partition.py`

**Interfaces:**
- Consumes: `models.COMMUNITY_BANDA` (Task 1).
- Produces: `FAIXAS: dict[str, tuple[int, int]]`, `CODIGOS_CONHECIDOS: tuple[int, ...]`, `familia_do_digito(valor: int) -> str | None`, `conferir_valor(banda, valor, familia) -> str | None`, `conferir_linha(*, banda, valor_v4, valor_v6, codigo) -> tuple[str, ...]`, `MENSAGENS: dict[str, str]`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/domain/test_communities_partition.py`:

```python
"""A partição do plano (spec §5): faixas, exceções e a conferência de uma linha."""
import pytest

from gerenet.domain.communities_partition import (
    CODIGOS_CONHECIDOS,
    FAIXAS,
    conferir_linha,
    conferir_valor,
    familia_do_digito,
)


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (3001, "v4"), (3101, "v6"), (4001, "v4"), (4101, "v6"),
        (7001, "v4"), (7103, "v6"), (5001, "v4"),
        (1010, None),   # família-agnóstico: a família viaja na large-community
        (992, "v4"), (993, "v6"),   # a família mora no último dígito
        (666, None), (11, None), (90, None), (91, None),
        (3301, None),   # segundo dígito que não é 0 nem 1: fora do padrão
    ],
)
def test_familia_do_digito(valor: int, esperado: str | None) -> None:
    assert familia_do_digito(valor) == esperado


def test_valor_conforme_e_o_que_a_faixa_e_a_familia_aceitam() -> None:
    assert conferir_valor("cliente", 3001, "v4") is None
    assert conferir_valor("transito", 1010, "v6") is None      # agnóstico nas duas colunas
    assert conferir_valor("especial", 993, "v6") is None
    assert conferir_valor("tamanho", 7003, "v4") is None


def test_valor_recusado_por_faixa_e_por_familia() -> None:
    assert conferir_valor("cliente", 4001, "v4") == "fora_da_faixa"
    assert conferir_valor("cliente", 3001, "v6") == "familia_incoerente"
    assert conferir_valor("especial", 992, "v6") == "familia_incoerente"
    assert conferir_valor(None, 3001, "v4") == "sem_banda"
    assert conferir_valor("especial", 3001, "v4") == "fora_da_faixa"


def test_linha_de_instrucao_nao_tem_valor_de_dois_bytes() -> None:
    assert conferir_linha(banda="instrucao", valor_v4=None, valor_v6=None, codigo=666) == ()
    assert conferir_linha(banda="instrucao", valor_v4=None, valor_v6=None, codigo=None) == (
        "instrucao_sem_codigo",
    )
    assert conferir_linha(banda="instrucao", valor_v4=3001, valor_v6=None, codigo=666) == (
        "instrucao_com_valor",
    )


def test_nome_sem_valor_nenhum_nao_e_problema() -> None:
    # `blackhole`, `no-export` e `no-advertise` são semeados sem valor (§4.1).
    assert conferir_linha(banda=None, valor_v4=None, valor_v6=None, codigo=None) == ()


def test_linha_de_classe_relata_o_problema_com_a_familia() -> None:
    assert conferir_linha(banda="cliente", valor_v4=3001, valor_v6=3101, codigo=None) == ()
    problemas = conferir_linha(banda="cliente", valor_v4=3001, valor_v6=3001, codigo=None)
    assert problemas == ("familia_incoerente:v6",)
    assert conferir_linha(banda="tamanho", valor_v4=7103, valor_v6=None, codigo=None) == (
        "familia_incoerente:v4",
    )


def test_as_faixas_da_spec_e_os_codigos_conhecidos() -> None:
    assert FAIXAS["local"] == (1, 99)
    assert FAIXAS["especial"] == (900, 999)
    assert FAIXAS["tamanho"] == (7000, 7999)
    # §6.2 — os códigos de instrução que o plano conhece.
    assert CODIGOS_CONHECIDOS == (1, 2, 3, 4, 6, 100, 666, 6662)
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run pytest tests/domain/test_communities_partition.py -q
```

Esperado: `ModuleNotFoundError: No module named 'gerenet.domain.communities_partition'`.

- [ ] **Step 3: Escrever o módulo**

`src/gerenet/domain/communities_partition.py`:

```python
"""A partição do plano de communities (spec §5) como contrato verificável.

A partição existe para que um valor novo não precise de reunião para ser
atribuído e para que a validação consiga reprovar um valor no lugar errado. Ela
**não** é porteiro de escrita: valor fora de faixa é exceção legítima e entra no
plano para ser apontado (§14.4). O serviço de catálogo só recusa o que é sempre
erro de digitação — a família na coluna errada.

O padrão de quatro dígitos é `[classe][família][item]`, com família `0` para v4
e `1` para v6, e as exceções da §5 ficam nomeadas aqui em vez de escondidas.
"""

# `instrucao` fica fora de propósito: o código da large-community não é um valor
# de 2 bytes e não pertence a faixa nenhuma.
FAIXAS: dict[str, tuple[int, int]] = {
    "local": (1, 99),
    "especial": (900, 999),
    "transito": (1000, 1999),
    "cliente": (3000, 3999),
    "parceiro": (4000, 4999),
    "conjunto": (5000, 5999),
    "tamanho": (7000, 7999),
}

# §5: `1010` é família-agnóstico (a família viaja na large-community) e `992`/
# `993` põem a família no último dígito. `666`, `11`, `90` e `91` nem chegam ao
# padrão de quatro dígitos.
FAMILIA_AGNOSTICA = frozenset({1010})
FAMILIA_NO_ULTIMO_DIGITO: dict[int, str] = {992: "v4", 993: "v6"}

# §6.2 — os códigos de instrução que o plano conhece. É por esta lista que a
# validação separa "código do plano" de "código órfão" (checagem 3).
CODIGOS_CONHECIDOS: tuple[int, ...] = (1, 2, 3, 4, 6, 100, 666, 6662)

MENSAGENS: dict[str, str] = {
    "fora_da_faixa": "o valor está fora da faixa da banda",
    "familia_incoerente": "o dígito de família do valor não é o da coluna",
    "sem_banda": "a linha tem valor e não declara banda",
    "banda_desconhecida": "a banda não é uma das da partição",
    "valor_em_instrucao": "instrução não carrega community de 2 bytes",
    "instrucao_sem_codigo": "instrução sem código",
    "instrucao_com_valor": "instrução com community de 2 bytes",
    "codigo_sem_instrucao": "código de instrução em linha que não é instrução",
}


def familia_do_digito(valor: int) -> str | None:
    """A família que o próprio valor declara, ou `None` quando ele é exceção.

    `None` não é "está errado": é "o valor não declara família", e é o que a
    §5 chama de exceção nomeada.
    """
    if valor in FAMILIA_AGNOSTICA:
        return None
    if valor in FAMILIA_NO_ULTIMO_DIGITO:
        return FAMILIA_NO_ULTIMO_DIGITO[valor]
    if not 1000 <= valor <= 9999:
        return None
    return {"0": "v4", "1": "v6"}.get(str(valor)[1])


def conferir_valor(banda: str | None, valor: int | None, familia: str) -> str | None:
    """O problema de um valor na coluna `familia`, ou `None` quando conforme.

    `familia` é a coluna em que o valor está (`v4` ou `v6`), e não o que o
    dígito dele diz: a conferência existe justamente para comparar os dois.
    """
    if valor is None:
        return None
    if banda is None:
        return "sem_banda"
    if banda == "instrucao":
        return "valor_em_instrucao"
    if banda not in FAIXAS:
        return "banda_desconhecida"
    minimo, maximo = FAIXAS[banda]
    if not minimo <= valor <= maximo:
        return "fora_da_faixa"
    declarada = familia_do_digito(valor)
    if declarada is not None and declarada != familia:
        return "familia_incoerente"
    return None


def conferir_linha(
    *, banda: str | None, valor_v4: int | None, valor_v6: int | None, codigo: int | None
) -> tuple[str, ...]:
    """Os problemas de uma linha do vocabulário; vazio quando está conforme.

    Cada problema de valor sai com a família no fim (`familia_incoerente:v6`)
    porque a mesma linha tem duas colunas e a mensagem precisa dizer qual delas.
    """
    if banda is None and valor_v4 is None and valor_v6 is None and codigo is None:
        # Nome reconhecido sem valor: `blackhole`, `no-export`, `no-advertise`.
        return ()
    if banda == "instrucao":
        problemas = []
        if codigo is None:
            problemas.append("instrucao_sem_codigo")
        if valor_v4 is not None or valor_v6 is not None:
            problemas.append("instrucao_com_valor")
        return tuple(problemas)
    problemas = []
    if banda is None:
        problemas.append("sem_banda")
    if codigo is not None:
        problemas.append("codigo_sem_instrucao")
    for familia, valor in (("v4", valor_v4), ("v6", valor_v6)):
        problema = conferir_valor(banda, valor, familia)
        if problema is not None:
            problemas.append(f"{problema}:{familia}")
    return tuple(problemas)
```

- [ ] **Step 4: Rodar e ver passar**

```bash
uv run pytest tests/domain/test_communities_partition.py -q
```

Esperado: 6 passed (o `parametrize` conta 1).

- [ ] **Step 5: Escrever o teste da guarda no serviço**

Acrescente ao `tests/domain/test_community_plan_models.py` (ou crie `tests/domain/test_communities_service_particao.py`):

```python
"""A guarda de família do catálogo (spec F1, Regra 2 do plano)."""
import pytest

from gerenet.domain import models
from gerenet.domain.schemas import CommunityCreate, CommunityUpdate
from gerenet.domain.services.communities import create_community, update_community
from gerenet.domain.services.errors import ValidationError


def test_criar_recusa_valor_na_familia_errada(session) -> None:
    with pytest.raises(ValidationError) as erro:
        create_community(
            session,
            CommunityCreate(
                name="com-TESTE-v6", tipo="tag_produto", banda="cliente", valor_v6=3001
            ),
            actor="teste",
        )
    assert "família" in str(erro.value).lower() or "familia" in str(erro.value).lower()


def test_criar_aceita_valor_fora_da_faixa_como_excecao(session) -> None:
    # §14.4: `61785:53062` é exceção legítima e precisa entrar no plano.
    com = create_community(
        session,
        CommunityCreate(name="com-ALT", tipo="tag_produto", banda="transito", codigo=53062),
        actor="teste",
    )
    assert com.banda == "transito"


def test_update_recusa_valor_na_familia_errada(session) -> None:
    com = create_community(
        session, CommunityCreate(name="com-TROCA-v4", tipo="tag_produto", banda="especial", valor_v4=992),
        actor="teste",
    )
    with pytest.raises(ValidationError):
        update_community(session, com.id, CommunityUpdate(valor_v6=992), actor="teste")
```

- [ ] **Step 6: Implementar a guarda**

Em `src/gerenet/domain/services/communities.py`, importe e chame a partição. No topo:

```python
from gerenet.domain.communities_partition import MENSAGENS, conferir_linha
```

E, em `create_community`, antes de montar o modelo:

```python
    _validar_particao(
        banda=data.banda, valor_v4=data.valor_v4, valor_v6=data.valor_v6, codigo=data.codigo
    )
    com = models.Community(
        name=nome, tipo=data.tipo, notes=data.notes,
        banda=data.banda, valor_v4=data.valor_v4, valor_v6=data.valor_v6, codigo=data.codigo,
    )
```

Em `update_community`, depois da validação de tipo:

```python
    if {"banda", "valor_v4", "valor_v6", "codigo"} & set(mudancas):
        _validar_particao(
            banda=mudancas.get("banda", com.banda),
            valor_v4=mudancas.get("valor_v4", com.valor_v4),
            valor_v6=mudancas.get("valor_v6", com.valor_v6),
            codigo=mudancas.get("codigo", com.codigo),
        )
```

E a função, depois de `_validar_tipo`:

```python
def _validar_particao(
    *, banda: str | None, valor_v4: int | None, valor_v6: int | None, codigo: int | None
) -> None:
    """Recusa só o que é sempre erro de digitação: a família na coluna errada.

    As outras queixas da partição (valor fora de faixa, sem banda) são exceções
    legítimas da §14.4: elas entram no plano e a validação as aponta, em vez de
    a escrita impedir que o operador registre o que o equipamento tem.
    """
    problemas = conferir_linha(banda=banda, valor_v4=valor_v4, valor_v6=valor_v6, codigo=codigo)
    for problema in problemas:
        if problema.startswith("familia_incoerente"):
            familia = problema.split(":", 1)[1]
            raise ValidationError(
                f"Valor 2 bytes na família errada (coluna {familia}): "
                "o dígito de família do valor não confere com a coluna."
            )
```

Também acrescente os campos novos às gravações de auditoria: onde hoje o `depois` leva `{"name": ..., "tipo": ..., "notes": ...}`, ele passa a levar também `banda`, `valor_v4`, `valor_v6` e `codigo`. A auditoria do projeto grava antes/depois de tudo o que muda, e um valor de community que muda sem evento é uma mudança invisível.

- [ ] **Step 7: Rodar tudo e ver passar**

```bash
uv run pytest tests/domain -q
uv run ruff check src tests
```

Esperado: verde, incluindo os testes de catálogo que já existiam.

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/domain/communities_partition.py src/gerenet/domain/services/communities.py tests/domain
git commit -m "feat(communities): a partição como contrato verificável"
```

---

### Task 3: O leitor das communities na configuração

O `config_vrp.py` lê peer e subinterface e descarta de propósito as linhas que não modela — inclusive `peer <nome-de-grupo>`, que não é endereço (linha 359 do parser). Esta task escreve o segundo leitor do mesmo arquivo, que é quem enxerga o que o plano precisa: as definições, quem aplica, quem testa, quem é citado e sem definição, e os grupos de peer.

**Files:**
- Create: `src/gerenet/automation/parsers/huawei_vrp/communities_vrp.py`
- Create: `tests/fixtures/huawei_vrp/comunidades_edge.txt`, `tests/fixtures/huawei_vrp/comunidades_vs.txt`
- Test: `tests/automation/test_communities_vrp.py`

**Interfaces:**
- Consumes: nada.
- Produces: `DefinicaoCorpus(nome, classe, sintaxe, valores, linhas)`, `UsoCommunity(filtro, operacao, valores, corpus, corpus_classe, negado, additive, condicao, linha)`, `AlvoLido(nome, asn, membros, linha)`, `LeituraCommunities(asn_local, definicoes, usos, alvos, avisos)` e `parse_communities_vrp(texto: str) -> LeituraCommunities` com `operacao` em `{"aplica", "aplica-large", "testa", "testa-large", "cita"}` e `classe`/`corpus_classe` em `{"community", "large-community", "as-path", "prefix"}`.

- [ ] **Step 1: Criar as fixtures**

`tests/fixtures/huawei_vrp/comunidades_edge.txt` — trechos copiados literalmente de `current-configuration.txt` (linhas 2627, 2628, 3479-3492, 4579-4600, 4664-4680, 5276-5300), sem segredo:

```
#
ip community-filter advanced com-TRANSITO-FULL index 10 permit 65000:1010
ip community-filter advanced com-CLIENTES_PARCEIROS-CDN index 10 permit 65000:5001
ip community-filter advanced com-BLACKHOLE index 10 permit 65001:666
ip community-filter 2 index 10 permit 888
#
route-policy rm-Clientes-v4-full-out permit node 15
 if-match community-filter com-TRANSITO-FULL
#
xpl route-filter CUSTOMER-BGP-v4
 if (community matches-within COMM-SET-BLACKHOLE) and (ip route-destination in {0.0.0.0 0 ge 31 le 32}) then
  apply ip next-hop 192.0.2.1
  apply community COMM-SET-BLACKHOLE-OI additive
  approve
 endif
 if (ip route-destination in {0.0.0.0 0 le 23}) then
  apply community com-EXPORT-UPSTREAM-v4 additive
  apply local-preference 1000
  apply med 0
  approve
 endif
 if (ip route-destination in {0.0.0.0 0 le 24}) then
  apply community com-EXPORT-CDN-v4 additive
  apply local-preference 1000
  apply med 0
  finish
 endif
 end-filter
#
xpl route-filter ERTEL-201-131-155-0P24
 apply large-community {61785:3:14840, 61785:3:53065} additive
 end-filter
#
xpl route-filter RouteExportCheck
 if not community matches-any {61785:7002, 61785:7102, 65000:3001, 65000:4001} or community matches-any {65000:991} then
  refuse
 endif
 end-filter
#
xpl route-filter RouteExportCheck-PARCEIROS
 if not community matches-any {65000:4001} then
  refuse
 endif
 end-filter
#
xpl route-filter RouteExportCheckV6
 if not community matches-any {61785:7012, 61785:7112, 65000:3101, 65000:4101} then
  refuse
 endif
 end-filter
#
xpl route-filter UPSTREAM-V4-IMPORT($asn)
 if rpki is invalid then
  refuse
 endif
 if ip route-destination in MEU-PREFIXOS then
  refuse
 endif
 end-filter
#
xpl community-list COMM-SET-BLACKHOLE
 61785:666
 end-list
#
xpl community-list COMM-SET-BLACKHOLE-OI
 8167:666
 end-list
#
xpl community-list com-AS8167
 61785:8167
 end-list
#
xpl community-list com-BLACKHOLE
 61785:666,
 65001:666,
 37468:666
 end-list
#
xpl community-list com-EXPORT-CDN-v4
 61785:4001
 end-list
#
xpl community-list com-EXPORT-UPSTREAM-v4
 61785:3001
 end-list
#
bgp 61785
 peer MSD-CDN-v4 as-number 53062
 peer 100.127.190.5 group PARCEIROS_CDN
 peer PARCEIROS_CDN as-number 61587
```

`tests/fixtures/huawei_vrp/comunidades_vs.txt` — trechos de `current-configuration-cdn.log` (linhas 938-945, 1202-1215, 1343, 1354, 1708-1718, 1207):

```
#
ip community-filter advanced com-BLACKHOLE index 10 permit 65001:666
ip community-filter advanced com-CLIENTES_PARCEIROS-CDN index 10 permit 65000:5001
ip community-filter advanced com-CUSTOMER-CLIENTE-v4 index 10 permit 65000:7001
ip community-filter advanced com-CUSTOMER-CLIENTE-v6 index 10 permit 65000:7101
#
route-policy rm-CUSTOMER-AS268061-V4-IN permit node 10
 description CUSTOMER-AS268061-ITANET-V4
 if-match ip-prefix pl-CUSTOMER-AS268061-AS61587-V4
 apply local-preference 1000
 apply community 65000:4001
 apply large-community 61785:14840:4 61785:666:14840 additive
#
route-policy rm-CUSTOMER-AS268061-V6-IN permit node 10
 apply local-preference 1000
 apply community 65000:4101
#
route-policy rm-PARCEIROS_CDN-v4-in permit node 100
 apply local-preference 1000
 apply community 65000:4001 additive
#
route-policy rm-PARCEIROS_CDN-v6-in permit node 100
 apply community 65000:4101
#
xpl route-filter RouteExportCheck
 if not community matches-any {61785:7002, 61785:7102, 65000:3001, 65000:4001, 65000:991} then
  refuse
 endif
 end-filter
#
xpl route-filter RouteExportCheckV6
 if not community matches-any {61785:7012, 61785:7112, 65000:3101, 65000:4101, 65000:991} then
  refuse
 endif
 end-filter
#
xpl route-filter XPL-GGC-V4-EXPORT
 if community matches-within com-BLACKHOLE then
  refuse
 endif
 if ip route-destination in {100.64.0.0 10 le 24} then
  apply community {15169:12000} additive
 endif
 end-filter
#
bgp 61785
 peer IX-CG as-number 26162
 peer EQUINIX_SP as-number 24115
 peer 45.227.2.253 group IX-CG
 peer 64.191.232.250 group EQUINIX_SP
```

- [ ] **Step 2: Escrever o teste que falha**

`tests/automation/test_communities_vrp.py`:

```python
"""O leitor das communities na configuração (spec §9)."""
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.communities_vrp import (
    parse_communities_vrp,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _leitura(nome: str):
    return parse_communities_vrp((FIXTURES / nome).read_text())


def test_le_as_definicoes_dos_dois_formatos() -> None:
    leitura = _leitura("comunidades_edge.txt")
    por_nome = {d.nome: d for d in leitura.definicoes}

    assert por_nome["com-TRANSITO-FULL"].valores == ("65000:1010",)
    assert por_nome["com-TRANSITO-FULL"].classe == "community"
    assert por_nome["com-TRANSITO-FULL"].sintaxe == "ip-community-filter-advanced"
    # A community-list do XPL: várias linhas, vírgula no fim, `end-list` fechando.
    assert por_nome["com-BLACKHOLE"].valores == ("61785:666", "65001:666", "37468:666")
    assert por_nome["com-BLACKHOLE"].sintaxe == "xpl-community-list"
    # A forma numerada não perde o nome por não ter a palavra `advanced`.
    assert por_nome["2"].valores == ("888",)


def test_le_quem_aplica_e_quem_testa() -> None:
    leitura = _leitura("comunidades_edge.txt")
    aplica_upstream = [
        u for u in leitura.usos
        if u.filtro == "CUSTOMER-BGP-v4" and u.operacao == "aplica" and not u.corpus
    ]
    # `apply community com-EXPORT-UPSTREAM-v4 additive` cita o corpus, não o valor.
    assert aplica_upstream == []
    cita = {u.corpus for u in leitura.usos if u.filtro == "CUSTOMER-BGP-v4" and u.operacao == "aplica"}
    assert cita == {"COMM-SET-BLACKHOLE-OI", "com-EXPORT-UPSTREAM-v4", "com-EXPORT-CDN-v4"}

    portao = [u for u in leitura.usos if u.filtro == "RouteExportCheck" and u.operacao == "testa"]
    negados = [u for u in portao if u.negado]
    assert negados[0].valores == ("61785:7002", "61785:7102", "65000:3001", "65000:4001")
    assert [u.valores for u in portao if not u.negado] == [("65000:991",)]


def test_le_condicao_do_bloco_e_ordem_da_large_community() -> None:
    leitura = _leitura("comunidades_vs.txt")
    ggc = [
        u for u in leitura.usos
        if u.filtro == "XPL-GGC-V4-EXPORT" and u.operacao == "aplica"
    ]
    assert ggc[0].valores == ("15169:12000",)
    assert ggc[0].condicao.startswith("if ip route-destination in {100.64.0.0")

    # A linha 1207 do VS: as duas ordens de large-community no mesmo `apply`.
    erteis = [u for u in leitura.usos if u.operacao == "aplica-large" and u.filtro == "rm-CUSTOMER-AS268061-V4-IN"]
    assert erteis[0].valores == ("61785:14840:4", "61785:666:14840")
    assert erteis[0].additive is True


def test_le_additive_ausente() -> None:
    leitura = _leitura("comunidades_vs.txt")
    v4 = [u for u in leitura.usos if u.filtro == "rm-PARCEIROS_CDN-v4-in" and u.operacao == "aplica"]
    v6 = [u for u in leitura.usos if u.filtro == "rm-PARCEIROS_CDN-v6-in" and u.operacao == "aplica"]
    assert v4[0].additive is True
    assert v6[0].additive is False


def test_le_citacao_sem_definicao() -> None:
    leitura = _leitura("comunidades_edge.txt")
    citados = {u.corpus for u in leitura.usos if u.operacao == "cita"}
    assert "MEU-PREFIXOS" in citados
    definidos = {d.nome for d in leitura.definicoes}
    assert "MEU-PREFIXOS" not in definidos


def test_le_os_grupos_de_peer_e_os_membros() -> None:
    leitura = _leitura("comunidades_vs.txt")
    por_nome = {a.nome: a for a in leitura.alvos}
    assert por_nome["IX-CG"].asn == 26162
    assert por_nome["IX-CG"].membros == ("45.227.2.253",)
    assert por_nome["EQUINIX_SP"].membros == ("64.191.232.250",)


def test_le_o_asn_do_bloco_bgp() -> None:
    assert _leitura("comunidades_edge.txt").asn_local == 61785
    assert _leitura("comunidades_vs.txt").asn_local == 61785


def test_texto_vazio_nao_estoura() -> None:
    leitura = parse_communities_vrp("")
    assert leitura.asn_local is None
    assert leitura.definicoes == () and leitura.usos == () and leitura.alvos == ()
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
uv run pytest tests/automation/test_communities_vrp.py -q
```

Esperado: `ModuleNotFoundError: No module named 'gerenet.automation.parsers.huawei_vrp.communities_vrp'`.

- [ ] **Step 4: Escrever o leitor**

`src/gerenet/automation/parsers/huawei_vrp/communities_vrp.py`:

```python
"""As communities da configuração do VRP (spec §9).

O `config_vrp.py` lê peer e subinterface e ignora de propósito o que não modela
— inclusive `peer <nome-de-grupo>`, que não é endereço (linha 359 de lá). O
plano precisa exatamente do que ele descarta: as definições de community, quem
aplica, quem testa, quem é citado sem definição e os grupos de peer. As duas
leituras do mesmo arquivo convivem porque cada uma responde uma pergunta, e
nenhuma das duas precisa da outra.

Tolerância igual à do `config_vrp`: linha que não casa com nenhum ramo é
ignorada, e o que a leitura não entendeu sai em `avisos`, para "não entendi o
formato" não ficar idêntico a "o equipamento não tem community".

Este módulo não lê linha de peer de sessão — só `peer <nome> as-number` (grupo)
e `peer <ip> group <nome>` (membro) —, então `password cipher` não passa por
aqui (§19).
"""
import ipaddress
import re
from dataclasses import dataclass, field

_CLASSES = ("community", "large-community", "as-path", "prefix")

# `888`, `65000:3001`, `61785:666:14840`: o formato do valor é o filtro.
_RE_VALOR = re.compile(r"\d+(?::\d+){0,2}")

# Palavras que aparecem na linha e não são nome de corpus.
_PALAVRAS = frozenset(
    {
        "if", "then", "endif", "else", "or", "and", "not", "in", "apply", "additive",
        "overwrite", "delete", "community", "large-community", "matches-any",
        "matches-within", "matches-all", "as-path", "ip", "ipv6", "route-destination",
        "ip-prefix", "prefix-list", "regular", "as-path-filter", "community-filter",
        "next-hop", "local-preference", "med", "prepend", "finish", "approve", "refuse",
    }
)

# As definições que a checagem 8 ("nome citado e não definido") conhece,
# agrupadas pela classe semântica do corpus.
_DEFINICOES = (
    ("ip community-filter advanced ", "community", "ip-community-filter-advanced"),
    ("ip community-filter ", "community", "ip-community-filter"),
    ("ip large-community-filter ", "large-community", "ip-large-community-filter"),
    ("ip as-path-filter ", "as-path", "ip-as-path-filter"),
    ("ip ip-prefix ", "prefix", "ip-ip-prefix"),
    ("ip ipv6-prefix ", "prefix", "ip-ipv6-prefix"),
)


@dataclass(frozen=True)
class DefinicaoCorpus:
    nome: str
    classe: str                    # "community" | "large-community" | "as-path" | "prefix"
    sintaxe: str                   # a forma exata no VRP, para o relatório
    valores: tuple[str, ...]
    linhas: tuple[int, ...]


@dataclass(frozen=True)
class UsoCommunity:
    """Uma linha que toca em community, dentro de um filtro.

    `negado` distingue os dois sentidos de um teste: em `if not community
    matches-any {A} then refuse`, a lista A é o que **sobrevive** ao portão (as
    aceitas); em `if community matches-any {A} then refuse`, A é o que ele
    recusa à parte. Cada cláusula de um `if` encadeado por `or` vira um uso
    próprio, porque as cláusulas têm sentidos diferentes.
    """

    filtro: str                    # o route-policy / route-filter / prefix-list que contém a linha
    operacao: str                  # "aplica" | "aplica-large" | "testa" | "testa-large" | "cita"
    valores: tuple[str, ...]
    corpus: str | None             # nome citado em vez de valor literal
    corpus_classe: str | None
    negado: bool                   # `not ... matches-any`: a lista dos aceitos (§4.4)
    additive: bool | None
    condicao: str | None           # o `if ...` que guarda a linha, quando houver
    linha: int


@dataclass(frozen=True)
class AlvoLido:
    nome: str
    asn: int | None
    membros: tuple[str, ...]
    linha: int


@dataclass(frozen=True)
class LeituraCommunities:
    asn_local: int | None = None
    definicoes: tuple[DefinicaoCorpus, ...] = ()
    usos: tuple[UsoCommunity, ...] = ()
    alvos: tuple[AlvoLido, ...] = ()
    avisos: tuple[str, ...] = ()

    def valores_do_corpus(self, nome: str) -> tuple[str, ...]:
        """Os valores de uma definição pelo nome; vazio quando ela não existe.

        É o que resolve `apply community com-EXPORT-UPSTREAM-v4`: sem isso, a
        validação veria um filtro que aplica corpus e não aplica valor nenhum, e
        o achado principal da §8.1 (o portão testa `65000:3001` e o filtro
        aplica `61785:3001`) não sairia.
        """
        for definicao in self.definicoes:
            if definicao.nome == nome:
                return definicao.valores
        return ()


def _valores(texto: str) -> tuple[str, ...]:
    """Os valores de community de um trecho.

    `{a, b}` e `{a b}` dão a mesma coisa e um `apply community 65000:4001` sem
    chaves dá um valor só. O que não é valor fica fora porque o filtro é o
    formato: número, `asn:x` ou `asn:x:y`.
    """
    return tuple(_RE_VALOR.findall(texto))


def _corpus(tokens: list[str]) -> str | None:
    """O primeiro token que não é valor nem palavra-chave da linha."""
    for token in tokens:
        limpo = token.strip("{},")
        if not limpo or limpo in _PALAVRAS or _RE_VALOR.fullmatch(limpo):
            continue
        return limpo
    return None


def _fecha_chaves(linha: str) -> bool:
    return linha.count("{") == linha.count("}")


def _asn_do_bloco(linha: str) -> int | None:
    partes = linha.split()
    if len(partes) < 2:
        return None
    try:
        return int(partes[1])
    except ValueError:
        return None


def _e_endereco(token: str) -> bool:
    try:
        ipaddress.ip_address(token)
        return True
    except ValueError:
        return False


def _definicao(
    linha: str, numero: int, prefixo: str, classe: str, sintaxe: str
) -> DefinicaoCorpus | None:
    """Uma definição numa linha só: `<prefixo> <nome> [index N permit|deny] <valores>`.

    A forma numerada (`ip community-filter 2 index 10 permit 888`) tem o nome
    onde a avançada tem `advanced`, e o resto é igual: o nome é o primeiro token
    depois do prefixo, com `advanced` pulado quando existe.
    """
    resto = linha[len(prefixo):].split()
    if not resto:
        return None
    if resto[0] == "advanced":
        resto = resto[1:]
    if not resto:
        return None
    nome = resto[0]
    # O valor pode vir depois de `permit`/`deny`; sem eles, a linha inteira já é
    # nome + valor.
    corpo = linha.split(" permit ", 1)[-1] if " permit " in linha else linha
    corpo = corpo.split(" deny ", 1)[-1] if " deny " in linha else corpo
    if corpo == linha:  # nem permit nem deny: o corpo começa depois do nome
        corpo = linha.split(nome, 1)[-1]
    return DefinicaoCorpus(
        nome=nome, classe=classe, sintaxe=sintaxe, valores=_valores(corpo), linhas=(numero,)
    )


def _uso_de_teste(clausula: str, *, numero: int, filtro: str) -> UsoCommunity:
    """Um teste a partir de uma cláusula de `matches-*`, com o sentido dela.

    O `negado` sai da cláusula e não da linha: numa cadeia `or`, só a primeira
    carrega o `not` do `if`, e cada cláusula tem o seu próprio sentido.
    """
    partes = clausula.split()
    grande = "large-community" in partes
    if "{" in clausula:
        valores = _valores(clausula[clausula.index("{") + 1:clausula.index("}")])
        corpus = None
    else:
        marca = next((p for p in partes if p.startswith("matches-")), None)
        resto = partes[partes.index(marca) + 1:] if marca else []
        valores = _valores(" ".join(resto))
        corpus = None if valores else _corpus(resto)
    return UsoCommunity(
        filtro=filtro,
        operacao="testa-large" if grande else "testa",
        valores=valores,
        corpus=corpus,
        corpus_classe="large-community" if grande else "community",
        negado="not" in partes,
        additive=None,
        condicao=None,
        linha=numero,
    )


def _aplica_linha_de_filtro(
    linha: str, numero: int, filtro: str, condicao: str | None, avisos: list[str]
) -> tuple[UsoCommunity, ...]:
    """As linhas de community dentro de um filtro: aplicação, teste ou citação."""
    if not _fecha_chaves(linha):
        avisos.append(
            f"linha {numero}: chaves não fechadas na mesma linha, uso ignorado: {linha!r}"
        )
        return ()
    negado = linha.startswith("if not ") or " not " in linha
    partes = linha.split()

    # `apply community X` / `apply large-community X`
    if partes[0] == "apply" and len(partes) >= 2 and partes[1] in ("community", "large-community"):
        grande = partes[1] == "large-community"
        resto = partes[2:]
        valores = _valores(" ".join(resto))
        corpus = None if valores else _corpus(resto)
        return (
            UsoCommunity(
                filtro=filtro,
                operacao="aplica-large" if grande else "aplica",
                valores=valores,
                corpus=corpus,
                corpus_classe="large-community" if grande else "community",
                negado=False,
                additive="additive" in partes[2:],
                condicao=condicao,
                linha=numero,
            ),
        )

    # `if ... community matches-any/matches-within/matches-all {...}` / `... X`
    if "matches-" in linha:
        # O `or` de um `if` encadeado separa cláusulas com sentidos diferentes:
        # `if not community matches-any {A} or community matches-any {B} then
        # refuse` recusa quem não está em A **e** quem está em B. Lendo as duas
        # como uma lista só, o `{65000:991}` da borda desapareceria — e ele é
        # justamente a diferença entre o portão do CDN e o do upstream (§7).
        clausulas = [c for c in linha.split(" or ") if "matches-" in c]
        return tuple(
            _uso_de_teste(clausula, numero=numero, filtro=filtro) for clausula in clausulas
        )

    # Citação de corpus sem valor: `if as-path in X`, `if ip route-destination in X`,
    # `if-match community-filter X`, `if-match ip-prefix X`.
    if " in " in linha or linha.startswith("if-match "):
        resto = linha.split(" in ", 1)[1].split() if " in " in linha else partes[1:]
        if resto and not _valores(" ".join(resto)):
            nome = _corpus(resto)
            if nome:
                return (
                    UsoCommunity(
                        filtro=filtro, operacao="cita", valores=(), corpus=nome,
                        corpus_classe=_classe_da_citacao(linha), negado=negado,
                        additive=None, condicao=None, linha=numero,
                    ),
                )
    return ()


def _classe_da_citacao(linha: str) -> str:
    if "large-community" in linha:
        return "large-community"
    if "as-path" in linha:
        return "as-path"
    if "route-destination" in linha or "ip-prefix" in linha or "prefix-list" in linha:
        return "prefix"
    return "community"


def parse_communities_vrp(texto: str) -> LeituraCommunities:
    """Lê definições, usos, citações e grupos de peer da configuração inteira."""
    definicoes: list[DefinicaoCorpus] = []
    usos: list[UsoCommunity] = []
    avisos: list[str] = []
    grupos: dict[str, dict] = {}
    membros: dict[str, list[str]] = {}
    asn_local: int | None = None
    filtro: str | None = None
    condicao: str | None = None
    lista_xpl: str | None = None
    valores_lista: list[str] = []
    linhas_lista: list[int] = []

    for numero, bruta in enumerate(texto.splitlines(), 1):
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue

        # Grupo de peer e membro: aparecem indentados (dentro do `bgp`) e soltos
        # na captura, então a indentação não decide nada aqui.
        if linha.startswith("peer "):
            partes = linha.split()
            if len(partes) >= 4 and partes[2] == "group":
                membros.setdefault(partes[3], []).append(partes[1])
            elif len(partes) >= 3 and partes[2] == "as-number" and not _e_endereco(partes[1]):
                registro = grupos.setdefault(
                    partes[1], {"nome": partes[1], "asn": None, "linha": numero}
                )
                registro["asn"] = _asn_do_bloco(" ".join(partes[1:]))
            continue

        if lista_xpl is not None:
            if linha.startswith("end-list"):
                definicoes.append(
                    DefinicaoCorpus(
                        nome=lista_xpl, classe="community", sintaxe="xpl-community-list",
                        valores=tuple(valores_lista), linhas=tuple(linhas_lista),
                    )
                )
                lista_xpl, valores_lista, linhas_lista = None, [], []
                continue
            encontrados = _valores(linha)
            if encontrados:
                valores_lista.extend(encontrados)
                linhas_lista.append(numero)
            else:
                avisos.append(f"linha {numero}: valor não reconhecido em `{lista_xpl}`: {linha!r}")
            continue

        if linha.startswith("end-filter"):
            filtro, condicao = None, None
            continue

        indentado = bruta[:1] in (" ", "\t")

        if not indentado:
            filtro, condicao = None, None
            if linha.startswith("bgp "):
                asn_local = _asn_do_bloco(linha) or asn_local
            elif linha.startswith("xpl community-list "):
                lista_xpl = linha.split()[2]
            elif linha.startswith("route-policy "):
                filtro = linha.split()[1]
            elif linha.startswith("xpl route-filter "):
                filtro = linha.split()[2].split("(")[0]
            else:
                for prefixo, classe, sintaxe in _DEFINICOES:
                    if linha.startswith(prefixo):
                        definicao = _definicao(linha, numero, prefixo, classe, sintaxe)
                        if definicao is not None:
                            definicoes.append(definicao)
                        break
            continue

        if filtro is None:
            continue
        if linha.startswith("if ") and linha.endswith(" then"):
            condicao = linha
            # O `if` também pode ser o teste de community e trazer a condição.
            usos.extend(_aplica_linha_de_filtro(linha, numero, filtro, None, avisos))
            continue
        usos.extend(_aplica_linha_de_filtro(linha, numero, filtro, condicao, avisos))

    alvos = tuple(
        AlvoLido(
            nome=registro["nome"], asn=registro["asn"],
            membros=tuple(sorted(membros.get(registro["nome"], []))), linha=registro["linha"],
        )
        for registro in grupos.values()
    )
    return LeituraCommunities(
        asn_local=asn_local,
        definicoes=tuple(definicoes),
        usos=tuple(usos),
        alvos=alvos,
        avisos=tuple(avisos),
    )
```

- [ ] **Step 5: Rodar e ver passar**

```bash
uv run pytest tests/automation/test_communities_vrp.py -q
uv run ruff check src tests
```

Esperado: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/parsers/huawei_vrp/communities_vrp.py tests/automation/test_communities_vrp.py tests/fixtures/huawei_vrp
git commit -m "feat(communities): o leitor das definitions, usos e grupos de peer"
```

---

### Task 4: A validação

As oito checagens da §8 sobre o plano e as leituras. Esta task é o coração da fatia: é ela que dá valor imediato à adoção, porque compara **quem aplica** com **quem testa**. Tudo aqui é função pura — o `PlanoLido` pode vir da SoT (depois de adotar) ou da proposta (antes), e a mesma função roda nos dois casos.

**Files:**
- Create: `src/gerenet/automation/community_plan.py`
- Test: `tests/automation/test_community_plan.py`

**Interfaces:**
- Consumes: `LeituraCommunities`, `UsoCommunity`, `DefinicaoCorpus`, `AlvoLido` (Task 3); `CODIGOS_CONHECIDOS`, `familia_do_digito` (Task 2).
- Produces: `Achado(codigo, severidade, descricao, valor, filtro, linha, acao)`, `ClassePlano`, `InstrucaoPlano`, `PortaoPlano`, `AlvoPlano`, `RegraImportPlano`, `PlanoLido`, `VOCABULARIO`, `validar(plano, leituras, *, direcoes, estados_alvo) -> tuple[Achado, ...]`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/automation/test_community_plan.py`:

```python
"""A validação do plano (spec §8) sobre as leituras das duas capturas."""
from pathlib import Path

from gerenet.automation.community_plan import (
    Achado,
    AlvoPlano,
    ClassePlano,
    InstrucaoPlano,
    PlanoLido,
    PortaoPlano,
    validar,
)
from gerenet.automation.parsers.huawei_vrp.communities_vrp import parse_communities_vrp

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _leitura(nome: str):
    return parse_communities_vrp((FIXTURES / nome).read_text())


def _plano() -> PlanoLido:
    """O vocabulário da §6.1, com os nomes que o plano teria depois da adoção."""
    return PlanoLido(
        asn_principal=61785,
        classes=(
            ClassePlano(nome="com-TECMAIS-v4", banda="cliente", tipo="tag_produto", valor_v4=3001, valor_v6=3101),
            ClassePlano(nome="com-PARCEIROS_CDN-v4", banda="parceiro", tipo="tag_produto", valor_v4=4001, valor_v6=4101),
            ClassePlano(nome="com-TRANSITO-FULL", banda="transito", tipo="tag_produto", valor_v4=1010, valor_v6=1010),
            ClassePlano(nome="com-ONLY-CDN", banda="especial", tipo="tag_produto", valor_v4=991, valor_v6=991),
            ClassePlano(nome="com-TAMANHO-2", banda="tamanho", tipo="tag_produto", valor_v4=7002, valor_v6=7102),
            ClassePlano(nome="com-TAMANHO-1", banda="tamanho", tipo="tag_produto", valor_v4=7001, valor_v6=7101),
        ),
        instrucoes=(
            InstrucaoPlano(nome="com-BLACKHOLE-DENY", codigo=666),
        ),
        portoes=(
            PortaoPlano(nome="RouteExportCheck", papel="upstream", afi="ipv4", padrao="recusar",
                        aceitas=("com-TAMANHO-2", "com-TECMAIS-v4"), recusadas=("com-ONLY-CDN",)),
        ),
        alvos=(AlvoPlano(nome="MSD-CDN-v4", papel="cdn", codigo_v4=53062),),
    )


def _codigos(achados: tuple[Achado, ...]) -> dict[str, list[Achado]]:
    saida: dict[str, list[Achado]] = {}
    for achado in achados:
        saida.setdefault(achado.codigo, []).append(achado)
    return saida


def test_achado_da_secao_8_1_classe_aplicada_e_nao_testada() -> None:
    """§8.1: o portão testa o que ninguém aplica, e o filtro aplica o que o portão
    não testa — as classes novas (`61785:3001`, `61785:4001`) não estão em portão
    nenhum, e o upstream recusaria toda rota de cliente em silêncio."""
    achados = validar(_plano(), [_leitura("comunidades_edge.txt")])
    por_codigo = _codigos(achados)

    nao_testadas = {a.valor for a in por_codigo["classe_aplicada_nao_testada"]}
    assert "61785:3001" in nao_testadas
    assert "61785:4001" in nao_testadas
    assert all(a.severidade == "critico" for a in por_codigo["classe_aplicada_nao_testada"])


def test_achado_da_secao_8_1_ordem_da_large_community() -> None:
    """§8.1: as duas ordens na mesma linha do VS (`apply large-community
    61785:14840:4 61785:666:14840 additive`), e a inversa é apontada uma vez."""
    achados = validar(_plano(), [_leitura("comunidades_vs.txt")])
    invertidas = [
        a for a in achados if a.codigo == "ordem_invertida" and a.valor == "61785:14840:4"
    ]
    assert len(invertidas) == 1
    assert invertidas[0].filtro == "rm-CUSTOMER-AS268061-V4-IN"
    assert invertidas[0].linha is not None  # a linha da fixture, que é um recorte


def test_achado_da_secao_8_1_nome_citado_e_nao_definido() -> None:
    """§8.1: `MEU-PREFIXOS` é citado em `UPSTREAM-V4-IMPORT` e não existe."""
    achados = validar(_plano(), [_leitura("comunidades_edge.txt")])
    orfaos = [a for a in achados if a.codigo == "nome_nao_definido"]
    assert [a.valor for a in orfaos] == ["MEU-PREFIXOS"]
    assert orfaos[0].filtro == "UPSTREAM-V4-IMPORT"


def test_achado_da_secao_8_1_familia_trocada_na_marca_de_tamanho() -> None:
    """§8.1: `BGP-IPV4-CUSTOMER` aplica valores v6 em rota v4."""
    texto = """
xpl route-filter BGP-IPV4-CUSTOMER
 if (ip route-destination in {0.0.0.0 0 le 22}) then
  apply community 61785:7001 additive
  approve
 endif
 if (ip route-destination in {0.0.0.0 0 le 23}) then
  apply community 65000:7101 additive
  approve
 endif
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    trocadas = [a for a in achados if a.codigo == "familia_incoerente" and a.valor == "65000:7101"]
    assert len(trocadas) == 1 and trocadas[0].filtro == "BGP-IPV4-CUSTOMER"


def test_achado_da_secao_8_1_apply_sem_additive() -> None:
    """§8.1: o mesmo par, a mesma classe, `additive` no v4 e não no v6 — e as
    seis linhas de import de cliente do VS, que aplicam a classe sem ele."""
    direcoes = {
        "rm-PARCEIROS_CDN-v4-in": "import",
        "rm-PARCEIROS_CDN-v6-in": "import",
        "rm-CUSTOMER-AS268061-V4-IN": "import",
    }
    achados = validar(_plano(), [_leitura("comunidades_vs.txt")], direcoes=direcoes)
    sem_additive = [a for a in achados if a.codigo == "community_sem_additive"]
    filtros = {a.filtro for a in sem_additive}
    assert "rm-PARCEIROS_CDN-v6-in" in filtros
    assert "rm-PARCEIROS_CDN-v4-in" not in filtros
    # `rm-CUSTOMER-AS268061-V4-IN` aplica `65000:4001` sem `additive` e é uma
    # das seis linhas de import de cliente da §8.1 (1207 da captura): o achado
    # sai para ele também.
    assert "rm-CUSTOMER-AS268061-V4-IN" in filtros


def test_achado_da_secao_8_1_instrucao_sem_portao() -> None:
    """§8.1: `com-TRANSITO-FULL` é aplicada no import e nenhum portão a considera."""
    texto = """
xpl route-filter ASN6762-V4-IMPORT($preference)
 apply community 65000:1010 additive
 end-filter
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    por_codigo = _codigos(achados)
    sem_portao = {a.valor for a in por_codigo.get("classe_aplicada_nao_testada", [])}
    assert "65000:1010" in sem_portao


def test_plano_conforme_nao_produz_achado_critico() -> None:
    texto = """
xpl route-filter CLASSIFICA-V4
 apply community 61785:3001 additive
 end-filter
xpl route-filter RouteExportCheck
 if not community matches-any {61785:3001} then
  refuse
 endif
 end-filter
"""
    plano = PlanoLido(
        asn_principal=61785,
        classes=(ClassePlano(nome="com-TECMAIS-v4", banda="cliente", tipo="tag_produto", valor_v4=3001),),
    )
    achados = validar(plano, [parse_communities_vrp(texto)])
    assert [a for a in achados if a.severidade == "critico"] == []


def test_alvo_sem_sessao_e_codigo_orfao() -> None:
    texto = """
xpl route-filter QUALQUER
 apply large-community 61785:9999:14840 additive
 end-filter
"""
    achados = validar(
        _plano(),
        [parse_communities_vrp(texto)],
        estados_alvo={"MSD-CDN-v4": "parado"},
    )
    por_codigo = _codigos(achados)
    assert [a.valor for a in por_codigo["codigo_orfao"]] == ["61785:9999:14840"]
    assert [a.valor for a in por_codigo["alvo_sem_sessao"]] == ["MSD-CDN-v4"]


def test_alvo_sem_linha_em_community_targets() -> None:
    """§8, checagem 3, segunda metade: o alvo de uma instrução do plano sem linha em
    `community_targets`.

    `61785:666:14840` é uma instrução do plano (666) apontada para o AS14840, que
    não tem linha de alvo; `61785:14840:4` é a mesma linha na ordem invertida, e a
    segunda metade da checagem **não** fala dela: o código 4 não é instrução
    deste plano recortado, então não há alvo de instrução para conferir.
    """
    achados = validar(_plano(), [_leitura("comunidades_vs.txt")])
    por_codigo = _codigos(achados)
    sem_linha = [a.valor for a in por_codigo.get("alvo_sem_target", [])]
    assert sem_linha == ["61785:666:14840"]
    assert por_codigo["alvo_sem_target"][0].severidade == "informativo"


def test_colisao_entre_namespaces() -> None:
    """O mesmo 2 bytes com dois nomes de significado diferente (§8, checagem 5)."""
    texto = """
ip community-filter advanced com-CUSTOMER-CLIENTE-v4 index 10 permit 65000:7001
ip community-filter advanced com-TAMANHO-1-v4 index 10 permit 65000:7001
"""
    achados = validar(_plano(), [parse_communities_vrp(texto)])
    colisoes = [a for a in achados if a.codigo == "colisao_namespace"]
    assert [a.valor for a in colisoes] == ["65000:7001"]


def test_vocabulario_fora_da_particao_e_apontado() -> None:
    plano = PlanoLido(
        asn_principal=61785,
        classes=(
            ClassePlano(nome="com-ERRADA", banda="cliente", tipo="tag_produto", valor_v4=7103),
            ClassePlano(nome="com-SEM-BANDA", tipo="tag_produto", valor_v4=3002),
        ),
    )
    achados = validar(plano, [])
    problemas = {a.valor for a in achados if a.codigo == "valor_fora_da_particao"}
    assert problemas == {"com-ERRADA", "com-SEM-BANDA"}
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run pytest tests/automation/test_community_plan.py -q
```

Esperado: `ModuleNotFoundError: No module named 'gerenet.automation.community_plan'`.

- [ ] **Step 3: Escrever o motor — parte 1: os tipos e o vocabulário**

`src/gerenet/automation/community_plan.py`, até a metade (a outra metade é o Step 4):

```python
"""O plano de communities como dado e as oito checagens da §8.

Função pura de propósito: o `PlanoLido` vem da SoT depois da adoção **ou** da
proposta antes dela, e `validar` roda igual nos dois casos. É isso que faz a
validação valer antes de o plano existir no banco — que é o ponto da §8.

A comparação de "quem aplica" contra "quem testa" é por **valor literal**
(`61785:3001` ≠ `65000:3001`), e não pela classe do código: as duas grafias são
a mesma classe e namespaces diferentes, e é justamente a troca de namespace
entre o filtro que aplica e o portão que testa que produz o achado principal da
§8.1. O rótulo do achado vem da classe do código, para o relatório falar a
língua do operador.
"""
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from gerenet.automation.parsers.huawei_vrp.communities_vrp import (
    DefinicaoCorpus,
    LeituraCommunities,
    UsoCommunity,
)
from gerenet.domain.communities_partition import (
    CODIGOS_CONHECIDOS,
    FAIXAS,
    conferir_linha,
    familia_do_digito,
)

SEVERIDADES = ("critico", "atencao", "informativo")


@dataclass(frozen=True)
class Achado:
    """Um problema encontrado na comparação, com o endereço dele no equipamento."""

    codigo: str
    severidade: str
    descricao: str
    valor: str | None = None
    filtro: str | None = None
    linha: int | None = None
    acao: str | None = None


@dataclass(frozen=True)
class ClassePlano:
    nome: str
    banda: str | None
    tipo: str
    valor_v4: int | None = None
    valor_v6: int | None = None
    id: int | None = None
    notas: str | None = None


@dataclass(frozen=True)
class InstrucaoPlano:
    nome: str
    codigo: int | None
    tipo: str = "informacao"
    id: int | None = None
    notas: str | None = None


@dataclass(frozen=True)
class PortaoPlano:
    nome: str
    papel: str
    afi: str
    padrao: str = "recusar"
    aceitas: tuple[str, ...] = ()
    recusadas: tuple[str, ...] = ()
    id: int | None = None


@dataclass(frozen=True)
class AlvoPlano:
    nome: str
    papel: str
    codigo_v4: int | None = None
    codigo_v6: int | None = None
    gate_nome: str | None = None
    classe_import: str | None = None
    upstream_id: int | None = None
    organization_id: int | None = None
    parametros: dict = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True)
class RegraImportPlano:
    papel: str
    afi: str
    classe: str
    condicao: dict = field(default_factory=dict)
    notas: str | None = None


@dataclass(frozen=True)
class PlanoLido:
    asn_principal: int | None = None
    asns_anunciados: tuple[dict, ...] = ()
    classes: tuple[ClassePlano, ...] = ()
    instrucoes: tuple[InstrucaoPlano, ...] = ()
    portoes: tuple[PortaoPlano, ...] = ()
    alvos: tuple[AlvoPlano, ...] = ()
    regras_import: tuple[RegraImportPlano, ...] = ()
    snapshot_id: int | None = None
    observacoes: str | None = None


# A §6.1 transcrita: a referência que permite rotular um valor antes de o plano
# existir no banco. `nome` é o nome no namespace clássico quando ele existe; o
# nome do XPL vai em `notas`, porque o índice único de `valor_v4` não deixa as
# duas grafias virarem duas linhas (Regra 1 do plano).
VOCABULARIO: tuple[ClassePlano, ...] = (
    ClassePlano("com-TECMAIS-v4", "cliente", "tag_produto", 3001, 3101,
                notas="namespace XPL: com-EXPORT-UPSTREAM-v4 (61785:3001)"),
    ClassePlano("com-PARCEIROS_CDN-v4", "parceiro", "tag_produto", 4001, 4101,
                notas="namespace XPL: com-EXPORT-CDN-v4 (61785:4001)"),
    ClassePlano("com-TRANSITO-FULL", "transito", "tag_produto", 1010, 1010),
    ClassePlano("com-ONLY-CDN", "especial", "tag_produto", 991, 991),
    ClassePlano("com-TROCA-v4", "especial", "tag_produto", 992, 993),
    ClassePlano("com-CLIENTES_PARCEIROS-CDN", "conjunto", "tag_produto", 5001, None),
    ClassePlano("com-IX-LOCAL-TECMAIS-v4", "local", "tag_produto", 90, 91),
    ClassePlano("com-PTT_SP", "local", "tag_produto", 11, None),
    ClassePlano("com-TAMANHO-1", "tamanho", "tag_produto", 7001, 7101),
    ClassePlano("com-TAMANHO-2", "tamanho", "tag_produto", 7002, 7102),
    ClassePlano("com-TAMANHO-3", "tamanho", "tag_produto", 7003, 7103),
)

# A §6.2 transcrita. O prepend guarda o **nível**; o código da borda é o nível
# vezes 11 e o do virtual system é o próprio nível (§6.2), e quem resolve isso
# é o render da F4.
VOCABULARIO_INSTRUCOES: tuple[InstrucaoPlano, ...] = (
    InstrucaoPlano("com-PROVENIENCIA-V4", 4, "informacao"),
    InstrucaoPlano("com-PROVENIENCIA-V6", 6, "informacao"),
    InstrucaoPlano("com-BLACKHOLE-DENY", 666, "acao_blackhole"),
    InstrucaoPlano("com-CLIENTE-MARCADO", 100, "informacao"),
    InstrucaoPlano("com-ERTEL", 3, "informacao", notas="mesmo código do prepend nível 3 no VS (§6.2)"),
    InstrucaoPlano("com-BLACKHOLE-2", 6662, "acao_blackhole"),
    InstrucaoPlano("com-PREPEND-1", 1, "acao_prepend", notas="na borda o código é 11"),
    InstrucaoPlano("com-PREPEND-2", 2, "acao_prepend", notas="na borda o código é 22"),
    InstrucaoPlano("com-PREPEND-3", 3, "acao_prepend", notas="na borda o código é 33"),
)


def _codigo_do_valor(valor: str) -> int | None:
    """O código de um valor, lido da **posição**: o segundo campo.

    Posicional e não "semântico" de propósito: numa large-community invertida
    (`61785:14840:4`) o segundo campo é o alvo, e quem sabe disso é a checagem 4
    (`_ordem_do_valor`), que troca os dois antes de usá-los.
    """
    partes = valor.split(":")
    if len(partes) < 2:
        return None
    try:
        return int(partes[1])
    except ValueError:
        return None


def _alvo_do_valor(valor: str) -> int | None:
    partes = valor.split(":")
    if len(partes) != 3:
        return None
    try:
        return int(partes[2])
    except ValueError:
        return None


def classe_do_valor(plano: PlanoLido, valor: str) -> ClassePlano | None:
    """A classe a que um valor de 2 bytes pertence, por código (namespace-agnóstico)."""
    if valor.count(":") != 1:
        return None
    codigo = _codigo_do_valor(valor)
    if codigo is None:
        return None
    for classe in plano.classes:
        if codigo in (classe.valor_v4, classe.valor_v6):
            return classe
    return None


def _e_valor_de_classe(valor: str) -> bool:
    """Se o valor de 2 bytes pode ser uma classe do plano.

    Os códigos do vocabulário de instruções (`CODIGOS_CONHECIDOS`) não viram
    classe: `8167:666` e `65001:666` são marcas de blackhole de outros ASNs e o
    666 é o `com-BLACKHOLE-DENY` (§6.2). Sem esta guarda, cada marca dessas
    viraria uma linha de classe na adoção e a checagem 1 acusaria "aplicada e
    não testada" para elas — que é assunto da checagem 3, não da 1.
    """
    return valor.count(":") == 1 and _codigo_do_valor(valor) not in CODIGOS_CONHECIDOS


def _ordem_do_valor(valor: str) -> str | None:
    """A ordem da large-community: `codigo:alvo` ou `alvo:codigo` (§8, checagem 4)."""
    partes = valor.split(":")
    if len(partes) != 3:
        return None
    try:
        meio, fim = int(partes[1]), int(partes[2])
    except ValueError:
        return None
    if fim in CODIGOS_CONHECIDOS and meio not in CODIGOS_CONHECIDOS:
        return "alvo:codigo"
    if meio in CODIGOS_CONHECIDOS:
        return "codigo:alvo"
    return None
```

- [ ] **Step 4: Escrever o motor — parte 2: as checagens**

Continue o mesmo arquivo:

```python
def _afi_do_filtro(filtro: str, valores: Sequence[str]) -> str | None:
    """O AFI de um filtro: o nome primeiro, os valores como desempate.

    O nome é o sinal forte (`BGP-IPV4-CUSTOMER`, `...-V6`). Sem ele, o dígito de
    família do valor decide quando todos concordam; sem os dois, `None` — e a
    checagem de família não roda, porque apontar sem evidência seria inventar.
    """
    minusculo = filtro.lower()
    if "ipv6" in minusculo or "-v6" in minusculo or "_v6" in minusculo or "v6-" in minusculo:
        return "ipv6"
    if "ipv4" in minusculo or "-v4" in minusculo or "_v4" in minusculo or "v4-" in minusculo:
        return "ipv4"
    familias = {familia for familia in (familia_do_digito(_codigo_do_valor(v) or 0) for v in valores) if familia}
    if len(familias) == 1:
        return "ipv6" if familias == {"v6"} else "ipv4"
    return None


def _aplicados_e_testados(
    leituras: Sequence[LeituraCommunities],
) -> tuple[list[UsoCommunity], list[UsoCommunity]]:
    """Os usos que aplicam e os que testam, com o corpus citado já resolvido.

    `apply community com-EXPORT-UPSTREAM-v4` aplica o **corpo** da lista, não o
    nome dela. Sem resolver, o `61785:3001` que o filtro aplica não existiria
    para a checagem 1 e o achado principal da §8.1 sairia pela metade: é a
    comparação dele com o `65000:3001` que o portão testa que aponta o problema.
    """
    por_nome = {d.nome: d.valores for leitura in leituras for d in leitura.definicoes}
    usos = [
        replace(uso, valores=por_nome.get(uso.corpus, ()))
        if uso.corpus and not uso.valores
        else uso
        for leitura in leituras
        for uso in leitura.usos
    ]
    aplicados = [u for u in usos if u.operacao.startswith("aplica")]
    testados = [u for u in usos if u.operacao.startswith("testa")]
    return aplicados, testados


def _com_valores(usos: Sequence[UsoCommunity]) -> list[UsoCommunity]:
    """Só os usos que chegam com valor: corpus sem definição não aplica nada."""
    return [uso for uso in usos if uso.valores]


def _conferir_vocabulario(plano: PlanoLido) -> list[Achado]:
    """Checagem 2: conformidade com a partição.

    Classes e instruções entram na mesma checagem com campos diferentes (a classe
    tem `valor_v4`/`valor_v6`, a instrução tem `codigo`), então a lista abaixo
    achata as duas formas em linhas de cinco campos antes de chamar
    `conferir_linha` — em vez de um laço que mistura os dois tipos e precisa de
    `getattr` para atravessar a diferença.
    """
    achados: list[Achado] = []
    linhas: list[tuple[str, str | None, int | None, int | None, int | None]] = [
        (classe.nome, classe.banda, classe.valor_v4, classe.valor_v6, None)
        for classe in plano.classes
    ]
    linhas += [
        (instrucao.nome, "instrucao", None, None, instrucao.codigo)
        for instrucao in plano.instrucoes
    ]
    for nome, banda, valor_v4, valor_v6, codigo in linhas:
        problemas = conferir_linha(
            banda=banda, valor_v4=valor_v4, valor_v6=valor_v6, codigo=codigo
        )
        if problemas:
            achados.append(
                Achado(
                    codigo="valor_fora_da_particao",
                    severidade="atencao",
                    descricao=f"{nome}: {', '.join(problemas)}",
                    valor=nome,
                    acao="ajustar a banda, o valor ou registrar a exceção na partição",
                )
            )
    vistos_v4: dict[int, str] = {}
    vistos_v6: dict[int, str] = {}
    for classe in plano.classes:
        for valor, vistos in ((classe.valor_v4, vistos_v4), (classe.valor_v6, vistos_v6)):
            if valor is None:
                continue
            if valor in vistos:
                achados.append(
                    Achado(
                        codigo="valor_duplicado",
                        severidade="critico",
                        descricao=f"{valor} em {vistos} e em {classe.nome}",
                        valor=str(valor),
                        acao="um valor é uma classe: desativar a linha repetida",
                    )
                )
            vistos[valor] = classe.nome
    return achados


def _conferir_quem_aplica_e_quem_testa(
    plano: PlanoLido, leituras: Sequence[LeituraCommunities]
) -> list[Achado]:
    """Checagem 1: a que dá valor imediato à adoção (§8.1)."""
    achados: list[Achado] = []
    aplicados, testados = _aplicados_e_testados(leituras)
    valores_aplicados = {v for uso in _com_valores(aplicados) for v in uso.valores if _e_valor_de_classe(v)}
    valores_testados = {v for uso in _com_valores(testados) for v in uso.valores if _e_valor_de_classe(v)}

    for uso in _com_valores(aplicados):
        for valor in uso.valores:
            if not _e_valor_de_classe(valor) or valor in valores_testados:
                continue
            classe = classe_do_valor(plano, valor)
            rotulo = classe.nome if classe else "sem classe no vocabulário"
            achados.append(
                Achado(
                    codigo="classe_aplicada_nao_testada",
                    severidade="critico",
                    descricao=f"{valor} ({rotulo}) é aplicado e nenhum portão o testa",
                    valor=valor, filtro=uso.filtro, linha=uso.linha,
                    acao="incluir a classe no portão do papel, com a grafia que o filtro aplica",
                )
            )
    for uso in _com_valores(testados):
        for valor in uso.valores:
            if not _e_valor_de_classe(valor) or valor in valores_aplicados:
                continue
            achados.append(
                Achado(
                    codigo="classe_testada_nao_aplicada",
                    severidade="atencao",
                    descricao=f"{valor} é testado por {uso.filtro} e nenhum filtro o aplica",
                    valor=valor, filtro=uso.filtro, linha=uso.linha,
                    acao="remover do portão ou passar a aplicar a classe na entrada",
                )
            )
    valores_large_aplicados = {v for uso in _com_valores(aplicados) for v in uso.valores if v.count(":") == 2}
    valores_large_testados = {v for uso in _com_valores(testados) for v in uso.valores if v.count(":") == 2}
    for uso in _com_valores(aplicados):
        for valor in uso.valores:
            if valor.count(":") != 2 or valor in valores_large_testados:
                continue
            if _codigo_do_valor(valor) not in CODIGOS_CONHECIDOS:
                continue  # código órfão é assunto da checagem 3
            achados.append(
                Achado(
                    codigo="instrucao_aplicada_nao_testada",
                    severidade="atencao",
                    descricao=f"a instrução {valor} é aplicada e nenhum filtro a testa",
                    valor=valor, filtro=uso.filtro, linha=uso.linha,
                    acao="verificar se a instrução deveria ter um ramo que a consuma",
                )
            )
    return achados


def _conferir_instrucoes(
    plano: PlanoLido, leituras: Sequence[LeituraCommunities]
) -> list[Achado]:
    """Checagens 3 e 4: código órfão, alvo sem `community_targets` e ordem invertida."""
    achados: list[Achado] = []
    codigos_do_plano = {i.codigo for i in plano.instrucoes}
    alvos_do_plano = {a.codigo_v4 for a in plano.alvos} | {a.codigo_v6 for a in plano.alvos}
    ordens: dict[tuple[int, int], set[str]] = {}
    for leitura in leituras:
        for uso in leitura.usos:
            for valor in uso.valores:
                if valor.count(":") != 2:
                    continue
                codigo, alvo_numero = _codigo_do_valor(valor), _alvo_do_valor(valor)
                if codigo is None or alvo_numero is None:
                    continue
                ordem = _ordem_do_valor(valor)
                if ordem == "alvo:codigo":
                    # Ordem invertida: o campo do meio é o alvo e o último é o
                    # código, o contrário do que os nomes dizem. Sem a troca, o
                    # alvo (14840) passaria por código e viraria `codigo_orfao`,
                    # e a inversão — que é o achado da §8.1 — não sairia.
                    codigo, alvo_numero = alvo_numero, codigo
                if codigo not in CODIGOS_CONHECIDOS:
                    achados.append(
                        Achado(
                            codigo="codigo_orfao", severidade="atencao",
                            descricao=f"o código {codigo} de {valor} não tem linha no vocabulário",
                            valor=valor, filtro=uso.filtro, linha=uso.linha,
                            acao="cadastrar a instrução no vocabulário ou corrigir o código",
                        )
                    )
                if alvo_numero not in alvos_do_plano and codigo in codigos_do_plano:
                    achados.append(
                        Achado(
                            codigo="alvo_sem_target", severidade="informativo",
                            descricao=f"o alvo {alvo_numero} de {valor} não tem linha em community_targets",
                            valor=valor, filtro=uso.filtro, linha=uso.linha,
                            acao="cadastrar o alvo no plano quando ele for um peer gerenciado",
                        )
                    )
                if ordem is not None and codigo in CODIGOS_CONHECIDOS:
                    # Depois da troca os dois nomes valem nos dois sentidos, então
                    # a chave é sempre (código, alvo) — é o que faz o import e o
                    # export do mesmo par caírem na mesma entrada de `ordens`.
                    ordens.setdefault((codigo, alvo_numero), set()).add(ordem)
    for (codigo, alvo_numero), vistas in ordens.items():
        if "alvo:codigo" in vistas:
            invertido = f"61785:{alvo_numero}:{codigo}"
            achados.append(
                Achado(
                    codigo="ordem_invertida", severidade="critico",
                    descricao=(
                        f"{invertido} está na ordem `alvo:código`; o vocabulário fixa "
                        f"`61785:<código>:<alvo>` (`61785:{codigo}:{alvo_numero}`)"
                    ),
                    valor=invertido,
                    acao="corrigir a ordem no equipamento por change request (§14.5)",
                )
            )
    return achados


def _conferir_namespaces(leituras: Sequence[LeituraCommunities]) -> list[Achado]:
    """Checagem 5: o mesmo 2 bytes com dois nomes de significados diferentes."""
    por_valor: dict[str, set[str]] = {}
    for leitura in leituras:
        for definicao in leitura.definicoes:
            if definicao.classe != "community":
                continue
            for valor in definicao.valores:
                if valor.count(":") == 1:
                    por_valor.setdefault(valor, set()).add(definicao.nome)
    achados: list[Achado] = []
    for valor, nomes in por_valor.items():
        if len(nomes) > 1:
            achados.append(
                Achado(
                    codigo="colisao_namespace", severidade="critico",
                    descricao=f"{valor} está definido como {' e '.join(sorted(nomes))}",
                    valor=valor,
                    acao="decidir qual sentido fica e migrar o outro (§14.2)",
                )
            )
    return achados


def _conferir_additive(
    leituras: Sequence[LeituraCommunities], direcoes: Mapping[str, str]
) -> list[Achado]:
    """Checagem 6: `apply community` sem `additive` numa regra de import.

    A direção não se adivinha pelo nome do filtro (Regra 4): ela vem do vínculo
    `peer ... route-policy <nome> import`, que o `config_vrp` já lê.
    """
    achados: list[Achado] = []
    for leitura in leituras:
        for uso in leitura.usos:
            if uso.operacao != "aplica" or uso.additive:
                continue
            if direcoes.get(uso.filtro) != "import":
                continue
            achados.append(
                Achado(
                    codigo="community_sem_additive", severidade="critico",
                    descricao=(
                        f"`apply community` sem `additive` em {uso.filtro} apaga as "
                        "communities que o par mandou"
                    ),
                    valor=",".join(uso.valores) or uso.corpus,
                    filtro=uso.filtro, linha=uso.linha,
                    acao="acrescentar `additive` ao comando, por change request",
                )
            )
    return achados


def _conferir_referencias(
    plano: PlanoLido, leituras: Sequence[LeituraCommunities]
) -> list[Achado]:
    """Checagem 8: nome citado e não definido.

    Todo uso que nomeia um corpus é uma referência, e não só o `cita`:
    `if community matches-within com-BLACKHOLE` referencia a lista do mesmo
    jeito que `ip route-destination in MEU-PREFIXOS` referencia a prefix-list, e
    sem definição não há o que casar. O achado sai um por uso — filtro e linha
    dizem onde, e é isso que o operador precisa para corrigir cada ponto.
    """
    achados: list[Achado] = []
    definidos: dict[str, set[str]] = {}
    for leitura in leituras:
        for definicao in leitura.definicoes:
            definidos.setdefault(definicao.classe, set()).add(definicao.nome)
    nomes_do_plano = {c.nome for c in plano.classes} | {i.nome for i in plano.instrucoes}
    for leitura in leituras:
        for uso in leitura.usos:
            if not uso.corpus:
                continue
            classe = uso.corpus_classe or "community"
            if uso.corpus in nomes_do_plano or uso.corpus in definidos.get(classe, set()):
                continue
            if uso.corpus in definidos.get("community", set()):
                continue  # definido, ainda que em outra forma
            achados.append(
                Achado(
                    codigo="nome_nao_definido", severidade="critico",
                    descricao=(
                        f"{uso.corpus} é citado em {uso.filtro} e não tem definição "
                        f"na configuração nem linha no plano"
                    ),
                    valor=uso.corpus, filtro=uso.filtro, linha=uso.linha,
                    acao="definir a lista no equipamento ou remover a referência (§14.3)",
                )
            )
    return achados


def _conferir_alvos(plano: PlanoLido, estados_alvo: Mapping[str, str]) -> list[Achado]:
    """Checagem 7: alvo do plano cujo peer não está Established."""
    achados: list[Achado] = []
    for alvo in plano.alvos:
        estado = estados_alvo.get(alvo.nome, "ausente")
        if estado == "established":
            continue
        achados.append(
            Achado(
                codigo="alvo_sem_sessao", severidade="atencao",
                descricao=f"{alvo.nome} está no plano e a sessão está {estado}",
                valor=alvo.nome,
                acao="confirmar se o alvo continua em uso ou desativá-lo no plano",
            )
        )
    return achados


def validar(
    plano: PlanoLido,
    leituras: Sequence[LeituraCommunities],
    *,
    direcoes: Mapping[str, str] | None = None,
    estados_alvo: Mapping[str, str] | None = None,
) -> tuple[Achado, ...]:
    """As oito checagens da §8, na ordem em que elas aparecem na spec.

    `direcoes` é o mapa filtro → `import`/`export` (checagem 6) e `estados_alvo`
    é o mapa alvo → `established`/`parado`/`ausente` (checagem 7): os dois são
    **observação** da SoT e do equipamento, não veredito, e por isso entram como
    parâmetro em vez de o motor consultar o banco.
    """
    achados: list[Achado] = []
    achados.extend(_conferir_vocabulario(plano))
    achados.extend(_conferir_quem_aplica_e_quem_testa(plano, leituras))
    achados.extend(_conferir_instrucoes(plano, leituras))
    achados.extend(_conferir_namespaces(leituras))
    achados.extend(_conferir_additive(leituras, direcoes or {}))
    achados.extend(_conferir_alvos(plano, estados_alvo or {}))
    achados.extend(_conferir_referencias(plano, leituras))
    return tuple(achados)
```

- [ ] **Step 5: Rodar e ver passar**

```bash
uv run pytest tests/automation/test_community_plan.py -q
uv run ruff check src tests
```

Esperado: 10 passed. Se `test_achado_da_secao_8_1_familia_trocada_na_marca_de_tamanho` falhar porque o AFI do filtro não foi resolvido, confira `_afi_do_filtro`: o nome `BGP-IPV4-CUSTOMER` tem `ipv4` e o valor `65000:7101` tem família `v6` — é essa contradição que produz o achado.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/community_plan.py tests/automation/test_community_plan.py
git commit -m "feat(communities): as oito checagens de validação do plano"
```

---

### Task 5: A proposta de adoção

Do que a leitura encontrou, montar o `PlanoLido` que a adoção gravaria — com a poda de sessão parada (§9.3) e as divergências que a adoção **não** decide sozinha (§9): o código ambíguo, o nome que discorda da faixa, o papel duvidoso do alvo.

**Files:**
- Modify: `src/gerenet/automation/community_plan.py` (acrescenta ao fim)
- Test: `tests/automation/test_community_plan_proposta.py`

**Interfaces:**
- Consumes: tudo da Task 4.
- Produces: `PropostaPlano(plano, divergencias, parados, avisos)`, `propor_plano(leituras, *, asn_principal, estados_alvo, papéis_da_sot) -> PropostaPlano`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/automation/test_community_plan_proposta.py`:

```python
"""A proposta de adoção do plano (spec §9): o que ela monta e o que ela não decide."""
from pathlib import Path

from gerenet.automation.community_plan import propor_plano
from gerenet.automation.parsers.huawei_vrp.communities_vrp import parse_communities_vrp

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _leitura(nome: str):
    return parse_communities_vrp((FIXTURES / nome).read_text())


def test_propoe_a_classe_com_o_valor_e_a_banda_da_faixa() -> None:
    proposta = propor_plano([_leitura("comunidades_edge.txt")], asn_principal=61785)
    por_nome = {c.nome: c for c in proposta.plano.classes}
    assert por_nome["com-TRANSITO-FULL"].banda == "transito"
    assert por_nome["com-TRANSITO-FULL"].valor_v4 == 1010
    assert por_nome["com-CLIENTES_PARCEIROS-CDN"].banda == "conjunto"


def test_propoe_o_portao_com_aceitas_e_recusadas() -> None:
    """O `not ... matches-any` é a lista de aceitas e o `or ... matches-any` a de
    recusadas, com padrão recusar (§4.4)."""
    proposta = propor_plano([_leitura("comunidades_edge.txt")], asn_principal=61785)
    portoes = {g.nome: g for g in proposta.plano.portoes}
    assert portoes["RouteExportCheck"].padrao == "recusar"
    assert "com-ONLY-CDN" in portoes["RouteExportCheck"].recusadas
    assert portoes["RouteExportCheck"].afi == "ipv4"
    assert portoes["RouteExportCheckV6"].afi == "ipv6"
    assert portoes["RouteExportCheck-PARCEIROS"].papel == "parceiro"


def test_o_portao_do_cdn_e_o_que_aceita_a_classe_so_cdn() -> None:
    """§7: a diferença entre o portão do CDN e o do upstream é o `65000:991`."""
    proposta = propor_plano([_leitura("comunidades_vs.txt")], asn_principal=61785)
    portoes = {g.nome: g for g in proposta.plano.portoes}
    assert portoes["RouteExportCheck"].papel == "cdn"


def test_poda_a_sessao_parada() -> None:
    """§9.3: só Established vira alvo; o resto sai na lista de parados."""
    proposta = propor_plano(
        [_leitura("comunidades_vs.txt")],
        asn_principal=61785,
        estados_alvo={"IX-CG": "established", "EQUINIX_SP": "parado"},
    )
    nomes = {a.nome for a in proposta.plano.alvos}
    assert nomes == {"IX-CG"}
    assert proposta.parados == ("EQUINIX_SP",)


def test_divergencia_de_codigo_ambiguo() -> None:
    """§6.2: o código `3` é ERTEL na borda e prepend 3 no VS — a adoção não escolhe."""
    proposta = propor_plano(
        [_leitura("comunidades_edge.txt"), _leitura("comunidades_vs.txt")], asn_principal=61785
    )
    ambiguos = [d for d in proposta.divergencias if d.codigo == "codigo_ambiguo"]
    assert [d.valor for d in ambiguos] == ["3"]


def test_divergencia_do_nome_que_discorda_da_faixa() -> None:
    """§14.2: `com-CUSTOMER-CLIENTE-v4` é `65000:7001`, que a faixa chama de tamanho.

    O par v6 (`7101`) diverge pelo mesmo motivo, e sai também: a divergência é do
    nome contra a faixa, e vale para as duas linhas.
    """
    proposta = propor_plano([_leitura("comunidades_vs.txt")], asn_principal=61785)
    discordam = [d for d in proposta.divergencias if d.codigo == "nome_e_faixa_discordam"]
    assert [d.valor for d in discordam] == [
        "com-CUSTOMER-CLIENTE-v4",
        "com-CUSTOMER-CLIENTE-v6",
    ]


def test_divergencia_de_papel_duvidoso() -> None:
    """§6.3: o `MSD-CDN-v4` tem nome de CDN e o ASN de um trânsito."""
    proposta = propor_plano(
        [_leitura("comunidades_edge.txt")],
        asn_principal=61785,
        papeis_da_sot={53062: "transito"},
        estados_alvo={"MSD-CDN-v4": "established"},
    )
    duvidosos = [d for d in proposta.divergencias if d.codigo == "papel_duvidoso"]
    assert [d.valor for d in duvidosos] == ["MSD-CDN-v4"]
    alvo = next(a for a in proposta.plano.alvos if a.nome == "MSD-CDN-v4")
    assert alvo.papel == "transito"  # a SoT vence o nome (Regra 5)


def test_o_portao_vira_pendencia_quando_nao_da_para_decidir() -> None:
    texto = """
xpl route-filter RouteExportCheck
 if not community matches-any {65000:4001} then
  refuse
 endif
 end-filter
"""
    proposta = propor_plano([parse_communities_vrp(texto)], asn_principal=61785)
    portao = proposta.plano.portoes[0]
    assert portao.papel == "upstream"   # sem a classe "só CDN", o palpite é o portão de trânsito
    assert any(a.codigo == "portao_sem_evidencia" for a in proposta.divergencias)
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run pytest tests/automation/test_community_plan_proposta.py -q
```

Esperado: `ImportError: cannot import name 'propor_plano'`.

- [ ] **Step 3: Escrever a proposta**

Acrescente ao fim de `src/gerenet/automation/community_plan.py`:

```python
@dataclass(frozen=True)
class PropostaPlano:
    plano: PlanoLido
    divergencias: tuple[Achado, ...] = ()
    parados: tuple[str, ...] = ()
    avisos: tuple[str, ...] = ()


@dataclass(frozen=True)
class _EvidenciaDaClasse:
    nome: str
    valor_v4: int | None = None
    valor_v6: int | None = None
    codigo: int | None = None
    banda: str | None = None


# Papel do alvo pelo nome do grupo, quando a SoT não tem o ASN (Regra 5).
_PAPEL_PELO_NOME = (
    ("GGC", "cdn"), ("NFLX", "cdn"), ("NETFLIX", "cdn"), ("OCA", "cdn"), ("CDN", "cdn"),
    ("PARCEIRO", "parceiro"),
    ("PTT", "ix"), ("PEERING", "ix"), ("IX", "ix"),
)

# Palavra do nome da definição → banda que ela sugere. Serve só para achar a
# discordância entre o nome e a faixa (§14.2), não para decidir a banda.
_PALAVRA_DA_BANDA = (
    ("CLIENTES_PARCEIROS", "conjunto"),
    ("CUSTOMER", "cliente"), ("CLIENTE", "cliente"),
    ("PARCEIRO", "parceiro"),
    ("TRANSITO", "transito"),
    ("TAMANHO", "tamanho"),
    ("IX", "local"), ("PTT", "local"),
    ("ONLY-CDN", "especial"), ("TROCA", "especial"),
)


def _banda_da_faixa(valor: int | None) -> str | None:
    """A banda que a faixa do valor declara (§5): é ela que o plano adota."""
    if valor is None:
        return None
    for banda, (minimo, maximo) in FAIXAS.items():
        if minimo <= valor <= maximo:
            return banda
    return None


def _papel_do_nome(nome: str) -> str | None:
    maiusculo = nome.upper()
    for marca, papel in _PAPEL_PELO_NOME:
        if marca in maiusculo:
            return papel
    return None


def _banda_do_nome(nome: str) -> str | None:
    maiusculo = nome.upper()
    for marca, banda in _PALAVRA_DA_BANDA:
        if marca in maiusculo:
            return banda
    return None


def propor_plano(
    leituras: Sequence[LeituraCommunities],
    *,
    asn_principal: int | None = None,
    estados_alvo: Mapping[str, str] | None = None,
    papeis_da_sot: Mapping[int, str] | None = None,
) -> PropostaPlano:
    """Monta o plano que a adoção gravaria, com a poda e as divergências.

    A banda de cada classe vem da **faixa** do valor (§5), não do nome: o nome é
    evidência do operador e a faixa é o contrato. Quando os dois discordam, a
    divergência sai para o operador decidir (§14.2).
    """
    estados_alvo = estados_alvo or {}
    papeis_da_sot = papeis_da_sot or {}
    divergencias: list[Achado] = []
    avisos: list[str] = []

    # 1. As classes: os valores de 2 bytes definidos ou aplicados, um por código.
    evidencias: dict[int, _EvidenciaDaClasse] = {}
    for leitura in leituras:
        avisos.extend(leitura.avisos)
        for definicao in leitura.definicoes:
            if definicao.classe != "community":
                continue
            for valor in definicao.valores:
                codigo = _codigo_do_valor(valor)
                if codigo is None or not _e_valor_de_classe(valor):
                    continue
                registro = evidencias.setdefault(
                    codigo, _EvidenciaDaClasse(nome=definicao.nome, banda=_banda_da_faixa(codigo))
                )
                if definicao.nome.startswith("com-") and not registro.nome.startswith("com-"):
                    registro.nome = definicao.nome  # o nome do vocabulário vence o numerado
    for leitura in leituras:
        for uso in leitura.usos:
            if uso.operacao != "aplica" or uso.valores:
                continue
            for valor in leitura.valores_do_corpus(uso.corpus) if uso.corpus else ():
                codigo = _codigo_do_valor(valor)
                if codigo is None or not _e_valor_de_classe(valor) or codigo in evidencias:
                    continue
                evidencias[codigo] = _EvidenciaDaClasse(
                    nome=f"com-{codigo}", banda=_banda_da_faixa(codigo)
                )

    classes: list[ClassePlano] = []
    # A referência é indexada pelos **dois** códigos do par: `com-TAMANHO-1` é
    # (7001, 7101) e a evidência pode chegar por qualquer um deles. Indexada só
    # por `valor_v4`, o `65000:7101` do `-v6` cairia no ramo sintético e viraria
    # uma segunda classe com um código v6 escrito na coluna v4 — uma linha que a
    # própria checagem 2 reprova depois de adotada.
    conhecidas: dict[int, ClassePlano] = {}
    for classe in VOCABULARIO:
        for valor in (classe.valor_v4, classe.valor_v6):
            if valor is not None:
                conhecidas.setdefault(valor, classe)
    vistas: set[tuple[int | None, int | None]] = set()
    for codigo in sorted(evidencias):
        evidencia = evidencias[codigo]
        da_referencia = conhecidas.get(codigo)
        entrada: ClassePlano | None
        if da_referencia is not None:
            chave = (da_referencia.valor_v4, da_referencia.valor_v6)
            entrada = None if chave in vistas else da_referencia
            vistas.add(chave)  # os dois códigos do par viram uma linha só
        else:
            # Código sem linha na referência (o `8167` do `com-AS8167`): a coluna
            # é a que o dígito declara, e não sempre a v4.
            coluna = "valor_v6" if familia_do_digito(codigo) == "v6" else "valor_v4"
            entrada = ClassePlano(
                nome=evidencia.nome, banda=evidencia.banda, tipo="tag_produto",
                **{coluna: codigo},
            )
        if entrada is not None:
            classes.append(entrada)
        # A divergência é do **nome contra a faixa**, então ela sai por código
        # encontrado, mesmo quando os dois códigos do par já viraram uma classe só.
        banda_do_nome = _banda_do_nome(evidencia.nome)
        if banda_do_nome is not None and banda_do_nome != evidencia.banda:
            divergencias.append(
                Achado(
                    codigo="nome_e_faixa_discordam", severidade="critico",
                    valor=evidencia.nome,
                    descricao=(
                        f"{evidencia.nome} é {codigo}, que a faixa da §5 chama de "
                        f"`{evidencia.banda}`; o nome diz `{banda_do_nome}`"
                    ),
                    acao="decidir qual sentido fica e migrar o outro (§14.2)",
                )
            )

    # 2. As instruções: os códigos de large-community que os filtros usam.
    codigos_vistos: set[int] = set()
    for leitura in leituras:
        for uso in leitura.usos:
            for valor in uso.valores:
                if valor.count(":") == 2:
                    codigo = _codigo_do_valor(valor)
                    if codigo in CODIGOS_CONHECIDOS:
                        codigos_vistos.add(codigo)
    instrucoes = tuple(i for i in VOCABULARIO_INSTRUCOES if i.codigo in codigos_vistos)
    do_codigo: dict[int, list[InstrucaoPlano]] = {}
    for instrucao in VOCABULARIO_INSTRUCOES:
        do_codigo.setdefault(instrucao.codigo or -1, []).append(instrucao)
    for codigo in sorted(codigos_vistos):
        candidatas = do_codigo.get(codigo, [])
        if len(candidatas) > 1:
            divergencias.append(
                Achado(
                    codigo="codigo_ambiguo", severidade="critico", valor=str(codigo),
                    descricao=(
                        f"o código {codigo} é "
                        + " e ".join(f"`{c.nome}`" for c in candidatas)
                        + "; o índice único de `codigo` não deixa as duas linhas existirem"
                    ),
                    acao="decidir qual sentido o código tem neste plano",
                )
            )

    # 3. Os portões: o que cada `RouteExportCheck*` aceita e recusa.
    portoes: list[PortaoPlano] = []
    for leitura in leituras:
        por_filtro: dict[str, list[UsoCommunity]] = {}
        for uso in leitura.usos:
            if uso.operacao == "testa":
                por_filtro.setdefault(uso.filtro, []).append(uso)
        for filtro, testes in por_filtro.items():
            if not filtro.startswith("RouteExportCheck"):
                continue
            aceitas = [v for uso in testes if uso.negado for v in uso.valores]
            recusadas = [v for uso in testes if not uso.negado for v in uso.valores]
            papel, evidencia = _papel_do_portao(filtro, aceitas)
            if evidencia is None:
                divergencias.append(
                    Achado(
                        codigo="portao_sem_evidencia", severidade="atencao", valor=filtro,
                        descricao=f"{filtro}: o nome não diz o papel e a lista de aceitas não decide",
                        acao="confirmar o papel do portão depois da adoção",
                    )
                )
            portoes.append(
                PortaoPlano(
                    nome=filtro, papel=papel, afi="ipv6" if "V6" in filtro.upper() else "ipv4",
                    padrao="recusar",
                    aceitas=tuple(_nome_do_valor(classes, v) for v in aceitas),
                    recusadas=tuple(_nome_do_valor(classes, v) for v in recusadas),
                )
            )

    # 4. Os alvos: grupos de peer, com a poda de sessão parada (§9.3).
    alvos: list[AlvoPlano] = []
    parados: list[str] = []
    for leitura in leituras:
        for alvo_lido in leitura.alvos:
            estado = estados_alvo.get(alvo_lido.nome, "ausente")
            if estado != "established":
                parados.append(alvo_lido.nome)
                continue
            da_sot = papeis_da_sot.get(alvo_lido.asn or -1)
            do_nome = _papel_do_nome(alvo_lido.nome)
            papel = da_sot or do_nome or "transito"
            if da_sot is not None and do_nome is not None and da_sot != do_nome:
                divergencias.append(
                    Achado(
                        codigo="papel_duvidoso", severidade="atencao", valor=alvo_lido.nome,
                        descricao=(
                            f"{alvo_lido.nome}: a SoT diz `{da_sot}` (AS{alvo_lido.asn}) e o "
                            f"nome do grupo diz `{do_nome}`"
                        ),
                        acao="confirmar o papel do alvo (§6.3)",
                    )
                )
            alvos.append(
                AlvoPlano(
                    nome=alvo_lido.nome, papel=papel,
                    codigo_v4=alvo_lido.asn, codigo_v6=alvo_lido.asn,
                    gate_nome=_portao_do_papel(portoes, papel),
                    classe_import=_classe_da_importacao(papel, classes),
                    parametros=_parametros_do_alvo(leituras, alvo_lido.nome),
                )
            )

    regras = _regras_de_importacao(classes)
    plano = PlanoLido(
        asn_principal=asn_principal,
        asns_anunciados=({"asn": asn_principal, "papel": "principal"},) if asn_principal else (),
        classes=tuple(classes), instrucoes=instrucoes, portoes=tuple(portoes), alvos=tuple(alvos),
        regras_import=regras,
    )
    return PropostaPlano(
        plano=plano, divergencias=tuple(divergencias), parados=tuple(sorted(set(parados))),
        avisos=tuple(avisos),
    )
```

E os quatro auxiliares que a proposta usa:

```python
def _nome_do_valor(classes: Sequence[ClassePlano], valor: str) -> str:
    """O nome de um valor: as classes da proposta primeiro, o vocabulário depois.

    O portão testa valor que pode não ser classe de ninguém — o `65000:991` da
    borda não é classe de linha nenhuma. Sem a segunda passada, o rótulo sairia
    como o literal e o operador leria `65000:991` onde o §7 diz `com-ONLY-CDN`.
    """
    codigo = _codigo_do_valor(valor)
    for classe in (*classes, *VOCABULARIO):
        if codigo in (classe.valor_v4, classe.valor_v6):
            return classe.nome
    return valor


# O código de `com-ONLY-CDN` (§6.1), lido da própria referência para os dois não
# saírem de sincronia.
_CODIGO_ONLY_CDN = next(c.valor_v4 for c in VOCABULARIO if c.nome == "com-ONLY-CDN")


def _papel_do_portao(filtro: str, aceitas: Sequence[str]) -> tuple[str, str | None]:
    """O papel do portão (Regra 6): o nome decide o óbvio, o que ele aceita decide o resto.

    `com-ONLY-CDN` é a classe "só CDN": o portão que a aceita é o portão do CDN,
    e é essa a diferença entre ele e o portão do upstream (§7) — a mesma classe
    passa no CDN e é recusada no upstream. Sem nenhuma das duas evidências o
    papel sai como `upstream` **com pendência**: palpite declarado se revisa,
    palpite silencioso não.
    """
    if "PARCEIROS" in filtro.upper():
        return "parceiro", "nome"
    if _CODIGO_ONLY_CDN in {_codigo_do_valor(valor) for valor in aceitas}:
        return "cdn", "aceitas"
    return "upstream", None


def _portao_do_papel(portoes: Sequence[PortaoPlano], papel: str) -> str | None:
    for portao in portoes:
        if portao.papel == papel and portao.afi == "ipv4":
            return portao.nome
    return portoes[0].nome if portoes else None


def _classe_da_importacao(papel: str, classes: Sequence[ClassePlano]) -> str | None:
    """§7: o cliente recebe a classe do cliente, o parceiro a do parceiro."""
    da_banda = {"cliente": "cliente", "parceiro": "parceiro"}.get(papel)
    if da_banda is None:
        return None
    for classe in classes:
        if classe.banda == da_banda:
            return classe.nome
    return None


def _parametros_do_alvo(leituras: Sequence[LeituraCommunities], nome: str) -> dict:
    """O que é específico do alvo: as exceções por prefixo (§6.3, §8.1).

    O filtro de CDN guarda um bloco de exceção (`100.64.0.0 10 le 24` levando a
    community da própria CDN) que é parâmetro do alvo, não classe do plano.
    """
    excecoes: list[dict] = []
    for leitura in leituras:
        for uso in leitura.usos:
            if uso.operacao != "aplica" or not uso.condicao or "route-destination" not in uso.condicao:
                continue
            excecoes.append({"condicao": uso.condicao, "communities": list(uso.valores)})
    return {"excecoes": excecoes} if excecoes else {}


def _regras_de_importacao(classes: Sequence[ClassePlano]) -> tuple[RegraImportPlano, ...]:
    """§4.5/§7: um papel por classe, com a condição que a produção usa."""
    regras: list[RegraImportPlano] = []
    for papel in ("cliente", "parceiro", "transito"):
        classe = next((c for c in classes if c.banda == papel), None)
        if classe is None:
            continue
        regras.append(
            RegraImportPlano(
                papel=papel, afi="ipv4", classe=classe.nome,
                condicao={"tamanho_max": 23} if papel == "cliente" else {},
            )
        )
    return tuple(regras)
```

O método `valores_do_corpus` que a proposta usa veio na Task 3 (`LeituraCommunities`).

- [ ] **Step 4: Rodar e ver passar**

```bash
uv run pytest tests/automation -q
uv run ruff check src tests
```

Esperado: verde.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/community_plan.py src/gerenet/automation/parsers/huawei_vrp/communities_vrp.py tests/automation
git commit -m "feat(communities): a proposta de adoção com poda e divergências"
```

---

### Task 6: O serviço — ler, validar e adotar

A escrita é **uma transação só** com auditoria, no formato do `adotar_proposta` da descoberta: qualquer recusa desfaz tudo, não existe adoção parcial. A leitura devolve o mesmo `PlanoLido` que a proposta produz, e é por isso que a validação roda igual antes e depois de adotar.

**Files:**
- Create: `src/gerenet/domain/services/community_plan.py`
- Test: `tests/domain/test_community_plan_service.py`

**Interfaces:**
- Consumes: `PlanoLido`, `propor_plano`, `validar`, `Achado` (Tasks 4-5); `_snapshot_com_config` (`automation/discovery.py`); `texto_backup`; `registrar`.
- Produces: `obter_plano(session) -> PlanoLido | None`, `propor_adocao(session, device_id) -> PropostaPlano`, `leituras_do_plano(session, device_ids) -> dict[int, LeituraCommunities]`, `validar_plano(session, device_ids=None) -> tuple[Achado, ...]`, `adotar_plano(session, proposta, *, device_id, snapshot_id, actor) -> models.CommunityPlan`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/domain/test_community_plan_service.py`:

```python
"""A adoção do plano (spec §9): transação única, idempotência e auditoria."""
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.automation.snapshots import texto_backup
from gerenet.domain import models
from gerenet.domain.services.community_plan import (
    adotar_plano,
    obter_plano,
    propor_adocao,
    validar_plano,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.schemas import DeviceCreate

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _device_com_snapshot(db_session, nome: str, fixture: str) -> models.Device:
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.9", asn=61785), actor="teste"
    )
    db_session.add(
        models.DeviceSnapshot(
            device_id=device.id, status="success",
            raw_files={"config_backup": [(FIXTURES / fixture).read_text()]},
        )
    )
    db_session.commit()
    return device


def test_propoe_a_partir_do_snapshot_coletado(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-01", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    assert proposta.plano.asn_principal == 61785
    assert {c.nome for c in proposta.plano.classes} >= {"com-TRANSITO-FULL", "com-CLIENTES_PARCEIROS-CDN"}
    assert db_session.scalar(select(models.CommunityPlan)) is None  # propor não escreve


def test_adota_numa_transacao_e_audita(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-02", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    plano = adotar_plano(
        db_session, proposta, device_id=device.id, snapshot_id=proposta.plano.snapshot_id, actor="ana"
    )
    db_session.commit()

    assert plano.asn_principal == 61785
    assert plano.origem == "adotado"
    assert db_session.scalar(select(models.CommunityPlan).where(models.CommunityPlan.admin_status)) is not None
    classe = db_session.scalar(select(models.Community).where(models.Community.valor_v4 == 1010))
    assert classe is not None and classe.banda == "transito" and classe.origem == "adotado"
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    )
    assert evento is not None and evento.actor == "ana"


def test_adotar_duas_vezes_nao_duplica(db_session) -> None:
    """§13: idempotência — o mesmo snapshot adotado duas vezes não muda nada."""
    device = _device_com_snapshot(db_session, "ne-plano-03", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    ).all()

    proposta_de_novo = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta_de_novo, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    assert len(db_session.scalars(select(models.CommunityPlan)).all()) == 1
    assert len(db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    ).all()) == len(eventos)  # sem transição, sem evento (ruling 5)
    assert len(db_session.scalars(
        select(models.Community).where(models.Community.name == "com-TRANSITO-FULL")
    ).all()) == 1


def test_a_validacao_roda_sobre_o_plano_adotado(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-04", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    achados = validar_plano(db_session, [device.id])
    assert obter_plano(db_session) is not None
    assert any(a.codigo == "classe_aplicada_nao_testada" and a.valor == "61785:3001" for a in achados)
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run pytest tests/domain/test_community_plan_service.py -q
```

Esperado: `ModuleNotFoundError: No module named 'gerenet.domain.services.community_plan'`.

- [ ] **Step 3: Escrever o serviço**

`src/gerenet/domain/services/community_plan.py`:

```python
"""O plano de communities na SoT: ler, propor, validar e adotar (spec §9).

A escrita é uma transação só, como a adoção de peer da descoberta: o plano é um
objeto coerente e uma adoção pela metade deixaria classes sem portão. Qualquer
recusa desfaz tudo. Nada aqui vai ao equipamento — o único caminho é o snapshot
já coletado, e mudar o roteador continua sendo change request.
"""
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gerenet.automation.community_plan import (
    Achado,
    AlvoPlano,
    ClassePlano,
    InstrucaoPlano,
    PlanoLido,
    PortaoPlano,
    PropostaPlano,
    RegraImportPlano,
    propor_plano,
    validar,
)
from gerenet.automation.discovery import _snapshot_com_config
from gerenet.automation.parsers.huawei_vrp.communities_vrp import (
    LeituraCommunities,
    parse_communities_vrp,
)
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import NotFoundError, ValidationError


def _leitura_do_device(session: Session, device_id: int) -> LeituraCommunities | None:
    snap, texto = _snapshot_com_config(session, device_id)
    if snap is None or not texto.strip():
        return None
    leitura = parse_communities_vrp(texto)
    return leitura


def ler_do_snapshot(session: Session, device_id: int) -> LeituraCommunities:
    """A leitura da configuração coletada de um equipamento (somente leitura)."""
    leitura = _leitura_do_device(session, device_id)
    if leitura is None:
        raise NotFoundError(
            f"Equipamento {device_id} não tem coleta com a configuração salva. "
            "Colete antes de ler o plano."
        )
    return leitura


def direcoes_do_device(session: Session, device_id: int) -> dict[str, str]:
    """O mapa filtro → direção, do vínculo real da sessão (Regra 4 do plano)."""
    direcoes: dict[str, str] = {}
    sessoes = session.scalars(
        select(models.BgpSession).where(models.BgpSession.device_id == device_id)
    ).all()
    for sessao in sessoes:
        if sessao.import_route_policy:
            direcoes.setdefault(sessao.import_route_policy, "import")
        if sessao.export_route_policy:
            direcoes.setdefault(sessao.export_route_policy, "export")
    return direcoes


def _peers_dos_snapshots(
    session: Session, device_ids: Sequence[int]
) -> dict[str, str]:
    """Endereço do peer → estado, da coleta mais recente de cada equipamento.

    O estado é do **equipamento**, não da SoT: a SoT guarda a intenção, e um
    `bgp_sessions` sem `shutdown` não é um peer de pé (§3). O recurso `bgp_peers`
    é o que tem o estado real, com uma linha por peer e família
    (`{afi, peer, asn, estado, pref_rcv, up_down}` — o `merge_bgp_peers`).
    """
    consulta = (
        select(models.DeviceSnapshot)
        .order_by(models.DeviceSnapshot.id.desc())
    )
    if device_ids:
        consulta = consulta.where(models.DeviceSnapshot.device_id.in_(list(device_ids)))
    vistos: set[int] = set()
    estados: dict[str, str] = {}
    for snap in session.scalars(consulta):
        if snap.device_id in vistos:
            continue
        linhas = (snap.resources or {}).get("bgp_peers")
        if not linhas:
            continue  # coleta sem a tabela de peers: a anterior ainda pode ter
        vistos.add(snap.device_id)
        for linha in linhas:
            endereco = linha.get("peer")
            if endereco:
                # `setdefault` pelo mesmo motivo do merge: a v4 vem antes da v6,
                # e o alvo de pé em qualquer uma das duas está de pé.
                estados.setdefault(endereco, linha.get("estado") or "ausente")
    return estados


def estados_dos_alvos(
    session: Session,
    leituras: Sequence[LeituraCommunities],
    device_ids: Sequence[int] = (),
) -> dict[str, str]:
    """O estado de cada alvo do plano, para a poda (§9.3) e a checagem 7 (§8).

    O alvo é um **grupo** de `peer` da configuração (`peer MSD-CDN-v4 as-number
    53062`) e o estado está por endereço, então o nome vira endereço pelos
    membros que o próprio leitor achou (`peer 45.227.2.253 group IX-CG`). Basta
    um membro Established para o alvo estar de pé; sem nenhum membro conhecido o
    alvo **não** entra no mapa, e a checagem 7 o trata como `ausente` — que é o
    que ele é para esta leitura.
    """
    coletados = _peers_dos_snapshots(session, device_ids)
    estados: dict[str, str] = {}
    for leitura in leituras:
        for alvo in leitura.alvos:
            vistos = [coletados[m] for m in alvo.membros if m in coletados]
            if not vistos:
                continue
            de_pe = next((e for e in vistos if e.lower().startswith("estab")), None)
            estados[alvo.nome] = "established" if de_pe else vistos[0]
    return estados


def papeis_da_sot(session: Session) -> dict[int, str]:
    """ASN da organização → tipo do upstream, para o papel do alvo (Regra 5)."""
    papeis: dict[int, str] = {}
    linhas = session.execute(
        select(models.Organization.asn, models.Upstream.tipo)
        .join(models.Upstream, models.Upstream.organization_id == models.Organization.id)
    ).all()
    for asn, tipo in linhas:
        if asn is not None:
            papeis[int(asn)] = tipo
    return papeis


def obter_plano(session: Session) -> PlanoLido | None:
    """O plano ativo da SoT, no mesmo formato que a proposta produz."""
    plano = session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.admin_status.is_(True))
    )
    if plano is None:
        return None
    # Um só dicionário por id, com as classes **e** as instruções: as duas
    # partilham a tabela (`codigo` nulo é classe, preenchido é instrução) e o
    # `nome_por_id` daí sai — é ele que traduz `classe_import_id` e `classe_id`
    # de volta para o nome que a leitura usa.
    por_id = {c.id: c for c in session.scalars(select(models.Community))}
    nome_por_id = {c.id: c.name for c in por_id.values()}

    def _nomes(ids) -> tuple[str, ...]:
        return tuple(nome_por_id.get(i, str(i)) for i in (ids or ()))

    return PlanoLido(
        asn_principal=plano.asn_principal,
        asns_anunciados=tuple(plano.asns_anunciados or ()),
        classes=tuple(
            ClassePlano(nome=c.name, banda=c.banda, tipo=c.tipo, valor_v4=c.valor_v4,
                        valor_v6=c.valor_v6, id=c.id, notas=c.notes)
            for c in por_id.values() if c.codigo is None
        ),
        instrucoes=tuple(
            InstrucaoPlano(nome=c.name, codigo=c.codigo, tipo=c.tipo, id=c.id, notas=c.notes)
            for c in por_id.values() if c.codigo is not None
        ),
        portoes=tuple(
            PortaoPlano(nome=g.nome, papel=g.papel, afi=g.afi, padrao=g.padrao,
                        aceitas=_nomes(g.aceitas), recusadas=_nomes(g.recusadas), id=g.id)
            for g in session.scalars(select(models.CommunityGate))
        ),
        alvos=tuple(
            AlvoPlano(nome=t.nome, papel=t.papel, codigo_v4=t.codigo_v4, codigo_v6=t.codigo_v6,
                      gate_nome=t.gate_nome, classe_import=nome_por_id.get(t.classe_import_id),
                      upstream_id=t.upstream_id, organization_id=t.organization_id,
                      parametros=t.parametros or {}, id=t.id)
            for t in session.scalars(select(models.CommunityTarget))
        ),
        regras_import=tuple(
            RegraImportPlano(papel=r.papel, afi=r.afi, classe=nome_por_id.get(r.classe_id, ""),
                             condicao=r.condicao or {}, notas=r.notas)
            for r in session.scalars(select(models.CommunityImportRule))
        ),
        snapshot_id=plano.origem_snapshot_id,
        observacoes=plano.observacoes,
    )


def propor_adocao(session: Session, device_id: int) -> PropostaPlano:
    """O que a adoção gravaria, lido do snapshot — sem escrever nada."""
    snap, texto = _snapshot_com_config(session, device_id)
    if snap is None or not texto.strip():
        raise NotFoundError(
            f"Equipamento {device_id} não tem coleta com a configuração salva. "
            "Colete antes de adotar o plano."
        )
    leitura = parse_communities_vrp(texto)
    proposta = propor_plano(
        [leitura],
        asn_principal=leitura.asn_local or _asn_do_equipamento(session, device_id),
        estados_alvo=estados_dos_alvos(session, [leitura], [device_id]),
        papeis_da_sot=papeis_da_sot(session),
    )
    return PropostaPlano(
        plano=PlanoLido(**{**proposta.plano.__dict__, "snapshot_id": snap.id}),
        divergencias=proposta.divergencias, parados=proposta.parados, avisos=proposta.avisos,
    )


def _asn_do_equipamento(session: Session, device_id: int) -> int | None:
    device = session.get(models.Device, device_id)
    return device.asn if device is not None else None


def validar_plano(session: Session, device_ids: list[int] | None = None) -> tuple[Achado, ...]:
    """As oito checagens sobre o plano ativo e a configuração coletada.

    Sem `device_ids`, valida contra todos os equipamentos que têm coleta — é o
    que a página mostra, porque a comparação que importa é entre a borda e o VS.
    """
    plano = obter_plano(session)
    if plano is None:
        return ()
    if device_ids is None:
        device_ids = list(session.scalars(
            select(models.DeviceSnapshot.device_id).distinct()
        ).all())
    leituras: list[LeituraCommunities] = []
    direcoes: dict[str, str] = {}
    for device_id in device_ids:
        leitura = _leitura_do_device(session, device_id)
        if leitura is None:
            continue
        leituras.append(leitura)
        direcoes.update(direcoes_do_device(session, device_id))
    return validar(
        plano, leituras, direcoes=direcoes,
        estados_alvo=estados_dos_alvos(session, leituras, device_ids),
    )
```

- [ ] **Step 4: Escrever a adoção (a transação única)**

No mesmo arquivo:

```python
def _resolve_classes(
    session: Session, classes: tuple[ClassePlano, ...], *, snapshot_id: int | None, actor: str
) -> dict[str, int]:
    """Cria as classes que faltam e devolve nome → id.

    A busca é pelo valor (namespace-agnóstico), como a do motor: `61785:3001` e
    `65000:3001` são a mesma classe (Regra 1). Nome já existente é reaproveitado.
    """
    ids: dict[str, int] = {}
    for classe in classes:
        existente = session.scalar(
            select(models.Community).where(models.Community.name == classe.nome)
        )
        for campo, valor in (("valor_v4", classe.valor_v4), ("valor_v6", classe.valor_v6)):
            if existente is None and valor is not None:
                existente = session.scalar(
                    select(models.Community).where(
                        getattr(models.Community, campo) == valor
                    )
                )
        if existente is not None:
            ids[classe.nome] = existente.id
            continue
        nova = models.Community(
            name=classe.nome, tipo=classe.tipo, banda=classe.banda, valor_v4=classe.valor_v4,
            valor_v6=classe.valor_v6, notes=classe.notas, origem="adotado",
            origem_snapshot_id=snapshot_id,
        )
        session.add(nova)
        session.flush()
        ids[classe.nome] = nova.id
    return ids


def adotar_plano(
    session: Session,
    proposta: PropostaPlano,
    *,
    device_id: int,
    snapshot_id: int | None,
    actor: str,
) -> models.CommunityPlan:
    """Grava o plano numa transação só, com auditoria. Idempotente.

    Adotar duas vezes o mesmo plano não cria linha nova nem evento novo: o
    segundo `POST` devolve o plano que já está lá (ruling 5 do repositório, o
    mesmo do `disable_community`).
    """
    existente = session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.admin_status.is_(True))
    )
    if existente is not None and existente.asn_principal == proposta.plano.asn_principal:
        # Mesmo ASN principal: o plano é o mesmo; nada a transicionar, nada a auditar.
        return existente

    ids = _resolve_classes(
        session, proposta.plano.classes, snapshot_id=snapshot_id, actor=actor
    )
    ids_instrucoes = _resolve_instrucoes(
        session, proposta.plano.instrucoes, snapshot_id=snapshot_id
    )
    if existente is not None:
        existente.admin_status = False  # uma linha ativa (§4.2)
        session.flush()

    plano = models.CommunityPlan(
        asn_principal=proposta.plano.asn_principal,
        asns_anunciados=[dict(a) for a in proposta.plano.asns_anunciados],
        origem="adotado", origem_snapshot_id=snapshot_id,
        observacoes=f"adotado da coleta do equipamento {device_id}",
    )
    session.add(plano)
    session.flush()

    for portao in proposta.plano.portoes:
        session.add(
            models.CommunityGate(
                nome=portao.nome, papel=portao.papel, afi=portao.afi, padrao=portao.padrao,
                aceitas=[ids[n] for n in portao.aceitas if n in ids],
                recusadas=[ids[n] for n in portao.recusadas if n in ids],
                origem="adotado", origem_snapshot_id=snapshot_id,
            )
        )
    for alvo in proposta.plano.alvos:
        session.add(
            models.CommunityTarget(
                nome=alvo.nome, papel=alvo.papel, codigo_v4=alvo.codigo_v4,
                codigo_v6=alvo.codigo_v6, gate_nome=alvo.gate_nome,
                classe_import_id=ids.get(alvo.classe_import or ""),
                parametros=alvo.parametros or None,
                origem="adotado", origem_snapshot_id=snapshot_id,
            )
        )
    for regra in proposta.plano.regras_import:
        if regra.classe not in ids:
            raise ValidationError(
                f"A regra de importação do papel `{regra.papel}` aponta para a classe "
                f"`{regra.classe}`, que não está na proposta."
            )
        session.add(
            models.CommunityImportRule(
                papel=regra.papel, afi=regra.afi, classe_id=ids[regra.classe],
                condicao=regra.condicao, notas=regra.notas,
                origem="adotado", origem_snapshot_id=snapshot_id,
            )
        )

    registrar(
        session, tipo="community_plan.adopt", ator=actor, objeto="community_plan",
        objeto_id=plano.id, antes=None,
        depois={
            "asn_principal": plano.asn_principal,
            "device_id": device_id, "snapshot_id": snapshot_id,
            "classes": len(proposta.plano.classes),
            "instrucoes": len(ids_instrucoes),
            "portoes": len(proposta.plano.portoes),
            "alvos": [a.nome for a in proposta.plano.alvos],
            "parados": list(proposta.parados),
            "divergencias": [d.codigo for d in proposta.divergencias],
        },
    )
    session.commit()
    session.refresh(plano)
    return plano


def _resolve_instrucoes(
    session: Session, instrucoes: tuple[InstrucaoPlano, ...], *, snapshot_id: int | None
) -> dict[int, int]:
    """Cria as instruções que faltam e devolve código → id."""
    ids: dict[int, int] = {}
    for instrucao in instrucoes:
        existente = session.scalar(
            select(models.Community).where(models.Community.codigo == instrucao.codigo)
        )
        if existente is not None:
            ids[instrucao.codigo] = existente.id
            continue
        nova = models.Community(
            name=instrucao.nome, tipo=instrucao.tipo, banda="instrucao",
            codigo=instrucao.codigo, notes=instrucao.notas, origem="adotado",
            origem_snapshot_id=snapshot_id,
        )
        session.add(nova)
        session.flush()
        ids[instrucao.codigo] = nova.id
    return ids
```

- [ ] **Step 5: Rodar e ver passar**

```bash
uv run pytest tests/domain/test_community_plan_service.py -q
uv run ruff check src tests
```

Esperado: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/community_plan.py tests/domain/test_community_plan_service.py
git commit -m "feat(communities): o serviço do plano, com adoção numa transação só"
```

---

### Task 7: A API

Três rotas em `/api/v1/communities/plan`, com os mesmos códigos de erro da adoção de peer (§13): 404 quando a proposta já não existe, 409 de unicidade, 422 de campo.

**Files:**
- Create: `src/gerenet/api/routers/community_plan.py`
- Modify: `src/gerenet/domain/schemas.py` (schemas do plano + os campos novos de `CommunityOut`)
- Modify: `src/gerenet/api/main.py:53` (registrar depois de `communities.router`)
- Test: `tests/api/test_community_plan_api.py`

**Interfaces:**
- Consumes: `obter_plano`, `propor_adocao`, `validar_plano`, `adotar_plano` (Task 6).
- Produces: `GET /api/v1/communities/plan` → `PlanoOut`; `GET /api/v1/communities/plan/validacao?device_id=` → `list[AchadoOut]`; `POST /api/v1/communities/plan/adopt` (201) → `PlanoAdotadoOut`.

- [ ] **Step 1: Escrever os schemas**

Em `src/gerenet/domain/schemas.py`, os três schemas de community (`schemas.py:561-581`)
passam a ser estes. É edição no lugar, não bloco novo: os campos de hoje ficam, e
os dois comentários de comportamento que já estão lá seguem junto (`tipo` validado
no serviço, e o PATCH puro de `admin_status` que roteia ao disable — Ruling 1):

```python
class CommunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    tipo: str = "padrao"  # validado no serviço contra models.COMMUNITY_TIPO
    notes: str | None = None
    valor_v4: int | None = None
    valor_v6: int | None = None
    codigo: int | None = None
    banda: str | None = None  # validado no serviço contra models.COMMUNITY_BANDA


class CommunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tipo: str
    notes: str | None = None
    admin_status: bool
    valor_v4: int | None = None
    valor_v6: int | None = None
    codigo: int | None = None
    banda: str | None = None
    origem: str = "manual"


class CommunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    tipo: str | None = None  # validado no serviço contra models.COMMUNITY_TIPO
    notes: str | None = None
    valor_v4: int | None = None
    valor_v6: int | None = None
    codigo: int | None = None
    banda: str | None = None
    admin_status: bool | None = None  # PATCH puro {"admin_status": false} roteia ao disable (Ruling 1)
```

E os do plano, ao fim do arquivo:

```python
class ClassePlanoOut(BaseModel):
    nome: str
    banda: str | None = None
    tipo: str
    valor_v4: int | None = None
    valor_v6: int | None = None
    id: int | None = None
    notas: str | None = None
    aplicam: list[str] = []
    testam: list[str] = []


class InstrucaoPlanoOut(BaseModel):
    nome: str
    codigo: int | None = None
    tipo: str
    id: int | None = None
    notas: str | None = None


class PortaoPlanoOut(BaseModel):
    nome: str
    papel: str
    afi: str
    padrao: str
    aceitas: list[str] = []
    recusadas: list[str] = []


class AlvoPlanoOut(BaseModel):
    nome: str
    papel: str
    codigo_v4: int | None = None
    codigo_v6: int | None = None
    gate_nome: str | None = None
    classe_import: str | None = None
    parametros: dict = {}
    estado: str = "ausente"


class AchadoOut(BaseModel):
    codigo: str
    severidade: str
    descricao: str
    valor: str | None = None
    filtro: str | None = None
    linha: int | None = None
    acao: str | None = None


class PlanoOut(BaseModel):
    asn_principal: int | None = None
    asns_anunciados: list[dict] = []
    observacoes: str | None = None
    snapshot_id: int | None = None
    classes: list[ClassePlanoOut] = []
    instrucoes: list[InstrucaoPlanoOut] = []
    portoes: list[PortaoPlanoOut] = []
    alvos: list[AlvoPlanoOut] = []


class AdocaoPlanoIn(BaseModel):
    device_id: int


class PlanoAdotadoOut(BaseModel):
    plano_id: int
    asn_principal: int
    classes: int
    portoes: int
    alvos: int
    divergencias: list[AchadoOut] = []
    parados: list[str] = []
```

- [ ] **Step 2: Escrever o teste que falha**

`tests/api/test_community_plan_api.py`:

```python
"""API do plano de communities (spec §13): consulta, validação e adoção."""
from pathlib import Path

from fastapi.testclient import TestClient

from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _device_com_snapshot(client: TestClient, nome: str, fixture: str) -> int:
    from gerenet.db import SessionLocal

    with SessionLocal() as session:
        device = create_device(
            session, DeviceCreate(name=nome, management_address="10.0.0.8", asn=61785), actor="teste"
        )
        session.add(
            models.DeviceSnapshot(
                device_id=device.id, status="success",
                raw_files={"config_backup": [(FIXTURES / fixture).read_text()]},
            )
        )
        session.commit()
        return device.id


def test_plano_vazio_devolve_200_sem_blocos(client: TestClient) -> None:
    resposta = client.get("/api/v1/communities/plan", headers=_auth())
    assert resposta.status_code == 200
    assert resposta.json()["classes"] == []
    assert resposta.json()["asn_principal"] is None


def test_posso_adotar_e_depois_consultar(client: TestClient) -> None:
    device_id = _device_com_snapshot(client, "ne-api-plano-01", "comunidades_edge.txt")
    adocao = client.post(
        "/api/v1/communities/plan/adopt", json={"device_id": device_id}, headers=_auth()
    )
    assert adocao.status_code == 201
    assert adocao.json()["asn_principal"] == 61785
    assert adocao.json()["classes"] > 0

    consulta = client.get("/api/v1/communities/plan", headers=_auth()).json()
    assert consulta["asn_principal"] == 61785
    nomes = {c["nome"] for c in consulta["classes"]}
    assert "com-TRANSITO-FULL" in nomes


def test_equipamento_sem_coleta_e_404(client: TestClient) -> None:
    from gerenet.db import SessionLocal

    with SessionLocal() as session:
        device = create_device(
            session, DeviceCreate(name="ne-api-plano-02", management_address="10.0.0.7", asn=61785),
            actor="teste",
        )
        device_id = device.id
    resposta = client.post(
        "/api/v1/communities/plan/adopt", json={"device_id": device_id}, headers=_auth()
    )
    assert resposta.status_code == 404


def test_validacao_devolve_os_achados(client: TestClient) -> None:
    device_id = _device_com_snapshot(client, "ne-api-plano-03", "comunidades_edge.txt")
    client.post("/api/v1/communities/plan/adopt", json={"device_id": device_id}, headers=_auth())

    resposta = client.get(
        f"/api/v1/communities/plan/validacao?device_id={device_id}", headers=_auth()
    )
    assert resposta.status_code == 200
    codigos = {a["codigo"] for a in resposta.json()}
    assert "classe_aplicada_nao_testada" in codigos


def test_sem_api_key_e_401(client: TestClient) -> None:
    assert client.get("/api/v1/communities/plan").status_code == 401
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
uv run pytest tests/api/test_community_plan_api.py -q
```

Esperado: 404 nas rotas (o router ainda não existe).

- [ ] **Step 4: Escrever o router**

`src/gerenet/api/routers/community_plan.py`:

```python
"""API do plano de communities (spec §11/§13).

`GET /plan` é a consulta que a página usa; `GET /plan/validacao` compara o plano
com a configuração coletada; `POST /plan/adopt` grava. Nenhuma rota escreve em
equipamento (§3). Os códigos de erro são os da adoção de peer: 404 quando não há
coleta (a proposta já não existe), 409 de unicidade, 422 de campo.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from gerenet.api.deps import require_actor
from gerenet.db import get_session
from gerenet.domain.schemas import AdocaoPlanoIn, AchadoOut, PlanoAdotadoOut, PlanoOut
from gerenet.domain.services import community_plan as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/communities/plan", tags=["communities"], dependencies=[Depends(require_actor)]
)


@router.get("", response_model=PlanoOut)
def consultar_plano(session=Depends(get_session)) -> PlanoOut:
    plano = svc.obter_plano(session)
    if plano is None:
        return PlanoOut()
    return svc.montar_plano_out(session, plano)


@router.get("/validacao", response_model=list[AchadoOut])
def validar(
    device_id: int | None = Query(default=None), session=Depends(get_session)
) -> list[AchadoOut]:
    device_ids = [device_id] if device_id is not None else None
    return [AchadoOut(**a.__dict__) for a in svc.validar_plano(session, device_ids)]


@router.post("/adopt", response_model=PlanoAdotadoOut, status_code=status.HTTP_201_CREATED)
def adotar(payload: AdocaoPlanoIn, session=Depends(get_session), actor: str = Depends(require_actor)):
    try:
        proposta = svc.propor_adocao(session, payload.device_id)
        plano = svc.adotar_plano(
            session, proposta, device_id=payload.device_id,
            snapshot_id=proposta.plano.snapshot_id, actor=actor,
        )
    except NotFoundError as erro:
        raise HTTPException(status_code=404, detail=str(erro)) from erro
    except ConflictError as erro:
        raise HTTPException(status_code=409, detail=str(erro)) from erro
    except ValidationError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    return PlanoAdotadoOut(
        plano_id=plano.id, asn_principal=plano.asn_principal,
        classes=len(proposta.plano.classes), portoes=len(proposta.plano.portoes),
        alvos=len(proposta.plano.alvos),
        divergencias=[AchadoOut(**d.__dict__) for d in proposta.divergencias],
        parados=list(proposta.parados),
    )
```

O `HTTPException` já vem no import do bloco acima. Falta o service: é o
`montar_plano_out`, onde os "quem aplica" e "quem testa" de cada classe entram no
`PlanoOut` (a página mostra os dois por classe, §11). Em
`src/gerenet/domain/services/community_plan.py`:

```python
def montar_plano_out(session: Session, plano: PlanoLido) -> "PlanoOut":
    """O plano com quem aplica e quem testa cada classe (spec §11).

    A contagem sai da leitura da configuração: é a mesma verdade que a validação
    usa, apresentada onde ela é consultada.
    """
    from gerenet.domain.schemas import (
        AlvoPlanoOut, ClassePlanoOut, InstrucaoPlanoOut, PlanoOut, PortaoPlanoOut,
    )

    device_ids = list(session.scalars(select(models.DeviceSnapshot.device_id).distinct()).all())
    aplicam: dict[str, list[str]] = {}
    testam: dict[str, list[str]] = {}
    # As leituras são lidas uma vez e servem às duas pontas: a contagem de quem
    # aplica/testa e o estado dos alvos (que sai dos membros que cada leitura achou).
    leituras = [
        leitura for leitura in (_leitura_do_device(session, i) for i in device_ids) if leitura
    ]
    estados = estados_dos_alvos(session, leituras, device_ids)
    for leitura in leituras:
        for uso in leitura.usos:
            if not uso.valores:
                continue
            for valor in uso.valores:
                if valor.count(":") != 1:
                    continue
                _, _, campo = valor.partition(":")
                if not campo.isdigit():
                    continue  # valor nomeado (`AS-X:FOO`), que não é código de classe
                codigo = int(campo)
                alvo = aplicam if uso.operacao == "aplica" else testam if uso.operacao == "testa" else None
                if alvo is None:
                    continue
                for classe in plano.classes:
                    if codigo in (classe.valor_v4, classe.valor_v6):
                        alvo.setdefault(classe.nome, []).append(uso.filtro)
    return PlanoOut(
        asn_principal=plano.asn_principal,
        asns_anunciados=[dict(a) for a in plano.asns_anunciados],
        observacoes=plano.observacoes, snapshot_id=plano.snapshot_id,
        classes=[
            ClassePlanoOut(
                nome=c.nome, banda=c.banda, tipo=c.tipo, valor_v4=c.valor_v4,
                valor_v6=c.valor_v6, id=c.id, notas=c.notas,
                aplicam=sorted(set(aplicam.get(c.nome, []))),
                testam=sorted(set(testam.get(c.nome, []))),
            )
            for c in plano.classes
        ],
        instrucoes=[InstrucaoPlanoOut(**i.__dict__) for i in plano.instrucoes],
        portoes=[
            PortaoPlanoOut(nome=g.nome, papel=g.papel, afi=g.afi, padrao=g.padrao,
                           aceitas=list(g.aceitas), recusadas=list(g.recusadas))
            for g in plano.portoes
        ],
        alvos=[
            AlvoPlanoOut(nome=a.nome, papel=a.papel, codigo_v4=a.codigo_v4, codigo_v6=a.codigo_v6,
                         gate_nome=a.gate_nome, classe_import=a.classe_import,
                         parametros=a.parametros, estado=estados.get(a.nome, "ausente"))
            for a in plano.alvos
        ],
    )
```

- [ ] **Step 5: Registrar o router e rodar**

Em `src/gerenet/api/main.py`, junto das outras linhas de `include_router`:

```python
    app.include_router(community_plan.router)
```

com o import correspondente (`from gerenet.api.routers import community_plan`) na ordem alfabética dos existentes.

```bash
uv run pytest tests/api -q
uv run ruff check src tests
```

Esperado: verde.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/api/routers/community_plan.py src/gerenet/api/main.py src/gerenet/domain/schemas.py src/gerenet/domain/services/community_plan.py tests/api/test_community_plan_api.py
git commit -m "feat(api): plano de communities, validação e adoção"
```

---

### Task 8: O CLI

`gerenet communities plan show|validar|adotar`, ao lado dos comandos de catálogo que já existem, e as colunas de valor e banda no `communities list`.

**Files:**
- Create: `src/gerenet/cli/community_plan.py`
- Modify: `src/gerenet/cli/communities.py`, `src/gerenet/cli/main.py`
- Test: `tests/cli/test_community_plan_cli.py`

**Interfaces:**
- Consumes: o serviço da Task 6.
- Produces: `python -m gerenet.cli`/`gerenet` com `communities plan`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/cli/test_community_plan_cli.py`:

```python
"""CLI do plano de communities (spec §9): smoke com CliRunner e banco real."""
from pathlib import Path

from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

runner = CliRunner()
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _device(db_session, nome: str, fixture: str) -> int:
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.6", asn=61785), actor="cli"
    )
    db_session.add(
        models.DeviceSnapshot(
            device_id=device.id, status="success",
            raw_files={"config_backup": [(FIXTURES / fixture).read_text()]},
        )
    )
    db_session.commit()
    return device.id


def test_show_sem_plano_avisa(db_session) -> None:
    resultado = runner.invoke(app, ["communities", "plan", "show"])
    assert resultado.exit_code == 0
    assert "Nenhum plano" in resultado.stdout


def test_adotar_e_depois_mostrar(db_session) -> None:
    device_id = _device(db_session, "ne-cli-plano-01", "comunidades_edge.txt")
    adocao = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert adocao.exit_code == 0, adocao.output
    assert "61785" in adocao.stdout

    show = runner.invoke(app, ["communities", "plan", "show"])
    assert show.exit_code == 0
    assert "com-TRANSITO-FULL" in show.stdout


def test_validar_lista_os_achados(db_session) -> None:
    device_id = _device(db_session, "ne-cli-plano-02", "comunidades_edge.txt")
    runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    resultado = runner.invoke(app, ["communities", "plan", "validar", "--device", str(device_id)])
    assert resultado.exit_code == 0
    assert "classe_aplicada_nao_testada" in resultado.stdout


def test_adotar_sem_coleta_sai_com_erro(db_session) -> None:
    device_id = _device_sem_snapshot(db_session, "ne-cli-plano-03")
    resultado = runner.invoke(app, ["communities", "plan", "adotar", str(device_id)])
    assert resultado.exit_code == 1
    assert "coleta" in resultado.stdout.lower() or "coleta" in (resultado.stderr or "").lower()


def _device_sem_snapshot(db_session, nome: str) -> int:
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.5", asn=61785), actor="cli"
    )
    db_session.commit()
    return device.id
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run pytest tests/cli/test_community_plan_cli.py -q
```

Esperado: `exit_code == 2` do Typer ("No such command 'plan'").

- [ ] **Step 3: Escrever o CLI**

`src/gerenet/cli/community_plan.py`:

```python
"""CLI do plano de communities (§11): consultar, validar e adotar.

A adoção lê a configuração já coletada e escreve na SoT. Nada vai ao
equipamento — mudar o roteador continua sendo change request.
"""
import typer
from rich.console import Console
from rich.table import Table

from gerenet.db import get_session
from gerenet.domain.services import community_plan as svc

app = typer.Typer(help="Plano de communities (vocabulário, alvos e portões).")
console = Console()


@app.command("show")
def mostrar() -> None:
    """Mostra o plano ativo da SoT."""
    with get_session() as session:
        plano = svc.obter_plano(session)
        if plano is None:
            console.print("Nenhum plano de communities adotado ainda.")
            raise typer.Exit(code=0)
        console.print(f"ASN principal: {plano.asn_principal}")
        if plano.observacoes:
            console.print(plano.observacoes)
        tabela = Table(title="Classes e instruções")
        for coluna in ("Nome", "Banda", "v4", "v6", "Código", "Quem aplica", "Quem testa"):
            tabela.add_column(coluna)
        for classe in plano.classes:
            tabela.add_row(
                classe.nome, classe.banda or "—", str(classe.valor_v4 or "—"),
                str(classe.valor_v6 or "—"), "—", "", "",
            )
        for instrucao in plano.instrucoes:
            tabela.add_row(
                instrucao.nome, "instrucao", "—", "—", str(instrucao.codigo or "—"), "", ""
            )
        console.print(tabela)
        if plano.alvos:
            alvos = Table(title="Alvos")
            for coluna in ("Nome", "Papel", "Código v4", "Código v6", "Portão"):
                alvos.add_column(coluna)
            for alvo in plano.alvos:
                alvos.add_row(
                    alvo.nome, alvo.papel, str(alvo.codigo_v4 or "—"),
                    str(alvo.codigo_v6 or "—"), alvo.gate_nome or "—",
                )
            console.print(alvos)


@app.command("validar")
def validar(device_id: int = typer.Option(None, "--device", help="Valida contra um equipamento só.")) -> None:
    """Compara o plano com a configuração coletada (as oito checagens da §8)."""
    with get_session() as session:
        achados = svc.validar_plano(session, [device_id] if device_id else None)
        if not achados:
            console.print("Nenhum achado: o plano e a configuração estão alinhados.")
            raise typer.Exit(code=0)
        tabela = Table(title=f"Achados ({len(achados)})")
        for coluna in ("Código", "Severidade", "Valor", "Filtro", "Linha", "O que fazer"):
            tabela.add_column(coluna)
        for achado in achados:
            tabela.add_row(
                achado.codigo, achado.severidade, achado.valor or "—", achado.filtro or "—",
                str(achado.linha or "—"), achado.acao or "—",
            )
        console.print(tabela)
        if any(a.severidade == "critico" for a in achados):
            raise typer.Exit(code=1)


@app.command("adotar")
def adotar(
    device_id: int = typer.Argument(..., help="Equipamento cuja coleta é a origem do plano."),
    actor: str = typer.Option("cli", help="Quem está adotando (vai para a auditoria)."),
) -> None:
    """Adota o plano a partir da configuração já coletada do equipamento."""
    with get_session() as session:
        try:
            proposta = svc.propor_adocao(session, device_id)
            plano = svc.adotar_plano(
                session, proposta, device_id=device_id,
                snapshot_id=proposta.plano.snapshot_id, actor=actor,
            )
        except Exception as erro:  # NotFound/Validation viram mensagem, não traceback
            console.print(f"[red]{erro}[/red]")
            raise typer.Exit(code=1) from erro
        console.print(
            f"Plano adotado (id {plano.id}): ASN {plano.asn_principal}, "
            f"{len(proposta.plano.classes)} classes, {len(proposta.plano.portoes)} portões, "
            f"{len(proposta.plano.alvos)} alvos."
        )
        for divergencia in proposta.divergencias:
            console.print(f"[yellow]divergência[/yellow] {divergencia.codigo}: {divergencia.descricao}")
        if proposta.parados:
            console.print(f"Configurado e parado (fora do plano): {', '.join(proposta.parados)}")
```

- [ ] **Step 4: Registrar e completar o `communities list`**

Em `src/gerenet/cli/communities.py`:

```python
from gerenet.cli.community_plan import app as plan_app

app.add_typer(plan_app, name="plan", help="Plano de communities.")
```

E o comando `list` passa a mostrar valor e banda — no mesmo estilo de linha única que
o arquivo já usa (o CLI deste projeto não tem `rich.Table`; quem tem tabela é o
`community_plan.py` do Step 3):

```python
@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista o catálogo de communities (valor e banda desde o plano central)."""
    with get_session() as session:
        for com in svc.list_communities(session, include_disabled=include_disabled):
            v4 = com.valor_v4 if com.valor_v4 is not None else "—"
            v6 = com.valor_v6 if com.valor_v6 is not None else "—"
            typer.echo(
                f"{com.id:>3}  {com.name:<24} v4={v4} v6={v6} "
                f"{com.banda or '—':<10} {com.notes or ''}"
            )
```

O corpo acima substitui o `def listar` inteiro do arquivo (`src/gerenet/cli/communities.py`,
linhas 13 a 20): era um `typer.echo` com id, nome e notas, e passa a ter as duas
colunas novas no meio.

Em `src/gerenet/cli/main.py` não há nada a mudar: o `plan` entra como sub-Typer de `communities`, que já está registrado.

- [ ] **Step 5: Rodar e ver passar**

```bash
uv run pytest tests/cli -q
uv run ruff check src tests
```

Esperado: verde.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/cli tests/cli/test_community_plan_cli.py
git commit -m "feat(cli): communities plan show, validar e adotar"
```

---

### Task 9: A página `Comunidades · Plano`

Os quatro blocos da §11 na página nova, mais o painel de divergências, e as colunas de valor e banda na página de `Communities` que já existe.

**Files:**
- Create: `web/src/pages/CommunitiesPlan.tsx`, `web/src/pages/CommunitiesPlan.test.tsx`
- Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/pages/Communities.tsx`, `web/src/components/Layout.tsx:33`, `web/src/App.tsx:71`, `web/src/help.ts`

**Interfaces:**
- Consumes: `GET /api/v1/communities/plan`, `GET /api/v1/communities/plan/validacao`.
- Produces: rota `/communities/plan`, item de nav `Comunidades · Plano` no grupo Roteamento.

- [ ] **Step 1: Tipos e hooks**

Em `web/src/api/types.ts`, acrescente `valor_v4`, `valor_v6`, `codigo`, `banda` e `origem` a `CommunityOut` (`origem: "manual" | "adotado"`) e `valor_v4`/`valor_v6`/`codigo`/`banda` a `CommunityCreateIn`/`CommunityUpdateIn`. Depois:

```ts
export interface ClassePlanoOut {
  nome: string;
  banda: string | null;
  tipo: string;
  valor_v4: number | null;
  valor_v6: number | null;
  id: number | null;
  notas: string | null;
  aplicam: string[];
  testam: string[];
}

export interface InstrucaoPlanoOut {
  nome: string;
  codigo: number | null;
  tipo: string;
  id: number | null;
  notas: string | null;
}

export interface PortaoPlanoOut {
  nome: string;
  papel: string;
  afi: string;
  padrao: string;
  aceitas: string[];
  recusadas: string[];
}

export interface AlvoPlanoOut {
  nome: string;
  papel: string;
  codigo_v4: number | null;
  codigo_v6: number | null;
  gate_nome: string | null;
  classe_import: string | null;
  parametros: Record<string, unknown>;
  estado: string;
}

export interface AchadoOut {
  codigo: string;
  severidade: "critico" | "atencao" | "informativo";
  descricao: string;
  valor: string | null;
  filtro: string | null;
  linha: number | null;
  acao: string | null;
}

export interface PlanoOut {
  asn_principal: number | null;
  asns_anunciados: Record<string, unknown>[];
  observacoes: string | null;
  snapshot_id: number | null;
  classes: ClassePlanoOut[];
  instrucoes: InstrucaoPlanoOut[];
  portoes: PortaoPlanoOut[];
  alvos: AlvoPlanoOut[];
}
```

Em `web/src/api/hooks.ts`, junto dos hooks de community. Os dois usam `useQuery`
direto (como o `useDashboard`, `hooks.ts:89`) e não o `useLista`: o `GET /plan`
devolve **um objeto**, e o `useLista` é tipado `apiFetch<T[]>` (`hooks.ts:109`) —
só serve a listas. A validação é lista, mas pede `useQuery` também, porque o
`useLista` monta a queryKey sem o `device_id` e dois equipamentos dividiriam a
mesma entrada de cache:

```ts
export function usePlano() {
  return useQuery({
    queryKey: ["communities-plan"],
    queryFn: () => apiFetch<PlanoOut>("/api/v1/communities/plan"),
  });
}

export function usePlanoValidacao(deviceId?: number) {
  return useQuery({
    queryKey: ["communities-plan-validacao", deviceId ?? null],
    queryFn: () =>
      apiFetch<AchadoOut[]>(
        `/api/v1/communities/plan/validacao${deviceId ? `?device_id=${deviceId}` : ""}`,
      ),
  });
}
```

Acrescente `AchadoOut`, `ClassePlanoOut`, `InstrucaoPlanoOut`, `AlvoPlanoOut`,
`PlanoOut` e `PortaoPlanoOut` à lista de tipos importados de `./types`
(`hooks.ts:3-53`, em ordem alfabética como está lá).

- [ ] **Step 2: Escrever o teste que falha**

`web/src/pages/CommunitiesPlan.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import CommunitiesPlan from "./CommunitiesPlan";
import { AuthProvider } from "@/auth/auth-context";

const PLANO = {
  asn_principal: 61785,
  asns_anunciados: [{ asn: 61785, papel: "principal" }],
  observacoes: "adotado da coleta do equipamento 1",
  snapshot_id: 7,
  classes: [
    {
      nome: "com-TECMAIS-v4", banda: "cliente", tipo: "tag_produto",
      valor_v4: 3001, valor_v6: 3101, id: 3, notas: null,
      aplicam: ["CUSTOMER-BGP-v4"], testam: ["RouteExportCheck"],
    },
    {
      nome: "com-TRANSITO-FULL", banda: "transito", tipo: "tag_produto",
      valor_v4: 1010, valor_v6: 1010, id: 4, notas: null,
      aplicam: ["ASN6762-V4-IMPORT"], testam: [],
    },
  ],
  instrucoes: [{ nome: "com-BLACKHOLE-DENY", codigo: 666, tipo: "acao_blackhole", id: 9, notas: null }],
  portoes: [
    { nome: "RouteExportCheck", papel: "upstream", afi: "ipv4", padrao: "recusar", aceitas: ["com-TECMAIS-v4"], recusadas: ["com-ONLY-CDN"] },
  ],
  alvos: [
    { nome: "MSD-CDN-v4", papel: "transito", codigo_v4: 53062, codigo_v6: 53062, gate_nome: "RouteExportCheck", classe_import: null, parametros: {}, estado: "established" },
  ],
};

const ACHADOS = [
  {
    codigo: "classe_aplicada_nao_testada", severidade: "critico",
    descricao: "61785:3001 (com-TECMAIS-v4) é aplicado e nenhum portão o testa",
    valor: "61785:3001", filtro: "CUSTOMER-BGP-v4", linha: 4586,
    acao: "incluir a classe no portão do papel",
  },
];

function renderPlano() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AuthProvider>
          <CommunitiesPlan />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Comunidades · Plano", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const json = (corpo: unknown) =>
          new Response(JSON.stringify(corpo), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        // `auth/me` responde o usuário, como nos outros testes de página: o
        // `AuthProvider` chama esse caminho na montagem e sem esta linha ele
        // receberia o plano no lugar do usuário.
        if (url === "/api/v1/auth/me")
          return json({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" });
        if (url.startsWith("/api/v1/communities/plan/validacao")) return json(ACHADOS);
        if (url === "/api/v1/communities/plan") return json(PLANO);
        return new Response("null", { status: 404 });
      }),
    );
  });

  it("mostra o cabeçalho com o ASN principal", async () => {
    renderPlano();
    const cabecalho = await screen.findByRole("region", { name: /cabeçalho/i });
    expect(cabecalho.textContent).toContain("ASN principal");
    expect(cabecalho.textContent).toContain("61785");
  });

  it("marca a classe aplicada e não testada", async () => {
    renderPlano();
    // A classe aparece duas vezes na página (tabela de classes e matriz), então
    // a busca é dentro da seção: `getByText` solto acharia as duas e estouraria.
    const secao = await screen.findByRole("region", { name: /classes e instruções/i });
    const linha = within(secao).getByText("com-TRANSITO-FULL").closest("tr");
    expect(linha?.textContent).toContain("não testada");
  });

  it("mostra o painel de divergências com o filtro e a linha", async () => {
    renderPlano();
    // `CUSTOMER-BGP-v4` também é o "quem aplica" de `com-TECMAIS-v4` na tabela
    // de classes — daí a busca ser dentro do painel.
    const painel = await screen.findByRole("region", { name: /divergências/i });
    expect(painel.textContent).toContain("é aplicado e nenhum portão o testa");
    expect(within(painel).getByText("CUSTOMER-BGP-v4")).toBeInTheDocument();
    expect(within(painel).getByText("4586")).toBeInTheDocument();
  });

  it("mostra a matriz classe × papel", async () => {
    renderPlano();
    const matriz = await screen.findByRole("table", { name: /matriz/i });
    expect(within(matriz).getByText("upstream")).toBeInTheDocument();
    // Na linha de `com-TECMAIS-v4` o portão de upstream a aceita; nas outras
    // três células da linha não há portão nenhum daquele papel.
    const linha = within(matriz)
      .getAllByRole("row")
      .find((l) => l.textContent?.startsWith("com-TECMAIS-v4"));
    expect(linha?.textContent).toContain("anunciada");
    expect(linha?.textContent?.match(/não mencionada/g)).toHaveLength(3);
  });
});
```

O `within` vem do `@testing-library/react`, junto do `render`/`screen`. Nenhum
`waitFor` no arquivo: os `findBy*` já esperam a resposta do stub.

As três seções consultadas existem porque o JSX do passo 4 as marca com
`aria-labelledby` apontando para o `h2` de cada uma (`<section>` com nome
acessível vira `role="region"`); a matriz tem `aria-label` próprio.

- [ ] **Step 3: Rodar e ver falhar**

```bash
cd web && npm run test -- CommunitiesPlan
```

Esperado: falha por `Cannot find module './CommunitiesPlan'`.

- [ ] **Step 4: Escrever a página**

`web/src/pages/CommunitiesPlan.tsx`, com os quatro blocos da §11 + o painel:

```tsx
import { useMemo } from "react";
import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { usePlano, usePlanoValidacao } from "@/api/hooks";
import { ApiError } from "@/api/client";
import type { AchadoOut, ClassePlanoOut } from "@/api/types";

const PAPEIS = ["upstream", "cdn", "parceiro", "ix"] as const;

const SEVERIDADE_ORDEM: Record<string, number> = { critico: 0, atencao: 1, informativo: 2 };

function celulaDaMatriz(classe: ClassePlanoOut, papel: string, portoes: { papel: string; aceitas: string[]; recusadas: string[] }[]) {
  const doPapel = portoes.filter((p) => p.papel === papel);
  if (doPapel.some((p) => p.aceitas.includes(classe.nome))) return "anunciada";
  if (doPapel.some((p) => p.recusadas.includes(classe.nome))) return "recusada";
  return "não mencionada";
}

export default function CommunitiesPlan() {
  const plano = usePlano();
  const validacao = usePlanoValidacao();
  const dados = plano.data;
  const achados = useMemo(
    () => [...(validacao.data ?? [])].sort((a, b) => (SEVERIDADE_ORDEM[a.severidade] ?? 9) - (SEVERIDADE_ORDEM[b.severidade] ?? 9)),
    [validacao.data],
  );

  if (plano.isLoading) return <main><p aria-busy="true">Carregando…</p></main>;
  if (plano.error) {
    return <main><PageHeader titulo="Comunidades · Plano" /><p role="alert">{plano.error instanceof ApiError ? plano.error.message : "Falha ao carregar o plano."}</p></main>;
  }
  if (!dados || (!dados.classes.length && !dados.instrucoes.length)) {
    return (
      <main>
        <PageHeader titulo="Comunidades · Plano" />
        <p>
          Nenhum plano adotado ainda. O plano vem da configuração já coletada, pelo
          <code>gerenet communities plan adotar</code> ou pelo <code>POST /api/v1/communities/plan/adopt</code>.
        </p>
      </main>
    );
  }

  const portoes = dados.portoes;
  const testes = new Set(dados.classes.flatMap((c) => (c.testam.length ? [c.nome] : [])));
  const aplicadas = new Set(dados.classes.flatMap((c) => (c.aplicam.length ? [c.nome] : [])));

  return (
    <main>
      <PageHeader titulo="Comunidades · Plano" />
      <section aria-labelledby="plano-cabecalho">
        <h2 id="plano-cabecalho">Cabeçalho</h2>
        <p><strong>ASN principal:</strong> {dados.asn_principal ?? "—"}</p>
        <p><strong>ASNs anunciados:</strong> {dados.asns_anunciados.map((a) => String(a.asn)).join(", ") || "—"}</p>
        <p><strong>Origem:</strong> {dados.observacoes ?? "—"}</p>
      </section>

      <section aria-labelledby="plano-classes">
        <h2 id="plano-classes">Classes e instruções</h2>
        <DataTable<ClassePlanoOut>
          colunas={[
            { key: "nome", title: "Nome" },
            { key: "banda", title: "Banda", render: (c) => c.banda ?? "—" },
            { key: "valor_v4", title: "v4", render: (c) => c.valor_v4 ?? "—" },
            { key: "valor_v6", title: "v6", render: (c) => c.valor_v6 ?? "—" },
            { key: "aplicam", title: "Quem aplica", render: (c) => c.aplicam.join(", ") || "ninguém" },
            { key: "testam", title: "Quem testa", render: (c) => c.testam.join(", ") || "ninguém" },
            {
              key: "selo",
              title: "Situação",
              render: (c) =>
                aplicadas.has(c.nome) && !testes.has(c.nome) ? (
                  <span className="badge badge-fail">aplicada e não testada</span>
                ) : testes.has(c.nome) && !aplicadas.has(c.nome) ? (
                  <span className="badge badge-warn">testada e não aplicada</span>
                ) : (
                  "—"
                ),
            },
          ]}
          linhas={dados.classes}
        />
      </section>

      <section aria-labelledby="plano-matriz">
        <h2 id="plano-matriz">Matriz classe × papel</h2>
        <table aria-label="matriz classe × papel">
          <thead>
            <tr>
              <th>Classe</th>
              {PAPEIS.map((p) => <th key={p}>{p}</th>)}
            </tr>
          </thead>
          <tbody>
            {dados.classes.map((classe) => (
              <tr key={classe.nome}>
                <td>{classe.nome}</td>
                {PAPEIS.map((papel) => (
                  <td key={papel}>{celulaDaMatriz(classe, papel, portoes)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p>Portões: {portoes.map((p) => p.nome).join(", ") || "nenhum"}.</p>
      </section>

      <section aria-labelledby="plano-alvos">
        <h2 id="plano-alvos">Alvos</h2>
        <DataTable
          colunas={[
            { key: "nome", title: "Grupo" },
            { key: "papel", title: "Papel" },
            { key: "codigo_v4", title: "Código v4", render: (a) => a.codigo_v4 ?? "—" },
            { key: "codigo_v6", title: "Código v6", render: (a) => a.codigo_v6 ?? "—" },
            { key: "gate_nome", title: "Portão", render: (a) => a.gate_nome ?? "—" },
            { key: "estado", title: "Sessão", render: (a) => a.estado },
          ]}
          linhas={dados.alvos}
        />
      </section>

      <section aria-labelledby="plano-divergencias">
        <h2 id="plano-divergencias">Divergências ({achados.length})</h2>
        <DataTable<AchadoOut>
          colunas={[
            { key: "severidade", title: "Severidade" },
            { key: "descricao", title: "Achado" },
            { key: "filtro", title: "Filtro", render: (a) => a.filtro ?? "—" },
            { key: "linha", title: "Linha", render: (a) => a.linha ?? "—" },
            { key: "acao", title: "Ação sugerida", render: (a) => a.acao ?? "—" },
          ]}
          linhas={achados}
          vazio="Nenhuma divergência entre o plano e a configuração."
        />
      </section>
    </main>
  );
}
```

Os dois selos usam `badge badge-fail` e `badge badge-warn`, que é o que o
`global.css:173-202` define (o `StatusBadge` deriva a classe do estado; aqui o
rótulo é frase, não estado, então a classe vai direto).

- [ ] **Step 5: Ligar a rota, o menu e as colunas**

`web/src/App.tsx`: importe `CommunitiesPlan from "@/pages/CommunitiesPlan"` e, depois da linha 71, `<Route path="/communities/plan" element={<CommunitiesPlan />} />`.

`web/src/components/Layout.tsx`, no grupo `roteamento` (linha 33), depois do item de Communities:

```tsx
      { para: "/communities/plan", rotulo: "Comunidades · Plano" },
```

`web/src/pages/Communities.tsx`: acrescente as quatro colunas **depois de `tipo`**,
antes da de Observações (`Communities.tsx:96-100`):

```tsx
          { key: "valor_v4", title: "v4", render: (c) => c.valor_v4 ?? "—" },
          { key: "valor_v6", title: "v6", render: (c) => c.valor_v6 ?? "—" },
          { key: "banda", title: "Banda", render: (c) => c.banda ?? "—" },
          { key: "origem", title: "Origem", render: (c) => (c.origem === "adotado" ? "adotada" : "manual") },
```

Nos dois formulários (criação e edição), três campos novos — `valor_v4`, `valor_v6`
e `banda` — com `help={help("community.valor_v4")}`, `help("community.valor_v6")` e
`help("community.banda")`, cada um antes do campo de Observações. São **três** chaves
novas em `web/src/help.ts`, na seção `// Communities` (`help.ts:103-105`):
`community.valor_v4`, `community.valor_v6`, `community.banda`. O `help()` é tipado
por `HelpKey = keyof typeof HELP`, então o `npm run build` quebra se a chave faltar.
`origem` **não** vira campo de formulário: quem a escreve é a adoção (`"adotado"`) ou
o cadastro (`"manual"`); é coluna de leitura e o `CommunityUpdate` não a aceita.

- [ ] **Step 6: Rodar tudo**

```bash
cd web && npm run test -- CommunitiesPlan && npm run build
```

Esperado: os 4 testes passando e o build sem erro (o `tsc -b` pega tipo errado e chave de ajuda faltando).

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "feat(web): página Comunidades · Plano com matriz e divergências"
```

---

### Task 10: Wiki e registro da frente

A página do wiki e o bullet do `CLAUDE.md` — o repositório registra cada frente no "Estado do repositório", e uma página nova sem documentação deixa a consulta pior do que era.

**Files:**
- Create: `docs/wiki/communities.md`
- Modify: `CLAUDE.md`
- Test: nenhum arquivo novo; o portão é o mesmo da Task 9 (`npm run build`) e a leitura da página no navegador

**Interfaces:**
- Consumes: tudo.
- Produces: documentação.

- [ ] **Step 1: Escrever a página do wiki**

A página é **nova** (`docs/wiki/communities.md`), não uma seção a mais em
`roteamento.md`: é o formato das outras frentes (a descoberta tem `descoberta.md`,
os upstreams têm `upstreams.md`) e o assunto tem seis tópicos próprios. O índice da
wiki lista **páginas**, não seções (`api/wiki.py:87-91`, `WikiIndiceItem` sem campo
de seção interna), então só uma página nova ganha item na barra lateral.

O frontmatter, na seção Roteamento, depois dos dois que já estão lá
(`roteamento.md` é `order: 1` e `upstreams.md` `order: 2`):

```markdown
---
title: Plano de communities
secao: Roteamento
secao_order: 3
order: 3
em_breve: false
---
```

O corpo responde, nesta ordem:

- **o que é o plano** — o vocabulário (classes e instruções), os alvos e os portões, e por que ele existe: o export ao upstream passa a ser por classe, e não por prefixo;
- **de onde ele vem** — da configuração já coletada, pelo `gerenet communities plan adotar <device>` ou pelo `POST /api/v1/communities/plan/adopt`; nunca do equipamento por comando novo;
- **o que é a partição** — as faixas da spec §5 em linguagem de operação (local, trânsito, cliente, parceiro, conjunto, tamanho, especial) e as exceções nomeadas;
- **as duas grafias** — `65000:<classe>` no clássico e `61785:<classe>` no XPL são a mesma classe, e o portão precisa testar a grafia que o filtro aplica (é o achado mais grave da primeira leitura, §8.1);
- **o que a validação cobra** — as oito checagens da §8, uma linha cada;
- **o que esta frente não faz** — o render não muda, a adoção do plano sai do CLI e da API (a revisão pela web fica para a F2, junto da edição), e mudar o roteador continua sendo change request.

Escreva os nomes de comando e de página como estão no CLI e na web
(`gerenet communities plan adotar`, `/communities/plan`) — a wiki é lida por quem
opera, não por quem lê o código.

- [ ] **Step 2: Ler a página renderizada**

```bash
cd web && npm run build && cd ..
uv run uvicorn gerenet.api.main:create_app --factory   # em outro terminal, ou com &
```

Abra `/wiki/communities` e confira o item "Plano de communities" na seção
Roteamento da barra lateral, e que o texto saiu sem markdown quebrado (a API
sanitiza com `nh3`).

- [ ] **Step 3: O bullet no `CLAUDE.md`**

Acrescente, ao fim da lista de "Estado do repositório", um bullet no formato dos outros:

```markdown
- Plano de communities — F1 (2026-09-17): o plano virou dado na SoT — `communities`
  ganhou `valor_v4`/`valor_v6`/`codigo`/`banda`/`origem` (+ snapshot de origem) e
  nasceram `community_plans` (uma linha ativa), `community_targets`, `community_gates`
  e `community_import_rules` (migração `alembic/versions/<hash>_plano_de_communities.py`,
  com o `<hash>` que o `alembic revision` deu na Task 1).
  A partição da spec §5 está em `domain/communities_partition.py` (faixas, exceções
  nomeadas e `conferir_linha`; a escrita só recusa valor na família errada — o resto é
  exceção legítima que a validação aponta). Leitor novo
  `automation/parsers/huawei_vrp/communities_vrp.py` (definições, quem aplica, quem
  testa, citações sem definição e grupos de peer — o `config_vrp.py` descarta
  `peer <nome-de-grupo>` de propósito), motor `automation/community_plan.py` com o
  `VOCABULARIO` da §6, a proposta (poda de sessão parada, divergências de código
  ambíguo, nome × faixa e papel duvidoso) e `validar` com as oito checagens da §8 —
  a checagem 1 compara **valor literal** (`61785:3001` ≠ `65000:3001`), que é o que
  produz o achado principal da §8.1. Serviço `domain/services/community_plan.py`
  (adoção numa transação só, idempotente, audit `community_plan.adopt`), API
  `/api/v1/communities/plan` (GET, GET `/validacao`, POST `/adopt`), CLI
  `gerenet communities plan show|validar|adotar` e a página `Comunidades · Plano`
  (cabeçalho, classes com quem aplica × quem testa, matriz classe × papel, alvos e o
  painel de divergências). O render **não** mudou nesta fatia (§3); a unificação de
  `upstream_communities` e a edição do plano pela web ficam para F3/F2.
```

- [ ] **Step 4: Commit**

```bash
git add docs/wiki/communities.md CLAUDE.md
git commit -m "docs(communities): a wiki e o registro da frente do plano"
```

---

## Self-review

**1. Cobertura da spec.**

| Seção da spec | Onde entra |
|---|---|
| §4.1 `communities` estendida | Task 1 (colunas e índices), Task 2 (guarda), Task 9 (colunas na página) |
| §4.2 `community_plans` | Task 1, Task 6 (`obter_plano`, `adotar_plano`) |
| §4.3 `community_targets` | Task 1, Task 5 (proposta com papel e códigos), Task 4 (checagem 7) |
| §4.4 `community_gates` | Task 1, Task 5 (aceitas × recusadas), Task 9 (matriz) |
| §4.5 `community_import_rules` | Task 1, Task 5 (`_regras_de_importacao`), gravadas na Task 6 |
| §5 partição | Task 2 (faixas e exceções), Task 4 (checagem 2) |
| §6.1 vocabulário de classes | Task 4 (`VOCABULARIO`) |
| §6.2 instruções | Task 4 (`VOCABULARIO_INSTRUCOES`, códigos conhecidos) |
| §6.3 alvos | Task 3 (grupos de peer), Task 5 (papel e poda) |
| §7 a forma híbrida | Task 4 (checagem 1 é a matriz; Regra 6 dá o papel do portão) |
| §8 as oito checagens | Task 4, uma função por checagem |
| §8.1 os sete achados | Task 4 (testes nomeados) e Task 5 (o `15169:12000` vira `parametros`, ver lacuna abaixo) |
| §9 a adoção | Task 5 (proposta), Task 6 (poda, transação única, auditoria) |
| §9.1 o que se reaproveita | Task 6 usa `_snapshot_com_config`; Task 1 segue o padrão `origem` + `origem_snapshot_id` |
| §9.2 o que é novo | Tasks 1, 3, 4, 5 — o ajuste do `_autorizadas_clientes` é F3, como a spec diz |
| §10 o render não muda | Global Constraint; nenhuma task toca `render.py` |
| §11 o frontend | Task 9 (quatro blocos + painel + colunas em Communities) |
| §12 fatias | Task 10 registra que F2/F3/F4 vêm depois |
| §13 testes | Toda task tem teste: partição, validação, adoção, parser, API e web |
| §14 dívidas | Task 5 emite as divergências 2, 4 e 6; as 1, 3 e 5 são change request e ficam registradas |

**Lacuna consciente:** o achado do `15169:12000` (§8.1) não vira `Achado` — ele é
`community_targets.parametros["excecoes"]`, como a própria spec diz ("isso é
parâmetro de alvo"). A página mostra o parâmetro no bloco de alvos; apontar que a
exceção está no filtro errado é julgamento humano e fica de fora da F1.

**Lacuna consciente 2:** a fixture da Task 4 para a checagem de família é
sintética (`BGP-IPV4-CUSTOMER` recortado), porque o trecho real do bloco de
`/22` e `/23` não foi copiado para a fixture sem trazer mais contexto do que o
parser precisa. O comportamento testado é o real: o filtro v4 que aplica valor
v6.

**2. Varredura de placeholder.** Nenhum "TBD", "implementar depois" ou "similar à
Task N": as tasks repetem o código de que precisam, e as três notas de ajuste
(`montar_plano_out`, `valores_do_corpus`, `_resolve_instrucoes`) trazem o código
inteiro em vez de descrever o que fazer.

**3. Consistência de tipos.** Os nomes atravessam as tasks sem divergir:
`LeituraCommunities.usos` com `operacao` em `{aplica, aplica-large, testa,
testa-large, cita}` (Task 3) é o que `_aplicados_e_testados` filtra com
`startswith` (Task 4) e o que `montar_plano_out` percorre (Task 7);
`PlanoLido.classes` é `ClassePlano` em todas as tasks que o constroem (4, 5, 6);
`PortaoPlano.aceitas` é `tuple[str, ...]` de **nomes** no motor e lista de
**ids** no banco, com a tradução em `adotar_plano`/`obter_plano` (Task 6) — a
única assimetria do desenho, e ela é deliberada (Regra 1: a proposta não tem ids).
`v4`/`v6` nos textos de teste da web são os rótulos das colunas, iguais aos do
`PlanoOut` real.

**4. Passe final sobre as tasks 3 a 10** (contra o código real do repositório e
contra os próprios textos do plano). O que foi corrigido:

- **A checagem 4 invertia o que consertava.** `_conferir_instrucoes` lia o campo do
  meio como código sempre; numa large-community invertida (`61785:14840:4`) leria
  `14840` como código, acusaria `codigo_orfao` falso e **não** emitiria o
  `ordem_invertida`, que é o achado que a §8.1 mais destaca. Agora `_ordem_do_valor`
  decide e `(codigo, alvo_numero)` trocam de lugar entre si; a chave de `ordens`
  passou a ser sempre `(código, alvo)` depois da troca, senão o import e o export do
  mesmo par não se encontravam.
- **`propor_plano` indexava a referência só por `valor_v4`.** O `65000:7101` do
  `-v6` caía no ramo sintético e gerava uma segunda classe com o código v6 escrito na
  coluna v4 — linha que a própria checagem 2 reprovaria depois de adotada. Passou a
  indexar os **dois** códigos do par, deduplicar por `(valor_v4, valor_v6)` e escolher
  a coluna pelo dígito do código.
- **`estados_dos_alvos` usava colunas que não existem.** A primeira versão lia
  `BgpSession.name`/`.estado`; `BgpSession` não tem nenhuma das duas (`models.py`).
  Agora o estado sai do recurso `bgp_peers` da coleta mais recente de cada
  equipamento, endereço por endereço, e o alvo é casado pelos membros que o leitor
  achou — que é o que a §3 manda (estado é do equipamento, não da SoT). Os três
  pontos de chamada (adoção, validação e `montar_plano_out`) passaram a receber
  `(session, leituras, device_ids)`.
- **`montar_plano_out` relia a coleta por device e o `int()` cru podia estourar.**
  Agora lê as leituras uma vez e usa as mesmas para a contagem e para o estado; o
  campo do meio só é convertido depois de `isdigit()`.
- **Os hooks da web não existiam como estavam escritos.** O plano mandava usar
  `useLista` no `GET /plan`, que devolve objeto; e `useLista` é `apiFetch<T[]>`
  (`hooks.ts:109`). Os dois hooks passaram a `useQuery` (o padrão do `useDashboard`) e
  o helper ganhou o nome real, `apiFetch` (era `pedir`). O `useLista` também monta a
  queryKey sem o `device_id`, então a validação de um equipamento serviria o cache do
  outro.
- **Os testes da web como estavam não passavam.** `getByText` solto acha **duas**
  ocorrências de `com-TRANSITO-FULL` (tabela de classes e matriz) e de
  `CUSTOMER-BGP-v4` (quem aplica e filtro do achado), e `/61785/` casa dois
  parágrafos do cabeçalho — todos estourariam com "found multiple elements". As
  buscas passaram a ser escopadas por `within` nas seções (que têm `aria-labelledby`)
  e na matriz, e o stub de `fetch` ganhou a resposta de `/auth/me` e o 404 do resto,
  como nos outros testes de página. O `waitFor` saiu (os `findBy*` já esperam) para
  o `noUnusedLocals` do `tsc -b` não quebrar o build.
- **Selos com classe CSS inexistente.** `badge-critico`/`badge-atencao` não existem
  em `styles/global.css`; são `badge badge-fail`/`badge badge-warn`.
- **A wiki ganhou página própria.** O índice lista páginas, não seções
  (`api/wiki.py`, `WikiIndiceItem`), então uma seção a mais em `roteamento.md` não
  apareceria na barra lateral como o plano prometia; a página é
  `docs/wiki/communities.md`, na seção Roteamento, `order: 3`.
- **A adoção não tem botão na web em F1.** O plano citava a página `Migrar` como
  caminho de adoção do plano e listava um `usePlanoAdotar` que task nenhuma define. A
  §11 dá à web só a consulta e joga a edição para a F2; os dois textos passaram a
  citar o CLI e a API, e o `Link` que sobrou sem uso saiu do arquivo (o
  `noUnusedLocals` de novo).

**Lacuna consciente 3:** a adoção em F1 é CLI/API. A revisão da proposta do plano
(pendências e divergências lado a lado, como a §9 descreve para o fluxo) tem a
metade de leitura na página nova e a de escrita no CLI — não há tela de revisão com
o botão de adotar, e isso é a F2, junto da edição.

---

## Execution handoff

Plano salvo em `docs/superpowers/plans/2026-09-17-gerenet-plano-de-communities.md`.

Duas formas de executar:

1. **Subagent-Driven (recomendada)** — um subagente novo por task, revisão entre
   tasks, iteração rápida. Cada task deste plano cabe numa sessão de subagente
   sem carregar as outras.
2. **Inline** — execução nesta sessão com `superpowers:executing-plans`, em
   lotes com checkpoint de revisão.

Qualquer uma das duas **exige uma worktree isolada**, criada com
`superpowers:using-git-worktrees` **antes do primeiro commit** — a regra do
`CLAUDE.md` global: nunca implementar na `main` nem numa branch compartilhada
com outra sessão. O merge definitivo no checkout principal é executado pelo
usuário.
