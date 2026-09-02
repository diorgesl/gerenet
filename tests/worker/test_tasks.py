import pytest
from redis import Redis
from rq import Queue

from gerenet.config import Settings
from gerenet.worker.tasks import enqueue_collect


@pytest.fixture()
def fila_limpa() -> Redis:
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    fila = Queue("gerenet-collect", connection=r)
    fila.empty()  # limpa antes e depois: a suíte não deixa jobs órfãos p/ o worker dev
    r.delete("gerenet:lock:device:1")
    yield r
    fila.empty()


def test_nao_duplica_job_pendente(fila_limpa: Redis) -> None:
    q = Queue("gerenet-collect", connection=fila_limpa)
    primeiro = enqueue_collect(1, actor="cli", origin="cli")
    assert primeiro["queued"] is True

    segundo = enqueue_collect(1, actor="cli", origin="cli")
    assert segundo["queued"] is False
    assert "pendente" in segundo["message"]
    assert q.count == 1
