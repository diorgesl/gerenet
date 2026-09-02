import os

# A suíte TRUNCATE o banco a cada teste: nunca rodar contra o banco dev.
# GERENET_DATABASE_URL do shell não vale aqui — override explícito via
# GERENET_TEST_DATABASE_URL (para CI), default gerenet_test.
_TEST_DATABASE_URL = os.environ.get("GERENET_TEST_DATABASE_URL") or (
    "postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test"
)
if "test" not in _TEST_DATABASE_URL.rsplit("/", 1)[-1]:
    raise SystemExit(
        "GERENET_TEST_DATABASE_URL deve apontar para um banco de teste "
        "(ex.: .../gerenet_test); a suíte TRUNCATE o banco a cada teste."
    )
os.environ["GERENET_DATABASE_URL"] = _TEST_DATABASE_URL

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from gerenet.config import Settings, set_settings
from gerenet.db import SessionLocal
from gerenet.domain import models  # noqa: F401


@pytest.fixture()
def db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _limpa_tabelas(db_session: Session) -> None:
    yield
    db_session.execute(
        text(
            "TRUNCATE audit_events, job_runs, device_snapshots, devices, credential_groups RESTART IDENTITY CASCADE"
        )
    )
    db_session.commit()


@pytest.fixture(autouse=True)
def _reseta_settings() -> None:
    yield
    set_settings(Settings())
