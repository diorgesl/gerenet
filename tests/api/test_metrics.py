"""Contrato do /metrics (Fase 6, parte 1): as séries do §20.1 vêm do banco e do Redis."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


def _cliente(**settings_kw) -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None, **settings_kw))
    return TestClient(create_app())


@pytest.fixture()
def ambiente(db_session: Session) -> models.Device:
    dev = create_device(
        db_session, DeviceCreate(name="r1", management_address="10.0.0.1"), actor="cli"
    )
    dev.comm_status = "ok"
    dev.consecutive_failures = 2
    db_session.add(
        models.DeviceSnapshot(
            device_id=dev.id,
            status="success",
            resources={
                "bgp_peers": [{"afi": "ipv4", "peer": "100.64.0.2", "estado": "Established"}],
                "divergencias": {
                    "total": 2, "critica": 1, "atencao": 1, "aviso": 0, "alerta": 0,
                    "parcial": False, "motivo": None,
                },
            },
            started_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    db_session.add(
        models.JobRun(
            device_id=dev.id, origin="cli", actor="cli", kind="collect", status="success",
            duration_ms=1500,
        )
    )
    dominio = models.MplsDomain(name="dom-metrics")
    db_session.add(dominio)
    db_session.flush()
    db_session.add_all([
        models.L2vcService(domain_id=dominio.id, vc_id=100, name="vc-metrics"),
        models.VsiService(domain_id=dominio.id, vsi_id=200, name="vsi-metrics", vrp_name="VSI-METRICS"),
        models.ChangeRequest(acao="provision", motivo="teste de métrica"),
    ])
    db_session.commit()
    return dev


def test_metrics_expoe_os_itens_do_20_1(ambiente: models.Device) -> None:
    resp = _cliente().get("/metrics")

    assert resp.status_code == 200
    corpo = resp.text
    assert 'gerenet_devices_comm_status{status="ok"} 1.0' in corpo
    assert 'gerenet_devices_active 1.0' in corpo
    assert 'gerenet_device_consecutive_failures{device="r1"} 2.0' in corpo
    assert 'gerenet_snapshot_age_seconds{device="r1"}' in corpo
    assert 'gerenet_divergencias{severidade="critica"} 1.0' in corpo
    assert 'gerenet_divergencias{severidade="atencao"} 1.0' in corpo
    assert "gerenet_devices_sem_resumo 0.0" in corpo
    assert 'gerenet_peers_bgp{estado="Established"} 1.0' in corpo
    assert 'gerenet_l2vc_oper_status{status="unknown"} 1.0' in corpo
    assert 'gerenet_vsi_oper_status{status="unknown"} 1.0' in corpo
    assert 'gerenet_change_requests{status="rascunho"} 1.0' in corpo
    assert 'gerenet_queue_jobs{queue="gerenet-collect"}' in corpo
    assert 'gerenet_queue_started{queue="gerenet-change"}' in corpo
    # A exposição ordena os rótulos alfabeticamente (exposition.py:300), não na
    # ordem em que a família os declara.
    assert 'gerenet_job_runs{device="r1",kind="collect",status="success"} 1.0' in corpo
    assert 'gerenet_job_duration_seconds{kind="collect",quantil="0.5"} 1.5' in corpo


def test_metrics_conta_equipamento_sem_resumo(db_session: Session) -> None:
    dev = create_device(
        db_session, DeviceCreate(name="r2", management_address="10.0.0.2"), actor="cli"
    )
    db_session.add(
        models.DeviceSnapshot(device_id=dev.id, status="success", resources={})
    )
    db_session.commit()

    corpo = _cliente().get("/metrics").text

    assert "gerenet_devices_sem_resumo 1.0" in corpo


def test_metrics_exige_token_quando_configurado() -> None:
    cliente = _cliente(metrics_token="s3gr3do")

    assert cliente.get("/metrics").status_code == 401
    assert cliente.get("/metrics", headers={"Authorization": "Bearer errado"}).status_code == 401

    ok = cliente.get("/metrics", headers={"Authorization": "Bearer s3gr3do"})
    assert ok.status_code == 200
    assert "gerenet_" in ok.text


def test_metrics_nao_cai_no_fallback_da_spa(tmp_path: Path) -> None:
    """O catch-all da SPA responde qualquer GET: /metrics precisa vir antes dele."""
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>gerenet</html>", encoding="utf-8")

    resp = _cliente(static_dir=dist).get("/metrics")

    assert resp.status_code == 200
    assert "gerenet_" in resp.text
