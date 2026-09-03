import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli import bgp_sessions as cli_bgp
from gerenet.cli.main import app
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device
from gerenet.secrets.vault_store import VaultSecretStore

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


def test_cli_circuits_reserve_desativado_da_erro(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="POP-CIRC-CLI-ERR"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Org Circ CLI Err", asn=64514), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-circ-cli-err", management_address="10.9.1.4"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-circ-cli-err", management_address="10.9.1.3", asn=64602),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")

    add = runner.invoke(
        app,
        [
            "circuits", "add", "--code", "CIRC-CLI-ERR",
            "--organization-id", str(org.id), "--site-id", str(site.id),
            "--access-device-id", str(sw.id), "--access-port", "GE0/0/1",
            "--edge-device-id", str(ne.id),
        ],
    )
    assert add.exit_code == 0, add.output

    off = runner.invoke(app, ["circuits", "disable", "CIRC-CLI-ERR"])
    assert off.exit_code == 0

    reserva = runner.invoke(app, ["circuits", "reserve", "CIRC-CLI-ERR"])
    assert reserva.exit_code == 1
    assert "Erro:" in reserva.output
    assert "desativado" in reserva.output


def test_cli_circuits_add_reserve_disable(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="POP-CIRC-CLI"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Org Circ CLI", asn=64513), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-circ-cli", management_address="10.9.1.2"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-circ-cli", management_address="10.9.1.1", asn=64601),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")

    add = runner.invoke(
        app,
        [
            "circuits", "add", "--code", "CIRC-CLI-1",
            "--organization-id", str(org.id), "--site-id", str(site.id),
            "--access-device-id", str(sw.id), "--access-port", "GE0/0/1",
            "--edge-device-id", str(ne.id),
        ],
    )
    assert add.exit_code == 0, add.output
    assert "CIRC-CLI-1" in add.output
    assert "CIRC-CLI-1" in runner.invoke(app, ["circuits", "list"]).output

    reserva = runner.invoke(app, ["circuits", "reserve", "CIRC-CLI-1"])
    assert reserva.exit_code == 0, reserva.output

    circ_db = db_session.scalar(select(models.Circuit).where(models.Circuit.code == "CIRC-CLI-1"))
    assert circ_db is not None
    assert db_session.scalar(
        select(models.Vlan).where(models.Vlan.circuit_id == circ_db.id)
    ) is not None

    repetida = runner.invoke(app, ["circuits", "reserve", "CIRC-CLI-1"])
    assert repetida.exit_code == 0
    vlans = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_db.id)))
    assert len(vlans) == 1

    off = runner.invoke(app, ["circuits", "disable", "CIRC-CLI-1"])
    assert off.exit_code == 0
    assert "CIRC-CLI-1" not in runner.invoke(app, ["circuits", "list"]).output

    faltante = runner.invoke(app, ["circuits", "reserve", "nao-existe"])
    assert faltante.exit_code == 1
    assert "não encontrado" in faltante.output


def _ambiente_bgp(db_session: Session) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-bgp-cli"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP CLI", asn=64513), actor="cli"
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-bgp-cli", management_address="10.8.2.2"), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne-bgp-cli", management_address="10.8.2.1", asn=64610),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _circuito_cli(db_session: Session, env: dict, code: str) -> int:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    return create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne_id"],
        ),
        actor="cli",
    ).id


def test_cli_bgp_sessions_add_list_disable(db_session: Session) -> None:
    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-CLI")

    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.10.1", "--remote-address", "100.64.10.2",
            "--asn-remote", "64513", "--maximum-prefix", "500",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "criada" in add.output

    lista = runner.invoke(app, ["bgp-sessions", "list"])
    assert lista.exit_code == 0
    assert "100.64.10.1" in lista.output

    off = runner.invoke(app, ["bgp-sessions", "disable", "1"])
    assert off.exit_code == 0
    assert "100.64.10.1" not in runner.invoke(app, ["bgp-sessions", "list"]).output
    assert "100.64.10.1" in runner.invoke(app, ["bgp-sessions", "list", "--all"]).output


def test_cli_bgp_sessions_password_set(db_session: Session) -> None:
    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-PW")
    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.11.1", "--remote-address", "100.64.11.2",
        ],
    )
    assert add.exit_code == 0, add.output

    setar = runner.invoke(
        app, ["bgp-sessions", "password", "set", "1"], input="md5-cli-segredo\nmd5-cli-segredo\n"
    )
    assert setar.exit_code == 0, setar.output
    assert "Vault" in setar.output

    sessao = db_session.scalar(select(models.BgpSession).where(models.BgpSession.id == 1))
    assert sessao is not None and sessao.password_ref == "gerenet/bgp-sessions/1/password"

    settings = Settings(_env_file=None)
    store = VaultSecretStore(settings.vault_url, settings.vault_token)
    assert store.get_secret(sessao.password_ref) == {"password": "md5-cli-segredo"}


def test_cli_bgp_sessions_password_vault_fora_do_ar(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _ambiente_bgp(db_session)
    circ = _circuito_cli(db_session, env, "CIRC-BGP-PW-ERR")
    add = runner.invoke(
        app,
        [
            "bgp-sessions", "add",
            "--circuit-id", str(circ), "--device-id", str(env["ne_id"]),
            "--afi", "ipv4",
            "--local-address", "100.64.12.1", "--remote-address", "100.64.12.2",
        ],
    )
    assert add.exit_code == 0, add.output

    def _falha(*args: object, **kwargs: object) -> None:
        raise RuntimeError("conexão recusada")

    monkeypatch.setattr(cli_bgp, "VaultSecretStore", _falha)
    setar = runner.invoke(
        app, ["bgp-sessions", "password", "set", "1"], input="md5-x\nmd5-x\n"
    )
    assert setar.exit_code == 1
    assert "Vault indisponível" in setar.output


def test_cli_autorizacoes_ciclo_de_vida(db_session: Session) -> None:
    org = create_organization(
        db_session, OrganizationCreate(name="Down CLI A", asn=64523), actor="cli"
    )
    add = runner.invoke(
        app,
        [
            "prefix-authorizations", "add",
            "--organization-id", str(org.id), "--family", "ipv4",
            "--prefix", "203.0.113.0/24",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "criada" in add.output

    lista = runner.invoke(app, ["prefix-authorizations", "list"])
    assert lista.exit_code == 0
    assert "203.0.113.0/24" in lista.output

    off = runner.invoke(app, ["prefix-authorizations", "disable", "1"])
    assert off.exit_code == 0
    assert "203.0.113.0/24" not in runner.invoke(app, ["prefix-authorizations", "list"]).output
    assert (
        "203.0.113.0/24"
        in runner.invoke(app, ["prefix-authorizations", "list", "--all"]).output
    )


def test_cli_policy_profiles_lista(db_session: Session) -> None:
    lista = runner.invoke(app, ["policy-profiles", "list"])
    assert lista.exit_code == 0
    assert len(lista.output.strip().splitlines()) == 6  # seeds de exportação

    so_export = runner.invoke(app, ["policy-profiles", "list", "--direction", "export"])
    assert so_export.exit_code == 0
    assert so_export.output == lista.output

    so_import = runner.invoke(app, ["policy-profiles", "list", "--direction", "import"])
    assert so_import.exit_code == 0
    assert so_import.output.strip() == ""

    invalida = runner.invoke(app, ["policy-profiles", "list", "--direction", "foo"])
    assert invalida.exit_code == 1
    assert "Erro:" in invalida.output


def test_cli_prefix_authorizations_family_invalida() -> None:
    invalida = runner.invoke(app, ["prefix-authorizations", "list", "--family", "foo"])
    assert invalida.exit_code == 1
    assert "Erro:" in invalida.output


def test_cli_sites_add_bloco_p2p_grande_da_erro() -> None:
    invalido = runner.invoke(app, ["sites", "add", "--name", "POP-BLOCO", "--p2p-ipv4-block", "x" * 65])
    assert invalido.exit_code == 1
    assert "Erro:" in invalido.output
