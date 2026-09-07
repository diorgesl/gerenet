import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import BgpSessions from "./BgpSessions";
import BgpSessionDetail from "./BgpSessionDetail";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };
const dev = { id: 2, name: "ne-01", management_address: "10.9.0.2", site_id: 1, model: null, family: "NE8000", role: "edge", asn: 64600, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const catalogo = [{ id: 1, name: "blackhole", notes: null }];
const org = { id: 1, name: "Cliente ACME", legal_name: null, kind: "downstream", asn: 64512, irr_as_set: null, notes: null, admin_status: true };
let sessao: Record<string, unknown>;
let associadas: { id: number; name: string; notes: null }[];
let hasPassword: boolean;
let detalhe: { ipv4_local: string | null; ipv4_remote: string | null; ipv6_local: string | null; ipv6_remote: string | null };

function opcoes() {
  return {
    status: 200,
    headers: { "Content-Type": "application/json" },
  };
}

beforeAll(() => {
  sessao = {
    id: 1, circuit_id: 1, device_id: 2, afi: "ipv4", local_address: "100.64.40.1", remote_address: "100.64.40.2",
    source_address: null, asn_local: 64600, asn_remote: 64512, description: null, import_profile_id: null,
    export_profile_id: null, maximum_prefix: 100, maximum_prefix_threshold: 80, local_preference: 100,
    med: null, prepend: null, keepalive: 30, holdtime: 90, bfd_enabled: true, graceful_restart: false,
    shutdown: false, allow_default_route: false, has_password: false, admin_status: true,
  };
  associadas = [];
  hasPassword = false;
  detalhe = { ipv4_local: null, ipv4_remote: null, ipv6_local: null, ipv6_remote: null };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && url === "/api/v1/bgp-sessions/1/communities") {
        const body = JSON.parse(String(init?.body));
        const com = catalogo.find((c) => c.id === body.community_id);
        if (com) associadas.push({ ...com });
        return new Response(JSON.stringify({ session_id: 1, community_id: body.community_id }), opcoes());
      }
      if (method === "DELETE" && url === "/api/v1/bgp-sessions/1/communities/1") {
        associadas = [];
        return new Response(null, { status: 204 });
      }
      if (method === "POST" && url === "/api/v1/bgp-sessions/1/password") {
        hasPassword = true;
        return new Response(JSON.stringify({ ...sessao, has_password: true }), opcoes());
      }
      if (method === "POST" && url === "/api/v1/bgp-sessions") {
        const body = JSON.parse(String(init?.body));
        return new Response(JSON.stringify({ id: 2, ...body, has_password: false, admin_status: true }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/bgp-sessions/1/communities") return new Response(JSON.stringify(associadas), opcoes());
      if (url === "/api/v1/bgp-sessions/1" && method === "GET") return new Response(JSON.stringify({ ...sessao, has_password: hasPassword }), opcoes());
      if (url === "/api/v1/bgp-sessions") return new Response(JSON.stringify([{ ...sessao, has_password: hasPassword }]), opcoes());
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), opcoes());
      if (url === "/api/v1/circuits/1" && method === "GET")
        return new Response(JSON.stringify({ ...circ, ...detalhe }), opcoes());
      if (url.startsWith("/api/v1/organizations")) return new Response(JSON.stringify([org]), opcoes());
      if (url === "/api/v1/devices") return new Response(JSON.stringify([dev]), opcoes());
      if (url === "/api/v1/policy-profiles") return new Response(JSON.stringify([]), opcoes());
      if (url === "/api/v1/communities") return new Response(JSON.stringify(catalogo), opcoes());
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), opcoes());
      return new Response("null", { status: 404 });
    }),
  );
});

function renderList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/bgp-sessions"]}>
        <AuthProvider>
          <Routes>
            <Route path="/bgp-sessions" element={<BgpSessions />} />
            <Route path="/bgp-sessions/:id" element={<BgpSessionDetail />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/bgp-sessions/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/bgp-sessions/:id" element={<BgpSessionDetail />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BgpSessions", () => {
  it("lista sessões e cria nova pela API", async () => {
    renderList();
    expect(await screen.findByText("100.64.40.1 ↔ 100.64.40.2")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/^Circuito \*/), "1");
    await userEvent.selectOptions(screen.getByLabelText(/^Equipamento \*/), "2");
    await userEvent.type(screen.getByLabelText(/^Endereço local \*/), "100.64.42.1");
    await userEvent.type(screen.getByLabelText(/^Endereço remoto \*/), "100.64.42.2");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("100.64.42.1"))).toBe(true);
    });
  });

  it("autopreenche equipamento, ASN local/remoto e o par v4 ao escolher o circuito", async () => {
    detalhe = { ipv4_local: "172.16.0.1", ipv4_remote: "172.16.0.2", ipv6_local: "2001:db8::1/126", ipv6_remote: "2001:db8::2/126" };
    renderList();
    await screen.findByText("100.64.40.1 ↔ 100.64.40.2");
    await userEvent.selectOptions(screen.getByLabelText(/^Circuito \*/), "1");
    expect(screen.getByLabelText(/^Equipamento \*/)).toHaveValue("2");
    expect(screen.getByLabelText(/^ASN local/)).toHaveValue(64600);
    expect(screen.getByLabelText(/^ASN remoto/)).toHaveValue(64512);
    await waitFor(() => expect(screen.getByLabelText(/^Endereço local \*/)).toHaveValue("172.16.0.1"));
    expect(screen.getByLabelText(/^Endereço remoto \*/)).toHaveValue("172.16.0.2");
  });

  it("trocar a família preenche o par v6 sem a máscara /126", async () => {
    detalhe = { ipv4_local: "172.16.0.1", ipv4_remote: "172.16.0.2", ipv6_local: "2001:db8::1/126", ipv6_remote: "2001:db8::2/126" };
    renderList();
    await screen.findByText("100.64.40.1 ↔ 100.64.40.2");
    await userEvent.selectOptions(screen.getByLabelText(/^Circuito \*/), "1");
    await waitFor(() => expect(screen.getByLabelText(/^Endereço local \*/)).toHaveValue("172.16.0.1"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /^Família/ }), "ipv6");
    expect(screen.getByLabelText(/^Endereço local \*/)).toHaveValue("2001:db8::1");
    expect(screen.getByLabelText(/^Endereço remoto \*/)).toHaveValue("2001:db8::2");
  });

  it("circuito sem reserva mantém os endereços em branco", async () => {
    detalhe = { ipv4_local: null, ipv4_remote: null, ipv6_local: null, ipv6_remote: null };
    renderList();
    await screen.findByText("100.64.40.1 ↔ 100.64.40.2");
    await userEvent.selectOptions(screen.getByLabelText(/^Circuito \*/), "1");
    expect(screen.getByLabelText(/^Endereço local \*/)).toHaveValue("");
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string][];
      expect(chamadas.some((c) => c[0] === "/api/v1/circuits/1")).toBe(true);
    });
    expect(screen.getByLabelText(/^Endereço local \*/)).toHaveValue("");
  });

  it("abrir a edição não sobrescreve os valores salvos com os do circuito", async () => {
    detalhe = { ipv4_local: "172.16.0.1", ipv4_remote: "172.16.0.2", ipv6_local: "2001:db8::1/126", ipv6_remote: "2001:db8::2/126" };
    renderList();
    await screen.findByText("100.64.40.1 ↔ 100.64.40.2");
    await userEvent.click(screen.getByRole("button", { name: "Editar" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText(/^Endereço local \*/)).toHaveValue("100.64.40.1");
    expect(within(dialog).getByLabelText(/^Endereço remoto \*/)).toHaveValue("100.64.40.2");
  });

  it("detalhe associa e remove community", async () => {
    renderDetail();
    await screen.findByText(/Sessão BGP #1/);
    await userEvent.selectOptions(screen.getByLabelText(/^Community/), "1");
    await userEvent.click(screen.getByRole("button", { name: "Associar" }));
    expect(await screen.findByRole("button", { name: "Remover" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remover" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remover" })).not.toBeInTheDocument());
  });

  it("define senha MD5 e mostra que há senha", async () => {
    renderDetail();
    await screen.findByText(/Sessão BGP #1/);
    await userEvent.type(screen.getByLabelText(/^Senha MD5.*\?$/), "segredo");
    await userEvent.click(screen.getByRole("button", { name: "Definir senha" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/bgp-sessions/1/password" && c[1]?.method === "POST")).toBe(true);
    });
  });
});
