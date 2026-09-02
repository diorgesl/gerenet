from redis import Redis
from rq import Queue, get_current_job

from gerenet.automation.runner import run_collection
from gerenet.config import Settings, get_settings


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url)


def enqueue_collect(device_id: int, *, actor: str, origin: str) -> dict:
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


def worker_main() -> None:
    from rq.worker import Worker

    settings = get_settings()
    with _redis(settings) as r:
        Worker(["gerenet-collect"], connection=r).work()
