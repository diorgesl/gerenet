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
  credential_group_id: number | null;
}
export interface CredentialGroupOut {
  id: number;
  name: string;
  kind: string;
  vault_path: string;
  admin_status: boolean;
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
  kind: "downstream" | "parceiro" | "operadora";
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
  organization_kind: string | null; // kind da organização do circuito — preenchido no router (fase 5)
}
export interface CircuitDetailOut extends CircuitOut {
  ipv4_local: string | null;
  ipv4_remote: string | null;
  ipv6_local: string | null;
  ipv6_remote: string | null;
  upstream_id: number | null; // vínculo com upstream (fase 5): no máx. 1 por circuito (BR-1)
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
  organization_kind: string | null; // kind da organização do circuito — preenchido no router (fase 5)
}
export interface PrefixAuthorizationOut {
  id: number;
  organization_id: number;
  family: "ipv4" | "ipv6";
  prefix: string;
  origin: string;
  validacao: string | null; // ok|diverge|desconhecida|nao_verificada (consultiva, fase 5)
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
  tipo: string; // categoria §7/§25.6 — espelha models.COMMUNITY_TIPO (models.py:53)
  notes: string | null;
  admin_status: boolean;
}

export type CommunityCreateIn = { name: string; tipo?: string; notes?: string | null };
export type CommunityUpdateIn = { name?: string; tipo?: string; notes?: string | null; admin_status?: boolean };

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
export interface WikiIndiceItem {
  slug: string;
  titulo: string;
  secao: string;
  order: number;
  em_breve: boolean;
}
export interface WikiPagina {
  slug: string;
  titulo: string;
  em_breve: boolean;
  html: string;
}

// Ciclo D — change requests (contrato T4/T5; "acao" presente nos blocos de plano T2/T3).
export interface ChangeBlocoOut extends BlocoOut {
  acao: "create" | "delete";
}
export interface ApprovalOut {
  id: number;
  user_id: number;
  decisao: string;
  comentario: string | null;
  created_at: string;
}
export interface PostCheckOut {
  snapshot_id: number | null;
  items: ReconcileItemOut[]; // mesmo shape do ReconcileOut (T6 grava asdict(item))
}
export interface ChangeStepOut {
  id: number;
  device_id: number;
  status: string;
  plano_json: ChangeBlocoOut[];
  aviso: string | null;
  baseline_snapshot_id: number | null;
  backup_snapshot_id: number | null;
  post_check_json: PostCheckOut | null;
  erro: string | null;
  finished_at: string | null;
}
export interface ChangeRequestOut {
  id: number;
  circuit_id: number | null;
  escopo: "circuito" | "l2vc" | "vsi" | "upstream";
  l2vc_id: number | null;
  l2vc_name: string | null;
  upstream_id: number | null;
  upstream_name: string | null;
  acao: "provision" | "remove";
  criticidade: "baixa" | "media" | "alta";
  motivo: string;
  ticket: string | null;
  solicitante_id: number | null;
  status: string;
  rollback_de: number | null;
  created_at: string;
  steps: ChangeStepOut[];
  approvals: ApprovalOut[];
}
export type ChangeRequestCreateIn = {
  escopo?: "circuito" | "l2vc" | "vsi" | "upstream";
  circuit_id?: number | null;
  l2vc_id?: number | null;
  upstream_id?: number | null;
  acao: "provision" | "remove";
  criticidade: "baixa" | "media" | "alta";
  motivo: string;
  ticket?: string | null;
};

// Ciclo F4 — MPLS (spec §9): domínios, L2VC e VSI (espelha schemas.py do backend).
export interface MplsMemberOut {
  device_id: number;
  device_name: string | null;
  loopback_address: string;
  role: "pe" | "core";
}
export interface MplsDomainOut {
  id: number;
  name: string;
  description: string | null;
  admin_status: boolean;
  created_at: string;
  updated_at: string;
  members: MplsMemberOut[];
}
export interface MplsDomainCreateIn {
  name: string;
  description?: string | null;
}
export interface MplsDomainUpdateIn {
  name?: string;
  description?: string | null;
  admin_status?: boolean;
}
export interface MplsMemberIn {
  device_id: number;
  loopback_address: string;
  role?: "pe" | "core";
}
export interface ServiceEndpointOut {
  id: number;
  kind: "l2vc" | "vsi";
  device_id: number;
  device_name?: string | null;
  interface: string;
  encapsulation: "dot1q" | "qinq" | "ethernet_raw";
  vlan_id: number | null;
  vid: number | null;
  inner_vlan: number | null;
  mtu: number | null;
  operational_status: string;
}
export interface L2vcOut {
  id: number;
  domain_id: number;
  domain_name?: string | null;
  vc_id: number;
  name: string;
  organization_id: number | null;
  mtu: number;
  control_word: boolean;
  flow_label: boolean;
  redundancy: string | null;
  description: string | null;
  admin_status: boolean;
  operational_status: string;
  last_collected_at: string | null;
  created_at: string;
  endpoints: ServiceEndpointOut[];
}
export interface L2vcEndpointIn {
  device_id: number;
  interface: string;
  encapsulation?: "dot1q" | "qinq";
  vid?: number | null;
  inner_vlan?: number | null;
  mtu?: number | null;
}
export interface L2vcCreateIn {
  domain_id: number;
  name: string;
  vc_id?: number | null;
  organization_id?: number | null;
  mtu?: number;
  control_word?: boolean;
  flow_label?: boolean;
  redundancy?: string | null;
  description?: string | null;
  endpoints: L2vcEndpointIn[];
}
// Blocos do plano L2VC — mesma forma do `plano_json` das CRs (automation/changes.py
// `_bloco_para_plano`), com o nome `objeto` incluído.
export interface PlanoBlocoL2vc {
  tipo: string;
  objeto: string;
  acao: "create" | "delete";
  objeto_id: number;
  comandos: string[];
}
export interface PlanoL2vcOut {
  device_id: number;
  blocos: PlanoBlocoL2vc[];
  aviso: string | null;
  baseline_snapshot_id: number | null;
}
export interface VsiMemberOut {
  device_id: number;
  device_name?: string | null;
}
export interface VsiOut {
  id: number;
  domain_id: number;
  domain_name?: string | null;
  vsi_id: number;
  name: string;
  vrp_name: string;
  signaling: string;
  mtu: number;
  split_horizon: boolean;
  mac_learning: boolean;
  mac_limit: number | null;
  admin_status: boolean;
  operational_status: string;
  last_collected_at: string | null;
  members: VsiMemberOut[];
}
export interface VsiCreateIn {
  domain_id: number;
  name: string;
  vsi_id?: number | null;
  mtu?: number;
  split_horizon?: boolean;
  mac_learning?: boolean;
  mac_limit?: number | null;
  members: number[];
}

// Fase 5 — Upstreams (spec §7): conectividade própria — trânsito/IX/PNI.
export type UpstreamTipo = "transito" | "ix" | "pni" | "contingencia";
export interface UpstreamOut {
  id: number;
  name: string;
  tipo: UpstreamTipo;
  capacity: string | null;
  priority: number | null;
  cost: string | null;
  organization_id: number;
  expected_prefixes_v4: number | null;
  expected_prefixes_v6: number | null;
  max_prefix_margin_pct: number;
  rpki_enabled: boolean;
  entrada_local_preference: number | null;
  contingencia_local_preference: number | null;
  contingencia_prepend: number | null;
  contingencia_notes: string | null;
  admin_status: boolean;
  organization_kind: string | null; // kind da organização (operadora) — preenchido no router
  organization_name: string | null; // nome da organização — preenchido no router
  created_at: string;
  updated_at: string;
}
export interface UpstreamCircuitOut {
  id: number;
  upstream_id: number;
  circuit_id: number;
  papel: "principal" | "contingencia";
  ordem: number;
}
export interface UpstreamCommunityOut {
  id: number;
  upstream_id: number;
  purpose: "blackhole" | "prepend" | "lp" | "info";
  value: string;
  direcao: "import" | "export" | "ambos";
  regiao: string | null;
  bloquear: boolean;
  notes: string | null;
  admin_status: boolean;
}
export interface UpstreamDetailOut extends UpstreamOut {
  circuitos: UpstreamCircuitOut[];
  sessoes: BgpSessionOut[];
  comunidades: UpstreamCommunityOut[];
}
export type UpstreamCreateIn = {
  name: string;
  tipo: UpstreamTipo;
  capacity?: string | null;
  priority?: number | null;
  cost?: string | null;
  organization_id: number;
  expected_prefixes_v4?: number | null;
  expected_prefixes_v6?: number | null;
  max_prefix_margin_pct?: number;
  rpki_enabled?: boolean;
  entrada_local_preference?: number | null;
  contingencia_local_preference?: number | null;
  contingencia_prepend?: number | null;
  contingencia_notes?: string | null;
};
export type UpstreamUpdateIn = Partial<UpstreamCreateIn> & { admin_status?: boolean };
export type UpstreamCircuitIn = {
  circuit_id: number;
  papel?: UpstreamCircuitOut["papel"];
  ordem?: number;
};
export type UpstreamCommunityCreateIn = {
  purpose: UpstreamCommunityOut["purpose"];
  value: string;
  direcao?: UpstreamCommunityOut["direcao"];
  regiao?: string | null;
  bloquear?: boolean;
  notes?: string | null;
};
