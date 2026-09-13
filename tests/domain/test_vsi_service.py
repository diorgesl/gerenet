"""Serviço VSI — fase 4, spec §3/§9.3 (modelo + consulta)."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from gerenet.automation.naming import vsi_nome
from gerenet.domain.schemas import (
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
    VsiEndpointIn,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member,
    create_domain,
    create_l2vc,
    create_vsi,
    get_vsi,
    list_vsi,
    out_vsi,
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
    # site nos devices: a reserva da VLAN de AC exige equipamento com site
    site = create_site(db_session, SiteCreate(name="pop-vsi"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-1", management_address="10.0.0.61", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-2", management_address="10.0.0.62", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.2.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.2.2"), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente acme", vsi_id=550, split_horizon=True,
        endpoints=[VsiEndpointIn(device_id=d1.id), VsiEndpointIn(device_id=d2.id)],
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
            domain_id=dom.id, name="vsi-membro", vsi_id=560,
            endpoints=[VsiEndpointIn(device_id=d1.id), VsiEndpointIn(device_id=d2.id)],
        ), actor="cli")


def test_vsi_id_duplicado_no_dominio(db_session):
    site = create_site(db_session, SiteCreate(name="pop-vsi3"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-5", management_address="10.0.0.65", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi3"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.4.1"), actor="cli")
    create_vsi(db_session, VsiCreate(domain_id=dom.id, name="a", vsi_id=570,
                                     endpoints=[VsiEndpointIn(device_id=d1.id)]), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(domain_id=dom.id, name="b", vsi_id=570,
                                         endpoints=[VsiEndpointIn(device_id=d1.id)]), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(domain_id=dom.id, name="a", vsi_id=571,
                                         endpoints=[VsiEndpointIn(device_id=d1.id)]), actor="cli")


def test_vsi_nome_so_whitespace_rejeitado(db_session):
    create_site(db_session, SiteCreate(name="pop-vsi4"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-6", management_address="10.0.0.66"), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi4"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.5.1"), actor="cli")
    with pytest.raises(ValidationError):
        create_vsi(db_session, VsiCreate(domain_id=dom.id, name="   ", vsi_id=571,
                                         endpoints=[VsiEndpointIn(device_id=d1.id)]), actor="cli")


def test_out_vsi_preenche_device_e_domain_name(db_session):
    site = create_site(db_session, SiteCreate(name="pop-vsi5"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-7", management_address="10.0.0.67", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi5"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.6.1"), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente-out", vsi_id=572,
        endpoints=[VsiEndpointIn(device_id=d1.id)],
    ), actor="cli")
    out = out_vsi(vsi)
    assert out.endpoints[0].device_name == d1.name
    assert out.domain_name == dom.name


def _dominio_com_dois_membros(db_session, sufixo: str):
    """(d1, d2, dom) com site, devices e membros LDP prontos para um VSI."""
    site = create_site(db_session, SiteCreate(name=f"pop-vsi-{sufixo}"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name=f"sw-a-{sufixo}", management_address=f"10.9.1.{len(sufixo)}1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name=f"sw-b-{sufixo}", management_address=f"10.9.2.{len(sufixo)}1", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name=f"dom-{sufixo}"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.7.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.7.2"), actor="cli")
    return d1, d2, dom


def test_vsi_cria_ac_com_vid_default_igual_ao_vsi_id(db_session):
    """Sem vid explícito a ponta usa o VSI-ID, a convenção da operação."""
    d1, d2, dom = _dominio_com_dois_membros(db_session, "dflt")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente default", vsi_id=600,
        endpoints=[VsiEndpointIn(device_id=d1.id), VsiEndpointIn(device_id=d2.id)],
    ), actor="cli")
    assert sorted(ep.interface for ep in vsi.endpoints) == ["Vlanif600", "Vlanif600"]
    assert sorted(ep.vlan.vid for ep in vsi.endpoints if ep.vlan is not None) == [600, 600]
    assert {ep.device_id for ep in vsi.endpoints} == {d1.id, d2.id}
    assert len(vsi.endpoints[0].interface) == len("Vlanif600")


def test_vsi_aceita_vid_explicito_e_deriva_a_interface(db_session):
    d1, d2, dom = _dominio_com_dois_membros(db_session, "expl")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente explicito", vsi_id=601, flow_label=True,
        description="VSI do cliente",
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=900, mtu=9100),
                   VsiEndpointIn(device_id=d2.id, vid=901)],
    ), actor="cli")
    por_device = {ep.device_id: ep for ep in vsi.endpoints}
    assert por_device[d1.id].interface == "Vlanif900"
    assert por_device[d2.id].interface == "Vlanif901"
    assert vsi.flow_label is True
    assert vsi.description == "VSI do cliente"


def test_vsi_recusa_endpoint_duplicado(db_session):
    d1, _, dom = _dominio_com_dois_membros(db_session, "dupl")
    with pytest.raises(ValidationError, match="duplicado"):
        create_vsi(db_session, VsiCreate(
            domain_id=dom.id, name="cliente duplicado", vsi_id=602,
            endpoints=[VsiEndpointIn(device_id=d1.id), VsiEndpointIn(device_id=d1.id)],
        ), actor="cli")


def test_vsi_recusa_vid_ocupado_no_mesmo_equipamento(db_session):
    d1, d2, dom = _dominio_com_dois_membros(db_session, "ocup")
    create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="primeiro", vsi_id=603,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=800), VsiEndpointIn(device_id=d2.id, vid=800)],
    ), actor="cli")
    with pytest.raises(ConflictError):
        create_vsi(db_session, VsiCreate(
            domain_id=dom.id, name="segundo", vsi_id=604,
            endpoints=[VsiEndpointIn(device_id=d1.id, vid=800), VsiEndpointIn(device_id=d2.id, vid=801)],
        ), actor="cli")


def test_vsi_recusa_vid_de_ac_ja_usado_por_l2vc(db_session):
    """AC de L2VC na mesma VLAN/equipamento não pode virar AC de VSI.

    A ponta de L2VC tem vsi_id NULL: o filtro por `vsi_id != <id>` não casa em
    SQL (NULL != id é NULL), então o conflito passaria batido e os dois
    serviços dividiriam a mesma VLAN de AC no equipamento.
    """
    d1, d2, dom = _dominio_com_dois_membros(db_session, "l2vx")
    create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="l2vc antes", vc_id=805,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=800),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=801),
        ],
    ), actor="cli")
    with pytest.raises(ConflictError, match="L2VC"):
        create_vsi(db_session, VsiCreate(
            domain_id=dom.id, name="vsi depois", vsi_id=606,
            endpoints=[VsiEndpointIn(device_id=d1.id, vid=800)],
        ), actor="cli")


def test_vsi_cadastro_exige_ao_menos_um_endpoint(db_session):
    _, _, dom = _dominio_com_dois_membros(db_session, "vazio")
    with pytest.raises(PydanticValidationError):
        VsiCreate(domain_id=dom.id, name="sem ponta", vsi_id=605, endpoints=[])
