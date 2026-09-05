import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, describe, expect, it, vi } from "vitest";
import AuditEvents from "./AuditEvents";

const EVENTOS = [
  { id: 1, type: "device.create", actor: "cli", details: { objeto: "device", objeto_id: 1 }, created_at: "2026-09-04T12:00:00Z" },
];

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      return new Response(JSON.stringify(EVENTOS), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuditEvents />
    </QueryClientProvider>,
  );
}

describe("AuditEvents", () => {
  it("lista eventos e filtra por tipo", async () => {
    renderPage();
    expect(await screen.findByText("device.create")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Tipo"), "device.");
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => String(c[0]).includes("tipo=device."))).toBe(true);
    });
  });

  it("expande os detalhes do evento", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Exibir"));
    expect(screen.getByText(/"objeto": "device"/)).toBeTruthy();
  });
});
