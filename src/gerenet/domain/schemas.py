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


class CircuitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    organization_id: int
    site_id: int
    access_device_id: int
    access_port: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9/\-]+$")
    edge_device_id: int
    backup_edge_device_id: int | None = None
    stack: Literal["ipv4", "ipv6", "dual"] = "dual"
    vlan_mode: Literal["unica", "separada"] = "unica"
    qinq: bool = False
    vrf: str | None = Field(default=None, max_length=64)
    mtu: int | None = Field(default=None, ge=576, le=9600)
    bandwidth: str | None = Field(default=None, max_length=32)
    bfd: bool = False
    p2p_v4_len: Literal[30, 31] = 31
    description: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class CircuitUpdate(BaseModel):
    organization_id: int | None = None
    site_id: int | None = None
    access_device_id: int | None = None
    access_port: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9/\-]+$")
    edge_device_id: int | None = None
    backup_edge_device_id: int | None = None
    stack: Literal["ipv4", "ipv6", "dual"] | None = None
    vlan_mode: Literal["unica", "separada"] | None = None
    qinq: bool | None = None
    vrf: str | None = Field(default=None, max_length=64)
    mtu: int | None = Field(default=None, ge=576, le=9600)
    bandwidth: str | None = Field(default=None, max_length=32)
    bfd: bool | None = None
    p2p_v4_len: Literal[30, 31] | None = None
    description: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class PrefixAuthorizationCreate(BaseModel):
    organization_id: int
    family: Literal["ipv4", "ipv6"]
    prefix: str = Field(min_length=1, max_length=64)
    notes: str | None = None


class BgpSessionCreate(BaseModel):
    circuit_id: int
    device_id: int
    afi: Literal["ipv4", "ipv6"]
    local_address: str = Field(min_length=1, max_length=64)
    remote_address: str = Field(min_length=1, max_length=64)
    source_address: str | None = Field(default=None, max_length=64)
    asn_local: int | None = None  # default device.asn no serviço (erro se o device não tem)
    asn_remote: int | None = None  # default organization.asn no serviço (erro se a org não tem)
    description: str | None = Field(default=None, max_length=255)
    import_profile_id: int | None = None
    export_profile_id: int | None = None
    maximum_prefix: int | None = None
    maximum_prefix_threshold: int | None = Field(default=None, ge=0, le=100)  # 0–100 (%)
    local_preference: int | None = None
    med: int | None = None
    prepend: int | None = Field(default=None, ge=0, le=10)  # 0–10
    keepalive: int | None = None
    holdtime: int | None = None
    bfd_enabled: bool = False
    graceful_restart: bool = False
    shutdown: bool = False
    allow_default_route: bool = False


class BgpSessionUpdate(BaseModel):
    # Not-null na prática (ruling 7): null explícito nesses campos é rejeitado
    # no serviço com "<campo> é obrigatório."; os demais aceitam null = limpar.
    circuit_id: int | None = None
    device_id: int | None = None
    afi: Literal["ipv4", "ipv6"] | None = None
    local_address: str | None = Field(default=None, min_length=1, max_length=64)
    remote_address: str | None = Field(default=None, min_length=1, max_length=64)
    asn_local: int | None = None
    asn_remote: int | None = None
    source_address: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    import_profile_id: int | None = None
    export_profile_id: int | None = None
    maximum_prefix: int | None = None
    maximum_prefix_threshold: int | None = Field(default=None, ge=0, le=100)
    local_preference: int | None = None
    med: int | None = None
    prepend: int | None = Field(default=None, ge=0, le=10)
    keepalive: int | None = None
    holdtime: int | None = None
    bfd_enabled: bool | None = None
    graceful_restart: bool | None = None
    shutdown: bool | None = None
    allow_default_route: bool | None = None
