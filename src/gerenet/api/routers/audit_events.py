from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.schemas import AuditEventOut

router = APIRouter(
    prefix="/api/v1/audit-events",
    tags=["audit-events"],
    dependencies=[Depends(require_api_key)],
)

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[AuditEventOut])
def listar(
    session: SessionDep,
    tipo: str | None = None,
    objeto: str | None = None,
    objeto_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list:
    """Trilha de auditoria (§18) — somente leitura, mais recentes primeiro."""
    stmt = select(models.AuditEvent).order_by(models.AuditEvent.id.desc()).limit(limit)
    if tipo is not None:
        stmt = stmt.where(models.AuditEvent.type == tipo)
    if objeto is not None:
        stmt = stmt.where(
            text("audit_events.details ->> 'objeto' = :objeto").bindparams(objeto=objeto)
        )
    if objeto_id is not None:
        stmt = stmt.where(
            text("CAST(audit_events.details ->> 'objeto_id' AS INTEGER) = :objeto_id").bindparams(
                objeto_id=objeto_id
            )
        )
    return list(session.scalars(stmt))
