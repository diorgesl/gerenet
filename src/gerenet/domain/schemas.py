from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    management_address: str
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    vendor: str = "huawei"
    model: str | None = None
    family: str | None = None
    role: str | None = None
    site: str | None = None
    credential_group_id: int | None = None
    tags: list[str] = Field(default_factory=list)


class DeviceUpdate(BaseModel):
    admin_status: bool | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    model: str | None = None
    family: str | None = None
    role: str | None = None
    site: str | None = None
    tags: list[str] | None = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    management_address: str
    ssh_port: int | None
    vendor: str
    model: str | None
    family: str | None
    role: str | None
    site: str | None
    vrp_version: str | None
    comm_status: str
    admin_status: bool
    last_collected_at: datetime | None
    tags: list[str]


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    resources: dict
    errors: dict
    duration_ms: int
