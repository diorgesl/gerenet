import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UpstreamDetail from "./UpstreamDetail";
import { AuthProvider } from "@/auth/auth-context";

let ME: Record<string, unknown> = {
  id: 1,
  username: "ops",
  role: "operador",
  is_active: true,
  last_login_at: null,
  created_at: "",
};

const UPSTREAM = {
  id: 1,
  name: "transito-telco-01",
  tipo: "transito",
  capacity: "10 Gbps",
  priority: 1,
  cost: "R$ 10",
  organization_id: 51,
  expected_prefixes_v4: 1000,
  expected_prefixes_v6: 200,
  max_prefix_margin_pct: 20,
  rpki_enabled: true,
  entrada_local_preference: 100,
  contingencia_local_preference: 60,
  contingencia_prepend: 3,
  contingencia_notes: "circuito de teste",
  admin_status: true,
  organization_kind: "operadora",
  organization_name: "Telco SP",
  created_at: "2026-09-08T10:00:00Z",
  updated_at: "2026-09-08T10:00:00Z",
  circuitos: [
    { id: 10, upstream_id: 1, circuit_id: 12, papel: "principal", ordem: 1 },
    { id: 11, upstream_id: 1, circuit_id: 8, papel: "contingencia", ordem: 2 },
  ],
  sessoes: [
    {
      id: 100,
      circuit_id: 12,
      device_id: 3,
      afi: "ipv4",
      local_address: "100.64.12.1",
      remote_address: "100.64.12.2",
      source_address: null,
      asn_local: 65001,
      asn_remote: 64531,
      description: "principal-v4",
      import_profile_id: null,
      export_profile_id: null,
      maximum_prefix: 1000,
      maximum_prefix_threshold: 90,
      local_preference: 100,
      med: null,
      prepend: null,
      keepalive: null,
      holdtime: null,
      bfd_enabled: true,
      graceful_restart: true,
      shutdown: false,
      allow_default_route: true,
      has_password: false,
      admin_status: true,
      organization_kind: "operadora",
    },
    {
      id: 101,
      circuit_id: 8,
      device_id: 3,
      afi: "ipv6",
      local_address: "2001:db8::1",
      remote_address: "2001:db8::2",
      source_address: null,
      asn_local: 65001,
      asn_remote: 64531,
      description: "contingencia-v6",
      import_profile_id: null,
      export_profile_id: null,
      maximum_prefix: null,
      maximum_prefix_threshold: null,
      local_preference: null,
      med: null,
      prepend: null,
      keepalive: null,
      holdtime: null,
      bfd_enabled: false,
      graceful_restart: false,
      shutdown: true,
      allow_default_route: false,
      has_password: false,
      admin_status: true,
      organization_kind: "operadora",
    },
  ],
  comunidades: [
    {
      id: 200,
      upstream_id: 1,
      purpose: "prepend",
      value: "65530:100:0",
      direcao: "ambos",
      regiao: "Nordeste",
      bloquear: false,
      notes: "prepend default",
      admin_status: true,
    },
  ],
};

const CIRCUITS = [
  { id: 12, code: "UP-PRINC-1", organization_id: 51, site_id: 5, access_device_id: 2, access_port: "GE0/0/1", edge_device_id: 3, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: null, bandwidth: "10 Gbps", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true },
  { id: 13, code: "UP-LIVRE-1", organization_id: 51, site_id: 5, access_device_id: 2, access_port: "GE0/0/2", edge_device_id: 3, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: null, bandwidth: "5 Gbps", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true },
];

const AUTORIZACOES = [
  { id: 300, organization_id: 51, family: "ipv4", prefix: "200.0.0.0/21", origin: "manual", validacao: "ok", notes: null, admin_status: true },
  { id: 301, organization_id: 51, family: "ipv6", prefix: "2001:db8::/32", origin: "manual", validacao: "diverge", notes: null, admin_status: true },
  { id: 302, organization_id: 51, family: "ipv4", prefix: "201.0.0.0/22", origin: "irr", validacao: null, notes: null, admin_status: false },
];

beforeEach(() => {
  ME = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };
});

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/auth/me") {
        return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/upstreams/1" && (init?.method === undefined || init.method === "GET")) {
        return new Response(JSON.stringify(UPSTREAM), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/circuits") {
        return new Response(JSON.stringify(CIRCUITS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/prefix-authorizations?organization_id=51") {
        return new Response(JSON.stringify(AUTORIZACOES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/upstreams/1/communities" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 201, upstream_id: 1, admin_status: true, ...body }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/v1/upstreams/1/communities/200" && init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      if (url === "/api/v1/upstreams/1/circuits" && init?.method === "POST") {
        return new Response(JSON.stringify(UPSTREAM), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url?.startsWith("/api/v1/change-requests") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 9, ...body, status: "rascunho", solicitante_id: 1, rollback_de: null, created_at: "2026-09-08T10:00:00Z", steps: [], approvals: [] }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/upstreams/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/upstreams/:id" element={<UpstreamDetail />} />
            <Route path="/change-requests/:id" element={<div>cr-detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("UpstreamDetail", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("renderiza o perfil e a matriz principal × contingência (papel/ordem/afi)", async () => {
    mockFetch();
    renderDetail();

    expect(await screen.findByText("transito-telco-01")).toBeInTheDocument();
    expect(screen.getByText("Telco SP")).toBeInTheDocument();
    // matriz: papéis, ordens e circuitos vinculados ("principal" também
    // aparece na option do seletor de papel — por isso getAllByText)
    expect(screen.getAllByText("principal").length).toBeGreaterThan(0);
    expect(screen.getByText("contingencia")).toBeInTheDocument();
    expect(screen.getByText("Circuito #12")).toBeInTheDocument();
    expect(screen.getByText("Circuito #8")).toBeInTheDocument();
    // sessões: afi + endereços + situação/cadastro (ipv4 também é a família
    // de uma autorização — por isso getAllByText)
    expect(screen.getAllByText("ipv4").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ipv6").length).toBeGreaterThan(0);
    expect(screen.getByText("100.64.12.1 ↔ 100.64.12.2")).toBeInTheDocument();
    expect(screen.getAllByText("ativo").length).toBeGreaterThan(0);
    // autorizações com validação
    expect(await screen.findByText("200.0.0.0/21")).toBeInTheDocument();
    expect(screen.getByText("diverge")).toBeInTheDocument();
  });

  it("lista communities e remove via diálogo de confirmação flutuante (DELETE)", async () => {
    mockFetch();
    renderDetail();

    expect(await screen.findByText("65530:100:0")).toBeInTheDocument();
    expect(screen.getByText("Nordeste")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remover" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/upstreams/1/communities/200" && c[1]?.method === "DELETE")).toBe(true);
    });
  });

  it("cadastra community via diálogo (POST no upstream)", async () => {
    mockFetch();
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Nova community" }));
    await userEvent.selectOptions(screen.getByLabelText("Purpose *"), "blackhole");
    await userEvent.type(screen.getByLabelText("Valor *"), "65530:99");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const chamada = chamadas.find(
        (c) => c[0] === "/api/v1/upstreams/1/communities" && c[1]?.method === "POST",
      );
      expect(chamada).toBeTruthy();
      expect(String(chamada?.[1]?.body)).toContain('"purpose":"blackhole"');
      expect(String(chamada?.[1]?.body)).toContain('"value":"65530:99"');
    });
  });

  it("Solicitar mudança abre o diálogo do componente compartilhado e cria CR de escopo upstream", async () => {
    mockFetch();
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança no upstream" }));
    await userEvent.type(screen.getByLabelText("Motivo *"), "Atualizar política de entrada");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    expect(await screen.findByText("cr-detail-page")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(
        chamadas.some(
          (c) =>
            c[1]?.method === "POST" &&
            String(c[1]?.body).includes('"escopo":"upstream"') &&
            String(c[1]?.body).includes('"upstream_id":1'),
        ),
      ).toBe(true);
    });
  });

  it("oculta ações de escrita para visualizador", async () => {
    ME = { ...ME, role: "visualizador" };
    mockFetch();
    renderDetail();

    await screen.findByText("transito-telco-01");
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Nova community" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Solicitar mudança no upstream" })).toBeNull();
    });
    // matriz ainda visível
    expect(screen.getByText("principal")).toBeInTheDocument();
  });
});
