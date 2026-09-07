"""Serviço de domínios MPLS — fase 4, spec §3 (mpls_domains/members)."""
import pytest

from gerenet.domain.schemas import (
    DeviceCreate,
    MplsDomainCreate,
    MplsDomainUpdate,
    MplsMemberIn,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member,
    create_domain,
    get_domain,
    list_domains,
    remove_domain_member,
    update_domain,
)


@pytest.fixture()
def dominio(db_session):
    return create_domain(db_session, MplsDomainCreate(name="mpls-pop-1", description="POP teste"), actor="cli")


def test_criar_e_listar(db_session, dominio):
    assert dominio.id is not None
    assert list_domains(db_session)[0].name == "mpls-pop-1"
    assert get_domain(db_session, dominio.id).description == "POP teste"


def test_nome_duplicado_409(db_session):
    create_domain(db_session, MplsDomainCreate(name="mpls-x"), actor="cli")
    with pytest.raises(ConflictError):
        create_domain(db_session, MplsDomainCreate(name="mpls-x"), actor="cli")


def test_get_inexistente_404(db_session):
    with pytest.raises(NotFoundError):
        get_domain(db_session, 999)


def test_dominio_desativado_nao_recebe_membro_nem_update_ativo(db_session, dominio):
    update_domain(db_session, dominio.id, MplsDomainUpdate(admin_status=False), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw1", management_address="10.0.0.31"), actor="cli")
    with pytest.raises(ConflictError):
        add_domain_member(db_session, dominio.id, MplsMemberIn(
            device_id=dev.id, loopback_address="10.255.0.1", role="pe",
        ), actor="cli")


def test_membro_exige_loopback_e_nao_duplica(db_session, dominio):
    dev = create_device(db_session, DeviceCreate(name="sw2", management_address="10.0.0.32"), actor="cli")
    with pytest.raises(ValidationError):
        add_domain_member(db_session, dominio.id, MplsMemberIn(
            device_id=dev.id, loopback_address="", role="pe",
        ), actor="cli")
    add_domain_member(db_session, dominio.id, MplsMemberIn(
        device_id=dev.id, loopback_address="10.255.0.2", role="pe",
    ), actor="cli")
    with pytest.raises(ConflictError):
        add_domain_member(db_session, dominio.id, MplsMemberIn(
            device_id=dev.id, loopback_address="10.255.0.3", role="pe",
        ), actor="cli")
    remove_domain_member(db_session, dominio.id, dev.id, actor="cli")
    assert not any(m.device_id == dev.id for m in get_domain(db_session, dominio.id).members)


def test_membro_de_outra_familia_nao_entra_em_dominio_desativado(db_session):
    """Regressão: desativar não apaga membros (objetos em uso são desativados, §14.1)."""
    dominio = create_domain(db_session, MplsDomainCreate(name="mpls-y"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw3", management_address="10.0.0.33"), actor="cli")
    add_domain_member(db_session, dominio.id, MplsMemberIn(
        device_id=dev.id, loopback_address="10.255.0.9", role="core",
    ), actor="cli")
    update_domain(db_session, dominio.id, MplsDomainUpdate(admin_status=False), actor="cli")
    assert len(get_domain(db_session, dominio.id).members) == 1
