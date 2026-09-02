import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device, disable_device, get_device, list_devices
from gerenet.domain.services.errors import ConflictError, NotFoundError


def test_cria_lista_desativa_device(db_session: Session) -> None:
    dev = create_device(db_session, DeviceCreate(name="sw1-acesso", management_address="10.0.0.2", model="S6730"))
    assert dev.family is None
    assert list_devices(db_session) == [dev]

    dev2 = disable_device(db_session, dev.id)
    assert dev2.admin_status is False
    assert list_devices(db_session) == []  # desativado some da listagem padrão
    assert [d.name for d in list_devices(db_session, include_disabled=True)] == ["sw1-acesso"]


def test_nome_duplicado_vira_conflito(db_session: Session) -> None:
    create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.1"))
    with pytest.raises(ConflictError):
        create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.9"))


def test_ssh_port_persiste_e_default_e_none(db_session: Session) -> None:
    dev = create_device(db_session, DeviceCreate(name="ne8k", management_address="10.0.0.7", ssh_port=61341))
    assert dev.ssh_port == 61341
    dev2 = create_device(db_session, DeviceCreate(name="ne8k2", management_address="10.0.0.8"))
    assert dev2.ssh_port is None  # connect usa 22 quando ausente


def test_get_device_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        get_device(db_session, 9999)
