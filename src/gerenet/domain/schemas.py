from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    management_address: str
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    vendor: str = "huawei"
    model: str | None = None
    family: str | None = None
    role: str | None = None
    site_id: int | None = None
    asn: int | None = Field(default=None, ge=1, le=4294967295)  # reservados barrados no serviço
    credential_group_id: int | None = None
    tags: list[str] = Field(default_factory=list)


class DeviceUpdate(BaseModel):
    admin_status: bool | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    model: str | None = None
    family: str | None = None
    role: str | None = None
    site_id: int | None = None
    asn: int | None = Field(default=None, ge=1, le=4294967295)
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
    site_id: int | None
    asn: int | None
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


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    city: str | None = Field(default=None, max_length=128)
    uf: str | None = Field(default=None, min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
    p2p_ipv4_block: str | None = Field(default=None, max_length=64)
    p2p_ipv6_base: str | None = Field(default=None, max_length=64)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    city: str | None = Field(default=None, max_length=128)
    uf: str | None = Field(default=None, min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
    p2p_ipv4_block: str | None = Field(default=None, max_length=64)
    p2p_ipv6_base: str | None = Field(default=None, max_length=64)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    legal_name: str | None = Field(default=None, max_length=255)
    kind: Literal["downstream", "parceiro"] = "downstream"
    # Sem limites pydantic: a validação de ASN é do serviço (asn_valido), que
    # levanta ValidationError do gerenet também para valores fora da faixa.
    asn: int | None = None
    irr_as_set: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    legal_name: str | None = Field(default=None, max_length=255)
    kind: Literal["downstream", "parceiro"] | None = None
    asn: int | None = None
    irr_as_set: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class ContactCreate(BaseModel):
    organization_id: int
    name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    kind: Literal["tecnico", "noc", "admin"] = "tecnico"


class ContactUpdate(BaseModel):
    organization_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    kind: Literal["tecnico", "noc", "admin"] | None = None
