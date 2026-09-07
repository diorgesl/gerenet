"""Smoke dos modelos MPLS — fase 4, spec §3."""
from gerenet.domain import models


def test_enums_do_spec():
    assert models.MPLS_ROLE == ("pe", "core")
    assert models.MPLS_OPER_STATUS == ("unknown", "up", "down", "partial")
    assert models.SERVICE_KIND == ("l2vc", "vsi")
    assert models.SERVICE_ENCAP == ("dot1q", "qinq", "ethernet_raw")
    assert models.SERVICE_SIGNALING == ("ldp",)
    assert "mpls_ac" in models.VLAN_KIND


def test_tabelas_esperadas():
    for classe, tabela in (
        (models.MplsDomain, "mpls_domains"),
        (models.MplsDomainMember, "mpls_domain_members"),
        (models.L2vcService, "l2vc_services"),
        (models.ServiceEndpoint, "service_endpoints"),
        (models.VsiService, "vsi_services"),
        (models.VsiMember, "vsi_members"),
    ):
        assert classe.__tablename__ == tabela


def test_criar_dominio_com_membro_e_servico(db_session):
    from gerenet.domain.schemas import DeviceCreate, SiteCreate
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.sites import create_site

    _site = create_site(db_session, SiteCreate(name="pop-mpls"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw1", management_address="10.0.0.11"), actor="cli")
    assert "mpls_flow_label" not in (dev.capabilities or [])
    dev.capabilities = ["mpls_flow_label"]
    db_session.flush()

    dom = models.MplsDomain(name="mpls-core-1")
    db_session.add(dom)
    db_session.flush()
    membro = models.MplsDomainMember(
        domain_id=dom.id, device_id=dev.id, loopback_address="10.255.0.1", role="pe",
    )
    db_session.add(membro)
    db_session.flush()

    servico = models.L2vcService(domain_id=dom.id, vc_id=100, name="cliente-acme")
    db_session.add(servico)
    db_session.flush()
    ep = models.ServiceEndpoint(
        kind="l2vc", l2vc_id=servico.id, device_id=dev.id,
        interface="10GE0/0/1", encapsulation="dot1q",
    )
    db_session.add(ep)
    db_session.flush()

    vsi = models.VsiService(domain_id=dom.id, vsi_id=200, name="vsi-cliente", vrp_name="VSI-CLIENTE-200")
    db_session.add(vsi)
    db_session.flush()
    db_session.add(models.VsiMember(vsi_id=vsi.id, device_id=dev.id))
    db_session.commit()

    assert dom.members[0].loopback_address == "10.255.0.1"
    assert servico.endpoints[0].device_id == dev.id
    assert vsi.vrp_name == "VSI-CLIENTE-200"
    assert dev.capabilities == ["mpls_flow_label"]


def test_mesmo_vid_em_devices_diferentes_do_mesmo_site(db_session):
    """§3/Q2: escopo da VLAN MPLS é por device — (site,vid) repetido entre switches é legítimo."""
    from gerenet.domain.schemas import DeviceCreate, SiteCreate
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.sites import create_site

    site = create_site(db_session, SiteCreate(name="pop-2"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-a", management_address="10.0.0.21"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-b", management_address="10.0.0.22"), actor="cli")
    for d in (d1, d2):
        db_session.add(models.Vlan(site_id=site.id, device_id=d.id, vid=500, kind="mpls_ac"))
    db_session.commit()
    assert len(
        db_session.query(models.Vlan)
        .filter(models.Vlan.site_id == site.id, models.Vlan.device_id.isnot(None), models.Vlan.vid == 500)
        .all()
    ) == 2


def test_mesmo_vid_no_mesmo_device_estoura_unique(db_session):
    """Mesmo (device, vid) = violação do índice parcial (dois serviços no mesmo switch)."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from gerenet.domain.schemas import DeviceCreate, SiteCreate
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.sites import create_site

    site = create_site(db_session, SiteCreate(name="pop-3"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-c", management_address="10.0.0.23"), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, device_id=dev.id, vid=501, kind="mpls_ac"))
    db_session.commit()
    db_session.add(models.Vlan(site_id=site.id, device_id=dev.id, vid=501, kind="mpls_ac"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
