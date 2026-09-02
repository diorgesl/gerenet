# gerenet Fase 1 (cortes 0–2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fundação do repositório **gerenet** + cadastro de devices + coleta read-only de `version` e backup de configuração, fim a fim, contra equipamento real Huawei.

**Architecture:** Monólito modular em camadas (src-layout, pacote `gerenet`): `domain` (SQLAlchemy + schemas Pydantic + serviços), `automation` (conexão Netmiko com host key validada, parsers TextFSM, runner de coleta), `worker` (fila RQ + locks Redis), `api` (FastAPI), `cli` (Typer). Dependências fluem `automation → domain → api`; `cli`/`worker` são portas de entrada do mesmo núcleo. Snapshot em JSONB; saída bruta em volume. Nornir entra no corte 5 (fan-out multi-device) — o `runner` é a fronteira que não muda; nos cortes 0–2 a conexão é Netmiko direto (fallback documentado na spec §12).

**Tech Stack:** Python 3.12 (uv), FastAPI, SQLAlchemy 2.0 + Alembic, PostgreSQL (JSONB), Redis + RQ, Netmiko, TextFSM, HashiCorp Vault (hvac), Typer, pytest, ruff.

**Spec:** [2026-09-02-gerenet-fase1-inventario-coleta-design.md](../specs/2026-09-02-gerenet-fase1-inventario-coleta-design.md) — implementa os cortes 0–2 (seções 3–7, 9 parcial, 11).

## Global Constraints

- Idioma de strings de usuário, mensagens de erro e docstrings: **PT-BR**. Identificadores de código em inglês.
- Nunca gravar credencial em banco, YAML, git ou logs; senhas vivem no Vault (`gerenet/credential-groups/<nome>`) (spec §5).
- Toda conexão valida host key do device; nenhum comando fora da allowlist `display *` (read-only) é executado.
- Fila: lock Redis por equipamento; segundo disparo com job pendente/ativo é recusado, sem duplicar (spec §6.3).
- Parsers em TextFSM com templates em `automation/parsers/huawei_vrp/textfsm/` desde o corte 2 (spec §6.2); fixtures reais sanitizadas.
- Python 3.12+, uv, ruff (line-length 100), pytest (TDD: teste falha → implementa → teste passa → commit).
- Todos os commits terminam com a linha `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- Infra dev (postgres/redis/vault) roda em `docker compose up -d`; app roda no host com `uv run` (iteração rápida + acesso à rede do lab). Portas: postgres 5432, redis 6379, vault 8200. Banco de teste: `gerenet_test` (JSONB exige postgres).
- CLI segue os nomes da spec §7: `gerenet devices add|list|disable`, `gerenet hostkey register`, `gerenet vault seed`, `gerenet collect run --device <id|nome>|--all`, `gerenet snapshot show <id> [--resource <nome>]`.

## Contratos centrais (assinaturas usadas por várias tasks)

```python
# gerenet/config.py — Settings (prefixo env GERENET_, lê .env):
#   database_url, redis_url, vault_url, vault_token, api_key, backups_dir: Path,
#   connect_timeout: float = 15.0, read_timeout: float = 60.0, lock_ttl_seconds: int = 300
#   get_settings() -> Settings            # respeita _override setado por set_settings(s) (testes)

# gerenet/db.py — Base(DeclarativeBase), engine, SessionLocal,
#   get_session()  (contextmanager; usado pelo CLI: `with get_session() as session:`)
#   get_db()       (generator p/ Depends do FastAPI — envolve get_session)

# gerenet/domain/models.py — Device, CredentialGroup, DeviceSnapshot, JobRun, AuditEvent
# gerenet/domain/schemas.py — DeviceCreate, DeviceUpdate, DeviceOut, SnapshotOut
# gerenet/domain/services/errors.py — GerenetError; NotFoundError; ConflictError (mensagens PT-BR)
# gerenet/domain/services/devices.py:
#   create_device(session, data: DeviceCreate) -> Device        (ConflictError se nome duplicado)
#   get_device(session, device_id: int) -> Device               (NotFoundError)
#   list_devices(session, include_disabled: bool = False) -> list[Device]
#   disable_device(session, device_id: int) -> Device
#   touch_collection(session, device, *, ok: bool, version: str|None = None, uptime: str|None = None)

# gerenet/automation/hostkeys.py — normalize_fingerprint(fp: str) -> str  (lowercase, sem espaços)
# gerenet/automation/netmiko_conn.py:
#   class HostKeyMismatch(Exception); class CommandNotAllowed(Exception); class ConnectionFailed(Exception)
#   connect_and_run(device, username, password, commands: list[str], settings) -> dict[str, str]
# gerenet/automation/parsers/huawei_vrp/registry.py:
#   parse_template(nome: str, output: str) -> list[dict]   # TextFSM do diretório textfsm/
# gerenet/automation/collectors.py — COLLECTORS: dict[str, dict]
#   # {"version": {"commands": ["display version"], "parser": "version", "backup": False},
#   #  "config_backup": {"commands": ["display current-configuration"], "parser": None, "backup": True}}
# gerenet/automation/runner.py:
#   run_collection(device_id: int, *, actor: str = "worker", origin: str = "rq",
#                  settings: Settings | None = None, session_override: Session | None = None) -> dict
#     # {"status": "success"|"partial"|"error", "snapshot_id": int|None, "error": str|None}
#     # adquire lock redis "gerenet:lock:device:<id>" (SET NX EX), grava job_runs/device_snapshots,
#     # brutos em <backups_dir>/<device>/<timestamp>/<recurso>/<cmd>.txt, atualiza o device
# gerenet/secrets/vault_store.py:
#   class VaultSecretStore: __init__(url: str, token: str)
#   def get_credential(self, vault_path: str) -> dict[str, str]  # {"username","password"}
#   def seed_dev(self, username: str, password: str) -> None     # escreve em gerenet/credential-groups/automacao
# gerenet/worker/tasks.py:
#   enqueue_collect(device_id: int, *, actor: str, origin: str) -> dict
#     # {"queued": bool, "message": str}; segunda chamada com job pendente/ativo -> queued False
#   collect_task(device_id: int) -> None        # função RQ; lê actor/origin do job.meta
#   worker_main() -> None                       # entrypoint gerenet-worker
# gerenet/api/main.py — create_app() -> FastAPI  (sem argumentos)
# gerenet/api/deps.py — require_api_key (X-API-Key, comparação constant-time)
# gerenet/cli/main.py — raiz typer "gerenet"; registra sub-apps conforme tasks 7–12
```

---

### Task 1: Scaffold do repositório (uv, git, healthz)

**Files:**
- Create: `pyproject.toml`, `README.md`
- Modify: `.gitignore`
- Create (vazios): `src/gerenet/__init__.py` e `src/gerenet/{api,domain,automation,worker,cli,secrets}/__init__.py`, `src/gerenet/domain/services/__init__.py`, `src/gerenet/api/routers/__init__.py`, `src/gerenet/automation/parsers/__init__.py`
- Create: `src/gerenet/api/main.py` (mínimo), `tests/test_healthz.py`

**Interfaces:**
- Consumes: nada (primeira task)
- Produces: projeto instalável (`uv run pytest` verde); app FastAPI `gerenet.api.main:create_app`

- [ ] **Step 1: Inicializar git e ajustar .gitignore**

```bash
cd /Users/diorgera/Projetos/BGP
git init -b main
```

Acrescentar ao final de `.gitignore`:

```gitignore
# app gerenet
data/
.claude/settings.local.json
.docker/
*.env
```

(`.claude/settings.local.json` contém token do harness — nunca versionar.)

- [ ] **Step 2: Criar pyproject.toml com uv**

```bash
uv init --bare --python 3.12 .
uv add "fastapi>=0.115" "uvicorn[standard]" "sqlalchemy>=2.0" "psycopg[binary]>=3.2" "alembic>=1.13" "pydantic>=2.9" "pydantic-settings>=2.5" "redis>=5" "rq>=1.16" "netmiko>=4.3" "hvac>=2.2" "typer>=0.12" "textfsm>=1.1.3"
uv add --dev pytest pytest-cov httpx "ruff>=0.6"
```

Se o `pyproject.toml` gerado não usar layout `src/`, ajustar para `[tool.setuptools] package-dir = {"" = "src"}` com `packages = ["gerenet"]`, e acrescentar:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[project.scripts]
gerenet = "gerenet.cli.main:app"
gerenet-worker = "gerenet.worker.tasks:worker_main"
```

- [ ] **Step 3: Criar pacote mínimo + teste que falha**

`src/gerenet/api/main.py`:

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="gerenet", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

`tests/test_healthz.py`:

```python
from fastapi.testclient import TestClient

from gerenet.api.main import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 4: Rodar e confirmar falha**

Run: `uv run pytest tests/test_healthz.py -v`
Expected: `ModuleNotFoundError: No module named 'gerenet'` (pacote ainda não instalado)

- [ ] **Step 5: Instalar e passar**

Run: `uv sync`  → depois `uv run pytest tests/test_healthz.py -v`
Expected: 1 passed

- [ ] **Step 6: README mínimo (PT-BR)**

`README.md`:

```markdown
# gerenet

Gerenciador de Rede Huawei VRP (spec: `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`).
Fase 1: inventário e coleta read-only.

## Desenvolvimento

- Infra: `docker compose up -d` (postgres, redis, vault dev)
- App: `cp .env.example .env`; `uv run uvicorn gerenet.api.main:create_app --factory --reload --port 8000`
- Testes: `uv run pytest`
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: scaffold gerenet (uv, pytest, healthz)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Infra dev no compose (postgres, redis, vault)

**Files:**
- Create: `compose.yaml`, `.env.example`

**Interfaces:**
- Consumes: Task 1
- Produces: `docker compose up -d` com `gerenet-db` (5432), `gerenet-redis` (6379), `gerenet-vault` (8200, root token `gerenet-dev-root`, KV v2 em `secret/`)

- [ ] **Step 1: Escrever compose.yaml**

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: gerenet-db
    environment:
      POSTGRES_USER: gerenet
      POSTGRES_PASSWORD: gerenet
      POSTGRES_DB: gerenet
    ports: ["5432:5432"]
    volumes: [db-data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gerenet"]
      interval: 2s
      timeout: 2s
      retries: 20

  redis:
    image: redis:7-alpine
    container_name: gerenet-redis
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 2s
      retries: 20

  vault:
    image: hashicorp/vault:1.17
    container_name: gerenet-vault
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: gerenet-dev-root
    ports: ["8200:8200"]
    cap_add: [IPC_LOCK]

volumes:
  db-data:
```

(O Vault dev ativa automaticamente o KV v2 no mount `secret/` — usado nas tasks 7 e 10.)

`.env.example`:

```bash
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet
GERENET_REDIS_URL=redis://localhost:6379/0
GERENET_VAULT_URL=http://localhost:8200
GERENET_VAULT_TOKEN=gerenet-dev-root
GERENET_API_KEY=trocar-em-producao
```

- [ ] **Step 2: Validar**

Run: `docker compose up -d && docker compose ps`
Expected: 3 containers healthy/up. Conferir Vault: `curl -s http://localhost:8200/v1/sys/health` retorna `"initialized":true`.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: infra dev (postgres, redis, vault) no compose

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Settings, engine e sessões do banco

**Files:**
- Create: `src/gerenet/config.py`, `src/gerenet/db.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: Task 1
- Produces: `Settings`/`get_settings()`/`set_settings()`, `Base`, `engine`, `SessionLocal`, `get_session()` (CLI) e `get_db()` (FastAPI)

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_config.py`:

```python
from gerenet.config import Settings


def test_settings_env_prefix() -> None:
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.connect_timeout == 15.0
    assert s.lock_ttl_seconds == 300
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar config.py e db.py**

`src/gerenet/config.py`:

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GERENET_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet"
    redis_url: str = "redis://localhost:6379/0"
    vault_url: str = "http://localhost:8200"
    vault_token: str = "gerenet-dev-root"
    api_key: str = "dev-key-change-me"
    backups_dir: Path = Path("data/backups")
    connect_timeout: float = 15.0
    read_timeout: float = 60.0
    lock_ttl_seconds: int = 300


_override: Settings | None = None


def set_settings(s: Settings) -> None:
    """Substitui os settings do processo (usado apenas nos testes)."""
    global _override
    _override = s


def get_settings() -> Settings:
    return _override if _override is not None else Settings()
```

`src/gerenet/db.py`:

```python
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gerenet.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


@contextmanager
def get_session() -> Iterator[Session]:
    """Sessão com commit/rollback automáticos — uso direto no CLI e internamente."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Dependency do FastAPI: entrega uma sessão por request."""
    with get_session() as session:
        yield session
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/test_config.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: settings e engine do banco

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Modelos (devices, credential_groups, device_snapshots, job_runs, audit_events) + migração Alembic

**Files:**
- Create: `src/gerenet/domain/models.py`, `tests/conftest.py`, `tests/domain/test_models.py`
- Create (gerado pelo alembic init): `alembic.ini`, `alembic/`
- Rewrite: `alembic/env.py`

**Interfaces:**
- Consumes: Tasks 2–3 (`Base`, `SessionLocal`, `get_session`)
- Produces: tabelas via `alembic upgrade head` (dbs `gerenet` e `gerenet_test`); fixture `db_session` + resets no conftest

- [ ] **Step 1: Escrever os modelos**

`src/gerenet/domain/models.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gerenet.db import Base

COMM_STATUS = ("unknown", "ok", "fail")
SNAPSHOT_STATUS = ("success", "partial", "error")
JOB_STATUS = ("queued", "running", "success", "partial", "error")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    management_address: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor: Mapped[str] = mapped_column(String(32), default="huawei", nullable=False)
    model: Mapped[str | None] = mapped_column(String(64))
    family: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(64))
    site: Mapped[str | None] = mapped_column(String(64))
    vrp_version: Mapped[str | None] = mapped_column(String(64))
    uptime: Mapped[str | None] = mapped_column(String(128))
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    comm_status: Mapped[str] = mapped_column(Enum(*COMM_STATUS, name="comm_status"), default="unknown", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    host_key_fingerprint: Mapped[str | None] = mapped_column(String(128))
    credential_group_id: Mapped[int | None] = mapped_column(ForeignKey("credential_groups.id"))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    credential_group: Mapped["CredentialGroup | None"] = relationship()
    snapshots: Mapped[list["DeviceSnapshot"]] = relationship(back_populates="device")


class CredentialGroup(Base):
    __tablename__ = "credential_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="tacacs_password", nullable=False)
    vault_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeviceSnapshot(Base):
    __tablename__ = "device_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Enum(*SNAPSHOT_STATUS, name="snapshot_status"), default="error", nullable=False)
    resources: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_files: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    device: Mapped[Device] = relationship(back_populates="snapshots")


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    origin: Mapped[str] = mapped_column(String(16), nullable=False)  # api | cli | rq
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="collect", nullable=False)
    status: Mapped[str] = mapped_column(Enum(*JOB_STATUS, name="job_status"), default="queued", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 2: Configurar Alembic e reescrever env.py**

```bash
uv run alembic init alembic
```

Substituir o conteúdo de `alembic/env.py` por:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from gerenet.config import get_settings
from gerenet.db import Base
from gerenet.domain import models  # noqa: F401 — registra as tabelas no metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Em `alembic.ini`, comentar/remover a linha `sqlalchemy.url = ...` do template (a URL vem do env.py).

- [ ] **Step 3: Gerar, aplicar e preparar o banco de teste**

Com o compose de pé (Task 2):

```bash
uv run alembic revision --autogenerate -m "initial tables"
uv run alembic upgrade head
docker compose exec -T db psql -U gerenet -d postgres -c "CREATE DATABASE gerenet_test" 2>/dev/null || true
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head
```

- [ ] **Step 4: Escrever o teste de round-trip + conftest**

`tests/conftest.py` (a variável de ambiente **antes** dos imports do `gerenet.db` — o engine é criado na importação):

```python
import os

os.environ.setdefault(
    "GERENET_DATABASE_URL",
    "postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test",
)

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from gerenet.config import Settings, set_settings
from gerenet.db import SessionLocal
from gerenet.domain import models  # noqa: F401


@pytest.fixture()
def db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _limpa_tabelas(db_session: Session) -> None:
    yield
    db_session.execute(
        text("TRUNCATE audit_events, job_runs, device_snapshots, devices, credential_groups RESTART IDENTITY CASCADE")
    )
    db_session.commit()


@pytest.fixture(autouse=True)
def _reseta_settings() -> None:
    yield
    set_settings(Settings())
```

(O conftest assume postgres do compose de pé em qualquer teste — rode `docker compose up -d` antes da suíte.)

`tests/domain/test_models.py`:

```python
from sqlalchemy.orm import Session

from gerenet.domain.models import CredentialGroup, Device


def test_device_roundtrip(db_session: Session) -> None:
    grupo = CredentialGroup(name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao")
    db_session.add(grupo)
    db_session.commit()

    dev = Device(name="r1-borda", management_address="10.0.0.1", credential_group_id=grupo.id)
    db_session.add(dev)
    db_session.commit()

    assert db_session.get(Device, dev.id).name == "r1-borda"
    assert db_session.get(CredentialGroup, grupo.id).vault_path.endswith("automacao")
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/domain/test_models.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: modelos iniciais + migração alembic

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Schemas e serviço de devices

**Files:**
- Create: `src/gerenet/domain/schemas.py`, `src/gerenet/domain/services/errors.py`, `src/gerenet/domain/services/devices.py`, `tests/domain/test_devices_service.py`

**Interfaces:**
- Consumes: Task 4 (modelos, `db_session`)
- Produces: `DeviceCreate/DeviceUpdate/DeviceOut/SnapshotOut`, `NotFoundError/ConflictError`, funções de serviço (Contratos centrais)

- [ ] **Step 1: Escrever o teste que falha**

`tests/domain/test_devices_service.py`:

```python
import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device, disable_device, get_device, list_devices
from gerenet.domain.services.errors import ConflictError, NotFoundError


def test_cria_lista_desativa_device(db_session: Session) -> None:
    dev = create_device(db_session, DeviceCreate(name="sw1-acesso", management_address="10.0.0.2", model="S6730"))
    assert dev.family is None
    assert list_devices(db_session) == [dev]

    dev2 = disable_device(db_session, dev.id)
    assert dev2.admin_status is False
    assert list_devices(db_session) == []  # desativado some da listagem padrão
    assert [d.name for d in list_devices(db_session, include_disabled=True)] == ["sw1-acesso"]


def test_nome_duplicado_vira_conflito(db_session: Session) -> None:
    create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.1"))
    with pytest.raises(ConflictError):
        create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.9"))


def test_get_device_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        get_device(db_session, 9999)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/domain/test_devices_service.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar schemas e serviço**

`src/gerenet/domain/schemas.py`:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    management_address: str
    vendor: str = "huawei"
    model: str | None = None
    family: str | None = None
    role: str | None = None
    site: str | None = None
    credential_group_id: int | None = None
    tags: list[str] = Field(default_factory=list)


class DeviceUpdate(BaseModel):
    admin_status: bool | None = None
    model: str | None = None
    family: str | None = None
    role: str | None = None
    site: str | None = None
    tags: list[str] | None = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    management_address: str
    vendor: str
    model: str | None
    family: str | None
    role: str | None
    site: str | None
    vrp_version: str | None
    comm_status: str
    admin_status: bool
    last_collected_at: datetime | None
    tags: list[str]


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    resources: dict
    errors: dict
    duration_ms: int
```

`src/gerenet/domain/services/errors.py`:

```python
class GerenetError(Exception):
    """Erro de domínio com mensagem amigável em PT-BR."""


class NotFoundError(GerenetError):
    pass


class ConflictError(GerenetError):
    pass
```

`src/gerenet/domain/services/devices.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError


def create_device(session: Session, data: DeviceCreate) -> models.Device:
    dev = models.Device(**data.model_dump())
    session.add(dev)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Já existe um equipamento com esse nome.") from exc
    session.refresh(dev)
    return dev


def get_device(session: Session, device_id: int) -> models.Device:
    dev = session.get(models.Device, device_id)
    if dev is None:
        raise NotFoundError(f"Equipamento {device_id} não encontrado.")
    return dev


def list_devices(session: Session, include_disabled: bool = False) -> list[models.Device]:
    stmt = select(models.Device).order_by(models.Device.name)
    if not include_disabled:
        stmt = stmt.where(models.Device.admin_status.is_(True))
    return list(session.scalars(stmt))


def disable_device(session: Session, device_id: int) -> models.Device:
    dev = get_device(session, device_id)
    dev.admin_status = False
    session.commit()
    return dev


def touch_collection(
    session: Session,
    device: models.Device,
    *,
    ok: bool,
    version: str | None = None,
    uptime: str | None = None,
) -> None:
    """Atualiza o estado de comunicação do device após uma coleta."""
    device.comm_status = "ok" if ok else "fail"
    device.consecutive_failures = 0 if ok else device.consecutive_failures + 1
    if ok:
        device.last_collected_at = datetime.now(timezone.utc)
        if version:
            device.vrp_version = version
        if uptime:
            device.uptime = uptime
    session.commit()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/domain/test_devices_service.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: schemas e serviço de devices

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: API — healthz, auth por API key, CRUD de devices

**Files:**
- Create: `src/gerenet/api/deps.py`, `src/gerenet/api/routers/devices.py`, `tests/api/test_devices_api.py`
- Rewrite: `src/gerenet/api/main.py`

**Interfaces:**
- Consumes: Tasks 4–5 (modelos, serviço, erros), `Settings.api_key`, `db.get_db`
- Produces: `/healthz`, `/api/v1/devices` CRUD com `X-API-Key`; 404/409 com mensagens do serviço

- [ ] **Step 1: Escrever o teste que falha**

`tests/api/test_devices_api.py`:

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


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_api_requer_chave(client: TestClient) -> None:
    resp = client.get("/api/v1/devices")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Chave de API ausente ou inválida."}


def test_crud_devices(client: TestClient) -> None:
    resp = client.post("/api/v1/devices", json={"name": "r2", "management_address": "10.0.0.3"}, headers=_auth())
    assert resp.status_code == 201
    dev_id = resp.json()["id"]

    lista = client.get("/api/v1/devices", headers=_auth())
    assert [d["name"] for d in lista.json()] == ["r2"]

    dup = client.post("/api/v1/devices", json={"name": "r2", "management_address": "10.0.0.4"}, headers=_auth())
    assert dup.status_code == 409
    assert "já existe" in dup.json()["detail"]

    inexistente = client.get("/api/v1/devices/9999", headers=_auth())
    assert inexistente.status_code == 404

    off = client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth())
    assert off.status_code == 200
    assert off.json()["admin_status"] is False
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/api/test_devices_api.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'gerenet.api.routers'`)

- [ ] **Step 3: Implementar**

`src/gerenet/api/deps.py`:

```python
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from gerenet.config import Settings, get_settings


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.")
```

`src/gerenet/api/routers/devices.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import DeviceCreate, DeviceOut, DeviceUpdate
from gerenet.domain.services import devices as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/api/v1/devices", tags=["devices"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[DeviceOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_devices(session, include_disabled=include_disabled)


@router.post("", response_model=DeviceOut, status_code=201)
def criar(data: DeviceCreate, session: SessionDep) -> object:
    try:
        return svc.create_device(session, data)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{device_id}", response_model=DeviceOut)
def detalhar(device_id: int, session: SessionDep) -> object:
    try:
        return svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{device_id}", response_model=DeviceOut)
def atualizar(device_id: int, data: DeviceUpdate, session: SessionDep) -> object:
    try:
        dev = svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(dev, campo, valor)
    if data.admin_status is False:
        dev.comm_status = "unknown"
    session.commit()
    session.refresh(dev)
    return dev
```

`src/gerenet/api/main.py` (substituir o conteúdo da Task 1 — mantém o factory `create_app()` que os testes da Task 1 usam):

```python
from fastapi import FastAPI

from gerenet.api.routers import devices


# uvicorn gerenet.api.main:create_app --factory
def create_app() -> FastAPI:
    app = FastAPI(title="gerenet", version="0.1.0")
    app.include_router(devices.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/api/test_devices_api.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: API de devices com auth por API key

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: SecretStore (Vault) + CLI `vault seed`

**Files:**
- Create: `src/gerenet/secrets/vault_store.py`, `src/gerenet/cli/main.py`, `src/gerenet/cli/vault.py`, `tests/test_secrets.py`

**Interfaces:**
- Consumes: Task 3 (`Settings`)
- Produces: `VaultSecretStore.get_credential/seed_dev`; comando `gerenet vault seed` (Vault dev do compose, KV v2 em `secret/`, caminho lógico `gerenet/credential-groups/automacao`)

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_secrets.py`:

```python
from gerenet.config import Settings
from gerenet.secrets.vault_store import VaultSecretStore

CAMINHO = "gerenet/credential-groups/automacao"


def test_seed_e_leitura_roundtrip() -> None:
    s = Settings(_env_file=None)
    store = VaultSecretStore(s.vault_url, s.vault_token)
    store.seed_dev(username="gerenet-auto", password="senha-teste")
    cred = store.get_credential(CAMINHO)
    assert cred == {"username": "gerenet-auto", "password": "senha-teste"}
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar**

`src/gerenet/secrets/vault_store.py`:

```python
import hvac


class VaultSecretStore:
    """Credenciais de grupos em Vault KV v2, caminho lógico gerenet/credential-groups/<nome>.

    O mount dev do compose é 'secret/' (KV v2): o hvac resolve o caminho
    'gerenet/credential-groups/automacao' para secret/data/gerenet/credential-groups/automacao.
    """

    def __init__(self, url: str, token: str) -> None:
        self._client = hvac.Client(url=url, token=token)
        if not self._client.is_authenticated():
            raise RuntimeError("Não foi possível autenticar no Vault (token inválido?).")

    def seed_dev(self, username: str, password: str) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path="gerenet/credential-groups/automacao",
            secret={"username": username, "password": password},
        )

    def get_credential(self, vault_path: str) -> dict[str, str]:
        resp = self._client.secrets.kv.v2.read_secret_version(path=vault_path)
        dados = resp["data"]["data"]
        return {"username": dados["username"], "password": dados["password"]}
```

`src/gerenet/cli/main.py` (nesta task só registra `vault`; tasks 8 e 11 acrescentam os demais sub-apps):

```python
import typer

from gerenet.cli import vault

app = typer.Typer(help="gerenet — Gerenciador de Rede Huawei VRP", no_args_is_help=True)
app.add_typer(vault.app, name="vault", help="Credenciais de automação no Vault.")
```

`src/gerenet/cli/vault.py`:

```python
import typer

from gerenet.config import get_settings
from gerenet.secrets.vault_store import VaultSecretStore

app = typer.Typer(help="Credenciais de automação no Vault.")


@app.command("seed")
def seed(
    username: str = typer.Option("gerenet-auto", help="Usuário da conta de automação."),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Senha da conta de automação."),
) -> None:
    """Grava a credencial do grupo 'automacao' no Vault (dev)."""
    s = get_settings()
    VaultSecretStore(s.vault_url, s.vault_token).seed_dev(username, password)
    typer.echo("Credencial gravada em gerenet/credential-groups/automacao.")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: 1 passed (vault do compose de pé). Se o mount do KV v2 não for `secret/`, ajustar `mount_point` nas chamadas hvac e registrar a divergência no commit.

- [ ] **Step 5: Validar CLI**

Run: `GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet vault seed --username gerenet-auto --password devpass`
Expected: `Credencial gravada em gerenet/credential-groups/automacao.`

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: SecretStore Vault + CLI vault seed

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Host keys (CLI `hostkey register`) e CLI `devices`

**Files:**
- Create: `src/gerenet/automation/hostkeys.py`, `src/gerenet/cli/hostkey.py`, `src/gerenet/cli/devices.py`, `tests/automation/test_hostkeys.py`
- Modify: `src/gerenet/cli/main.py` (registrar `devices` e `hostkey`)

**Interfaces:**
- Consumes: Tasks 4–5 (Device), Tasks 6–7 (padrão de CLI/settings)
- Produces: `normalize_fingerprint(str) -> str`; helper `resolver(session, device)` (por ID ou nome, inclui desativados) compartilhado pelos sub-comandos; comandos `gerenet devices add|list|disable` e `gerenet hostkey register <id|nome> <fingerprint>` (persiste em `Device.host_key_fingerprint` + `AuditEvent`)

- [ ] **Step 1: Escrever o teste que falha**

`tests/automation/test_hostkeys.py`:

```python
from sqlalchemy.orm import Session

from gerenet.automation.hostkeys import normalize_fingerprint
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


def test_normaliza_fingerprint() -> None:
    assert normalize_fingerprint("  SHA256:AbCdEf==  ") == "sha256:AbCdEf=="
    assert normalize_fingerprint("SHA256:abcdef==") == "sha256:abcdef=="


def test_registro_gera_audit(db_session: Session) -> None:
    from gerenet.domain.models import AuditEvent

    dev = create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.1"))
    dev.host_key_fingerprint = "sha256:xyz"
    evento = AuditEvent(type="hostkey.register", actor="cli", details={"device_id": dev.id, "fingerprint": "sha256:xyz"})
    db_session.add(evento)
    db_session.commit()
    assert db_session.get(AuditEvent, evento.id).type == "hostkey.register"
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/automation/test_hostkeys.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar**

`src/gerenet/automation/hostkeys.py`:

```python
def normalize_fingerprint(fingerprint: str) -> str:
    """Canonicaliza 'SHA256:AbC' / '  sha256:abc  ' para 'sha256:AbC'.

    Normaliza só o rótulo do esquema ('sha256:'). O corpo base64 preserva
    maiúsculas/minúsculas — ele é dado do hash e não pode ser alterado.
    """
    fp = fingerprint.strip()
    if ":" in fp:
        esquema, valor = fp.split(":", 1)
        return f"{esquema.strip().lower()}:{valor.strip()}"
    return fp
```

`src/gerenet/cli/devices.py` (define também o helper `resolver`, usado por `hostkey` e `collect`):

```python
import typer

from gerenet.db import get_session
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services import devices as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Cadastro e consulta de equipamentos.")


def resolver(session, device: str):
    """Devolve o equipamento (ativo ou não) por ID ou nome; None se não existir.

    Helper compartilhado dos sub-comandos que recebem '<id|nome>'
    (devices disable, hostkey register, collect run).
    """
    if device.isdigit():
        try:
            return svc.get_device(session, int(device))
        except NotFoundError:
            return None
    return next((d for d in svc.list_devices(session, include_disabled=True) if d.name == device), None)


@app.command("add")
def add(
    name: str = typer.Option(..., help="Nome único do equipamento."),
    address: str = typer.Option(..., "--address", help="Endereço de gerenciamento."),
    model: str | None = typer.Option(None, help="Modelo (ex.: NE8000-M8)."),
    family: str | None = typer.Option(None, help="Família (ex.: ne8000)."),
    role: str | None = typer.Option(None, help="Função (ex.: borda)."),
    site: str | None = typer.Option(None, help="Site/POP."),
) -> None:
    """Cadastra um equipamento Huawei."""
    with get_session() as session:
        try:
            dev = svc.create_device(
                session,
                DeviceCreate(name=name, management_address=address, model=model, family=family, role=role, site=site),
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Equipamento {dev.id} criado: {dev.name} ({dev.management_address})")


@app.command("list")
def listar(include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados.")) -> None:
    """Lista equipamentos cadastrados."""
    with get_session() as session:
        for dev in svc.list_devices(session, include_disabled=include_disabled):
            linha = f"{dev.id:>4}  {dev.name:<20} {dev.management_address:<16} {dev.comm_status}"
            typer.echo(linha)


@app.command("disable")
def disable(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Desativa um equipamento (mantém histórico e registro)."""
    with get_session() as session:
        dev = resolver(session, device)
        if dev is None:
            typer.echo("Equipamento não encontrado.", err=True)
            raise typer.Exit(1)
        svc.disable_device(session, dev.id)
    typer.echo(f"Equipamento {dev.name} desativado.")
```

`src/gerenet/cli/hostkey.py`:

```python
import typer

from gerenet.automation.hostkeys import normalize_fingerprint
from gerenet.cli.devices import resolver
from gerenet.db import get_session
from gerenet.domain.models import AuditEvent

app = typer.Typer(help="Host keys dos equipamentos.")


@app.command("register")
def register(
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
    fingerprint: str = typer.Argument(..., help="Fingerprint esperado (ex.: SHA256:abcd...)."),
) -> None:
    """Registra o fingerprint esperado (SHA-256) de um equipamento."""
    fp = normalize_fingerprint(fingerprint)
    with get_session() as session:
        dev = resolver(session, device)
        if dev is None:
            typer.echo("Equipamento não encontrado.", err=True)
            raise typer.Exit(1)
        dev.host_key_fingerprint = fp
        session.add(
            AuditEvent(
                type="hostkey.register",
                actor="cli",
                details={"device_id": dev.id, "fingerprint": fp},
            )
        )
    typer.echo(f"Host key registrada para {dev.name}.")
```

Em `src/gerenet/cli/main.py`, substituir os imports/registros por:

```python
import typer

from gerenet.cli import devices, hostkey, vault

app = typer.Typer(help="gerenet — Gerenciador de Rede Huawei VRP", no_args_is_help=True)
app.add_typer(devices.app, name="devices", help="Cadastro e consulta de equipamentos.")
app.add_typer(hostkey.app, name="hostkey", help="Host keys dos equipamentos.")
app.add_typer(vault.app, name="vault", help="Credenciais de automação no Vault.")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/automation/test_hostkeys.py -v`
Expected: 2 passed

- [ ] **Step 5: Validar CLI**

Run:

```bash
uv run gerenet devices add --name r1-lab --address 10.0.0.99
uv run gerenet hostkey register r1-lab SHA256:0000
uv run gerenet devices add --name sw1-lab --address 10.0.0.98
uv run gerenet devices disable sw1-lab
uv run gerenet devices list
```

Expected: r1-lab ativo com fingerprint `sha256:0000`; sw1-lab some da listagem após o `disable` (confirmação do fingerprint real entra na Task 13). r1-lab fica ativo para as tasks 11 e 13.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: host key fingerprint + CLI devices e hostkey

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: Conexão Netmiko com host key validada + allowlist

**Files:**
- Create: `src/gerenet/automation/netmiko_conn.py`, `tests/automation/test_netmiko_conn.py` (fakes — sem equipamento real)

**Interfaces:**
- Consumes: Task 8 (`normalize_fingerprint`)
- Produces: `connect_and_run(device, username, password, commands, settings) -> dict[str, str]`; erros `HostKeyMismatch`, `CommandNotAllowed`, `ConnectionFailed`

- [ ] **Step 1: Escrever o teste que falha**

`tests/automation/test_netmiko_conn.py`:

```python
import base64
import hashlib
from unittest.mock import MagicMock

import pytest

from gerenet.automation.netmiko_conn import (
    CommandNotAllowed,
    HostKeyMismatch,
    connect_and_run,
)
from gerenet.config import Settings

SETTINGS = Settings(_env_file=None)


def _fingerprint_de(bytes_chave: bytes) -> str:
    b64 = base64.b64encode(hashlib.sha256(bytes_chave).digest()).decode()
    return f"sha256:{b64}"


def _conexao_fake() -> MagicMock:
    conn = MagicMock()
    chave = MagicMock()
    chave.asbytes.return_value = b"chave-de-teste"
    conn.remote_conn.transport.get_remote_server_key.return_value = chave
    return conn


def test_recusa_comando_fora_da_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: _conexao_fake(),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    with pytest.raises(CommandNotAllowed):
        connect_and_run(dev, "u", "p", ["configure terminal"], SETTINGS)


def test_fingerprint_ausente_impede_conexao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: _conexao_fake(),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", None
    with pytest.raises(HostKeyMismatch):
        connect_and_run(dev, "u", "p", ["display version"], SETTINGS)


def test_fingerprint_divergente_impede_conexao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gerenet.automation.netmiko_conn.ConnectHandler",
        lambda **kwargs: _conexao_fake(),
    )
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", "sha256:outra=="
    with pytest.raises(HostKeyMismatch):
        connect_and_run(dev, "u", "p", ["display version"], SETTINGS)


def test_conecta_e_roda_com_host_key_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _conexao_fake()
    conn.send_command.return_value = "saida bruta"
    monkeypatch.setattr("gerenet.automation.netmiko_conn.ConnectHandler", lambda **kwargs: conn)
    dev = MagicMock()
    dev.name, dev.management_address, dev.host_key_fingerprint = "r1", "10.0.0.1", _fingerprint_de(b"chave-de-teste")
    saidas = connect_and_run(dev, "u", "p", ["display version"], SETTINGS)
    assert saidas == {"display version": "saida bruta"}
    conn.send_command.assert_called_once_with("display version", read_timeout=SETTINGS.read_timeout)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/automation/test_netmiko_conn.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar**

`src/gerenet/automation/netmiko_conn.py`:

```python
import base64
import hashlib
import re

from netmiko import ConnectHandler

from gerenet.automation.hostkeys import normalize_fingerprint

_ALLOWED_COMMAND = re.compile(r"^display\b")


class HostKeyMismatch(Exception):
    def __init__(self, device: str, actual: str) -> None:
        self.device = device
        self.actual = actual
        super().__init__(
            f"Host key de {device} não confere (recebido {actual}). Não conectando — "
            "registre o fingerprint correto com `gerenet hostkey register`."
        )


class CommandNotAllowed(Exception):
    pass


class ConnectionFailed(Exception):
    pass


def _fingerprint_do_servidor(conn) -> str | None:
    """SHA-256 base64 do host key recebido, no formato OpenSSH 'sha256:...'."""
    try:
        chave = conn.remote_conn.transport.get_remote_server_key()
        b64 = base64.b64encode(hashlib.sha256(chave.asbytes()).digest()).decode()
        return f"sha256:{b64}"
    except Exception:
        return None


def connect_and_run(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    """Conecta via Netmiko (huawei_vrp), valida host key e allowlist, executa comandos read-only."""
    if not device.host_key_fingerprint:
        raise HostKeyMismatch(
            device.name,
            "nenhum fingerprint registrado — use `gerenet hostkey register` antes de coletar",
        )
    for cmd in commands:
        if not _ALLOWED_COMMAND.match(cmd):
            raise CommandNotAllowed(f"Comando fora da allowlist read-only: {cmd!r}")

    try:
        conn = ConnectHandler(
            device_type="huawei_vrp",
            host=device.management_address,
            username=username,
            password=password,
            conn_timeout=settings.connect_timeout,
        )
    except Exception as exc:
        raise ConnectionFailed(f"Não foi possível conectar em {device.name}: {exc}") from exc

    try:
        actual = _fingerprint_do_servidor(conn)
        if actual is not None and actual != normalize_fingerprint(device.host_key_fingerprint):
            raise HostKeyMismatch(device.name, actual)
        saidas: dict[str, str] = {}
        for cmd in commands:
            saidas[cmd] = conn.send_command(cmd, read_timeout=settings.read_timeout)
        return saidas
    except HostKeyMismatch:
        raise
    except Exception as exc:
        raise ConnectionFailed(f"Falha ao executar comandos em {device.name}: {exc}") from exc
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/automation/test_netmiko_conn.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: conexão netmiko com host key sha256 e allowlist

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: Parser TextFSM de `version` + runner de coleta (version + config backup)

**Files:**
- Create: `src/gerenet/automation/collectors.py`, `src/gerenet/automation/parsers/huawei_vrp/__init__.py`, `src/gerenet/automation/parsers/huawei_vrp/textfsm/version.template`, `src/gerenet/automation/parsers/huawei_vrp/registry.py`, `src/gerenet/automation/runner.py`, `tests/automation/test_runner.py`

**Interfaces:**
- Consumes: Tasks 4–5, 7, 9 (`connect_and_run`, `VaultSecretStore`, serviços e modelos)
- Produces: `COLLECTORS`, `parse_template("version", saida) -> list[dict]`, `run_collection(...)` conforme Contratos centrais; brutos em `data/backups/<device>/<timestamp>/<recurso>/<cmd>.txt`

- [ ] **Step 1: Escrever o teste que falha**

`tests/automation/test_runner.py`:

```python
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from gerenet.automation.netmiko_conn import ConnectionFailed
from gerenet.automation.runner import run_collection
from gerenet.config import Settings
from gerenet.domain.models import CredentialGroup, DeviceSnapshot, JobRun
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

VERSION_SAIDA = """Huawei Versatile Routing Platform Software
VRP (R) software, Version 8.210 (NE8000 V200R021C10SPC600)
Copyright (c) 2012-2019 Huawei Technologies Co., Ltd.
Huawei NE8000 uptime is 5 days, 2 hours, 10 minutes
"""

# Saídas que o fake de conexão devolve, por comando — como o connect_and_run real,
# que só devolve o que recebeu na lista `commands`.
SAIDAS = {
    "display version": VERSION_SAIDA,
    "display current-configuration": "sysname r1\n#\n",
}


class VaultFake:
    """Substitui o VaultSecretStore no teste — nunca tocar o Vault real aqui."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _dev_com_grupo(db_session: Session, nome: str, endereco: str):
    grupo = CredentialGroup(name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao")
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(db_session, DeviceCreate(name=nome, management_address=endereco, credential_group_id=grupo.id))
    dev.host_key_fingerprint = "sha256:fake"
    db_session.commit()
    return dev


def test_coleta_version_atualiza_device_e_snapshot(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r1", "10.0.0.1")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    db_session.refresh(dev)
    assert dev.comm_status == "ok"
    assert dev.vrp_version == "8.210"
    assert dev.uptime == "5 days, 2 hours, 10 minutes"
    assert dev.last_collected_at is not None

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    assert snap is not None
    assert snap.status == "success"
    assert snap.resources["version"]["version"] == "8.210"
    assert snap.resources["config_backup"]["backup"] is True
    assert len(snap.raw_files["version"]) == 1
    assert len(snap.raw_files["config_backup"]) == 1
    assert sorted(p.name for p in tmp_path.glob("r1/*/version/*.txt")) == ["version.txt"]

    job_row = db_session.query(JobRun).filter_by(device_id=dev.id).first()
    assert job_row is not None
    assert job_row.status == "success"
    assert job_row.snapshot_id == snap.id


def test_falha_de_conexao_marca_device_como_fail(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r2", "10.0.0.2")

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)

    def _falha(device, username, password, commands, settings):
        raise ConnectionFailed("host inacessível")

    monkeypatch.setattr("gerenet.automation.runner._conectar_e_executar", _falha)
    resultado = run_collection(
        dev.id, settings=Settings(_env_file=None, backups_dir=Path("/tmp")), session_override=db_session
    )
    assert resultado["status"] == "error"
    db_session.refresh(dev)
    assert dev.comm_status == "fail"
    assert dev.consecutive_failures == 1
```

Obs.: o segundo teste precisa do grupo de credencial para exercer de verdade o caminho de `ConnectionFailed` (status error, `comm_status=fail`); sem grupo, o runner falharia antes de conectar e não atualizaria o device.

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/automation/test_runner.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar catálogo, parser TextFSM e runner**

`src/gerenet/automation/collectors.py`:

```python
# Catálogo de coletores read-only. parser None = recurso bruto sem parse estruturado.
COLLECTORS: dict[str, dict] = {
    "version": {"commands": ["display version"], "parser": "version", "backup": False},
    "config_backup": {"commands": ["display current-configuration"], "parser": None, "backup": True},
}
```

`src/gerenet/automation/parsers/huawei_vrp/textfsm/version.template`:

```
Value Required version (\S+)
Value uptime (.+)

Start
  ^VRP \(R\) software, Version ${version}
  ^.* uptime is ${uptime} -> Record
```

`src/gerenet/automation/parsers/huawei_vrp/registry.py`:

```python
from pathlib import Path

import textfsm

_TEMPLATES = Path(__file__).parent / "textfsm"


def parse_template(nome: str, output: str) -> list[dict]:
    """Executa o template TextFSM <nome>.template e devolve as linhas como dicts."""
    with (_TEMPLATES / f"{nome}.template").open(encoding="utf-8") as arquivo:
        fsm = textfsm.TextFSM(arquivo)
    return [dict(zip(fsm.header, linha)) for linha in fsm.ParseText(output)]
```

`src/gerenet/automation/runner.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation.collectors import COLLECTORS
from gerenet.automation.netmiko_conn import connect_and_run
from gerenet.automation.parsers.huawei_vrp.registry import parse_template
from gerenet.config import Settings, get_settings
from gerenet.db import SessionLocal
from gerenet.domain.models import AuditEvent, DeviceSnapshot, JobRun
from gerenet.domain.services import devices as device_svc
from gerenet.secrets.vault_store import VaultSecretStore


def _conectar_e_executar(device, username: str, password: str, commands: list[str], settings) -> dict[str, str]:
    return connect_and_run(device, username, password, commands, settings)


def _nome_do_arquivo(comando: str) -> str:
    partes = comando.split()
    return partes[1] if len(partes) > 1 else "output"


def run_collection(
    device_id: int,
    *,
    actor: str = "worker",
    origin: str = "rq",
    settings: Settings | None = None,
    session_override: Session | None = None,
) -> dict:
    settings = settings or get_settings()
    session = session_override or SessionLocal()
    job: JobRun | None = None
    snapshot: DeviceSnapshot | None = None

    redis = Redis.from_url(settings.redis_url)
    chave_lock = f"gerenet:lock:device:{device_id}"
    if not redis.set(chave_lock, "1", nx=True, ex=settings.lock_ttl_seconds):
        redis.close()
        return {"status": "error", "snapshot_id": None, "error": "Equipamento já está sendo coletado (lock ativo)."}
    try:
        dev = device_svc.get_device(session, device_id)
        grupo = dev.credential_group
        if grupo is None:
            raise ValueError(f"{dev.name} não possui grupo de credencial.")

        job = JobRun(device_id=dev.id, actor=actor, origin=origin, kind="collect", status="running")
        session.add(job)
        session.commit()

        cred = VaultSecretStore(settings.vault_url, settings.vault_token).get_credential(grupo.vault_path)

        inicio = datetime.now(timezone.utc)
        snapshot = DeviceSnapshot(device_id=dev.id, status="error")
        session.add(snapshot)
        session.commit()

        base = settings.backups_dir / dev.name / inicio.strftime("%Y%m%dT%H%M%S")
        erros: dict[str, str] = {}
        recursos: dict[str, object] = {}
        arquivos_brutos: dict[str, list[str]] = {}
        for nome, spec in COLLECTORS.items():
            try:
                saidas = _conectar_e_executar(dev, cred["username"], cred["password"], spec["commands"], settings)
                lista_arquivos: list[str] = []
                for comando, saida in saidas.items():
                    caminho = base / nome / f"{_nome_do_arquivo(comando)}.txt"
                    caminho.parent.mkdir(parents=True, exist_ok=True)
                    caminho.write_text(saida, encoding="utf-8")
                    lista_arquivos.append(str(caminho))
                arquivos_brutos[nome] = lista_arquivos
                if spec["parser"]:
                    linhas = parse_template(spec["parser"], saidas[spec["commands"][0]])
                    recursos[nome] = linhas[0] if linhas else {"erro": "Saída sem registros parseáveis."}
                else:
                    recursos[nome] = {"backup": True}
            except Exception as exc:  # HostKeyMismatch, ConnectionFailed, falha de parse etc.
                erros[nome] = str(exc)

        snapshot.finished_at = datetime.now(timezone.utc)
        snapshot.duration_ms = int((snapshot.finished_at - inicio).total_seconds() * 1000)
        snapshot.resources = recursos
        snapshot.errors = erros
        snapshot.raw_files = arquivos_brutos
        snapshot.status = "success" if not erros else ("error" if not recursos else "partial")

        versao = recursos.get("version")
        device_svc.touch_collection(
            session,
            dev,
            ok=bool(recursos),
            version=versao.get("version") if isinstance(versao, dict) else None,
            uptime=versao.get("uptime") if isinstance(versao, dict) else None,
        )

        job.status = snapshot.status
        job.finished_at = snapshot.finished_at
        job.duration_ms = snapshot.duration_ms
        job.snapshot_id = snapshot.id
        session.commit()

        if erros:
            session.add(
                AuditEvent(type="collect.errors", actor=actor, details={"device_id": dev.id, "errors": erros})
            )
            session.commit()

        return {"status": snapshot.status, "snapshot_id": snapshot.id}
    except Exception as exc:
        if job is not None:
            job.status = "error"
            job.finished_at = datetime.now(timezone.utc)
            session.commit()
        return {"status": "error", "snapshot_id": snapshot.id if snapshot else None, "error": str(exc)}
    finally:
        redis.delete(chave_lock)  # no-op se o lock nunca foi adquirido
        redis.close()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/automation/test_runner.py -v`
Expected: 2 passed (redis do compose de pé — o runner toma o lock)

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: parser TextFSM version + runner de coleta com snapshot

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: Fila RQ com lock por equipamento + CLI `collect`/`snapshot`

**Files:**
- Create: `src/gerenet/worker/tasks.py`, `src/gerenet/cli/collect.py`, `src/gerenet/cli/snapshot.py`, `tests/worker/test_tasks.py`
- Modify: `src/gerenet/cli/main.py` (registrar `collect` e `snapshot`)

**Interfaces:**
- Consumes: Task 10 (`run_collection`), Task 4 (`JobRun`)
- Produces: `enqueue_collect(device_id, *, actor, origin) -> dict` (dedupe de pendente/ativo), `collect_task(device_id)`, `worker_main()`; comandos `gerenet collect run --device <id|nome>|--all` e `gerenet snapshot show <id> [--resource <nome>]`

- [ ] **Step 1: Escrever o teste que falha**

`tests/worker/test_tasks.py`:

```python
import pytest
from redis import Redis
from rq import Queue

from gerenet.config import Settings
from gerenet.worker.tasks import enqueue_collect


@pytest.fixture()
def fila_limpa() -> Redis:
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    fila = Queue("gerenet-collect", connection=r)
    fila.empty()  # limpa antes e depois: a suíte não deixa jobs órfãos p/ o worker dev
    r.delete("gerenet:lock:device:1")
    yield r
    fila.empty()


def test_nao_duplica_job_pendente(fila_limpa: Redis) -> None:
    q = Queue("gerenet-collect", connection=fila_limpa)
    primeiro = enqueue_collect(1, actor="cli", origin="cli")
    assert primeiro["queued"] is True

    segundo = enqueue_collect(1, actor="cli", origin="cli")
    assert segundo["queued"] is False
    assert "pendente" in segundo["message"]
    assert q.count == 1
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/worker/test_tasks.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar**

`src/gerenet/worker/tasks.py`:

```python
from redis import Redis
from rq import Queue, get_current_job

from gerenet.automation.runner import run_collection
from gerenet.config import Settings, get_settings


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url)


def enqueue_collect(device_id: int, *, actor: str, origin: str) -> dict:
    settings = get_settings()
    r = _redis(settings)
    chave_lock = f"gerenet:lock:device:{device_id}"
    if r.get(chave_lock):
        return {"queued": False, "message": "Já existe uma coleta em andamento para este equipamento."}

    q = Queue("gerenet-collect", connection=r)
    pendentes = list(q.job_ids) + list(q.started_job_registry.get_job_ids())
    for job_id in pendentes:
        job = q.fetch_job(job_id)
        if job is not None and job.args and job.args[0] == device_id:
            return {"queued": False, "message": "Já existe uma coleta pendente para este equipamento."}

    job = q.enqueue(
        collect_task,
        device_id,
        job_timeout=600,
        result_ttl=3600,
        meta={"actor": actor, "origin": origin},
    )
    # job_id = id do job RQ; o job_runs no banco é criado pelo runner ao executar
    return {"queued": True, "job_id": job.id, "message": "Coleta enfileirada."}


def collect_task(device_id: int) -> None:
    """Executada pelo worker; actor/origin chegam pelo job.meta."""
    job = get_current_job()
    meta = job.meta if job is not None else {}
    run_collection(device_id, actor=meta.get("actor", "worker"), origin=meta.get("origin", "rq"))


def worker_main() -> None:
    from rq.worker import Worker

    settings = get_settings()
    with _redis(settings) as r:
        Worker(["gerenet-collect"], connection=r).work()
```

(O lock do `run_collection` é o mesmo `gerenet:lock:device:<id>` checado aqui — dois workers nunca coletam o mesmo device.)

`src/gerenet/cli/collect.py` (o `resolver` é o helper definido na Task 8 em `cli/devices.py`):

```python
import typer

from gerenet.cli.devices import resolver
from gerenet.db import get_session
from gerenet.domain.services import devices as svc
from gerenet.worker.tasks import enqueue_collect

app = typer.Typer(help="Coleta read-only.")


@app.command("run")
def run(
    device: str | None = typer.Option(None, "--device", help="ID ou nome do equipamento."),
    todos: bool = typer.Option(False, "--all", help="Enfileira coleta de todos os equipamentos ativos."),
) -> None:
    """Dispara coleta read-only via fila (1 job por equipamento)."""
    with get_session() as session:
        if todos:
            alvos = svc.list_devices(session)
            if not alvos:
                typer.echo("Nenhum equipamento ativo cadastrado.")
                raise typer.Exit(1)
        else:
            if device is None:
                typer.echo("Informe --device <id|nome> ou --all.", err=True)
                raise typer.Exit(2)
            alvo = resolver(session, device)
            alvos = [] if alvo is None else [alvo]
            if not alvos:
                typer.echo("Equipamento não encontrado.", err=True)
                raise typer.Exit(1)
        for dev in alvos:
            if not dev.admin_status:
                typer.echo(f"{dev.name}: desativado — reative antes de coletar.")
                continue
            resultado = enqueue_collect(dev.id, actor="cli", origin="cli")
            typer.echo(f"{dev.name}: {resultado['message']}")
```

`src/gerenet/cli/snapshot.py`:

```python
import typer

from gerenet.db import get_session
from gerenet.domain.models import DeviceSnapshot

app = typer.Typer(help="Snapshots de coleta.")


@app.command("show")
def show(
    snapshot_id: int = typer.Argument(..., help="ID do snapshot."),
    recurso: str | None = typer.Option(None, "--resource", help="Mostra só um recurso."),
) -> None:
    """Exibe um snapshot (resumo ou um recurso específico)."""
    with get_session() as session:
        snap = session.get(DeviceSnapshot, snapshot_id)
        if snap is None:
            typer.echo("Snapshot não encontrado.", err=True)
            raise typer.Exit(1)
        if recurso:
            typer.echo(snap.resources.get(recurso))
            return
        typer.echo(f"#{snap.id} device={snap.device_id} status={snap.status} duração={snap.duration_ms}ms")
        typer.echo("Recursos: " + ", ".join(snap.resources.keys()))
        typer.echo("Brutos: " + ", ".join(str(p) for ps in snap.raw_files.values() for p in ps))
```

Em `src/gerenet/cli/main.py`, acrescentar imports e registros:

```python
from gerenet.cli import collect, devices, hostkey, snapshot, vault
...
app.add_typer(collect.app, name="collect", help="Coleta read-only.")
app.add_typer(snapshot.app, name="snapshot", help="Snapshots de coleta.")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/worker/test_tasks.py -v`
Expected: 1 passed (redis do compose de pé)

- [ ] **Step 5: Validar CLI + worker encadeados**

Run (terminal A): `GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet-worker`
Run (terminal B): `uv run gerenet collect run --device r1-lab`  (r1-lab veio da Task 8; ainda sem grupo de credencial)
Expected: CLI responde "Coleta enfileirada." Com o worker ativo, conferir no banco dev:

Run: `docker compose exec -T db psql -U gerenet -d gerenet -c "select id, device_id, status from job_runs order by id desc limit 3;"`
Expected: job do r1-lab com status `error` — sem grupo de credencial o runner falha antes do Vault/Netmiko; nenhuma conexão ao device é tentada. Confirma o encadeamento CLI → fila → worker → runner; o fluxo completo contra device real é a Task 13.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: fila RQ com dedupe + CLI collect e snapshot

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: Endpoints de coleta e snapshots na API

**Files:**
- Modify: `src/gerenet/api/routers/devices.py` e `src/gerenet/api/main.py`
- Create: `tests/api/test_collect_api.py`

**Interfaces:**
- Consumes: Tasks 6 (router), 10 (`DeviceSnapshot`), 11 (`enqueue_collect`), Task 5 (`SnapshotOut`)
- Produces: `POST /api/v1/devices/{id}/collect` (202/409/404), `GET /api/v1/devices/{id}/snapshots`, `GET /api/v1/snapshots/{id}`

- [ ] **Step 1: Escrever o teste que falha**

`tests/api/test_collect_api.py`:

```python
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.models import CredentialGroup, DeviceSnapshot
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_dispara_coleta_202(client: TestClient, db_session) -> None:
    dev = create_device(db_session, DeviceCreate(name="r3", management_address="10.0.0.5"))
    with patch(
        "gerenet.api.routers.devices.enqueue_collect",
        return_value={"queued": True, "message": "Coleta enfileirada."},
    ) as enfileirar:
        resp = client.post(f"/api/v1/devices/{dev.id}/collect", headers=_auth())
    assert resp.status_code == 202
    assert resp.json()["queued"] is True
    enfileirar.assert_called_once_with(dev.id, actor="api", origin="api")


def test_coleta_de_device_inexistente_da_404(client: TestClient) -> None:
    with patch("gerenet.api.routers.devices.enqueue_collect") as enfileirar:
        resp = client.post("/api/v1/devices/9999/collect", headers=_auth())
    assert resp.status_code == 404
    enfileirar.assert_not_called()


def test_snapshots_lista_e_detalhe(client: TestClient, db_session) -> None:
    grupo = CredentialGroup(name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao")
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(db_session, DeviceCreate(name="r4", management_address="10.0.0.6", credential_group_id=grupo.id))
    snap = DeviceSnapshot(device_id=dev.id, status="success", resources={"version": {"version": "8.210"}})
    db_session.add(snap)
    db_session.commit()

    lista = client.get(f"/api/v1/devices/{dev.id}/snapshots", headers=_auth())
    assert lista.status_code == 200
    assert [s["id"] for s in lista.json()] == [snap.id]

    detalhe = client.get(f"/api/v1/snapshots/{snap.id}", headers=_auth())
    assert detalhe.status_code == 200
    assert detalhe.json()["status"] == "success"

    assert client.get("/api/v1/snapshots/9999", headers=_auth()).status_code == 404
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `uv run pytest tests/api/test_collect_api.py -v`
Expected: FAIL (rotas não existem → 404/405)

- [ ] **Step 3: Implementar**

Em `src/gerenet/api/routers/devices.py`, acrescentar imports e as rotas de coleta e snapshots. As duas rotas de snapshot vivem num router próprio (`/api/v1/snapshots`) no mesmo módulo; a rota de coleta fica no router de devices existente.

Acrescentar ao topo de `src/gerenet/api/routers/devices.py`:

```python
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, DeviceOut, DeviceUpdate, SnapshotOut
from gerenet.worker.tasks import enqueue_collect

snap_router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"], dependencies=[Depends(require_api_key)])
```

No router `devices`, após o PATCH existente:

```python
@router.post("/{device_id}/collect", status_code=202)
def coletar(device_id: int, session: SessionDep) -> dict:
    try:
        svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    resultado = enqueue_collect(device_id, actor="api", origin="api")
    if not resultado["queued"]:
        raise HTTPException(status_code=409, detail=resultado["message"])
    return resultado


@router.get("/{device_id}/snapshots", response_model=list[SnapshotOut])
def snapshots_do_device(device_id: int, session: SessionDep, limit: int = 20) -> list:
    try:
        svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    stmt = (
        select(models.DeviceSnapshot)
        .where(models.DeviceSnapshot.device_id == device_id)
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(min(max(limit, 1), 100))
    )
    return list(session.scalars(stmt))
```

No router `snap_router` (mesmo módulo):

```python
@snap_router.get("/{snapshot_id}", response_model=SnapshotOut)
def detalhe_snapshot(snapshot_id: int, session: SessionDep) -> object:
    snap = session.get(models.DeviceSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot não encontrado.")
    return snap
```

Em `src/gerenet/api/main.py`, registrar o segundo router no factory (mantém o `/healthz` e o `create_app()` usados nos testes da Task 1):

```python
from fastapi import FastAPI

from gerenet.api.routers import devices


# uvicorn gerenet.api.main:create_app --factory
def create_app() -> FastAPI:
    app = FastAPI(title="gerenet", version="0.1.0")
    app.include_router(devices.router)
    app.include_router(devices.snap_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/api/test_collect_api.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: endpoints de coleta e snapshots na API

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 13: Validação fim a fim contra equipamento real (NE8000, read-only)

**Files:**
- Create: `tests/fixtures/huawei_vrp/ne8000_display_version.txt` (captura real sanitizada)
- Create: `tests/automation/test_parsers_golden.py`
- Modify: `src/gerenet/automation/parsers/huawei_vrp/textfsm/version.template` (apenas se a saída real divergir)

**Interfaces:**
- Consumes: Tasks 1–12
- Produces: Fase 1 (cortes 0–2) validada contra equipamento real; fixture golden versionada

- [ ] **Step 1: Capturar saída real (manual, read-only)**

Em um NE8000 real (ou homologação), executar manualmente e salvar o resultado de:

```bash
display version
```

Salvar em `tests/fixtures/huawei_vrp/ne8000_display_version.txt`. **Revisar o conteúdo antes de versionar** para remover qualquer dado sensível (o `display version` não traz configuração — confira mesmo assim).

- [ ] **Step 2: Escrever teste golden com a captura real**

`tests/automation/test_parsers_golden.py`:

```python
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.registry import parse_template

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_version.txt")


def test_parse_version_contra_captura_real() -> None:
    saida = FIXTURE.read_text(encoding="utf-8")
    linhas = parse_template("version", saida)
    assert len(linhas) == 1
    assert linhas[0]["version"]  # versão VRP identificada
    assert linhas[0]["uptime"]
```

- [ ] **Step 3: Registrar device, host key e credencial (manual)**

```bash
# fingerprint real (SSH-2 RSA key, formato sha256 do OpenSSH):
ssh-keyscan -t rsa <ip-mgmt> 2>/dev/null | ssh-keygen -lf -E sha256 -   # anotar "SHA256:..."
uv run gerenet devices add --name <nome> --address <ip-mgmt> --family ne8000 --role borda
uv run gerenet hostkey register <nome> SHA256:<fingerprint-real>
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet vault seed --username gerenet-auto --password <senha-da-conta>
```

O fingerprint registrado usa o mesmo formato `sha256:<b64>` que o `connect_and_run` calcula do host key recebido (Task 9) — o `normalize_fingerprint` normaliza ambos para comparar.

- [ ] **Step 4: Rodar a coleta fim a fim (manual, read-only)**

Terminal A (worker):

```bash
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet-worker
```

Terminal B:

```bash
uv run gerenet collect run --device <nome>
uv run gerenet snapshot show <id>
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "select id, status from device_snapshots order by id desc limit 5;"
```

Expected: snapshot `success`; `vrp_version`/`uptime` preenchidos no device; 2 arquivos brutos em `data/backups/<nome>/<timestamp>/...`; `job_runs` com status success e `snapshot_id`. A saída de `display current-configuration` **não** é versionada nem exibida em logs.

- [ ] **Step 5: Ajustar parser/template se a saída real divergir**

Se `parse_template("version", ...)` falhar ou capturar vazio (formato da linha de versão/uptime diferente, ex.: NE40/VRP5), ajustar `version.template`, atualizar o fixture e re-rodar o teste golden. Registrar no commit o padrão real observado.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: validação fim a fim da coleta contra NE8000 real

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Critério de aceite do plano (cortes 0–2)

- `uv run pytest` verde com postgres/redis/vault do compose de pé.
- CLI: `gerenet devices add|list`, `gerenet hostkey register`, `gerenet vault seed`, `gerenet collect run`, `gerenet snapshot show` funcionando.
- API: `/healthz`, CRUD de devices autenticado, `POST /{id}/collect` (202/409/404), listagem/detalhe de snapshots.
- Coleta real read-only de 1 NE8000: snapshot success/partial com `version` parseado via TextFSM, backup de config em `data/backups/`, device atualizado (`vrp_version`, `comm_status=ok`, `last_collected_at`), `job_runs` e `audit_events` íntegros.
- Nenhuma credencial em git/banco/logs; host key validada antes de toda conexão; nenhum comando fora da allowlist.
