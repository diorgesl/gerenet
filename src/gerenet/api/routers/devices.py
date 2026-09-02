from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import DeviceCreate, DeviceOut, DeviceUpdate, SnapshotOut
from gerenet.domain.services import devices as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.validators import asn_valido
from gerenet.worker.tasks import enqueue_collect

router = APIRouter(prefix="/api/v1/devices", tags=["devices"], dependencies=[Depends(require_api_key)])

snap_router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[DeviceOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_devices(session, include_disabled=include_disabled)


@router.post("", response_model=DeviceOut, status_code=201)
def criar(data: DeviceCreate, session: SessionDep) -> object:
    try:
        return svc.create_device(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{device_id}", response_model=DeviceOut)
def detalhar(device_id: int, session: SessionDep) -> object:
    try:
        return svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{device_id}", response_model=DeviceOut)
def atualizar(device_id: int, data: DeviceUpdate, session: SessionDep) -> object:
    try:
        dev = svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    mudancas = data.model_dump(exclude_unset=True)
    try:
        if mudancas.get("asn") is not None and not asn_valido(mudancas["asn"]):
            raise ValidationError(f"ASN inválido ou reservado: {mudancas['asn']}.")
        antes = {campo: getattr(dev, campo) for campo in mudancas}
        desativando = (
            mudancas.get("admin_status") is False
            and set(mudancas) == {"admin_status"}
            and dev.admin_status is not False
        )
        if mudancas == {"admin_status": False} and not desativando:
            return dev  # repeat disable: sem transição, sem evento (Ruling 5)
        registrar(
            session,
            tipo="device.disable" if desativando else "device.update",
            ator="api",
            objeto="device",
            objeto_id=dev.id,
            antes=antes,
            depois=mudancas,
        )
        for campo, valor in mudancas.items():
            setattr(dev, campo, valor)
        if desativando:
            dev.comm_status = "unknown"
        session.commit()
        session.refresh(dev)
    except ValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dev


@router.post("/{device_id}/collect", status_code=202)
def coletar(device_id: int, session: SessionDep) -> dict:
    try:
        svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    resultado = enqueue_collect(device_id, actor="api", origin="api")
    if not resultado["queued"]:
        raise HTTPException(status_code=409, detail=resultado["message"])
    return resultado


@router.get("/{device_id}/snapshots", response_model=list[SnapshotOut])
def snapshots_do_device(device_id: int, session: SessionDep, limit: int = 20) -> list:
    try:
        svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    stmt = (
        select(models.DeviceSnapshot)
        .where(models.DeviceSnapshot.device_id == device_id)
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(min(max(limit, 1), 100))
    )
    return list(session.scalars(stmt))


@snap_router.get("/{snapshot_id}", response_model=SnapshotOut)
def detalhe_snapshot(snapshot_id: int, session: SessionDep) -> object:
    snap = session.get(models.DeviceSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot não encontrado.")
    return snap
