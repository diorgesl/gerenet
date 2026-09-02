# gerenet

Gerenciador de Rede Huawei VRP (spec: `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`).
Fase 1: inventário e coleta read-only.

## Desenvolvimento

- Infra: `docker compose up -d` (postgres, redis, vault dev)
- App: `cp .env.example .env`; `uv run uvicorn gerenet.api.main:create_app --factory --reload --port 8000`
- Testes: `uv run pytest`
