"""Serviço L2VC — fase 4, validações §9.2."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from gerenet.domain import models
from gerenet.domain.schemas import (
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member,
    create_domain,
    create_l2vc,
    get_l2vc,
    list_l2vc,
    set_l2vc_status,
)
from gerenet.domain.services.sites import create_site

# Regras que o schema rejeita (Literal, min_length) lançam PydanticValidationError
# na CONSTRUÇÃO, antes de chegar ao serviço — os testes usam alias separado do
# ValidationError do domínio (gerenet.domain.services.errors).


@pytest.fixture()
def pares(db_session):
    site = create_site(db_session, SiteCreate(name="pop-l2vc"), actor="cli")
    # Correção do controller (ruling T3): ponta MPLS exige device com site —
    # vlans.site_id é NOT NULL e reservar_vlan_ac valida isso.
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.0.0.51", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.0.0.52", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-l2vc"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.1.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.1.2"), actor="cli")
    return site, d1, d2, dom


def _create(db_session, dom, d1, d2, **kw):
    # Correção do brief (T4): o helper não retirava "endpoints" do **kw — os
    # testes de simetria passam endpoints explícitos e caíam em TypeError
    # ("multiple values for keyword argument 'endpoints'").
    data = L2vcCreate(
        domain_id=dom.id, name=kw.pop("name", "cliente-teste"),
        endpoints=kw.pop("endpoints", [
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=101),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=102),
        ]),
        **kw,
    )
    return create_l2vc(db_session, data, actor="cli")


def test_criar_com_reservas_e_simetria(db_session, pares):
    _, d1, d2, dom = pares
    svc = _create(db_session, dom, d1, d2)
    assert svc.vc_id is not None
    assert svc.mtu == 1500
    assert len(svc.endpoints) == 2
    assert all(ep.vlan_id is not None for ep in svc.endpoints)
    vlan_a = db_session.get(models.Vlan, svc.endpoints[0].vlan_id)
    assert vlan_a.kind == "mpls_ac" and vlan_a.device_id == d1.id


def test_vc_id_duplicado_409(db_session, pares):
    _, d1, d2, dom = pares
    _create(db_session, dom, d1, d2, vc_id=1000)
    with pytest.raises(ConflictError):
        _create(db_session, dom, d1, d2, name="dupe", vc_id=1000)
    with pytest.raises(ConflictError):
        _create(db_session, dom, d1, d2, name="dupe2", vc_id=1000 + 0)  # mesmo ID, outra ponta


def test_nome_duplicado_por_dominio(db_session, pares):
    _, d1, d2, dom = pares
    _create(db_session, dom, d1, d2, name="mesmo")
    with pytest.raises(ConflictError):
        _create(db_session, dom, d1, d2, name="mesmo", vc_id=None)


def test_pontas_iguais_rejeitado(db_session, pares):
    _, d1, _, dom = pares
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d1, name="x")


def test_loopback_do_par_obrigatorio(db_session, pares):
    _, d1, d2, dom = pares
    # remove o membro B: a ponta B não tem loopback LDP
    from gerenet.domain.services.mpls import remove_domain_member
    remove_domain_member(db_session, dom.id, d2.id, actor="cli")
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d2, name="sem-par")


def test_encap_e_mtu_simetricos(db_session, pares):
    _, d1, d2, dom = pares
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d2, name="assimetrico", endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=111, mtu=1500),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="qinq", vid=222, inner_vlan=31, mtu=1500),
        ])
    with pytest.raises(ValidationError):
        _create(db_session, dom, d1, d2, name="mtu-diff", endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=111, mtu=1500),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=222, mtu=1600),
        ])


def test_ethernet_raw_fora_do_ciclo(db_session, pares):
    _, d1, d2, dom = pares
    # ethernet_raw nem passa do schema: Literal rejeita na construção
    with pytest.raises(PydanticValidationError):
        L2vcCreate(
            domain_id=dom.id, name="raw", endpoints=[
                L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="ethernet_raw"),
                L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="ethernet_raw"),
            ],
        )


def test_qinq_exige_inner_vlan(db_session, pares):
    _, d1, d2, dom = pares
    data = L2vcCreate(
        domain_id=dom.id, name="qinq-sem-inner", endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="qinq", vid=211),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="qinq", vid=212),
        ],
    )
    with pytest.raises(ValidationError):
        create_l2vc(db_session, data, actor="cli")


def test_list_get_status(db_session, pares):
    _, d1, d2, dom = pares
    svc = _create(db_session, dom, d1, d2)
    assert get_l2vc(db_session, svc.id).id == svc.id
    assert [s.id for s in list_l2vc(db_session)] == [svc.id]
    assert list_l2vc(db_session, domain_id=dom.id)[0].vc_id == svc.vc_id
    assert list_l2vc(db_session, domain_id=9999) == []
    set_l2vc_status(db_session, svc.id, admin_status=False, actor="cli")
    assert get_l2vc(db_session, svc.id).admin_status is False
    assert list_l2vc(db_session) == []  # desativado some da lista padrão
    with pytest.raises(NotFoundError):
        get_l2vc(db_session, 99999)
