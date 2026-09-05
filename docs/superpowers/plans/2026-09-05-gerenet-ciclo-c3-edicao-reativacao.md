# Ciclo C3 — Edição e reativação de entidades: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar o ciclo de vida das entidades cadastrais na web (ver desativados, reagirar, editar) e liquidar os follow-ups da revisão final do C2 (rate limit de login, sessões na desativação, cards do dashboard, a11y de dialog, guard do Playwright, catálogos com update/PATCH/CLI).

**Architecture:** Delta mínimo sobre o que já existe — o backend de PATCH de edição já está pronto para a maioria das entidades; o C3 preenche as lacunas (contacts `include_disabled`, catálogos update/service/PATCH/CLI, roteamento PATCH de devices → `enable_device`, `disable_user` removendo sessões, módulo de rate limit) e concentra o trabalho no front (Modal com a11y, toggle "ver desativados", botoes Editar/Reativar por página, cards do dashboard, `.catch` de mutações). Cada task é testável isoladamente (TDD).

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy + Pydantic v2 + Typer + pytest/ruff (backend); React 18 + Vite + TypeScript + react-query + Vitest + Playwright (web).

**Spec:** [docs/superpowers/specs/2026-09-05-gerenet-ciclo-c3-edicao-reativacao-design.md](../specs/2026-09-05-gerenet-ciclo-c3-edicao-reativacao-design.md) — o plano argumenta a partir dela; executores leem os dois.

## Global Constraints

- **Idioma**: todos os artefatos/documentação/copy em PT-BR; handlers de router e comandos em PT-BR (`listar`, `atualizar`, `desativar`); identificadores de classes/colunas/serviços em EN.
- **Ruling 1**: PATCH com mudança pura de desativação (`{"admin_status": false}` ou `{"is_active": false}`) → serviço dedicado `*.disable` com evento `*.disable`; qualquer outro corpo → `*.update` com evento `*.update`.
- **Ruling 5**: repetição idempotente — PATCH que repete um estado já existente não transiciona e não registra evento de auditoria.
- **Catálogos seedados** (`bgp_policy_profiles`, `communities`) ficam **fora do TRUNCATE** do `tests/conftest.py` (ruling 2): qualquer teste que insira linhas de catálogo **deve apagá-las ao final** (try/finally + `db_session.delete` + commit), senão quebra `test_catalogo_communities_tem_as_tres_sementes` / `test_catalogo_export_tem_os_seis_produtos`.
- **Banco/execução**: suíte pytest roda em `gerenet_test` (`GERENET_DATABASE_URL` apontado pelo conftest, com guard `SystemExit`); e2e em `gerenet_e2e` dedicado — nunca o default `gerenet`. `npm run test:e2e` exige uvicorn de dev parado na :8000 (a partir do T13 isso é falha dura, não aviso).
- **Comandos**: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build`, `cd web && npm run test`, `cd web && npm run test:e2e` (banco dedicado).
- **Protocolo**: ciclo executa em worktree (branch de trabalho); o merge no main é executado pelo usuário. Nenhum ciclo toca `gerenet_test` com outro ciclo em voo.
- **Segurança**: nenhum segredo novo; senha/token nunca em argv, log ou estado persistente do front; a mensagem 429 não revela existência de usuário; `credentials: "include"` nos fetches (inalterado).
- **Setup de testes web**: `web/vite.config.ts` usa `environment: "jsdom"`, `globals: true`, `setupFiles: ["./src/test-setup.ts"]` — os testes seguem o estilo de `web/src/pages/Sites.test.tsx` (stub de `fetch` global, `QueryClient` com retry:false, `AuthProvider` + `MemoryRouter`).

---

### Task 1: contacts `include_disabled` (S1.1)

**Files:**
- Modify: `src/gerenet/domain/services/contacts.py:35-40` (`list_contacts`)
- Modify: `src/gerenet/api/routers/contacts.py:26-27` (`listar`)
- Test: `tests/api/test_contacts_api.py`

**Interfaces:**
- Consumes: `models.Contact.admin_status` (já existe); padrão `list_*` das demais entidades (ex.: `list_policy_profiles(session, direction=None, include_disabled=False)`).
- Produces: `svc.list_contacts(session, organization_id=None, include_disabled=False) -> list[models.Contact]`; `GET /api/v1/contacts?include_disabled=true` — consumido pela web na Task 9.

- [ ] **Step 1: Escrever o teste que falha**

Adicione em `tests/api/test_contacts_api.py`:

```python
def test_lista_nao_inclui_desativados_sem_flag(client: TestClient) -> None:
    org_id = _org(client)
    criado = client.post(
        "/api/v1/contacts",
        json={"organization_id": org_id, "name": "Zé NOC", "kind": "noc"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    cid = criado.json()["id"]
    assert client.patch(f"/api/v1/contacts/{cid}", json={"admin_status": False}, headers=_auth()).status_code == 200

    sem_flag = client.get("/api/v1/contacts", headers=_auth()).json()
    assert [c["name"] for c in sem_flag] == []
    com_flag = client.get("/api/v1/contacts?include_disabled=true", headers=_auth()).json()
    assert [c["name"] for c in com_flag] == ["Zé NOC"]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/api/test_contacts_api.py::test_lista_nao_inclui_desativados_sem_flag -q`
Expected: FAIL — a query `?include_disabled=true` ainda retorna lista vazia (o param é ignorado e o filtro `admin_status.is_(True)` vale sempre).

- [ ] **Step 3: Implementar o service**

Em `src/gerenet/domain/services/contacts.py`, substitua `list_contacts`:

```python
def list_contacts(
    session: Session, organization_id: int | None = None, include_disabled: bool = False
) -> list[models.Contact]:
    stmt = select(models.Contact).order_by(models.Contact.name)
    if organization_id is not None:
        stmt = stmt.where(models.Contact.organization_id == organization_id)
    if not include_disabled:
        stmt = stmt.where(models.Contact.admin_status.is_(True))
    return list(session.scalars(stmt))
```

- [ ] **Step 4: Implementar o router**

Em `src/gerenet/api/routers/contacts.py`, substitua `listar`:

```python
@router.get("", response_model=list[ContactOut])
def listar(
    session: SessionDep, organization_id: int | None = None, include_disabled: bool = False
) -> list:
    return svc.list_contacts(session, organization_id=organization_id, include_disabled=include_disabled)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_contacts_api.py -q`
Expected: PASS (suíte do arquivo inteira — nada do fluxo existente muda: o default segue `include_disabled=False`).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/contacts.py src/gerenet/api/routers/contacts.py tests/api/test_contacts_api.py
git commit -m "feat(api): list de contacts aceita include_disabled (S1.1)"
```

---

### Task 2: Rate limit de login em Redis com fail-open (S1.4)

**Files:**
- Create: `src/gerenet/api/rate_limit.py`
- Modify: `src/gerenet/api/auth.py:32-62` (`login`)
- Create: `tests/api/test_rate_limit.py`
- Modify: `tests/api/test_auth_api.py`

**Interfaces:**
- Consumes: `Settings.redis_url` (já existe); `redis.Redis` (já é dependência — RQ/locks); `redis.exceptions.RedisError`.
- Produces:
  - `rate_limit.MAX_FALHAS: int = 5`
  - `rate_limit.JANELA_SEGUNDOS: int = 300`
  - `rate_limit.chave(ip: str, username: str) -> str` (formato `gerenet:login:fail:{ip}:{username}`)
  - `rate_limit.conectar(settings) -> Redis` (separado para testes injetarem fake)
  - `rate_limit.permitir(redis, ip, username) -> bool`
  - `rate_limit.registrar_falha(redis, ip, username) -> int`
  - `rate_limit.limpar(redis, ip, username) -> None`
  - `POST /api/v1/auth/login` passa a responder `429` (com `Retry-After: 300`) quando o par `ip+username` acumular 5 falhas na janela.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/api/test_rate_limit.py`:

```python
from redis.exceptions import ConnectionError as RedisConnectionError

from gerenet.api import rate_limit


class FakeRedis:
    """Subset duck-typed do Redis (get/incr/expire/delete) para os testes."""

    def __init__(self) -> None:
        self._valores: dict[str, int] = {}
        self._expirados: set[str] = set()

    def get(self, chave: str) -> int | None:
        return self._valores.get(chave)

    def incr(self, chave: str) -> int:
        self._valores[chave] = self._valores.get(chave, 0) + 1
        return self._valores[chave]

    def expire(self, chave: str, _segundos: int) -> bool:
        self._expirados.add(chave)
        return True

    def delete(self, chave: str) -> int:
        return 1 if self._valores.pop(chave, None) is not None else 0


class RedisForaDoAr:
    """Redis que levanta em todo comando — simula a indisponibilidade."""

    def get(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")

    def incr(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")

    def expire(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")

    def delete(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")


def test_chave_formato() -> None:
    assert rate_limit.chave("10.0.0.1", "op1") == "gerenet:login:fail:10.0.0.1:op1"


def test_registrar_falha_incrementa_e_expira_na_primeira() -> None:
    redis = FakeRedis()
    assert rate_limit.registrar_falha(redis, "10.0.0.1", "op1") == 1
    assert redis._expirados == {"gerenet:login:fail:10.0.0.1:op1"}
    assert rate_limit.registrar_falha(redis, "10.0.0.1", "op1") == 2


def test_permitir_bloqueia_apos_5_falhas() -> None:
    redis = FakeRedis()
    for _ in range(4):
        rate_limit.registrar_falha(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is True
    rate_limit.registrar_falha(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is False


def test_limpar_zera_contador() -> None:
    redis = FakeRedis()
    for _ in range(5):
        rate_limit.registrar_falha(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is False
    rate_limit.limpar(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is True


def test_fail_open_quando_redis_fora_do_ar() -> None:
    sem_redis = RedisForaDoAr()
    assert rate_limit.permitir(sem_redis, "10.0.0.1", "op1") is True
    assert rate_limit.registrar_falha(sem_redis, "10.0.0.1", "op1") == 0
    rate_limit.limpar(sem_redis, "10.0.0.1", "op1")  # não levanta
```

Em `tests/api/test_auth_api.py`, adicione:

```python
def test_login_bloqueia_apos_5_falhas(client: TestClient, db_session, monkeypatch) -> None:
    from gerenet.api import rate_limit
    from tests.api.test_rate_limit import FakeRedis

    _cria_usuario(db_session)
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "conectar", lambda settings: fake)

    for _ in range(5):
        resp = client.post("/api/v1/auth/login", json={"username": "op1", "password": "errada-9"})
        assert resp.status_code == 401

    bloqueado = client.post("/api/v1/auth/login", json={"username": "op1", "password": "errada-9"})
    assert bloqueado.status_code == 429
    assert bloqueado.headers.get("retry-after") == "300"
    assert bloqueado.json() == {"detail": "Muitas tentativas de login. Tente novamente em alguns minutos."}


def test_login_sucesso_limpa_falhas(client: TestClient, db_session, monkeypatch) -> None:
    from gerenet.api import rate_limit
    from tests.api.test_rate_limit import FakeRedis

    _cria_usuario(db_session)
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "conectar", lambda settings: fake)

    for _ in range(4):
        assert client.post("/api/v1/auth/login", json={"username": "op1", "password": "errada-9"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "op1", "password": "senha-super-8"}).status_code == 200

    for _ in range(4):
        assert client.post("/api/v1/auth/login", json={"username": "op1", "password": "errada-9"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "op1", "password": "errada-9"}).status_code == 429


def test_login_fail_open_sem_redis(client: TestClient, db_session, monkeypatch) -> None:
    from gerenet.api import rate_limit
    from tests.api.test_rate_limit import RedisForaDoAr

    _cria_usuario(db_session)
    monkeypatch.setattr(rate_limit, "conectar", lambda settings: RedisForaDoAr())

    resp = client.post("/api/v1/auth/login", json={"username": "op1", "password": "senha-super-8"})
    assert resp.status_code == 200
    nova = client.post("/api/v1/auth/login", json={"username": "op1", "password": "errada-9"})
    assert nova.status_code == 401  # não explode em 500 nem bloqueia
```

> O suite inteiro usa real Redis opcionalmente? Atenção: os testes de auth existentes (sem monkeypatch) chamam `rate_limit.conectar` de verdade — com Redis fora do ar o módulo opera fail-open e os testes continuam passando; com Redis ativo, as chaves expiram em 300 s. Não há dependência de Redis ligado na suíte de auth.

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/api/test_rate_limit.py tests/api/test_auth_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerenet.api.rate_limit'`.

- [ ] **Step 3: Criar o módulo de rate limit**

Crie `src/gerenet/api/rate_limit.py`:

```python
"""Rate limit de login — fixed window por IP+username no Redis (fail-open).

Decisão C3 §3.7: conta apenas falhas (5 → bloqueio de 5 min com 429 +
Retry-After). Redis fora do ar → o login segue sem bloqueio (fail-open,
decisão reversível e documentada); login com sucesso limpa a chave.
"""
import logging

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

MAX_FALHAS = 5
JANELA_SEGUNDOS = 300


def chave(ip: str, username: str) -> str:
    return f"gerenet:login:fail:{ip}:{username}"


def conectar(settings) -> Redis:
    """Cliente Redis — função separada para os testes injetarem um fake."""
    return Redis.from_url(settings.redis_url)


def permitir(redis: Redis, ip: str, username: str) -> bool:
    """True enquanto o par ip+username acumula menos de MAX_FALHAS falhas."""
    try:
        return int(redis.get(chave(ip, username)) or 0) < MAX_FALHAS
    except RedisError:
        logger.warning("Redis indisponível no rate limit de login; permitindo (fail-open).", exc_info=True)
        return True


def registrar_falha(redis: Redis, ip: str, username: str) -> int:
    """INCR + EXPIRE na primeira falha; devolve o total acumulado na janela."""
    try:
        total = int(redis.incr(chave(ip, username)))
        if total == 1:
            redis.expire(chave(ip, username), JANELA_SEGUNDOS)
        return total
    except RedisError:
        logger.warning("Redis indisponível no rate limit de login; seguindo (fail-open).", exc_info=True)
        return 0


def limpar(redis: Redis, ip: str, username: str) -> None:
    """Login com sucesso zera o contador de falhas."""
    try:
        redis.delete(chave(ip, username))
    except RedisError:
        logger.warning("Redis indisponível ao limpar rate limit de login (fail-open).", exc_info=True)
```

- [ ] **Step 4: Integrar no `login` da auth**

Em `src/gerenet/api/auth.py`:

1. Adicione o import após `from gerenet.api.deps import SESSION_COOKIE, SessionDep`:

```python
from gerenet.api import rate_limit
```

2. Substitua o handler `login` por:

```python
@router.post("/login", response_model=UserOut)
def login(
    data: UserLoginIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> models.User:
    ip = request.client.host if request.client is not None else "?"
    redis = rate_limit.conectar(settings)
    # Consulta ANTES do scrypt: tentativa bloqueada custa quase nada e a
    # mensagem 429 é genérica (não revela existência de usuário).
    if not rate_limit.permitir(redis, ip, data.username):
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(rate_limit.JANELA_SEGUNDOS)},
            detail="Muitas tentativas de login. Tente novamente em alguns minutos.",
        )
    usuario = svc.autenticar(session, data.username, data.password)
    if usuario is None:
        rate_limit.registrar_falha(redis, ip, data.username)
        registrar(
            session, tipo="auth.login_failed", ator=data.username, objeto="auth", objeto_id=0
        )
        # O HTTPException interrompe a teardown da sessão (rollback): o evento
        # da falha precisa ser gravado antes (trilha imutável — §18).
        session.commit()
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    rate_limit.limpar(redis, ip, data.username)
    token = svc.iniciar_sessao(session, usuario, settings=settings)
    usuario.last_login_at = datetime.now(UTC)
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
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_rate_limit.py tests/api/test_auth_api.py -q`
Expected: PASS. Em seguida rode a suíte incompleta para garantir que nada mais quebrou:
`uv run pytest -q` (esperado: toda a suíte verde — o `request` novo no `login` é passado automaticamente pelo FastAPI).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/api/rate_limit.py src/gerenet/api/auth.py tests/api/test_rate_limit.py tests/api/test_auth_api.py
git commit -m "feat(api): rate limit de login no Redis com fail-open (S1.4)"
```

---

### Task 3: `disable_user` remove sessões + roteamento no PATCH (S1.5)

**Files:**
- Modify: `src/gerenet/domain/services/users.py` (novo `disable_user`, após `update_user` ~linha 144)
- Modify: `src/gerenet/api/users.py:28-43` (`atualizar`)
- Test: `tests/domain/test_users_service.py`
- Modify: `tests/api/test_users_api.py:124-152` (`test_desativar_invalida_sessao`)

**Interfaces:**
- Consumes: `delete`/`select` de `sqlalchemy` (já importados em users.py); `models.UserSession.user_id`; padrão de `reset_password` (linhas 147-163).
- Produces:
  - `svc.disable_user(session: Session, user_id: int, *, actor: str = "cli") -> models.User` — idempotente (Ruling 5), evento `user.disable`, apaga linhas de `user_sessions`.
  - Comportamento novo: PATCH puro `{"is_active": false}` em `POST /api/v1/users/{id}` passa a limpar as sessões do usuário; `require_actor` responde **401** (cookie inválido) em vez de **403**, para uma sessão revogada.

- [ ] **Step 1: Escrever o teste de domínio que falha**

Adicione em `tests/domain/test_users_service.py` (reaproveite o padrão de `test_reset_password_invalida_sessoes`, linha 131):

```python
def test_disable_user_invalida_sessoes_e_audita(db_session: Session) -> None:
    from gerenet.config import Settings

    usuario = svc.create_user(
        db_session, username="boss", password="senha-super-8", role="administrador", actor="cli"
    )
    svc.iniciar_sessao(db_session, usuario, settings=Settings(_env_file=None))
    db_session.commit()

    desativado = svc.disable_user(db_session, usuario.id, actor="admin")
    assert desativado is usuario
    assert usuario.is_active is False
    # Sessões apagadas (mesmo padrão do reset de senha).
    linhas = db_session.scalar(select(models.UserSession).where(models.UserSession.user_id == usuario.id))
    assert linhas is None
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "user.disable")
    )
    assert evento is not None and evento.actor == "admin"


def test_disable_user_idempotente_nao_audita_de_novo(db_session: Session) -> None:
    usuario = svc.create_user(
        db_session, username="op2", password="senha-super-8", role="operador", actor="cli"
    )
    db_session.commit()
    svc.disable_user(db_session, usuario.id, actor="cli")
    db_session.commit()
    svc.disable_user(db_session, usuario.id, actor="cli")  # repetição: sem transição (Ruling 5)
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "user.disable")
    ).all()
    assert len(eventos) == 1
```

> Confirme o import de `models` no topo de `test_users_service.py` (já é o padrão dos demais testes do arquivo — ajuste se faltar).

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/domain/test_users_service.py::test_disable_user_invalida_sessoes_e_audita tests/domain/test_users_service.py::test_disable_user_idempotente_nao_audita_de_novo -q`
Expected: FAIL — `AttributeError: module 'gerenet.domain.services.users' has no attribute 'disable_user'`.

- [ ] **Step 3: Implementar `disable_user` no service**

Em `src/gerenet/domain/services/users.py`, após `update_user` (antes de `reset_password`):

```python
def disable_user(
    session: Session, user_id: int, *, actor: str = "cli"
) -> models.User:
    usuario = session.get(models.User, user_id)
    if usuario is None:
        raise NotFoundError("Usuário não encontrado.")
    if usuario.is_active is False:
        return usuario  # idempotente: sem transição, sem evento (Ruling 5)
    # Segurança: desativar invalida as sessões — reativar não "ressuscita" sessões
    # antigas (padrão de reset_password, spec §4.5).
    session.execute(delete(models.UserSession).where(models.UserSession.user_id == user_id))
    usuario.is_active = False
    registrar(
        session,
        tipo="user.disable",
        ator=actor,
        objeto="user",
        objeto_id=usuario.id,
        antes={"is_active": True},
        depois={"is_active": False},
    )
    return usuario
```

- [ ] **Step 4: Roteamento no router de users**

Em `src/gerenet/api/users.py`, substitua `atualizar` por:

```python
@router.patch("/{user_id}", response_model=UserOut)
def atualizar(data: UserUpdateIn, user_id: int, actor: AdminDep, session: SessionDep) -> object:
    if actor.usuario is not None and actor.usuario.id == user_id and (data.role is not None or data.is_active is not None):
        raise HTTPException(status_code=403, detail="Não é possível alterar a própria conta.")
    mudancas = data.model_dump(exclude_unset=True)
    # Ruling 1: desativação pura vira o serviço dedicado (evento user.disable,
    # sessões revogadas). Mudança mista (ex.: username + is_active) segue no
    # update genérico — mesmo desenho dos demais routers.
    if mudancas == {"is_active": False}:
        try:
            return svc.disable_user(session, user_id, actor=actor.nome)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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
```

- [ ] **Step 5: Atualizar `test_desativar_invalida_sessao` (403 → 401)**

Em `tests/api/test_users_api.py`, a sessão do diogo passa a ser **revogada** na desativação. Substitua o bloco:

```python
    # sessão existente do diogo passa a 403 (usuário desativado) e login novo → 401
    diogo.cookies.clear()
    diogo.cookies.set("gerenet_sess", token)
    # /users é o único router com require_actor no T4 (a troca dos demais é a T5)
    resp = diogo.get("/api/v1/users")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Usuário desativado."}
```

por:

```python
    # desativar revoga as sessões do diogo: o cookie antigo não vale mais (401)
    diogo.cookies.clear()
    diogo.cookies.set("gerenet_sess", token)
    resp = diogo.get("/api/v1/users")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Chave de API ausente ou inválida."}
```

> Leia o restante do teste (linhas 145-170) antes: o trecho seguinte reativa o usuário para um "logon próprio" — a reativação continua via PATCH `{"is_active": true}` → `update_user` (Ruling 1: só desativação é roteada; reativação de usuários permanece `user.update`, decisão §3.6).

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_users_service.py tests/api/test_users_api.py -q`
Expected: PASS (atenção: qualquer teste que assuma evento `user.update` na desativação mudaria aqui — o teste novo de API cobre o evento).

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/services/users.py src/gerenet/api/users.py tests/domain/test_users_service.py tests/api/test_users_api.py
git commit -m "feat(api): desativar usuário revoga sessões e audita user.disable (S1.5)"
```

---

### Task 4: Catálogos — schemas e services update/disable (S1.2, backend 1/3)

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`CommunityOut` ~line 435; novos `CommunityUpdate`, `PolicyProfileUpdate`)
- Modify: `src/gerenet/domain/services/communities.py`
- Modify: `src/gerenet/domain/services/policy_profiles.py`
- Test: `tests/domain/test_communities_service.py`, `tests/domain/test_policy_profiles_service.py`

**Interfaces:**
- Consumes: `registrar` de `gerenet.domain.audit`; `NotFoundError`, `ConflictError`, `ValidationError`; padrao de `update_contact`/`disable_contact` (services/contacts.py:44-73); `models.DIRECTION = ("import", "export")`; `models.PROFILE_KIND = ("produto",)`.
- Produces:
  - `CommunityUpdate` (name?, notes?, admin_status?), `PolicyProfileUpdate` (name?, label?, direction?, kind?, prefixes?, notes?, admin_status?); `CommunityOut` passa a incluir `admin_status: bool`.
  - `svc.update_community(session, community_id, data: CommunityUpdate, *, actor: str) -> models.Community`
  - `svc.disable_community(session, community_id, *, actor: str) -> models.Community`
  - `svc.update_policy_profile(session, profile_id, data: PolicyProfileUpdate, *, actor: str) -> models.PolicyProfile`
  - `svc.disable_policy_profile(session, profile_id, *, actor: str) -> models.PolicyProfile`
  - Consumidos pelos routers (Task 5), CLI (Task 6) e web (Tasks 9-10).

- [ ] **Step 1: Escrever os testes de domínio que falham**

Em `tests/domain/test_communities_service.py` (o arquivo importa `db_session` e `models` — siga o estilo; **todo item criado é apagado no finally**, pois catálogo não é truncado):

```python
def test_update_community_altera_e_audita(db_session: Session) -> None:
    from gerenet.domain.schemas import CommunityUpdate

    com = models.Community(name="c3-teste-upd", notes="antes")
    db_session.add(com)
    db_session.commit()
    try:
        saida = svc.update_community(
            db_session, com.id, CommunityUpdate(name="c3-teste-novo", notes="depois"), actor="cli"
        )
        assert saida.name == "c3-teste-novo" and saida.notes == "depois"
        evento = db_session.scalar(
            select(models.AuditEvent).where(models.AuditEvent.type == "community.update")
        )
        assert evento is not None
        assert db_session.scalar(
            select(models.AuditEvent).where(models.AuditEvent.type == "community.update")
        ).before == {"name": "c3-teste-upd", "notes": "antes"}
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def test_update_community_rejeita_nome_duplicado(db_session: Session) -> None:
    from gerenet.domain.schemas import CommunityUpdate
    from gerenet.domain.services.errors import ConflictError

    a = models.Community(name="c3-com-a")
    b = models.Community(name="c3-com-b")
    db_session.add_all([a, b])
    db_session.commit()
    try:
        with pytest.raises(ConflictError):
            svc.update_community(db_session, b.id, CommunityUpdate(name="c3-com-a"), actor="cli")
    finally:
        for obj in (a, b):
            obj = db_session.get(models.Community, obj.id)
            if obj is not None:
                db_session.delete(obj)
        db_session.commit()


def test_disable_community_idempotente(db_session: Session) -> None:
    com = models.Community(name="c3-com-off")
    db_session.add(com)
    db_session.commit()
    try:
        svc.disable_community(db_session, com.id, actor="cli")
        db_session.commit()
        assert com.admin_status is False
        svc.disable_community(db_session, com.id, actor="cli")  # repetição: sem evento (Ruling 5)
        eventos = db_session.scalars(
            select(models.AuditEvent).where(models.AuditEvent.type == "community.disable")
        ).all()
        assert len(eventos) == 1
        assert [c.name for c in svc.list_communities(db_session)] == ["blackhole", "no-advertise", "no-export"]
        com_tudo = svc.list_communities(db_session, include_disabled=True)
        assert "c3-com-off" in [c.name for c in com_tudo]
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()
```

> Ajuste os imports do arquivo se precisar (`pytest`, `select`, `svc` já são usados lá).

Em `tests/domain/test_policy_profiles_service.py`, adicione:

```python
def test_update_policy_profile_altera_e_valida(db_session: Session) -> None:
    from gerenet.domain.schemas import PolicyProfileUpdate
    from gerenet.domain.services.errors import ValidationError

    perfil = models.PolicyProfile(
        name="c3-perfil-teste", label="Teste", direction="export", kind="produto", prefixes=None
    )
    db_session.add(perfil)
    db_session.commit()
    try:
        saida = svc.update_policy_profile(
            db_session,
            perfil.id,
            PolicyProfileUpdate(label="Teste atualizado", prefixes=["192.0.2.0/24"]),
            actor="cli",
        )
        assert saida.label == "Teste atualizado" and saida.prefixes == ["192.0.2.0/24"]
        # Direção só aceita import|export; nome vazio é rejeitado (ValidationError).
        with pytest.raises(ValidationError):
            svc.update_policy_profile(
                db_session, perfil.id, PolicyProfileUpdate(direction="entrada"), actor="cli"
            )
        with pytest.raises(ValidationError):
            svc.update_policy_profile(
                db_session, perfil.id, PolicyProfileUpdate(name="  "), actor="cli"
            )
    finally:
        perfil = db_session.get(models.PolicyProfile, perfil.id)
        if perfil is not None:
            db_session.delete(perfil)
            db_session.commit()


def test_disable_policy_profile_audita(db_session: Session) -> None:
    perfil = models.PolicyProfile(
        name="c3-perfil-off", label="Desliga", direction="export", kind="produto", prefixes=None
    )
    db_session.add(perfil)
    db_session.commit()
    try:
        svc.disable_policy_profile(db_session, perfil.id, actor="cli")
        assert perfil.admin_status is False
        evento = db_session.scalar(
            select(models.AuditEvent).where(models.AuditEvent.type == "policy_profile.disable")
        )
        assert evento is not None
        assert perfil not in svc.list_policy_profiles(db_session)
    finally:
        perfil = db_session.get(models.PolicyProfile, perfil.id)
        if perfil is not None:
            db_session.delete(perfil)
            db_session.commit()
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/domain/test_communities_service.py tests/domain/test_policy_profiles_service.py -q`
Expected: FAIL — `AttributeError ... 'communities' has no attribute 'update_community'`.

- [ ] **Step 3: Schemas**

Em `src/gerenet/domain/schemas.py`:

1. Em `CommunityOut` (linha ~435), adicione o campo:

```python
class CommunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    notes: str | None = None
    admin_status: bool
```

2. Logo após `CommunityOut`, adicione:

```python
class CommunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = None
    admin_status: bool | None = None  # PATCH puro {"admin_status": false} roteia ao disable (Ruling 1)


class PolicyProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, min_length=1, max_length=64)
    direction: Literal["import", "export"] | None = None
    kind: str | None = None  # validado no serviço contra models.PROFILE_KIND
    prefixes: list[str] | None = None
    notes: str | None = None
    admin_status: bool | None = None
```

- [ ] **Step 4: Services de communities**

Substitua o conteúdo de `src/gerenet/domain/services/communities.py` por:

```python
"""Catálogo de communities (§25.6) — list no ciclo A; update/disable no C3."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import CommunityUpdate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


def get_community(session: Session, community_id: int) -> models.Community:
    com = session.get(models.Community, community_id)
    if com is None:
        raise NotFoundError(f"Community {community_id} não encontrada.")
    return com


def list_communities(
    session: Session, include_disabled: bool = False
) -> list[models.Community]:
    stmt = select(models.Community).order_by(models.Community.name)
    if not include_disabled:
        stmt = stmt.where(models.Community.admin_status.is_(True))
    return list(session.scalars(stmt))


def update_community(
    session: Session, community_id: int, data: CommunityUpdate, *, actor: str
) -> models.Community:
    com = get_community(session, community_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return com
    if "name" in mudancas:
        nome = mudancas["name"]
        if not nome.strip():
            raise ValidationError("Nome da community não pode ser vazio.")
        ocupado = session.scalar(
            select(models.Community).where(
                models.Community.name == nome, models.Community.id != community_id
            )
        )
        if ocupado is not None:
            raise ConflictError(f"Community já existe: {nome}.")
    antes = {campo: getattr(com, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(com, campo, valor)
    registrar(
        session, tipo="community.update", ator=actor, objeto="community", objeto_id=com.id,
        antes=antes, depois=mudancas,
    )
    session.commit()
    session.refresh(com)
    return com


def disable_community(session: Session, community_id: int, *, actor: str) -> models.Community:
    com = get_community(session, community_id)
    if com.admin_status is False:
        return com  # idempotente: sem transição, sem evento (Ruling 5)
    com.admin_status = False
    registrar(
        session, tipo="community.disable", ator=actor, objeto="community", objeto_id=com.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return com
```

- [ ] **Step 5: Services de policy profiles**

Em `src/gerenet/domain/services/policy_profiles.py`, adicione no fim (e ajuste os imports para incluir `registrar`, `ConflictError`, `PolicyProfileUpdate`):

```python
def update_policy_profile(
    session: Session, profile_id: int, data: PolicyProfileUpdate, *, actor: str
) -> models.PolicyProfile:
    perfil = get_policy_profile(session, profile_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return perfil
    if "name" in mudancas:
        nome = mudancas["name"]
        if not nome.strip():
            raise ValidationError("Nome do perfil não pode ser vazio.")
        ocupado = session.scalar(
            select(models.PolicyProfile).where(
                models.PolicyProfile.name == nome, models.PolicyProfile.id != profile_id
            )
        )
        if ocupado is not None:
            raise ConflictError(f"Perfil já existe: {nome}.")
    if "label" in mudancas and not mudancas["label"].strip():
        raise ValidationError("Label do perfil não pode ser vazio.")
    if "direction" in mudancas and mudancas["direction"] not in models.DIRECTION:
        raise ValidationError(
            f"Direção inválida: {mudancas['direction']} (esperado {', '.join(models.DIRECTION)})."
        )
    if "kind" in mudancas and mudancas["kind"] not in models.PROFILE_KIND:
        raise ValidationError(
            f"Tipo inválido: {mudancas['kind']} (esperado {', '.join(models.PROFILE_KIND)})."
        )
    antes = {campo: getattr(perfil, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(perfil, campo, valor)
    registrar(
        session, tipo="policy_profile.update", ator=actor, objeto="policy_profile", objeto_id=perfil.id,
        antes=antes, depois=mudancas,
    )
    session.commit()
    session.refresh(perfil)
    return perfil


def disable_policy_profile(
    session: Session, profile_id: int, *, actor: str
) -> models.PolicyProfile:
    perfil = get_policy_profile(session, profile_id)
    if perfil.admin_status is False:
        return perfil  # idempotente: sem transição, sem evento (Ruling 5)
    perfil.admin_status = False
    registrar(
        session, tipo="policy_profile.disable", ator=actor, objeto="policy_profile", objeto_id=perfil.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return perfil
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_communities_service.py tests/domain/test_policy_profiles_service.py -q`
Expected: PASS. (Se um teste listar as seeds com nomes extras, é linha de catálogo não apagada — corrija o teste culpado.)

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/communities.py src/gerenet/domain/services/policy_profiles.py tests/domain/test_communities_service.py tests/domain/test_policy_profiles_service.py
git commit -m "feat(api): catálogos com update/disable no service e schemas (S1.2)"
```

---

### Task 5: Catálogos — PATCH nos routers com Ruling 1 (S1.2, backend 2/3)

**Files:**
- Modify: `src/gerenet/api/routers/communities.py`
- Modify: `src/gerenet/api/routers/policy_profiles.py`
- Test: `tests/api/test_communities_api.py`, `tests/api/test_policy_profiles_api.py`

**Interfaces:**
- Consumes: `CommunityUpdate`/`PolicyProfileUpdate` e services da Task 4; padrão do router de contacts (PATCH com `actor` e erros 409/404/400).
- Produces:
  - `PATCH /api/v1/communities/{id}` e `PATCH /api/v1/policy-profiles/{id}` com:
    - corpo puro `{"admin_status": false}` → `disable_*` (evento `*.disable`);
    - qualquer outro corpo → `update_*` (evento `*.update`), incluindo reativação pura `{"admin_status": true}`;
    - `admin_status: null` → 400; repetição idempotente → 200 sem evento (Ruling 5); sem auth → 401.

- [ ] **Step 1: Escrever os testes de API que falham**

Em `tests/api/test_communities_api.py`, adicione (siga o padrão do arquivo — confira os imports existentes e o fixture `client` com `set_settings(api_key="teste-key")`):

```python
def _cria_community(db_session: Session, name: str, notes: str | None = None) -> models.Community:
    com = models.Community(name=name, notes=notes)
    db_session.add(com)
    db_session.commit()
    return com


def test_patch_community_disable_e_update_segundo_ruling_1(
    client: TestClient, db_session: Session
) -> None:
    com = _cria_community(db_session, "api-c3-com")
    try:
        # PATCH puro de desativação → community.disable
        off = client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": False}, headers=_auth())
        assert off.status_code == 200 and off.json()["admin_status"] is False

        # repetição → 200 sem novo evento
        off2 = client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": False}, headers=_auth())
        assert off2.status_code == 200
        tipos = [
            e.type
            for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        ]
        assert tipos.count("community.disable") == 1

        # sem flag: fora da lista; com flag: dentro
        assert com.id not in [c["id"] for c in client.get("/api/v1/communities", headers=_auth()).json()]
        assert com.id in [
            c["id"]
            for c in client.get("/api/v1/communities?include_disabled=true", headers=_auth()).json()
        ]

        # reativação pura → *.update (sem enable_* dedicado, decisão §3.6)
        on = client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": True}, headers=_auth())
        assert on.status_code == 200 and on.json()["admin_status"] is True
        tipos = [
            e.type
            for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
        ]
        assert tipos.count("community.update") == 1

        # nome → community.update com antes/depois
        renomear = client.patch(f"/api/v1/communities/{com.id}", json={"name": "api-c3-renomeada"}, headers=_auth())
        assert renomear.status_code == 200 and renomear.json()["name"] == "api-c3-renomeada"
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def test_patch_community_erros(client: TestClient, db_session: Session) -> None:
    com = _cria_community(db_session, "api-c3-err")
    try:
        # admin_status null → 400
        assert client.patch(f"/api/v1/communities/{com.id}", json={"admin_status": None}, headers=_auth()).status_code == 400
        # nome vazio → 400
        assert client.patch(f"/api/v1/communities/{com.id}", json={"name": "  "}, headers=_auth()).status_code == 400
        # 404
        assert client.patch("/api/v1/communities/99999", json={"name": "x"}, headers=_auth()).status_code == 404
        # sem credencial → 401 (require_actor)
        assert client.patch(f"/api/v1/communities/{com.id}", json={"name": "x"}).status_code == 401
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def test_patch_policy_profile_ruling_1(client: TestClient, db_session: Session) -> None:
    perfil = models.PolicyProfile(
        name="api-c3-perfil", label="Perfil API", direction="export", kind="produto", prefixes=None
    )
    db_session.add(perfil)
    db_session.commit()
    try:
        off = client.patch(
            f"/api/v1/policy-profiles/{perfil.id}", json={"admin_status": False}, headers=_auth()
        )
        assert off.status_code == 200 and off.json()["admin_status"] is False
        assert perfil.id not in [
            p["id"] for p in client.get("/api/v1/policy-profiles", headers=_auth()).json()
        ]
        on = client.patch(
            f"/api/v1/policy-profiles/{perfil.id}", json={"admin_status": True}, headers=_auth()
        )
        assert on.status_code == 200 and on.json()["admin_status"] is True
        perfil.id  # id no schema de resposta
        edit = client.patch(
            f"/api/v1/policy-profiles/{perfil.id}",
            json={"label": "Perfil API 2", "direction": "import"},
            headers=_auth(),
        )
        assert edit.status_code == 200 and edit.json()["label"] == "Perfil API 2"
        assert edit.json()["direction"] == "import"
        # 404 e sem auth
        assert client.patch("/api/v1/policy-profiles/99999", json={"label": "x"}, headers=_auth()).status_code == 404
        assert client.patch(f"/api/v1/policy-profiles/{perfil.id}", json={"label": "x"}).status_code == 401
    finally:
        perfil = db_session.get(models.PolicyProfile, perfil.id)
        if perfil is not None:
            db_session.delete(perfil)
            db_session.commit()
```

> Confira o topo de `tests/api/test_communities_api.py`: se o fixture `client` não existir lá, copie o padrão de `test_contacts_api.py` (fixture `client` com `set_settings(Settings(api_key="teste-key", _env_file=None))` + helper `_auth()`).

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/api/test_communities_api.py tests/api/test_policy_profiles_api.py -q`
Expected: FAIL — `405 Method Not Allowed` no PATCH.

- [ ] **Step 3: PATCH no router de communities**

Em `src/gerenet/api/routers/communities.py`, substitua o arquivo por:

```python
"""Catálogo de communities (§25.6) — list desde o ciclo B; update/disable no C3."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import CommunityOut, CommunityUpdate
from gerenet.domain.services import communities as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/communities", tags=["communities"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[CommunityOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_communities(session, include_disabled=include_disabled)


@router.patch("/{community_id}", response_model=CommunityOut)
def atualizar(
    community_id: int,
    data: CommunityUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        # Ruling 1: desativação pura → serviço dedicado (idempotente — Ruling 5);
        # o resto (inclusive reativação pura) → update_* genérico.
        if mudancas == {"admin_status": False}:
            return svc.disable_community(session, community_id, actor=actor.nome)
        return svc.update_community(session, community_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 4: PATCH no router de policy profiles**

Em `src/gerenet/api/routers/policy_profiles.py`, adicione após `listar`:

```python
@router.patch("/{profile_id}", response_model=PolicyProfileOut)
def atualizar(
    profile_id: int,
    data: PolicyProfileUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        # Ruling 1: desativação pura → serviço dedicado (idempotente — Ruling 5).
        if mudancas == {"admin_status": False}:
            return svc.disable_policy_profile(session, profile_id, actor=actor.nome)
        return svc.update_policy_profile(session, profile_id, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

E atualize os imports desse arquivo:

```python
from gerenet.api.deps import Actor, require_actor
from gerenet.domain.schemas import PolicyProfileOut, PolicyProfileUpdate
from gerenet.domain.services import policy_profiles as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_communities_api.py tests/api/test_policy_profiles_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/api/routers/communities.py src/gerenet/api/routers/policy_profiles.py tests/api/test_communities_api.py tests/api/test_policy_profiles_api.py
git commit -m "feat(api): PATCH de catálogos com ruling 1 (S1.2)"
```

---

### Task 6: Catálogos — comando `update` no CLI + limpeza restante (S1.2, backend 3/3 + S3.2)

**Files:**
- Modify: `src/gerenet/cli/communities.py`
- Modify: `src/gerenet/cli/policy_profiles.py`
- Test: `tests/cli/test_cli_smoke.py`

**Interfaces:**
- Consumes: `svc.update_community`/`svc.update_policy_profile` (Task 4); `get_session` de `gerenet.db`; `CliRunner` (padrão do arquivo).
- Produces:
  - `gerenet communities update <ID> [--name ...] [--notes ...]`
  - `gerenet policy-profiles update <ID> [--name ...] [--label ...] [--direction ...] [--kind ...] [--prefixes ...] [--notes ...]`
  - Nenhuma opção nova no `list` (já tem `--all`); **sem `--disable` no CLI** (espec: só `update` — desativação continua via PATCH/web).

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/cli/test_cli_smoke.py`, adicione (o arquivo já importa `runner`, `models`, `select`; confira — e note que **item de catálogo criado aqui é apagado no finally**):

```python
def test_cli_communities_update(db_session: Session) -> None:
    com = models.Community(name="cli-c3-com", notes="antes")
    db_session.add(com)
    db_session.commit()
    try:
        r = runner.invoke(app, ["communities", "update", str(com.id), "--name", "cli-c3-novo", "--notes", "depois"])
        assert r.exit_code == 0, r.output
        assert "cli-c3-novo" in r.output
        persistido = db_session.scalar(
            select(models.Community).where(models.Community.id == com.id)
        )
        assert persistido.name == "cli-c3-novo" and persistido.notes == "depois"
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def test_cli_policy_profiles_update(db_session: Session) -> None:
    perfil = models.PolicyProfile(
        name="cli-c3-perfil", label="Perfil CLI", direction="export", kind="produto", prefixes=None
    )
    db_session.add(perfil)
    db_session.commit()
    try:
        r = runner.invoke(
            app,
            ["policy-profiles", "update", str(perfil.id), "--label", "Perfil CLI 2", "--prefixes", "192.0.2.0/24,198.51.100.0/24"],
        )
        assert r.exit_code == 0, r.output
        persistido = db_session.scalar(
            select(models.PolicyProfile).where(models.PolicyProfile.id == perfil.id)
        )
        assert persistido.label == "Perfil CLI 2"
        assert persistido.prefixes == ["192.0.2.0/24", "198.51.100.0/24"]
    finally:
        perfil = db_session.get(models.PolicyProfile, perfil.id)
        if perfil is not None:
            db_session.delete(perfil)
            db_session.commit()
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/cli/test_cli_smoke.py::test_cli_communities_update tests/cli/test_cli_smoke.py::test_cli_policy_profiles_update -q`
Expected: FAIL — `No such command 'update'`.

- [ ] **Step 3: Implementar o CLI de communities**

Em `src/gerenet/cli/communities.py`, substitua o arquivo por:

```python
"""Communities (catálogo) — list desde o ciclo B; update no C3 (spec §S1.2)."""
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import CommunityUpdate
from gerenet.domain.services import communities as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Communities BGP (catálogo).")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista o catálogo de communities."""
    with get_session() as session:
        for com in svc.list_communities(session, include_disabled=include_disabled):
            typer.echo(f"{com.id:>3}  {com.name:<16} {com.notes or ''}")


@app.command("update")
def atualizar(
    community_id: int = typer.Argument(..., help="ID da community."),
    name: str | None = typer.Option(None, "--name", help="Novo nome."),
    notes: str | None = typer.Option(None, "--notes", help="Novas observações."),
) -> None:
    """Atualiza nome/observações de uma community (evento community.update)."""
    dados: dict = {}
    if name is not None:
        dados["name"] = name
    if notes is not None:
        dados["notes"] = notes
    with get_session() as session:
        try:
            com = svc.update_community(session, community_id, CommunityUpdate(**dados), actor="cli")
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Community {com.id} atualizada: {com.name} ({com.notes or 'sem observações'}).")
```

- [ ] **Step 4: Implementar o CLI de policy profiles**

Em `src/gerenet/cli/policy_profiles.py`, adicione após `listar`:

```python
@app.command("update")
def atualizar(
    profile_id: int = typer.Argument(..., help="ID do perfil."),
    name: str | None = typer.Option(None, "--name", help="Novo nome (slug EN)."),
    label: str | None = typer.Option(None, "--label", help="Novo rótulo PT-BR."),
    direction: str | None = typer.Option(None, "--direction", help="Direção: import|export."),
    kind: str | None = typer.Option(None, "--kind", help="Tipo (produto)."),
    prefixes: str | None = typer.Option(None, "--prefixes", help="Novos prefixos, separados por vírgula."),
    notes: str | None = typer.Option(None, "--notes", help="Novas observações."),
) -> None:
    """Atualiza campos de um produto de roteamento (evento policy_profile.update)."""
    dados: dict = {}
    if name is not None:
        dados["name"] = name
    if label is not None:
        dados["label"] = label
    if direction is not None:
        dados["direction"] = direction
    if kind is not None:
        dados["kind"] = kind
    if prefixes is not None:
        dados["prefixes"] = [p.strip() for p in prefixes.split(",") if p.strip()]
    if notes is not None:
        dados["notes"] = notes
    with get_session() as session:
        try:
            perfil = svc.update_policy_profile(
                session, profile_id, PolicyProfileUpdate(**dados), actor="cli"
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Perfil {perfil.id} atualizado: {perfil.name} ({perfil.label}).")
```

E ajuste os imports de `src/gerenet/cli/policy_profiles.py`:

```python
from gerenet.domain.schemas import PolicyProfileUpdate
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/cli/test_cli_smoke.py -q`
Expected: PASS (inclui os fumos existentes — a docstring do `app` mudou, sem efeito).

- [ ] **Step 6: Verificação final do S3.2 (sem-trabalho registrado)**

Run: `rtk proxy grep -n "include-disabled" src/gerenet/cli/users.py && rtk proxy grep -n "DIST" tests/api/test_static_spa.py`
Expected: `cli/users.py` com `--include-disabled` e `--all`; **nenhum** `DIST` no test_static_spa (fixture usa `tmp_path`) — os dois itens de limpeza já foram resolvidos na revisão final do C2; não há código a mudar aqui.

- [ ] **Step 7: Commit**

```bash
git add src/gerenet/cli/communities.py src/gerenet/cli/policy_profiles.py tests/cli/test_cli_smoke.py
git commit -m "feat(cli): comando update para catálogos communities e policy-profiles (S1.2)"
```

---

### Task 7: PATCH de devices roteia para `enable_device` (S1.3)

**Files:**
- Modify: `src/gerenet/api/routers/devices.py:60-75` (`atualizar`)
- Test: `tests/api/test_devices_api.py`

**Interfaces:**
- Consumes: `svc.enable_device(session, device_id, *, actor)` (services/devices.py:70-83 — idempotente, evento `device.enable`).
- Produces: PATCH puro `{"admin_status": true}` num device desativado → `device.enable` (em vez de `device.update`); repetição → 200 sem evento (Ruling 5); mudanças mistas permanecem `device.update`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/api/test_devices_api.py`, adicione:

```python
def test_patch_reativar_usa_enable_device(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r5-en", "management_address": "10.0.0.11"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]

    assert client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()).status_code == 200
    resp = client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": True}, headers=_auth())
    assert resp.status_code == 200 and resp.json()["admin_status"] is True

    # repetição (já ativo) → 200 sem novo evento (Ruling 5)
    repetido = client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": True}, headers=_auth())
    assert repetido.status_code == 200 and repetido.json()["admin_status"] is True

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.disable", "device.enable"]


def test_patch_reativar_misto_continua_update(db_session: Session, client: TestClient) -> None:
    criado = client.post(
        "/api/v1/devices",
        json={"name": "r6-mix", "management_address": "10.0.0.12"},
        headers=_auth(),
    )
    assert criado.status_code == 201
    dev_id = criado.json()["id"]
    assert client.patch(f"/api/v1/devices/{dev_id}", json={"admin_status": False}, headers=_auth()).status_code == 200
    # admin_status true + outro campo → caminho genérico (device.update)
    resp = client.patch(
        f"/api/v1/devices/{dev_id}", json={"admin_status": True, "role": "edge"}, headers=_auth()
    )
    assert resp.status_code == 200 and resp.json()["role"] == "edge"
    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.disable", "device.update"]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/api/test_devices_api.py::test_patch_reativar_usa_enable_device -q`
Expected: FAIL — `assert tipos == ["device.create", "device.disable", "device.enable"]` vira `[... "device.update"]` (rota genérica).

- [ ] **Step 3: Implementar o roteamento**

Em `src/gerenet/api/routers/devices.py`, dentro de `atualizar`, logo após o bloco `desativando` (linhas 66-70), insira:

```python
        reativando = (
            mudancas.get("admin_status") is True
            and set(mudancas) == {"admin_status"}
            and dev.admin_status is not True
        )
        if mudancas == {"admin_status": True} and not reativando:
            return dev  # repeat enable: sem transição, sem evento (Ruling 5)
        if reativando:
            return svc.enable_device(session, device_id, actor=actor.nome)
```

> O `desativar` inline continua como está (evento `device.disable` + `comm_status = "unknown"`); apenas o caminho de reativação pura passa a usar o serviço dedicado, como decide a spec §3.6.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/api/test_devices_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/api/routers/devices.py tests/api/test_devices_api.py
git commit -m "feat(api): PATCH de devices reativa via enable_device (S1.3)"
```

---

### Task 8: Modal com a11y + ConfirmDialog + dialog de reset do Users (S2.1)

**Files:**
- Create: `web/src/components/Modal.tsx`
- Modify: `web/src/components/ConfirmDialog.tsx`
- Modify: `web/src/pages/Users.tsx:95-118` (dialog de reset → Modal)
- Modify: `web/src/styles/global.css` (near `.dialog` ~linha 265)
- Test: `web/src/components/Modal.test.tsx`

**Interfaces:**
- Consumes: classes já existentes `.dialog-backdrop`, `.dialog`, `.dialog-actions` (global.css:259-274).
- Produces:
  - `<Modal aberto titulo onFechar children ariaLabel?>` — `role="dialog"`, `aria-modal`, `aria-labelledby` (ou `aria-label`), foco inicial no primeiro focusable, trap de `Tab`, `Escape` fecha, clique no backdrop fecha, retorno de foco ao fechar, scroll interno.
  - `ConfirmDialog` mantém a API atual (`aberto/titulo/mensagem/onConfirmar/onCancelar/confirmando?`) — agora sobre o Modal.
  - `Users.tsx` migra o reset de senha para o Modal (mesmo comportamento, sem dialog cru).

- [ ] **Step 1: Escrever o teste que falha**

Crie `web/src/components/Modal.test.tsx`:

```tsx
import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";

function AbreEFecha() {
  const [aberto, setAberto] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setAberto(true)}>
        Gatilho
      </button>
      {aberto && (
        <Modal aberto titulo="Teste" onFechar={() => setAberto(false)}>
          <input aria-label="Campo" />
          <button type="button">Ok</button>
        </Modal>
      )}
    </>
  );
}

describe("Modal", () => {
  it("recebe foco no primeiro focusable ao abrir", async () => {
    render(
      <Modal aberto titulo="Teste" onFechar={vi.fn()}>
        <input aria-label="Campo" />
        <button type="button">Ok</button>
      </Modal>,
    );
    await waitFor(() => expect(screen.getByLabelText("Campo")).toHaveFocus());
  });

  it("Escape fecha", async () => {
    const onFechar = vi.fn();
    render(
      <Modal aberto titulo="Teste" onFechar={onFechar}>
        <button type="button">Ok</button>
      </Modal>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("clique no backdrop fecha (e não no conteúdo)", async () => {
    const onFechar = vi.fn();
    const { container } = render(
      <Modal aberto titulo="Teste" onFechar={onFechar}>
        <button type="button">Ok</button>
      </Modal>,
    );
    await userEvent.click(container.querySelector(".dialog-backdrop") as Element);
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("Tab faz trap no dialog", async () => {
    render(
      <Modal aberto titulo="Teste" onFechar={vi.fn()}>
        <input aria-label="Campo" />
        <button type="button">Ok</button>
      </Modal>,
    );
    const campo = screen.getByLabelText("Campo");
    await waitFor(() => expect(campo).toHaveFocus());
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Ok" })).toHaveFocus();
    await userEvent.tab();
    expect(campo).toHaveFocus(); // voltou para o primeiro (trap)
  });

  it("devolve o foco ao gatilho ao fechar", async () => {
    render(<AbreEFecha />);
    await userEvent.click(screen.getByRole("button", { name: "Gatilho" }));
    await waitFor(() => expect(screen.getByLabelText("Campo")).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.getByRole("button", { name: "Gatilho" })).toHaveFocus());
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: (em `web/`) `npm run test -- src/components/Modal.test.tsx`
Expected: FAIL — `Cannot find module './Modal'`.

- [ ] **Step 3: Implementar o Modal**

Crie `web/src/components/Modal.tsx`:

```tsx
import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({
  aberto,
  titulo,
  onFechar,
  children,
  ariaLabel,
}: {
  aberto: boolean;
  titulo: string;
  onFechar: () => void;
  children: ReactNode;
  ariaLabel?: string;
}) {
  const tituloId = useId();
  const painelRef = useRef<HTMLDivElement>(null);
  // Ref para não re-executar o effect a cada render (onFechar é inline nos callers).
  const onFecharRef = useRef(onFechar);
  onFecharRef.current = onFechar;

  useEffect(() => {
    if (!aberto) return;
    const painel = painelRef.current;
    if (!painel) return;
    const anterior = document.activeElement as HTMLElement | null;
    const focaveis = () =>
      Array.from(painel.querySelectorAll<HTMLElement>(FOCUSABLE));
    (focaveis()[0] ?? painel).focus();

    function aoTeclar(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onFecharRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const els = focaveis();
      if (els.length === 0) {
        e.preventDefault();
        return;
      }
      const primeiro = els[0];
      const ultimo = els[els.length - 1];
      if (e.shiftKey && document.activeElement === primeiro) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primeiro.focus();
      }
    }
    document.addEventListener("keydown", aoTeclar);
    return () => {
      document.removeEventListener("keydown", aoTeclar);
      anterior?.focus();
    };
  }, [aberto]);

  if (!aberto) return null;
  return (
    <div
      className="dialog-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onFecharRef.current();
      }}
    >
      <div
        ref={painelRef}
        className="dialog dialog-scroll"
        role="dialog"
        aria-modal="true"
        aria-labelledby={tituloId}
        aria-label={ariaLabel}
        tabIndex={-1}
      >
        <h2 id={tituloId}>{titulo}</h2>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: CSS do scroll interno**

Em `web/src/styles/global.css`, após o bloco `.dialog-actions` (~linha 274), adicione:

```css
.dialog-scroll { max-height: 85vh; overflow-y: auto; }
```

- [ ] **Step 5: Refatorar o ConfirmDialog sobre o Modal**

Substitua o conteúdo de `web/src/components/ConfirmDialog.tsx` por:

```tsx
import { Modal } from "@/components/Modal";

export function ConfirmDialog({
  aberto,
  titulo,
  mensagem,
  onConfirmar,
  onCancelar,
  confirmando,
}: {
  aberto: boolean;
  titulo: string;
  mensagem: string;
  onConfirmar: () => void;
  onCancelar: () => void;
  confirmando?: boolean;
}) {
  // API preservada (spec S2.1): a implementação passa a ser o Modal com a11y.
  return (
    <Modal aberto={aberto} titulo={titulo} onFechar={onCancelar}>
      <p>{mensagem}</p>
      <div className="dialog-actions">
        <button onClick={onCancelar} disabled={confirmando}>
          Cancelar
        </button>
        <button className="danger" onClick={onConfirmar} disabled={confirmando}>
          {confirmando ? "Aguarde…" : "Confirmar"}
        </button>
      </div>
    </Modal>
  );
}
```

- [ ] **Step 6: Migrar o dialog de reset do Users**

Em `web/src/pages/Users.tsx`, substitua o bloco `{resetando && (<div role="dialog" ...>...</div>)}` (linhas 95-118) por:

```tsx
      {resetando && (
        <Modal
          aberto
          titulo={`Redefinir senha de ${resetando.username}`}
          onFechar={() => setResetando(null)}
        >
          <FormField label="Nova senha">
            <input
              type="password"
              value={senhaReset}
              onChange={(e) => setSenhaReset(e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
          {senha.error && <p role="alert">{String(senha.error.message ?? "Falha ao redefinir.")}</p>}
          <div className="dialog-actions">
            <button onClick={() => setResetando(null)} disabled={senha.isPending}>
              Cancelar
            </button>
            <button
              className="primary"
              disabled={senha.isPending || senhaReset.length === 0}
              onClick={() =>
                void senha
                  .mutateAsync({ id: resetando.id, password: senhaReset })
                  .then(() => setResetando(null))
                  .catch(() => undefined)
              }
            >
              {senha.isPending ? "Aguarde…" : "Redefinir"}
            </button>
          </div>
        </Modal>
      )}
```

E adicione o import no topo de `web/src/pages/Users.tsx`:

```tsx
import { Modal } from "@/components/Modal";
```

- [ ] **Step 7: Rodar e ver passar**

Run: (em `web/`) `npm run test -- src/components/Modal.test.tsx src/pages/Users.test.tsx`
Expected: PASS (o teste de reset do Users — se existir — usa o mesmo fluxo; `test-setup.ts` já importa `@testing-library/jest-dom` para os matchers).

- [ ] **Step 8: Commit**

```bash
git add web/src/components/Modal.tsx web/src/components/ConfirmDialog.tsx web/src/pages/Users.tsx web/src/styles/global.css web/src/components/Modal.test.tsx
git commit -m "feat(web): Modal com a11y (foco, Escape, backdrop, trap) e ConfirmDialog refatorado sobre ele (S2.1)"
```

---

### Task 9: Hooks com `includeDisabled`, toggle "Ver desativados" e Reativar por página (S2.2)

**Files:**
- Modify: `web/src/api/types.ts` (CommunityOut + novos tipos de update)
- Modify: `web/src/api/hooks.ts` (`useLista` + hooks por entidade + hooks de atualizar dos catálogos)
- Modify: `web/src/styles/global.css` (classe `.inline-check`)
- Modify: páginas: `web/src/pages/Users.tsx`, `Devices.tsx`, `Sites.tsx`, `Organizations.tsx`, `Contacts.tsx`, `Circuits.tsx`, `BgpSessions.tsx`, `PrefixAuthorizations.tsx`, `Communities.tsx`, `PolicyProfiles.tsx`
- Test: `web/src/pages/Sites.test.tsx`, `web/src/pages/Users.test.tsx`

**Interfaces:**
- Consumes: backend S1.1 (contacts `include_disabled`), S1.2/PATCH de catálogos; `StatusBadge` com estados `ativo`/`inativo`.
- Produces:
  - `useLista<T>(chave, url, opts?: { includeDisabled?: boolean })` — queryKey `[chave, booleano]` (a invalidação por `[chave]` continua cobrindo, pois react-query invalida por prefixo).
  - `useDevices/useSites/useOrganizations/useContacts/useCircuits/useCommunities(opts?)`, `useUsers(opts?)`, `useBgpSessions(filtros & { include_disabled? })`, `usePolicyProfiles(filtros & { include_disabled? })`.
  - `useCommunityAtualizar`, `usePolicyProfileAtualizar`.
  - Em cada página: checkbox "Ver desativados", coluna/estado "Situação" (badge), botão **Reativar** (ConfirmDialog, texto invertido) e **`.catch`** nos confirm handlers (erro visível em `role="alert"`).
  - `Users.tsx`: botão rotula **Desativar** ou **Reativar** conforme `is_active` (correção do bug de rótulo).

- [ ] **Step 1: Escrever os testes de página que falham**

Substitua o conteúdo de `web/src/pages/Sites.test.tsx` por:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Sites from "./Sites";
import { AuthProvider } from "@/auth/auth-context";

const ativa = { id: 1, name: "SPO", city: "São Paulo", uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true };
const inativa = { id: 2, name: "REC-off", city: "Recife", uf: "PE", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: false };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ ...(url.includes("1") ? ativa : inativa), ...body }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ id: 3, ...body, p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.startsWith("/api/v1/sites")) {
        const comDesativados = new URL(url).search.includes("include_disabled=true");
        return new Response(JSON.stringify(comDesativados ? [ativa, inativa] : [ativa]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/v1/auth/me")
        return new Response(JSON.stringify({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderSites() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <Sites />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Sites", () => {
  it("lista sites e cria novo pela API", async () => {
    renderSites();
    expect(await screen.findByText("SPO")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Nome *"), "REC");
    await userEvent.type(screen.getByLabelText("Cidade"), "Recife");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("REC"))).toBe(true);
    });
  });

  it("usa o perfil do usuário logado para liberar escrita", async () => {
    renderSites();
    expect(await screen.findByText("SPO")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cadastrar" })).toBeInTheDocument();
  });

  it("ver desativados liga include_disabled e mostra o badge de inativo", async () => {
    renderSites();
    expect(await screen.findByText("SPO")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await screen.findByText("REC-off");
    expect(screen.getByText("inativo")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => String(c[0]).includes("include_disabled=true"))).toBe(true);
    });
  });

  it("Reativar dispara PATCH admin_status:true no fluxo de confirmação", async () => {
    renderSites();
    await screen.findByText("SPO");
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await userEvent.click(await screen.findByRole("button", { name: "Reativar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(
        chamadas.some(
          (c) => c[1]?.method === "PATCH" && c[1]?.body && String(c[1].body).includes('"admin_status":true'),
        ),
      ).toBe(true);
    });
  });
});
```

Em `web/src/pages/Users.test.tsx`, ajuste o teste existente do botão (se o texto "Desativar" era assertado para um usuário ativo continua igual) e adicione:

```tsx
  it("mostra Reativar para usuário inativo", async () => {
    // mock de users inclui o usuário "inativo-1" quando include_disabled=true
    renderUsers();
    await screen.findByText("boss");
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await screen.findByText("inativo-1");
    expect(screen.getByRole("button", { name: "Reativar" })).toBeInTheDocument();
  });
```

> Verifique o mock de `fetch` atual do `Users.test.tsx`: ele deve devolver `[user ativo, user inativo-1]` quando a URL contém `include_disabled=true`, e o fixture de usuário precisa do shape de `UserOut`. Ajuste o mock localmente se o shape atual divergir (o teste é sobre o rótulo do botão, não sobre o mock).

- [ ] **Step 2: Rodar para ver falhar**

Run: (em `web/`) `npm run test -- src/pages/Sites.test.tsx src/pages/Users.test.tsx`
Expected: FAIL — falta o checkbox "Ver desativados" (query byLabelText falha) e o fetch não recebe `include_disabled=true`.

- [ ] **Step 3: Types**

Em `web/src/api/types.ts`:

1. Em `CommunityOut`, adicione o campo (deve ficar igual ao do backend — Task 4):

```ts
export interface CommunityOut {
  id: number;
  name: string;
  notes: string | null;
  admin_status: boolean;
}
```

2. Após `CommunityOut`, adicione:

```ts
export type CommunityUpdateIn = { name?: string; notes?: string | null; admin_status?: boolean };

export type PolicyProfileUpdateIn = {
  name?: string;
  label?: string;
  direction?: "import" | "export";
  kind?: string;
  prefixes?: string[] | null;
  notes?: string | null;
  admin_status?: boolean;
};
```

- [ ] **Step 4: Hooks**

Em `web/src/api/hooks.ts`:

1. Substitua `useLista` e os hooks de lista por:

```ts
export function useLista<T>(chave: string, url: string, opts: { includeDisabled?: boolean } = {}) {
  return useQuery({
    queryKey: [chave, opts.includeDisabled ?? false],
    queryFn: () => apiFetch<T[]>(opts.includeDisabled ? `${url}?include_disabled=true` : url),
  });
}
```

2. Adicione os hooks de atualizar dos catálogos (junto aos demais `useXxxAtualizar`):

```ts
export const useCommunityAtualizar = () =>
  useAtualizar<CommunityUpdateIn, CommunityOut>("communities", "/api/v1/communities");
export const usePolicyProfileAtualizar = () =>
  useAtualizar<PolicyProfileUpdateIn, PolicyProfileOut>("policy-profiles", "/api/v1/policy-profiles");
```

3. Ajuste as assinaturas listadas (mantendo os callers existentes sem argumento funcionando):

```ts
export const useUsers = (opts?: { includeDisabled?: boolean }) =>
  useQuery({
    queryKey: ["users", opts?.includeDisabled ?? false],
    queryFn: () => apiFetch<UserOut[]>(opts?.includeDisabled ? "/api/v1/users?include_disabled=true" : "/api/v1/users"),
  });

export const useDevices = (opts?: { includeDisabled?: boolean }) => useLista<DeviceOut>("devices", "/api/v1/devices", opts);
export const useSites = (opts?: { includeDisabled?: boolean }) => useLista<SiteOut>("sites", "/api/v1/sites", opts);
export const useOrganizations = (opts?: { includeDisabled?: boolean }) => useLista<OrganizationOut>("organizations", "/api/v1/organizations", opts);
export const useContacts = (opts?: { includeDisabled?: boolean }) => useLista<ContactOut>("contacts", "/api/v1/contacts", opts);
export const useCircuits = (opts?: { includeDisabled?: boolean }) => useLista<CircuitOut>("circuits", "/api/v1/circuits", opts);
export const useCommunities = (opts?: { includeDisabled?: boolean }) => useLista<CommunityOut>("communities", "/api/v1/communities", opts);
```

4. Em `useBgpSessions` (linha ~218), estenda o tipo de filtro e a query string:

```ts
export const useBgpSessions = (filtros?: { circuit_id?: number; device_id?: number; include_disabled?: boolean }) =>
  useQuery({
    queryKey: ["bgp-sessions", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.circuit_id) qs.set("circuit_id", String(filtros.circuit_id));
      if (filtros?.device_id) qs.set("device_id", String(filtros.device_id));
      if (filtros?.include_disabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<BgpSessionOut[]>(`/api/v1/bgp-sessions${suf}`);
    },
  });
```

5. Em `usePolicyProfiles` (linha ~289), estenda:

```ts
export const usePolicyProfiles = (filtros?: { direction?: string; include_disabled?: boolean }) =>
  useQuery({
    queryKey: ["policy-profiles", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.direction) qs.set("direction", filtros.direction);
      if (filtros?.include_disabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<PolicyProfileOut[]>(`/api/v1/policy-profiles${suf}`);
    },
  });
```

> `usePrefixAuthorizations` já aceita `include_disabled` no filtro (linha ~302) — nenhuma mudança é necessária nela.

- [ ] **Step 5: CSS do checkbox**

Em `web/src/styles/global.css`, adicione perto dos estilos de form (após `.form-inline`):

```css
.inline-check {
  display: inline-flex; align-items: center; gap: 0.4rem;
  margin: 0.8rem 0; font-size: 0.9rem; cursor: pointer;
}
```

- [ ] **Step 6: Página modelo — `Sites.tsx`**

Aplique este diff completo (estado + toggle + coluna + Reativar + `.catch`):

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useSiteAtualizar, useSiteCriar, useSites } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { SiteOut } from "@/api/types";

const FORM_VAZIO = { name: "", city: "", uf: "", p2p_ipv4_block: "", p2p_ipv6_base: "" };

export default function Sites() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useSites({ includeDisabled: incluirInativos });
  const criar = useSiteCriar();
  const atualizar = useSiteAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<SiteOut | null>(null);
  const [reativando, setReativando] = useState<SiteOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        city: form.city || null,
        uf: form.uf || null,
        p2p_ipv4_block: form.p2p_ipv4_block || null,
        p2p_ipv6_base: form.p2p_ipv6_base || null,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar site.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Sites" />
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
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="Cidade">
            <input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
          </FormField>
          <FormField label="UF">
            <input value={form.uf} onChange={(e) => setForm({ ...form, uf: e.target.value })} />
          </FormField>
          <FormField label="Bloco IPv4 p2p">
            <input value={form.p2p_ipv4_block} onChange={(e) => setForm({ ...form, p2p_ipv4_block: e.target.value })} />
          </FormField>
          <FormField label="Base IPv6 p2p">
            <input value={form.p2p_ipv6_base} onChange={(e) => setForm({ ...form, p2p_ipv6_base: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<SiteOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "city", title: "Cidade", render: (s) => s.city ?? "—" },
          { key: "uf", title: "UF", render: (s) => s.uf ?? "—" },
          { key: "p2p_ipv4_block", title: "Bloco v4 p2p", render: (s) => s.p2p_ipv4_block ?? "—" },
          { key: "p2p_ipv6_base", title: "Base v6 p2p", render: (s) => s.p2p_ipv6_base ?? "—" },
          {
            key: "admin_status",
            title: "Situação",
            render: (s) => <StatusBadge estado={s.admin_status ? "ativo" : "inativo"} />,
          },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(s) =>
          podeEscrever && s.admin_status ? (
            <>
              <button type="button" onClick={() => setDesativando(s)}>
                Desativar
              </button>
            </>
          ) : podeEscrever ? (
            <button type="button" onClick={() => setReativando(s)}>
              Reativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O site fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar o site."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.name ?? ""}?`}
        mensagem="O site volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar o site."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
```

> Os botões do ConfirmDialog disparados por linhas mantêm `role="dialog"` via Modal; o `setErro` reaproveita o `<p role="alert">` existente (S2.5).

- [ ] **Step 7: Aplicar o mesmo padrão nas demais páginas**

Para cada página abaixo, replicar o diff padrão: (a) `useState` `incluirInativos`; (b) hook de lista com `{ includeDisabled: incluirInativos }` (ou filtro estendido); (c) `<label className="inline-check">` logo após o `PageHeader`; (d) coluna `Situação`/status quando faltar; (e) estado `reativando` + botão na ação inversa; (f) `.catch` no handler do ConfirmDialog.

- **`Devices.tsx`**: hook → `useDevices({ includeDisabled: incluirInativos })`; adicionar coluna após `last_collected_at`:
  ```tsx
  { key: "admin_status", title: "Situação", render: (d) => <StatusBadge estado={d.admin_status ? "ativo" : "inativo"} /> },
  ```
  Reativar usa o mesmo `useDeviceAtualizar` (PATCH `admin_status: true` — que agora cai em `enable_device` no backend, Task 7).
  ```tsx
  const [reativando, setReativando] = useState<DeviceOut | null>(null);
  ...
  <ConfirmDialog
    aberto={reativando !== null}
    titulo={`Reativar ${reativando?.name ?? ""}?`}
    mensagem="Volta a ser gerenciado; a coleta será retomada."
    onConfirmar={() => {
      if (reativando)
        void atualizar
          .mutateAsync({ id: reativando.id, admin_status: true })
          .then(() => setReativando(null))
          .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar o equipamento."));
    }}
    onCancelar={() => setReativando(null)}
    confirmando={atualizar.isPending}
  />
  ```
  na ação: `{podeEscrever && !d.admin_status && (<button type="button" onClick={() => setReativando(d)}>Reativar</button>)}`.
- **`Organizations.tsx`**: hook → `useOrganizations({ includeDisabled: incluirInativos })`; coluna `Situação` com `StatusBadge` (o arquivo já importa `StatusBadge`); mesmos dois estados/dialogs com mensagens equivalentes.
- **`Contacts.tsx`**: hook → `useContacts({ includeDisabled: incluirInativos })`; coluna `Situação` com `StatusBadge` (importar); dialogs Desativar/Reativar com `.catch` → `setErro`.
- **`Circuits.tsx`**: hook → `useCircuits({ includeDisabled: incluirInativos })`; a coluna `Situação` já existe (`admin_status`); dialogs com `.catch`.
- **`BgpSessions.tsx`**: hook → `useBgpSessions({ include_disabled: incluirInativos })` (filtro); a coluna "Situação" atual reflete `shutdown` — adicionar coluna de cadastro:
  ```tsx
  { key: "cadastro", title: "Cadastro", render: (s) => <StatusBadge estado={s.admin_status ? "ativo" : "inativo"} /> },
  ```
- **`PrefixAuthorizations.tsx`**: `usePrefixAuthorizations({ include_disabled: incluirInativos })`; trocar o render da coluna `admin_status` por `StatusBadge` (importar `StatusBadge`).
- **`Communities.tsx`**: hook → `useCommunities({ includeDisabled: incluirInativos })`; adicionar coluna:
  ```tsx
  { key: "admin_status", title: "Situação", render: (c) => <StatusBadge estado={c.admin_status ? "ativo" : "inativo"} /> },
  ```
  + `useCommunityAtualizar` para Reativar (`admin_status: true`); manter o botão "Detalhar" existente (será migrado para o Modal na Task 10).
- **`PolicyProfiles.tsx`**: `usePolicyProfiles({ direction: direcao || undefined, include_disabled: incluirInativos })`; coluna `Situação` com `StatusBadge`; `usePolicyProfileAtualizar` para Reativar.
- **`Users.tsx`**: hook → `useUsers({ includeDisabled: incluirInativos })`; corrigir `alternarAtivo` (bug de rótulo) OU manter o fluxo de um botão só com rótulo correto:

```tsx
  function alternarAtivo(u: UserOut) {
    if (u.id === usuario?.id) return;
    void atualizar.mutate({ id: u.id, is_active: !u.is_active });
  }
  ...
  {u.id !== usuario?.id && (
    <button type="button" onClick={() => alternarAtivo(u)}>
      {u.is_active ? "Desativar" : "Reativar"}
    </button>
  )}
```

- [ ] **Step 8: Rodar e ver passar**

Run: (em `web/`) `npm run test`
Expected: PASS (Sites/Users novos + todos os testes existentes — as colunas novas não mudam os textos assertados; se algum teste falhar por texto de botão, ajuste apenas o teste).

- [ ] **Step 9: Commit**

```bash
git add web/src/api/types.ts web/src/api/hooks.ts web/src/styles/global.css
git add web/src/pages/Sites.tsx web/src/pages/Devices.tsx web/src/pages/Organizations.tsx web/src/pages/Contacts.tsx web/src/pages/Circuits.tsx web/src/pages/BgpSessions.tsx web/src/pages/PrefixAuthorizations.tsx web/src/pages/Communities.tsx web/src/pages/PolicyProfiles.tsx web/src/pages/Users.tsx web/src/pages/Sites.test.tsx web/src/pages/Users.test.tsx
git commit -m "feat(web): ver desativados + reativar em todas as páginas (S2.2)"
```

---

### Task 10: Dialog de edição por página (S2.3)

**Files:**
- Modify: `web/src/pages/Sites.tsx`, `Devices.tsx`, `Users.tsx`, `Organizations.tsx`, `Contacts.tsx`, `Circuits.tsx`, `BgpSessions.tsx`, `PrefixAuthorizations.tsx`, `Communities.tsx`, `PolicyProfiles.tsx`
- Modify: `web/src/pages/Communities.tsx` (dialog "Detalhar" → Modal, a11y)
- Test: `web/src/pages/Sites.test.tsx` (edição), `web/src/pages/PrefixAuthorizations.test.tsx` (desativar+criar)

**Interfaces:**
- Consumes: `Modal` (Task 8); hooks `useXxxAtualizar` existentes + `useCommunityAtualizar`/`usePolicyProfileAtualizar` (Task 9); backend PATCHes (já existentes para as 8 operacionais + novos para catálogos).
- Produces: botão **Editar** na linha (quando `podeEscrever`), `<Modal>` com os campos do form de criação preenchidos com os valores atuais, submit → `mutateAsync`, `isPending` desabilita, erro dentro do dialog (`role="alert"`), sucesso fecha + refetch (invalidates do react-query já cobrem). **POA**: salvar = desativar a atual + criar outra (decisão do operador 2026-09-05).

- [ ] **Step 1: Escrever os testes que falham**

Em `web/src/pages/Sites.test.tsx`, adicione:

```tsx
  it("Editar preenche o modal, envia PATCH e fecha", async () => {
    renderSites();
    await screen.findByText("SPO");
    await userEvent.click(screen.getByRole("button", { name: "Editar" }));
    const nome = screen.getByLabelText("Nome *");
    await waitFor(() => expect(nome).toHaveValue("SPO"));
    await userEvent.clear(nome);
    await userEvent.type(nome, "SPO-2");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(
        chamadas.some(
          (c) => c[1]?.method === "PATCH" && c[1]?.body && String(c[1].body).includes("SPO-2"),
        ),
      ).toBe(true);
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
```

> Ajuste o mock PATCH do `beforeAll` se necessário para devolver `{ ...ativa, ...body }` (já faz isso no teste da Task 9).

Em `web/src/pages/PrefixAuthorizations.test.tsx` (crie o arquivo seguindo o padrão de `Sites.test.tsx` — stub de fetch com GET `/api/v1/prefix-authorizations`, `/api/v1/organizations` e `/api/v1/auth/me`):

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import PrefixAuthorizations from "./PrefixAuthorizations";
import { AuthProvider } from "@/auth/auth-context";

const authz = {
  id: 7,
  organization_id: 1,
  family: "ipv4",
  prefix: "192.0.2.0/24",
  origin: "manual",
  notes: null,
  admin_status: true,
};

beforeAll(() => {
  const chamadas: { metodo?: string; body?: BodyInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method) chamadas.push({ metodo: init.method, body: init.body });
      if (url.startsWith("/api/v1/prefix-authorizations"))
        return new Response(JSON.stringify([authz]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/organizations"))
        return new Response(JSON.stringify([{ id: 1, name: "Org", kind: "downstream", admin_status: true }]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      if (url === "/api/v1/auth/me")
        return new Response(JSON.stringify({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      return new Response("null", { status: 404 });
    }),
  );
});

describe("PrefixAuthorizations", () => {
  it("Editar desativa a atual e cria outra com os valores novos", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <AuthProvider>
            <PrefixAuthorizations />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("192.0.2.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Editar" }));
    const prefixo = screen.getByLabelText("Prefixo *");
    await waitFor(() => expect(prefixo).toHaveValue("192.0.2.0/24"));
    await userEvent.clear(prefixo);
    await userEvent.type(prefixo, "198.51.100.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    const chamadas = (fetch as ReturnType<typeof vi.fn>).mock.calls as [
      string,
      RequestInit | undefined,
    ][];
    await waitFor(() => {
      expect(chamadas.some((c) => c[1]?.method === "PATCH" && String(c[1].body).includes("admin_status"))).toBe(true);
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1].body).includes("198.51.100.0/24"))).toBe(true);
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: (em `web/`) `npm run test -- src/pages/Sites.test.tsx src/pages/PrefixAuthorizations.test.tsx`
Expected: FAIL — sem botão "Editar" (queryByName falha).

- [ ] **Step 3: Sites — edição por Modal (página de referência)**

Em `web/src/pages/Sites.tsx` (após a Task 9), adicione:

```tsx
import { Modal } from "@/components/Modal";
```

e no corpo do componente:

```tsx
  const [editando, setEditando] = useState<SiteOut | null>(null);
  const [formEdit, setFormEdit] = useState(FORM_VAZIO);
  const [erroEdit, setErroEdit] = useState<string | null>(null);

  function abrirEdicao(s: SiteOut) {
    setFormEdit({
      name: s.name,
      city: s.city ?? "",
      uf: s.uf ?? "",
      p2p_ipv4_block: s.p2p_ipv4_block ?? "",
      p2p_ipv6_base: s.p2p_ipv6_base ?? "",
    });
    setErroEdit(null);
    setEditando(s);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        name: formEdit.name,
        city: formEdit.city || null,
        uf: formEdit.uf || null,
        p2p_ipv4_block: formEdit.p2p_ipv4_block || null,
        p2p_ipv6_base: formEdit.p2p_ipv6_base || null,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar o site.");
    }
  }
```

Na `acao` (antes do Desativar):

```tsx
          {podeEscrever && (
            <button type="button" onClick={() => abrirEdicao(s)}>
              Editar
            </button>
          )}
```

E, antes do `</main>` (após os ConfirmDialogs):

```tsx
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Nome *">
              <input value={formEdit.name} onChange={(e) => setFormEdit({ ...formEdit, name: e.target.value })} required />
            </FormField>
            <FormField label="Cidade">
              <input value={formEdit.city} onChange={(e) => setFormEdit({ ...formEdit, city: e.target.value })} />
            </FormField>
            <FormField label="UF">
              <input value={formEdit.uf} onChange={(e) => setFormEdit({ ...formEdit, uf: e.target.value })} />
            </FormField>
            <FormField label="Bloco IPv4 p2p">
              <input value={formEdit.p2p_ipv4_block} onChange={(e) => setFormEdit({ ...formEdit, p2p_ipv4_block: e.target.value })} />
            </FormField>
            <FormField label="Base IPv6 p2p">
              <input value={formEdit.p2p_ipv6_base} onChange={(e) => setFormEdit({ ...formEdit, p2p_ipv6_base: e.target.value })} />
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
```

- [ ] **Step 4: Aplicar o mesmo padrão nas demais páginas**

A estrutura por página: `editando` + `formEdit` + `abrirEdicao(linha)` + `salvarEdicao(submit do PATCH)` + botão **Editar** + `<Modal>`. Campos por página (todos os campos do form de criação, menos os que o schema PATCH não aceita — `name` de devices e `code` de circuits são imutáveis, por isso ficam de fora):

- **`Devices.tsx`** (`DeviceUpdate`: ssh_port, model, family, role, site_id, asn, tags — sem `name`):
  ```tsx
  setFormEdit({
    ssh_port: d.ssh_port === null ? "" : String(d.ssh_port),
    model: d.model ?? "",
    family: d.family ?? "",
    role: d.role ?? "",
    site_id: d.site_id === null ? "" : String(d.site_id),
    asn: d.asn === null ? "" : String(d.asn),
    tags: d.tags.join(", "),
  });
  ```
  Submit:
  ```tsx
  await atualizar.mutateAsync({
    id: editando.id,
    ssh_port: formEdit.ssh_port === "" ? null : Number(formEdit.ssh_port),
    model: formEdit.model || null,
    family: formEdit.family || null,
    role: formEdit.role || null,
    site_id: formEdit.site_id === "" ? null : Number(formEdit.site_id),
    asn: formEdit.asn === "" ? null : Number(formEdit.asn),
    tags: formEdit.tags.split(",").map((t) => t.trim()).filter(Boolean),
  });
  ```
  O dialog usa o mesmo `<select>` de sites e o mesmo `FormField` do form de criação (os labels existentes: "Porta SSH", "Modelo", "Família", "Função", "Site", "ASN", "Tags (separadas por vírgula)").
- **`Users.tsx`** (`UserUpdateIn`: username + role):
  ```tsx
  setFormEdit({ username: u.username, role: u.role });
  // submit:
  await atualizar.mutateAsync({ id: editando.id, username: formEdit.username, role: formEdit.role });
  ```
  Formulário com `FormField "Usuário"` (input), `FormField "Perfil"` (select com `ROLES`) e botão Salvar. **Nota**: PATCH `role` em si mesmo → 403 do backend (guard existente); não mostrar Editar para a própria conta (`u.id !== usuario?.id`), como no botão de ativar.
- **`Organizations.tsx`** (`OrganizationUpdate`: name, legal_name, kind, asn, irr_as_set, notes):
  ```tsx
  setFormEdit({
    name: o.name,
    legal_name: o.legal_name ?? "",
    kind: o.kind as "downstream" | "parceiro",
    asn: o.asn === null ? "" : String(o.asn),
    irr_as_set: o.irr_as_set ?? "",
    notes: o.notes ?? "",
  });
  // submit:
  await atualizar.mutateAsync({
    id: editando.id,
    name: formEdit.name,
    legal_name: formEdit.legal_name || null,
    kind: formEdit.kind,
    asn: formEdit.asn === "" ? null : Number(formEdit.asn),
    irr_as_set: formEdit.irr_as_set || null,
    notes: formEdit.notes || null,
  });
  ```
- **`Contacts.tsx`** (`ContactUpdate`: organization_id, name, email, phone, kind) — prefill idêntico ao form; submit com `organization_id: Number(formEdit.organization_id)`; selects de organização já disponíveis.
- **`Circuits.tsx`** (`CircuitUpdate`: sem `code`; os demais campos) — prefill:
  ```tsx
  setFormEdit({
    organization_id: String(c.organization_id),
    site_id: String(c.site_id),
    access_device_id: String(c.access_device_id),
    access_port: c.access_port,
    edge_device_id: String(c.edge_device_id),
    backup_edge_device_id: c.backup_edge_device_id === null ? "" : String(c.backup_edge_device_id),
    stack: c.stack as "ipv4" | "ipv6" | "dual",
    vlan_mode: c.vlan_mode as "unica" | "separada",
    qinq: c.qinq,
    vrf: c.vrf ?? "",
    mtu: c.mtu === null ? "" : String(c.mtu),
    bandwidth: c.bandwidth ?? "",
    bfd: c.bfd,
    p2p_v4_len: String(c.p2p_v4_len) as "30" | "31",
    description: c.description ?? "",
    notes: c.notes ?? "",
    edge_trunk: c.edge_trunk ?? "",
  });
  ```
  Submit com `num()` para numéricos nulos (reaproveitar o helper `num` já existente na página).
- **`BgpSessions.tsx`** — o modal edita os **campos do PATCH** (BgpSessionUpdate: circuito, equipamento, afi, local/remote, source, asns, descrição, perfis, maximum-prefix + limiar, local-pref, med, prepend, keepalive, holdtime, BFD, graceful, shutdown, default route) — as ações especiais (communities, password) permanecem no detalhe. Prefill de `s` (`BgpSessionOut`) com os mesmos labels do form de criação; submit via `atualizar.mutateAsync({ id: editando.id, ...campos })` replicando as conversões do `onSubmit` (com `num()`).
- **`PrefixAuthorizations.tsx`** — fluxo especial (desativar + criar):
  ```tsx
  function abrirEdicao(z: PrefixAuthorizationOut) {
    setFormEdit({ organization_id: String(z.organization_id), family: z.family, prefix: z.prefix, notes: z.notes ?? "" });
    setErroEdit(null);
    setEditando(z);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      // Ruling 2: mudar dado = desativar a atual + criar outra (decisão C3 2026-09-05).
      await desativar.mutateAsync({ id: editando.id, admin_status: false });
      await criar.mutateAsync({
        organization_id: Number(formEdit.organization_id),
        family: formEdit.family,
        prefix: formEdit.prefix,
        notes: formEdit.notes || null,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar a autorização.");
    }
  }
  ```
  O modal traz seleção de organização, família, prefixo e observações (labels do form de criação: "Organização *", "Família", "Prefixo *", "Observações").
- **`Communities.tsx`** — além da edição (`CommunityUpdate`: name, notes), **migrar o dialog "Detalhar" para o Modal** (a11y):
  ```tsx
  const [editando, setEditando] = useState<CommunityOut | null>(null);
  const [formEdit, setFormEdit] = useState({ name: "", notes: "" });
  ...
  {detalhe && (
    <Modal aberto titulo={detalhe.name} onFechar={() => setDetalhe(null)}>
      <p>{detalhe.notes ?? "Sem observações."}</p>
      <div className="dialog-actions">
        <button type="button" onClick={() => setDetalhe(null)}>Fechar</button>
      </div>
    </Modal>
  )}
  ```
  e o dialog de edição usa `useCommunityAtualizar`.
- **`PolicyProfiles.tsx`** — `PolicyProfileUpdate`: name, label, direction (select import/export), kind (select com "produto"), prefixes (textarea, um por linha — split por `\n` no submit), notes; submit via `usePolicyProfileAtualizar`.

- [ ] **Step 5: Rodar e ver passar**

Run: (em `web/`) `npm run test`
Expected: PASS. Se o campo "Prefixo *" no POA colidir com outro label, use `getAllByLabelText` no teste (o form de criação também tem esse label).

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Sites.tsx web/src/pages/Devices.tsx web/src/pages/Users.tsx web/src/pages/Organizations.tsx web/src/pages/Contacts.tsx web/src/pages/Circuits.tsx web/src/pages/BgpSessions.tsx web/src/pages/PrefixAuthorizations.tsx web/src/pages/Communities.tsx web/src/pages/PolicyProfiles.tsx web/src/pages/Sites.test.tsx web/src/pages/PrefixAuthorizations.test.tsx
git commit -m "feat(web): dialog de edição por página (S2.3)"
```

---

### Task 11: Cards do dashboard — by_comm_status e idade da coleta (S2.4)

**Files:**
- Modify: `web/src/pages/Dashboard.tsx`
- Modify: `web/src/styles/global.css` (classe `.estados-equipamentos`)
- Modify: `web/src/pages/Dashboard.test.tsx`

**Interfaces:**
- Consumes: `DashboardOut` (já inclui `devices.by_comm_status: {ok?, fail?, unknown?}` e `per_device[].snapshot_age_seconds: number | null`).
- Produces: bloco abaixo do `h2` "Equipamentos" com total e contagens por estado (ok/falha/desconhecido, total = soma) + new card `.metric` "idade da última coleta" (maior `snapshot_age_seconds`, alerta > 24h).

- [ ] **Step 1: Escrever os testes que falham**

Substitua o fixture `DASH` e adicione asserts em `web/src/pages/Dashboard.test.tsx`:

1. No fixture, mude a linha do device:

```ts
      snapshot_age_seconds: 90000, // 25 h > 24 h → alerta
```

2. Adicione no `it` atual um bloco de asserts (após `expect(screen.getByText("2/3")).toBeTruthy();`):

```tsx
    expect(screen.getByText("3 equipamento(s): 1 ok · 1 com falha · 1 desconhecido")).toBeTruthy();
    expect(screen.getByText("25.0 h")).toBeTruthy();
```

- [ ] **Step 2: Rodar para ver falhar**

Run: (em `web/`) `npm run test -- src/pages/Dashboard.test.tsx`
Expected: FAIL — textos ausentes.

- [ ] **Step 3: Implementar**

Em `web/src/pages/Dashboard.tsx`, adicione antes do componente:

```tsx
const IDADE_ALERTA_SEGUNDOS = 24 * 3600;

function formatarIdade(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} d`;
}
```

E dentro do componente, após `const { data, isLoading, error } = useDashboard();`:

```tsx
  const idades = (data?.per_device ?? [])
    .map((d) => d.snapshot_age_seconds)
    .filter((x): x is number => x != null);
  const idadeMax = idades.length > 0 ? Math.max(...idades) : null;
```

Insira o card de coleta como **último card** de `<section className="health">` (logo após o card de prefixos, antes do `</section>`) e adicione o bloco de estados logo após o fechamento da `</section>`:

```tsx
            <div className="metric">
              <span
                className={`led ${idadeMax == null ? "gray" : idadeMax > IDADE_ALERTA_SEGUNDOS ? "amber" : "green"}`}
                aria-hidden="true"
              />
              <span className="val">{formatarIdade(idadeMax)}</span>
              <span className="label">idade da<br />última coleta</span>
            </div>
          </section>
          <p className="estados-equipamentos">
            {data.devices.total} equipamento(s): {data.devices.by_comm_status.ok ?? 0} ok ·{" "}
            {data.devices.by_comm_status.fail ?? 0} com falha ·{" "}
            {data.devices.by_comm_status.unknown ?? 0} desconhecido
          </p>
```

Ajuste a checagem de estados no aviso visual: o `led` do card de coleta fica "amber" quando a **maior** idade passa de 24 h.

Em `web/src/styles/global.css`, perto do `.health`, adicione:

```css
.estados-equipamentos { margin: 0 0 0.8rem; font-size: 0.85rem; color: var(--sub); }
```

- [ ] **Step 4: Rodar e ver passar**

Run: (em `web/`) `npm run test -- src/pages/Dashboard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Dashboard.tsx web/src/pages/Dashboard.test.tsx web/src/styles/global.css
git commit -m "feat(web): cards do dashboard com by_comm_status e idade da coleta (S2.4)"
```

---

### Task 12: `.catch` nas mutações restantes (S2.5)

**Files:**
- Modify: `web/src/pages/Users.tsx` (reset de senha — demais casos já cobertos nas Tasks 9/10 via `.catch` → `setErro`)
- Modify: `web/src/components/Layout.tsx:68` (logout)
- Modify: `web/src/pages/DeviceDetail.tsx:46` (coletar)
- Modify: `web/src/pages/BgpSessionDetail.tsx` (verificar `assoc.mutate` sem catch — linha 48)

**Interfaces:**
- Consumes: handlers já com `.catch` das Tasks 9-10 (ConfirmDialog e dialogs de edição); estados de erro existentes (`erro`/`atualizar.error`/`senha.error`).
- Produces: nenhuma rejeição não tratada (unhandled rejection) nas ações de página; erro visível no padrão `role="alert"` quando houver estado, e não-propagação quando a semântica for de navegação.

- [ ] **Step 1: Verificar o estado atual (levantar o que falta)**

Run: (na raiz) `rtk proxy grep -rn "void .*mutateAsync" web/src --include="*.tsx" | grep -v "\.catch" | grep -v "\.then"`
Expected: a lista de ocorrências restantes, para ajustar a seguir (não deve sobrar `mutateAsync` sem cadeia de `.catch`).

- [ ] **Step 2: Correções pontuais**

1. `web/src/pages/Users.tsx` — o handler do reset já ganhou `.catch(() => undefined)` na Task 8 (o erro visível é o `senha.error` já renderizado); confirme que não há outro `mutateAsync` sem catch no arquivo.
2. `web/src/components/Layout.tsx:68` — substitua:

```tsx
        <button type="button" onClick={() => void logout().then(() => navigate("/login"))}>
```

por:

```tsx
        <button
          type="button"
          onClick={() => void logout().then(() => navigate("/login")).catch(() => undefined)}
        >
```

3. `web/src/pages/DeviceDetail.tsx:46` — substitua:

```tsx
          onClick={() => void coletar.mutateAsync(device.id).then(() => navigate(`/jobs?device_id=${device.id}`))}
```

por:

```tsx
          onClick={() =>
            void coletar.mutateAsync(device.id)
              .then(() => navigate(`/jobs?device_id=${device.id}`))
              .catch(() => undefined)
          }
```

> Se `DeviceDetail.tsx` tiver um estado `erro` (verifique), use-o no catch em vez de `() => undefined` — a coleta já devolve erro de negócio em JSON na resposta (409/400), então o codepath de rejeição é só rede/5xx.

4. `web/src/pages/BgpSessionDetail.tsx:48` — a ação de desassociar usa `void assoc.mutate(...)` (retorna void em react-query v5; erro vai para `assoc.error`, não é unhandled) — verifique que a página exibe `assoc.error`; se não exibir, adicione junto ao `{erro && ...}` existente: `{assoc.error && <p role="alert">{String(assoc.error.message ?? "Falha ao associar community.")}</p>}`.

- [ ] **Step 3: Rodar e ver passar**

Run: (em `web/`) `npm run test` e, na raiz, `uv run ruff check src tests` (nada de backend mudou — quick sanity).
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/Layout.tsx web/src/pages/DeviceDetail.tsx web/src/pages/BgpSessionDetail.tsx web/src/pages/Users.tsx
git commit -m "fix(web): sem unhandled rejection em logout, coleta e reset de senha (S2.5)"
```

---

### Task 13: Guard de falha dura no Playwright (S3.1)

**Files:**
- Modify: `web/playwright.config.ts` (`reuseExistingServer: true` → `false`)
- Modify: `web/e2e/README.md` (seções "O que o comando faz" e a tabela "Erros comuns")

**Interfaces:**
- Consumes: restante da config (webServer command/url/timeout) inalterado.
- Produces: e2e falham no boot se a porta :8000 estiver ocupada (nunca reusam o uvicorn de dev com banco errado); run-book atualizado.

- [ ] **Step 1: Mudar a config**

Em `web/playwright.config.ts`, substitua:

```ts
    reuseExistingServer: true,
```

por:

```ts
    // Falha dura: se a porta 8000 já estiver ocupada, o smoke morre no boot —
    // nunca reusa o uvicorn de dev (que apontaria para o banco default).
    reuseExistingServer: false,
```

- [ ] **Step 2: Atualizar o run-book**

Em `web/e2e/README.md`:

1. Na seção "O que o comando faz", substitua:

```
  devolveria `{"detail":"Not Found"}`), com `reuseExistingServer: true` (se já
  houver algo na porta 8000, reusa — **não rode os e2e com o uvicorn de dev
  ativo na 8000**: ele é reutilizado, a env `GERENET_DATABASE_URL` do comando
  vira no-op e o seed toca o banco de dev).
```

por:

```
  devolveria `{"detail":"Not Found"}`), com `reuseExistingServer: false`
  (**falha dura**: se houver algo na porta 8000, o smoke morre já no boot —
  nunca reusa o uvicorn de dev, que apontaria para o banco default `gerenet`;
  antes de rodar, garantia: nada escutando na 8000 — por exemplo, pare o
  uvicorn de dev).
```

2. Na tabela "Erros comuns", substitua a linha:

```
| fumos rodam mas não contra o banco dedicado | o webServer reutiliza uvicorn já ativo na porta 8000 (feito para o dev) — **pare o uvicorn de dev** antes do `npm run test:e2e`, senão o seed toca o banco default `gerenet` |
```

por:

```
| `Error: reuseExistingServer` / port 8000 ocupada | outro processo já escuta na 8000 (uvicorn de dev, IDE…) — **pare-o** e rode de novo; o webServer agora falha duro, sem reutilizar |
```

- [ ] **Step 3: Rodar os e2e (banco dedicado)**

Run (com o uvicorn de dev **parado**):

```bash
docker compose ps  # conferir que o postgres do compose está de pé
docker compose exec db createdb -U gerenet gerenet_e2e 2>/dev/null || true
GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_e2e" \
  uv run alembic upgrade head
cd web && GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_e2e" \
  E2E_PASSWORD="e2e-super-8" npm run test:e2e
```

Expected: PASS (smoke + login; nenhum teste de edição foi adicionado no C3 — o roteiro de edição fica para um ciclo futuro, como registra a spec §7).

- [ ] **Step 4: Commit**

```bash
git add web/playwright.config.ts web/e2e/README.md
git commit -m "chore(e2e): reuseExistingServer desligado — falha dura na porta ocupada (S3.1)"
```

---

### Task 14: Docs — estado do repositório no CLAUDE.md (S3.3)

**Files:**
- Modify: `CLAUDE.md` (seção "Estado do repositório")

**Interfaces:**
- Consumes: conclusão das Tasks 1-13.
- Produces: seção refletindo o ciclo C3 (edição/reativação na web; catálogos editáveis; rate limit; sessões revogadas; guard e2e).

- [ ] **Step 1: Atualizar a seção "Estado do repositório"**

Em `CLAUDE.md`, na subseção "Web (ciclo C2)", adicione um parágrafo novo após o bloco atual:

```markdown
- Web (ciclo C3): edição/reativação de todas as entidades com página web
  (ver desativados + Editar/Reativar em dialogs acessíveis — `Modal`); catálogos
  (communities, policy-profiles) passaram a ter update/PATCH/CLI `update` (criação
  continua apenas via seed); login tem rate limit por IP+username no Redis
  (5 falhas → 429 + Retry-After; fail-open se o Redis cair) e desativar usuário
  revoga as sessões; dashboard usa `by_comm_status` e `snapshot_age_seconds`;
  `npm run test:e2e` tem guard com `reuseExistingServer: false` (porta 8000
  ocupada = falha dura).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: estado do repositório com o ciclo C3 (S3.3)"
```

---

### Verificação final da suíte

Execute na ordem (raiz do repo):

1. `uv run ruff check src tests` — sem warnings.
2. `uv run pytest -q` — suíte backend completa.
3. `cd web && npm run build` — TypeScript + Vite ok.
4. `cd web && npm run test` — Vitest completo.
5. `cd web && GERENET_DATABASE_URL=...gerenet_e2e... E2E_PASSWORD="e2e-super-8" npm run test:e2e` — fumos com o guard novo (uvicorn de dev parado).

Antes do merge no main (executado pelo usuário, protocolo do projeto): revisar o diff total e conferir que nenhum teste de catálogo deixou linhas para trás (`select` com nomes `c3-`/`api-c3-`/`cli-c3-` em `bgp_policy_profiles`/`communities` do `gerenet_test`).

> **Registro de escopo (spec §7)**: o roteiro e2e de edição não entra no C3 — os fumos existentes continuam como gate; o fluxo de edição/reativação é coberto por Vitest (Tasks 9-11).
