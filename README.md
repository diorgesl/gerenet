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
disponível. O conteúdo vive em `docs/wiki/` (10 páginas) e é editado via PR
(renderização server-side com `markdown` + sanitização `nh3` — o HTML vem
sanitizado do servidor; nenhum markdown é renderizado no cliente). Cada página usa frontmatter
`title`/`secao`/`order`/`em_breve` — `em_breve: true` mostra o aviso
"Recurso planejado — não disponível ainda." no topo da página.
