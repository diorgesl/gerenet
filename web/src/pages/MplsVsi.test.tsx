import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import MplsVsi from "./MplsVsi";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
// O papel define `podeEscrever` no AuthProvider; os testes que precisam de um
// visualizador trocam o valor antes do render.
let papel = "administrador";
// Status de erro forçado no POST de cadastro (0 = sucesso).
let erroNoPost = 0;
const dom = { id: 7, name: "POP-SPO", description: null, admin_status: true, members: [] };
const dev1 = { id: 1, name: "sw-01" };
const dev2 = { id: 2, name: "sw-02" };
const vsi = {
  id: 1, vrp_name: "VSI-VSI-API-550", vsi_id: 550, name: "vsi api", domain_id: 7, domain_name: "POP-SPO",
  admin_status: true, operational_status: "up", mtu: 1500, flow_label: false, description: null,
  endpoints: [
    { device_id: 1, device_name: "sw-01", interface: "Vlanif550", vid: 550, mtu: 1500, operational_status: "up" },
    { device_id: 2, device_name: "sw-02", interface: "Vlanif550", vid: 550, mtu: 1500, operational_status: "down" },
  ],
};

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (corpo: unknown, status = 200) =>
        new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
      if (init?.method === "POST" && url === "/api/v1/mpls/vsi") {
        if (erroNoPost) return json({ detail: "VSI-ID 600 já existe no domínio POP-SPO." }, erroNoPost);
        return json({ ...vsi, ...JSON.parse(String(init.body)) }, 201);
      }
      if (url === "/api/v1/mpls/vsi") return json([vsi]);
      if (url === "/api/v1/mpls/domains") return json([dom]);
      if (url === "/api/v1/devices") return json([dev1, dev2]);
      if (url === "/api/v1/auth/me") return json({ ...ME, role: papel });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderVsi() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/mpls/vsi"]}>
        <AuthProvider>
          <Routes>
            <Route path="/mpls/vsi" element={<MplsVsi />} />
            <Route path="/mpls/vsi/:id" element={<div>detail-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MplsVsi", () => {
  beforeEach(() => {
    papel = "administrador";
    erroNoPost = 0;
    // O stub é instalado uma vez: sem limpar, as chamadas acumulam entre os
    // testes e um `find` de POST acha o corpo do teste anterior.
    vi.mocked(fetch).mockClear();
  });

  it("lista VSIs mostrando o vrp_name e a contagem de PEs", async () => {
    renderVsi();
    expect(await screen.findByText("VSI-VSI-API-550")).toBeInTheDocument();
    expect(screen.getByText("PEs")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("oferece o cadastro para quem pode escrever", async () => {
    renderVsi();
    expect(await screen.findByRole("button", { name: "Novo VSI" })).toBeInTheDocument();
  });

  it("esconde o cadastro de quem só visualiza", async () => {
    papel = "visualizador";
    renderVsi();
    expect(await screen.findByText("VSI-VSI-API-550")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Novo VSI" })).not.toBeInTheDocument();
  });

  it("abre o modal de cadastro com os campos do serviço e uma ponta", async () => {
    renderVsi();
    await userEvent.click(await screen.findByRole("button", { name: "Novo VSI" }));
    expect(screen.getByRole("dialog", { name: "Novo VSI" })).toBeInTheDocument();
    // `selector` desambigua: o `aria-label` do tooltip do FormField começa com a
    // mesma palavra do rótulo (ex.: "Domínio MPLS do serviço…").
    expect(screen.getByLabelText(/^Domínio/, { selector: "select" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Nome/, { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^VSI-ID/, { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^MTU do serviço/, { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Descrição/, { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Flow-label/, { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Equipamento/, { selector: "select" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adicionar PE" })).toBeInTheDocument();
  });

  it("cadastra o VSI com o serviço e as pontas preenchidas", async () => {
    renderVsi();
    await userEvent.click(await screen.findByRole("button", { name: "Novo VSI" }));
    await userEvent.selectOptions(screen.getByLabelText(/^Domínio/, { selector: "select" }), "7");
    await userEvent.type(screen.getByLabelText(/^Nome/, { selector: "input" }), "VSI-NOVO");
    await userEvent.type(screen.getByLabelText(/^VSI-ID/, { selector: "input" }), "600");
    await userEvent.selectOptions(screen.getByLabelText(/^Equipamento/, { selector: "select" }), "1");
    await userEvent.type(screen.getByLabelText(/^VID/, { selector: "input" }), "600");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));

    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const post = chamadas.find((c) => c[0] === "/api/v1/mpls/vsi" && c[1]?.method === "POST");
      expect(post).toBeDefined();
      expect(JSON.parse(String(post![1].body))).toMatchObject({
        domain_id: 7,
        name: "VSI-NOVO",
        vsi_id: 600,
        mtu: 1500,
        flow_label: false,
        endpoints: [{ device_id: 1, vid: 600 }],
      });
    });
  });

  it("cadastra com mais de um PE quando se adiciona uma ponta", async () => {
    renderVsi();
    await userEvent.click(await screen.findByRole("button", { name: "Novo VSI" }));
    await userEvent.selectOptions(screen.getByLabelText(/^Domínio/, { selector: "select" }), "7");
    await userEvent.type(screen.getByLabelText(/^Nome/, { selector: "input" }), "VSI-MULTI");
    await userEvent.selectOptions(screen.getByLabelText(/^Equipamento/, { selector: "select" }), "1");
    await userEvent.type(screen.getByLabelText(/^VID/, { selector: "input" }), "600");

    await userEvent.click(screen.getByRole("button", { name: "Adicionar PE" }));
    const equipamentos = screen.getAllByLabelText(/^Equipamento/, { selector: "select" });
    expect(equipamentos).toHaveLength(2);
    await userEvent.selectOptions(equipamentos[1], "2");
    await userEvent.type(screen.getAllByLabelText(/^VID/, { selector: "input" })[1], "601");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));

    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const post = chamadas.find((c) => c[0] === "/api/v1/mpls/vsi" && c[1]?.method === "POST");
      expect(post).toBeDefined();
      expect(JSON.parse(String(post![1].body))).toMatchObject({
        endpoints: [{ device_id: 1, vid: 600 }, { device_id: 2, vid: 601 }],
      });
    });
  });

  it("mostra o erro da API quando o cadastro é recusado", async () => {
    erroNoPost = 409;
    renderVsi();
    await userEvent.click(await screen.findByRole("button", { name: "Novo VSI" }));
    await userEvent.selectOptions(screen.getByLabelText(/^Domínio/, { selector: "select" }), "7");
    await userEvent.type(screen.getByLabelText(/^Nome/, { selector: "input" }), "VSI-DUP");
    await userEvent.selectOptions(screen.getByLabelText(/^Equipamento/, { selector: "select" }), "1");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("já existe no domínio POP-SPO");
    // O modal continua aberto para o operador corrigir o que enviou.
    expect(screen.getByRole("dialog", { name: "Novo VSI" })).toBeInTheDocument();
  });

  it("não deixa remover a última ponta", async () => {
    renderVsi();
    await userEvent.click(await screen.findByRole("button", { name: "Novo VSI" }));
    expect(screen.getByRole("button", { name: "Remover PE" })).toBeDisabled();
  });

  it("avisa que o provisionamento exige dois PEs", async () => {
    renderVsi();
    await userEvent.click(await screen.findByRole("button", { name: "Novo VSI" }));
    expect(
      screen.getByText("O cadastro aceita um PE; o provisionamento exige dois ou mais."),
    ).toBeInTheDocument();
  });

  it("remove uma ponta adicionada e mantém a primeira no cadastro", async () => {
    renderVsi();
    await userEvent.click(await screen.findByRole("button", { name: "Novo VSI" }));
    await userEvent.selectOptions(screen.getByLabelText(/^Domínio/, { selector: "select" }), "7");
    await userEvent.type(screen.getByLabelText(/^Nome/, { selector: "input" }), "VSI-REMOVE");
    await userEvent.selectOptions(screen.getByLabelText(/^Equipamento/, { selector: "select" }), "1");
    await userEvent.click(screen.getByRole("button", { name: "Adicionar PE" }));
    await userEvent.selectOptions(screen.getAllByLabelText(/^Equipamento/, { selector: "select" })[1], "2");

    await userEvent.click(screen.getAllByRole("button", { name: "Remover PE" })[1]);
    expect(screen.getAllByLabelText(/^Equipamento/, { selector: "select" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));

    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const post = chamadas.find((c) => c[0] === "/api/v1/mpls/vsi" && c[1]?.method === "POST");
      expect(post).toBeDefined();
      expect(JSON.parse(String(post![1].body))).toMatchObject({
        name: "VSI-REMOVE",
        endpoints: [{ device_id: 1 }],
      });
    });
  });
});
