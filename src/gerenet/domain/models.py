from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gerenet.db import Base

COMM_STATUS = ("unknown", "ok", "fail")
SNAPSHOT_STATUS = ("success", "partial", "error")
JOB_STATUS = ("queued", "running", "success", "partial", "error")
ORG_KIND = ("downstream", "parceiro")
CONTACT_KIND = ("tecnico", "noc", "admin")
CIRCUIT_STACK = ("ipv4", "ipv6", "dual")
VLAN_MODE = ("unica", "separada")
VLAN_KIND = ("vlan", "s_vlan")
FAMILY = ("ipv4", "ipv6")
ALLOC_STATUS = ("reservada", "liberada")
PREFIX_KIND = ("p2p",)
DIRECTION = ("import", "export")
PROFILE_KIND = ("produto",)
AUTH_ORIGIN = ("manual",)
USER_ROLES = ("visualizador", "operador", "aprovador", "executor", "administrador")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    management_address: Mapped[str] = mapped_column(String(255), nullable=False)
    ssh_port: Mapped[int | None] = mapped_column(Integer)  # None = porta padrão 22 na conexão
    vendor: Mapped[str] = mapped_column(String(32), default="huawei", nullable=False)
    model: Mapped[str | None] = mapped_column(String(64))
    family: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(64))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"))
    asn: Mapped[int | None] = mapped_column(BigInteger)  # ASN local do roteador (§5)
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
    site: Mapped["Site | None"] = relationship(back_populates="devices")


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
    error: Mapped[str | None] = mapped_column(Text)  # motivo da falha, quando status=error


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Site(Base):
    """POP/local. Escopo padrão das regras de unicidade do §14.1."""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    city: Mapped[str | None] = mapped_column(String(128))
    uf: Mapped[str | None] = mapped_column(String(2))
    p2p_ipv4_block: Mapped[str | None] = mapped_column(String(64))  # default: settings
    p2p_ipv6_base: Mapped[str | None] = mapped_column(String(64))  # default: settings
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    devices: Mapped[list["Device"]] = relationship(back_populates="site")


class Organization(Base):
    """Cliente (downstream) ou parceiro. ASN único mesmo desativado (§14.1)."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(Enum(*ORG_KIND, name="org_kind"), default="downstream", nullable=False)
    asn: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    irr_as_set: Mapped[str | None] = mapped_column(String(64))
    commercial_status: Mapped[str] = mapped_column(String(16), default="ativo", nullable=False)
    operational_status: Mapped[str] = mapped_column(String(16), default="ativo", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    contacts: Mapped[list["Contact"]] = relationship(back_populates="organization")


class Contact(Base):
    """Contato de uma organização (técnico/NOC/admin)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(
        Enum(*CONTACT_KIND, name="contact_kind"), default="tecnico", nullable=False
    )
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="contacts")


class Circuit(Base):
    """Circuito de acesso de um downstream no POP (acesso do switch até o edge NE8000)."""

    __tablename__ = "circuits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    access_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    access_port: Mapped[str] = mapped_column(String(64), nullable=False)
    edge_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    backup_edge_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    stack: Mapped[str] = mapped_column(Enum(*CIRCUIT_STACK, name="circuit_stack"), default="dual", nullable=False)
    vlan_mode: Mapped[str] = mapped_column(Enum(*VLAN_MODE, name="vlan_mode"), default="unica", nullable=False)
    qinq: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vrf: Mapped[str | None] = mapped_column(String(64))  # None = instância pública (§25.3)
    mtu: Mapped[int | None] = mapped_column(Integer)
    bandwidth: Mapped[str | None] = mapped_column(String(32))
    bfd: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    p2p_v4_len: Mapped[int] = mapped_column(Integer, default=31, nullable=False)  # /31 padrão, /30 opção
    description: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text())
    edge_trunk: Mapped[str | None] = mapped_column(String(64))  # trunk do edge com as subinterfaces (§25.18)
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship()


class Vlan(Base):
    """VLAN reservada num site para um circuito (kind vlan ou s_vlan no QinQ)."""

    __tablename__ = "vlans"

    __table_args__ = (
        # S-VLAN e VLAN partilham o mesmo espaço de VID no switch (spec)
        UniqueConstraint("site_id", "vid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    vid: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Enum(*VLAN_KIND, name="vlan_kind"), default="vlan", nullable=False)
    family: Mapped[str | None] = mapped_column(Enum(*FAMILY, name="family"))
    circuit_id: Mapped[int | None] = mapped_column(ForeignKey("circuits.id"))
    status: Mapped[str] = mapped_column(
        Enum(*ALLOC_STATUS, name="alloc_status"), default="reservada", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IpPrefix(Base):
    """Enlace p2p reservado num site (v4 /31|/30 e v6 /126 derivado §25.8)."""

    __tablename__ = "ip_prefixes"

    __table_args__ = (
        # Ruling 1: rede de segurança contra duplicidade exata no site
        UniqueConstraint("site_id", "network"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network: Mapped[str] = mapped_column(String(64), nullable=False)  # CIDR canônico alinhado
    kind: Mapped[str] = mapped_column(Enum(*PREFIX_KIND, name="prefix_kind"), default="p2p", nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    circuit_id: Mapped[int | None] = mapped_column(ForeignKey("circuits.id"))
    status: Mapped[str] = mapped_column(
        Enum(*ALLOC_STATUS, name="alloc_status"), default="reservada", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PolicyProfile(Base):
    """Produto de roteamento reutilizável (§6.5/§25.5) — catálogo read-only no ciclo A.

    direction import nasce no ciclo B junto da renderização; os seeds deste
    plano são os 6 produtos de exportação do §25.5.
    """

    __tablename__ = "bgp_policy_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # slug EN
    label: Mapped[str] = mapped_column(String(64), nullable=False)  # PT-BR
    direction: Mapped[str] = mapped_column(Enum(*DIRECTION, name="direction"), nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum(*PROFILE_KIND, name="profile_kind"), default="produto", nullable=False
    )
    prefixes: Mapped[list | None] = mapped_column(JSON)  # CIDRs de cdn/personalizado
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Community(Base):
    """Community BGP reutilizável (§25.6) — catálogo read-only no ciclo A.

    O valor concreto (ex.: NO_EXPORT vs ASN:tag) é definido na renderização do
    ciclo B conforme o template e o ASN local; aqui só o nome lógico.
    """

    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BgpSession(Base):
    """Sessão BGP por família (§6.3) — SoT da intenção; sem renderização (ciclo B)."""

    __tablename__ = "bgp_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_id: Mapped[int] = mapped_column(ForeignKey("circuits.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    afi: Mapped[str] = mapped_column(Enum(*FAMILY, name="family"), nullable=False)
    local_address: Mapped[str] = mapped_column(String(64), nullable=False)
    remote_address: Mapped[str] = mapped_column(String(64), nullable=False)
    source_address: Mapped[str | None] = mapped_column(String(64))
    asn_local: Mapped[int | None] = mapped_column(BigInteger)  # default device.asn (§4); sempre resolvido no serviço
    asn_remote: Mapped[int] = mapped_column(BigInteger, nullable=False)  # default organization.asn (§4)
    description: Mapped[str | None] = mapped_column(String(255))
    import_profile_id: Mapped[int | None] = mapped_column(ForeignKey("bgp_policy_profiles.id"))
    export_profile_id: Mapped[int | None] = mapped_column(ForeignKey("bgp_policy_profiles.id"))
    maximum_prefix: Mapped[int | None] = mapped_column(Integer)
    maximum_prefix_threshold: Mapped[int | None] = mapped_column(Integer)  # 0-100 (%)
    local_preference: Mapped[int | None] = mapped_column(Integer)
    med: Mapped[int | None] = mapped_column(Integer)
    prepend: Mapped[int | None] = mapped_column(Integer)  # 0-10
    keepalive: Mapped[int | None] = mapped_column(Integer)
    holdtime: Mapped[int | None] = mapped_column(Integer)
    bfd_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    graceful_restart: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shutdown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_default_route: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password_ref: Mapped[str | None] = mapped_column(String(255))  # path Vault; valor nunca no banco

    @property
    def has_password(self) -> bool:
        """Senha definida? (valor só no Vault — password_ref guarda o path)."""
        return self.password_ref is not None

    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BgpSessionCommunity(Base):
    """Associação N:N sessão ↔ community (UNIQUE por par). Linha deletável — a
    trilha fica na auditoria (ruling 13); sem soft-delete."""

    __tablename__ = "bgp_session_communities"

    __table_args__ = (
        UniqueConstraint("session_id", "community_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("bgp_sessions.id"), nullable=False)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BgpPrefixAuthorization(Base):
    """Prefixo autorizado de um downstream (origem manual; IRR/RPKI = F5)."""

    __tablename__ = "bgp_prefix_authorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    family: Mapped[str] = mapped_column(Enum(*FAMILY, name="family"), nullable=False)
    prefix: Mapped[str] = mapped_column(String(64), nullable=False)  # CIDR alinhado
    origin: Mapped[str] = mapped_column(
        Enum(*AUTH_ORIGIN, name="auth_origin"), default="manual", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text())
    admin_status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    """Usuário gerenet (login local, §17). Senha nunca fica fora de password_hash."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum(*USER_ROLES, name="user_role"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserSession(Base):
    """Sessão de login web — token opaco no cookie; banco guarda só o hash."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
