"""CR de L2VC — fase 4, spec §5 (escopo generalizado)."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from gerenet.domain.schemas import (
    ChangeRequestCreate,
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
)
from gerenet.domain.services.change_requests import create_change_request
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def l2vc(db_session):
    site = create_site(db_session, SiteCreate(name="pop-cr"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.0.0.81", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.0.0.82", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cr"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.8.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.8.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="cr-test", vc_id=500,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=301),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=302),
        ],
    ), actor="cli")
    return d1, d2, svc


def test_cr_l2vc_nasce_com_2_steps(db_session, l2vc):
    d1, d2, svc = l2vc
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", motivo="Ativar L2VC do cliente.",
    ), ator_id=None)
    assert cr.escopo == "l2vc"
    assert cr.l2vc_id == svc.id
    assert cr.circuit_id is None
    assert {s.device_id for s in cr.steps} == {d1.id, d2.id}
    assert cr.status == "rascunho"


def test_cr_l2vc_exige_l2vc_id(db_session):
    # o schema valida o escopo (model_validator) na CONSTRUÇÃO — PydanticValidationError
    with pytest.raises(PydanticValidationError):
        ChangeRequestCreate(escopo="l2vc", motivo="sem id")


def test_cr_l2vc_desativado(db_session, l2vc):
    from gerenet.domain.services.mpls import set_l2vc_status
    _, _, svc = l2vc
    set_l2vc_status(db_session, svc.id, admin_status=False, actor="cli")
    from gerenet.domain.services.errors import ConflictError
    with pytest.raises(ConflictError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="l2vc", l2vc_id=svc.id, motivo="off",
        ), ator_id=None)


def test_cr_l2vc_remocao_plano_vazio_sem_snapshot_da_remocao(db_session, l2vc):
    """Sem snapshot: provision ainda gera plano (aviso), mas a remoção exige coleta (§5.2)."""
    _, _, svc = l2vc
    create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", motivo="provisionar primeiro",
    ), ator_id=None)
    # remoção sem snapshot fresco: ValidationError (mesma regra do circuito)
    with pytest.raises(ValidationError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="l2vc", l2vc_id=svc.id, acao="remove", motivo="remover sem coleta",
        ), ator_id=None)


def test_cr_circuito_default_inalterada(db_session):
    """Regressão: CR de circuito continua com escopo default e circuit_id obrigatório."""
    from gerenet.domain.schemas import BgpSessionCreate, CircuitCreate, OrganizationCreate
    from gerenet.domain.services.bgp_sessions import create_session
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.ipam import reservar_circuito
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site, link_device

    site = create_site(db_session, SiteCreate(name="pop-reg"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="r-reg", management_address="10.0.0.83"), actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="reg", asn=64512), actor="cli")
    circ = create_circuit(db_session, CircuitCreate(
        code="reg-1", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1",
        edge_device_id=dev.id, stack="ipv4", vlan_mode="unica",
    ), actor="cli")
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(db_session, BgpSessionCreate(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.1.1", remote_address="100.64.1.2",
        asn_local=65000, asn_remote=64512,
    ), actor="cli")
    cr = create_change_request(db_session, ChangeRequestCreate(
        circuit_id=circ.id, acao="provision", motivo="regressão circuito",
    ), ator_id=None)
    assert cr.escopo == "circuito"
    assert cr.circuit_id == circ.id
