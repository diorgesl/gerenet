import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Devices from "./Devices";
import { AuthProvider } from "@/auth/auth-context";

const equipamentos = [
  {
    id: 1,
    name: "ne8000-01",
    management_address: "10.99.0.1",
    site_id: 1,
    role: "core",
    comm_status: "ok",
    last_collected_at: null,
    admin_status: true,
  },
];
const sites = [{ id: 1, name: "SPO", city: null, uf: "SP", p2p_ipv4_block: null, p2p_ipv6_base: null, admin_status: true }];

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        if (url === "/api/v1/devices/1/collect") {
          return new Response(JSON.stringify({ queued: true, message: "Coleta enfileirada.", job_id: "rq-abc" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({ id: 2, ...body, site_id: null, comm_status: "unknown", last_collected_at: null, admin_status: true }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url === "/api/v1/devices/1" && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ...equipamentos[0], admin_status: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/v1/devices") {
        return new Response(JSON.stringify(equipamentos), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/sites") {
        return new Response(JSON.stringify(sites), { status: 200, headers: { "Content-Type": "application/json" } });
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

function renderDevices() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/devices"]}>
        <AuthProvider>
          <Routes>
            <Route path="/devices" element={<Devices />} />
            <Route path="/jobs" element={<div>jobs-page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Devices", () => {
  it("lista equipamentos e cadastra novo pela API", async () => {
    renderDevices();
    expect(await screen.findByText("ne8000-01")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Nome \*/), "ne8000-02");
    await userEvent.type(screen.getByLabelText(/^IP de gestão \*/), "10.99.0.2");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("ne8000-02"))).toBe(true);
    });
  });

  it("Coletar agora dispara a coleta e navega para /jobs com o device", async () => {
    renderDevices();
    await screen.findByText("ne8000-01");
    await userEvent.click(screen.getByRole("button", { name: "Coletar agora" }));
    expect(await screen.findByText("jobs-page")).toBeInTheDocument();
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls;
      expect(chamadas.some((c) => c[0] === "/api/v1/devices/1/collect" && c[1]?.method === "POST")).toBe(true);
    });
  });

  it("Desativar pede confirmação e envia PATCH admin_status:false", async () => {
    renderDevices();
    await screen.findByText("ne8000-01");
    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    expect(screen.getByRole("dialog", { name: "Desativar ne8000-01?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => {
      const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
      const patch = chamadas.find((c) => c[0] === "/api/v1/devices/1" && c[1]?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(String(patch![1].body))).toEqual({ admin_status: false });
    });
  });
});
