"""CLI MPLS — fase 4, spec §9: smoke via CliRunner + DB real."""
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain.schemas import DeviceCreate, MplsDomainCreate, MplsMemberIn, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import add_domain_member, create_domain
from gerenet.domain.services.sites import create_site

runner = CliRunner()


def _dominio(db_session: Session) -> tuple[int, int, int]:
    # site_id em ambos: a reserva de VLAN de AC (T3) exige equipamento com site.
    site = create_site(db_session, SiteCreate(name="pop-mpls-cli"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-mpls-cli-1", management_address="10.0.0.81", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-mpls-cli-2", management_address="10.0.0.82", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cli", description="teste"), actor="cli")
    add_domain_member(db_session, dom.id,
                      MplsMemberIn(device_id=d1.id, loopback_address="10.255.8.1", role="pe"), actor="cli")
    add_domain_member(db_session, dom.id,
                      MplsMemberIn(device_id=d2.id, loopback_address="10.255.8.2", role="pe"), actor="cli")
    db_session.commit()
    return d1.id, d2.id, dom.id


def test_domain_add_list(db_session: Session) -> None:
    _dominio(db_session)
    add = runner.invoke(app, ["mpls", "domain", "add", "--name", "dom-cli-2", "--description", "via cli"])
    assert add.exit_code == 0, add.output
    assert "Domínio" in add.output and "dom-cli-2" in add.output
    lista = runner.invoke(app, ["mpls", "domain", "list"])
    assert lista.exit_code == 0, lista.output
    assert "dom-cli" in lista.output


def test_mpls_l2vc_add_list(db_session: Session) -> None:
    d1, d2, dom_id = _dominio(db_session)
    add = runner.invoke(app, [
        "mpls", "l2vc", "add",
        "--domain-id", str(dom_id), "--name", "l2vc-cli",
        "--device-a", str(d1), "--interface-a", "10GE0/0/1", "--vid-a", "501",
        "--device-b", str(d2), "--interface-b", "10GE0/0/2", "--vid-b", "502",
    ])
    assert add.exit_code == 0, add.output
    assert "l2vc-cli" in add.output and "VC-ID" in add.output
    lista = runner.invoke(app, ["mpls", "l2vc", "list"])
    assert lista.exit_code == 0, lista.output
    assert "l2vc-cli" in lista.output


def test_mpls_vsi_list_vazio(db_session: Session) -> None:
    lista = runner.invoke(app, ["mpls", "vsi", "list"])
    assert lista.exit_code == 0, lista.output
