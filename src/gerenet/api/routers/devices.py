from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.automation.hostkeys import HostKeyScanError, fingerprint_ssh, normalize_fingerprint
from gerenet.config import get_settings
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import DeviceCreate, DeviceOut, DeviceUpdate, HostkeyIn, SnapshotOut
from gerenet.domain.services import credential_groups as groups_svc
from gerenet.domain.services import devices as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.validators import asn_valido
from gerenet.worker.tasks import enqueue_collect

router = APIRouter(prefix="/api/v1/devices", tags=["devices"], dependencies=[Depends(require_actor)])

snap_router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"], dependencies=[Depends(require_actor)])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[DeviceOut])
def listar(session: SessionDep, include_disabled: bool = False) -> list:
    return svc.list_devices(session, include_disabled=include_disabled)


@router.post("", response_model=DeviceOut, status_code=201)
def criar(
    data: DeviceCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.create_device(session, data, actor=actor.nome)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{device_id}", response_model=DeviceOut)
def detalhar(device_id: int, session: SessionDep) -> object:
    try:
        return svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{device_id}", response_model=DeviceOut)
def atualizar(
    device_id: int,
    data: DeviceUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    try:
        dev = svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    mudancas = data.model_dump(exclude_unset=True)
    try:
        if mudancas.get("asn") is not None and not asn_valido(mudancas["asn"]):
            raise ValidationError(f"ASN inválido ou reservado: {mudancas['asn']}.")
        if mudancas.get("credential_group_id") is not None:
            groups_svc.get_credential_group(session, mudancas["credential_group_id"])
        antes = {campo: getattr(dev, campo) for campo in mudancas}
        desativando = (
            mudancas.get("admin_status") is False
            and set(mudancas) == {"admin_status"}
            and dev.admin_status is not False
        )
        if mudancas == {"admin_status": False} and not desativando:
            return dev  # repeat disable: sem transição, sem evento (Ruling 5)
        reativando = (
            mudancas.get("admin_status") is True
            and set(mudancas) == {"admin_status"}
            and dev.admin_status is not True
        )
        if mudancas == {"admin_status": True} and not reativando:
            return dev  # repeat enable: sem transição, sem evento (Ruling 5)
        if reativando:
            return svc.enable_device(session, device_id, actor=actor.nome)
        registrar(
            session,
            tipo="device.disable" if desativando else "device.update",
            ator=actor.nome,
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
    except NotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dev


@router.post("/{device_id}/hostkey/scan")
def escanear_hostkey(device_id: int, session: SessionDep) -> dict:
    """Lê a host key do equipamento sem autenticar e devolve o fingerprint.

    Só usa a rede de gerência; a gravação continua dependendo da confirmação do
    operador (POST /hostkey), pois o fingerprint é a defesa contra MITM.
    """
    try:
        dev = svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    s = get_settings()
    try:
        fp = fingerprint_ssh(dev.management_address, dev.ssh_port or 22, s.connect_timeout)
    except HostKeyScanError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível obter a host key de {dev.name}: {exc}",
        ) from exc
    return {"fingerprint": fp}


@router.post("/{device_id}/hostkey", response_model=DeviceOut)
def registrar_hostkey(
    device_id: int,
    data: HostkeyIn,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    """Registra a fingerprint recebida (o operador o confere antes de chamar)."""
    try:
        dev = svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    fp = normalize_fingerprint(data.fingerprint)
    if not fp.startswith("sha256:"):
        raise HTTPException(
            status_code=400,
            detail="Fingerprint deve usar o esquema SHA-256 (ex.: sha256:AbCdEf).",
        )
    dev.host_key_fingerprint = fp
    registrar(
        session,
        tipo="hostkey.register",
        ator=actor.nome,
        objeto="device",
        objeto_id=dev.id,
        antes=None,
        depois={"fingerprint": fp},
    )
    session.commit()
    session.refresh(dev)
    return dev


@router.post("/{device_id}/collect", status_code=202)
def coletar(
    device_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> dict:
    try:
        svc.get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    resultado = enqueue_collect(device_id, actor=actor.nome, origin="api")
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
