import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Circuits from "./Circuits";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
const org = { id: 1, name: "Cliente A", legal_name: null, kind: "downstream", asn: 64512, irr_as_set: null, notes: null, admin_status: true };
const site = { id: 1, name: "SPO", city: "São Paulo", uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true };
const dev1 = { id: 1, name: "sw-01", management_address: "10.9.0.1", site_id: 1, model: null, family: "S6730", role: "acesso", asn: null, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const dev2 = { id: 2, name: "ne-01", management_address: "10.9.0.2", site_id: 1, model: null, family: "NE8000", role: "edge", asn: 64600, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ id: 2, ...body, admin_status: true }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/organizations") return new Response(JSON.stringify([org]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sites") return new Response(JSON.stringify([site]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return new Response(JSON.stringify([dev1, dev2]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderCircuits() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/circuits"]}>
        <AuthProvider>
          <Routes>
            <Route path="/circuits" element={<Circuits />} />
            <Route path="/circuits/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Circuits", () => {
  it("lista circuitos e cria novo pela API", async () => {
    renderCircuits();
    expect(await screen.findByText("CIRC-01")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Código \*/), "CIRC-02");
    await userEvent.selectOptions(screen.getByLabelText(/^Organização \*/), "1");
    await userEvent.selectOptions(screen.getByLabelText(/^Site \*/), "1");
    await userEvent.selectOptions(screen.getByLabelText(/^Equipamento de acesso \*/), "1");
    await userEvent.type(screen.getByLabelText(/^Porta de acesso \*/), "GE0/0/2");
    await userEvent.selectOptions(screen.getByLabelText(/^Edge \*/), "2");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("CIRC-02"))).toBe(true);
    });
  });

  it("permite navegar para o detalhe pelo código", async () => {
    renderCircuits();
    await userEvent.click(await screen.findByRole("link", { name: "CIRC-01" }));
    expect(await screen.findByText("detail-page")).toBeInTheDocument();
  });
});
