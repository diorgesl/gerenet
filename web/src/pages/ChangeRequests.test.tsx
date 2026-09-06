import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import ChangeRequests from "./ChangeRequests";
import { AuthProvider } from "@/auth/auth-context";

let criarFalhar = false; // mutável por teste — simula 422/409 na criação

const ME = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };
const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };
const cr = {
  id: 1, circuit_id: 1, acao: "provision", criticidade: "media", motivo: "Novo cliente GALAXIA",
  ticket: "TICKET-42", solicitante_id: 1, status: "rascunho", rollback_de: null,
  created_at: "2026-09-01T10:00:00Z", steps: [], approvals: [],
};

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        if (criarFalhar) {
          return new Response(JSON.stringify({ detail: "Circuito sem sessões ativas para planejar o provisionamento." }), { status: 422, headers: { "Content-Type": "application/json" } });
        }
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 9, ...body, status: "rascunho", solicitante_id: 1, rollback_de: null, created_at: "2026-09-05T10:00:00Z", steps: [], approvals: [] }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.startsWith("/api/v1/change-requests")) return new Response(JSON.stringify([cr]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

beforeEach(() => {
  criarFalhar = false;
});

function renderChangeRequests() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/change-requests"]}>
        <AuthProvider>
          <Routes>
            <Route path="/change-requests" element={<ChangeRequests />} />
            <Route path="/change-requests/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ChangeRequests", () => {
  it("lista change requests e navega para o detalhe", async () => {
    renderChangeRequests();
    expect(await screen.findByText("Novo cliente GALAXIA")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "#1" }));
    expect(await screen.findByText("detail-page")).toBeInTheDocument();
  });

  it("cria CR solicitando pela API", async () => {
    renderChangeRequests();
    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança" }));
    await userEvent.selectOptions(screen.getByLabelText("Circuito *"), "1");
    await userEvent.type(screen.getByLabelText("Motivo *"), "Troca de banda CIRC-01");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("Troca de banda CIRC-01"))).toBe(true);
    });
  });

  it("filtra por status enviando ?status=", async () => {
    renderChangeRequests();
    await screen.findByText("Novo cliente GALAXIA");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "aguardando_aprovacao");
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/change-requests?status=aguardando_aprovacao")).toBe(true);
    });
  });

  it("falha na criação mantém o modal aberto e mostra o erro", async () => {
    criarFalhar = true;
    renderChangeRequests();
    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança" }));
    await userEvent.selectOptions(screen.getByLabelText("Circuito *"), "1");
    await userEvent.type(screen.getByLabelText("Motivo *"), "Sem sessões ativas");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Circuito sem sessões ativas");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
