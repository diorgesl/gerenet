from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models

runner = CliRunner()


def test_cli_sites_add_list_disable() -> None:
    r = runner.invoke(app, ["sites", "add", "--name", "POP-CLI", "--city", "Campinas", "--uf", "SP"])
    assert r.exit_code == 0, r.output
    assert "POP-CLI" in r.output

    assert "POP-CLI" in runner.invoke(app, ["sites", "list"]).output

    off = runner.invoke(app, ["sites", "disable", "POP-CLI"])
    assert off.exit_code == 0
    assert "desativado" in off.output

    oculto = runner.invoke(app, ["sites", "list"])
    assert "POP-CLI" not in oculto.output
    com_tudo = runner.invoke(app, ["sites", "list", "--all"])
    assert "POP-CLI" in com_tudo.output


def test_cli_sites_erros() -> None:
    assert runner.invoke(app, ["sites", "add", "--name", "POP-CLI-ERR"]).exit_code == 0
    segundo = runner.invoke(app, ["sites", "add", "--name", "POP-CLI-ERR"])
    assert segundo.exit_code == 1
    assert "Erro:" in segundo.output

    faltante = runner.invoke(app, ["sites", "disable", "nao-existe"])
    assert faltante.exit_code == 1
    assert "não encontrado" in faltante.output


def test_cli_sites_link_device(db_session: Session) -> None:
    site = runner.invoke(app, ["sites", "add", "--name", "POP-LINK"])
    assert site.exit_code == 0, site.output
    dev = runner.invoke(app, ["devices", "add", "--name", "ne-cli", "--address", "10.20.0.1"])
    assert dev.exit_code == 0, dev.output
    vinculo = runner.invoke(app, ["sites", "link-device", "POP-LINK", "ne-cli"])
    assert vinculo.exit_code == 0, vinculo.output

    dev_db = db_session.scalar(select(models.Device).where(models.Device.name == "ne-cli"))
    site_db = db_session.scalar(select(models.Site).where(models.Site.name == "POP-LINK"))
    assert dev_db is not None and dev_db.site_id == site_db.id


def test_cli_organizations_add_list_disable() -> None:
    r = runner.invoke(
        app, ["organizations", "add", "--name", "Cliente CLI", "--asn", "64577"]
    )
    assert r.exit_code == 0, r.output
    assert "Cliente CLI" in r.output

    lista = runner.invoke(app, ["organizations", "list"])
    assert lista.exit_code == 0
    assert "Cliente CLI" in lista.output

    off = runner.invoke(app, ["organizations", "disable", "Cliente CLI"])
    assert off.exit_code == 0
    assert "desativada" in off.output

    oculto = runner.invoke(app, ["organizations", "list"])
    assert "Cliente CLI" not in oculto.output
    assert "Cliente CLI" in runner.invoke(app, ["organizations", "list", "--all"]).output


def test_cli_contacts_add_list_disable(db_session: Session) -> None:
    org = runner.invoke(
        app, ["organizations", "add", "--name", "Org CLI Contatos"]
    )
    assert org.exit_code == 0, org.output
    org_id = db_session.scalar(
        select(models.Organization.id).where(models.Organization.name == "Org CLI Contatos")
    )

    add = runner.invoke(
        app,
        [
            "contacts", "add",
            "--organization-id", str(org_id),
            "--name", "Ana NOC",
            "--email", "ana@example.com",
            "--kind", "noc",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "Ana NOC" in add.output

    assert "Ana NOC" in runner.invoke(app, ["contacts", "list"]).output
    filtrada = runner.invoke(app, ["contacts", "list", "--organization-id", str(org_id)])
    assert "Ana NOC" in filtrada.output

    off = runner.invoke(app, ["contacts", "disable", str(1)])
    assert off.exit_code == 0
    assert "Ana NOC" not in runner.invoke(app, ["contacts", "list"]).output
