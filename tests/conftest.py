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
    # Catálogos (bgp_policy_profiles, communities) ficam de fora de propósito:
    # são seedados pela migration e imutáveis no ciclo A (ruling 2 do Plano 2).
    db_session.execute(
        text(
            "TRUNCATE approvals, change_steps, change_requests, audit_events, user_sessions, users, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations, vsi_members, vsi_services, service_endpoints, l2vc_services, mpls_domain_members, mpls_domains RESTART IDENTITY CASCADE"
        )
    )
    db_session.commit()


@pytest.fixture(autouse=True)
def _reseta_settings() -> None:
    yield
    set_settings(Settings())
