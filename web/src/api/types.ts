// Espelhos dos *Out do Pydantic (contrato da API /api/v1) — atualizar se o backend mudar.
export interface UserOut {
  id: number;
  username: string;
  role: "visualizador" | "operador" | "aprovador" | "executor" | "administrador";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}
export interface DeviceOut {
  id: number;
  name: string;
  management_address: string;
  ssh_port: number | null;
  vendor: string;
  model: string | null;
  family: string | null;
  role: string | null;
  site_id: number | null;
  asn: number | null;
  vrp_version: string | null;
  comm_status: string;
  admin_status: boolean;
  last_collected_at: string | null;
  tags: string[];
}
export interface SiteOut {
  id: number;
  name: string;
  city: string | null;
  uf: string | null;
  p2p_ipv4_block: string | null;
  p2p_ipv6_base: string | null;
  admin_status: boolean;
}
export interface OrganizationOut {
  id: number;
  name: string;
  legal_name: string | null;
  kind: "downstream" | "parceiro";
  asn: number | null;
  irr_as_set: string | null;
  notes: string | null;
  admin_status: boolean;
}
export interface ContactOut {
  id: number;
  organization_id: number;
  name: string;
  email: string | null;
  phone: string | null;
  kind: "tecnico" | "noc" | "admin";
  admin_status: boolean;
}
export interface CircuitOut {
  id: number;
  code: string;
  organization_id: number;
  site_id: number;
  access_device_id: number;
  access_port: string;
  edge_device_id: number;
  backup_edge_device_id: number | null;
  stack: "ipv4" | "ipv6" | "dual";
  vlan_mode: "unica" | "separada";
  qinq: boolean;
  vrf: string | null;
  mtu: number | null;
  bandwidth: string | null;
  bfd: boolean;
  p2p_v4_len: 30 | 31;
  description: string | null;
  notes: string | null;
  edge_trunk: string | null;
  admin_status: boolean;
}
export interface CircuitDetailOut extends CircuitOut {
  ipv4_local: string | null;
  ipv4_remote: string | null;
  ipv6_local: string | null;
  ipv6_remote: string | null;
}
export interface BgpSessionOut {
  id: number;
  circuit_id: number;
  device_id: number;
  afi: "ipv4" | "ipv6";
  local_address: string;
  remote_address: string;
  source_address: string | null;
  asn_local: number | null;
  asn_remote: number | null;
  description: string | null;
  import_profile_id: number | null;
  export_profile_id: number | null;
  maximum_prefix: number | null;
  maximum_prefix_threshold: number | null;
  local_preference: number | null;
  med: number | null;
  prepend: number | null;
  keepalive: number | null;
  holdtime: number | null;
  bfd_enabled: boolean;
  graceful_restart: boolean;
  shutdown: boolean;
  allow_default_route: boolean;
  has_password: boolean;
  admin_status: boolean;
}
export interface PrefixAuthorizationOut {
  id: number;
  organization_id: number;
  family: "ipv4" | "ipv6";
  prefix: string;
  origin: string;
  notes: string | null;
  admin_status: boolean;
}
export interface PolicyProfileOut {
  id: number;
  name: string;
  label: string;
  direction: "import" | "export";
  kind: string;
  prefixes: string[] | null;
  notes: string | null;
  admin_status: boolean;
}
export interface CommunityOut {
  id: number;
  name: string;
  notes: string | null;
  admin_status: boolean;
}

export type CommunityUpdateIn = { name?: string; notes?: string | null; admin_status?: boolean };

export type PolicyProfileUpdateIn = {
  name?: string;
  label?: string;
  direction?: "import" | "export";
  kind?: string;
  prefixes?: string[] | null;
  notes?: string | null;
  admin_status?: boolean;
};
export interface AuditEventOut {
  id: number;
  type: string;
  actor: string;
  details: Record<string, unknown>;
  created_at: string;
}
export interface SnapshotOut {
  id: number;
  device_id: number;
  started_at: string;
  finished_at: string | null;
  status: "success" | "partial" | "error";
  resources: Record<string, unknown>;
  errors: Record<string, unknown>;
  duration_ms: number;
}
export interface BlocoOut {
  tipo: string;
  objeto: string;
  objeto_id: number;
  comandos: string[];
}
export interface DesiredConfigOut {
  device_id: number;
  gerado_em: string;
  texto: string;
  blocos: BlocoOut[];
}
export interface ReconcileItemOut {
  tipo: string;
  severidade: string;
  esperado: string;
  encontrado: string;
  acao: string;
}
export interface ReconcileOut {
  device_id: number;
  snapshot_id: number | null;
  aviso: string | null;
  gerado_em: string;
  items: ReconcileItemOut[];
}
export interface PerDeviceOut {
  device_id: number;
  name: string;
  site_id: number | null;
  site_name: string | null;
  comm_status: string;
  last_collected_at: string | null;
  snapshot_age_seconds: number | null;
  latest_snapshot: { id: number; status: string; started_at: string; error: string | null } | null;
  active_job: { id: number; status: string } | null;
}
export interface DashboardOut {
  devices: {
    total: number;
    active: number;
    with_snapshot: number;
    by_comm_status: Record<"unknown" | "ok" | "fail", number>;
  };
  per_device: PerDeviceOut[];
  bgp_sessions: { total: number; active: number; shutdown: number };
  circuits: { total: number; active: number };
  vlans: { reserved: number; freed: number };
  ip_prefixes: { reserved: number; freed: number };
  recent_audit: AuditEventOut[];
}
export interface JobRunOut {
  id: number;
  device_id: number | null;
  origin: string;
  actor: string;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  snapshot_id: number | null;
  error: string | null;
}
export interface CollectResposta {
  queued: boolean;
  message: string;
  job_id: string;
}
