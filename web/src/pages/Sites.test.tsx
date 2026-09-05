import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Sites from "./Sites";
import { AuthProvider } from "@/auth/auth-context";

const ativa = { id: 1, name: "SPO", city: "São Paulo", uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true };
const inativa = { id: 2, name: "REC-off", city: "Recife", uf: "PE", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: false };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ ...(url.includes("1") ? ativa : inativa), ...body }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ id: 3, ...body, p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.startsWith("/api/v1/sites")) {
        const comDesativados = new URL(url, "http://localhost").search.includes("include_disabled=true");
        return new Response(JSON.stringify(comDesativados ? [ativa, inativa] : [ativa]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/v1/auth/me")
        return new Response(JSON.stringify({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      return new Response("null", { status: 404 });
    }),
  );
});

function renderSites() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <Sites />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Sites", () => {
  it("lista sites e cria novo pela API", async () => {
    renderSites();
    expect(await screen.findByText("SPO")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Nome \*/), "REC");
    await userEvent.type(screen.getByLabelText(/^Cidade.*\?$/), "Recife");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("REC"))).toBe(true);
    });
  });

  it("usa o perfil do usuário logado para liberar escrita", async () => {
    renderSites();
    expect(await screen.findByText("SPO")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cadastrar" })).toBeInTheDocument();
  });

  it("ver desativados liga include_disabled e mostra o badge de inativo", async () => {
    renderSites();
    expect(await screen.findByText("SPO")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await screen.findByText("REC-off");
    expect(screen.getByText("inativo")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => String(c[0]).includes("include_disabled=true"))).toBe(true);
    });
  });

  it("Reativar dispara PATCH admin_status:true no fluxo de confirmação", async () => {
    renderSites();
    await screen.findByText("SPO");
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await userEvent.click(await screen.findByRole("button", { name: "Reativar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(
        chamadas.some(
          (c) => c[1]?.method === "PATCH" && c[1]?.body && String(c[1].body).includes('"admin_status":true'),
        ),
      ).toBe(true);
    });
  });

  it("Editar preenche o modal, envia PATCH e fecha", async () => {
    renderSites();
    await screen.findByText("SPO");
    await userEvent.click(screen.getByRole("button", { name: "Editar" }));
    const nome = within(screen.getByRole("dialog")).getByLabelText(/^Nome \*/);
    await waitFor(() => expect(nome).toHaveValue("SPO"));
    await userEvent.clear(nome);
    await userEvent.type(nome, "SPO-2");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(
        chamadas.some(
          (c) => c[1]?.method === "PATCH" && c[1]?.body && String(c[1].body).includes("SPO-2"),
        ),
      ).toBe(true);
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
