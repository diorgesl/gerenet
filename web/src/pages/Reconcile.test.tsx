import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reconcile from "./Reconcile";

const DEVICES = [{ id: 1, name: "ne8000-01" }];
const RECONCILE = {
  device_id: 1,
  snapshot_id: null,
  aviso: "Sem snapshot; comparando com o estado de produção.",
  gerado_em: "2026-09-04T00:00:00Z",
  items: [
    { tipo: "bgp", severidade: "critica", esperado: "peer up", encontrado: "peer down", acao: "reconciliar" },
    { tipo: "vlan", severidade: "atencao", esperado: "vlan 10", encontrado: "ausente", acao: "criar" },
  ],
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/devices") {
        return new Response(JSON.stringify(DEVICES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.startsWith("/api/v1/reconciliation?")) {
        return new Response(JSON.stringify(RECONCILE), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderReconcile(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Reconcile />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Reconcile", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("mostra divergências com aviso e filtra por severidade", async () => {
    mockFetch();
    renderReconcile("/reconcile?device_id=1");
    expect(await screen.findByText("Sem snapshot; comparando com o estado de produção.")).toBeInTheDocument();
    expect(screen.getByText("bgp")).toBeInTheDocument();
    expect(screen.getByText("vlan")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severidade"), "critica");
    expect(screen.getByText("bgp")).toBeInTheDocument();
    expect(screen.queryByText("vlan")).not.toBeInTheDocument();
  });

  it("snapshot_id na URL aciona o modo snapshot", async () => {
    mockFetch();
    renderReconcile("/reconcile?snapshot_id=7");
    expect(await screen.findByText("bgp")).toBeInTheDocument();
    const chamada = vi.mocked(fetch).mock.calls.some((c) => String(c[0]).includes("snapshot_id=7"));
    expect(chamada).toBe(true);
  });
});
