"""O `commit=False` que a adoção usa para caber numa transação só (design §3)."""
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


def test_organizacao_com_commit_false_nao_grava_antes_do_commit(db_session) -> None:
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Sem Commit"), actor="cli", commit=False
    )
    # o flush e a auditoria continuam acontecendo, dentro da transação do chamador
    assert org.id is not None
    assert db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "organization.create")
    ) is not None
    db_session.rollback()
    assert db_session.scalar(
        select(models.Organization).where(models.Organization.name == "Cliente Sem Commit")
    ) is None


def test_organizacao_no_default_grava_como_sempre(db_session) -> None:
    create_organization(db_session, OrganizationCreate(name="Cliente Com Commit"), actor="cli")
    # o rollback descarta o que estivesse só flushado: o que sobrar foi commitado
    db_session.rollback()
    assert db_session.scalar(
        select(models.Organization).where(models.Organization.name == "Cliente Com Commit")
    ) is not None


def _ambiente(db_session):
    """Site, organização e equipamento: `CircuitCreate` exige device de acesso e edge."""
    site = create_site(db_session, SiteCreate(name="pop-commit"), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="Org Commit", asn=64700), actor="cli")
    dev = create_device(
        db_session,
        DeviceCreate(name="ne-commit", management_address="10.9.9.9", asn=65001, site_id=site.id),
        actor="cli",
    )
    return site, org, dev


def test_circuito_com_commit_false_nao_grava_antes_do_commit(db_session) -> None:
    site, org, dev = _ambiente(db_session)
    circ = create_circuit(
        db_session,
        CircuitCreate(code="CIRC-SEM-COMMIT", organization_id=org.id, site_id=site.id,
                      access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id),
        actor="cli", commit=False,
    )
    # o flush e a auditoria continuam acontecendo, dentro da transação do chamador
    assert circ.id is not None
    assert db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "circuit.create")
    ) is not None
    db_session.rollback()
    assert db_session.scalar(
        select(models.Circuit).where(models.Circuit.code == "CIRC-SEM-COMMIT")
    ) is None


def test_sessao_com_commit_false_nao_grava_antes_do_commit(db_session) -> None:
    site, org, dev = _ambiente(db_session)
    circuito = create_circuit(
        db_session,
        CircuitCreate(code="CIRC-SESSAO", organization_id=org.id, site_id=site.id,
                      access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id),
        actor="cli",
    )
    sessao = create_session(
        db_session,
        BgpSessionCreate(circuit_id=circuito.id, device_id=dev.id, afi="ipv4",
                         local_address="100.64.90.0", remote_address="100.64.90.1",
                         asn_remote=64700),
        actor="cli", commit=False,
    )
    # o flush e a auditoria continuam acontecendo, dentro da transação do chamador
    assert sessao.id is not None
    assert db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "bgp_session.create")
    ) is not None
    db_session.rollback()
    assert db_session.scalar(
        select(models.BgpSession).where(models.BgpSession.remote_address == "100.64.90.1")
    ) is None
