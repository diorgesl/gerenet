import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device, disable_device, get_device, list_devices
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


def test_cria_lista_desativa_device(db_session: Session) -> None:
    dev = create_device(
        db_session,
        DeviceCreate(name="sw1-acesso", management_address="10.0.0.2", model="S6730"),
        actor="cli",
    )
    assert dev.family is None
    assert list_devices(db_session) == [dev]

    dev2 = disable_device(db_session, dev.id, actor="cli")
    assert dev2.admin_status is False
    assert list_devices(db_session) == []  # desativado some da listagem padrão
    assert [d.name for d in list_devices(db_session, include_disabled=True)] == ["sw1-acesso"]


def test_nome_duplicado_vira_conflito(db_session: Session) -> None:
    create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.1"), actor="cli")
    with pytest.raises(ConflictError):
        create_device(db_session, DeviceCreate(name="r1", management_address="10.0.0.9"), actor="cli")


def test_ssh_port_persiste_e_default_e_none(db_session: Session) -> None:
    dev = create_device(
        db_session, DeviceCreate(name="ne8k", management_address="10.0.0.7", ssh_port=61341), actor="cli"
    )
    assert dev.ssh_port == 61341
    dev2 = create_device(db_session, DeviceCreate(name="ne8k2", management_address="10.0.0.8"), actor="cli")
    assert dev2.ssh_port is None  # connect usa 22 quando ausente


def test_get_device_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        get_device(db_session, 9999)


def test_asn_reservado_vira_erro_de_validacao(db_session: Session) -> None:
    with pytest.raises(ValidationError, match="reservado"):
        create_device(
            db_session, DeviceCreate(name="ne8k", management_address="10.0.0.7", asn=23456), actor="cli"
        )


def test_asn_4_bytes_valido_persiste(db_session: Session) -> None:
    dev = create_device(
        db_session,
        DeviceCreate(name="ne8k-4byte", management_address="10.0.0.11", asn=4000000000),
        actor="cli",
    )
    assert dev.asn == 4000000000


def test_criar_e_desativar_device_auditam(db_session: Session) -> None:
    dev = create_device(
        db_session,
        DeviceCreate(name="ne8k-aud", management_address="10.0.0.6"),
        actor="cli",
    )
    disable_device(db_session, dev.id, actor="cli")

    eventos = list(
        db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    )
    assert [e.type for e in eventos] == ["device.create", "device.disable"]
    assert eventos[0].actor == "cli"
    assert eventos[0].details["objeto"] == "device"
    assert eventos[0].details["objeto_id"] == dev.id
    assert eventos[0].details["antes"] is None
    assert "name" in eventos[0].details["depois"]
    assert eventos[1].details == {
        "objeto": "device",
        "objeto_id": dev.id,
        "antes": {"admin_status": True},
        "depois": {"admin_status": False},
    }


def test_disable_idempotente_nao_audita_duas_vezes(db_session: Session) -> None:
    dev = create_device(
        db_session, DeviceCreate(name="ne8k-aud2", management_address="10.0.0.8"), actor="cli"
    )
    disable_device(db_session, dev.id, actor="cli")
    disable_device(db_session, dev.id, actor="cli")  # no-op

    tipos = [
        e.type
        for e in db_session.scalars(select(models.AuditEvent).order_by(models.AuditEvent.id))
    ]
    assert tipos == ["device.create", "device.disable"]
