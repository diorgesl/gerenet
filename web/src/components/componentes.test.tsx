import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "./DataTable";
import { StatusBadge } from "./StatusBadge";
import { SeverityBadge } from "./SeverityBadge";
import { ConfirmDialog } from "./ConfirmDialog";
import { TimeAgo } from "./TimeAgo";
import { MonoCode } from "./MonoCode";
import { FormField } from "./FormField";
import { PageHeader } from "./PageHeader";

describe("kit", () => {
  it("StatusBadge mapeia ok/success/ativo → badge-ok", () => {
    const { container } = render(<StatusBadge estado="success" />);
    expect(container.querySelector(".badge-ok")).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
  });

  it("SeverityBadge critica → danger", () => {
    const { container } = render(<SeverityBadge severidade="critica" />);
    expect(container.querySelector(".badge-danger")).toBeInTheDocument();
  });

  it("DataTable vazio mostra 'Nenhum registro.'", () => {
    render(<DataTable colunas={[{ key: "a", title: "A" }]} linhas={[]} />);
    expect(screen.getByText("Nenhum registro.")).toBeInTheDocument();
  });

  it("DataTable carregando bloqueia linhas", () => {
    render(<DataTable colunas={[{ key: "a", title: "A" }]} linhas={[{ a: 1 }]} carregando />);
    expect(screen.getByText("Carregando…")).toBeInTheDocument();
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });

  it("DataTable com erro mostra alert e não o vazio", () => {
    render(<DataTable colunas={[{ key: "a", title: "A" }]} linhas={[]} erro="Falha ao carregar os registros." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Falha ao carregar os registros.");
    expect(screen.queryByText("Nenhum registro.")).not.toBeInTheDocument();
  });

  it("ConfirmDialog confirma e cancela", async () => {
    const onConfirmar = vi.fn();
    const onCancelar = vi.fn();
    render(
      <ConfirmDialog
        aberto
        titulo="Desativar?"
        mensagem="Desativar este registro?"
        onConfirmar={onConfirmar}
        onCancelar={onCancelar}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(onConfirmar).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(onCancelar).toHaveBeenCalledOnce();
  });

  it("TimeAgo formata idade relativa", () => {
    const ago = new Date(Date.now() - 3600 * 1000).toISOString();
    render(<TimeAgo iso={ago} />);
    expect(screen.getByText("há 1h")).toBeInTheDocument();
  });

  it("MonoCode copia o texto e sinaliza", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(Navigator.prototype, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<MonoCode texto="display version" />);
    await userEvent.click(screen.getByRole("button", { name: "Copiar" }));
    expect(writeText).toHaveBeenCalledWith("display version");
    expect(screen.getByText("Copiado ✓")).toBeInTheDocument();
  });

  it("FormField mostra erro com role alert", () => {
    render(
      <FormField label="Nome" erro="Obrigatório.">
        <input />
      </FormField>,
    );
    expect(screen.getByText("Obrigatório.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("PageHeader mostra título e ações", () => {
    render(<PageHeader titulo="Devices" acoes={<button>Novo</button>} />);
    expect(screen.getByRole("heading", { name: "Devices" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Novo" })).toBeTruthy();
  });
});
