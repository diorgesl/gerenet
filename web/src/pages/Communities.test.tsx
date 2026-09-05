import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Communities from "./Communities";
import { AuthProvider } from "@/auth/auth-context";

const ativa = { id: 1, name: "CUSTOMER1", notes: null, admin_status: true };
const inativa = { id: 2, name: "PEER2", notes: "legado", admin_status: false };

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
});
