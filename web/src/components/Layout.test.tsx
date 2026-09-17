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

/** `entrada` é a rota montada: `/communities` e `/communities/plan` existem aqui
 * porque uma é prefixo da outra, que é o caso que o item ativo tem de resolver. */
function renderLayout(entrada = "/devices") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={[entrada]}>
          <Routes>
            <Route path="/login" element={<div>login-page</div>} />
            <Route element={<Layout />}>
              <Route path="/devices" element={<div>devices-page</div>} />
              <Route path="/communities" element={<div>communities-page</div>} />
              <Route path="/communities/plan" element={<div>communities-plan-page</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

/** O `active` é a classe que o `NavLink` do react-router põe em todo item que
 * casa com a rota, e é ela que a folha de estilo transforma no item aceso. */
function linksAtivos() {
  return screen.getAllByRole("link").filter((a) => a.classList.contains("active"));
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

  it("em /communities/plan o item atual é o casamento mais longo, e não o prefixo", async () => {
    mockFetch();
    renderLayout("/communities/plan");
    // O grupo do item atual abre sozinho, então o item fica visível sem clique.
    expect(await screen.findByText("Comunidades · Plano")).toBeInTheDocument();

    // O breadcrumb nomeia o item, e não o `/communities` que também casa por prefixo.
    expect(screen.getByText("Roteamento / Comunidades · Plano")).toBeInTheDocument();
    const ativos = linksAtivos();
    expect(ativos).toHaveLength(1);
    expect(ativos[0]).toHaveTextContent("Comunidades · Plano");
  });

  it("em /communities o breadcrumb é o do catálogo, com um ativo só", async () => {
    mockFetch();
    renderLayout("/communities");
    expect(await screen.findByText("Communities")).toBeInTheDocument();
    expect(screen.getByText("Roteamento / Communities")).toBeInTheDocument();
    const ativos = linksAtivos();
    expect(ativos).toHaveLength(1);
    expect(ativos[0]).toHaveTextContent("Communities");
  });
});
