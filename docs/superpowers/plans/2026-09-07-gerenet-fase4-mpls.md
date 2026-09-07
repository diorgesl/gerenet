# Fase 4 — MPLS nos switches (gerenet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar os itens MPLS do MVP (§23): domínios MPLS/LDP, serviço **L2VC** de dois switches (provisionar e remover via **uma única change request** com 2 steps, pós-validação) e **consulta de VSI** (modelo + estado coletado, sem config).

**Architecture:** Estender os padrões existentes. Modelos novos (`mpls_domains`, `mpls_domain_members`, `l2vc_services`, `service_endpoints`, `vsi_services`, `vsi_members`) + VLANs de AC reusando `vlans` com `kind='mpls_ac'` e **escopo por device** (índices parciais); IDAM simples (UNIQUEs + helpers `proximo_vc_id`/`proximo_vsi_id`/`reservar_vlan_ac`, sem tabela `allocations`); `ChangeRequest` generalizado (`circuit_id` nullable + `escopo` + `l2vc_id`, máquina de estados intacta); render/plano em `automation/l2vc.py` (templates Jinja2 novos, diff por bloco padrão `changes.py`); runner **escopo-aware** (gate de re-diff e setup por escopo — documentado no spec §7 como ajuste); coletores/parsers TextFSM novos (mpls_ldp_peer, l2vc, vsi); API/CLI/web no padrão dos demais routers/groups; validação em equipamento real via runbook (§10).

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 (Mapped/mapped_column) + Alembic + Pydantic v2 + Typer + RQ/Redis + Netmiko + Jinja2 (existente) + React/Vite/React Query + Vitest + Playwright.

**Spec:** [docs/superpowers/specs/2026-09-07-gerenet-fase4-mpls-design.md](2026-09-07-gerenet-fase4-mpls-design.md) — o executor lê o spec junto do plano; regras divergentes: o spec ganha. **As duas notas "pós-escrita" do spec §7 são normativas** (capabilities materializado nesta fase; runner escopo-aware).

## Global Constraints

- **Idioma PT-BR** em mensagens de erro, docstrings, eventos de auditoria, textos de UI e commits.
- **Nomes VRP via `gerenet.automation.naming`** (nunca hardcode): novo `naming.vsi_nome(name_logico, vsi_id)` → `VSI-<SIGLA>-<ID>` (≤63 chars, maiúsculas, `-`); subinterface de AC via `naming.subinterface(interface, vid)`.
- **Escopo de VLAN MPLS é por DEVICE**: mesmas (site, vid) entre devices do mesmo POP são legítimas; só o mesmo (device, vid) é proibido (índice parcial `device_id IS NOT NULL`). Validadores de circuito (`ipam._primeiro_vid`) filtram `device_id IS NULL`.
- **`devices.capabilities`** (JSON, default `[]`) é **adicionado nesta fase** (o B2 não o materializou; spec principal §5 exige capacidades por equipamento). `flow_label` só renderiza se `"mpls_flow_label" in capabilities` do device.
- **Runner escopo-aware** (additivo, máquina de estados intacta): `escopo="circuito"` (default) ⇒ comportamento atual byte a byte; `escopo="l2vc"` ⇒ chaves de re-diff `("interfaces", "l2vc", "config_backup")`, setup valida o serviço L2VC (não `circuit_id`), pré-checks/pós-checks L2VC chamados do runner.
- **Segredos nunca em logs/snapshots/auditoria**: mêmes regras do ciclo D (mascaramento; comandos L2VC não carregam segredos).
- **Migrações**: T1 (MPLS + VLAN + capabilities) e T7 (CR generalizada), `down_revision` = cabeça atual (verificar com `uv run alembic heads` antes de cada revision). Rodar `uv run alembic upgrade head` também no banco de teste `gerenet_test` (o env do alembic lê `GERENET_DATABASE_URL`; use `GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head`).
- **conftest.py** [tests/conftest.py:41](tests/conftest.py#L41): o TRUNCATE passa a listar também `vsi_members, vsi_services, service_endpoints, l2vc_services, mpls_domain_members, mpls_domains` — falha em esquecer deixa resíduo entre testes.
- **`connect_and_run` permanece read-only**; nenhum comando novo de escrita por ali — o runner aplica via `connect_and_apply` (padrão do ciclo D).
- **Verificação final obrigatória**: `uv run ruff check src tests` limpo · `uv run pytest -q` verde · `cd web && npm run build` · `npm run test` · e2e com banco dedicado `gerenet_e2e` e `reuseExistingServer: false`.
- **Testes de render/parser**: fixtures de output com o shape real dos switches (família S); valores exatos de `display` podem divergir por versão — o runbook (T15) é o ajuste dos goldens, não do código de teste (o parser é tolerante: linha com shape inesperado é ignorada pelo TextFSM, nunca erro).
- **Comandos exatos do AC no template** seguem o spec §6 (dot1q/qinq + `mpls l2vc ... encapsulation vlan|vlan-vpls remote <loopback>`); a confirmação contra os switches reais é o passo 1 do runbook (T15) — se o VRP divergir, **o ajuste é no template/runbook, não na validação do modelo** (nova template por versão se necessário, padrão já existente).

---

### Task 1: Modelos MPLS + migração (inclui VLAN de AC, `devices.capabilities`) + conftest

**Files:**
- Modify: `src/gerenet/domain/models.py` (enums, coluna `capabilities` em `Device`, coluna `device_id` + índices parciais em `Vlan`, 6 classes novas após `Approval`)
- Create: `alembic/versions/<hash>_mpls_models.py` (via `uv run alembic revision --autogenerate -m "mpls models"`; ajustar manualmente: índice parcial/ALTER TYPE são casos que o autogenerate não cobre bem)
- Modify: `tests/conftest.py:39-43` (lista do TRUNCATE)
- Test: `tests/domain/test_mpls_models.py`

**Interfaces:**
- Produces: enums `MPLS_ROLE = ("pe", "core")`, `MPLS_OPER_STATUS = ("unknown", "up", "down", "partial")`, `SERVICE_KIND = ("l2vc", "vsi")`, `SERVICE_ENCAP = ("dot1q", "qinq", "ethernet_raw")`, `SERVICE_SIGNALING = ("ldp",)`; `VLAN_KIND` vira `("vlan", "s_vlan", "mpls_ac")`; classes `models.MplsDomain`, `models.MplsDomainMember`, `models.L2vcService`, `models.ServiceEndpoint`, `models.VsiService`, `models.VsiMember` (campos exatos abaixo); `Device.capabilities: Mapped[list] = mapped_column(JSON, default=list)`; `Vlan.device_id: Mapped[int | None]` + índices parciais `uq_vlans_site_vid` (device_id IS NULL) e `uq_vlans_device_vid` (device_id IS NOT NULL). Tasks 2-14 consomem esses nomes.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/domain/test_mpls_models.py`:

```python
"""Smoke dos modelos MPLS — fase 4, spec §3."""
from gerenet.domain import models


def test_enums_do_spec():
    assert models.MPLS_ROLE == ("pe", "core")
    assert models.MPLS_OPER_STATUS == ("unknown", "up", "down", "partial")
    assert models.SERVICE_KIND == ("l2vc", "vsi")
    assert models.SERVICE_ENCAP == ("dot1q", "qinq", "ethernet_raw")
    assert models.SERVICE_SIGNALING == ("ldp",)
    assert "mpls_ac" in models.VLAN_KIND


def test_tabelas_esperadas():
    for classe, tabela in (
        (models.MplsDomain, "mpls_domains"),
        (models.MplsDomainMember, "mpls_domain_members"),
        (models.L2vcService, "l2vc_services"),
        (models.ServiceEndpoint, "service_endpoints"),
        (models.VsiService, "vsi_services"),
        (models.VsiMember, "vsi_members"),
    ):
        assert classe.__tablename__ == tabela


def test_criar_dominio_com_membro_e_servico(db_session):
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.sites import create_site
    from gerenet.domain.schemas import DeviceCreate, SiteCreate

    site = create_site(db_session, SiteCreate(name="pop-mpls"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw1", management_address="10.0.0.11"), actor="cli")
    assert "mpls_flow_label" not in (dev.capabilities or [])
    dev.capabilities = ["mpls_flow_label"]
    db_session.flush()

    dom = models.MplsDomain(name="mpls-core-1")
    db_session.add(dom)
    db_session.flush()
    membro = models.MplsDomainMember(
        domain_id=dom.id, device_id=dev.id, loopback_address="10.255.0.1", role="pe",
    )
    db_session.add(membro)
    db_session.flush()

    servico = models.L2vcService(domain_id=dom.id, vc_id=100, name="cliente-acme")
    db_session.add(servico)
    db_session.flush()
    ep = models.ServiceEndpoint(
        kind="l2vc", l2vc_id=servico.id, device_id=dev.id,
        interface="10GE0/0/1", encapsulation="dot1q",
    )
    db_session.add(ep)
    db_session.flush()

    vsi = models.VsiService(domain_id=dom.id, vsi_id=200, name="vsi-cliente", vrp_name="VSI-CLIENTE-200")
    db_session.add(vsi)
    db_session.flush()
    db_session.add(models.VsiMember(vsi_id=vsi.id, device_id=dev.id))
    db_session.commit()

    assert dom.members[0].loopback_address == "10.255.0.1"
    assert servico.endpoints[0].device_id == dev.id
    assert vsi.vrp_name == "VSI-CLIENTE-200"
    assert dev.capabilities == ["mpls_flow_label"]


def test_mesmo_vid_em_devices_diferentes_do_mesmo_site(db_session):
    """§3/Q2: escopo da VLAN MPLS é por device — (site,vid) repetido entre switches é legítimo."""
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.sites import create_site
    from gerenet.domain.schemas import DeviceCreate, SiteCreate

    site = create_site(db_session, SiteCreate(name="pop-2"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-a", management_address="10.0.0.21"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-b", management_address="10.0.0.22"), actor="cli")
    for d in (d1, d2):
        db_session.add(models.Vlan(site_id=site.id, device_id=d.id, vid=500, kind="mpls_ac"))
    db_session.commit()
    assert len(
        db_session.query(models.Vlan)
        .filter(models.Vlan.site_id == site.id, models.Vlan.device_id.isnot(None), models.Vlan.vid == 500)
        .all()
    ) == 2


def test_mesmo_vid_no_mesmo_device_estoura_unique(db_session):
    """Mesmo (device, vid) = violação do índice parcial (dois serviços no mesmo switch)."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.sites import create_site
    from gerenet.domain.schemas import DeviceCreate, SiteCreate

    site = create_site(db_session, SiteCreate(name="pop-3"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-c", management_address="10.0.0.23"), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, device_id=dev.id, vid=501, kind="mpls_ac"))
    db_session.commit()
    db_session.add(models.Vlan(site_id=site.id, device_id=dev.id, vid=501, kind="mpls_ac"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_mpls_models.py -v`
Expected: FAIL — `AttributeError: module 'gerenet.domain.models' has no attribute 'MPLS_ROLE'` (e/ou erro de coluna/índice inexistente ao commitar).

- [ ] **Step 3: Implementar os modelos**

Em `src/gerenet/domain/models.py`:

1. Imports: adicionar `Index` e `text` à lista do `sqlalchemy` (linha 3-15).
2. Enums novos após `APPROVAL_DECISION` (linha ~41):

```python
MPLS_ROLE = ("pe", "core")
MPLS_OPER_STATUS = ("unknown", "up", "down", "partial")
SERVICE_KIND = ("l2vc", "vsi")
SERVICE_ENCAP = ("dot1q", "qinq", "ethernet_raw")
SERVICE_SIGNALING = ("ldp",)
VLAN_KIND = ("vlan", "s_vlan", "mpls_ac")
```

3. `Device` (linha 44): adicionar após `tags` (linha 67):

```python
    capabilities: Mapped[list] = mapped_column(JSON, default=list)  # §5: suportes por equipamento (ex.: "mpls_flow_label")
```

4. `Vlan` (linha 250): substituir o `__table_args__` e adicionar a coluna:

```python
    __table_args__ = (
        # S-VLAN e VLAN partilham o mesmo espaço de VID no switch (spec).
        # Filas de circuito: escopo de site (device_id NULL); filas MPLS:
        # escopo de device (mesmo VID é legítimo em switches diferentes).
        Index("uq_vlans_site_vid", "site_id", "vid", unique=True,
              postgresql_where=text("device_id IS NULL")),
        Index("uq_vlans_device_vid", "device_id", "vid", unique=True,
              postgresql_where=text("device_id IS NOT NULL")),
    )
    ...
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
```

(mantendo `site_id`, `vid`, `kind`, `family`, `circuit_id`, `status`, `notes`, `created_at`, `updated_at` na ordem atual do bloco.)

5. Seis classes novas **após `Approval`** (fim do arquivo):

```python
class MplsDomain(Base):
    """Domínio MPLS/LDP (§9.1): PEs e interfaces de core ficam nos membros."""

    __tablename__ = "mpls_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    members: Mapped[list["MplsDomainMember"]] = relationship(
        back_populates="domain", order_by="MplsDomainMember.id", cascade="all, delete-orphan"
    )


class MplsDomainMember(Base):
    """PE/core de um domínio com o loopback LDP (remote do L2VC, §9.1)."""

    __tablename__ = "mpls_domain_members"

    __table_args__ = (UniqueConstraint("domain_id", "device_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("mpls_domains.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    loopback_address: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(Enum(*MPLS_ROLE, name="mpls_role"), default="pe", nullable=False)

    domain: Mapped[MplsDomain] = relationship(back_populates="members")
    device: Mapped[Device] = relationship()


class L2vcService(Base):
    """Serviço L2VC ponto a ponto (§9.2) — VC-ID único no domínio."""

    __tablename__ = "l2vc_services"

    __table_args__ = (
        UniqueConstraint("domain_id", "vc_id"),
        UniqueConstraint("domain_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("mpls_domains.id"), nullable=False)
    vc_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    mtu: Mapped[int] = mapped_column(Integer, default=1500, nullable=False)
    control_word: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flow_label: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redundancy: Mapped[str | None] = mapped_column(Text())  # anotação §9.2
    description: Mapped[str | None] = mapped_column(String(255))
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    operational_status: Mapped[str] = mapped_column(
        Enum(*MPLS_OPER_STATUS, name="mpls_oper_status"), default="unknown", nullable=False
    )
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    domain: Mapped[MplsDomain] = relationship()
    organization: Mapped[Organization | None] = relationship()
    endpoints: Mapped[list["ServiceEndpoint"]] = relationship(
        back_populates="l2vc", order_by="ServiceEndpoint.id", cascade="all, delete-orphan"
    )


class ServiceEndpoint(Base):
    """Ponta de serviço MPLS (§14) — exatamente um de l2vc_id/vsi_id (validado no serviço)."""

    __tablename__ = "service_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Enum(*SERVICE_KIND, name="service_kind"), nullable=False)
    l2vc_id: Mapped[int | None] = mapped_column(ForeignKey("l2vc_services.id"))
    vsi_id: Mapped[int | None] = mapped_column(ForeignKey("vsi_services.id"))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    interface: Mapped[str] = mapped_column(String(64), nullable=False)  # da coleta, sem FK
    encapsulation: Mapped[str] = mapped_column(
        Enum(*SERVICE_ENCAP, name="service_encap"), default="dot1q", nullable=False
    )
    vlan_id: Mapped[int | None] = mapped_column(ForeignKey("vlans.id"))
    inner_vlan: Mapped[int | None] = mapped_column(Integer)  # QinQ: espaço do cliente
    mtu: Mapped[int | None] = mapped_column(Integer)
    operational_status: Mapped[str] = mapped_column(
        Enum(*MPLS_OPER_STATUS, name="mpls_oper_status"), default="unknown", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    l2vc: Mapped[L2vcService | None] = relationship(back_populates="endpoints")
    vsi: Mapped["VsiService | None"] = relationship()
    device: Mapped[Device] = relationship()
    vlan: Mapped[Vlan | None] = relationship()


class VsiService(Base):
    """VSI multiponto (§9.3) — somente modelo + consulta neste ciclo (§11.3)."""

    __tablename__ = "vsi_services"

    __table_args__ = (
        UniqueConstraint("domain_id", "vsi_id"),
        UniqueConstraint("domain_id", "vrp_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("mpls_domains.id"), nullable=False)
    vsi_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    vrp_name: Mapped[str] = mapped_column(String(64), nullable=False)  # naming.vsi_nome, identidade VRP
    signaling: Mapped[str] = mapped_column(
        Enum(*SERVICE_SIGNALING, name="service_signaling"), default="ldp", nullable=False
    )
    mtu: Mapped[int] = mapped_column(Integer, default=1500, nullable=False)
    split_horizon: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mac_learning: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mac_limit: Mapped[int | None] = mapped_column(Integer)
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    operational_status: Mapped[str] = mapped_column(
        Enum(*MPLS_OPER_STATUS, name="mpls_oper_status"), default="unknown", nullable=False
    )
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    domain: Mapped[MplsDomain] = relationship()
    members: Mapped[list["VsiMember"]] = relationship(
        back_populates="vsi", order_by="VsiMember.id", cascade="all, delete-orphan"
    )
    endpoints: Mapped[list[ServiceEndpoint]] = relationship(
        order_by="ServiceEndpoint.id", cascade="all, delete-orphan"
    )


class VsiMember(Base):
    """PE participante de um VSI (§9.3)."""

    __tablename__ = "vsi_members"

    __table_args__ = (UniqueConstraint("vsi_id", "device_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vsi_id: Mapped[int] = mapped_column(ForeignKey("vsi_services.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)

    vsi: Mapped[VsiService] = relationship(back_populates="members")
    device: Mapped[Device] = relationship()
```

- [ ] **Step 4: Gerar e ajustar a migração**

Run: `uv run alembic revision --autogenerate -m "mpls models"` — e então **ajustar manualmente** a migration gerada:

1. `vlans`: remover o `drop_constraint/UniqueConstraint` antigo do autogen se ele só reagir ao índice novo (o autogenerate frequentemente não trata `postgresql_where`); adicionar explicitamente, na ordem certa (drop primeiro):

```python
    op.drop_constraint("vlans_site_id_vid_key", "vlans", type_="unique")
    op.create_index("uq_vlans_site_vid", "vlans", ["site_id", "vid"],
                    unique=True, postgresql_where=sa.text("device_id IS NULL"))
    op.create_index("uq_vlans_device_vid", "vlans", ["device_id", "vid"],
                    unique=True, postgresql_where=sa.text("device_id IS NOT NULL"))
```

(Confirme o nome real do constraint antigo com `\d vlans` no banco; o padrão do Postgres é `tab_col_col_key`.)

2. Adicionar `sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=True)` em `op.add_column("vlans", ...)`.

3. `ALTER TYPE`: adicionar após os creates das tabelas (o autogen do Enum* com valor novo gera o `ALTER TYPE` corretamente? não — conferir; em caso de dúvida deixar explícito):

```python
    op.execute("ALTER TYPE vlan_kind ADD VALUE IF NOT EXISTS 'mpls_ac'")
```

4. `devices.capabilities`: conferir que o autogen criou `sa.Column('capabilities', sa.JSON(), nullable=False)` (com `server_default`? o model usa `default=list` Python-side; adicionar `server_default='[]'` na migration para linhas existentes — em Postgres, JSON default: `server_default=sa.text("'[]'::json")`).

5. As 6 tabelas novas: conferir enums (`mpls_role`, `mpls_oper_status`, `service_kind`, `service_encap`, `service_signaling`), FKs, uniques de `mpls_domain_members (domain_id, device_id)`, `l2vc_services (domain_id, vc_id)` + `(domain_id, name)`, `vsi_services (domain_id, vsi_id)` + `(domain_id, vrp_name)`, `vsi_members (vsi_id, device_id)` e `service_endpoints` (vsi_id FK para `vsi_services`).

- [ ] **Step 5: Rodar a migração no banco dev e no de teste**

Run: `uv run alembic upgrade head` e depois `GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head`
Expected: sem erro; `\d vlans` mostra `device_id` + 2 índices parciais.

- [ ] **Step 6: Atualizar o TRUNCATE do conftest**

Em `tests/conftest.py:41`, incluir na lista (antes do `RESTART IDENTITY CASCADE`):

```text
vsi_members, vsi_services, service_endpoints, l2vc_services, mpls_domain_members, mpls_domains,
```

- [ ] **Step 7: Rodar os testes**

Run: `uv run pytest tests/domain/test_mpls_models.py -v && uv run pytest tests/domain/test_reserva_circuito.py -q`
Expected: PASS (4 testes novos) e regressão da reserva de circuito verde (índice parcial não alterou o caminho com `device_id IS NULL`).

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/domain/models.py alembic/versions/ tests/conftest.py tests/domain/test_mpls_models.py
git commit -m "feat(mpls): modelos MPLS/L2VC/VSI + VLAN mpls_ac por device + devices.capabilities (fase 4 T1)"
```

---

### Task 2: Serviço de domínios MPLS (CRUD + membros) + schemas

**Files:**
- Create: `src/gerenet/domain/services/mpls.py` (domínios)
- Modify: `src/gerenet/domain/schemas.py` (schemas de domínio)
- Test: `tests/domain/test_mpls_domains.py`

**Interfaces:**
- Consumes: `models.MplsDomain`, `models.MplsDomainMember` (T1); `ConflictError`/`NotFoundError`/`ValidationError` de `gerenet.domain.services.errors`; `registrar` de `gerenet.domain.audit`.
- Produces: `create_domain(session, data: MplsDomainCreate, *, actor="cli") -> models.MplsDomain`; `list_domains(session, include_disabled=False) -> list[MplsDomain]`; `get_domain(session, domain_id) -> MplsDomain` (NotFoundError); `update_domain(session, domain_id, data: MplsDomainUpdate, *, actor="cli") -> MplsDomain`; `add_domain_member(session, domain_id, data: MplsMemberIn, *, actor="cli") -> MplsDomainMember`; `remove_domain_member(session, domain_id, device_id, *, actor="cli") -> None`; `out_domain(dom: MplsDomain) -> MplsDomainOut` (serializador explícito — preenche `members[].device_name`; `_out_membro` interno). Tasks 3-5, 8, 11-12 consomem.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/domain/test_mpls_domains.py`:

```python
"""Serviço de domínios MPLS — fase 4, spec §3 (mpls_domains/members)."""
import pytest

from gerenet.domain.schemas import (
    DeviceCreate, MplsDomainCreate, MplsDomainUpdate, MplsMemberIn,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member, create_domain, get_domain, list_domains,
    remove_domain_member, update_domain,
)


@pytest.fixture()
def dominio(db_session):
    return create_domain(db_session, MplsDomainCreate(name="mpls-pop-1", description="POP teste"), actor="cli")


def test_criar_e_listar(db_session, dominio):
    assert dominio.id is not None
    assert list_domains(db_session)[0].name == "mpls-pop-1"
    assert get_domain(db_session, dominio.id).description == "POP teste"


def test_nome_duplicado_409(db_session):
    create_domain(db_session, MplsDomainCreate(name="mpls-x"), actor="cli")
    with pytest.raises(ConflictError):
        create_domain(db_session, MplsDomainCreate(name="mpls-x"), actor="cli")


def test_get_inexistente_404(db_session):
    with pytest.raises(NotFoundError):
        get_domain(db_session, 999)


def test_dominio_desativado_nao_recebe_membro_nem_update_ativo(db_session, dominio):
    update_domain(db_session, dominio.id, MplsDomainUpdate(admin_status=False), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw1", management_address="10.0.0.31"), actor="cli")
    with pytest.raises(ConflictError):
        add_domain_member(db_session, dominio.id, MplsMemberIn(
            device_id=dev.id, loopback_address="10.255.0.1", role="pe",
        ), actor="cli")


def test_membro_exige_loopback_e_nao_duplica(db_session, dominio):
    dev = create_device(db_session, DeviceCreate(name="sw2", management_address="10.0.0.32"), actor="cli")
    with pytest.raises(ValidationError):
        add_domain_member(db_session, dominio.id, MplsMemberIn(
            device_id=dev.id, loopback_address="", role="pe",
        ), actor="cli")
    add_domain_member(db_session, dominio.id, MplsMemberIn(
        device_id=dev.id, loopback_address="10.255.0.2", role="pe",
    ), actor="cli")
    with pytest.raises(ConflictError):
        add_domain_member(db_session, dominio.id, MplsMemberIn(
            device_id=dev.id, loopback_address="10.255.0.3", role="pe",
        ), actor="cli")
    remove_domain_member(db_session, dominio.id, dev.id, actor="cli")
    assert not any(m.device_id == dev.id for m in get_domain(db_session, dominio.id).members)


def test_membro_de_outra_familia_nao_entra_em_dominio_desativado(db_session):
    """Regressão: desativar não apaga membros (objetos em uso são desativados, §14.1)."""
    dominio = create_domain(db_session, MplsDomainCreate(name="mpls-y"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw3", management_address="10.0.0.33"), actor="cli")
    add_domain_member(db_session, dominio.id, MplsMemberIn(
        device_id=dev.id, loopback_address="10.255.0.9", role="core",
    ), actor="cli")
    update_domain(db_session, dominio.id, MplsDomainUpdate(admin_status=False), actor="cli")
    assert len(get_domain(db_session, dominio.id).members) == 1
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_mpls_domains.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.domain.services.mpls'`.

- [ ] **Step 3: Implementar os schemas**

Em `src/gerenet/domain/schemas.py` (seguindo o padrão dos schemas existentes — ver `SiteCreate`/`DeviceCreate` e os `Out` com `ConfigDict(from_attributes=True)`):

```python
class MplsMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_id: int
    device_name: str | None = None
    loopback_address: str
    role: str


class MplsDomainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)


class MplsDomainUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    admin_status: bool | None = None


class MplsMemberIn(BaseModel):
    device_id: int
    loopback_address: str = Field(min_length=1, max_length=64)
    role: Literal["pe", "core"] = "pe"


class MplsDomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    admin_status: bool
    created_at: datetime
    updated_at: datetime
    members: list[MplsMemberOut] = Field(default_factory=list)
```

Por quê: `from_attributes` não preenche `device_name` (o modelo `MplsDomainMember` tem a relationship `device`, não um atributo `device_name`). Seguindo o precedente do repositório (ex.: `dashboard.py` monta `site_name` explícito), os Out são construídos pelo serviço, nunca por `model_validate` direto. Por isso o `ConfigDict(from_attributes=True)` fica só como convenção de schema; quem serializa é `out_domain` (abaixo).

- [ ] **Step 4: Implementar o serviço**

Criar `src/gerenet/domain/services/mpls.py`:

```python
"""Domínios MPLS (§9.1) — serviço transacional no padrão dos demais."""
import ipaddress

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.schemas import MplsDomainCreate, MplsDomainUpdate, MplsMemberIn


def _dom(session: Session, domain_id: int) -> models.MplsDomain:
    dom = session.scalars(
        select(models.MplsDomain).options(
            selectinload(models.MplsDomain.members).selectinload(models.MplsDomainMember.device),
        ).where(models.MplsDomain.id == domain_id)
    ).first()
    if dom is None:
        raise NotFoundError(f"Domínio MPLS {domain_id} não encontrado.")
    return dom


def create_domain(session: Session, data: MplsDomainCreate, *, actor: str = "cli") -> models.MplsDomain:
    nome = data.name.strip()
    ja_existe = session.scalars(
        select(models.MplsDomain.id).where(models.MplsDomain.name == nome).limit(1)
    ).first()
    if ja_existe is not None:
        raise ConflictError(f"Domínio MPLS '{nome}' já existe.")
    dom = models.MplsDomain(name=nome, description=data.description)
    session.add(dom)
    session.flush()
    registrar(session, tipo="mpls.domain.create", ator=actor, objeto="mpls_domain",
              objeto_id=dom.id, antes=None, depois={"name": dom.name})
    session.commit()
    return _dom(session, dom.id)


def list_domains(session: Session, include_disabled: bool = False) -> list[models.MplsDomain]:
    q = select(models.MplsDomain).options(
        selectinload(models.MplsDomain.members).selectinload(models.MplsDomainMember.device),
    ).order_by(models.MplsDomain.name)
    if not include_disabled:
        q = q.where(models.MplsDomain.admin_status.is_(True))
    return list(session.scalars(q))


def get_domain(session: Session, domain_id: int) -> models.MplsDomain:
    return _dom(session, domain_id)


def update_domain(session: Session, domain_id: int, data: MplsDomainUpdate, *, actor: str = "cli") -> models.MplsDomain:
    dom = _dom(session, domain_id)
    antes = {"name": dom.name, "admin_status": dom.admin_status, "description": dom.description}
    if data.name is not None and data.name.strip() != dom.name:
        nomes = session.scalars(
            select(models.MplsDomain.id).where(
                models.MplsDomain.name == data.name.strip(), models.MplsDomain.id != dom.id,
            ).limit(1)
        ).first()
        if nomes is not None:
            raise ConflictError(f"Domínio MPLS '{data.name}' já existe.")
        dom.name = data.name.strip()
    if data.description is not None:
        dom.description = data.description
    if data.admin_status is not None:
        dom.admin_status = data.admin_status
    session.flush()
    registrar(session, tipo="mpls.domain.update", ator=actor, objeto="mpls_domain", objeto_id=dom.id,
              antes=antes, depois={"name": dom.name, "admin_status": dom.admin_status})
    session.commit()
    return _dom(session, dom.id)


def add_domain_member(session: Session, domain_id: int, data: MplsMemberIn, *, actor: str = "cli") -> models.MplsDomainMember:
    dom = _dom(session, domain_id)
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe membros.")
    device = get_device(session, data.device_id)  # NotFoundError propaga
    loopback = data.loopback_address.strip()
    if not loopback:
        raise ValidationError("Loopback LDP do membro é obrigatório.")
    try:
        ipaddress.ip_address(loopback)
    except ValueError:
        raise ValidationError(f"Loopback LDP inválido: {loopback}.") from None
    ja = session.scalars(
        select(models.MplsDomainMember.id).where(
            models.MplsDomainMember.domain_id == dom.id,
            models.MplsDomainMember.device_id == device.id,
        ).limit(1)
    ).first()
    if ja is not None:
        raise ConflictError(f"Equipamento {device.name} já é membro do domínio {dom.name}.")
    membro = models.MplsDomainMember(
        domain_id=dom.id, device_id=device.id, loopback_address=loopback, role=data.role,
    )
    session.add(membro)
    session.flush()
    registrar(session, tipo="mpls.domain.member_add", ator=actor, objeto="mpls_domain",
              objeto_id=dom.id, antes=None,
              depois={"device_id": device.id, "loopback_address": loopback, "role": data.role})
    session.commit()
    return membro


def remove_domain_member(session: Session, domain_id: int, device_id: int, *, actor: str = "cli") -> None:
    dom = _dom(session, domain_id)
    membro = session.scalars(
        select(models.MplsDomainMember).where(
            models.MplsDomainMember.domain_id == dom.id,
            models.MplsDomainMember.device_id == device_id,
        )
    ).first()
    if membro is None:
        raise NotFoundError(f"Equipamento {device_id} não é membro do domínio {dom.name}.")
    session.delete(membro)
    session.flush()
    registrar(session, tipo="mpls.domain.member_remove", ator=actor, objeto="mpls_domain",
              objeto_id=dom.id, antes={"device_id": device_id}, depois={"device_id": None})
    session.commit()


# ---- Serialização para a API (padrão dashboard.py: Out explícito) -------

def _out_membro(m: models.MplsDomainMember) -> MplsMemberOut:
    return MplsMemberOut(
        device_id=m.device_id,
        device_name=m.device.name if m.device is not None else None,
        loopback_address=m.loopback_address,
        role=m.role,
    )


def out_domain(dom: models.MplsDomain) -> MplsDomainOut:
    return MplsDomainOut(
        id=dom.id,
        name=dom.name,
        description=dom.description,
        admin_status=dom.admin_status,
        created_at=dom.created_at,
        updated_at=dom.updated_at,
        members=[_out_membro(m) for m in dom.members],
    )
```

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/domain/test_mpls_domains.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/mpls.py src/gerenet/domain/schemas.py tests/domain/test_mpls_domains.py
git commit -m "feat(mpls): serviço de domínios MPLS + membros (fase 4 T2)"
```

---

### Task 3: IDAM MPLS — `proximo_vc_id` / `proximo_vsi_id` / `reservar_vlan_ac` + filtro do validador de circuito

**Files:**
- Modify: `src/gerenet/domain/services/ipam.py` (filtro `device_id IS NULL` em `_primeiro_vid`)
- Modify: `src/gerenet/domain/services/mpls.py` (helpers IDAM)
- Test: `tests/domain/test_mpls_idam.py`

**Interfaces:**
- Consumes: `models.Vlan` (T1: `device_id`, `kind='mpls_ac'`, índices parciais).
- Produces: `proximo_vc_id(session, domain_id) -> int`; `proximo_vsi_id(session, domain_id) -> int`; `reservar_vlan_ac(session, *, device_id, vid: int | None = None, notes=None, actor="cli") -> models.Vlan` (idempotente; `vid=None` ⇒ menor livre no device; `ConflictError` se o (device, vid) já tiver linha `mpls_ac`; valida `validar_vid`). Tasks 4-5 consomem.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/domain/test_mpls_idam.py`:

```python
"""IDAM MPLS — fase 4, spec §4 (sem tabela allocations: UNIQUE + helpers)."""
import pytest

from gerenet.domain.schemas import DeviceCreate, MplsDomainCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError
from gerenet.domain.services.ipam import _primeiro_vid
from gerenet.domain.services.mpls import create_domain, proximo_vc_id, proximo_vsi_id, reservar_vlan_ac
from gerenet.domain.services.sites import create_site


def _dominio(db_session):
    return create_domain(db_session, MplsDomainCreate(name="idam"), actor="cli")


def test_proximo_vc_id_sequencial(db_session):
    dom = _dominio(db_session)
    assert proximo_vc_id(db_session, dom.id) == 100
    assert proximo_vc_id(db_session, dom.id, inicio=200) == 200
    assert proximo_vc_id(db_session, dom.id, inicio=200) == 200  # helper é imutável por construção


def test_proximo_vc_id_pula_ocupados(db_session):
    from gerenet.domain import models
    dom = _dominio(db_session)
    db_session.add(models.L2vcService(domain_id=dom.id, vc_id=101, name="a"))
    db_session.add(models.L2vcService(domain_id=dom.id, vc_id=103, name="b"))
    db_session.commit()
    assert proximo_vc_id(db_session, dom.id, inicio=100) in (100, 102, 104)


def test_proximo_vsi_id(db_session):
    dom = _dominio(db_session)
    assert proximo_vsi_id(db_session, dom.id, inicio=500) == 500


def test_reservar_vlan_ac_por_device(db_session):
    site = create_site(db_session, SiteCreate(name="pop-idam"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-id", management_address="10.0.0.41"), actor="cli")
    vlan = reservar_vlan_ac(db_session, device_id=dev.id, vid=777, actor="cli")
    assert vlan.kind == "mpls_ac"
    assert vlan.site_id == site.id
    assert vlan.device_id == dev.id
    assert vlan.circuit_id is None
    assert vlan.status == "reservada"

    # idempotente: mesma ponta não duplica, devolve a existente
    de_novo = reservar_vlan_ac(db_session, device_id=dev.id, vid=777, actor="cli")
    assert de_novo.id == vlan.id

    # mesmo device + mesmo vid = conflito (índice parcial uq_vlans_device_vid)
    dev2 = create_device(db_session, DeviceCreate(name="sw-id2", management_address="10.0.0.42"), actor="cli")
    outra = reservar_vlan_ac(db_session, device_id=dev2.id, vid=777, actor="cli")
    assert outra.id != vlan.id  # mesmo POP, mesmo VID, switch diferente = legítimo

    from gerenet.domain.services.errors import ValidationError
    with pytest.raises(ValidationError):
        reservar_vlan_ac(db_session, device_id=dev.id, vid=1, actor="cli")  # VID fora do range 2-4094


def test_primeiro_vid_de_circuito_ignora_linhas_mpls(db_session):
    """§3/Q2: reserva de circuito não enxerga VLAN mpls_ac (device_id NOT NULL)."""
    site = create_site(db_session, SiteCreate(name="pop-filtro"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-f", management_address="10.0.0.43"), actor="cli")
    reservar_vlan_ac(db_session, device_id=dev.id, vid=2, actor="cli")
    assert _primeiro_vid(db_session, site.id) == 2  # 2 continue livre para o circuito
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_mpls_idam.py -v`
Expected: FAIL — `ImportError` (`proximo_vc_id`/`reservar_vlan_ac` não existem) e/ou `_primeiro_vid` devolvendo 3.

- [ ] **Step 3: Implementar os helpers**

No fim de `src/gerenet/domain/services/mpls.py`:

```python
# ---- IDAM simples (§4): UNIQUEs garantem; helpers dão UX ---------------

def proximo_vc_id(session: Session, domain_id: int, *, inicio: int = 100) -> int:
    """Menor VC-ID livre no domínio a partir de `inicio` (conveniência — a UNIQUE garante)."""
    ocupados = set(
        session.scalars(select(models.L2vcService.vc_id).where(models.L2vcService.domain_id == domain_id))
    )
    vc = inicio
    while vc in ocupados:
        vc += 1
    return vc


def proximo_vsi_id(session: Session, domain_id: int, *, inicio: int = 500) -> int:
    ocupados = set(
        session.scalars(select(models.VsiService.vsi_id).where(models.VsiService.domain_id == domain_id))
    )
    vc = inicio
    while vc in ocupados:
        vc += 1
    return vc


def _primeiro_vid_device(session: Session, device_id: int) -> int:
    """Menor VID 2-4094 livre **no device** (linhas mpls_ac + circuitos do device).
    Linhas de circuito são de site — não bloqueiam o device (escopo distinto)."""
    ocupados = set(
        session.scalars(
            select(models.Vlan.vid).where(models.Vlan.device_id == device_id)
        )
    )
    for vid in range(2, 4095):
        if vid not in ocupados:
            validar_vid(vid)
            return vid
    raise ConflictError("VLANs esgotadas neste equipamento.")


def reservar_vlan_ac(session: Session, *, device_id: int, vid: int | None = None,
                     notes: str | None = None, actor: str = "cli") -> models.Vlan:
    """Reserva a VLAN de AC do endpoint (§4) — idempotente; escopo por device.

    vid None ⇒ menor livre no device (helper acima). Repetição da mesma ponta
    devolve a linha existente (no-op auditado); (device, vid) ocupado por OUTRA
    linha mpls_ac ⇒ ConflictError (índice parcial uq_vlans_device_vid).
    """
    device = get_device(session, device_id)
    ja = session.scalars(
        select(models.Vlan).where(
            models.Vlan.device_id == device.id, models.Vlan.kind == "mpls_ac",
        )
    ).all()
    if vid is not None:
        validar_vid(vid)
        existente = next((v for v in ja if v.vid == vid), None)
    else:
        vid = _primeiro_vid_device(session, device.id)
        existente = None
    if existente is not None:
        registrar(session, tipo="mpls.vlan.reserve", ator=actor, objeto="vlan",
                  objeto_id=existente.id, antes=None, depois={"repetida": True, "vid": vid})
        session.commit()
        return existente
    linha = models.Vlan(
        site_id=device.site_id, device_id=device.id, vid=vid, kind="mpls_ac",
        circuit_id=None, status="reservada", notes=notes,
    )
    session.add(linha)
    session.flush()
    registrar(session, tipo="mpls.vlan.reserve", ator=actor, objeto="vlan",
              objeto_id=linha.id, antes=None,
              depois={"device_id": device.id, "vid": vid, "kind": "mpls_ac"})
    session.commit()
    return linha
```

Em `ipam.py`, corrigir `_primeiro_vid` (linha 103-106) para ignorar linhas MPLS:

```python
    ocupados = set(session.scalars(
        select(models.Vlan.vid).where(
            models.Vlan.site_id == site_id, models.Vlan.device_id.is_(None),
        )
    ))
```

Imports em `mpls.py`: `from gerenet.domain.validators import validar_vid` (mesmo caminho de `ipam.py` — a função mora em `domain/validators.py:50`).

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/domain/test_mpls_idam.py tests/domain/test_reserva_circuito.py -q`
Expected: PASS (helpers + regressão da reserva de circuito).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/domain/services/mpls.py src/gerenet/domain/services/ipam.py tests/domain/test_mpls_idam.py
git commit -m "feat(mpls): IDAM de VC-ID/VSI-ID/VLAN de AC por device + filtro do validador de circuito (fase 4 T3)"
```

---

### Task 4: Serviço L2VC (criação com validações §9.2, list/get, set-status) + schemas

**Files:**
- Modify: `src/gerenet/domain/services/mpls.py` (L2VC)
- Modify: `src/gerenet/domain/schemas.py` (L2vc schemas)
- Test: `tests/domain/test_l2vc_service.py`

**Interfaces:**
- Consumes: helpers da T3; `models.L2vcService`/`ServiceEndpoint` (T1); `MplsDomainMember` (loopback por device).
- Produces: `create_l2vc(session, data: L2vcCreate, *, actor="cli") -> models.L2vcService`; `list_l2vc(session, domain_id=None, include_disabled=False) -> list[L2vcService]`; `get_l2vc(session, l2vc_id) -> L2vcService` (NotFoundError; com `endpoints` carregados); `set_l2vc_status(session, l2vc_id, *, admin_status: bool, actor="cli") -> L2vcService`; `out_l2vc(svc: L2vcService) -> L2vcOut` (serializador explícito — preenche `endpoints[].device_name/vid` e `domain_name`; `_out_endpoint` interno); schemas `L2vcEndpointIn`, `L2vcCreate`, `L2vcOut`, `ServiceEndpointOut`. Tasks 6-8, 11-12 consomem.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/domain/test_l2vc_service.py`:

```python
"""Serviço L2VC — fase 4, validações §9.2."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from gerenet.domain import models
from gerenet.domain.schemas import (
    DeviceCreate, L2vcCreate, L2vcEndpointIn, MplsDomainCreate, MplsMemberIn,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member, create_domain, create_l2vc, get_l2vc, list_l2vc, set_l2vc_status,
)
from gerenet.domain.services.sites import create_site

# Regras que o schema rejeita (Literal, min_length) lançam PydanticValidationError
# na CONSTRUÇÃO, antes de chegar ao serviço — os testes usam alias separado do
# ValidationError do domínio (gerenet.domain.services.errors).


@pytest.fixture()
def pares(db_session):
    site = create_site(db_session, SiteCreate(name="pop-l2vc"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-a", management_address="10.0.0.51"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-b", management_address="10.0.0.52"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-l2vc"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.1.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.1.2"), actor="cli")
    return site, d1, d2, dom


def _create(db_session, dom, d1, d2, **kw):
    data = L2vcCreate(
        domain_id=dom.id, name=kw.pop("name", "cliente-teste"),
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=101),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=102),
        ],
        **kw,
    )
    return create_l2vc(db_session, data, actor="cli")


def test_criar_com_reservas_e_simetria(db_session, pares):
    _, d1, d2, dom = pares
    svc = _create(db_session, dom, d1, d2)
    assert svc.vc_id is not None
    assert svc.mtu == 1500
    assert len(svc.endpoints) == 2
    assert all(ep.vlan_id is not None for ep in svc.endpoints)
    vlan_a = db_session.get(models.Vlan, svc.endpoints[0].vlan_id)
    assert vlan_a.kind == "mpls_ac" and vlan_a.device_id == d1.id


def test_vc_id_duplicado_409(db_session, pares):
    _, d1, d2, dom = pares
    _create(db_session, dom, d1, d2, vc_id=1000)
    with pytest.raises(ConflictError):
        _create(db_session, dom, d1, d2, name="dupe", vc_id=1000)
    with pytest.raises(ConflictError):
        _create(db_session, dom, d1, d2, name="dupe2", vc_id=1000 + 0)  # mesmo ID, outra ponta


def test_nome_duplicado_por_dominio(db_session, pares):
    _, d1, d2, dom = pares
    _create(db_session, dom, d1, d2, name="mesmo")
    with pytest.raises(ConflictError):
        _create(db_session, dom, d1, d2, name="mesmo", vc_id=None)


def test_pontas_iguais_rejeitado(db_session, pares):
    site, d1, d2, dom = pares
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d1, name="x")


def test_loopback_do_par_obrigatorio(db_session, pares):
    _, d1, d2, dom = pares
    # remove o membro B: a ponta B não tem loopback LDP
    from gerenet.domain.services.mpls import remove_domain_member
    remove_domain_member(db_session, dom.id, d2.id, actor="cli")
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d2, name="sem-par")


def test_encap_e_mtu_simetricos(db_session, pares):
    _, d1, d2, dom = pares
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d2, name="assimetrico", endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=111, mtu=1500),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="qinq", vid=222, inner_vlan=31, mtu=1500),
        ])
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d2, name="mtu-diff", endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=111, mtu=1500),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=222, mtu=1600),
        ])


def test_ethernet_raw_fora_do_ciclo(db_session, pares):
    _, d1, d2, dom = pares
    # ethernet_raw nem passa do schema: Literal rejeita na construção
    with pytest.raises(PydanticValidationError):
        L2vcCreate(
            domain_id=dom.id, name="raw", endpoints=[
                L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="ethernet_raw"),
                L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="ethernet_raw"),
            ],
        )


def test_qinq_exige_inner_vlan(db_session, pares):
    _, d1, d2, dom = pares
    data = L2vcCreate(
        domain_id=dom.id, name="qinq-sem-inner", endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="qinq", vid=211),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="qinq", vid=212),
        ],
    )
    with pytest.raises(ValidationError):
        create_l2vc(db_session, data, actor="cli")


def test_list_get_status(db_session, pares):
    _, d1, d2, dom = pares
    svc = _create(db_session, dom, d1, d2)
    assert get_l2vc(db_session, svc.id).id == svc.id
    assert [s.id for s in list_l2vc(db_session)] == [svc.id]
    assert list_l2vc(db_session, domain_id=dom.id)[0].vc_id == svc.vc_id
    assert list_l2vc(db_session, domain_id=9999) == []
    set_l2vc_status(db_session, svc.id, admin_status=False, actor="cli")
    assert get_l2vc(db_session, svc.id).admin_status is False
    assert list_l2vc(db_session) == []  # desativado some da lista padrão
    with pytest.raises(NotFoundError):
        get_l2vc(db_session, 99999)
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_l2vc_service.py -v`
Expected: FAIL — `AttributeError: ... 'create_l2vc'`.

- [ ] **Step 3: Implementar os schemas**

Em `schemas.py` (padrão dos existentes):

```python
class L2vcEndpointIn(BaseModel):
    device_id: int
    interface: str = Field(min_length=1, max_length=64)
    encapsulation: Literal["dot1q", "qinq"] = "dot1q"  # ethernet_raw: fora do ciclo (§10)
    vid: int | None = Field(default=None, ge=2, le=4094)  # None ⇒ auto-reserva no device
    inner_vlan: int | None = Field(default=None, ge=1, le=4094)  # QinQ: obrigatório
    mtu: int | None = Field(default=None, ge=576, le=9216)  # None ⇒ herda service.mtu


class L2vcCreate(BaseModel):
    domain_id: int
    name: str = Field(min_length=1, max_length=64)
    vc_id: int | None = Field(default=None, ge=1, le=4294967295)  # None ⇒ proximo_vc_id
    organization_id: int | None = None
    mtu: int = Field(default=1500, ge=576, le=9216)
    control_word: bool = False
    flow_label: bool = False
    redundancy: str | None = None
    description: str | None = Field(default=None, max_length=255)
    endpoints: list[L2vcEndpointIn] = Field(min_length=2, max_length=2)


class ServiceEndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    device_id: int
    device_name: str | None = None
    interface: str
    encapsulation: str
    vlan_id: int | None = None
    vid: int | None = None
    inner_vlan: int | None = None
    mtu: int | None = None
    operational_status: str


class L2vcOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    domain_id: int
    vc_id: int
    name: str
    organization_id: int | None
    mtu: int
    control_word: bool
    flow_label: bool
    redundancy: str | None
    description: str | None
    admin_status: bool
    operational_status: str
    last_collected_at: datetime | None
    created_at: datetime
    endpoints: list[ServiceEndpointOut] = Field(default_factory=list)
    domain_name: str | None = None
```

Assim como no T2, `from_attributes` não preenche `device_name` nem `vid` (que vem de `ep.vlan.vid`); os campos são montados por `out_l2vc`/`_out_endpoint` (Step 4).

- [ ] **Step 4: Implementar o serviço**

Em `mpls.py` (continuar):

```python
# ---- Serviços L2VC (§9.2) -----------------------------------------------

def _l2vc(session: Session, l2vc_id: int) -> models.L2vcService:
    svc = session.scalars(
        select(models.L2vcService)
        .options(
            selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.vlan),
            selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.device),
            selectinload(models.L2vcService.domain),
        )
        .where(models.L2vcService.id == l2vc_id)
    ).first()
    if svc is None:
        raise NotFoundError(f"Serviço L2VC {l2vc_id} não encontrado.")
    return svc


def _membro_loopback(session: Session, domain_id: int, device_id: int) -> str | None:
    linha = session.scalars(
        select(models.MplsDomainMember.loopback_address).where(
            models.MplsDomainMember.domain_id == domain_id,
            models.MplsDomainMember.device_id == device_id,
        ).limit(1)
    ).first()
    return linha


def create_l2vc(session: Session, data: L2vcCreate, *, actor: str = "cli") -> models.L2vcService:
    dom = _dom(session, data.domain_id)  # NotFound/desativado? _dom não checa status — checar abaixo
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe serviços.")

    a, b = data.endpoints
    if a.device_id == b.device_id:
        raise ValidationError("As duas pontas do L2VC devem ser equipamentos distintos.")
    if a.encapsulation != b.encapsulation:
        raise ValidationError("Encapsulamento das pontas deve ser simétrico (ambas dot1q ou ambas qinq).")
    mtu_a = a.mtu or data.mtu
    mtu_b = b.mtu or data.mtu
    if mtu_a != mtu_b:
        raise ValidationError(f"MTU das pontas diverge ({mtu_a} × {mtu_b}); ajuste o MTU do serviço ou das pontas.")
    for ep in (a, b):
        if ep.encapsulation == "qinq" and ep.inner_vlan is None:
            raise ValidationError(f"Ponta {ep.interface}: encapsulamento qinq exige inner-vlan.")
        if _membro_loopback(session, dom.id, ep.device_id) is None:
            raise ValidationError(f"Equipamento {ep.device_id} sem loopback LDP no domínio (membro inexistente).")
    if data.redundancy not in (None, "none", "single", "dual"):
        raise ValidationError(f"Redundância inválida: {data.redundancy} (use none/single/dual).")

    vc_id = data.vc_id or proximo_vc_id(session, dom.id)
    nome = data.name.strip()
    qtd = session.scalars(
        select(models.L2vcService.id).where(
            models.L2vcService.domain_id == dom.id,
            models.L2vcService.name == nome,
        ).limit(1)
    ).first()
    if qtd is not None:
        raise ConflictError(f"Serviço L2VC '{nome}' já existe no domínio {dom.name}.")
    duplicado = session.scalars(
        select(models.L2vcService.id).where(
            models.L2vcService.domain_id == dom.id, models.L2vcService.vc_id == vc_id,
        ).limit(1)
    ).first()
    if duplicado is not None:
        raise ConflictError(f"VC-ID {vc_id} já usado no domínio {dom.name}.")

    svc = models.L2vcService(
        domain_id=dom.id, vc_id=vc_id, name=nome, organization_id=data.organization_id,
        mtu=data.mtu, control_word=data.control_word, flow_label=data.flow_label,
        redundancy=data.redundancy, description=data.description,
    )
    session.add(svc)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"VC-ID {vc_id} já usado no domínio {dom.name}.") from exc
    for ep in (a, b):
        vlan = reservar_vlan_ac(session, device_id=ep.device_id, vid=ep.vid, actor=actor)
        session.add(models.ServiceEndpoint(
            kind="l2vc", l2vc_id=svc.id, device_id=ep.device_id, interface=ep.interface.strip(),
            encapsulation=ep.encapsulation, vlan_id=vlan.id, inner_vlan=ep.inner_vlan,
            mtu=ep.mtu or data.mtu,
        ))
    session.flush()
    registrar(session, tipo="mpls.l2vc.create", ator=actor, objeto="l2vc", objeto_id=svc.id,
              antes=None, depois={"vc_id": vc_id, "name": nome, "domain_id": dom.id})
    session.commit()
    return _l2vc(session, svc.id)


def list_l2vc(session: Session, domain_id: int | None = None, include_disabled: bool = False) -> list[models.L2vcService]:
    q = select(models.L2vcService).options(
        selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.vlan),
        selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.device),
        selectinload(models.L2vcService.domain),
    ).order_by(models.L2vcService.domain_id, models.L2vcService.vc_id)
    if domain_id is not None:
        q = q.where(models.L2vcService.domain_id == domain_id)
    if not include_disabled:
        q = q.where(models.L2vcService.admin_status.is_(True))
    return list(session.scalars(q))


def get_l2vc(session: Session, l2vc_id: int) -> models.L2vcService:
    return _l2vc(session, l2vc_id)


def set_l2vc_status(session: Session, l2vc_id: int, *, admin_status: bool, actor: str = "cli") -> models.L2vcService:
    svc = _l2vc(session, l2vc_id)
    antes, svc.admin_status = svc.admin_status, admin_status
    session.flush()
    registrar(session, tipo="mpls.l2vc.status", ator=actor, objeto="l2vc", objeto_id=svc.id,
              antes={"admin_status": antes}, depois={"admin_status": admin_status})
    session.commit()
    return _l2vc(session, svc.id)


# ---- Serialização L2VC (padrão dashboard.py: Out explícito) --------------

def _out_endpoint(ep: models.ServiceEndpoint) -> ServiceEndpointOut:
    return ServiceEndpointOut(
        id=ep.id,
        kind=ep.kind,
        device_id=ep.device_id,
        device_name=ep.device.name if ep.device is not None else None,
        interface=ep.interface,
        encapsulation=ep.encapsulation,
        vlan_id=ep.vlan_id,
        vid=ep.vlan.vid if ep.vlan is not None else None,
        inner_vlan=ep.inner_vlan,
        mtu=ep.mtu,
        operational_status=ep.operational_status,
    )


def out_l2vc(svc: models.L2vcService) -> L2vcOut:
    return L2vcOut(
        id=svc.id,
        domain_id=svc.domain_id,
        vc_id=svc.vc_id,
        name=svc.name,
        organization_id=svc.organization_id,
        mtu=svc.mtu,
        control_word=svc.control_word,
        flow_label=svc.flow_label,
        redundancy=svc.redundancy,
        description=svc.description,
        admin_status=svc.admin_status,
        operational_status=svc.operational_status,
        last_collected_at=svc.last_collected_at,
        created_at=svc.created_at,
        endpoints=[_out_endpoint(e) for e in svc.endpoints],
        domain_name=svc.domain.name if svc.domain is not None else None,
    )
```

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/domain/test_l2vc_service.py -v`
Expected: PASS.

Sobre o `except IntegrityError` do Step 4: é o padrão de `circuits.py:40-42` (`session.rollback(); raise ConflictError(...) from exc`). No teste ele nem dispara — o pré-check do `duplicado` cobre o caminho normal; o catch existe para corrida entre duas criações com o mesmo VC-ID.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/mpls.py src/gerenet/domain/schemas.py tests/domain/test_l2vc_service.py
git commit -m "feat(mpls): serviço L2VC com validações §9.2 (fase 4 T4)"
```

---

### Task 5: `naming.vsi_nome` + serviço VSI (modelo + consulta, sem config) + schemas

**Files:**
- Modify: `src/gerenet/automation/naming.py` (`vsi_nome`)
- Modify: `src/gerenet/domain/services/mpls.py` (VSI)
- Modify: `src/gerenet/domain/schemas.py` (Vsi schemas)
- Test: `tests/domain/test_vsi_service.py` (e um teste de naming)

**Interfaces:**
- Consumes: T1/T3 (`models.VsiService`/`VsiMember`, `proximo_vsi_id`).
- Produces: `naming.vsi_nome(name_logico: str, vsi_id: int) -> str`; `create_vsi(session, data: VsiCreate, *, actor="cli") -> models.VsiService`; `list_vsi(session, domain_id=None, include_disabled=False) -> list[VsiService]`; `get_vsi(session, vsi_id) -> VsiService`; `out_vsi(svc: VsiService) -> VsiOut` (serializador explícito — preenche `members[].device_name` e `domain_name`; `_out_vsi_membro` interno); schemas `VsiCreate`, `VsiMemberOut`, `VsiOut`. Tasks 9-10, 8, 11-12 consomem.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/domain/test_vsi_service.py`:

```python
"""Serviço VSI — fase 4, spec §3/§9.3 (modelo + consulta)."""
import pytest

from gerenet.automation.naming import vsi_nome
from gerenet.domain.schemas import (
    DeviceCreate, MplsDomainCreate, MplsMemberIn, VsiCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member, create_domain, create_vsi, get_vsi, list_vsi,
)
from gerenet.domain.services.sites import create_site
from gerenet.domain.schemas import SiteCreate


def test_vsi_nome_golden():
    assert vsi_nome("acme americas", 12) == "VSI-ACME-AMERICAS-12"
    assert vsi_nome("cliente acme pop", 200) == "VSI-CLIENTE-ACME-POP-200"
    assert len(vsi_nome("x", 1)) <= 63
    with pytest.raises(ValidationError):
        vsi_nome("a" * 30, 1)  # sanitized > 20 chars: nome VRP estouraria o limite
    with pytest.raises(ValidationError):
        vsi_nome("", 1)


def test_criar_vsi_com_derivacao_do_nome_vrp(db_session):
    site = create_site(db_session, SiteCreate(name="pop-vsi"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-1", management_address="10.0.0.61"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-2", management_address="10.0.0.62"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.2.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.2.2"), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente acme", vsi_id=550, split_horizon=True,
        members=[d1.id, d2.id],
    ), actor="cli")
    assert vsi.vrp_name == "VSI-CLIENTE-ACME-550"
    assert vsi.signaling == "ldp"
    assert {m.device_id for m in vsi.members} == {d1.id, d2.id}
    assert get_vsi(db_session, vsi.id).vrp_name == vsi.vrp_name
    assert [v.id for v in list_vsi(db_session)] == [vsi.id]


def test_vsi_membro_nao_membro_do_dominio(db_session):
    site = create_site(db_session, SiteCreate(name="pop-vsi2"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-3", management_address="10.0.0.63"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-4", management_address="10.0.0.64"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi2"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.3.1"), actor="cli")
    with pytest.raises(ValidationError):
        create_vsi(db_session, VsiCreate(
            domain_id=dom.id, name="vsi-membro", vsi_id=560, members=[d1.id, d2.id],
        ), actor="cli")


def test_vsi_id_duplicado_no_dominio(db_session):
    site = create_site(db_session, SiteCreate(name="pop-vsi3"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-5", management_address="10.0.0.65"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi3"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.4.1"), actor="cli")
    create_vsi(db_session, VsiCreate(domain_id=dom.id, name="a", vsi_id=570, members=[d1.id]), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(domain_id=dom.id, name="b", vsi_id=570, members=[d1.id]), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(domain_id=dom.id, name="a", vsi_id=571, members=[d1.id]), actor="cli")
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_vsi_service.py -v`
Expected: FAIL — `ImportError ... vsi_nome` (não existe).

- [ ] **Step 3: Implementar `vsi_nome`**

Em `src/gerenet/automation/naming.py` (após `pfx_produto`):

```python
def vsi_nome(name_logico: str, vsi_id: int) -> str:
    """Nome VRP do VSI: VSI-<SIGLA>-<ID> (≤63, maiúsculas, separador '-').

    SIGLA = nome lógico sanitizado (não alfanumérico vira '-', caixa alta),
    limitado a 20 chars — o restante do nome não pode tornar o total > 63
    quando somado ao ID. Ex.: vsi_nome("cliente acme", 12) -> "VSI-CLIENTE-ACME-12".
    """
    if not name_logico.strip():
        raise ValidationError("Nome lógico do VSI vazio.")
    sigla = re.sub(r"[^A-Z0-9]+", "-", name_logico.strip().upper()).strip("-")
    if not sigla:
        raise ValidationError(f"Nome lógico do VSI sem letras/dígitos: {name_logico}.")
    if len(sigla) > 20:
        raise ValidationError(f"Nome longo demais para nome VRP: {name_logico} (máx. 20 chars na sigla).")
    return f"VSI-{sigla}-{vsi_id}"
```

Adicionar `import re` no topo de `naming.py`.

- [ ] **Step 4: Implementar schemas e serviço VSI**

Schemas:

```python
class VsiMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_id: int
    device_name: str | None = None


class VsiCreate(BaseModel):
    domain_id: int
    name: str = Field(min_length=1, max_length=64)
    vsi_id: int | None = None  # None ⇒ proximo_vsi_id
    mtu: int = Field(default=1500, ge=576, le=9216)
    split_horizon: bool = True
    mac_learning: bool = True
    mac_limit: int | None = Field(default=None, ge=0)
    members: list[int] = Field(default_factory=list, min_length=1)


class VsiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    domain_id: int
    vsi_id: int
    name: str
    vrp_name: str
    signaling: str
    mtu: int
    split_horizon: bool
    mac_learning: bool
    mac_limit: int | None
    admin_status: bool
    operational_status: str
    last_collected_at: datetime | None
    created_at: datetime
    members: list[VsiMemberOut] = Field(default_factory=list)
    domain_name: str | None = None
```

`device_name` vem de `member.device.name` — montado por `_out_vsi_membro`/`out_vsi` (mesmo motivo do T2/T4).

Serviço (em `mpls.py`):

```python
# ---- Serviços VSI (§9.3: modelo + consulta; sem render/CR neste ciclo) --

def _vsi(session: Session, vsi_id: int) -> models.VsiService:
    svc = session.scalars(
        select(models.VsiService)
        .options(
            selectinload(models.VsiService.members).selectinload(models.VsiMember.device),
            selectinload(models.VsiService.domain),
        )
        .where(models.VsiService.id == vsi_id)
    ).first()
    if svc is None:
        raise NotFoundError(f"VSI {vsi_id} não encontrado.")
    return svc


def create_vsi(session: Session, data: VsiCreate, *, actor: str = "cli") -> models.VsiService:
    from gerenet.automation.naming import vsi_nome
    dom = _dom(session, data.domain_id)
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe serviços.")
    vsi_id = data.vsi_id or proximo_vsi_id(session, dom.id)
    nome = data.name.strip()
    ja_nome = session.scalars(
        select(models.VsiService.id).where(
            models.VsiService.domain_id == dom.id, models.VsiService.name == nome,
        ).limit(1)
    ).first()
    if ja_nome is not None:
        raise ConflictError(f"VSI '{nome}' já existe no domínio {dom.name}.")
    ja_id = session.scalars(
        select(models.VsiService.id).where(
            models.VsiService.domain_id == dom.id, models.VsiService.vsi_id == vsi_id,
        ).limit(1)
    ).first()
    if ja_id is not None:
        raise ConflictError(f"VSI-ID {vsi_id} já usado no domínio {dom.name}.")
    vrp = vsi_nome(nome, vsi_id)
    ja_vrp = session.scalars(
        select(models.VsiService.id).where(
            models.VsiService.domain_id == dom.id, models.VsiService.vrp_name == vrp,
        ).limit(1)
    ).first()
    if ja_vrp is not None:
        raise ConflictError(f"Nome VRP {vrp} já usado no domínio {dom.name}.")
    devices = [get_device(session, did) for did in dict.fromkeys(data.members)]
    for dev in devices:
        if _membro_loopback(session, dom.id, dev.id) is None:
            raise ValidationError(f"Equipamento {dev.name} sem loopback LDP no domínio (membro inexistente).")
    vsi = models.VsiService(
        domain_id=dom.id, vsi_id=vsi_id, name=nome, vrp_name=vrp,
        mtu=data.mtu, split_horizon=data.split_horizon, mac_learning=data.mac_learning,
        mac_limit=data.mac_limit,
    )
    session.add(vsi)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"VSI-ID {vsi_id} já usado no domínio {dom.name}.") from exc
    for dev in devices:
        session.add(models.VsiMember(vsi_id=vsi.id, device_id=dev.id))
    session.flush()
    registrar(session, tipo="mpls.vsi.create", ator=actor, objeto="vsi", objeto_id=vsi.id,
              antes=None, depois={"vsi_id": vsi_id, "name": nome, "vrp_name": vrp})
    session.commit()
    return _vsi(session, vsi.id)


def list_vsi(session: Session, domain_id: int | None = None, include_disabled: bool = False) -> list[models.VsiService]:
    q = select(models.VsiService).options(
        selectinload(models.VsiService.members).selectinload(models.VsiMember.device),
        selectinload(models.VsiService.domain),
    ).order_by(models.VsiService.domain_id, models.VsiService.vsi_id)
    if domain_id is not None:
        q = q.where(models.VsiService.domain_id == domain_id)
    if not include_disabled:
        q = q.where(models.VsiService.admin_status.is_(True))
    return list(session.scalars(q))


def get_vsi(session: Session, vsi_id: int) -> models.VsiService:
    return _vsi(session, vsi_id)


# ---- Serialização VSI (padrão dashboard.py: Out explícito) --------------

def _out_vsi_membro(m: models.VsiMember) -> VsiMemberOut:
    return VsiMemberOut(
        device_id=m.device_id,
        device_name=m.device.name if m.device is not None else None,
    )


def out_vsi(svc: models.VsiService) -> VsiOut:
    return VsiOut(
        id=svc.id,
        domain_id=svc.domain_id,
        vsi_id=svc.vsi_id,
        name=svc.name,
        vrp_name=svc.vrp_name,
        signaling=svc.signaling,
        mtu=svc.mtu,
        split_horizon=svc.split_horizon,
        mac_learning=svc.mac_learning,
        mac_limit=svc.mac_limit,
        admin_status=svc.admin_status,
        operational_status=svc.operational_status,
        last_collected_at=svc.last_collected_at,
        created_at=svc.created_at,
        members=[_out_vsi_membro(m) for m in svc.members],
        domain_name=svc.domain.name if svc.domain is not None else None,
    )
```

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/domain/test_vsi_service.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/naming.py src/gerenet/domain/services/mpls.py src/gerenet/domain/schemas.py tests/domain/test_vsi_service.py
git commit -m "feat(mpls): naming.vsi_nome + serviço VSI (modelo+consulta, §9.3) (fase 4 T5)"
```

---

### Task 6: Automação L2VC — template, `automation/l2vc.py` (render, planos, pré/pós-checks) + hooks no diff runner

**Files:**
- Create: `src/gerenet/automation/templates/huawei_vrp/l2vc_ac.j2`
- Create: `src/gerenet/automation/l2vc.py`
- Modify: `src/gerenet/automation/runner.py` (ramo `tipo == "l2vc_ac"` em `_estado_do_bloco`)
- Test: `tests/automation/test_l2vc.py`

**Interfaces:**
- Consumes: `changes.PlanoDevice`/`_ultimo_snapshot_ok`/`_bloco_para_plano`/`_SEM_RECURSOS_AVISO` de `automation/changes.py`; `BlocoRender`/`_render_template` de `automation/render.py` (e `naming.subinterface`); `models.L2vcService`/`ServiceEndpoint`/`MplsDomainMember`/`Vlan` (T1); máquina de estados do ciclo D intocada.
- Produces: `estado_bloco_l2vc(bloco: dict, recursos: dict) -> str` ("consta"|"ausente"|"conflito"); `render_l2vc(session, service) -> dict[int, list[BlocoRender]]` (device_id → blocos); `plan_provision_l2vc(session, service) -> list[PlanoDevice]`; `plan_remocao_l2vc(session, service) -> list[PlanoDevice]` (fresh snapshot obrigatório, padrão `plan_remocao` do ciclo D); `valida_pre_checks_l2vc(session, service, device, recursos) -> str | None`; `valida_pos_l2vc(session, service, snapshot) -> list[dict]` (items no shape de `ReconcileItem`). Tasks 7, 10, 13 consomem.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/automation/test_l2vc.py` (fixtures autocontidas; `DeviceSnapshot(status="success", resources=...)` é o mesmo shape que `_ultimo_snapshot_ok` consome):

```python
"""Render/planos/pré-pós-checks L2VC — fase 4, spec §6."""
import pytest

from gerenet.automation import l2vc
from gerenet.automation.changes import PlanoDevice
from gerenet.domain.schemas import (
    DeviceCreate, L2vcCreate, L2vcEndpointIn, MplsDomainCreate, MplsMemberIn, SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def servico(db_session):
    site = create_site(db_session, SiteCreate(name="pop-aut"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-a", management_address="10.0.0.71"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-b", management_address="10.0.0.72"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-aut"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.9.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.9.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="cliente-acme", vc_id=1000,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=101, mtu=1500),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=202, mtu=1500),
        ],
    ), actor="cli")
    return d1, d2, svc


def _snapshot(db_session, dev, recursos):
    from gerenet.domain import models
    snap = models.DeviceSnapshot(device_id=dev.id, status="success", resources=recursos)
    db_session.add(snap)
    db_session.commit()
    return snap


def _recursos_vazios(interface: str):
    return {
        "interfaces": [{"nome": interface, "phy": "up", "protocolo": "up"}],
        "l2vc": [],
        "mpls_ldp_peer": [],
        "config_backup": "",
    }


def test_render_l2vc_dot1q(servico, db_session):
    d1, d2, svc = servico
    por_device = l2vc.render_l2vc(db_session, svc)
    assert set(por_device) == {d1.id, d2.id}
    blocos = por_device[d1.id]
    assert len(blocos) == 1
    bloco = blocos[0]
    assert bloco.tipo == "l2vc_ac"
    assert bloco.objeto == "l2vc" and bloco.objeto_id == svc.id
    comandos = bloco.comandos
    assert comandos[0] == "interface 10GE0/0/1.101"
    assert any(c.startswith("mpls l2vc 1000 encapsulation vlan remote 10.255.9.2") for c in comandos)
    assert any("control-word" in c for c in comandos) is False
    # ponta B aponta para o loopback da ponta A
    comandos_b = por_device[d2.id][0].comandos
    assert any("remote 10.255.9.1" in c for c in comandos_b)


def test_render_qinq_control_word_e_mtu(servico, db_session):
    d1, d2, svc = servico
    svc.control_word = True
    svc.mtu = 1600
    from gerenet.domain import models
    for ep in svc.endpoints:
        ep.encapsulation = "qinq"
        ep.inner_vlan = 31
    db_session.commit()
    por_device = l2vc.render_l2vc(db_session, svc)
    comandos = por_device[d1.id][0].comandos
    linha = next(c for c in comandos if c.startswith("mpls l2vc 1000"))
    assert "encapsulation vlan-vpls" in linha
    assert "control-word" in linha
    assert "mtu 1600" in linha
    assert any("inner-vlan" in c.upper() or "encapsulation qinq" in c.lower() for c in comandos)


def test_flow_label_so_com_capacidade(servico, db_session):
    d1, d2, svc = servico
    svc.flow_label = True
    db_session.commit()
    por_device = l2vc.render_l2vc(db_session, svc)
    assert all("flow-label" not in " ".join(b.comandos) for b in por_device[d1.id])
    d1.capabilities = ["mpls_flow_label"]
    db_session.commit()
    por_device = l2vc.render_l2vc(db_session, svc)
    assert any("flow-label" in " ".join(b.comandos) for b in por_device[d1.id])


def test_estado_bloco_l2vc(servico):
    d1, d2, svc = servico
    bloco = {
        "tipo": "l2vc_ac", "objeto": "l2vc", "objeto_id": svc.id, "acao": "create",
        "comandos": ["interface 10GE0/0/1.101", "mpls l2vc 1000 encapsulation vlan remote 10.255.9.2"],
    }
    ausente = l2vc.estado_bloco_l2vc(bloco, _recursos_vazios("10GE0/0/1.101"))
    assert ausente == "ausente"
    presente = l2vc.estado_bloco_l2vc(bloco, {
        "interfaces": [{"nome": "10GE0/0/1.101"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    assert presente == "consta"
    conflito = l2vc.estado_bloco_l2vc(bloco, {
        "interfaces": [{"nome": "10GE0/0/1.101"}],
        "l2vc": [],  # subinterface existe sem o l2vc: config parcial/mudada desde o plano
    })
    assert conflito == "conflito"
    remocao = l2vc.estado_bloco_l2vc({**bloco, "acao": "delete"}, {
        "interfaces": [{"nome": "10GE0/0/1.101"}], "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    assert remocao == "consta"
    remocao_ausente = l2vc.estado_bloco_l2vc({**bloco, "acao": "delete"}, _recursos_vazios("10GE0/0/1.101"))
    assert remocao_ausente == "ausente"


def test_plan_provision_idempotente(servico, db_session):
    d1, d2, svc = servico
    _snapshot(db_session, d1, _recursos_vazios("10GE0/0/1.101"))
    _snapshot(db_session, d2, _recursos_vazios("10GE0/0/2.202"))
    plano = l2vc.plan_provision_l2vc(db_session, svc)
    assert len(plano) == 2
    assert all(isinstance(p, PlanoDevice) for p in plano)
    assert all(len(p.blocos) == 1 for p in plano)
    # segunda chamada: ainda cenário "ausente" — diffs estáveis (nenhum write)
    plano2 = l2vc.plan_provision_l2vc(db_session, svc)
    assert [len(p.blocos) for p in plano2] == [1, 1]
    # aplicado na coleta ⇒ plano vazio (skip de tudo)
    _snapshot(db_session, d1, {
        "interfaces": [{"nome": "10GE0/0/1.101", "phy": "up", "protocolo": "up"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    plano3 = l2vc.plan_provision_l2vc(db_session, svc)
    por_dev = {p.device_id: p for p in plano3}
    assert por_dev[d1.id].blocos == []


def test_plan_remocao_exige_snapshot_novo(servico, db_session):
    d1, d2, svc = servico
    with pytest.raises(Exception):
        l2vc.plan_remocao_l2vc(db_session, svc)
    _snapshot(db_session, d1, _recursos_vazios("10GE0/0/1.101"))
    _snapshot(db_session, d2, _recursos_vazios("10GE0/0/2.202"))
    plano = l2vc.plan_remocao_l2vc(db_session, svc)
    assert len(plano) == 2
    bloco = plano[0].blocos[0]
    assert bloco["acao"] == "delete"
    assert bloco["comandos"] == ["undo interface 10GE0/0/1.101"]


def test_pre_checks_ldp_e_binding(servico, db_session):
    d1, d2, svc = servico
    sem_ldp = l2vc.valida_pre_checks_l2vc(db_session, svc, svc.endpoints[0].device, {
        **_recursos_vazios("10GE0/0/1.101"), "mpls_ldp_peer": [],
    })
    assert sem_ldp is not None and "10.255.9.2" in sem_ldp
    ok = l2vc.valida_pre_checks_l2vc(db_session, svc, svc.endpoints[0].device, {
        **_recursos_vazios("10GE0/0/1.101"),
        "mpls_ldp_peer": [{"peer_id": "10.255.9.2", "estado": "up"}],
    })
    assert ok is None
    conflito = l2vc.valida_pre_checks_l2vc(db_session, svc, svc.endpoints[0].device, {
        "interfaces": [{"nome": "10GE0/0/1.101"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1", "estado": "up"}],
        "mpls_ldp_peer": [{"peer_id": "10.255.9.2", "estado": "up"}],
    })
    assert conflito is not None and "conflit" in conflito.lower()


def test_pos_check_up_e_down(servico, db_session):
    d1, d2, svc = servico
    snap_up = _snapshot(db_session, d1, {
        "interfaces": [{"nome": "10GE0/0/1.101", "phy": "up", "protocolo": "up"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    assert l2vc.valida_pos_l2vc(db_session, svc, snap_up) == []
    snap_down = _snapshot(db_session, d1, {
        "interfaces": [{"nome": "10GE0/0/1.101", "phy": "up", "protocolo": "up"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "down"}],
    })
    items = l2vc.valida_pos_l2vc(db_session, svc, snap_down)
    assert any(i["tipo"] == "l2vc.estado" and i["severidade"] == "critica" for i in items)
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/automation/test_l2vc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.automation.l2vc'`.

- [ ] **Step 3: Implementar o template**

Criar `src/gerenet/automation/templates/huawei_vrp/l2vc_ac.j2`:

```jinja2
interface {{ interface }}
{% if encapsulation == "qinq" %}
 encapsulation qinq vid {{ vid }} inner-vid {{ inner_vlan }}
{% else %}
 encapsulation dot1q vid {{ vid }}
{% endif %}
 mpls l2vc {{ vc_id }} encapsulation {{ "vlan-vpls" if encapsulation == "qinq" else "vlan" }} remote {{ remote_loopback }}{% if control_word %} control-word{% endif %}{% if flow_label %} flow-label{% endif %} mtu {{ mtu }}
```

O contexto passa `interface` como a subinterface completa (`naming.subinterface(trunk, vid)`, ex. `10GE0/0/1.101`) e `vid` em separado para o `encapsulation` — mesmo padrão de `subinterface.j2` (a linha 1 do template é `interface {{ interface }}`, nunca `interface X.vid`).

- [ ] **Step 4: Implementar `automation/l2vc.py`**

O módulo espelha `changes.py`/`render.py` (PlanoDevice, `_bloco_para_plano`, `_render_template`) sem tocar no fluxo de circuito. Código:

```python
"""Automação L2VC (spec §6): render dos ACs, planos e pré/pós-checks.

Usa o maquinário de `changes.py` (PlanoDevice, snapshot da última coleta)
e `render.py` (BlocoRender, templates), sem tocar no fluxo de circuito.
"""
import re

from sqlalchemy.orm import Session

from gerenet.automation import changes
from gerenet.automation.naming import subinterface
from gerenet.automation.render import BlocoRender, _render_template
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import _membro_loopback, get_l2vc

_SEM_L2VC_AVISO = (
    "Sem coleta do recurso 'l2vc' — plano gerado sem diff confiável; "
    "a execução re-valida (gate §5.3) e pode pular blocos já presentes."
)


def _par_loopback(session: Session, service: models.L2vcService, device_id: int) -> str:
    """Loopback LDP do PAR do endpoint (membro do domínio; exigido na criação)."""
    for ep in service.endpoints:
        if ep.device_id == device_id:
            continue
        loopback = _membro_loopback(session, service.domain_id, ep.device_id)
        if loopback is None:
            raise ValidationError(
                f"Par {ep.device_id} sem loopback LDP no domínio — revalide o serviço."
            )
        return loopback
    raise ValidationError("Serviço L2VC sem pontas — revalide o serviço.")


def render_l2vc(session: Session, service: models.L2vcService) -> dict[int, list[BlocoRender]]:
    """Blocos create por device (A/B) derivados da SoT via template."""
    service = get_l2vc(session, service.id)  # endpoints carregados
    por_device: dict[int, list[BlocoRender]] = {}
    loopbacks = {ep.device_id: _par_loopback(session, service, ep.device_id) for ep in service.endpoints}
    devices = {ep.device_id: session.get(models.Device, ep.device_id) for ep in service.endpoints}
    for ep in service.endpoints:
        vlan = session.get(models.Vlan, ep.vlan_id) if ep.vlan_id else None
        if vlan is None:
            raise ValidationError(
                f"Ponta {ep.interface} do serviço {service.name} sem VLAN reservada."
            )
        dev = devices[ep.device_id]
        support_fc = "mpls_flow_label" in (dev.capabilities or [])
        comandos = _render_template("l2vc_ac", {
            "interface": subinterface(ep.interface, vlan.vid),
            "vid": vlan.vid,
            "inner_vlan": ep.inner_vlan,
            "encapsulation": ep.encapsulation,
            "vc_id": service.vc_id,
            "remote_loopback": loopbacks[ep.device_id],
            "control_word": service.control_word,
            "flow_label": service.flow_label and support_fc,
            "mtu": ep.mtu or service.mtu,
        }).splitlines()  # _render_template devolve str; callers fazem .splitlines() (padrão _bloco_sub)
        por_device.setdefault(ep.device_id, []).append(BlocoRender(
            tipo="l2vc_ac", objeto="l2vc", objeto_id=service.id, comandos=comandos,
        ))
    return por_device


def estado_bloco_l2vc(bloco: dict, recursos: dict) -> str:
    """Presença do AC no encontrado, por identidade (vc-id + subinterface)."""
    comandos = bloco.get("comandos") or []
    if not comandos:
        return "ausente"
    partes = comandos[0].split(None, 1)
    if len(partes) < 2:
        return "ausente"
    nome = partes[1]
    if partes[0] == "undo":
        nome = nome.split(" ", 1)[1] if " " in nome else nome
    encontradas = [i for i in recursos.get("interfaces", []) if i.get("nome") == nome]
    vc_id = None
    for cmd in comandos:
        m = re.search(r"mpls l2vc (\d+)", cmd)
        if m:
            vc_id = int(m.group(1))
            break
    if bloco.get("acao", "create") == "delete":
        return "consta" if encontradas else "ausente"
    if not encontradas:
        return "ausente"
    if vc_id is None:
        return "conflito"
    linhas = [l for l in recursos.get("l2vc", []) if l.get("vc_id") == vc_id]
    if not linhas:
        return "conflito"  # subinterface presente sem o VC: parcial/mudada desde o plano
    if linhas[0].get("interface") not in (None, nome):
        return "conflito"
    return "consta"


_RECURSOS_L2VC = ("interfaces", "l2vc")
"""Recursos mínimos para diff confiável de um AC (espelho de `_RECURSOS_MINIMOS`)."""


def _recursos_snapshot(snap: models.DeviceSnapshot | None) -> tuple[dict, bool]:
    """(recursos, tem_l2vc) — recursos do snapshot ok, ou ({}, False) se vazio."""
    if snap is None or snap.resources is None:
        return {}, False
    return snap.resources, all(k in snap.resources for k in _RECURSOS_L2VC)


def plan_provision_l2vc(session: Session, service: models.L2vcService) -> list[changes.PlanoDevice]:
    """Plano de criação por ponta — blocos do render, menos os já presentes (§5.1)."""
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_l2vc(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if tem:
            a_aplicar = [
                changes._bloco_para_plano(b, "create")
                for b in blocos
                if estado_bloco_l2vc(changes._bloco_para_plano(b, "create"), recursos) != "consta"
            ]
        else:
            a_aplicar = [changes._bloco_para_plano(b, "create") for b in blocos]
        plano.append(changes.PlanoDevice(
            device_id=device_id,
            blocos=a_aplicar,
            baseline_snapshot_id=snap.id if snap is not None and tem else None,
            aviso=None if tem else _SEM_L2VC_AVISO,
        ))
    return plano


def plan_remocao_l2vc(session: Session, service: models.L2vcService) -> list[changes.PlanoDevice]:
    """Blocos delete por ponta; snapshot fresco obrigatório (padrão plan_remocao, §5.2).

    A identidade da remoção é a subinterface no recurso `interfaces` (o AC inteiro
    cai com `undo interface <sub>`), sem precisar do texto do backup.
    """
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_l2vc(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if not tem:
            raise ValidationError(
                "Sem snapshot recente com 'l2vc' para gerar a remoção — colete antes de remover (§5.2)."
            )
        a_remover: list[dict] = []
        for bloco in blocos:
            item = changes._bloco_para_plano(bloco, "delete")
            if bloco.comandos:
                item["comandos"] = [f"undo {bloco.comandos[0]}"]  # "interface X" -> "undo interface X"
            if estado_bloco_l2vc(item, recursos) == "consta":
                a_remover.append(item)
        plano.append(changes.PlanoDevice(
            device_id=device_id, blocos=a_remover, baseline_snapshot_id=snap.id,
        ))
    return plano


def valida_pre_checks_l2vc(session: Session, service: models.L2vcService, device: models.Device,
                           recursos: dict) -> str | None:
    """§12.2/§9.2 — peer LDP UP, sem binding conflitante, simetria (SoT)."""
    par_loopback = _par_loopback(session, service, device.id)
    ldp = recursos.get("mpls_ldp_peer")
    if ldp is None:
        return ("Coleta sem 'mpls_ldp_peer' — colete antes de executar (§5.3).")
    achado = next((l for l in ldp if l.get("peer_id") == par_loopback), None)
    if achado is None or str(achado.get("estado", "")).lower() != "up":
        return f"Par LDP {par_loopback} não está UP na coleta do {device.name} (§9.2)."
    ep = next((e for e in service.endpoints if e.device_id == device.id), None)
    if ep is None:
        return "Serviço L2VC sem ponta neste equipamento — revalide o serviço."
    vlan = session.get(models.Vlan, ep.vlan_id) if ep.vlan_id is not None else None
    esperado = subinterface(ep.interface, vlan.vid) if vlan is not None else ep.interface
    vc_linhas = [l for l in recursos.get("l2vc", []) if l.get("vc_id") == service.vc_id]
    if vc_linhas and vc_linhas[0].get("interface") not in (None, esperado):
        return (f"Binding conflitante: VC {service.vc_id} já está na interface "
                f"{vc_linhas[0].get('interface')} (esperado {esperado}).")
    # simetria (SoT): regex já imposta na criação; re-verifica aqui (§6)
    if len(service.endpoints) != 2:
        return "Serviço L2VC sem as duas pontas — revalide o serviço."
    e0, e1 = service.endpoints
    if e0.encapsulation != e1.encapsulation or (e0.mtu or service.mtu) != (e1.mtu or service.mtu):
        return "Pontas do L2VC assimétricas (encap/MTU) — revalide o serviço."
    return None


def valida_pos_l2vc(session: Session, service: models.L2vcService, snapshot: models.DeviceSnapshot) -> list[dict]:
    """Pós-check §13 — VC presente e UP na coleta pós-aplicação."""
    recursos = snapshot.resources or {}
    op = "unknown"
    linhas = [l for l in recursos.get("l2vc", []) if l.get("vc_id") == service.vc_id]
    achada = linhas[0] if linhas else None
    items: list[dict] = []
    if achada is None:
        items.append({
            "tipo": "l2vc.ausente", "severidade": "critica",
            "esperado": f"{service.name} (vc {service.vc_id})", "encontrado": "nao listado",
            "acao": "Verificar config do AC e revalidar (display l2vc).",
        })
    elif str(achada.get("estado", "")).lower() != "up":
        items.append({
            "tipo": "l2vc.estado", "severidade": "critica",
            "esperado": "up", "encontrado": str(achada.get("estado")),
            "acao": "Verificar estado do pseudowire/AC (LDP up, MTU, encap simétrico).",
        })
    return items
```

Contratos verificados no código atual: `_render_template(nome, contexto) -> str` (caller faz `.splitlines()`); `changes.PlanoDevice(device_id, blocos, baseline_snapshot_id=None, aviso=None)`; `changes._bloco_para_plano(bloco, acao)`; `changes._ultimo_snapshot_ok(session, device_id)`; `removal.texto_backup(snap)` (em `removal.py`, não em `changes` — o plano de remoção L2VC nem usa). O módulo acima reusa todos, sem helpers próprios.

- [ ] **Step 5: Ramo `l2vc_ac` no `_estado_do_bloco` do runner**

Em `src/gerenet/automation/runner.py`, no fim de `_estado_do_bloco` (antes do `return "ausente"  # tipo fora do repertório`, linha ~446):

```python
    if tipo == "l2vc_ac":
        from gerenet.automation.l2vc import estado_bloco_l2vc
        return estado_bloco_l2vc(bloco, recursos)
```

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/automation/test_l2vc.py -v && uv run pytest tests/automation/test_rendering.py tests/automation/test_runner_change.py -q`
Expected: PASS (novos) + regressão verde (runner tem o ramo novo, mas tipos antigos seguem o fluxo atual).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/automation/l2vc.py src/gerenet/automation/templates/huawei_vrp/l2vc_ac.j2 src/gerenet/automation/runner.py tests/automation/test_l2vc.py
git commit -m "feat(mpls): render/planos/pré-pós-checks de L2VC + estado do bloco no runner (fase 4 T6)"
```

---

### Task 7: ChangeRequest generalizado — modelo, migração com backfill, schema, serviço e hooks escopo-aware no runner

**Files:**
- Modify: `src/gerenet/domain/models.py` (`ChangeRequest`: `circuit_id` nullable, `escopo`, `l2vc_id`)
- Create: `alembic/versions/<hash>_change_request_escopo.py` (backfill `escopo='circuito'`)
- Modify: `src/gerenet/domain/schemas.py` (`ChangeRequestCreate`: `escopo`/`circuit_id?`/`l2vc_id?`)
- Modify: `src/gerenet/domain/services/change_requests.py` (`create_change_request` por escopo)
- Modify: `src/gerenet/automation/runner.py` (setup por escopo + gate + pré/pós-checks L2VC)
- Test: `tests/domain/test_change_requests_l2vc.py` + `tests/automation/test_runner_l2vc.py`

**Interfaces:**
- Consumes: T4 (`get_l2vc`), T6 (`plan_provision_l2vc`, `plan_remocao_l2vc`, `valida_pre_checks_l2vc`, `valida_pos_l2vc`); máquina de estados/step do ciclo D (intocada).
- Produces: `models.CHANGE_ESCOPO = ("circuito", "l2vc", "vsi")`; `ChangeRequest.escopo` / `.l2vc_id`; `ChangeRequestCreate(escopo="circuito", circuit_id: int | None, l2vc_id: int | None, ...)`; `create_change_request` aceita `l2vc_id` e valida conforme o escopo; runner: `_chaves_incompletas(recursos, erros, escopo="circuito")` (kwarg com default — call sites antigos seguem funcionando) com `_CHAVES_POR_ESCOPO = {"circuito": ("interfaces", "bgp_peers", "config_backup"), "l2vc": ("interfaces", "l2vc", "config_backup")}`; `run_change` setup por escopo; `_executa_step` pré-check e pós-check L2VC. Tasks 8, 13 consomem.

- [ ] **Step 1: Escrever os testes (failing)**

`tests/domain/test_change_requests_l2vc.py`:

```python
"""CR de L2VC — fase 4, spec §5 (escopo generalizado)."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from gerenet.domain.schemas import (
    ChangeRequestCreate, DeviceCreate, L2vcCreate, L2vcEndpointIn,
    MplsDomainCreate, MplsMemberIn, SiteCreate,
)
from gerenet.domain.services.change_requests import create_change_request
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import PlanoVazio, ValidationError
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def l2vc(db_session):
    site = create_site(db_session, SiteCreate(name="pop-cr"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-a", management_address="10.0.0.81"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-b", management_address="10.0.0.82"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cr"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.8.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.8.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="cr-test", vc_id=500,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=301),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=302),
        ],
    ), actor="cli")
    return d1, d2, svc


def test_cr_l2vc_nasce_com_2_steps(db_session, l2vc):
    d1, d2, svc = l2vc
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", motivo="Ativar L2VC do cliente.",
    ), ator_id=None)
    assert cr.escopo == "l2vc"
    assert cr.l2vc_id == svc.id
    assert cr.circuit_id is None
    assert {s.device_id for s in cr.steps} == {d1.id, d2.id}
    assert cr.status == "rascunho"


def test_cr_l2vc_exige_l2vc_id(db_session):
    # o schema valida o escopo (model_validator) na CONSTRUÇÃO — PydanticValidationError
    with pytest.raises(PydanticValidationError):
        ChangeRequestCreate(escopo="l2vc", motivo="sem id")


def test_cr_l2vc_desativado(db_session, l2vc):
    from gerenet.domain.services.mpls import set_l2vc_status
    _, _, svc = l2vc
    set_l2vc_status(db_session, svc.id, admin_status=False, actor="cli")
    from gerenet.domain.services.errors import ConflictError
    with pytest.raises(ConflictError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="l2vc", l2vc_id=svc.id, motivo="off",
        ), ator_id=None)


def test_cr_l2vc_remocao_plano_vazio_sem_snapshot_da_remocao(db_session, l2vc):
    """Sem snapshot: provision ainda gera plano (aviso), mas a remoção exige coleta (§5.2)."""
    d1, d2, svc = l2vc
    create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", motivo="provisionar primeiro",
    ), ator_id=None)
    # remoção sem snapshot fresco: ValidationError (mesma regra do circuito)
    with pytest.raises(ValidationError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="l2vc", l2vc_id=svc.id, acao="remove", motivo="remover sem coleta",
        ), ator_id=None)


def test_cr_circuito_default_inalterada(db_session):
    """Regressão: CR de circuito continua com escopo default e circuit_id obrigatório."""
    from gerenet.domain.schemas import CircuitCreate, OrganizationCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site
    from gerenet.domain.services.devices import create_device

    site = create_site(db_session, SiteCreate(name="pop-reg"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="r-reg", management_address="10.0.0.83"), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="reg", asn=64500), actor="cli")
    circ = create_circuit(db_session, CircuitCreate(
        code="reg-1", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1",
        edge_device_id=dev.id, stack="ipv4", vlan_mode="unica",
    ), actor="cli")
    cr = create_change_request(db_session, ChangeRequestCreate(
        circuit_id=circ.id, acao="provision", motivo="regressão circuito",
    ), ator_id=None)
    assert cr.escopo == "circuito"
    assert cr.circuit_id == circ.id
```

`tests/automation/test_runner_l2vc.py` (espelha `test_runner_change.py`: mesmo `VaultFake`, `_fakes_de_mudanca`, `Settings(_env_file=None, backups_dir=tmp_path)`):

```python
"""Runner escopo-aware — CR de L2VC (§5/§7 spec): gate, pré-check e pós-check."""
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from gerenet.automation import l2vc as l2vc_auto
from gerenet.automation.naming import subinterface
from gerenet.automation.runner import _chaves_incompletas, run_change
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.models import CredentialGroup
from gerenet.domain.schemas import (
    DeviceCreate, L2vcCreate, L2vcEndpointIn, MplsDomainCreate, MplsMemberIn, SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.sites import create_site


class VaultFake:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _ambiente_l2vc(db_session: Session):
    site = create_site(db_session, SiteCreate(name="pop-l2vc-run"), actor="cli")
    grupo = CredentialGroup(
        name="automacao-l2vc", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao-l2vc"
    )
    db_session.add(grupo)
    db_session.commit()
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.0.0.91", credential_group_id=grupo.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.0.0.92", credential_group_id=grupo.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-run"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.7.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.7.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="run-l2vc", vc_id=600,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=401),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=402),
        ],
    ), actor="cli")
    return d1, d2, svc


def _par_loopback(db_session, svc, dev) -> str:
    outros = [m for m in svc.domain.members if m.device_id != dev.id]
    return outros[0].loopback_address


def _recursos_l2vc_vazios(db_session, dev, svc, *, peer_up: bool = True) -> dict:
    """Encontrado sem o AC — re-diff aplica tudo; LDP UP passa no pré-check."""
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [], "l2vc": [],
        "mpls_ldp_peer": ([{"peer_id": _par_loopback(db_session, svc, dev), "estado": "up"}]
                          if peer_up else []),
        "config_backup": {"backup": True},
    }


def _subs_do_render(db_session, dev, svc) -> list[str]:
    nomes = []
    for ep in svc.endpoints:
        if ep.device_id != dev.id:
            continue
        vlan = db_session.get(models.Vlan, ep.vlan_id)
        nomes.append(subinterface(ep.interface, vlan.vid))
    return nomes


def _recursos_l2vc_aplicados(db_session, dev, svc, *, estado: str = "up") -> dict:
    nomes = _subs_do_render(db_session, dev, svc)
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [{"nome": n, "phy": "up", "protocolo": "up",
                        "enderecos_v4": [], "enderecos_v6": [], "vpn": None} for n in nomes],
        "l2vc": [{"vc_id": svc.vc_id, "interface": n, "estado": estado} for n in nomes],
        "mpls_ldp_peer": [{"peer_id": _par_loopback(db_session, svc, dev), "estado": "up"}],
        "config_backup": {"backup": True},
    }


def _cr_l2vc_aprovada(db_session, d1, d2, svc) -> models.ChangeRequest:
    plano = l2vc_auto.plan_provision_l2vc(db_session, svc)
    cr = models.ChangeRequest(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", criticidade="media",
        motivo="Ativação L2VC.", status="aprovado",
    )
    db_session.add(cr)
    db_session.flush()
    for item in plano:
        db_session.add(models.ChangeStep(
            change_request_id=cr.id, device_id=item.device_id, status="pendente",
            plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
            aviso=item.aviso,
        ))
    db_session.commit()
    db_session.refresh(cr)
    return cr


def _fakes_de_mudanca(monkeypatch, db_session, dev, colas: list[dict]):
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    ultimo: list[dict | None] = [None]

    def _coleta(session, device, cred, settings, base):
        recursos = colas.pop(0) if colas else ultimo[0]
        ultimo[0] = recursos
        return dict(recursos), {}, {}

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_aplicar",
        lambda device, username, password, commands, settings: {"config": ("\n".join(commands) + "\n")},
    )


def test_run_change_l2vc_fluxo_ok(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_l2vc_vazios(db_session, d1, svc), _recursos_l2vc_aplicados(db_session, d1, svc),
        _recursos_l2vc_vazios(db_session, d2, svc), _recursos_l2vc_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert cr.status == "aplicado"
    assert {s.status for s in cr.steps} == {"aplicado"}
    for step in cr.steps:
        assert step.post_check_json and "items" in step.post_check_json
        assert all(i["severidade"] != "critica" for i in step.post_check_json["items"])


def test_run_change_l2vc_pre_check_ldp_down_aborta(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [_recursos_l2vc_vazios(db_session, d1, svc, peer_up=False)] * 4
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    assert "LDP" in (cr.steps[0].erro or "")


def test_run_change_l2vc_pos_down_vira_com_divergencia(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_l2vc_vazios(db_session, d1, svc), _recursos_l2vc_aplicados(db_session, d1, svc, estado="down"),
        _recursos_l2vc_vazios(db_session, d2, svc), _recursos_l2vc_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "com_divergencia"
    db_session.refresh(cr)
    assert cr.status == "com_divergencia"
    step_a = next(s for s in cr.steps if s.device_id == d1.id)
    assert any(i["tipo"] == "l2vc.estado" and i["severidade"] == "critica"
               for i in step_a.post_check_json["items"])


def test_run_change_l2vc_bloco_ja_presente_marca_pulado(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    d1, d2, svc = _ambiente_l2vc(db_session)
    cr = _cr_l2vc_aprovada(db_session, d1, d2, svc)
    colas = [
        _recursos_l2vc_aplicados(db_session, d1, svc), _recursos_l2vc_aplicados(db_session, d1, svc),
        _recursos_l2vc_aplicados(db_session, d2, svc), _recursos_l2vc_aplicados(db_session, d2, svc),
    ]
    _fakes_de_mudanca(monkeypatch, db_session, d1, colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path),
                           session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert {s.status for s in cr.steps} == {"pulado"}


def test_chaves_incompletas_por_escopo() -> None:
    # gate do circuito continua exigindo bgp_peers; l2vc não exige (switch sem BGP)
    assert _chaves_incompletas({}, {}, escopo="circuito") == ["interfaces", "bgp_peers", "config_backup"]
    assert _chaves_incompletas({}, {}, escopo="l2vc") == ["interfaces", "l2vc", "config_backup"]
    # coleta de circuito com "l2vc" ausente não bloqueia
    assert "l2vc" not in _chaves_incompletas(
        {"interfaces": [], "bgp_peers": [], "config_backup": {}}, {}, escopo="circuito")
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_change_requests_l2vc.py -v`
Expected: FAIL — `AttributeError: ChangeRequestCreate` não tem `escopo`/`l2vc_id`.

- [ ] **Step 3: Modelo + migração**

Em `models.py`:

```python
CHANGE_ESCOPO = ("circuito", "l2vc", "vsi")
```

Na classe `ChangeRequest` (linha 472):
- `circuit_id` vira `Mapped[int | None] = mapped_column(ForeignKey("circuits.id"))`;
- adicionar após `circuit_id`:

```python
    escopo: Mapped[str] = mapped_column(
        Enum(*CHANGE_ESCOPO, name="change_escopo"), default="circuito", nullable=False
    )
    l2vc_id: Mapped[int | None] = mapped_column(ForeignKey("l2vc_services.id"))
```

Migração:

```python
"""change requests: escopo + l2vc_id (circuit_id nullable) — fase 4 T7"""
import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    change_escopo = sa.Enum("circuito", "l2vc", "vsi", name="change_escopo")
    change_escopo.create(op.get_bind(), checkfirst=True)
    op.add_column("change_requests", sa.Column("escopo", change_escopo, server_default="circuito", nullable=False))
    op.add_column("change_requests", sa.Column("l2vc_id", sa.Integer(), nullable=True))
    op.alter_column("change_requests", "circuit_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key("fk_change_requests_l2vc_id", "change_requests", "l2vc_services", ["l2vc_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_change_requests_l2vc_id", "change_requests", type_="foreignkey")
    op.drop_column("change_requests", "l2vc_id")
    op.drop_column("change_requests", "escopo")
    op.alter_column("change_requests", "circuit_id", existing_type=sa.Integer(), nullable=False)
```

Gerar o arquivo com `uv run alembic revision -m "change request escopo"` e substituir o corpo pelo acima (o autogenerate não adivinha o `server_default` de backfill). O `server_default="circuito"` é o backfill: todas as CRs existentes são de circuito — valor correto. Manter o server_default no schema final é o padrão do repo (migrations mantêm `server_default` — ex. `sa.true()` em `users.is_active`); o modelo repete `default="circuito"` do lado Python.

Rodar `uv run alembic upgrade head` em dev e no `gerenet_test`.

- [ ] **Step 4: Schema**

Em `schemas.py`:
1. no import do pydantic, adicionar `model_validator` — `from pydantic import BaseModel, ConfigDict, Field, model_validator`;
2. substituir `ChangeRequestCreate` por:

```python
class ChangeRequestCreate(BaseModel):
    escopo: Literal["circuito", "l2vc", "vsi"] = "circuito"
    circuit_id: int | None = None
    l2vc_id: int | None = None
    acao: Literal["provision", "remove"] = "provision"
    criticidade: Literal["baixa", "media", "alta"] = "media"
    motivo: str = Field(min_length=1, max_length=2000)
    ticket: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _valida_escopo(self) -> "ChangeRequestCreate":
        if self.escopo == "circuito" and self.circuit_id is None:
            raise ValueError("circuit_id é obrigatório para escopo 'circuito'.")
        if self.escopo == "l2vc" and self.l2vc_id is None:
            raise ValueError("l2vc_id é obrigatório para escopo 'l2vc'.")
        if self.escopo == "vsi":
            raise ValueError("Escopo 'vsi' não está disponível neste ciclo.")
        return self
```

Em `ChangeRequestOut`, adicionar `escopo: str` e `l2vc_id: int | None = None` (e `l2vc_name: str | None = None` quando o serviço serializar).

- [ ] **Step 5: Serviço por escopo**

Em `create_change_request` (leia o arquivo atual antes; o fluxo do ciclo D permanece para `escopo="circuito"`):

```python
def create_change_request(session, data: ChangeRequestCreate, *, ator_id=None, actor="cli"):
    # ... setup comum (usuario, auditoria, TRANSICOES) preservado ...
    if data.escopo == "l2vc":
        return _create_l2vc(session, data, ator_id=ator_id, actor=actor)
    # ... caminho atual de circuito (circuit_id obrigatório já validado no schema) ...
```

Helper (no mesmo arquivo):

```python
def _create_l2vc(session, data: ChangeRequestCreate, *, ator_id=None, actor="cli"):
    from gerenet.automation import l2vc as l2vc_auto
    from gerenet.domain.services.mpls import get_l2vc, _membro_loopback
    from gerenet.domain.services.errors import ConflictError

    servico = get_l2vc(session, data.l2vc_id)  # NotFoundError propaga (404)
    if not servico.admin_status:
        raise ConflictError("Serviço L2VC desativado não recebe mudanças.")
    dom = servico.domain
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe mudanças.")
    plano = (
        l2vc_auto.plan_provision_l2vc(session, servico)
        if data.acao == "provision"
        else l2vc_auto.plan_remocao_l2vc(session, servico)
    )
    cr = models.ChangeRequest(
        circuit_id=None, l2vc_id=servico.id, acao=data.acao, criticidade=data.criticidade,
        motivo=data.motivo, ticket=data.ticket, solicitante_id=ator_id, status="rascunho",
        escopo="l2vc",
    )
    session.add(cr)
    session.flush()
    _cria_steps(session, cr, plano)
    if not cr.steps:
        raise PlanoVazio("Serviço L2VC sem pontas ativas — revalide antes de planejar.")
    registrar(
        session, tipo="change.created", ator=actor, objeto="change_request",
        objeto_id=cr.id, antes=None,
        depois={"l2vc_id": servico.id, "acao": cr.acao, "criticidade": cr.criticidade,
                "steps": len(cr.steps), "blocos": sum(len(s.plano_json) for s in cr.steps)},
    )
    session.commit()
    session.refresh(cr)
    return cr
```

Reusa `_cria_steps(session, cr, plano)` do mesmo arquivo (um step por PlanoDevice, mesmo com `blocos=[]` — espelho exato do caminho de circuito; a guarda de `PlanoVazio` roda após). Import local de `_cria_steps` desnecessário: está no mesmo módulo.

- [ ] **Step 6: Runner escopo-aware**

Em `runner.py`:

1. Substituir `_RE_DIFF_KEYS`/`_chaves_incompletas` (linhas 91-101):

```python
_CHAVES_POR_ESCOPO = {
    "circuito": ("interfaces", "bgp_peers", "config_backup"),
    "l2vc": ("interfaces", "l2vc", "config_backup"),
}

def _chaves_incompletas(recursos: dict, erros: dict, escopo: str = "circuito") -> list[str]:
    chaves = _CHAVES_POR_ESCOPO.get(escopo, _CHAVES_POR_ESCOPO["circuito"])
    return [k for k in chaves if k in erros or k not in recursos]
```

(e no comentário acima, explicar o escopo l2vc: pode omitir `bgp_peers` — switch sem BGP tem `display bgp peer` em erro na coleta.)

2. Chamadas: em `_executa_step` (linhas 578 e 612), passar o escopo:

```python
        incompletos_pre = _chaves_incompletas(recursos_pre, erros_pre, cr.escopo)
        ...
        incompletos_pos = _chaves_incompletas(recursos_pos, erros_pos, cr.escopo)
```

3. Pré-check L2VC (em `_executa_step`, após o gate `incompletos_pre` e antes do re-diff):

```python
        if cr.escopo == "l2vc":
            from gerenet.automation import l2vc as l2vc_auto
            from gerenet.domain.services.mpls import get_l2vc
            servico = get_l2vc(session, cr.l2vc_id)
            pre_erro = l2vc_auto.valida_pre_checks_l2vc(session, servico, dev, recursos_pre)
            if pre_erro is not None:
                raise ValueError(pre_erro)
```

4. Setup em `run_change` (linha 765):

```python
            if cr.escopo == "l2vc":
                from gerenet.domain.services.mpls import get_l2vc
                get_l2vc(session, cr.l2vc_id)  # setup: NotFoundError propaga
            else:
                get_circuit(session, cr.circuit_id)  # setup: NotFoundError propaga
```

5. Pós-check L2VC (em `_executa_step`, ramo provision — adicionar após o `resultado = reconciliar_device(...)`):

```python
            itens = [asdict(i) for i in resultado.items]
            if cr.escopo == "l2vc":
                from gerenet.automation import l2vc as l2vc_auto
                from gerenet.domain.services.mpls import get_l2vc
                servico = get_l2vc(session, cr.l2vc_id)
                itens += l2vc_auto.valida_pos_l2vc(session, servico, snap_pos)
            step.post_check_json = {"snapshot_id": snap_pos.id, "aviso": resultado.aviso, "items": itens}
```

- [ ] **Step 7: Runbook dos testes do runner**

Implementar `tests/automation/test_runner_l2vc.py` com base em `test_runner_change.py`:
- cenário A+B com snapshots (recursos com `interfaces`/`l2vc`/`mpls_ldp_peer`/`config_backup`), CR aprovada → `run_change` ⇒ `aplicado`, steps `aplicado`, `post_check_json` sem itens críticos;
- `_conectar_e_aplicar` mockado falhando **só** no device B ⇒ CR `parcial`, step B `falhou`, passo A `aplicado` (o lock e o desfecho seguem o ciclo D);
- idempotência: nova execução após `aplicado` ⇒ steps `pulado`/CR `aplicado`;
- regressão: CR de circuito com coleta em device que **não** tem `bgp_peers` ⇒ gate bloqueia (mensagem atual); com `escopo="circuito"` mas recurso `l2vc` faltando ⇒ NÃO bloqueia (não está nas chaves do circuito).

- [ ] **Step 8: Rodar os testes**

Run: `uv run pytest tests/domain/test_change_requests_l2vc.py tests/automation/test_runner_l2vc.py -v && uv run pytest tests/automation/test_runner_change.py tests/domain/test_change_requests.py -q`
Expected: PASS (novos) + regressão do ciclo D verde.

- [ ] **Step 9: Commit**

```bash
git add src/gerenet/domain/models.py alembic/versions/ src/gerenet/domain/schemas.py src/gerenet/domain/services/change_requests.py src/gerenet/automation/runner.py tests/domain/test_change_requests_l2vc.py tests/automation/test_runner_l2vc.py
git commit -m "feat(change): escopo l2vc na change request + runner escopo-aware (fase 4 T7)"
```

---

### Task 8: API e CLI — CR por escopo + endpoints CRUD de domínio/L2VC/VSI

**Files:**
- Create: `src/gerenet/api/routers/mpls.py`
- Modify: `src/gerenet/api/main.py` (include_router)
- Modify: `src/gerenet/api/routers/change_requests.py` (POST aceita `escopo`/`l2vc_id` — o schema já valida; conferir o handler de erro)
- Modify: `src/gerenet/cli/change_requests.py` (`--escopo`, `--l2vc-id`)
- Create: `src/gerenet/cli/mpls.py` (grupo `gerenet mpls`)
- Modify: `src/gerenet/cli/main.py` (registrar o grupo)
- Test: `tests/api/test_mpls_api.py` + `tests/api/test_change_requests_api.py` (casos l2vc) + `tests/cli/test_mpls_cli.py`

**Interfaces:**
- Consumes: T2/T4/T5 (serviços), T7 (schema/CR).
- Produces: rotas — `GET/POST /api/v1/mpls/domains`, `GET/PATCH /api/v1/mpls/domains/{id}`, `POST /api/v1/mpls/domains/{id}/members`, `DELETE /api/v1/mpls/domains/{id}/members/{device_id}`, `GET/POST /api/v1/mpls/l2vc`, `GET /api/v1/mpls/l2vc/{id}`, `PATCH /api/v1/mpls/l2vc/{id}/status`, `GET /api/v1/mpls/l2vc/{id}/plano`, `GET/POST /api/v1/mpls/vsi`, `GET /api/v1/mpls/vsi/{id}`; CLI `gerenet mpls domain add|list|add-member|remove-member`, `mpls l2vc add|list|show|set-status|plano`, `mpls vsi list|show`, `change-requests add --escopo l2vc --l2vc-id N`. Tasks 13-14 consomem.

- [ ] **Step 1: Escrever os testes (failing)**

`tests/api/test_mpls_api.py` (padrão `test_change_requests_api.py` — client, login/AdminUser):

```python
"""API MPLS — fase 4, spec §9."""
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


def _criar_site_devs_dominio(client, headers):
    site = client.post("/api/v1/sites", headers=headers, json={"name": "pop-api-mpls"}).json()
    d1 = client.post("/api/v1/devices", headers=headers,
                     json={"name": "sw-api-1", "management_address": "10.0.0.91"}).json()
    d2 = client.post("/api/v1/devices", headers=headers,
                     json={"name": "sw-api-2", "management_address": "10.0.0.92"}).json()
    dom = client.post("/api/v1/mpls/domains", headers=headers, json={"name": "dom-api"}).json()
    for dev, lp in ((d1, "10.255.7.1"), (d2, "10.255.7.2")):
        client.post(f"/api/v1/mpls/domains/{dom['id']}/members", headers=headers,
                    json={"device_id": dev["id"], "loopback_address": lp, "role": "pe"})
    return site, d1, d2, dom


def test_domains_crud_e_membros(client):
    headers = _auth()
    site, d1, d2, dom = _criar_site_devs_dominio(client, headers)
    assert client.get("/api/v1/mpls/domains", headers=headers).json()[0]["name"] == "dom-api"
    detalhe = client.get(f"/api/v1/mpls/domains/{dom['id']}", headers=headers).json()
    assert len(detalhe["members"]) == 2
    ok = client.patch(f"/api/v1/mpls/domains/{dom['id']}", headers=headers, json={"admin_status": False})
    assert ok.status_code == 200 and ok.json()["admin_status"] is False
    dup = client.post("/api/v1/mpls/domains", headers=headers, json={"name": "dom-api"})
    assert dup.status_code == 409
    naive = client.get("/api/v1/mpls/domains", headers=headers)
    assert len(naive.json()) == 0  # default exclude disabled


def test_l2vc_criar_com_409_e_plano(client):
    headers = _auth()
    site, d1, d2, dom = _criar_site_devs_dominio(client, headers)

    def _l2vc():
        return client.post("/api/v1/mpls/l2vc", headers=headers, json={
            "domain_id": dom["id"], "name": "api-l2vc", "vc_id": 800,
            "endpoints": [
                {"device_id": d1["id"], "interface": "10GE0/0/1", "encapsulation": "dot1q", "vid": 401},
                {"device_id": d2["id"], "interface": "10GE0/0/2", "encapsulation": "dot1q", "vid": 402},
            ]})
    criada = _l2vc()
    assert criada.status_code == 200
    svc = criada.json()
    assert svc["vc_id"] == 800 and len(svc["endpoints"]) == 2
    dupe = _l2vc()
    assert dupe.status_code == 409
    plano = client.get(f"/api/v1/mpls/l2vc/{svc['id']}/plano", headers=headers)
    assert plano.status_code == 200
    assert len(plano.json()) == 2  # um por ponta (blocos com aviso sem coleta)
    descon = client.patch(f"/api/v1/mpls/l2vc/{svc['id']}/status", headers=headers, json={"admin_status": False})
    assert descon.json()["admin_status"] is False
    assert client.get("/api/v1/mpls/l2vc", headers=headers).json() == []


def test_vsi_criar_e_consultar(client):
    headers = _auth()
    site, d1, d2, dom = _criar_site_devs_dominio(client, headers)
    criado = client.post("/api/v1/mpls/vsi", headers=headers, json={
        "domain_id": dom["id"], "name": "vsi api", "vsi_id": 550,
        "members": [d1["id"], d2["id"]],
    })
    assert criado.status_code == 200
    vsi = criado.json()
    assert vsi["vrp_name"] == "VSI-VSI-API-550"
    assert len(vsi["members"]) == 2
    assert client.get(f"/api/v1/mpls/vsi/{vsi['id']}", headers=headers).json()["vsi_id"] == 550


def test_change_request_l2vc(client):
    headers = _auth()
    site, d1, d2, dom = _criar_site_devs_dominio(client, headers)
    svc = client.post("/api/v1/mpls/l2vc", headers=headers, json={
        "domain_id": dom["id"], "name": "cr-api", "vc_id": 801,
        "endpoints": [
            {"device_id": d1["id"], "interface": "10GE0/0/1", "encapsulation": "dot1q", "vid": 411},
            {"device_id": d2["id"], "interface": "10GE0/0/2", "encapsulation": "dot1q", "vid": 412},
        ]}).json()
    cr = client.post("/api/v1/change-requests", headers=headers, json={
        "escopo": "l2vc", "l2vc_id": svc["id"], "acao": "provision", "motivo": "ativar", "criticidade": "baixa",
    })
    assert cr.status_code == 200
    body = cr.json()
    assert body["escopo"] == "l2vc" and len(body["steps"]) == 2
    sem_id = client.post("/api/v1/change-requests", headers=headers, json={
        "escopo": "l2vc", "acao": "provision", "motivo": "sem id",
    })
    assert sem_id.status_code == 422
```

(`test_change_requests_api.py` ganha o caso de 422/201 l2vc junto.)

`tests/cli/test_mpls_cli.py` (espelha `test_change_requests_cli.py`: `runner = CliRunner()` módulo e `app` de `gerenet.cli.main`; seed via services):

```python
"""CLI MPLS — fase 4, spec §9: smoke via CliRunner + DB real."""
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain.schemas import DeviceCreate, MplsDomainCreate, MplsMemberIn
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import add_domain_member, create_domain

runner = CliRunner()


def _dominio(db_session: Session) -> tuple[int, int, int]:
    d1 = create_device(db_session, DeviceCreate(name="sw-mpls-cli-1", management_address="10.0.0.81"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-mpls-cli-2", management_address="10.0.0.82"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cli", description="teste"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.8.1", role="pe"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.8.2", role="pe"), actor="cli")
    db_session.commit()
    return d1.id, d2.id, dom.id


def test_domain_add_list(db_session: Session) -> None:
    _dominio(db_session)
    add = runner.invoke(app, ["mpls", "domain", "add", "--name", "dom-cli-2", "--description", "via cli"])
    assert add.exit_code == 0, add.output
    assert "Domínio" in add.output and "dom-cli-2" in add.output
    lista = runner.invoke(app, ["mpls", "domain", "list"])
    assert lista.exit_code == 0, lista.output
    assert "dom-cli" in lista.output


def test_mpls_l2vc_add_list(db_session: Session) -> None:
    d1, d2, dom_id = _dominio(db_session)
    add = runner.invoke(app, [
        "mpls", "l2vc", "add",
        "--domain-id", str(dom_id), "--name", "l2vc-cli",
        "--device-a", str(d1), "--interface-a", "10GE0/0/1", "--vid-a", "501",
        "--device-b", str(d2), "--interface-b", "10GE0/0/2", "--vid-b", "502",
    ])
    assert add.exit_code == 0, add.output
    assert "l2vc-cli" in add.output and "VC-ID" in add.output
    lista = runner.invoke(app, ["mpls", "l2vc", "list"])
    assert lista.exit_code == 0, lista.output
    assert "l2vc-cli" in lista.output


def test_mpls_vsi_list_vazio(db_session: Session) -> None:
    lista = runner.invoke(app, ["mpls", "vsi", "list"])
    assert lista.exit_code == 0, lista.output
```

O fumo `test_change_requests_cli.py` ganha um caso de `change-requests add --escopo l2vc --l2vc-id N` (idem `test_cli_add_list_show_erros`, com o L2VC seedado via services e a asserção `"rascunho" in add.output` e `len(cr.steps) == 2`).

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/api/test_mpls_api.py tests/cli/test_mpls_cli.py -v`
Expected: FAIL — 404 nas rotas `/api/v1/mpls/...` (router inexistente) e `No such command 'mpls'` no CLI.

- [ ] **Step 3: Router da API**

Criar `src/gerenet/api/routers/mpls.py` seguindo o padrão de `routers/sites.py`/`change_requests.py` (deps `SessionDep`, `ActorDep`, `require_papel` para escrita; `mpls.domain.member_add` etc. em auditoria via serviços):

- Router `GET /mpls/domains` → `MplsDomainOut[]` (serializar `members` com `device_name` via lookup); `POST /mpls/domains`; `GET /mpls/domains/{domain_id}`; `PATCH /mpls/domains/{domain_id}`; `POST /mpls/domains/{domain_id}/members`; `DELETE /mpls/domains/{domain_id}/members/{device_id}`.
- `GET /mpls/l2vc` (`?domain_id=`); `POST /mpls/l2vc`; `GET /mpls/l2vc/{l2vc_id}`; `PATCH /mpls/l2vc/{l2vc_id}/status` (body `{"admin_status": bool}`); `GET /mpls/l2vc/{l2vc_id}/plano` → `list[PlanoL2vcOut]` = `[{device_id, blocos, aviso, baseline_snapshot_id}]` (chama `plan_provision_l2vc` puro — read-only; o tipo `PlanoL2vcOut` é definido em T11).
- `GET /mpls/vsi`; `POST /mpls/vsi`; `GET /mpls/vsi/{vsi_id}`.
- Handlers de erro: `ConflictError`→409, `NotFoundError`→404, `ValidationError`→400, `PlanoVazio`→422 (padrão do router de change_requests).

Serialização: os serviços já expõem `mpls.out_domain(dom)`, `mpls.out_l2vc(svc)` e `mpls.out_vsi(vsi)` (T2/T4/T5) — use-os como `response_model`-ready nos handlers de GET/POST/PATCH, sem montar dict manualmente. Para a rota de plano, mapeie os `PlanoDevice` de `l2vc.plan_provision_l2vc` para o shape `PlanoL2vcOut` (ver T11): `asdict`-like `{device_id, blocos, aviso, baseline_snapshot_id}`.

Em `api/main.py`, adicionar `mpls` ao import de `routers` e `app.include_router(mpls.router)`.

- [ ] **Step 4: CLI**

`src/gerenet/cli/change_requests.py` — em `add`, o `circuit_id` deixa de ser obrigatório e entram as opções de escopo (a validação cruzada fica no schema, T7):

```python
@app.command("add")
def add(
    motivo: str = typer.Option(..., help="Motivo da mudança."),
    escopo: Literal["circuito", "l2vc", "vsi"] = typer.Option(
        "circuito", "--escopo", help="circuito, l2vc ou vsi."
    ),
    circuit_id: int | None = typer.Option(None, "--circuit-id", help="ID do circuito (escopo circuito)."),
    l2vc_id: int | None = typer.Option(None, "--l2vc-id", help="ID do serviço L2VC (escopo l2vc)."),
    ticket: str | None = typer.Option(None, help="Ticket de referência."),
    acao: Literal["provision", "remove"] = typer.Option("provision", "--acao", help="provision ou remove."),
    criticidade: Literal["baixa", "media", "alta"] = typer.Option(
        "media", "--criticidade", help="baixa, media ou alta."
    ),
) -> None:
    """Cria uma change request (plano congelado; nasce rascunho)."""
    with get_session() as session:
        try:
            cr = svc.create_change_request(
                session,
                ChangeRequestCreate(
                    escopo=escopo, circuit_id=circuit_id, l2vc_id=l2vc_id,
                    acao=acao, criticidade=criticidade, motivo=motivo, ticket=ticket,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        # steps contados dentro da sessão (lazy): após o close, viraria
        # DetachedInstanceError no eco final.
        n_steps = len(cr.steps)
        n_blocos = sum(len(s.plano_json) for s in cr.steps)
    typer.echo(
        f"CR #{cr.id} criada (rascunho): {n_steps} step(s), {n_blocos} bloco(s)."
    )
```

(`list` ganha `escopo: Literal[...] = typer.Option(None, "--escopo", help="Filtra por escopo.")` e repassa a `list_change_requests`; o eco ganha `{cr.escopo}` depois do status.)

`src/gerenet/cli/mpls.py` (novo; espelha o estilo de `cli/circuits.py` — `get_session()`, `typer.echo` de erro com `exit 1`, subgrupos via `add_typer`):

```python
"""MPLS em switches no CLI (spec §9): domínios, L2VC e VSI.

`gerenet mpls` vira `mpls domain ...` / `mpls l2vc ...` / `mpls vsi ...`
via `add_typer` no próprio arquivo; `cli/main.py` registra só o grupo raiz.
"""
from typing import Literal

import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.automation import l2vc as l2vc_auto
from gerenet.db import get_session
from gerenet.domain.schemas import L2vcCreate, L2vcEndpointIn, MplsDomainCreate, MplsMemberIn
from gerenet.domain.services import mpls as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(no_args_is_help=True, help="MPLS em switches (domínios, L2VC, VSI).")
domain_app = typer.Typer(no_args_is_help=True, help="Domínios MPLS.")
l2vc_app = typer.Typer(no_args_is_help=True, help="Serviços L2VC.")
vsi_app = typer.Typer(no_args_is_help=True, help="Serviços VSI (consulta).")
app.add_typer(domain_app, name="domain")
app.add_typer(l2vc_app, name="l2vc")
app.add_typer(vsi_app, name="vsi")


@domain_app.command("add")
def domain_add(
    name: str = typer.Option(..., help="Nome do domínio MPLS."),
    description: str | None = typer.Option(None, help="Descrição."),
) -> None:
    """Cadastra um domínio MPLS."""
    with get_session() as session:
        try:
            dom = svc.create_domain(
                session, MplsDomainCreate(name=name, description=description), actor="cli"
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Domínio #{dom.id} criado: {dom.name}")


@domain_app.command("list")
def domain_list(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista domínios MPLS."""
    with get_session() as session:
        for dom in svc.list_domains(session, include_disabled=include_disabled):
            n = len(dom.members)
            typer.echo(
                f"{dom.id:>3}  {dom.name:<20} "
                f"{'desativado' if not dom.admin_status else 'ativo':<10} {n} membro(s)"
            )


@domain_app.command("add-member")
def domain_add_member(
    domain_id: int = typer.Option(..., "--domain-id", help="ID do domínio."),
    device_id: int = typer.Option(..., "--device-id", help="ID do equipamento (PE)."),
    loopback: str = typer.Option(..., "--loopback", help="Loopback LDP."),
    role: Literal["pe", "core"] = typer.Option("pe", help="pe ou core."),
) -> None:
    """Adiciona um equipamento ao domínio."""
    with get_session() as session:
        try:
            membro = svc.add_domain_member(
                session, domain_id,
                MplsMemberIn(device_id=device_id, loopback_address=loopback, role=role),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"{membro.device_id} adicionado ao domínio #{domain_id} (loopback {loopback}).")


@domain_app.command("remove-member")
def domain_remove_member(
    domain_id: int = typer.Option(..., "--domain-id", help="ID do domínio."),
    device_id: int = typer.Option(..., "--device-id", help="ID do equipamento."),
) -> None:
    """Remove um equipamento do domínio."""
    with get_session() as session:
        try:
            svc.remove_domain_member(session, domain_id, device_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"{device_id} removido do domínio #{domain_id}.")


@l2vc_app.command("add")
def l2vc_add(
    domain_id: int = typer.Option(..., "--domain-id", help="ID do domínio MPLS."),
    name: str = typer.Option(..., help="Nome lógico do serviço."),
    vc_id: int | None = typer.Option(None, "--vc-id", help="VC-ID (default: próximo livre do domínio)."),
    device_a: int = typer.Option(..., "--device-a", help="ID do switch da ponta A."),
    interface_a: str = typer.Option(..., "--interface-a", help="Interface de acesso (ex.: 10GE0/0/1)."),
    vid_a: int = typer.Option(..., "--vid-a", help="VLAN de acesso da ponta A."),
    device_b: int = typer.Option(..., "--device-b", help="ID do switch da ponta B."),
    interface_b: str = typer.Option(..., "--interface-b", help="Interface de acesso (ex.: 10GE0/0/2)."),
    vid_b: int = typer.Option(..., "--vid-b", help="VLAN de acesso da ponta B."),
    encap: Literal["dot1q", "qinq"] = typer.Option("dot1q", help="dot1q ou qinq."),
    inner_vlan_a: int | None = typer.Option(None, "--inner-vlan-a", help="VLAN interna da ponta A (qinq)."),
    inner_vlan_b: int | None = typer.Option(None, "--inner-vlan-b", help="VLAN interna da ponta B (qinq)."),
    mtu: int | None = typer.Option(None, min=1500, max=9600, help="MTU do L2VC."),
    control_word: bool = typer.Option(False, "--control-word", help="Habilita control-word."),
    flow_label: bool = typer.Option(
        False, "--flow-label", help="Habilita flow-label (requer 'mpls_flow_label' na capability)."
    ),
    organization_id: int | None = typer.Option(None, "--organization-id", help="Organização (opcional)."),
) -> None:
    """Cadastra um serviço L2VC entre duas pontas."""
    with get_session() as session:
        try:
            servico = svc.create_l2vc(
                session,
                L2vcCreate(
                    domain_id=domain_id, name=name, vc_id=vc_id, organization_id=organization_id,
                    mtu=mtu, control_word=control_word, flow_label=flow_label,
                    endpoints=[
                        L2vcEndpointIn(
                            device_id=device_a, interface=interface_a, encapsulation=encap,
                            vid=vid_a, inner_vlan=inner_vlan_a, mtu=mtu,
                        ),
                        L2vcEndpointIn(
                            device_id=device_b, interface=interface_b, encapsulation=encap,
                            vid=vid_b, inner_vlan=inner_vlan_b, mtu=mtu,
                        ),
                    ],
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"L2VC #{servico.id} criado: {servico.name} (VC-ID {servico.vc_id})")


@l2vc_app.command("list")
def l2vc_list(
    domain_id: int | None = typer.Option(None, "--domain-id", help="Filtra por domínio."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista serviços L2VC."""
    with get_session() as session:
        for servico in svc.list_l2vc(session, domain_id=domain_id, include_disabled=include_disabled):
            estado = "desativado" if not servico.admin_status else servico.operational_status
            typer.echo(f"{servico.id:>3}  {servico.name:<24} vc {servico.vc_id:>5}  {estado}")


@l2vc_app.command("show")
def l2vc_show(l2vc_id: int = typer.Argument(..., help="ID do L2VC.")) -> None:
    """Mostra um L2VC: pontas e parâmetros."""
    with get_session() as session:
        try:
            servico = svc.get_l2vc(session, l2vc_id)
        except NotFoundError as exc:
            typer.echo(f"L2VC não encontrado: {l2vc_id}.", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"L2VC #{servico.id}: {servico.name} — VC-ID {servico.vc_id} ({servico.operational_status})")
        typer.echo(
            f"  mtu {servico.mtu} | control-word {'sim' if servico.control_word else 'não'} "
            f"| flow-label {'sim' if servico.flow_label else 'não'}"
        )
        for ep in servico.endpoints:
            typer.echo(f"  ponta device {ep.device_id}: {ep.interface} ({ep.encapsulation})")


@l2vc_app.command("set-status")
def l2vc_set_status(
    l2vc_id: int = typer.Argument(..., help="ID do L2VC."),
    ativo: bool = typer.Option(True, "--ativo/--inativo", help="Ativa (default) ou desativa o serviço."),
) -> None:
    """Reativa ou desativa um serviço L2VC."""
    with get_session() as session:
        try:
            servico = svc.set_l2vc_status(session, l2vc_id, admin_status=ativo, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"L2VC #{servico.id} {'ativado' if ativo else 'desativado'}.")


@l2vc_app.command("plano")
def l2vc_plano(l2vc_id: int = typer.Argument(..., help="ID do L2VC.")) -> None:
    """Mostra o plano de provision por ponta (sem executar)."""
    with get_session() as session:
        try:
            servico = svc.get_l2vc(session, l2vc_id)
        except NotFoundError as exc:
            typer.echo(f"L2VC não encontrado: {l2vc_id}.", err=True)
            raise typer.Exit(1) from exc
        for item in l2vc_auto.plan_provision_l2vc(session, servico):
            typer.echo(f"ponta device {item.device_id}: {len(item.blocos)} bloco(s)")
            for bloco in item.blocos:
                primeiro = bloco["comandos"][0] if bloco["comandos"] else "(sem comandos)"
                typer.echo(f"  {bloco['tipo']} {bloco['acao']}: {primeiro}")
            if item.aviso:
                typer.echo(f"  aviso: {item.aviso}")


@vsi_app.command("list")
def vsi_list(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista serviços VSI (consulta)."""
    with get_session() as session:
        for servico in svc.list_vsi(session, include_disabled=include_disabled):
            typer.echo(
                f"{servico.id:>3}  {servico.name:<24} vsi {servico.vsi_id:>5}  {servico.vrp_name}"
            )


@vsi_app.command("show")
def vsi_show(vsi_id: int = typer.Argument(..., help="ID do VSI.")) -> None:
    """Mostra um VSI: parâmetros e membros."""
    with get_session() as session:
        try:
            servico = svc.get_vsi(session, vsi_id)
        except NotFoundError as exc:
            typer.echo(f"VSI não encontrado: {vsi_id}.", err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"VSI #{servico.id}: {servico.name} ({servico.vrp_name}) — {servico.operational_status}")
        typer.echo(
            f"  mtu {servico.mtu} | split-horizon {'sim' if servico.split_horizon else 'não'} "
            f"| mac-limit {servico.mac_limit}"
        )
        for m in servico.members:
            typer.echo(f"  membro device {m.device_id}")
```

Em `cli/main.py`: adicionar `mpls` ao import de `gerenet.cli` e registrar `app.add_typer(mpls.app, name="mpls", help="MPLS em switches (domínios, L2VC, VSI).")` (mesmo padrão dos demais grupos).

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/api/test_mpls_api.py tests/api/test_change_requests_api.py tests/cli/test_mpls_cli.py tests/cli/test_change_requests_cli.py -v && uv run ruff check src tests && uv run ruff check --fix src/gerenet/cli/mpls.py`
Expected: PASS + ruff limpo.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/api/routers/mpls.py src/gerenet/api/main.py src/gerenet/api/routers/change_requests.py src/gerenet/cli/mpls.py src/gerenet/cli/change_requests.py src/gerenet/cli/main.py tests/api/test_mpls_api.py tests/api/test_change_requests_api.py tests/cli/test_mpls_cli.py
git commit -m "feat(mpls): API e CLI de domínios/L2VC/VSI + CR --escopo l2vc (fase 4 T8)"
```

---

### Task 9: Coletores + parsers TextFSM (mpls_ldp_peer, l2vc, vsi) + merges

**Files:**
- Modify: `src/gerenet/automation/collectors.py` (3 entradas novas)
- Create: `src/gerenet/automation/parsers/huawei_vrp/textfsm/mpls_ldp_peer.template`, `l2vc.template`, `vsi.template`
- Modify: `src/gerenet/automation/parsers/huawei_vrp/merge.py` (3 funções de merge)
- Test: `tests/automation/test_parsers_mpls.py`

**Interfaces:**
- Consumes: padrão de `COLLECTORS` (entradas `parsers`+`merge`), `parse_template`, `merge_parsed` (T1-B2, existentes).
- Produces: recursos de snapshot — `mpls_ldp_peer: [{"peer_id": str, "estado": "up"|"down"}]`, `l2vc: [{"vc_id": int, "interface": str|None, "estado": "up"|"down"}]`, `vsi: [{"name": str, "vsi_id": int|None, "estado": "up"|"down"}]` — tolerantes a vazio (output vazio ⇒ `[]`, nunca erro). Tasks 6, 10, 13 consomem.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/automation/test_parsers_mpls.py` (padrão dos testes de parser existentes — busque `test_parsers`/`parse_template` nos testes do ciclo B1 e espelhe):

```python
"""Parsers MPLS — fase 4, spec §8."""
from gerenet.automation.parsers.huawei_vrp.registry import parse_template


def test_mpls_ldp_peer_vazio():
    assert parse_template("mpls_ldp_peer", "") == []


def test_mpls_ldp_peer_cheio():
    saida = """
 Peer LDP ID : 10.255.9.2:0
  State       : Up
 Peer LDP ID : 10.255.9.3:0
  State       : Down
"""
    linhas = parse_template("mpls_ldp_peer", saida)
    assert {"peer_id": "10.255.9.2", "estado": "up"} in linhas
    assert {"peer_id": "10.255.9.3", "estado": "down"} in linhas


def test_l2vc_vazio_e_cheio():
    assert parse_template("l2vc", "") == []
    saida = """
 0 : VC-ID : 1000, Interface : 10GE0/0/1.101, State : Up
 1 : VC-ID : 1001, Interface : 10GE0/0/2.202, State : Down
"""
    linhas = parse_template("l2vc", saida)
    assert {"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"} in linhas
    assert {"vc_id": 1001, "interface": "10GE0/0/2.202", "estado": "down"} in linhas


def test_vsi_vazio_e_cheio():
    assert parse_template("vsi", "") == []
    saida = """
VSI Name : VSI-CLIENTE-ACME-550        VSI ID : 550
  State       : up
"""
    linhas = parse_template("vsi", saida)
    assert {"name": "VSI-CLIENTE-ACME-550", "vsi_id": 550, "estado": "up"} in linhas


def test_merge_vazios_devolvem_lista():
    from gerenet.automation.parsers.huawei_vrp.merge import merge_parsed
    assert merge_parsed("mpls_ldp_peer", {}) == []
    assert merge_parsed("l2vc", {}) == []
    assert merge_parsed("vsi", {}) == []
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/automation/test_parsers_mpls.py -v`
Expected: FAIL — `KeyError: 'mpls_ldp_peer'` no registry/merge (parser não existe).

- [ ] **Step 3: Templates TextFSM**

Crie os 3 arquivos em `src/gerenet/automation/parsers/huawei_vrp/textfsm/` seguindo o estilo de `bgp_peer.template` (Read ele antes):

`mpls_ldp_peer.template`:

```text
Value peer_id (\S+)
Value estado (\S+)

Start
  ^Peer LDP ID\s*:\s*${peer_id}\s*$ -> Continue
  ^\s*State\s*:\s*${estado} -> Record
```

Regras de merge (`mpls_ldp_peer`): a linha real é `Peer LDP ID : 10.255.9.2:0`, então `peer_id` chega como `"10.255.9.2:0"` — o merge normaliza com `peer_id.split(":")[0]` e `"up" if estado.lower() == "up" else "down"` (essa normalização é o que o teste de T9 Step 1 asserta).

`l2vc.template`:

```text
Value vc_id (\d+)
Value interface (\S+)
Value estado (\S+)

Start
  ^(\s*\d+\s*:\s*)?VC-ID\s*:\s*${vc_id},\s*Interface\s*:\s*${interface},\s*State\s*:\s*${estado}\s*$ -> Record
```

(O índice inicial `0 :` é opcional no regex — se a versão não imprimir o índice, a linha ainda casa. Regras de merge (`l2vc`): `vc_id` → `int`, `estado` → `"up" if lower() == "up" else "down"`; linha que não casar é ignorada pelo TextFSM sem erro.)

`vsi.template`:

```text
Value name (\S+)
Value vsi_id (\d+)
Value estado (\S+)

Start
  ^VSI Name\s*:\s*${name}\s+VSI ID\s*:\s*${vsi_id} -> Continue
  ^\s*State\s*:\s*${estado} -> Record
```

- [ ] **Step 4: Merge e coletores**

Em `merge.py`, funções novas (padrão `merge_interfaces` — cada uma trata `por_comando` como dict {comando: linhas} e devolve list):

```python
def normaliza_ldp(linhas: list[dict]) -> list[dict]:
    saida = []
    for l in linhas:
        peer = str(l.get("peer_id", "")).split(":")[0].strip()
        if not peer:
            continue
        saida.append({"peer_id": peer,
                      "estado": "up" if str(l.get("estado", "")).lower() == "up" else "down"})
    return saida


def normaliza_l2vc(linhas: list[dict]) -> list[dict]:
    saida = []
    for l in linhas:
        vc = l.get("vc_id")
        if vc is None:
            continue
        saida.append({
            "vc_id": int(vc),
            "interface": l.get("interface"),
            "estado": "up" if str(l.get("estado", "")).lower() == "up" else "down",
        })
    return saida


def normaliza_vsi(linhas: list[dict]) -> list[dict]:
    saida = []
    for l in linhas:
        if not l.get("name"):
            continue
        saida.append({
            "name": l["name"],
            "vsi_id": int(l["vsi_id"]) if l.get("vsi_id") not in (None, "") else None,
            "estado": "up" if str(l.get("estado", "")).lower() == "up" else "down",
        })
    return saida
```

E registrar no `merge_parsed` (você encontrará o mapeamento `_MERGES`/if/elif do arquivo — siga o padrão):

```python
    if nome == "mpls_ldp_peer":
        return normaliza_ldp(next(iter(por_comando.values())) if por_comando else [])
    if nome == "l2vc":
        return normaliza_l2vc(next(iter(por_comando.values())) if por_comando else [])
    if nome == "vsi":
        return normaliza_vsi(next(iter(por_comando.values())) if por_comando else [])
```

(um comando por recurso ⇒ `next(iter(...))`; vazio ⇒ `[]`.)

Em `collectors.py`, adicionar ao `COLLECTORS`:

```python
    "mpls_ldp_peer": {
        "commands": ["display mpls ldp peer"],
        "parsers": {"display mpls ldp peer": "mpls_ldp_peer"},
        "merge": "mpls_ldp_peer",
    },
    "l2vc": {
        "commands": ["display l2vc"],
        "parsers": {"display l2vc": "l2vc"},
        "merge": "l2vc",
    },
    "vsi": {
        "commands": ["display vsi"],
        "parsers": {"display vsi": "vsi"},
        "merge": "vsi",
    },
```

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/automation/test_parsers_mpls.py tests/automation/test_runner.py -q`
Expected: PASS + coleta existente verde (3 entradas novas só acrescentam comandos; se algum switch/router falhar em `display vsi` na coleta da suíte, verifique se a suíte usa `_coleta_recursos` com fakes de saída — ajuste os fakes para incluir os comandos novos, como foi feito no ciclo B1 para os comandos de interface/peer).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/collectors.py src/gerenet/automation/parsers/huawei_vrp/textfsm/mpls_ldp_peer.template src/gerenet/automation/parsers/huawei_vrp/textfsm/l2vc.template src/gerenet/automation/parsers/huawei_vrp/textfsm/vsi.template src/gerenet/automation/parsers/huawei_vrp/merge.py tests/automation/test_parsers_mpls.py
git commit -m "feat(mpls): coletores e parsers TextFSM de LDP/L2VC/VSI (fase 4 T9)"
```

---

### Task 10: Sincronização de estado operacional MPLS (coleta → serviços)

**Files:**
- Modify: `src/gerenet/domain/services/mpls.py` (`sincronizar_mpls`)
- Modify: `src/gerenet/automation/runner.py` (chamadas em `run_collection` e `_grava_snapshot`)
- Test: `tests/domain/test_mpls_sync.py`

**Interfaces:**
- Consumes: T1/T3/T4/T5, T9 (recursos `l2vc`/`vsi` no snapshot).
- Produces: `sincronizar_mpls(session, snapshot: models.DeviceSnapshot) -> None` — por linha do recurso `l2vc` do device do snapshot atualiza o `L2vcService`/`ServiceEndpoint` correspondente (match por `vc_id` + `device_id` + `interface` como guarda) e o `operational_status`/`last_collected_at`; idem `vsi` (match por `vsi_id` + `VsiMember.device_id`); agregação por serviço: todos os endpoints up ⇒ `up`; nenhum up ⇒ `down`; misto ⇒ `partial`; sem linha na coleta ⇒ mantém o status anterior. Sem efeito em devices sem MPLS (no-op). A consulta de VSI da web lê esses campos (T13).

- [ ] **Step 1: Escrever o teste (failing)**

`tests/domain/test_mpls_sync.py`:

```python
"""Sincronização de estado MPLS a partir da coleta — fase 4, spec §8/§9."""
import pytest

from gerenet.domain import models
from gerenet.domain.schemas import (
    DeviceCreate, L2vcCreate, L2vcEndpointIn, MplsDomainCreate, MplsMemberIn,
    SiteCreate, VsiCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import (
    add_domain_member, create_domain, create_l2vc, create_vsi, get_l2vc, get_vsi,
    sincronizar_mpls,
)
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def cenario(db_session):
    site = create_site(db_session, SiteCreate(name="pop-sync"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-s1", management_address="10.0.0.95"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-s2", management_address="10.0.0.96"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-sync"), actor="cli")
    for dev, lp in ((d1, "10.255.6.1"), (d2, "10.255.6.2")):
        add_domain_member(db_session, dom.id, MplsMemberIn(device_id=dev.id, loopback_address=lp), actor="cli")
    l2vc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="sync-l2vc", vc_id=900,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=601),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=602),
        ],
    ), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(domain_id=dom.id, name="sync vsi", vsi_id=610,
                                           members=[d1.id, d2.id]), actor="cli")
    return d1, d2, l2vc, vsi


def _snap(db_session, dev, recursos):
    snap = models.DeviceSnapshot(device_id=dev.id, status="success", resources=recursos)
    db_session.add(snap)
    db_session.commit()
    return snap


def test_sync_l2vc_up_nas_duas_pontas(db_session, cenario):
    d1, d2, l2vc, vsi = cenario
    _snap(db_session, d1, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1.601", "estado": "up"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d1.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1.601", "estado": "up"}]},
    ))
    _snap(db_session, d2, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2.602", "estado": "up"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d2.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2.602", "estado": "up"}]},
    ))
    svc = get_l2vc(db_session, l2vc.id)
    assert svc.operational_status == "up"
    assert svc.last_collected_at is not None
    assert all(ep.operational_status == "up" for ep in svc.endpoints)


def test_sync_l2vc_down_vira_down_e_misto_vira_partial(db_session, cenario):
    d1, d2, l2vc, _ = cenario
    _snap(db_session, d1, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1.601", "estado": "down"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d1.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1.601", "estado": "down"}]},
    ))
    assert get_l2vc(db_session, l2vc.id).operational_status == "down"
    _snap(db_session, d2, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2.602", "estado": "up"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d2.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2.602", "estado": "up"}]},
    ))
    assert get_l2vc(db_session, l2vc.id).operational_status == "partial"


def test_sync_vsi(db_session, cenario):
    d1, d2, _, vsi = cenario
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d1.id, status="success",
        resources={"vsi": [{"name": "VSI-SYNC-VSI-610", "vsi_id": 610, "estado": "up"}]},
    ))
    assert get_vsi(db_session, vsi.id).operational_status == "up"


def test_sync_sem_mpls_e_no_op(db_session, cenario):
    d1, d2, l2vc, vsi = cenario
    dev3 = create_device(db_session, DeviceCreate(name="sw-r", management_address="10.0.0.97"), actor="cli")
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=dev3.id, status="success", resources={"interfaces": []},
    ))
    assert get_l2vc(db_session, l2vc.id).operational_status == "unknown"
```

(obs.: o `_snap` do fixture é decorativo para `last_collected_at`; se preferir, crie o snapshot com `finished_at` explícito para asserts de data — ajuste conforme os fixtures reais do repo.)

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_mpls_sync.py -v`
Expected: FAIL — `ImportError` (`sincronizar_mpls` não existe).

- [ ] **Step 3: Implementar**

Em `mpls.py`:

```python
def _status_agregado(session: Session, endpoints: list) -> str:
    """Aggregate do serviço a partir do estado das pontas (up/partial/down)."""
    estados = {ep.operational_status for ep in endpoints}
    if not estados or estados == {"unknown"}:
        return "unknown"
    if estados == {"up"}:
        return "up"
    if "up" not in estados:
        return "down"
    return "partial"


def sincronizar_mpls(session: Session, snapshot: models.DeviceSnapshot) -> None:
    """Atualiza estado operacional dos serviços MPLS do device (coleta → SoT §8).

    Match L2VC: (vc_id, device, interface guard) sobre os endpoints do device;
    Match VSI: (vsi_id, membro do VSI no device). Linha ausente na coleta
    mantém o status anterior. Dispositivo sem MPLS: no-op.
    """
    recursos = snapshot.resources or {}
    mexeu = False
    agora = snapshot.finished_at
    for linha in recursos.get("l2vc", []) or []:
        vc_id = linha.get("vc_id")
        if vc_id is None:
            continue
        eps = session.scalars(
            select(models.ServiceEndpoint)
            .where(models.ServiceEndpoint.device_id == snapshot.device_id,
                   models.ServiceEndpoint.kind == "l2vc",
                   models.ServiceEndpoint.l2vc_id.isnot(None))
        ).all()
        ep = next((e for e in eps if e.l2vc.vc_id == int(vc_id) and
                   (linha.get("interface") in (None, e.interface))), None)  # interface guard
        if ep is None:
            continue
        estado = linha.get("estado", "unknown")
        ep.operational_status = estado
        svc = ep.l2vc
        svc.last_collected_at = agora or svc.last_collected_at
        svc.operational_status = _status_agregado(session, svc.endpoints)
        mexeu = True
    for linha in recursos.get("vsi", []) or []:
        vsi_id = linha.get("vsi_id")
        if vsi_id is None:
            continue
        membro = session.scalars(
            select(models.VsiMember).join(models.VsiService)
            .where(models.VsiMember.device_id == snapshot.device_id,
                   models.VsiService.vsi_id == int(vsi_id)).limit(1)
        ).first()
        if membro is None:
            continue
        vsi = membro.vsi
        vsi.operational_status = linha.get("estado", "unknown")
        vsi.last_collected_at = agora or vsi.last_collected_at
        mexeu = True
    if mexeu:
        session.flush()
        session.commit()
```

(A relação existe no modelo T1 como `ServiceEndpoint.l2vc` (back_populates `L2vcService.endpoints`) e `VsiMember.vsi` (`VsiService.members`). Carregue os endpoints/membros por selectin na consulta de match — o loop acima é por serviço do device, então o match `ep.vc_id` pode consultar `L2vcService` por `domain_id` + `vc_id` com `selectinload(L2vcService.endpoints)` e checar `ep.device_id`.)

No runner: chamar no fim do `run_collection` (após `session.commit()` do snapshot, linha ~174) e no fim de `_grava_snapshot` (após o `session.commit()`):

```python
    from gerenet.domain.services.mpls import sincronizar_mpls
    sincronizar_mpls(session, snapshot)
```

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/domain/test_mpls_sync.py -v && uv run pytest tests/automation/test_runner.py -q`
Expected: PASS + regressão verde.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/domain/services/mpls.py src/gerenet/automation/runner.py tests/domain/test_mpls_sync.py
git commit -m "feat(mpls): sincroniza estado operacional L2VC/VSI a partir da coleta (fase 4 T10)"
```

---

### Task 11: Web — tipos, hooks, rotas, nav MPLS e páginas (Domínios, L2VC, VSI, dashboard)

**Files:**
- Modify: `web/src/api/types.ts` (tipos MPLS + `ChangeRequestCreateIn` com `escopo`/`l2vc_id`)
- Modify: `web/src/api/hooks.ts` (hooks MPLS; `useChangeRequestCriar` já aceita o body novo via tipo)
- Modify: `web/src/App.tsx` (rotas `/mpls/domains`, `/mpls/domains/:id`, `/mpls/l2vc`, `/mpls/l2vc/:id`, `/mpls/vsi`, `/mpls/vsi/:id`)
- Modify: `web/src/components/Layout.tsx` (grupo "MPLS")
- Modify: `web/src/components/SolicitarMudanca.tsx` (aceitar `escopo`/`l2vc_id`)
- Modify: `web/src/components/SolicitarMudanca.test.tsx` (caso com `l2vc_id` — o arquivo existe)
- Create: `web/src/pages/MplsDomains.tsx`, `MplsL2vc.tsx`, `MplsL2vcDetail.tsx`, `MplsVsi.tsx`, `MplsVsiDetail.tsx`
- Modify: `web/src/pages/Dashboard.tsx` (card "Serviços MPLS")
- Test: `web/src/pages/MplsDomains.test.tsx`, `MplsL2vc.test.tsx`, `MplsVsi.test.tsx`

**Interfaces:**
- Consumes: rotas da T8; `useLista<T>`/`useCriar<TIn,TOut>`/`useAtualizar` (hooks.ts:84-110), componentes `DataTable`/`PageHeader`/`Modal`/`FormField`/`StatusBadge`/`TimeAgo`/`ConfirmDialog`, `useAuth().podeEscrever`, `ApiError`.
- Produces: hooks `useMplsDomains(opts)`, `useMplsDomainCriar`, `useMplsDomainAtualizar`, `useMplsMemberAdicionar`, `useMplsMemberRemover`, `useL2vc(opts)`, `useL2vcCriar`, `useL2vcDetalhe(id)`, `useL2vcStatus`, `useL2vcPlano(id)`, `useVsi(opts)`, `useVsiCriar`, `useVsiDetalhe(id)` (detalhe por `Detalhe` para não colidir com a lista — padrão `useCircuitDetail`); página `/mpls/domains` (CRUD + membros em Modal), `/mpls/l2vc` (lista com badges), `/mpls/l2vc/:id` (pontas + plano + "Solicitar mudança"), `/mpls/vsi` + `/mpls/vsi/:id` (somente leitura); dashboard com contagem L2VC/VSI.

- [ ] **Step 1: Escrever os testes (failing)**

`web/src/pages/MplsL2vc.test.tsx` (padrão `ChangeRequests.test.tsx`/`Sites.test.tsx` — mock dos hooks com `vi.mock`):

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MplsL2vc from "./MplsL2vc";

vi.mock("@/api/hooks", () => ({
  useL2vc: () => ({ data: [
    { id: 1, name: "cliente-acme", vc_id: 800, domain_name: "dom-api",
      admin_status: true, operational_status: "up" },
  ], isLoading: false, error: null }),
  // modal "Novo L2VC": selects de domínio e de devices + mutate de criação
  useMplsDomains: () => ({ data: [{ id: 1, name: "dom-api", admin_status: true }], isLoading: false, error: null }),
  useDevices: () => ({ data: [], isLoading: false, error: null }),
  useL2vcCriar: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock("@/auth/auth-context", () => ({ useAuth: () => ({ podeEscrever: true, ehAdmin: false }) }));

describe("MplsL2vc", () => {
  it("lista serviços com status operacional", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><MplsL2vc /></MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("cliente-acme")).toBeInTheDocument();
    expect(screen.getByText("up")).toBeInTheDocument();
  });
});
```

`MplsDomains.test.tsx` (lista + botão criar):

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MplsDomains from "./MplsDomains";

vi.mock("@/api/hooks", () => ({
  useMplsDomains: () => ({ data: [
    { id: 1, name: "dom-api", description: "switch do pop", admin_status: true, members: [] },
  ], isLoading: false, error: null }),
  useMplsDomainCriar: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock("@/auth/auth-context", () => ({ useAuth: () => ({ podeEscrever: true, ehAdmin: false }) }));

describe("MplsDomains", () => {
  it("lista domínios e exibe o botão de novo domínio", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><MplsDomains /></MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("dom-api")).toBeInTheDocument();
    expect(screen.getByText("Novo domínio")).toBeInTheDocument();
  });
});
```

`MplsVsi.test.tsx` (mostra `vrp_name`; mock de `useVsi` com um item `{ id: 1, vrp_name: "VSI-VSI-API-550", vsi_id: 550, name: "vsi api", admin_status: true }` e a asserção `screen.findByText("VSI-VSI-API-550")`, mesmo esqueleto de render acima — só trocam o mock e o texto assertado).

- [ ] **Step 2: Rodar e verificar falha**

Run: `npx vitest run src/pages/MplsL2vc.test.tsx`
Expected: FAIL — módulo `./MplsL2vc` não existe.

- [ ] **Step 3: Tipos e hooks**

`web/src/api/types.ts` — adicionar (seguindo o estilo do arquivo):

```ts
export interface MplsMemberOut { device_id: number; device_name: string | null; loopback_address: string; role: "pe" | "core" }
export interface MplsDomainOut { id: number; name: string; description: string | null; admin_status: boolean; created_at: string; updated_at: string; members: MplsMemberOut[] }
export interface MplsDomainCreateIn { name: string; description?: string | null }
export interface MplsDomainUpdateIn { name?: string; description?: string | null; admin_status?: boolean }
export interface MplsMemberIn { device_id: number; loopback_address: string; role?: "pe" | "core" }
export interface ServiceEndpointOut { id: number; kind: "l2vc" | "vsi"; device_id: number; device_name?: string | null; interface: string; encapsulation: "dot1q" | "qinq" | "ethernet_raw"; vlan_id: number | null; vid: number | null; inner_vlan: number | null; mtu: number | null; operational_status: string }
export interface L2vcOut { id: number; domain_id: number; domain_name?: string | null; vc_id: number; name: string; organization_id: number | null; mtu: number; control_word: boolean; flow_label: boolean; redundancy: string | null; description: string | null; admin_status: boolean; operational_status: string; last_collected_at: string | null; created_at: string; endpoints: ServiceEndpointOut[] }
export interface L2vcEndpointIn { device_id: number; interface: string; encapsulation?: "dot1q" | "qinq"; vid?: number | null; inner_vlan?: number | null; mtu?: number | null }
export interface L2vcCreateIn { domain_id: number; name: string; vc_id?: number | null; organization_id?: number | null; mtu?: number; control_word?: boolean; flow_label?: boolean; redundancy?: string | null; description?: string | null; endpoints: L2vcEndpointIn[] }
export interface PlanoBlocoL2vc { tipo: string; acao: "create" | "delete"; objeto_id: number; comandos: string[] }
export interface PlanoL2vcOut { device_id: number; blocos: PlanoBlocoL2vc[]; aviso: string | null; baseline_snapshot_id: number | null }
export interface VsiMemberOut { device_id: number; device_name?: string | null }
export interface VsiOut { id: number; domain_id: number; domain_name?: string | null; vsi_id: number; name: string; vrp_name: string; signaling: string; mtu: number; split_horizon: boolean; mac_learning: boolean; mac_limit: number | null; admin_status: boolean; operational_status: string; last_collected_at: string | null; members: VsiMemberOut[] }
export interface VsiCreateIn { domain_id: number; name: string; vsi_id?: number | null; mtu?: number; split_horizon?: boolean; mac_learning?: boolean; mac_limit?: number | null; members: number[] }
```

Em `ChangeRequestCreateIn` (existe em types.ts): adicionar `escopo?: "circuito" | "l2vc" | "vsi"; l2vc_id?: number | null; circuit_id?: number | null`. Em `ChangeRequestOut`: `escopo: "circuito" | "l2vc" | "vsi"; l2vc_id: number | null`.

`web/src/api/hooks.ts` — adicionar após os hooks de change requests, usando `useLista`/`useCriar`/`useAtualizar` (padrão hooks.ts:84-110) e queries diretas; no bloco `import type` do arquivo, acrescentar `MplsDomainOut`, `MplsMemberOut`, `L2vcOut`, `L2vcCreateIn`, `VsiOut`, `VsiCreateIn`, `PlanoL2vcOut`:

```ts
export function useMplsDomains(opts: { includeDisabled?: boolean } = {}) {
  return useLista<MplsDomainOut>("mpls-domains", "/api/v1/mpls/domains", opts);
}
export function useMplsDomainCriar() { return useCriar<MplsDomainCreateIn, MplsDomainOut>("mpls-domains", "/api/v1/mpls/domains"); }
export function useMplsDomainAtualizar() { return useAtualizar<MplsDomainUpdateIn, MplsDomainOut>("mpls-domains", "/api/v1/mpls/domains"); }
export function useMplsMemberAdicionar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ domainId, ...body }: { domainId: number } & MplsMemberIn) =>
      apiFetch<MplsMemberOut>(`/api/v1/mpls/domains/${domainId}/members`, { method: "POST", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["mpls-domains"] }),
  });
}
export function useMplsMemberRemover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ domainId, deviceId }: { domainId: number; deviceId: number }) =>
      apiFetch<void>(`/api/v1/mpls/domains/${domainId}/members/${deviceId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["mpls-domains"] }),
  });
}
export function useL2vc(opts: { domainId?: number; includeDisabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["mpls-l2vc", opts.domainId ?? null, opts.includeDisabled ?? false],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.domainId) qs.set("domain_id", String(opts.domainId));
      if (opts.includeDisabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<L2vcOut[]>(`/api/v1/mpls/l2vc${suf}`);
    },
  });
}
export const useL2vcCriar = () => useCriar<L2vcCreateIn, L2vcOut>("mpls-l2vc", "/api/v1/mpls/l2vc");
export const useL2vcDetalhe = (id: number) =>
  useQuery({ queryKey: ["mpls-l2vc", id], queryFn: () => apiFetch<L2vcOut>(`/api/v1/mpls/l2vc/${id}`), enabled: id > 0 });
export function useL2vcStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, admin_status }: { id: number; admin_status: boolean }) =>
      apiFetch<L2vcOut>(`/api/v1/mpls/l2vc/${id}/status`, { method: "PATCH", body: { admin_status } }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["mpls-l2vc"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
export function useL2vcPlano(id: number) {
  return useQuery({
    queryKey: ["mpls-l2vc-plano", id],
    queryFn: () => apiFetch<PlanoL2vcOut[]>(`/api/v1/mpls/l2vc/${id}/plano`),
    enabled: id > 0,
  });
}
export function useVsi(opts: { domainId?: number; includeDisabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["mpls-vsi", opts.domainId ?? null, opts.includeDisabled ?? false],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.domainId) qs.set("domain_id", String(opts.domainId));
      if (opts.includeDisabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<VsiOut[]>(`/api/v1/mpls/vsi${suf}`);
    },
  });
}
export const useVsiCriar = () => useCriar<VsiCreateIn, VsiOut>("mpls-vsi", "/api/v1/mpls/vsi");
export const useVsiDetalhe = (id: number) =>
  useQuery({ queryKey: ["mpls-vsi", id], queryFn: () => apiFetch<VsiOut>(`/api/v1/mpls/vsi/${id}`), enabled: id > 0 });
```

- [ ] **Step 4: Rotas, nav e SolicitarMudanca**

`App.tsx`: imports + rotas:

```tsx
<Route path="/mpls/domains" element={<MplsDomains />} />
<Route path="/mpls/domains/:id" element={<MplsDomains />} />
<Route path="/mpls/l2vc" element={<MplsL2vc />} />
<Route path="/mpls/l2vc/:id" element={<MplsL2vcDetail />} />
<Route path="/mpls/vsi" element={<MplsVsi />} />
<Route path="/mpls/vsi/:id" element={<MplsVsiDetail />} />
```

(`/mpls/domains/:id` renderiza `<MplsDomains />`: essa página faz lista+detalhe no mesmo componente, seguindo o padrão do `MplsDomains.tsx` do Step 5; as demais separam lista e detalhe em componentes distintos, como `Circuits`/`CircuitDetail`.)

`Layout.tsx` — grupo novo após "Roteamento":

```tsx
  {
    rotulo: "MPLS",
    itens: [
      { para: "/mpls/domains", rotulo: "Domínios" },
      { para: "/mpls/l2vc", rotulo: "Serviços L2VC" },
      { para: "/mpls/vsi", rotulo: "VSIs" },
    ],
  },
```

`SolicitarMudanca.tsx` — props `{ circuit_id?: number; l2vc_id?: number }`; no `mutateAsync` enviar `escopo: l2vc_id ? "l2vc" : "circuito"`, `circuit_id: circuit_id ?? null`, `l2vc_id: l2vc_id ?? null`; `CircuitDetail`/`BgpSessionDetail` continuam passando `circuit_id` (sem quebra: a prop vira opcional). Adicionar um `title`/rótulo no botão quando `l2vc_id` ("Solicitar mudança no L2VC"). `SolicitarMudanca.test.tsx` ganha um caso: renderizar com `l2vc_id={7}` (rota de teste), abrir o modal, preencher Motivo e submit, e assertar que o `mutateAsync` foi chamado com `{ escopo: "l2vc", circuit_id: null, l2vc_id: 7 }` — espelhando o caso existente de `circuit_id`.

- [ ] **Step 5: Páginas**

`MplsDomains.tsx` — lista (`DataTable`) com nome/descrição/status/membros; `PageHeader` + botão "Novo domínio" (`Modal` com `MplsDomainCreateIn`); em cada linha "Detalhe" (`/mpls/domains/:id`) — a **mesma página** recebe `useParams` e no modo detalhe renderiza a tabela de membros com `Modal` de adicionar membro (device select + loopback + role; `useMplsMemberAdicionar`), botão remover por membro (`ConfirmDialog` — o repo não usa `window.confirm`) + "Ativar/desativar" (`useMplsDomainAtualizar`). Formatação: `StatusBadge` para `admin_status`.

`MplsL2vc.tsx` — lista (id, nome, VC-ID, domínio, status admin, status operacional via `StatusBadge`); botão "Novo L2VC" (`Modal`): domínio select (`useMplsDomains`), nome, `vc_id` (opcional), ponta A/B: device select (`useDevices`), interface, encap select, vid, inner-vlan (se qinq), mtu; `useL2vcCriar`.

`MplsL2vcDetail.tsx` — carrega `useL2vcDetalhe(id)` (useParams); tabela de pontas (device, interface, encap, vid/inner, mtu, estado) + parâmetros (control-word, flow-label, mtu, redundancy); botão **"Solicitar mudança"** renderizando `<SolicitarMudanca l2vc_id={Number(id)} />`; link para `/change-requests`; seção "Plano previsto (diff da última coleta)" com `useL2vcPlano(id)` listando por device os blocos em `MonoCode` (padrão do `ChangeRequestDetail` para diff) e o `aviso` quando houver.

`MplsVsi.tsx` — lista (id, nome, `vrp_name`, VSI-ID, domínio, estado) via `useVsi(opts)`; `MplsVsiDetail.tsx` — somente leitura via `useVsiDetalhe(id)`: parâmetros (mtu, split_horizon, mac_learning, mac_limit, signaling) + membros (devices) + estado coletado.

`Dashboard.tsx` — nova `metric` (após a de mudanças pendentes):

```tsx
<div className="metric">
  <span className={`led ${((l2vc?.length ?? 0) + (vsi?.length ?? 0)) > 0 ? "green" : "gray"}`} aria-hidden="true" />
  <span className="val">{(l2vc?.length ?? 0) + (vsi?.length ?? 0)}</span>
  <span className="label">serviços<br />MPLS</span>
</div>
```

com `const { data: l2vc } = useL2vc();` e `const { data: vsi } = useVsi();` no componente (e `useL2vc, useVsi` acrescentados ao import de `@/api/hooks`, que hoje importa `useChangeRequests, useDashboard`).

- [ ] **Step 6: Build + testes**

Run: `cd web && npm run build && npm run test`
Expected: build (`tsc -b && vite build`) limpo; vitest verde (páginas novas + regressão das existentes — `Circuits.test.tsx`, `ChangeRequests.test.tsx` e `components/SolicitarMudanca.test.tsx` com o caso novo).

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "feat(web): páginas MPLS (domínios/L2VC/VSI), nav, solicitar mudança por escopo e card no dashboard (fase 4 T11)"
```

---

### Task 12: E2E — fumo MPLS (domínio + L2VC + solicitar mudança)

**Files:**
- Create: `web/e2e/mpls.spec.ts`
- Modify: (nenhum no setup — admin/aprovador já seedados; switches criados via API no próprio spec como `change.spec.ts` faz com o circuito)

**Interfaces:**
- Consumes: rotas web `/#/mpls/domains`, `/mpls/l2vc`, `/mpls/l2vc/:id`; API com `x-api-key`; padrões de `web/e2e/change.spec.ts` (`SENHA`, `API_KEY`, `RODADA`, `entrar`, `api` via `page.request`).

- [ ] **Step 1: Escrever o spec**

`web/e2e/mpls.spec.ts` (copie o esqueleto de `change.spec.ts`):

```ts
// RERUN-SAFE: RODADA = Date.now(); seeds únicos por execução.
// Fluxo: API cria site + 2 devices + domínio + membros + L2VC (vc-id da RODADA);
// web: login admin -> /mpls/l2vc -> abre o serviço -> "Solicitar mudança" -> motivo ->
//        CR criada (rascunho, 2 steps) -> muda para aprovador e rejeita (limpeza).
```

Passos concretos:
1. `RODADA = Date.now()`; via API: `POST /api/v1/sites` (name `e2e-mpls-${RODADA}`), 2× `POST /api/v1/devices` (`sw-a-${RODADA}`, `sw-b-${RODADA}`), `POST /api/v1/mpls/domains` (`dom-e2e-${RODADA}`), 2× `POST .../members` (loopback `10.99.${n}.1/2`), `POST /api/v1/mpls/l2vc` (`vc_id` = `1000 + (RODADA % 10000)`, vids `600 + (RODADA % 300)` / `700 + (RODADA % 300)`).
2. `entrar(page)` (admin); `page.goto("/mpls/l2vc")`; find pelo nome `e2e-mpls-ld-${RODADA}`; clicar no link do detalhe.
3. No detalhe: clicar "Solicitar mudança"; preencher `Motivo` (`mount via e2e ${RODADA}`); `Criticidade` = baixa; submit; esperar navegação para `/change-requests/:id`; esperar status "rascunho" e dois steps (use os mesmos seletores de `change.spec.ts` para CR — se a página de CR não renderizar "2 steps" por texto, use `getByText` de IDs de device).
4. Limpeza/round-trip: login como `e2e-aprovador` (senha `E2E_PASSWORD`), abrir a CR, rejeitar (como `change.spec.ts`), confirmar status `rejeitado`.
5. Asserts finais com `expect(page.getByText(...)).toBeVisible()`.

- [ ] **Step 2: Rodar o e2e**

Run: `cd web && npm run test:e2e -- mpls.spec.ts`
Expected: verde (o fumo sobe webServer + uvicorn na raiz com o banco `gerenet_e2e`; `reuseExistingServer: false`). Se a porta 8000 estiver ocupada, derrube o serviço antes.

- [ ] **Step 3: Commit**

```bash
git add web/e2e/mpls.spec.ts
git commit -m "test(e2e): fumo MPLS — domínio, L2VC e solicitar mudança (fase 4 T12)"
```

---

### Task 13: Runbook de validação em equipamento real (§10) + estado do repositório

**Files:**
- Create: `docs/runbook-validacao-switch-mpls.md`
- Modify: `docs/wiki/em-breve/mpls.md` (a página "Em breve" do ciclo E — remover `em_breve: true` do frontmatter e reescrever para o estado implementado)
- Modify: `CLAUDE.md` (parágrafo "Estado do repositório" — adicionar o resumo da fase 4)

**Interfaces:**
- Consumes: comandos/templates/parsers da T6/T9; fluxo de CR (T7/T8).

- [ ] **Step 1: Escrever o runbook**

`docs/runbook-validacao-switch-mpls.md` — em PT-BR, com as 3 etapas do spec §10 e os campos concretos:

1. **Etapa 1 — somente leitura** (contra os switches reais da família S):
   - `display mpls ldp peer`, `display l2vc`, `display vsi` — registrar **outputs reais** em fixtures (`tests/automation/test_parsers_mpls.py` + arquivos `textfsm`) — passos: colete os outputs, compare com o que os templates casam, ajuste os templates se o formato divergir, re-rode `uv run pytest tests/automation/test_parsers_mpls.py`.
   - Validar os **comandos do AC** (`interface X.Y` + `encapsulation dot1q vid`/`qinq ... inner-vid` + `mpls l2vc <vc-id> encapsulation vlan|vlan-vpls remote <loopback> [control-word] [mtu]`) contra um switch em modo sup/display only (use `display this`/`display configuration` em uma interface de teste **não conectada**) — ajuste `l2vc_ac.j2` se o VRP divergir e anote a versão correta (família/VRP) no próprio template via comentário.
   - `flow-label`/`control-word`: confirmar suporte na família S da versão alvo; registrar a string do `devices.capabilities` (`"mpls_flow_label"`).
2. **Etapa 2 — geração sem execução**: criar domínio + L2VC no SoT, abrir a CR em `rascunho` e revisar o diff por bloco (página de CR) — NÃO executar; conferir loopbacks LDP, VC-IDs, vids, encap e mtu para confirmar contra o `display` real.
3. **Etapa 3 — execução de teste**: serviço L2VC com `name`/organização de teste (`teste-...`), em **switch não crítico**, via CR aprovada no fluxo normal (aprovador ≠ solicitante): pré-checks (backup, coleta), execução, pós-check (`display l2vc` ⇒ `up`), rollback via CR inversa; registrar a decisão no **ledger**: data, equipamento, motivo, janela, resultado — a validação é em produção com escolha consciente (spec §10, sem lab por decisão do usuário 2026-09-07). Nada de execução automática sem aprovação (§3.3).
4. **Checklists** de pré/pós com os comandos exatos e os critérios de "ok" (LDP peer: `State: Up`; AC: `State: Up`; MTU consistente; sem alarmes novos no `display alarm`).

- [ ] **Step 2: Atualizar docs de estado**

Em `CLAUDE.md` — "Estado do repositório": parágrafo novo da fase 4 (modelos/CR escopo/coletores/web mpls, comandos de teste, nota de que a validação em produção depende do runbook).

Em `docs/wiki/em-breve/mpls.md` — frontmatter vira `title: Serviços MPLS (L2VC e VSI)`, `secao: MPLS`, `order: 2` (sem `em_breve: true`); o aviso "nesta fase, nada disso existe no código" sai, substituído por: domínio MPLS cadastrável com membros/loopbacks (página `/mpls/domains`), L2VC entre duas pontas com VC-ID único por domínio, reserva de VLAN por device, fluxo de mudança com escopo `l2vc` (CR aprovada → execução com pré-check LDP e pós-check), coleta e parsing de `display mpls ldp peer`/`display l2vc`, e **VSI apenas cadastro e consulta** (provisionamento multiponto vem em fase posterior) — com links para `/wiki/circuitos`, `/wiki/equipamentos` e `/wiki/mudancas-controladas` (os mesmos do rodapé atual) e para `runbook-validacao-switch-mpls.md` via nota em itálico ("validação em equipamento real: ver runbook...").

- [ ] **Step 3: Rodar a suíte completa**

Run: `uv run ruff check src tests && uv run pytest -q && cd web && npm run build && npm run test`
Expected: tudo verde (os e2e não rodam aqui — só no passo seguinte se o usuário rodar; o fumo T12 já foi validado isolado).

- [ ] **Step 4: Commit**

```bash
git add docs/runbook-validacao-switch-mpls.md CLAUDE.md docs/wiki/
git commit -m "docs(mpls): runbook de validação em equipamento real + estado do repositório (fase 4 T13)"
```

---

## Verificação final do plano

Depois de todas as tasks:
1. `uv run ruff check src tests` limpo.
2. `uv run pytest -q` completo verde (inclui regressão dos ciclos anteriores).
3. `cd web && npm run build && npm run test` limpo.
4. `cd web && npm run test:e2e` com banco `gerenet_e2e` (fumos: change + mpls).
5. Roteiro de validação em produção: seguir `docs/runbook-validacao-switch-mpls.md` (etapas 1→3 com o usuário; sem execução automática).

## Notas de desvio em relação ao spec (documentadas no próprio spec, §7)

1. **`devices.capabilities`** adicionado nesta fase (o B2 não o materializou); `flow_label` gated por `"mpls_flow_label"`.
2. **Runner escopo-aware** (gate e setup por `escopo`, pré/pós-checks L2VC chamados do runner) — necessário porque `_RE_DIFF_KEYS`/`run_change.get_circuit` são circuitocêntricos e uma CR de L2VC em switch sem BGP tropeçaria nos dois. Máquina de estados intocada.
3. **VLAN `mpls_ac` por device** (índice parcial) — decisão revisada do usuário em 2026-09-07 (mesmo VID legítimo em switches diferentes do mesmo POP).
4. **`service_endpoints.kind='vsi'`** existe no modelo (extensibilidade), mas nenhuma ponta VSI é criada neste ciclo (YAGNI §11.4).
