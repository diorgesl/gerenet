"""Serviço VSI — fase 4, spec §3/§9.3 (modelo + consulta)."""
import pytest

from gerenet.automation.naming import vsi_nome
from gerenet.domain.schemas import (
    DeviceCreate,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member,
    create_domain,
    create_vsi,
    get_vsi,
    list_vsi,
)
from gerenet.domain.services.sites import create_site


def test_vsi_nome_golden():
    assert vsi_nome("acme americas", 12) == "VSI-ACME-AMERICAS-12"
    assert vsi_nome("cliente acme pop", 200) == "VSI-CLIENTE-ACME-POP-200"
    assert len(vsi_nome("x", 1)) <= 63
    with pytest.raises(ValidationError):
        vsi_nome("a" * 30, 1)  # sanitized > 20 chars: nome VRP estouraria o limite
    with pytest.raises(ValidationError):
        vsi_nome("", 1)


def test_criar_vsi_com_derivacao_do_nome_vrp(db_session):
    create_site(db_session, SiteCreate(name="pop-vsi"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-1", management_address="10.0.0.61"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-2", management_address="10.0.0.62"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.2.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.2.2"), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente acme", vsi_id=550, split_horizon=True,
        members=[d1.id, d2.id],
    ), actor="cli")
    assert vsi.vrp_name == "VSI-CLIENTE-ACME-550"
    assert vsi.signaling == "ldp"
    assert {m.device_id for m in vsi.members} == {d1.id, d2.id}
    assert get_vsi(db_session, vsi.id).vrp_name == vsi.vrp_name
    assert [v.id for v in list_vsi(db_session)] == [vsi.id]


def test_vsi_membro_nao_membro_do_dominio(db_session):
    create_site(db_session, SiteCreate(name="pop-vsi2"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-3", management_address="10.0.0.63"), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-4", management_address="10.0.0.64"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi2"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.3.1"), actor="cli")
    with pytest.raises(ValidationError):
        create_vsi(db_session, VsiCreate(
            domain_id=dom.id, name="vsi-membro", vsi_id=560, members=[d1.id, d2.id],
        ), actor="cli")


def test_vsi_id_duplicado_no_dominio(db_session):
    create_site(db_session, SiteCreate(name="pop-vsi3"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-5", management_address="10.0.0.65"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi3"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.4.1"), actor="cli")
    create_vsi(db_session, VsiCreate(domain_id=dom.id, name="a", vsi_id=570, members=[d1.id]), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(domain_id=dom.id, name="b", vsi_id=570, members=[d1.id]), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(domain_id=dom.id, name="a", vsi_id=571, members=[d1.id]), actor="cli")
