# Grupos de Credencial na Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir criar, listar, editar e desativar grupos de credencial pela interface web do gerenet e vincular um grupo a um equipamento pela mesma interface (eliminando a dependência do CLI para o fluxo "equipamento sem grupo de credencial").

**Architecture:** O backend já tem modelo (`credential_groups`), service (`create`/`list`) e CLI; falta a faceta REST (router com CRUD completo), o vínculo editável/exibível no device (schema) e a UI. Seguimos os padrões consolidados do repo: catálogo espelho de `contacts` (service + router + testes) e páginas web espelho de `Contacts.tsx`/`Devices.tsx`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Pydantic (backend); React + Vite + TanStack Query + Vitest + Playwright (web); pytest/ruff (backend).

**Spec:** design aprovado em chat (2026-09-08, sessão de brainstorming) — ver CLAUDE.md §"Domínios do sistema" (§5 credenciais referenciadas por grupo; §14.1 objetos em uso desativados, nunca excluídos) e ciclo C3 (padrão de edição/reativação web).

## Global Constraints

- Idioma dos artefatos: **português (PT-BR)** — nomes de testes, docstrings, mensagens de erro e textos de UI em PT.
- Credenciais **nunca** no registro do equipamento nem em logs/auditoria — a UI só registra o **vínculo** (FK); o segredo segue no Vault (`credential_groups.vault_path` aponta o caminho lógico).
- Regra §14.1: desativação, nunca exclusão física — `CredentialGroup` ganha `admin_status` (default `True`), sem DELETE.
- Segredos nunca em `snapshots`, logs ou auditoria — o campo `vault_path` é metadado, pode aparecer em auditoria (como hoje no CLI).
- A migração Alembic é **manual** (padrão do repo: docstring PT, `revision`/`down_revision` explícitos); head atual: **`7dd3d6db4796`**.
- Rodar `git commit` apenas quando o step manda; mensagens em PT com conventional commits (`feat(web): …`), terminadas com:
  `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- Implementação deve acontecer em **worktree isolada** (CLAUDE.md global) — ver `superpowers:using-git-worktrees` antes do primeiro commit.

---

### Task 1: Migração e modelo — `credential_groups.admin_status` + `updated_at`

**Files:**
- Create: `alembic/versions/<hash>_credential_groups_admin_status.py`
- Modify: `src/gerenet/domain/models.py:98-108`

**Interfaces:**
- Produces: `models.CredentialGroup` com `admin_status: bool` e `updated_at: datetime` — consumido pelas Tasks 2-4.

- [ ] **Step 1: Gerar o hash da revisão**

Run: `uv run alembic revision -m "credential_groups admin_status" --rev-id $(date +%s | tail -c 13) 2>/dev/null || uv run alembic revision -m "credential_groups admin_status"`
Expected: cria `alembic/versions/<hash>_credential_groups_admin_status.py` com `down_revision: str | Sequence[str] | None = "7dd3d6db4796"`.

- [ ] **Step 2: Escrever o corpo da migração**

Em `alembic/versions/<hash>_credential_groups_admin_status.py`, substituir `upgrade`/`downgrade` por:

```python
def upgrade() -> None:
    """admin_status (desativação §14.1) e updated_at em credential_groups."""
    op.add_column(
        "credential_groups",
        sa.Column("admin_status", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "credential_groups",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("credential_groups", "updated_at")
    op.drop_column("credential_groups", "admin_status")
```

- [ ] **Step 3: Atualizar o modelo**

Em `src/gerenet/domain/models.py`, na classe `CredentialGroup` (linhas 98-108), após `created_at`, adicionar:

```python
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 4: Migrar os bancos dev e de teste**

Run:
```bash
uv run alembic upgrade head        # banco dev (GERENET_DATABASE_URL default)
GERENET_DATABASE_URL="postgresql+psycopg://localhost:5432/gerenet_test" uv run alembic upgrade head
```
(Conferir a URL exata do teste em `tests/conftest.py:5-8` — o pytest usa `gerenet_test` por padrão e o `alembic` lê `GERENET_DATABASE_URL`, não a var de teste.)
Expected: `Running upgrade 7dd3d6db4796 -> <hash>`. O `gerenet_dev`/`gerenet_test` ganham as colunas (o `server_default=sa.true()` reaproveita linhas existentes).

- [ ] **Step 5: Rodar a suíte existente de credential_groups**

Run: `uv run pytest tests/domain/test_credential_groups.py -q`
Expected: PASS (3 testes existentes; colunas novas não afetam os asserts).

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/<hash>_credential_groups_admin_status.py src/gerenet/domain/models.py
git commit -m "feat(credential-groups): admin_status e updated_at no modelo

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Service — get/update/disable/enable com auditoria

**Files:**
- Modify: `src/gerenet/domain/services/credential_groups.py`
- Test: `tests/domain/test_credential_groups.py`

**Interfaces:**
- Consumes: `models.CredentialGroup.admin_status` (Task 1); `NotFoundError`/`ConflictError`/`ValidationError` de `gerenet.domain.services.errors`; `registrar` de `gerenet.domain.audit`.
- Nota de ordem: o service tipa `data: CredentialGroupUpdate`, então o Step 1 desta task cria esse schema (adianta uma parte da Task 3 — schemas não têm lógica e não quebram nada a sós).
- Produces: `get_credential_group(session, credential_group_id) -> models.CredentialGroup`; `list_credential_groups(session, include_disabled=False) -> list`; `update_credential_group(session, credential_group_id, data: CredentialGroupUpdate, *, actor) -> models.CredentialGroup`; `disable_credential_group(...)`; `enable_credential_group(...)`. Auditoria: `credential_group.update` / `.disable` / `.enable`. Consumido pela Task 3 (router) e Task 4 (validação do vínculo no device).

- [ ] **Step 1: Criar os schemas mínimos**

Em `src/gerenet/domain/schemas.py`, logo após a classe `DeviceOut` (antes de `SnapshotOut`, linha ~50), adicionar:

```python
class CredentialGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    vault_path: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="tacacs_password", max_length=32)


class CredentialGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    vault_path: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = Field(default=None, max_length=32)


class CredentialGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    vault_path: str
    admin_status: bool
```

- [ ] **Step 2: Escrever os testes que falham**

Adicionar ao final de `tests/domain/test_credential_groups.py`:

```python
def test_get_e_list_filtram_desativados(db_session: Session) -> None:
    grupo = create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    assert get_credential_group(db_session, grupo.id).name == "automacao"
    assert list_credential_groups(db_session) == [grupo]

    disable_credential_group(db_session, grupo.id, actor="cli")
    assert list_credential_groups(db_session) == []
    assert [g.name for g in list_credential_groups(db_session, include_disabled=True)] == ["automacao"]


def test_get_inexistente_levanta_not_found(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Grupo de credencial 999 não encontrado"):
        get_credential_group(db_session, 999)


def test_update_grupo_renomeia_e_audita(db_session: Session) -> None:
    grupo = create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    atualizado = update_credential_group(
        db_session, grupo.id, CredentialGroupUpdate(vault_path="gerenet/credential-groups/automacao2"), actor="cli"
    )
    assert atualizado.vault_path == "gerenet/credential-groups/automacao2"
    assert db_session.scalar(select(AuditEvent).filter_by(type="credential_group.update")) is not None


def test_update_nome_duplicado_levanta_conflito(db_session: Session) -> None:
    create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    outro = create_credential_group(
        db_session, name="outro", vault_path="gerenet/credential-groups/outro", actor="cli"
    )
    with pytest.raises(ConflictError, match="grupo de credencial com esse nome"):
        update_credential_group(
            db_session, outro.id, CredentialGroupUpdate(name="automacao"), actor="cli"
        )


def test_disable_enable_sao_idempotentes_e_auditam(db_session: Session) -> None:
    grupo = create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    disable_credential_group(db_session, grupo.id, actor="cli")
    disable_credential_group(db_session, grupo.id, actor="cli")  # segunda vez: sem novo evento
    enable_credential_group(db_session, grupo.id, actor="cli")
    assert db_session.query(AuditEvent).filter_by(type="credential_group.disable").count() == 1
    assert db_session.query(AuditEvent).filter_by(type="credential_group.enable").count() == 1
    assert grupo.admin_status is True
```

E atualizar os imports do arquivo:

```python
from gerenet.domain.schemas import CredentialGroupUpdate
from gerenet.domain.services.credential_groups import (
    create_credential_group,
    disable_credential_group,
    enable_credential_group,
    get_credential_group,
    get_or_create_credential_group,
    list_credential_groups,
    update_credential_group,
)
from gerenet.domain.services.errors import ConflictError, NotFoundError
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/domain/test_credential_groups.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_credential_group' ...`.

- [ ] **Step 4: Implementar o service**

Em `src/gerenet/domain/services/credential_groups.py`, adicionar `update` (com `IntegrityError` → `ConflictError`) e alinhar `list` ao padrão de filtro:

```python
def list_credential_groups(session: Session, include_disabled: bool = False) -> list[models.CredentialGroup]:
    stmt = select(models.CredentialGroup).order_by(models.CredentialGroup.name)
    if not include_disabled:
        stmt = stmt.where(models.CredentialGroup.admin_status.is_(True))
    return list(session.scalars(stmt))


def get_credential_group(session: Session, credential_group_id: int) -> models.CredentialGroup:
    grupo = session.get(models.CredentialGroup, credential_group_id)
    if grupo is None:
        raise NotFoundError(f"Grupo de credencial {credential_group_id} não encontrado.")
    return grupo


def update_credential_group(
    session: Session, credential_group_id: int, data: schemas.CredentialGroupUpdate, *, actor: str
) -> models.CredentialGroup:
    grupo = get_credential_group(session, credential_group_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return grupo
    antes = {campo: getattr(grupo, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(grupo, campo, valor)
    try:
        registrar(
            session, tipo="credential_group.update", ator=actor, objeto="credential_group",
            objeto_id=grupo.id, antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Já existe um grupo de credencial com esse nome.") from exc
    session.refresh(grupo)
    return grupo


def disable_credential_group(session: Session, credential_group_id: int, *, actor: str) -> models.CredentialGroup:
    grupo = get_credential_group(session, credential_group_id)
    if grupo.admin_status is False:
        return grupo
    grupo.admin_status = False
    registrar(
        session, tipo="credential_group.disable", ator=actor, objeto="credential_group",
        objeto_id=grupo.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return grupo


def enable_credential_group(session: Session, credential_group_id: int, *, actor: str) -> models.CredentialGroup:
    grupo = get_credential_group(session, credential_group_id)
    if grupo.admin_status is True:
        return grupo
    grupo.admin_status = True
    registrar(
        session, tipo="credential_group.enable", ator=actor, objeto="credential_group",
        objeto_id=grupo.id, antes={"admin_status": False}, depois={"admin_status": True},
    )
    session.commit()
    return grupo
```

E adicionar `from gerenet.domain import models, schemas` (substituir o import atual `from gerenet.domain import models` por `from gerenet.domain import models, schemas`).

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/domain/test_credential_groups.py -q`
Expected: PASS (8 testes).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/credential_groups.py src/gerenet/domain/schemas.py tests/domain/test_credential_groups.py
git commit -m "feat(credential-groups): service de busca/update/desativar com auditoria

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Router REST `/api/v1/credential-groups`

**Files:**
- Create: `src/gerenet/api/routers/credential_groups.py`
- Modify: `src/gerenet/api/main.py:39-60` (import + `include_router`)
- Test: `tests/api/test_credential_groups_api.py`

**Interfaces:**
- Consumes: service da Task 2 (assinaturas exatas listadas lá).
- Produces: `APIRouter` com `GET ""` (query `include_disabled: bool = False`), `POST ""` (201), `GET "/{group_id}"`, `PATCH "/{group_id}"`. Erros: `ConflictError` → 409, `NotFoundError` → 404, `ValidationError` → 400. Consumido pela web (Tasks 6-7).

- [ ] **Step 1: Escrever o teste de API que falha**

Criar `tests/api/test_credential_groups_api.py`:

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


def _grupo(client: TestClient, nome: str = "automacao") -> dict:
    resp = client.post(
        "/api/v1/credential-groups",
        json={"name": nome, "vault_path": f"gerenet/credential-groups/{nome}"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_crud_grupos(client: TestClient) -> None:
    grupo = _grupo(client, "automacao")
    assert grupo["name"] == "automacao"
    assert grupo["kind"] == "tacacs_password"
    assert grupo["admin_status"] is True

    lista = client.get("/api/v1/credential-groups", headers=_auth()).json()
    assert [g["name"] for g in lista] == ["automacao"]

    corpo = client.get(f"/api/v1/credential-groups/{grupo['id']}", headers=_auth()).json()
    assert corpo["vault_path"] == "gerenet/credential-groups/automacao"

    inexistente = client.get("/api/v1/credential-groups/9999", headers=_auth())
    assert inexistente.status_code == 404


def test_grupo_duplicado_da_409_e_sem_nome_400(client: TestClient) -> None:
    _grupo(client, "automacao")
    duplicado = client.post(
        "/api/v1/credential-groups",
        json={"name": "automacao", "vault_path": "outro/caminho"},
        headers=_auth(),
    )
    assert duplicado.status_code == 409

    sem_nome = client.post(
        "/api/v1/credential-groups", json={"name": "", "vault_path": "x"}, headers=_auth()
    )
    assert sem_nome.status_code == 400


def test_patch_grupo_edita_desativa_reativa_e_audita(db_session: Session, client: TestClient) -> None:
    grupo = _grupo(client, "automacao")

    editado = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}",
        json={"vault_path": "gerenet/credential-groups/auto2"},
        headers=_auth(),
    )
    assert editado.status_code == 200
    assert editado.json()["vault_path"] == "gerenet/credential-groups/auto2"

    off = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}", json={"admin_status": False}, headers=_auth()
    )
    assert off.status_code == 200
    assert off.json()["admin_status"] is False

    sem_flag = client.get("/api/v1/credential-groups", headers=_auth()).json()
    assert [g["name"] for g in sem_flag] == []
    com_flag = client.get(
        "/api/v1/credential-groups?include_disabled=true", headers=_auth()
    ).json()
    assert [g["name"] for g in com_flag] == ["automacao"]

    on = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}", json={"admin_status": True}, headers=_auth()
    )
    assert on.status_code == 200

    null = client.patch(
        f"/api/v1/credential-groups/{grupo['id']}", json={"admin_status": None}, headers=_auth()
    )
    assert null.status_code == 400

    tipos = [
        e.type for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == [
        "credential_group.create",
        "credential_group.update",
        "credential_group.disable",
        "credential_group.enable",
    ]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/api/test_credential_groups_api.py -q`
Expected: FAIL — `404 Not Found` (rota inexistente).

- [ ] **Step 3: Criar o router**

Criar `src/gerenet/api/routers/credential_groups.py` (espelho do padrão `contacts.py`):

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import CredentialGroupCreate, CredentialGroupOut, CredentialGroupUpdate
from gerenet.domain.services import credential_groups as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/credential-groups",
    tags=["credential-groups"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[CredentialGroupOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_credential_groups(session, include_disabled=include_disabled)


@router.post("", response_model=CredentialGroupOut, status_code=201)
def criar(
    data: CredentialGroupCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.create_credential_group(
            session, name=data.name, vault_path=data.vault_path, kind=data.kind, actor=actor.nome
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{group_id}", response_model=CredentialGroupOut)
def detalhar(group_id: int, session: SessionDep) -> object:
    try:
        return svc.get_credential_group(session, group_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{group_id}", response_model=CredentialGroupOut)
def atualizar(
    group_id: int,
    data: CredentialGroupUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_credential_group(session, group_id, actor=actor.nome)
        if mudancas == {"admin_status": True}:
            return svc.enable_credential_group(session, group_id, actor=actor.nome)
        return svc.update_credential_group(session, group_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 4: Registrar no main.py**

Em `src/gerenet/api/main.py`:
- No import `from gerenet.api.routers import (`, adicionar `credential_groups,` (manter ordem alfabética);
- Junto aos `include_router(...)` (após `contacts.router`, linha ~44), adicionar:

```python
    app.include_router(credential_groups.router)
```

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/api/test_credential_groups_api.py -q`
Expected: PASS (3 testes).

- [ ] **Step 6: Rodar a suíte de API completa para detectar regressões**

Run: `uv run pytest tests/api -q`
Expected: PASS. (O `_limpa_tabelas` do conftest já trunca `credential_groups`.)

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/api/routers/credential_groups.py src/gerenet/api/main.py tests/api/test_credential_groups_api.py
git commit -m "feat(credential-groups): router REST com CRUD e auditoria

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Vínculo do grupo ao equipamento (API)

**Files:**
- Modify: `src/gerenet/domain/schemas.py:21-31` (`DeviceUpdate`) e `:32-50` (`DeviceOut`)
- Modify: `src/gerenet/domain/services/devices.py:14-35` (`create_device`)
- Modify: `src/gerenet/api/routers/devices.py:49-99` (`atualizar` PATCH)
- Test: `tests/api/test_devices_api.py` (adicionar casos) e `tests/api/test_collect_api.py:43` (se usar `DeviceCreate`, nenhum ajuste — só verificar)

**Interfaces:**
- Consumes: `get_credential_group` (Task 2); `CredentialGroup`/`Devices` já têm a FK (`devices.credential_group_id`, models.py:82).
- Produces: `DeviceUpdate.credential_group_id: int | None`; `DeviceOut.credential_group_id: int | None`; `POST /devices` e `PATCH /devices/{id}` aceitam o vínculo (404 para grupo inexistente). Consumido pela web (Tasks 6, 8).

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao final de `tests/api/test_devices_api.py`:

```python
def _grupo(client: TestClient, nome: str = "automacao") -> dict:
    resp = client.post(
        "/api/v1/credential-groups",
        json={"name": nome, "vault_path": f"gerenet/credential-groups/{nome}"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_device_aceita_credential_group_id_no_create(client: TestClient) -> None:
    grupo = _grupo(client)
    resp = client.post(
        "/api/v1/devices",
        json={"name": "sw-core", "management_address": "10.99.0.10", "credential_group_id": grupo["id"]},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["credential_group_id"] == grupo["id"]


def test_device_create_com_grupo_inexistente_da_404(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/devices",
        json={"name": "sw-core", "management_address": "10.99.0.10", "credential_group_id": 9999},
        headers=_auth(),
    )
    assert resp.status_code == 404
    assert "Grupo de credencial" in resp.json()["detail"]


def test_device_patch_vincula_e_desvincula_grupo(client: TestClient) -> None:
    grupo = _grupo(client)
    criado = client.post(
        "/api/v1/devices", json={"name": "sw-core", "management_address": "10.99.0.10"}, headers=_auth()
    )
    dev_id = criado.json()["id"]

    vincula = client.patch(
        f"/api/v1/devices/{dev_id}", json={"credential_group_id": grupo["id"]}, headers=_auth()
    )
    assert vincula.status_code == 200
    assert vincula.json()["credential_group_id"] == grupo["id"]

    desvincula = client.patch(
        f"/api/v1/devices/{dev_id}", json={"credential_group_id": None}, headers=_auth()
    )
    assert desvincula.status_code == 200
    assert desvincula.json()["credential_group_id"] is None

    inexistente = client.patch(
        f"/api/v1/devices/{dev_id}", json={"credential_group_id": 9999}, headers=_auth()
    )
    assert inexistente.status_code == 404
```

(Reusar o `_auth()` do `test_devices_api.py` — conferir se a fixture `client` do arquivo existe; se o arquivo usa outro helper de auth, adaptar a chamada mantendo o shape.)

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/api/test_devices_api.py -q -k credential`
Expected: FAIL — 422 (`extra fields not permitted` no Pydantic) ou 201 com `credential_group_id` ausente no response.

- [ ] **Step 3: Atualizar os schemas**

Em `src/gerenet/domain/schemas.py`:

```python
class DeviceUpdate(BaseModel):
    admin_status: bool | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    model: str | None = None
    family: str | None = None
    role: str | None = None
    site_id: int | None = None
    asn: int | None = Field(default=None, ge=1, le=4294967295)
    tags: list[str] | None = None
    credential_group_id: int | None = None
```

E em `DeviceOut`, após `tags: list[str]`, adicionar:

```python
    credential_group_id: int | None
```

- [ ] **Step 4: Validar o vínculo no `create_device`**

Em `src/gerenet/domain/services/devices.py`, dentro de `create_device`, antes de `dev = models.Device(...)`:

```python
    if data.credential_group_id is not None:
        get_credential_group(session, data.credential_group_id)  # NotFoundError PT
```

E ajustar o import:

```python
from gerenet.domain.services.credential_groups import get_credential_group
```

- [ ] **Step 5: Validar o vínculo no PATCH da API**

Em `src/gerenet/api/routers/devices.py`, no `try` do handler `atualizar` (após o check de `asn`), adicionar:

```python
        if mudancas.get("credential_group_id") is not None:
            svc_grupos.get_credential_group(session, mudancas["credential_group_id"])
```

E trocar o tratamento de erro para incluir 404. Na estrutura atual, o bloco `try/except` captura `ValidationError`; adicionar o `except NotFoundError` (é o erro do get_device, que hoje está fora do try) de modo que o handler fique:

```python
    mudancas = data.model_dump(exclude_unset=True)
    try:
        if mudancas.get("asn") is not None and not asn_valido(mudancas["asn"]):
            raise ValidationError(f"ASN inválido ou reservado: {mudancas['asn']}.")
        if mudancas.get("credential_group_id") is not None:
            groups_svc.get_credential_group(session, mudancas["credential_group_id"])
        antes = {campo: getattr(dev, campo) for campo in mudancas}
        ...
    except ValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

Com os imports:

```python
from gerenet.domain.services import credential_groups as groups_svc
```

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/api/test_devices_api.py tests/api/test_collect_api.py -q`
Expected: PASS (novos + existentes).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/devices.py src/gerenet/api/routers/devices.py tests/api/test_devices_api.py
git commit -m "feat(devices): criar/editar vínculo de grupo de credencial via API

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Mensagem do worker orienta o caminho web

**Files:**
- Modify: `src/gerenet/worker/tasks.py:26-31`

**Interfaces:**
- Consumes: nada de tasks anteriores. Produces: nova mensagem de erro exibida quando um device é enfileirado para coleta sem grupo de credencial.

- [ ] **Step 1: Atualizar a mensagem**

Em `src/gerenet/worker/tasks.py`, substituir o texto do erro (linhas 26-31):

```python
        if dev.credential_group is None:
            raise ValueError(
                f"Equipamento {dev.name} não possui grupo de credencial — crie-o na "
                "página Credenciais (ou com `gerenet credential-groups create`) e "
                "vincule-o ao equipamento em Equipamentos > Editar."
            )
```

- [ ] **Step 2: Rodar os testes do worker**

Run: `uv run pytest tests/worker/test_tasks.py tests/api/test_collect_api.py -q`
Expected: PASS — nenhum teste asserta a frase completa (verificado: apenas um comentário em `tests/automation/test_runner_change.py:34`).

- [ ] **Step 3: Commit**

```bash
git add src/gerenet/worker/tasks.py
git commit -m "fix(worker): mensagem de coleta sem credencial cita o caminho web

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: Web — types, hooks e help

**Files:**
- Modify: `web/src/api/types.ts:10-26` (`DeviceOut`)
- Modify: `web/src/api/hooks.ts` (novos hooks + `DeviceCreateIn`)
- Modify: `web/src/help.ts` (novas chaves)

**Interfaces:**
- Consumes: contrato REST da Task 3/4.
- Produces: `CredentialGroupOut` (types), `useCredentialGroups`, `useCredentialGroupCriar`, `useCredentialGroupAtualizar` (hooks), `credential_group_id` em `DeviceCreateIn`, chaves `help(...)` — consumidos pelas Tasks 7-8.

- [ ] **Step 1: Adicionar o tipo e o campo no DeviceOut**

Em `web/src/api/types.ts`, após a interface `DeviceOut` (linha ~26), adicionar:

```ts
export interface CredentialGroupOut {
  id: number;
  name: string;
  kind: string;
  vault_path: string;
  admin_status: boolean;
}
```

E em `DeviceOut`, após `tags: string[];`, adicionar:

```ts
  credential_group_id: number | null;
```

- [ ] **Step 2: Adicionar os hooks e o campo no DeviceCreateIn**

Em `web/src/api/hooks.ts`:

1. No import de `./types`, adicionar `CredentialGroupOut,` (ordem alfabética);
2. Após `useContacts` (linha ~135), adicionar:

```ts
export const useCredentialGroups = (opts?: { includeDisabled?: boolean }) =>
  useLista<CredentialGroupOut>("credential-groups", "/api/v1/credential-groups", opts);
export type CredentialGroupCreateIn = { name: string; vault_path: string; kind?: string };
export type CredentialGroupUpdateIn = Partial<CredentialGroupCreateIn>;
export const useCredentialGroupCriar = () =>
  useCriar<CredentialGroupCreateIn, CredentialGroupOut>("credential-groups", "/api/v1/credential-groups");
export const useCredentialGroupAtualizar = () =>
  useAtualizar<CredentialGroupUpdateIn & { admin_status?: boolean }, CredentialGroupOut>(
    "credential-groups",
    "/api/v1/credential-groups",
  );
```

3. Em `DeviceCreateIn` (linhas 137-147), adicionar `credential_group_id?: number | null;` após `asn`.

- [ ] **Step 3: Adicionar as chaves de help**

Em `web/src/help.ts`, após o bloco `// Devices` (que termina em `"device.tags"`, linha ~21), adicionar:

```ts
  "device.credential_group": "Grupo de credencial usado para acessar o equipamento — o segredo fica no Vault; aqui fica só o vínculo.",
```

E adicionar um novo bloco após `// Devices`:

```ts
  // Credential groups
  "credential_group.name": "Nome único do grupo (1–64); identificador referenciado pelo equipamento.",
  "credential_group.vault_path": "Caminho lógico no Vault onde o segredo do grupo é armazenado (ex.: gerenet/credential-groups/automacao).",
  "credential_group.kind": "Tipo de credencial do grupo (default: tacacs_password).",
```

- [ ] **Step 4: Validar com o build**

Run: `cd web && npm run build`
Expected: PASS — o build valida as chaves de `help()` (as chaves todas referenciadas existem; `tsc -b` valida os tipos).

- [ ] **Step 5: Commit**

```bash
git add web/src/api/types.ts web/src/api/hooks.ts web/src/help.ts
git commit -m "feat(web): tipos, hooks e help de grupos de credencial

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Página `CredentialGroups.tsx` + rota + navegação

**Files:**
- Create: `web/src/pages/CredentialGroups.tsx`
- Create: `web/src/pages/CredentialGroups.test.tsx`
- Modify: `web/src/App.tsx` (import + rota)
- Modify: `web/src/components/Layout.tsx:12-15` (nav grupo "Ativos")

**Interfaces:**
- Consumes: hooks/Typing da Task 6; componentes `DataTable`, `FormField`, `StatusBadge`, `PageHeader`, `ConfirmDialog`, `Modal` (mesmos usados em `Contacts.tsx`).
- Produces: página em `/credential-groups` com criar/listar/editar/desativar/reativar; link "Credenciais" na nav.

- [ ] **Step 1: Escrever a página**

Criar `web/src/pages/CredentialGroups.tsx` (espelho de `Contacts.tsx`, com os 3 campos do grupo):

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useCredentialGroupAtualizar,
  useCredentialGroupCriar,
  useCredentialGroups,
} from "@/api/hooks";
import { help } from "@/help";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import type { CredentialGroupOut } from "@/api/types";

const FORM_VAZIO = { name: "", vault_path: "", kind: "tacacs_password" };

export default function CredentialGroups() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useCredentialGroups({ includeDisabled: incluirInativos });
  const criar = useCredentialGroupCriar();
  const atualizar = useCredentialGroupAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<CredentialGroupOut | null>(null);
  const [reativando, setReativando] = useState<CredentialGroupOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<CredentialGroupOut | null>(null);
  const [formEdit, setFormEdit] = useState(FORM_VAZIO);
  const [erroEdit, setErroEdit] = useState<string | null>(null);

  function abrirEdicao(g: CredentialGroupOut) {
    setFormEdit({ name: g.name, vault_path: g.vault_path, kind: g.kind });
    setErroEdit(null);
    setEditando(g);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        name: formEdit.name,
        vault_path: formEdit.vault_path,
        kind: formEdit.kind,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar o grupo.");
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        vault_path: form.vault_path,
        kind: form.kind,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar o grupo.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Grupos de credencial" />
      <label className="inline-check">
        <input
          type="checkbox"
          checked={incluirInativos}
          onChange={(e) => setIncluirInativos(e.target.checked)}
        />
        Ver desativados
      </label>
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Nome *" help={help("credential_group.name")}>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="Caminho no Vault *" help={help("credential_group.vault_path")}>
            <input value={form.vault_path} onChange={(e) => setForm({ ...form, vault_path: e.target.value })} required />
          </FormField>
          <FormField label="Tipo" help={help("credential_group.kind")}>
            <input value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<CredentialGroupOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "kind", title: "Tipo" },
          { key: "vault_path", title: "Caminho no Vault" },
          {
            key: "admin_status",
            title: "Situação",
            render: (g) => <StatusBadge estado={g.admin_status ? "ativo" : "inativo"} />,
          },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(g) => (
          <>
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(g)}>
                Editar
              </button>
            )}
            {podeEscrever && g.admin_status ? (
              <button type="button" onClick={() => setDesativando(g)}>
                Desativar
              </button>
            ) : podeEscrever ? (
              <button type="button" onClick={() => setReativando(g)}>
                Reativar
              </button>
            ) : null}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O grupo fica indisponível para novos vínculos; equipamentos já vínculados mantêm o grupo."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar o grupo."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.name ?? ""}?`}
        mensagem="O grupo volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar o grupo."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Nome *" help={help("credential_group.name")}>
              <input value={formEdit.name} onChange={(e) => setFormEdit({ ...formEdit, name: e.target.value })} required />
            </FormField>
            <FormField label="Caminho no Vault *" help={help("credential_group.vault_path")}>
              <input value={formEdit.vault_path} onChange={(e) => setFormEdit({ ...formEdit, vault_path: e.target.value })} required />
            </FormField>
            <FormField label="Tipo" help={help("credential_group.kind")}>
              <input value={formEdit.kind} onChange={(e) => setFormEdit({ ...formEdit, kind: e.target.value })} />
            </FormField>
            <div className="dialog-actions">
              <button type="button" onClick={() => setEditando(null)} disabled={atualizar.isPending}>
                Cancelar
              </button>
              <button className="primary" type="submit" disabled={atualizar.isPending}>
                {atualizar.isPending ? "Salvando…" : "Salvar"}
              </button>
            </div>
          </form>
          {erroEdit && <p role="alert">{erroEdit}</p>}
        </Modal>
      )}
    </main>
  );
}
```

- [ ] **Step 2: Escrever o teste de componente**

Criar `web/src/pages/CredentialGroups.test.tsx` (espelho do shape de `Devices.test.tsx`):

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import CredentialGroups from "./CredentialGroups";
import { AuthProvider } from "@/auth/auth-context";

const grupos = [
  {
    id: 1,
    name: "automacao",
    kind: "tacacs_password",
    vault_path: "gerenet/credential-groups/automacao",
    admin_status: true,
  },
];

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 2, ...body, admin_status: true }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/v1/credential-groups" && init?.method === undefined) {
        return new Response(JSON.stringify(grupos), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/auth/me") {
        return new Response(
          JSON.stringify({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response("null", { status: 404 });
    }),
  );
});

function renderPagina() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/credential-groups"]}>
        <AuthProvider>
          <CredentialGroups />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CredentialGroups", () => {
  it("lista grupos e cadastra novo pela API", async () => {
    renderPagina();
    await waitFor(() => expect(screen.getByText("automacao")).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText("Nome *"), "backup");
    await userEvent.type(screen.getByLabelText("Caminho no Vault *"), "gerenet/credential-groups/backup");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));

    await waitFor(() =>
      expect(screen.getByLabelText("Nome *")).toHaveValue(""),
    );
  });

  it("desativa grupo com confirmação", async () => {
    renderPagina();
    await waitFor(() => expect(screen.getByText("automacao")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Desativar automacao/ })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
  });
});
```

(Ao implementar: conferir labels/a11y reais do `ConfirmDialog` e ajustar o teste se necessário — o segundo teste depende do botão do dialog; se o padrão de `ConfirmDialog` usar outro nome de confirmar, adaptar com base em `Devices.test.tsx`/`Contacts.test.tsx`.)

- [ ] **Step 3: Registrar rota e navegação**

Em `web/src/App.tsx`:
- Import: `import CredentialGroups from "@/pages/CredentialGroups";`
- Rota (após `/devices/:id`, linha ~49): `<Route path="/credential-groups" element={<CredentialGroups />} />`

Em `web/src/components/Layout.tsx`, no grupo `"Ativos"` (após o item de Equipamentos, linha ~12):

```ts
      { para: "/credential-groups", rotulo: "Credenciais" },
```

- [ ] **Step 4: Rodar os testes de componente**

Run: `cd web && npm run test -- CredentialGroups`
Expected: PASS (2 testes).

- [ ] **Step 5: Validar build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/CredentialGroups.tsx web/src/pages/CredentialGroups.test.tsx web/src/App.tsx web/src/components/Layout.tsx
git commit -m "feat(web): página de grupos de credencial com CRUD

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Select de credencial no formulário de equipamento

**Files:**
- Modify: `web/src/pages/Devices.tsx`
- Test: `web/src/pages/Devices.test.tsx`

**Interfaces:**
- Consumes: `useCredentialGroups` + `credential_group_id` em `DeviceOut`/`DeviceCreateIn` (Task 6).
- Produces: formulário de criação com `<select>` "Grupo de credencial"; modal de edição com o mesmo `<select>` (incluindo opção dinâmica quando o device referencia um grupo desativado); coluna "Credencial" na tabela.

- [ ] **Step 1: Atualizar o mock do teste**

Em `web/src/pages/Devices.test.tsx`:
- Adicionar ao `beforeAll` do `fetch` mock, antes do `if (url === "/api/v1/devices")`:

```ts
      if (url === "/api/v1/credential-groups") {
        return new Response(
          JSON.stringify([
            { id: 1, name: "automacao", kind: "tacacs_password", vault_path: "gerenet/credential-groups/automacao", admin_status: true },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
```

- No `equipamentos` (linhas 9-20), adicionar `credential_group_id: null,` e `ssh_port: null,` (conferir se o resto dos campos exigidos por `DeviceOut` já está presente; o objeto atual é parcial — o `useQuery` só consome o que a página renderiza).

- [ ] **Step 2: Escrever o teste que falha (vínculo na edição)**

Adicionar ao final do `describe("Devices", ...)`:

```tsx
  it("vincula grupo de credencial ao editar um equipamento", async () => {
    renderDevices();
    await waitFor(() => expect(screen.getByText("ne8000-01")).toBeInTheDocument());

    await userEvent.click(screen.getAllByRole("button", { name: "Editar" })[0]);
    await userEvent.selectOptions(screen.getByLabelText("Grupo de credencial"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
  });
```

(Conferir o nome exato do botão de salvar no `Modal` de `Devices.tsx` — "Salvar" — e se o fetch mock de PATCH precisa aceitar o campo: o mock atual devolve `{ ...equipamentos[0], admin_status: false }`; para o teste de vínculo, a resposta do PATCH deve incluir `credential_group_id: 1` — ajustar o mock para devolver `{ ...equipamentos[0], admin_status: true, credential_group_id: body?.credential_group_id ?? null }` no ramo PATCH, ou simplesmente `{ ...equipamentos[0], credential_group_id: 1 }`.)

- [ ] **Step 3: Rodar para ver falhar**

Run: `cd web && npm run test -- Devices`
Expected: FAIL — campo "Grupo de credencial" ausente (ou mock sem ramo → o select não existe).

- [ ] **Step 4: Implementar na página**

Em `web/src/pages/Devices.tsx`:

1. Import: adicionar `useCredentialGroups` ao import de `@/api/hooks` e `CredentialGroupOut` ao import de `@/api/types` (se precisar de tipo — coluna usa `grupos?.find(...)`, sem tipo explícito).
2. Hook (após `const { data: sites } = useSites();`):

```ts
  const { data: grupos } = useCredentialGroups();
```

3. `FORM_VAZIO` (linhas 23-33): adicionar `credential_group_id: "",`.
4. `FORM_EDIT_VAZIO` (linha 35): adicionar `credential_group_id: "",`.
5. `onSubmit` (linhas 59-69): adicionar ao corpo do POST:

```ts
        credential_group_id: form.credential_group_id === "" ? null : Number(form.credential_group_id),
```

6. `abrirEdicao` (linhas 76-88): adicionar ao `setFormEdit`:

```ts
      credential_group_id: d.credential_group_id === null ? "" : String(d.credential_group_id),
```

7. `salvarEdicao` (linhas 95-104): adicionar ao corpo do PATCH:

```ts
        credential_group_id: formEdit.credential_group_id === "" ? null : Number(formEdit.credential_group_id),
```

8. No form de **criação** (após o `FormField` de Site, linha ~162), adicionar:

```tsx
          <FormField label="Grupo de credencial" help={help("device.credential_group")}>
            <select value={form.credential_group_id} onChange={(e) => setForm({ ...form, credential_group_id: e.target.value })}>
              <option value="">—</option>
              {(grupos ?? []).map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </FormField>
```

9. No **modal de edição** (após o `FormField` de Site, linha ~264), adicionar — com opção dinâmica para o grupo atual não estar na lista (desativado):

```tsx
            <FormField label="Grupo de credencial" help={help("device.credential_group")}>
              <select value={formEdit.credential_group_id} onChange={(e) => setFormEdit({ ...formEdit, credential_group_id: e.target.value })}>
                <option value="">—</option>
                {(grupos ?? []).map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
                {formEdit.credential_group_id !== "" &&
                  !(grupos ?? []).some((g) => g.id === Number(formEdit.credential_group_id)) && (
                    <option value={formEdit.credential_group_id}>
                      {`(desativado) #${formEdit.credential_group_id}`}
                    </option>
                  )}
              </select>
            </FormField>
```

10. Na `DataTable` de devices, após a coluna `"site"` (linha ~176), adicionar:

```tsx
          {
            key: "credential",
            title: "Credencial",
            render: (d) => grupos?.find((g) => g.id === d.credential_group_id)?.name ?? "—",
          },
```

- [ ] **Step 5: Rodar os testes**

Run: `cd web && npm run test -- Devices`
Expected: PASS (testes existentes + novo).

- [ ] **Step 6: Validar build**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/Devices.tsx web/src/pages/Devices.test.tsx
git commit -m "feat(web): vínculo de grupo de credencial no formulário de equipamento

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: Fumo e2e — criar grupo e vincular ao equipamento

**Files:**
- Create: `web/e2e/credential-groups.spec.ts`

**Interfaces:**
- Consumes: página `/credential-groups` (Task 7), `/devices` com o select (Task 8), seed `ne8000-01` (setup.ts:103) e usuário `admin` do seed e2e.
- Produces: fumo Playwright rerun-safe (grupo único por rodada via `Date.now()`).

- [ ] **Step 1: Escrever o fumo**

Criar `web/e2e/credential-groups.spec.ts` (espelho da estrutura de `upstream.spec.ts`):

```ts
// Fumo: grupo de credencial criado pela página de Credenciais + vínculo ao
// equipamento seed ne8000-01 pela página de Equipamentos (Editar > select
// "Grupo de credencial"). Rerun-safe: grupo único por rodada (Date.now()).
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";
const RODADA = Date.now();
const NOME_GRUPO = `e2e-credencial-${RODADA}`;

async function entrar(page: Page, usuario = "admin"): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuário").fill(usuario);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("button", { name: "Sair" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("credential-groups: cria grupo pela UI e vincula ao equipamento", async ({ page }) => {
  // 1. Admin entra e cria o grupo pela página de Credenciais.
  await entrar(page);
  await page.getByRole("link", { name: "Credenciais" }).click();
  await expect(page).toHaveURL(/\/credential-groups/);
  await expect(page.getByRole("heading", { name: "Grupos de credencial" })).toBeVisible();
  await page.getByLabel("Nome *").fill(NOME_GRUPO);
  await page.getByLabel("Caminho no Vault *").fill(`gerenet/credential-groups/${NOME_GRUPO}`);
  await page.getByRole("button", { name: "Cadastrar" }).click();
  await expect(page.getByRole("row", { name: NOME_GRUPO })).toBeVisible();

  // 2. Vincula o grupo ao equipamento seed ne8000-01 via Editar.
  await page.getByRole("link", { name: "Equipamentos" }).click();
  await expect(page).toHaveURL(/\/devices/);
  const linhaDevice = page.getByRole("row", { name: /ne8000-01/ });
  await expect(linhaDevice).toBeVisible();
  await linhaDevice.getByRole("button", { name: "Editar" }).click();
  await page.getByLabel("Grupo de credencial").selectOption({ label: NOME_GRUPO });
  await page.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByLabel("Grupo de credencial")).toBeHidden();

  // 3. A coluna "Credencial" mostra o nome do grupo.
  await expect(
    page.getByRole("row", { name: /ne8000-01/ }).getByText(NOME_GRUPO),
  ).toBeVisible();
});
```

- [ ] **Step 2: Migrar o banco e2e**

Run:
```bash
GERENET_DATABASE_URL="postgresql+psycopg://localhost:5432/gerenet_e2e" uv run alembic upgrade head
```
(Conferir a URL do e2e em `web/e2e/README.md`; o banco é migrado à parte — nunca o default.)

- [ ] **Step 3: Rodar o fumo**

Run: `cd web && npm run test:e2e`
Expected: todos os specs passam, incluindo o novo. (Para rodar só o novo: `npx playwright test e2e/credential-groups.spec.ts` com o projeto/runner de `playwright.config` já configurado pelo `webServer`.)

- [ ] **Step 4: Verificação final da branch**

Run (na raiz do repo):
```bash
uv run pytest -q
uv run ruff check src tests
cd web && npm run build && npm run test
```

- [ ] **Step 5: Commit**

```bash
git add web/e2e/credential-groups.spec.ts
git commit -m "test(e2e): fumo de grupos de credencial e vínculo ao equipamento

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-Review (executado ao escrever o plano)

- **Cobertura do design:** migração+modelo (T1), service+schemas (T2), router REST+main (T3), vínculo device API (T4), mensagem worker (T5), web types/hooks/help (T6), página+rota+nav (T7), select+coluna em Devices (T8), e2e (T9). Nada do design ficou sem task.
- **Placeholders:** nenhum — cada step tem código ou comando exato. As únicas instruções "conferir" são pontos de verificação explícitos (URLs de banco locais, labels a11y de dialogs) com o arquivo de referência nomeado.
- **Consistência de tipos:** `CredentialGroupOut { id, name, kind, vault_path, admin_status }` consistente entre schemas Pydantic (T2), types.ts (T6) e mocks de teste (T7-T9). `get_credential_group` assinatura igual em T2/T3/T4. Hooks web `useCredentialGroupCriar/Atualizar` iguais em T6/T7/T8.
- **Risco conhecido:** o PATCH de `devices.py` hoje captura apenas `ValidationError` dentro do try; a T4 adiciona `except NotFoundError` — verificar que o `get_device` fora do try continua coberto (ele já lança 404 antes do try; não muda).
- **`DeviceOut` ganha `credential_group_id`** — campos extra no response model podem quebrar testes que asseram o corpo completo; a T4 roda `test_devices_api.py` inteiro para capturar.
