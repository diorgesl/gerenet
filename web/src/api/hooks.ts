import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type {
  CollectResposta,
  ContactOut,
  DashboardOut,
  DeviceOut,
  JobRunOut,
  OrganizationOut,
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
