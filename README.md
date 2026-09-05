# gerenet

Gerenciador de Rede Huawei VRP (spec: `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`).
Fase 1: inventário e coleta read-only.

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

## Interface web — dev e build

- **Dev** (hot reload, dois processos): API `uv run uvicorn gerenet.api.main:create_app --factory --port 8000` + SPA `cd web && npm run dev` (Vite proxia `/api` → :8000).
- **Prod/local completo**: `cd web && npm run build` → `web/dist` servido pelo próprio FastAPI (fallback SPA; sem build, as rotas da aplicação não são atendidas). Servir o FastAPI sob HTTPS em produção: `GERENET_COOKIE_SECURE=true` (ver autenticação acima).
- **Testes**: `cd web && npm run test` (Vitest, componentes). Fumos end-to-end: `cd web && npm run test:e2e` (Playwright — sobe build + uvicorn, roda o seed automático e idempotente; ver `web/e2e/README.md`).
