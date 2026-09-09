import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import CredentialGroups from "./CredentialGroups";
import { AuthProvider } from "@/auth/auth-context";

const grupos = [
  {
    id: 1,
    name: "automacao",
    kind: "tacacs_password",
    vault_path: "gerenet/credential-groups/automacao",
    admin_status: true,
  },
];

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 2, ...body, admin_status: true }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ ...grupos[0], admin_status: body.admin_status ?? grupos[0].admin_status }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/v1/credential-groups") {
        return new Response(JSON.stringify(grupos), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/auth/me") {
        return new Response(
          JSON.stringify({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response("null", { status: 404 });
    }),
  );
});

function renderPagina() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/credential-groups"]}>
        <AuthProvider>
          <CredentialGroups />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CredentialGroups", () => {
  it("lista grupos e cadastra novo pela API", async () => {
    renderPagina();
    await waitFor(() => expect(screen.getByText("automacao")).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText(/^Nome \*/), "backup");
    await userEvent.type(screen.getByLabelText(/^Caminho no Vault \*/), "gerenet/credential-groups/backup");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));

    await waitFor(() =>
      expect(screen.getByLabelText(/^Nome \*/)).toHaveValue(""),
    );
  });

  it("desativa grupo com confirmação", async () => {
    renderPagina();
    await waitFor(() => expect(screen.getByText("automacao")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    expect(screen.getByRole("dialog", { name: "Desativar automacao?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find((c) => c[0] === "/api/v1/credential-groups/1" && c[1]?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(String(patch![1].body))).toEqual({ admin_status: false });
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
