# Ciclo D — Fluxo de mudança controlada (gerenet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o fluxo de mudança controlada do gerenet — change requests a partir de circuitos BGP, geração de plano (provision + remove), aprovação registrada, execução aprovada no worker com backup/pré-checks/pós-validação e rollback conservador por comandos inversos.

**Architecture:** Abordagem A (estender padrões existentes). Modelos novos (`change_requests`, `change_steps`, `approvals`) + serviço puro em `domain/services/change_requests.py` espelhando os serviços atuais; plano puro em `automation/changes.py` derivando de `render_desejado` (provision, com skip de blocos já presentes) e de um novo render inverso `automation/removal.py` (remove, a partir do *encontrado* no snapshot); execução em `runner.run_change` na nova fila RQ `gerenet-change`, com lock por device + lock por CR, snapshot fresco como backup, aplicação bloco a bloco com parada em erro do VRP, pós-validação via reconcile + `display bgp peer`; API e CLI no padrão dos demais routers/groups; web com páginas de lista/detalhe + botões por papel + card no dashboard; rollback = novo CR inverso com `rollback_de`.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 (Mapped/mapped_column) + Alembic + Pydantic v2 + Typer + RQ/Redis + Netmiko + Jinja2 (existente) + React/Vite/React Query + Vitest + Playwright.

**Spec:** [docs/superpowers/specs/2026-09-05-gerenet-ciclo-d-mudanca-design.md](2026-09-05-gerenet-ciclo-d-mudanca-design.md) — o executor lê o spec junto do plano; regras divergentes: o spec ganha.

## Global Constraints

- **Idioma PT-BR** em mensagens de erro, docstrings, eventos de auditoria, textos de UI e commits.
- **Papéis (literais, models.py USER_ROLES):** `visualizador | operador | aprovador | executor | administrador`. Ações de escrita bloqueiam `visualizador` (já no `require_actor`); aprovação exige papel `aprovador`**ou** `administrador`; execução exige `executor`**ou** `administrador`.
- **Nomes VRP §25.4** sempre via `gerenet.automation.naming` (nunca hardcode: `rp_import/rp_export/pfx_in/pfx_produto/subinterface`).
- **Segredos nunca em logs/snapshots/auditoria**: `plano_json`, `post_check_json`, `details` de `AuditEvent` e saídas mascaradas seguem o padrão `domain/audit.mascarar` — communities/passwords nunca em texto.
- **`connect_and_run` permanece read-only** (allowlist `display...` em netmiko_conn.py). Comandos de escrita NUNCA passam por ela: o executor usa a nova `connect_and_apply` com denylist própria.
- **Migrations**: nova migration com `down_revision` = cabeça atual (verificar com `uv run alembic heads` — em 2026-09-05 é `7f668fb682d4`). Rodar `uv run alembic upgrade head` também no banco de teste `gerenet_test` (GERENET_DATABASE_URL apontado) — o env do alembic lê GERENET_DATABASE_URL.
- **conftest.py** (tests/conftest.py:41): o TRUNCATE precisa incluir as tabelas novas (`change_steps, approvals, change_requests`) — falha em esquecer deixa resíduo entre testes.
- **Verificação final obrigatória**: `uv run ruff check src tests` limpo · `uv run pytest -q` verde · `cd web && npm run build` · `npm run test` · e2e com banco dedicado `gerenet_e2e` e `reuseExistingServer: false`.
- **Locks Redis**: chave por device `gerenet:lock:device:{id}` (padrão runner.py) + nova chave por mudança `gerenet:lock:change:{id}`, token + TTL (settings.lock_ttl_seconds), liberação por compare-and-delete (`_liberta_lock`).

---

### Task 1: Modelos `ChangeRequest`/`ChangeStep`/`Approval` + migração + conftest

**Files:**
- Modify: `src/gerenet/domain/models.py` (enums + 3 classes; inserir após `UserSession`, antes do fim)
- Create: `alembic/versions/<hash>_change_requests_flow.py` (via `uv run alembic revision --autogenerate -m "change requests flow"`; ajustar manualmente se necessário)
- Modify: `tests/conftest.py:41-43` (lista do TRUNCATE)
- Test: `tests/domain/test_change_models.py`

**Interfaces:**
- Produces: enums `CHANGE_ACTION = ("provision", "remove")`, `CHANGE_CRITICALITY = ("baixa", "media", "alta")`, `CHANGE_STATUS = ("rascunho", "aguardando_aprovacao", "aprovado", "executando", "aplicado", "com_divergencia", "parcial", "erro", "rejeitado", "cancelado")`, `CHANGE_STEP_STATUS = ("pendente", "aplicado", "pulado", "falhou", "rollback")`, `APPROVAL_DECISION = ("aprovar", "rejeitar")`; classes `models.ChangeRequest`, `models.ChangeStep`, `models.Approval` (campos exatos abaixo). Tasks 2-10 consomem esses nomes.

- [ ] **Step 1: Escrever o teste (failing)**

`tests/domain/test_change_models.py`:

```python
"""Smoke dos modelos do fluxo de mudança — ciclo D, spec §4."""
from gerenet.domain import models


def test_enums_tem_os_valores_do_spec():
    assert models.CHANGE_ACTION == ("provision", "remove")
    assert models.CHANGE_CRITICALITY == ("baixa", "media", "alta")
    assert models.CHANGE_STATUS == (
        "rascunho", "aguardando_aprovacao", "aprovado", "executando",
        "aplicado", "com_divergencia", "parcial", "erro", "rejeitado", "cancelado",
    )
    assert models.CHANGE_STEP_STATUS == ("pendente", "aplicado", "pulado", "falhou", "rollback")
    assert models.APPROVAL_DECISION == ("aprovar", "rejeitar")


def test_modelos_existem_e_tabelas_esperadas():
    assert models.ChangeRequest.__tablename__ == "change_requests"
    assert models.ChangeStep.__tablename__ == "change_steps"
    assert models.Approval.__tablename__ == "approvals"


def test_criar_change_request_com_circuito(db_session):
    """FKs reais: circuito/device/organization + solicitante (aprovação exige usuário)."""
    from gerenet.domain.schemas import (
        CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate,
    )
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site
    from gerenet.domain.services.users import create_user

    site = create_site(db_session, SiteCreate(name="pop-teste"), actor="cli")
    dev = create_device(
        db_session, DeviceCreate(name="r1", management_address="10.0.0.1", asn=65000),
        actor="cli",
    )
    org = create_organization(db_session, OrganizationCreate(name="cliente", asn=64500), actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="circ-1", organization_id=org.id, site_id=site.id,
            access_device_id=dev.id, access_port="GE0/0/1",
            edge_device_id=dev.id, stack="ipv4", vlan_mode="unica",
        ),
        actor="cli",
    )
    sol = create_user(db_session, username="operador", password="senha12345", role="operador")
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao="provision", criticidade="media",
        motivo="Ativação do circuito.", solicitante_id=sol.id, status="rascunho",
    )
    db_session.add(cr)
    db_session.commit()
    assert cr.id is not None
    assert cr.status == "rascunho"

    step = models.ChangeStep(
        change_request_id=cr.id, device_id=dev.id, status="pendente",
        plano_json=[{"tipo": "subinterface", "objeto": "circuit", "objeto_id": circ.id,
                     "acao": "create", "comandos": ["interface GE0/0/1.100"]}],
    )
    db_session.add(step)
    db_session.commit()

    ap = models.Approval(
        change_request_id=cr.id, user_id=sol.id, decisao="aprovar", comentario="ok"
    )
    db_session.add(ap)
    db_session.commit()
    assert ap.id is not None
    assert cr.approvals[0].comentario == "ok"
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_change_models.py -v`
Expected: FAIL — `AttributeError: module 'gerenet.domain.models' has no attribute 'ChangeRequest'` (ou erro de tabela no commit).

- [ ] **Step 3: Implementar os modelos**

Em `src/gerenet/domain/models.py`, após `UserSession` (fim do arquivo), adicionar os enums no bloco de constantes (junto de `USER_ROLES = (...)` na linha 34):

```python
CHANGE_ACTION = ("provision", "remove")
CHANGE_CRITICALITY = ("baixa", "media", "alta")
# Terminales: aplicado, com_divergencia, rejeitado, cancelado (spec §4.1).
CHANGE_STATUS = ("rascunho", "aguardando_aprovacao", "aprovado", "executando",
                 "aplicado", "com_divergencia", "parcial", "erro", "rejeitado", "cancelado")
CHANGE_STEP_STATUS = ("pendente", "aplicado", "pulado", "falhou", "rollback")
APPROVAL_DECISION = ("aprovar", "rejeitar")
```

E as classes (no fim do arquivo):

```python
class ChangeRequest(Base):
    """Mudança controlada sobre um circuito (§12) — aprovação e execução registradas."""

    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_id: Mapped[int] = mapped_column(ForeignKey("circuits.id"), nullable=False)
    acao: Mapped[str] = mapped_column(Enum(*CHANGE_ACTION, name="change_action"), nullable=False)
    criticidade: Mapped[str] = mapped_column(
        Enum(*CHANGE_CRITICALITY, name="change_criticality"), default="media", nullable=False
    )
    motivo: Mapped[str] = mapped_column(Text(), nullable=False)
    ticket: Mapped[str | None] = mapped_column(String(64))
    solicitante_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(
        Enum(*CHANGE_STATUS, name="change_status"), default="rascunho", nullable=False
    )
    rollback_de: Mapped[int | None] = mapped_column(ForeignKey("change_requests.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    circuito: Mapped[Circuit] = relationship()
    solicitante: Mapped[User | None] = relationship()
    steps: Mapped[list["ChangeStep"]] = relationship(
        back_populates="change_request", order_by="ChangeStep.id", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="change_request", order_by="Approval.id", cascade="all, delete-orphan"
    )


class ChangeStep(Base):
    """Plano + resultado por equipamento afetado por uma mudança."""

    __tablename__ = "change_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_request_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*CHANGE_STEP_STATUS, name="change_step_status"), default="pendente", nullable=False
    )
    # [{tipo, objeto, objeto_id, acao: create|delete, comandos:[str]}] — plano congelado.
    plano_json: Mapped[list] = mapped_column(JSON, default=list)
    aviso: Mapped[str | None] = mapped_column(Text())  # §5.1: sem recursos p/ diff de skip
    baseline_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))
    backup_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))
    post_check_json: Mapped[dict | None] = mapped_column(JSON)
    erro: Mapped[str | None] = mapped_column(Text())
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    change_request: Mapped[ChangeRequest] = relationship(back_populates="steps")
    device: Mapped[Device] = relationship()


class Approval(Base):
    """Decisão de aprovação registrada na trilha (1 por mudança no MVP)."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_request_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    decisao: Mapped[str] = mapped_column(Enum(*APPROVAL_DECISION, name="approval_decision"), nullable=False)
    comentario: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    change_request: Mapped[ChangeRequest] = relationship(back_populates="approvals")
    user: Mapped[User] = relationship()
```

- [ ] **Step 4: Gerar a migração**

```bash
uv run alembic revision --autogenerate -m "change requests flow"
```

Verifique o arquivo gerado: deve criar `change_requests`, `change_steps`, `approvals` (+ tipos enum `change_action`, `change_criticality`, `change_status`, `change_step_status`, `approval_decision`) e FKs para `circuits`/`devices`/`users`/`device_snapshots` + FK autorreferente `rollback_de` em `change_requests`. Se o autogenerate perder algo (ex.: cascade), ajuste à mão seguindo o padrão de `6973e567cc43_circuits_edge_trunk_import_seed.py`. Confirme o `down_revision` com `uv run alembic heads` ANTES de revisar.

- [ ] **Step 5: Atualizar o TRUNCATE do conftest**

`tests/conftest.py:41` — a lista do TRUNCATE passa a começar com:

```python
"TRUNCATE approvals, change_steps, change_requests, audit_events, user_sessions, users, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations RESTART IDENTITY CASCADE"
```

- [ ] **Step 6: Migrar o banco de teste e rodar**

```bash
uv run alembic upgrade head
GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test" uv run alembic upgrade head
uv run pytest tests/domain/test_change_models.py -v
```

Expected: PASS (2 testes).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/models.py alembic/versions/ tests/domain/test_change_models.py tests/conftest.py
git commit -m "feat(models): change requests, steps e approvals + migração (ciclo D T1)"
```

---

### Task 2: Render inverso — `automation/removal.py`

**Files:**
- Create: `src/gerenet/automation/removal.py`
- Test: `tests/automation/test_removal.py`

**Interfaces:**
- Consumes: `gerenet.automation.naming` (funções `rp_import/rp_export/pfx_in/subinterface`), `gerenet.domain.services.bgp_sessions.list_sessions`, `gerenet.domain.models` (Circuit, DeviceSnapshot, BgpSession), JSON do snapshot (`resources`: `interfaces`, `bgp_peers`; `raw_files.config_backup` = caminho do txt).
- Produces: `blocos_remocao(session, circuito: models.Circuit, device_id: int, *, snapshot: models.DeviceSnapshot | None) -> list[dict]` — cada dict: `{"tipo": str, "objeto": "circuit"|"session", "objeto_id": int, "acao": "delete", "comandos": list[str]}` na ordem **inversa** da criação (peer → RP export → RP import → prefix-list → subinterface). Também exporta `texto_backup(snapshot) -> str` (usado pela Task 3).

- [ ] **Step 1: Escrever os testes (failing)**

Shape dos recursos no snapshot (o que os parsers reais produzem — ver `src/gerenet/automation/reconcile.py:104-131`): `resources["interfaces"]` = lista de dicts com key `nome`; `resources["bgp_peers"]` = lista de dicts com keys `afi`/`peer`/`asn`. O snapshot é montado à mão (sem coleta real), com `raw_files={"config_backup": [str(tmp_path / "cfg.txt")]}`.

Nota sobre os helpers: o serviço `_colidente_linha` (bgp_sessions.py:56) só conflita sessões **ativas** no mesmo (device, afi); `_colidente_par` (L77) só conflita pares ativos. Por isso as sessões "de outro circuito" dos testes 2/3 são criadas ativas e **desativadas** via `disable_session` (a config delas pode existir no equipamento — proteção conservadora, spec §14.1).

`tests/automation/test_removal.py`:

```python
"""Render inverso (remove) — blocos a partir do ENCONTRADO no snapshot (spec §5.2)."""
from pathlib import Path

from sqlalchemy import select

from gerenet.automation import naming, removal
from gerenet.domain import models


def _snapshot(db_session, device, *, interfaces=None, peers=None, backup="", tmp_path: Path):
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(backup, encoding="utf-8")
    snap = models.DeviceSnapshot(
        device_id=device.id, status="success",
        resources={"interfaces": interfaces or [], "bgp_peers": peers or []},
        raw_files={"config_backup": [str(arquivo)]},
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _ambiente(db_session):
    """site (com bloco p2p) + device (ASN 65000) + org (ASN 64500)."""
    from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site

    site = create_site(
        db_session, SiteCreate(name="pop-rm", p2p_ipv4_block="10.0.0.0/24"), actor="cli"
    )
    dev = create_device(
        db_session, DeviceCreate(name="ne8000-rm", management_address="10.0.0.1", asn=65000),
        actor="cli",
    )
    org = create_organization(db_session, OrganizationCreate(name="cliente-x", asn=64500), actor="cli")
    return {"site": site, "dev": dev, "org": org}


def _circuito(db_session, ambiente, *, code="circ-001", stack="ipv4"):
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.ipam import reservar_circuito

    circ = create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=ambiente["org"].id, site_id=ambiente["site"].id,
            access_device_id=ambiente["dev"].id, access_port="GE0/0/1",
            edge_device_id=ambiente["dev"].id, stack=stack, vlan_mode="unica",
            edge_trunk="GE1/0/0", p2p_v4_len=31,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    return circ


def _sessao(db_session, circ, dev, *, afi="ipv4", remote="100.64.1.2", local=None, ativa=True):
    from gerenet.domain.schemas import BgpSessionCreate
    from gerenet.domain.services.bgp_sessions import create_session, disable_session

    local_address = local or ("100.64.1.1" if afi == "ipv4" else "2001:db8::1")
    sessao = create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=dev.id, afi=afi,
            local_address=local_address, remote_address=remote,
            asn_local=65000, asn_remote=64500,
        ),
        actor="cli",
    )
    if not ativa:
        disable_session(db_session, sessao.id, actor="cli")
    return sessao


def _vid(db_session, circ):
    return db_session.scalar(
        select(models.Vlan.vid).where(models.Vlan.circuit_id == circ.id)
    )
```

Teste 1 — remoção completa (v4, sem compartilhamento):

```python
def test_remocao_v4_ordem_e_comandos(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb["dev"])
    vid = _vid(db_session, circ)
    subif = naming.subinterface("GE1/0/0", vid)
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"ip ip-prefix {naming.pfx_in(64500, 'ipv4')} index 10 permit 192.0.2.0/24\n"
            f"route-policy {naming.rp_import(64500, 'ipv4')} permit node 10\n"
            f"interface {subif}\n"
            f" vlan-type dot1q vid {vid}\n"
            f" ip address 100.64.1.1 255.255.255.254\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64500, "estado": "Established"}],
        interfaces=[{"nome": subif, "phy": "up", "protocolo": "up",
                     "enderecos_v4": ["100.64.1.1/31"], "enderecos_v6": []}],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    assert [b["tipo"] for b in blocos] == [
        "bgp_peer", "route_policy_export", "route_policy_import", "prefix_list", "subinterface",
    ]
    assert all(b["acao"] == "delete" for b in blocos)
    assert blocos[0]["comandos"] == ["bgp 65000", "undo peer 100.64.1.2"]
    assert blocos[1]["comandos"] == [f"undo route-policy {naming.rp_export(64500, 'ipv4')}"]
    assert blocos[2]["comandos"] == [f"undo route-policy {naming.rp_import(64500, 'ipv4')}"]
    assert blocos[3]["comandos"] == [f"undo ip ip-prefix {naming.pfx_in(64500, 'ipv4')}"]
    assert blocos[-1]["comandos"] == [f"undo interface {subif}"]
```

Teste 2 — peer compartilhado por outra sessão ⇒ `undo peer <ip>` COMPLETO fica proibido; entra undo por família:

```python
def test_remocao_peer_compartilhado_usa_undo_por_familia(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    sessao = _sessao(db_session, circ, amb["dev"])
    circ2 = _circuito(db_session, amb, code="circ-002")
    # Mesmo remote, local diferente (evita _colidente_par) e desativada
    # (ativa conflitaria no device+afi): a config do peer pode existir.
    _sessao(db_session, circ2, amb["dev"], remote="100.64.1.2", local="100.64.2.1", ativa=False)
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup="#",
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64500, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    peers_blocks = [b for b in blocos if b["tipo"] == "bgp_peer"]
    assert peers_blocks == [{
        "tipo": "bgp_peer", "objeto": "session", "objeto_id": sessao.id,
        "acao": "delete",
        "comandos": ["bgp 65000", "ipv4-family unicast", "undo peer 100.64.1.2 enable"],
    }]
```

Teste 3 — nomes §25.4 usados por outra sessão (mesmo asn_remote+afi) ficam no equipamento:

```python
def test_remocao_nao_remove_definicao_em_uso(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb["dev"])
    circ2 = _circuito(db_session, amb, code="circ-002")
    # Outra sessão com o MESMO (asn_remote, afi) => mesmos nomes de RP/prefix-list;
    # remote DIFERENTE para isolar esta regra (o peer do teste 1 continua completo).
    _sessao(db_session, circ2, amb["dev"], remote="100.64.1.99", local="100.64.2.1", ativa=False)
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"ip ip-prefix {naming.pfx_in(64500, 'ipv4')} index 10 permit 192.0.2.0/24\n"
            f"route-policy {naming.rp_import(64500, 'ipv4')} permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64500, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    assert {b["tipo"] for b in blocos} == {"bgp_peer"}
```

Teste 4 — §5.2: sem snapshot/recursos ⇒ não gera plano (exige coleta fresca):

```python
def test_remocao_sem_snapshot_nao_gera_plano(db_session):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb["dev"])
    assert removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=None) == []
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/automation/test_removal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.automation.removal'`.

- [ ] **Step 3: Implementar `automation/removal.py`**

```python
"""Render inverso (remoção) para o fluxo de mudança (spec ciclo D §5.2).

Gera blocos `delete` a partir do ENCONTRADO no snapshot (nunca do desejado):
`undo peer`, `undo route-policy`, `undo ip-prefix`, `undo interface`, na ordem
inversa à criação (peer → RP export → RP import → prefix-list → subinterface).
Regras de segurança:
- `undo peer <ip>` completo só quando NENHUMA outra sessão de outro circuito
  referencia o mesmo remote no device; senão undo por família
  (`undo peer <ip> enable`) — não derruba o par alheio. Qualquer sessão de
  outro circuito (ativa OU desativada) protege: a config dela pode existir.
- `undo route-policy`/`undo ip-prefix` só quando nenhuma outra sessão do mesmo
  (asn_remote, afi) os referencia no device — nomes §25.4 derivam do ASN.
- Sem snapshot/recursos ⇒ [] (exige coleta fresca antes do planejamento §5.2).
"""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import naming
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions


def texto_backup(snapshot: models.DeviceSnapshot | None) -> str:
    """Texto do `display current-configuration` salvo no snapshot (ou "")."""
    if snapshot is None:
        return ""
    arquivos = (snapshot.raw_files or {}).get("config_backup", [])
    if not arquivos:
        return ""
    try:
        return Path(str(arquivos[0])).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tem_prefix_list(texto: str, afi: str, nome: str) -> bool:
    cmd = "ip ipv6-prefix" if afi == "ipv6" else "ip ip-prefix"
    return f"{cmd} {nome} index" in texto


def _tem_route_policy(texto: str, nome: str) -> bool:
    return f"route-policy {nome} permit node" in texto


def _tem_peer(recursos: dict, remote: str) -> bool:
    return any(linha.get("peer") == remote for linha in recursos.get("bgp_peers", []))


def _outras_sessoes(session: Session, device_id: int, circuito_id: int) -> list:
    """Sessões de OUTROS circuitos no mesmo device (ativas ou desativadas)."""
    return [
        s for s in list_sessions(session, device_id=device_id, include_disabled=True)
        if s.circuit_id != circuito_id
    ]


def blocos_remocao(
    session: Session, circuito: models.Circuit, device_id: int, *,
    snapshot: models.DeviceSnapshot | None,
) -> list[dict]:
    """Blocos delete do circuito num device, a partir do snapshot (ver docstring)."""
    recursos = (snapshot.resources or {}) if snapshot is not None else {}
    texto = texto_backup(snapshot)
    sessoes = [
        s for s in list_sessions(session, circuit_id=circuito.id, include_disabled=True)
        if s.device_id == device_id
    ]
    outras = _outras_sessoes(session, device_id, circuito.id)
    blocos: list[dict] = []
    ja_undo_completo: set[str] = set()

    # 1) peers (ordem por afi/remote; 1 bloco por sessão)
    for sessao in sorted(sessoes, key=lambda s: (s.afi, s.remote_address)):
        if not _tem_peer(recursos, sessao.remote_address):
            continue
        compartilhado = any(
            outra.remote_address == sessao.remote_address for outra in outras
        )
        if compartilhado:
            blocos.append({
                "tipo": "bgp_peer", "objeto": "session", "objeto_id": sessao.id,
                "acao": "delete",
                "comandos": [
                    f"bgp {sessao.asn_local}",
                    f"{sessao.afi}-family unicast",
                    f"undo peer {sessao.remote_address} enable",
                ],
            })
        elif sessao.remote_address not in ja_undo_completo:
            ja_undo_completo.add(sessao.remote_address)
            blocos.append({
                "tipo": "bgp_peer", "objeto": "session", "objeto_id": sessao.id,
                "acao": "delete",
                "comandos": [f"bgp {sessao.asn_local}", f"undo peer {sessao.remote_address}"],
            })

    # 2) route-policy export/import + prefix-lists (nome por ASN+afi §25.4)
    prefix_lists: set[tuple[str, str]] = set()  # (afi, nome)
    for sessao in sorted(sessoes, key=lambda s: (s.afi, s.remote_address)):
        if sessao.asn_remote is None:
            continue
        nomes_compartilhados = any(
            outra.asn_remote == sessao.asn_remote and outra.afi == sessao.afi
            for outra in outras
        )
        if nomes_compartilhados:
            continue
        afi = sessao.afi
        nome_export = naming.rp_export(sessao.asn_remote, afi)
        if _tem_route_policy(texto, nome_export):
            blocos.append({
                "tipo": "route_policy_export", "objeto": "session",
                "objeto_id": sessao.id, "acao": "delete",
                "comandos": [f"undo route-policy {nome_export}"],
            })
        nome_import = naming.rp_import(sessao.asn_remote, afi)
        if _tem_route_policy(texto, nome_import):
            blocos.append({
                "tipo": "route_policy_import", "objeto": "session",
                "objeto_id": sessao.id, "acao": "delete",
                "comandos": [f"undo route-policy {nome_import}"],
            })
        nome_pfx = naming.pfx_in(sessao.asn_remote, afi)
        if _tem_prefix_list(texto, afi, nome_pfx):
            prefix_lists.add((afi, nome_pfx))

    # 3) prefix-lists (1 undo por nome)
    for afi, nome in sorted(prefix_lists):
        cmd = "undo ip ipv6-prefix" if afi == "ipv6" else "undo ip ip-prefix"
        blocos.append({
            "tipo": "prefix_list", "objeto": "circuit", "objeto_id": circuito.id,
            "acao": "delete", "comandos": [f"{cmd} {nome}"],
        })

    # 4) subinterfaces (1 undo por nome existente no snapshot)
    if circuito.edge_trunk and (
        circuito.edge_device_id == device_id or circuito.backup_edge_device_id == device_id
    ):
        nomes = {
            naming.subinterface(circuito.edge_trunk, vlan.vid)
            for vlan in session.scalars(
                select(models.Vlan).where(models.Vlan.circuit_id == circuito.id)
            )
        }
        existentes = {i["nome"] for i in recursos.get("interfaces", [])}
        for nome in sorted(nomes & existentes):
            blocos.append({
                "tipo": "subinterface", "objeto": "circuit",
                "objeto_id": circuito.id, "acao": "delete",
                "comandos": [f"undo interface {nome}"],
            })
    return blocos
```

- [ ] **Step 4: Rodar e verificar verde**

Run: `uv run pytest tests/automation/test_removal.py -v`
Expected: PASS (4 testes: ordinal, família, proteção de nomes, sem snapshot).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/removal.py tests/automation/test_removal.py
git commit -m "feat(automation): render inverso de remoção por encontrado (ciclo D T2)"
```

---

### Task 3: Plano — `automation/changes.py` (provision + remoção)

**Files:**
- Create: `src/gerenet/automation/changes.py`
- Test: `tests/automation/test_changes.py`

**Interfaces:**
- Consumes: `render_desejado(session, device_id) -> RenderResult{device_id, blocos: list[BlocoRender{tipo, objeto, objeto_id, comandos}], texto}` (render.py:356); `removal.blocos_remocao(session, circuito, device_id, *, snapshot) -> list[dict]` e `removal.texto_backup(snapshot) -> str` (Task 2); `list_sessions(session, circuit_id=..., device_id=..., include_disabled=...)` (bgp_sessions.py:191).
- Produces: dataclass `PlanoDevice(device_id: int, blocos: list[dict], baseline_snapshot_id: int | None = None, aviso: str | None = None)`; `plan_provision(session, circuito) -> list[PlanoDevice]`; `plan_remocao(session, circuito) -> list[PlanoDevice]` (levanta `ValidationError` se um device não tiver snapshot com recursos — §5.2). Tasks 4, 6, 7 (rollback) consomem.

- [ ] **Step 1: Escrever os testes (failing)**

Os testes derivam o "encontrado" do próprio render (snapshot simulado = config desejada aplicada): um snapshot honesto para exercitar o skip. Nota: `render_desejado` precisa de reserva (Vlan+IpPrefix), autorização de prefixo da org (senão não há bloco de import — render.py:192) e perfil de produto "full" (senão não há RP de export — render.py:259, seedado na migration e não truncado pelo conftest).

`tests/automation/test_changes.py`:

```python
"""Plano do ciclo D (spec §5): diff do render vs encontrado (provision) e inverso (remove)."""
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.automation import changes, render
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError


def _ambiente(db_session):
    from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site

    site = create_site(
        db_session, SiteCreate(name="pop-rm", p2p_ipv4_block="10.0.0.0/24"), actor="cli"
    )
    dev = create_device(
        db_session, DeviceCreate(name="ne8000-rm", management_address="10.0.0.1", asn=65000),
        actor="cli",
    )
    org = create_organization(db_session, OrganizationCreate(name="cliente-x", asn=64500), actor="cli")
    return {"site": site, "dev": dev, "org": org}


def _circuito(db_session, amb):
    from gerenet.domain.schemas import CircuitCreate, PrefixAuthorizationCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.ipam import reservar_circuito
    from gerenet.domain.services.prefix_authorizations import create_authorization

    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="circ-001", organization_id=amb["org"].id, site_id=amb["site"].id,
            access_device_id=amb["dev"].id, access_port="GE0/0/1",
            edge_device_id=amb["dev"].id, stack="ipv4", vlan_mode="unica",
            edge_trunk="GE1/0/0", p2p_v4_len=31,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=amb["org"].id, family="ipv4", prefix="192.0.2.0/24"
        ),
        actor="cli",
    )
    return circ


def _sessao(db_session, circ, amb, *, perfil_full=True):
    from gerenet.domain.schemas import BgpSessionCreate
    from gerenet.domain.services.bgp_sessions import create_session

    perfil_id = None
    if perfil_full:
        perfil = db_session.scalar(
            select(models.PolicyProfile).where(models.PolicyProfile.name == "full")
        )
        assert perfil is not None, "catálogo de produtos não seedado?"
        perfil_id = perfil.id
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=amb["dev"].id, afi="ipv4",
            local_address="100.64.1.1", remote_address="100.64.1.2",
            asn_local=65000, asn_remote=64500, export_profile_id=perfil_id,
        ),
        actor="cli",
    )


def _snapshot_encontrado(db_session, amb, tmp_path: Path):
    """Snapshot cujo estado ENCONTRADO é exatamente o desejado (render aplicado)."""
    r = render.render_desejado(db_session, amb["dev"].id)
    arquivo = tmp_path / "cfg.txt"
    arquivo.write_text(r.texto + "\n", encoding="utf-8")
    snap = models.DeviceSnapshot(
        device_id=amb["dev"].id, status="success",
        resources={
            "interfaces": [
                {"nome": b.comandos[0].split(None, 1)[1]}
                for b in r.blocos if b.tipo == "subinterface"
            ],
            "bgp_peers": [
                {"afi": "ipv4", "peer": b.comandos[1].split()[1], "asn": 64500}
                for b in r.blocos if b.tipo == "bgp_peer"
            ],
        },
        raw_files={"config_backup": [str(arquivo)]},
    )
    db_session.add(snap)
    db_session.commit()
    return snap
```

Notas: o bloco `bgp_peer` do render tem `comandos[0] == "bgp 65000"` e `comandos[1]` começando com `peer <ip>` — por isso o índice 1 com `.split()[1]` (cauteloso: use um loop simples se a ordem variar — o contrato é "o primeiro `peer ` command revela o remote", como em `removal._tem_peer`). Se o template unir tudo na linha 0, extraia com o mesmo padrão do `_peer_remote` da Task 2. Os testes abaixo:

```python
TIPOS_ESPERADOS = ["subinterface", "prefix_list", "route_policy_import", "route_policy_export", "bgp_peer"]


def test_plan_provision_gera_blocos_create_na_ordem_do_render(db_session):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    plano = changes.plan_provision(db_session, circ)
    assert [p.device_id for p in plano] == [amb["dev"].id]
    assert [b["tipo"] for b in plano[0].blocos] == TIPOS_ESPERADOS
    assert all(b["acao"] == "create" for b in plano[0].blocos)
    assert plano[0].baseline_snapshot_id is None
    assert plano[0].aviso is not None  # sem snapshot: skip vazio, aviso §5.1


def test_plan_provision_pula_blocos_ja_presentes(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    snap = _snapshot_encontrado(db_session, amb, tmp_path)
    plano = changes.plan_provision(db_session, circ)
    assert plano[0].blocos == []
    assert plano[0].baseline_snapshot_id == snap.id
    assert plano[0].aviso is None


def test_plan_provision_ignora_comentarios(db_session, tmp_path):
    """Divergências viram bloco `comentario` (render.py:254) — nunca comandos."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    # remove uma autorização depois de planejar? Não: o cenário é render com dívida.
    # Simular dívida: política é estável; o filtro `b.tipo != "comentario"` é o alvo.
    plano = changes.plan_provision(db_session, circ)
    assert all(b["tipo"] != "comentario" for p in plano for b in p.blocos)


def test_plan_remocao_usa_ordem_inversa_do_encontrado(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    _snapshot_encontrado(db_session, amb, tmp_path)
    plano = changes.plan_remocao(db_session, circ)
    assert [b["tipo"] for b in plano[0].blocos] == list(reversed(TIPOS_ESPERADOS))
    assert all(b["acao"] == "delete" for b in plano[0].blocos)
    assert plano[0].baseline_snapshot_id is not None
    assert plano[0].aviso is None


def test_plan_remocao_exige_snapshot_com_recursos(db_session):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    with pytest.raises(ValidationError, match="colete antes"):
        changes.plan_remocao(db_session, circ)
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/automation/test_changes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.automation.changes'`.

- [ ] **Step 3: Implementar `automation/changes.py`**

```python
"""Geração de plano do fluxo de mudança (spec ciclo D §5): diff do render vs.
encontrado (provision) e inversos a partir do encontrado (remove).

`PlanoDevice` carrega o que um step aplica num device + o baseline congelado
(tudo que a web/CLI exibem vem daqui; a execução re-checa §5.3 — mudou o
encontrado entre o plano e a execução ⇒ aborta).
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import removal, render
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.errors import ValidationError

_RECURSOS_MINIMOS = ("interfaces", "bgp_peers")
_SEM_RECURSOS_AVISO = (
    "Snapshot sem recursos de interfaces/peers: skip do diff vazio; "
    "a execução re-coleta antes do re-diff (§5.1)."
)


@dataclass
class PlanoDevice:
    device_id: int
    blocos: list[dict]
    baseline_snapshot_id: int | None = None
    aviso: str | None = None


def _ultimo_snapshot_ok(session: Session, device_id: int) -> models.DeviceSnapshot | None:
    return session.scalars(
        select(models.DeviceSnapshot)
        .where(
            models.DeviceSnapshot.device_id == device_id,
            models.DeviceSnapshot.status == "success",
        )
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(1)
    ).first()


def _bloco_para_plano(bloco: render.BlocoRender, acao: str) -> dict:
    return {
        "tipo": bloco.tipo, "objeto": bloco.objeto, "objeto_id": bloco.objeto_id,
        "acao": acao, "comandos": bloco.comandos,
    }


def _peer_remote(comandos: list[str]) -> str | None:
    for cmd in comandos:
        partes = cmd.split()
        if len(partes) >= 2 and partes[0] == "peer":
            return partes[1]
    return None


def _ja_existe(bloco: render.BlocoRender, recursos: dict, texto: str) -> bool:
    """§5.1 passo 3 — bloco cujos comandos já constam do encontrado (skip)."""
    if bloco.tipo == "subinterface":
        comandos = bloco.comandos or [""]
        nome = comandos[0].split(None, 1)[1] if " " in comandos[0] else ""
        return nome in {i.get("nome") for i in recursos.get("interfaces", [])}
    if bloco.tipo == "prefix_list":
        partes = bloco.comandos[0].split() if bloco.comandos else []
        if len(partes) >= 3 and partes[0] == "ip" and partes[1].endswith("-prefix"):
            return f"{partes[0]} {partes[1]} {partes[2]} index" in texto
        return False
    if bloco.tipo in ("route_policy_import", "route_policy_export"):
        partes = bloco.comandos[0].split() if bloco.comandos else []
        if len(partes) >= 2:
            return f"route-policy {partes[1]} permit node" in texto
        return False
    if bloco.tipo == "bgp_peer":
        remote = _peer_remote(bloco.comandos)
        return remote is not None and any(
            linha.get("peer") == remote for linha in recursos.get("bgp_peers", [])
        )
    return False


def plan_provision(session: Session, circuito: models.Circuit) -> list[PlanoDevice]:
    """Plano de criação por device — blocos do circuito no render, menos os já presentes."""
    sessoes = list_sessions(session, circuit_id=circuito.id)  # ativas (padrão)
    ids = {circuito.id} | {s.id for s in sessoes}
    plano: list[PlanoDevice] = []
    for device_id in sorted({s.device_id for s in sessoes}):
        resultado = render.render_desejado(session, device_id)
        snap = _ultimo_snapshot_ok(session, device_id)
        recursos = (snap.resources or {}) if snap is not None else {}
        texto = removal.texto_backup(snap)
        tem_recursos = all(k in recursos for k in _RECURSOS_MINIMOS)
        blocos = [
            _bloco_para_plano(b, "create")
            for b in resultado.blocos
            if b.tipo != "comentario"
            and b.objeto_id in ids
            and (not tem_recursos or not _ja_existe(b, recursos, texto))
        ]
        plano.append(PlanoDevice(
            device_id=device_id,
            blocos=blocos,
            baseline_snapshot_id=snap.id if snap is not None and tem_recursos else None,
            aviso=None if tem_recursos else _SEM_RECURSOS_AVISO,
        ))
    return plano


def plan_remocao(session: Session, circuito: models.Circuit) -> list[PlanoDevice]:
    """Plano de remoção por device — inversos a partir do ENCONTRADO (§5.2,
    todas as sessões do circuito, ativas ou desativadas).

    Exige snapshot success com recursos por device: sem ele, ValidationError
    (colete antes — nunca um plano de remoção otimista).
    """
    sessoes = list_sessions(session, circuit_id=circuito.id, include_disabled=True)
    devices = sorted({s.device_id for s in sessoes})
    if not devices:
        raise ValidationError(f"Circuito {circuito.code} sem sessões BGP — não há o que remover.")
    plano: list[PlanoDevice] = []
    for device_id in devices:
        snap = _ultimo_snapshot_ok(session, device_id)
        recursos = (snap.resources or {}) if snap is not None else {}
        sem_recursos = snap is None or not all(k in recursos for k in _RECURSOS_MINIMOS)
        if sem_recursos:
            raise ValidationError(
                f"Circuito {circuito.code}: sem snapshot recente com recursos no device "
                f"{device_id} — colete antes de planejar a remoção (§5.2)."
            )
        plano.append(PlanoDevice(
            device_id=device_id,
            blocos=removal.blocos_remocao(session, circuito, device_id, snapshot=snap),
            baseline_snapshot_id=snap.id,
        ))
    return plano
```

- [ ] **Step 4: Rodar e verificar verde**

Run: `uv run pytest tests/automation/test_changes.py -v`
Expected: PASS (5 testes). Se `test_plan_provision_gera_blocos_create_na_ordem_do_render` falhar na ordem dos tipos, confira a saída real do render (ordem `TIPO_ORDEM` = subinterface → prefix_list → route_policy_import → route_policy_export → bgp_peer) e ajuste `TIPOS_ESPERADOS` só se a regra de ordem do render for outra (nunca mude a ordem esperada por comodidade — ela é o contrato §5.1.4).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/changes.py tests/automation/test_changes.py
git commit -m "feat(automation): plano de mudança — provision por diff e remoção por encontrado (ciclo D T3)"
```

### Task 4: Serviço do fluxo — `domain/services/change_requests.py` + schemas

**Files:**
- Create: `src/gerenet/domain/services/change_requests.py`
- Modify: `src/gerenet/domain/schemas.py` (schemas `ChangeRequestCreate`, `ApprovalIn`, `ApprovalOut`, `ChangeStepOut`, `ChangeRequestOut` no fim do arquivo)
- Test: `tests/domain/test_change_requests.py`

**Interfaces:**
- Consumes: `changes.plan_provision/plan_remocao` + `PlanoDevice` (T3); `removal.blocos_remocao` (T2); `registrar` (domain/audit.py:47); `get_circuit` (services/circuits.py:47); `list_sessions` (bgp_sessions.py:191); `models` (T1, `ChangeStep.aviso` incluso); erros de `domain/services/errors`.
- Produces: `TRANSICOES: dict[str, set[str]]`; `create_change_request`, `get_change_request`, `list_change_requests`, `enviar_para_aprovacao`, `aprovar`, `cancelar`, `marcar_executando`, `reconciliar`, `gerar_rollback` (assinaturas abaixo, `actor` = nome p/ auditoria, `ator_id` = user id quando autenticado). Tasks 5, 7, 8 consomem.

- [ ] **Step 1: Escrever os testes (failing)**

`tests/domain/test_change_requests.py`:

```python
"""Máquina de estados + regras de aprovação do fluxo de mudança (spec §4/§7)."""
import pytest
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.services import change_requests as crsvc
from gerenet.domain.services.errors import ValidationError, ConflictError


def _usuario(db_session, username, role):
    from gerenet.domain.services.users import create_user
    return create_user(db_session, username=username, password="senha12345", role=role)


def _circuito_reservado(db_session):
    from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.ipam import reservar_circuito
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site

    site = create_site(db_session, SiteCreate(name="pop-t", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    dev = create_device(
        db_session, DeviceCreate(name="ne1", management_address="10.0.0.1", asn=65000), actor="cli"
    )
    org = create_organization(db_session, OrganizationCreate(name="cliente", asn=64500), actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="c1", organization_id=org.id, site_id=site.id,
            access_device_id=dev.id, access_port="GE0/0/1",
            edge_device_id=dev.id, stack="ipv4", vlan_mode="unica", edge_trunk="GE1/0/0",
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    return circ, dev


def _sessao(db_session, circ, dev):
    from gerenet.domain.schemas import BgpSessionCreate
    from gerenet.domain.services.bgp_sessions import create_session
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=dev.id, afi="ipv4",
            local_address="10.0.0.1", remote_address="10.0.0.2",
            asn_local=65000, asn_remote=64500,
        ),
        actor="cli",
    )


def _cria_cr(db_session, circ, *, acao="provision"):
    from gerenet.domain.schemas import ChangeRequestCreate
    sol = _usuario(db_session, "operador", "operador")
    cr = crsvc.create_change_request(
        db_session,
        ChangeRequestCreate(circuit_id=circ.id, acao=acao, motivo="Ativação.", criticidade="media"),
        ator_id=sol.id, actor="operador",
    )
    return cr, sol
```

```python
def test_criar_gera_steps_e_auditoria(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, sol = _cria_cr(db_session, circ)
    assert cr.status == "rascunho"
    assert len(cr.steps) == 1
    assert cr.steps[0].device_id == dev.id
    assert cr.steps[0].plano_json
    tipo = db_session.scalar(
        select(models.AuditEvent.type).where(models.AuditEvent.actor == "operador").order_by(models.AuditEvent.id.desc()).limit(1)
    )
    assert tipo == "change.created"


def test_transicao_invalida_levanta_validation(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    with pytest.raises(ValidationError, match="inválida"):
        crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    with pytest.raises(ValidationError, match="inválida"):
        crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")


def test_aprovacao_regras_papel_e_duplicidade(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, sol = _cria_cr(db_session, circ)
    # solicitante não pode aprovar (spec §3.3)
    with pytest.raises(ValidationError, match="solicitante"):
        crsvc.aprovar(db_session, cr.id, ator_id=sol.id, actor="operador", decisao="aprovar")
    crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    aprovador = _usuario(db_session, "aprovador", "aprovador")
    cr_ok = crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="aprovar")
    assert cr_ok.status == "aprovado"
    assert cr_ok.approvals[0].decisao == "aprovar"
    # duplicada ⇒ ValidationError (spec §4.3)
    with pytest.raises(ValidationError, match="já decidido"):
        crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="aprovar")


def test_rejeitar_termina_cr(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    aprovador = _usuario(db_session, "aprov2", "aprovador")
    cr_final = crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="rejeitar", comentario="janela")
    assert cr_final.status == "rejeitado"
    assert cr_final.approvals[0].decisao == "rejeitar"


def test_cancelar_de_rascunho_e_de_aprovado(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    crsvc.cancelar(db_session, cr.id, actor="operador")
    assert cr.status == "cancelado"


def test_reconciliar_de_parcial_recomputa_steps(db_session, monkeypatch):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    cr.steps[0].status = "falhou"
    cr.steps[0].erro = "VRP: % Error"
    cr.status = "parcial"
    db_session.commit()
    cr_final = crsvc.reconciliar(db_session, cr.id, actor="operador")
    assert cr_final.status == "aguardando_aprovacao"
    assert cr_final.steps[0].status == "pendente"
    assert cr_final.steps[0].erro is None


def test_rollback_gera_cr_filho_inverso(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    cr.status = "aplicado"
    cr.steps[0].status = "aplicado"  # gerar_rollback exige ≥1 step aplicado
    db_session.commit()
    filho = crsvc.gerar_rollback(db_session, cr.id, ator_id=_usuario(db_session, "exe", "executor").id, actor="executor")
    assert filho.acao == "remove"
    assert filho.rollback_de == cr.id
    assert filho.status == "aguardando_aprovacao"
    assert filho.motivo == f"Rollback do CR #{cr.id}"
    assert all(any(c["acao"] == "delete" for c in s.plano_json) for s in filho.steps)
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/domain/test_change_requests.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.domain.services.change_requests'` (e `ImportError` do schema em `_cria_cr`).

- [ ] **Step 3: Implementar o serviço**

`src/gerenet/domain/services/change_requests.py`:

```python
"""Fluxo de mudança controlada (spec §4/§7): estados, aprovação, rollback.

Regras (spec ciclo D): criar já planeja (nasce `rascunho` com steps + diff);
aprovação única com papel aprovador/admin e aprovador ≠ solicitante;
transições inválidas ⇒ ValidationError; rollback = novo CR inverso em
`aguardando_aprovacao` com `rollback_de`; reconciliação de `erro|parcial`
recomputa só os steps não aplicados.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import changes, removal
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.circuits import get_circuit
from gerenet.domain.services.errors import ConflictError, ValidationError

TRANSICOES: dict[str, set[str]] = {
    "rascunho": {"aguardando_aprovacao", "cancelado"},
    "aguardando_aprovacao": {"aprovado", "rejeitado", "cancelado"},
    "aprovado": {"executando", "cancelado"},
    "executando": {"aplicado", "com_divergencia", "parcial", "erro"},
    "erro": {"aguardando_aprovacao"},  # via reconciliar
    "parcial": {"aguardando_aprovacao"},
    "aplicado": set(),
    "com_divergencia": set(),
    "rejeitado": set(),
    "cancelado": set(),
}

_ATUAIS = ("aplicado", "com_divergencia", "parcial", "erro")


def _transita(cr: models.ChangeRequest, novo: str, *, ator: str, tipo: str) -> None:
    if novo not in TRANSICOES[cr.status]:
        raise ValidationError(f"Transição inválida: {cr.status} → {novo}.")
    antes = cr.status
    cr.status = novo
    registrar(
        None_placeholder  # não
    )
```

(Complete no Step 3 — o código segue literalmente no bloco abaixo; nada foi omitido: `_transita` registra `AuditEvent` com `tipo` e `antes/depois`.)

```python
def _transita(cr, novo, *, ator, tipo):
    if novo not in TRANSICOES[cr.status]:
        raise ValidationError(f"Transição inválida: {cr.status} → {novo}.")
    antes = cr.status
    cr.status = novo
    registrar(
        session_placeholder  # substituído no bloco final
    )
```

Não. O código completo de verdade, sem placeholders:

```python
def _transita(
    session: Session, cr: models.ChangeRequest, novo: str, *, ator: str, tipo: str,
) -> None:
    if novo not in TRANSICOES[cr.status]:
        raise ValidationError(f"Transição inválida: {cr.status} → {novo}.")
    antes = cr.status
    cr.status = novo
    registrar(
        session, tipo=tipo, ator=ator, objeto="change_request",
        objeto_id=cr.id, antes={"status": antes}, depois={"status": novo},
    )


def _cria_steps(session: Session, cr: models.ChangeRequest, plano: list[changes.PlanoDevice]) -> None:
    for item in plano:
        session.add(models.ChangeStep(
            change_request_id=cr.id, device_id=item.device_id, status="pendente",
            plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
            aviso=item.aviso,
        ))


def create_change_request(
    session: Session, data: models.ChangeRequestCreate, *, ator_id: int | None = None, actor: str = "cli",
) -> models.ChangeRequest:
    circ = get_circuit(session, data.circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe mudanças.")
    if data.acao == "provision":
        plano = changes.plan_provision(session, circ)
    else:
        plano = changes.plan_remocao(session, circ)  # ValidationError sem snapshot ok (§5.2)
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao=data.acao, criticidade=data.criticidade,
        motivo=data.motivo, ticket=data.ticket, solicitante_id=ator_id,
        status="rascunho",
    )
    session.add(cr)
    session.flush()
    _cria_steps(session, cr, plano)
    registrar(
        session, tipo="change.created", ator=actor, objeto="change_request",
        objeto_id=cr.id, antes=None,
        depois={"circuit_id": circ.id, "acao": cr.acao, "criticidade": cr.criticidade,
                "steps": len(cr.steps), "blocos": sum(len(s.plano_json) for s in cr.steps)},
    )
    session.commit()
    session.refresh(cr)
    return cr


def get_change_request(session: Session, cr_id: int) -> models.ChangeRequest:
    cr = session.get(models.ChangeRequest, cr_id)
    if cr is None:
        from gerenet.domain.services.errors import NotFoundError
        raise NotFoundError(f"Change request {cr_id} não encontrada.")
    return cr


def list_change_requests(
    session: Session, *, status: str | None = None,
    solicitante_id: int | None = None, circuit_id: int | None = None,
) -> list[models.ChangeRequest]:
    stmt = select(models.ChangeRequest).order_by(models.ChangeRequest.id.desc())
    if status is not None:
        stmt = stmt.where(models.ChangeRequest.status == status)
    if solicitante_id is not None:
        stmt = stmt.where(models.ChangeRequest.solicitante_id == solicitante_id)
    if circuit_id is not None:
        stmt = stmt.where(models.ChangeRequest.circuit_id == circuit_id)
    return list(session.scalars(stmt))


def enviar_para_aprovacao(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    _transita(session, cr, "aguardando_aprovacao", ator=actor, tipo="change.sent_for_approval")
    session.commit()
    return cr


def aprovar(
    session: Session, cr_id: int, *, ator_id: int | None = None, actor: str,
    decisao: str, comentario: str | None = None,
) -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    if cr.approvals:
        raise ValidationError("Change request já decidida — aprovação é única (spec §4.3).")
    if ator_id is not None and cr.solicitante_id is not None and cr.solicitante_id == ator_id:
        raise ValidationError("Aprovador não pode ser o próprio solicitante (spec §3.3).")
    _transita(session, cr, "aprovado" if decisao == "aprovar" else "rejeitado",
              ator=actor, tipo="change.approved" if decisao == "aprovar" else "change.rejected")
    session.add(models.Approval(
        change_request_id=cr.id, user_id=ator_id, decisao=decisao, comentario=comentario,
    ))
    session.commit()
    session.refresh(cr)
    return cr


def cancelar(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    _transita(session, cr, "cancelado", ator=actor, tipo="change.cancelled")
    session.commit()
    return cr


def marcar_executando(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    """Transição aprovado → executando; idempotente quando já executando.

    O WORKER é o transitor autoritativo (T7): re-chamadas do endpoint ao
    enfileirar de novo não devem falhar com transição inválida — o enqueue
    já validou aprovado e segurou o lock de CR.
    """
    cr = get_change_request(session, cr_id)
    if cr.status == "executando":
        return cr
    _transita(session, cr, "executando", ator=actor, tipo="change.executing")
    session.commit()
    return cr


def _replaneja(session: Session, cr: models.ChangeRequest, device_id: int) -> changes.PlanoDevice:
    circ = get_circuit(session, cr.circuit_id)
    if cr.acao == "provision":
        plano = changes.plan_provision(session, circ)
    else:
        plano = changes.plan_remocao(session, circ)
    for item in plano:
        if item.device_id == device_id:
            return item
    return changes.PlanoDevice(device_id=device_id, blocos=[], baseline_snapshot_id=None)


def reconciliar(session: Session, cr_id: int, *, actor: str = "cli") -> models.ChangeRequest:
    cr = get_change_request(session, cr_id)
    if cr.status not in ("erro", "parcial"):
        raise ValidationError(f"Reconciliar só de erro|parcial (atual: {cr.status}).")
    pendentes = [s for s in cr.steps if s.status in ("pendente", "falhou")]
    if not pendentes:
        raise ValidationError("Nenhum step não aplicado a recomputar.")
    for step in pendentes:
        item = _replaneja(session, cr, step.device_id)
        step.plano_json = item.blocos
        step.baseline_snapshot_id = item.baseline_snapshot_id
        step.aviso = item.aviso
        step.status = "pendente"
        step.erro = None
    _transita(session, cr, "aguardando_aprovacao", ator=actor, tipo="change.reconciled")
    session.commit()
    session.refresh(cr)
    return cr


def gerar_rollback(
    session: Session, cr_id: int, *, ator_id: int | None = None, actor: str = "cli",
) -> models.ChangeRequest:
    """Novo CR inverso em aguardando_aprovacao (§7), com rollback_de.

    provision → remove com plano derivado do BASELINE de cada step aplicado
    (o que a mudança adicionou, visto do snapshot pré-mudança);
    remove → provision re-renderizado do desejado (SoT atual).
    """
    cr = get_change_request(session, cr_id)
    if cr.status not in ("aplicado", "com_divergencia", "parcial") or not any(
        s.status == "aplicado" for s in cr.steps
    ):
        raise ValidationError("Rollback só de aplicado/com_divergencia/parcial com steps aplicados.")
    circ = get_circuit(session, cr.circuit_id)
    filho = models.ChangeRequest(
        circuit_id=cr.circuit_id, acao="remove" if cr.acao == "provision" else "provision",
        criticidade=cr.criticidade, motivo=f"Rollback do CR #{cr.id}",
        solicitante_id=ator_id, status="aguardando_aprovacao", rollback_de=cr.id,
    )
    session.add(filho)
    session.flush()
    for step in cr.steps:
        if step.status != "aplicado":
            continue
        if cr.acao == "provision":
            if step.baseline_snapshot_id is None:
                continue  # sem baseline: sem evidência do encontrado — não inventa (§5.2)
            snap = session.get(models.DeviceSnapshot, step.baseline_snapshot_id)
            if snap is None:
                continue
            blocos = removal.blocos_remocao(session, circ, step.device_id, snapshot=snap)
            session.add(models.ChangeStep(
                change_request_id=filho.id, device_id=step.device_id, status="pendente",
                plano_json=blocos, baseline_snapshot_id=snap.id,
            ))
        else:
            item = _replaneja(session, cr, step.device_id)
            session.add(models.ChangeStep(
                change_request_id=filho.id, device_id=step.device_id, status="pendente",
                plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
                aviso=item.aviso,
            ))
    registrar(
        session, tipo="change.rollback_created", ator=actor, objeto="change_request",
        objeto_id=cr.id, depois={"filho": filho.id, "acao": filho.acao},
    )
    session.commit()
    session.refresh(filho)
    return filho
```

Schemas (no fim de `src/gerenet/domain/schemas.py`):

```python
class ChangeRequestCreate(BaseModel):
    circuit_id: int
    acao: Literal["provision", "remove"] = "provision"
    criticidade: Literal["baixa", "media", "alta"] = "media"
    motivo: str = Field(min_length=1, max_length=2000)
    ticket: str | None = Field(default=None, max_length=64)


class ApprovalIn(BaseModel):
    decisao: Literal["aprovar", "rejeitar"]
    comentario: str | None = Field(default=None, max_length=1000)


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    decisao: str
    comentario: str | None
    created_at: datetime


class ChangeStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    status: str
    plano_json: list
    aviso: str | None
    baseline_snapshot_id: int | None
    backup_snapshot_id: int | None
    post_check_json: dict | None
    erro: str | None
    finished_at: datetime | None


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    circuit_id: int
    acao: str
    criticidade: str
    motivo: str
    ticket: str | None
    solicitante_id: int | None
    status: str
    rollback_de: int | None
    created_at: datetime
    steps: list[ChangeStepOut] = []
    approvals: list[ApprovalOut] = []
```

- [ ] **Step 4: Rodar e verificar verde**

Run: `uv run pytest tests/domain/test_change_requests.py -v`
Expected: PASS (7 testes). Se `test_reconciliar...` falhar no `erro` persistido, chame `db_session.refresh(cr)` antes do `crsvc.reconciliar` no teste (o `status="parcial"` setado direto não dispara máquina de estados — é setup de teste, ok).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/domain/services/change_requests.py src/gerenet/domain/schemas.py tests/domain/test_change_requests.py
git commit -m "feat(domain): serviço de change requests — estados, aprovação, rollback (ciclo D T4)"
```

### Task 5: API — router `/api/v1/change-requests` + `require_papel`

**Files:**
- Create: `src/gerenet/api/routers/change_requests.py`
- Modify: `src/gerenet/api/deps.py` (adicionar `require_papel` ao fim)
- Modify: `src/gerenet/api/main.py:36-53` (registrar router)
- Test: `tests/api/test_change_requests_api.py`

**Interfaces:**
- Consumes: `change_requests.create_change_request/get/list/enviar_para_aprovacao/aprovar/cancelar/marcar_executando/reconciliar/gerar_rollback` (T4); schemas `ChangeRequestCreate/Out`, `ApprovalIn` (T4); `require_actor`, `Actor`, `SessionDep` (api/deps.py:15-46); erros → HTTPException (padrão circuits.py:63-74).
- Produces: `require_papel(*papeis: str) -> Callable` (dependência FastAPI); endpoints `POST /, GET /, GET /{id}, POST /{id}/enviar|approve|cancelar|executar|rollback|reconciliar` — consumidos pela web (T9) e e2e (T11).

- [ ] **Step 1: Escrever os testes (failing)**

`tests/api/test_change_requests_api.py`:

```python
"""API do fluxo de mudança (spec §8): contratos, papéis e transições."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services import users as usvc
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _cria_cenario(db_session: Session) -> int:
    """Circuito reservado com sessão BGP v4 — retorna circuit_id."""
    site = create_site(db_session, SiteCreate(name="pop-cr-api", p2p_ipv4_block="10.60.0.0/24"), actor="cli")
    ne = create_device(db_session, DeviceCreate(name="ne-cr-api", management_address="10.60.0.1", asn=65000), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-cr-api", asn=64500), actor="cli")
    circ = create_circuit(
        db_session,
        {"code": "CR-API-1", "organization_id": org.id, "site_id": site.id,
         "access_device_id": ne.id, "access_port": "GE0/0/1",
         "edge_device_id": ne.id, "edge_trunk": "GE1/0/0"},
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(
        db_session,
        {"circuit_id": circ.id, "device_id": ne.id, "afi": "ipv4",
         "local_address": "10.0.0.1", "remote_address": "10.0.0.2",
         "asn_local": 65000, "asn_remote": 64500},
        actor="cli",
    )
    # Snapshot com recursos (encontrado real, sem nada deste circuito): o plano
    # da ativação sai cheio, baseline congelado e aviso None (T3: tem_recursos).
    db_session.add(models.DeviceSnapshot(
        device_id=ne.id, status="success",
        resources={"version": {"version": "8.210", "uptime": "10 days"},
                   "interfaces": [], "bgp_peers": []},
    ))
    db_session.commit()
    return circ.id
```

(Os dicts acima são aceitos — `create_session`/`create_circuit` são Pydantic 2, e dicts passam direto. Se `create_circuit` reclamar do dict, use as classes `CircuitCreate`/`BgpSessionCreate` importadas como no T4.)

```python
def _usuario(db_session: Session, username: str, role: str) -> None:
    usvc.create_user(db_session, username=username, password="senha-super-8", role=role, actor="cli")
    db_session.commit()


def _login(client: TestClient, username: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": "senha-super-8"})
    assert resp.status_code == 200, resp.text


def _cria_cr(client: TestClient, circuit_id: int) -> dict:
    resp = client.post(
        "/api/v1/change-requests",
        json={"circuit_id": circuit_id, "acao": "provision", "motivo": "Ativação.", "criticidade": "media"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
```

```python
def test_criar_listar_detalhar_404(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    assert cr["status"] == "rascunho"
    assert len(cr["steps"]) == 1
    assert cr["steps"][0]["plano_json"]
    assert cr["approvals"] == []
    assert cr["steps"][0]["aviso"] is None
    assert "password" not in str(cr)  # nada de segredo no payload (spreadcheck)

    lista = client.get("/api/v1/change-requests", headers=_auth())
    assert lista.status_code == 200
    assert [c["id"] for c in lista.json()] == [cr["id"]]
    assert client.get(f"/api/v1/change-requests?status=aprovado", headers=_auth()).json() == []
    assert client.get("/api/v1/change-requests/9999", headers=_auth()).status_code == 404


def test_fluxo_enviar_transicao_invalida_cancelar(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    env = client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth())
    assert env.status_code == 200
    assert env.json()["status"] == "aguardando_aprovacao"
    # repetido → 400 (transição inválida)
    assert client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth()).status_code == 400
    # cancelamento de aguardando_aprovacao
    can = client.post(f"/api/v1/change-requests/{cr['id']}/cancelar", headers=_auth())
    assert can.json()["status"] == "cancelado"


def test_approve_somente_papel_e_uma_vez(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    _usuario(db_session, "aprovador-api", "aprovador")
    _usuario(db_session, "operador-api", "operador")
    client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth())

    # chave de API não é pessoa → 403
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}, headers=_auth()
    ).status_code == 403
    # operador não aprova → 403
    _login(client, "operador-api")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 403
    # aprovador aprova
    client.post("/api/v1/auth/logout")
    _login(client, "aprovador-api")
    ok = client.post(
        f"/api/v1/change-requests/{cr['id']}/approve",
        json={"decisao": "aprovar", "comentario": "janela ok"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "aprovado"
    assert ok.json()["approvals"][0]["comentario"] == "janela ok"
    # duplicada → 400
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 400


def test_executar_marca_executando(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    _usuario(db_session, "aprovador-ex", "aprovador")
    _usuario(db_session, "executor-ex", "executor")
    client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth())
    _login(client, "aprovador-ex")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 200
    client.post("/api/v1/auth/logout")
    # executor não aprova, mas executa
    _login(client, "executor-ex")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 403
    exec = client.post(f"/api/v1/change-requests/{cr['id']}/executar")
    assert exec.status_code == 200
    assert exec.json()["status"] == "executando"


def test_rollback_gera_cr_filho_inverso(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    modelo = db_session.get(models.ChangeRequest, cr["id"])
    modelo.status = "aplicado"
    modelo.steps[0].status = "aplicado"  # gerar_rollback exige ≥1 step aplicado
    db_session.commit()
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/rollback", headers=_auth())
    assert resp.status_code == 200
    filho = resp.json()
    assert filho["acao"] == "remove"
    assert filho["rollback_de"] == cr["id"]
    assert filho["status"] == "aguardando_aprovacao"
    # Baseline congelado ⇒ filho NASCE com steps; blocos vêm do encontrado do
    # baseline (aqui não tem nada deste circuito: evidência honesta, §5.2).
    assert len(filho["steps"]) == 1
    assert filho["steps"][0]["plano_json"] == []
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/api/test_change_requests_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.api.routers.change_requests'` (e rota 404 nos primeiros testes).

- [ ] **Step 3: Adicionar `require_papel` em `api/deps.py`**

Acrescentar ao fim de `src/gerenet/api/deps.py`:

```python
def require_papel(*papeis: str):
    """Fábrica de dependência: exige usuário de SESSÃO com um dos papéis.

    Diferente de require_actor, chave de API não passa (o nome 'api' não tem
    papel) — aprovação/execução exigem pessoa (spec §3.3/§8).
    """

    def _checa_papel(actor: Annotated[Actor, Depends(require_actor)]) -> Actor:
        if actor.usuario is None or actor.usuario.role not in papeis:
            raise HTTPException(status_code=403, detail=f"Perfil sem permissão: {', '.join(papeis)}.")
        return actor

    return _checa_papel
```

- [ ] **Step 4: Criar o router**

`src/gerenet/api/routers/change_requests.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from gerenet.api.deps import Actor, SessionDep, require_actor, require_papel
from gerenet.domain.schemas import ApprovalIn, ChangeRequestCreate, ChangeRequestOut
from gerenet.domain.services import change_requests as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/change-requests",
    tags=["change-requests"],
    dependencies=[Depends(require_actor)],
)

ApproverDep = Annotated[Actor, Depends(require_papel("aprovador", "administrador"))]
ExecutorDep = Annotated[Actor, Depends(require_papel("executor", "administrador"))]


@router.post("", response_model=ChangeRequestOut, status_code=201)
def criar(data: ChangeRequestCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        return svc.create_change_request(
            session, data,
            ator_id=actor.usuario.id if actor.usuario is not None else None,
            actor=actor.nome,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[ChangeRequestOut])
def listar(
    session: SessionDep,
    status: str | None = None,
    solicitante_id: int | None = None,
    circuit_id: int | None = None,
) -> list:
    return svc.list_change_requests(
        session, status=status, solicitante_id=solicitante_id, circuit_id=circuit_id
    )


@router.get("/{cr_id}", response_model=ChangeRequestOut)
def detalhar(cr_id: int, session: SessionDep) -> object:
    try:
        return svc.get_change_request(session, cr_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{cr_id}/enviar", response_model=ChangeRequestOut)
def enviar(cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        return svc.enviar_para_aprovacao(session, cr_id, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/approve", response_model=ChangeRequestOut)
def aprovar(
    cr_id: int, data: ApprovalIn, session: SessionDep, approver: ApproverDep,
) -> object:
    """Papel aprovador/admin; aprovador ≠ solicitante (spec §3.3)."""
    try:
        return svc.aprovar(
            session, cr_id,
            ator_id=approver.usuario.id, actor=approver.nome,
            decisao=data.decisao, comentario=data.comentario,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/cancelar", response_model=ChangeRequestOut)
def cancelar(cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        return svc.cancelar(session, cr_id, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/executar", response_model=ChangeRequestOut)
def executar(cr_id: int, session: SessionDep, executor: ExecutorDep) -> object:
    """Papel executor/admin. T7 pluga aqui o enqueue (fila gerenet-change)."""
    try:
        return svc.marcar_executando(session, cr_id, actor=executor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/rollback", response_model=ChangeRequestOut)
def rollback(cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        filho = svc.gerar_rollback(
            session, cr_id,
            ator_id=actor.usuario.id if actor.usuario is not None else None,
            actor=actor.nome,
        )
        return filho
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{cr_id}/reconciliar", response_model=ChangeRequestOut)
def reconciliar(cr_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        return svc.reconciliar(session, cr_id, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Registrar em `src/gerenet/api/main.py`:

```python
from gerenet.api.routers import (
    audit_events,
    bgp_sessions,
    change_requests,   # <— adicionar (ordem alfabética)
    circuits,
    ...
)
...
app.include_router(change_requests.router)  # após circuits.router
```

- [ ] **Step 5: Rodar e verificar verde**

Run: `uv run pytest tests/api/test_change_requests_api.py -v`
Expected: PASS (5 testes). Possíveis ajustes pontuais:
- Se `create_session`/`create_circuit` recusarem dict, troque pelos objetos das classes Pydantic (`CircuitCreate(...)`, `BgpSessionCreate(...)`) — mesmo efeito.
- `test_rollback_gera_cr_filho_inverso` foi corrigido na escrita do plano: o baseline agora existe (snapshot adicionado ao `_cria_cenario`) e o assert espera `plano_json == []` — o encontrado do baseline não tem nada deste circuito, e o rollback não inventa comandos (§5.2). Se o step do pai não tiver `baseline_snapshot_id` (plano recalculado sem snapshot), o filho nasce sem steps: nesse caso o assert de `len(filho["steps"]) == 1` falha de verdade e indica que o refresh do modelo não viu o snapshot — adicione `db_session.refresh` antes do commit.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/api/deps.py src/gerenet/api/routers/change_requests.py src/gerenet/api/main.py tests/api/test_change_requests_api.py
git commit -m "feat(api): router /api/v1/change-requests + require_papel (ciclo D T5)"
```

### Task 6: Execução no runner — `connect_and_apply` (denylist) + `run_change`

**Files:**
- Modify: `src/gerenet/automation/netmiko_conn.py` (extração `_abre_conexao`, `ConfigNotAllowed`, `connect_and_apply`)
- Modify: `src/gerenet/automation/runner.py` (`ERROS_VRP`, extração `_coleta_recursos`/`_grava_snapshot`, `run_change`)
- Modify: `tests/automation/test_netmiko_conn.py` (novos testes de denylist/apply)
- Create: `tests/automation/test_runner_change.py`

**Interfaces:**
- Consumes: `connect_and_run` (netmiko_conn.py:43, intacto); `_conectar_e_executar` (runner.py:19); `COLLECTORS`/`comandos_verbose` (collectors.py); `changes.plan_provision/plan_remocao` + `PlanoDevice` (T3); `removal.blocos_remocao`/`texto_backup` (T2); `reconciliador_device`? Não: `reconciliar_device(session, device_id, *, snapshot_id=None) -> ReconcileResult{items: [{tipo, severidade, esperado, encontrado, acao}]}` (reconcile.py:73); `get_circuit` (circuits.py); `get_device` (devices.py); `registrar` (audit.py:47); `mascarar` (audit.py:21); `models.ChangeRequest/ChangeStep/JobRun/DeviceSnapshot/AuditEvent` (T1).
- Produces: `connect_and_apply(device, username, password, commands, settings) -> {"config": str}` (levanta `ConfigNotAllowed`/`HostKeyMismatch`/`ConnectionFailed`); `ERROS_VRP` (regex); `run_change(change_request_id, *, actor="worker", origin="rq", settings=None, session_override=None) -> dict` (contrato `{"status", "error"}` como `run_collection`). Tasks 7 (change_task) e 8 (CLI execute) consomem `run_change`.

**Nota de decisão (plano, vale para o execução do executor):** o JobRun não tem coluna de meta; a trilha CR/step vai nos `details` dos eventos de auditoria `change.step_*` (`change_request_id`/`change_step_id`/`device_id`), e `JobRun.kind="change"` + `device_id` identificam o JobRun do step.

- [ ] **Step 1: Escrever testes de `connect_and_apply` (failing)**

Acrescentar a `tests/automation/test_netmiko_conn.py` (mesmos `_fingerprint_de`/`_conexao_fake` já definidos):

```python
from gerenet.automation.netmiko_conn import ConfigNotAllowed, connect_and_apply


def test_apply_recusa_save_e_multilinha_antes_de_conectar(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = MagicMock(return_value=_conexao_fake())
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", handler)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(ConfigNotAllowed):
        connect_and_apply(dev, "u", "p", ["save"], SETTINGS)
    with pytest.raises(ConfigNotAllowed):
        connect_and_apply(dev, "u", "p", ["peer 10.0.0.2 enable\nreboot"], SETTINGS)
    handler.assert_not_called()


def test_apply_aceita_comandos_do_plano(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _conexao_fake()
    conn.send_config_set.return_value = "config aplicado"
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", lambda **kwargs: conn)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    saida = connect_and_apply(
        dev, "u", "p",
        ["bgp 65000", "peer 10.0.0.2 as-number 64500", "peer 10.0.0.2 shutdown"],
        SETTINGS,
    )
    assert saida == {"config": "config aplicado"}
    conn.send_config_set.assert_called_once_with(
        ["bgp 65000", "peer 10.0.0.2 as-number 64500", "peer 10.0.0.2 shutdown"],
        read_timeout=SETTINGS.read_timeout,
    )


def test_apply_falha_de_conexao_vira_connection_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: (_ for _ in ()).throw(OSError("ssh para baixo")),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(ConnectionFailed):
        connect_and_apply(dev, "u", "p", ["bgp 65000"], SETTINGS)
```

Run: `uv run pytest tests/automation/test_netmiko_conn.py -v`
Expected: FAIL — ImportError de `ConfigNotAllowed` (e o `pending`/`fail` nos novos testes; os antigos seguem passando).

- [ ] **Step 2: Implementar `connect_and_apply` + extração `_abre_conexao`**

Em `src/gerenet/automation/netmiko_conn.py` — substituir `connect_and_run` por a extração compartilhada + manter as funções existentes (a semântica não muda):

```python
# Denylist de aplicação: o plano vem do render próprio, mas um comando que
# escapa do stream de config (system-view/return/quit) ou persiste/destrói
# (save/reset/reboot/clear/delete) nunca deve ser enviado — defesa em
# profundidade (§12.3/§19). `shutdown` NÃO está aqui: o render emite
# `peer <ip> shutdown` (bgp_peer.j2:19) para sessões com shutdown=True.
_BLOCKED_CONFIG = re.compile(
    r"^(?:system-view|return|quit|save|reset|reboot|clear|delete)\b",
    re.IGNORECASE,
)


class ConfigNotAllowed(Exception):
    """Comando fora da denylist de aplicação de configuração."""


def _comando_config_proibido(cmd: str) -> bool:
    if "\n" in cmd or "\r" in cmd:
        return True
    return _BLOCKED_CONFIG.match(cmd.lstrip()) is not None


def _abre_conexao(device, username: str, password: str, settings):
    """ConnectHandler + validação de host key; levanta HostKeyMismatch/ConnectionFailed."""
    if not device.host_key_fingerprint:
        raise HostKeyMismatch(
            device.name,
            "nenhum fingerprint registrado — use `gerenet hostkey register` antes de coletar",
        )
    try:
        conn = ConnectHandler(
            device_type="huawei_vrp",
            host=device.management_address,
            port=device.ssh_port or 22,
            username=username,
            password=password,
            conn_timeout=settings.connect_timeout,
        )
    except Exception as exc:
        raise ConnectionFailed(f"Não foi possível conectar em {device.name}: {exc}") from exc
    try:
        actual = _fingerprint_do_servidor(conn)
        if actual is None:
            raise HostKeyMismatch(
                device.name,
                "indisponível — verifique a conectividade SSH e tente novamente",
            )
        if normalize_fingerprint(actual) != normalize_fingerprint(device.host_key_fingerprint):
            raise HostKeyMismatch(device.name, normalize_fingerprint(actual))
        return conn
    except Exception:
        try:
            conn.disconnect()
        except Exception:  # noqa: BLE001, S110 — disconnect best-effort
            pass
        raise
```

Depois, `connect_and_run` vira:

```python
def connect_and_run(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    """Conecta via Netmiko (huawei_vrp), valida host key e allowlist, executa comandos read-only."""
    for cmd in commands:
        if "\n" in cmd or "\r" in cmd or _ALLOWED_COMMAND.fullmatch(cmd) is None:
            raise CommandNotAllowed(f"Comando fora da allowlist read-only: {cmd!r}")
    conn = _abre_conexao(device, username, password, settings)
    try:
        saidas: dict[str, str] = {}
        for cmd in commands:
            saidas[cmd] = conn.send_command(cmd, read_timeout=settings.read_timeout)
        return saidas
    except Exception as exc:
        raise ConnectionFailed(f"Falha ao executar comandos em {device.name}: {exc}") from exc
    finally:
        try:
            conn.disconnect()
        except Exception:  # noqa: BLE001, S110 — disconnect best-effort no finally
            pass


def connect_and_apply(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    """Conecta, valida host key/denylist e aplica comandos via send_config_set (write path).

    Uma conexão por bloco (spec §6.4); a detecção de erros do VRP é feita pela
    saída (runner.ERROS_VRP) sobre o texto devolvido aqui.
    """
    for cmd in commands:
        if _comando_config_proibido(cmd):
            raise ConfigNotAllowed(f"Comando fora da denylist de aplicação: {cmd!r}")
    conn = _abre_conexao(device, username, password, settings)
    try:
        saida = conn.send_config_set(commands, read_timeout=settings.read_timeout)
        return {"config": saida}
    except Exception as exc:
        raise ConnectionFailed(f"Falha ao aplicar comandos em {device.name}: {exc}") from exc
    finally:
        try:
            conn.disconnect()
        except Exception:  # noqa: BLE001, S110 — disconnect best-effort no finally
            pass
```

- [ ] **Step 3: Rodar e verificar verde (netmiko)**

Run: `uv run pytest tests/automation/test_netmiko_conn.py -v`
Expected: PASS (os 8 antigos + 3 novos).

- [ ] **Step 4: Escrever testes de `run_change` (failing)**

`tests/automation/test_runner_change.py` — fakes no padrão de test_runner.py (VaultFake, monkeypatch em `gerenet.automation.runner.*`), Redis real para o teste de lock (padrão `test_lock_alheio_nao_e_liberado`):

```python
"""run_change (spec §6/§5.3): execução de CR aprovada com fake de coleta/aplicação."""
from pathlib import Path

import pytest
from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation import render
from gerenet.automation.runner import run_change
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


class VaultFake:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _ambiente(db_session: Session) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-cr", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cr", management_address="10.0.0.1", asn=65000), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-cr", asn=64500), actor="cli")
    from gerenet.automation.removal import _tem_peer  # noqa: F401 — usado nos helpers? (descomente se usar)

    return {"site": site, "dev": dev, "org": org}


def _circuito(db_session: Session, amb: dict):
    circ = create_circuit(
        db_session,
        {
            "code": "CR-RUN-1", "organization_id": amb["org"].id, "site_id": amb["site"].id,
            "access_device_id": amb["dev"].id, "access_port": "GE0/0/1",
            "edge_device_id": amb["dev"].id, "stack": "ipv4", "vlan_mode": "unica",
            "edge_trunk": "GE1/0/0", "p2p_v4_len": 31,
        },
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    from gerenet.domain.schemas import BgpSessionCreate
    create_session(
        db_session,
        {
            "circuit_id": circ.id, "device_id": amb["dev"].id, "afi": "ipv4",
            "local_address": "100.64.1.1", "remote_address": "100.64.1.2",
            "asn_local": 65000, "asn_remote": 64500,
        },
        actor="cli",
    )
    db_session.commit()
    return circ
```

(Os dicts passam em Pydantic 2 — como no T5. Se algum serviço reclamar, use as classes.)

```python
def _cr_aprovada(db_session: Session, circ, dev) -> models.ChangeRequest:
    """CR aprovada direto (setup de teste: o plano real vem do render do circuito)."""
    from gerenet.automation.changes import plan_provision

    plano = plan_provision(db_session, circ)
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao="provision", criticidade="media",
        motivo="Ativação.", status="aprovado",
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


def _recursos_vazios(db_session: Session, dev) -> dict:
    """Encontrado sem nada do circuito — re-diff não vê skip, aplica tudo."""
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [], "bgp_peers": [],
    }


def _recursos_aplicados(db_session: Session, dev) -> dict:
    """Encontrado = desejado (render aplicado) — reconciliador pós-mudança sem critica."""
    r = render.render_desejado(db_session, dev.id)
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [
            {"nome": b.comandos[0].split(None, 1)[1]} for b in r.blocos if b.tipo == "subinterface"
        ],
        "bgp_peers": [
            {"afi": "ipv4", "peer": b.comandos[1].split()[1], "asn": 64500}
            for b in r.blocos if b.tipo == "bgp_peer"
        ],
    }


def _fakes_de_mudanca(monkeypatch: pytest.MonkeyPatch, db_session: Session, dev, colas: list[dict]):
    """Orquestra as fakes: cola retorna uma coleção por chamada (pré → pós)."""
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    chamadas_coleta: list[int] = []

    def _coleta(session, device, cred, settings, base):
        chamadas_coleta.append(1)
        recursos = colas.pop(0) if colas else _recursos_vazios(db_session, dev)
        return recursos, {}, {}

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_aplicar",
        lambda device, username, password, commands, settings: {"config": ("\n".join(commands) + "\n")},
    )
    return chamadas_coleta
```

(Nota: a fake `_coleta` devolve `raw_files={}` — `_grava_snapshot` monta os arquivos vazios; o teste não lê arquivos de mudança. O `base` é usado pelo `pathlib` só dentro de `_coleta_recursos` real.)

```python
def test_run_change_fluxo_ok_cr_aplicada(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    colas = [_recursos_vazios(db_session, amb["dev"]), _recursos_aplicados(db_session, amb["dev"])]
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"

    db_session.refresh(cr)
    assert cr.status == "aplicado"
    step = cr.steps[0]
    assert step.status == "aplicado"
    assert step.backup_snapshot_id is not None
    assert step.post_check_json and "items" in step.post_check_json
    assert step.erro is None
    jobs = db_session.query(models.JobRun).filter_by(kind="change", device_id=amb["dev"].id).all()
    assert len(jobs) == 1
    assert jobs[0].status == "success"
    eventos = db_session.query(models.AuditEvent).filter_by(type="change.applied").all()
    assert len(eventos) == 1


def test_run_change_erro_vrp_no_meio_marca_cr_erro(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._coleta_recursos",
        lambda session, device, cred, settings, base: (_recursos_vazios(db_session, amb["dev"]), {}, {}),
    )

    def _falha(device, username, password, commands, settings):
        # primeiro bloco ok (bgp 65000? não: a ordem do render é subinterface → …:
        # falha no SEGUNDO bloco aplicado; o primeiro já entrou)
        return {"config": f"{commands[0]}\n% Error: Incomplete command found"}

    monkeypatch.setattr("gerenet.automation.runner._conectar_e_aplicar", _falha)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.status == "erro"
    assert cr.steps[0].status == "falhou"
    assert "Error" in (cr.steps[0].erro or "")
    job = db_session.query(models.JobRun).filter_by(kind="change").first()
    assert job.status == "error"
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_failed").count() == 1


def test_run_change_bloco_ja_presente_marca_step_pulado(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [_recursos_aplicados(db_session, amb["dev"])])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert cr.steps[0].status == "pulado"
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_skipped").count() == 1


def test_run_change_estado_divergente_aborta(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Subinterface existe com endereço diferente do plano congelado ⇒ aborta (§5.3)."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    recursos_divergentes = {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [{"nome": "GigabitEthernet1/0/0.100"}],  # presente, mas com outro endereço
        "bgp_peers": [],
    }
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [recursos_divergentes])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    assert "divergente" in (cr.steps[0].erro or "")
    # conexão de aplicação nunca aconteceu
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_failed").count() == 1


def test_run_change_post_check_critica_vira_com_divergencia(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    recursos_que_nao_incluem_peer = {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [{"nome": "GigabitEthernet1/0/0.100"}],
        "bgp_peers": [],
    }
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [recursos_que_nao_incluem_peer, recursos_que_nao_incluem_peer])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "com_divergencia"
    db_session.refresh(cr)
    assert cr.status == "com_divergencia"
    assert cr.steps[0].status == "aplicado"
    assert any(i["severidade"] == "critica" for i in cr.steps[0].post_check_json["items"])
    assert db_session.query(models.AuditEvent).filter_by(type="change.com_divergencia").count() == 1


def test_run_change_lock_por_device_impede_etapa(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    # sem fake de coleta: deve falhar ANTES, no lock.
    redis = Redis.from_url(Settings(_env_file=None, backups_dir=tmp_path).redis_url)
    chave = f"gerenet:lock:device:{amb['dev'].id}"
    redis.set(chave, "outro", nx=True, ex=300)
    try:
        resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
        assert resultado["status"] == "erro"
        db_session.refresh(cr)
        assert cr.status == "erro"
        assert "lock" in (cr.steps[0].erro or "")
    finally:
        redis.delete(chave)
        redis.close()
```

- [ ] **Step 5: Rodar e verificar falha**

Run: `uv run pytest tests/automation/test_runner_change.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_change'`.

- [ ] **Step 6: Implementar no runner**

Em `src/gerenet/automation/runner.py` (substituir o bloco do laço da coleta pela extração; manter `run_collection` com o mesmo contrato — teste a suíte antiga no fim):

```python
from gerenet.automation.changes import PlanoDevice, plan_provision, plan_remocao  # ou imports locais
from gerenet.automation.netmiko_conn import connect_and_apply
from gerenet.automation.reconcile import reconciliar_device
```

(Importe `changes`/`reconcile` no topo do módulo junto aos existentes; `connect_and_apply` entra no mesmo import de `netmiko_conn`.)

```python
# Erros de configuração do VRP (spec §6.4) — 1ª linha da saída do send_config_set
# costuma ser o comando ecoado; "^" é a marca de posição em linha própria.
ERROS_VRP = re.compile(r"% Error:|\^$|Incomplete command|Ambiguous command|Unrecognized command", re.MULTILINE)


def _coleta_recursos(session: Session, dev, cred: dict, settings, base: Path) -> tuple[dict, dict, dict]:
    """Roda os COLLECTORS do device (comandos por sessão quando aplicável).

    Devolve (recursos, erros, arquivos_brutos) — compartilhado entre a coleta
    (run_collection) e o backup/re-coleta do fluxo de mudança (run_change).
    """
    recursos: dict[str, object] = {}
    erros: dict[str, str] = {}
    arquivos_brutos: dict[str, list[str]] = {}
    for nome, spec in COLLECTORS.items():
        try:
            if spec.get("alvo_sessoes"):
                comandos = comandos_verbose(spec, dev.id, session)
                if not comandos:
                    continue
            else:
                comandos = spec["commands"]
            saidas = _conectar_e_executar(dev, cred["username"], cred["password"], comandos, settings)
            lista_arquivos: list[str] = []
            for comando, saida in saidas.items():
                caminho = base / nome / f"{_nome_do_arquivo(comando)}.txt"
                caminho.parent.mkdir(parents=True, exist_ok=True)
                caminho.write_text(saida, encoding="utf-8")
                lista_arquivos.append(str(caminho))
            arquivos_brutos[nome] = lista_arquivos
            if spec.get("parser"):
                linhas = parse_template(spec["parser"], saidas[spec["commands"][0]])
                recursos[nome] = linhas[0] if linhas else {"erro": "Saída sem registros parseáveis."}
            elif spec.get("parsers"):
                por_comando = {
                    comando: parse_template(spec["parsers"][comando], saidas[comando])
                    for comando in comandos
                }
                recursos[nome] = merge_parsed(spec["merge"], por_comando)
            elif spec.get("alvo_sessoes"):
                por_comando = {
                    comando: parse_template(spec["parser_alvo"], saidas[comando])
                    for comando in comandos
                }
                recursos[nome] = merge_parsed(spec["merge"], por_comando)
            else:
                recursos[nome] = {"backup": True}
        except Exception as exc:  # noqa: BLE001 — falha de recurso vira erro no dict
            erros[nome] = str(exc)
    return recursos, erros, arquivos_brutos
```

Substituir no corpo de `run_collection` as linhas 101-148 (a criação de snapshot + o laço) por:

```python
            inicio = datetime.now(UTC)
            snapshot = DeviceSnapshot(device_id=dev.id, status="error")
            session.add(snapshot)
            session.commit()

            base = settings.backups_dir / dev.name / inicio.strftime("%Y%m%dT%H%M%S")
            recursos, erros, arquivos_brutos = _coleta_recursos(session, dev, cred, settings, base)

            snapshot.finished_at = datetime.now(UTC)
            snapshot.duration_ms = int((snapshot.finished_at - inicio).total_seconds() * 1000)
            snapshot.resources = recursos
            snapshot.errors = erros
            snapshot.raw_files = arquivos_brutos
            snapshot.status = "success" if not erros else ("error" if not recursos else "partial")
```

(As linhas de 101-122 usam `recursos`/`erros`/`arquivos_brutos`/`base` já inicializados — remova as declarações antigas do laço. O restante de `run_collection` — touch_collection, job, auditoria, locks — fica intacto. Rodar `uv run pytest tests/automation/test_runner.py -q` ao fim do Step 7 para garantir o refactor.)

Agora as funções novas (acrescentar ao fim de runner.py):

```python
def _grava_snapshot(session: Session, dev, inicio: datetime, recursos: dict, erros: dict, arquivos: dict, actor: str) -> models.DeviceSnapshot:
    """DeviceSnapshot completo + touch_collection (compartilhado coleção/mudança)."""
    agora = datetime.now(UTC)
    snap = DeviceSnapshot(
        device_id=dev.id,
        status="success" if not erros else ("error" if not recursos else "partial"),
        resources=recursos, errors=erros, raw_files=arquivos,
        started_at=inicio, finished_at=agora,
        duration_ms=int((agora - inicio).total_seconds() * 1000),
    )
    session.add(snap)
    session.commit()
    versao = recursos.get("version")
    device_svc.touch_collection(
        session, dev,
        ok=bool(recursos),
        version=versao.get("version") if isinstance(versao, dict) else None,
        uptime=versao.get("uptime") if isinstance(versao, dict) else None,
    )
    session.commit()
    return snap


def _chave_bloco(bloco: dict) -> tuple:
    return (bloco["tipo"], bloco["objeto_id"], bloco["comandos"][0] if bloco["comandos"] else "")


def _re_diff(recompute: list[dict], congelado: list[dict]) -> tuple[list[dict], list[dict], str | None]:
    """§5.3 — re-diff do plano congelado contra o recomputado na coleta fresca.

    Devolve (a_aplicar, a_pular, erro_divergencia): create que já existe e
    delete que já não existe saem do plano (pulados); comando diferente para o
    mesmo objeto ⇒ divergência, aborta (config inalterada ≠ §12.2).
    """
    por_chave = {_chave_bloco(b): b for b in recompute}
    a_aplicar: list[dict] = []
    a_pular: list[dict] = []
    for bloco in congelado:
        chave = _chave_bloco(bloco)
        atual = por_chave.pop(chave, None)
        if atual is None:
            a_pular.append(bloco)
        elif atual["comandos"] == bloco["comandos"]:
            a_aplicar.append(bloco)
        else:
            return [], [], (
                f"Estado divergente no objeto {bloco['tipo']} (#{bloco['objeto_id']}): "
                f"comandos mudaram entre o plano e a execução (§5.3)."
            )
    if por_chave:
        sobra = next(iter(por_chave.values()))
        return [], [], f"Estado divergente: objeto {sobra['tipo']} (#{sobra['objeto_id']}) inesperado no encontrado."
    return a_aplicar, a_pular, None


def _aplica_blocos(session: Session, dev, cred: dict, blocos: list[dict], settings) -> str | None:
    """Bloco a bloco (uma conexão por bloco, §6.4); None = ok, senão primeira linha de erro VRP."""
    for bloco in blocos:
        comandos = bloco.get("comandos") or []
        if not comandos:
            continue
        saida = _conectar_e_aplicar(dev, cred["username"], cred["password"], comandos, settings)
        texto = saida.get("config", "")
        if ERROS_VRP.search(texto):
            linha = next((l.strip() for l in texto.splitlines() if ERROS_VRP.search(l)), "Erro do VRP")
            return linha[:500]
    return None
```

E a função principal:

```python
def run_change(
    change_request_id: int,
    *,
    actor: str = "worker",
    origin: str = "rq",
    settings: Settings | None = None,
    session_override: Session | None = None,
) -> dict:
    """Executa uma change request aprovada (spec §6): por step — lock por device,
    coleta fresca (backup pré-mudança §12.3), re-diff §5.3, aplicação bloco a
    bloco com denylist, nova coleta + pós-validação, classificação §6.5."""
    settings = settings or get_settings()
    session_propria = session_override is None
    session = session_override or SessionLocal()
    redis: Redis | None = None
    try:
        token = secrets.token_hex(16)
        redis = Redis.from_url(settings.redis_url)
        cr = session.get(models.ChangeRequest, change_request_id)
        if cr is None:
            raise ValueError(f"Change request {change_request_id} não encontrada.")
        chave_cr = f"gerenet:lock:change:{change_request_id}"
        if not redis.set(chave_cr, token, nx=True, ex=settings.lock_ttl_seconds):
            session.add(models.AuditEvent(
                type="change.skipped", actor=actor,
                details={"change_request_id": change_request_id, "reason": "lock"},
            ))
            session.commit()
            return {"status": "error", "error": "Change request já está sendo executada (lock ativo)."}
        try:
            if cr.status == "aprovado":
                cr.status = "executando"
                session.add(models.AuditEvent(
                    type="change.executing", actor=actor,
                    details={"change_request_id": cr.id, "criticidade": cr.criticidade},
                ))
                session.commit()
            elif cr.status != "executando":
                session.add(models.AuditEvent(
                    type="change.skipped", actor=actor,
                    details={"change_request_id": cr.id, "reason": f"estado {cr.status}"},
                ))
                session.commit()
                return {"status": "error", "error": f"Change request não executável (estado {cr.status})."}

            circ = get_circuit(session, cr.circuit_id)  # NotFoundError propaga (falha de setup)
            base = settings.backups_dir / f"change-{cr.id}" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            resultados: list[str] = []
            post_ok = True
            for step in cr.steps:
                if step.status != "pendente":
                    continue
                dev = device_svc.get_device(session, step.device_id)
                cred = None
                grupo = dev.credential_group
                if grupo is not None:
                    cred = VaultSecretStore(settings.vault_url, settings.vault_token).get_credential(grupo.vault_path)

                chave_dev = f"gerenet:lock:device:{dev.id}"
                if not redis.set(chave_dev, token, nx=True, ex=settings.lock_ttl_seconds):
                    step.status = "falhou"
                    step.erro = "Equipamento ocupado (lock ativo) — reexecute após a coleta em andamento."
                    step.finished_at = datetime.now(UTC)
                    job = JobRun(device_id=dev.id, actor=actor, origin=origin, kind="change", status="error", error=step.erro)
                    session.add(job)
                    session.commit()
                    session.add(models.AuditEvent(
                        type="change.step_failed", actor=actor,
                        details={"change_request_id": cr.id, "change_step_id": step.id,
                                 "device_id": dev.id, "reason": "lock"},
                    ))
                    session.commit()
                    resultados.append("falhou")
                    continue
                try:
                    resultado_do_step = _executa_step(
                        session, cr, step, dev, cred, settings, base, actor=actor, origin=origin,
                    )
                    resultados.append(resultado_do_step)
                    if resultado_do_step in ("aplicado", "pulado"):
                        post_ok = True  # marcado por step — ver classificação abaixo
                finally:
                    _liberta_lock(redis, chave_dev, token)

            if resultados:
                post_criticas = any(
                    step.post_check_json and any(i["severidade"] == "critica" for i in step.post_check_json.get("items", []))
                    for step in cr.steps if step.status in ("aplicado", "pulado")
                )
                status_cr = None
                if all(r in ("aplicado", "pulado") for r in resultados):
                    status_cr = "com_divergencia" if post_criticas else "aplicado"
                elif any(r in ("aplicado", "pulado") for r in resultados):
                    status_cr = "parcial"
                else:
                    status_cr = "erro"
                cr.status = status_cr
                session.add(models.AuditEvent(type=f"change.{status_cr}", actor=actor, details={"change_request_id": cr.id}))
                session.commit()
                return {"status": status_cr}
            return {"status": "erro", "error": "Change request sem steps pendentes."}
        except Exception as exc:  # noqa: BLE001 — contrato dict preservado
            if cr.status == "executando":
                cr.status = "erro"
                session.add(models.AuditEvent(
                    type="change.errors", actor=actor,
                    details={"change_request_id": cr.id, "error": mascarar(str(exc))[:500]},
                ))
                session.commit()
            return {"status": "error", "error": str(exc)}
        finally:
            _liberta_lock(redis, chave_cr, token)
    except Exception as exc:  # noqa: BLE001 — falha pré-lock
        return {"status": "error", "error": str(exc)}
    finally:
        if redis is not None:
            redis.close()
        if session_propria:
            session.close()
```

E `_executa_step` (a mesma função usada pelos testes):

```python
def _executa_step(session: Session, cr, step, dev, cred, settings, base, *, actor: str, origin: str) -> str:
    """Um step: coleta fresca → re-diff → aplicação → pós-validação.

    Retorna "aplicado" | "pulado" | "falhou" (e preenche step/JobRun/auditoria).
    """
    inicio = datetime.now(UTC)
    job = JobRun(device_id=dev.id, actor=actor, origin=origin, kind="change", status="running")
    session.add(job)
    session.commit()
    try:
        if cred is None:
            raise ValueError(f"{dev.name} não possui grupo de credencial.")
        recursos_pre, erros_pre, arquivos_pre = _coleta_recursos(session, dev, cred, settings, base / "pre")
        snap_pre = _grava_snapshot(session, dev, inicio, recursos_pre, erros_pre, arquivos_pre, actor)
        step.backup_snapshot_id = snap_pre.id  # backup pré-mudança §12.3

        if erros_pre and not recursos_pre:
            raise ValueError(f"Coleta pré-mudança sem recursos: {list(erros_pre)[:3]}")

        # re-diff §5.3 contra o plano congelado
        replan = plan_provision(session, cr.circuito) if cr.acao == "provision" else plan_remocao(session, cr.circuito)
        recompute = next((p.blocos for p in replan if p.device_id == dev.id), None)
        if recompute is None:
            raise ValueError(f"Recompute sem device {dev.id} no plano do circuito.")
        a_aplicar, a_pular, divergencia = _re_diff(recompute, step.plano_json or [])
        if divergencia is not None:
            raise ValueError(divergencia)

        erro = _aplica_blocos(session, dev, cred, a_aplicar, settings)
        if erro is not None:
            step.status = "falhou"
            step.erro = erro
            step.finished_at = datetime.now(UTC)
            job.status = "error"
            job.error = erro
            job.finished_at = step.finished_at
            session.commit()
            session.add(models.AuditEvent(
                type="change.step_failed", actor=actor,
                details={"change_request_id": cr.id, "change_step_id": step.id,
                         "device_id": dev.id, "error": mascarar(erro)},
            ))
            session.commit()
            return "falhou"

        # pós-coleta de verificação (a "validação do resultado" §12.3/§13)
        recursos_pos, erros_pos, arquivos_pos = _coleta_recursos(session, dev, cred, settings, base / "pos")
        snap_pos = _grava_snapshot(session, dev, datetime.now(UTC), recursos_pos, erros_pos, arquivos_pos, actor)
        if cr.acao == "provision":
            resultado = reconciliar_device(session, dev.id, snapshot_id=snap_pos.id)
            items = [asdict(i) for i in resultado.items]
        else:
            # remoção: pós-check é "the removed objects estão ausentes" (encontrado pós)
            itens = []
            for bloco in (step.plano_json or []):
                if bloco.get("acao") == "delete" and bloco.get("tipo") == "bgp_peer":
                    remote = bloco["comandos"][1].split()[1] if len(bloco["comandos"]) > 1 else None
                    achados = [l.get("peer") for l in snap_pos.resources.get("bgp_peers", [])]
                    if remote is not None and remote in achados:
                        itens.append({"tipo": "bgp_peer.removido", "severidade": "critica",
                                      "esperado": f"peer {remote} ausente", "encontrado": f"peer {remote} presente", "acao": "Remover manualmente."})
            items = itens
        step.post_check_json = {"snapshot_id": snap_pos.id, "items": items}

        label = "aplicado" if a_aplicar else "pulado"
        step.status = label
        step.finished_at = datetime.now(UTC)
        job.status = "success"
        job.finished_at = step.finished_at
        session.commit()
        session.add(models.AuditEvent(
            type="change.step_applied" if label == "aplicado" else "change.step_skipped",
            actor=actor,
            details={"change_request_id": cr.id, "change_step_id": step.id,
                     "device_id": dev.id, "blocos": len(a_aplicar), "pulados": len(a_pular)},
        ))
        session.commit()
        return label
    except Exception as exc:  # noqa: BLE001 — contrato string
        session.rollback()
        step.status = "falhou"
        step.erro = mascarar(str(exc))[:500]
        step.finished_at = datetime.now(UTC)
        job.status = "error"
        job.error = step.erro
        job.finished_at = step.finished_at
        session.commit()
        session.add(models.AuditEvent(
            type="change.step_failed", actor=actor,
            details={"change_request_id": cr.id, "change_step_id": step.id,
                     "device_id": dev.id, "error": step.erro},
        ))
        session.commit()
        return "falhou"
```

Imports novos no runner.py:

```python
from dataclasses import asdict

from gerenet.automation import changes
from gerenet.automation.netmiko_conn import connect_and_apply
from gerenet.automation.reconcile import reconciliar_device
from gerenet.domain.models import AuditEvent, ChangeRequest, ChangeStep, DeviceSnapshot, JobRun
```

(`_conectar_e_aplicar` — wrapper de monkeypatch, junto de `_conectar_e_executar`):

```python
def _conectar_e_aplicar(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    return connect_and_apply(device, username, password, commands, settings)
```

Notas sobre o contrato da classificação (para não errar o teste `test_run_change_fluxo_ok_cr_aplicada`): `run_change` retorna `{"status": ...}` sem `error` no sucesso; no lock de device a CR termina `erro` com step `falhou` (todos falharam) — o teste de lock espera exatamente isso. O step `pulado` acontece quando a coleta fresca já traz o encontrado = desejado (o re-diff pula tudo) — no teste correspondente o `colas` tem UMA coleção (a pré); a execução de `_aplica_blocos` com `a_aplicar=[]` não conecta, e a pós-coleta re-popularia `colas` — ajuste a fake `_coleta` para devolver `_recursos_aplicados` quando a lista esvazia (a `_fakes_de_mudanca` já cai no fallback `_recursos_vazios`; troque o fallback para `_recursos_aplicados` se a pós-coleta comparar o desejado). Mais simples e determinístico: na `_fakes_de_mudanca`, o fallback (`colas` vazia) devolve **o último elemento repetido** — implemente com `default=colas[-1]` antes do pop:

```python
    def _coleta(session, device, cred, settings, base):
        recursos = colas.pop(0) if colas else colas_ultimo
        return recursos, {}, {}
    colas_ultimo = ...  # captura no closure via não-local
```

Use este shape definitivo:

```python
def _fakes_de_mudanca(monkeypatch: pytest.MonkeyPatch, db_session: Session, dev, colas: list[dict]):
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    ultimo: list[dict | None] = [None]

    def _coleta(session, device, cred, settings, base):
        recursos = colas.pop(0) if colas else ultimo[0]
        ultimo[0] = recursos
        return dict(recursos), {}, {}

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_aplicar",
        lambda device, username, password, commands, settings: {"config": "\n".join(commands) + "\n"},
    )
```

(O `_coleta` precisa devolver RECURSOS novos a cada chamada — `dict(recursos)` — porque o `_grava_snapshot`/reconciliador só leem; o importante é o teste com 1 coleção, cujo fallback repete o estado aplicado.)

- [ ] **Step 7: Rodar e verificar verde**

Run: `uv run pytest tests/automation/test_runner_change.py tests/automation/test_runner.py -q`
Expected: PASS (6 novos + suíte de runner intacta — o refactor de `_coleta_recursos` não muda comportamento).

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/automation/netmiko_conn.py src/gerenet/automation/runner.py tests/automation/test_netmiko_conn.py tests/automation/test_runner_change.py
git commit -m "feat(automation): connect_and_apply (denylist) + run_change com re-diff/pós-validação (ciclo D T6)"
```

### Task 7: Worker — fila `gerenet-change` + endpoint `/executar` enfileira antes de transitar

**Files:**
- Modify: `src/gerenet/worker/tasks.py` (`enqueue_change`, `change_task`, `worker_main` com 2 filas)
- Modify: `src/gerenet/api/routers/change_requests.py` (substituir `//executar` pelo enqueue + 202)
- Modify: `tests/api/test_change_requests_api.py` (ajustar `test_executar_marca_executando` — T5 escreveu 200 sem fila)
- Create: `tests/worker/test_tasks_change.py`

**Interfaces:**
- Consumes: `run_change(change_request_id, *, actor="worker", origin="rq", settings=None, session_override=None) -> dict` (T6); `marcar_executando` agora idempotente (T4); `get_change_request` (T4); padrões de `enqueue_collect`/`collect_task`/`worker_main` (tasks.py:15-70, intactos); padrão do `/collect` 202/404/409 (devices.py:102-113).
- Produces: `enqueue_change(change_request_id, *, actor, origin) -> dict` (contrato `{"queued": bool, "job_id"?, "message"}` igual ao de coleta); `change_task(change_request_id)`; `worker_main()` escutando `["gerenet-collect", "gerenet-change"]` (spec ciclo D §6.6 — entrypoint `gerenet-worker` de pyproject não muda); endpoint `/executar` devolve 202 `{"queued": True, "job_id", "message"}`. Task 8 (CLI execute) consome `enqueue_change` com origin="cli".

**Nota de decisão (já registrada no spec, §6.6):** o worker é o **transitor autoritativo** — a fila só trabalha CRs `aprovado|executando`; o endpoint enfileira primeiro (validação + locks + dedup) e depois chama `marcar_executando` (agora idempotente: `executando` → devolve como está). Nunca fica um `aprovado` com job consumido nem um `executando` órfão.

- [ ] **Step 1: Escrever os testes do worker (failing)**

`tests/worker/test_tasks_change.py` (padrão de test_tasks.py — Redis real, fila limpa antes/depois):

```python
"""enqueue_change (spec §6.6): validação, dedup e lock antes da fila gerenet-change."""
import pytest
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from gerenet.config import Settings
from gerenet.domain.schemas import ChangeRequestCreate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services import change_requests as crsvc
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site
from gerenet.worker.tasks import change_task, enqueue_change


@pytest.fixture()
def fila_limpa() -> Redis:
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    fila = Queue("gerenet-change", connection=r)
    fila.empty()  # limpa antes e depois: a suíte não deixa jobs órfãos p/ o worker dev
    r.delete("gerenet:lock:change:1")
    yield r
    fila.empty()


def _cr(db_session: Session, *, aprovada: bool = False) -> int:
    """Circuito reservado com sessão + CR; aprovada=True leva a CR a aprovado."""
    site = create_site(db_session, SiteCreate(name="pop-q", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-q", management_address="10.0.0.1", asn=65000), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-q", asn=64500), actor="cli")
    circ = create_circuit(
        db_session,
        {
            "code": "CR-Q-1", "organization_id": org.id, "site_id": site.id,
            "access_device_id": dev.id, "access_port": "GE0/0/1",
            "edge_device_id": dev.id, "edge_trunk": "GE1/0/0", "p2p_v4_len": 31,
        },
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(
        db_session,
        {
            "circuit_id": circ.id, "device_id": dev.id, "afi": "ipv4",
            "local_address": "10.0.0.1", "remote_address": "10.0.0.2",
            "asn_local": 65000, "asn_remote": 64500,
        },
        actor="cli",
    )
    cr = crsvc.create_change_request(
        db_session, ChangeRequestCreate(circuit_id=circ.id, acao="provision", motivo="Ativação."),
        actor="cli",
    )
    if aprovada:
        crsvc.enviar_para_aprovacao(db_session, cr.id, actor="cli")
        crsvc.aprovar(db_session, cr.id, actor="cli", decisao="aprovar")
    db_session.commit()
    return cr.id


def test_nao_duplica_job_pendente(fila_limpa: Redis, db_session: Session) -> None:
    cr_id = _cr(db_session, aprovada=True)
    q = Queue("gerenet-change", connection=fila_limpa)
    primeiro = enqueue_change(cr_id, actor="cli", origin="cli")
    assert primeiro["queued"] is True
    assert primeiro["job_id"]

    segundo = enqueue_change(cr_id, actor="cli", origin="cli")
    assert segundo["queued"] is False
    assert "pendente" in segundo["message"]
    visiveis = len(list(q.get_jobs())) + len(list(q.started_job_registry.get_job_ids()))
    assert visiveis == 1


def test_enqueue_bloqueia_cr_nao_aprovada(db_session: Session) -> None:
    """A validação vem antes do Redis: queixa clara, sem job fútil (spec §6.1)."""
    cr_id = _cr(db_session)
    resultado = enqueue_change(cr_id, actor="cli", origin="cli")
    assert resultado["queued"] is False
    assert "aprovada" in resultado["message"]
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/worker/test_tasks_change.py -v`
Expected: FAIL — `ImportError: cannot import name 'enqueue_change'`.

- [ ] **Step 3: Implementar no worker**

Em `src/gerenet/worker/tasks.py`:

```python
from gerenet.automation.runner import run_change, run_collection
from gerenet.domain.services import change_requests as change_svc
```

Acrescentar ao fim do arquivo (consertar `worker_main` no meio — ver último bloco):

```python
def enqueue_change(change_request_id: int, *, actor: str, origin: str) -> dict:
    """Valida a CR e enfileira a execução na fila `gerenet-change` (spec §6.6).

    Espelho de enqueue_collect: queixa clara na origem antes de job fútil;
    não enfileira se a CR não está aprovada ou já tem job pendente/iniciado.
    O lock real é do worker (run_change); aqui só a checagem barata.
    """
    with get_session() as session:
        try:
            cr = change_svc.get_change_request(session, change_request_id)
        except NotFoundError:
            return {"queued": False, "message": "Change request não encontrada."}
        if cr.status != "aprovado":
            return {
                "queued": False,
                "message": f"Change request não está aprovada para execução (status: {cr.status}).",
            }
        if not cr.steps:
            return {"queued": False, "message": "Change request sem steps para executar."}

    settings = get_settings()
    r = _redis(settings)
    chave_lock = f"gerenet:lock:change:{change_request_id}"
    if r.get(chave_lock):
        return {"queued": False, "message": "Já existe uma execução em andamento para esta change request."}

    q = Queue("gerenet-change", connection=r)
    pendentes = list(q.job_ids) + list(q.started_job_registry.get_job_ids())
    for job_id in pendentes:
        job = q.fetch_job(job_id)
        if job is not None and job.args and job.args[0] == change_request_id:
            return {"queued": False, "message": "Já existe uma execução pendente para esta change request."}

    job = q.enqueue(
        change_task,
        change_request_id,
        job_timeout=3600,
        result_ttl=3600,
        meta={"actor": actor, "origin": origin},
    )
    return {"queued": True, "job_id": job.id, "message": "Mudança enfileirada."}


def change_task(change_request_id: int) -> None:
    """Executada pelo worker; actor/origin chegam pelo job.meta."""
    job = get_current_job()
    meta = job.meta if job is not None else {}
    run_change(
        change_request_id,
        actor=meta.get("actor", "worker"),
        origin=meta.get("origin", "rq"),
    )
```

`worker_main` passa a escutar as duas filas (spec ciclo D §6.6; entrypoint pyproject permanece):

```python
def worker_main() -> None:
    from rq.worker import Worker

    settings = get_settings()
    with _redis(settings) as r:
        Worker(["gerenet-collect", "gerenet-change"], connection=r).work()
```

- [ ] **Step 4: Rodar e verificar verde**

Run: `uv run pytest tests/worker/test_tasks_change.py tests/worker/test_tasks.py -q`
Expected: PASS (2 novos + 2 antigos intactos).

- [ ] **Step 5: Ajustar o teste T5 do `/executar` + implementar o enqueue no router**

Em `tests/api/test_change_requests_api.py`, substituir `test_executar_marca_executando` (T5) por:

```python
def test_executar_enfileira_e_marca_executando(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    _usuario(db_session, "aprovador-ex", "aprovador")
    _usuario(db_session, "executor-ex", "executor")
    client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth())
    _login(client, "aprovador-ex")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 200
    client.post("/api/v1/auth/logout")
    # executor não aprova, mas executa
    _login(client, "executor-ex")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 403

    with patch(
        "gerenet.api.routers.change_requests.enqueue_change",
        return_value={"queued": True, "job_id": "abc123", "message": "Mudança enfileirada."},
    ) as enfileirar:
        exec = client.post(f"/api/v1/change-requests/{cr['id']}/executar")
    assert exec.status_code == 202
    assert exec.json()["queued"] is True
    enfileirar.assert_called_once_with(cr["id"], actor="executor-ex", origin="api")
    modelo = db_session.get(models.ChangeRequest, cr["id"])
    assert modelo.status == "executando"
```

(Importar `from unittest.mock import patch` no topo do arquivo de teste, e `from gerenet.domain import models` local — como já usados no test_rollback.)

Em `src/gerenet/api/routers/change_requests.py`:

- Importar: `from gerenet.worker.tasks import enqueue_change`.
- Substituir a função `executar` (T5) por:

```python
@router.post("/{cr_id}/executar", status_code=202)
def executar(cr_id: int, session: SessionDep, executor: ExecutorDep) -> dict:
    """Papel executor/admin; valida e ENFILEIRA antes de transitar (worker é o
    transitor autoritativo — reexecução segura, lock de CR no run_change).
    """
    try:
        svc.get_change_request(session, cr_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    enfileirado = enqueue_change(cr_id, actor=executor.nome, origin="api")
    if not enfileirado["queued"]:
        raise HTTPException(status_code=409, detail=enfileirado["message"])
    try:
        svc.marcar_executando(session, cr_id, actor=executor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"queued": True, "job_id": enfileirado.get("job_id"), "message": enfileirado["message"]}
```

(Nota: `svc.marcar_executando` é chamado DEPOIS do enqueue — se o worker agarrar o job e transitar primeiro, o `marcar_executando` é idempotente e retorna como está (T4). `get_change_request` antes do enqueue dá 404 em vez de 409 para CR inexistente — espelha o `/collect` de devices.py:102-113.)

- [ ] **Step 6: Rodar e verificar verde (API + worker)**

Run: `uv run pytest tests/api/test_change_requests_api.py tests/worker/ -q`
Expected: PASS (5 testes de API — 1 ajustado — + 2 worker novos + 2 antigos). Cuidado com locks órfãos: use o padrão try/finally dos demais testes de Redis ou rode com redis limpo (o `fila_limpa` já limpa a fila; o lock de CR usa `ex=300` e é removido pelo teste de DB de outra suíte — nenhum teste de enqueue seta o lock).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/worker/tasks.py src/gerenet/api/routers/change_requests.py tests/api/test_change_requests_api.py tests/worker/test_tasks_change.py
git commit -m "feat(worker): fila gerenet-change + enqueue_change e /executar 202 com enqueue primeiro (ciclo D T7)"
```

### Task 8: CLI — `change-requests` (add/list/show/send/approve/cancel/execute/rollback/reconcile)

**Files:**
- Create: `src/gerenet/cli/change_requests.py`
- Modify: `src/gerenet/cli/main.py` (import + `app.add_typer(change_requests.app, name="change-requests", ...)`)
- Test: `tests/cli/test_change_requests_cli.py`

**Interfaces:**
- Consumes: serviço `change_requests` T4 (`create_change_request/aprovar/enviar_para_aprovacao/cancelar/marcar_executando/gerar_rollback/reconciliar/get_change_request/list_change_requests` — todos aceitam `actor="cli"` sem `ator_id`); `enqueue_change(change_request_id, *, actor, origin)` (T7); `GerenetError`/`NotFoundError` (domain/services/errors.py); `get_session` (db.py); padrão de CLI: `typer.Typer`, `@app.command`, `get_session()` como context manager (cli/circuits.py:1-129).
- Produces: grupo CLI `gerenet change-requests <comando>` — `add|list|show|send|approve|cancel|execute|rollback|reconcile`; testado por `tests/cli/test_change_requests_cli.py` (CliRunner + DB real, padrão test_cli_smoke.py).

**Nota (especifica o T4):** a CLI não tem identidade de usuário — `aprovador ≠ solicitante` não é aplicável para o CLI (ator_id=None), e a auditoria registra `actor="cli"`. Regra de papel/pessoa vale para a API/web (T5).

- [ ] **Step 1: Escrever os testes (failing)**

`tests/cli/test_change_requests_cli.py`:

```python
"""CLI do fluxo de mudança (spec ciclo D §8.1): smoke via CliRunner + DB real."""
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site

runner = CliRunner()


def _circuito(db_session: Session) -> int:
    site = create_site(db_session, SiteCreate(name="pop-cr-cli", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cr-cli", management_address="10.0.0.1", asn=65000), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-cr-cli", asn=64500), actor="cli")
    circ = create_circuit(
        db_session,
        {"code": "CR-CLI-1", "organization_id": org.id, "site_id": site.id,
         "access_device_id": dev.id, "access_port": "GE0/0/1",
         "edge_device_id": dev.id, "edge_trunk": "GE1/0/0", "p2p_v4_len": 31},
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(
        db_session,
        {"circuit_id": circ.id, "device_id": dev.id, "afi": "ipv4",
         "local_address": "10.0.0.1", "remote_address": "10.0.0.2",
         "asn_local": 65000, "asn_remote": 64500},
        actor="cli",
    )
    db_session.commit()
    return circ.id


def _cr_id(add_output: str) -> int:
    return int(add_output.split("CR #")[1].split()[0])
```

```python
def test_cli_add_list_show_erros(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    assert add.exit_code == 0, add.output
    assert "rascunho" in add.output
    cr_id = _cr_id(add.output)
    assert f"CR #{cr_id}" in runner.invoke(app, ["change-requests", "list"]).output

    show = runner.invoke(app, ["change-requests", "show", str(cr_id)])
    assert show.exit_code == 0, show.output
    assert "subinterface" in show.output
    assert "pendente" in show.output

    sem_circuito = runner.invoke(app, ["change-requests", "add", "--circuit-id", "9999", "--motivo", "X"])
    assert sem_circuito.exit_code == 1
    assert "Erro:" in sem_circuito.output
    inexistente = runner.invoke(app, ["change-requests", "show", "9999"])
    assert inexistente.exit_code == 1
    assert "não encontrada" in inexistente.output


def test_cli_send_approve_fluxo(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    env = runner.invoke(app, ["change-requests", "send", str(cr_id)])
    assert env.exit_code == 0, env.output
    assert "aprova" in env.output
    ap = runner.invoke(app, ["change-requests", "approve", str(cr_id), "--comentario", "janela ok"])
    assert ap.exit_code == 0, ap.output
    cr = db_session.get(models.ChangeRequest, cr_id)
    assert cr.status == "aprovado"
    assert cr.approvals[0].decisao == "aprovar"
    # aprovar de novo ⇒ erro de negócio (decisão única)
    de_novo = runner.invoke(app, ["change-requests", "approve", str(cr_id)])
    assert de_novo.exit_code == 1
    assert "Erro:" in de_novo.output


def test_cli_execute_enfileira_e_marca_executando(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    runner.invoke(app, ["change-requests", "send", str(cr_id)])
    runner.invoke(app, ["change-requests", "approve", str(cr_id)])

    with patch(
        "gerenet.cli.change_requests.enqueue_change",
        return_value={"queued": True, "job_id": "job-1", "message": "Mudança enfileirada."},
    ) as enfileirar:
        ok = runner.invoke(app, ["change-requests", "execute", str(cr_id)])
    assert ok.exit_code == 0, ok.output
    assert "enfileirada" in ok.output
    enfileirar.assert_called_once_with(cr_id, actor="cli", origin="cli")
    assert db_session.get(models.ChangeRequest, cr_id).status == "executando"


def test_cli_execute_sem_aprovacao_da_erro(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    erro = runner.invoke(app, ["change-requests", "execute", str(cr_id)])
    assert erro.exit_code == 1
    assert "Erro:" in erro.output
    assert "aprovada" in erro.output


def test_cli_rollback_gera_filho(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    cr = db_session.get(models.ChangeRequest, cr_id)
    cr.status = "aplicado"
    cr.steps[0].status = "aplicado"  # gerar_rollback exige ≥1 step aplicado
    db_session.commit()
    rb = runner.invoke(app, ["change-requests", "rollback", str(cr_id)])
    assert rb.exit_code == 0, rb.output
    filho = db_session.scalar(
        select(models.ChangeRequest).where(models.ChangeRequest.rollback_de == cr_id)
    )
    assert filho is not None
    assert filho.acao == "remove"
    assert filho.status == "aguardando_aprovacao"
    assert "rollback" in rb.output
```

- [ ] **Step 2: Rodar e verificar falha**

Run: `uv run pytest tests/cli/test_change_requests_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.cli.change_requests'` (comando 404 no CliRunner).

- [ ] **Step 3: Implementar `cli/change_requests.py`**

```python
"""Change requests no CLI (spec ciclo D §8.1): cria, lista, envia, aprova, executa.

A CLI não tem identidade de usuário: ator_id fica None (auditoria actor="cli");
aprovação por papel/pessoa vale na API/web (T5).
"""
from typing import Literal

import typer

from gerenet.db import get_session
from gerenet.domain.schemas import ChangeRequestCreate
from gerenet.domain.services import change_requests as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError
from gerenet.worker.tasks import enqueue_change

app = typer.Typer(help="Change requests (fluxo de mudança controlada).")


def _pelo_id(session, cr_id: int):
    """CR por ID com erro de CLI amigável; aborta com exit 1 se não existir."""
    try:
        return svc.get_change_request(session, cr_id)
    except NotFoundError as exc:
        typer.echo(f"Change request não encontrada: {cr_id}.", err=True)
        raise typer.Exit(1) from exc


@app.command("add")
def add(
    circuit_id: int = typer.Option(..., "--circuit-id", help="ID do circuito."),
    motivo: str = typer.Option(..., help="Motivo da mudança."),
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
                    circuit_id=circuit_id, acao=acao, criticidade=criticidade,
                    motivo=motivo, ticket=ticket,
                ),
                actor="cli",
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(
        f"CR #{cr.id} criada (rascunho): {len(cr.steps)} step(s), "
        f"{sum(len(s.plano_json) for s in cr.steps)} bloco(s)."
    )


@app.command("list")
def listar(
    status: str | None = typer.Option(None, "--status", help="Filtra por status."),
    circuit_id: int | None = typer.Option(None, "--circuit-id", help="Filtra por circuito."),
) -> None:
    """Lista change requests (mais recentes primeiro)."""
    with get_session() as session:
        for cr in svc.list_change_requests(session, status=status, circuit_id=circuit_id):
            typer.echo(
                f"CR #{cr.id:>4}  {cr.acao:<9} {cr.status:<18} "
                f"circuito {cr.circuit_id:>4}  {cr.criticidade:<5}  {cr.motivo[:48]}"
            )


@app.command("show")
def show(cr_id: int = typer.Argument(..., help="ID da CR.")) -> None:
    """Mostra uma CR: status, steps e primeiro comando de cada bloco."""
    with get_session() as session:
        cr = _pelo_id(session, cr_id)
        typer.echo(f"CR #{cr.id}: {cr.acao} — {cr.status} (criticidade {cr.criticidade})")
        typer.echo(f"Motivo: {cr.motivo}")
        if cr.ticket:
            typer.echo(f"Ticket: {cr.ticket}")
        for step in cr.steps:
            typer.echo(
                f"  step {step.id} — device {step.device_id}: {step.status} "
                f"({len(step.plano_json)} bloco(s))"
            )
            for bloco in step.plano_json:
                primeiro = bloco["comandos"][0] if bloco["comandos"] else "(sem comandos)"
                typer.echo(f"    {bloco['tipo']} {bloco['acao']} #{bloco['objeto_id']}: {primeiro}")


@app.command("send")
def enviar(cr_id: int = typer.Argument(..., help="ID da CR.")) -> None:
    """Envia para aprovação (rascunho → aguardando_aprovacao)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            cr = svc.enviar_para_aprovacao(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} enviada para aprovação.")


@app.command("approve")
def aprovar(
    cr_id: int = typer.Argument(..., help="ID da CR."),
    decisao: Literal["aprovar", "rejeitar"] = typer.Option(
        "aprovar", "--decisao", help="aprovar ou rejeitar."
    ),
    comentario: str | None = typer.Option(None, "--comentario", help="Comentário do aprovador."),
) -> None:
    """Registra a decisão de aprovação (única por CR)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            cr = svc.aprovar(session, cr_id, actor="cli", decisao=decisao, comentario=comentario)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} agora está {cr.status}.")


@app.command("cancel")
def cancelar(cr_id: int = typer.Argument(..., help="ID da CR.")) -> None:
    """Cancela a CR (de rascunho ou aguardando_aprovacao)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            cr = svc.cancelar(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} cancelada.")


@app.command("execute")
def executar(cr_id: int = typer.Argument(..., help="ID da CR aprovada.")) -> None:
    """Enfileira a execução aprovada (fila gerenet-change) e marca executando."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        enfileirado = enqueue_change(cr_id, actor="cli", origin="cli")
        if not enfileirado["queued"]:
            typer.echo(f"Erro: {enfileirado['message']}", err=True)
            raise typer.Exit(1)
        try:
            svc.marcar_executando(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr_id} enfileirada ({enfileirado['job_id']}) — status executando.")


@app.command("rollback")
def rollback(cr_id: int = typer.Argument(..., help="ID da CR aplicada.")) -> None:
    """Gera a CR inversa (aguardando_aprovacao) a partir do baseline (§7)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            filho = svc.gerar_rollback(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{filho.id} de rollback criada ({filho.status}) a partir do CR #{cr_id}.")


@app.command("reconcile")
def reconciliar(cr_id: int = typer.Argument(..., help="ID da CR em erro/parcial.")) -> None:
    """Replaneja steps não aplicados e devolve a CR à aprovação."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            cr = svc.reconciliar(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} reconciliada — {cr.status}.")
```

Em `src/gerenet/cli/main.py`:

- Importar no bloco `from gerenet.cli import (...)` (ordem alfabética): `change_requests,` entre `bgp_sessions,` e `circuits,`.
- Registrar após `bgp_sessions`:

```python
app.add_typer(change_requests.app, name="change-requests", help="Change requests (fluxo de mudança).")
```

- [ ] **Step 4: Rodar e verificar verde**

Run: `uv run pytest tests/cli/test_change_requests_cli.py -v`
Expected: PASS (5 testes). Atenção: `runner.invoke` contra o app real usa o banco de teste (conftest trunca entre testes) — não chamar Redis fora do patch de `enqueue_change` (o `test_cli_execute_sem_aprovacao_da_erro` falha ANTES do Redis na validação).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/cli/change_requests.py src/gerenet/cli/main.py tests/cli/test_change_requests_cli.py
git commit -m "feat(cli): gerenet change-requests (add/send/approve/execute/rollback) (ciclo D T8)"
```

### Task 9: Web — páginas de change requests (lista, detalhe, ações por papel)

**Files:**
- Modify: `web/src/api/types.ts` (append espelhos: `ChangeBlocoOut`, `ApprovalOut`, `ChangeStepOut`, `ChangeRequestOut`, `PostCheckOut`, `ChangeRequestCreateIn`)
- Modify: `web/src/api/hooks.ts` (append hooks de CR; tipos: importar `ChangeRequestCreateIn`/`ChangeRequestOut`)
- Create: `web/src/pages/ChangeRequests.tsx`
- Create: `web/src/pages/ChangeRequestDetail.tsx`
- Modify: `web/src/App.tsx` (imports + 2 rotas após `/bgp-sessions/:id`)
- Modify: `web/src/components/Layout.tsx` (grupo "Mudanças" na `GRUPOS_NAV`, entre "Coleta" e "Governança")
- Test: `web/src/pages/ChangeRequests.test.tsx`
- Test: `web/src/pages/ChangeRequestDetail.test.tsx`

**Interfaces:**
- Consumes: API T5/T7 — `GET /api/v1/change-requests[?status=]` e `GET /{cr_id}` → `ChangeRequestOut`; `POST /api/v1/change-requests` (body `ChangeRequestCreateIn`, 201); `POST /{cr_id}/enviar|cancelar|rollback|reconciliar` (200 → `ChangeRequestOut`, qualquer usuário de sessão); `POST /{cr_id}/approve` (body `ApprovalIn`; papel `aprovador|administrador`; aprovador ≠ solicitante — T5); `POST /{cr_id}/executar` (202 → `{queued, message, job_id}` — mesmo shape de `CollectResposta`; papel `executor|administrador` — T7). `useAuth` → `{usuario, podeEscrever}`; `useCircuits`/`useDevices` (C2) para nomes; `DataTable`/`StatusBadge`/`PageHeader`/`Modal`/`ConfirmDialog`/`FormField`/`ApiError`.
- Produces: hooks `useChangeRequests(filtros)/useChangeRequest(id)/useChangeRequestCriar/useChangeRequestEnviar/useChangeRequestAprovar/useChangeRequestCancelar/useChangeRequestExecutar/useChangeRequestRollback/useChangeRequestReconciliar`; páginas; rotas `/change-requests` e `/change-requests/:id`; item "Change requests" na navegação. Consumidos por T10 (botões em CircuitDetail/BgpSessionDetail + card no dashboard) e T11 (e2e).

**Nota (regra de papéis na UI, spec §10):** criar/enviar/cancelar/reconciliar/rollback → qualquer usuário autenticado que não seja *visualizador* (`podeEscrever`); aprovar/rejeitar → `aprovador|administrador` e apenas se `cr.solicitante_id !== usuario.id` (o próprio pedido não aparece); executar → `executor|administrador`. O servidor é a autoridade (403 se burlado) — a UI apenas esconde o que o papel não pode.

- [ ] **Step 1: Espelhos de tipos em `web/src/api/types.ts`**

Acrescentar ao fim de `web/src/api/types.ts` (após `CollectResposta`):

```ts
// Ciclo D — change requests (contrato T4/T5; "acao" presente nos blocos de plano T2/T3).
export interface ChangeBlocoOut extends BlocoOut {
  acao: "create" | "delete";
}
export interface ApprovalOut {
  id: number;
  user_id: number;
  decisao: string;
  comentario: string | null;
  created_at: string;
}
export interface PostCheckOut {
  snapshot_id: number | null;
  items: ReconcileItemOut[]; // mesmo shape do ReconcileOut (T6 grava asdict(item))
}
export interface ChangeStepOut {
  id: number;
  device_id: number;
  status: string;
  plano_json: ChangeBlocoOut[];
  aviso: string | null;
  baseline_snapshot_id: number | null;
  backup_snapshot_id: number | null;
  post_check_json: PostCheckOut | null;
  erro: string | null;
  finished_at: string | null;
}
export interface ChangeRequestOut {
  id: number;
  circuit_id: number;
  acao: "provision" | "remove";
  criticidade: "baixa" | "media" | "alta";
  motivo: string;
  ticket: string | null;
  solicitante_id: number | null;
  status: string;
  rollback_de: number | null;
  created_at: string;
  steps: ChangeStepOut[];
  approvals: ApprovalOut[];
}
export type ChangeRequestCreateIn = {
  circuit_id: number;
  acao: "provision" | "remove";
  criticidade: "baixa" | "media" | "alta";
  motivo: string;
  ticket?: string | null;
};
```

- [ ] **Step 2: Hooks em `web/src/api/hooks.ts`**

No bloco de imports tipados, inserir após `BgpSessionOut` (ordem alfabética):

```ts
  ChangeRequestCreateIn,
  ChangeRequestOut,
```

Acrescentar após `useSessionSenha` (fim da seção BGP, antes de `usePolicyProfiles`):

```ts
export const useChangeRequests = (filtros?: { status?: string; circuit_id?: number; solicitante_id?: number }) =>
  useQuery({
    queryKey: ["change-requests", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.status) qs.set("status", filtros.status);
      if (filtros?.circuit_id) qs.set("circuit_id", String(filtros.circuit_id));
      if (filtros?.solicitante_id) qs.set("solicitante_id", String(filtros.solicitante_id));
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<ChangeRequestOut[]>(`/api/v1/change-requests${suf}`);
    },
  });
export const useChangeRequest = (id: number) =>
  useQuery({
    queryKey: ["change-request", id],
    queryFn: () => apiFetch<ChangeRequestOut>(`/api/v1/change-requests/${id}`),
    enabled: id > 0,
  });

export const useChangeRequestCriar = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChangeRequestCreateIn) =>
      apiFetch<ChangeRequestOut>("/api/v1/change-requests", { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
};

// Ações de transição com corpo vazio — espelham os endpoints T5 (POST retorna ChangeRequestOut).
function useChangeAction(caminho: (id: number) => string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<ChangeRequestOut>(caminho(id), { method: "POST" }),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ["change-request", id] });
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
export const useChangeRequestEnviar = () => useChangeAction((id) => `/api/v1/change-requests/${id}/enviar`);
export const useChangeRequestCancelar = () => useChangeAction((id) => `/api/v1/change-requests/${id}/cancelar`);
export const useChangeRequestRollback = () => useChangeAction((id) => `/api/v1/change-requests/${id}/rollback`);
export const useChangeRequestReconciliar = () => useChangeAction((id) => `/api/v1/change-requests/${id}/reconciliar`);

export function useChangeRequestAprovar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decisao, comentario }: { id: number; decisao: "aprovar" | "rejeitar"; comentario?: string | null }) =>
      apiFetch<ChangeRequestOut>(`/api/v1/change-requests/${id}/approve`, { method: "POST", body: { decisao, comentario } }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["change-request", v.id] });
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useChangeRequestExecutar() {
  const qc = useQueryClient();
  return useMutation({
    // /executar devolve 202 {queued, message, job_id} (T7) — mesmo shape de CollectResposta.
    mutationFn: (id: number) =>
      apiFetch<CollectResposta>(`/api/v1/change-requests/${id}/executar`, { method: "POST" }),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ["change-request", id] });
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
```

- [ ] **Step 3: Página de lista `web/src/pages/ChangeRequests.tsx`**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useChangeRequestCriar, useChangeRequests, useCircuits } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { Modal } from "@/components/Modal";
import type { ChangeRequestOut } from "@/api/types";

const STATUS_OPCOES = [
  { valor: "", rotulo: "Todos" },
  { valor: "rascunho", rotulo: "Rascunho" },
  { valor: "aguardando_aprovacao", rotulo: "Aguardando aprovação" },
  { valor: "aprovado", rotulo: "Aprovado" },
  { valor: "executando", rotulo: "Executando" },
  { valor: "aplicado", rotulo: "Aplicado" },
  { valor: "com_divergencia", rotulo: "Com divergência" },
  { valor: "parcial", rotulo: "Parcial" },
  { valor: "erro", rotulo: "Erro" },
  { valor: "rejeitado", rotulo: "Rejeitado" },
  { valor: "cancelado", rotulo: "Cancelado" },
];

const FORM_VAZIO = {
  circuit_id: "",
  acao: "provision" as "provision" | "remove",
  criticidade: "media" as "baixa" | "media" | "alta",
  motivo: "",
  ticket: "",
};

export default function ChangeRequests() {
  const { podeEscrever } = useAuth();
  const [status, setStatus] = useState("");
  const { data, isLoading, error } = useChangeRequests({ status: status || undefined });
  const { data: circuits } = useCircuits();
  const criar = useChangeRequestCriar();
  const [criando, setCriando] = useState(false);
  const [form, setForm] = useState(FORM_VAZIO);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        circuit_id: Number(form.circuit_id),
        acao: form.acao,
        criticidade: form.criticidade,
        motivo: form.motivo,
        ticket: form.ticket || null,
      });
      setForm(FORM_VAZIO);
      setCriando(false);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar a change request.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Change requests" />
      <form className="form-inline">
        <label className="field">
          <span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPCOES.map((o) => (
              <option key={o.valor} value={o.valor}>{o.rotulo}</option>
            ))}
          </select>
        </label>
      </form>
      {podeEscrever && (
        <button
          className="primary"
          type="button"
          onClick={() => {
            setForm(FORM_VAZIO);
            setErro(null);
            setCriando(true);
          }}
        >
          Solicitar mudança
        </button>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<ChangeRequestOut>
        colunas={[
          { key: "id", title: "ID", render: (cr) => <Link to={`/change-requests/${cr.id}`}>#{cr.id}</Link> },
          { key: "circuit", title: "Circuito", render: (cr) => circuits?.find((c) => c.id === cr.circuit_id)?.code ?? `#${cr.circuit_id}` },
          { key: "acao", title: "Ação", render: (cr) => cr.acao },
          { key: "criticidade", title: "Criticidade", render: (cr) => cr.criticidade },
          { key: "status", title: "Status", render: (cr) => <StatusBadge estado={cr.status} /> },
          { key: "motivo", title: "Motivo", render: (cr) => cr.motivo },
          { key: "created_at", title: "Criada em", render: (cr) => new Date(cr.created_at).toLocaleString("pt-BR") },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar as change requests." : undefined}
      />
      {criando && (
        <Modal aberto titulo="Solicitar mudança" onFechar={() => setCriando(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <FormField label="Circuito *">
              <select value={form.circuit_id} onChange={(e) => setForm({ ...form, circuit_id: e.target.value })} required>
                <option value="">—</option>
                {(circuits ?? []).map((c) => (
                  <option key={c.id} value={c.id}>{c.code}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Ação *">
              <select value={form.acao} onChange={(e) => setForm({ ...form, acao: e.target.value as "provision" | "remove" })}>
                <option value="provision">provision — aplicar configuração</option>
                <option value="remove">remove — remover configuração</option>
              </select>
            </FormField>
            <FormField label="Criticidade *">
              <select value={form.criticidade} onChange={(e) => setForm({ ...form, criticidade: e.target.value as "baixa" | "media" | "alta" })}>
                <option value="baixa">baixa</option>
                <option value="media">média</option>
                <option value="alta">alta</option>
              </select>
            </FormField>
            <FormField label="Motivo *">
              <textarea value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} required rows={3} />
            </FormField>
            <FormField label="Ticket">
              <input value={form.ticket} onChange={(e) => setForm({ ...form, ticket: e.target.value })} />
            </FormField>
            <div className="dialog-actions">
              <button type="button" onClick={() => setCriando(false)} disabled={criar.isPending}>
                Cancelar
              </button>
              <button className="primary" type="submit" disabled={criar.isPending}>
                {criar.isPending ? "Criando…" : "Criar"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </main>
  );
}
```

- [ ] **Step 4: Testes da lista `web/src/pages/ChangeRequests.test.tsx`**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import ChangeRequests from "./ChangeRequests";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };
const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };
const cr = {
  id: 1, circuit_id: 1, acao: "provision", criticidade: "media", motivo: "Novo cliente GALAXIA",
  ticket: "TICKET-42", solicitante_id: 1, status: "rascunho", rollback_de: null,
  created_at: "2026-09-01T10:00:00Z", steps: [], approvals: [],
};

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 9, ...body, status: "rascunho", solicitante_id: 1, rollback_de: null, created_at: "2026-09-05T10:00:00Z", steps: [], approvals: [] }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.startsWith("/api/v1/change-requests")) return new Response(JSON.stringify([cr]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderChangeRequests() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/change-requests"]}>
        <AuthProvider>
          <Routes>
            <Route path="/change-requests" element={<ChangeRequests />} />
            <Route path="/change-requests/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ChangeRequests", () => {
  it("lista change requests e navega para o detalhe", async () => {
    renderChangeRequests();
    expect(await screen.findByText("Novo cliente GALAXIA")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "#1" }));
    expect(await screen.findByText("detail-page")).toBeInTheDocument();
  });

  it("cria CR solicitando pela API", async () => {
    renderChangeRequests();
    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança" }));
    await userEvent.selectOptions(screen.getByLabelText("Circuito *"), "1");
    await userEvent.type(screen.getByLabelText("Motivo *"), "Troca de banda CIRC-01");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("Troca de banda CIRC-01"))).toBe(true);
    });
  });

  it("filtra por status enviando ?status=", async () => {
    renderChangeRequests();
    await screen.findByText("Novo cliente GALAXIA");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "aguardando_aprovacao");
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/change-requests?status=aguardando_aprovacao")).toBe(true);
    });
  });
});
```

(Dica: `screen.getByLabelText("Status")` resolve o `<select>` dentro do `<label className="field"><span>Status</span>…` — mesmo padrão de `AuditEvents.tsx`; se o "Todos" do filter já estiver renderizado como `<option>`, use `screen.getByRole("combobox", { name: "Status" })` na dúvida. Os stubs respondem tanto a URL exata quanto com query — por isso o `startsWith` no branch de CR.)

- [ ] **Step 5: Página de detalhe `web/src/pages/ChangeRequestDetail.tsx`**

```tsx
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useChangeRequest,
  useChangeRequestAprovar,
  useChangeRequestCancelar,
  useChangeRequestEnviar,
  useChangeRequestExecutar,
  useChangeRequestReconciliar,
  useChangeRequestRollback,
  useCircuits,
  useDevices,
} from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ChangeRequestOut } from "@/api/types";

const CONFIRMACOES: Record<string, { titulo: string; mensagem: string }> = {
  cancelar: {
    titulo: "Cancelar a change request?",
    mensagem: "A CR vai a cancelado e não pode mais ser aprovada nem executada (o registro permanece).",
  },
  rejeitar: {
    titulo: "Rejeitar a change request?",
    mensagem: "A CR vai a rejeitado; para voltar ao fluxo, crie uma nova.",
  },
  executar: {
    titulo: "Executar a change request?",
    mensagem: "A mudança será aplicada nos equipamentos pelo worker — confira o diff abaixo antes de confirmar.",
  },
  reconciliar: {
    titulo: "Reconciliar a change request?",
    mensagem: "Steps não aplicados serão replanejados com base no estado atual e a CR volta à aprovação.",
  },
  rollback: {
    titulo: "Gerar rollback?",
    mensagem: "Uma nova CR inversa (aguardando_aprovacao) será criada a partir do snapshot anterior à mudança.",
  },
};

export default function ChangeRequestDetail() {
  const { id } = useParams();
  const crId = Number(id);
  const navigate = useNavigate();
  const { usuario, podeEscrever } = useAuth();
  const { data: cr, isLoading, error } = useChangeRequest(crId);
  const { data: circuits } = useCircuits();
  const { data: devices } = useDevices();
  const enviar = useChangeRequestEnviar();
  const cancelar = useChangeRequestCancelar();
  const aprovar = useChangeRequestAprovar();
  const executar = useChangeRequestExecutar();
  const reconciliar = useChangeRequestReconciliar();
  const rollback = useChangeRequestRollback();
  const [dialogo, setDialogo] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!cr) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar a change request."}</p>
      </main>
    );
  }

  const ehAprovador = usuario !== null && (usuario.role === "aprovador" || usuario.role === "administrador");
  const ehExecutor = usuario !== null && (usuario.role === "executor" || usuario.role === "administrador");
  const ehSolicitante = cr.solicitante_id !== null && usuario !== null && cr.solicitante_id === usuario.id;
  const status = cr.status;
  const circuito = circuits?.find((c) => c.id === cr.circuit_id);

  function executarAcao(fn: () => Promise<unknown>) {
    setErro(null);
    fn().catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao executar a ação."));
  }

  function confirmarAcao() {
    if (dialogo === null) return;
    const acao =
      dialogo === "cancelar" ? () => cancelar.mutateAsync(cr.id)
      : dialogo === "rejeitar" ? () => aprovar.mutateAsync({ id: cr.id, decisao: "rejeitar" })
      : dialogo === "executar" ? () => executar.mutateAsync(cr.id)
      : dialogo === "reconciliar" ? () => reconciliar.mutateAsync(cr.id)
      : () => rollback.mutateAsync(cr.id).then((filho) => navigate(`/change-requests/${filho.id}`));
    setDialogo(null);
    executarAcao(acao);
  }

  const confirmando =
    cancelar.isPending || aprovar.isPending || executar.isPending || reconciliar.isPending || rollback.isPending;

  return (
    <main>
      <PageHeader
        titulo={`Change request #${cr.id}`}
        sub={`${cr.acao} · ${cr.criticidade} · ${new Date(cr.created_at).toLocaleString("pt-BR")}`}
        acoes={
          <>
            <Link to="/change-requests">← Voltar</Link>
            {status === "rascunho" && podeEscrever && (
              <button type="button" disabled={enviar.isPending} onClick={() => executarAcao(() => enviar.mutateAsync(cr.id))}>
                Enviar para aprovação
              </button>
            )}
            {(status === "rascunho" || status === "aguardando_aprovacao") && podeEscrever && (
              <button type="button" onClick={() => setDialogo("cancelar")}>Cancelar</button>
            )}
            {status === "aguardando_aprovacao" && ehAprovador && !ehSolicitante && (
              <>
                <button className="primary" type="button" disabled={aprovar.isPending} onClick={() => executarAcao(() => aprovar.mutateAsync({ id: cr.id, decisao: "aprovar" }))}>
                  Aprovar
                </button>
                <button type="button" onClick={() => setDialogo("rejeitar")}>Rejeitar</button>
              </>
            )}
            {status === "aprovado" && ehExecutor && (
              <button className="primary" type="button" onClick={() => setDialogo("executar")}>Executar</button>
            )}
            {(status === "erro" || status === "parcial") && podeEscrever && (
              <button type="button" onClick={() => setDialogo("reconciliar")}>Reconciliar</button>
            )}
            {(status === "aplicado" || status === "com_divergencia" || status === "parcial") && podeEscrever && (
              <button type="button" onClick={() => setDialogo("rollback")}>Gerar rollback</button>
            )}
          </>
        }
      />
      {erro && <p role="alert">{erro}</p>}
      <table>
        <tbody>
          <tr><th>Status</th><td><StatusBadge estado={status} /></td></tr>
          <tr><th>Circuito</th><td>{circuito ? <Link to={`/circuits/${circuito.id}`}>{circuito.code}</Link> : `#${cr.circuit_id}`}</td></tr>
          <tr><th>Solicitante</th><td>{cr.solicitante_id ?? "cli"}</td></tr>
          <tr><th>Ticket</th><td>{cr.ticket ?? "—"}</td></tr>
          <tr><th>Rollback de</th><td>{cr.rollback_de ? <Link to={`/change-requests/${cr.rollback_de}`}>#{cr.rollback_de}</Link> : "—"}</td></tr>
          <tr><th>Motivo</th><td>{cr.motivo}</td></tr>
        </tbody>
      </table>

      <h2>Aprovações</h2>
      {cr.approvals.length === 0 && <p>Nenhuma aprovação registrada.</p>}
      {cr.approvals.length > 0 && (
        <table>
          <tbody>
            {cr.approvals.map((a) => (
              <tr key={a.id}>
                <td><StatusBadge estado={a.decisao} /></td>
                <td>por usuário #{a.user_id}</td>
                <td>{a.comentario ?? "—"}</td>
                <td>{new Date(a.created_at).toLocaleString("pt-BR")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Steps por equipamento</h2>
      {cr.steps.length === 0 && <p>Sem steps ainda — envie a CR para aprovação para gerar o plano.</p>}
      {cr.steps.map((step) => (
        <section key={step.id}>
          <h3>{devices?.find((d) => d.id === step.device_id)?.name ?? `Device #${step.device_id}`} <StatusBadge estado={step.status} /></h3>
          {step.aviso && <p role="alert">{step.aviso}</p>}
          {step.erro && <p role="alert">{step.erro}</p>}
          <p>
            Baseline: {step.baseline_snapshot_id ?? "—"} · Backup pré-mudança: {step.backup_snapshot_id ?? "—"}
            {step.finished_at && <> · Fim: {new Date(step.finished_at).toLocaleString("pt-BR")}</>}
          </p>
          {step.plano_json.length === 0 && <p>Nenhum comando planejado para o estado atual.</p>}
          {step.plano_json.map((bloco) => (
            <details key={`${bloco.tipo}-${bloco.objeto_id}-${bloco.comandos[0] ?? ""}`}>
              <summary>{bloco.acao} · {bloco.objeto} #{bloco.objeto_id}</summary>
              <pre>{bloco.comandos.join("\n")}</pre>
            </details>
          ))}
          {step.post_check_json && step.post_check_json.items.length > 0 && (
            <>
              <p>Pós-check (snapshot #{step.post_check_json.snapshot_id}):</p>
              <ul>
                {step.post_check_json.items.map((item, idx) => (
                  <li key={idx}>
                    <StatusBadge estado={item.severidade} /> {item.esperado} — encontrado: {item.encontrado}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ))}

      {dialogo !== null && (
        <ConfirmDialog
          aberto
          titulo={CONFIRMACOES[dialogo].titulo}
          mensagem={CONFIRMACOES[dialogo].mensagem}
          onConfirmar={confirmarAcao}
          onCancelar={() => setDialogo(null)}
          confirmando={confirmando}
        />
      )}
    </main>
  );
}
```

*Nota de escopo* (declarada, não implementada aqui): o preço/tamanho da página fica dentro do padrão C2/C3 (`details`+`summary` como em `AuditEvents.tsx`); não há paginação nem export — YAGNI.

- [ ] **Step 6: Testes do detalhe `web/src/pages/ChangeRequestDetail.test.tsx`**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, beforeAll, describe, expect, it, vi } from "vitest";
import ChangeRequestDetail from "./ChangeRequestDetail";
import { AuthProvider } from "@/auth/auth-context";

let ME: Record<string, unknown>; // mutável por teste — define o papel do usuário logado

const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };
const dev1 = { id: 1, name: "ne-01", management_address: "10.9.0.2", site_id: 1, model: null, family: "NE8000", role: "edge", asn: 64600, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const crBase = {
  id: 1, circuit_id: 1, acao: "provision", criticidade: "media", motivo: "Novo cliente GALAXIA",
  ticket: "TICKET-42", rollback_de: null, created_at: "2026-09-01T10:00:00Z",
  approvals: [{ id: 1, user_id: 9, decisao: "aprovar", comentario: "ok", created_at: "2026-09-02T10:00:00Z" }],
  steps: [{
    id: 1, device_id: 1, status: "pendente", aviso: null, baseline_snapshot_id: 3,
    backup_snapshot_id: null, erro: null, finished_at: null,
    post_check_json: null, plano_json: [
      { tipo: "bgp_peer", objeto: "peer", objeto_id: 1, acao: "create", comandos: ["peer 10.9.0.9 as-number 64512", "peer 10.9.0.9 description CLIENTE-GALAXIA"] },
    ],
  }],
};

function crDe(solicitanteId: number | null, status: string) {
  return { ...crBase, solicitante_id: solicitanteId, status };
}

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/approve")) {
        const body = JSON.parse(String(init.body)) as { decisao: string };
        return new Response(JSON.stringify({ ...crDe(2, "aprovado"), approvals: [{ ...crBase.approvals[0], user_id: ME.id as number }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (init?.method === "POST" && url.endsWith("/executar")) {
        return new Response(JSON.stringify({ queued: true, message: "Mudança enfileirada.", job_id: "abc123" }), { status: 202, headers: { "Content-Type": "application/json" } });
      }
      if (url === `/api/v1/change-requests/1`) return new Response(JSON.stringify(CR_ATUAL()), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return new Response(JSON.stringify([dev1]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

const CR_ATUAL = () => crAtual;
let crAtual = crDe(2, "aguardando_aprovacao");

beforeEach(() => {
  ME = { id: 1, username: "aprovador-ex", role: "aprovador", is_active: true, last_login_at: null, created_at: "" };
  crAtual = crDe(2, "aguardando_aprovacao");
});

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/change-requests/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/change-requests/:id" element={<ChangeRequestDetail />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ChangeRequestDetail", () => {
  it("aprovador aprova e vê o diff por bloco", async () => {
    renderDetail();
    expect(await screen.findByText("Change request #1")).toBeInTheDocument();
    expect(screen.getByText(/as-number 64512/)).toBeInTheDocument();
    expect(screen.getByText("por usuário #9")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/change-requests/1/approve" && String(c[1]?.body).includes('"decisao":"aprovar"'))).toBe(true);
    });
  });

  it("executor executa (202) e não vê aprovar", async () => {
    ME = { ...ME, role: "executor", username: "executor-ex" };
    crAtual = crDe(2, "aprovado");
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.queryByRole("button", { name: "Aprovar" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Executar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/change-requests/1/executar" && c[1]?.method === "POST")).toBe(true);
    });
  });

  it("não mostra aprovar/rejeitar para o próprio pedido", async () => {
    crAtual = crDe(1, "aguardando_aprovacao"); // ME.id = 1 é o solicitante
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.queryByRole("button", { name: "Aprovar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rejeitar" })).toBeNull();
  });
});
```

(Correção de ordem de declaração: `crAtual` e `CR_ATUAL` precisam ser definidos ANTES do `beforeAll` — mova-os para antes do bloco de stub se o linter reclamar de uso antes de declaração na ordem do arquivo; o stub lê `crAtual` em tempo de execução, então a ordem real de declarações no código acima é: `ME` → `circ/dev1/crBase/crDe` → stub `beforeAll` → `crAtual`/`CR_ATUAL` → `beforeEach` → render — esta ordem funciona porque `beforeAll` só roda depois de todo o corpo do módulo.)

- [ ] **Step 7: Rotas e navegação**

Em `web/src/App.tsx`:

- Importar após `BgpSessionDetail`:

```tsx
import ChangeRequests from "@/pages/ChangeRequests";
import ChangeRequestDetail from "@/pages/ChangeRequestDetail";
```

- Registrar após a rota `/bgp-sessions/:id` (linha 46):

```tsx
<Route path="/change-requests" element={<ChangeRequests />} />
<Route path="/change-requests/:id" element={<ChangeRequestDetail />} />
```

Em `web/src/components/Layout.tsx`, inserir entre o grupo "Coleta" e o grupo "Governança" da `GRUPOS_NAV`:

```tsx
  {
    rotulo: "Mudanças",
    itens: [{ para: "/change-requests", rotulo: "Change requests" }],
  },
```

- [ ] **Step 8: Rodar e verificar verde**

Run: `cd web && npm run test -- src/pages/ChangeRequests.test.tsx src/pages/ChangeRequestDetail.test.tsx`
Expected: PASS (3 + 3 testes). Se `findByText(/as-number 64512/)` falhar, o `<pre>` junta os comandos com `\n` em um único nó de texto — o regex de substring casa mesmo assim; se ainda falhar, use `screen.getByText((_, el) => el?.tagName === "PRE" && el.textContent?.includes("as-number 64512") ?? false)`. Se `getByLabelText("Status")` não resolver (duplicidade de "Status" no page), use `getByRole("combobox", { name: "Status" })`.

Para sanidade do build TS: `cd web && npm run build` (parte da verificação final T11, mas recomendo rodar aqui — pega erro de tipo dos espelhos antes de avançar).

- [ ] **Step 9: Commit**

```bash
git add web/src/api/types.ts web/src/api/hooks.ts web/src/pages/ChangeRequests.tsx web/src/pages/ChangeRequestDetail.tsx web/src/pages/ChangeRequests.test.tsx web/src/pages/ChangeRequestDetail.test.tsx web/src/App.tsx web/src/components/Layout.tsx
git commit -m "feat(web): páginas de change requests com ações por papel (ciclo D T9)"
```

### Task 10: Web — "Solicitar mudança" (detalhes) + card "Aprovações pendentes" (dashboard)

**Files:**
- Create: `web/src/components/SolicitarMudanca.tsx` (botão + dialog → POST → navega ao detalhe)
- Modify: `web/src/pages/CircuitDetail.tsx:30-32` (adicionar o botão ao `PageHeader acoes`)
- Modify: `web/src/pages/BgpSessionDetail.tsx:32` (idem)
- Modify: `web/src/pages/Dashboard.tsx` (card de aprovações pendentes na seção `health`)
- Modify: `web/src/pages/Dashboard.test.tsx` (stub de `change-requests?status=…` + asserção do novo card)
- Test: `web/src/components/SolicitarMudanca.test.tsx`

**Interfaces:**
- Consumes: `useChangeRequestCriar` (T9); `useChangeRequests({ status })` (T9); `useAuth().podeEscrever`; `BgpSessionOut.circuit_id` (sessão sempre pertence a um circuito — `CircuitDetailOut` idem); navegação `useNavigate` → `/change-requests/{id}`.
- Produces: componente `SolicitarMudanca({ circuit_id }: { circuit_id: number })` (exige cria a CR com aquele circuito e navega ao detalhe; auto-oculto para `visualizador`); card "mudanças aguardando aprovação" no dashboard (contagem de `GET /api/v1/change-requests?status=aguardando_aprovacao`, padrão dos cards `.metric` existentes — sem navegação, como os demais).

- [ ] **Step 1: Componente `web/src/components/SolicitarMudanca.tsx`**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useChangeRequestCriar } from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";

const FORM_VAZIO = {
  acao: "provision" as "provision" | "remove",
  criticidade: "media" as "baixa" | "media" | "alta",
  motivo: "",
  ticket: "",
};

export default function SolicitarMudanca({ circuit_id }: { circuit_id: number }) {
  const { podeEscrever } = useAuth();
  const navigate = useNavigate();
  const criar = useChangeRequestCriar();
  const [aberto, setAberto] = useState(false);
  const [form, setForm] = useState(FORM_VAZIO);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      const cr = await criar.mutateAsync({
        circuit_id,
        acao: form.acao,
        criticidade: form.criticidade,
        motivo: form.motivo,
        ticket: form.ticket || null,
      });
      setForm(FORM_VAZIO);
      setAberto(false);
      navigate(`/change-requests/${cr.id}`);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar a change request.");
    }
  }

  if (!podeEscrever) return null;

  return (
    <>
      <button
        className="primary"
        type="button"
        onClick={() => {
          setForm(FORM_VAZIO);
          setErro(null);
          setAberto(true);
        }}
      >
        Solicitar mudança
      </button>
      {aberto && (
        <Modal aberto titulo="Solicitar mudança" onFechar={() => setAberto(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <FormField label="Ação *">
              <select value={form.acao} onChange={(e) => setForm({ ...form, acao: e.target.value as "provision" | "remove" })}>
                <option value="provision">provision — aplicar configuração</option>
                <option value="remove">remove — remover configuração</option>
              </select>
            </FormField>
            <FormField label="Criticidade *">
              <select value={form.criticidade} onChange={(e) => setForm({ ...form, criticidade: e.target.value as "baixa" | "media" | "alta" })}>
                <option value="baixa">baixa</option>
                <option value="media">média</option>
                <option value="alta">alta</option>
              </select>
            </FormField>
            <FormField label="Motivo *">
              <textarea value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} required rows={3} />
            </FormField>
            <FormField label="Ticket">
              <input value={form.ticket} onChange={(e) => setForm({ ...form, ticket: e.target.value })} />
            </FormField>
            <div className="dialog-actions">
              <button type="button" onClick={() => setAberto(false)} disabled={criar.isPending}>
                Cancelar
              </button>
              <button className="primary" type="submit" disabled={criar.isPending}>
                {criar.isPending ? "Criando…" : "Criar"}
              </button>
            </div>
          </form>
          {erro && <p role="alert">{erro}</p>}
        </Modal>
      )}
    </>
  );
}
```

(Nota: as validações de papel que importam — aprovação/execução — ficam no detalhe da CR (T9); aqui o create é aberto a qualquer usuário autenticado que não seja visualizador, como no T9.)

- [ ] **Step 2: Teste do componente `web/src/components/SolicitarMudanca.test.tsx`**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import SolicitarMudanca from "./SolicitarMudanca";
import { AuthProvider } from "@/auth/auth-context";

let ME: Record<string, unknown> = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };

beforeEach(() => {
  ME = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };
});

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 9, ...body, status: "rascunho", solicitante_id: 1, rollback_de: null, created_at: "2026-09-05T10:00:00Z", steps: [], approvals: [] }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderSolicitar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/circuits/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/circuits/1" element={<SolicitarMudanca circuit_id={1} />} />
            <Route path="/change-requests/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SolicitarMudanca", () => {
  it("cria CR do circuito e navega ao detalhe", async () => {
    renderSolicitar();
    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança" }));
    await userEvent.type(screen.getByLabelText("Motivo *"), "Troca de banda do CIRC-01");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes('"circuit_id":1'))).toBe(true);
    });
    expect(await screen.findByText("detail-page")).toBeInTheDocument();
  });

  it("não aparece para visualizador", async () => {
    ME = { ...ME, role: "visualizador" };
    renderSolicitar();
    // waitFor com retry: enquanto o /auth/me resolve o botão não existe (gate de
    // escrita) — e, se o gate for removido, o botão aparece e o teste falha.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Solicitar mudança" })).toBeNull();
    });
  });
});
```

(use `vi.mocked(fetch)`/`waitFor` como nos testes C3; o `beforeEach` reseta o `ME` para o papel operador — o stub lê `ME` no momento da chamada.)

- [ ] **Step 3: Botões nos detalhes**

`web/src/pages/CircuitDetail.tsx`:

- Importar: `import SolicitarMudanca from "@/components/SolicitarMudanca";` (após os componentes existentes).
- Trocar o `PageHeader` (linhas 30-32):

```tsx
      <PageHeader
        titulo={`Circuito ${data.code}`}
        acoes={
          <>
            <Link to="/circuits">← Voltar</Link>
            <SolicitarMudanca circuit_id={data.id} />
          </>
        }
      />
```

`web/src/pages/BgpSessionDetail.tsx`:

- Importar `SolicitarMudanca`.
- Trocar a linha 32:

```tsx
      <PageHeader titulo={`Sessão BGP #${data.id}`} acoes={<SolicitarMudanca circuit_id={data.circuit_id} />} />
```

- [ ] **Step 4: Card no dashboard**

`web/src/pages/Dashboard.tsx`:

- Importar `useChangeRequests` junto de `useDashboard`:

```tsx
import { useChangeRequests, useDashboard } from "@/api/hooks";
```

- No corpo, junto de `const { data, isLoading, error } = useDashboard();`:

```tsx
  const { data: pendentes } = useChangeRequests({ status: "aguardando_aprovacao" });
```

- Inserir como último `.metric` da seção `health` (após o card "idade da última coleta", antes do `</section>`):

```tsx
            <div className="metric">
              <span className={`led ${(pendentes?.length ?? 0) > 0 ? "amber" : "gray"}`} aria-hidden="true" />
              <span className="val">{pendentes?.length ?? 0}</span>
              <span className="label">mudanças<br />aguardando aprovação</span>
            </div>
```

- [ ] **Step 5: Ajustar `web/src/pages/Dashboard.test.tsx`**

No stub de `fetch` do teste existente, acrescentar antes do fallback 404:

```tsx
        if (url === "/api/v1/change-requests?status=aguardando_aprovacao") {
          return new Response(
            JSON.stringify([
              { id: 1, circuit_id: 1, acao: "provision", criticidade: "media", motivo: "m1", ticket: null, solicitante_id: 1, status: "aguardando_aprovacao", rollback_de: null, created_at: "2026-09-05T10:00:00Z", steps: [], approvals: [] },
              { id: 2, circuit_id: 1, acao: "remove", criticidade: "alta", motivo: "m2", ticket: null, solicitante_id: 2, status: "aguardando_aprovacao", rollback_de: null, created_at: "2026-09-05T11:00:00Z", steps: [], approvals: [] },
            ]),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
```

E no final do `it(...)`, acrescentar:

```tsx
    expect(screen.getByText(/mudanças/)).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
```

(No teste existente, o número "2" ainda não é asserido em outro lugar — se colidir, restrinja com `screen.getByText("2").closest(".metric")` ou assevere `document.querySelector`. Se quiser evitar ambiguidade, troque para `expect(screen.getByText("mudanças")).toBeTruthy()` e confie no card; o `val` 2 vem do stub — verificação visual no e2e T11.)

- [ ] **Step 6: Rodar e verificar verde**

Run: `cd web && npm run test -- src/components/SolicitarMudanca.test.tsx src/pages/Dashboard.test.tsx`
Expected: PASS (2 + 1). Atenção: o `SolicitarMudanca` exige o `Modal` — o dialog renderiza em portal (`document.body`); os `getByLabelText` funcionam normalmente (padrão dos testes C3).

- [ ] **Step 7: Commit**

```bash
git add web/src/components/SolicitarMudanca.tsx web/src/components/SolicitarMudanca.test.tsx web/src/pages/CircuitDetail.tsx web/src/pages/BgpSessionDetail.tsx web/src/pages/Dashboard.tsx web/src/pages/Dashboard.test.tsx
git commit -m "feat(web): solicitar mudança nos detalhes + aprovações pendentes no dashboard (ciclo D T10)"
```

### Task 11: e2e do fluxo de mudança + verificação final + CLAUDE.md

**Files:**
- Modify: `web/e2e/setup.ts` (seedar usuário `e2e-aprovador`)
- Create: `web/e2e/change.spec.ts`
- Modify: `web/e2e/README.md` (seed + specs)
- Modify: `CLAUDE.md` (parágrafo "Web (ciclo D)" no "Estado do repositório")

**Interfaces:**
- Consumes: seed C2 idempotente (admin, site/device/org/circuito/prefix-auth); API com `X-Api-Key` (padrão do setup.ts); fluxo web T9/T10 completo; `require_papel`/`aprovador ≠ solicitante` (T5) — por isso o usuário `e2e-aprovador` no seed; `enqueue_change` (T7) enfileira sem worker → CR fica `executando` = "jobs fake" do spec §10.
- Produces: fumo e2e rerun-safe do fluxo completo; README + CLAUDE.md atualizados.

**Decisão de rerun-safety (importante):** o seed `ne8000-01` acumula sessões BGP entre execuções e `create_session` rejeita 2ª sessão `ipv4` ativa no mesmo equipamento (bgp_sessions.py:133) — então o fumo **cria equipamento, circuito e sessão próprios por execução** (códigos/endereços derivados de `Date.now()`); nada no fumo depende de estado de execuções anteriores além do seed base.

- [ ] **Step 1: Seedar o usuário aprovador em `web/e2e/setup.ts`**

Substituir o bloco "Usuário admin (CLI)" (`usuarioAdminExiste`/`criarUsuarioAdmin`) por:

```ts
function usuarioExiste(nome: string): boolean {
  const stdout = execSync("uv run gerenet users list", { env: process.env, encoding: "utf8" });
  return stdout
    .split("\n")
    .map((linha) => linha.trim().split(/\s+/))
    .some((campos) => campos[1] === nome);
}

function criarUsuario(nome: string, role: string): void {
  execSync(`uv run gerenet users create ${nome} --role ${role}`, {
    input: `${SENHA}\n${SENHA}\n`,
    env: process.env,
    encoding: "utf8",
    stdio: ["pipe", "pipe", "pipe"],
  });
}
```

E no `globalSetup`:

```ts
export default async function globalSetup(): Promise<void> {
  if (!usuarioExiste("admin")) {
    criarUsuario("admin", "administrador");
  }
  // Aprovador distinto do solicitante — o fumo de mudança solicita como admin
  // e aprova como e2e-aprovador (spec §3.3: não aprovar o próprio pedido).
  if (!usuarioExiste("e2e-aprovador")) {
    criarUsuario("e2e-aprovador", "aprovador");
  }
  await seed();
}
```

- [ ] **Step 2: Escrever `web/e2e/change.spec.ts`**

```ts
// Fumo do fluxo de mudança (ciclo D): equipamento+circuito+sessão novos (API)
// → solicitar pela UI → aprovar (outro usuário) → executar. Sem worker rodando
// ("jobs fake" do spec §10): o enqueue vai para a fila Redis e a CR fica
// `executando`. Rerun-safe: tudo derivado de Date.now().
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";
const API_KEY = process.env.GERENET_API_KEY ?? "dev-key-change-me";

const RODADA = Date.now();
const REDE = `10.99.${(RODADA % 200) + 10}`; // 10.99.10..209 por execução
const API = { "x-api-key": API_KEY, "content-type": "application/json" };

async function entrar(page: Page, usuario = "admin"): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuário").fill(usuario);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

async function sair(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("fluxo de mudança: criar, solicitar, aprovar e executar", async ({ page }) => {
  // 0. Admin entra e cria um equipamento novo via API (X-Api-Key, como o
  //    globalSetup) — evita o colidente "2ª sessão ipv4 no mesmo device"
  //    entre execuções (bgp_sessions.py:133).
  await entrar(page);
  const respSite = await page.request.get("/api/v1/sites", { headers: API });
  expect(respSite.ok()).toBeTruthy();
  const sites = (await respSite.json()) as { id: number; name: string }[];
  const idSite = sites.find((s) => s.name === "e2e-site-01")?.id ?? 0;
  expect(idSite).toBeGreaterThan(0);

  const nomeDevice = `e2e-ne-${RODADA}`;
  const respDev = await page.request.post("/api/v1/devices", {
    headers: API,
    data: {
      name: nomeDevice,
      management_address: `${REDE}.3`,
      vendor: "huawei",
      model: "NE8000M12",
      family: "NE8000",
      role: "edge",
      site_id: idSite,
    },
  });
  expect(respDev.status()).toBe(201);
  const idDevice = ((await respDev.json()) as { id: number }).id;
  expect(idDevice).toBeGreaterThan(0);

  // 1. Circuito novo pela UI (form de Circuitos)
  const codigo = `e2e-change-${RODADA}`;
  await page.getByRole("link", { name: "Circuitos" }).click();
  await expect(page).toHaveURL(/\/circuits/);
  await page.getByLabel("Código *").fill(codigo);
  await page.getByLabel("Organização *").selectOption({ label: "e2e-cliente-downstream" });
  await page.getByLabel("Site *").selectOption({ label: "e2e-site-01" });
  await page.getByLabel("Equipamento de acesso *").selectOption({ label: nomeDevice });
  await page.getByLabel("Porta de acesso *").fill("GE0/0/22");
  await page.getByLabel("Edge *").selectOption({ label: nomeDevice });
  await page.getByRole("button", { name: "Cadastrar" }).click();
  const linha = page.getByRole("row", { name: codigo });
  await expect(linha).toBeVisible();
  await linha.getByRole("link", { name: codigo }).click();
  await expect(page).toHaveURL(/\/circuits\/\d+/);
  const idCircuito = Number(page.url().match(/\/circuits\/(\d+)/)?.[1] ?? 0);
  expect(idCircuito).toBeGreaterThan(0);

  // 2. Sessão BGP via API — é ela que dá origem aos steps do plano
  //    (plan_provision itera as sessões do circuito, T3:903). Endereços
  //    únicos por execução (evita _colidente_par entre rodadas).
  const respSess = await page.request.post("/api/v1/bgp-sessions", {
    headers: API,
    data: {
      circuit_id: idCircuito,
      device_id: idDevice,
      afi: "ipv4",
      local_address: `${REDE}.1`,
      remote_address: `${REDE}.2`,
      asn_local: 64600,
      asn_remote: 65001,
      description: `e2e ${codigo}`,
    },
  });
  expect(respSess.status()).toBe(201);

  // 3. Solicitar a mudança no detalhe do circuito
  await page.reload();
  await page.getByRole("button", { name: "Solicitar mudança" }).click();
  const dialogo = page.getByRole("dialog");
  await dialogo.getByLabel("Motivo *").fill(`e2e ${codigo} — aplicar configuração`);
  await dialogo.getByRole("button", { name: "Criar" }).click();
  await expect(page).toHaveURL(/\/change-requests\/\d+/);
  const urlCr = page.url();
  const idCr = Number(page.url().match(/\/change-requests\/(\d+)/)?.[1] ?? 0);
  expect(idCr).toBeGreaterThan(0);
  // O diff por bloco renderiza (pelo menos um <details> com comandos)
  await expect(page.locator("details").first()).toBeVisible();

  // 4. Enviar para aprovação
  await page.getByRole("button", { name: "Enviar para aprovação" }).click();
  await expect(page.getByText("aguardando_aprovacao")).toBeVisible();

  // 5. Aprovador (usuário distinto) aprova — o admin não pode aprovar o
  //    próprio pedido (T5) e o botão nem aparece para ele.
  await sair(page);
  await entrar(page, "e2e-aprovador");
  await page.goto(urlCr);
  await page.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("aprovado")).toBeVisible();

  // 6. Admin (administrador = executor) executa; sem worker o job fica na
  //    fila e a CR permanece `executando`.
  await sair(page);
  await entrar(page);
  await page.goto(urlCr);
  await page.getByRole("button", { name: "Executar" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("executando")).toBeVisible();
});
```

(Notas: o log server da API pode reclamar da sessão `e2e ne-<ts>` sem `source_address` — validação de endereço aceita e o `description` é opcional; se a validação de `asn_local`/`asn_remote` vier a exigir os ASNs do device/org, os valores acima já batem com a organização seed `65001`. Se o `status` do device `e2e-ne-*` atrapalhar a coleta futura do layout, tanto faz — é um objeto do banco e2e.)

- [ ] **Step 3: Atualizar `web/e2e/README.md`**

- No bloco "O que o comando faz" → seed: acrescentar `e2e-aprovador` à lista (após o admin):

```md
  - usuários `admin` (`administrador`) e `e2e-aprovador` (`aprovador`) via
    `uv run gerenet users list`/`create` — senha `E2E_PASSWORD` no stdin;
```

- Na seção "Specs", acrescentar:

```md
- `change.spec.ts` — fluxo de mudança (ciclo D): cria equipamento/circuito/
  sessão BGP (API, rerun-safe), solicita a mudança pela UI no detalhe do
  circuito, envia para aprovação, aprova como `e2e-aprovador` (o admin não
  pode aprovar o próprio pedido) e executa como admin — sem worker, a CR
  fica `executando` com o job na fila Redis.
```

- [ ] **Step 4: Rodar os e2e**

```bash
# infra + banco dedicado (uma vez por máquina — ver README seção
# "Banco dedicado gerenet_e2e"; repetível depois)
docker compose up -d
docker compose exec db createdb -U gerenet gerenet_e2e 2>/dev/null || true
GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_e2e" \
  uv run alembic upgrade head
# porta 8000 livre (nada de uvicorn de dev rodando — reuseExistingServer: false)
cd web
GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_e2e" \
E2E_PASSWORD="e2e-super-8" npm run test:e2e
```

Expected: PASS (3 login + 2 smoke + 1 change = 6). Se o fumo novo falhar com 409 no POST da sessão, rode de novo (datas nunca se repetem — a não ser que o POST tenha falhado no meio e recriado na mesma rodada; nesse caso apenas rode o `delete` da CR/sessão órfã no `gerenet_e2e` ou crie outra execução). Atenção extra: o passo 6 deixa uma CR `executando` e um job na fila `gerenet-change` do Redis — os jobs ficam na fila (sem worker), não prejudicam execuções seguintes (dedup do enqueue é por `change_request_id` e cada rodada tem CR nova).

- [ ] **Step 5: Verificação completa**

```bash
uv run ruff check src tests
uv run pytest -q
cd web && npm run build && npm run test
```

Expected: ruff limpo; pytest PASS (toda a suíte: T1–T8 + anteriores); `tsc -b && vite build` sem erros; vitest PASS (incluindo os novos `ChangeRequests*`/`SolicitarMudanca`/Dashboard).

- [ ] **Step 6: Atualizar o "Estado do repositório" do `CLAUDE.md`**

Acrescentar ao bloco "Web (ciclo C3): …" (ou após), um parágrafo:

```md
- Ciclo D (fluxo de mudança controlada): change requests com máquina de
  estados (rascunho → aguardando_aprovacao → aprovado → executando →
  aplicado/com_divergencia/parcial/erro; rejeitado/cancelado), planos de
  provision/remoção gerados da SoT × última coleta, aprovação única com
  papel `aprovador`/`administrador` e aprovador ≠ solicitante, worker RQ na
  fila `gerenet-change` (lock por CR e por device, backup pré-mudança,
  re-diff na execução, pós-check `reconciliar_device`, classificação ao
  final), rollback como nova CR inversa, e web: páginas
  `/change-requests` (lista/detalhe com diff por bloco e botões por papel),
  "Solicitar mudança" nos detalhes de circuito/sessão e "Aprovações
  pendentes" no dashboard; e2e `web/e2e/change.spec.ts`.
```

- [ ] **Step 7: Commit**

```bash
git add web/e2e/setup.ts web/e2e/change.spec.ts web/e2e/README.md CLAUDE.md
git commit -m "docs(e2e): fumo do fluxo de mudança + estado do repositório (ciclo D T11)"
```

(Os demais commits por etapa ficam nas tasks T1–T10; este é o fechamento do ciclo.)
