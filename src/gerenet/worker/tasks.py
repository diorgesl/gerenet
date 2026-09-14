import secrets
from datetime import UTC, datetime, timedelta

from redis import Redis
from rq import Queue, get_current_job
from sqlalchemy import func, select

from gerenet.automation.runner import liberta_lock, run_change, run_collection
from gerenet.config import Settings, get_settings
from gerenet.db import get_session
from gerenet.domain import models
from gerenet.domain.services import change_requests as change_svc
from gerenet.domain.services import devices as device_svc
from gerenet.domain.services.errors import NotFoundError

SWEEP_LOCK = "gerenet:lock:sweep"
SWEEP_JOB_TIMEOUT = 600


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
    chave_lock = f"gerenet:lock:device:{device_id}"
    # `with` porque a varredura chama esta função uma vez por equipamento a cada
    # ciclo: cliente solto deixaria uma conexão aberta por chamada até o GC.
    with _redis(settings) as r:
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


def armar_varredura(r: Redis, settings: Settings | None = None) -> bool:
    """Agenda a varredura, se a coleta periódica está ligada e nenhuma está agendada.

    Idempotente de propósito: o worker chama na subida, então uma agenda perdida
    no Redis volta no próximo boot sem duplicar job.
    """
    settings = settings or get_settings()
    if settings.collect_interval_minutes <= 0:
        return False
    fila = Queue("gerenet-collect", connection=r)
    alvo = f"{varredura_coletas.__module__}.{varredura_coletas.__name__}"
    for job_id in fila.scheduled_job_registry.get_job_ids():
        # fetch_job (e não Job.fetch) tolera id órfão no registry: devolve None.
        job = fila.fetch_job(job_id)
        if job is not None and job.func_name == alvo:
            return False
    fila.enqueue_in(
        timedelta(minutes=settings.collect_interval_minutes),
        varredura_coletas,
        job_timeout=SWEEP_JOB_TIMEOUT,
    )
    return True


def varredura_coletas(agora: datetime | None = None) -> dict:
    """Enfileira a coleta dos equipamentos ativos com credencial (§10, F6).

    Chamada pelo agendador do worker (e pelos testes) e, ao fim de cada execução,
    reagenda a si mesma — inclusive quando o corpo falha, senão a coleta periódica
    morreria em silêncio até o próximo boot. Não levanta por recusa: quem não entra
    na fila (coleta em andamento, job pendente, equipamento desativado desde a
    consulta) conta em `recusados` e fica auditado. O lock `gerenet:lock:sweep`
    impede duas varreduras sobrepostas.
    """
    settings = get_settings()
    if settings.collect_interval_minutes <= 0:
        return {"status": "skipped", "message": "Coleta periódica desligada."}

    agora = agora or datetime.now(UTC)
    limite = agora - timedelta(minutes=settings.collect_interval_minutes)
    r = _redis(settings)
    token = secrets.token_hex(16)
    executou = False
    try:
        if not r.set(SWEEP_LOCK, token, nx=True, ex=settings.lock_ttl_seconds):
            return {"status": "skipped", "message": "Varredura já em andamento."}
        executou = True
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
            # Uma consulta para todos os devices: aqui vale a data da coleta mais
            # recente (é a idade que decide se pula), não o id do snapshot — o
            # max(started_at) por device responde a mesma pergunta em 2 consultas
            # em vez de N+1.
            ultimos = dict(
                session.execute(
                    select(
                        models.DeviceSnapshot.device_id,
                        func.max(models.DeviceSnapshot.started_at),
                    ).group_by(models.DeviceSnapshot.device_id)
                ).all()
            )
            for dev in devices:
                ultimo = ultimos.get(dev.id)
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
        if executou:
            # Reagenda também quando o corpo falha: uma exceção no meio (Postgres ou
            # Redis tropeçando) deixaria a coleta periódica parada até o próximo boot
            # do worker, com o job só no registry de falhas. Só o caminho que tomou o
            # lock reagenda, então duas varreduras sobrepostas não se multiplicam.
            # Best-effort de propósito: falhar aqui não pode mascarar o erro real da
            # varredura nem impedir a liberação do lock — o boot do worker rearma.
            try:
                armar_varredura(r)
            except Exception:  # noqa: BLE001, S110 — redis indisponível ao reagendar: o boot rearma
                pass
        liberta_lock(r, SWEEP_LOCK, token)
        r.close()


def worker_main() -> None:
    from rq.worker import Worker

    settings = get_settings()
    with _redis(settings) as r:
        armar_varredura(r, settings)
        Worker(["gerenet-collect", "gerenet-change"], connection=r).work(with_scheduler=True)
