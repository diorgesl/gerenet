import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Upstreams from "./Upstreams";

const ctx = vi.hoisted(() => {
  const up = {
    id: 1,
    name: "transito-01",
    tipo: "transito",
    capacity: "10 Gbps",
    priority: 1,
    cost: null,
    organization_id: 10,
    expected_prefixes_v4: 1200,
    expected_prefixes_v6: 400,
    max_prefix_margin_pct: 20,
    rpki_enabled: true,
    produto_import: "full",
    entrada_local_preference: null,
    contingencia_local_preference: 90,
    contingencia_prepend: 2,
    contingencia_notes: null,
    admin_status: true,
    organization_kind: "operadora",
    organization_name: "Operadora A",
    created_at: "",
    updated_at: "",
  };
  const org = {
    id: 10,
    name: "Operadora A",
    legal_name: null,
    kind: "operadora",
    asn: 64501,
    irr_as_set: null,
    notes: null,
    admin_status: true,
  };
  // Um site e um equipamento bastam para a seção de acesso: o teste do bloco
  // não escolhe entre opções, só precisa de um valor para cada select.
  const site = { id: 1, name: "SPO", city: "São Paulo", uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true };
  const device = {
    id: 2,
    name: "ne-01",
    management_address: "10.9.0.2",
    site_id: 1,
    family: "NE8000",
    role: "edge",
    admin_status: true,
  };
  return { up, org, site, device, criar: vi.fn(), atualizar: vi.fn() };
});

vi.mock("@/api/hooks", () => ({
  useUpstreams: () => ({ data: [ctx.up], isLoading: false, error: null }),
  useOrganizations: () => ({ data: [ctx.org], isLoading: false, error: null }),
  useSites: () => ({ data: [ctx.site], isLoading: false, error: null }),
  useDevices: () => ({ data: [ctx.device], isLoading: false, error: null }),
  useUpstreamCriar: () => ({ mutateAsync: ctx.criar, isPending: false }),
  useUpstreamAtualizar: () => ({ mutateAsync: ctx.atualizar, isPending: false }),
}));
vi.mock("@/auth/auth-context", () => ({ useAuth: () => ({ podeEscrever: true, ehAdmin: false }) }));

function renderUpstreams() {
  return render(
    <MemoryRouter>
      <Upstreams />
    </MemoryRouter>,
  );
}

describe("Upstreams", () => {
  beforeEach(() => {
    ctx.criar.mockReset();
    ctx.atualizar.mockReset();
    ctx.criar.mockResolvedValue({ id: 2 });
    ctx.atualizar.mockResolvedValue({ id: 1 });
  });

  it("lista upstreams com nome, operadora e tipo", async () => {
    renderUpstreams();
    expect(await screen.findByText("transito-01")).toBeInTheDocument();
    expect(screen.getByText("Operadora A")).toBeInTheDocument();
    expect(screen.getByText("Trânsito")).toBeInTheDocument();
  });

  it("cria upstream pelo dialog", async () => {
    renderUpstreams();
    await screen.findByText("transito-01");
    await userEvent.click(screen.getByRole("button", { name: "Novo upstream" }));
    await userEvent.type(screen.getByLabelText(/^Nome \*/), "ix-02");
    await userEvent.selectOptions(screen.getByLabelText(/^Tipo \*/), "ix");
    await userEvent.selectOptions(screen.getByLabelText(/^Operadora \*/), "10");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      expect(ctx.criar).toHaveBeenCalledWith(
        expect.objectContaining({ name: "ix-02", tipo: "ix", organization_id: 10 }),
      );
    });
  });

  it("edita upstream pelo dialog com o formulário preenchido", async () => {
    renderUpstreams();
    await screen.findByText("transito-01");
    await userEvent.click(screen.getByRole("button", { name: "Editar" }));
    const nome = screen.getByLabelText(/^Nome \*/);
    expect(nome).toHaveValue("transito-01");
    await userEvent.clear(nome);
    await userEvent.type(nome, "transito-01b");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => {
      expect(ctx.atualizar).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1, name: "transito-01b" }),
      );
    });
  });

  // Os obrigatórios da seção de acesso: sem todos eles o submit não sai.
  async function preencherAcesso() {
    await userEvent.click(screen.getByRole("checkbox", { name: /Acesso/ }));
    await userEvent.type(screen.getByLabelText(/^Código do circuito \*/), "CIRC-WEB");
    await userEvent.selectOptions(screen.getByLabelText(/^Site \*/), "1");
    await userEvent.selectOptions(screen.getByLabelText(/^Edge \*/), "2");
    await userEvent.selectOptions(screen.getByLabelText(/^Equipamento de acesso \*/), "2");
    await userEvent.type(screen.getByLabelText(/^Porta de acesso \*/), "GE0/0/9");
  }

  it("manda o bloco de acesso junto do upstream", async () => {
    renderUpstreams();
    await screen.findByText("transito-01");
    await userEvent.click(screen.getByRole("button", { name: "Novo upstream" }));
    await userEvent.type(screen.getByLabelText(/^Nome \*/), "up-web");
    await userEvent.selectOptions(screen.getByLabelText(/^Operadora \*/), "10");
    await userEvent.selectOptions(screen.getByLabelText(/^Tipo de policy/), "parcial");
    // A seção só nasce com a caixa marcada, e é a legenda que dá o nome
    // acessível do `fieldset`.
    expect(screen.queryByRole("group", { name: /Acesso/ })).not.toBeInTheDocument();
    await preencherAcesso();
    expect(screen.getByRole("group", { name: /Acesso/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      expect(ctx.criar).toHaveBeenCalledWith(
        expect.objectContaining({
          produto_import: "parcial",
          circuito: expect.objectContaining({
            code: "CIRC-WEB",
            site_id: 1,
            edge_device_id: 2,
            access_device_id: 2,
            access_port: "GE0/0/9",
          }),
        }),
      );
    });
  });

  it("a edição leva o tipo de policy e não leva o bloco de acesso", async () => {
    renderUpstreams();
    await screen.findByText("transito-01");
    await userEvent.click(screen.getByRole("button", { name: "Editar" }));
    expect(screen.getByLabelText(/^Tipo de policy/)).toHaveValue("full");
    // O acesso é só da criação: o vínculo de um upstream que já existe
    // continua no detalhe.
    expect(screen.queryByRole("group", { name: /Acesso/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => {
      expect(ctx.atualizar).toHaveBeenCalledWith(expect.objectContaining({ id: 1, produto_import: "full" }));
    });
    expect(ctx.atualizar.mock.calls[0][0]).not.toHaveProperty("circuito");
  });

  it("desativa upstream via ConfirmDialog", async () => {
    renderUpstreams();
    await screen.findByText("transito-01");
    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Desativar transito-01?");
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      expect(ctx.atualizar).toHaveBeenCalledWith({ id: 1, admin_status: false });
    });
  });
});
