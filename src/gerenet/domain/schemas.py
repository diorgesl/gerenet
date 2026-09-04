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
    admin_status: bool | None = None


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
    admin_status: bool | None = None


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
    admin_status: bool | None = None


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
    edge_trunk: str | None = None


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
    edge_trunk: str | None = None
    admin_status: bool | None = None


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
    admin_status: bool | None = None


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str | None
    uf: str | None
    p2p_ipv4_block: str | None
    p2p_ipv6_base: str | None
    admin_status: bool


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    legal_name: str | None
    kind: str
    asn: int | None
    irr_as_set: str | None
    notes: str | None
    admin_status: bool


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    email: str | None
    phone: str | None
    kind: str
    admin_status: bool


class CircuitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    organization_id: int
    site_id: int
    access_device_id: int
    access_port: str
    edge_device_id: int
    backup_edge_device_id: int | None
    stack: str
    vlan_mode: str
    qinq: bool
    vrf: str | None
    mtu: int | None
    bandwidth: str | None
    bfd: bool
    p2p_v4_len: int
    description: str | None
    notes: str | None
    edge_trunk: str | None
    admin_status: bool


class CircuitDetailOut(CircuitOut):
    """Circuito reservado: pontas derivadas dos enlaces p2p (ruling 4).

    v4 sem máscara (pontas_v4); v6 com '/126' (pontas_v6). Linhas internas
    de derivação (stack=ipv6) não são expostas.
    """

    ipv4_local: str | None = None
    ipv4_remote: str | None = None
    ipv6_local: str | None = None
    ipv6_remote: str | None = None


class BgpSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    circuit_id: int
    device_id: int
    afi: str
    local_address: str
    remote_address: str
    source_address: str | None
    asn_local: int | None
    asn_remote: int | None
    description: str | None
    import_profile_id: int | None
    export_profile_id: int | None
    maximum_prefix: int | None
    maximum_prefix_threshold: int | None
    local_preference: int | None
    med: int | None
    prepend: int | None
    keepalive: int | None
    holdtime: int | None
    bfd_enabled: bool
    graceful_restart: bool
    shutdown: bool
    allow_default_route: bool
    has_password: bool  # property do modelo — o valor nunca trafega aqui
    admin_status: bool


class PrefixAuthorizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    family: str
    prefix: str
    origin: str
    notes: str | None
    admin_status: bool


class PolicyProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    label: str
    direction: str
    kind: str
    prefixes: list | None
    notes: str | None
    admin_status: bool


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    actor: str
    details: dict
    created_at: datetime


class PrefixAuthorizationDisable(BaseModel):
    """PATCH de autorização aceita só {"admin_status": false} (ruling 2)."""

    model_config = ConfigDict(extra="forbid")

    admin_status: Literal[False]


class BgpSessionPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class BgpSessionCommunityIn(BaseModel):
    community_id: int


class CommunityOut(BaseModel):
    id: int
    name: str
    notes: str | None = None


class BlocoOut(BaseModel):
    tipo: str
    objeto: str
    objeto_id: int
    comandos: list[str]


class DesiredConfigOut(BaseModel):
    device_id: int
    gerado_em: datetime
    texto: str
    blocos: list[BlocoOut]


class ReconcileItemOut(BaseModel):
    tipo: str
    severidade: str
    esperado: str
    encontrado: str
    acao: str


class ReconcileOut(BaseModel):
    device_id: int
    snapshot_id: int | None
    aviso: str | None
    gerado_em: datetime
    items: list[ReconcileItemOut]
