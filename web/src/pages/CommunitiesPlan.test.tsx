import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import CommunitiesPlan from "./CommunitiesPlan";
import { AuthProvider } from "@/auth/auth-context";

const PLANO = {
  asn_principal: 61785,
  asns_anunciados: [{ asn: 61785, papel: "principal" }],
  observacoes: "adotado da coleta do equipamento 1",
  snapshot_id: 7,
  classes: [
    {
      nome: "com-TECMAIS-v4", banda: "cliente", tipo: "tag_produto",
      valor_v4: 3001, valor_v6: 3101, id: 3, notas: null,
      aplicam: ["CUSTOMER-BGP-v4"], testam: ["RouteExportCheck"],
    },
    {
      nome: "com-TRANSITO-FULL", banda: "transito", tipo: "tag_produto",
      valor_v4: 1010, valor_v6: 1010, id: 4, notas: null,
      aplicam: ["ASN6762-V4-IMPORT"], testam: [],
    },
    {
      // Só testada: um portão a recusa e ninguém a aplica — é o outro selo.
      nome: "com-SO-TESTE-v4", banda: "cliente", tipo: "tag_produto",
      valor_v4: 3201, valor_v6: 3201, id: 5, notas: null,
      aplicam: [], testam: ["RouteExportCheck"],
    },
  ],
  instrucoes: [{ nome: "com-BLACKHOLE-DENY", codigo: 666, tipo: "acao_blackhole", id: 9, notas: null }],
  portoes: [
    { nome: "RouteExportCheck", papel: "upstream", afi: "ipv4", padrao: "recusar", aceitas: ["com-TECMAIS-v4"], recusadas: ["com-ONLY-CDN", "com-SO-TESTE-v4"] },
  ],
  alvos: [
    { nome: "MSD-CDN-v4", papel: "transito", codigo_v4: 53062, codigo_v6: 53062, gate_nome: "RouteExportCheck", classe_import: null, parametros: {}, estado: "established" },
  ],
};

const ACHADOS = [
  {
    codigo: "classe_aplicada_nao_testada", severidade: "critico",
    descricao: "61785:3001 (com-TECMAIS-v4) é aplicado e nenhum portão o testa",
    valor: "61785:3001", filtro: "CUSTOMER-BGP-v4", linha: 4586,
    acao: "incluir a classe no portão do papel",
  },
];

/* A validação é a única chamada com dois estados que os testes trocam antes de
   montar a página: em voo (o painel não mediu nada ainda) e falha (não deu para
   ler). Os dois são `false` por padrão, que é a resposta boa. */
let validacaoPendente = false;
let validacaoFalha = false;

/* O `client` volta junto para o teste do refetch que falha: é por ele que a
   consulta é refeita sem desmontar a página, como o `refetchOnWindowFocus`
   faz quando o operador volta para a janela com a API fora. */
function renderPlano() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AuthProvider>
          <CommunitiesPlan />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, client };
}

describe("Comunidades · Plano", () => {
  beforeEach(() => {
    validacaoPendente = false;
    validacaoFalha = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const json = (corpo: unknown) =>
          new Response(JSON.stringify(corpo), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        // `auth/me` responde o usuário, como nos outros testes de página: o
        // `AuthProvider` chama esse caminho na montagem e sem esta linha ele
        // receberia o plano no lugar do usuário.
        if (url === "/api/v1/auth/me")
          return json({ id: 1, username: "boss", role: "administrador", is_active: true, last_login_at: null, created_at: "" });
        if (url.startsWith("/api/v1/communities/plan/validacao")) {
          if (validacaoPendente) return new Promise<Response>(() => {});
          if (validacaoFalha)
            return new Response(JSON.stringify({ detail: "Erro interno." }), {
              status: 500,
              headers: { "Content-Type": "application/json" },
            });
          return json(ACHADOS);
        }
        if (url === "/api/v1/communities/plan") return json(PLANO);
        return new Response("null", { status: 404 });
      }),
    );
  });

  it("mostra o cabeçalho com o ASN principal", async () => {
    renderPlano();
    const cabecalho = await screen.findByRole("region", { name: /cabeçalho/i });
    // O 61785 também está em `asns_anunciados`, então uma asserção no texto da
    // seção inteira passaria com qualquer campo trocado desde que o número
    // batesse: a asserção é no parágrafo do campo, texto exato.
    const linha = within(cabecalho).getByText(/ASN principal/).closest("p");
    expect(linha?.textContent).toBe("ASN principal: 61785");
  });

  it("marca a classe aplicada e não testada", async () => {
    renderPlano();
    // A classe aparece duas vezes na página (tabela de classes e matriz), então
    // a busca é dentro da seção: `getByText` solto acharia as duas e estouraria.
    const secao = await screen.findByRole("region", { name: /classes e instruções/i });
    const linha = within(secao).getByText("com-TRANSITO-FULL").closest("tr");
    expect(linha?.textContent).toContain("não testada");
  });

  it("marca a classe testada e não aplicada", async () => {
    renderPlano();
    const secao = await screen.findByRole("region", { name: /classes e instruções/i });
    const linha = within(secao).getByText("com-SO-TESTE-v4").closest("tr");
    expect(linha?.textContent).toContain("testada e não aplicada");
    expect(within(linha as HTMLElement).getByText("testada e não aplicada")).toHaveClass("badge-warn");
  });

  it("enquanto a validação não chega, o painel não afirma alinhamento", async () => {
    validacaoPendente = true;
    renderPlano();
    const painel = await screen.findByRole("region", { name: /divergências/i });
    // Sem a resposta não há contagem nem frase de vazio: o painel espera.
    expect(within(painel).getByText(/Carregando/)).toBeInTheDocument();
    expect(painel.textContent).not.toContain("(0)");
    expect(painel.textContent).not.toContain("Nenhuma divergência");
  });

  it("quando a validação falha, o painel diz que não pôde ser lida", async () => {
    validacaoFalha = true;
    renderPlano();
    const painel = await screen.findByRole("region", { name: /divergências/i });
    const alerta = await within(painel).findByRole("alert");
    expect(alerta.textContent).toMatch(/^Não foi possível ler a validação/);
    expect(painel.textContent).not.toContain("Nenhuma divergência");
    expect(painel.textContent).not.toContain("(0)");
  });

  it("com a validação lida, o painel conta os achados no título", async () => {
    renderPlano();
    const painel = await screen.findByRole("region", { name: /divergências/i });
    expect(within(painel).getByRole("heading").textContent).toBe("Divergências (1)");
    expect(within(painel).getByText("4586")).toBeInTheDocument();
  });

  it("refetch que falha depois de uma carga boa tira o número do título", async () => {
    const { client } = renderPlano();
    const painel = await screen.findByRole("region", { name: /divergências/i });
    expect(within(painel).getByRole("heading").textContent).toBe("Divergências (1)");

    // A consulta volta falhando com o dado velho ainda no cache: o estado real
    // do refetch falho do TanStack é `{status:"error", isError:true, data:[...]}`,
    // e é o que o `refetchOnWindowFocus` produz sem nenhum caso exótico.
    validacaoFalha = true;
    await client.refetchQueries({ queryKey: ["communities-plan-validacao", null] }).catch(() => undefined);
    const estado = client.getQueryState(["communities-plan-validacao", null]);
    expect(estado?.status).toBe("error");
    expect(estado?.data).toHaveLength(1);

    // O título não pode contar o que o corpo diz não ter lido.
    expect((await within(painel).findByRole("alert")).textContent).toMatch(/^Não foi possível ler a validação/);
    expect(within(painel).getByRole("heading").textContent).toBe("Divergências");
    expect(painel.textContent).not.toContain("(1)");
  });

  it("mostra o painel de divergências com o filtro e a linha", async () => {
    renderPlano();
    // `CUSTOMER-BGP-v4` também é o "quem aplica" de `com-TECMAIS-v4` na tabela
    // de classes — daí a busca ser dentro do painel.
    const painel = await screen.findByRole("region", { name: /divergências/i });
    expect(painel.textContent).toContain("é aplicado e nenhum portão o testa");
    expect(within(painel).getByText("CUSTOMER-BGP-v4")).toBeInTheDocument();
    expect(within(painel).getByText("4586")).toBeInTheDocument();
  });

  it("mostra a matriz classe × papel", async () => {
    renderPlano();
    const matriz = await screen.findByRole("table", { name: /matriz/i });
    expect(within(matriz).getByText("upstream")).toBeInTheDocument();
    // Na linha de `com-TECMAIS-v4` o portão de upstream a aceita; nas outras
    // três células da linha não há portão nenhum daquele papel.
    const linha = within(matriz)
      .getAllByRole("row")
      .find((l) => l.textContent?.startsWith("com-TECMAIS-v4"));
    expect(linha?.textContent).toContain("anunciada");
    expect(linha?.textContent?.match(/não mencionada/g)).toHaveLength(3);
  });
});
