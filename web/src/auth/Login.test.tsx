import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Login from "./Login";
import { AuthProvider } from "./auth-context";

// mock do /auth/me (carregando→null) para o provider não explodir
beforeAll(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/v1/auth/me") return new Response("null", { status: 401 });
    return new Response(JSON.stringify({ detail: "Usuário ou senha inválidos." }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }));
});

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Login />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("Login", () => {
  it("mostra erro único para credenciais inválidas", async () => {
    renderLogin();
    await userEvent.type(screen.getByLabelText("Usuário"), "boss");
    await userEvent.type(screen.getByLabelText("Senha"), "errada");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Usuário ou senha inválidos.");
  });

  it("não registra a senha em lugar nenhum (sem campos de senha persistidos)", async () => {
    renderLogin();
    const senha = screen.getByLabelText("Senha") as HTMLInputElement;
    await userEvent.type(senha, "segredo123");
    expect(senha.value).toBe("segredo123");
    // garantia: nada em localStorage/sessionStorage
    expect(localStorage.getItem("gerenet")).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });
});
