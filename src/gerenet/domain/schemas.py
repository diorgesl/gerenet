from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class CredentialGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    vault_path: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="tacacs_password", max_length=32)


class CredentialGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    vault_path: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = Field(default=None, max_length=32)
    admin_status: bool | None = None


class CredentialGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    vault_path: str
    admin_status: bool


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
    kind: Literal["downstream", "parceiro", "operadora"] = "downstream"
    # Sem limites pydantic: a validação de ASN é do serviço (asn_valido), que
    # levanta ValidationError do gerenet também para valores fora da faixa.
    asn: int | None = None
    irr_as_set: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    legal_name: str | None = Field(default=None, max_length=255)
    kind: Literal["downstream", "parceiro", "operadora"] | None = None
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
    edge_trunk: str | None = Field(default=None, max_length=64)


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
    edge_trunk: str | None = Field(default=None, max_length=64)
    admin_status: bool | None = None


class PrefixAuthorizationCreate(BaseModel):
    organization_id: int
    family: Literal["ipv4", "ipv6"]
    prefix: str = Field(min_length=1, max_length=64)
    origin: Literal["manual", "irr", "rpki"] = "manual"
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
    organization_kind: str | None = None  # derivado da organização do circuito (router/fase 5)


class CircuitDetailOut(CircuitOut):
    """Circuito reservado: pontas derivadas dos enlaces p2p (ruling 4).

    v4 sem máscara (pontas_v4); v6 com '/126' (pontas_v6). Linhas internas
    de derivação (stack=ipv6) não são expostas.
    """

    ipv4_local: str | None = None
    ipv4_remote: str | None = None
    ipv6_local: str | None = None
    ipv6_remote: str | None = None
    upstream_id: int | None = None  # vínculo com upstream (fase 5); no máx. 1 por circuito (BR-1 §7)


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
    organization_kind: str | None = None  # derivado da organização do circuito da sessão (router/fase 5)


class PrefixAuthorizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    family: str
    prefix: str
    origin: str
    validacao: str | None  # ok|diverge|desconhecida|nao_verificada (consultiva, fase 5)
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


class DevicesAggOut(BaseModel):
    total: int
    active: int
    with_snapshot: int
    by_comm_status: dict[str, int]


class SnapshotResumoOut(BaseModel):
    id: int
    status: str
    started_at: datetime
    error: str | None = None  # primeiro motivo de falha, quando o último snapshot não está ok


class JobResumoOut(BaseModel):
    id: int
    status: str


class PerDeviceOut(BaseModel):
    device_id: int
    name: str
    site_id: int | None
    site_name: str | None
    comm_status: str
    last_collected_at: datetime | None
    snapshot_age_seconds: float | None
    latest_snapshot: SnapshotResumoOut | None
    active_job: JobResumoOut | None


class BgpSessionsAggOut(BaseModel):
    total: int
    active: int
    shutdown: int


class CircuitsAggOut(BaseModel):
    total: int
    active: int


class AllocAggOut(BaseModel):
    reserved: int
    freed: int


class DashboardOut(BaseModel):
    devices: DevicesAggOut
    per_device: list[PerDeviceOut]
    bgp_sessions: BgpSessionsAggOut
    circuits: CircuitsAggOut
    vlans: AllocAggOut
    ip_prefixes: AllocAggOut
    recent_audit: list[AuditEventOut]


class PrefixAuthorizationDisable(BaseModel):
    """PATCH de autorização aceita só {"admin_status": false} (ruling 2)."""

    model_config = ConfigDict(extra="forbid")

    admin_status: Literal[False]


class BgpSessionPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class BgpSessionCommunityIn(BaseModel):
    community_id: int


class CommunityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    tipo: str = "padrao"  # validado no serviço contra models.COMMUNITY_TIPO
    notes: str | None = None


class CommunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tipo: str
    notes: str | None = None
    admin_status: bool


class CommunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    tipo: str | None = None  # validado no serviço contra models.COMMUNITY_TIPO
    notes: str | None = None
    admin_status: bool | None = None  # PATCH puro {"admin_status": false} roteia ao disable (Ruling 1)


class PolicyProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, min_length=1, max_length=64)
    direction: str | None = None  # validado no serviço contra models.DIRECTION
    kind: str | None = None  # validado no serviço contra models.PROFILE_KIND
    prefixes: list[str] | None = None
    notes: str | None = None
    admin_status: bool | None = None


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


class UserLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(max_length=128)  # mesmo limite do UserLoginIn; mínimo (8) validado no serviço
    role: str  # validação em serviço (padrão do catálogo; 422 só no formato)


class UserUpdateIn(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    role: str | None = None
    is_active: bool | None = None


class UserPasswordIn(BaseModel):
    password: str = Field(max_length=128)  # mesmo limite do UserLoginIn; mínimo (8) validado no serviço


class JobRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int | None
    origin: str
    actor: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int
    snapshot_id: int | None
    error: str | None = None  # motivo da falha (falha pré-snapshot: grupo, lock, segredo…)


class ChangeRequestCreate(BaseModel):
    escopo: Literal["circuito", "l2vc", "vsi", "upstream"] = "circuito"
    circuit_id: int | None = None
    l2vc_id: int | None = None
    upstream_id: int | None = None  # escopo upstream (fase 5)
    acao: Literal["provision", "remove"] = "provision"
    criticidade: Literal["baixa", "media", "alta"] = "media"
    motivo: str = Field(min_length=1, max_length=2000)
    ticket: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _valida_escopo(self) -> "ChangeRequestCreate":
        if self.escopo == "circuito" and self.circuit_id is None:
            raise ValueError("circuit_id é obrigatório para escopo 'circuito'.")
        if self.escopo == "l2vc" and self.l2vc_id is None:
            raise ValueError("l2vc_id é obrigatório para escopo 'l2vc'.")
        if self.escopo == "upstream" and self.upstream_id is None:
            raise ValueError("upstream_id é obrigatório para escopo 'upstream'.")
        if self.escopo == "vsi":
            raise ValueError("Escopo 'vsi' não está disponível neste ciclo.")
        return self


class ApprovalIn(BaseModel):
    decisao: Literal["aprovar", "rejeitar"]
    comentario: str | None = Field(default=None, max_length=1000)


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    decisao: str
    comentario: str | None
    created_at: datetime


class ChangeStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    status: str
    plano_json: list
    aviso: str | None
    baseline_snapshot_id: int | None
    backup_snapshot_id: int | None
    post_check_json: dict | None
    erro: str | None
    finished_at: datetime | None


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    circuit_id: int | None
    escopo: str
    l2vc_id: int | None = None
    l2vc_name: str | None = None
    upstream_id: int | None = None
    upstream_name: str | None = None  # espelho do modelo (propriedade upstream_name)
    acao: str
    criticidade: str
    motivo: str
    ticket: str | None
    solicitante_id: int | None
    status: str
    rollback_de: int | None
    created_at: datetime
    steps: list[ChangeStepOut] = []
    approvals: list[ApprovalOut] = []


class MplsMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_id: int
    device_name: str | None = None
    loopback_address: str
    role: str


class MplsDomainCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)


class MplsDomainUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    admin_status: bool | None = None


class MplsMemberIn(BaseModel):
    device_id: int
    loopback_address: str = Field(max_length=64)  # conteúdo validado no serviço (vazio → ValidationError)
    role: Literal["pe", "core"] = "pe"


class MplsDomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    admin_status: bool
    created_at: datetime
    updated_at: datetime
    members: list[MplsMemberOut] = Field(default_factory=list)


class L2vcEndpointIn(BaseModel):
    device_id: int
    interface: str = Field(min_length=1, max_length=64)
    encapsulation: Literal["dot1q", "qinq"] = "dot1q"  # ethernet_raw: fora do ciclo (§10)
    vid: int | None = Field(default=None, ge=2, le=4094)  # None ⇒ auto-reserva no device
    inner_vlan: int | None = Field(default=None, ge=1, le=4094)  # QinQ: obrigatório
    mtu: int | None = Field(default=None, ge=576, le=9216)  # None ⇒ herda service.mtu


class L2vcCreate(BaseModel):
    domain_id: int
    name: str = Field(min_length=1, max_length=64)
    vc_id: int | None = Field(default=None, ge=1, le=4294967295)  # None ⇒ proximo_vc_id
    organization_id: int | None = None
    mtu: int = Field(default=1500, ge=576, le=9216)
    control_word: bool = False
    flow_label: bool = False
    redundancy: str | None = None
    description: str | None = Field(default=None, max_length=255)
    endpoints: list[L2vcEndpointIn] = Field(min_length=2, max_length=2)


class ServiceEndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    device_id: int
    device_name: str | None = None
    interface: str
    encapsulation: str
    vlan_id: int | None = None
    vid: int | None = None
    inner_vlan: int | None = None
    mtu: int | None = None
    operational_status: str


class L2vcOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    domain_id: int
    vc_id: int
    name: str
    organization_id: int | None
    mtu: int
    control_word: bool
    flow_label: bool
    redundancy: str | None
    description: str | None
    admin_status: bool
    operational_status: str
    last_collected_at: datetime | None
    created_at: datetime
    endpoints: list[ServiceEndpointOut] = Field(default_factory=list)
    domain_name: str | None = None


class VsiMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_id: int
    device_name: str | None = None


class VsiCreate(BaseModel):
    domain_id: int
    name: str = Field(min_length=1, max_length=64)
    vsi_id: int | None = Field(default=None, ge=1, le=4294967295)  # None ⇒ proximo_vsi_id
    mtu: int = Field(default=1500, ge=576, le=9216)
    split_horizon: bool = True
    mac_learning: bool = True
    mac_limit: int | None = Field(default=None, ge=0)
    members: list[int] = Field(default_factory=list, min_length=1)


class VsiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    domain_id: int
    vsi_id: int
    name: str
    vrp_name: str
    signaling: str
    mtu: int
    split_horizon: bool
    mac_learning: bool
    mac_limit: int | None
    admin_status: bool
    operational_status: str
    last_collected_at: datetime | None
    created_at: datetime
    members: list[VsiMemberOut] = Field(default_factory=list)
    domain_name: str | None = None


# ---- Fase 5 (upstreams, §7): conectividade própria — trânsito/IX/PNI. ----

def _valida_margem(v: int | None) -> int | None:
    """Margem do maximum-prefix entre 0 e 100 — mensagem PT-BR (mode="before").

    Aceita string numérica (JSON via API chega cru ao validator; `0 <= "101"`
    era TypeError e pydantic v2 não converte TypeError em ValidationError —
    virava 500 em vez de 422 — revisão final M-1). `None` atravessa (campo
    opcional do Update).
    """
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = int(v)
        except ValueError:
            raise ValueError(
                "margem (max_prefix_margin_pct) deve ser um inteiro entre 0 e 100."
            ) from None
    if not 0 <= v <= 100:
        raise ValueError("margem (max_prefix_margin_pct) deve estar entre 0 e 100.")
    return v


class UpstreamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    tipo: Literal["transito", "ix", "pni", "contingencia"]
    capacity: str | None = Field(default=None, max_length=32)
    priority: int | None = None  # 1 = maior prioridade
    cost: str | None = Field(default=None, max_length=32)
    organization_id: int
    expected_prefixes_v4: int | None = None
    expected_prefixes_v6: int | None = None
    max_prefix_margin_pct: int = Field(default=20, ge=0, le=100)
    rpki_enabled: bool = True
    entrada_local_preference: int | None = None
    contingencia_local_preference: int | None = None
    contingencia_prepend: int | None = Field(default=None, ge=0, le=10)
    contingencia_notes: str | None = None

    @field_validator("max_prefix_margin_pct", mode="before")
    @classmethod
    def _margem(cls, v: int | None) -> int | None:
        # mode="before": o erro de margem em PT-BR precisa anteceder o do Field(ge/le).
        return _valida_margem(v)


class UpstreamUpdate(BaseModel):
    name: str | None = None
    tipo: Literal["transito", "ix", "pni", "contingencia"] | None = None
    capacity: str | None = Field(default=None, max_length=32)
    priority: int | None = None
    cost: str | None = Field(default=None, max_length=32)
    organization_id: int | None = None
    expected_prefixes_v4: int | None = None
    expected_prefixes_v6: int | None = None
    # M-2 (revisão final): o Create tinha os limites; sem eles no PATCH/CLI
    # valores absurdos iam direto ao banco (design §9: margem 0-100, prepend 0-10).
    max_prefix_margin_pct: int | None = Field(default=None, ge=0, le=100)
    rpki_enabled: bool | None = None
    entrada_local_preference: int | None = None
    contingencia_local_preference: int | None = None
    contingencia_prepend: int | None = Field(default=None, ge=0, le=10)
    contingencia_notes: str | None = None
    admin_status: bool | None = None

    @field_validator("max_prefix_margin_pct", mode="before")
    @classmethod
    def _margem(cls, v: int | None) -> int | None:
        return _valida_margem(v)


class UpstreamCommunityCreate(BaseModel):
    purpose: Literal["blackhole", "prepend", "lp", "info"]
    value: str = Field(min_length=2, max_length=64)
    direcao: Literal["import", "export", "ambos"] = "ambos"
    regiao: str | None = Field(default=None, max_length=64)
    bloquear: bool = False
    notes: str | None = None


class UpstreamCircuitIn(BaseModel):
    circuit_id: int
    papel: Literal["principal", "contingencia"] = "principal"
    ordem: int = 1


class UpstreamCircuitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    upstream_id: int
    circuit_id: int
    papel: str
    ordem: int


class UpstreamCommunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    upstream_id: int
    purpose: str
    value: str
    direcao: str
    regiao: str | None
    bloquear: bool
    notes: str | None
    admin_status: bool


class UpstreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tipo: str
    capacity: str | None
    priority: int | None
    cost: str | None
    organization_id: int
    expected_prefixes_v4: int | None
    expected_prefixes_v6: int | None
    max_prefix_margin_pct: int
    rpki_enabled: bool
    entrada_local_preference: int | None
    contingencia_local_preference: int | None
    contingencia_prepend: int | None
    contingencia_notes: str | None
    admin_status: bool
    organization_kind: str | None = None  # kind da organização (operadora) — preenchido no router
    organization_name: str | None = None  # nome da organização — preenchido no router
    created_at: datetime
    updated_at: datetime


class UpstreamDetailOut(UpstreamOut):
    """Detalhe do upstream: circuitos vinculados, sessões dos circuitos e communities (§7)."""

    circuitos: list[UpstreamCircuitOut] = Field(default_factory=list)
    sessoes: list[BgpSessionOut] = Field(default_factory=list)
    comunidades: list[UpstreamCommunityOut] = Field(default_factory=list)
