import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import CircuitDetail from "./CircuitDetail";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
const org = { id: 1, name: "Cliente A", kind: "downstream", asn: 64512, admin_status: true };
const site = { id: 1, name: "SPO", admin_status: true };
const dev1 = { id: 1, name: "sw-01", management_address: "10.9.0.1", site_id: 1, family: "S6730", role: "acesso", asn: null, ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const dev2 = { id: 2, name: "ne-01", management_address: "10.9.0.2", site_id: 1, family: "NE8000", role: "edge", asn: 64600, ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };

let reservado = true;
const detalhe = () => ({
  id: 1, code: "CIRC-01", organization_id: 1, site_id: 1,
  access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2,
  backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false,
  vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31,
  description: null, notes: null, edge_trunk: null, admin_status: true,
  ipv4_local: reservado ? "100.64.0.0" : null,
  ipv4_remote: reservado ? "100.64.0.1" : null,
  ipv6_local: reservado ? "2804:194C:1000::6400:1/126" : null,
  ipv6_remote: reservado ? "2804:194C:1000::6400:2/126" : null,
  upstream_id: null,
});

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/unreserve")) {
        reservado = false;
        return new Response(JSON.stringify(detalhe()), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/circuits/1") return new Response(JSON.stringify(detalhe()), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/bgp-sessions")) return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/organizations") return new Response(JSON.stringify([org]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sites") return new Response(JSON.stringify([site]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return new Response(JSON.stringify([dev1, dev2]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderDetalhe() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/circuits/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/circuits/:id" element={<CircuitDetail />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CircuitDetail", () => {
  it("mostra 'Remover recursos' quando o circuito tem reservas", async () => {
    reservado = true;
    renderDetalhe();
    expect(await screen.findByRole("button", { name: "Reservar recursos" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remover recursos" })).toBeInTheDocument();
  });

  it("confirma antes de chamar o unreserve e esconde o botão após liberar", async () => {
    reservado = true;
    renderDetalhe();
    await userEvent.click(await screen.findByRole("button", { name: "Remover recursos" }));

    const confirmar = await screen.findByRole("button", { name: "Confirmar" });
    await userEvent.click(confirmar);

    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[0]).endsWith("/unreserve"))).toBe(true);
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Remover recursos" })).not.toBeInTheDocument();
    });
  });

  it("não mostra 'Remover recursos' sem reservas", async () => {
    reservado = false;
    renderDetalhe();
    await screen.findByText(/CIRC-01/);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Remover recursos" })).not.toBeInTheDocument();
    });
  });
});
