# Interface web (ciclo C2 — SPA em web/) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar a SPA React do gerenet (login, dashboard, telas de todas as entidades que a API expõe hoje), acompanhada dos últimos ajustes de backend herdados (auth dos routers do B2 e limpezas do C1).

**Architecture:** Frontend React 18 + Vite + TypeScript em `web/` consumindo a API `/api/v1` já existente (contrato: Pydantic `*Out` espelhado em `src/api/types.ts`). Sessão por cookie `gerenet_sess` (HttpOnly/SameSite=Lax), `apiFetch` com `credentials: "include"`; 401 → redireciona `/login`. TanStack Query para cache, Vitest para unit (jsdom), Playwright só para fumos. Em produção o build (`web/dist`) é servido pelo FastAPI (já montado no C1); em dev o Vite proxya `/api` → `:8000`.

**Tech Stack:** React 18, react-router-dom 7, @tanstack/react-query 5, Vite, TypeScript estrito, Vitest + Testing Library, Playwright, ESLint + Prettier. Backend: apenas ajustes mecânicos (require_actor) e limpeza — nenhuma dependência nova.

**Spec:** [docs/superpowers/specs/2026-09-04-gerenet-ciclo-c-web-ui-design.md](../specs/2026-09-04-gerenet-ciclo-c-web-ui-design.md) — seções §6 (frontend), §7 (execução), §8 (segurança), §9.2 (testes frontend), §12 (critérios de aceite 4–8). O C1 já entregou §4–5 (auth/dashboard/jobs/serve estático) — o ponto de partida é o main pós-C1 (`b5fad3f`).

## Global Constraints

- **Idioma da UI: português (PT-BR)** — todos os rótulos, mensagens de erro, botões e avisos. Identificadores de código (variáveis, funções, componentes, chaves de rota) em **inglês**; nomes de arquivo em inglês.
- **Mensagens de erro idênticas às da API** (não re-escrever): 401 login → "Usuário ou senha inválidos."; 401 geral → "Chave de API ausente ou inválida." (o front redireciona e **não** exibe essa); 403 "Usuário desativado."; 403 "Perfil Visualizador permite apenas leitura."; 403 "Somente administradores."; 403 "Não é possível alterar a própria conta."; falha de rede → "Servidor indisponível. Tente novamente."; 404 "Job não encontrado."; 422 → erros por campo (mensagens do `detail` da validação, em PT-BR).
- **Nenhum segredo no browser**: senha nunca persiste em `localStorage`/`sessionStorage` nem em log; token só no cookie HttpOnly; payload de login nunca é logado. O front **nunca** recebe a API key.
- **Sem framework de UI de terceiros**: componentes próprios (DataTable, FormField, StatusBadge, SeverityBadge, ConfirmDialog), CSS vars tokenizadas, dark-first com light por `prefers-color-scheme`.
- **Dependências node** (resolvidas na T2 — se divergirem do brief, a T2 é a autoridade e o desvio fica documentado): `react@18`, `react-dom@18`, `react-router-dom@7`, `@tanstack/react-query@5`; dev: `vite@6` (resolvido 6.4.x), `typescript@5` (5.9.x), **`vitest@3`** (o brief pedia 2.1.x, mas vitest 2 peer-depende de vite 5 e quebra a augmentação de config sob TS 5.9 — bump aprovado no review da T2), `jsdom@25`, `@testing-library/react@16`, `@testing-library/jest-dom@6`, `@testing-library/user-event@14`, `@playwright/test@1`, `eslint@9`, `@eslint/js`, `typescript-eslint@8`, `prettier@3`, `@types/node`.
- **`.gitignore`**: adicionar `web/node_modules/`, `web/dist/`, `web/playwright-report/`, `web/test-results/`. O `.claude/settings.local.json` e `config.yaml` permanecem fora do git (já ignorados) — **nunca** alterar/comitar.
- **Testes backend**: pytest verde sem editar testes existentes (a troca `require_api_key` → `require_actor` nos routers do B2 deve manter API key funcionando — os testes atuais usam a chave).
- **Commits**: mensagem em PT-BR, escopo (feat/fix/chore/docs), trailer `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- **SDD**: ledger em `.superpowers/sdd/2026-09-04-gerenet-ciclo-c2-web-ui/progress.md`; revisor por task; revisão final de branch.
- **Node não vira requisito de runtime/deploy**: só devs rodam build; o produto segue servindo estático pelo Python.
- **BD de teste**: suíte backend roda com `GERENET_TEST_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test_c2` (banco alternativo — `gerenet_test` não é tocado enquanto o ciclo estiver em voo; ver memória `gerenet-b2-rebase-protocol`). Alembic para migrar banco de teste: `GERENET_DATABASE_URL=...://gerenet_test_c2 uv run alembic upgrade head` (o alembic **lê** `GERENET_DATABASE_URL`, não o `_TEST_`; ver memória `gerenet-alembic-env-url`).

## Estrutura de arquivos

```
web/
  package.json, package-lock.json, tsconfig.json, tsconfig.node.json
  vite.config.ts            # plugin react + proxy /api → :8000 + vitest (jsdom, globals)
  eslint.config.js, .prettierrc, .gitignore (ou no raiz), index.html
  playwright.config.ts      # baseURL :8000 (build+uvicorn) ou :5173; webServer opcional
  src/
    main.tsx                # ReactDOM + QueryClient + Router
    App.tsx                 # rotas + layout + auth provider
    styles/global.css       # tokens :root + dark-first + componentes básicos
    api/
      client.ts             # apiFetch<T> + ApiError + onUnauthorized
      types.ts              # espelhos dos *Out do Pydantic
      hooks.ts              # useQuery/useMutation por recurso + useMe + useJobPoll
    auth/
      auth-context.tsx      # useMe/RequireAuth/RequireAdmin
      Login.tsx
    components/
      DataTable.tsx  FormField.tsx  StatusBadge.tsx  SeverityBadge.tsx
      ConfirmDialog.tsx  TimeAgo.tsx  PageHeader.tsx  MonoCode.tsx
    pages/
      Dashboard.tsx  Users.tsx  Devices.tsx  DeviceDetail.tsx
      Sites.tsx  Organizations.tsx  Contacts.tsx
      Circuits.tsx  CircuitDetail.tsx  BgpSessions.tsx  BgpSessionDetail.tsx
      PrefixAuthorizations.tsx  PolicyProfiles.tsx  Communities.tsx
      Snapshots.tsx  DesiredConfig.tsx  Reconcile.tsx  Jobs.tsx  JobDetail.tsx
      AuditEvents.tsx
    tests/ (co-localizados ou em __tests__/)  → convenção: *.test.ts(x) ao lado do módulo
  e2e/ (Playwright)
    setup.ts (seed via CLI/API), login.spec.ts, smoke.spec.ts
```

## Contratos da API (fonte única para types.ts)

| Rota | Método | Response / body in |
|---|---|---|
| `/api/v1/auth/login` | POST | body `{username, password}` → 200 `UserOut` (cookie setado) |
| `/api/v1/auth/logout` | POST | 204 |
| `/api/v1/auth/me` | GET | 200 `UserOut` |
| `/api/v1/users` | GET/POST | `UserOut[]` / `{username, password, role}` → `UserOut` |
| `/api/v1/users/{id}` | PATCH | `{username?, role?, is_active?}` → `UserOut` |
| `/api/v1/users/{id}/password` | POST | `{password}` → 204 |
| `/api/v1/dashboard` | GET | `DashboardOut` |
| `/api/v1/devices` | GET/POST/PATCH/GET{id} | `DeviceOut` |
| `/api/v1/devices/{id}/collect` | POST | 202 `{queued, message, job_id}` |
| `/api/v1/devices/{id}/snapshots` | GET | `SnapshotOut[]` |
| `/api/v1/devices/{id}/desired-config` | GET | `DesiredConfigOut` |
| `/api/v1/snapshots/{id}` | GET | `SnapshotOut` |
| `/api/v1/sites` | GET/POST/PATCH{id} | `SiteOut` |
| `/api/v1/organizations` | GET/POST/PATCH{id} | `OrganizationOut` |
| `/api/v1/downstreams` | GET/POST/PATCH{id} | `OrganizationOut` (mesma shape) |
| `/api/v1/contacts` | GET/POST/PATCH{id} | `ContactOut` |
| `/api/v1/circuits` | GET/POST/PATCH{id} | `CircuitOut`; GET/{id} → `CircuitDetailOut` |
| `/api/v1/circuits/{id}/reserve` | POST | 200 `CircuitDetailOut` |
| `/api/v1/bgp-sessions` | GET/POST/PATCH{id} | `BgpSessionOut` |
| `/api/v1/bgp-sessions/{id}/password` | POST | body `{password}` → `BgpSessionOut` (Vault) |
| `/api/v1/bgp-sessions/{id}/communities` | POST | `{community_id}` → 200 `{session_id, community_id}` |
| `/api/v1/bgp-sessions/{id}/communities/{cid}` | DELETE | 204 |
| `/api/v1/prefix-authorizations` | GET/POST/PATCH{id} | `PrefixAuthorizationOut` |
| `/api/v1/policy-profiles` | GET | `PolicyProfileOut[]` |
| `/api/v1/communities` | GET | `CommunityOut[]` |
| `/api/v1/reconciliation` | GET | `?device_id=` **ou** `?snapshot_id=` → `ReconcileOut` |
| `/api/v1/audit-events` | GET | `?tipo=&objeto=&objeto_id=&limit=` → `AuditEventOut[]` |
| `/api/v1/jobs` | GET | `?device_id=&status=&kind=&limit=&offset=` → `JobRunOut[]` |
| `/api/v1/jobs/{id}` | GET | `JobRunOut` |

---

### Task 1: Backend — auth dos routers do B2 + limpezas herdadas do C1

**Files:**
- Modify: `src/gerenet/api/routers/reconciliation.py:8,17,21`
- Modify: `src/gerenet/api/routers/communities.py:7,14`
- Modify: `src/gerenet/api/deps.py`
- Modify: `src/gerenet/cli/users.py` (alias `--include-disabled`)
- Modify: `tests/api/test_static_spa.py:9` (remover `DIST` morto)
- Modify: `tests/api/test_static_spa.py` (fixture `static_dir` em todos os testes)
- Create: `tests/api/conftest.py` (fixture comum `spa_static_dir` + cliente com static controlado)
- Create: `tests/api/test_actor_b2_routes.py`
- Create: `tests/api/test_users_api.py` (2 testes baratos) ou em `tests/domain/test_users_service.py`
- Create: `tests/domain/test_users_service.py` (guard `verify_password("x", None)`)

**Interfaces:**
- Consumes: `require_actor` de `gerenet.api.deps` (assinatura: `def require_actor(request: Request, session: SessionDep, db: SessionDep) -> Actor` — via Depends no router); `settings` com `static_dir`.
- Produces: routers de `reconciliation` (pref. `/api/v1/reconciliation`) e `communities` autenticáveis por cookie; `require_api_key` **removido** de deps.py (nada mais o usa); `cli users list --include-disabled` como alias de `--all`.

**Contexto do gap:** o ciclo B2 rodou em worktree paralela e seus routers novel (`reconciliation.py`, `communities.py`) continuaram em `require_api_key` — nenhuma rota de texto estava coberta pelo T5 do C1. A troca é mecânica (mesmo padrão do T5), preservando o caminho X-Api-Key (os testes existentes de communities/reconcile usam a chave e devem continuar verdes sem edição).

- [ ] **Step 1: Trocar `require_api_key` → `require_actor` nos dois routers**

`src/gerenet/api/routers/reconciliation.py`:
```python
from gerenet.api.deps import require_actor
```
(substitui `from gerenet.api.deps import require_api_key`) e nos dois APIRouter:
```python
dependencies=[Depends(require_actor)],
```
`src/gerenet/api/routers/communities.py`: mesmo ajuste no import e no router.

- [ ] **Step 2: Remover `require_api_key` morto de deps.py**

Em `src/gerenet/api/deps.py`, apagar a função `require_api_key` (e seu import `hmac`/`compare_digest` se ficarem sem uso — checar `deps.py` inteiro). Manter `require_actor`, `require_admin`, `Actor`, `SESSION_COOKIE`, `SessionDep`.

Run: `uv run ruff check src/gerenet/api/deps.py`.
Expected: Passed (sem F401/atributo não usado).

- [ ] **Step 3: Escrever o teste de cookie nas rotas B2 (antes do fix nos outros arquivos? não — já feito) — regressão**

Criar `tests/api/test_actor_b2_routes.py`:

```python
"""Rotas do B2 (reconciliation, communities) autenticáveis por cookie de sessão."""


def _cookie_de_usuario(client, db_session) -> dict:
    """Cria usuário, loga via API e devolve headers com o cookie gerenet_sess."""
    from gerenet.domain.services.users import create_user

    from gerenet.domain.schemas import UserCreateIn, UserPasswordIn

    u = create_user(db_session, UserCreateIn(username="admin-spa", password="senha-super-8", role="administrador"), actor="cli")
    r = client.post("/api/v1/auth/login", json={"username": "admin-spa", "password": "senha-super-8"})
    assert r.status_code == 200, r.text
    return {"Cookie": r.headers.get("set-cookie", "").split(";", 1)[0]}


def test_reconciliation_aceita_cookie(client, db_session):
    headers = _cookie_de_usuario(client, db_session)
    # 404 (rua alcançada com o cookie; device inexistente) prova o cookie autenticou
    r1 = client.get("/api/v1/reconciliation", params={"device_id": 999019}, headers=headers)
    assert r1.status_code == 404
    # sem autenticação continua 401 (mensagem preservada)
    r2 = client.get("/api/v1/reconciliation", params={"device_id": 999019})
    assert r2.status_code == 401


def test_communities_aceita_cookie(client, db_session):
    headers = _cookie_de_usuario(client, db_session)
    r = client.get("/api/v1/communities", headers=headers)
    assert r.status_code == 200


def test_communities_seguem_com_api_key(client):
    # caminho da chave preservado — smoke com a chave dos fixtures de teste
    r = client.get("/api/v1/communities", headers={"X-Api-Key": "teste-key"})
    assert r.status_code == 200
```

> Chave dos fixtures: os testes de API usam `api_key="teste-key"` (ver `tests/conftest.py`/`tests/api/test_static_spa.py:19`) — confirmar na abertura do conftest e usar o mesmo valor. O fixture `client` **não** injeta a chave por padrão (os 401 acima dependem disso); se injetar, criar sem o header.

Run: `GERENET_TEST_DATABASE_URL=...gerenet_test_c2 uv run pytest tests/api/test_actor_b2_routes.py -v`.
Expected: PASS.

- [ ] **Step 4: Alias `--include-disabled` no CLI de users**

Em `src/gerenet/cli/users.py`, a função `listar` (onde hoje `--all` é a única flag) ganha o segundo nome na mesma opção — o Click aceita vários nomes longos por parâmetro:

```python
@app.command("list")
def listar(
    include_disabled: bool = typer.Option(
        False, "--include-disabled", "--all", help="Inclui desativados."
    ),
) -> None:
    """Lista usuários."""
    with get_session() as session:
        for u in svc.list_users(session, include_disabled=include_disabled):
            estado = "ativo" if u.is_active else "desativado"
            typer.echo(f"{u.id:>4}  {u.username:<16} {u.role:<14} {estado}")
```

O teste do C1 (`tests/cli/test_cli_smoke.py`) usa `--all` — o par duplo de nomes mantém ambos válidos.

Run: `uv run pytest tests/cli/test_cli_smoke.py -q -k users`.
Expected: PASS.

Run: `uv run pytest tests/cli/test_cli_smoke.py -q -k users`.
Expected: PASS.

- [ ] **Step 5: fixture comum `static_dir` controlado em `tests/api`**

Criar `tests/api/conftest.py` (novo — fixtures comuns dos testes de API; hoje os testes de estático criam o diretório ao vivo em cada arquivo):

```python
"""Fixtures comuns dos testes de API.

`static_dir_inexistente`: aponta o build da SPA para um diretório vazio — o
fallback de `/` nunca serve arquivos fora do build real, sem depender do
`web/dist` que existir na máquina.
"""

from pathlib import Path

import pytest


@pytest.fixture
def static_dir_inexistente(tmp_path: Path) -> Path:
    return tmp_path / "sem-build"
```

Ajustar `tests/api/test_static_spa.py`:
- remover a constante morta `DIST` (~L9);
- usar o fixture `static_dir_inexistente` onde hoje se constrói `dist` ao vivo, mantendo a forma existente do override: `set_settings(Settings(api_key="teste-key", static_dir=dist, _env_file=None))` — `_env_file=None` é essencial (sem ele o `.env` do repo pode vazar para os settings de teste); o `set_settings` já é chamado antes de `create_app` no teste.

Run: `uv run pytest tests/api/test_static_spa.py -q`.
Expected: PASS.

- [ ] **Step 6: Testes baratos — guard existente do verify_password e senha longa**

Fatos confirmados: `verify_password` **já** guarda `not isinstance(armazenado, str) → False` (users.py:46) — é teste de regressão puro; `_valida_senha` (users.py:63-66) rejeita > 128 chars com `ValidationError` (errors.py:13); `create_user(session, *, username, password, role, actor="cli")` (assintatura keyword-only).

`tests/domain/test_users_service.py`:

```python
def test_verify_password_nao_string_retorna_false() -> None:
    from gerenet.domain.services.users import verify_password

    assert verify_password("qualquer", None) is False
    assert verify_password("qualquer", 123) is False
    assert verify_password("qualquer", "rotulo-quebrado") is False
    assert verify_password("qualquer", "md5$ajs8db") is False  # prefixo errado


def test_senha_acima_de_128_rejeitada_no_servico(db_session) -> None:
    from gerenet.domain.services import users
    from gerenet.domain.services.errors import ValidationError

    import pytest

    with pytest.raises(ValidationError):
        users.create_user(
            db_session, username="user-longo", password="x" * 129, role="visualizador", actor="cli"
        )
```

`tests/api/test_users_api.py`:

```python
def test_create_user_senha_longa_422(client):
    r = client.post(
        "/api/v1/users",
        json={"username": "tamanho", "password": "x" * 129, "role": "operador"},
        headers={"X-Api-Key": "teste-key"},
    )
    assert r.status_code == 422
```

Run: `uv run pytest tests/domain/test_users_service.py tests/api/test_users_api.py -q`.
Expected: PASS.

- [ ] **Step 7: Suíte completa + commit**

> **NÃO rodar `alembic upgrade head`** — a cadeia já está aplicada no `gerenet_test_c2` (baseline) e o alembic lê `GERENET_DATABASE_URL` (default = banco dev `gerenet`; ver memória `gerenet-alembic-env-url`). Só pytest roda nesta task.

```bash
GERENET_TEST_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test_c2 uv run pytest -q
```
Expected: 355 passed (349 baseline + 6 novos; nenhum existente quebrado — a troca preserva X-Api-Key).

```bash
git add -A
git commit -m "fix(api): autentica routers do B2 por sessao cookie + limpezas do C1

reconciliation/communities seguiam em require_api_key (código nasceu na
worktree do B2, o T5 do C1 não os alcançou); com cookie a SPA agora
alcança /reconciliation e /devices/{id}/desired-config.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Scaffold do web/ (Vite + React + TS + toolchain)

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/tsconfig.node.json`, `web/vite.config.ts`, `web/index.html`, `web/eslint.config.js`, `web/.prettierrc`, `web/playwright.config.ts`
- Create: `web/src/main.tsx`, `web/src/App.tsx` (stub com rota mínima), `web/src/styles/global.css`
- Modify: `.gitignore` (padrões node)

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `web/` com `npm run dev|build|test|lint|format|test:e2e`; servidor dev na 5173 proxando `/api` → 8000.

- [ ] **Step 1: Adicionar `.gitignore` do node**

Em `.gitignore` (raiz), acrescentar:
```
# web (frontend)
web/node_modules/
web/dist/
web/playwright-report/
web/test-results/
```

- [ ] **Step 2: `package.json` exato**

```json
{
  "name": "gerenet-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "lint": "eslint .",
    "format": "prettier --write ."
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^7.1.1"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.1",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.18",
    "@types/react-dom": "^18.3.5",
    "@vitejs/plugin-react": "^4.3.4",
    "eslint": "^9.17.0",
    "jsdom": "^25.0.1",
    "prettier": "^3.4.2",
    "typescript": "^5.7.2",
    "typescript-eslint": "^8.19.1",
    "vite": "^6.0.5",
    "vitest": "^2.1.8"
  }
}
```

- [ ] **Step 3: Configs**

`web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src", "e2e", "vite.config.ts"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`web/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "playwright.config.ts"]
}
```

`web/vite.config.ts`:
```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
  },
});
```

`web/index.html`:
```html
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>gerenet — Gerenciador de Rede Huawei VRP</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/eslint.config.js`:
```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "playwright-report", "test-results"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
```

`web/.prettierrc`:
```json
{ "semi": true, "singleQuote": false, "printWidth": 100, "trailingComma": "all" }
```

`web/playwright.config.ts` (fumos exigem a stack: uvicorn com web/dist buildado + dados seed):
```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { baseURL: "http://localhost:8000", trace: "retain-on-failure" },
  // A stack (postgres + redis + uvicorn + web/dist) sobe manualmente — ver
  // e2e/README.md (Task 12). O webServer só sobe o uvicorn se nada já estiver
  // na porta; o run-book manda rodar `npm run build` antes do `test:e2e`.
  webServer: {
    command: "uv run uvicorn gerenet.api.main:create_app --factory --port 8000",
    url: "http://localhost:8000/api/v1/dashboard",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
```

> Nesta task nenhum e2e roda ainda — o config fica como esqueleto válido e a Task 12 o refina com o run-book.

`web/src/test-setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 4: `main.tsx` + `App.tsx` stub + CSS tokens**

`web/src/main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles/global.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

`web/src/App.tsx` (stub — rotas reais chegam nas tasks seguintes):
```tsx
export default function App() {
  return <main>gerenet — SPA (em construção)</main>;
}
```

`web/src/styles/global.css` — tokens dark-first (§6.4):

```css
:root {
  --bg: #0f141a;
  --bg-elevated: #171d24;
  --bg-hover: #1f2730;
  --border: #2a333d;
  --text: #d7dde3;
  --text-muted: #8a96a3;
  --accent: #4aa8ff;
  --danger: #e5534b;
  --warn: #d29a3a;
  --ok: #3fb27f;
  --unknown: #8a96a3;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #f5f7f9;
    --bg-elevated: #ffffff;
    --bg-hover: #eef2f5;
    --border: #d3dbe2;
    --text: #1b232b;
    --text-muted: #5a6875;
    color-scheme: light;
  }
}
body { margin: 0; background: var(--bg); color: var(--text); }
a { color: var(--accent); }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { border-bottom: 1px solid var(--border); padding: 0.4rem 0.6rem; text-align: left; }
button, input, select, textarea { font: inherit; }
button { cursor: pointer; background: var(--bg-elevated); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.8rem; }
button:hover { background: var(--bg-hover); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
input, select, textarea { background: var(--bg-elevated); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.5rem; }
code, pre { font-family: var(--mono); }
```

- [ ] **Step 5: install + smoke do build**

```bash
cd web && npm install
npm run build
npm run lint
```
Expected: build + lint sem erros; `web/dist/index.html` criado.

- [ ] **Step 6: Vitest roda vazio (setup ok)**

```bash
cd web && npm run test
```
Expected: "no test files found" (ou exit 0) — harness ok.

- [ ] **Step 7: commit**

```bash
git add .gitignore web/package.json web/package-lock.json web/tsconfig.json web/tsconfig.node.json web/vite.config.ts web/index.html web/eslint.config.js web/.prettierrc web/playwright.config.ts web/src
git commit -m "feat(web): scaffold Vite + React + TS com token, lint e vitest (ciclo C2)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: `src/api/client.ts` + `types.ts` + teste Vitest do client

**Files:**
- Create: `web/src/api/types.ts`
- Create: `web/src/api/client.ts`
- Create: `web/src/api/client.test.ts`

**Interfaces:**
- Consumes: nada (App não usa ainda).
- Produces: `apiFetch<T>(path, opts)` → `Promise<T>`; `ApiError` (status + mensagem + campos?); `onUnauthorized` registrável; `types` para todas as telas seguintes.

- [ ] **Step 1: `types.ts` — espelhos exatos dos `*Out`**

```ts
// Espelhos dos *Out do Pydantic (contrato da API /api/v1) — atualizar se o backend mudar.
export interface UserOut {
  id: number;
  username: string;
  role: "visualizador" | "operador" | "aprovador" | "executor" | "administrador";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}
export interface DeviceOut {
  id: number;
  name: string;
  management_address: string;
  ssh_port: number | null;
  vendor: string;
  model: string | null;
  family: string | null;
  role: string | null;
  site_id: number | null;
  asn: number | null;
  vrp_version: string | null;
  comm_status: string;
  admin_status: boolean;
  last_collected_at: string | null;
  tags: string[];
}
export interface SiteOut {
  id: number;
  name: string;
  city: string | null;
  uf: string | null;
  p2p_ipv4_block: string | null;
  p2p_ipv6_base: string | null;
  admin_status: boolean;
}
export interface OrganizationOut {
  id: number;
  name: string;
  legal_name: string | null;
  kind: "downstream" | "parceiro";
  asn: number | null;
  irr_as_set: string | null;
  notes: string | null;
  admin_status: boolean;
}
export interface ContactOut {
  id: number;
  organization_id: number;
  name: string;
  email: string | null;
  phone: string | null;
  kind: "tecnico" | "noc" | "admin";
  admin_status: boolean;
}
export interface CircuitOut {
  id: number;
  code: string;
  organization_id: number;
  site_id: number;
  access_device_id: number;
  access_port: string;
  edge_device_id: number;
  backup_edge_device_id: number | null;
  stack: "ipv4" | "ipv6" | "dual";
  vlan_mode: "unica" | "separada";
  qinq: boolean;
  vrf: string | null;
  mtu: number | null;
  bandwidth: string | null;
  bfd: boolean;
  p2p_v4_len: 30 | 31;
  description: string | null;
  notes: string | null;
  edge_trunk: string | null;
  admin_status: boolean;
}
export interface CircuitDetailOut extends CircuitOut {
  ipv4_local: string | null;
  ipv4_remote: string | null;
  ipv6_local: string | null;
  ipv6_remote: string | null;
}
export interface BgpSessionOut {
  id: number;
  circuit_id: number;
  device_id: number;
  afi: "ipv4" | "ipv6";
  local_address: string;
  remote_address: string;
  source_address: string | null;
  asn_local: number | null;
  asn_remote: number | null;
  description: string | null;
  import_profile_id: number | null;
  export_profile_id: number | null;
  maximum_prefix: number | null;
  maximum_prefix_threshold: number | null;
  local_preference: number | null;
  med: number | null;
  prepend: number | null;
  keepalive: number | null;
  holdtime: number | null;
  bfd_enabled: boolean;
  graceful_restart: boolean;
  shutdown: boolean;
  allow_default_route: boolean;
  has_password: boolean;
  admin_status: boolean;
}
export interface PrefixAuthorizationOut {
  id: number;
  organization_id: number;
  family: "ipv4" | "ipv6";
  prefix: string;
  origin: string;
  notes: string | null;
  admin_status: boolean;
}
export interface PolicyProfileOut {
  id: number;
  name: string;
  label: string;
  direction: "import" | "export";
  kind: string;
  prefixes: string[] | null;
  notes: string | null;
  admin_status: boolean;
}
export interface CommunityOut {
  id: number;
  name: string;
  notes: string | null;
}
export interface AuditEventOut {
  id: number;
  type: string;
  actor: string;
  details: Record<string, unknown>;
  created_at: string;
}
export interface SnapshotOut {
  id: number;
  device_id: number;
  started_at: string;
  finished_at: string | null;
  status: "success" | "partial" | "error";
  resources: Record<string, unknown>;
  errors: Record<string, unknown>;
  duration_ms: number;
}
export interface BlocoOut {
  tipo: string;
  objeto: string;
  objeto_id: number;
  comandos: string[];
}
export interface DesiredConfigOut {
  device_id: number;
  gerado_em: string;
  texto: string;
  blocos: BlocoOut[];
}
export interface ReconcileItemOut {
  tipo: string;
  severidade: string;
  esperado: string;
  encontrado: string;
  acao: string;
}
export interface ReconcileOut {
  device_id: number;
  snapshot_id: number | null;
  aviso: string | null;
  gerado_em: string;
  items: ReconcileItemOut[];
}
export interface PerDeviceOut {
  device_id: number;
  name: string;
  site_id: number | null;
  site_name: string | null;
  comm_status: string;
  last_collected_at: string | null;
  snapshot_age_seconds: number | null;
  latest_snapshot: { id: number; status: string; started_at: string } | null;
  active_job: { id: number; status: string } | null;
}
export interface DashboardOut {
  devices: {
    total: number;
    active: number;
    with_snapshot: number;
    by_comm_status: Record<"unknown" | "ok" | "fail", number>;
  };
  per_device: PerDeviceOut[];
  bgp_sessions: { total: number; active: number; shutdown: number };
  circuits: { total: number; active: number };
  vlans: { reserved: number; freed: number };
  ip_prefixes: { reserved: number; freed: number };
  recent_audit: AuditEventOut[];
}
export interface JobRunOut {
  id: number;
  device_id: number;
  origin: string;
  actor: string;
  kind: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  snapshot_id: number | null;
}
export interface CollectResposta {
  queued: boolean;
  message: string;
  /** id do job RQ (uuid) — NÃO é o JobRun.id da tabela; não usar para navegar a /jobs/{id} */
  job_id: string;
}
```

- [ ] **Step 2: `client.ts`**

```ts
// Camada única de acesso à API: cookie de sessão, erros tipados PT-BR e
// redirecionamento para /login em 401 (§6.2 da spec).
export class ApiError extends Error {
  readonly status: number;
  /** mensagem única, ex.: "Usuário ou senha inválidos." */
  readonly message: string;
  /** erros por campo do 422: {campo: mensagem} */
  readonly fieldErrors: Record<string, string>;
  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.message = message;
    this.fieldErrors = fieldErrors;
  }
}

let onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(fn: () => void) {
  onUnauthorized = fn;
}

function mensagemDeDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // [{loc: ["body","password"], msg: "..."}] → concat das mensagens de campo
    const msgs = detail
      .map((e) => (typeof e === "object" && e !== null && "msg" in e ? String(e.msg) : ""))
      .filter((m) => m !== "");
    if (msgs.length > 0) return msgs.join("; ");
  }
  return null;
}

function fieldErrorsDoDetail(detail: unknown): Record<string, string> {
  if (!Array.isArray(detail)) return {};
  const out: Record<string, string> = {};
  for (const e of detail) {
    const loc = e?.loc as (string | number)[] | undefined;
    const campo = loc?.slice(1).join(".") ?? "geral";
    out[campo] = e?.msg ?? "Inválido.";
  }
  return out;
}

export async function apiFetch<T>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const { method = "GET", body } = opts;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Servidor indisponível. Tente novamente.");
  }

  if (res.status === 401 && !path.startsWith("/api/v1/auth/login")) {
    onUnauthorized?.();
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      const data = await res.json();
      detail = data?.detail ?? null;
    } catch {
      /* sem corpo — usa status */
    }
    const fieldErrors = fieldErrorsDoDetail(detail);
    const message = fieldErrors["geral"] ?? mensagemDeDetail(detail) ?? mensagemPorStatus(res.status);
    throw new ApiError(res.status, message, fieldErrors);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function mensagemPorStatus(status: number): string {
  if (status === 401) return "Chave de API ausente ou inválida.";
  if (status === 403) return "Permissão negada.";
  if (status === 404) return "Não encontrado.";
  if (status === 409) return "Conflito com registro existente.";
  return `Erro do servidor (${status}).`;
}
```

> Nota: `mensagemDeDetail`/`fieldErrorsDoDetail` tratam o `detail` do FastAPI: string OU lista de erros de validação com `loc`/`msg`.

- [ ] **Step 3: teste do client (fetch mockado)**

`web/src/api/client.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ApiError, setOnUnauthorized } from "./client";

function responder(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("envia cookie e JSON no corpo", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(responder(200, { id: 1 }));
    await apiFetch("/api/v1/auth/me");
    const [url, init] = vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/me");
    expect(init.credentials).toBe("include");
    expect(init.body).toBeUndefined();
  });

  it("402/409 → ApiError com a mensagem do detail", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(responder(409, { detail: "Registro duplicado." }));
    await expect(apiFetch("/api/v1/sites", { method: "POST", body: {} })).rejects.toThrow(ApiError);
    await expect(apiFetch("/api/v1/sites", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 409,
      message: "Registro duplicado.",
    });
  });

  it("401 fora do login chama onUnauthorized", async () => {
    const spy = vi.fn();
    setOnUnauthorized(spy);
    vi.mocked(fetch).mockResolvedValueOnce(responder(401, { detail: "Chave de API ausente ou inválida." }));
    await expect(apiFetch("/api/v1/devices")).rejects.toThrow(ApiError);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("401 no login não redireciona (erro exibido na tela)", async () => {
    const spy = vi.fn();
    setOnUnauthorized(spy);
    vi.mocked(fetch).mockResolvedValueOnce(responder(401, { detail: "Usuário ou senha inválidos." }));
    await expect(apiFetch("/api/v1/auth/login", { method: "POST", body: {} })).rejects.toThrow(ApiError);
    expect(spy).not.toHaveBeenCalled();
  });

  it("422 vira erros por campo", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      responder(422, { detail: [{ loc: ["body", "password"], msg: "String should have at least 1 character" }] }),
    );
    await expect(apiFetch("/api/v1/auth/login", { method: "POST", body: { password: "" } })).rejects.toThrow(ApiError);
  });

  it("falha de rede → mensagem amigável", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(apiFetch("/api/v1/devices")).rejects.toThrow("Servidor indisponível. Tente novamente.");
  });

  it("204 → undefined", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(apiFetch("/api/v1/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });
});
```

Run: `cd web && npx vitest run src/api/client.test.ts`.
Expected: PASS.

- [ ] **Step 4: commit**

```bash
git add web/src/api/
git commit -m "feat(web): client HTTP com sessão cookie, erros PT-BR e redirecionamento em 401

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Auth front — contexto, RequireAuth, Login e layout shell

**Files:**
- Create: `web/src/auth/auth-context.tsx`
- Create: `web/src/auth/Login.tsx`
- Create: `web/src/auth/Login.test.tsx`, `web/src/auth/auth-context.test.tsx`
- Modify: `web/src/App.tsx` (rotas: `/login`, `/`, demais protegidas)
- Modify: `web/src/main.tsx` (setOnUnauthorized → navigate /login)

**Interfaces:**
- Consumes: `apiFetch`, `UserOut` (Task 3).
- Produces: `<AuthProvider>`, `useAuth().usuario/refreshUsuarios`, `<RequireAuth>`, `<RequireAdmin>`.

- [ ] **Step 1: `auth-context.tsx`**

```tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { apiFetch } from "@/api/client";
import type { UserOut } from "@/api/types";

interface AuthState {
  usuario: UserOut | null;
  carregando: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  podeEscrever: boolean;
  ehAdmin: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<UserOut | null>(null);
  const [carregando, setCarregando] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUsuario(await apiFetch<UserOut>("/api/v1/auth/me"));
    } catch {
      setUsuario(null);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const u = await apiFetch<UserOut>("/api/v1/auth/login", {
      method: "POST",
      body: { username, password },
    });
    setUsuario(u);
  }, []);

  const logout = useCallback(async () => {
    await apiFetch<void>("/api/v1/auth/logout", { method: "POST" });
    setUsuario(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      usuario,
      carregando,
      login,
      logout,
      refresh,
      podeEscrever: usuario !== null && usuario.role !== "visualizador",
      ehAdmin: usuario?.role === "administrador",
    }),
    [usuario, carregando, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth fora do AuthProvider");
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { usuario, carregando } = useAuth();
  const location = useLocation();
  if (carregando) return <p aria-live="polite">Carregando…</p>;
  if (!usuario) return <Navigate to="/login" state={{ from: location }} replace />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { ehAdmin } = useAuth();
  if (!ehAdmin) return <p>Somente administradores.</p>;
  return <>{children}</>;
}
```

- [ ] **Step 2: `Login.tsx` + test**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./auth-context";
import { ApiError } from "@/api/client";

export default function Login() {
  const { usuario, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const destino = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? "/";

  if (usuario) return <Navigate to={destino} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await login(username, password);
      navigate(destino, { replace: true });
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Usuário ou senha inválidos.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="login">
      <h1>gerenet</h1>
      {erro && <p role="alert">{erro}</p>}
      <form onSubmit={onSubmit}>
        <label>
          Usuário
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Senha
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <button className="primary" type="submit" disabled={enviando}>
          Entrar
        </button>
      </form>
    </main>
  );
}
```

`web/src/auth/Login.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Login from "./Login";
import { AuthProvider } from "./auth-context";
import { setOnUnauthorized } from "@/api/client";

// mock do /auth/me (carregando→null) para o provider não explodir
beforeAll(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/auth/me") return new Response("null", { status: 401 });
    return new Response(JSON.stringify({ detail: "Usuário ou senha inválidos." }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }));
});

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Login />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("Login", () => {
  it("mostra erro único para credenciais inválidas", async () => {
    renderLogin();
    await userEvent.type(screen.getByLabelText("Usuário"), "boss");
    await userEvent.type(screen.getByLabelText("Senha"), "errada");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Usuário ou senha inválidos.");
  });

  it("não registra a senha em lugar nenhum (sem campos de senha persistidos)", async () => {
    renderLogin();
    const senha = screen.getByLabelText("Senha") as HTMLInputElement;
    await userEvent.type(senha, "segredo123");
    expect(senha.value).toBe("segredo123");
    // garantia: nada em localStorage/sessionStorage
    expect(localStorage.getItem("gerenet")).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });
});
```
(ajustar o mock do fetch conforme o client — retorno `Promise<Response>`; o `Response` do jsdom é o do Node 20+, ok.)

`web/src/auth/auth-context.test.tsx` (testes do RequireAuth/RequireAdmin — só matchers base, sem jest-dom; o mock retorna 401 quando role é `null`):

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, RequireAdmin, RequireAuth } from "./auth-context";

const ME_BASE = {
  id: 1,
  username: "boss",
  is_active: true,
  last_login_at: null,
  created_at: "2026-09-04T00:00:00Z",
};

function mockMe(role: string | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url !== "/api/v1/auth/me") return new Response(null, { status: 404 });
      if (role === null) return new Response(null, { status: 401 });
      return new Response(JSON.stringify({ ...ME_BASE, role }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

describe("RequireAuth/RequireAdmin", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sem sessão, RequireAuth redireciona para /login", async () => {
    mockMe(null);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<RequireAuth><div>seguro</div></RequireAuth>} />
            <Route path="/login" element={<div>pagina-login</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("pagina-login")).toBeTruthy();
    expect(screen.queryByText("seguro")).toBeNull();
  });

  it("RequireAdmin bloqueia perfil não administrador", async () => {
    mockMe("operador");
    render(
      <MemoryRouter>
        <AuthProvider>
          <RequireAdmin><div>conteudo-admin</div></RequireAdmin>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Somente administradores.")).toBeTruthy();
    expect(screen.queryByText("conteudo-admin")).toBeNull();
  });

  it("RequireAdmin libera administrador", async () => {
    mockMe("administrador");
    render(
      <MemoryRouter>
        <AuthProvider>
          <RequireAdmin><div>conteudo-admin</div></RequireAdmin>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("conteudo-admin")).toBeTruthy();
  });
});
```

- [ ] **Step 3: `App.tsx` com rotas + setOnUnauthorized em `main.tsx`**

`web/src/main.tsx` — arquivo completo (o scaffold da T2 tem `queryClient` + `BrowserRouter` + `App` em `react-dom.createRoot`; o `setOnUnauthorized` precisa do `navigate`, então vive em componente dentro do Router e o `AuthProvider` envolve tudo):

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, useNavigate } from "react-router-dom";
import { AuthProvider } from "./auth/auth-context";
import { setOnUnauthorized } from "./api/client";
import App from "./App";
import "./styles/global.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

function Raiz() {
  const navigate = useNavigate();
  useEffect(() => {
    setOnUnauthorized(() => navigate("/login", { replace: true }));
  }, [navigate]);
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Raiz />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

`web/src/App.tsx`:
```tsx
import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAuth } from "@/auth/auth-context";
import Dashboard from "@/pages/Dashboard";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
```
(convenção: routes reais das tasks seguintes; esta task cria só `/login` + `/` apontando para um Dashboard placeholder criado na mesma task — ver Step 4.)

- [ ] **Step 4: Dashboard placeholder (substituído na Task 6)**

`web/src/pages/Dashboard.tsx`:
```tsx
export default function Dashboard() {
  return (
    <main>
      <h1>Dashboard</h1>
      <p>Em construção — ciclo C2.</p>
    </main>
  );
}
```

- [ ] **Step 5: testes passam + commit**

```bash
cd web && npx vitest run
```
Expected: PASS (client.test + Login.test + auth-context.test).

```bash
git add web/src
git commit -m "feat(web): login, auth context, RequireAuth/RequireAdmin e shell de rotas

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Componentes genéricos (DataTable, FormField, StatusBadge, SeverityBadge, ConfirmDialog, TimeAgo, PageHeader, MonoCode)

**Files:**
- Create: `web/src/components/DataTable.tsx`, `FormField.tsx`, `StatusBadge.tsx`, `SeverityBadge.tsx`, `ConfirmDialog.tsx`, `TimeAgo.tsx`, `PageHeader.tsx`, `MonoCode.tsx`
- Create: `web/src/components/*.test.tsx` (badges, DataTable, ConfirmDialog, TimeAgo)
- Modify: `web/src/styles/global.css` (classes dos componentes)

**Interfaces:**
- Consumes: nada além de React.
- Produces: kit usado por todas as telas (tasks 6–16).

- [ ] **Step 1: `StatusBadge` + `SeverityBadge`**

`web/src/components/StatusBadge.tsx`:
```tsx
type Estado =
  | "ok" | "fail" | "unknown"
  | "success" | "partial" | "error"
  | "queued" | "running"
  | "ativo" | "inativo"
  | string;

export function StatusBadge({ estado }: { estado: Estado }) {
  const cls =
    ["ok", "success", "ativo"].includes(estado) ? "ok"
    : ["fail", "error"].includes(estado) ? "fail"
    : ["running", "queued"].includes(estado) ? "warn"
    : "unknown";
  return <span className={`badge badge-${cls}`}>{estado}</span>;
}
```

`web/src/components/SeverityBadge.tsx`:
```tsx
export function SeverityBadge({ severidade }: { severidade: string }) {
  const cls = severidade === "critica" ? "danger" : severidade === "atencao" ? "warn" : "unknown";
  return <span className={`badge badge-${cls}`}>{severidade}</span>;
}
```

CSS (appendar em `global.css`): além das classes abaixo, ajuste de tokens (fecha os minors de design da T2 — o `#fff` hardcoded e o contraste do accent no light): (a) em `:root`, adicionar `--text-on-accent: #fff;`; (b) em `button.primary`, trocar `color: #fff` por `color: var(--text-on-accent);`; (c) no bloco `@media (prefers-color-scheme: light)`, adicionar `--accent: #1f6feb;` (branco sobre `#1f6feb` ≈ 4.6:1 — AA).

```css
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75rem; border: 1px solid var(--border); }
.badge-ok { color: var(--ok); }
.badge-fail, .badge-danger { color: var(--danger); }
.badge-warn { color: var(--warn); }
.badge-unknown { color: var(--unknown); }
.field { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.8rem; font-size: 0.9rem; }
.field em { color: var(--danger); font-style: normal; font-size: 0.8rem; }
.dialog-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; }
.dialog { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; max-width: 420px; width: 90%; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem; }
.mono-block { position: relative; }
.mono-block pre { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 6px; padding: 0.8rem; overflow-x: auto; white-space: pre-wrap; }
.mono-block button { position: absolute; top: 0.5rem; right: 0.5rem; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; }
.page-header h1 { margin: 0; font-size: 1.3rem; }
.login { max-width: 360px; margin: 15vh auto; padding: 1.5rem; }
.login h1 { margin-top: 0; }
.login form { display: flex; flex-direction: column; gap: 0.8rem; }
```

- [ ] **Step 2: `DataTable`**

```tsx
import type { ReactNode } from "react";

export interface Coluna<T> {
  key: string;
  title: string;
  render?: (linha: T) => ReactNode;
}

interface Props<T> {
  colunas: Coluna<T>[];
  linhas: T[];
  carregando?: boolean;
  vazio?: string;
  acoes?: (linha: T) => ReactNode;
}

export function DataTable<T>({ colunas, linhas, carregando, vazio = "Nenhum registro.", acoes }: Props<T>) {
  if (carregando) return <p aria-busy="true">Carregando…</p>;
  const vazioMsg = linhas.length === 0 ? <p>{vazio}</p> : null;
  return (
    <>
      <table>
        <thead>
          <tr>
            {colunas.map((c) => (
              <th key={c.key}>{c.title}</th>
            ))}
            {acoes && <th>Ações</th>}
          </tr>
        </thead>
        <tbody>
          {linhas.map((linha, i) => (
            <tr key={i}>
              {colunas.map((c) => (
                <td key={c.key}>{c.render ? c.render(linha) : String((linha as Record<string, unknown>)[c.key] ?? "")}</td>
              ))}
              {acoes && <td>{acoes(linha)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {vazioMsg}
    </>
  );
}
```

- [ ] **Step 3: `FormField`**

```tsx
import type { ReactNode } from "react";

interface Props {
  label: string;
  erro?: string;
  children: ReactNode;
}

export function FormField({ label, erro, children }: Props) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {erro && <em role="alert">{erro}</em>}
    </label>
  );
}
```

- [ ] **Step 4: `ConfirmDialog`**

```tsx
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
  if (!aberto) return null;
  return (
    <div role="dialog" aria-modal="true" aria-label={titulo} className="dialog-backdrop">
      <div className="dialog">
        <h2>{titulo}</h2>
        <p>{mensagem}</p>
        <div className="dialog-actions">
          <button onClick={onCancelar} disabled={confirmando}>
            Cancelar
          </button>
          <button className="danger" onClick={onConfirmar} disabled={confirmando}>
            {confirmando ? "Aguarde…" : "Confirmar"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: `TimeAgo`, `PageHeader`, `MonoCode`**

`TimeAgo.tsx`:
```tsx
export function TimeAgo({ iso }: { iso: string | null }) {
  if (!iso) return <span>—</span>;
  const dt = new Date(iso);
  const s = Math.round((dt.getTime() - Date.now()) / 1000);
  const abs = Math.abs(s);
  const texto =
    abs < 60 ? "agora"
    : abs < 3600 ? `há ${Math.round(abs / 60)}min`
    : abs < 86400 ? `há ${Math.round(abs / 3600)}h`
    : `há ${Math.round(abs / 86400)}d`;
  return <span title={dt.toLocaleString("pt-BR")}>{texto}</span>;
}
```

`PageHeader.tsx`:
```tsx
import type { ReactNode } from "react";

export function PageHeader({ titulo, acoes }: { titulo: string; acoes?: ReactNode }) {
  return (
    <header className="page-header">
      <h1>{titulo}</h1>
      {acoes}
    </header>
  );
}
```

`MonoCode.tsx`:
```tsx
import { useState } from "react";

export function MonoCode({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  async function copiar() {
    await navigator.clipboard.writeText(texto);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 1500);
  }
  return (
    <div className="mono-block">
      <button type="button" onClick={copiar}>
        {copiado ? "Copiado ✓" : "Copiar"}
      </button>
      <pre>{texto}</pre>
    </div>
  );
}
```

- [ ] **Step 6: testes dos componentes**

`web/src/components/componentes.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataTable } from "./DataTable";
import { StatusBadge } from "./StatusBadge";
import { SeverityBadge } from "./SeverityBadge";
import { ConfirmDialog } from "./ConfirmDialog";
import { TimeAgo } from "./TimeAgo";
import { MonoCode } from "./MonoCode";
import { FormField } from "./FormField";
import { PageHeader } from "./PageHeader";

describe("kit", () => {
  it("StatusBadge mapeia ok/success/ativo → badge-ok", () => {
    const { container } = render(<StatusBadge estado="success" />);
    expect(container.querySelector(".badge-ok")).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
  });

  it("SeverityBadge critica → danger", () => {
    const { container } = render(<SeverityBadge severidade="critica" />);
    expect(container.querySelector(".badge-danger")).toBeInTheDocument();
  });

  it("DataTable vazio mostra 'Nenhum registro.'", () => {
    render(<DataTable colunas={[{ key: "a", title: "A" }]} linhas={[]} />);
    expect(screen.getByText("Nenhum registro.")).toBeInTheDocument();
  });

  it("DataTable carregando bloqueia linhas", () => {
    render(<DataTable colunas={[{ key: "a", title: "A" }]} linhas={[{ a: 1 }]} carregando />);
    expect(screen.getByText("Carregando…")).toBeInTheDocument();
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });

  it("ConfirmDialog confirma e cancela", async () => {
    const onConfirmar = vi.fn();
    const onCancelar = vi.fn();
    render(
      <ConfirmDialog
        aberto
        titulo="Desativar?"
        mensagem="Desativar este registro?"
        onConfirmar={onConfirmar}
        onCancelar={onCancelar}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(onConfirmar).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(onCancelar).toHaveBeenCalledOnce();
  });

  it("TimeAgo formata idade relativa", () => {
    const ago = new Date(Date.now() - 3600 * 1000).toISOString();
    render(<TimeAgo iso={ago} />);
    expect(screen.getByText("há 1h")).toBeInTheDocument();
  });

  it("MonoCode copia o texto e sinaliza", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(Navigator.prototype, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<MonoCode texto="display version" />);
    await userEvent.click(screen.getByRole("button", { name: "Copiar" }));
    expect(writeText).toHaveBeenCalledWith("display version");
    expect(screen.getByText("Copiado ✓")).toBeInTheDocument();
  });

  it("FormField mostra erro com role alert", () => {
    render(
      <FormField label="Nome" erro="Obrigatório.">
        <input />
      </FormField>,
    );
    expect(screen.getByText("Obrigatório.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("PageHeader mostra título e ações", () => {
    render(<PageHeader titulo="Devices" acoes={<button>Novo</button>} />);
    expect(screen.getByRole("heading", { name: "Devices" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Novo" })).toBeTruthy();
  });
});
```

Run: `cd web && npx vitest run src/components`.
Expected: PASS.

- [ ] **Step 7: commit**

```bash
git add web/src/components web/src/styles/global.css
git commit -m "feat(web): kit de componentes (DataTable, FormField, badges, dialog, timeago)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: Página Users (admin) e Dashboard

> Esta task entrega as duas telas mais centrais; as demais CRUDs (7–16) derivam do mesmo kit.

**Files:**
- Create: `web/src/pages/Users.tsx` (+ `Users.test.tsx`)
- Create: `web/src/pages/Dashboard.tsx` (substitui placeholder) (+ `Dashboard.test.tsx`)
- Modify: `web/src/App.tsx` (+ rota `/users` com RequireAdmin, `/` já existe)
- Create: `web/src/api/hooks.ts`

**Interfaces:**
- Consumes: `apiFetch`, tipos (Task 3), `useAuth` (Task 4), kit (Task 5).
- Produces: `useUsers`, `useDashboard`, `useUserCriar`, `useUserAtualizar`, `useUserSenha`, `useMe`; tela `/users`; Dashboard real.

- [ ] **Step 1: `hooks.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { DashboardOut, JobRunOut, UserOut } from "./types";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => apiFetch<UserOut>("/api/v1/auth/me"), retry: false });
}

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => apiFetch<UserOut[]>("/api/v1/users"),
  });
}

export function useUserCriar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string; role: string }) =>
      apiFetch<UserOut>("/api/v1/users", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUserAtualizar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Pick<UserOut, "role">> & { username?: string; is_active?: boolean }) =>
      apiFetch<UserOut>(`/api/v1/users/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUserSenha() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      apiFetch<void>(`/api/v1/users/${id}/password`, { method: "POST", body: { password } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useDashboard() {
  return useQuery({ queryKey: ["dashboard"], queryFn: () => apiFetch<DashboardOut>("/api/v1/dashboard") });
}

// JOB_STATUS do domínio (models.py:22): queued/running/success/partial/error
const JOB_STATUS_TERMINAL = ["success", "partial", "error"];

export function useJobPoll(id: number | null) {
  return useQuery({
    queryKey: ["job", id],
    queryFn: () => apiFetch<JobRunOut>(`/api/v1/jobs/${id}`),
    enabled: id !== null && id > 0,
    refetchInterval: (query) =>
      query.state.data && JOB_STATUS_TERMINAL.includes(query.state.data.status) ? false : 3000,
  });
}
```

- [ ] **Step 2: `Users.tsx`**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useUserAtualizar, useUserCriar, useUserSenha, useUsers } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import type { UserOut } from "@/api/types";

const ROLES = ["visualizador", "operador", "aprovador", "executor", "administrador"] as const;

export default function Users() {
  const { usuario } = useAuth();
  const { data, isLoading } = useUsers();
  const criar = useUserCriar();
  const atualizar = useUserAtualizar();
  const senha = useUserSenha();
  const [username, setUsername] = useState("");
  const [senhaNova, setSenhaNova] = useState("");
  const [role, setRole] = useState<string>("operador");
  const [erro, setErro] = useState<string | null>(null);
  const [resetando, setResetando] = useState<UserOut | null>(null); // alvo do diálogo de redefinição
  const [senhaReset, setSenhaReset] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({ username, password: senhaNova, role });
      setUsername(""); setSenhaNova("");
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar usuário.");
    }
  }

  function alternarAtivo(u: UserOut) {
    if (u.id === usuario?.id) return;
    void atualizar.mutate({ id: u.id, is_active: !u.is_active });
  }

  return (
    <main>
      <PageHeader titulo="Usuários" />
      <form onSubmit={onSubmit} className="form-inline">
        <FormField label="Usuário">
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </FormField>
        <FormField label="Senha">
          <input type="password" value={senhaNova} onChange={(e) => setSenhaNova(e.target.value)} required />
        </FormField>
        <FormField label="Perfil">
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </FormField>
        <button className="primary" type="submit" disabled={criar.isPending}>
          Criar
        </button>
      </form>
      {erro && <p role="alert">{erro}</p>}
      <DataTable<UserOut>
        colunas={[
          { key: "username", title: "Usuário" },
          { key: "role", title: "Perfil" },
          { key: "is_active", title: "Situação", render: (u) => <StatusBadge estado={u.is_active ? "ativo" : "inativo"} /> },
          { key: "last_login_at", title: "Último login" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(u) => (
          <>
            <button
              type="button"
              onClick={() => {
                setResetando(u);
                setSenhaReset("");
              }}
            >
              Resetar senha
            </button>
            {u.id !== usuario?.id && (
              <button type="button" onClick={() => alternarAtivo(u)}>
                {u.is_active ? "Desativar" : "Reativar"}
              </button>
            )}
          </>
        )}
      />
      {atualizar.error && <p role="alert">{String(atualizar.error?.message ?? "Falha ao atualizar.")}</p>}
      {resetando && (
        <div role="dialog" aria-modal="true" aria-label={`Redefinir senha de ${resetando.username}`}>
          <h2>Redefinir senha de {resetando.username}</h2>
          <FormField label="Nova senha">
            <input
              type="password"
              value={senhaReset}
              onChange={(e) => setSenhaReset(e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
          {senha.error && <p role="alert">{String(senha.error.message ?? "Falha ao redefinir.")}</p>}
          <button
            className="danger"
            disabled={senha.isPending || senhaReset.length === 0}
            onClick={() =>
              void senha.mutateAsync({ id: resetando.id, password: senhaReset }).then(() => setResetando(null))
            }
          >
            Redefinir
          </button>
          <button onClick={() => setResetando(null)}>Cancelar</button>
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 3: `Dashboard.tsx` (substitui o placeholder)**

```tsx
import { Link } from "react-router-dom";
import { useDashboard } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import type { PerDeviceOut } from "@/api/types";

export default function Dashboard() {
  const { data, isLoading } = useDashboard();

  return (
    <main>
      <PageHeader titulo="Dashboard" />
      {isLoading && <p aria-busy="true">Carregando…</p>}
      {data && (
        <>
          <section className="cards">
            <div className="card"><strong>{data.devices.total}</strong> equipamentos</div>
            <div className="card"><strong>{data.devices.active}</strong> ativos</div>
            <div className="card"><strong>{data.bgp_sessions.active}</strong> sessões BGP ativas</div>
            <div className="card"><strong>{data.circuits.active}</strong> circuitos ativos</div>
            <div className="card"><strong>{data.vlans.reserved}</strong> VLANs reservadas</div>
            <div className="card"><strong>{data.ip_prefixes.reserved}</strong> prefixos reservados</div>
          </section>
          <h2>Equipamentos</h2>
          <table>
            <thead>
              <tr>
                <th>Nome</th><th>Site</th><th>Status</th><th>Última coleta</th><th>Snapshot</th><th>Job</th><th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {data.per_device.map((d: PerDeviceOut) => (
                <tr key={d.device_id}>
                  <td><Link to={`/devices/${d.device_id}`}>{d.name}</Link></td>
                  <td>{d.site_name ?? "—"}</td>
                  <td><StatusBadge estado={d.comm_status} /></td>
                  <td><TimeAgo iso={d.last_collected_at} /></td>
                  <td>{d.latest_snapshot ? <StatusBadge estado={d.latest_snapshot.status} /> : "—"}</td>
                  <td>{d.active_job ? <StatusBadge estado={d.active_job.status} /> : "—"}</td>
                  <td>
                    <Link to={`/devices/${d.device_id}`}>Detalhe</Link>{" "}
                    <Link to={`/devices/${d.device_id}`}>Coletar</Link>{" "}
                    <Link to={`/reconcile?device_id=${d.device_id}`}>Reconciliar</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>Auditoria recente</h2>
          <table>
            <thead><tr><th>Quando</th><th>Ação</th><th>Autor</th></tr></thead>
            <tbody>
              {data.recent_audit.map((e) => (
                <tr key={e.id}>
                  <td><TimeAgo iso={e.created_at} /></td>
                  <td>{e.type}</td>
                  <td>{e.actor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
```

- [ ] **Step 4: rotas em `App.tsx`**

```tsx
import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAdmin, RequireAuth } from "@/auth/auth-context";
import Dashboard from "@/pages/Dashboard";
import Users from "@/pages/Users";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/users"
        element={
          <RequireAuth>
            <RequireAdmin>
              <Users />
            </RequireAdmin>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
```

CSS a appendar em `global.css` (classes usadas por estas duas telas):

```css
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; margin-bottom: 1.2rem; }
.card { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 8px; padding: 0.9rem; font-size: 0.9rem; }
.card strong { display: block; font-size: 1.5rem; }
.form-inline { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.6rem; margin-bottom: 1rem; }
```

- [ ] **Step 5: testes**

`web/src/pages/Users.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Users from "./Users";
import { AuthProvider } from "@/auth/auth-context";

const ME_ADMIN = {
  id: 1,
  username: "boss",
  role: "administrador",
  is_active: true,
  last_login_at: null,
  created_at: "2026-09-04T00:00:00Z",
};

const USUARIOS = [
  ME_ADMIN,
  {
    id: 2,
    username: "operador1",
    role: "operador",
    is_active: true,
    last_login_at: null,
    created_at: "2026-09-04T00:00:00Z",
  },
];

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/auth/me") {
        return new Response(JSON.stringify(ME_ADMIN), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/users" && (init?.method === undefined || init.method === "GET")) {
        return new Response(JSON.stringify(USUARIOS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/users/2" && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ...USUARIOS[1], is_active: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderUsers() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <Users />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Users", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lista usuários e a conta própria não tem botão de ativar/desativar", async () => {
    mockFetch();
    renderUsers();
    expect(await screen.findByText("operador1")).toBeTruthy();
    const botoes = screen.getAllByRole("button", { name: /desativar/i });
    expect(botoes).toHaveLength(1);
  });

  it("desativar dispara PATCH is_active:false", async () => {
    mockFetch();
    renderUsers();
    await screen.findByText("operador1");
    await userEvent.click(screen.getAllByRole("button", { name: /desativar/i })[0]);
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find(([u, i]) => u === "/api/v1/users/2" && i.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(String(patch![1].body))).toEqual({ is_active: false });
    });
  });
});
```

`web/src/pages/Dashboard.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";

const DASH = {
  devices: { total: 3, active: 2, with_snapshot: 1, by_comm_status: { unknown: 1, ok: 1, fail: 1 } },
  per_device: [
    {
      device_id: 1,
      name: "ne8000-01",
      site_id: null,
      site_name: null,
      comm_status: "ok",
      last_collected_at: null,
      snapshot_age_seconds: null,
      latest_snapshot: null,
      active_job: null,
    },
  ],
  bgp_sessions: { total: 4, active: 3, shutdown: 1 },
  circuits: { total: 2, active: 1 },
  vlans: { reserved: 5, freed: 0 },
  ip_prefixes: { reserved: 7, freed: 0 },
  recent_audit: [{ id: 1, type: "coleta", actor: "boss", details: {}, created_at: "2026-09-04T00:00:00Z" }],
};

describe("Dashboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renderiza cards, per_device e auditoria recente", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/v1/dashboard") {
          return new Response(JSON.stringify(DASH), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        return new Response(null, { status: 404 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("ne8000-01")).toBeTruthy();
    expect(screen.getByText(/^3 equipamentos$/)).toBeTruthy();
    expect(screen.getByText("coleta")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Reconciliar" })).toBeTruthy();
  });
});
```

Run: `cd web && npx vitest run`.
Expected: PASS.

- [ ] **Step 6: commit**

```bash
git add web/src/api/hooks.ts web/src/pages/Users.tsx web/src/pages/Dashboard.tsx web/src/App.tsx web/src/pages/Users.test.tsx web/src/pages/Dashboard.test.tsx
git commit -m "feat(web): telas de usuarios (admin) e dashboard com agregados e per_device

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Telas CRUD — devices, sites, organizations, contacts

**Files:**
- Create: `web/src/pages/Devices.tsx`, `Sites.tsx`, `Organizations.tsx`, `Contacts.tsx`
- Modify: `web/src/App.tsx` (rotas `/devices`, `/sites`, `/organizations`, `/contacts`)
- Create: `web/src/pages/Devices.test.tsx`, `Sites.test.tsx`

**Interfaces:**
- Consumes: hooks (Task 6) — adicionar `useDevices`, `useSites`, `useOrganizations`, `useContacts` no `hooks.ts` (mesmo padrão `useQuery` + `useMutation` com invalidação).
- Produces: CRUDs funcionais das 4 entidades — base das demais (circuits/bgp-sessions na Task 8).

- [ ] **Step 1: hooks das 4 entidades no `hooks.ts`**

```ts
export function useLista<T>(chave: string, url: string) {
  return useQuery({ queryKey: [chave], queryFn: () => apiFetch<T[]>(url) });
}

export function useCriar<TIn, TOut>(chave: string, url: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TIn) => apiFetch<TOut>(url, { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [chave] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useAtualizar<TIn, TOut>(chave: string, url: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: TIn & { id: number }) =>
      apiFetch<TOut>(`${url}/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [chave] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useDevices = () => useLista<DeviceOut>("devices", "/api/v1/devices");
export const useSites = () => useLista<SiteOut>("sites", "/api/v1/sites");
export const useOrganizations = () => useLista<OrganizationOut>("organizations", "/api/v1/organizations");
export const useContacts = () => useLista<ContactOut>("contacts", "/api/v1/contacts");

export type DeviceCreateIn = {
  name: string;
  management_address: string;
  ssh_port?: number | null;
  model?: string | null;
  family?: string | null;
  role?: string | null;
  site_id?: number | null;
  asn?: number | null;
  tags?: string[];
};
export const useDeviceCriar = () => useCriar<DeviceCreateIn, DeviceOut>("devices", "/api/v1/devices");
export const useDeviceAtualizar = () =>
  useAtualizar<Partial<DeviceCreateIn> & { admin_status?: boolean }, DeviceOut>("devices", "/api/v1/devices");

export function useDeviceColetar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: number) =>
      apiFetch<CollectResposta>(`/api/v1/devices/${deviceId}/collect`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["devices"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export type SiteCreateIn = {
  name: string;
  city?: string | null;
  uf?: string | null;
  p2p_ipv4_block?: string | null;
  p2p_ipv6_base?: string | null;
};
export const useSiteCriar = () => useCriar<SiteCreateIn, SiteOut>("sites", "/api/v1/sites");
export const useSiteAtualizar = () => useAtualizar<Partial<SiteCreateIn> & { admin_status?: boolean }, SiteOut>("sites", "/api/v1/sites");

export type OrganizationCreateIn = {
  name: string;
  legal_name?: string | null;
  kind: "downstream" | "parceiro";
  asn?: number | null;
  irr_as_set?: string | null;
  notes?: string | null;
};
export const useOrganizationCriar = () =>
  useCriar<OrganizationCreateIn, OrganizationOut>("organizations", "/api/v1/organizations");
export const useOrganizationAtualizar = () =>
  useAtualizar<Partial<OrganizationCreateIn> & { admin_status?: boolean }, OrganizationOut>("organizations", "/api/v1/organizations");

export type ContactCreateIn = {
  organization_id: number;
  name: string;
  email?: string | null;
  phone?: string | null;
  kind: "tecnico" | "noc" | "admin";
};
export const useContactCriar = () => useCriar<ContactCreateIn, ContactOut>("contacts", "/api/v1/contacts");
export const useContactAtualizar = () =>
  useAtualizar<Partial<ContactCreateIn> & { admin_status?: boolean }, ContactOut>("contacts", "/api/v1/contacts");
```

- [ ] **Step 2: `Devices.tsx` — o modelo canônico de todas as CRUDs**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useDeviceAtualizar,
  useDeviceColetar,
  useDeviceCriar,
  useDevices,
  useSites,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { DeviceOut } from "@/api/types";

const FORM_VAZIO = {
  name: "",
  management_address: "",
  ssh_port: "",
  model: "",
  family: "",
  role: "",
  asn: "",
  tags: "",
  site_id: "",
};

export default function Devices() {
  const { podeEscrever } = useAuth();
  const navigate = useNavigate();
  const { data, isLoading } = useDevices();
  const { data: sites } = useSites();
  const criar = useDeviceCriar();
  const atualizar = useDeviceAtualizar();
  const coletar = useDeviceColetar();

  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<DeviceOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        management_address: form.management_address,
        ssh_port: form.ssh_port === "" ? null : Number(form.ssh_port),
        model: form.model || null,
        family: form.family || null,
        role: form.role || null,
        asn: form.asn === "" ? null : Number(form.asn),
        tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
        site_id: form.site_id === "" ? null : Number(form.site_id),
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar equipamento.");
    }
  }

  function desativar() {
    if (!desativando) return;
    void atualizar
      .mutateAsync({ id: desativando.id, admin_status: false })
      .then(() => setDesativando(null));
  }

  return (
    <main>
      <PageHeader titulo="Equipamentos" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="IP de gestão *">
            <input value={form.management_address} onChange={(e) => setForm({ ...form, management_address: e.target.value })} required />
          </FormField>
          <FormField label="Porta SSH">
            <input type="number" value={form.ssh_port} onChange={(e) => setForm({ ...form, ssh_port: e.target.value })} />
          </FormField>
          <FormField label="Modelo">
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </FormField>
          <FormField label="Família">
            <input value={form.family} onChange={(e) => setForm({ ...form, family: e.target.value })} />
          </FormField>
          <FormField label="Função">
            <input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
          </FormField>
          <FormField label="ASN">
            <input type="number" value={form.asn} onChange={(e) => setForm({ ...form, asn: e.target.value })} />
          </FormField>
          <FormField label="Site">
            <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
              <option value="">—</option>
              {(sites ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Tags (separadas por vírgula)">
            <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<DeviceOut>
        colunas={[
          { key: "name", title: "Nome", render: (d) => <Link to={`/devices/${d.id}`}>{d.name}</Link> },
          { key: "management_address", title: "IP" },
          { key: "site", title: "Site", render: (d) => sites?.find((s) => s.id === d.site_id)?.name ?? "—" },
          { key: "role", title: "Função", render: (d) => d.role ?? "—" },
          { key: "comm_status", title: "Comunicação", render: (d) => <StatusBadge estado={d.comm_status} /> },
          { key: "last_collected_at", title: "Última coleta", render: (d) => <TimeAgo iso={d.last_collected_at} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(d) => (
          <>
            {podeEscrever && (
              <button
                type="button"
                onClick={() => void coletar.mutate(d.id).then(() => navigate(`/jobs?device_id=${d.id}`))}
              >
                Coletar agora
              </button>
            )}
            {podeEscrever && d.admin_status && (
              <button type="button" onClick={() => setDesativando(d)}>
                Desativar
              </button>
            )}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="Não exclui o registro: só desativa a administração."
        onConfirmar={desativar}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
```

> `credential_group_id` fica fora da UI do C2 — não há rota de leitura de grupos de credencial (cadeia de segurança: referência apenas via configuração/CLI).

- [ ] **Step 3: `Sites.tsx` — variante do mesmo padrão (campos: name, city, uf, p2p_ipv4_block, p2p_ipv6_base)**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useSiteAtualizar, useSiteCriar, useSites } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { SiteOut } from "@/api/types";

const FORM_VAZIO = { name: "", city: "", uf: "", p2p_ipv4_block: "", p2p_ipv6_base: "" };

export default function Sites() {
  const { podeEscrever } = useAuth();
  const { data, isLoading } = useSites();
  const criar = useSiteCriar();
  const atualizar = useSiteAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<SiteOut | null>(null);
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
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(s) =>
          podeEscrever && s.admin_status ? (
            <button type="button" onClick={() => setDesativando(s)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O site fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando) void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
```

- [ ] **Step 4: `Organizations.tsx` e `Contacts.tsx`** (mesmo padrão de `Sites.tsx`)

`web/src/pages/Organizations.tsx`:

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useOrganizationAtualizar, useOrganizationCriar, useOrganizations } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { OrganizationOut } from "@/api/types";

const FORM_VAZIO = { name: "", legal_name: "", kind: "downstream" as "downstream" | "parceiro", asn: "", irr_as_set: "", notes: "" };

export default function Organizations() {
  const { podeEscrever } = useAuth();
  const { data, isLoading } = useOrganizations();
  const criar = useOrganizationCriar();
  const atualizar = useOrganizationAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<OrganizationOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        legal_name: form.legal_name || null,
        kind: form.kind,
        asn: form.asn === "" ? null : Number(form.asn),
        irr_as_set: form.irr_as_set || null,
        notes: form.notes || null,
      });
      setForm({ ...FORM_VAZIO });
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar organização.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Organizações" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="Razão social">
            <input value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} />
          </FormField>
          <FormField label="Tipo">
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as "downstream" | "parceiro" })}
            >
              <option value="downstream">downstream</option>
              <option value="parceiro">parceiro</option>
            </select>
          </FormField>
          <FormField label="ASN">
            <input type="number" value={form.asn} onChange={(e) => setForm({ ...form, asn: e.target.value })} />
          </FormField>
          <FormField label="IRR AS-SET">
            <input value={form.irr_as_set} onChange={(e) => setForm({ ...form, irr_as_set: e.target.value })} />
          </FormField>
          <FormField label="Observações">
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<OrganizationOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "legal_name", title: "Razão social", render: (o) => o.legal_name ?? "—" },
          { key: "kind", title: "Tipo", render: (o) => <StatusBadge estado={o.kind} /> },
          { key: "asn", title: "ASN", render: (o) => o.asn ?? "—" },
          { key: "irr_as_set", title: "IRR AS-SET", render: (o) => o.irr_as_set ?? "—" },
          { key: "notes", title: "Observações", render: (o) => o.notes ?? "—" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(o) =>
          podeEscrever && o.admin_status ? (
            <button type="button" onClick={() => setDesativando(o)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="A organização fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
```

`web/src/pages/Contacts.tsx`:

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useContactAtualizar, useContactCriar, useContacts, useOrganizations } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ContactOut } from "@/api/types";

const FORM_VAZIO = { organization_id: "", name: "", email: "", phone: "", kind: "tecnico" as "tecnico" | "noc" | "admin" };

export default function Contacts() {
  const { podeEscrever } = useAuth();
  const { data, isLoading } = useContacts();
  const { data: organizations } = useOrganizations();
  const criar = useContactCriar();
  const atualizar = useContactAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<ContactOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    if (form.organization_id === "") return;
    try {
      await criar.mutateAsync({
        organization_id: Number(form.organization_id),
        name: form.name,
        email: form.email || null,
        phone: form.phone || null,
        kind: form.kind,
      });
      setForm({ ...FORM_VAZIO });
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar contato.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Contatos" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Organização *">
            <select
              value={form.organization_id}
              onChange={(e) => setForm({ ...form, organization_id: e.target.value })}
              required
            >
              <option value="">—</option>
              {(organizations ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="E-mail">
            <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </FormField>
          <FormField label="Telefone">
            <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </FormField>
          <FormField label="Tipo">
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as "tecnico" | "noc" | "admin" })}
            >
              <option value="tecnico">tecnico</option>
              <option value="noc">noc</option>
              <option value="admin">admin</option>
            </select>
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<ContactOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "email", title: "E-mail", render: (c) => c.email ?? "—" },
          { key: "phone", title: "Telefone", render: (c) => c.phone ?? "—" },
          { key: "kind", title: "Tipo" },
          {
            key: "organization",
            title: "Organização",
            render: (c) => organizations?.find((o) => o.id === c.organization_id)?.name ?? "—",
          },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(c) =>
          podeEscrever && c.admin_status ? (
            <button type="button" onClick={() => setDesativando(c)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O contato fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
```

Teste de referência (`web/src/pages/Sites.test.tsx`; o de `Devices.test.tsx` está no Step 6 — inclui o fluxo coletar→`/jobs`):

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Sites from "./Sites";
import { AuthProvider } from "@/auth/auth-context";

const lista = [{ id: 1, name: "SPO", city: "São Paulo", uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true }];

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ id: 2, ...body, p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.startsWith("/api/v1/sites")) return new Response(JSON.stringify(lista), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" }), { status: 200, headers: { "Content-Type": "application/json" } });
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
      expect(chamadas.some((c) => (c[1]?.method === "POST") && String(c[1]?.body).includes("REC"))).toBe(true);
    });
  });

  it("usa o perfil do usuário logado para liberar escrita", async () => {
    renderSites();
    expect(await screen.findByText("SPO")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cadastrar" })).toBeInTheDocument();
  });
});
```

> `getByLabelText` depende do `FormField` transformar o label child de modo que o `htmlFor`/wrapper associe ao input. Se o ajuste for necessário, usar `screen.getByPlaceholderText`? Não — preferir `FormField` com `<label>` envolvendo o campo (associação implícita, como no Login.tsx).

- [ ] **Step 5: rotas em `App.tsx`** (substituir o arquivo inteiro):

```tsx
import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAdmin, RequireAuth } from "@/auth/auth-context";
import Contacts from "@/pages/Contacts";
import Dashboard from "@/pages/Dashboard";
import Devices from "@/pages/Devices";
import Organizations from "@/pages/Organizations";
import Sites from "@/pages/Sites";
import Users from "@/pages/Users";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/users"
        element={
          <RequireAuth>
            <RequireAdmin>
              <Users />
            </RequireAdmin>
          </RequireAuth>
        }
      />
      <Route
        path="/devices"
        element={
          <RequireAuth>
            <Devices />
          </RequireAuth>
        }
      />
      <Route
        path="/sites"
        element={
          <RequireAuth>
            <Sites />
          </RequireAuth>
        }
      />
      <Route
        path="/organizations"
        element={
          <RequireAuth>
            <Organizations />
          </RequireAuth>
        }
      />
      <Route
        path="/contacts"
        element={
          <RequireAuth>
            <Contacts />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
```

- [ ] **Step 6: `Devices.test.tsx` + testes + build + lint + commit**

`web/src/pages/Devices.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Devices from "./Devices";
import { AuthProvider } from "@/auth/auth-context";

const equipamentos = [
  {
    id: 1,
    name: "ne8000-01",
    management_address: "10.99.0.1",
    site_id: 1,
    role: "core",
    comm_status: "ok",
    last_collected_at: null,
    admin_status: true,
  },
];
const sites = [{ id: 1, name: "SPO", city: null, uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true }];

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        if (url === "/api/v1/devices/1/collect") {
          return new Response(JSON.stringify({ queued: true, message: "Coleta enfileirada.", job_id: "rq-abc" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 2, ...body, site_id: null, comm_status: "unknown", last_collected_at: null, admin_status: true }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/v1/devices/1" && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ...equipamentos[0], admin_status: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/v1/devices") {
        return new Response(JSON.stringify(equipamentos), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/sites") {
        return new Response(JSON.stringify(sites), { status: 200, headers: { "Content-Type": "application/json" } });
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

function renderDevices() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/devices"]}>
        <AuthProvider>
          <Routes>
            <Route path="/devices" element={<Devices />} />
            <Route path="/jobs" element={<div>jobs-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Devices", () => {
  it("lista equipamentos e cadastra novo pela API", async () => {
    renderDevices();
    expect(await screen.findByText("ne8000-01")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Nome *"), "ne8000-02");
    await userEvent.type(screen.getByLabelText("IP de gestão *"), "10.99.0.2");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("ne8000-02"))).toBe(true);
    });
  });

  it("Coletar agora dispara a coleta e navega para /jobs com o device", async () => {
    renderDevices();
    await screen.findByText("ne8000-01");
    await userEvent.click(screen.getByRole("button", { name: "Coletar agora" }));
    expect(await screen.findByText("jobs-page")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => c[0] === "/api/v1/devices/1/collect" && c[1]?.method === "POST")).toBe(true);
    });
  });

  it("Desativar pede confirmação e envia PATCH admin_status:false", async () => {
    renderDevices();
    await screen.findByText("ne8000-01");
    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    expect(screen.getByRole("dialog", { name: "Desativar ne8000-01?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      const patch = chamadas.find((c) => c[0] === "/api/v1/devices/1" && c[1]?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(String(patch![1].body))).toEqual({ admin_status: false });
    });
  });
});
```

Run (na raiz do repositório):

```bash
cd web && npx vitest run src/pages/Devices.test.tsx src/pages/Sites.test.tsx
cd web && npm run build
cd web && npx eslint src
```

Expected: 5 testes PASS, build sem erro, lint limpo.

- [ ] **Step 7: commit**

```bash
git add web/src/pages web/src/App.tsx web/src/api/hooks.ts
git commit -m "feat(web): CRUD de devices, sites, organizations e contacts

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Telas circuits e bgp-sessions (+ detalhes com reserve, communities, definição de senha no Vault)

**Files:**
- Create: `web/src/pages/Circuits.tsx`, `CircuitDetail.tsx`, `BgpSessions.tsx`, `BgpSessionDetail.tsx`
- Modify: `web/src/App.tsx`, `web/src/api/hooks.ts` (hooks de circuits/bgp-sessions + mutations de reserve/communities/senha)
- Create: `web/src/pages/Circuits.test.tsx`, `BgpSessions.test.tsx`

**Interfaces:**
- Consumes: Task 7 (padrão CRUD), schemas `CircuitOut/CircuitDetailOut/BgpSessionOut` (Task 3).
- Produces: circuito com "Reservar recursos" (POST `/circuits/{id}/reserve`) e detalhe (VLANs/prefixos, sessões); sessão BGP com associação de communities (POST/DELETE) e "Definir senha" (POST `/bgp-sessions/{id}/password` — nunca exibe a senha; mostra `has_password`).

> **Ruling (lacuna de contrato):** `BgpSessionOut` NÃO carrega as communities associadas (schemas.py:323 só `has_password`); a API só tinha POST/DELETE de associação. A UI precisa de leitura — o Step 0 abaixo adiciona `GET /api/v1/bgp-sessions/{session_id}/communities` (idempotente e auditável, igual ao padrão do router).

- [ ] **Step 0 (backend): `GET /api/v1/bgp-sessions/{session_id}/communities`**

Em `src/gerenet/domain/services/bgp_sessions.py` (após `get_session`, ~linha 172):

```python
def list_communities(session: Session, session_id: int) -> list[models.Community]:
    """Communities associadas à sessão, na ordem de associação."""
    get_session(session, session_id)
    return list(
        session.scalars(
            select(models.Community)
            .join(
                models.BgpSessionCommunity,
                models.BgpSessionCommunity.community_id == models.Community.id,
            )
            .where(models.BgpSessionCommunity.session_id == session_id)
            .order_by(models.BgpSessionCommunity.id)
        )
    )
```

Em `src/gerenet/api/routers/bgp_sessions.py`: adicionar `CommunityOut` ao import de `gerenet.domain.schemas`, e a rota para `listar_communities` (após `definir_senha`):

```python
@router.get("/{session_id}/communities", response_model=list[CommunityOut])
def listar_communities(session_id: int, session: SessionDep) -> object:
    """Communities associadas à sessão, na ordem de associação."""
    try:
        return svc.list_communities(session, session_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

Em `tests/api/test_communities_api.py` (após `test_associacao_inexistente_da_404`):

```python
def test_lista_communities_da_sessao(client: TestClient, db_session: Session) -> None:
    sessao_id = _sessao(db_session)
    comunidade = client.get("/api/v1/communities", headers=_auth()).json()[0]  # blackhole
    associada = client.post(
        f"/api/v1/bgp-sessions/{sessao_id}/communities",
        json={"community_id": comunidade["id"]}, headers=_auth(),
    )
    assert associada.status_code == 200

    lista = client.get(f"/api/v1/bgp-sessions/{sessao_id}/communities", headers=_auth())
    assert lista.status_code == 200, lista.text
    assert [c["name"] for c in lista.json()] == ["blackhole"]

    assert client.get("/api/v1/bgp-sessions/9999/communities", headers=_auth()).status_code == 404
```

Run: `uv run pytest -q tests/api/test_communities_api.py`
Expected: 4 passed.

> **Ruling (pré-dispatch, verificado na implementação):** a linha `Expected: 4 passed` acima é INALCANÇÁVEL até a infra de teste ser tornada independente do `web/dist` que existir na máquina. `montar_spa` (static_spa.py) registra o catch-all quando `web/dist/index.html` EXISTE NO DISCO (não é rastreado; nasce do `vite build` do T2). Com o catch-all ativo, `POST /api/v1/communities` (rota real só-GET) casa com `/{path:path}` (POST) e devolve **404** (contrato documentado "404, não 405"), quebrando o `test_lista_communities_read_only` pré-existente do C1 (escreve 405). Em máquina sem `web/dist`, o teste passa (casa sem catch-all → 405 natural do Starlette). É o minor parkado do C1 "static_dir em fixtures": o `static_dir_inexistente` existe em tests/api/conftest.py mas só é usado por test_static_spa.py. **Correção (infra de teste, não produção, não o teste antigo):** autouse que pina um static_dir inexistente — o teste 405 fica intacto e a suíte volta a ser determinística para qualquer gate backend do ciclo (T8, T13).

- [ ] **Step 0.5 (infra de teste): autouse `spa_sem_build` em tests/api/conftest.py**

```python
@pytest.fixture(autouse=True)
def spa_sem_build(static_dir_inexistente: Path) -> Iterator[None]:
    # Minor C1: os testes de API nunca devem depender do web/dist que existir
    # na máquina — com o build presente, montar_spa registra o catch-all e
    # POST/PUT/PATCH/DELETE em rota desconhecida devolvem 404 (contrato
    # pré-fallback) em vez do 405 natural do Starlette. Pinando um diretório
    # inexistente, o fallback não é montado; test_static_spa.py sobrepõe pelo
    # próprio set_settings no fixture client (ordem: autouse corre antes).
    set_settings(Settings(static_dir=static_dir_inexistente, _env_file=None))
    yield
```

(Import: `from collections.abc import Iterator`; `from gerenet.config import Settings, set_settings`.)

- [ ] **Step 1: hooks de circuits/bgp-sessions no `hooks.ts`** (append após os hooks da Task 6/7)

```ts
export const useCircuits = () => useLista<CircuitOut>("circuits", "/api/v1/circuits");
export const useCircuitDetail = (id: number) =>
  useQuery({ queryKey: ["circuit", id], queryFn: () => apiFetch<CircuitDetailOut>(`/api/v1/circuits/${id}`) });

export type CircuitCreateIn = {
  code: string;
  organization_id: number;
  site_id: number;
  access_device_id: number;
  access_port: string;
  edge_device_id: number;
  backup_edge_device_id?: number | null;
  stack: "ipv4" | "ipv6" | "dual";
  vlan_mode: "unica" | "separada";
  qinq?: boolean;
  vrf?: string | null;
  mtu?: number | null;
  bandwidth?: string | null;
  bfd?: boolean;
  p2p_v4_len?: 30 | 31;
  description?: string | null;
  notes?: string | null;
  edge_trunk?: string | null;
};
export const useCircuitCriar = () => useCriar<CircuitCreateIn, CircuitOut>("circuits", "/api/v1/circuits");
export const useCircuitAtualizar = () =>
  useAtualizar<Partial<CircuitCreateIn> & { admin_status?: boolean }, CircuitOut>("circuits", "/api/v1/circuits");
export function useCircuitoReservar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<CircuitDetailOut>(`/api/v1/circuits/${id}/reserve`, { method: "POST" }),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ["circuit", id] });
      void qc.invalidateQueries({ queryKey: ["circuits"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useBgpSessions = (filtros?: { circuit_id?: number; device_id?: number }) =>
  useQuery({
    queryKey: ["bgp-sessions", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.circuit_id) qs.set("circuit_id", String(filtros.circuit_id));
      if (filtros?.device_id) qs.set("device_id", String(filtros.device_id));
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<BgpSessionOut[]>(`/api/v1/bgp-sessions${suf}`);
    },
  });
export const useBgpSession = (id: number) =>
  useQuery({ queryKey: ["bgp-session", id], queryFn: () => apiFetch<BgpSessionOut>(`/api/v1/bgp-sessions/${id}`) });

export type BgpSessionCreateIn = {
  circuit_id: number;
  device_id: number;
  afi: "ipv4" | "ipv6";
  local_address: string;
  remote_address: string;
  source_address?: string | null;
  asn_local?: number | null;
  asn_remote?: number | null;
  description?: string | null;
  import_profile_id?: number | null;
  export_profile_id?: number | null;
  maximum_prefix?: number | null;
  maximum_prefix_threshold?: number | null;
  local_preference?: number | null;
  med?: number | null;
  prepend?: number | null;
  keepalive?: number | null;
  holdtime?: number | null;
  bfd_enabled?: boolean;
  graceful_restart?: boolean;
  shutdown?: boolean;
  allow_default_route?: boolean;
};
export const useBgpSessionCriar = () => useCriar<BgpSessionCreateIn, BgpSessionOut>("bgp-sessions", "/api/v1/bgp-sessions");
export const useBgpSessionAtualizar = () =>
  useAtualizar<Partial<BgpSessionCreateIn> & { admin_status?: boolean }, BgpSessionOut>("bgp-sessions", "/api/v1/bgp-sessions");

export const useSessionCommunities = (sessionId: number) =>
  useQuery({
    queryKey: ["bgp-session-communities", sessionId],
    queryFn: () => apiFetch<CommunityOut[]>(`/api/v1/bgp-sessions/${sessionId}/communities`),
  });
export function useSessionCommunity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, communityId, associa }: { sessionId: number; communityId: number; associa: boolean }) =>
      associa
        ? apiFetch<void>( // resposta não usada: a lista é refetched por invalidação; ambos os ramos → Promise<void>
            `/api/v1/bgp-sessions/${sessionId}/communities`,
            { method: "POST", body: { community_id: communityId } },
          )
        : apiFetch<void>(`/api/v1/bgp-sessions/${sessionId}/communities/${communityId}`, { method: "DELETE" }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["bgp-session-communities", v.sessionId] });
      void qc.invalidateQueries({ queryKey: ["bgp-session", v.sessionId] });
    },
  });
}
export function useSessionSenha() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, password }: { sessionId: number; password: string }) =>
      apiFetch<BgpSessionOut>(`/api/v1/bgp-sessions/${sessionId}/password`, { method: "POST", body: { password } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["bgp-sessions"] }),
  });
}

export const usePolicyProfiles = (filtros?: { direction?: string }) =>
  useQuery({
    queryKey: ["policy-profiles", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.direction) qs.set("direction", filtros.direction);
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<PolicyProfileOut[]>(`/api/v1/policy-profiles${suf}`);
    },
  });
export const useCommunities = () => useLista<CommunityOut>("communities", "/api/v1/communities");
```

> `usePolicyProfiles`/`useCommunities` nascem aqui (usadas pelo form de sessão e pelo detail); a Task 9 só cria as telas, não os hooks de lista.

- [ ] **Step 2: `Circuits.tsx`**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useCircuitAtualizar, useCircuitCriar, useCircuits, useDevices, useOrganizations, useSites } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { CircuitOut } from "@/api/types";

const FORM_VAZIO = {
  code: "",
  organization_id: "",
  site_id: "",
  access_device_id: "",
  access_port: "",
  edge_device_id: "",
  backup_edge_device_id: "",
  stack: "dual" as "ipv4" | "ipv6" | "dual",
  vlan_mode: "unica" as "unica" | "separada",
  qinq: false,
  vrf: "",
  mtu: "",
  bandwidth: "",
  bfd: false,
  p2p_v4_len: "31" as "30" | "31",
  description: "",
  notes: "",
  edge_trunk: "",
};

export default function Circuits() {
  const { podeEscrever } = useAuth();
  const { data, isLoading } = useCircuits();
  const { data: organizations } = useOrganizations();
  const { data: sites } = useSites();
  const { data: devices } = useDevices();
  const criar = useCircuitCriar();
  const atualizar = useCircuitAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<CircuitOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const num = (v: string) => (v === "" ? null : Number(v));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        code: form.code,
        organization_id: Number(form.organization_id),
        site_id: Number(form.site_id),
        access_device_id: Number(form.access_device_id),
        access_port: form.access_port,
        edge_device_id: Number(form.edge_device_id),
        backup_edge_device_id: form.backup_edge_device_id === "" ? null : Number(form.backup_edge_device_id),
        stack: form.stack,
        vlan_mode: form.vlan_mode,
        qinq: form.qinq,
        vrf: form.vrf || null,
        mtu: num(form.mtu),
        bandwidth: form.bandwidth || null,
        bfd: form.bfd,
        p2p_v4_len: Number(form.p2p_v4_len) as 30 | 31,
        description: form.description || null,
        notes: form.notes || null,
        edge_trunk: form.edge_trunk || null,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar circuito.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Circuitos" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Código *">
            <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </FormField>
          <FormField label="Organização *">
            <select value={form.organization_id} onChange={(e) => setForm({ ...form, organization_id: e.target.value })} required>
              <option value="">—</option>
              {(organizations ?? []).map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Site *">
            <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })} required>
              <option value="">—</option>
              {(sites ?? []).map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Equipamento de acesso *">
            <select value={form.access_device_id} onChange={(e) => setForm({ ...form, access_device_id: e.target.value })} required>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Porta de acesso *">
            <input value={form.access_port} onChange={(e) => setForm({ ...form, access_port: e.target.value })} required />
          </FormField>
          <FormField label="Edge *">
            <select value={form.edge_device_id} onChange={(e) => setForm({ ...form, edge_device_id: e.target.value })} required>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Edge de contingência">
            <select value={form.backup_edge_device_id} onChange={(e) => setForm({ ...form, backup_edge_device_id: e.target.value })}>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Stack">
            <select value={form.stack} onChange={(e) => setForm({ ...form, stack: e.target.value as "ipv4" | "ipv6" | "dual" })}>
              <option value="ipv4">ipv4</option>
              <option value="ipv6">ipv6</option>
              <option value="dual">dual</option>
            </select>
          </FormField>
          <FormField label="VLAN">
            <select value={form.vlan_mode} onChange={(e) => setForm({ ...form, vlan_mode: e.target.value as "unica" | "separada" })}>
              <option value="unica">única</option>
              <option value="separada">separada</option>
            </select>
          </FormField>
          <FormField label="QinQ">
            <input type="checkbox" checked={form.qinq} onChange={(e) => setForm({ ...form, qinq: e.target.checked })} />
          </FormField>
          <FormField label="VRF">
            <input value={form.vrf} onChange={(e) => setForm({ ...form, vrf: e.target.value })} />
          </FormField>
          <FormField label="MTU">
            <input type="number" value={form.mtu} onChange={(e) => setForm({ ...form, mtu: e.target.value })} />
          </FormField>
          <FormField label="Banda">
            <input value={form.bandwidth} onChange={(e) => setForm({ ...form, bandwidth: e.target.value })} />
          </FormField>
          <FormField label="BFD">
            <input type="checkbox" checked={form.bfd} onChange={(e) => setForm({ ...form, bfd: e.target.checked })} />
          </FormField>
          <FormField label="Len /30 ou /31">
            <select value={form.p2p_v4_len} onChange={(e) => setForm({ ...form, p2p_v4_len: e.target.value as "30" | "31" })}>
              <option value="31">/31</option>
              <option value="30">/30</option>
            </select>
          </FormField>
          <FormField label="Descrição">
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </FormField>
          <FormField label="Observações">
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </FormField>
          <FormField label="Eth-Trunk do edge">
            <input value={form.edge_trunk} onChange={(e) => setForm({ ...form, edge_trunk: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<CircuitOut>
        colunas={[
          { key: "code", title: "Código", render: (c) => <Link to={`/circuits/${c.id}`}>{c.code}</Link> },
          { key: "organization", title: "Organização", render: (c) => organizations?.find((o) => o.id === c.organization_id)?.name ?? "—" },
          { key: "site", title: "Site", render: (c) => sites?.find((s) => s.id === c.site_id)?.name ?? "—" },
          {
            key: "devices",
            title: "Access → Edge",
            render: (c) => `${devices?.find((d) => d.id === c.access_device_id)?.name ?? "—"} → ${devices?.find((d) => d.id === c.edge_device_id)?.name ?? "—"}`,
          },
          { key: "stack", title: "Stack", render: (c) => <StatusBadge estado={c.stack} /> },
          { key: "bfd", title: "BFD", render: (c) => (c.bfd ? "Sim" : "—") },
          { key: "admin_status", title: "Situação", render: (c) => <StatusBadge estado={c.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(c) =>
          podeEscrever && c.admin_status ? (
            <button type="button" onClick={() => setDesativando(c)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.code ?? ""}?`}
        mensagem="O circuito não recebe novas sessões; o registro permanece."
        onConfirmar={() => {
          if (desativando) void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
```

- [ ] **Step 3: `CircuitDetail.tsx`**

```tsx
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useBgpSessions, useCircuitDetail, useCircuitoReservar, useDevices, useOrganizations, useSites } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";

export default function CircuitDetail() {
  const { id } = useParams();
  const circuitId = Number(id);
  const { data, isLoading } = useCircuitDetail(circuitId);
  const { data: sessions } = useBgpSessions({ circuit_id: circuitId });
  const { data: devices } = useDevices();
  const { data: sites } = useSites();
  const { data: organizations } = useOrganizations();
  const reservar = useCircuitoReservar();
  const [erro, setErro] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) return <p role="alert">Circuito não encontrado.</p>;

  return (
    <main>
      <PageHeader
        titulo={`Circuito ${data.code}`}
        acoes={<Link to="/circuits">← Voltar</Link>}
      />
      <table>
        <tbody>
          <tr><th>Organização</th><td>{organizations?.find((o) => o.id === data.organization_id)?.name ?? "—"}</td></tr>
          <tr><th>Site</th><td>{sites?.find((s) => s.id === data.site_id)?.name ?? "—"}</td></tr>
          <tr><th>Access → Edge</th><td>{devices?.find((d) => d.id === data.access_device_id)?.name ?? "—"} → {devices?.find((d) => d.id === data.edge_device_id)?.name ?? "—"}</td></tr>
          <tr><th>Stack</th><td><StatusBadge estado={data.stack} /></td></tr>
          <tr><th>VLAN</th><td>{data.vlan_mode}</td></tr>
          <tr><th>MTU</th><td>{data.mtu ?? "—"}</td></tr>
          <tr><th>BFD</th><td>{data.bfd ? "Sim" : "—"}</td></tr>
          {(data.stack === "ipv4" || data.stack === "dual") && (
            <>
              <tr><th>Pontas IPv4</th><td>{data.ipv4_local ?? "—"} ↔ {data.ipv4_remote ?? "—"}</td></tr>
            </>
          )}
          {(data.stack === "ipv6" || data.stack === "dual") && (
            <tr><th>Pontas IPv6</th><td>{data.ipv6_local ?? "—"} ↔ {data.ipv6_remote ?? "—"}</td></tr>
          )}
          <tr><th>Descrição</th><td>{data.description ?? "—"}</td></tr>
        </tbody>
      </table>
      <button
        className="primary"
        type="button"
        disabled={reservar.isPending}
        onClick={() => {
          setErro(null);
          void reservar.mutateAsync(circuitId).catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reservar recursos."));
        }}
      >
        {reservar.isPending ? "Reservando…" : "Reservar recursos"}
      </button>
      {reservar.error && <p role="alert">{String(reservar.error.message ?? "Falha ao reservar recursos.")}</p>}
      {erro && <p role="alert">{erro}</p>}
      <h2>Sessões BGP</h2>
      {sessions && sessions.length === 0 && <p>Nenhuma sessão vinculada.</p>}
      {sessions?.map((s) => (
        <p key={s.id}>
          <Link to={`/bgp-sessions/${s.id}`}>{s.afi}</Link> {s.local_address} ↔ {s.remote_address}
        </p>
      ))}
    </main>
  );
}
```

- [ ] **Step 4: `BgpSessions.tsx`**

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useBgpSessionAtualizar,
  useBgpSessionCriar,
  useBgpSessions,
  useCircuits,
  useDevices,
  usePolicyProfiles,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { BgpSessionOut } from "@/api/types";

const FORM_VAZIO = {
  circuit_id: "",
  device_id: "",
  afi: "ipv4" as "ipv4" | "ipv6",
  local_address: "",
  remote_address: "",
  source_address: "",
  asn_local: "",
  asn_remote: "",
  description: "",
  import_profile_id: "",
  export_profile_id: "",
  maximum_prefix: "",
  maximum_prefix_threshold: "",
  local_preference: "",
  med: "",
  prepend: "",
  keepalive: "",
  holdtime: "",
  bfd_enabled: false,
  graceful_restart: false,
  shutdown: false,
  allow_default_route: false,
};

export default function BgpSessions() {
  const { podeEscrever } = useAuth();
  const { data, isLoading } = useBgpSessions();
  const { data: circuits } = useCircuits();
  const { data: devices } = useDevices();
  const { data: profiles } = usePolicyProfiles();
  const criar = useBgpSessionCriar();
  const atualizar = useBgpSessionAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<BgpSessionOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const num = (v: string) => (v === "" ? null : Number(v));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        circuit_id: Number(form.circuit_id),
        device_id: Number(form.device_id),
        afi: form.afi,
        local_address: form.local_address,
        remote_address: form.remote_address,
        source_address: form.source_address || null,
        asn_local: num(form.asn_local),
        asn_remote: num(form.asn_remote),
        description: form.description || null,
        import_profile_id: form.import_profile_id === "" ? null : Number(form.import_profile_id),
        export_profile_id: form.export_profile_id === "" ? null : Number(form.export_profile_id),
        maximum_prefix: num(form.maximum_prefix),
        maximum_prefix_threshold: num(form.maximum_prefix_threshold),
        local_preference: num(form.local_preference),
        med: num(form.med),
        prepend: num(form.prepend),
        keepalive: num(form.keepalive),
        holdtime: num(form.holdtime),
        bfd_enabled: form.bfd_enabled,
        graceful_restart: form.graceful_restart,
        shutdown: form.shutdown,
        allow_default_route: form.allow_default_route,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar sessão BGP.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Sessões BGP" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Circuito *">
            <select value={form.circuit_id} onChange={(e) => setForm({ ...form, circuit_id: e.target.value })} required>
              <option value="">—</option>
              {(circuits ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.code}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Equipamento *">
            <select value={form.device_id} onChange={(e) => setForm({ ...form, device_id: e.target.value })} required>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Família">
            <select value={form.afi} onChange={(e) => setForm({ ...form, afi: e.target.value as "ipv4" | "ipv6" })}>
              <option value="ipv4">ipv4</option>
              <option value="ipv6">ipv6</option>
            </select>
          </FormField>
          <FormField label="Endereço local *">
            <input value={form.local_address} onChange={(e) => setForm({ ...form, local_address: e.target.value })} required />
          </FormField>
          <FormField label="Endereço remoto *">
            <input value={form.remote_address} onChange={(e) => setForm({ ...form, remote_address: e.target.value })} required />
          </FormField>
          <FormField label="Source address">
            <input value={form.source_address} onChange={(e) => setForm({ ...form, source_address: e.target.value })} />
          </FormField>
          <FormField label="ASN local">
            <input type="number" value={form.asn_local} onChange={(e) => setForm({ ...form, asn_local: e.target.value })} />
          </FormField>
          <FormField label="ASN remoto">
            <input type="number" value={form.asn_remote} onChange={(e) => setForm({ ...form, asn_remote: e.target.value })} />
          </FormField>
          <FormField label="Descrição">
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </FormField>
          <FormField label="Perfil de importação">
            <select value={form.import_profile_id} onChange={(e) => setForm({ ...form, import_profile_id: e.target.value })}>
              <option value="">—</option>
              {(profiles ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Perfil de exportação">
            <select value={form.export_profile_id} onChange={(e) => setForm({ ...form, export_profile_id: e.target.value })}>
              <option value="">—</option>
              {(profiles ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Maximum-prefix">
            <input type="number" value={form.maximum_prefix} onChange={(e) => setForm({ ...form, maximum_prefix: e.target.value })} />
          </FormField>
          <FormField label="Limiar (%)">
            <input type="number" value={form.maximum_prefix_threshold} onChange={(e) => setForm({ ...form, maximum_prefix_threshold: e.target.value })} />
          </FormField>
          <FormField label="Local-preference">
            <input type="number" value={form.local_preference} onChange={(e) => setForm({ ...form, local_preference: e.target.value })} />
          </FormField>
          <FormField label="MED">
            <input type="number" value={form.med} onChange={(e) => setForm({ ...form, med: e.target.value })} />
          </FormField>
          <FormField label="Prepend">
            <input type="number" value={form.prepend} onChange={(e) => setForm({ ...form, prepend: e.target.value })} />
          </FormField>
          <FormField label="Keepalive">
            <input type="number" value={form.keepalive} onChange={(e) => setForm({ ...form, keepalive: e.target.value })} />
          </FormField>
          <FormField label="Holdtime">
            <input type="number" value={form.holdtime} onChange={(e) => setForm({ ...form, holdtime: e.target.value })} />
          </FormField>
          <FormField label="BFD">
            <input type="checkbox" checked={form.bfd_enabled} onChange={(e) => setForm({ ...form, bfd_enabled: e.target.checked })} />
          </FormField>
          <FormField label="Graceful restart">
            <input type="checkbox" checked={form.graceful_restart} onChange={(e) => setForm({ ...form, graceful_restart: e.target.checked })} />
          </FormField>
          <FormField label="Shutdown">
            <input type="checkbox" checked={form.shutdown} onChange={(e) => setForm({ ...form, shutdown: e.target.checked })} />
          </FormField>
          <FormField label="Default route">
            <input type="checkbox" checked={form.allow_default_route} onChange={(e) => setForm({ ...form, allow_default_route: e.target.checked })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<BgpSessionOut>
        colunas={[
          { key: "circuit", title: "Circuito", render: (s) => circuits?.find((c) => c.id === s.circuit_id)?.code ?? "—" },
          { key: "device", title: "Equipamento", render: (s) => devices?.find((d) => d.id === s.device_id)?.name ?? "—" },
          { key: "afi", title: "Família", render: (s) => <StatusBadge estado={s.afi} /> },
          { key: "addresses", title: "Endereços", render: (s) => `${s.local_address} ↔ ${s.remote_address}` },
          { key: "asns", title: "ASNs", render: (s) => `${s.asn_local ?? "—"} ↔ ${s.asn_remote ?? "—"}` },
          { key: "shutdown", title: "Situação", render: (s) => <StatusBadge estado={s.shutdown ? "inativo" : "ativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(s) => (
          <>
            <Link to={`/bgp-sessions/${s.id}`}>Detalhe</Link>{" "}
            {podeEscrever && s.admin_status && (
              <button type="button" onClick={() => setDesativando(s)}>
                Desativar
              </button>
            )}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar sessão ${desativando?.id ?? ""}?`}
        mensagem="A sessão fica indisponível para novas configurações; o registro permanece."
        onConfirmar={() => {
          if (desativando) void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
```

- [ ] **Step 5: `BgpSessionDetail.tsx`**

```tsx
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useBgpSession, useCommunities, useSessionCommunities, useSessionCommunity, useSessionSenha } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";

export default function BgpSessionDetail() {
  const { id } = useParams();
  const sessionId = Number(id);
  const { data, isLoading } = useBgpSession(sessionId);
  const { data: comunidades } = useSessionCommunities(sessionId);
  const { data: catalogo } = useCommunities();
  const assoc = useSessionCommunity();
  const senha = useSessionSenha();
  const [communityId, setCommunityId] = useState("");
  const [senhaNova, setSenhaNova] = useState("");
  const [erro, setErro] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) return <p role="alert">Sessão não encontrada.</p>;

  return (
    <main>
      <PageHeader titulo={`Sessão BGP #${data.id}`} />
      <table>
        <tbody>
          <tr><th>Família</th><td><StatusBadge estado={data.afi} /></td></tr>
          <tr><th>Endereços</th><td>{data.local_address} ↔ {data.remote_address}</td></tr>
          <tr><th>ASNs</th><td>{data.asn_local ?? "—"} ↔ {data.asn_remote ?? "—"}</td></tr>
          <tr><th>Maximum-prefix</th><td>{data.maximum_prefix ?? "—"} ({data.maximum_prefix_threshold ?? "—"}%)</td></tr>
          <tr><th>BFD</th><td>{data.bfd_enabled ? "Sim" : "—"}</td></tr>
          <tr><th>Descrição</th><td>{data.description ?? "—"}</td></tr>
          <tr><th>Shutdown</th><td>{data.shutdown ? "Sim" : "Não"}</td></tr>
        </tbody>
      </table>
      <h2>Communities</h2>
      {comunidades?.map((c) => (
        <p key={c.id}>
          {c.name}{" "}
          <button type="button" onClick={() => void assoc.mutate({ sessionId, communityId: c.id, associa: false })}>
            Remover
          </button>
        </p>
      ))}
      <form
        className="form-inline"
        onSubmit={(e) => {
          e.preventDefault();
          setErro(null);
          if (communityId === "") return;
          void assoc
            .mutateAsync({ sessionId, communityId: Number(communityId), associa: true })
            .then(() => setCommunityId(""))
            .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao associar community."));
        }}
      >
        <FormField label="Community">
          <select value={communityId} onChange={(e) => setCommunityId(e.target.value)}>
            <option value="">—</option>
            {(catalogo ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </FormField>
        <button className="primary" type="submit" disabled={assoc.isPending}>
          Associar
        </button>
      </form>
      {erro && <p role="alert">{erro}</p>}
      {assoc.error && <p role="alert">{String(assoc.error.message ?? "Falha ao associar community.")}</p>}
      <h2>Senha MD5</h2>
      <p>Situação: {data.has_password ? "Sim" : "Não"}</p>
      <form
        className="form-inline"
        onSubmit={(e) => {
          e.preventDefault();
          setErro(null);
          void senha.mutateAsync({ sessionId, password: senhaNova }).then(() => setSenhaNova("")).catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao definir senha."));
        }}
      >
        <FormField label="Senha MD5">
          <input
            type="password"
            value={senhaNova}
            onChange={(e) => setSenhaNova(e.target.value)}
            autoComplete="new-password"
            required
          />
        </FormField>
        <button className="primary" type="submit" disabled={senha.isPending}>
          Definir senha
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 6: testes `Circuits.test.tsx` e `BgpSessions.test.tsx`**

`web/src/pages/Circuits.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Circuits from "./Circuits";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
const org = { id: 1, name: "Cliente A", legal_name: null, kind: "downstream", asn: 64512, irr_as_set: null, notes: null, admin_status: true };
const site = { id: 1, name: "SPO", city: "São Paulo", uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true };
const dev1 = { id: 1, name: "sw-01", management_address: "10.9.0.1", site_id: 1, model: null, family: "S6730", role: "acesso", asn: null, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const dev2 = { id: 2, name: "ne-01", management_address: "10.9.0.2", site_id: 1, model: null, family: "NE8000", role: "edge", asn: 64600, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ id: 2, ...body, admin_status: true }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/organizations") return new Response(JSON.stringify([org]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sites") return new Response(JSON.stringify([site]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return new Response(JSON.stringify([dev1, dev2]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderCircuits() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/circuits"]}>
        <AuthProvider>
          <Routes>
            <Route path="/circuits" element={<Circuits />} />
            <Route path="/circuits/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Circuits", () => {
  it("lista circuitos e cria novo pela API", async () => {
    renderCircuits();
    expect(await screen.findByText("CIRC-01")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Código *"), "CIRC-02");
    await userEvent.selectOptions(screen.getByLabelText("Organização *"), "1");
    await userEvent.selectOptions(screen.getByLabelText("Site *"), "1");
    await userEvent.selectOptions(screen.getByLabelText("Equipamento de acesso *"), "1");
    await userEvent.type(screen.getByLabelText("Porta de acesso *"), "GE0/0/2");
    await userEvent.selectOptions(screen.getByLabelText("Edge *"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("CIRC-02"))).toBe(true);
    });
  });

  it("permite navegar para o detalhe pelo código", async () => {
    renderCircuits();
    await userEvent.click(await screen.findByRole("link", { name: "CIRC-01" }));
    expect(await screen.findByText("detail-page")).toBeInTheDocument();
  });
});
```

`web/src/pages/BgpSessions.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import BgpSessions from "./BgpSessions";
import BgpSessionDetail from "./BgpSessionDetail";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };
const dev = { id: 2, name: "ne-01", management_address: "10.9.0.2", site_id: 1, model: null, family: "NE8000", role: "edge", asn: 64600, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const catalogo = [{ id: 1, name: "blackhole", notes: null }];
let sessao: Record<string, unknown>;
let associadas: { id: number; name: string; notes: null }[];
let hasPassword: boolean;

function opcoes() {
  return {
    status: 200,
    headers: { "Content-Type": "application/json" },
  };
}

beforeAll(() => {
  sessao = {
    id: 1, circuit_id: 1, device_id: 2, afi: "ipv4", local_address: "100.64.40.1", remote_address: "100.64.40.2",
    source_address: null, asn_local: 64600, asn_remote: 64512, description: null, import_profile_id: null,
    export_profile_id: null, maximum_prefix: 100, maximum_prefix_threshold: 80, local_preference: 100,
    med: null, prepend: null, keepalive: 30, holdtime: 90, bfd_enabled: true, graceful_restart: false,
    shutdown: false, allow_default_route: false, has_password: false, admin_status: true,
  };
  associadas = [];
  hasPassword = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && url === "/api/v1/bgp-sessions/1/communities") {
        const body = JSON.parse(String(init?.body));
        const com = catalogo.find((c) => c.id === body.community_id);
        if (com) associadas.push({ ...com });
        return new Response(JSON.stringify({ session_id: 1, community_id: body.community_id }), opcoes());
      }
      if (method === "DELETE" && url === "/api/v1/bgp-sessions/1/communities/1") {
        associadas = [];
        return new Response(null, { status: 204 });
      }
      if (method === "POST" && url === "/api/v1/bgp-sessions/1/password") {
        hasPassword = true;
        return new Response(JSON.stringify({ ...sessao, has_password: true }), opcoes());
      }
      if (method === "POST" && url === "/api/v1/bgp-sessions") {
        const body = JSON.parse(String(init?.body));
        return new Response(JSON.stringify({ id: 2, ...body, has_password: false, admin_status: true }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/bgp-sessions/1/communities") return new Response(JSON.stringify(associadas), opcoes());
      if (url === "/api/v1/bgp-sessions/1" && method === "GET") return new Response(JSON.stringify({ ...sessao, has_password: hasPassword }), opcoes());
      if (url === "/api/v1/bgp-sessions") return new Response(JSON.stringify([{ ...sessao, has_password: hasPassword }]), opcoes());
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), opcoes());
      if (url === "/api/v1/devices") return new Response(JSON.stringify([dev]), opcoes());
      if (url === "/api/v1/policy-profiles") return new Response(JSON.stringify([]), opcoes());
      if (url === "/api/v1/communities") return new Response(JSON.stringify(catalogo), opcoes());
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), opcoes());
      return new Response("null", { status: 404 });
    }),
  );
});

function renderList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/bgp-sessions"]}>
        <AuthProvider>
          <Routes>
            <Route path="/bgp-sessions" element={<BgpSessions />} />
            <Route path="/bgp-sessions/:id" element={<BgpSessionDetail />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/bgp-sessions/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/bgp-sessions/:id" element={<BgpSessionDetail />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BgpSessions", () => {
  it("lista sessões e cria nova pela API", async () => {
    renderList();
    expect(await screen.findByText("100.64.40.1 ↔ 100.64.40.2")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Circuito *"), "1");
    await userEvent.selectOptions(screen.getByLabelText("Equipamento *"), "2");
    await userEvent.type(screen.getByLabelText("Endereço local *"), "100.64.42.1");
    await userEvent.type(screen.getByLabelText("Endereço remoto *"), "100.64.42.2");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("100.64.42.1"))).toBe(true);
    });
  });

  it("detalhe associa e remove community", async () => {
    renderDetail();
    await screen.findByText(/Sessão BGP #1/);
    await userEvent.selectOptions(screen.getByLabelText("Community"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Associar" }));
    // "blackhole" aparece também no <option> do catálogo — assertar pelo botão da linha (sem colisão)
    expect(await screen.findByRole("button", { name: "Remover" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remover" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remover" })).not.toBeInTheDocument());
  });

  it("define senha MD5 e mostra que há senha", async () => {
    renderDetail();
    await screen.findByText(/Sessão BGP #1/);
    await userEvent.type(screen.getByLabelText("Senha MD5"), "segredo");
    await userEvent.click(screen.getByRole("button", { name: "Definir senha" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/bgp-sessions/1/password" && c[1]?.method === "POST")).toBe(true);
    });
  });
});
```

Run (na raiz do repositório):

```bash
cd web && npx vitest run src/pages/Circuits.test.tsx src/pages/BgpSessions.test.tsx
cd web && npm run build
cd web && npx eslint src
```

Expected: 5 testes PASS, build sem erro, lint limpo.

- [ ] **Step 7: rotas em `App.tsx`** — adicionar, junto às existentes:

```tsx
import CircuitDetail from "@/pages/CircuitDetail";
import Circuits from "@/pages/Circuits";
import BgpSessionDetail from "@/pages/BgpSessionDetail";
import BgpSessions from "@/pages/BgpSessions";
```

```tsx
<Route
  path="/circuits"
  element={
    <RequireAuth>
      <Circuits />
    </RequireAuth>
  }
/>
<Route
  path="/circuits/:id"
  element={
    <RequireAuth>
      <CircuitDetail />
    </RequireAuth>
  }
/>
<Route
  path="/bgp-sessions"
  element={
    <RequireAuth>
      <BgpSessions />
    </RequireAuth>
  }
/>
<Route
  path="/bgp-sessions/:id"
  element={
    <RequireAuth>
      <BgpSessionDetail />
    </RequireAuth>
  }
/>
```

- [ ] **Step 8: commit** (backend e web em commits separados)

```bash
git add src/gerenet/domain/services/bgp_sessions.py src/gerenet/api/routers/bgp_sessions.py tests/api/test_communities_api.py tests/api/conftest.py
git commit -m "feat(api): GET /bgp-sessions/{id}/communities para leitura das associacoes

O mesclado carrega também a infra autouse spa_sem_build: sem ela o gate
backend depende do web/dist existir na máquina (catch-all → 404 no lugar
do 405 natural), quebrando test_lista_communities_read_only do C1.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

```bash
git add web/src/pages web/src/App.tsx web/src/api/hooks.ts
git commit -m "feat(web): telas de circuitos e sessoes BGP com reserve, communities e vault

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: Telas de leitura — policy-profiles, communities, prefix-authorizations (CRUD), audit-events

**Files:**
- Create: `web/src/pages/PolicyProfiles.tsx`, `Communities.tsx`, `PrefixAuthorizations.tsx`, `AuditEvents.tsx`
- Modify: `web/src/App.tsx`, `web/src/api/hooks.ts`

**Interfaces:** Predecessores: Task 7 (padrão) e Task 8 (`usePolicyProfiles`/`useCommunities` já existem — NÃO duplicar). Prefix-auth tem POST/PATCH `{"admin_status": false}` (Literal False — sem reativação pela API; desativar + criar para mudar, ruling 2 do backend); policy/communities/audit são GET-only. Filtro de audit-events: `tipo`, `objeto`, `objeto_id` (não existe filtro por ator — o ator é coluna própria).

- [ ] **Step 1: hooks no `hooks.ts`** (append; os de lista de policy/communities vieram da Task 8)

```ts
export const usePrefixAuthorizations = (filtros?: { organization_id?: number; family?: string; include_disabled?: boolean }) =>
  useQuery({
    queryKey: ["prefix-authorizations", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.organization_id) qs.set("organization_id", String(filtros.organization_id));
      if (filtros?.family) qs.set("family", filtros.family);
      if (filtros?.include_disabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<PrefixAuthorizationOut[]>(`/api/v1/prefix-authorizations${suf}`);
    },
  });
export type PrefixAuthorizationCreateIn = {
  organization_id: number;
  family: "ipv4" | "ipv6";
  prefix: string;
  notes?: string | null;
};
export const usePrefixAuthorizationCriar = () =>
  useCriar<PrefixAuthorizationCreateIn, PrefixAuthorizationOut>("prefix-authorizations", "/api/v1/prefix-authorizations");
export const usePrefixAuthorizationDesativar = () =>
  useAtualizar<{ admin_status?: boolean }, PrefixAuthorizationOut>("prefix-authorizations", "/api/v1/prefix-authorizations");

export const useAuditEvents = (filtros?: { tipo?: string; objeto?: string; objeto_id?: number }) =>
  useQuery({
    queryKey: ["audit-events", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.tipo) qs.set("tipo", filtros.tipo);
      if (filtros?.objeto) qs.set("objeto", filtros.objeto);
      if (filtros?.objeto_id) qs.set("objeto_id", String(filtros.objeto_id));
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<AuditEventOut[]>(`/api/v1/audit-events${suf}`);
    },
  });
```

- [ ] **Step 2: `PolicyProfiles.tsx`** — read-only, com filtro de direção:

```tsx
import { useState } from "react";
import { usePolicyProfiles } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { MonoCode } from "@/components/MonoCode";
import type { PolicyProfileOut } from "@/api/types";

export default function PolicyProfiles() {
  const [direcao, setDirecao] = useState("");
  const { data, isLoading } = usePolicyProfiles(direcao ? { direction: direcao } : {});
  return (
    <main>
      <PageHeader
        titulo="Perfis de política"
        acoes={
          <select value={direcao} onChange={(e) => setDirecao(e.target.value)} aria-label="Direção">
            <option value="">todas</option>
            <option value="import">import</option>
            <option value="export">export</option>
          </select>
        }
      />
      <DataTable<PolicyProfileOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "label", title: "Produto" },
          { key: "direction", title: "Direção", render: (p) => <StatusBadge estado={p.direction} /> },
          { key: "kind", title: "Tipo" },
          { key: "prefixes", title: "Prefixos", render: (p) => (p.prefixes && p.prefixes.length > 0 ? <MonoCode texto={p.prefixes.join("\n")} /> : "—") },
          { key: "notes", title: "Observações", render: (p) => p.notes ?? "—" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
      />
    </main>
  );
}
```

- [ ] **Step 3: `Communities.tsx`** — read-only, com janela de detalhe (name, notes):

```tsx
import { useState } from "react";
import { useCommunities } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import type { CommunityOut } from "@/api/types";

export default function Communities() {
  const { data, isLoading } = useCommunities();
  const [detalhe, setDetalhe] = useState<CommunityOut | null>(null);
  return (
    <main>
      <PageHeader titulo="Communities" />
      <DataTable<CommunityOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "notes", title: "Observações", render: (c) => c.notes ?? "—" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(c) => (
          <button type="button" onClick={() => setDetalhe(c)}>
            Detalhar
          </button>
        )}
      />
      {detalhe && (
        <div role="dialog" aria-modal="true" aria-label={`Dados de ${detalhe.name}`}>
          <h2>{detalhe.name}</h2>
          <p>{detalhe.notes ?? "Sem observações."}</p>
          <button onClick={() => setDetalhe(null)}>Fechar</button>
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 4: `PrefixAuthorizations.tsx`** — form + desativar (origin exibido, só leitura):

```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useOrganizations,
  usePrefixAuthorizationCriar,
  usePrefixAuthorizationDesativar,
  usePrefixAuthorizations,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { PrefixAuthorizationOut } from "@/api/types";

const FORM_VAZIO = { organization_id: "", family: "ipv4" as "ipv4" | "ipv6", prefix: "", notes: "" };

export default function PrefixAuthorizations() {
  const { podeEscrever } = useAuth();
  const { data, isLoading } = usePrefixAuthorizations();
  const { data: organizations } = useOrganizations();
  const criar = usePrefixAuthorizationCriar();
  const desativar = usePrefixAuthorizationDesativar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<PrefixAuthorizationOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        organization_id: Number(form.organization_id),
        family: form.family,
        prefix: form.prefix,
        notes: form.notes || null,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar autorização.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Prefixos autorizados" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Organização *">
            <select value={form.organization_id} onChange={(e) => setForm({ ...form, organization_id: e.target.value })} required>
              <option value="">—</option>
              {(organizations ?? []).map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Família">
            <select value={form.family} onChange={(e) => setForm({ ...form, family: e.target.value as "ipv4" | "ipv6" })}>
              <option value="ipv4">ipv4</option>
              <option value="ipv6">ipv6</option>
            </select>
          </FormField>
          <FormField label="Prefixo *">
            <input value={form.prefix} onChange={(e) => setForm({ ...form, prefix: e.target.value })} required />
          </FormField>
          <FormField label="Observações">
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<PrefixAuthorizationOut>
        colunas={[
          { key: "organization", title: "Organização", render: (z) => organizations?.find((o) => o.id === z.organization_id)?.name ?? "—" },
          { key: "family", title: "Família" },
          { key: "prefix", title: "Prefixo" },
          { key: "origin", title: "Origem" },
          { key: "notes", title: "Observações", render: (z) => z.notes ?? "—" },
          { key: "admin_status", title: "Situação", render: (z) => (z.admin_status ? "ativo" : "inativo") },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(z) =>
          podeEscrever && z.admin_status ? (
            <button type="button" onClick={() => setDesativando(z)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.prefix ?? ""}?`}
        mensagem="Para alterar um prefixo autorizado, desative e cadastre um novo."
        onConfirmar={() => {
          if (desativando) void desativar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={desativar.isPending}
      />
    </main>
  );
}
```

- [ ] **Step 5: `AuditEvents.tsx`** — filtros tipo/objeto, `details` expansível:

```tsx
import { useState } from "react";
import { useAuditEvents } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import type { AuditEventOut } from "@/api/types";

export default function AuditEvents() {
  const [tipo, setTipo] = useState("");
  const [objeto, setObjeto] = useState("");
  const { data, isLoading } = useAuditEvents({
    ...(tipo ? { tipo } : {}),
    ...(objeto ? { objeto } : {}),
  });
  return (
    <main>
      <PageHeader titulo="Auditoria" />
      <form className="form-inline">
        <label className="field">
          <span>Tipo</span>
          <input value={tipo} onChange={(e) => setTipo(e.target.value)} />
        </label>
        <label className="field">
          <span>Objeto</span>
          <input value={objeto} onChange={(e) => setObjeto(e.target.value)} />
        </label>
      </form>
      <DataTable<AuditEventOut>
        colunas={[
          { key: "created_at", title: "Quando", render: (e) => <TimeAgo iso={e.created_at} /> },
          { key: "type", title: "Ação" },
          { key: "actor", title: "Autor" },
          {
            key: "details",
            title: "Detalhes",
            render: (e) => (
              <details>
                <summary>Exibir</summary>
                <pre>{JSON.stringify(e.details, null, 2)}</pre>
              </details>
            ),
          },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
      />
    </main>
  );
}
```

- [ ] **Step 6: testes + rotas + build + lint**

`web/src/pages/PrefixAuthorizations.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, describe, expect, it, vi } from "vitest";
import PrefixAuthorizations from "./PrefixAuthorizations";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
const org = { id: 1, name: "Cliente A", legal_name: null, kind: "downstream", asn: 64512, irr_as_set: null, notes: null, admin_status: true };
const autorizacao = { id: 1, organization_id: 1, family: "ipv4", prefix: "200.200.1.0/24", origin: "manual", notes: null, admin_status: true };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (init?.method === "POST") return json({ id: 2, ...JSON.parse(String(init.body)), origin: "manual", admin_status: true }, 201);
      if (url === "/api/v1/prefix-authorizations/1" && init?.method === "PATCH") return json({ ...autorizacao, admin_status: false });
      if (url === "/api/v1/prefix-authorizations") return json([autorizacao]);
      if (url === "/api/v1/organizations") return json([org]);
      if (url === "/api/v1/auth/me") return json(ME);
      return new Response("null", { status: 404 });
    }),
  );
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <PrefixAuthorizations />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("PrefixAuthorizations", () => {
  it("lista e cadastra autorização pela API", async () => {
    renderPage();
    expect(await screen.findByText("200.200.1.0/24")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Organização *"), "1");
    await userEvent.type(screen.getByLabelText("Prefixo *"), "200.200.2.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("200.200.2.0/24"))).toBe(true);
    });
  });

  it("desativa com confirmação", async () => {
    renderPage();
    await screen.findByText("200.200.1.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find((c) => c[0] === "/api/v1/prefix-authorizations/1" && c[1]?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(String(patch![1].body))).toEqual({ admin_status: false });
    });
  });
});
```

`web/src/pages/AuditEvents.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, describe, expect, it, vi } from "vitest";
import AuditEvents from "./AuditEvents";

const EVENTOS = [
  { id: 1, type: "device.create", actor: "cli", details: { objeto: "device", objeto_id: 1 }, created_at: "2026-09-04T12:00:00Z" },
];

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      return new Response(JSON.stringify(EVENTOS), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuditEvents />
    </QueryClientProvider>,
  );
}

describe("AuditEvents", () => {
  it("lista eventos e filtra por tipo", async () => {
    renderPage();
    expect(await screen.findByText("device.create")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Tipo"), "device.");
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => String(c[0]).includes("tipo=device."))).toBe(true);
    });
  });

  it("expande os detalhes do evento", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Exibir"));
    expect(screen.getByText(/"objeto": "device"/)).toBeTruthy();
  });
});
```

Run: `cd web && npx vitest run src/pages/PrefixAuthorizations.test.tsx src/pages/AuditEvents.test.tsx` — Expected: 4 PASS.

Rotas em `App.tsx` (adicionar às existentes):

```tsx
<Route path="/policy-profiles" element={<RequireAuth><PolicyProfiles /></RequireAuth>} />
<Route path="/communities" element={<RequireAuth><Communities /></RequireAuth>} />
<Route path="/prefix-authorizations" element={<RequireAuth><PrefixAuthorizations /></RequireAuth>} />
<Route path="/audit-events" element={<RequireAuth><AuditEvents /></RequireAuth>} />
```

Run: `cd web && npm run build` e `cd web && npx eslint src` — Expected: sem erros.

- [ ] **Step 7: commit**

```bash
git add web/src/pages web/src/App.tsx web/src/api/hooks.ts
git commit -m "feat(web): paginas de catalogo (policy/communities), prefix-authorizations e auditoria

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: Telas especializadas — snapshots, desired-config, reconcile, jobs

**Files:**
- Create: `web/src/pages/Snapshots.tsx`, `DesiredConfig.tsx`, `Reconcile.tsx`, `Jobs.tsx`, `JobDetail.tsx`
- Modify: `web/src/App.tsx`, `web/src/api/hooks.ts`
- Create: `web/src/pages/Reconcile.test.tsx`, `Snapshots.test.tsx`

**Interfaces:**
- Consumes: hooks (Tasks 6–9). Específicos desta task: `useDevices` (Task 7), `useJobPoll` (Task 6), e os hooks definidos no Step 1 (`useSnapshots`, `useSnapshot`, `useDesiredConfig`, `useReconcile`, `useJobs`). Contratos de backend verificados: `GET /devices/{id}/snapshots` (lista, `limit` máx. 100), `GET /snapshots/{id}`, `GET /devices/{id}/desired-config`, `GET /reconciliation?device_id|snapshot_id` (exatamente um; 400 "Informe exatamente um de device_id ou snapshot_id."), `GET /jobs?device_id|status|kind|limit|offset` e `GET /jobs/{id}`.
- Produces: as 4 telas de inspeção técnica (snapshot JSON com colapso por chave top-level; desired-config em acordeão por bloco + MonoCode com botão copiar; reconcile com filtro por severidade e aviso de snapshot ausente; jobs com filtros + detalhe com timing e link ao reconcile do snapshot).
- Rotas novas: `/snapshots`, `/desired-config`, `/reconcile`, `/jobs`, `/jobs/:id`. A T6 já linkava `/reconcile?device_id=` (Dashboard) e a T10/`JobDetail` linka `/reconcile?snapshot_id=` — a tela Reconcile lê os dois params.

> **Correções de defeito do rascunho (ruling da orquestração):**
> (a) `useSnapshot` com key `["snapshots", id]` colidiria com a key da lista `["snapshots", deviceId]` (ids de snapshot e de device são ambos `int` pequenos — uma colisão serviria a lista no lugar do detalhe); a key do detalhe é `["snapshot", id]`.
> (b) `useSnapshots(deviceId)` sem `enabled` dispararia `GET /devices/0/snapshots` quando o componente monta sem device; recebeu `enabled: deviceId > 0`.
> (c) `Object.entries` inclui chaves com valor `undefined` — `new URLSearchParams([["snapshot_id", "undefined"]])` mandaria `snapshot_id=undefined` ao backend (422). Os dois novos hooks filtram `undefined` antes de montar a query string.

- [ ] **Step 1: hooks** (append no `web/src/api/hooks.ts`; adicionar `DesiredConfigOut`, `ReconcileOut` e `SnapshotOut` ao bloco de import de tipos ordenado existente — não substituir; ele já lista outros tipos em uso)

```ts
export function useSnapshots(deviceId: number) {
  return useQuery({
    queryKey: ["snapshots", deviceId],
    queryFn: () => apiFetch<SnapshotOut[]>(`/api/v1/devices/${deviceId}/snapshots`),
    enabled: deviceId > 0,
  });
}
export function useSnapshot(id: number) {
  return useQuery({
    queryKey: ["snapshot", id], // distinta de ["snapshots", deviceId] (ver correção a)
    queryFn: () => apiFetch<SnapshotOut>(`/api/v1/snapshots/${id}`),
    enabled: id > 0,
  });
}
export function useDesiredConfig(deviceId: number | null) {
  return useQuery({
    queryKey: ["desired", deviceId],
    queryFn: () => apiFetch<DesiredConfigOut>(`/api/v1/devices/${deviceId}/desired-config`),
    enabled: Boolean(deviceId),
    retry: false,
  });
}
export function useReconcile(filtro: { device_id?: number; snapshot_id?: number }) {
  return useQuery({
    queryKey: ["reconcile", filtro],
    queryFn: () =>
      apiFetch<ReconcileOut>(
        `/api/v1/reconciliation?${new URLSearchParams(
          Object.entries(filtro)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)] as [string, string]),
        ).toString()}`,
      ),
    enabled: Number(filtro.device_id ?? filtro.snapshot_id) > 0,
    retry: false,
  });
}
export function useJobs(filtros: {
  device_id?: number;
  status?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["jobs", filtros],
    queryFn: () =>
      apiFetch<JobRunOut[]>(
        `/api/v1/jobs?${new URLSearchParams(
          Object.entries(filtros)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)] as [string, string]),
        ).toString()}`,
      ),
  });
}
```

- [ ] **Step 2: `Snapshots.tsx`**

```tsx
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useDevices, useSnapshot, useSnapshots } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import type { SnapshotOut } from "@/api/types";

const LIMITE_ARRAY = 60;

function JsonValor({ valor }: { valor: unknown }) {
  if (valor === null || typeof valor !== "object") return <>{String(valor)}</>;
  if (Array.isArray(valor)) return <JsonArray itens={valor} />;
  return (
    <ul>
      {Object.entries(valor as Record<string, unknown>).map(([k, v]) => (
        <li key={k}>
          {k}: <JsonValor valor={v} />
        </li>
      ))}
    </ul>
  );
}

function JsonArray({ itens }: { itens: unknown[] }) {
  const [corte, setCorte] = useState(LIMITE_ARRAY);
  const visiveis = itens.slice(0, corte);
  const restante = itens.length - visiveis.length;
  return (
    <>
      <ol>
        {visiveis.map((item, i) => (
          <li key={i}>
            <JsonValor valor={item} />
          </li>
        ))}
      </ol>
      {restante > 0 && (
        <button type="button" onClick={() => setCorte((c) => c + LIMITE_ARRAY)}>
          Mostrar mais ({restante})
        </button>
      )}
    </>
  );
}

function JsonTree({ recursos }: { recursos: Record<string, unknown> }) {
  return (
    <ul>
      {Object.entries(recursos).map(([chave, valor]) => (
        <li key={chave}>
          <details>
            <summary>{chave}</summary>
            <JsonValor valor={valor} />
          </details>
        </li>
      ))}
    </ul>
  );
}

export default function Snapshots() {
  const [params, setParams] = useSearchParams();
  const { data: devices, isLoading: carregandoDevices } = useDevices();
  const [deviceId, setDeviceId] = useState<number>(Number(params.get("device_id") ?? 0));
  const { data: snapshots, isLoading } = useSnapshots(deviceId);
  const [selecionado, setSelecionado] = useState<number | null>(null);
  const detalhe = useSnapshot(selecionado ?? 0);

  return (
    <main>
      <PageHeader titulo="Snapshots" />
      <FormField label="Equipamento">
        <select
          value={deviceId}
          onChange={(e) => {
            const v = Number(e.target.value);
            setDeviceId(v);
            setSelecionado(null);
            setParams(v > 0 ? { device_id: String(v) } : {});
          }}
        >
          <option value={0}>Selecione…</option>
          {(devices ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </FormField>
      {deviceId === 0 && <p>Selecione um equipamento.</p>}
      {deviceId > 0 && (
        <DataTable<SnapshotOut>
          colunas={[
            { key: "id", title: "Snapshot" },
            { key: "started_at", title: "Início", render: (s) => <TimeAgo iso={s.started_at} /> },
            { key: "status", title: "Status", render: (s) => <StatusBadge estado={s.status} /> },
            { key: "duration_ms", title: "Duração (ms)" },
          ]}
          linhas={snapshots ?? []}
          carregando={carregandoDevices || isLoading}
          vazio="Nenhum snapshot deste equipamento."
          acoes={(s) => (
            <button type="button" onClick={() => setSelecionado(s.id)}>
              Ver
            </button>
          )}
        />
      )}
      {detalhe.data && (
        <section>
          <h2>
            Snapshot #{detalhe.data.id} ({detalhe.data.status})
          </h2>
          <p>
            Início: <TimeAgo iso={detalhe.data.started_at} /> · duração: {detalhe.data.duration_ms} ms
          </p>
          <h3>resources</h3>
          <JsonTree recursos={detalhe.data.resources} />
          {Object.keys(detalhe.data.errors).length > 0 && (
            <>
              <h3>errors</h3>
              <JsonTree recursos={detalhe.data.errors} />
            </>
          )}
        </section>
      )}
      {detalhe.isError && <p role="alert">Falha ao carregar o snapshot.</p>}
    </main>
  );
}
```

- [ ] **Step 3: `DesiredConfig.tsx`**

```tsx
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useDesiredConfig, useDevices } from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { MonoCode } from "@/components/MonoCode";
import { PageHeader } from "@/components/PageHeader";

export default function DesiredConfig() {
  const [params, setParams] = useSearchParams();
  const { data: devices } = useDevices();
  const [deviceId, setDeviceId] = useState<number>(Number(params.get("device_id") ?? 0));
  const { data, isLoading } = useDesiredConfig(deviceId > 0 ? deviceId : null);

  return (
    <main>
      <PageHeader titulo="Configuração desejada" />
      <FormField label="Equipamento">
        <select
          value={deviceId}
          onChange={(e) => {
            const v = Number(e.target.value);
            setDeviceId(v);
            setParams(v > 0 ? { device_id: String(v) } : {});
          }}
        >
          <option value={0}>Selecione…</option>
          {(devices ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </FormField>
      {deviceId === 0 && <p>Selecione um equipamento.</p>}
      {isLoading && <p aria-busy="true">Carregando…</p>}
      {data && (
        <>
          <p>Gerada em {new Date(data.gerado_em).toLocaleString("pt-BR")}</p>
          <MonoCode texto={data.texto} />
          <h2>Blocos</h2>
          {data.blocos.length === 0 && <p>Nenhum bloco renderizado.</p>}
          {data.blocos.map((b) => (
            <details key={`${b.tipo}-${b.objeto}-${b.objeto_id}`}>
              <summary>
                {b.tipo} · {b.objeto} #{b.objeto_id}
              </summary>
              <pre>{b.comandos.join("\n")}</pre>
            </details>
          ))}
        </>
      )}
    </main>
  );
}
```

- [ ] **Step 4: `Reconcile.tsx`** (lê `device_id`/`snapshot_id` da URL — a T6 já linka `/reconcile?device_id=` e o JobDetail linka `/reconcile?snapshot_id=`; os dois modos são mutuamente exclusivos, gerando sempre exatamente um filtro)

```tsx
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useDevices, useReconcile } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import type { ReconcileItemOut } from "@/api/types";

const SEVERIDADES = ["todas", "critica", "atencao", "aviso"] as const;

export default function Reconcile() {
  const [params, setParams] = useSearchParams();
  const { data: devices } = useDevices();
  const deviceParam = Number(params.get("device_id") ?? 0);
  const snapshotParam = Number(params.get("snapshot_id") ?? 0);
  const [modo, setModo] = useState<"device" | "snapshot">(snapshotParam > 0 ? "snapshot" : "device");
  const [deviceSel, setDeviceSel] = useState<number>(deviceParam);
  const [snapInput, setSnapInput] = useState<string>(snapshotParam > 0 ? String(snapshotParam) : "");
  const [severidade, setSeveridade] = useState<string>("todas");

  const filtro =
    modo === "device"
      ? { device_id: deviceSel > 0 ? deviceSel : undefined, snapshot_id: undefined }
      : { device_id: undefined, snapshot_id: Number(snapInput) > 0 ? Number(snapInput) : undefined };
  const { data, isLoading, error } = useReconcile(filtro);
  const items = (data?.items ?? []).filter((i) => severidade === "todas" || i.severidade === severidade);

  return (
    <main>
      <PageHeader titulo="Reconciliação" />
      <FormField label="Modo">
        <select value={modo} onChange={(e) => setModo(e.target.value as "device" | "snapshot")}>
          <option value="device">Equipamento</option>
          <option value="snapshot">Snapshot</option>
        </select>
      </FormField>
      {modo === "device" && (
        <FormField label="Equipamento">
          <select
            value={deviceSel}
            onChange={(e) => {
              const v = Number(e.target.value);
              setDeviceSel(v);
              setParams(v > 0 ? { device_id: String(v) } : {});
            }}
          >
            <option value={0}>Selecione…</option>
            {(devices ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </FormField>
      )}
      {modo === "snapshot" && (
        <FormField label="Snapshot (id)">
          <input type="number" min={1} value={snapInput} onChange={(e) => setSnapInput(e.target.value)} />
        </FormField>
      )}
      <FormField label="Severidade">
        <select value={severidade} onChange={(e) => setSeveridade(e.target.value)}>
          {SEVERIDADES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </FormField>
      {data?.aviso && <p role="status">{data.aviso}</p>}
      {error && <p role="alert">{error instanceof ApiError ? error.message : "Falha ao reconciliar."}</p>}
      {(modo === "device" ? deviceSel === 0 : snapInput === "") && (
        <p>Selecione um equipamento ou informe um snapshot.</p>
      )}
      <DataTable<ReconcileItemOut>
        colunas={[
          { key: "tipo", title: "Tipo" },
          { key: "severidade", title: "Severidade", render: (i) => <SeverityBadge severidade={i.severidade} /> },
          { key: "esperado", title: "Esperado" },
          { key: "encontrado", title: "Encontrado" },
          { key: "acao", title: "Ação recomendada" },
        ]}
        linhas={items}
        carregando={isLoading}
        vazio="Nenhuma divergência encontrada."
      />
    </main>
  );
}
```

- [ ] **Step 5: `Jobs.tsx` + `JobDetail.tsx`**

`Jobs.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { useDevices, useJobs } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import type { JobRunOut } from "@/api/types";

const STATUS = ["queued", "running", "success", "partial", "error"] as const;

export default function Jobs() {
  const { data: devices } = useDevices();
  const [deviceId, setDeviceId] = useState(0);
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [limite, setLimite] = useState(100);
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useJobs({
    device_id: deviceId > 0 ? deviceId : undefined,
    status: status || undefined,
    kind: kind || undefined,
    limit: limite,
    offset,
  });

  return (
    <main>
      <PageHeader titulo="Jobs" />
      <div className="form-inline">
        <FormField label="Equipamento">
          <select
            value={deviceId}
            onChange={(e) => {
              setDeviceId(Number(e.target.value));
              setOffset(0);
            }}
          >
            <option value={0}>Todos</option>
            {(devices ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Status">
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Todos</option>
            {STATUS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Tipo">
          <input value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }} />
        </FormField>
        <FormField label="Limite">
          <select
            value={limite}
            onChange={(e) => {
              setLimite(Number(e.target.value));
              setOffset(0);
            }}
          >
            {[10, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </FormField>
      </div>
      <DataTable<JobRunOut>
        colunas={[
          {
            key: "id",
            title: "Job",
            render: (j) => <Link to={`/jobs/${j.id}`}>#{j.id}</Link>,
          },
          { key: "device_id", title: "Device", render: (j) => j.device_id ?? "—" },
          { key: "kind", title: "Tipo" },
          { key: "actor", title: "Autor" },
          { key: "status", title: "Status", render: (j) => <StatusBadge estado={j.status} /> },
          { key: "started_at", title: "Início", render: (j) => <TimeAgo iso={j.started_at} /> },
          { key: "duration_ms", title: "Duração (ms)" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        vazio="Nenhum job."
      />
      <p>
        <button type="button" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - limite))}>
          Anterior
        </button>{" "}
        <button type="button" onClick={() => setOffset((o) => o + limite)}>
          Próximo
        </button>
      </p>
    </main>
  );
}
```

`JobDetail.tsx`:

```tsx
import { Link, useParams } from "react-router-dom";
import { useJobPoll } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";

export default function JobDetail() {
  const { id } = useParams();
  const jobId = Number(id);
  const { data, isLoading } = useJobPoll(jobId);

  return (
    <main>
      <PageHeader titulo={`Job #${data ? data.id : (id ?? "")}`} acoes={<Link to="/jobs">← Voltar</Link>} />
      {isLoading && <p aria-busy="true">Carregando…</p>}
      {!data && !isLoading && <p>Job não encontrado.</p>}
      {data && (
        <>
          <dl>
            <dt>Equipamento</dt>
            <dd>{data.device_id ?? "—"}</dd>
            <dt>Origem</dt>
            <dd>{data.origin}</dd>
            <dt>Autor</dt>
            <dd>{data.actor}</dd>
            <dt>Tipo</dt>
            <dd>{data.kind}</dd>
            <dt>Status</dt>
            <dd><StatusBadge estado={data.status} /></dd>
            <dt>Início</dt>
            <dd><TimeAgo iso={data.started_at} /></dd>
            <dt>Fim</dt>
            <dd>{data.finished_at ? <TimeAgo iso={data.finished_at} /> : "—"}</dd>
            <dt>Duração</dt>
            <dd>{data.duration_ms} ms</dd>
          </dl>
          {data.snapshot_id !== null && (
            <p>
              <Link to={`/reconcile?snapshot_id=${data.snapshot_id}`}>
                Ver reconcile do snapshot #{data.snapshot_id}
              </Link>
            </p>
          )}
        </>
      )}
    </main>
  );
}
```

- [ ] **Step 6: testes**

`web/src/pages/Reconcile.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reconcile from "./Reconcile";

const DEVICES = [{ id: 1, name: "ne8000-01" }];
const RECONCILE = {
  device_id: 1,
  snapshot_id: null,
  aviso: "Sem snapshot; comparando com o estado de produção.",
  gerado_em: "2026-09-04T00:00:00Z",
  items: [
    { tipo: "bgp", severidade: "critica", esperado: "peer up", encontrado: "peer down", acao: "reconciliar" },
    { tipo: "vlan", severidade: "atencao", esperado: "vlan 10", encontrado: "ausente", acao: "criar" },
  ],
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/devices") {
        return new Response(JSON.stringify(DEVICES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.startsWith("/api/v1/reconciliation?")) {
        return new Response(JSON.stringify(RECONCILE), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderReconcile(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Reconcile />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Reconcile", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("mostra divergências com aviso e filtra por severidade", async () => {
    mockFetch();
    renderReconcile("/reconcile?device_id=1");
    expect(await screen.findByText("Sem snapshot; comparando com o estado de produção.")).toBeInTheDocument();
    expect(screen.getByText("bgp")).toBeInTheDocument();
    expect(screen.getByText("vlan")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severidade"), "critica");
    expect(screen.getByText("bgp")).toBeInTheDocument();
    expect(screen.queryByText("vlan")).not.toBeInTheDocument();
  });

  it("snapshot_id na URL aciona o modo snapshot", async () => {
    mockFetch();
    renderReconcile("/reconcile?snapshot_id=7");
    expect(await screen.findByText("bgp")).toBeInTheDocument();
    const chamada = vi.mocked(fetch).mock.calls.some((c) => String(c[0]).includes("snapshot_id=7"));
    expect(chamada).toBe(true);
  });
});
```

`web/src/pages/Snapshots.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Snapshots from "./Snapshots";

const DEVICES = [{ id: 1, name: "ne8000-01" }];
const SNAPSHOTS = [
  {
    id: 10,
    device_id: 1,
    started_at: "2026-09-04T00:00:00Z",
    finished_at: "2026-09-04T00:00:05Z",
    status: "success",
    resources: {},
    errors: {},
    duration_ms: 5000,
  },
  {
    id: 11,
    device_id: 1,
    started_at: "2026-09-04T00:00:00Z",
    finished_at: null,
    status: "partial",
    resources: {},
    errors: {},
    duration_ms: 2000,
  },
];
const DETAIL = {
  id: 11,
  device_id: 1,
  started_at: "2026-09-04T00:00:00Z",
  finished_at: null,
  status: "partial",
  resources: {
    interfaces: { "GE0/0/0": { up: true } },
    bd: Array.from({ length: 70 }, (_, i) => i),
  },
  errors: { coleta_v4: "timeout" },
  duration_ms: 2000,
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/devices") {
        return new Response(JSON.stringify(DEVICES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/devices/1/snapshots") {
        return new Response(JSON.stringify(SNAPSHOTS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/snapshots/11") {
        return new Response(JSON.stringify(DETAIL), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderSnapshots() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/snapshots"]}>
        <Snapshots />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Snapshots", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lista snapshots, seleciona e mostra a árvore colapsável com paginação", async () => {
    mockFetch();
    renderSnapshots();
    // espera o useDevices resolver antes do selectOptions (a opção não existe
    // enquanto a lista está carregando — `Value "1" not found` de forma determinística)
    await screen.findByRole("option", { name: "ne8000-01" });
    await userEvent.selectOptions(screen.getByLabelText("Equipamento"), "1");
    expect(await screen.findByText("11")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Ver" })[1]);
    expect(await screen.findByText("interfaces")).toBeInTheDocument();
    expect(screen.getByText("Mostrar mais (10)")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Mostrar mais (10)"));
    await waitFor(() => {
      expect(screen.queryByText("Mostrar mais (10)")).not.toBeInTheDocument();
    });
  });
});
```

Run: `cd web && npx vitest run src/pages/Reconcile.test.tsx src/pages/Snapshots.test.tsx` — Expected: 3 PASS. Depois a suíte completa de web e `npm run build` + `npx eslint src`.

Rotas em `App.tsx` (adicionar às existentes; com os imports `Snapshots`, `DesiredConfig`, `Reconcile`, `Jobs`, `JobDetail` de `@/pages/*`):

```tsx
<Route path="/snapshots" element={<RequireAuth><Snapshots /></RequireAuth>} />
<Route path="/desired-config" element={<RequireAuth><DesiredConfig /></RequireAuth>} />
<Route path="/reconcile" element={<RequireAuth><Reconcile /></RequireAuth>} />
<Route path="/jobs" element={<RequireAuth><Jobs /></RequireAuth>} />
<Route path="/jobs/:id" element={<RequireAuth><JobDetail /></RequireAuth>} />
```

- [ ] **Step 7: commit**

```bash
git add web/src/pages web/src/App.tsx web/src/api/hooks.ts
git commit -m "feat(web): visualizadores de snapshot, desired-config, reconcile e jobs

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: DeviceDetail + navegação entre telas + layout completo (nav lateral)

**Files:**
- Create: `web/src/pages/DeviceDetail.tsx`, `web/src/pages/DeviceDetail.test.tsx`, `web/src/components/Layout.tsx`, `web/src/components/Layout.test.tsx`
- Modify: `web/src/App.tsx` (rota `/devices/:id` + rotas protegidas sob o `<Layout>`), `web/src/api/hooks.ts` (hook `useDevice`), `web/src/styles/global.css` (nav)

**Interfaces:**
- Consumes: `useAuth` (Task 4: `usuario`, `ehAdmin`, `logout` — POST `/api/v1/auth/logout` → 204, limpa `usuario`), `useDeviceColetar` (Task 7 — POST collect → `{queued, message, job_id}`), `useSnapshots(deviceId)` (Task 10), `useSites` (Task 7), tipos `DeviceOut`/`SiteOut` (Task 3).
- Produces: `useDevice(id)` (novo hook, Step 1); `Layout` com nav lateral + logout; rota `/devices/:id`; links de inspeção com `?device_id=`.

> **Correção de defeito do rascunho (ruling da orquestração, compatível com o ruling da T3 e a implementação da T7):** o texto original dizia "POST collect → retorna `job_id` → navega para `/jobs/{id}` e faz poll". **Errado**: o `job_id` do `/collect` é o **uuid da fila RQ**, NÃO o `JobRun.id` (int) — a rota `/jobs/{id}` só aceita int; `Number(uuid)` = NaN → `useJobPoll` desabilitado → "Job não encontrado." A navegação correta (idêntica à da T7/Devices, e ao teste da T7) é para **`/jobs?device_id=<id>`** — a lista filtrida. Polling individual do JobRun não é possível no pós-coleta (JobRun só nasce na execução do runner) — wart de backend parkado como follow-up pós-ciclo (ver ledger T3).
> Também: a T7 define `useDevices` (lista) mas **nenhum** `useDevice` (detalhe) — o Step 1 cria o hook.

- [ ] **Step 1: `useDevice` em `web/src/api/hooks.ts`** (append; adicionar `DeviceOut` ao bloco de import de tipos ordenado existente — não substituir)

```ts
export function useDevice(id: number) {
  return useQuery({
    queryKey: ["device", id],
    queryFn: () => apiFetch<DeviceOut>(`/api/v1/devices/${id}`),
    enabled: id > 0,
  });
}
```

- [ ] **Step 2: `Layout.tsx`**

`web/src/components/Layout.tsx` (usa `<Outlet />` — o App o define como rota-pai):

```tsx
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";

const ITENS_NAV: { para: string; rotulo: string; admin?: boolean }[] = [
  { para: "/", rotulo: "Dashboard" },
  { para: "/devices", rotulo: "Equipamentos" },
  { para: "/sites", rotulo: "Sites" },
  { para: "/organizations", rotulo: "Organizações" },
  { para: "/contacts", rotulo: "Contatos" },
  { para: "/circuits", rotulo: "Circuitos" },
  { para: "/bgp-sessions", rotulo: "Sessões BGP" },
  { para: "/prefix-authorizations", rotulo: "Prefixos autorizados" },
  { para: "/policy-profiles", rotulo: "Perfis de política" },
  { para: "/communities", rotulo: "Communities" },
  { para: "/snapshots", rotulo: "Snapshots" },
  { para: "/desired-config", rotulo: "Config desejada" },
  { para: "/reconcile", rotulo: "Reconciliação" },
  { para: "/jobs", rotulo: "Jobs" },
  { para: "/audit-events", rotulo: "Auditoria" },
  { para: "/users", rotulo: "Usuários", admin: true },
];

export function Layout() {
  const { usuario, ehAdmin, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="app-titulo">
          Gerenet
        </Link>
        <span className="app-usuario">{usuario?.username}</span>
        <button type="button" onClick={() => void logout().then(() => navigate("/login"))}>
          Sair
        </button>
      </header>
      <div className="app-corpo">
        <nav className="app-nav" aria-label="Navegação principal">
          {ITENS_NAV.filter((i) => !i.admin || ehAdmin).map((i) => (
            <NavLink key={i.para} to={i.para} end={i.para === "/"}>
              {i.rotulo}
            </NavLink>
          ))}
        </nav>
        <div className="app-conteudo">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
```

CSS a appendar em `global.css` (as páginas mantêm `<main>` interno; o conteúdo do layout é `<div>` para não aninhar mains):

```css
.app-shell { display: flex; flex-direction: column; min-height: 100vh; }
.app-header { display: flex; align-items: center; gap: 1rem; padding: 0.6rem 1rem; border-bottom: 1px solid var(--border); background: var(--bg-elevated); }
.app-header .app-titulo { font-weight: 700; text-decoration: none; color: inherit; }
.app-header .app-usuario { margin-left: auto; font-size: 0.85rem; opacity: 0.8; }
.app-corpo { display: flex; flex: 1; }
.app-nav { display: flex; flex-direction: column; gap: 0.1rem; min-width: 190px; padding: 0.8rem; border-right: 1px solid var(--border); }
.app-nav a { padding: 0.3rem 0.5rem; color: inherit; text-decoration: none; border-radius: 6px; font-size: 0.9rem; }
.app-nav a.active { background: var(--accent); color: var(--text-on-accent); }
.app-conteudo { flex: 1; padding: 1rem; overflow-x: auto; }
```

- [ ] **Step 3: `App.tsx`** — rotas protegidas aninhadas sob o `Layout` (rota pai sem path + `<Outlet />`), nova rota `/devices/:id`, `/login` fora do layout

```tsx
import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAdmin, RequireAuth } from "@/auth/auth-context";
import { Layout } from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Users from "@/pages/Users";
import Devices from "@/pages/Devices";
import DeviceDetail from "@/pages/DeviceDetail";
import Sites from "@/pages/Sites";
import Organizations from "@/pages/Organizations";
import Contacts from "@/pages/Contacts";
import Circuits from "@/pages/Circuits";
import CircuitDetail from "@/pages/CircuitDetail";
import BgpSessions from "@/pages/BgpSessions";
import BgpSessionDetail from "@/pages/BgpSessionDetail";
import PolicyProfiles from "@/pages/PolicyProfiles";
import Communities from "@/pages/Communities";
import PrefixAuthorizations from "@/pages/PrefixAuthorizations";
import AuditEvents from "@/pages/AuditEvents";
import Snapshots from "@/pages/Snapshots";
import DesiredConfig from "@/pages/DesiredConfig";
import Reconcile from "@/pages/Reconcile";
import Jobs from "@/pages/Jobs";
import JobDetail from "@/pages/JobDetail";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/devices" element={<Devices />} />
        <Route path="/devices/:id" element={<DeviceDetail />} />
        <Route path="/sites" element={<Sites />} />
        <Route path="/organizations" element={<Organizations />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/circuits" element={<Circuits />} />
        <Route path="/circuits/:id" element={<CircuitDetail />} />
        <Route path="/bgp-sessions" element={<BgpSessions />} />
        <Route path="/bgp-sessions/:id" element={<BgpSessionDetail />} />
        <Route path="/policy-profiles" element={<PolicyProfiles />} />
        <Route path="/communities" element={<Communities />} />
        <Route path="/prefix-authorizations" element={<PrefixAuthorizations />} />
        <Route path="/audit-events" element={<AuditEvents />} />
        <Route path="/snapshots" element={<Snapshots />} />
        <Route path="/desired-config" element={<DesiredConfig />} />
        <Route path="/reconcile" element={<Reconcile />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route
          path="/users"
          element={
            <RequireAdmin>
              <Users />
            </RequireAdmin>
          }
        />
      </Route>
    </Routes>
  );
}
```

(Se um nome de default export de alguma página divergir do que está acima, ajustar o import ao nome real — o `tsc -b` do build acusa.)

- [ ] **Step 4: `DeviceDetail.tsx`**

```tsx
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useDevice, useDeviceColetar, useSites, useSnapshots } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";

export default function DeviceDetail() {
  const { id } = useParams();
  const deviceId = Number(id);
  const navigate = useNavigate();
  const { data: device, isLoading, error } = useDevice(deviceId);
  const { data: sites } = useSites();
  const { data: snapshots } = useSnapshots(deviceId);
  const coletar = useDeviceColetar();
  const siteNome = sites?.find((s) => s.id === device?.site_id)?.name ?? null;
  const ultimoSnapshot = snapshots && snapshots.length > 0 ? snapshots[0] : null;

  if (isLoading) return <main><p aria-busy="true">Carregando…</p></main>;
  if (!device) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar o equipamento."}</p>
      </main>
    );
  }

  return (
    <main>
      <PageHeader titulo={device.name} acoes={<Link to="/devices">← Voltar</Link>} />
      <ul>
        <li>Endereço de gestão: <span>{device.management_address}</span></li>
        <li>Site: <span>{siteNome ?? "—"}</span></li>
        <li>Função: <span>{device.role ?? "—"}</span></li>
        <li>Modelo: <span>{device.model ?? "—"}</span> · Família: <span>{device.family ?? "—"}</span></li>
        <li>Versão VRP: <span>{device.vrp_version ?? "—"}</span></li>
        <li>ASN: <span>{device.asn ?? "—"}</span></li>
        <li>Comunicação: <StatusBadge estado={device.comm_status} /></li>
        <li>Situação: <StatusBadge estado={device.admin_status ? "ativo" : "inativo"} /></li>
        <li>Última coleta: <TimeAgo iso={device.last_collected_at} /></li>
      </ul>
      <p>
        <button
          className="primary"
          disabled={coletar.isPending}
          onClick={() => void coletar.mutateAsync(device.id).then(() => navigate(`/jobs?device_id=${device.id}`))}
        >
          Coletar agora
        </button>
        {coletar.error && (
          <span role="alert"> {String(coletar.error.message ?? "Falha ao coletar.")}</span>
        )}
      </p>
      <h2>Último snapshot</h2>
      <p>
        {ultimoSnapshot ? (
          <>
            #{ultimoSnapshot.id} · <StatusBadge estado={ultimoSnapshot.status} /> ·{" "}
            <TimeAgo iso={ultimoSnapshot.started_at} />
          </>
        ) : (
          "Nenhum snapshot."
        )}
      </p>
      <h2>Inspeção</h2>
      <p>
        <Link to={`/snapshots?device_id=${device.id}`}>Snapshots</Link>{" "}
        <Link to={`/desired-config?device_id=${device.id}`}>Config desejada</Link>{" "}
        <Link to={`/reconcile?device_id=${device.id}`}>Reconciliar</Link>
      </p>
    </main>
  );
}
```

> **Correção de defeito do rascunho (ruling da orquestração):** os valores deste `<ul>` são envolvidos em `<span>` (uniforme). Motivo: `getByText` da @testing-library compara `getNodeText` — a concatenação dos filhos diretos que são text nodes; `<li>ASN: {device.asn ?? "—"}</li>` vira `"ASN: 65001"` e a asserção `getByText("65001")` do teste (Step 5) falha de forma determinística (`Unable to find an element with the text: 65001`). Com `<span>` o valor é nó textual direto do próprio elemento e casa default `exact: true` — o mesmo vale para todos os valores do `ul` (estrutura uniforme para o que estiver no teste). Não mexer nos `StatusBadge`/`TimeAgo` (elementos filhos, ignorados pelo getNodeText — não afetam).
>
> **Segunda correção (revisor T11, Important):** `if (!device)` colocava 404, rede e 500 no mesmo texto "Equipamento não encontrado." — sem superfície de erro para `useDevice`. Agora o guard renderiza `role="alert"` com a mensagem exata (404 = `"Equipamento {id} não encontrado."` da API via `ApiError.message`; rede/500 idem — constraint de mensagens idênticas) e o texto estático fica só como fallback de query sem erro. MESMA família do pool T10 (JobDetail, listas de jobs/snapshots) — os demais casos ficam na revisão final.

- [ ] **Step 5: testes**

`web/src/components/Layout.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Layout } from "./Layout";
import { AuthProvider } from "@/auth/auth-context";

const ME_ADMIN = {
  id: 1,
  username: "boss",
  role: "administrador",
  is_active: true,
  last_login_at: null,
  created_at: "2026-09-04T00:00:00Z",
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/auth/me") {
        return new Response(JSON.stringify(ME_ADMIN), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/auth/logout" && init?.method === "POST") {
        return new Response(null, { status: 204 });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderLayout() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/devices"]}>
          <Routes>
            <Route path="/login" element={<div>login-page</div>} />
            <Route element={<Layout />}>
              <Route path="/devices" element={<div>devices-page</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Layout", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renderiza a nav com item admin e faz logout", async () => {
    mockFetch();
    renderLayout();
    expect(await screen.findByText("Equipamentos")).toBeInTheDocument();
    expect(screen.getByText("Usuários")).toBeInTheDocument();
    expect(screen.getByText("devices-page")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sair" }));
    expect(await screen.findByText("login-page")).toBeInTheDocument();
    const chamada = vi.mocked(fetch).mock.calls.find(
      (c) => String(c[0]) === "/api/v1/auth/logout" && String(c[1]?.method) === "POST",
    );
    expect(chamada).toBeTruthy();
  });
});
```

`web/src/pages/DeviceDetail.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DeviceDetail from "./DeviceDetail";

const DEVICE = {
  id: 1,
  name: "ne8000-01",
  management_address: "10.0.0.1",
  ssh_port: null,
  vendor: "huawei",
  model: "NE8000",
  family: "NE8000",
  role: "edge",
  site_id: 1,
  asn: 65001,
  vrp_version: "V800R021",
  comm_status: "ok",
  admin_status: true,
  last_collected_at: null,
  tags: [],
};
const SITES = [
  { id: 1, name: "POP-SP", city: null, uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true },
];
const SNAPSHOTS = [
  {
    id: 10,
    device_id: 1,
    started_at: "2026-09-04T00:00:00Z",
    finished_at: null,
    status: "success",
    resources: {},
    errors: {},
    duration_ms: 1000,
  },
];

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/devices/1" && (init?.method === undefined || init.method === "GET")) {
        return new Response(JSON.stringify(DEVICE), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/sites") {
        return new Response(JSON.stringify(SITES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/devices/1/snapshots") {
        return new Response(JSON.stringify(SNAPSHOTS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/devices/1/collect" && init?.method === "POST") {
        return new Response(JSON.stringify({ queued: true, message: "ok", job_id: "uuid-do-job" }), { status: 202, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/devices/1"]}>
        <Routes>
          <Route path="/devices/:id" element={<DeviceDetail />} />
          <Route path="/jobs" element={<div>jobs-page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DeviceDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renderiza dados do equipamento, snapshot e links de inspeção", async () => {
    mockFetch();
    renderDetail();
    expect(await screen.findByText("ne8000-01")).toBeInTheDocument();
    expect(screen.getByText("65001")).toBeInTheDocument();
    expect(screen.getByText("POP-SP")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reconciliar" })).toBeInTheDocument();
  });

  it("Coletar agora envia POST e navega para /jobs?device_id=1", async () => {
    mockFetch();
    renderDetail();
    await userEvent.click(await screen.findByRole("button", { name: "Coletar agora" }));
    expect(await screen.findByText("jobs-page")).toBeInTheDocument();
    const chamada = vi.mocked(fetch).mock.calls.find(
      (c) => String(c[0]) === "/api/v1/devices/1/collect" && String(c[1]?.method) === "POST",
    );
    expect(chamada).toBeTruthy();
  });
});
```

Run: `cd web && npx vitest run src/components/Layout.test.tsx src/pages/DeviceDetail.test.tsx` — Expected: 3 PASS. Depois `cd web && npx vitest run` (suíte completa), `npm run build` e `npx eslint src`.

- [ ] **Step 6: commit**

```bash
git add web/src/pages/DeviceDetail.tsx web/src/pages/DeviceDetail.test.tsx web/src/components/Layout.tsx web/src/components/Layout.test.tsx web/src/App.tsx web/src/api/hooks.ts web/src/styles/global.css
git commit -m "feat(web): detalhe de device com coleta e layout de navegacao com logout

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: E2E (Playwright) + seed + README/docs

**Files:**
- Create: `web/e2e/setup.ts` (seed dados via API + CLI)
- Create: `web/e2e/login.spec.ts`, `web/e2e/smoke.spec.ts`
- Create: `web/e2e/README.md` (run-book)
- Modify: `web/playwright.config.ts` (usa webServer: `uvicorn` — melhor com `webServer.command: "bash -c '…'"`; build antes)
- Modify: `README.md` (seção "Interface web — dev e build")
- Modify: `CLAUDE.md` ("Estado do repositório" — web/ e comandos novos)

**Interfaces:**
- Consumes: backend de verdade (compose + alembic + uvicorn) com `.env`/config padrão.
- Produces: 2 specs de fumo verdes localmente com a stack de pé; documentos.

- [ ] **Step 1: `web/e2e/setup.ts`** — seeds idempotentes: cria usuário `admin` via `gerenet users create admin --role administrador` (senha via env `E2E_PASSWORD` padrão `e2e-super-8`), cria device+site+org+circuito+vlan+prefixo através da API com X-Api-Key (enviada ao backend diretamente via fetch node com Api-Key de `settings.api_key` — ler de `GERENET_API_KEY` env). Sem segredo hardcoded: senha só no env.
- [ ] **Step 2: `login.spec.ts`**:
  - `test('login ok → dashboard', …)`: goto `/login`, preenche, entra; vê h1 "Dashboard".
  - `test('login inválido → erro', …)`: senha errada; vê "Usuário ou senha inválidos."
  - `test('logout', …)`: sai; volta ao `/login`.
- [ ] **Step 3: `smoke.spec.ts`**:
  - `test('criar e desativar site', …)`: site → lista → desativar com confirmação.
  - `test('abrir Reconcile com device seedado', …)`: select device → tabela/aviso renderizada.
- [ ] **Step 4: run-book `web/e2e/README.md`**:
```
1. docker compose up -d && uv run alembic upgrade head
2. uv run uvicorn gerenet.api.main:create_app --factory
3. cd web && npm run build && npm run test:e2e   (segundo terminal: rodar seed `npx playwright test e2e/setup? — ou script npm run e2e:seed`)
```
- [ ] **Step 5: README.md** — seção "Interface web — dev e build" (run-book §7 da spec; mencionar `GERENET_COOKIE_SECURE=true` sob HTTPS).
- [ ] **Step 6: CLAUDE.md** — atualizar "Estado do repositório" com `web/` (scripts, proxy, o que roda em dev).
- [ ] **Step 7: rodar e2e (stack local de pé) e commit.**

```bash
git add web/e2e web/playwright.config.ts README.md CLAUDE.md
git commit -m "docs+test(web): fumos e2e com seed, run-book da interface web e CLAUDE.md atualizado

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 13: Fechamento — suíte completa, lint, build produção, revisão de critérios de aceite

**Files:** nenhum novo (verificação).

- [ ] **Step 1: suíte backend inteira** (post-C1 + T1):

```bash
GERENET_TEST_DATABASE_URL=postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test_c2 uv run pytest -q
```
Expected: todos verdes (349 + novos).

- [ ] **Step 2: front**

```bash
cd web && npm run lint && npm run test && npm run build
```
Expected: lint e testes verdes; build gera `web/dist`.

- [ ] **Step 3: conferência manual dos critérios de aceite §12** (fazer via navegação local: start uvicorn com `web/dist` existente):
  1. login/sessão/logout reais; API key segue valendo (testes backend);
  2. auditoria com autor real — pytest cobre;
  3. Visualizador 403 na escrita — coberto por teste backend;
  4. dashboard abre com agregados — testes;
  5. todas as entidades da API têm tela — navegar: gerenciar equipamentos, sites, orgs, contatos, circuitos, BGP sessions, prefix auth, catálogos, auditoria, jobs + as 3 de inspeção (snapshots/desired-config/reconcile);
  6. snapshot/desired-config/reconcile navegáveis + coleta com job e poll — fumos;
  7. nenhum segredo no front — revisão manual do código (`credentials: include` only; nenhuma senha em state persistente);
  8. Vitest/fumos verdes, lint TS limpo — steps 1–2.

- [ ] **Step 4: commit final** (se houver ajustes) + revisão final de branch (subagent) + limpeza do workspace SDD.

## Self-Review da spec

- **Cobertura da spec §6.3**: todas as 16 rotas da tabela cobertas: `/login` (T4), `/` (T4/tela T6), `/devices` (+detalhe) (T7/T11), `/sites`, `/organizations`, `/contacts` (T7), `/circuits` (+detalhe) (T8), `/bgp-sessions` (+detalhe) (T8), `/policy-profiles`, `/communities` (T9), `/prefix-authorizations` (T9), `/snapshots` (T10), `/desired-config` (T10), `/reconcile` (T10), `/jobs`+`/:id` (T10), `/audit-events` (T9), `/users` (T6). ✓
- **§6.1**: scaffold com deps/scripts precisos (T2); **§6.2**: client+types+hooks (T3, T6); **§6.4**: tokens dark-first (T2 CSS); **§7**: dev/prod/deploy (run-book T12); **§9 frontend**: Vitest (T3–T6, T10), Playwright (T12); **§8**: sem segredos (constraints + T3 test); **§10**: docs (T12).
- **Buraco encontrado na revisão do estado**: `reconciliation.py`/`communities.py` em `require_api_key` — coberto na **T1** (falla se a web for usar cookie).
- **Placeholders**: nenhum TODO/TBD — os esboços curtos (Task 7 e 8) indicam campos exatos do schema e o padrão do teste, que o implementer segue à risca (as telas derivam mecanicamente).
- **Consistência**: client sempre `apiFetch`; todas as rotas sob `RequireAuth`; **`useJobPoll` definido uma vez na Task 6** (`enabled` + refetchInterval 3s até status terminal `success/partial/error` — `JOB_STATUS` de models.py:22) e consumido nas Tasks 10 e 11 com o mesmo nome; tipos `*Out` conferidos nesta revisão contra models/schemas (`COMM_STATUS`, `SNAPSHOT_STATUS`, `JOB_STATUS`) e `verify_password` (users.py:46) / `_valida_senha` (users.py:63) / `create_user` (keyword-only) confirmados no código real.
