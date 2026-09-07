import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MplsDomains from "./MplsDomains";

vi.mock("@/api/hooks", () => ({
  useMplsDomains: () => ({ data: [
    { id: 1, name: "dom-api", description: "switch do pop", admin_status: true, members: [] },
  ], isLoading: false, error: null }),
  useMplsDomainCriar: () => ({ mutateAsync: vi.fn() }),
  useMplsDomainAtualizar: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMplsMemberAdicionar: () => ({ mutateAsync: vi.fn() }),
  useMplsMemberRemover: () => ({ mutateAsync: vi.fn() }),
  useDevices: () => ({ data: [], isLoading: false, error: null }),
}));
vi.mock("@/auth/auth-context", () => ({ useAuth: () => ({ podeEscrever: true, ehAdmin: false }) }));

describe("MplsDomains", () => {
  it("lista domínios e exibe o botão de novo domínio", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><MplsDomains /></MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("dom-api")).toBeInTheDocument();
    expect(screen.getByText("Novo domínio")).toBeInTheDocument();
  });
});
