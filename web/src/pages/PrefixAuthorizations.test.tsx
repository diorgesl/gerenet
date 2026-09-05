import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, describe, expect, it, vi } from "vitest";
import PrefixAuthorizations from "./PrefixAuthorizations";
import { AuthProvider } from "@/auth/auth-context";

const ME = { id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" };
const org = { id: 1, name: "Cliente A", legal_name: null, kind: "downstream", asn: 64512, irr_as_set: null, notes: null, admin_status: true };
const autorizacao = { id: 1, organization_id: 1, family: "ipv4", prefix: "200.200.1.0/24", origin: "manual", notes: null, admin_status: true };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (init?.method === "POST") return json({ id: 2, ...JSON.parse(String(init.body)), origin: "manual", admin_status: true }, 201);
      if (url === "/api/v1/prefix-authorizations/1" && init?.method === "PATCH") return json({ ...autorizacao, admin_status: false });
      if (url === "/api/v1/prefix-authorizations") return json([autorizacao]);
      if (url === "/api/v1/organizations") return json([org]);
      if (url === "/api/v1/auth/me") return json(ME);
      return new Response("null", { status: 404 });
    }),
  );
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <PrefixAuthorizations />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("PrefixAuthorizations", () => {
  it("lista e cadastra autorização pela API", async () => {
    renderPage();
    expect(await screen.findByText("200.200.1.0/24")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Organização *"), "1");
    await userEvent.type(screen.getByLabelText("Prefixo *"), "200.200.2.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("200.200.2.0/24"))).toBe(true);
    });
  });

  it("desativa com confirmação", async () => {
    renderPage();
    await screen.findByText("200.200.1.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find((c) => c[0] === "/api/v1/prefix-authorizations/1" && c[1]?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(String(patch![1].body))).toEqual({ admin_status: false });
    });
  });

  it("Editar desativa a atual e cria outra com os valores novos", async () => {
    renderPage();
    await screen.findByText("200.200.1.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Editar" }));
    const prefixo = within(screen.getByRole("dialog")).getByLabelText("Prefixo *");
    await waitFor(() => expect(prefixo).toHaveValue("200.200.1.0/24"));
    await userEvent.clear(prefixo);
    await userEvent.type(prefixo, "198.51.100.0/24");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    const chamadas = (fetch as ReturnType<typeof vi.fn>).mock.calls as [
      string,
      RequestInit | undefined,
    ][];
    await waitFor(() => {
      expect(chamadas.some((c) => c[1]?.method === "PATCH" && String(c[1].body).includes("admin_status"))).toBe(true);
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1].body).includes("198.51.100.0/24"))).toBe(true);
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
