# Fumos e2e da interface web (Playwright)

Os 10 fumos (3 de login + 3 de smoke + 1 de mudança + 1 de MPLS + 1 de
upstream + 1 de credencial) exercitam a SPA real contra o backend real
(FastAPI + PostgreSQL) — sem mocks. Rodam tudo por um único comando:

```bash
# 0. Infra local (postgres, redis, vault) — uma vez
docker compose up -d

# 1. Banco — fluxo padrão do dev (banco default `gerenet`)
uv run alembic upgrade head

# 2. Navegador do Playwright — uma vez (download do Chromium)
cd web
./node_modules/.bin/playwright install chromium
# — ou, se o download falhar (CDN do Playwright inacessível), instale o
#   Google Chrome do sistema e rode os fumos com GERENET_E2E_CHANNEL=chrome
#   (o config usa o canal "chrome" apenas com essa env)

# 3. (obrigatório, antes de cada execução) parar a API e o worker do compose —
#    são os nomes de SERVIÇO (`api`/`worker`; `gerenet-api`/`gerenet-worker`
#    são apenas os nomes dos containers). Motivos: a API ocupa a porta 8000
#    (com `reuseExistingServer: false`, qualquer processo nela é **falha dura**
#    no boot do webServer) e o worker, se ativo, consumiria o job da fila
#    `gerenet-change` no meio do fumo e derrubaria o assert final
#    `executando` do change.spec.ts — a CR só permanece `executando` com o
#    worker parado ("jobs fake" do spec §10).
docker compose stop api worker

# 4. Rodar os fumos (build da SPA + uvicorn + seed automático + specs)
# (máquina fresca: primeiro crie/migre o banco dedicado — ver a seção
#  "Banco dedicado `gerenet_e2e`" abaixo, passos 1-2)
GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_e2e" \
E2E_PASSWORD="e2e-super-8" npm run test:e2e

# 5. (obrigatório, depois dos fumos) restaurar a stack
docker compose start api worker
```

## O que o comando faz

- `playwright.config.ts` sobe um webServer: `npm run build` (`web/dist` — a SPA
  só é servida pelo FastAPI com o build presente) e depois o uvicorn **a partir
  da raiz do repositório** (`cd ..` antes de `uv run uvicorn ...`; o webServer
  roda com CWD em `web/`, e `static_dir` (`web/dist`) é um caminho relativo ao
  CWD — subido de `web/` a API não registraria o fallback SPA e `/login`
  devolveria `{"detail":"Not Found"}`), com `reuseExistingServer: false`
  (**falha dura**: se houver algo na porta 8000, o smoke morre já no boot —
  nunca reusa o uvicorn de dev, que apontaria para o banco default `gerenet`;
  antes de rodar, garantia: nada escutando na 8000 — por exemplo, pare o
  uvicorn de dev).
- `e2e/setup.ts` é o **globalSetup**: roda automaticamente antes dos specs e
  é **idempotente** (repetir a execução não duplica o seed):
  - usuários `admin` (`administrador`) e `e2e-aprovador` (`aprovador`) via
    `uv run gerenet users list`/`create` — senha `E2E_PASSWORD` no stdin;
    criados **só se ausentes** (prompt oculto — nunca em argv). O aprovador é
    distinto do solicitante — o fumo de mudança (spec §3.3) solicita como
    `admin` e aprova como `e2e-aprovador`;
  - site `e2e-site-01`, device `ne8000-01`, organização
    `e2e-cliente-downstream`, circuito `e2e-circ-01` e autorização de prefixo
    `192.0.2.0/24` via API com `X-Api-Key` (`GERENET_API_KEY` ou
    `dev-key-change-me`). POST que devolve 409 (já existe) segue em frente;
  - fase 5 (upstreams): organização operadora `e2e-operadora-tier1`
    (kind `operadora`), upstream `e2e-upstream-tier1` (trânsito — fixtures
    estáveis, sem vínculos), circuito `e2e-circ-operadora-01` + sessão BGP
    V4 par `10.99.128.1/2` e community `prepend`/Região Sul — checados
    antes de POSTar (padrão do prefix-authorization, sem 409 como controle).

## Banco dedicado `gerenet_e2e`

Os e2e usam o banco dedicado **`gerenet_e2e`** — **nunca** o banco default
`gerenet` nem `gerenet_test*`. Em máquina fresca, os passos únicos (o compose
só cria o default `gerenet`):

```bash
docker compose exec db createdb -U gerenet gerenet_e2e
GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_e2e" \
  uv run alembic upgrade head
```

A variável `GERENET_DATABASE_URL` deve estar no processo do `npm run test:e2e`:
o uvicorn do webServer, o CLI do seed e o globalSetup herdam o mesmo ambiente.
Sem ela, o uvicorn cai no banco default dev, e o seed pode tocar dados de
desenvolvimento.

Fluxo padrão do dev sem e2e: `uv run alembic upgrade head` contra o banco
default (`postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet`).

Os fumos acumulam objetos entre execuções no banco dedicado (device/circuito/
sessão e CR por rodada, CRs deixadas em `executando`, jobs órfãos na fila RQ
`gerenet-change` e a CR/circuito/sessão da rodada que falhou): inofensivo por
design — o banco é dedicado, o seed e o fumo são rerun-safe (nada deles
reutiliza esses objetos) e um job órfão consumido depois pelo worker é no-op
(aponta para uma CR que só existe no `gerenet_e2e`).

## Erros comuns

| Sintoma | Causa provável / solução |
| --- | --- |
| `Executable doesn't exist at ...` | rodar o passo 2 (`playwright install chromium`); se o download falhar (`Download failure, code=1`), o CDN do Playwright está inacessível na rede — instalar o Google Chrome do sistema e rodar com `GERENET_E2E_CHANNEL=chrome` (o config só usa o canal "chrome" com essa env) |
| `Error: reuseExistingServer` / port 8000 ocupada | outro processo já escuta na 8000 (uvicorn de dev, IDE…) — **pare-o** e rode de novo; o webServer agora falha duro, sem reutilizar |
| `Timed out waiting 60000ms from config.webServer` | subiu com o banco fora do ar — verificar `docker compose ps` (porta 8000 ocupada hoje é falha dura no boot: ver `Error: reuseExistingServer` acima) |
| login falha com "Usuário ou senha inválidos" | o `admin` **ou** o `e2e-aprovador` do banco `gerenet_e2e` tem senha de outra execução — resetar o usuário com `GERENET_DATABASE_URL="postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_e2e" uv run gerenet users set-password <usuário>` (substitua por `admin` ou `e2e-aprovador`; sempre com a env! sem ela o reset cai no banco de dev) e usar o mesmo valor de `E2E_PASSWORD` |
| testes passam mas o seed parece vazio | conferir `GERENET_DATABASE_URL` apontando para `gerenet_e2e` no mesmo comando |

## Specs

- `login.spec.ts` — login ok → Dashboard; senha errada → "Usuário ou senha
  inválidos."; logout → volta ao `/login`. Cada teste roda em contexto limpo.
- `smoke.spec.ts` — criar e desativar um site pela UI; abrir a Reconciliação
  com o device seedado `ne8000-01` e conferir que a superfície renderiza
  (aviso `role="status"`, tabela ou "Nenhuma divergência encontrada."); abrir
  o wiki pelo menu Ajuda (rota `/wiki`) e conferir o tooltip de um campo de
  formulário.
- `change.spec.ts` — fluxo de mudança (ciclo D): cria equipamento/circuito/
  sessão BGP (API, rerun-safe), solicita a mudança pela UI no detalhe do
  circuito, envia para aprovação, aprova como `e2e-aprovador` (o admin não
  pode aprovar o próprio pedido) e executa como admin — sem worker, a CR
  fica `executando` com o job na fila Redis.
- `upstream.spec.ts` — fase 5: cria organização operadora pela página de
  Organizações (R-27 — kind `operadora` no select), upstream pelo dialog
  (trânsito, operadora), device/circuito/sessão BGP novos (API, rerun-safe),
  vincula o circuito pela UI (matriz principal × contingência), adiciona a
  community `prepend`/Região Sul pelo dialog e solicita a CR de escopo
  `upstream` no detalhe — aprovada pelo `e2e-aprovador` (usuário distinto).

Relatório: `playwright-report/` (html) e artefatos em `test-results/`
(ambos ignorados pelo git).
