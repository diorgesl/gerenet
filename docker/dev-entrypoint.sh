#!/bin/sh
set -e

# Aplica migrações antes de servir — idempotente; só o serviço api roda com
# RUN_MIGRATIONS=true para evitar corridas de alembic em banco novo.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    uv run alembic upgrade head
fi

exec "$@"
