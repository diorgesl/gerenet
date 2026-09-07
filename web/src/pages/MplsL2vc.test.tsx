import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MplsL2vc from "./MplsL2vc";

vi.mock("@/api/hooks", () => ({
  useL2vc: () => ({ data: [
    { id: 1, name: "cliente-acme", vc_id: 800, domain_name: "dom-api",
      admin_status: true, operational_status: "up" },
  ], isLoading: false, error: null }),
  // modal "Novo L2VC": selects de domínio e de devices + mutate de criação
  useMplsDomains: () => ({ data: [{ id: 1, name: "dom-api", admin_status: true }], isLoading: false, error: null }),
  useDevices: () => ({ data: [], isLoading: false, error: null }),
  useL2vcCriar: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock("@/auth/auth-context", () => ({ useAuth: () => ({ podeEscrever: true, ehAdmin: false }) }));

describe("MplsL2vc", () => {
  it("lista serviços com status operacional", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><MplsL2vc /></MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("cliente-acme")).toBeInTheDocument();
    expect(screen.getByText("up")).toBeInTheDocument();
  });
});
