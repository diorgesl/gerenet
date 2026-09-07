import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import SolicitarMudanca from "./SolicitarMudanca";
import { AuthProvider } from "@/auth/auth-context";

let ME: Record<string, unknown> = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };

beforeEach(() => {
  ME = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };
});

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 9, ...body, status: "rascunho", solicitante_id: 1, rollback_de: null, created_at: "2026-09-05T10:00:00Z", steps: [], approvals: [] }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderSolicitar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/circuits/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/circuits/1" element={<SolicitarMudanca circuit_id={1} />} />
            <Route path="/change-requests/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderSolicitarL2vc() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/l2vc/7"]}>
        <AuthProvider>
          <Routes>
            <Route path="/l2vc/7" element={<SolicitarMudanca l2vc_id={7} />} />
            <Route path="/change-requests/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SolicitarMudanca", () => {
  it("cria CR do circuito e navega ao detalhe", async () => {
    renderSolicitar();
    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança" }));
    await userEvent.type(screen.getByLabelText("Motivo *"), "Troca de banda do CIRC-01");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes('"circuit_id":1'))).toBe(true);
    });
    expect(await screen.findByText("detail-page")).toBeInTheDocument();
  });

  it("cria CR do L2VC com escopo l2vc e navega ao detalhe", async () => {
    renderSolicitarL2vc();
    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança no L2VC" }));
    await userEvent.type(screen.getByLabelText("Motivo *"), "Provisionar L2VC do cliente");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(
        chamadas.some(
          (c) =>
            c[1]?.method === "POST" &&
            String(c[1]?.body).includes('"escopo":"l2vc"') &&
            String(c[1]?.body).includes('"l2vc_id":7'),
        ),
      ).toBe(true);
    });
    expect(await screen.findByText("detail-page")).toBeInTheDocument();
  });

  it("não aparece para visualizador", async () => {
    ME = { ...ME, role: "visualizador" };
    renderSolicitar();
    // waitFor com retry: enquanto o /auth/me resolve o botão não existe (gate de
    // escrita) — e, se o gate for removido, o botão aparece e o teste falha.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Solicitar mudança" })).toBeNull();
    });
  });
});
