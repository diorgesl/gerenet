from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gerenet.db import Base

COMM_STATUS = ("unknown", "ok", "fail")
SNAPSHOT_STATUS = ("success", "partial", "error")
JOB_STATUS = ("queued", "running", "success", "partial", "error")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    management_address: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor: Mapped[str] = mapped_column(String(32), default="huawei", nullable=False)
    model: Mapped[str | None] = mapped_column(String(64))
    family: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(64))
    site: Mapped[str | None] = mapped_column(String(64))
    vrp_version: Mapped[str | None] = mapped_column(String(64))
    uptime: Mapped[str | None] = mapped_column(String(128))
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    comm_status: Mapped[str] = mapped_column(
        Enum(*COMM_STATUS, name="comm_status"), default="unknown", nullable=False
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    host_key_fingerprint: Mapped[str | None] = mapped_column(String(128))
    credential_group_id: Mapped[int | None] = mapped_column(ForeignKey("credential_groups.id"))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    credential_group: Mapped["CredentialGroup | None"] = relationship()
    snapshots: Mapped[list["DeviceSnapshot"]] = relationship(back_populates="device")


class CredentialGroup(Base):
    __tablename__ = "credential_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="tacacs_password", nullable=False)
    vault_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DeviceSnapshot(Base):
    __tablename__ = "device_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Enum(*SNAPSHOT_STATUS, name="snapshot_status"), default="error", nullable=False
    )
    resources: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_files: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    device: Mapped[Device] = relationship(back_populates="snapshots")


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    origin: Mapped[str] = mapped_column(String(16), nullable=False)  # api | cli | rq
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="collect", nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*JOB_STATUS, name="job_status"), default="queued", nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("device_snapshots.id"))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
