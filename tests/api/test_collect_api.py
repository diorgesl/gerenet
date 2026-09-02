from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain.models import CredentialGroup, DeviceSnapshot
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_dispara_coleta_202(client: TestClient, db_session) -> None:
    dev = create_device(db_session, DeviceCreate(name="r3", management_address="10.0.0.5"), actor="cli")
    with patch(
        "gerenet.api.routers.devices.enqueue_collect",
        return_value={"queued": True, "message": "Coleta enfileirada."},
    ) as enfileirar:
        resp = client.post(f"/api/v1/devices/{dev.id}/collect", headers=_auth())
    assert resp.status_code == 202
    assert resp.json()["queued"] is True
    enfileirar.assert_called_once_with(dev.id, actor="api", origin="api")


def test_coleta_de_device_inexistente_da_404(client: TestClient) -> None:
    with patch("gerenet.api.routers.devices.enqueue_collect") as enfileirar:
        resp = client.post("/api/v1/devices/9999/collect", headers=_auth())
    assert resp.status_code == 404
    enfileirar.assert_not_called()


def test_snapshots_lista_e_detalhe(client: TestClient, db_session) -> None:
    grupo = CredentialGroup(name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao")
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(db_session, DeviceCreate(name="r4", management_address="10.0.0.6", credential_group_id=grupo.id), actor="cli")
    snap = DeviceSnapshot(device_id=dev.id, status="success", resources={"version": {"version": "8.210"}})
    db_session.add(snap)
    db_session.commit()

    lista = client.get(f"/api/v1/devices/{dev.id}/snapshots", headers=_auth())
    assert lista.status_code == 200
    assert [s["id"] for s in lista.json()] == [snap.id]

    detalhe = client.get(f"/api/v1/snapshots/{snap.id}", headers=_auth())
    assert detalhe.status_code == 200
    assert detalhe.json()["status"] == "success"

    assert client.get("/api/v1/snapshots/9999", headers=_auth()).status_code == 404
