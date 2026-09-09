import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Layout } from "./Layout";
import { AuthProvider } from "@/auth/auth-context";

const ME_ADMIN = {
  id: 1,
  username: "boss",
  role: "administrador",
  is_active: true,
  last_login_at: null,
  created_at: "2026-09-04T00:00:00Z",
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/auth/me") {
        return new Response(JSON.stringify(ME_ADMIN), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/auth/logout" && init?.method === "POST") {
        return new Response(null, { status: 204 });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderLayout() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/devices"]}>
          <Routes>
            <Route path="/login" element={<div>login-page</div>} />
            <Route element={<Layout />}>
              <Route path="/devices" element={<div>devices-page</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Layout", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renderiza a nav com item admin e faz logout", async () => {
    mockFetch();
    renderLayout();
    expect(await screen.findByText("Equipamentos")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Gestão" }));
    expect(screen.getByText("Usuários")).toBeInTheDocument();
    expect(screen.getByText("devices-page")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sair" }));
    expect(await screen.findByText("login-page")).toBeInTheDocument();
    const chamada = vi.mocked(fetch).mock.calls.find(
      (c) => String(c[0]) === "/api/v1/auth/logout" && String(c[1]?.method) === "POST",
    );
    expect(chamada).toBeTruthy();
  });

  it("sanfona: abre o grupo do item atual e alterna os demais pelo rótulo", async () => {
    mockFetch();
    renderLayout();
    expect(await screen.findByText("Equipamentos")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Infraestrutura" })).toHaveAttribute("aria-expanded", "true");

    // Outros grupos começam fechados e abrem/fecham pelo rótulo clicável.
    const roteamento = screen.getByRole("button", { name: "Roteamento" });
    expect(roteamento).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Upstreams")).not.toBeVisible();
    await userEvent.click(roteamento);
    expect(roteamento).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Upstreams")).toBeVisible();
    await userEvent.click(roteamento);
    expect(roteamento).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Upstreams")).not.toBeVisible();
  });
});
