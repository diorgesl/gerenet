# Imagem de produção: a SPA é construída no estágio Node e o `dist` entra no
# estágio Python, que serve tudo (API + SPA + wiki) num processo só.
#
# Ao contrário da imagem de dev (Dockerfile.dev), esta não monta código, não
# traz as dependências de teste e não usa `--reload`.
FROM node:22-alpine AS web

WORKDIR /srv/web

# Manifestos primeiro (cache de camada)
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build


FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /srv/app

# `alembic`, `uvicorn`, `gerenet` e `gerenet-worker` vêm do venv (mesmo PATH da
# imagem de dev, para os comandos de operação valerem nos dois casos).
ENV PATH="/srv/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

# O cliente `whois` é chamado por subprocess em `automation/irr.py`
# (`identificar_asn` e `consultar`); a imagem slim não o traz. Sem ele a
# consulta ao registro falha com FileNotFoundError e a api responde 503.
RUN apt-get update && \
    apt-get install -y --no-install-recommends whois && \
    rm -rf /var/lib/apt/lists/*

# Manifestos primeiro; o projeto em si instala depois do src (cache de camada —
# mexer em código não obriga a reinstalar as dependências).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev

# Os dois caminhos abaixo são lidos em runtime, relativos ao CWD (/srv/app):
# `static_dir` aponta para web/dist (SPA) e `wiki_dir` para docs/wiki.
COPY docs/wiki ./docs/wiki
COPY --from=web /srv/web/dist ./web/dist

COPY docker/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint && \
    mkdir -p /srv/app/data/backups && \
    useradd --uid 1000 --create-home gerenet && \
    chown -R gerenet:gerenet /srv/app

# O diretório de backups é montado pelo compose por cima deste caminho;
# o volume/diretório do host precisa pertencer ao uid 1000 (runbook).
USER gerenet

EXPOSE 8000

# Aplica as migrações quando RUN_MIGRATIONS=true (só a api do compose liga).
ENTRYPOINT ["/usr/local/bin/entrypoint"]

CMD ["uvicorn", "gerenet.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
