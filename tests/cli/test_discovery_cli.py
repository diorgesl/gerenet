"""CLI da descoberta (§13 do design)."""
from pathlib import Path

from typer.testing import CliRunner

from gerenet.cli.main import app as cli_app
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.sites import create_site, link_device

runner = CliRunner()
FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _ambiente(db_session, tmp_path: Path) -> models.Device:
    site = create_site(db_session, SiteCreate(name="pop-desc-cli",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc-cli",
                                                 management_address="10.0.0.1", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return dev


def test_list_mostra_veredito_e_classificacao(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "1001" in r.output
    assert "adotavel_com_pendencias" in r.output
    assert "100.64.10.1" in r.output
    assert "interno" in r.output  # o peer com o próprio ASN aparece na lista separada


def test_show_detalha_pendencias_e_conflitos(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "100.64.10.1"])
    assert r.exit_code == 0, r.output
    assert "organizacao_ausente" in r.output
    assert "senha_nao_legivel" in r.output


def test_ignore_e_unignore(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, [
        "discovery", "ignore", dev.name, "100.64.10.4", "--motivo", "cliente saiu",
    ])
    assert r.exit_code == 0, r.output
    assert "100.64.10.4" not in runner.invoke(cli_app, ["discovery", "list", dev.name]).output

    r = runner.invoke(cli_app, ["discovery", "unignore", dev.name, "100.64.10.4"])
    assert r.exit_code == 0, r.output
    assert "100.64.10.4" in runner.invoke(cli_app, ["discovery", "list", dev.name]).output


def test_device_sem_coleta_avisa(db_session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-cli-sem-coleta"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-sem-coleta",
                                                 management_address="10.0.0.9", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "Colete antes" in r.output
