import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, beforeAll, describe, expect, it, vi } from "vitest";
import ChangeRequestDetail from "./ChangeRequestDetail";
import { AuthProvider } from "@/auth/auth-context";

let ME: Record<string, unknown>; // mutável por teste — define o papel do usuário logado

const circ = { id: 1, code: "CIRC-01", organization_id: 1, site_id: 1, access_device_id: 1, access_port: "GE0/0/1", edge_device_id: 2, backup_edge_device_id: null, stack: "dual", vlan_mode: "unica", qinq: false, vrf: null, mtu: 1500, bandwidth: "1G", bfd: true, p2p_v4_len: 31, description: null, notes: null, edge_trunk: null, admin_status: true };
const dev1 = { id: 1, name: "ne-01", management_address: "10.9.0.2", site_id: 1, model: null, family: "NE8000", role: "edge", asn: 64600, tags: [], ssh_port: 22, vendor: "Huawei", vrp_version: null, comm_status: "ok", admin_status: true, last_collected_at: null };
const crBase = {
  id: 1, circuit_id: 1 as number | null, escopo: "circuito" as string, l2vc_id: null as number | null, l2vc_name: null as string | null,
  upstream_id: null as number | null, upstream_name: null as string | null,
  acao: "provision", criticidade: "media", motivo: "Novo cliente GALAXIA",
  ticket: "TICKET-42", rollback_de: null, created_at: "2026-09-01T10:00:00Z",
  approvals: [{ id: 1, user_id: 9, decisao: "aprovar", comentario: "ok", created_at: "2026-09-02T10:00:00Z" }],
  steps: [{
    id: 1, device_id: 1, status: "pendente", aviso: null, baseline_snapshot_id: 3,
    backup_snapshot_id: null, erro: null, finished_at: null,
    post_check_json: null, plano_json: [
      { tipo: "bgp_peer", objeto: "peer", objeto_id: 1, acao: "create", comandos: ["peer 10.9.0.9 as-number 64512", "peer 10.9.0.9 description CLIENTE-GALAXIA"] },
    ],
  }],
};

function crDe(solicitanteId: number | null, status: string) {
  return { ...crBase, solicitante_id: solicitanteId, status };
}

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/approve")) {
        return new Response(JSON.stringify({ ...crDe(2, "aprovado"), approvals: [{ ...crBase.approvals[0], user_id: ME.id as number }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (init?.method === "POST" && url.endsWith("/executar")) {
        return new Response(JSON.stringify({ queued: true, message: "Mudança enfileirada.", job_id: "abc123" }), { status: 202, headers: { "Content-Type": "application/json" } });
      }
      if (url === `/api/v1/change-requests/1`) return new Response(JSON.stringify(CR_ATUAL()), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/circuits") return new Response(JSON.stringify([circ]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return new Response(JSON.stringify([dev1]), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/auth/me") return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("null", { status: 404 });
    }),
  );
});

const CR_ATUAL = () => crAtual;
let crAtual = crDe(2, "aguardando_aprovacao");

beforeEach(() => {
  ME = { id: 1, username: "aprovador-ex", role: "aprovador", is_active: true, last_login_at: null, created_at: "" };
  crAtual = crDe(2, "aguardando_aprovacao");
});

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/change-requests/1"]}>
        <AuthProvider>
          <Routes>
            <Route path="/change-requests/:id" element={<ChangeRequestDetail />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ChangeRequestDetail", () => {
  it("aprovador aprova e vê o diff por bloco", async () => {
    renderDetail();
    expect(await screen.findByText("Change request #1")).toBeInTheDocument();
    expect(screen.getByText(/as-number 64512/)).toBeInTheDocument();
    expect(screen.getByText("por usuário #9")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/change-requests/1/approve" && String(c[1]?.body).includes('"decisao":"aprovar"'))).toBe(true);
    });
  });

  it("executor executa (202) e não vê aprovar", async () => {
    ME = { ...ME, role: "executor", username: "executor-ex" };
    crAtual = crDe(2, "aprovado");
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.queryByRole("button", { name: "Aprovar" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Executar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[0] === "/api/v1/change-requests/1/executar" && c[1]?.method === "POST")).toBe(true);
    });
  });

  it("não mostra aprovar/rejeitar para o próprio pedido", async () => {
    crAtual = crDe(1, "aguardando_aprovacao"); // ME.id = 1 é o solicitante
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.queryByRole("button", { name: "Aprovar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rejeitar" })).toBeNull();
  });

  it("exibe l2vc_name (sem #null) na linha Circuito para CR de escopo l2vc", async () => {
    // CR de escopo l2vc: sem circuito, com nome do serviço — regressão do "#null"
    crAtual = { ...crDe(2, "aguardando_aprovacao"), circuit_id: null, escopo: "l2vc", l2vc_id: 1, l2vc_name: "L2VC-0001" };
    renderDetail();
    expect(await screen.findByText("L2VC-0001")).toBeInTheDocument();
    expect(screen.queryByText("#null")).toBeNull();
  });

  it("exibe upstream_name na linha Circuito para CR de escopo upstream", async () => {
    // Mesma regressão do l2vc para a fase 5: o nome do upstream substitui "—"
    crAtual = {
      ...crDe(2, "aguardando_aprovacao"),
      circuit_id: null,
      escopo: "upstream",
      l2vc_id: null,
      l2vc_name: null,
      upstream_id: 7,
      upstream_name: "upstream-tier1",
    };
    renderDetail();
    expect(await screen.findByText("upstream-tier1")).toBeInTheDocument();
    expect(screen.queryByText("#null")).toBeNull();
  });

  it("não mostra rollback/reconciliar para CR de escopo l2vc (circuito mantém)", async () => {
    // parcial é o modo de falha desenhado do L2VC: onde o operador acharia o
    // beco sem saída — os botões são truncados para o escopo l2vc (risco S2-1).
    crAtual = { ...crDe(2, "parcial"), circuit_id: null, escopo: "l2vc", l2vc_id: 1, l2vc_name: "L2VC-0001" };
    const { unmount } = renderDetail();
    expect(await screen.findByText("Change request #1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Gerar rollback" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reconciliar" })).toBeNull();
    unmount();
    // regressão: CR de escopo circuito no mesmo estado continua com os botões
    crAtual = crDe(2, "parcial");
    renderDetail();
    expect(await screen.findByText("Change request #1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerar rollback" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconciliar" })).toBeInTheDocument();
  });
});
