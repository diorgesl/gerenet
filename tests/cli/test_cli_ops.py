from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

runner = CliRunner()


def test_cli_credential_groups_create_list() -> None:
    r = runner.invoke(
        app,
        [
            "credential-groups",
            "create",
            "automacao",
            "--vault-path",
            "gerenet/credential-groups/automacao",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "Grupo SoT criado" in r.output

    lista = runner.invoke(app, ["credential-groups", "list"])
    assert lista.exit_code == 0
    assert "automacao" in lista.output
    assert "gerenet/credential-groups/automacao" in lista.output

    duplicado = runner.invoke(
        app, ["credential-groups", "create", "automacao", "--vault-path", "outro/caminho"]
    )
    assert duplicado.exit_code == 1
    assert "Erro:" in duplicado.output


def test_cli_devices_enable_apos_disable(db_session: Session) -> None:
    add = runner.invoke(app, ["devices", "add", "--name", "ne-enable", "--address", "10.0.0.9"])
    assert add.exit_code == 0, add.output

    off = runner.invoke(app, ["devices", "disable", "ne-enable"])
    assert off.exit_code == 0, off.output

    liga = runner.invoke(app, ["devices", "enable", "ne-enable"])
    assert liga.exit_code == 0, liga.output
    assert "reativado" in liga.output

    dev = db_session.scalar(select(models.Device).where(models.Device.name == "ne-enable"))
    assert dev is not None and dev.admin_status is True

    # Idempotência: reativar quem já está ativo não falha nem gera novo evento.
    de_novo = runner.invoke(app, ["devices", "enable", "ne-enable"])
    assert de_novo.exit_code == 0, de_novo.output
    eventos = db_session.query(models.AuditEvent).filter_by(type="device.enable").all()
    assert len(eventos) == 1

    faltante = runner.invoke(app, ["devices", "enable", "nao-existe"])
    assert faltante.exit_code == 1
    assert "não encontrado" in faltante.output


def test_cli_snapshot_show_exibe_erros(db_session: Session) -> None:
    dev = create_device(
        db_session, DeviceCreate(name="snap-erros", management_address="10.0.0.10"), actor="cli"
    )
    snap = models.DeviceSnapshot(
        device_id=dev.id,
        status="partial",
        resources={"version": {"version": "8.210"}},
        errors={"config_backup": "timeout ao coletar display current-configuration"},
    )
    db_session.add(snap)
    db_session.commit()

    r = runner.invoke(app, ["snapshot", "show", str(snap.id)])
    assert r.exit_code == 0, r.output
    assert "Erros:" in r.output
    assert "config_backup" in r.output
    assert "timeout ao coletar" in r.output
