import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.models import JobRun
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_lista_filtros_e_detalhe(client: TestClient, db_session) -> None:
    # Desvio do brief: device_id=1/2 fixos violam a FK job_runs.device_id → devices.id
    # quando a suíte está truncada; cria os devices e usa os ids reais.
    d1 = create_device(db_session, DeviceCreate(name="job-dev-1", management_address="10.9.0.11"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="job-dev-2", management_address="10.9.0.12"), actor="cli")
    j1 = JobRun(device_id=d1.id, origin="api", actor="api", kind="collect", status="queued")
    j2 = JobRun(device_id=d2.id, origin="cli", actor="cli", kind="collect", status="success", duration_ms=1200)
    db_session.add_all([j1, j2])
    db_session.commit()

    lista = client.get("/api/v1/jobs", headers=_auth()).json()
    assert [j["id"] for j in lista] == [j2.id, j1.id]
    assert set(lista[0]) == {
        "id", "device_id", "origin", "actor", "kind", "status",
        "started_at", "finished_at", "duration_ms", "snapshot_id",
    }

    so_running = client.get("/api/v1/jobs?status=queued", headers=_auth()).json()
    assert [j["id"] for j in so_running] == [j1.id]

    por_device = client.get(f"/api/v1/jobs?device_id={j2.device_id}", headers=_auth()).json()
    assert [j["id"] for j in por_device] == [j2.id]

    detalhe = client.get(f"/api/v1/jobs/{j1.id}", headers=_auth())
    assert detalhe.status_code == 200 and detalhe.json()["status"] == "queued"
    assert client.get("/api/v1/jobs/9999", headers=_auth()).status_code == 404


def test_jobs_exige_autenticacao(client: TestClient) -> None:
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.post("/api/v1/jobs", headers={"X-API-Key": "teste-key"}).status_code == 405


def test_collect_202_tem_job_id(client: TestClient, db_session, monkeypatch) -> None:
    """Contrato da spec §5.2: o 202 do collect carrega job_id.

    Em produção `enqueue_collect` (worker/tasks.py:34) já devolve job_id —
    nenhuma mudança de produção nesta task; o teste apenas fixa o contrato.
    """
    dev = create_device(
        db_session, DeviceCreate(name="job-dash", management_address="10.9.0.1"), actor="cli"
    )
    monkeypatch.setattr(
        "gerenet.api.routers.devices.enqueue_collect",
        lambda *a, **k: {"queued": True, "message": "Coleta enfileirada.", "job_id": 42},
    )
    resp = client.post(f"/api/v1/devices/{dev.id}/collect", headers=_auth())
    assert resp.status_code == 202
    assert resp.json()["job_id"] == 42
