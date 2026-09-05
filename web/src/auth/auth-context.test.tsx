import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, RequireAdmin, RequireAuth } from "./auth-context";

const ME_BASE = {
  id: 1,
  username: "boss",
  is_active: true,
  last_login_at: null,
  created_at: "2026-09-04T00:00:00Z",
};

function mockMe(role: string | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url !== "/api/v1/auth/me") return new Response(null, { status: 404 });
      if (role === null) return new Response(null, { status: 401 });
      return new Response(JSON.stringify({ ...ME_BASE, role }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

describe("RequireAuth/RequireAdmin", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sem sessão, RequireAuth redireciona para /login", async () => {
    mockMe(null);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<RequireAuth><div>seguro</div></RequireAuth>} />
            <Route path="/login" element={<div>pagina-login</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("pagina-login")).toBeTruthy();
    expect(screen.queryByText("seguro")).toBeNull();
  });

  it("RequireAdmin bloqueia perfil não administrador", async () => {
    mockMe("operador");
    render(
      <MemoryRouter>
        <AuthProvider>
          <RequireAdmin><div>conteudo-admin</div></RequireAdmin>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Somente administradores.")).toBeTruthy();
    expect(screen.queryByText("conteudo-admin")).toBeNull();
  });

  it("RequireAdmin libera administrador", async () => {
    mockMe("administrador");
    render(
      <MemoryRouter>
        <AuthProvider>
          <RequireAdmin><div>conteudo-admin</div></RequireAdmin>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("conteudo-admin")).toBeTruthy();
  });
});
