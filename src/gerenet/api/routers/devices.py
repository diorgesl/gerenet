from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain.schemas import DeviceCreate, DeviceOut, DeviceUpdate
from gerenet.domain.services import devices as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/api/v1/devices", tags=["devices"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[DeviceOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_devices(session, include_disabled=include_disabled)


@router.post("", response_model=DeviceOut, status_code=201)
def criar(data: DeviceCreate, session: SessionDep) -> object:
    try:
        return svc.create_device(session, data)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(dev, campo, valor)
    if data.admin_status is False:
        dev.comm_status = "unknown"
    session.commit()
    session.refresh(dev)
    return dev
