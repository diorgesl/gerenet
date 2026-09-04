# Design — Ciclo C: interface web (gerenet)

> Especificação do **ciclo C** do gerenet — interface web sobre o que já existe hoje
> (API + CLI + worker), na ordem antecipada pelo operador (ver decisão 8).
> Documentos-fonte: [ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md](../../../ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md)
> (§4.2, §6, §15–19), spec do ciclo B (2026-09-03, render + divergência — em andamento) e
> spec do ciclo A (2026-09-02, SoT + API/CLI).

## 1. Objetivo e escopo

Entregar a **interface web** do gerenet: autenticação de usuários com perfis §17
(login local, sessão por cookie — API key continua valendo para CLI/automações), um
**dashboard** §16.1, e telas para **tudo que a API já expõe no dia de hoje**: CRUD de
devices, sites, organizações/downstreams, contacts, circuitos, sessões BGP,
policy-profiles, prefix-authorizations, audit-events, communities; e visualização de
snapshots, desired-config e reconciliação (desejado × encontrado), além de disparo de
coleta com acompanhamento de job.

Fora do ciclo C (destino): assistentes web §16.2/16.3 (downstream/MPLS) — virão junto do
motor de mudanças; change requests/aprovações §12 (o motor de mudanças já existirá com
usuários/perfis e sessões disponíveis); execução de mudanças no equipamento a partir da
web (a UI só lê, coleta e mostra comandos — nada de provisionar); OIDC/LDAP/TACACS+ como
provedores de autenticação (evolução do login local §4.2); 2FA/rate limit; i18n; gráficos
avançados; servidor MCP das ferramentas (arco de integrações).

## 2. Contexto (o que já existe)

- **F1 (cortes 0–2)**: devices + Vault + host keys; coleta `version` + backup via fila/lock
  (`automation/`); `device_snapshots` (`resources` JSON, `status` success/partial/error),
  `job_runs` (`status` queued/running/success/partial/error, `origin` api|cli|rq, `actor`);
  worker RQ; `POST /api/v1/devices/{id}/collect` (202, retorna dict de `enqueue_collect`),
  `GET /api/v1/devices/{id}/snapshots`, `GET /api/v1/snapshots/{id}`.
- **Ciclo A (P1–P3)**: SoT + serviços + API `/api/v1` + CLI Typer; auditoria imutável
  `audit_events` (`actor` string; routers hoje passam o literal `"api"`); catálogos seedados
  (policy-profiles, communities); 216+ testes (pytest + goldens + CLI smoke); `require_api_key`
  único (X-Api-Key vs `settings.api_key`, compare_digest).
- **Ciclo B (2026-09-03, em andamento por outro agente)**: render Jinja2 (desired-config),
  divergência on-demand, communities na API/CLI, `circuits.edge_trunk` — o **ponto de
  partida deste ciclo é o head pós-B2**: as telas de desired-config/reconcile/communities
  dependem desses endpoints.
- **Spec**: §4.2 sugere "autenticação local no MVP (evoluir p/ OIDC/LDAP)" e "React/Next.js
  ou interface server-side no MVP" — a escolha em 2026-09-04 foi React SPA sobre a API
  existente (a API já é o frontend contract; sem backend de view próprio).
- **Não existe**: usuários, perfis, sessões, nenhuma UI, Node/JS no repositório, CI.

## 3. Decisões de design (aprovadas em 2026-09-04 no brainstorm)

1. **React 18 + Vite + TypeScript em `web/`**, SPA de origem única: em produção o build
   (`web/dist`) é servido pelo próprio FastAPI (sem CORS, cookie SameSite ok); em dev o
   Vite proxya `/api` → `:8000`. Sem framework de UI de terceiros: componentes próprios
   leves (DataTable, FormField, StatusBadge…) com CSS vars tokenizadas, dark-first com
   fallback claro por `prefers-color-scheme`.
2. **Autenticação local**: tabela `users` (hash scrypt via `hashlib` stdlib — **nenhuma
   dependência nova de Python**), sessões em **banco** (`user_sessions`, token opaco no
   cookie `gerenet_sess` HttpOnly/SameSite=Lax, hash sha256 no banco). API key permanece:
   `require_actor` aceita cookie **ou** X-Api-Key em todas as rotas existentes — CLI,
   automações e os testes atuais (que usam a chave) seguem verdes.
3. **Perfis §17 no banco desde já** (`role` enum visualizador|operador|aprovador|executor|
   administrador), com enforcement v1 centralizado: **Visualizador = somente leitura** (403
   em escrita); demais perfis = leitura+escrita. A separação fina aprovador×executor fica para
   o motor de mudanças — a coluna já nasce.
4. **Escopo v1 = tudo que existe hoje** (seção 1); sem wizards, sem change requests.
5. **Auditoria com quem é quem**: routers trocam o literal `actor="api"` pelo nome do
   usuário da sessão (`actor.nome`); via X-Api-Key continua "api". Login/logout também são
   eventos de auditoria (`auth.login`, `auth.login_failed`, `auth.logout`).
6. **Dashboard com endpoint próprio no backend** (`GET /api/v1/dashboard`) — agregação
   server-side (device/snapshot/jobs/sessões/circuitos/vlans/prefixos/últimas auditorias)
   para o front não fazer N+1. Divergências **não** são contadas no dashboard v1 (custo de
   re-render por device; a página Reconcile faz isso sob demanda) — §16.1 fica parcial, o
   campo "divergências" chega junto da reconciliação agendada (F6).
7. **Coleta com acompanhamento**: o retorno do `enqueue_collect` ganha `job_id` (compatível)
   e a API ganha leitura de jobs (`GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`) — lista §15 já
   previa `/api/v1/jobs`. O front faz poll curto do job até sucesso/parcial/falha.
8. **Ordem do roadmap ajustada pelo operador (2026-09-04)**: UI web **antes** do motor de
   mudanças, invertendo o ruling 8 da spec do ciclo B (B → C → UI). Motivo: usuários,
   sessões e perfis são pré-requisito de aprovações/execuções, e a UI de visualização
   (divergência, desired-config, snapshot) é a mais valiosa para o uso diário. O motor de
   mudanças vira o ciclo D, reutilizando esta camada de usuários/perfis.

## 4. Autenticação e usuários

### 4.1 Modelo de dados (migration única)

`users`:
| coluna | tipo | regra |
|---|---|---|
| id | Integer PK | — |
| username | String(64), unique, NOT NULL | criado em lowercase; sem normalização silenciosa |
| password_hash | String(255), NOT NULL | `scrypt$N$r$p$salt_hex$key_hex` (constantes N=16384, r=8, p=1) |
| role | Enum `user_role` (visualizador/operador/aprovador/executor/administrador), NOT NULL | exigido em todo create |
| is_active | Boolean, default true | desativação nunca é exclusão (§14.1) |
| last_login_at | DateTime(tz) | — |
| created_at / updated_at | DateTime(tz) | padrão do repo |

`user_sessions`:
| coluna | tipo | regra |
|---|---|---|
| id | Integer PK | — |
| token_hash | String(64), unique, NOT NULL | sha256 hex do token do cookie |
| user_id | FK users.id, NOT NULL | — |
| expires_at | DateTime(tz), NOT NULL | `settings.session_ttl_seconds` (default 28800) |
| created_at | DateTime(tz) | — |

Regras: token = `secrets.token_urlsafe(32)`; **nenhum dos dois** possui o valor do token —
cookie guarda o token, banco só o hash. Sessão expirada é apagada na primeira leitura
(lazy); logout apaga a linha e limpa o cookie. Múltiplas sessões simultâneas por usuário
são permitidas (mantidas no MVP). `down_revision`: head vigente ao iniciar o plano
(pós-B2). Sem seed de usuário na migration: o primeiro admin nasce via CLI.

### 4.2 Endpoints de auth (`gerenet/api/auth.py`, prefix `/api/v1/auth`)

- `POST /login` — body `{username, password}`; verifica `is_active` + hash; sucesso: cria
  sessão, seta cookie, grava `auth.login` (ator=username) e retorna `UserOut` (200).
  Falha (usuário inexistente, inativo ou senha errada): **mesma mensagem** — 401 "Usuário
  ou senha inválidos." — e grava `auth.login_failed`. Senha nunca entra em log/resposta.
- `POST /logout` — 204; apaga a sessão, limpa o cookie, grava `auth.logout`.
- `GET /me` — 200 `UserOut`; sem sessão válida, 401 "Não autenticado." (login/logout/me não
  exigem X-Api-Key).

Cookie: nome `gerenet_sess`, HttpOnly, SameSite=Lax, path=/; `max_age=session_ttl_seconds`;
`Secure` = `settings.cookie_secure` (default False; documentar True sob HTTPS).

Config: `settings.session_ttl_seconds: int = 28800`, `settings.cookie_secure: bool = False`,
`settings.static_dir: Path = Path("web/dist")`.

### 4.3 `require_actor` (substitui `require_api_key` nas rotas existentes)

`Actor(usuario: User | None, nome: str)` — `nome` = `usuario.username` ou `"api"`.

1. Cookie presente → hash sha256 → sessão não expirada → usuário existente:
   - sessão inválida/expirada: apaga a sessão e responde 401 com a mensagem atual
     ("Chave de API ausente ou inválida." — preservada, testes existentes; o front
     redireciona ao `/login` em qualquer 401, sem exibir a mensagem);
   - usuário `is_active=false`: 403 "Usuário desativado." (seção invalidada).
2. Sem cookie: X-Api-Key válida → `Actor(None, "api")`.
3. Nada válido: 401 **"Chave de API ausente ou inválida."** (mensagem atual, preservada —
   testes existentes).
4. Enforcement de perfil: `Visualizador` + método de escrita → 403 "Perfil Visualizador
   permite apenas leitura." (checagem central no `require_actor`, com o `Request`).

Todas as rotas existentes trocam `dependencies=[Depends(require_api_key)]` por
`[Depends(require_actor)]`; os handlers que gravam auditoria assumem `actor: Actor =
Depends(require_actor)` e passam `actor.nome` no lugar do literal `"api"` — como as
mensagens 401/403 e o caminho X-Api-Key permanecem idênticos, os testes atuais continuam
verdes sem edição (o que muda é verificável por um teste novo por sessão-e-cookie).

### 4.4 `require_admin`

Dependência para o router de usuários: 403 "Somente administradores." para não-admin.

### 4.5 Router de usuários (`gerenet/api/users.py`, prefix `/api/v1/users`, admin-only)

- `GET /` — lista `UserOut`; default = ativos + query `include_disabled` (padrão dos
  catálogos). 403 não-admin; 401 sem autenticação.
- `POST /` — `{username, password, role}` → 201 `UserOut`; username duplicado → 409;
  senha < 8 caracteres → 400; audit `users.create`.
- `PATCH /{id}` — `{username?, role?, is_active?}` → 200; 404; username duplicado → 409;
  **proibido alterar role/is_active da própria conta** (403 "Não é possível alterar a
  própria conta." — evita lockout acidental); audit `users.update`.
- `POST /{id}/password` — `{password}` → 204; valida mínimo 8; audit `users.reset_password`
  (senha fora da trilha — `mascarar` já cobre chaves com "password" no nome).
- Sem DELETE: desativação por `is_active=false`, que invalida imediatamente as sessões
  (check no `require_actor`).

`UserOut`: `{id, username, role, is_active, last_login_at, created_at}` — **nunca**
`password_hash` (nem da própria conta).

### 4.6 CLI (`gerenet/cli/users.py`, registrado em `cli/main.py`)

- `gerenet users create <username> --role <role>` — senha via prompt oculto (2x,
  `typer.prompt(password=True)`); sem senha em argv/log; valida role e mínimo 8.
- `gerenet users set-password <username>` — prompt oculto.
- `gerenet users list [--include-disabled]`.
- Constrói o primeiro admin: `gerenet users create admin --role administrador`.

## 5. API — dashboard e jobs

### 5.1 `GET /api/v1/dashboard` (`gerenet/api/dashboard.py`, auth `require_actor`)

Resposta `DashboardOut` (agregações server-side; campos exatos):

Chaves em inglês snake_case, como os `*Out` do repo (padrão P3):

```json
{
  "devices": {"total": 3, "active": 3, "with_snapshot": 2, "by_comm_status": {"ok": 2, "fail": 1}},
  "per_device": [
    {"device_id": 1, "name": "r1-lab", "site_id": 1, "site_name": "GRU",
     "comm_status": "ok", "last_collected_at": "...", "snapshot_age_seconds": 3600,
     "latest_snapshot": {"id": 9, "status": "success", "started_at": "..."},
     "active_job": {"id": 12, "status": "running"} }
  ],
  "bgp_sessions": {"total": 8, "active": 6, "shutdown": 2},
  "circuits": {"total": 4, "active": 4},
  "vlans": {"reserved": 5, "freed": 1},
  "ip_prefixes": {"reserved": 6, "freed": 0},
  "recent_audit": [ ...20 AuditEventOut mais recentes... ]
}
```

`job_em_andamento` = job kind `collect` com status `queued|running` do device (ou null);
`snapshot_mais_recente` = snapshot de maior id. Agregações só sobre `admin_status`/status
reais do modelo (§2); nenhuma chamada a `reconciliar_device` aqui.

### 5.2 Jobs (`gerenet/api/jobs.py`, read-only, auth `require_actor`)

- `GET /api/v1/jobs` — lista `JobRunOut` (ordenado por id desc; filtros `device_id`,
  `status`, `kind`; `limit`/`offset` no padrão do P3).
- `GET /api/v1/jobs/{id}` — 404 "Job não encontrado." quando ausente.
- `POST /api/v1/devices/{id}/collect` — retorno atual ganha `job_id` (chave nova no dict
  existente; sem quebra — `{"queued": true, "message": ..., "job_id": 12}`).

`JobRunOut`: `{id, device_id, origin, actor, kind, status, started_at, finished_at,
duration_ms, snapshot_id}`.

## 6. Frontend

### 6.1 Projeto `web/`

- Template Vite + React + TS estrito, sem aliases especiais além de `@/` → `src/`.
- Deps: `react@18`, `react-dom@18`, `react-router-dom@7`, `@tanstack/react-query@5`;
  dev: `vite`, `typescript`, `vitest`, `jsdom`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/user-event`, `@playwright/test`,
  `eslint` (+ `typescript-eslint`), `prettier`.
- `vite.config.ts`: plugin react + `server.proxy {"/api": "http://localhost:8000"}` +
  config do vitest (jsdom, globals).
- Scripts: `dev`, `build`, `preview`, `test` (vitest run), `test:e2e` (playwright test),
  `lint`, `format`.

### 6.2 Camada de dados

- `src/api/client.ts`: `apiFetch<T>(path, {method, body})` com `credentials: "include"`,
  Content-Type JSON quando houver corpo, `ApiError{status, mensagem}` tipado:
  - 400/404/409/422 → mensagem `detail` (string ou lista de erros de validação → texto
    amigável PT-BR, erros por campo);
  - 401 (exceto em `/auth/login`) → `onUnauthorized()` (limpa estado, redireciona `/login`);
  - falha de rede → "Servidor indisponível. Tente novamente.";
  - secrets: o client não envia nem imprime senha (payload do login nunca é logado).
- `src/api/types.ts`: tipos TS escritos à mão espelhando os `*Out` do Pydantic (sem codegen
  de OpenAPI no MVP — os contratos são pequenos e o client testa os mapeamentos).
- TanStack Query: `useQuery` por recurso (`["devices"]`, `["circuit", id]`…), `useMutation`
  com `queryClient.invalidateQueries` no sucesso; `retry: 1`; `staleTime` curto.

### 6.3 Telas (todas PT-BR; `RequireAuth` exceto `/login`; `/users` só admin)

| Rota | Tela | Notas |
|---|---|---|
| `/login` | Login | erro único "Usuário ou senha inválidos."; redireciona ao destino previsto |
| `/` | Dashboard | cards: devices por status/idade, sessões, circuitos, uso de VLAN/prefixos; tabela `per_device` com badge de status, idade, job em andamento e ações (coletar / snapshot / reconciliar / desired-config); últimos eventos de auditoria |
| `/devices` | lista + cadastro/edição/desativação | `admin_status` com confirmação; action "Coletar agora" |
| `/devices/:id` | detalhe | informações + último snapshot (resumo), botão coleta (poll do job §5.2), links para desired-config/reconcile/snapshots |
| `/sites` | CRUD | campos do modelo + p2p blocks |
| `/organizations` | CRUD | filtro kind; seção downstreams do cadastro (§6.6) |
| `/contacts` | CRUD | select de organização |
| `/circuits` + `/:id` | CRUD + detalhe | detalhe: contexto (org, site, devices), VLans/IpPrefixes reservados, botão "Reservar recursos" (POST do endpoint de reserva existente), `edge_trunk` (pós-B2), sessões BGP do circuito |
| `/bgp-sessions` + `/:id` | CRUD + detalhe | detalhe: associação de communities (POST/DELETE do B2), "Definir senha" (envia ao Vault; nunca exibe `password_ref` de volta — só o indicador `has_password`) |
| `/policy-profiles` | leitura | catálogo read-only; filtro direction (import/export) |
| `/prefix-authorizations` | CRUD | family + prefixo; desativação |
| `/communities` | leitura | catálogo read-only |
| `/snapshots` | visualização | seletor de device → lista → detail JSON (`resources`) em viewer read-only com colapsável por chave top-level |
| `/desired-config` | visualização | seletor de device → `GET /devices/{id}/desired-config` → blocos em acordeão por tipo (subinterface, prefix-list, route-policy, peer…) + texto mono + botão copiar; vazio → aviso "Nenhum bloco renderizado." |
| `/reconcile` | visualização | seletor (device ou snapshot_id via campo) → tabela `{tipo, severidade, esperado, encontrado, acao}` com filtro por severidade; aviso quando snapshot ausente; read-only |
| `/jobs` + `/:id` | leitura | filtros device/status/kind; detalhe com timing e snapshot resultante |
| `/audit-events` | leitura | filtros tipo/ator/objeto + paginação; `details` expansível (antes/depois) |
| `/users` | administração | lista com `include_disabled`; criar (role+senha), alterar role/is_active (exceto conta própria), resetar senha |

Formulários: um componente `FormField` por tipo (text/select/checkbox/textarea) com erro
por campo (mapeando `loc` do 422); `ConfirmDialog` para toda desativação; tabelas
`DataTable` genérica (colunas/linhas/estado vazio/loading/ações); `StatusBadge`
(ok/fail/unknown, success/partial/error, queued/running, ativo/inativo) e `SeverityBadge`
(crítica/atenção/aviso) com cores por token.

### 6.4 Estilo

Dark-first: tokens em `:root` (cores, espaçamentos, fonte), `prefers-color-scheme: light`
atende o modo claro; fonte mono para config/comandos; tabelas densas com timestamps
formatados ("há 2h", "há 3d"); acessível por contraste básico. **Sem biblioteca visual**
no v1 (YAGNI: componentes próprios com menos de ~6 estilos cada); criar tokens apenas
quando um terceiro uso aparecer.

## 7. Execução e deploy

- **Dev**: `docker compose up -d` (db/redis/vault) → `alembic upgrade head` →
  `uv run uvicorn gerenet.api.main:create_app --factory` (:8000) → `cd web && npm install &&
  npm run dev` (:5173, proxy `/api` → :8000). Sem CORS em dev (proxy de mesma origem).
- **Prod/local**: `npm run build` → `web/dist`; o FastAPI monta o estático e serve o
  `index.html` como fallback SPA para rotas que não começam com `/api` (e `/healthz`),
  com assets versionados por hash e cache imutável. `static_dir` vem de settings
  (`GERENET_STATIC_DIR`).
- **Cookies sob TLS**: `GERENET_COOKIE_SECURE=true` em produção HTTPS (documentado no
  README); compose.yaml não muda neste ciclo.
- **`.gitignore`**: `web/node_modules/`, `web/dist/`, `web/playwright-report/`,
  `web/test-results/`.
- **README**: seção "Interface web — dev e build" (run-book acima).

## 8. Segredos e segurança

- Senha de usuário: só `password_hash` (scrypt); nunca em log, resposta, snapshot ou
  auditoria (`mascarar` já cobre por nome de campo).
- Login: payload nunca logado; falha não distingue usuário inexistente/inativo/senha errada.
- Cookie: token opaco, HttpOnly, SameSite=Lax; banco guarda só o hash; expiração fixa (sem
  sliding no v1 — débito).
- CSRF: SameSite=Lax + contrato JSON (escrita exige `Content-Type: application/json`, que
  requisição cross-site não envia sem preflight) — base defensiva documentada; hardening
  posterior (token anti-CSRF) se o SameSite não bastar.
- A chave de API permanece para CLI/automações; o front **nunca** a recebe.
- Client-side: nenhum segredo em `localStorage`/`sessionStorage`; token só no cookie
  HttpOnly.

## 9. Testes

### Backend (pytest, padrão do repo)

- `tests/api/test_auth_api.py`: login ok (cookie + `UserOut` + `auth.login` na trilha);
  401 senha errada (mensagem única, `auth.login_failed` gravado); logout 204 (cookie
  limpo + sessão removida); `/me` 200/401; sessão expirada → 401 + remoção lazy; usuário
  desativado → login 401, sessão existente → 403.
- `tests/api/test_users_api.py`: 401 sem auth; 403 não-admin (todos os métodos); lista
  default ativos + `include_disabled`; create 201 (sem hash na resposta; duplicado 409;
  senha curta 400); patch (role/is_active, conta própria 403, 404); reset de senha (204 +
  novo login funciona); desativar invalida sessão.
- `tests/api/test_dashboard_api.py`: 401 sem auth; agregados com fixtures (device
  ok/fail/unknown, snapshots success/error, job queued/running, sessões ativas/shutdown,
  circuits, vlans/prefixes reservados/liberados, audit_ultimos limitado).
- `tests/api/test_jobs_api.py`: listagem + filtros (device_id/status/kind) + 404 no detalhe;
  `job_id` presente no 202 do collect.
- `tests/api/test_actor_sessao.py` (ou nos existentes): GET autenticado por cookie funciona
  (dual); escrita via cookie grava `actor=username` na auditoria; via X-Api-Key continua
  `"api"`; `Visualizador` recebe 403 em POST/PATCH/DELETE/POST-collect.
- Domain: `tests/domain/test_users_service.py` — código do hash por salt único, verify
  ok/errada, hash corrompido → falha limpa (sem crash), role validado, username único,
  mínimo 8.
- CLI: `test_cli_smoke.py` — `users create` (prompt monkeypatched), `set-password`, `list`.

### Frontend

- Vitest (jsdom): `client.ts` (status→mensagem/campo, 401→redirect, rede) com fetch mockado;
  `RequireAuth`; `StatusBadge`/`SeverityBadge` (variantes); `DataTable` (vazio/loading/
  ações); `Login` (submit, erro, sem log de senha); `Reconcile` (itens mock, filtro por
  severidade, aviso de snapshot ausente); formulários de Users (validações).
- Playwright (fumos, `web/tests/e2e/`): exige a stack local (compose + `alembic upgrade
  head` + uvicorn) e dados seedados (usuário via CLI; device+snapshot via script de setup
  que insere a partir de fixtures sanitizadas existentes); fluxos: login ok → dashboard;
  login inválido → erro; criar/desativar site; abrir Reconcile com device+snapshot;
  logout. O smoke **não** substitui o pytest; roda localmente/documentado (CI quando
  existir).

## 10. Fronteiras e débitos herdados

- Assistente de downstream §16.2 e MPLS §16.3: dependem do motor de mudanças (ciclo D) —
  as telas dessa spec são a fundação (usuários, perfis, sessões, dashboards).
- Divergências no dashboard (contagem por severidade): F6 (reconciliação agendada).
- Sessões: sliding de TTL, rate limit de login, lockout, 2FA, revogação de sessão
  individual/lista — débitos anotados (mais relevantes quando o motor de mudanças chegar).
- Sessões em Redis (hoje em banco): migrar só se houver necessidade real de escala.
- `reconcile` e `desired-config` são read-only na UI — coerente com o ciclo B.
- Documentação: atualizar CLAUDE.md/README, que hoje descrevem o repo como "sem código"
  (desatualizado desde o ciclo A) e não mencionam o run-book da web — incluir neste ciclo
  como tarefa de docs.
- Sem i18n, sem modo manual de tema, sem responsividade fina (tabelas com scroll
  horizontal) — aceitável para operadores em desktop.

## 11. Riscos

- **Escopo**: ~20 telas. Mitigação: componentes genéricos (DataTable/FormField/StatusBadge)
  + plan em tasks por área (auth → admin → dashboard/jobs → CRUD → especializadas) no
  padrão SDD; telas derivam mecanicamente do Pydantic.
- **Troca `require_api_key` → `require_actor`**: mudança em todos os routers. Mitigação:
  caminho da chave e mensagens 401/403 preservados — os testes atuais protegem a
  compatibilidade; a troca é mecânica (sed + revisão).
- **Conflito com o ciclo B em andamento**: ciclo C inicia **após o merge do B2**; a spec
  assume head pós-B2 (endpoints de communities/reconciliation/desired-config, `edge_trunk`).
  A migration usa o head vigente da data do plano.
- **Snapshot `resources` grande na tela**: viewer com colapso por chave e paginação de
  arrays (peers 60+ linhas) — sem renderizar todo o JSON de uma vez.
- **Playwright frágil/estimulante**: fumos mínimos e determinísticos (dados seedados), não
  suíte ampla de e2e.
- **Node toolchain novo**: só os desenvolvedores rodam build; o deploy continua servindo
  estático pelo Python (Node não vira requisito de runtime).

## 12. Critérios de aceite do ciclo C

1. Login/sessão/logout funcionam; API key continua funcionando em todos os endpoints
   antigos (CLI + automações intactos; suíte backend verde sem editar testes de
   compatibilidade).
2. Auditoria registra o autor real (`username`) em escritas via sessão; login/logout são
   auditáveis. Nunca há hash/senha em logs, respostas ou trilha.
3. `Visualizador` não escreve (403) e todos os demais perfis escrevem.
4. Dashboard abre com dados reais do banco (sem chamada N+1 do front).
5. Todas as entidades da API têm tela de listagem + criação + edição + desativação;
   catálogos (policy-profiles, communities) são somente leitura.
6. Snapshot / desired-config / reconcile navegáveis com o B2; coleta dispõe job e poll de
   status; falhas aparecem com mensagem amigável PT-BR.
7. Nenhum segredo no front (token só no cookie HttpOnly; senha nunca persiste no browser).
8. Playwright fumos verdes e Vitest cobrindo client/componentes críticos; `ruff` e lint TS
   limpos.
