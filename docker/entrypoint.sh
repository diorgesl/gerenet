#!/bin/sh
set -e

# Aplica migrações antes de servir — idempotente; só a api roda com
# RUN_MIGRATIONS=true para evitar corridas de alembic em banco novo.
#
# `alembic` vem do venv, que as duas imagens (dev e produção) põem no PATH.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    alembic upgrade head
fi

exec "$@"
