import pytest
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from gerenet.config import Settings
from gerenet.domain.models import CredentialGroup
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device
from gerenet.worker.tasks import enqueue_collect


@pytest.fixture()
def fila_limpa() -> Redis:
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    fila = Queue("gerenet-collect", connection=r)
    fila.empty()  # limpa antes e depois: a suíte não deixa jobs órfãos p/ o worker dev
    r.delete("gerenet:lock:device:1")
    yield r
    fila.empty()


def test_nao_duplica_job_pendente(fila_limpa: Redis, db_session: Session) -> None:
    # O enqueue passou a validar o equipamento antes da fila — o teste precisa
    # de um device real com grupo de credencial (padrão do test_runner).
    grupo = CredentialGroup(name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao")
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(
        db_session,
        DeviceCreate(name="ne-fila", management_address="10.0.0.50", credential_group_id=grupo.id),
        actor="cli",
    )

    q = Queue("gerenet-collect", connection=fila_limpa)
    primeiro = enqueue_collect(dev.id, actor="cli", origin="cli")
    assert primeiro["queued"] is True

    segundo = enqueue_collect(dev.id, actor="cli", origin="cli")
    assert segundo["queued"] is False
    assert "pendente" in segundo["message"]
    # Pendente OU já retirado pelo worker (started): o ponto é não duplicar.
    visiveis = len(list(q.get_jobs())) + len(list(q.started_job_registry.get_job_ids()))
    assert visiveis == 1


def test_enqueue_bloqueia_sem_grupo_ou_desativado(db_session: Session) -> None:
    """A validação acontece no enqueue — queixa clara antes de enfileirar job fútil."""
    dev = create_device(
        db_session, DeviceCreate(name="sem-grupo-enqueue", management_address="10.0.0.47"), actor="cli"
    )

    sem_grupo = enqueue_collect(dev.id, actor="cli", origin="cli")
    assert sem_grupo["queued"] is False
    assert "grupo de credencial" in sem_grupo["message"]

    dev.admin_status = False
    db_session.commit()
    desativado = enqueue_collect(dev.id, actor="cli", origin="cli")
    assert desativado["queued"] is False
    assert "desativado" in desativado["message"]
