import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import DeviceCreate, SiteCreate, SiteUpdate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.sites import (
    create_site,
    disable_site,
    link_device,
    list_sites,
    update_site,
)


def test_cria_lista_e_desativa_site(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-spo-01", uf="SP"), actor="cli")
    assert site.name == "pop-spo-01"
    assert [s.name for s in list_sites(db_session)] == ["pop-spo-01"]

    disable_site(db_session, site.id, actor="cli")
    assert list_sites(db_session) == []
    assert [s.name for s in list_sites(db_session, include_disabled=True)] == ["pop-spo-01"]


def test_site_nome_duplicado_vira_conflito(db_session: Session) -> None:
    create_site(db_session, SiteCreate(name="pop-a"), actor="cli")
    with pytest.raises(ConflictError):
        create_site(db_session, SiteCreate(name="pop-a"), actor="cli")


def test_site_com_blocos_invalidos_rejeitado(db_session: Session) -> None:
    with pytest.raises(ValidationError):
        create_site(db_session, SiteCreate(name="pop-x", p2p_ipv4_block="300.0.0.0/24"), actor="cli")
    with pytest.raises(ValidationError):
        create_site(db_session, SiteCreate(name="pop-y", p2p_ipv6_base="2001::zz/48"), actor="cli")


def test_update_site_altera_campos(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-a", city="São Paulo"), actor="cli")
    atualizado = update_site(db_session, site.id, SiteUpdate(city="Campinas"), actor="cli")
    assert atualizado.city == "Campinas"


def test_link_device_valida_site_e_device(db_session: Session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-a"), actor="cli")
    dev = create_device(
        db_session, DeviceCreate(name="ne8k-link", management_address="10.0.0.9"), actor="cli"
    )
    dev = link_device(db_session, site.id, dev.id, actor="cli")
    assert dev.site_id == site.id
    with pytest.raises(NotFoundError):
        link_device(db_session, 9999, dev.id, actor="cli")
    with pytest.raises(NotFoundError):
        link_device(db_session, site.id, 9999, actor="cli")
