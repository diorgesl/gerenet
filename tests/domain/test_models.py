from sqlalchemy.orm import Session

from gerenet.domain.models import (
    Circuit,
    Contact,
    CredentialGroup,
    Device,
    IpPrefix,
    Organization,
    Site,
    Vlan,
)


def test_device_roundtrip(db_session: Session) -> None:
    grupo = CredentialGroup(
        name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao"
    )
    db_session.add(grupo)
    db_session.commit()

    dev = Device(name="r1-borda", management_address="10.0.0.1", credential_group_id=grupo.id)
    db_session.add(dev)
    db_session.commit()

    assert db_session.get(Device, dev.id).name == "r1-borda"
    assert db_session.get(CredentialGroup, grupo.id).vault_path.endswith("automacao")


def test_nucleo_so_t_roundtrip(db_session: Session) -> None:
    site = Site(name="pop-spo-01", p2p_ipv4_block="100.64.0.0/24")
    db_session.add(site)
    db_session.flush()

    org = Organization(name="Cliente X", asn=64512)
    db_session.add(org)
    db_session.flush()

    contato = Contact(organization_id=org.id, name="Fulano", email="noc@x.com.br")
    db_session.add(contato)

    dev = Device(name="ne8k-lab", management_address="10.0.0.9", site_id=site.id)
    db_session.add(dev)
    db_session.flush()

    circ = Circuit(
        code="CIRC-0001",
        organization_id=org.id,
        site_id=site.id,
        access_device_id=dev.id,
        access_port="GE0/0/1",
        edge_device_id=dev.id,
    )
    db_session.add(circ)
    db_session.flush()

    vlan = Vlan(site_id=site.id, vid=100, circuit_id=circ.id)
    rede = IpPrefix(site_id=site.id, network="100.64.0.0/31", circuit_id=circ.id)
    db_session.add_all([vlan, rede])
    db_session.commit()

    assert db_session.get(Site, site.id).name == "pop-spo-01"
    assert db_session.get(Organization, org.id).asn == 64512
    assert db_session.get(Circuit, circ.id).vlan_mode == "unica"
    assert db_session.get(Vlan, vlan.id).status == "reservada"
    assert db_session.get(IpPrefix, rede.id).kind == "p2p"
