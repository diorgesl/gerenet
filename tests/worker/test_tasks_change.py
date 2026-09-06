"""enqueue_change (spec §6.6): validação, dedup e lock antes da fila gerenet-change."""
import pytest
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from gerenet.config import Settings
from gerenet.domain.schemas import (
    BgpSessionCreate,
    ChangeRequestCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services import change_requests as crsvc
from gerenet.domain.services import users as usvc
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device
from gerenet.worker.tasks import enqueue_change


@pytest.fixture()
def fila_limpa() -> Redis:
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    fila = Queue("gerenet-change", connection=r)
    fila.empty()  # limpa antes e depois: a suíte não deixa jobs órfãos p/ o worker dev
    r.delete("gerenet:lock:change:1")
    yield r
    fila.empty()


def _cr(db_session: Session, *, aprovada: bool = False) -> int:
    """Circuito reservado com sessão + CR; aprovada=True leva a CR a aprovado."""
    site = create_site(db_session, SiteCreate(name="pop-q", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    dev = create_device(
        db_session, DeviceCreate(name="ne-q", management_address="10.0.0.1", asn=65000), actor="cli"
    )
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-q", asn=64512), actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CR-Q-1",
            organization_id=org.id,
            site_id=site.id,
            access_device_id=dev.id,
            access_port="GE0/0/1",
            edge_device_id=dev.id,
            edge_trunk="GE1/0/0",
            p2p_v4_len=31,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id,
            device_id=dev.id,
            afi="ipv4",
            local_address="10.0.0.1",
            remote_address="10.0.0.2",
            asn_local=65000,
            asn_remote=64512,
        ),
        actor="cli",
    )
    cr = crsvc.create_change_request(
        db_session, ChangeRequestCreate(circuit_id=circ.id, acao="provision", motivo="Ativação."),
        actor="cli",
    )
    if aprovada:
        aprovador = usvc.create_user(
            db_session,
            username="aprovador-q",
            password="senha-super-8",
            role="aprovador",
            actor="cli",
        )
        crsvc.enviar_para_aprovacao(db_session, cr.id, actor="cli")
        crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="cli", decisao="aprovar")
    db_session.commit()
    return cr.id


def test_nao_duplica_job_pendente(fila_limpa: Redis, db_session: Session) -> None:
    cr_id = _cr(db_session, aprovada=True)
    q = Queue("gerenet-change", connection=fila_limpa)
    primeiro = enqueue_change(cr_id, actor="cli", origin="cli")
    assert primeiro["queued"] is True
    assert primeiro["job_id"]

    segundo = enqueue_change(cr_id, actor="cli", origin="cli")
    assert segundo["queued"] is False
    assert "pendente" in segundo["message"]
    visiveis = len(list(q.get_jobs())) + len(list(q.started_job_registry.get_job_ids()))
    assert visiveis == 1


def test_enqueue_bloqueia_cr_nao_aprovada(db_session: Session) -> None:
    """A validação vem antes do Redis: queixa clara, sem job fútil (spec §6.1)."""
    cr_id = _cr(db_session)
    resultado = enqueue_change(cr_id, actor="cli", origin="cli")
    assert resultado["queued"] is False
    assert "aprovada" in resultado["message"]
