import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type {
  BgpSessionOut,
  CircuitDetailOut,
  CircuitOut,
  CollectResposta,
  CommunityOut,
  ContactOut,
  DashboardOut,
  DeviceOut,
  JobRunOut,
  OrganizationOut,
  PolicyProfileOut,
  SiteOut,
  UserOut,
} from "./types";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => apiFetch<UserOut>("/api/v1/auth/me"), retry: false });
}

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => apiFetch<UserOut[]>("/api/v1/users"),
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
      query.state.data && JOB_STATUS_TERMINAL.includes(query.state.data.status) ? false : 3000,
  });
}

export function useLista<T>(chave: string, url: string) {
  return useQuery({ queryKey: [chave], queryFn: () => apiFetch<T[]>(url) });
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

export const useDevices = () => useLista<DeviceOut>("devices", "/api/v1/devices");
export const useSites = () => useLista<SiteOut>("sites", "/api/v1/sites");
export const useOrganizations = () => useLista<OrganizationOut>("organizations", "/api/v1/organizations");
export const useContacts = () => useLista<ContactOut>("contacts", "/api/v1/contacts");

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

export const useCircuits = () => useLista<CircuitOut>("circuits", "/api/v1/circuits");
export const useCircuitDetail = (id: number) =>
  useQuery({ queryKey: ["circuit", id], queryFn: () => apiFetch<CircuitDetailOut>(`/api/v1/circuits/${id}`) });

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

export const useBgpSessions = (filtros?: { circuit_id?: number; device_id?: number }) =>
  useQuery({
    queryKey: ["bgp-sessions", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.circuit_id) qs.set("circuit_id", String(filtros.circuit_id));
      if (filtros?.device_id) qs.set("device_id", String(filtros.device_id));
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<BgpSessionOut[]>(`/api/v1/bgp-sessions${suf}`);
    },
  });
export const useBgpSession = (id: number) =>
  useQuery({ queryKey: ["bgp-session", id], queryFn: () => apiFetch<BgpSessionOut>(`/api/v1/bgp-sessions/${id}`) });

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
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["bgp-sessions"] }),
  });
}

export const usePolicyProfiles = (filtros?: { direction?: string }) =>
  useQuery({
    queryKey: ["policy-profiles", filtros],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (filtros?.direction) qs.set("direction", filtros.direction);
      const suf = qs.size > 0 ? `?${qs.toString()}` : "";
      return apiFetch<PolicyProfileOut[]>(`/api/v1/policy-profiles${suf}`);
    },
  });
export const useCommunities = () => useLista<CommunityOut>("communities", "/api/v1/communities");
