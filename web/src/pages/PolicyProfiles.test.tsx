import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import PolicyProfiles from "./PolicyProfiles";
import { AuthProvider } from "@/auth/auth-context";

const ativo = { id: 1, name: "TRANSITO-IMPORT", label: "trânsito", direction: "import", kind: "produto", prefixes: null, notes: null, admin_status: true };
const inativo = { id: 2, name: "FULL-OFF", label: "full", direction: "export", kind: "produto", prefixes: ["10.0.0.0/8"], notes: "legado", admin_status: false };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ ...(url.includes("1") ? ativo : inativo), ...body }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.startsWith("/api/v1/policy-profiles")) {
        const comDesativados = new URL(url, "http://localhost").search.includes("include_disabled=true");
        return new Response(JSON.stringify(comDesativados ? [ativo, inativo] : [ativo]), {
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

function renderPolicyProfiles() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <PolicyProfiles />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PolicyProfiles", () => {
  it("Desativar dispara PATCH admin_status:false no fluxo de confirmação", async () => {
    renderPolicyProfiles();
    await screen.findByText("TRANSITO-IMPORT");
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
    renderPolicyProfiles();
    await screen.findByText("TRANSITO-IMPORT");
    await userEvent.click(screen.getByLabelText("Ver desativados"));
    await screen.findByText("FULL-OFF");
    expect(screen.getByText("inativo")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => String(c[0]).includes("include_disabled=true"))).toBe(true);
    });
  });
});
