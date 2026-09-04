"""Reconciliation (divergência read-only) e desired-config (spec §8)."""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.automation.reconcile import reconciliar_device
from gerenet.automation.render import render_desejado
from gerenet.db import get_db
from gerenet.domain.schemas import BlocoOut, DesiredConfigOut, ReconcileItemOut, ReconcileOut
from gerenet.domain.services.errors import NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/reconciliation", tags=["reconciliation"],
    dependencies=[Depends(require_api_key)],
)
config_router = APIRouter(
    prefix="/api/v1/devices", tags=["devices"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ReconcileOut)
def reconciliar(
    session: SessionDep, device_id: int | None = None, snapshot_id: int | None = None
) -> ReconcileOut:
    """Divergência desejado × encontrado; exatamente um filtro (ruling 9)."""
    if (device_id is None) == (snapshot_id is None):
        raise HTTPException(
            status_code=400, detail="Informe exatamente um de device_id ou snapshot_id."
        )
    try:
        resultado = reconciliar_device(session, device_id, snapshot_id=snapshot_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReconcileOut(
        device_id=resultado.device_id,
        snapshot_id=resultado.snapshot_id,
        aviso=resultado.aviso,
        gerado_em=datetime.now(UTC),
        items=[ReconcileItemOut(**vars(i)) for i in resultado.items],
    )


@config_router.get("/{device_id}/desired-config", response_model=DesiredConfigOut)
def config_desejada(device_id: int, session: SessionDep) -> DesiredConfigOut:
    """Blocos de configuração desejada do device (render puro, read-only)."""
    try:
        resultado = render_desejado(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DesiredConfigOut(
        device_id=resultado.device_id,
        gerado_em=datetime.now(UTC),
        texto=resultado.texto,
        blocos=[BlocoOut(tipo=b.tipo, objeto=b.objeto, objeto_id=b.objeto_id, comandos=b.comandos)
                for b in resultado.blocos],
    )
