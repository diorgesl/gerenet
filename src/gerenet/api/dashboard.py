from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from gerenet.api.deps import SessionDep, require_actor
from gerenet.domain import models
from gerenet.domain.schemas import (
    AllocAggOut,
    AuditEventOut,
    BgpSessionsAggOut,
    CircuitsAggOut,
    DashboardOut,
    DevicesAggOut,
    JobResumoOut,
    PerDeviceOut,
    SnapshotResumoOut,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=[Depends(require_actor)])


@router.get("", response_model=DashboardOut)
def dashboard(session: SessionDep) -> DashboardOut:
    """Agregações do dashboard §16.1 — sem chamadas a reconcile (read-only barato)."""
    agora = datetime.now(UTC)

    devices = list(
        session.scalars(select(models.Device).options(selectinload(models.Device.site)).order_by(models.Device.name))
    )
    by_status: dict[str, int] = {}
    for status in ("unknown", "ok", "fail"):
        by_status[status] = sum(1 for d in devices if d.comm_status == status)

    per_device: list[PerDeviceOut] = []
    for d in devices:
        snap = session.scalar(
            select(models.DeviceSnapshot)
            .where(models.DeviceSnapshot.device_id == d.id)
            .order_by(models.DeviceSnapshot.id.desc())
            .limit(1)
        )
        job = session.scalar(
            select(models.JobRun)
            .where(
                models.JobRun.device_id == d.id,
                models.JobRun.kind == "collect",
                models.JobRun.status.in_(["queued", "running"]),
            )
            .order_by(models.JobRun.id.desc())
            .limit(1)
        )
        idade = (agora - snap.started_at).total_seconds() if snap is not None else None
        per_device.append(
            PerDeviceOut(
                device_id=d.id,
                name=d.name,
                site_id=d.site_id,
                site_name=d.site.name if d.site is not None else None,
                comm_status=d.comm_status,
                last_collected_at=d.last_collected_at,
                snapshot_age_seconds=idade,
                latest_snapshot=(
                    SnapshotResumoOut(id=snap.id, status=snap.status, started_at=snap.started_at)
                    if snap is not None else None
                ),
                active_job=JobResumoOut(id=job.id, status=job.status) if job is not None else None,
            )
        )

    sessoes = list(session.scalars(select(models.BgpSession)))
    circuitos = list(session.scalars(select(models.Circuit)))
    vlans = list(session.scalars(select(models.Vlan)))
    prefixos = list(session.scalars(select(models.IpPrefix)))
    auditoria = list(
        session.scalars(
            select(models.AuditEvent).order_by(models.AuditEvent.id.desc()).limit(20)
        )
    )

    return DashboardOut(
        devices=DevicesAggOut(
            total=len(devices),
            active=sum(1 for d in devices if d.admin_status),
            with_snapshot=sum(1 for d in devices if d.last_collected_at is not None),
            by_comm_status=by_status,
        ),
        per_device=per_device,
        bgp_sessions=BgpSessionsAggOut(
            total=len(sessoes),
            active=sum(1 for s in sessoes if s.admin_status and not s.shutdown),
            shutdown=sum(1 for s in sessoes if s.shutdown),
        ),
        circuits=CircuitsAggOut(
            total=len(circuitos), active=sum(1 for c in circuitos if c.admin_status)
        ),
        vlans=AllocAggOut(
            reserved=sum(1 for v in vlans if v.status == "reservada"),
            freed=sum(1 for v in vlans if v.status == "liberada"),
        ),
        ip_prefixes=AllocAggOut(
            reserved=sum(1 for p in prefixos if p.status == "reservada"),
            freed=sum(1 for p in prefixos if p.status == "liberada"),
        ),
        recent_audit=[AuditEventOut.model_validate(e) for e in auditoria],
    )
