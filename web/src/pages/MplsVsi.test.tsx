import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MplsVsi from "./MplsVsi";

vi.mock("@/api/hooks", () => ({
  useVsi: () => ({ data: [
    { id: 1, vrp_name: "VSI-VSI-API-550", vsi_id: 550, name: "vsi api", admin_status: true },
  ], isLoading: false, error: null }),
}));
vi.mock("@/auth/auth-context", () => ({ useAuth: () => ({ podeEscrever: true, ehAdmin: false }) }));

describe("MplsVsi", () => {
  it("lista VSIs mostrando o vrp_name", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><MplsVsi /></MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("VSI-VSI-API-550")).toBeInTheDocument();
  });
});
