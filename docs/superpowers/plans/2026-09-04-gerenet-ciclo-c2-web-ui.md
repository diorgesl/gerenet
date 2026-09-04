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

CSS (em `global.css`):
```css
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75rem; border: 1px solid var(--border); }
.badge-ok { color: var(--ok); }
.badge-fail, .badge-danger { color: var(--danger); }
.badge-warn { color: var(--warn); }
.badge-unknown { color: var(--unknown); }
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

- [ ] **Step 5: testes**

`web/src/pages/Users.test.tsx`: render com `AuthProvider` + `QueryClientProvider` + mock fetch com `/api/v1/users` → lista, clicar "Desativar" → PATCH enviado (assert fetch chamado com método PATCH e body `{is_active:false}`), e conta própria sem botão.

`web/src/pages/Dashboard.test.tsx`: mock fetch com `/api/v1/dashboard` → cards renderizados, links presentes.

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

- [ ] **Step 4: `Organizations.tsx` e `Contacts.tsx`**

Mesmo padrão exato de `Sites.tsx`, com os campos:

- **Organizations** — form: `name` (obrigatório), `legal_name`, `kind` (select `downstream`/`parceiro`, default `downstream`), `asn` (number), `irr_as_set`, `notes`; tabela: name, legal_name, kind (badge), asn, irr_as_set, notes.
- **Contacts** — form: `organization_id` (select: name das organizações — `useOrganizations()`), `name` (obrigatório), `email`, `phone`, `kind` (select `tecnico`/`noc`/`admin`); tabela: name, email, phone, kind, organização.
- A tela de Organizations usa `useOrganizationCriar`/`useOrganizationAtualizar`; a de Contacts usa `useContactCriar`/`useContactAtualizar`.

Teste de referência (`web/src/pages/Sites.test.tsx` — os demais seguem igual):

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

- [ ] **Step 5: rotas em `App.tsx`** (padrão `/devices`, `/sites`, `/organizations`, `/contacts` todas sob `RequireAuth`).

- [ ] **Step 6: testes + `npm run build` + lint** e commit.

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

- [ ] **Step 1: hooks** — padrão da Task 7 + `useCircuitoReservar(id)` (POST `/circuits/${id}/reserve`), `useSessionCommunity` (POST/DELETE `/bgp-sessions/${id}/communities`), `useSessionSenha` (POST `/bgp-sessions/${id}/password`).
- [ ] **Step 2: `Circuits.tsx`** — tabela: code, org, site, devices, stack, bfd, admin; form com todos os campos do `CircuitCreate` (code, organization_id, site_id, access_device_id, access_port, edge_device_id, backup_edge_device_id, stack, vlan_mode, qinq, vrf, mtu, bandwidth, bfd, p2p_v4_len, description, notes, edge_trunk).
- [ ] **Step 3: `CircuitDetail.tsx`** — `GET /circuits/{id}` → `CircuitDetailOut`: pontas V4/V6; botão "Reservar recursos" (POST reserve → atualiza o detail); sessões BGP do circuito (GET `/bgp-sessions?circuit_id=`).
- [ ] **Step 4: `BgpSessions.tsx`** — tabela: circuit, device, afi, addresses, ASNs, shutdown; form com campos do `BgpSessionCreate`.
- [ ] **Step 5: `BgpSessionDetail.tsx`** — communities associadas (GET `/bgp-sessions/{id}` + lista de `/communities` + POST/DELETE); "Definir senha" (campo e POST; mostra `has_password`).
- [ ] **Step 6: testes (mock fetch dos fluxos principais) + `npm run build` + lint + commit** (uma por arquivo de tela, padrão C1: testes de fluxo feliz e erro exibido).

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

**Interfaces:** Predecessores: Task 7 (padrão). Prefix-auth tem POST/PATCH; policy/communities/audit são GET-only (read-only — frente `podeEscrever` desabilita botões quando visualizador).

- [ ] **Step 1: hooks** de `prefix-authorizations` (lista + criar + ativar/desativar) e `audit-events` (com filtros `tipo`, `objeto`, `objeto_id`) e `policy-profiles`, `communities` (listas).
- [ ] **Step 2: `PolicyProfiles.tsx` e `Communities.tsx`** — tabela read-only com filtro direction (policy-profiles) / janela de detalhe (communities: name, notes).
- [ ] **Step 3: `PrefixAuthorizations.tsx`** — form: `organization_id`, `family` (select v4/v6), `prefix`, `notes`; desativar com ConfirmDialog; `origin` mostrado (manual).
- [ ] **Step 4: `AuditEvents.tsx`** — filtros (tipo/ator/objeto) e tabela `details` expansível (colapsável `<details>`).
- [ ] **Step 5: testes + build + lint + commit.**

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
- Consumes: hooks (Task 9). Específicos `useDesiredConfig(deviceId)`, `useReconcile({device_id|snapshot_id})`, `useSnapshots(deviceId)`, `useJobPoll`, `useJobs({filtros})`.
- Produces: as 4 telas de inspeção técnica (snapshot JSON com colapso por chave top-level; desired-config em acordeão por bloco + MonoCode + botão copiar; reconcile com filtro por severidade e aviso de snapshot ausente; jobs com filtros + detalhe com timing e snapshot).

- [ ] **Step 1: hooks**
```ts
export function useSnapshots(deviceId: number) {
  return useQuery({ queryKey: ["snapshots", deviceId], queryFn: () => apiFetch<SnapshotOut[]>(`/api/v1/devices/${deviceId}/snapshots`) });
}
export function useSnapshot(id: number) {
  return useQuery({ queryKey: ["snapshots", id], queryFn: () => apiFetch<SnapshotOut>(`/api/v1/snapshots/${id}`), enabled: id > 0 });
}
export function useDesiredConfig(deviceId: number | null) {
  return useQuery({ queryKey: ["desired", deviceId], queryFn: () => apiFetch<DesiredConfigOut>(`/api/v1/devices/${deviceId}/desired-config`), enabled: !!deviceId, retry: false });
}
export function useReconcile(filtro: { device_id?: number; snapshot_id?: number }) {
  return useQuery({
    queryKey: ["reconcile", filtro],
    queryFn: () =>
      apiFetch<ReconcileOut>(
        `/api/v1/reconciliation?${new URLSearchParams(
          Object.entries(filtro).map(([k, v]) => [k, String(v)]) as [string, string][],
        ).toString()}`,
      ),
    enabled: Number(filtro.device_id ?? filtro.snapshot_id) > 0,
    retry: false,
  });
}
```
- [ ] **Step 2: `Snapshots.tsx`** — seletor de device (select de `/devices`) → lista `/devices/{id}/snapshots` → seleciona → `GET /snapshots/{id}` e renderiza `resources` como árvore colapsável (recursion em componente `JsonTree` local: `<details>` por valor objeto/array; arrays com slice + paginação se > 60 itens).
- [ ] **Step 3: `DesiredConfig.tsx`** — seletor de device → GET desired-config → blocos em acordeão (`<details>` por `tipo/objeto`) + `MonoCode` com o `texto`; vazio → "Nenhum bloco renderizado."
- [ ] **Step 4: `Reconcile.tsx`** — dois modos: select de device OU input `snapshot_id`; query `useReconcile`; tabela com `SeverityBadge`, filtro client-side por severidade; `aviso` exibido quando presente; erro 400 com "Informe exatamente um de device_id ou snapshot_id." exibido.
- [ ] **Step 5: `Jobs.tsx` + `JobDetail.tsx`** — lista com filtros (device/status/kind) e select limit/offset; detalhe do job com mesclar `started_at/finished_at/duration_ms` e link ao snapshot; polling via `useJobPoll(id)` (refetchInterval 3s encerrado em status terminal).
- [ ] **Step 6: testes (`Reconcile.test.tsx` — itens mock, filtro por severidade, aviso; `Snapshots.test.tsx` — tree colapsável e paginação de array) + build + lint + commit.**

```bash
git add web/src/pages web/src/App.tsx web/src/api/hooks.ts
git commit -m "feat(web): visualizadores de snapshot, desired-config, reconcile e jobs

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: DeviceDetail + navegação entre telas + layout completo (nav lateral)

**Files:**
- Create: `web/src/pages/DeviceDetail.tsx`
- Modify: `web/src/App.tsx` (rota `/devices/:id` + layout com nav), `web/src/components/Layout.tsx` (nav com links + logout)
- Modify: `web/src/styles/global.css` (nav)

**Interfaces:** Consuma `useDevices/{id}` (Task 7), `useSnapshot`/`useSnapshots` (Task 10). Botões: "Coletar agora" (POST collect → retorna `job_id` → navega para `/jobs/{id}` e faz poll), abrir snapshots/desired-config/reconcile.

- [ ] **Step 1: `Layout.tsx`** — header com título + nav (Dashboard, Devices, Sites, Organizations, Contacts, Circuits, BGP Sessions, Prefix Auths, Policy Profiles, Communities, Snapshots, Desired Config, Reconcile, Jobs, Audit, Users (admin)) + botão logout (useAuth). Opcional: quebra por seções usando `<details>`? Não no v1 — nav direta.
- [ ] **Step 2: `App.tsx`** — envolver todas as rotas protegidas no `<Layout>`; rota `/devices/:id` → `DeviceDetail`.
- [ ] **Step 3: `DeviceDetail.tsx`** — GET `/devices/{id}`; cartões (com status, site, coleta, asn, vrp), último snapshot resumo (via `/devices/{id}/snapshots` → primeiro), links para detalhe (desired-config/reconcile/snapshots), botão coleta + poll de job.
- [ ] **Step 4: test + build + lint + commit.**

```bash
git add web/src/pages/DeviceDetail.tsx web/src/components/Layout.tsx web/src/App.tsx web/src/styles/global.css
git commit -m "feat(web): detalhe de device com coleta/poll de job e layout de navegacao

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
