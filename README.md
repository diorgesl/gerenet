# gerenet

Gerenciador de Rede Huawei VRP (spec: `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`).
Fase 1: inventário e coleta read-only.

## Desenvolvimento

- Infra: `docker compose up -d` (postgres, redis, vault dev)
- App: `cp .env.example .env`; `GERENET_DATABASE_URL=… uv run alembic upgrade head`; `uv run uvicorn gerenet.api.main:create_app --factory --reload --port 8000`
- Testes: `uv run pytest`

## Docker — dev completo (compose)

Tudo (db, redis, vault, API, worker e frontend) com um comando, sem instalar
Python/Node na máquina (só Docker):

```bash
docker compose up -d --build
```

- **API** (FastAPI, hot reload) em `http://localhost:8000` — migrações rodam no
  start (`alembic upgrade head`, somente no serviço `api`);
- **Frontend** (Vite + HMR) em `http://localhost:5173`, com `/api` proxyado
  para o serviço `api` (`VITE_API_PROXY_TARGET`);
- **Worker** RQ conectado ao redis.

Primeiro uso: criar o usuário admin
`docker compose exec api gerenet users create admin --role administrador`
(senha por prompt — nunca em argv).

Comandos dentro do container:
`docker compose exec api uv run pytest -q`,
`docker compose exec api gerenet …`, `docker compose logs -f api web`.

Ao alterar `pyproject.toml`/`Dockerfile.dev` (dependências), recriar:
`docker compose up -d --build`.

Observabilidade de dev: `docker compose up -d prometheus grafana` sobe o
Prometheus (http://localhost:9090) e o Grafana (http://localhost:3000, leitura
anônima como viewer e o login de admin do primeiro boot para editar e exportar)
com o dashboard `gerenet — operação` provisionado, raspando `api:8000/metrics` a
cada 30 s. A plataforma expõe os itens do §20.1 no `/metrics`, sem autenticação
na rede de gerência; ligar o `GERENET_METRICS_TOKEN` pede duas edições (a
variável no serviço `api` e o token no scrape, por arquivo montado de fora do
repositório), descritas no runbook de observabilidade. O worker do compose já
sobe com a coleta periódica ligada (`GERENET_COLLECT_INTERVAL_MINUTES: "60"` —
coleta a frota do banco dev a cada hora; `"0"` desliga), com as regras em
`/wiki/equipamentos`.

⚠️ **`npm run test:e2e` (host): pare o compose antes** — o Playwright sobe o
próprio uvicorn na :8000 e usa o banco dedicado `gerenet_e2e`; a api do compose
ocupando a porta/banco de dev quebra esse fluxo.

## Autenticação web (ciclo C)

- Login local com perfis §17: `gerenet users create admin --role administrador` (senha por
  prompt — nunca em argv); a API key continua valendo para CLI/automações
  (`X-Api-Key`).
- Cookie de sessão `gerenet_sess` (HttpOnly, SameSite=Lax). Em produção sob HTTPS:
  `GERENET_COOKIE_SECURE=true`.
- A interface web (`web/`, ciclo C2) é servida pelo próprio FastAPI a partir de
  `web/dist`; em desenvolvimento, `cd web && npm install && npm run dev` proxya
  `/api` → :8000.

## Interface web — dev e build

- **Dev** (hot reload, dois processos): API `uv run uvicorn gerenet.api.main:create_app --factory --port 8000` + SPA `cd web && npm run dev` (Vite proxia `/api` → :8000).
- **Prod/local completo**: `cd web && npm run build` → `web/dist` servido pelo próprio FastAPI (fallback SPA; sem build, as rotas da aplicação não são atendidas). Servir o FastAPI sob HTTPS em produção: `GERENET_COOKIE_SECURE=true` (ver autenticação acima).
- **Testes**: `cd web && npm run test` (Vitest, componentes). Fumos end-to-end: `cd web && npm run test:e2e` (Playwright — sobe build + uvicorn, roda o seed automático e idempotente; ver `web/e2e/README.md`).

## Wiki operacional (ciclo E)

Após o build da SPA (ou no dev com a API rodando), o operador autenticado acessa
`/wiki` (menu "Ajuda") para ler a documentação operacional; a sidebar agrupa as
páginas por seção e marca com "(em breve)" as que ainda não têm recurso
disponível. O conteúdo vive em `docs/wiki/` (12 páginas, contando as de `em-breve/`) e é editado via PR
(renderização server-side com `markdown` + sanitização `nh3` — o HTML vem
sanitizado do servidor; nenhum markdown é renderizado no cliente). Cada página usa frontmatter
`title`/`secao`/`order`/`em_breve` — `em_breve: true` mostra o aviso
"Recurso planejado — não disponível ainda." no topo da página.

## Descoberta na configuração — "Migrar" (partes 1 e 2)

A página `/discovery` (menu Operação, "Migrar") e o grupo
`gerenet discovery list|show|ignore|unignore|adopt` leem o `display
current-configuration` já coletado e mostram o que o equipamento tem que a SoT
ainda não conhece. A **parte 1** é a leitura: nenhum comando vai ao equipamento
por esses caminhos, e a lista de ignorados (na SoT) era a única escrita. A
**parte 2** é a adoção — a revisão de uma proposta na página, ou `gerenet
discovery adopt <equipamento> <peer> --json <arquivo>`, grava organização,
circuito, reservas (nos valores reais da configuração) e sessões **numa
transação só**, com a conferência de fidelidade na frente e o `ciente` quando
ela achar diferença que mudaria o equipamento. Adotar não manda comando nenhum:
mudar o roteador continua sendo change request. Operação:
`docs/wiki/descoberta.md`; validação contra um NE8000 real (com a adoção num
equipamento não crítico e o rollback ao lado):
`docs/runbook-validacao-ne8000.md`.
