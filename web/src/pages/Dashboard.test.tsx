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
      snapshot_age_seconds: null,
      latest_snapshot: null,
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
    expect(screen.getByText("equipamentos")).toHaveTextContent(/^3 equipamentos$/);
    expect(screen.getByText("coleta")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Reconciliar" })).toBeTruthy();
  });
});
