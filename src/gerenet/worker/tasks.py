import secrets
from datetime import UTC, datetime, timedelta

from redis import Redis
from rq import Queue, get_current_job
from sqlalchemy import select

from gerenet.automation.runner import liberta_lock, run_change, run_collection
from gerenet.config import Settings, get_settings
from gerenet.db import get_session
from gerenet.domain import models
from gerenet.domain.services import change_requests as change_svc
from gerenet.domain.services import devices as device_svc
from gerenet.domain.services.errors import NotFoundError

SWEEP_LOCK = "gerenet:lock:sweep"


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url)


def enqueue_collect(device_id: int, *, actor: str, origin: str) -> dict:
    # Validação antes da fila: queixa clara na origem, sem job fútil no RQ.
    # (Só postergada ao worker, uma falha aqui viraria JobRun de erro invisível.)
    with get_session() as session:
        try:
            dev = device_svc.get_device(session, device_id)
        except NotFoundError:
            return {"queued": False, "message": "Equipamento não encontrado."}
        if not dev.admin_status:
            return {"queued": False, "message": f"Equipamento {dev.name} está desativado — reative antes de coletar."}
        if dev.credential_group is None:
            return {
                "queued": False,
                "message": (
                    f"Equipamento {dev.name} não possui grupo de credencial — crie-o na "
                    "página Credenciais (ou com `gerenet credential-groups create`) e "
                    "vincule-o ao equipamento em Equipamentos > Editar."
                ),
            }

    settings = get_settings()
    r = _redis(settings)
    chave_lock = f"gerenet:lock:device:{device_id}"
    if r.get(chave_lock):
        return {"queued": False, "message": "Já existe uma coleta em andamento para este equipamento."}

    q = Queue("gerenet-collect", connection=r)
    pendentes = list(q.job_ids) + list(q.started_job_registry.get_job_ids())
    for job_id in pendentes:
        job = q.fetch_job(job_id)
        if job is not None and job.args and job.args[0] == device_id:
            return {"queued": False, "message": "Já existe uma coleta pendente para este equipamento."}

    job = q.enqueue(
        collect_task,
        device_id,
        job_timeout=600,
        result_ttl=3600,
        meta={"actor": actor, "origin": origin},
    )
    # job_id = id do job RQ; o job_runs no banco é criado pelo runner ao executar
    return {"queued": True, "job_id": job.id, "message": "Coleta enfileirada."}


def collect_task(device_id: int) -> None:
    """Executada pelo worker; actor/origin chegam pelo job.meta."""
    job = get_current_job()
    meta = job.meta if job is not None else {}
    run_collection(device_id, actor=meta.get("actor", "worker"), origin=meta.get("origin", "rq"))


def enqueue_change(change_request_id: int, *, actor: str, origin: str) -> dict:
    """Valida a CR e enfileira a execução na fila `gerenet-change` (spec §6.6).

    Espelho de enqueue_collect: queixa clara na origem antes de job fútil;
    não enfileira se a CR não está aprovada ou já tem job pendente/iniciado.
    O lock real é do worker (run_change); aqui só a checagem barata.
    """
    with get_session() as session:
        try:
            cr = change_svc.get_change_request(session, change_request_id)
        except NotFoundError:
            return {"queued": False, "message": "Change request não encontrada."}
        if cr.status != "aprovado":
            return {
                "queued": False,
                "message": f"Change request não está aprovada para execução (status: {cr.status}).",
            }
        if not cr.steps:
            return {"queued": False, "message": "Change request sem steps para executar."}

    settings = get_settings()
    r = _redis(settings)
    chave_lock = f"gerenet:lock:change:{change_request_id}"
    if r.get(chave_lock):
        return {"queued": False, "message": "Já existe uma execução em andamento para esta change request."}

    q = Queue("gerenet-change", connection=r)
    pendentes = list(q.job_ids) + list(q.started_job_registry.get_job_ids())
    for job_id in pendentes:
        job = q.fetch_job(job_id)
        if job is not None and job.args and job.args[0] == change_request_id:
            return {"queued": False, "message": "Já existe uma execução pendente para esta change request."}

    job = q.enqueue(
        change_task,
        change_request_id,
        job_timeout=3600,
        result_ttl=3600,
        meta={"actor": actor, "origin": origin},
    )
    return {"queued": True, "job_id": job.id, "message": "Mudança enfileirada."}


def change_task(change_request_id: int) -> None:
    """Executada pelo worker; actor/origin chegam pelo job.meta."""
    job = get_current_job()
    meta = job.meta if job is not None else {}
    run_change(
        change_request_id,
        actor=meta.get("actor", "worker"),
        origin=meta.get("origin", "rq"),
    )


def varredura_coletas(agora: datetime | None = None) -> dict:
    """Enfileira a coleta dos equipamentos ativos com credencial (§10, F6).

    Chamada pelo agendador do worker (e pelos testes). Não levanta por recusa:
    quem não entra na fila (coleta em andamento, job pendente, equipamento
    desativado desde a consulta) conta em `recusados` e fica auditado. O lock
    `gerenet:lock:sweep` impede duas varreduras sobrepostas.
    """
    settings = get_settings()
    if settings.collect_interval_minutes <= 0:
        return {"status": "skipped", "message": "Coleta periódica desligada."}

    agora = agora or datetime.now(UTC)
    limite = agora - timedelta(minutes=settings.collect_interval_minutes)
    r = _redis(settings)
    token = secrets.token_hex(16)
    try:
        if not r.set(SWEEP_LOCK, token, nx=True, ex=settings.lock_ttl_seconds):
            return {"status": "skipped", "message": "Varredura já em andamento."}
        enfileirados: list[str] = []
        recusados: list[dict] = []
        pulados_idade = 0
        with get_session() as session:
            devices = list(
                session.scalars(
                    select(models.Device)
                    .where(
                        models.Device.admin_status.is_(True),
                        models.Device.credential_group_id.isnot(None),
                    )
                    .order_by(models.Device.name)
                )
            )
            for dev in devices:
                ultimo = session.scalar(
                    select(models.DeviceSnapshot.started_at)
                    .where(models.DeviceSnapshot.device_id == dev.id)
                    .order_by(models.DeviceSnapshot.id.desc())
                    .limit(1)
                )
                if ultimo is not None and ultimo > limite:
                    pulados_idade += 1
                    continue
                enfileirado = enqueue_collect(dev.id, actor="scheduler", origin="scheduler")
                if enfileirado["queued"]:
                    enfileirados.append(dev.name)
                else:
                    recusados.append({"device": dev.name, "motivo": enfileirado["message"]})
            session.add(
                models.AuditEvent(
                    type="collect.sweep",
                    actor="scheduler",
                    details={
                        "enfileirados": len(enfileirados),
                        "pulados_idade": pulados_idade,
                        "recusados": recusados,
                    },
                )
            )
        return {
            "status": "ok",
            "enfileirados": len(enfileirados),
            "pulados_idade": pulados_idade,
            "recusados": recusados,
        }
    finally:
        liberta_lock(r, SWEEP_LOCK, token)
        r.close()


def worker_main() -> None:
    from rq.worker import Worker

    settings = get_settings()
    with _redis(settings) as r:
        Worker(["gerenet-collect", "gerenet-change"], connection=r).work()
