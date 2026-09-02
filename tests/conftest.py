import os

os.environ.setdefault(
    "GERENET_DATABASE_URL",
    "postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet_test",
)

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
