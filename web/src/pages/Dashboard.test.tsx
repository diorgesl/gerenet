import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";

const DASH = {
  devices: { total: 3, active: 2, with_snapshot: 1, by_comm_status: { unknown: 1, ok: 1, fail: 1 } },
  per_device: [
    {
      device_id: 1,
      name: "ne8000-01",
      site_id: null,
      site_name: null,
      comm_status: "ok",
      last_collected_at: null,
      snapshot_age_seconds: 90000, // 25 h > 24 h → alerta
      latest_snapshot: {
        id: 9,
        status: "error",
        started_at: "2026-09-05T17:12:42Z",
        error: "Authentication to device failed.",
      },
      active_job: null,
    },
  ],
  bgp_sessions: { total: 4, active: 3, shutdown: 1 },
  circuits: { total: 2, active: 1 },
  vlans: { reserved: 5, freed: 0 },
  ip_prefixes: { reserved: 7, freed: 0 },
  recent_audit: [{ id: 1, type: "coleta", actor: "boss", details: {}, created_at: "2026-09-04T00:00:00Z" }],
};

describe("Dashboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renderiza cards, per_device e auditoria recente", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/v1/dashboard") {
          return new Response(JSON.stringify(DASH), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url === "/api/v1/change-requests?status=aguardando_aprovacao") {
          return new Response(
            JSON.stringify([
              { id: 1, circuit_id: 1, acao: "provision", criticidade: "media", motivo: "m1", ticket: null, solicitante_id: 1, status: "aguardando_aprovacao", rollback_de: null, created_at: "2026-09-05T10:00:00Z", steps: [], approvals: [] },
              { id: 2, circuit_id: 1, acao: "remove", criticidade: "alta", motivo: "m2", ticket: null, solicitante_id: 2, status: "aguardando_aprovacao", rollback_de: null, created_at: "2026-09-05T11:00:00Z", steps: [], approvals: [] },
            ]),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url === "/api/v1/mpls/l2vc") {
          return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url === "/api/v1/mpls/vsi") {
          return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url === "/api/v1/upstreams") {
          return new Response(
            JSON.stringify([
              { id: 1, name: "tr-01", tipo: "transito", admin_status: true },
              { id: 2, name: "con-01", tipo: "contingencia", admin_status: false },
            ]),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(null, { status: 404 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("ne8000-01")).toBeTruthy();
    expect(screen.getByText("2/3")).toBeTruthy();
    expect(screen.getByText("3 equipamento(s): 1 ok · 1 com falha · 1 desconhecido")).toBeTruthy();
    expect(screen.getByText("25.0 h")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Equipamentos" })).toBeTruthy();
    expect(screen.getByText("Authentication to device failed.")).toBeTruthy();
    expect(screen.getByText("coleta")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Reconciliar" })).toBeTruthy();
    expect(screen.getByText(/mudanças/)).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    // Card de upstreams (R-28): 1 ativo de 2 cadastrados — a contagem usa useUpstreams().
    expect(screen.getByText(/upstreams/)).toBeTruthy();
    expect(vi.mocked(fetch).mock.calls.some((c) => String(c[0]) === "/api/v1/upstreams")).toBe(true);
  });
});
