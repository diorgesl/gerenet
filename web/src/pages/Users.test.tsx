import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Users from "./Users";
import { AuthProvider } from "@/auth/auth-context";

const ME_ADMIN = {
  id: 1,
  username: "boss",
  role: "administrador",
  is_active: true,
  last_login_at: null,
  created_at: "2026-09-04T00:00:00Z",
};

const USUARIOS = [
  ME_ADMIN,
  {
    id: 2,
    username: "operador1",
    role: "operador",
    is_active: true,
    last_login_at: null,
    created_at: "2026-09-04T00:00:00Z",
  },
];

const INATIVO1 = {
  id: 3,
  username: "inativo-1",
  role: "operador",
  is_active: false,
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
      if (url === "/api/v1/users?include_disabled=true") {
        return new Response(JSON.stringify([...USUARIOS, INATIVO1]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/users" && (init?.method === undefined || init.method === "GET")) {
        return new Response(JSON.stringify(USUARIOS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/users/2" && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ...USUARIOS[1], is_active: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderUsers() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <Users />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Users", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lista usuários e a conta própria não tem botão de ativar/desativar", async () => {
    mockFetch();
    renderUsers();
    expect(await screen.findByText("operador1")).toBeTruthy();
    const botoes = screen.getAllByRole("button", { name: /desativar/i });
    expect(botoes).toHaveLength(1);
  });

  it("desativar dispara PATCH is_active:false", async () => {
    mockFetch();
    renderUsers();
    await screen.findByText("operador1");
    await userEvent.click(screen.getAllByRole("button", { name: /desativar/i })[0]);
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find(([u, i]) => u === "/api/v1/users/2" && i.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(String(patch![1].body))).toEqual({ is_active: false });
    });
  });

  it("mostra Reativar para usuário inativo", async () => {
    mockFetch();
    renderUsers();
    await screen.findByText("boss");
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await screen.findByText("inativo-1");
    expect(screen.getByRole("button", { name: "Reativar" })).toBeInTheDocument();
  });
});
