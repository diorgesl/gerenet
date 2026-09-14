import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MplsVsiDetail from "./MplsVsiDetail";
import { AuthProvider } from "@/auth/auth-context";

let ME: Record<string, unknown>;

// Espelho do `VsiOut` da Task 1: ACs em `endpoints` (Vlanif derivada do VID),
// mais flow_label/description. Nada de `members` — a página lia o campo que
// saiu do contrato e estourava em runtime.
const VSI = {
  id: 3,
  domain_id: 2,
  domain_name: "dom-mpls",
  vsi_id: 550,
  name: "vsi-cliente",
  vrp_name: "VSI-VSI-CLIENTE-550",
  signaling: "ldp",
  mtu: 1500,
  split_horizon: true,
  mac_learning: true,
  mac_limit: null,
  flow_label: true,
  description: "VSI do cliente GALAXIA",
  admin_status: true,
  operational_status: "up",
  last_collected_at: "2026-09-13T10:00:00Z",
  created_at: "2026-09-13T09:00:00Z",
  endpoints: [
    {
      device_id: 1,
      device_name: "sw-01",
      interface: "Vlanif550",
      vid: 550,
      mtu: 1500,
      operational_status: "up",
    },
    {
      device_id: 2,
      device_name: "sw-02",
      interface: "Vlanif551",
      vid: 551,
      mtu: 1400,
      operational_status: "down",
    },
  ],
};

function mockFetch(vsi = VSI, falhaStatus = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/auth/me") {
        return new Response(JSON.stringify(ME), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === `/api/v1/mpls/vsi/${vsi.id}/status` && init?.method === "PATCH") {
        if (falhaStatus) {
          return new Response(
            JSON.stringify({ detail: "VSI desativado não pode ser provisionado." }),
            { status: 409, headers: { "Content-Type": "application/json" } },
          );
        }
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ ...vsi, admin_status: body.admin_status }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === `/api/v1/mpls/vsi/${vsi.id}`) {
        return new Response(JSON.stringify(vsi), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/change-requests" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({
            id: 9, ...body, status: "rascunho", solicitante_id: 1, rollback_de: null,
            created_at: "2026-09-13T10:00:00Z", steps: [], approvals: [],
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/mpls/vsi/3"]}>
        <AuthProvider>
          <Routes>
            <Route path="/mpls/vsi/:id" element={<MplsVsiDetail />} />
            <Route path="/change-requests/:id" element={<div>cr-detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MplsVsiDetail", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    ME = { id: 1, username: "ops", role: "operador", is_active: true, last_login_at: null, created_at: "" };
  });

  it("lista os ACs vindos de endpoints com equipamento, Vlanif, VLAN, MTU e estado", async () => {
    mockFetch();
    renderDetail();

    expect(await screen.findByText("VSI vsi-cliente")).toBeInTheDocument();
    // Cada AC na sua linha, afirmando por CÉLULA: `toHaveTextContent` com
    // string é `includes`, então no escopo da linha a Vlanif ("Vlanif550") já
    // satisfaria a asserção da VLAN e uma coluna ausente (ou VLAN↔MTU
    // trocadas) passaria batido. Ordem das colunas: Equipamento, Vlanif,
    // VLAN, MTU, Estado.
    const linha01 = screen.getByText("sw-01").closest("tr");
    const cels01 = linha01!.querySelectorAll("td");
    expect(cels01).toHaveLength(5);
    expect(cels01[0]).toHaveTextContent("sw-01");
    expect(cels01[1]).toHaveTextContent("Vlanif550");
    expect(cels01[2]).toHaveTextContent("550");
    expect(cels01[3]).toHaveTextContent("1500");
    expect(cels01[4]).toHaveTextContent("up");
    // estado por AC: o down de uma ponta convive com o up do VSI e da outra
    const linha02 = screen.getByText("sw-02").closest("tr");
    const cels02 = linha02!.querySelectorAll("td");
    expect(cels02[1]).toHaveTextContent("Vlanif551");
    expect(cels02[2]).toHaveTextContent("551");
    expect(cels02[3]).toHaveTextContent("1400");
    expect(cels02[4]).toHaveTextContent("down");
  });

  it("mostra flow-label e descrição do serviço", async () => {
    // flow_label falso com os outros dois verdadeiros: pina a linha do
    // flow-label contra um mapeamento trocado para split-horizon/mac-learning
    mockFetch({ ...VSI, flow_label: false });
    renderDetail();

    await screen.findByText("VSI vsi-cliente");
    expect(screen.getByText("VSI do cliente GALAXIA")).toBeInTheDocument();
    expect(screen.getByText("Flow-label").closest("tr")).toHaveTextContent("—");
    expect(screen.getByText("Split-horizon").closest("tr")).toHaveTextContent("Sim");
  });

  it("Solicitar mudança cria CR de escopo vsi e navega para o detalhe da CR", async () => {
    mockFetch();
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Solicitar mudança no VSI" }));
    await userEvent.type(screen.getByLabelText("Motivo *"), "Ativar VSI multiponto");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));

    expect(await screen.findByText("cr-detail-page")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(
        chamadas.some(
          (c) =>
            c[0] === "/api/v1/change-requests" &&
            c[1]?.method === "POST" &&
            String(c[1]?.body).includes('"escopo":"vsi"') &&
            String(c[1]?.body).includes('"vsi_id":3'),
        ),
      ).toBe(true);
    });
  });

  it("desativa o VSI pelo diálogo de confirmação (PATCH status)", async () => {
    mockFetch();
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Desativar" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Desativar vsi-cliente?");
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find((c) => c[0] === "/api/v1/mpls/vsi/3/status" && c[1]?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(String(patch?.[1]?.body)).toContain('"admin_status":false');
    });
  });

  it("reativa um VSI desativado (PATCH status)", async () => {
    mockFetch({ ...VSI, admin_status: false });
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Reativar" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Reativar vsi-cliente?");
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find((c) => c[0] === "/api/v1/mpls/vsi/3/status" && c[1]?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(String(patch?.[1]?.body)).toContain('"admin_status":true');
    });
  });

  it("fecha o diálogo e mostra o erro da página quando o PATCH de status falha", async () => {
    // A mensagem não pode ficar escondida sob o backdrop: o diálogo fecha nos
    // dois caminhos e o erro sai no corpo da página (convenção do CircuitDetail).
    mockFetch(VSI, true);
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Desativar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("VSI desativado não pode ser provisionado.");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("oculta as ações de escrita para o visualizador", async () => {
    ME = { ...ME, role: "visualizador" };
    mockFetch();
    renderDetail();

    await screen.findByText("VSI vsi-cliente");
    expect(screen.queryByRole("button", { name: "Solicitar mudança no VSI" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Desativar" })).toBeNull();
    // a consulta continua visível
    expect(screen.getByText("sw-01")).toBeInTheDocument();
  });
});
