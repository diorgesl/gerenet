import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Snapshots from "./Snapshots";

const DEVICES = [{ id: 1, name: "ne8000-01" }];
const SNAPSHOTS = [
  {
    id: 10,
    device_id: 1,
    started_at: "2026-09-04T00:00:00Z",
    finished_at: "2026-09-04T00:00:05Z",
    status: "success",
    resources: {},
    errors: {},
    duration_ms: 5000,
  },
  {
    id: 11,
    device_id: 1,
    started_at: "2026-09-04T00:00:00Z",
    finished_at: null,
    status: "partial",
    resources: {},
    errors: {},
    duration_ms: 2000,
  },
];
const DETAIL = {
  id: 11,
  device_id: 1,
  started_at: "2026-09-04T00:00:00Z",
  finished_at: null,
  status: "partial",
  resources: {
    interfaces: { "GE0/0/0": { up: true } },
    bd: Array.from({ length: 70 }, (_, i) => i),
  },
  errors: { coleta_v4: "timeout" },
  duration_ms: 2000,
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/devices") {
        return new Response(JSON.stringify(DEVICES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/devices/1/snapshots") {
        return new Response(JSON.stringify(SNAPSHOTS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/snapshots/11") {
        return new Response(JSON.stringify(DETAIL), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderSnapshots() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/snapshots"]}>
        <Snapshots />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Snapshots", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lista snapshots, seleciona e mostra a árvore colapsável com paginação", async () => {
    mockFetch();
    renderSnapshots();
    // espera o useDevices resolver antes do selectOptions (a opção não existe
    // enquanto a lista está carregando — `Value "1" not found` de forma determinística)
    await screen.findByRole("option", { name: "ne8000-01" });
    await userEvent.selectOptions(screen.getByLabelText("Equipamento"), "1");
    expect(await screen.findByText("11")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Ver" })[1]);
    expect(await screen.findByText("interfaces")).toBeInTheDocument();
    expect(screen.getByText("Mostrar mais (10)")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Mostrar mais (10)"));
    await waitFor(() => {
      expect(screen.queryByText("Mostrar mais (10)")).not.toBeInTheDocument();
    });
  });
});
