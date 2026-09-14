"""Varredura de coletas (Fase 6, parte 1): o que a coleta periódica enfileira.

Redis real, o mesmo dos testes de `tasks`: a varredura usa lock e fila de
verdade. A limpeza cobre a fila `gerenet-collect`, o registry de agendados e o
lock da varredura.

A suíte divide o Redis com o stack de dev, então o worker do compose consome os
jobs destes testes: por isso as contagens incluem os jobs já iniciados, e uma
suíte determinística pede o worker parado (`docker compose stop worker`).
"""
from datetime import UTC, datetime, timedelta

import pytest
from redis import Redis
from rq import Queue
from rq.job import Job
from sqlalchemy.orm import Session

from gerenet.config import Settings, set_settings
from gerenet.domain.models import AuditEvent, CredentialGroup, DeviceSnapshot
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device
from gerenet.worker.tasks import SWEEP_LOCK, armar_varredura, varredura_coletas

CHAVE_AGENDADOS = "rq:scheduled:gerenet-collect"


@pytest.fixture()
def fila_limpa() -> Redis:
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    fila = Queue("gerenet-collect", connection=r)
    fila.empty()
    r.delete(CHAVE_AGENDADOS, SWEEP_LOCK)
    yield r
    fila.empty()
    r.delete(CHAVE_AGENDADOS, SWEEP_LOCK)


def _grupo(db_session: Session) -> CredentialGroup:
    grupo = CredentialGroup(
        name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao"
    )
    db_session.add(grupo)
    db_session.commit()
    return grupo


def _dev(
    db_session: Session,
    nome: str,
    endereco: str,
    *,
    grupo: CredentialGroup | None,
    ativo: bool = True,
):
    dev = create_device(
        db_session,
        DeviceCreate(
            name=nome,
            management_address=endereco,
            credential_group_id=grupo.id if grupo is not None else None,
        ),
        actor="cli",
    )
    if not ativo:
        dev.admin_status = False
        db_session.commit()
    return dev


def _com_snapshot(db_session: Session, dev, *, minutos_atras: int) -> None:
    db_session.add(
        DeviceSnapshot(
            device_id=dev.id,
            status="success",
            resources={},
            started_at=datetime.now(UTC) - timedelta(minutes=minutos_atras),
        )
    )
    db_session.commit()


def _jobs_visiveis(fila: Queue) -> list:
    """Jobs da fila mais os que o worker já retirou (registry de iniciados).

    O worker do stack de dev compartilha o Redis: um job enfileirado pode já
    estar em execução quando a asserção roda (padrão do `test_nao_duplica_job_pendente`).
    `fetch_job` devolve None para job já apagado pelo `empty()`, que só limpa a
    fila, não o registry.
    """
    jobs = list(fila.get_jobs())
    for job_id in fila.started_job_registry.get_job_ids():
        job = fila.fetch_job(job_id)
        if job is not None:
            jobs.append(job)
    return jobs


def _jobs_do_device(fila: Queue, device_id: int) -> list:
    return [job for job in _jobs_visiveis(fila) if job.args and job.args[0] == device_id]


def test_varredura_enfileira_so_ativos_com_credencial(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    alvo = _dev(db_session, "com-credencial", "10.10.0.1", grupo=grupo)
    _dev(db_session, "sem-credencial", "10.10.0.2", grupo=None)
    _dev(db_session, "desativado", "10.10.0.3", grupo=grupo, ativo=False)

    resultado = varredura_coletas()

    assert resultado["status"] == "ok"
    assert resultado["enfileirados"] == 1
    assert resultado["pulados_idade"] == 0
    assert resultado["recusados"] == []
    do_alvo = _jobs_do_device(Queue("gerenet-collect", connection=fila_limpa), alvo.id)
    assert len(do_alvo) == 1
    assert do_alvo[0].meta["origin"] == "scheduler"

    evento = db_session.query(AuditEvent).filter_by(type="collect.sweep").one()
    assert evento.actor == "scheduler"
    assert evento.details["enfileirados"] == 1
    assert evento.details["pulados_idade"] == 0
    assert evento.details["recusados"] == []


def test_varredura_pula_coletado_dentro_do_intervalo(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "coletado-agora", "10.10.1.1", grupo=grupo)
    _com_snapshot(db_session, dev, minutos_atras=5)

    resultado = varredura_coletas()

    assert resultado["pulados_idade"] == 1
    assert resultado["enfileirados"] == 0
    assert _jobs_do_device(Queue("gerenet-collect", connection=fila_limpa), dev.id) == []


def test_varredura_enfileira_quem_esta_fora_do_intervalo(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "coletado-ha-tempo", "10.10.1.2", grupo=grupo)
    _com_snapshot(db_session, dev, minutos_atras=120)

    resultado = varredura_coletas()

    assert resultado["pulados_idade"] == 0
    assert resultado["enfileirados"] == 1


def test_varredura_conta_recusa_do_enqueue(fila_limpa: Redis, db_session: Session) -> None:
    """Coleta em andamento não entra de novo: a recusa do enqueue vira `recusados`.

    O teste segura o lock do equipamento, e não uma coleta pendente de verdade:
    o caminho "pendente" já tem teste determinístico em
    `tests/worker/test_tasks.py::test_nao_duplica_job_pendente`, e a recusa por
    lock é a que um worker ativo não consegue mascarar (ele retiraria o job da
    fila antes de a varredura consultá-la).
    """
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "em-coleta", "10.10.1.3", grupo=grupo)
    chave_lock = f"gerenet:lock:device:{dev.id}"
    fila_limpa.set(chave_lock, "outra-coleta", ex=60)

    resultado = varredura_coletas()

    fila_limpa.delete(chave_lock)
    assert resultado["enfileirados"] == 0
    assert resultado["recusados"][0]["device"] == "em-coleta"
    assert "andamento" in resultado["recusados"][0]["motivo"]


def test_varredura_desligada_nao_faz_nada(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=0))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "ativo", "10.10.2.1", grupo=grupo)

    resultado = varredura_coletas()

    assert resultado == {"status": "skipped", "message": "Coleta periódica desligada."}
    assert _jobs_do_device(Queue("gerenet-collect", connection=fila_limpa), dev.id) == []
    assert db_session.query(AuditEvent).filter_by(type="collect.sweep").count() == 0


def test_varredura_com_lock_tomado_nao_enfileira(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=60))
    grupo = _grupo(db_session)
    dev = _dev(db_session, "ativo", "10.10.3.1", grupo=grupo)
    fila_limpa.set(SWEEP_LOCK, "outra-varredura")

    resultado = varredura_coletas()

    assert resultado == {"status": "skipped", "message": "Varredura já em andamento."}
    assert _jobs_do_device(Queue("gerenet-collect", connection=fila_limpa), dev.id) == []


def test_armar_sem_intervalo_nao_agenda(fila_limpa: Redis) -> None:
    armar = armar_varredura(fila_limpa, Settings(_env_file=None, collect_interval_minutes=0))
    assert armar is False
    assert fila_limpa.zcard(CHAVE_AGENDADOS) == 0


def test_armar_e_idempotente(fila_limpa: Redis) -> None:
    settings = Settings(_env_file=None, collect_interval_minutes=30)

    assert armar_varredura(fila_limpa, settings) is True
    assert armar_varredura(fila_limpa, settings) is False

    fila = Queue("gerenet-collect", connection=fila_limpa)
    assert len(fila.scheduled_job_registry.get_job_ids()) == 1


def test_varredura_reagenda_a_proxima(fila_limpa: Redis, db_session: Session) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=30))
    grupo = _grupo(db_session)
    _dev(db_session, "ativo", "10.11.0.1", grupo=grupo)

    varredura_coletas()

    fila = Queue("gerenet-collect", connection=fila_limpa)
    agendados = fila.scheduled_job_registry.get_job_ids()
    assert len(agendados) == 1
    assert Job.fetch(agendados[0], connection=fila_limpa).func_name.endswith(".varredura_coletas")


def test_varredura_desligada_nao_reagenda(fila_limpa: Redis) -> None:
    set_settings(Settings(_env_file=None, collect_interval_minutes=0))

    varredura_coletas()

    assert fila_limpa.zcard(CHAVE_AGENDADOS) == 0
