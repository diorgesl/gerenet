from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError


def create_device(session: Session, data: DeviceCreate) -> models.Device:
    dev = models.Device(**data.model_dump())
    session.add(dev)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Já existe um equipamento com esse nome.") from exc
    session.refresh(dev)
    return dev


def get_device(session: Session, device_id: int) -> models.Device:
    dev = session.get(models.Device, device_id)
    if dev is None:
        raise NotFoundError(f"Equipamento {device_id} não encontrado.")
    return dev


def list_devices(session: Session, include_disabled: bool = False) -> list[models.Device]:
    stmt = select(models.Device).order_by(models.Device.name)
    if not include_disabled:
        stmt = stmt.where(models.Device.admin_status.is_(True))
    return list(session.scalars(stmt))


def disable_device(session: Session, device_id: int) -> models.Device:
    dev = get_device(session, device_id)
    dev.admin_status = False
    session.commit()
    return dev


def touch_collection(
    session: Session,
    device: models.Device,
    *,
    ok: bool,
    version: str | None = None,
    uptime: str | None = None,
) -> None:
    """Atualiza o estado de comunicação do device após uma coleta."""
    device.comm_status = "ok" if ok else "fail"
    device.consecutive_failures = 0 if ok else device.consecutive_failures + 1
    if ok:
        device.last_collected_at = datetime.now(timezone.utc)
        if version:
            device.vrp_version = version
        if uptime:
            device.uptime = uptime
    session.commit()
