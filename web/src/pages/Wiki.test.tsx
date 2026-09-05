import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Wiki from "./Wiki";

const INDICE = [
  { slug: "index", titulo: "Visão geral", secao: "Começando", order: 1, em_breve: false },
  { slug: "mpls", titulo: "Serviços MPLS", secao: "Em breve", order: 2, em_breve: true },
];
const PAGINA_INDEX = {
  slug: "index",
  titulo: "Visão geral",
  em_breve: false,
  html: '<h1>Visão geral</h1><p>Olá.</p><p><a href="/wiki/mpls">Ler sobre MPLS</a></p>',
};
const PAGINA_MPLS = { slug: "mpls", titulo: "Serviços MPLS", em_breve: true, html: "<h1>Serviços MPLS</h1>" };

beforeAll(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/wiki") {
        return new Response(JSON.stringify(INDICE), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/wiki/index") {
        return new Response(JSON.stringify(PAGINA_INDEX), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/wiki/mpls") {
        return new Response(JSON.stringify(PAGINA_MPLS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response("null", { status: 404 });
    }),
  );
});

function renderWiki(initial: string = "/wiki") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/wiki/:slug?" element={<Wiki />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Wiki", () => {
  it("renderiza o índice (Visão geral) sem slug", async () => {
    renderWiki();
    expect(await screen.findByRole("heading", { name: "Visão geral" })).toBeInTheDocument();
    // "Serviços MPLS" é link da barra lateral (com sufixo "(em breve)"); o h1 do índice é o único heading
    expect(screen.getByRole("link", { name: /Serviços MPLS/ })).toBeInTheDocument();
  });

  it("navega pelo link da barra lateral sem reload", async () => {
    const user = userEvent.setup();
    renderWiki();
    await user.click(await screen.findByRole("link", { name: /Serviços MPLS/ }));
    expect(await screen.findByRole("heading", { name: "Serviços MPLS" })).toBeInTheDocument();
  });

  it("navega por link interno do HTML sem reload", async () => {
    const user = userEvent.setup();
    renderWiki();
    await user.click(await screen.findByRole("link", { name: "Ler sobre MPLS" }));
    expect(await screen.findByRole("heading", { name: "Serviços MPLS" })).toBeInTheDocument();
  });

  it("mostra estado de página não encontrada com link de volta", async () => {
    renderWiki("/wiki/nao-existe");
    expect(await screen.findByText(/Página não encontrada/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voltar ao índice" })).toBeInTheDocument();
  });
});
