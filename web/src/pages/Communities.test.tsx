import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Communities from "./Communities";
import { AuthProvider } from "@/auth/auth-context";

const ativa = { id: 1, name: "CUSTOMER1", tipo: "padrao", notes: null, admin_status: true };
const inativa = { id: 2, name: "PEER2", tipo: "informacao", notes: "legado", admin_status: false };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ id: 3, ...body, admin_status: true }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ ...(url.includes("1") ? ativa : inativa), ...body }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.startsWith("/api/v1/communities")) {
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

function renderCommunities() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <Communities />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Communities", () => {
  it("Desativar dispara PATCH admin_status:false no fluxo de confirmação", async () => {
    renderCommunities();
    await screen.findByText("CUSTOMER1");
    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(
        chamadas.some(
          (c) => c[1]?.method === "PATCH" && c[1]?.body && String(c[1].body).includes('"admin_status":false'),
        ),
      ).toBe(true);
    });
  });

  it("ver desativados liga include_disabled e mostra o badge de inativo", async () => {
    renderCommunities();
    await screen.findByText("CUSTOMER1");
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await screen.findByText("PEER2");
    expect(screen.getByText("inativo")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => String(c[0]).includes("include_disabled=true"))).toBe(true);
    });
  });

  it("mostra a coluna Tipo na tabela", async () => {
    renderCommunities();
    await screen.findByText("CUSTOMER1");
    expect(screen.getByRole("columnheader", { name: "Tipo" })).toBeInTheDocument();
    expect(screen.getByText("padrao")).toBeInTheDocument();
  });

  it("cria nova community pelo dialog com name, tipo e notes", async () => {
    renderCommunities();
    await screen.findByText("CUSTOMER1");
    await userEvent.click(screen.getByRole("button", { name: "Nova community" }));
    // textbox por role: getByLabelText colidiria com o aria-label do tooltip de ajuda.
    await userEvent.type(screen.getByRole("textbox", { name: /^Nome \*/ }), "NEWCOM");
    await userEvent.selectOptions(screen.getByLabelText(/^Tipo/), "informacao");
    await userEvent.type(screen.getByRole("textbox", { name: /^Observações/ }), "nota nova");
    await userEvent.click(screen.getByRole("button", { name: "Criar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(
        chamadas.some(
          (c) =>
            c[1]?.method === "POST" &&
            String(c[1].body).includes('"name":"NEWCOM"') &&
            String(c[1].body).includes('"tipo":"informacao"') &&
            String(c[1].body).includes('"notes":"nota nova"'),
        ),
      ).toBe(true);
    });
  });
});
