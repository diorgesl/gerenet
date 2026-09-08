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
  return { up, org, criar: vi.fn(), atualizar: vi.fn() };
});

vi.mock("@/api/hooks", () => ({
  useUpstreams: () => ({ data: [ctx.up], isLoading: false, error: null }),
  useOrganizations: () => ({ data: [ctx.org], isLoading: false, error: null }),
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
