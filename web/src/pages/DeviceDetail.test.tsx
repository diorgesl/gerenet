import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DeviceDetail from "./DeviceDetail";

const DEVICE = {
  id: 1,
  name: "ne8000-01",
  management_address: "10.0.0.1",
  ssh_port: null,
  vendor: "huawei",
  model: "NE8000",
  family: "NE8000",
  role: "edge",
  site_id: 1,
  asn: 65001,
  vrp_version: "V800R021",
  comm_status: "ok",
  admin_status: true,
  last_collected_at: null,
  tags: [],
};
const SITES = [
  { id: 1, name: "POP-SP", city: null, uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true },
];
const SNAPSHOTS = [
  {
    id: 10,
    device_id: 1,
    started_at: "2026-09-04T00:00:00Z",
    finished_at: null,
    status: "success",
    resources: {},
    errors: {},
    duration_ms: 1000,
  },
];

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/devices/1" && (init?.method === undefined || init.method === "GET")) {
        return new Response(JSON.stringify(DEVICE), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/sites") {
        return new Response(JSON.stringify(SITES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/devices/1/snapshots") {
        return new Response(JSON.stringify(SNAPSHOTS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/devices/1/collect" && init?.method === "POST") {
        return new Response(JSON.stringify({ queued: true, message: "ok", job_id: "uuid-do-job" }), { status: 202, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/devices/1"]}>
        <Routes>
          <Route path="/devices/:id" element={<DeviceDetail />} />
          <Route path="/jobs" element={<div>jobs-page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DeviceDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renderiza dados do equipamento, snapshot e links de inspeção", async () => {
    mockFetch();
    renderDetail();
    expect(await screen.findByText("ne8000-01")).toBeInTheDocument();
    expect(screen.getByText("65001")).toBeInTheDocument();
    expect(screen.getByText("POP-SP")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reconciliar" })).toBeInTheDocument();
  });

  it("Coletar agora envia POST e navega para /jobs?device_id=1", async () => {
    mockFetch();
    renderDetail();
    await userEvent.click(await screen.findByRole("button", { name: "Coletar agora" }));
    expect(await screen.findByText("jobs-page")).toBeInTheDocument();
    const chamada = vi.mocked(fetch).mock.calls.find(
      (c) => String(c[0]) === "/api/v1/devices/1/collect" && String(c[1]?.method) === "POST",
    );
    expect(chamada).toBeTruthy();
  });
});
