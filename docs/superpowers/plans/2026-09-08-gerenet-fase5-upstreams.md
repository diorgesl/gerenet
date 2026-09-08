# Fase 5 — Upstreams e políticas avançadas Implementation Plan

> **Para workers agentic:** SUB-SKILL OBRIGATÓRIO: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa a tarefa. Passos usam checkbox (`- [ ]`).

**Goal:** Fechar a Fase 5 do gerenet: upstream (operadora + N circuitos com papel/ordem) como entidade do sistema, com render de importação up-full/up-parcial/up-default, anúncio de internas + clientes ao trânsito, communities de engenharia de tráfego por operadora (valores concretos), proteções §7.1, IRR/RPKI consultivos e CR com escopo `upstream`.

**Architecture:** O upstream reutiliza `circuits`/`bgp_sessions` (liga via `upstream_circuits` com papel/ordem) e adiciona tabelas próprias (`upstreams`, `upstream_communities`, `roas`, `irr_cache`). O render ganha um caminho alternativo para sessões de circuito de upstream (`org.kind == "operadora"`), o fluxo de mudança ganha o escopo `upstream` (plano agrega por device, re-diff, pós-check por peer com contagens) e a validação IRR/RPKI é consultiva (dados + feed local; sem RTR). Estágios A–E; cada um termina com software testável.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic (PostgreSQL) + Jinja2 + TextFSM + Typer + RQ/Redis; web React + Vite + Vitest + Playwright (e2e).

**Spec:** [docs/superpowers/specs/2026-09-08-gerenet-fase5-upstreams-design.md](docs/superpowers/specs/2026-09-08-gerenet-fase5-upstreams-design.md) — o plano argumenta a partir do spec; execute o spec junto.

## Global Constraints

- Idioma dos artefatos: **português (PT-BR)** — mensagens, docstrings, commits, UI.
- Commands de teste: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build && npm run test`; e2e: `cd web && npm run test:e2e` (banco **dedicado** `gerenet_e2e`, `reuseExistingServer: false` — porta 8000 ocupada = falha dura).
- Migrações devem ser **idempotentes** (`on conflict do nothing` em seeds; `ADD VALUE IF NOT EXISTS` em enums) e o `down_revision` encadeia em `b8c714be9ba5` (head atual).
- Nomes VRP (§25.4): derivam do **ASN do par**; ≤ 63 chars, maiúsculas, separador `-`. Novo: `pfx_internas(afi)` → `IP-PFX-INTERNAS-<AFI>`; community-filter → `CF-<ASN>-<SUFIXO>`.
- Segredos nunca entram em logs/snapshots/auditoria (sessão BGP usa `password_ref` → Vault; nada novo aqui).
- Render idempotente por construção (deriva sempre do SoT); falha-safe: sessão de upstream **sem** import profile ⇒ deny-all.
- CR: mesma máquina de estados do ciclo D (`rascunho → …`), tratamento de erros via `Contact` de `gerenet/domain/services/errors` (`NotFoundError` 404, `ConflictError` 409, `ValidationError` 400) nos routers.
- API sob `/api/v1` com `Depends(require_actor)`; CLI Typer com `get_session()`; objetos em uso são **desativados, nunca excluídos** (§14.1) — exceção: `bgp_session_communities` (deletável, ruling 13) e linhas de `roas`/`irr_cache` (dados externos, regraváveis).
- Cada tarefa termina com **commit**; nunca commitar código que deixe pytest/ruff/web build vermelhos.
- `.claude/settings.local.json` é local: não versionar/alterar.

---

# Estágio A — Fundamentos (modelo, migração, serviços, API, CLI)

## Task A1: Modelos + migração Alembic (upstreams, communities.tipo, enums, roas, irr_cache)

**Files:**
- Modify: `src/gerenet/domain/models.py` (enums L25-40; Org L184; Circuit L229-239; Device L70; Community L348-366; BgpPrefixAuthorization L431-450; ChangeRequest L488-535)
- Create: `alembic/versions/<rev>_upstreams_f5.py` (gerada com `uv run alembic revision -m "upstreams_f5"`; depois preencher)
- Test: `tests/domain/test_upstream_models.py` (novo)

**Interfaces:**
- Consumes: nada novo (tudo existente).
- Produces: classes `Upstream`, `UpstreamCircuit`, `UpstreamCommunity`, `Roa`, `IrrCache`; enums `UPSTREAM_TIPO`, `UPSTREAM_PAPEL`, `UCOMM_PURPOSE`, `UCOMM_DIR`, `COMMUNITY_TIPO`; colunas novas em `organizations.kind` (`operadora`), `circuits.vlan_mode` (`none`), `circuits.access_device_id` nullable, `devices.loopback`, `communities.tipo`, `bgp_prefix_authorizations.validacao`, `change_requests.upstream_id`.

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Modelos da fase 5 (§3 do design) — defaults e unicidades."""
import pytest

from gerenet.domain import models


def test_upstream_defaults_e_unicidade(session, org_operadora):
    up = models.Upstream(name="transito-acme", tipo="transito",
                         organization_id=org_operadora.id,
                         expected_prefixes_v4=900000, expected_prefixes_v6=300000)
    session.add(up)
    session.commit()
    assert up.max_prefix_margin_pct == 20
    assert up.rpki_enabled is True


def test_org_kind_operadora_disponivel(session):
    assert "operadora" in models.ORG_KIND
    assert models.AUTH_ORIGIN == ("manual", "irr", "rpki")
    assert models.CHANGE_ESCOPO == ("circuito", "l2vc", "vsi", "upstream")
    assert "none" in models.VLAN_MODE


def test_unicidade_upstream_circuit(session, org_operadora, circuito_up, up):
    session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=circuito_up.id))
    session.commit()
    with pytest.raises(Exception):
        session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=circuito_up.id))
        session.commit()


def test_roa_unicidade(session):
    session.add(models.Roa(prefix="180.10.0.0/16", origin_asn=64512, max_length=24))
    session.commit()
    with pytest.raises(Exception):
        session.add(models.Roa(prefix="180.10.0.0/16", origin_asn=64512, max_length=24))
        session.commit()
```

- [ ] **Step 2: Rodar e verificar que falha**

Run: `uv run pytest tests/domain/test_upstream_models.py -q`
Expected: FAIL (classes/enums inexistentes).

- [ ] **Step 3: Adicionar enums e alterar colunas existentes em `models.py`**

```python
# topo de models.py (junto de ORG_KIND etc.)
ORG_KIND = ("downstream", "parceiro", "operadora")
VLAN_MODE = ("unica", "separada", "none")
AUTH_ORIGIN = ("manual", "irr", "rpki")
CHANGE_ESCOPO = ("circuito", "l2vc", "vsi", "upstream")
COMMUNITY_TIPO = ("padrao", "acao_blackhole", "acao_prepend", "acao_lp", "informacao", "tag_produto")
UPSTREAM_TIPO = ("transito", "ix", "pni", "contingencia")
UPSTREAM_PAPEL = ("principal", "contingencia")
UCOMM_PURPOSE = ("blackhole", "prepend", "lp", "info")
UCOMM_DIR = ("import", "export", "ambos")
```

Depois, nos models existentes:

```python
class Organization(Base):
    kind: Mapped[str] = mapped_column(Enum(*ORG_KIND, name="org_kind"), default="downstream", nullable=False)  # já apresenta a coluna; só o ENUM muda
```

```python
class Device(Base):
    loopback: Mapped[str | None] = mapped_column(String(64))  # loopback do roteador (§5) — rotas internas F5
```

```python
class Circuit(Base):
    access_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))  # nullable: circuito de upstream sem switch de acesso
```

```python
class Community(Base):
    tipo: Mapped[str] = mapped_column(
        Enum(*COMMUNITY_TIPO, name="community_tipo"), default="padrao", nullable=False
    )  # §7/§25.6: categorização; criação de novas via UI/CLI desde a F5
```

```python
class BgpPrefixAuthorization(Base):
    origin: Mapped[str] = mapped_column(
        Enum(*AUTH_ORIGIN, name="auth_origin"), default="manual", nullable=False)
    validacao: Mapped[str | None] = mapped_column(String(32))  # ok|diverge|desconhecida|nao_verificada (consultiva, F5)
```

```python
class ChangeRequest(Base):
    upstream_id: Mapped[int | None] = mapped_column(ForeignKey("upstreams.id"))
    # relationship:
    upstream: Mapped["Upstream | None"] = relationship()

    @property
    def upstream_name(self) -> str | None:
        return self.upstream.name if self.upstream else None
```

- [ ] **Step 4: Adicionar as classes novas ao final de `models.py` (antes de `User`)**

```python
class Upstream(Base):
    """Conectividade própria de trânsito/IX/PNI (§7) — a intenção; nada roda no roteador sem CR."""

    __tablename__ = "upstreams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(Enum(*UPSTREAM_TIPO, name="upstream_tipo"), nullable=False)
    capacity: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[str | None] = mapped_column(String(32))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    expected_prefixes_v4: Mapped[int | None] = mapped_column(Integer)
    expected_prefixes_v6: Mapped[int | None] = mapped_column(Integer)
    max_prefix_margin_pct: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    rpki_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    entrada_local_preference: Mapped[int | None] = mapped_column(Integer)
    contingencia_local_preference: Mapped[int | None] = mapped_column(Integer)
    contingencia_prepend: Mapped[int | None] = mapped_column(Integer)  # 0-10
    contingencia_notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship()
    circuitos: Mapped[list["UpstreamCircuit"]] = relationship(
        back_populates="upstream", order_by="UpstreamCircuit.ordem",
        cascade="all, delete-orphan")
    comunidades: Mapped[list["UpstreamCommunity"]] = relationship(
        back_populates="upstream", order_by="UpstreamCommunity.id",
        cascade="all, delete-orphan")


class UpstreamCircuit(Base):
    """Vínculo upstream ↔ circuito (§7; design §3): papel e ordem de preferência."""

    __tablename__ = "upstream_circuits"
    __table_args__ = (UniqueConstraint("upstream_id", "circuit_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upstream_id: Mapped[int] = mapped_column(ForeignKey("upstreams.id"), nullable=False)
    circuit_id: Mapped[int] = mapped_column(ForeignKey("circuits.id"), nullable=False)
    papel: Mapped[str] = mapped_column(Enum(*UPSTREAM_PAPEL, name="upstream_papel"), default="principal", nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    upstream: Mapped[Upstream] = relationship(back_populates="circuitos")
    circuito: Mapped[Circuit] = relationship()


class UpstreamCommunity(Base):
    """Community de operadora com VALOR CONCRETO (design §3; §7.1) — cadastro livre."""

    __tablename__ = "upstream_communities"
    __table_args__ = (UniqueConstraint("upstream_id", "purpose", "value", "regiao"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upstream_id: Mapped[int] = mapped_column(ForeignKey("upstreams.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(Enum(*UCOMM_PURPOSE, name="ucomm_purpose"), nullable=False)
    value: Mapped[str] = mapped_column(String(64), nullable=False)  # valor concreto (ex.: 65530:20:0)
    direcao: Mapped[str] = mapped_column(Enum(*UCOMM_DIR, name="ucomm_dir"), default="ambos", nullable=False)
    regiao: Mapped[str | None] = mapped_column(String(64))
    bloquear: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # info: deny no import
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    upstream: Mapped[Upstream] = relationship(back_populates="comunidades")


class Roa(Base):
    """ROA do validador local (rpki-client JSON → §6 design) — dado externo, regravável."""

    __tablename__ = "roas"
    __table_args__ = (UniqueConstraint("prefix", "origin_asn", "max_length"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    origin_asn: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_length: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="rpki-client", nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IrrCache(Base):
    """Cache de consultas IRR (whois) — §6 design; TTL 24h."""

    __tablename__ = "irr_cache"
    __table_args__ = (UniqueConstraint("source", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # radb|altdb|lacnic...
    key: Mapped[str] = mapped_column(String(128), nullable=False)  # AS-SET ou ASN
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    queried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5: Escrever a migração**

Aplicar em `alembic/versions/<rev>_upstreams_f5.py` (gerada com `uv run alembic revision -m "upstreams_f5"`; `down_revision = "b8c714be9ba5"`):

```python
def upgrade() -> None:
    # enums com ADD VALUE (padrão 9081b87de351; fora de transação de DDL no PG < 12 — usar op.execute)
    op.execute("ALTER TYPE org_kind ADD VALUE IF NOT EXISTS 'operadora'")
    op.execute("ALTER TYPE vlan_mode ADD VALUE IF NOT EXISTS 'none'")
    op.execute("ALTER TYPE auth_origin ADD VALUE IF NOT EXISTS 'irr'")
    op.execute("ALTER TYPE auth_origin ADD VALUE IF NOT EXISTS 'rpki'")
    op.execute("ALTER TYPE change_escopo ADD VALUE IF NOT EXISTS 'upstream'")
    op.execute("CREATE TYPE community_tipo AS ENUM ('padrao','acao_blackhole','acao_prepend','acao_lp','informacao','tag_produto')")
    op.execute("CREATE TYPE upstream_tipo AS ENUM ('transito','ix','pni','contingencia')")
    op.execute("CREATE TYPE upstream_papel AS ENUM ('principal','contingencia')")
    op.execute("CREATE TYPE ucomm_purpose AS ENUM ('blackhole','prepend','lp','info')")
    op.execute("CREATE TYPE ucomm_dir AS ENUM ('import','export','ambos')")

    op.add_column('devices', sa.Column('loopback', sa.String(64), nullable=True))
    op.alter_column('circuits', 'access_device_id', existing_type=sa.Integer(), nullable=True)
    op.add_column('communities', sa.Column('tipo', postgresql.ENUM('community_tipo', name='community_tipo', create_type=False), nullable=True))
    op.execute("UPDATE communities SET tipo = 'padrao' WHERE tipo IS NULL")
    op.alter_column('communities', 'tipo', nullable=False, server_default="'padrao'")
    op.add_column('bgp_prefix_authorizations', sa.Column('validacao', sa.String(32), nullable=True))
    op.add_column('change_requests', sa.Column('upstream_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_change_requests_upstream', 'change_requests', 'upstreams', ['upstream_id'], ['id'])

    op.create_table('upstreams', ...)   # usar sa.Column conforme o model (id, name, tipo, ...) + FK organizations
    op.create_table('upstream_circuits', ...)  # + UniqueConstraint('upstream_id','circuit_id')
    op.create_table('upstream_communities', ...)  # + UniqueConstraint('upstream_id','purpose','value','regiao')
    op.create_table('roas', ...)  # + UniqueConstraint('prefix','origin_asn','max_length')
    op.create_table('irr_cache', ...)  # + UniqueConstraint('source','key')

    # seeds de importação de upstream (§4.1) — idempotentes
    op.execute(
        sa.text("insert into bgp_policy_profiles (name, label, direction, kind, admin_status) "
                "values (:name, :label, 'import', 'produto', true) on conflict do nothing"),
        [{"name": "up-full", "label": "Full (trânsito/IX)"},
         {"name": "up-parcial", "label": "Parcial (comunidade do provedor)"},
         {"name": "up-default", "label": "Somente default"}],
    )


def downgrade() -> None:
    op.execute("ALTER TYPE change_escopo DROP VALUE ...")  # PG não remove valor de enum em < 14? — na prática: apenas criar migração de downgrade que dropa tabelas e colunas; oráculos dos enums ficam (padrão do projeto: drop type if exists).
    # Seguir padrão do projeto: drop das tabelas novas, colunas e types.
```

_Nota do executor:_ siga o padrão de `downgrade` do projeto (ex.: `alembic/versions/9081b87de351`), dropando tabelas novas, colunas e tipos criados via `op.execute("DROP TYPE IF EXISTS ...")` — nunca remover valores de enum em `downgrade` (limitação PG).

- [ ] **Step 6: Rodar migração e testes**

Run: `uv run alembic upgrade head` (banco dev) e `uv run pytest tests/domain/test_upstream_models.py -q`
Expected: migration aplica; testes PASS.

- [ ] **Step 7: Rodar suíte completa e commit**

Run: `uv run pytest -q` e `uv run ruff check src tests`
Expected: tudo PASS (se algum teste antigo quebrar por enum novo — ex.: sim de `ORG_KIND` — corrigir o assert, não o enum).

```bash
git add src/gerenet/domain/models.py alembic/versions/<rev>_upstreams_f5.py tests/domain/test_upstream_models.py
git commit -m "feat(f5): modelos e migração da fase 5 (upstreams, communities tipo, roas, irr_cache)"
```

## Task A2: Schemas Pydantic (upstreams, upstream_communities, ChangeRequest, autorizações)

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (junto de `ChangeRequestCreate` L538 e `ChangeRequestOut` L588)
- Test: `tests/domain/test_upstream_schemas.py` (novo)

**Interfaces:**
- Consumes: enums do A1.
- Produces: `UpstreamCreate`, `UpstreamUpdate`, `UpstreamOut`, `UpstreamDetailOut` (com `circuitos` e `sessoes` aninhados), `UpstreamCommunityCreate`, `UpstreamCommunityOut`; campos `upstream_id` em `ChangeRequestCreate` (validação de escopo) e `upstream_id`/`upstream_name` em `ChangeRequestOut`; `validacao` em `BgpPrefixAuthorizationOut`.

- [ ] **Step 1: Teste que falha**

```python
def test_change_request_upstream_escopo_valida():
    from gerenet.domain.schemas import ChangeRequestCreate
    with pytest.raises(ValueError, match="upstream_id"):
        ChangeRequestCreate(escopo="upstream", motivo="m", actor="cli" if False else "cli")
    ok = ChangeRequestCreate(escopo="upstream", upstream_id=1, motivo="m", criticidade="media")
    assert ok.upstream_id == 1


def test_upstream_create_valida_campos():
    from gerenet.domain.schemas import UpstreamCreate
    s = UpstreamCreate(name="transito-x", tipo="transito", organization_id=1)
    assert s.max_prefix_margin_pct == 20
    with pytest.raises(ValueError, match="margem"):
        UpstreamCreate(name="x", tipo="ix", organization_id=1, max_prefix_margin_pct=101)
```

- [ ] **Step 2: Rodar — FAIL esperado.**

- [ ] **Step 3: Implementar no `schemas.py`**

```python
class UpstreamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    tipo: Literal["transito", "ix", "pni", "contingencia"]
    capacity: str | None = None
    priority: int | None = None  # 1 = maior prioridade
    cost: str | None = None
    organization_id: int
    expected_prefixes_v4: int | None = None
    expected_prefixes_v6: int | None = None
    max_prefix_margin_pct: int = Field(default=20, ge=0, le=100)
    rpki_enabled: bool = True
    entrada_local_preference: int | None = None
    contingencia_local_preference: int | None = None
    contingencia_prepend: int | None = Field(default=None, ge=0, le=10)
    contingencia_notes: str | None = None

    @field_validator("max_prefix_margin_pct")
    @classmethod
    def _margem(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("margem (max_prefix_margin_pct) deve estar entre 0 e 100.")
        return v


class UpstreamUpdate(BaseModel):
    name: str | None = None
    tipo: str | None = None
    capacity: str | None = None
    priority: int | None = None
    cost: str | None = None
    organization_id: int | None = None
    expected_prefixes_v4: int | None = None
    expected_prefixes_v6: int | None = None
    max_prefix_margin_pct: int | None = None
    rpki_enabled: bool | None = None
    entrada_local_preference: int | None = None
    contingencia_local_preference: int | None = None
    contingencia_prepend: int | None = None
    contingencia_notes: str | None = None
    admin_status: bool | None = None


class UpstreamCommunityCreate(BaseModel):
    purpose: Literal["blackhole", "prepend", "lp", "info"]
    value: str = Field(min_length=2, max_length=64)
    direcao: Literal["import", "export", "ambos"] = "ambos"
    regiao: str | None = None
    bloquear: bool = False
    notes: str | None = None


class UpstreamCircuitIn(BaseModel):
    circuit_id: int
    papel: Literal["principal", "contingencia"] = "principal"
    ordem: int = 1
```

`ChangeRequestCreate` ganha:

```python
class ChangeRequestCreate(BaseModel):
    escopo: Literal["circuito", "l2vc", "vsi", "upstream"] = "circuito"
    circuit_id: int | None = None
    l2vc_id: int | None = None
    upstream_id: int | None = None  # novo
    acao: Literal["provision", "remove"] = "provision"
    criticidade: Literal["baixa", "media", "alta", "critica"] = "media"
    motivo: str = Field(min_length=3)
    ticket: str | None = None

    def _valida_escopo(self) -> "ChangeRequestCreate":
        if self.escopo == "circuito" and self.circuit_id is None:
            raise ValueError("circuit_id é obrigatório para escopo 'circuito'.")
        if self.escopo == "l2vc" and self.l2vc_id is None:
            raise ValueError("l2vc_id é obrigatório para escopo 'l2vc'.")
        if self.escopo == "upstream" and self.upstream_id is None:
            raise ValueError("upstream_id é obrigatório para escopo 'upstream'.")
        if self.escopo == "vsi":
            raise ValueError("escopo 'vsi' ainda não é provisionável (consulta apenas).")
        return self
```

`ChangeRequestOut` ganha `upstream_id: int | None = None` e `upstream_name: str | None = None` (espelho do `l2vc_name`).

- [ ] **Step 4: Rodar testes PASS; commit (`feat(f5): schemas de upstream e escopo upstream na CR`).**

## Task A3: Serviço de upstreams (CRUD + vínculo de circuitos + propagação)

**Files:**
- Create: `src/gerenet/domain/services/upstreams.py`
- Test: `tests/domain/test_upstreams_service.py` (novo)

**Interfaces:**
- Consumes: modelos do A1, `get_organization` (services/organizations.py), `get_circuit` (services/circuits.py), `get_policy_profile` (services/policy_profiles.py), `registrar` (domain/audit.py).
- Produces: `create_upstream(session, data, *, actor) -> Upstream`; `get_upstream(session, upstream_id)`; `list_upstreams(session, *, include_disabled=False, organization_id=None)`; `update_upstream(session, upstream_id, data, *, actor)`; `disable_upstream(...)`; `vincular_circuito(session, upstream_id, circuit_id, *, papel, ordem, actor)`; `desvincular_circuito(session, upstream_id, circuit_id, *, actor)`; `propagar_defaults(session, upstream) -> list[str]` (retorna resumo das sessões alteradas); `upstream_do_circuito(session, circuit_id) -> Upstream | None`.

- [ ] **Step 1: Testes que falham**

```python
def test_cria_upstream_exige_operadora(session, org_downstream):
    from gerenet.domain.schemas import UpstreamCreate
    from gerenet.domain.services.errors import ValidationError
    with pytest.raises(ValidationError, match="operadora"):
        upstreams.create_upstream(
            session, UpstreamCreate(name="x", tipo="transito", organization_id=org_downstream.id),
            actor="cli")


def test_propagacao_aplica_defaults_e_sessoes_vencem(session, org_operadora, circuito_up, bgp_session_principal):
    from gerenet.domain.services import upstreams as svc
    up = svc.create_upstream(
        session, UpstreamCreate(name="transito-x", tipo="transito", organization_id=org_operadora.id,
                                expected_prefixes_v4=1000, expected_prefixes_v6=200,
                                entrada_local_preference=100, contingencia_local_preference=60,
                                contingencia_prepend=3, max_prefix_margin_pct=10),
        actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1, actor="cli")
    sess = session.get(models.BgpSession, bgp_session_principal.id)
    assert sess.maximum_prefix == 1100  # 1000 * 1.10
    assert sess.maximum_prefix_threshold == 80
    assert sess.local_preference == 100
    # sessão explícita vence: edita e repropaga
    sess.local_preference = 150
    session.commit()
    svc.propagar_defaults(session, up)
    session.refresh(sess)
    assert sess.local_preference == 150


def test_upstream_do_circuito(session, up, up2, circuito_up):
    svc.vincular(session, up.id, circuito_up.id, ...)  # via vincular_circuito
    assert svc.upstream_do_circuito(session, circuito_up.id).id == up.id
```

(Nota: `bgp_session_principal` deve ser fixture de sessão com perfil import `up-full` para o teste acima ter `maximum_prefix` propagado; simplifique no fixture: sessão sem maximum_prefix.)

- [ ] **Step 2: Rodar — FAIL.**

- [ ] **Step 3: Implementar `services/upstreams.py`**

```python
"""Upstreams (§7) — CRUD, vínculo com circuitos e propagação de defaults às sessões."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import UpstreamCreate, UpstreamUpdate, UpstreamCircuitIn
from gerenet.domain.services.circuits import get_circuit
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.services.policy_profiles import get_policy_profile

PRODUTO_IMPORT_POR_TIPO = {"transito": "up-full", "ix": "up-full",
                           "pni": "up-parcial", "contingencia": "up-default"}


def _perfil_import(session: Session, nome: str) -> models.PolicyProfile | None:
    return session.scalar(
        select(models.PolicyProfile).where(
            models.PolicyProfile.name == nome,
            models.PolicyProfile.direction == "import",
            models.PolicyProfile.admin_status.is_(True),
        ))


def get_upstream(session: Session, upstream_id: int) -> models.Upstream:
    up = session.get(models.Upstream, upstream_id)
    if up is None:
        raise NotFoundError(f"Upstream {upstream_id} não encontrado.")
    return up


def list_upstreams(session: Session, *, organization_id: int | None = None,
                   include_disabled: bool = False) -> list[models.Upstream]:
    stmt = select(models.Upstream).order_by(models.Upstream.name)
    if not include_disabled:
        stmt = stmt.where(models.Upstream.admin_status.is_(True))
    if organization_id is not None:
        stmt = stmt.where(models.Upstream.organization_id == organization_id)
    return list(session.scalars(stmt))


def _validar_org_operadora(session: Session, organization_id: int) -> models.Organization:
    org = get_organization(session, organization_id)
    if org.kind != "operadora":
        raise ValidationError(f"Organização {org.id} não é operadora (kind={org.kind}).")
    return org


def _valida_nomes(nome: str) -> None:
    if len(nome) < 2 or len(nome) > 128:
        raise ValidationError("Nome do upstream deve ter entre 2 e 128 caracteres.")


def create_upstream(session: Session, data: UpstreamCreate, *, actor: str) -> models.Upstream:
    _validar_org_operadora(session, data.organization_id)
    _valida_nomes(data.name)
    dump = data.model_dump()
    up = models.Upstream(**dump)
    session.add(up)
    try:
        session.flush()
        registrar(session, tipo="upstream.create", ator=actor, objeto="upstream",
                  objeto_id=up.id, antes=None, depois=dump)
        # produto de import "escondido" por tipo: o perfil é escolhido no upstream
        _aplica_perfil_import(session, up)
        propagar_defaults(session, up)
        session.commit()
    except IntegrityError:  # noqa: F821 — import no topo do módulo
        session.rollback()
        raise ConflictError(f"Já existe um upstream com o nome {data.name}.") from None
    session.refresh(up)
    return up
```

(Seção do `_aplica_perfil_import` e o restante: `update_upstream` (mesmo padrão de `update_circuit`: `model_dump(exclude_unset=True)`, valida org operadora se mudar, `_valida_nomes`, registrar, commit), `disable_upstream`, `vincular_circuito` (checa circuito existe; circuito ativo; já não vinculado a outro upstream ⇒ `ConflictError("Circuito já vinculado a um upstream.")`; `flush` + registrar), `desvincular_circuito` (remove a linha — trilha na auditoria), `upstream_do_circuito` (join por `UpstreamCircuit`), `propagar_defaults`:

```python
def propagar_defaults(session: Session, up: models.Upstream) -> list[int]:
    """Aplica defaults do upstream às sessões dos circuitos vinculados (§3.1).

    Sessões com campo explícito NÃO são sobrescritas (campo vence), salvo
    máxima_prefix quando veio da propagação anterior — ver regra:
    maximum_prefix/maximum_prefix_threshold são RECALCULADOS sempre
    (derivam do esperado×margem); LP/prepend/import_profile só quando
    a sessão está com o valor default do render (None).
    """
    alterados: list[int] = []
    for vinculo in up.circuitos:
        cir = vinculo.circuito
        margem = up.max_prefix_margin_pct / 100
        esperado = {"ipv4": up.expected_prefixes_v4, "ipv6": up.expected_prefixes_v6}
        for sessao in list_sessions(session, circuit_id=cir.id, include_disabled=False):
            esperado_afi = esperado.get(sessao.afi)
            if esperado_afi is not None:
                max_p = int(esperado_afi * (1 + margem))
                if sessao.maximum_prefix != max_p:
                    sessao.maximum_prefix = max_p
                    if sessao.maximum_prefix_threshold is None:
                        sessao.maximum_prefix_threshold = 80
                    alterados.append(sessao.id)
            if vinculo.papel == "contingencia":
                if up.contingencia_local_preference is not None and sessao.local_preference is None:
                    sessao.local_preference = up.contingencia_local_preference
                if up.contingencia_prepend is not None and sessao.prepend is None:
                    sessao.prepend = up.contingencia_prepend
            else:
                if up.entrada_local_preference is not None and sessao.local_preference is None:
                    sessao.local_preference = up.entrada_local_preference
            if sessao.import_profile_id is None:
                perfil = _perfil_import(session, PRODUTO_IMPORT_POR_TIPO[up.tipo])
                if perfil is not None:
                    sessao.import_profile_id = perfil.id
                    alterados.append(sessao.id)
    return alterados
```

_Nota:_ importar `list_sessions` de `services.bgp_sessions` e `IntegrityError` de `sqlalchemy.exc` no topo.

- [ ] **Step 4: Rodar testes PASS; commit (`feat(f5): serviço de upstreams com propagação de defaults às sessões`).**

## Task A4: Communities — tipo no catálogo + CRUD habilitado + serviço de upstream_communities

**Files:**
- Modify: `src/gerenet/domain/services/communities.py`, `src/gerenet/domain/schemas.py` (CommunityCreate/CommunityUpdate com `tipo`), `src/gerenet/api/routers/communities.py` (POST habilitado + filtro tipo)
- Create: `src/gerenet/domain/services/upstream_communities.py`
- Test: `tests/domain/test_communities_service.py` (add caso tipo/criação), `tests/domain/test_upstream_communities_service.py` (novo)

**Interfaces:**
- Consumes: modelos A1.
- Produces: `create_community(session, data, *, actor) -> Community`; `list_communities(session, *, tipo=None, include_disabled)`; `add_upstream_community(session, upstream_id, data, *, actor)`; `list_upstream_communities(session, upstream_id, *, include_disabled)`; `remove_upstream_community(session, upstream_id, community_id, *, actor)`.

- [ ] **Step 1: Testes que falham (trechos-chave)**

```python
def test_cria_comunidade_global_com_tipo(session):
    s = schemas.CommunityCreate(name="blackhole-sul", tipo="acao_blackhole", notes="v6/32 p/ Sul")
    c = communities.create_community(session, s, actor="cli")
    assert c.tipo == "acao_blackhole"


def test_upstream_community_valor_concreto(session, up):
    s = schemas.UpstreamCommunityCreate(purpose="prepend", value="65530:20:0", regiao="sul", direcao="export")
    uc = ucomm.add_upstream_community(session, up.id, s, actor="cli")
    assert uc.value == "65530:20:0"
    dupe = schemas.UpstreamCommunityCreate(purpose="prepend", value="65530:20:0", regiao="sul")
    with pytest.raises(ConflictError):
        ucomm.add_upstream_community(session, up.id, dupe, actor="cli")
```

- [ ] **Step 2: Rodar — FAIL.**

- [ ] **Step 3: Implementar**

Em `services/communities.py`: `create_community` + `list_communities(tipo=...)` com validação `tipo in COMMUNITY_TIPO`; `update_community` passa a aceitar `tipo` (schema existe para update no C3 — estender com campo opcional).
Em `schemas.py`: `CommunityCreate` (name, tipo=“padrao”, notes), `CommunityUpdate.tipo: str | None`.
Em `api/routers/communities.py`: `@router.post("")` (201) e filtro `tipo` no GET.
Em `services/upstream_communities.py`:

```python
def add_upstream_community(session, upstream_id, data, *, actor):
    up = get_upstream(session, upstream_id)
    if not up.admin_status:
        raise ConflictError(f"Upstream {up.name} desativado não recebe communities.")
    uc = models.UpstreamCommunity(upstream_id=up.id, **data.model_dump())
    session.add(uc)
    try:
        session.flush()
        registrar(session, tipo="upstream_community.create", ator=actor,
                  objeto="upstream", objeto_id=up.id,
                  antes=None, depois={"community": data.value, "purpose": data.purpose})
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("Community já cadastrada para este upstream (purpose/value/regiao).") from None
    session.refresh(uc)
    return uc
```

(remove = deletar a linha + registrar `upstream_community.remove`; list com include_disabled.)

- [ ] **Step 4: Rodar PASS; commit (`feat(f5): communities por operadora (upstream_communities) e tipo no catálogo com criação habilitada`).**

## Task A5: API routers — upstreams + ajustes de organizations/circuits/sessions/authorizations/change_requests

**Files:**
- Create: `src/gerenet/api/routers/upstreams.py`
- Modify: `src/gerenet/api/main.py` (registrar router), `src/gerenet/api/routers/organizations.py` (kind operadora no cadastro — verifica enum já aceita), `src/gerenet/api/routers/bgp_sessions.py` e `circuits.py` (expor `organization_kind` — via schema), `src/gerenet/api/routers/prefix_authorizations.py` (origin/validacao nos esquemas), `src/gerenet/api/routers/change_requests.py` (upstream_id/upstream_name nas respostas)
- Test: `tests/api/test_upstreams_router.py` (novo)

**Interfaces:**
- Consumes: serviços A3/A4.
- Produces: rotas `GET/POST /api/v1/upstreams`, `GET/PATCH /api/v1/upstreams/{id}`, `POST /{id}/circuits` (vínculo), `DELETE /{id}/circuits/{circuit_id}`, `POST /{id}/communities`, `DELETE /{id}/communities/{community_id}`; `UpstreamOut.organization_kind`.

- [ ] **Step 1: Teste que falha (exemplo)**

```python
def test_cria_upstream_router(client, org_operadora):
    resp = client.post("/api/v1/upstreams", json={
        "name": "transito-fb", "tipo": "transito", "organization_id": org_operadora.id})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "transito-fb"


def test_upstream_detail_traz_circuitos(client, up_com_circuito):
    resp = client.get(f"/api/v1/upstreams/{up_com_circuito.id}")
    assert resp.status_code == 200
    assert resp.json()["circuitos"][0]["papel"] == "principal"
```

- [ ] **Step 2: Falhar. Step 3: Implementar router seguindo `routers/circuits.py`** (mesmo molde: `SessionDep`, `Actor`, `require_actor`, try/except `ConflictError/NotFoundError/ValidationError`).

`main.py`: `from gerenet.api.routers import upstreams` + `app.include_router(upstreams.router)`.

`prefix_authorizations.py`: `origin` já é enum — garantir que `BgpPrefixAuthorizationOut` inclua `validacao` (espelho do campo). `change_requests.py`: adicionar `upstream_id`/`upstream_name` derivado (usar `cr.upstream_name`). `bgp_sessions.py`/`circuits.py` — `organization_kind`:

```python
# schemas.CircuitOut
organization_kind: str | None = None  # preenchido no router via session.get(Organization, c.organization_id).kind
```

(Router: construir o `CircuitOut.model_copy(update={"organization_kind": ...})` no `listar`/`detalhar`; ou adicionar `@property` no model — preferir o model_copy no router, como `_detalhe` já faz com pontas.)

- [ ] **Step 4: PASS + commit (`feat(f5): API de upstreams e exposição de kind/validacao/upstream_name`).**

## Task A6: CLI — `gerenet upstreams` e `gerenet upstream-communities`

**Files:**
- Create: `src/gerenet/cli/upstreams.py`
- Modify: `src/gerenet/cli/main.py` (registrar typer)
- Test: `tests/cli/test_upstreams_cli.py` (novo — com mock de `get_session` ou via `CliRunner`? Seguir o padrão dos testes de CLI existentes — verificar `tests/cli/` para o molde e usar o mesmo.)

**Interfaces:**
- Consumes: serviços A3/A4.
- Produces: `gerenet upstreams add|list|show|update|disable|circuit-add|circuit-rm`; `gerenet upstream-communities add|list|remove`.

- [ ] **Step 1: Teste exemplo (`CliRunner` no padrão da casa)**

```python
def test_upstreams_add_cli(monkeypatch, session_factory, org_operadora):
    from typer.testing import CliRunner
    runner = CliRunner()
    # Seguir o padrão de monkeypatch de get_session usado nos testes de CLI existentes
    result = runner.invoke(upstreams_cli.app, [
        "add", "--name", "cli-up", "--tipo", "transito", "--organization-id", str(org_operadora.id)])
    assert result.exit_code == 0
    assert "criado" in result.stdout
```

- [ ] **Step 2: FAIL. Step 3: Implementar `cli/upstreams.py`** seguindo o molde de `cli/circuits.py` (`get_session()`, `typer.Option`, `GerenetError` → `exit 1`, mensagens PT); `cli/main.py`: `app.add_typer(upstreams.app, name="upstreams")` + `name="upstream-communities"` para o segundo.

- [ ] **Step 4: rodar `uv run gerenet upstreams --help`; PASS; commit (`feat(f5): CLI de upstreams e upstream-communities`).**

---

# Estágio B — Render e políticas

## Task B1: `internas_prefixos()` + `naming.pfx_internas` + coluna `devices.loopback` em uso

**Files:**
- Modify: `src/gerenet/automation/naming.py` (nova função), `src/gerenet/automation/render.py` (helper + exposição), criar `src/gerenet/automation/internas.py` OU adicionar em `render.py` (preferir módulo pequeno `render` mesmo — seguir o padrão: render é o orquestrador)
- Test: `tests/automation/test_internas_prefixos.py` (novo)

**Interfaces:**
- Produces: `internas_prefixos(session) -> dict[str, list[str]]` (`{"ipv4": [...], "ipv6": [...]}`; p2p alocados (IpPrefix kind p2p reservada) + `devices.loopback` ativos); `naming.pfx_internas(afi) -> "IP-PFX-INTERNAS-<AFI>"`.

- [ ] **Step 1-2: teste + falha** — exemplo:

```python
def test_internas_prefixos_loopback_e_p2p(session, device_edge, circuito_com_p2p):
    out = internas_prefixos(session)
    assert "10.0.0.0/31" in out["ipv4"]  # p2p reservado do circuito
    assert device_edge.loopback in out["ipv4"]
```

- [ ] **Step 3: Implementar**

```python
# naming.py
def pfx_internas(afi: str) -> str:
    return f"IP-PFX-INTERNAS-{_afi_valida(afi)}"


# render.py
def internas_prefixos(session: Session) -> dict[str, list[str]]:
    """Prefixos próprios (rotas internas): loopbacks + enlaces p2p alocados ativos."""
    saida: dict[str, list[str]] = {"ipv4": [], "ipv6": []}
    for dev in session.scalars(select(models.Device).where(models.Device.admin_status.is_(True))):
        if dev.loopback:
            afi = "ipv4" if ipaddress.ip_address(dev.loopback).version == 4 else "ipv6"
            saida[afi].append(str(ipaddress.ip_network(f"{dev.loopback}/32", strict=False)))
    for ip in session.scalars(
        select(models.IpPrefix).where(
            models.IpPrefix.kind == "p2p", models.IpPrefix.status == "reservada")
    ):
        rede = ipaddress.ip_network(ip.network)
        saida["ipv4" if rede.version == 4 else "ipv6"].append(str(rede))
    for afi in saida:  # ordena e normaliza (sem dups)
        saida[afi] = sorted(set(saida[afi]))
    return saida
```

- [ ] **Step 4: PASS; commit (`feat(f5): rotas internas — helper internas_prefixos e nome de prefix-list`).**

## Task B2: Templates — `community_filter.j2` + `route_policy_import.j2` (produtos up-*) + `route_policy_export.j2` (anúncio ao trânsito)

**Files:**
- Create: `src/gerenet/automation/templates/huawei_vrp/community_filter.j2`
- Modify: `.../route_policy_import.j2`, `.../route_policy_export.j2`
- Test: `tests/automation/test_templates.py` (novos casos)

**Interfaces:**
- Consumes: contexto do render (nomes/nome da lista; aplicações).
- Produces: templates renderizáveis com os parâmetros: import → `{"nome", "afi", "lista", "local_preference", "produto", "foo": False}`, `"deny_communities": [str...]`; export upstream → `{"nome", "afi", "lista", "asn_local", "med", "prepend", "aplicacoes": [{"tipo","valor","regiao"}]}`.

- [ ] **Step 1: Teste que falha** (conferir o template atual e a assinatura usada) — após ler `route_policy_import.j2`/`route_policy_export.j2` atuais, escrever:

```python
def test_import_up_full_rejeita_bogons_e_info_community(template_env):
    texto = template_env.get_template("route_policy_import.j2").render(
        nome="RP-64512-IMPORT-V4", afi="ipv4", lista="IP-PFX-64512-IN-V4",
        local_preference=None, produto="up-full",
        deny_communities=["65530:666:0"], fail_safe=False)
    assert "if-match community-filter" in texto.replace(" -", "-") or "if-match community-filter" in texto
    assert "deny" in texto
    assert "local-preference" not in texto


def test_import_sem_perfil_fail_safe(template_env):
    texto = template_env.get_template("route_policy_import.j2").render(
        nome="RP-64512-IMPORT-V4", afi="ipv4", lista=None, local_preference=None,
        produto=None, deny_communities=[], fail_safe=True)
    assert "deny" in texto and "permit" not in texto
```

- [ ] **Step 2: FAIL; Step 3: Implementar templates** — `route_policy_import.j2` com Variantes:

```jinja2
route-policy {{ nome }} permit node 10
{% if fail_safe %}
 deny
{% else %}
 {% if lista %} if-match ip-prefix {{ lista }} {% endif %}
 {% for c in deny_communities %} if-match community-filter {{ c }} {% endif %}
 ... (seguir o template atual; acima conforme o produto: up-default ⇒ apenas `0.0.0.0/0` na lista; up-parcial ⇒ default + comunidade; up-full ⇒ lista de proteção + accept)
 apply local-preference X quando local_preference definido (aplica se usada)
{% endif %}
```

(Ler o `route_policy_import.j2` atual como base — ele expõe `nome/afi/lista/local_preference`; a nova variante usa `produto` para decidir o corpo e `deny_communities` para os `if-match` de bloqueio. `community_filter.j2`:

```jinja2
ip community-filter {{ nome }} permit {{ valor }}
```

`route_policy_export.j2`: variante `aplicacoes`: para cada `aplicacao` (tipo=prepend|blackhole|lp): `if-match ...` (para prepend/lp: aplicar community condicional — o match de região fica documentado no comentário quando `regiao` for definido — *ex.:* `apply community {{ valor }}`), manter o corpo atual com `lista` e `med/prepend/asn_local`.)

- [ ] **Step 4: rodar goldens existentes (`tests/automation/test_templates.py`) + novos; PASS; commit (`feat(f5): templates de community-filter e variantes upstream no import/export`).**

## Task B3: Render — `_bloco_import`/`_bloco_export` para sessões de upstream

**Files:**
- Modify: `src/gerenet/automation/render.py` (funções novas: `_eh_upstream(session, sessao) -> bool` via `services.upstreams.upstream_do_circuito`; `_bloco_import_upstream`; `_bloco_export_upstream`; despacho em `render_desejado`)
- Test: `tests/automation/test_render_upstream.py` (novo; reusar fixtures)

**Interfaces:**
- Consumes: `internas_prefixos`, `upstream_do_circuito`, `naming.pfx_internas`, template B2; `list_upstream_communities`.
- Produces: blocos `prefix_list` (internas/clientes para export; proteções para import), `community_filter`, `route_policy_import|export` (com dedup via `_apensa_definicao`), referências no peer por existência de definição.

- [ ] **Step 1: Teste que falha**

```python
def test_render_upstream_full_import_com_protecoes(session, up_com_sessao_upfull, edge_device):
    # sessão de circuito vinculado ao upstream; produto up-full; info-community bloquear cadastrada
    res = render_desejado(session, edge_device.id)
    textos = [b.texto for b in res.blocos]
    assert any("if-match community-filter" in t for t in textos)
    assert any("IP-PFX-64512-IN-V4" in t for t in textos)  # prefix-list de proteção
    rp = next(t for t in textos if "route-policy RP-64512-IMPORT-V4" in t)
    assert "deny" in rp


def test_render_upstream_export_anuncia_internas(session, up_com_sessao_upfull, edge_device, circuito_com_p2p):
    res = render_desejado(session, edge_device.id)
    textos = "".join(b.texto for b in res.blocos)
    assert "IP-PFX-INTERNAS-V4" in textos
```

- [ ] **Step 2: FAIL; Step 3: Implementar**

```python
def _eh_upstream(session, sessao) -> models.Upstream | None:
    from gerenet.domain.services.upstreams import upstream_do_circuito
    return upstream_do_circuito(session, sessao.circuit_id)


def _bloco_import_upstream(session, circuito, sessao, definidas, up) -> tuple[list[BlocoRender], str | None]:
    afi = sessao.afi
    perfil = get_policy_profile(session, sessao.import_profile_id) if sessao.import_profile_id else None
    if perfil is None:
        # fail-safe §4.1: deny explícito, nunca accept-all
        nome_rp = naming.rp_import(sessao.asn_remote, afi)
        bloco = BlocoRender("route_policy_import", "session", sessao.id,
                            _render_template("route_policy_import", {
                                "nome": nome_rp, "afi": afi, "lista": None,
                                "local_preference": sessao.local_preference,
                                "produto": None, "deny_communities": [], "fail_safe": True}).splitlines())
        return [bloco], nome_rp
    produto = perfil.name
    if produto not in {"up-full", "up-parcial", "up-default"}:
        return [], None
    # lista de proteção: autorizadas de clientes + internas (up-full) etc. (conforme §4.1)
    autorizadas = [a for a in list_authorizations(session) 
                   if a.family == afi and a.admin_status and a.organization.kind != "operadora"]
    internas = internas_prefixos(session)[afi]
    entradas = [{"index": 10 * (i + 1), "prefixo": p} for i, p in enumerate(internas + [a.prefix for a in autorizadas])]
    cmd_pl = _render_template("prefix_list", {"nome": naming.pfx_in(sessao.asn_remote, afi), "afi": afi, "entradas": entradas}).splitlines()
    # community-filters de bloqueio (info + bloquear + direcao import/ambos)
    deniers = [uc.value for uc in up.comunidades if uc.purpose == "info" and uc.bloquear
               and uc.admin_status and uc.direcao in ("import", "ambos")]
    cf_blocos = []
    for i, valor in enumerate(deniers):
        nome_cf = f"CF-{sessao.asn_remote}-BLK-{i + 1}"
        cf_blocos.append(BlocoRender("community_filter", "session", sessao.id,
            _render_template("community_filter", {"nome": nome_cf, "valor": valor}).splitlines()))
    rp = _render_template("route_policy_import", {
        "nome": naming.rp_import(sessao.asn_remote, afi), "afi": afi,
        "lista": naming.pfx_in(sessao.asn_remote, afi),
        "local_preference": sessao.local_preference, "produto": produto,
        "deny_communities": [f"CF-{sessao.asn_remote}-BLK-{i + 1}" for i, _ in enumerate(deniers)],
        "fail_safe": False}).splitlines()
    blocos = cf_blocos
    _apensa_definicao(blocos, definidas, BlocoRender("prefix_list", "session", sessao.id, cmd_pl),
                      ("prefix_list", naming.pfx_in(sessao.asn_remote, afi)))
    _apensa_definicao(blocos, definidas, BlocoRender("route_policy_import", "session", sessao.id, rp),
                      ("route_policy_import", naming.rp_import(sessao.asn_remote, afi)))
    return blocos, naming.rp_import(sessao.asn_remote, afi)
```

`_bloco_export_upstream`: prefix-list `IP-PFX-INTERNAS-<AFI>` (internas + autorizadas de clientes ativas) + `RP-<ASN>-EXPORT-<AFI>` com `aplicacoes` (prepend/lp/blackhole de `up.comunidades` com propósito correspondente, `direcao export/ambos`) + dedup. Despacho em `render_desejado`: para cada sessão, `up = _eh_upstream(...)`; import = `_bloco_import_upstream` se up, senão atual; export idem.

- [ ] **Step 4: PASS (suíte de render/divergência e goldens continuam verdes); commit (`feat(f5): render de upstream — import com proteções e export de internas+clientes`).**

## Task B4: Pagar a dívida `default_internas`/`parcial` (render para clientes)

**Files:**
- Modify: `src/gerenet/automation/render.py` (`_bloco_export` branch final)
- Test: `tests/automation/test_templates.py` (atualizar o assert de dívida → agora renderiza)

**Interfaces:**
- Consumes: `internas_prefixos` (B1), `naming.pfx_produto`.
- Produces: `default_internas` → prefix-list `IP-PFX-DEFAULT-INTERNAS-<AFI>` contendo default + internas + autorizadas da org da sessão; `parcial` → internas + autorizadas da org (produto “parcial” = internas + clientes selecionados — por ora: internas + autorizadas da org da sessão; se vazio, comentário-dívida).

- [ ] **Step 1: teste (modifica o atual)** — em `tests/automation/test_templates` e/ou um teste de render novo: produto `default_internas` em sessão de cliente agora deve emitir prefix-list (sem comentário de dívida).

- [ ] **Step 2: FAIL (hoje retorna comentário)**. **Step 3: implementar** o branch (usar `internas_prefixos()` + autorizadas da org do circuito da sessão + dedup `_apensa_definicao`).

- [ ] **Step 4: PASS + commit (`feat(f5): render de default_internas/parcial com rotas internas (dívida ciclo B paga)`).**

## Task B5: Variação anormal — contagem vs esperado×margem na reconciliação/coleta

**Files:**
- Modify: `src/gerenet/automation/reconcile.py` (nova checagem `bgp.variação_anormal` no `reconciliar_device`), `src/gerenet/api/routers/reconciliation.py` (nada — lista itens já genérica), dashboard/metrics se existir
- Test: `tests/automation/test_reconcile.py` (novo item)

**Interfaces:**
- Consumes: `_recursos` do snapshot (`bgp_peers` com `prefixos`— conferir chave real no parser/merge e usar a mesma), `expected_prefixes`/margem da sessão/upstream.
- Produces: `ReconcileItem(tipo="bgp.anomalia_prefixos", severidade="alerta", esperado=..., encontrado=..., acao="...)` por peer quando `|contagem - esperado| > margem`; quando não há esperado cadastrado, compara com o histórico do próprio snapshot anterior (K=2 coletas anteriores; variação > 50% — default constante de módulo).

- [ ] **Step 1: teste** (montar snapshot com `bgp_peers` de contagem alta vs esperado do upstream):

```python
def test_reconcile_acusa_variacao_anormal_acima_da_margem(session, up_com_sessao, edge_device, snapshot_bgp_ok, monkeypatch):
    # snapshot com peer contagem 1000; sessão com maximum_prefix 1100 e esperado 1000->margem 10%
    ...
    items = reconciliar_device(session, edge_device.id, snapshot.id)
    assert any(i.tipo == "bgp.anomalia_prefixos" and i.severidade == "alerta" for i in items)
```

- [ ] **Step 2: FAIL; Step 3: implementar** (leia `reconcile.py` L73+ e siga o shape `_item(...)`: para cada peer de sessão de upstream, `esperado = maximum_prefix` (ou expected×margem via upstream) e `encontrado = contagem coletada`; diferença > margem ⇒ item alerta. Sem esperado: histórico (últimas coberturas com contagem) e variação > 50% default ⇒ também alerta.)

- [ ] **Step 4: PASS + commit (`feat(f5): alerta de variação anormal de prefixos na reconciliação`).**

---

# Estágio C — CR escopo `upstream`

## Task C1: `automation/upstream.py` — plano de provision/remoção agregado + pre/post-checks

**Files:**
- Create: `src/gerenet/automation/upstream.py`
- Test: `tests/automation/test_upstream_automation.py` (novo)

**Interfaces:**
- Consumes: `changes.PlanoDevice`, `changes.plan_provision`/`plan_remocao`, `removal.blocos_remocao`, `render_desejado`, snapshots, `runner._chaves` (só para shape), `upstreams` service.
- Produces: `plan_provision_upstream(session, up) -> list[changes.PlanoDevice]`; `plan_remocao_upstream(session, up)`; `valida_pre_upstream(session, up, device) -> list[dict]`; `valida_pos_upstream(session, up, snapshot) -> list[dict]`.

- [ ] **Step 1: Teste que falha**

```python
def test_plan_provision_upstream_agrega_por_device(session, up_com_2_circuitos, edge_device):
    plano = plan_provision_upstream(session, up_com_2_circuitos)
    assert len(plano) == 1  # 2 circuitos no mesmo edge
    plano_edge = plano[0]
    assert all(b["objeto_id"] in {ids das sessões dos 2 circuitos} or b["tipo"] == "community_filter" for b in plano_edge.blocos)
```

- [ ] **Step 2: FAIL; Step 3: Implementar**

```python
def _ids_upstream(session, up) -> set[int]:
    """Sessões dos circuitos vinculados (devices/sessões com objeto_origin upstream)."""
    ids: set[int] = set()
    for vin in up.circuitos:
        for s in list_sessions(session, circuit_id=vin.circuit_id):
            ids.add(s.id)
    return ids


def plan_provision_upstream(session, up):
    if not up.admin_status:
        raise ConflictError(...)
    ids = _ids_upstream(session, up)
    if not ids:
        raise ValidationError("Upstream sem sessões ativas — cadastre circuitos e sessões antes de planejar.")
    devices = sorted({s.device_id for s in list_sessions(session, circuit_id=vin.circuit_id)
                      for vin in up.circuitos})
    plano = []
    for device_id in devices:
        resultado = render.render_desejado(session, device_id)
        snap = _ultimo_snapshot_ok(session, device_id)  # importar de changes (privada) ou replicar
        recursos = (snap.resources or {}) if snap is not None else {}
        texto = removal.texto_backup(snap)
        tem_recursos = all(k in recursos for k in changes._RECURSOS_MINIMOS)
        blocos = [
            changes._bloco_para_plano(b, "create")
            for b in resultado.blocos
            if b.tipo != "comentario"
            and (b.objeto_id in ids or b.tipo == "community_filter")
            and (not tem_recursos or not changes._ja_existe(b, recursos, texto))
        ]
        plano.append(changes.PlanoDevice(device_id=device_id, blocos=blocos,
                    baseline_snapshot_id=snap.id if snap is not None and tem_recursos else None,
                    aviso=None if tem_recursos else changes._SEM_RECURSOS_AVISO))
    return plano
```

`plan_remocao_upstream`: para cada circuito (na ordem `ordem`), `changes.plan_remocao(session, circuito)` e **mistura por device** (concatenar blocos; se algum circuito não tiver sessões ⇒ `ValidationError` para não gerar plano parcial). `valida_pre_upstream`/`valida_pos_upstream`:

```python
def valida_pos_upstream(session, up, snapshot) -> list[dict]:
    """§13 pós-check upstream: para cada sessão do upstream no device — peer
    Established, contagem dentro de [esperado×(1±margem)], sem peers novos caídos."""
    itens = []
    for vin in up.circuitos:
        for s in list_sessions(session, circuit_id=vin.circuit_id):
            if s.device_id != snapshot.device_id:
                continue
            linha = pegar_peer(recursos, s.remote_address, s.afi)  # helper local: linha["peer"] == ...
            if linha is None:
                itens.append({"tipo": "upstream.peer_ausente", "severidade": "erro", ...})
                continue
            if linha.get("estado") != "established":
                itens.append({"tipo": "upstream.peer_nao_estabelecido", "severidade": "erro", ...})
            cont = linha.get("prefixos")  # conferir chave real do parser (merge.py)
            esperado = s.maximum_prefix
            if esperado and cont is not None and abs(cont - esperado) > esperado * 0.2:
                itens.append({"tipo": "upstream.contagem_fora_esperado", "severidade": "alerta", ...})
    return itens
```

- [ ] **Step 4: PASS + commit (`feat(f5): plano e checks de CR upstream (provision/remoção/pos)`).**

## Task C2: `domain/services/change_requests.py` — branch `_create_upstream`, `_replaneja`, rollback/reconcile por escopo

**Files:**
- Modify: `src/gerenet/domain/services/change_requests.py` (L61-99 create; L245-280 reconciliar; L283-344 gerar_rollback; L259/293 guards)
- Test: `tests/domain/test_change_requests_upstream.py` (novo)

**Interfaces:**
- Consumes: `automation/upstream` (C1), `Upstream` model, `get_upstream`.
- Produces: CR com `escopo="upstream"` e `upstream_id`; `reconciliar`/`gerar_rollback` suportam upstream (rollback/reconciliação de CR upstream = agregação por device, mesma mecânica de circuito); guards do escopo `!= circuito` ficam **por escopo real** (`{"l2vc": "…", "vsi": "…"}` — mensagem citando o escopo).

- [ ] **Step 1: Teste**

```python
def test_create_cr_upstream_plano_na_criacao(session, up_com_2_circuitos, actor):
    cr = create_change_request(session, schemas.ChangeRequestCreate(
        escopo="upstream", upstream_id=up.id, acao="provision", motivo="subir trânsito", criticidade="alta"),
        ator_id=actor.id, actor="cli")
    assert cr.escopo == "upstream" and cr.upstream_id == up.id
    assert cr.steps and all(s.plano_json for s in cr.steps)


def test_create_cr_upstream_sem_sessoes_eh_plano_vazio(session, up_sem_circuitos):
    with pytest.raises(PlanoVazio):
        create_change_request(...)
```

- [ ] **Step 2: FAIL; Step 3: Implementar**

```python
def _create_upstream(session, data, *, ator_id=None, actor="cli"):
    from gerenet.automation import upstream as up_auto
    from gerenet.domain.services.upstreams import get_upstream
    up = get_upstream(session, data.upstream_id)
    if not up.admin_status:
        raise ConflictError(f"Upstream {up.name} desativado não recebe mudanças.")
    plano = (up_auto.plan_provision_upstream(session, up) if data.acao == "provision"
             else up_auto.plan_remocao_upstream(session, up))
    cr = models.ChangeRequest(circuit_id=None, upstream_id=up.id, escopo="upstream",
                              acao=data.acao, criticidade=data.criticidade, motivo=data.motivo,
                              ticket=data.ticket, solicitante_id=ator_id, status="rascunho")
    session.add(cr); session.flush()
    _cria_steps(session, cr, plano)
    if not cr.steps:
        raise PlanoVazio("Upstream sem circuitos/sessões ativas — cadastre antes de planejar.")
    registrar(...); session.commit(); session.refresh(cr)
    return cr
```

`create_change_request` despacha `data.escopo == "upstream"` antes do circuito; `_replaneja` ganha branch por escopo (upstream → `up_auto.plan_provision_upstream`) ; `reconciliar`/`gerar_rollback`: `if cr.escopo != "circuito":` → trocar por mapa de mensagem por escopo e, para upstream, executar a mecânica normal (agregação).

- [ ] **Step 4: PASS + commit (`feat(f5): CR escopo upstream com plano na criação, rollback e reconciliação`).**

## Task C3: Worker/runner — chaves de re-diff e pre/post-check por escopo

**Files:**
- Modify: `src/gerenet/automation/runner.py` (L92-110 `_CHAVES_POR_ESCOPO` + L593-660 pre/post; L794), `src/gerenet/worker/tasks.py` (passagem do escopo — verificar como o re-diff usa; se `changes.plan_provision` for chamado por circuito, adaptar para upstream via helper `plan_do_escopo`)
- Test: `tests/automation/test_runner_upstream.py` (novo)

**Interfaces:**
- Consumes: C1/C2.
- Produces: escopo `upstream` com chaves iguais a `circuito` (`interfaces`, `bgp_peers`) e pré-check `valida_pre_upstream` + pós-check `valida_pos_upstream` no fluxo.

- [ ] **Step 1-3:** adicionar em `_CHAVES_POR_ESCOPO["upstream"] = _CHAVES_POR_ESCOPO["circuito"]`; nos pontos `if cr.escopo == "l2vc":` (L603, L655, L794) generalizar para `if cr.escopo in ("l2vc", "upstream"):` chamando `valida_pre_upstream`/`valida_pos_upstream` para upstream; verificar o re-diff por escopo (o código chama `changes`/`l2vc` — adicionar `if cr.escopo == "upstream": plano = up_auto.plan_provision_upstream(...)`).

- [ ] **Step 4: PASS + commit (`feat(f5): runner/worker escopo upstream (re-diff, pré e pós-check)`).**

## Task C4: API/CLI change-requests por escopo upstream + detalhe

**Files:**
- Modify: `src/gerenet/api/routers/change_requests.py` (query param/valores; já aceita escopo — confirmar os literais), `src/gerenet/cli/change_requests.py` (opção `--escopo upstream`/`--upstream-id`)
- Test: `tests/api/test_change_requests_upstream.py` (ex.: POST CR escopo upstream 202; list com `escopo=upstream` traz `upstream_name`)

- [ ] **Step 1-3:** seguir o teste do fumo D (solicitar como admin; 202 + enqueue) e CLI: `gerenet change-requests add --escopo upstream --upstream-id N --acao provision --motivo "..."`.

- [ ] **Step 4: PASS + commit (`feat(f5): API/CLI de CR com escopo upstream`).**

---

# Estágio D — Web (páginas upstream, communities, dashboard, e2e)

> Padrões F4: páginas em `web/src/pages/`, rotas em `App.tsx`, API client em `web/src/api/client.ts` + `types.ts` + `hooks.ts`, tooltips em `web/src/help.ts`. Seguir `MplsL2vcDetail.tsx`/`MplsDomains.tsx` como molde de lista/detalhe e dialogs.

## Task D1: types/hooks + rotas + nav

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/App.tsx`, nav (onde MPC pages estão agrupadas — seguir o grupo “MPLS”)
- Test: `web/src/components/componentes.test.tsx`/`npm run build` (validação de help.ts)

**Interfaces:**
- Produces: `Upstream`, `UpstreamCommunity`, `UpstreamDetail` tipos; hooks `useUpstreams`, `useUpstream(id)`, `useUpstreamCreate/Update`, `useUpstreamCommunities(id)`, `useAddUpstreamCommunity`, `useRemoveUpstreamCommunity` (seguir `hooks.ts` padrão com `apiFetch`).

- [ ] **Step 1-3:** seguir o shape de `MplsDomain`/`MplsL2vc` para `Upstream`:

```ts
export interface Upstream {
  id: number; name: string; tipo: string; capacity: string | null;
  priority: number | null; cost: string | null; organization_id: number;
  organization_name?: string | null; expected_prefixes_v4: number | null;
  expected_prefixes_v6: number | null; max_prefix_margin_pct: number;
  rpki_enabled: boolean; entrada_local_preference: number | null;
  contingencia_local_preference: number | null; contingencia_prepend: number | null;
  contingencia_notes: string | null; admin_status: boolean;
}
export interface UpstreamCircuitLink { id: number; circuit_id: number;
  circuito_desc?: string; papel: "principal" | "contingencia"; ordem: number; }
export interface UpstreamDetail extends Upstream { circuitos: UpstreamCircuitLink[]; comunidades: UpstreamCommunity[]; }
```

Rotas: `/upstreams`, `/upstreams/:id`; nav item “Upstreams” (grupo onde “MPLS” está).

- [ ] **Step 4: `cd web && npm run build` PASS + commit (`feat(f5): web — tipos, hooks, rotas e nav de upstreams`).**

## Task D2: Página lista `/upstreams` (+ dialogs criar/editar/desativar)

**Files:**
- Create: `web/src/pages/Upstreams.tsx` (+ `Upstreams.test.tsx`)
- Modify: `web/src/help.ts` (chaves `upstream.*`)

**Interfaces:**
- Consumes: D1.
- Produces: tabela (nome, operadora, tipo badge, circuitos/ordem, expected v4/v6, status) com `Modal` de criar/editar seguindo `MplsDomains.tsx`; chamadas `useUpstreams`/`useUpstreamCreate/Update`.

- [ ] **Step 1-3:** seguir `MplsDomains.tsx` (lista + Modal `UpstreamForm` com campos do tipo `UpstreamCreate` — campos numeréricos com `form.getField`.. — seguir implementação existente de `MplsDomainForm`). Tooltips em `help.ts` (ex.: `"upstream.max_prefix_margin_pct": "Margem percentual sobre o esperado de prefixos (0-100) — o maximum-prefix da sessão vira esperado × (1+margem)."`, `"upstream.tipo": "trânsito, IX, PNI ou contingência."`, `"upstream_community.value": "Valor concreto da community (ex.: 65530:20:0)."`).

- [ ] **Step 4: `npm run build && npm run test` PASS + commit (`feat(f5): web — página de upstreams com criar/editar`).**

## Task D3: Página detalhe `/upstreams/:id` (matriz, communities, solicitar mudança)

**Files:**
- Create: `web/src/pages/UpstreamDetail.tsx` (+ teste)
- Modify: `web/src/pages/CircuitDetail.tsx` e `BgpSessionDetail.tsx` (botão “Solicitar mudança” com escopo upstream quando aplicável — segue padrão já existente do circuito; manter)
- Test: teste de componente (render de matriz + dialogs de community e de `change-request`)

**Interfaces:**
- Consumes: D1/D2.
- Produces: detalhe com: card perfil (tipo/capacidade/prioridade/custo), **matriz principal × contingência** (circuitos com papel/ordem + estados das sessões), tabela `upstream_communities` (purpose/value/regiao/direção/bloquear + add/remover em dialog), “Solicitar mudança” (reusa modal de CR do `CircuitDetail` — verificar se é componente reutilizável; senão copiar o shape do de circuito/l2vc), exibição de `validacao` nas autorizações.

- [ ] **Step 1-3:** seguir `MplsL2vcDetail.tsx` (detalhe + ações + modais).

- [ ] **Step 4: build/test PASS + commit (`feat(f5): web — detalhe de upstream com matriz, communities e solicitar mudança`).**

## Task D4: Badges e dashboard + comunidades (tipo/criação na página)

**Files:**
- Modify: `web/src/pages/Circuits.tsx`/`BgpSessions.tsx` (badge “upstream” quando `organization_kind === "operadora"`), `web/src/pages/Dashboard.tsx` (card “Upstreams” — total ativos × por tipo e alertas de variação recentes; seguir shape dos cards existentes), `web/src/pages/Communities.tsx` (coluna `tipo` + criação via dialog)
- Test: `Dashboard.test.tsx`, `Communities.test.tsx`

- [ ] **Step 1-3:** badge: `{c.organization_kind === "operadora" && <span className="badge-upstream">upstream</span>}`; card: mínima contagem (`useUpstreams()`; `Upstreams ativos: N`) + no card de divergências as `bgp.anomalia_prefixos` já aparecem automaticamente (via reconciliation GET — confirmar). Communities: `tipo` no form/dialog (select com os 6 valores) e na tabela.

- [ ] **Step 4: build/test PASS + commit (`feat(f5): web — badges, card de upstreams no dashboard e tipo/criação no catálogo de communities`).**

## Task D5: e2e fumo `upstream.spec.ts`

**Files:**
- Create: `web/e2e/upstream.spec.ts`; Modify: `web/e2e/setup.ts` (seed de operadora + upstream + circuito upstream + sessão — **idempotente** via API/CLI como os demais objetos)
- Test: `cd web && npm run test:e2e` (criar `gerenet_e2e` migrado antes — ver `web/e2e/README.md`)

- [ ] **Step 1-5:** seguir `web/e2e/mpls.spec.ts`: loga como `admin`; navega `/upstreams`; cria operadora (org kind) via página de organizações; cria upstream (nome, tipo transito, operadora); vincula circuito (criar circuito com org operadora via UI/API como os seeds); adiciona community (prepend/sul); **solicitar CR** (como admin) e **aprovar como `e2e-aprovador`** correspondente; asserta elementos-chave (título, linhas da matriz, status da CR). Seed idempotente adicionado a `setup.ts` (padrão dos existentes: checar se existe antes de POST).

- [ ] **Step 6: `npm run test:e2e` PASS + commit (`test(e2e): fumo de upstream — criar, vincular, comunidade e CR`).**

---

# Estágio E — IRR/RPKI e documentação

## Task E1: `automation/irr.py` — consulta whois com cache (`irr_cache`)

**Files:**
- Create: `src/gerenet/automation/irr.py`
- Test: `tests/automation/test_irr.py` (mock de subprocess)

**Interfaces:**
- Produces: `consultar(source: str, key: str, *, ttl_horas: int = 24) -> dict` (payload: `{"asns": [...], "prefixos": [...]}`; usa `subprocess.run(["whois", f"as{key}" se ASN, "-h", ...])` se `key` for AS-SET: `whois -h whois.radb.net <as-set>`; parse por regex `^route:\s*(\S+)`, `^origin:\s*AS(\d+)`, `^member-of` etc.; cache em `irr_cache` com `expires_at = now + ttl`; falha de rede ⇒ `IrrError` com aviso (fail-soft: retorna último cache se vivo; senão sobe para o caller tratar).

- [ ] **Step 1-3:** implementar com teste usando `monkeypatch` em `subprocess.run` (castro de saída whois real de exemplo — incluir no teste case `route: 180.10.0.0/16 origin: AS64512`).

- [ ] **Step 4: PASS + commit (`feat(f5): consulta IRR com cache (irr.py)`).**

## Task E2: `automation/rpki.py` — sincronização de ROAs + validação consultiva

**Files:**
- Create: `src/gerenet/automation/rpki.py`; `src/gerenet/config.py` (setting `rpki_roas_file: str | None` + env `GERENET_RPKI_ROAS_FILE`)
- Test: `tests/automation/test_rpki.py`

**Interfaces:**
- Produces: `sincronizar_roas(session, caminho: str) -> int` (parse do JSON rpki-client: `{"roas": [{"prefix":…, "maxLength":…, "asn":…, "validUntil":…}]}`; upsert em `roas` — remover linhas órfãs do source e reinserir (uma transação); retorna nº de ROAs) e `validar_origem(session, prefixo, asn) -> str` (`ok|diverge|desconhecida`; prefixo mais específico que ROA → `diverge`; sem ROA → `desconhecida`).

- [ ] **Step 1-3:** implementar com testes (JSON de exemplo; idempotência: 2ª sync não duplica; órfãs removidas).

- [ ] **Step 4: PASS + commit (`feat(f5): sincronização de ROAs do rpki-client e validação de origem consultiva`).**

## Task E3: autorizações com origem irr/rpki + `validacao` exposta

**Files:**
- Modify: `src/gerenet/domain/services/prefix_authorizations.py` (validar origin enum; `validacao` setada/default `nao_verificada` para irr/rpki; `revalidar_autorizacoes(session)` chamada após sync de ROAs — atualiza `validacao` via `validar_origem`), `src/gerenet/api/routers/prefix_authorizations.py` (campo `validacao` nas respostas + origem aceita), `src/gerenet/cli/prefix_authorizations.py` (opções `--origin irr|rpki`)
- Test: `tests/domain/test_prefix_authorizations_irr_rpki.py`

**Interfaces:**
- Consumes: E1/E2.
- Produces: autorizações com `origin in ("manual","irr","rpki")` e `validacao` (`nao_verificada` para origem irr/rpki; recalculada).

- [ ] **Step 1-3:** regra: origem `irr`/`rpki` só é aceita com `notes` não vazios? — NÃO (simplificação aprovada §10.4): basta o cadastro autenticado; o `validacao` nasce `nao_verificada` e é atualizada por `revalidar_autorizacoes` (chamado ao final de `sincronizar_roas` e por CLI `gerenet rpki sync`), e exibida na web (D3) e na API.

- [ ] **Step 4: PASS + commit (`feat(f5): autorizações com origem IRR/RPKI e validação consultiva exposta`).**

## Task E4: CLI `gerenet rpki sync` + `gerenet irr query` + jobs

**Files:**
- Create: `src/gerenet/cli/rpki.py` (ou integrar em `cli/prefix_authorizations.py` — preferir arquivo próprio `cli/rpki.py`)
- Modify: `src/gerenet/cli/main.py`
- Test: `tests/cli/test_rpki_cli.py`

- [ ] **Step 1-3:** `gerenet rpki sync --file <path>`; `gerenet irr query <as-set|asn> [--source radb]`; registrar em `main.py`. (Nota: enfileirar job para F6 — por ora rodar síncrono no CLI.)

- [ ] **Step 4: PASS + commit (`feat(f5): CLI rpki sync e irr query`).**

## Task E5: Documentação — runbook de validação + wiki upstream real + estado do repositório

**Files:**
- Create: `docs/runbook-validacao-upstream.md`; Modify: `docs/wiki/em-breve/upstreams.md` → mover para `docs/wiki/upstreams.md` (`em_breve: false`), e a página `/wiki` passa a mostrá-la real; `CLAUDE.md` (seção “clico/estado” — atualizar com a F5 como nas fases anteriores)
- Test: `web/e2e/wiki.spec.ts` deve ser ajustado se pinar página “em breve” (ver commit 939146d — repontar se necessário); `npm run test:e2e`.

- [ ] **Step 1-3:** seguir o padrão do runbook da fase 4 (`docs/runbook-validacao-switch-mpls.md`): somente leitura → geração sem execução → teste em circuito/edge não crítico com aprovação; sem lab (decisão 2026-09-07). Conteúdo da wiki: copiar o texto da página antiga + adicionar o que passou a existir (entidades operadora/upstream, communities por operadora, CR upstream, IRR/RPKI consultivos).

- [ ] **Step 4: `cd web && npm run build && npm run test` PASSA; e2e (`npm run test:e2e`) PASSA` + commit (`docs(f5): runbook de validação upstream, wiki real e estado do repositório`).**

## Task E6: Fechamento — suíte completa + graphify update + revisão

- [ ] **Step 1:** `uv run pytest -q` (banco dev + test), `uv run ruff check src tests`, `cd web && npm run build && npm run test`, e2e (`npm run test:e2e` com banco `gerenet_e2e`).
- [ ] **Step 2:** `graphify update .` (rule do projeto — manter o grafo corrente).
- [ ] **Step 3:** revisar os itens parkados da fase 4 que a spec mandou incorporar: guarda por escopo com mensagem real (C2), e conferir se `change_requests` da CLI listam `upstream None` em vez de eco de `upstream_name` para escopo upstream (cosmético, M-T8-2 — se afetar, corrigir no C4).
- [ ] **Step 4:** commit final: `chore(f5): encerramento — suíte completa e grafo atualizado`.
