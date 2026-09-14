import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MplsVsi from "./MplsVsi";

// Os ACs vêm de `endpoints` (não de `members`, que saiu do contrato do VsiOut).
vi.mock("@/api/hooks", () => ({
  useVsi: () => ({ data: [
    {
      id: 1, vrp_name: "VSI-VSI-API-550", vsi_id: 550, name: "vsi api", admin_status: true,
      operational_status: "up",
      endpoints: [
        { device_id: 1, device_name: "sw-01", interface: "Vlanif550", vid: 550, mtu: 1500, operational_status: "up" },
        { device_id: 2, device_name: "sw-02", interface: "Vlanif550", vid: 550, mtu: 1500, operational_status: "down" },
      ],
    },
  ], isLoading: false, error: null }),
}));
vi.mock("@/auth/auth-context", () => ({ useAuth: () => ({ podeEscrever: true, ehAdmin: false }) }));

describe("MplsVsi", () => {
  it("lista VSIs mostrando o vrp_name e a contagem de PEs", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><MplsVsi /></MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByText("VSI-VSI-API-550")).toBeInTheDocument();
    expect(screen.getByText("PEs")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
