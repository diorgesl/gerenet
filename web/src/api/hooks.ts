import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type {
  AuditEventOut,
  BgpSessionOut,
  ChangeRequestCreateIn,
  ChangeRequestOut,
  CircuitDetailOut,
  CircuitOut,
  CollectResposta,
  CommunityOut,
  CommunityUpdateIn,
  ContactOut,
  DashboardOut,
  DesiredConfigOut,
  DeviceOut,
  JobRunOut,
  L2vcCreateIn,
  L2vcOut,
  MplsDomainCreateIn,
  MplsDomainOut,
  MplsDomainUpdateIn,
  MplsMemberIn,
  MplsMemberOut,
  OrganizationOut,
  PlanoL2vcOut,
  PolicyProfileOut,
  PolicyProfileUpdateIn,
  PrefixAuthorizationOut,
  ReconcileOut,
  SiteOut,
  SnapshotOut,
  UpstreamCircuitIn,
  UpstreamCommunityCreateIn,
  UpstreamCommunityOut,
  UpstreamCreateIn,
  UpstreamDetailOut,
  UpstreamOut,
  UpstreamUpdateIn,
  UserOut,
  VsiCreateIn,
  VsiOut,
  WikiIndiceItem,
  WikiPagina,
} from "./types";

export function useUsers(opts?: { includeDisabled?: boolean }) {
  return useQuery({
    queryKey: ["users", opts?.includeDisabled ?? false],
    queryFn: () => apiFetch<UserOut[]>(opts?.includeDisabled ? "/api/v1/users?include_disabled=true" : "/api/v1/users"),
  });
}

export function useUserCriar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string; role: string }) =>
      apiFetch<UserOut>("/api/v1/users", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUserAtualizar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<Pick<UserOut, "role">> & { username?: string; is_active?: boolean }) =>
      apiFetch<UserOut>(`/api/v1/users/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUserSenha() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      apiFetch<void>(`/api/v1/users/${id}/password`, { method: "POST", body: { password } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useDashboard() {
  return useQuery({ queryKey: ["dashboard"], queryFn: () => apiFetch<DashboardOut>("/api/v1/dashboard") });
}

// JOB_STATUS do domínio (models.py:22): queued/running/success/partial/error
const JOB_STATUS_TERMINAL = ["success", "partial", "error"];

export function useJobPoll(id: number | null) {
  return useQuery({
    queryKey: ["job", id],
    queryFn: () => apiFetch<JobRunOut>(`/api/v1/jobs/${id}`),
    enabled: id !== null && id > 0,
    refetchInterval: (query) =>
      query.state.status === "error" ||
      (query.state.data && JOB_STATUS_TERMINAL.includes(query.state.data.status))
        ? false
        : 3000,
  });
}

export function useLista<T>(chave: string, url: string, opts: { includeDisabled?: boolean } = {}) {
  return useQuery({
    queryKey: [chave, opts.includeDisabled ?? false],
    queryFn: () => apiFetch<T[]>(opts.includeDisabled ? `${url}?include_disabled=true` : url),
  });
}

export function useCriar<TIn, TOut>(chave: string, url: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TIn) => apiFetch<TOut>(url, { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [chave] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useAtualizar<TIn, TOut>(chave: string, url: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: TIn & { id: number }) =>
      apiFetch<TOut>(`${url}/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [chave] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useDevices = (opts?: { includeDisabled?: boolean }) => useLista<DeviceOut>("devices", "/api/v1/devices", opts);
export const useSites = (opts?: { includeDisabled?: boolean }) => useLista<SiteOut>("sites", "/api/v1/sites", opts);
export const useOrganizations = (opts?: { includeDisabled?: boolean }) => useLista<OrganizationOut>("organizations", "/api/v1/organizations", opts);
export const useContacts = (opts?: { includeDisabled?: boolean }) => useLista<ContactOut>("contacts", "/api/v1/contacts", opts);

export type DeviceCreateIn = {
  name: string;
  management_address: string;
  ssh_port?: number | null;
  model?: string | null;
  family?: string | null;
  role?: string | null;
  site_id?: number | null;
  asn?: number | null;
  tags?: string[];
};
export const useDeviceCriar = () => useCriar<DeviceCreateIn, DeviceOut>("devices", "/api/v1/devices");
export const useDeviceAtualizar = () =>
  useAtualizar<Partial<DeviceCreateIn> & { admin_status?: boolean }, DeviceOut>("devices", "/api/v1/devices");

export function useDeviceColetar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: number) =>
      apiFetch<CollectResposta>(`/api/v1/devices/${deviceId}/collect`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["devices"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useDevice(id: number) {
  return useQuery({
    queryKey: ["device", id],
    queryFn: () => apiFetch<DeviceOut>(`/api/v1/devices/${id}`),
    enabled: id > 0,
  });
}

export type SiteCreateIn = {
  name: string;
  city?: string | null;
  uf?: string | null;
  p2p_ipv4_block?: string | null;
  p2p_ipv6_base?: string | null;
};
export const useSiteCriar = () => useCriar<SiteCreateIn, SiteOut>("sites", "/api/v1/sites");
export const useSiteAtualizar = () => useAtualizar<Partial<SiteCreateIn> & { admin_status?: boolean }, SiteOut>("sites", "/api/v1/sites");

export type OrganizationCreateIn = {
  name: string;
  legal_name?: string | null;
  kind: "downstream" | "parceiro";
  asn?: number | null;
  irr_as_set?: string | null;
  notes?: string | null;
};
export const useOrganizationCriar = () =>
  useCriar<OrganizationCreateIn, OrganizationOut>("organizations", "/api/v1/organizations");
export const useOrganizationAtualizar = () =>
  useAtualizar<Partial<OrganizationCreateIn> & { admin_status?: boolean }, OrganizationOut>("organizations", "/api/v1/organizations");

export type ContactCreateIn = {
  organization_id: number;
  name: string;
  email?: string | null;
  phone?: string | null;
  kind: "tecnico" | "noc" | "admin";
};
export const useContactCriar = () => useCriar<ContactCreateIn, ContactOut>("contacts", "/api/v1/contacts");
export const useContactAtualizar = () =>
  useAtualizar<Partial<ContactCreateIn> & { admin_status?: boolean }, ContactOut>("contacts", "/api/v1/contacts");

export const useCircuits = (opts?: { includeDisabled?: boolean }) => useLista<CircuitOut>("circuits", "/api/v1/circuits", opts);
export const useCircuitDetail = (id: number) =>
  useQuery({ queryKey: ["circuit", id], queryFn: () => apiFetch<CircuitDetailOut>(`/api/v1/circuits/${id}`), enabled: id > 0 });

export type CircuitCreateIn = {
  code: string;
  organization_id: number;
  site_id: number;
  access_device_id: number;
  access_port: string;
  edge_device_id: number;
  backup_edge_device_id?: number | null;
  stack: "ipv4" | "ipv6" | "dual";
  vlan_mode: "unica" | "separada";
  qinq?: boolean;
  vrf?: string | null;
  mtu?: number | null;
  bandwidth?: string | null;
  bfd?: boolean;
  p2p_v4_len?: 30 | 31;
  description?: string | null;
  notes?: string | null;
  edge_trunk?: string | null;
};
export const useCircuitCriar = () => useCriar<CircuitCreateIn, CircuitOut>("circuits", "/api/v1/circuits");
export const useCircuitAtualizar = () =>
  useAtualizar<Partial<CircuitCreateIn> & { admin_status?: boolean }, CircuitOut>("circuits", "/api/v1/circuits");
export function useCircuitoReservar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<CircuitDetailOut>(`/api/v1/circuits/${id}/reserve`, { method: "POST" }),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ["circuit", id] });
      void qc.invalidateQueries({ queryKey: ["circuits"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useBgpSessions = (filtros?: { circuit_id?: number; device_id?: number; include_disabled?: boolean }) =>
  useQuery({
    queryKey: ["bgp-sessions", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.circuit_id) qs.set("circuit_id", String(filtros.circuit_id));
      if (filtros?.device_id) qs.set("device_id", String(filtros.device_id));
      if (filtros?.include_disabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<BgpSessionOut[]>(`/api/v1/bgp-sessions${suf}`);
    },
  });
export const useBgpSession = (id: number) =>
  useQuery({ queryKey: ["bgp-session", id], queryFn: () => apiFetch<BgpSessionOut>(`/api/v1/bgp-sessions/${id}`), enabled: id > 0 });

export type BgpSessionCreateIn = {
  circuit_id: number;
  device_id: number;
  afi: "ipv4" | "ipv6";
  local_address: string;
  remote_address: string;
  source_address?: string | null;
  asn_local?: number | null;
  asn_remote?: number | null;
  description?: string | null;
  import_profile_id?: number | null;
  export_profile_id?: number | null;
  maximum_prefix?: number | null;
  maximum_prefix_threshold?: number | null;
  local_preference?: number | null;
  med?: number | null;
  prepend?: number | null;
  keepalive?: number | null;
  holdtime?: number | null;
  bfd_enabled?: boolean;
  graceful_restart?: boolean;
  shutdown?: boolean;
  allow_default_route?: boolean;
};
export const useBgpSessionCriar = () => useCriar<BgpSessionCreateIn, BgpSessionOut>("bgp-sessions", "/api/v1/bgp-sessions");
export const useBgpSessionAtualizar = () =>
  useAtualizar<Partial<BgpSessionCreateIn> & { admin_status?: boolean }, BgpSessionOut>("bgp-sessions", "/api/v1/bgp-sessions");

export const useSessionCommunities = (sessionId: number) =>
  useQuery({
    queryKey: ["bgp-session-communities", sessionId],
    queryFn: () => apiFetch<CommunityOut[]>(`/api/v1/bgp-sessions/${sessionId}/communities`),
  });
export function useSessionCommunity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, communityId, associa }: { sessionId: number; communityId: number; associa: boolean }) =>
      associa
        ? apiFetch<void>(
            `/api/v1/bgp-sessions/${sessionId}/communities`,
            { method: "POST", body: { community_id: communityId } },
          )
        : apiFetch<void>(`/api/v1/bgp-sessions/${sessionId}/communities/${communityId}`, { method: "DELETE" }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["bgp-session-communities", v.sessionId] });
      void qc.invalidateQueries({ queryKey: ["bgp-session", v.sessionId] });
    },
  });
}
export function useSessionSenha() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, password }: { sessionId: number; password: string }) =>
      apiFetch<BgpSessionOut>(`/api/v1/bgp-sessions/${sessionId}/password`, { method: "POST", body: { password } }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["bgp-session", v.sessionId] });
      void qc.invalidateQueries({ queryKey: ["bgp-sessions"] });
    },
  });
}

export const useChangeRequests = (filtros?: { status?: string; circuit_id?: number; solicitante_id?: number }) =>
  useQuery({
    queryKey: ["change-requests", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.status) qs.set("status", filtros.status);
      if (filtros?.circuit_id) qs.set("circuit_id", String(filtros.circuit_id));
      if (filtros?.solicitante_id) qs.set("solicitante_id", String(filtros.solicitante_id));
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<ChangeRequestOut[]>(`/api/v1/change-requests${suf}`);
    },
  });
export const useChangeRequest = (id: number) =>
  useQuery({
    queryKey: ["change-request", id],
    queryFn: () => apiFetch<ChangeRequestOut>(`/api/v1/change-requests/${id}`),
    enabled: id > 0,
  });

export const useChangeRequestCriar = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChangeRequestCreateIn) =>
      apiFetch<ChangeRequestOut>("/api/v1/change-requests", { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
};

// Ações de transição com corpo vazio — espelham os endpoints T5 (POST retorna ChangeRequestOut).
function useChangeAction(caminho: (id: number) => string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<ChangeRequestOut>(caminho(id), { method: "POST" }),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ["change-request", id] });
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
export const useChangeRequestEnviar = () => useChangeAction((id) => `/api/v1/change-requests/${id}/enviar`);
export const useChangeRequestCancelar = () => useChangeAction((id) => `/api/v1/change-requests/${id}/cancelar`);
export const useChangeRequestRollback = () => useChangeAction((id) => `/api/v1/change-requests/${id}/rollback`);
export const useChangeRequestReconciliar = () => useChangeAction((id) => `/api/v1/change-requests/${id}/reconciliar`);

export function useChangeRequestAprovar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decisao, comentario }: { id: number; decisao: "aprovar" | "rejeitar"; comentario?: string | null }) =>
      apiFetch<ChangeRequestOut>(`/api/v1/change-requests/${id}/approve`, { method: "POST", body: { decisao, comentario } }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["change-request", v.id] });
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useChangeRequestExecutar() {
  const qc = useQueryClient();
  return useMutation({
    // /executar devolve 202 {queued, message, job_id} (T7) — mesmo shape de CollectResposta.
    mutationFn: (id: number) =>
      apiFetch<CollectResposta>(`/api/v1/change-requests/${id}/executar`, { method: "POST" }),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ["change-request", id] });
      void qc.invalidateQueries({ queryKey: ["change-requests"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

// ---- MPLS (spec §9; rotas da T8) ------------------------------------------
export function useMplsDomains(opts: { includeDisabled?: boolean } = {}) {
  return useLista<MplsDomainOut>("mpls-domains", "/api/v1/mpls/domains", opts);
}
export function useMplsDomainCriar() {
  return useCriar<MplsDomainCreateIn, MplsDomainOut>("mpls-domains", "/api/v1/mpls/domains");
}
export function useMplsDomainAtualizar() {
  return useAtualizar<MplsDomainUpdateIn, MplsDomainOut>("mpls-domains", "/api/v1/mpls/domains");
}
export function useMplsMemberAdicionar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ domainId, ...body }: { domainId: number } & MplsMemberIn) =>
      apiFetch<MplsMemberOut>(`/api/v1/mpls/domains/${domainId}/members`, { method: "POST", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["mpls-domains"] }),
  });
}
export function useMplsMemberRemover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ domainId, deviceId }: { domainId: number; deviceId: number }) =>
      apiFetch<void>(`/api/v1/mpls/domains/${domainId}/members/${deviceId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["mpls-domains"] }),
  });
}
export function useL2vc(opts: { domainId?: number; includeDisabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["mpls-l2vc", opts.domainId ?? null, opts.includeDisabled ?? false],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.domainId) qs.set("domain_id", String(opts.domainId));
      if (opts.includeDisabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<L2vcOut[]>(`/api/v1/mpls/l2vc${suf}`);
    },
  });
}
export const useL2vcCriar = () => useCriar<L2vcCreateIn, L2vcOut>("mpls-l2vc", "/api/v1/mpls/l2vc");
export const useL2vcDetalhe = (id: number) =>
  useQuery({ queryKey: ["mpls-l2vc", id], queryFn: () => apiFetch<L2vcOut>(`/api/v1/mpls/l2vc/${id}`), enabled: id > 0 });
export function useL2vcStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, admin_status }: { id: number; admin_status: boolean }) =>
      apiFetch<L2vcOut>(`/api/v1/mpls/l2vc/${id}/status`, { method: "PATCH", body: { admin_status } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mpls-l2vc"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
export function useL2vcPlano(id: number) {
  return useQuery({
    queryKey: ["mpls-l2vc-plano", id],
    queryFn: () => apiFetch<PlanoL2vcOut[]>(`/api/v1/mpls/l2vc/${id}/plano`),
    enabled: id > 0,
  });
}
export function useVsi(opts: { domainId?: number; includeDisabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["mpls-vsi", opts.domainId ?? null, opts.includeDisabled ?? false],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.domainId) qs.set("domain_id", String(opts.domainId));
      if (opts.includeDisabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<VsiOut[]>(`/api/v1/mpls/vsi${suf}`);
    },
  });
}
export const useVsiCriar = () => useCriar<VsiCreateIn, VsiOut>("mpls-vsi", "/api/v1/mpls/vsi");
export const useVsiDetalhe = (id: number) =>
  useQuery({ queryKey: ["mpls-vsi", id], queryFn: () => apiFetch<VsiOut>(`/api/v1/mpls/vsi/${id}`), enabled: id > 0 });

// ---- Upstreams (spec §7; rotas da fase 5) ---------------------------------
// O detail traz circuitos, sessões e communities DENTRO do UpstreamDetailOut —
// nada de listas separadas, para não duplicar fetch (R-23).
export function useUpstreams(opts: { organizationId?: number; includeDisabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["upstreams", opts.organizationId ?? null, opts.includeDisabled ?? false],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (opts.organizationId) qs.set("organization_id", String(opts.organizationId));
      if (opts.includeDisabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<UpstreamOut[]>(`/api/v1/upstreams${suf}`);
    },
  });
}
export const useUpstreamDetail = (id: number) =>
  useQuery({
    queryKey: ["upstream", id],
    queryFn: () => apiFetch<UpstreamDetailOut>(`/api/v1/upstreams/${id}`),
    enabled: id > 0,
  });
// Wrapper fino do detail (comunidades vêm dentro do UpstreamDetailOut) — não
// efetua fetch próprio: reaproveita o cache de ["upstream", id].
export function useUpstreamCommunities(id: number) {
  const detalhe = useUpstreamDetail(id);
  return { ...detalhe, data: detalhe.data?.comunidades };
}
export const useUpstreamCriar = () => useCriar<UpstreamCreateIn, UpstreamOut>("upstreams", "/api/v1/upstreams");
export const useUpstreamAtualizar = () =>
  useAtualizar<UpstreamUpdateIn, UpstreamOut>("upstreams", "/api/v1/upstreams");
export function useVincularCircuito() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ upstreamId, ...body }: { upstreamId: number } & UpstreamCircuitIn) =>
      apiFetch<UpstreamDetailOut>(`/api/v1/upstreams/${upstreamId}/circuits`, { method: "POST", body }),
    onSuccess: (_d, v) => void qc.invalidateQueries({ queryKey: ["upstream", v.upstreamId] }),
  });
}
export function useDesvincularCircuito() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ upstreamId, circuitId }: { upstreamId: number; circuitId: number }) =>
      apiFetch<void>(`/api/v1/upstreams/${upstreamId}/circuits/${circuitId}`, { method: "DELETE" }),
    onSuccess: (_d, v) => void qc.invalidateQueries({ queryKey: ["upstream", v.upstreamId] }),
  });
}
export function useAddUpstreamCommunity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ upstreamId, ...body }: { upstreamId: number } & UpstreamCommunityCreateIn) =>
      apiFetch<UpstreamCommunityOut>(`/api/v1/upstreams/${upstreamId}/communities`, { method: "POST", body }),
    onSuccess: (_d, v) => void qc.invalidateQueries({ queryKey: ["upstream", v.upstreamId] }),
  });
}
export function useRemoveUpstreamCommunity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ upstreamId, communityId }: { upstreamId: number; communityId: number }) =>
      apiFetch<void>(`/api/v1/upstreams/${upstreamId}/communities/${communityId}`, { method: "DELETE" }),
    onSuccess: (_d, v) => void qc.invalidateQueries({ queryKey: ["upstream", v.upstreamId] }),
  });
}

export const usePolicyProfiles = (filtros?: { direction?: string; include_disabled?: boolean }) =>
  useQuery({
    queryKey: ["policy-profiles", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.direction) qs.set("direction", filtros.direction);
      if (filtros?.include_disabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<PolicyProfileOut[]>(`/api/v1/policy-profiles${suf}`);
    },
  });
export const useCommunities = (opts?: { includeDisabled?: boolean }) => useLista<CommunityOut>("communities", "/api/v1/communities", opts);
export const useCommunityAtualizar = () =>
  useAtualizar<CommunityUpdateIn, CommunityOut>("communities", "/api/v1/communities");
export const usePolicyProfileAtualizar = () =>
  useAtualizar<PolicyProfileUpdateIn, PolicyProfileOut>("policy-profiles", "/api/v1/policy-profiles");

export const usePrefixAuthorizations = (filtros?: { organization_id?: number; family?: string; include_disabled?: boolean }) =>
  useQuery({
    queryKey: ["prefix-authorizations", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.organization_id) qs.set("organization_id", String(filtros.organization_id));
      if (filtros?.family) qs.set("family", filtros.family);
      if (filtros?.include_disabled) qs.set("include_disabled", "true");
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<PrefixAuthorizationOut[]>(`/api/v1/prefix-authorizations${suf}`);
    },
  });
export type PrefixAuthorizationCreateIn = {
  organization_id: number;
  family: "ipv4" | "ipv6";
  prefix: string;
  notes?: string | null;
};
export const usePrefixAuthorizationCriar = () =>
  useCriar<PrefixAuthorizationCreateIn, PrefixAuthorizationOut>("prefix-authorizations", "/api/v1/prefix-authorizations");
export const usePrefixAuthorizationDesativar = () =>
  useAtualizar<{ admin_status?: boolean }, PrefixAuthorizationOut>("prefix-authorizations", "/api/v1/prefix-authorizations");

export const useAuditEvents = (filtros?: { tipo?: string; objeto?: string; objeto_id?: number }) =>
  useQuery({
    queryKey: ["audit-events", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.tipo) qs.set("tipo", filtros.tipo);
      if (filtros?.objeto) qs.set("objeto", filtros.objeto);
      if (filtros?.objeto_id) qs.set("objeto_id", String(filtros.objeto_id));
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<AuditEventOut[]>(`/api/v1/audit-events${suf}`);
    },
  });

export function useSnapshots(deviceId: number) {
  return useQuery({
    queryKey: ["snapshots", deviceId],
    queryFn: () => apiFetch<SnapshotOut[]>(`/api/v1/devices/${deviceId}/snapshots`),
    enabled: deviceId > 0,
  });
}
export function useSnapshot(id: number) {
  return useQuery({
    queryKey: ["snapshot", id], // distinta de ["snapshots", deviceId] (ver correção a)
    queryFn: () => apiFetch<SnapshotOut>(`/api/v1/snapshots/${id}`),
    enabled: id > 0,
  });
}
export function useDesiredConfig(deviceId: number | null) {
  return useQuery({
    queryKey: ["desired", deviceId],
    queryFn: () => apiFetch<DesiredConfigOut>(`/api/v1/devices/${deviceId}/desired-config`),
    enabled: Boolean(deviceId),
    retry: false,
  });
}
export function useReconcile(filtro: { device_id?: number; snapshot_id?: number }) {
  return useQuery({
    queryKey: ["reconcile", filtro],
    queryFn: () =>
      apiFetch<ReconcileOut>(
        `/api/v1/reconciliation?${new URLSearchParams(
          Object.entries(filtro)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)] as [string, string]),
        ).toString()}`,
      ),
    enabled: Number(filtro.device_id ?? filtro.snapshot_id) > 0,
    retry: false,
  });
}
export function useJobs(filtros: {
  device_id?: number;
  status?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["jobs", filtros],
    queryFn: () =>
      apiFetch<JobRunOut[]>(
        `/api/v1/jobs?${new URLSearchParams(
          Object.entries(filtros)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)] as [string, string]),
        ).toString()}`,
      ),
  });
}

export function useWikiIndice() {
  return useQuery({
    queryKey: ["wiki-indice"],
    queryFn: () => apiFetch<WikiIndiceItem[]>("/api/v1/wiki"),
  });
}

export function useWikiPagina(slug: string | undefined) {
  return useQuery({
    queryKey: ["wiki-pagina", slug],
    queryFn: () => apiFetch<WikiPagina>(`/api/v1/wiki/${slug}`),
    enabled: Boolean(slug),
  });
}
