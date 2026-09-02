from pathlib import Path

import pytest
from redis import Redis
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


def test_sessao_autocriada_e_fechada(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r3", "10.0.0.3")
    settings = Settings(_env_file=None, backups_dir=tmp_path)
    fechadas: list[object] = []

    def _fabrica_sessao():
        from gerenet.db import SessionLocal as _SessionLocalReal

        sessao = _SessionLocalReal()
        _close_real = sessao.close

        def _close_rastreado():
            fechadas.append(sessao)
            _close_real()

        sessao.close = _close_rastreado
        return sessao

    monkeypatch.setattr("gerenet.automation.runner.SessionLocal", _fabrica_sessao)
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings)
    assert resultado["status"] == "success"
    assert len(fechadas) == 1


def test_redis_fora_do_ar_retorna_dict_e_fecha_sessao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis fora do ar antes do try interno: contrato dict mantido, sem exceção propagada,
    e a sessão autocriada é fechada (o fix anterior cobriu os caminhos dentro do try)."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    fechadas: list[object] = []

    def _fabrica_sessao():
        from gerenet.db import SessionLocal as _SessionLocalReal

        sessao = _SessionLocalReal()
        _close_real = sessao.close

        def _close_rastreado():
            fechadas.append(sessao)
            _close_real()

        sessao.close = _close_rastreado
        return sessao

    def _from_url_que_falha(*args, **kwargs):
        raise RedisConnectionError("redis fora do ar")

    monkeypatch.setattr("gerenet.automation.runner.SessionLocal", _fabrica_sessao)
    monkeypatch.setattr("gerenet.automation.runner.Redis.from_url", _from_url_que_falha)

    # A falha acontece antes de qualquer acesso ao banco: device inexistente basta.
    resultado = run_collection(9999, settings=Settings(_env_file=None))
    assert resultado["status"] == "error"
    assert resultado["snapshot_id"] is None
    assert resultado["error"]
    assert len(fechadas) == 1


def test_lock_alheio_nao_e_liberado(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    dev = _dev_com_grupo(db_session, "r4", "10.0.0.4")
    settings = Settings(_env_file=None, backups_dir=Path("/tmp"))
    redis = Redis.from_url(settings.redis_url)
    chave = f"gerenet:lock:device:{dev.id}"
    redis.set(chave, "token-de-outro", nx=True, ex=300)
    try:
        # Lock de outro worker ativo: o runner cai no early-return antes de conectar.
        resultado = run_collection(dev.id, settings=settings)
        assert resultado["status"] == "error"
        assert "lock" in resultado["error"]
        assert redis.get(chave) == b"token-de-outro"
    finally:
        redis.delete(chave)
        redis.close()


def test_lock_proprio_e_liberado(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r5", "10.0.0.5")
    settings = Settings(_env_file=None, backups_dir=tmp_path)
    redis = Redis.from_url(settings.redis_url)
    chave = f"gerenet:lock:device:{dev.id}"

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    try:
        resultado = run_collection(dev.id, settings=settings, session_override=db_session)
        assert resultado["status"] == "success"
        # Compare-and-delete no caminho feliz: o lock próprio foi liberado.
        assert redis.get(chave) is None
    finally:
        redis.delete(chave)
        redis.close()
