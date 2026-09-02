from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from gerenet.automation.netmiko_conn import ConnectionFailed
from gerenet.automation.runner import run_collection
from gerenet.config import Settings
from gerenet.domain.models import CredentialGroup, DeviceSnapshot, JobRun
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

VERSION_SAIDA = """Huawei Versatile Routing Platform Software
VRP (R) software, Version 8.210 (NE8000 V200R021C10SPC600)
Copyright (c) 2012-2019 Huawei Technologies Co., Ltd.
Huawei NE8000 uptime is 5 days, 2 hours, 10 minutes
"""

# Saídas que o fake de conexão devolve, por comando — como o connect_and_run real,
# que só devolve o que recebeu na lista `commands`.
SAIDAS = {
    "display version": VERSION_SAIDA,
    "display current-configuration": "sysname r1\n#\n",
}


class VaultFake:
    """Substitui o VaultSecretStore no teste — nunca tocar o Vault real aqui."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _dev_com_grupo(db_session: Session, nome: str, endereco: str):
    grupo = CredentialGroup(name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao")
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(db_session, DeviceCreate(name=nome, management_address=endereco, credential_group_id=grupo.id))
    dev.host_key_fingerprint = "sha256:fake"
    db_session.commit()
    return dev


def test_coleta_version_atualiza_device_e_snapshot(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r1", "10.0.0.1")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    db_session.refresh(dev)
    assert dev.comm_status == "ok"
    assert dev.vrp_version == "8.210"
    assert dev.uptime == "5 days, 2 hours, 10 minutes"
    assert dev.last_collected_at is not None

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    assert snap is not None
    assert snap.status == "success"
    assert snap.resources["version"]["version"] == "8.210"
    assert snap.resources["config_backup"]["backup"] is True
    assert len(snap.raw_files["version"]) == 1
    assert len(snap.raw_files["config_backup"]) == 1
    assert sorted(p.name for p in tmp_path.glob("r1/*/version/*.txt")) == ["version.txt"]

    job_row = db_session.query(JobRun).filter_by(device_id=dev.id).first()
    assert job_row is not None
    assert job_row.status == "success"
    assert job_row.snapshot_id == snap.id


def test_falha_de_conexao_marca_device_como_fail(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r2", "10.0.0.2")

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)

    def _falha(device, username, password, commands, settings):
        raise ConnectionFailed("host inacessível")

    monkeypatch.setattr("gerenet.automation.runner._conectar_e_executar", _falha)
    resultado = run_collection(
        dev.id, settings=Settings(_env_file=None, backups_dir=Path("/tmp")), session_override=db_session
    )
    assert resultado["status"] == "error"
    db_session.refresh(dev)
    assert dev.comm_status == "fail"
    assert dev.consecutive_failures == 1
