import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";

function AbreEFecha() {
  const [aberto, setAberto] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setAberto(true)}>
        Gatilho
      </button>
      {aberto && (
        <Modal aberto titulo="Teste" onFechar={() => setAberto(false)}>
          <input aria-label="Campo" />
          <button type="button">Ok</button>
        </Modal>
      )}
    </>
  );
}

describe("Modal", () => {
  it("recebe foco no primeiro focusable ao abrir", async () => {
    render(
      <Modal aberto titulo="Teste" onFechar={vi.fn()}>
        <input aria-label="Campo" />
        <button type="button">Ok</button>
      </Modal>,
    );
    await waitFor(() => expect(screen.getByLabelText("Campo")).toHaveFocus());
  });

  it("Escape fecha", async () => {
    const onFechar = vi.fn();
    render(
      <Modal aberto titulo="Teste" onFechar={onFechar}>
        <button type="button">Ok</button>
      </Modal>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("clique no backdrop fecha (e não no conteúdo)", async () => {
    const onFechar = vi.fn();
    const { container } = render(
      <Modal aberto titulo="Teste" onFechar={onFechar}>
        <button type="button">Ok</button>
      </Modal>,
    );
    await userEvent.click(container.querySelector(".dialog-backdrop") as Element);
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("Tab faz trap no dialog", async () => {
    render(
      <Modal aberto titulo="Teste" onFechar={vi.fn()}>
        <input aria-label="Campo" />
        <button type="button">Ok</button>
      </Modal>,
    );
    const campo = screen.getByLabelText("Campo");
    await waitFor(() => expect(campo).toHaveFocus());
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Ok" })).toHaveFocus();
    await userEvent.tab();
    expect(campo).toHaveFocus(); // voltou para o primeiro (trap)
  });

  it("devolve o foco ao gatilho ao fechar", async () => {
    render(<AbreEFecha />);
    await userEvent.click(screen.getByRole("button", { name: "Gatilho" }));
    await waitFor(() => expect(screen.getByLabelText("Campo")).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.getByRole("button", { name: "Gatilho" })).toHaveFocus());
  });
});
