# Ciclo C1 — Autenticação de usuários, dashboard e jobs (gerenet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o backend da interface web do gerenet: usuários com perfis §17 (login local, sessão por cookie, hash scrypt), `require_actor` dual (cookie OU X-Api-Key) sem quebrar CLI/automações, endpoints de auth/usuários/dashboard/jobs e o serviço de estáticos da SPA — tudo testado por pytest.

**Architecture:** Auth local sobre o SoT existente: tabelas `users` + `user_sessions` (sessão em banco, token opaco no cookie, hash sha256 no banco) numa única migration; serviço `domain/services/users.py` com hash scrypt via stdlib (zero dependência nova); `require_actor` (com perfil Visualizador=leitura e `require_admin`) substitui `require_api_key` em todas as rotas com o caminho da chave preservado — testes atuais verdes; routers passam o ator real (username) para a auditoria; dashboard agrega no backend; jobs ganham leitura (`JobRunOut` — `enqueue_collect` já retorna `job_id`); FastAPI serve `web/dist` com fallback SPA.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, FastAPI, Typer, pytest, ruff, stdlib `hashlib.scrypt` (nenhuma dependência nova).

**Spec:** [docs/superpowers/specs/2026-09-04-gerenet-ciclo-c-web-ui-design.md](../specs/2026-09-04-gerenet-ciclo-c-web-ui-design.md) — autoridade vinculante; o plano argumenta a partir dela e registra rulings próprios. Complementam: ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md §4.2/§15–19, spec do ciclo B (render/divergência — mergeado antes deste plano), spec do ciclo A (padrão P3 de API/CLI).

## Global Constraints

Toda task herda esta seção:

- **Idioma**: mensagens de erro/CLI/API/help em PT-BR (padrão do repo); identificadores de código em EN; mensagens de commit em PT-BR no padrão do repo (`feat(auth): …`).
- **Segredos**: senha de usuário nunca em log/resposta/snapshot/auditoria — só `users.password_hash` (scrypt); payload de login nunca é logado; `password_hash`/`token` nunca aparecem em `UserOut`/`JobRunOut`/qualquer resposta. `mascarar` do `domain/audit.py` já cobre chaves com "password"/"token" na trilha.
- **Ator**: `require_actor` é dual — cookie de sessão OU `X-Api-Key`. Sem cookie e sem chave → 401 **"Chave de API ausente ou inválida."** (mensagem atual preservada — testes existentes). Usuário inativo com sessão → 403 **"Usuário desativado."**. Visualizador em método de escrita → 403 **"Perfil Visualizador permite apenas leitura."**. Não-admin em `/users` → 403 **"Somente administradores."**. Login falho → 401 **"Usuário ou senha inválidos."** (mesma mensagem para inexistente/inativo/senha errada).
- **Perfis**: `USER_ROLES = ("visualizador", "operador", "aprovador", "executor", "administrador")` — `role` NOT NULL, exigido em todo create.
- **Hash scrypt** (formato): `scrypt$16384$8$1$<salt_hex>$<key_hex>`, salt=16 bytes `secrets.token_bytes`, dklen=32, verificação com `hmac.compare_digest`; hash corrompido/formatado errado → `False` (sem exceção).
- **Username**: case-sensitive, como digitado — sem normalização no create nem no login.
- **API**: padrão P3 — `SessionDep = Annotated[Session, Depends(get_db)]` local por router, `response_model` nos endpoints, try/except `NotFoundError→404`, `ConflictError→409`, `ValidationError→400`; fixtures de teste de API por arquivo (`client` + `_auth()` locais, `set_settings(Settings(api_key="teste-key", _env_file=None))`).
- **CLI**: Typer, `with get_session() as session`, `except GerenetError` → `typer.echo(f"Erro: {exc}", err=True)` + `Exit(1)`; senha só por prompt oculto (`typer.prompt(..., hide_input=True)`); registros de apps no `cli/main.py`; help PT-BR.
- **Testes**: `uv run pytest -q` ao fim de cada task; `uv run ruff check` no fim (suíte verde + lint). Nunca rodar contra banco dev — conftest aborta se o banco não for de teste. Antes de qualquer task: `GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head`. A suíte TRUNCATE roda por teste — `users`/`user_sessions` entram no TRUNCATE do conftest (T1).
- **Commits**: trailer `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

## Rulings (conflitos/ambiguidades resolvidos — a spec é a autoridade)

1. **Migration**: nova migration `users` + `user_sessions` com `down_revision` = **head vigente no início do plano** (o ciclo B mergeou antes; rodar `uv run alembic heads` no T1 e usar o id único retornado). Sem seed de usuário na migration — o primeiro admin nasce via CLI (`gerenet users create … --role administrador`).
2. **`enqueue_collect` já retorna `job_id`** (`worker/tasks.py:34`) — nada a mudar no retorno do POST collect; só o ator (T5).
3. **Sessões**: TTL fixo via `settings.session_ttl_seconds` (default 28800), sem sliding no v1; expirada é apagada lazy na primeira leitura; múltiplas sessões simultâneas permitidas; `reset_password` e logout invalidam apenas as sessões afetadas (reset = todas do usuário; logout = a do token).
4. **`UserOut`** não expõe `password_hash` nem `last_login_at`? — expõe `last_login_at` (útil para a UI) e **não** expõe `password_hash`.
5. **Rotas existentes**: troca `require_api_key→require_actor` é por-router (deps) + handlers que passam `actor=` ganham `actor: Annotated[Actor, Depends(require_actor)]` — o caminho X-Api-Key mantém ator `"api"`, então `test_collect_api` e os demais seguem verdes sem edição.
6. **Dashboard**: agregação em Python sobre selects simples (dados pequenos no MVP); `by_comm_status` sempre com as três chaves (`unknown`/`ok`/`fail`); `active_job` = job kind `collect` com status `queued|running` mais recente (ou null); `latest_snapshot` = snapshot de maior id (ou null). **Nenhuma chamada a `reconciliar_device` aqui.**
7. **Estáticos**: fallback SPA só é registrado se `web/dist/index.html` existir (settings `static_dir`, default `Path("web/dist")`); rotas que começam com `api/` jamais caem no fallback (404 JSON continua). Assets de `assets/` respondem com `Cache-Control: public,max-age=31536000,immutable`.
8. **Auditoria de auth**: `auth.login` (ator=username, objeto_id=user.id), `auth.login_failed` (ator=username tentado, objeto_id=0 — nunca deixa de registrar falha), `auth.logout` (ator=username se achado). `users.*` events: `user.create`, `user.update`, `user.reset_password` (depois `{"password_reset": True}` — flag, sem valor sensível).
9. **Proteção própria**: PATCH em si mesmo com `role` ou `is_active` → 403 "Não é possível alterar a própria conta." (alterar username da própria conta é permitido; ator via X-Api-Key não sofre a regra — é `usuario=None`).

---

## File Structure

| Arquivo | Situação | Responsabilidade |
|---|---|---|
| `src/gerenet/domain/models.py` | **Modificar** | `USER_ROLES`, `User`, `UserSession` |
| `alembic/versions/<rev>_users_sessions.py` | **Criar (T1)** | tabelas `users`/`user_sessions` + enum `user_role` |
| `tests/conftest.py` | **Modificar (T1)** | TRUNCATE ganha `users`, `user_sessions` |
| `tests/domain/test_users_service.py` | **Criar (T2)** | hash/verify + serviço de usuários |
| `src/gerenet/domain/services/users.py` | **Criar (T2)** | hash + create/list/update/reset/autenticar/sessões |
| `tests/domain/test_auth_sessions.py` | **Criar (T2)** | sessões (iniciar/validar/expirar/encerrar) |
| `src/gerenet/config.py` | **Modificar (T3)** | `session_ttl_seconds`, `cookie_secure`, `static_dir` |
| `src/gerenet/api/deps.py` | **Modificar (T3)** | `SESSION_COOKIE`, `Actor`, `require_actor`, `require_admin` |
| `tests/api/test_auth_api.py` | **Criar (T3)** | login/logout/me |
| `src/gerenet/domain/schemas.py` | **Modificar (T3/T7)** | `UserLoginIn`, `UserOut` (T3); `UserCreateIn`, `UserUpdateIn`, `UserPasswordIn`, `JobRunOut`, `DashboardOut`+nested (T6/T7) |
| `src/gerenet/api/auth.py` | **Criar (T3)** | `/api/v1/auth/*` |
| `src/gerenet/api/main.py` | **Modificar (T3–T9)** | includes (auth, users, dashboard, jobs), catch-all SPA |
| `src/gerenet/api/users.py` | **Criar (T4)** | `/api/v1/users*` admin |
| `tests/api/test_users_api.py` | **Criar (T4)** | CRUD admin + regras |
| `src/gerenet/api/routers/*.py` | **Modificar (T5)** | `require_actor` + ator real |
| `tests/api/test_actor_sessao.py` | **Criar (T5)** | dual auth, ator na trilha, visualizador |
| `src/gerenet/api/dashboard.py` | **Criar (T6)** | `GET /api/v1/dashboard` |
| `tests/api/test_dashboard_api.py` | **Criar (T6)** | agregados |
| `src/gerenet/api/jobs.py` | **Criar (T7)** | `GET /api/v1/jobs*` |
| `tests/api/test_jobs_api.py` | **Criar (T7)** | list/filtros/404 |
| `src/gerenet/cli/users.py` | **Criar (T8)** | `users create|set-password|list` |
| `src/gerenet/cli/main.py` | **Modificar (T8)** | registro do app |
| `tests/cli/test_cli_smoke.py` | **Modificar (T8)** | comandos users |
| `src/gerenet/api/static_spa.py` | **Criar (T9)** | montagem de `web/dist` + fallback |
| `tests/api/test_static_spa.py` | **Criar (T9)** | index/asset/cache/404 api |
| `CLAUDE.md` | **Modificar (T10)** | estado do repositório (ciclos A/C1) |
| `README.md` | **Modificar (T10)** | bootstrap do primeiro usuário + menção à web (C2) |

---

### Task 1: Modelos `User`/`UserSession` + migration + TRUNCATE do conftest

**Files:**
- Modify: `src/gerenet/domain/models.py` (após `BgpPrefixAuthorization`, fim do arquivo)
- Create: `alembic/versions/<rev>_users_sessions.py` (gerado via `alembic revision`)
- Modify: `tests/conftest.py:41` (lista TRUNCATE)
- Test: `tests/domain/test_users_service.py` (só o mapeamento/migration nesta task)

**Interfaces:**
- Consumes: padrão Base/SQLAlchemy do repo (`db.py`, `func.now()`).
- Produces: `models.USER_ROLES: tuple[str, ...]`, `models.User`, `models.UserSession` — consumidos por T2+.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/domain/test_users_service.py`:

```python
"""Mapeamento de User/UserSession + migration (T1)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from gerenet.domain import models


def test_user_model_grava_e_le(db_session) -> None:
    u = models.User(username="ana-teste", password_hash="scrypt$16384$8$1$00$00", role="operador")
    db_session.add(u)
    db_session.commit()

    achado = db_session.scalar(select(models.User).where(models.User.username == "ana-teste"))
    assert achado is not None
    assert achado.role == "operador"
    assert achado.is_active is True
    assert achado.id == 1


def test_user_session_model(db_session) -> None:
    u = models.User(username="carol", password_hash="x", role="operador")
    db_session.add(u)
    db_session.commit()

    s = models.UserSession(
        token_hash="a" * 64,
        user_id=u.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(s)
    db_session.commit()

    linha = db_session.scalar(
        select(models.UserSession).where(models.UserSession.token_hash == "a" * 64)
    )
    assert linha is not None and linha.user_id == u.id
```

- [ ] **Step 2: Rodar o teste para verificar que falha**

Run: `uv run pytest tests/domain/test_users_service.py -q`
Expected: FAIL com `AttributeError: module 'gerenet.domain.models' has no attribute 'User'`.

- [ ] **Step 3: Modelos — `USER_ROLES`, `User`, `UserSession`**

Em `src/gerenet/domain/models.py`, adicionar após `AUTH_ORIGIN` (L33) a constante (`Enum`, `Boolean`, `UniqueConstraint` e `func` já estão importados no topo do arquivo — não alterar imports):

```python
USER_ROLES = ("visualizador", "operador", "aprovador", "executor", "administrador")
```

E no fim do arquivo:

```python
class User(Base):
    """Usuário gerenet (login local, §17). Senha nunca fica fora de password_hash."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum(*USER_ROLES, name="user_role"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserSession(Base):
    """Sessão de login web — token opaco no cookie; banco guarda só o hash."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: Migration**

```bash
uv run alembic heads
```
Expected: exatamente um id (o head vigente — B2 já mergeado; se houver mais de um, parar e reportar).
Escrever esse id — será o `down_revision`.

```bash
uv run alembic revision -m "users and user_sessions"
```
Substituir TODO o corpo do arquivo gerado por:

```python
"""users and user_sessions

Revision ID: <id_gerado>
Revises: <head_vigente>
Create Date: 2026-09-04

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '<id_gerado>'
down_revision: str | Sequence[str] | None = '<head_vigente>'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Usuários do gerenet (§17) + sessões web (cookie opaco, hash no banco).

    Sem seed: o primeiro admin nasce via CLI (`gerenet users create`.
    """
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum(*USER_ROLES, name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("user_sessions")
    op.drop_table("users")
```
Atenção: a constante `USER_ROLES` precisa existir no módulo da migration — importar do repo é proibido (migrations imutáveis); definir no topo do arquivo da migration:

```python
USER_ROLES = ("visualizador", "operador", "aprovador", "executor", "administrador")
```
(adicionar à migration, acima de `revision`).

- [ ] **Step 5: Rodar a migration no banco de teste e ver o teste passar**

```bash
GERENET_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test uv run alembic upgrade head
uv run pytest tests/domain/test_users_service.py -q
```
Expected: PASS.

- [ ] **Step 6: Conftest — TRUNCATE inclui as tabelas novas**

Em `tests/conftest.py`, trocar a lista do TRUNCATE (linha 41):

```python
            "TRUNCATE audit_events, user_sessions, users, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations RESTART IDENTITY CASCADE"
```

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/models.py alembic/versions tests/conftest.py tests/domain/test_users_service.py
git commit -m "feat(soT): usuarios e sessoes de login (ciclo C1)

Tabelas users/user_sessions + enum user_role em migration unica;
TRUNCATE do conftest cobre as tabelas novas.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Serviço de usuários — hash scrypt, CRUD, autenticação e sessões

**Files:**
- Create: `src/gerenet/domain/services/users.py`
- Modify: `tests/domain/test_users_service.py` (adicionar os testes do serviço)

**Interfaces:**
- Consumes: `models.User/UserSession` (T1), `registrar` de `domain.audit`, `GerenetError/NotFoundError/ConflictError/ValidationError` de `domain.services.errors`, `Settings` de `config`.
- Produces:
  - `_hash_password(senha: str) -> str` e `verificar_senha(senha: str, armazenado: str) -> bool` (privado/público — exposto para testes: `usuario_hash` e `usuario_verifica`? Não: expor `hash_password`/`verify_password` públicos para goldens da T2)
  - `create_user(session, *, username, password, role, actor="cli") -> models.User`
  - `list_users(session, include_disabled=False) -> list[models.User]`
  - `update_user(session, user_id, *, username=None, role=None, is_active=None, actor="cli") -> models.User`
  - `reset_password(session, user_id, *, password, actor="cli") -> models.User`
  - `autenticar(session, username, password) -> models.User | None`
  - `iniciar_sessao(session, usuario, *, settings) -> str`
  - `validar_sessao(session, token) -> models.User | None` (apaga sessão expirada)
  - `encerrar_sessao(session, token) -> models.User | None`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao fim de `tests/domain/test_users_service.py`:

```python
"""Serviço de usuários — hash scrypt, CRUD, autenticação e sessões."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.services import users as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


def test_hash_password_formato_salt_unico() -> None:
    h1 = svc.hash_password("senha-super-8")
    h2 = svc.hash_password("senha-super-8")
    assert h1 != h2  # salt aleatório
    assert h1.startswith("scrypt$16384$8$1$") and len(h1.split("$")) == 6


def test_verify_password_ok_e_falha_corrompido() -> None:
    h = svc.hash_password("senha-super-8")
    assert svc.verify_password("senha-super-8", h) is True
    assert svc.verify_password("outra-senha", h) is False
    assert svc.verify_password("qualquer", "lixo") is False
    assert svc.verify_password("qualquer", "scrypt$16384$8$1$zz$zz") is False


def test_create_user_valida_e_audita(db_session) -> None:
    u = svc.create_user(db_session, username="op1", password="senha-super-8", role="operador", actor="cli")
    assert u.id == 1 and u.is_active is True
    assert u.password_hash != "senha-super-8" and u.password_hash.startswith("scrypt$")

    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "user.create")
    )
    assert evento is not None and evento.actor == "cli"
    assert "password" not in db_session.query(models.AuditEvent).filter(
        models.AuditEvent.type == "user.create"
    ).one().details.get("depois", {})

    with pytest.raises(ConflictError):
        svc.create_user(db_session, username="op1", password="senha-super-8", role="operador")
    with pytest.raises(ValidationError):
        svc.create_user(db_session, username="curto", password="123", role="operador")
    with pytest.raises(ValidationError):
        svc.create_user(db_session, username="nao-existe-role-x", password="senha-super-8", role="root")


def test_list_users_sem_inativos(db_session) -> None:
    u = svc.create_user(db_session, username="ops", password="senha-super-8", role="operador")
    svc.create_user(db_session, username="vis", password="senha-super-8", role="visualizador")
    svc.update_user(db_session, u.id, is_active=False, actor="cli")

    assert [u.username for u in svc.list_users(db_session)] == ["vis"]
    assert {u.username for u in svc.list_users(db_session, include_disabled=True)} == {"ops", "vis"}


def test_update_user_audita_e_protege_duplicidade(db_session) -> None:
    svc.create_user(db_session, username="ana", password="senha-super-8", role="operador")
    svc.create_user(db_session, username="bruno", password="senha-super-8", role="operador")
    ana = svc.list_users(db_session)[0]

    atualizado = svc.update_user(db_session, ana.id, role="aprovador", actor="cli")
    assert atualizado.role == "aprovador"

    with pytest.raises(NotFoundError):
        svc.update_user(db_session, 9999, username="x")
    with pytest.raises(ConflictError):
        svc.update_user(db_session, ana.id, username="bruno")
    with pytest.raises(ValidationError):
        svc.update_user(db_session, ana.id, role="super")

    trilha = db_session.scalar(
        select(models.AuditEvent).where(
            models.AuditEvent.type == "user.update", models.AuditEvent.actor == "cli"
        )
    )
    assert trilha.details["antes"]["role"] == "operador"
    assert trilha.details["depois"] == {"role": "aprovador"}


def test_reset_password_invalida_sessoes(db_session) -> None:
    u = svc.create_user(db_session, username="mario", password="senha-super-8", role="operador")
    settings = Settings(session_ttl_seconds=3600, _env_file=None)
    token = svc.iniciar_sessao(db_session, u, settings=settings)
    assert svc.validar_sessao(db_session, token) is not None

    svc.reset_password(db_session, u.id, password="outra-super-8", actor="cli")
    old = svc.validar_sessao(db_session, token)
    assert old is None and svc.verify_password("outra-super-8", u.password_hash)


def test_autenticar_inativos_e_senha_errada(db_session) -> None:
    u = svc.create_user(db_session, username="ze", password="senha-super-8", role="operador")
    assert svc.autenticar(db_session, "ze", "senha-super-8") is not None
    assert svc.autenticar(db_session, "ze", "errada-8") is None
    svc.update_user(db_session, u.id, is_active=False, actor="cli")
    assert svc.autenticar(db_session, "ze", "senha-super-8") is None


def test_sessoes_validar_encerrar_e_expirada(db_session) -> None:
    u = svc.create_user(db_session, username="ana2", password="senha-super-8", role="operador")
    settings = Settings(session_ttl_seconds=3600, _env_file=None)
    token = svc.iniciar_sessao(db_session, u, settings=settings)

    assert svc.validar_sessao(db_session, token) == u
    assert svc.validar_sessao(db_session, "token-inventado") is None

    usuario = svc.encerrar_sessao(db_session, token)
    assert usuario is not None and usuario.username == "ana2"
    assert svc.validar_sessao(db_session, token) is None

    t2 = svc.iniciar_sessao(db_session, u, settings=settings)
    sess = db_session.scalar(select(models.UserSession))
    sess.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    assert svc.validar_sessao(db_session, t2) is None  # expirada → None (e apagada lazy)
    assert db_session.scalar(select(models.UserSession)) is None
```

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/domain/test_users_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.domain.services.users'`.

- [ ] **Step 3: Implementar `src/gerenet/domain/services/users.py`**

```python
"""Usuários e sessões (login local, §17).

Hash de senha: scrypt da stdlib (nenhuma dependência nova). Formato:
``scrypt$N$r$p$salt_hex$key_hex``. Sessões: token opaco no cookie; no banco
só o sha256 hex do token; expirada é apagada lazy na primeira leitura.
Segredos: senha e hash nunca aparecem em log/resposta/trilha (o ``mascarar``
de domain/audit cobre as chaves sensíveis da auditoria).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_SENHA_MINIMA = 8


def hash_password(senha: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    chave = hashlib.scrypt(senha.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_BYTES)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${chave.hex()}"


def verify_password(senha: str, armazenado: str) -> bool:
    """Verifica contra o formato scrypt; formato inválido → False (sem exceção)."""
    try:
        prefixo, n_s, r_s, p_s, salt_hex, chave_hex = armazenado.split("$")
        if prefixo != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        chave = hashlib.scrypt(
            senha.encode(), salt=salt, n=int(n_s), r=int(r_s), p=int(p_s), dklen=_KEY_BYTES
        )
        return hmac.compare_digest(chave.hex(), chave_hex)
    except (ValueError, TypeError):
        return False


def _valida_senha(senha: str) -> None:
    if len(senha) < _SENHA_MINIMA:
        raise ValidationError(f"Senha deve ter pelo menos {_SENHA_MINIMA} caracteres.")


def create_user(
    session: Session, *, username: str, password: str, role: str, actor: str = "cli"
) -> models.User:
    if not 1 <= len(username) <= 64:
        raise ValidationError("Username deve ter entre 1 e 64 caracteres.")
    _valida_senha(password)
    if role not in models.USER_ROLES:
        raise ValidationError("Perfil inválido.")
    if session.scalar(select(models.User).where(models.User.username == username)) is not None:
        raise ConflictError("Username já existe.")
    usuario = models.User(username=username, password_hash=hash_password(password), role=role)
    session.add(usuario)
    session.flush()
    registrar(
        session,
        tipo="user.create",
        ator=actor,
        objeto="user",
        objeto_id=usuario.id,
        depois={"username": usuario.username, "role": usuario.role},
    )
    return usuario


def list_users(session: Session, include_disabled: bool = False) -> list[models.User]:
    stmt = select(models.User).order_by(models.User.username)
    if not include_disabled:
        stmt = stmt.where(models.User.is_active.is_(True))
    return list(session.scalars(stmt))


def update_user(
    session: Session,
    user_id: int,
    *,
    username: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    actor: str = "cli",
) -> models.User:
    usuario = session.get(models.User, user_id)
    if usuario is None:
        raise NotFoundError("Usuário não encontrado.")
    antes: dict = {}
    depois: dict = {}
    if username is not None:
        if not 1 <= len(username) <= 64:
            raise ValidationError("Username deve ter entre 1 e 64 caracteres.")
        ocupado = session.scalar(
            select(models.User).where(models.User.username == username, models.User.id != user_id)
        )
        if ocupado is not None:
            raise ConflictError("Username já existe.")
        antes["username"] = usuario.username
        usuario.username = username
        depois["username"] = username
    if role is not None:
        if role not in models.USER_ROLES:
            raise ValidationError("Perfil inválido.")
        antes["role"] = usuario.role
        usuario.role = role
        depois["role"] = role
    if is_active is not None:
        antes["is_active"] = usuario.is_active
        usuario.is_active = is_active
        depois["is_active"] = is_active
    registrar(
        session,
        tipo="user.update",
        ator=actor,
        objeto="user",
        objeto_id=usuario.id,
        antes=antes,
        depois=depois,
    )
    return usuario


def reset_password(session: Session, user_id: int, *, password: str, actor: str = "cli") -> models.User:
    _valida_senha(password)
    usuario = session.get(models.User, user_id)
    if usuario is None:
        raise NotFoundError("Usuário não encontrado.")
    # Segurança: reset invalida todas as sessões do usuário (spec §4.5).
    session.execute(delete(models.UserSession).where(models.UserSession.user_id == user_id))
    usuario.password_hash = hash_password(password)
    registrar(
        session,
        tipo="user.reset_password",
        ator=actor,
        objeto="user",
        objeto_id=usuario.id,
        depois={"password_reset": True},
    )
    return usuario


def autenticar(session: Session, username: str, password: str) -> models.User | None:
    """Valida credenciais; None para usuário inexistente, inativo ou senha errada."""
    usuario = session.scalar(select(models.User).where(models.User.username == username))
    if usuario is None or not usuario.is_active or not verify_password(password, usuario.password_hash):
        return None
    return usuario


def iniciar_sessao(session: Session, usuario: models.User, *, settings: Settings) -> str:
    """Cria a sessão e devolve o token (seu sha256 fica no banco)."""
    token = secrets.token_urlsafe(32)
    expira = datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)
    session.add(
        models.UserSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=usuario.id, expires_at=expira)
    )
    return token


def validar_sessao(session: Session, token: str) -> models.User | None:
    linha = session.execute(
        select(models.UserSession, models.User)
        .join(models.User, models.UserSession.user_id == models.User.id)
        .where(models.UserSession.token_hash == hashlib.sha256(token.encode()).hexdigest())
    ).first()
    if linha is None:
        return None
    sessao, usuario = linha
    if sessao.expires_at <= datetime.now(timezone.utc):
        session.delete(sessao)
        session.commit()
        return None
    return usuario


def encerrar_sessao(session: Session, token: str) -> models.User | None:
    """Apaga a sessão; devolve o usuário para a auditoria (None se token inválido)."""
    linha = session.execute(
        select(models.UserSession, models.User)
        .join(models.User, models.UserSession.user_id == models.User.id)
        .where(models.UserSession.token_hash == hashlib.sha256(token.encode()).hexdigest())
    ).first()
    if linha is None:
        return None
    sessao, usuario = linha
    session.delete(sessao)
    return usuario
```

Nota: `gerenet.config.Settings` é usado só como tipo (`settings.session_ttl_seconds`).

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/domain/test_users_service.py -q`
Expected: PASS.

- [ ] **Step 5: Ruff + commit**

```bash
uv run ruff check src/gerenet/domain/services/users.py tests/domain/test_users_service.py
git add src/gerenet/domain/services/users.py tests/domain/test_users_service.py
git commit -m "feat(auth): servico de usuarios — hash scrypt, CRUD, autenticacao e sessoes

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Settings novos + `require_actor`/`require_admin` + router de auth

**Files:**
- Modify: `src/gerenet/config.py`
- Modify: `src/gerenet/api/deps.py`
- Modify: `src/gerenet/domain/schemas.py` (UserLoginIn, UserOut)
- Create: `src/gerenet/api/auth.py`
- Modify: `src/gerenet/api/main.py` (include auth)
- Create: `tests/api/test_auth_api.py`

**Interfaces:**
- Consumes: serviço `users` (T2), models (T1).
- Produces: `api.deps.SESSION_COOKIE`, `api.deps.Actor(usuario, nome)`, `api.deps.require_actor`, `api.deps.require_admin`, `schemas.UserLoginIn`, `schemas.UserOut`; rotas `/api/v1/auth/login|logout|me` — consumidos por T4–T9 e pela SPA.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/api/test_auth_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.services import users as svc


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", session_ttl_seconds=3600, _env_file=None))
    return TestClient(create_app())


def _cria_usuario(db_session, username="op1", role="operador") -> models.User:
    return svc.create_user(
        db_session, username=username, password="senha-super-8", role=role, actor="cli"
    )


def test_login_ok_seta_cookie_e_audita(client: TestClient, db_session) -> None:
    _cria_usuario(db_session)
    resp = client.post("/api/v1/auth/login", json={"username": "op1", "password": "senha-super-8"})
    assert resp.status_code == 200
    corpo = resp.json()
    assert set(corpo) == {"id", "username", "role", "is_active", "last_login_at", "created_at"}
    assert corpo["role"] == "operador"
    cookie = resp.headers.get("set-cookie", "")
    assert "gerenet_sess=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie

    trilha = db_session.scalar(select(models.AuditEvent).where(models.AuditEvent.type == "auth.login"))
    assert trilha is not None and trilha.actor == "op1"


def test_login_falha_mensagem_unica_e_audita(client: TestClient, db_session) -> None:
    _cria_usuario(db_session)
    for payload in ({"username": "op1", "password": "errada-8"}, {"username": "fantasma", "password": "senha-super-8"}):
        resp = client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Usuário ou senha inválidos."}

    falhas = db_session.query(models.AuditEvent).filter(models.AuditEvent.type == "auth.login_failed").all()
    assert len(falhas) == 2
    assert {e.actor for e in falhas} == {"op1", "fantasma"}


def test_me_com_sessao_e_sem(client: TestClient, db_session) -> None:
    _cria_usuario(db_session)
    client.post("/api/v1/auth/login", json={"username": "op1", "password": "senha-super-8"})
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200 and resp.json()["username"] == "op1"

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    # /me é web-only: X-Api-Key não vale aqui (mensagem "Não autenticado.")
    resp_key = client.get("/api/v1/auth/me", headers={"X-API-Key": "teste-key"})
    assert resp_key.status_code == 401 and resp_key.json() == {"detail": "Não autenticado."}
```

Nota: o teste de **sessão expirada via cookie em rota protegida** só é verificável depois de o `require_actor` valer nas rotas existentes — ele vive na **T5** (comportamento dual). A T3 falha por rotas de auth inexistentes — esperado no Step 2.

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/api/test_auth_api.py -q`
Expected: FAIL no modo atual (rotas de auth inexistentes → 404; `require_actor` não existe).

- [ ] **Step 3: Settings**

Em `src/gerenet/config.py`, adicionar ao `Settings` (depois de `lock_ttl_seconds`):

```python
    session_ttl_seconds: int = 28800  # TTL do cookie de sessão web (§4.2)
    cookie_secure: bool = False  # True em produção sob HTTPS
    static_dir: Path = Path("web/dist")  # build da SPA (ciclo C2)
```

- [ ] **Step 4: `deps.py` — `SessionDep`, `Actor`, `require_actor`, `require_admin`**

Substituir TODO o conteúdo de `src/gerenet/api/deps.py` por:

```python
import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from gerenet.config import Settings, get_settings
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.services import users as svc

SESSION_COOKIE = "gerenet_sess"

SessionDep = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class Actor:
    """Quem faz a chamada: usuário de sessão web ou a chave de API (nome 'api')."""

    usuario: models.User | None
    nome: str


def require_actor(request: Request, session: SessionDep, settings: SettingsDep) -> Actor:
    """Auth dual: cookie de sessão (web) OU X-Api-Key (CLI/automações).

    Perfil Visualizador é somente leitura (spec §4.3): métodos de escrita → 403.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if token is not None:
        usuario = svc.validar_sessao(session, token)
        if usuario is None:
            raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.")
        if not usuario.is_active:
            raise HTTPException(status_code=403, detail="Usuário desativado.")
        if usuario.role == "visualizador" and request.method not in ("GET", "HEAD", "OPTIONS"):
            raise HTTPException(status_code=403, detail="Perfil Visualizador permite apenas leitura.")
        return Actor(usuario=usuario, nome=usuario.username)
    x_api_key = request.headers.get("x-api-key")
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.")
    return Actor(usuario=None, nome="api")


def require_admin(actor: Annotated[Actor, Depends(require_actor)]) -> Actor:
    """Somente Administrador (usuário autenticado por sessão, §4.4)."""
    if actor.usuario is None or actor.usuario.role != "administrador":
        raise HTTPException(status_code=403, detail="Somente administradores.")
    return actor
```

Nota: adicionar também `models` import? Já importado. `settings`/`session` — ok. Remover o import de `secrets`? permanece (compare_digest).

- [ ] **Step 5: Schemas**

Em `src/gerenet/domain/schemas.py`, adicionar no fim:

```python
class UserLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
```

- [ ] **Step 6: Router `src/gerenet/api/auth.py`**

Arquivo completo (os três endpoints; `UserOut` exige `from_attributes` — já no schema):

```python
"""Autenticação local (spec ciclo C §4.2) — login, logout e sessão atual.

Senha nunca vai a log/resposta; falha de login não distingue usuário
inexistente, inativo ou senha errada (mensagem única).
"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from gerenet.api.deps import SESSION_COOKIE, SessionDep
from gerenet.config import Settings, get_settings
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import UserLoginIn, UserOut
from gerenet.domain.services import users as svc

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _usuario_atual(request: Request, session: SessionDep) -> models.User:
    """Usuário da sessão do cookie para /me (web-only — X-Api-Key não vale aqui)."""
    token = request.cookies.get(SESSION_COOKIE)
    usuario = svc.validar_sessao(session, token) if token else None
    if usuario is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    if not usuario.is_active:
        raise HTTPException(status_code=403, detail="Usuário desativado.")
    return usuario


@router.post("/login", response_model=UserOut)
def login(
    data: UserLoginIn,
    response: Response,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> models.User:
    usuario = svc.autenticar(session, data.username, data.password)
    if usuario is None:
        registrar(
            session, tipo="auth.login_failed", ator=data.username, objeto="auth", objeto_id=0
        )
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    token = svc.iniciar_sessao(session, usuario, settings=settings)
    usuario.last_login_at = datetime.now(timezone.utc)
    registrar(
        session, tipo="auth.login", ator=usuario.username, objeto="auth", objeto_id=usuario.id
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return usuario


@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDep) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    usuario = svc.encerrar_sessao(session, token) if token else None
    if usuario is not None:
        registrar(
            session, tipo="auth.logout", ator=usuario.username, objeto="auth", objeto_id=usuario.id
        )
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=UserOut)
def me(request: Request, session: SessionDep) -> models.User:
    return _usuario_atual(request, session)
```

Rulings do plano (a spec é a autoridade; dois pontos resolvem ambiguidades dela):
- `/me` não usa `require_actor` — a spec §4.2 exige 401 "Não autenticado." sem sessão (o 401 genérico de chave seria contraditório num endpoint web-only; X-Api-Key não vale em `/me`).
- `objeto_id=0` nos `auth.login_failed`: trilha sem FK obrigatória; nunca se deixa de registrar falha.

- [ ] **Step 7: `main.py` — include**

Em `src/gerenet/api/main.py`, importar e incluir (junto dos demais):

```python
from gerenet.api import auth
...
    app.include_router(auth.router)
```

- [ ] **Step 8: Rodar os testes**

Run: `uv run pytest tests/api/test_auth_api.py -q`
Expected: PASS. (Arquivo da T1/T2 de domain deve continuar verde: rodar a suíte toda ao final — T5 fará a troca dos routers.)

- [ ] **Step 9: Commit**

```bash
git add src/gerenet/config.py src/gerenet/api/deps.py src/gerenet/domain/schemas.py src/gerenet/api/auth.py src/gerenet/api/main.py tests/api/test_auth_api.py
git commit -m "feat(auth): login local — cookie de sessao, require_actor dual, /auth/login|logout|me

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: API de usuários (admin) — `/api/v1/users`

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`UserCreateIn`, `UserUpdateIn`, `UserPasswordIn`)
- Create: `src/gerenet/api/users.py`
- Modify: `src/gerenet/api/main.py` (include)
- Create: `tests/api/test_users_api.py`

**Interfaces:**
- Consumes: `require_admin`/`Actor` (T3), serviço `users` (T2).
- Produces: rotas `GET/POST /api/v1/users`, `PATCH /api/v1/users/{id}`, `POST /api/v1/users/{id}/password` — consumidas pela SPA (C2) e pelo CLI? não (CLI é local).

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/api/test_users_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.services import users as svc


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _admin(db_session) -> None:
    svc.create_user(db_session, username="boss", password="senha-super-8", role="administrador", actor="cli")


def _login(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"username": "boss", "password": "senha-super-8"})


def test_somente_admin_pode_listar(client: TestClient, db_session) -> None:
    assert client.get("/api/v1/users", headers=_auth()).status_code == 403
    svc.create_user(db_session, username="posse", password="senha-super-8", role="operador", actor="cli")
    _admin(db_session)
    _login(client)
    lista = client.get("/api/v1/users").json()
    assert [u["username"] for u in lista] == ["boss", "posse"]
    assert "password_hash" not in lista[0]


def test_criar_audita_listar_com_include_disabled(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    resp = client.post(
        "/api/v1/users", json={"username": "vis3", "password": "senha-super-8", "role": "visualizador"}
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "visualizador"

    dup = client.post(
        "/api/v1/users", json={"username": "vis3", "password": "senha-super-8", "role": "visualizador"}
    )
    assert dup.status_code == 409

    curta = client.post(
        "/api/v1/users", json={"username": "curto4", "password": "123", "role": "operador"}
    )
    assert curta.status_code == 400

    dados = client.get("/api/v1/users").json()
    assert [u["username"] for u in dados] == ["boss", "vis3"]
    assert client.get("/api/v1/users?include_disabled=true").status_code == 200


def test_patch_regras(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    alvo = client.post(
        "/api/v1/users", json={"username": "ana", "password": "senha-super-8", "role": "operador"}
    ).json()
    uid = alvo["id"]

    resp = client.patch(f"/api/v1/users/{uid}", json={"role": "aprovador"})
    assert resp.status_code == 200 and resp.json()["role"] == "aprovador"

    assert client.patch(f"/api/v1/users/9999", json={"is_active": True}).status_code == 404

    outros = client.post(
        "/api/v1/users", json={"username": "bela", "password": "senha-super-8", "role": "operador"}
    ).json()
    assert client.patch(f"/api/v1/users/{outros['id']}", json={"username": "ana"}).status_code == 409


def test_nao_alterar_propria_conta(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    me = client.get("/api/v1/auth/me").json()
    resp = client.patch(f"/api/v1/users/{me['id']}", json={"role": "operador"})
    assert resp.status_code == 403
    assert "própria conta" in resp.json()["detail"]
    # username da própria conta é permitido
    assert client.patch(f"/api/v1/users/{me['id']}", json={"username": "boss2"}).status_code == 200


def test_reset_senha_invalida_antiga(client: TestClient, db_session) -> None:
    _admin(db_session)
    _login(client)
    alvo = client.post(
        "/api/v1/users", json={"username": "carol", "password": "senha-super-8", "role": "operador"}
    ).json()
    uid = alvo["id"]

    assert client.post(f"/api/v1/users/{uid}/password", json={"password": "nova-super-9"}).status_code == 204
    assert client.post(f"/api/v1/users/{uid}/password", json={"password": "curta"}).status_code == 400

    client.post("/api/v1/auth/logout")
    login = client.post("/api/v1/auth/login", json={"username": "carol", "password": "nova-super-9"})
    assert login.status_code == 200


def test_desativar_invalida_sessao(client: TestClient, db_session) -> None:
    _admin(db_session)
    client.post("/api/v1/auth/login", json={"username": "boss", "password": "senha-super-8"})
    operador = client.post(
        "/api/v1/users", json={"username": "diogo", "password": "senha-super-8", "role": "operador"}
    ).json()

    # diogo loga no próprio client só com cookie
    diogo = TestClient(create_app())
    diogo.post("/api/v1/auth/login", json={"username": "diogo", "password": "senha-super-8"})
    token = diogo.cookies.get("gerenet_sess")
    assert token is not None

    # admin desativa o diogo
    assert client.patch(f"/api/v1/users/{operador['id']}", json={"is_active": False}).status_code == 200

    # sessão existente do diogo passa a 403 (usuário desativado) e login novo → 401
    diogo.cookies.clear()
    diogo.cookies.set("gerenet_sess", token)
    resp = diogo.get("/api/v1/devices")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Usuário desativado."}
    with TestClient(create_app()) as diogo:
        diogo.post("/api/v1/auth/login", json={"username": "diogo", "password": "senha-super-8"})
        token = diogo.cookies.get("gerenet_sess")
        assert token is not None

        assert client.patch(f"/api/v1/users/{operador['id']}", json={"is_active": False}).status_code == 200

        # o cookie do diogo (da sessão do logon próprio) agora é rejeitado
        resp = diogo.get("/api/v1/devices")
        assert resp.status_code == 403
        assert resp.json() == {"detail": "Usuário desativado."}
        login = diogo.post("/api/v1/auth/login", json={"username": "diogo", "password": "senha-super-8"})
        assert login.status_code == 401
```

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/api/test_users_api.py -q`
Expected: FAIL (rotas inexistentes).

- [ ] **Step 3: Schemas**

Adicionar em `src/gerenet/domain/schemas.py`:

```python
class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str  # sem limite pydantic: validação de tamanho é do serviço (padrão asn do OrganizationCreate)
    role: str  # validação em serviço (padrão do catálogo; 422 só no formato)


class UserUpdateIn(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    role: str | None = None
    is_active: bool | None = None


class UserPasswordIn(BaseModel):
    password: str
```

- [ ] **Step 4: Router `src/gerenet/api/users.py`**

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from gerenet.api.deps import Actor, SessionDep, require_admin
from gerenet.domain.schemas import UserCreateIn, UserOut, UserPasswordIn, UserUpdateIn
from gerenet.domain.services import users as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/users", tags=["users"])

AdminDep = Annotated[Actor, Depends(require_admin)]


@router.get("", response_model=list[UserOut])
def listar(
    actor: AdminDep,
    session: SessionDep,
    include_disabled: bool = False,
) -> list:
    return svc.list_users(session, include_disabled=include_disabled)


@router.post("", response_model=UserOut, status_code=201)
def criar(data: UserCreateIn, actor: AdminDep, session: SessionDep) -> object:
    try:
        return svc.create_user(
            session, username=data.username, password=data.password, role=data.role, actor=actor.nome
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserOut)
def atualizar(data: UserUpdateIn, user_id: int, actor: AdminDep, session: SessionDep) -> object:
    if actor.usuario is not None and actor.usuario.id == user_id and (data.role is not None or data.is_active is not None):
        raise HTTPException(status_code=403, detail="Não é possível alterar a própria conta.")
    try:
        return svc.update_user(
            session,
            user_id,
            username=data.username,
            role=data.role,
            is_active=data.is_active,
            actor=actor.nome,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{user_id}/password", status_code=204)
def resetar_senha(data: UserPasswordIn, user_id: int, actor: AdminDep, session: SessionDep) -> None:
    try:
        svc.reset_password(session, user_id, password=data.password, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 5: `main.py` — include**

```python
from gerenet.api import auth, users
...
    app.include_router(users.router)
```

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/api/test_users_api.py -q` e `uv run pytest tests/api -q`
Expected: PASS (a troca de ator acontece na T5 — NÃO alterar routers ainda; `require_admin` só existe em users/auth).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/api/users.py src/gerenet/api/main.py tests/api/test_users_api.py
git commit -m "feat(users): API admin de usuarios (CRUD parcial, sem exclusao fisica)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: `require_actor` em todos os routers + ator real na auditoria

**Files:**
- Modify: `src/gerenet/api/routers/devices.py`, `sites.py`, `organizations.py`, `contacts.py`, `circuits.py`, `bgp_sessions.py`, `policy_profiles.py`, `prefix_authorizations.py`, `audit_events.py`
- Create: `tests/api/test_actor_sessao.py`

**Interfaces:**
- Consumes: `require_actor`/`Actor` (T3).
- Produces: todos os endpoints aceitam cookie de sessão (web) além da chave; escritas via usuário gravam `actor=username` na trilha; `POST /api/v1/devices/{id}/collect` passa `actor=actor.nome`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/api/test_actor_sessao.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.services import users as svc


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _cria_e_loga(client: TestClient, db_session, username="operador1", role="operador") -> None:
    svc.create_user(db_session, username=username, password="senha-super-8", role=role, actor="cli")
    client.post("/api/v1/auth/login", json={"username": username, "password": "senha-super-8"})


def test_get_por_cookie_sem_chave(client: TestClient, db_session) -> None:
    _cria_e_loga(client, db_session)
    resp = client.get("/api/v1/devices")  # sem X-API-Key
    assert resp.status_code == 200


def test_escrita_por_cookie_audita_usuario(client: TestClient, db_session) -> None:
    _cria_e_loga(client, db_session, username="dona")
    resp = client.post("/api/v1/sites", json={"name": "POP-WEB", "city": "Recife", "uf": "PE"})
    assert resp.status_code == 201
    trilha = client.get("/api/v1/audit-events?tipo=site.create").json()
    assert trilha[0]["actor"] == "dona"


def test_visualizador_nao_escreve(client: TestClient, db_session) -> None:
    _cria_e_loga(client, db_session, username="v1", role="visualizador")
    assert client.get("/api/v1/devices").status_code == 200
    resp = client.post("/api/v1/sites", json={"name": "POP-N", "city": "Niterói", "uf": "RJ"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Perfil Visualizador permite apenas leitura."}


def test_chave_de_api_continua_escrevendo_como_api(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/sites",
        json={"name": "POP-KEY", "city": "Brasília", "uf": "DF"},
        headers={"X-API-Key": "teste-key"},
    )
    assert resp.status_code == 201
    trilha = client.get("/api/v1/audit-events?tipo=site.create", headers={"X-API-Key": "teste-key"}).json()
    assert trilha[0]["actor"] == "api"


def test_sessao_expirada_e_apagada_lazy(client: TestClient, db_session) -> None:
    from datetime import datetime, timedelta, timezone

    from gerenet.config import Settings as S
    from gerenet.domain import models as m
    from sqlalchemy import select as s

    _cria_e_loga(client, db_session, username="contora")
    token = client.cookies.get("gerenet_sess")
    assert token is not None

    u = db_session.scalar(s(m.User).where(m.User.username == "contora"))
    sessao = db_session.scalar(s(m.UserSession).where(m.UserSession.user_id == u.id))
    sessao.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    resp = client.get("/api/v1/devices")  # sem X-Api-Key — só o cookie expirado
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Chave de API ausente ou inválida."}
    assert db_session.scalar(s(m.UserSession)) is None  # apagada na leitura (lazy)
```

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/api/test_actor_sessao.py -q`
Expected: FAIL — login funciona (T3), mas `GET /devices` por cookie sobe 401 (`require_api_key` não olha cookie). A correção é a troca abaixo.

- [ ] **Step 3: Trocar os routers — imports e deps**

Em **cada** arquivo de `src/gerenet/api/routers/*.py`:

1. Trocar `from gerenet.api.deps import require_api_key` por `from gerenet.api.deps import Actor, require_actor, SessionDep` — se o arquivo já tem `SessionDep` local, trocar apenas a importação de `require_api_key` (o `Actor` só onde há `actor=`).

2. Trocar toda ocorrência de `dependencies=[Depends(require_api_key)]` por `dependencies=[Depends(require_actor)]` (APIRouter de devices, snap_router, sites, organizations, downstreams_router, contacts, circuits, bgp_sessions, policy_profiles, prefix_authorizations, audit_events).

3. Nos handlers que passam `actor="api"` (localizar: `grep -rn 'actor="api"' src/gerenet/api/routers/`) inserir o parâmetro de dependência e o valor:

Antes (ex. `routers/sites.py` — mesmo padrão em `create_site`/`update_site`/`disable_site` e demais arquivos):

```python
def criar(data: SiteCreate, session: SessionDep) -> object:
    try:
        return svc.create_site(session, data, actor="api")
```

Depois:

```python
def criar(data: SiteCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> object:
    try:
        return svc.create_site(session, data, actor=actor.nome)
```

Arquivos e ocorrências (lista da data do plano — revalidar com o grep acima):
- `routers/devices.py`: `criar` (L30) e `coletar` (L87) — em `coletar`, trocar também o `actor="api"` do `enqueue_collect` por `actor=actor.nome`; origin permanece `"api"`.
- `routers/bgp_sessions.py`: sessões `create`/`update`/`disable`/`password` (L42, L66-67, L92) — 5 usos.
- `routers/circuits.py`: `create_circuit`, `disable_circuit`, `update_circuit`, `reservar_circuito` (L66, L90-91, L108).
- `routers/contacts.py`: `create_contact`, `disable_contact`, `update_contact` (L25, L49-50).
- `routers/organizations.py`, `routers/sites.py`, `routers/prefix_authorizations.py`: mesmos 3 usos (create/update/disable) cada.
- `routers/policy_profiles.py`, `routers/audit_events.py`: só a troca do import e da dependencies (sem `actor=`).

Exemplo completo de um handler com `Annotated` já importado no arquivo (`devices.py` já tem `from typing import Annotated`):

```python
@router.post("/{device_id}/collect", status_code=202)
def coletar(device_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]) -> dict:
    try:
        svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    resultado = enqueue_collect(device_id, actor=actor.nome, origin="api")
    if not resultado["queued"]:
        raise HTTPException(status_code=409, detail=resultado["message"])
    return resultado
```

Atenção: a ordem dos parâmetros com valor default — `SessionDep` e `actor` são `Annotated`/Depends (sem default), podem ir depois dos `data: SiteCreate`. Manter a ordem atual dos handlers, acrescentando `actor` ao fim.

- [ ] **Step 4: Rodar os testes novos e a suíte**

Run: `uv run pytest tests/api/test_actor_sessao.py -q` e depois `uv run pytest -q`
Expected: PASS — a suíte toda (os testes existentes usam X-Api-Key e seguem com ator `"api"`; `test_collect_api` espera `enqueue_collect(dev.id, actor="api", origin="api")` — verde pois a chave não muda o ator).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/api/ tests/api/test_actor_sessao.py
git commit -m "feat(auth): requster_actor em todas as rotas — cookie OU chave, ator real na auditoria

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```
(Ajustar palavra do título para o padrão se preferir: `feat(auth): require_actor em todas as rotas — cookie OU chave, ator real na auditoria`.)

---

### Task 6: Dashboard — `GET /api/v1/dashboard`

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`DashboardOut` + nested)
- Create: `src/gerenet/api/dashboard.py`
- Modify: `src/gerenet/api/main.py` (include)
- Create: `tests/api/test_dashboard_api.py`

**Interfaces:**
- Consumes: modelos (T1), `require_actor` (T3), `AuditEventOut` (existente).
- Produces: `DashboardOut` — consumido pela SPA (C2).

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/api/test_dashboard_api.py`:

```python
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session) -> dict:
    """Site, org, switch, 2 NE8000 + circuito + 2 sessoes + vlans/prefixos (padrão dos testes BGP)."""
    site = create_site(db_session, SiteCreate(name="pop-dash"), actor="cli")
    env = {
        "site_id": site.id,
        "org_id": create_organization(
            db_session, OrganizationCreate(name="Cliente Dash", asn=64512), actor="cli"
        ).id,
    }
    sw = create_device(
        db_session, DeviceCreate(name="sw-dash", management_address="10.8.2.1"), actor="cli"
    )
    ne1 = create_device(
        db_session, DeviceCreate(name="ne8k-dash1", management_address="10.8.2.2", asn=64600), actor="cli"
    )
    ne2 = create_device(
        db_session, DeviceCreate(name="ne8k-dash2", management_address="10.8.2.3", asn=64601), actor="cli"
    )
    env.update({"sw_id": sw.id, "ne1_id": ne1.id, "ne2_id": ne2.id})
    circ = models.Circuit(
        code="DASH-01",
        organization_id=env["org_id"],
        site_id=env["site_id"],
        access_device_id=sw.id,
        access_port="GE0/0/1",
        edge_device_id=ne1.id,
    )
    db_session.add(circ)
    db_session.flush()
    env["circ_id"] = circ.id
    return env


def test_dashboard_agrega(client: TestClient, db_session) -> None:
    env = _ambiente(db_session)

    r1 = create_device(
        db_session,
        DeviceCreate(name="r1", management_address="10.0.0.1", site_id=env["site_id"]),
        actor="cli",
    )
    r2 = create_device(
        db_session, DeviceCreate(name="r2", management_address="10.0.0.2"), actor="cli"
    )
    r3 = create_device(
        db_session, DeviceCreate(name="r3", management_address="10.0.0.3"), actor="cli"
    )
    r3.comm_status = "fail"

    r1.last_collected_at = datetime.now(timezone.utc)  # uma coleta já feita
    snap = models.DeviceSnapshot(device_id=r1.id, status="success", resources={})
    job = models.JobRun(device_id=r2.id, origin="api", actor="api", kind="collect", status="running")
    sessao_ativa = models.BgpSession(
        circuit_id=env["circ_id"], device_id=env["ne1_id"], afi="ipv4",
        local_address="100.64.1.1", remote_address="100.64.1.2", asn_remote=64512,
    )
    sessao_shutdown = models.BgpSession(
        circuit_id=env["circ_id"], device_id=env["ne2_id"], afi="ipv6",
        local_address="100.64.2.1", remote_address="100.64.2.2", asn_remote=64512,
        shutdown=True,
    )
    db_session.add_all([snap, job, sessao_ativa, sessao_shutdown])
    db_session.add_all([
        models.Vlan(site_id=env["site_id"], vid=100),  # default reservada
        models.Vlan(site_id=env["site_id"], vid=200, status="liberada"),
        models.IpPrefix(network="10.99.1.0/31", site_id=env["site_id"]),  # default reservada
        models.IpPrefix(network="10.99.2.0/31", site_id=env["site_id"], status="liberada"),
    ])
    db_session.commit()

    resp = client.get("/api/v1/dashboard", headers=_auth())
    assert resp.status_code == 200
    dados = resp.json()

    assert dados["devices"] == {
        "total": 3, "active": 3, "with_snapshot": 1,
        "by_comm_status": {"unknown": 2, "ok": 0, "fail": 1},
    }
    nomes = [p["name"] for p in dados["per_device"]]
    assert nomes == ["r1", "r2", "r3"]
    p = {d["name"]: d for d in dados["per_device"]}
    assert p["r1"]["latest_snapshot"]["id"] == snap.id
    assert p["r1"]["latest_snapshot"]["status"] == "success"
    assert isinstance(p["r1"]["snapshot_age_seconds"], (int, float))
    assert p["r1"]["site_name"] == "pop-dash"
    assert p["r2"]["active_job"] == {"id": job.id, "status": "running"}
    assert p["r1"]["active_job"] is None
    assert p["r3"]["latest_snapshot"] is None and p["r3"]["active_job"] is None

    assert dados["bgp_sessions"] == {"total": 2, "active": 1, "shutdown": 1}
    assert dados["circuits"] == {"total": 1, "active": 1}
    assert dados["vlans"] == {"reserved": 1, "freed": 1}
    assert dados["ip_prefixes"] == {"reserved": 1, "freed": 1}
    assert 1 <= len(dados["recent_audit"]) <= 20
    assert set(dados["recent_audit"][0]) == {"id", "type", "actor", "details", "created_at"}


def test_dashboard_exige_autenticacao(client: TestClient) -> None:
    assert client.get("/api/v1/dashboard").status_code == 401
```

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/api/test_dashboard_api.py -q`
Expected: FAIL (rota inexistente).

- [ ] **Step 3: Schemas**

Adicionar em `src/gerenet/domain/schemas.py`:

```python
class DevicesAggOut(BaseModel):
    total: int
    active: int
    with_snapshot: int
    by_comm_status: dict[str, int]


class SnapshotResumoOut(BaseModel):
    id: int
    status: str
    started_at: datetime


class JobResumoOut(BaseModel):
    id: int
    status: str


class PerDeviceOut(BaseModel):
    device_id: int
    name: str
    site_id: int | None
    site_name: str | None
    comm_status: str
    last_collected_at: datetime | None
    snapshot_age_seconds: float | None
    latest_snapshot: SnapshotResumoOut | None
    active_job: JobResumoOut | None


class BgpSessionsAggOut(BaseModel):
    total: int
    active: int
    shutdown: int


class CircuitsAggOut(BaseModel):
    total: int
    active: int


class AllocAggOut(BaseModel):
    reserved: int
    freed: int


class DashboardOut(BaseModel):
    devices: DevicesAggOut
    per_device: list[PerDeviceOut]
    bgp_sessions: BgpSessionsAggOut
    circuits: CircuitsAggOut
    vlans: AllocAggOut
    ip_prefixes: AllocAggOut
    recent_audit: list[AuditEventOut]
```

- [ ] **Step 4: Router `src/gerenet/api/dashboard.py`**

```python
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from gerenet.api.deps import Actor, SessionDep, require_actor
from gerenet.domain import models
from gerenet.domain.schemas import (
    AuditEventOut,
    BgpSessionsAggOut,
    CircuitsAggOut,
    DashboardOut,
    DevicesAggOut,
    JobResumoOut,
    PerDeviceOut,
    SnapshotResumoOut,
    AllocAggOut,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=[Depends(require_actor)])


@router.get("", response_model=DashboardOut)
def dashboard(session: SessionDep) -> DashboardOut:
    """Agregações do dashboard §16.1 — sem chamadas a reconcile (read-only barato)."""
    agora = datetime.now(timezone.utc)

    devices = list(
        session.scalars(select(models.Device).options(selectinload(models.Device.site)).order_by(models.Device.name))
    )
    by_status: dict[str, int] = {}
    for status in ("unknown", "ok", "fail"):
        by_status[status] = sum(1 for d in devices if d.comm_status == status)

    per_device: list[PerDeviceOut] = []
    for d in devices:
        snap = session.scalar(
            select(models.DeviceSnapshot)
            .where(models.DeviceSnapshot.device_id == d.id)
            .order_by(models.DeviceSnapshot.id.desc())
            .limit(1)
        )
        job = session.scalar(
            select(models.JobRun)
            .where(
                models.JobRun.device_id == d.id,
                models.JobRun.kind == "collect",
                models.JobRun.status.in_(["queued", "running"]),
            )
            .order_by(models.JobRun.id.desc())
            .limit(1)
        )
        idade = (agora - snap.started_at).total_seconds() if snap is not None else None
        per_device.append(
            PerDeviceOut(
                device_id=d.id,
                name=d.name,
                site_id=d.site_id,
                site_name=d.site.name if d.site is not None else None,
                comm_status=d.comm_status,
                last_collected_at=d.last_collected_at,
                snapshot_age_seconds=idade,
                latest_snapshot=(
                    SnapshotResumoOut(id=snap.id, status=snap.status, started_at=snap.started_at)
                    if snap is not None else None
                ),
                active_job=JobResumoOut(id=job.id, status=job.status) if job is not None else None,
            )
        )

    sessoes = list(session.scalars(select(models.BgpSession)))
    circuitos = list(session.scalars(select(models.Circuit)))
    vlans = list(session.scalars(select(models.Vlan)))
    prefixos = list(session.scalars(select(models.IpPrefix)))
    auditoria = list(
        session.scalars(
            select(models.AuditEvent).order_by(models.AuditEvent.id.desc()).limit(20)
        )
    )

    return DashboardOut(
        devices=DevicesAggOut(
            total=len(devices),
            active=sum(1 for d in devices if d.admin_status),
            with_snapshot=sum(1 for d in devices if d.last_collected_at is not None),
            by_comm_status=by_status,
        ),
        per_device=per_device,
        bgp_sessions=BgpSessionsAggOut(
            total=len(sessoes),
            active=sum(1 for s in sessoes if s.admin_status and not s.shutdown),
            shutdown=sum(1 for s in sessoes if s.shutdown),
        ),
        circuits=CircuitsAggOut(
            total=len(circuitos), active=sum(1 for c in circuitos if c.admin_status)
        ),
        vlans=AllocAggOut(
            reserved=sum(1 for v in vlans if v.status == "reservada"),
            freed=sum(1 for v in vlans if v.status == "liberada"),
        ),
        ip_prefixes=AllocAggOut(
            reserved=sum(1 for p in prefixos if p.status == "reservada"),
            freed=sum(1 for p in prefixos if p.status == "liberada"),
        ),
        recent_audit=[AuditEventOut.model_validate(e) for e in auditoria],
    )
```

- [ ] **Step 5: `main.py` — include**

```python
from gerenet.api import dashboard
...
    app.include_router(dashboard.router)
```

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/api/test_dashboard_api.py -q`
Expected: PASS. (`snapshot_age_seconds` é `(agora - started_at).total_seconds()` — o teste compara com `isinstance` porque `started_at` vem do `server_default now()` do banco e pode diferir em milissegundos do relógio do teste.)

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/api/dashboard.py src/gerenet/api/main.py tests/api/test_dashboard_api.py
git commit -m "feat(dashboard): endpoint agregador do dashboard (devices, sessoes, uso, auditoria)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Jobs — `GET /api/v1/jobs` + `GET /api/v1/jobs/{id}`

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`JobRunOut`)
- Create: `src/gerenet/api/jobs.py`
- Modify: `src/gerenet/api/main.py` (include)
- Create: `tests/api/test_jobs_api.py`

**Interfaces:**
- Consumes: `models.JobRun` (existente), `require_actor` (T3).
- Produces: `JobRunOut`; rotas read-only de jobs — a SPA acompanha coletas com poll (spec §3.7).

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/api/test_jobs_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.models import JobRun


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_lista_filtros_e_detalhe(client: TestClient, db_session) -> None:
    j1 = JobRun(device_id=1, origin="api", actor="api", kind="collect", status="queued")
    j2 = JobRun(device_id=2, origin="cli", actor="cli", kind="collect", status="success", duration_ms=1200)
    db_session.add_all([j1, j2])
    db_session.commit()

    lista = client.get("/api/v1/jobs", headers=_auth()).json()
    assert [j["id"] for j in lista] == [j2.id, j1.id]
    assert set(lista[0]) == {
        "id", "device_id", "origin", "actor", "kind", "status",
        "started_at", "finished_at", "duration_ms", "snapshot_id",
    }

    so_running = client.get("/api/v1/jobs?status=queued", headers=_auth()).json()
    assert [j["id"] for j in so_running] == [j1.id]

    por_device = client.get(f"/api/v1/jobs?device_id={j2.device_id}", headers=_auth()).json()
    assert [j["id"] for j in por_device] == [j2.id]

    detalhe = client.get(f"/api/v1/jobs/{j1.id}", headers=_auth())
    assert detalhe.status_code == 200 and detalhe.json()["status"] == "queued"
    assert client.get("/api/v1/jobs/9999", headers=_auth()).status_code == 404


def test_jobs_exige_autenticacao(client: TestClient) -> None:
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.post("/api/v1/jobs", headers={"X-API-Key": "teste-key"}).status_code == 405


def test_collect_202_tem_job_id(client: TestClient, db_session, monkeypatch) -> None:
    """Contrato da spec §5.2: o 202 do collect carrega job_id.

    Em produção `enqueue_collect` (worker/tasks.py:34) já devolve job_id —
    nenhuma mudança de produção nesta task; o teste apenas fixa o contrato.
    """
    dev = create_device(
        db_session, DeviceCreate(name="job-dash", management_address="10.9.0.1"), actor="cli"
    )
    monkeypatch.setattr(
        "gerenet.api.routers.devices.enqueue_collect",
        lambda *a, **k: {"queued": True, "message": "Coleta enfileirada.", "job_id": 42},
    )
    resp = client.post(f"/api/v1/devices/{dev.id}/collect", headers=_auth())
    assert resp.status_code == 202
    assert resp.json()["job_id"] == 42
```

Além dos imports já listados, o arquivo precisa de:

```python
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device
```

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/api/test_jobs_api.py -q`
Expected: FAIL (rota inexistente).

- [ ] **Step 3: Schema `JobRunOut`**

Adicionar em `src/gerenet/domain/schemas.py`:

```python
class JobRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int | None
    origin: str
    actor: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int
    snapshot_id: int | None
```

- [ ] **Step 4: Router `src/gerenet/api/jobs.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Query

from gerenet.api.deps import Actor, SessionDep, require_actor
from gerenet.domain import models
from gerenet.domain.schemas import JobRunOut
from sqlalchemy import select

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"], dependencies=[Depends(require_actor)])


@router.get("", response_model=list[JobRunOut])
def listar(
    session: SessionDep,
    device_id: int | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list:
    stmt = select(models.JobRun).order_by(models.JobRun.id.desc()).limit(limit).offset(offset)
    if device_id is not None:
        stmt = stmt.where(models.JobRun.device_id == device_id)
    if status is not None:
        stmt = stmt.where(models.JobRun.status == status)
    if kind is not None:
        stmt = stmt.where(models.JobRun.kind == kind)
    return list(session.scalars(stmt))


@router.get("/{job_id}", response_model=JobRunOut)
def detalhar(job_id: int, session: SessionDep) -> object:
    job = session.get(models.JobRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return job
```

- [ ] **Step 5: `main.py` — include**

```python
from gerenet.api import jobs
...
    app.include_router(jobs.router)
```

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/api/test_jobs_api.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/api/jobs.py src/gerenet/api/main.py tests/api/test_jobs_api.py
git commit -m "feat(jobs): leitura de jobs (lista, filtros, detalhe) — fim do padrao P3

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: CLI — `gerenet users create|set-password|list`

**Files:**
- Create: `src/gerenet/cli/users.py`
- Modify: `src/gerenet/cli/main.py` (registro)
- Modify: `tests/cli/test_cli_smoke.py` (comandos users)

**Interfaces:**
- Consumes: serviço `users` (T2) — CLI registra ator `"cli"`.
- Produces: `gerenet users …` — primeiro admin: `gerenet users create admin --role administrador`.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao fim de `tests/cli/test_cli_smoke.py`:

```python
from sqlalchemy import select as _select


def test_cli_users_create_list_set_password() -> None:
    r = runner.invoke(
        app,
        ["users", "create", "boss", "--role", "administrador"],
        input="senha-super-8\nsenha-super-8\n",
    )
    assert r.exit_code == 0, r.output
    assert "boss" in r.output

    lista = runner.invoke(app, ["users", "list"])
    assert lista.exit_code == 0
    assert "boss" in lista.output and "administrador" in lista.output

    trocar = runner.invoke(app, ["users", "set-password", "boss"], input="outra-super-8\noutra-super-8\n")
    assert trocar.exit_code == 0, trocar.output

    sem_senha = runner.invoke(app, ["users", "create", "fraco", "--role", "operador"], input="curta\ncurta\n")
    assert sem_senha.exit_code == 1
    assert "Erro:" in sem_senha.output

    role_bad = runner.invoke(
        app, ["users", "create", "nao", "--role", "root"], input="senha-super-8\nsenha-super-8\n"
    )
    assert role_bad.exit_code == 1
    assert "Erro:" in role_bad.output
```

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/cli/test_cli_smoke.py::test_cli_users_create_list_set_password -q`
Expected: FAIL — sem o app `users`.

- [ ] **Step 3: `src/gerenet/cli/users.py`**

```python
import typer

from gerenet.db import get_session
from gerenet.domain import models
from gerenet.domain.services import users as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Usuários e perfis do gerenet (§17).")


def _confere_senhas(senha1: str, senha2: str) -> str:
    if senha1 != senha2:
        typer.echo("Erro: As senhas não conferem.", err=True)
        raise typer.Exit(1)
    return senha1


@app.command("create")
def create(
    username: str = typer.Argument(..., help="Nome de usuário (case-sensitive)."),
    role: str = typer.Option(..., "--role", help="Perfil: visualizador/operador/aprovador/executor/administrador."),
) -> None:
    """Cria um usuário (senha por prompt oculto; nunca em argv)."""
    senha = typer.prompt("Senha", hide_input=True)
    confirmacao = typer.prompt("Confirme a senha", hide_input=True)
    senha = _confere_senhas(senha, confirmacao)
    with get_session() as session:
        try:
            usuario = svc.create_user(
                session, username=username, password=senha, role=role, actor="cli"
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Usuário {usuario.username} criado (id {usuario.id}, perfil {usuario.role}).")


@app.command("set-password")
def set_password(username: str = typer.Argument(..., help="Nome de usuário.")) -> None:
    """Redefine a senha de um usuário (invalida as sessões dele)."""
    senha = typer.prompt("Nova senha", hide_input=True)
    confirmacao = typer.prompt("Confirme", hide_input=True)
    senha = _confere_senhas(senha, confirmacao)
    with get_session() as session:
        target = next((u for u in svc.list_users(session, include_disabled=True) if u.username == username), None)
        if target is None:
            typer.echo("Usuário não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            svc.reset_password(session, target.id, password=senha, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Senha de {username} redefinida (sessões antigas invalidadas).")


@app.command("list")
def listar(include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados.")) -> None:
    """Lista usuários."""
    with get_session() as session:
        for u in svc.list_users(session, include_disabled=include_disabled):
            estado = "ativo" if u.is_active else "desativado"
            typer.echo(f"{u.id:>4}  {u.username:<16} {u.role:<14} {estado}")
```

- [ ] **Step 4: Registrar no `cli/main.py`**

```python
from gerenet.cli import users as cli_users
...
app.add_typer(cli_users.app, name="users", help="Usuários e perfis.")
```"
```

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/cli/test_cli_smoke.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/cli/users.py src/gerenet/cli/main.py tests/cli/test_cli_smoke.py
git commit -m "feat(cli): gerenet users create|set-password|list

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: Servir a SPA (`web/dist`) com fallback + cache

**Files:**
- Create: `src/gerenet/api/static_spa.py`
- Modify: `src/gerenet/api/main.py` (registro condicional)
- Create: `tests/api/test_static_spa.py`

**Interfaces:**
- Consumes: `settings.static_dir` (T3), `FileResponse`/`StaticFiles` do FastAPI — sem dependência da SPA ainda (C2 gera o `web/dist`).
- Produces: numa instância com build presente, `GET /` → `index.html`; `GET /<rota-client>` → `index.html`; `GET /assets/<hash>` → arquivo imutável; nenhuma rota `api/*` cai no fallback. Sem build presente, nada é montado (404 da API continua normal).

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/api/test_static_spa.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings

DIST = Path("/tmp/gerenet-spa-fake")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "web" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>gerenet</html>", encoding="utf-8")
    (assets / "app.abc123.js").write_text("console.log(1)", encoding="utf-8")
    set_settings(Settings(api_key="teste-key", static_dir=dist, _env_file=None))
    return TestClient(create_app())


def test_servira_index_e_assets(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == "<html>gerenet</html>"

    rota_client = client.get("/reconcile")
    assert rota_client.status_code == 200 and rota_client.text == "<html>gerenet</html>"

    asset = client.get("/assets/app.abc123.js")
    assert asset.status_code == 200
    assert asset.headers.get("cache-control") == "public,max-age=31536000,immutable"


def test_rotas_api_nao_caem_no_fallback(client: TestClient) -> None:
    resp = client.get("/api/v1/nao-existe")
    assert resp.status_code == 404
    assert resp.text.strip().startswith("{")  # erro JSON, não index.html


def test_sem_build_nao_registra(client: TestClient) -> None:
    set_settings(Settings(api_key="teste-key", static_dir=Path("/tmp/nao-existe-dist-xyz"), _env_file=None))
    resp = client.get("/")
    assert resp.status_code == 404
```

- [ ] **Step 2: Rodar para verificar que falham**

Run: `uv run pytest tests/api/test_static_spa.py -q`
Expected: FAIL — 404 em todas as rotas (nada montado).

- [ ] **Step 3: `src/gerenet/api/static_spa.py`**

```python
"""Servir o build da SPA (web/dist) com fallback para rotas do client (ciclo C).

Mesma origem do backend (spec §3.1): sem CORS; o index.html só cai nas rotas
GET que não começam com /api. Assets de /assets/ são imutáveis (hash no nome).
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def montar_spa(app, static_dir: Path) -> None:  # noqa: ANN001 — app FastAPI
    """Registra o fallback SPA quando o build existe; senão, nada acontece."""
    index = static_dir / "index.html"
    if not index.exists():
        return

    router = APIRouter(include_in_schema=False)

    @router.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        alvo = static_dir / path
        if path and alvo.is_file():
            cabecalhos = (
                {"Cache-Control": "public,max-age=31536000,immutable"}
                if path.startswith("assets/")
                else {}
            )
            return FileResponse(alvo, headers=cabecalhos)
        # fallback SPA: qualquer rota do client (react-router) → index.html
        return FileResponse(index)

    app.include_router(router)
```

- [ ] **Step 4: Registrar em `main.py` (último, depois dos includes)**

Em `src/gerenet/api/main.py`, acrescentar os imports e chamar `montar_spa` por **último** (depois dos includes de rotas e do `healthz` — o fallback nunca tapa rotas reais):

```python
from gerenet.api.static_spa import montar_spa
from gerenet.config import get_settings
...
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Por último: fallback SPA (só registra se web/dist/index.html existir).
    montar_spa(app, get_settings().static_dir)

    return app
```

- [ ] **Step 5: Rodar os testes**

Run: `uv run pytest tests/api/test_static_spa.py -q`
Expected: PASS.

- [ ] **Step 6: Suíte completa + lint + commit**

```bash
uv run pytest -q
uv run ruff check
git add src/gerenet/api/static_spa.py src/gerenet/api/main.py tests/api/test_static_spa.py
git commit -m "feat(api): serve o build da SPA com fallback e cache de assets (ciclo C1)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: Docs — estado do repositório (CLAUDE.md) e bootstrap de usuário (README)

**Files:**
- Modify: `CLAUDE.md` (seção "Estado do repositório")
- Modify: `README.md` (seção "Desenvolvimento" + nova "Autenticação web")

**Interfaces:**
- Consumes: nada de código novo — documenta o resultado de T1–T8 (spec ciclo C §10: CLAUDE.md/README estão desatualizados desde o ciclo A — obrigação explícita desta spec).
- Produces: run-book textual "primeiro usuário + web" que o **C2** estenderá com o run-book de desenvolvimento da SPA (npm/vite).

- [ ] **Step 1: `CLAUDE.md` — substituir o primeiro bullet de "Estado do repositório"**

Trocar:

```markdown
- Nenhum código ainda; não há comandos de build/lint/test para executar — não inventá-los.
```

por:

```markdown
- Já há código (ciclo A/C1): SoT + API FastAPI `/api/v1` + CLI Typer + worker RQ + pytest/ruff.
  Comandos: `uv run pytest -q`, `uv run ruff check`, `uv run alembic upgrade head`,
  `uv run uvicorn gerenet.api.main:create_app --factory` (dev). A interface web (ciclo C)
  nasce no `web/` (C2) e é servida pelo próprio FastAPI.
```

- [ ] **Step 2: `README.md` — ajustar e acrescentar**

Substituir a seção `## Desenvolvimento` por (mantém o rumo atual e acrescenta o bootstrap de usuário):

```markdown
## Desenvolvimento

- Infra: `docker compose up -d` (postgres, redis, vault dev)
- App: `cp .env.example .env`; `GERENET_DATABASE_URL=… uv run alembic upgrade head`; `uv run uvicorn gerenet.api.main:create_app --factory --reload --port 8000`
- Testes: `uv run pytest`

## Autenticação web (ciclo C)

- Login local com perfis §17: `gerenet users create admin --role administrador` (senha por
  prompt — nunca em argv); a API key continua valendo para CLI/automações
  (`X-Api-Key`).
- Cookie de sessão `gerenet_sess` (HttpOnly, SameSite=Lax). Em produção sob HTTPS:
  `GERENET_COOKIE_SECURE=true`.
- A interface web (`web/`, ciclo C2) é servida pelo próprio FastAPI a partir de
  `web/dist`; em desenvolvimento, `cd web && npm install && npm run dev` proxya
  `/api` → :8000.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs(c1): estado do repositorio + run-book de primeiro usuario e web

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Rulings adicionais para o executor

- A **T5** é a única task que toca 9 routers — rodar `grep -rn 'actor="api"\|require_api_key' src/gerenet/api/routers/` ANTES de editar para confirmar a lista; qualquar router que ficar para trás deixará a suíte de `test_actor_sessao` vermelha (e.g., GET por cookie).
- A **T3** não pode quebrar `test_exige_chave_e_somente_get` (audit-events): status 401 sem chave e 405 nos POST/PATCH/DELETE — trocar a dependencies de `audit_events.py` (T5) preserva ambos.
- Ao final de cada task: `uv run pytest -q` verde; ao fim do plano: `uv run ruff check` + suite toda + `uv run python -m gerenet` smoke? (basta o CLI smoke).
- Documentação: a tarefa de docs (README run-book da web e CLAUDE.md "estado do repositório") é explicitamente do **C2** (plan da SPA) — não fazer aqui.
