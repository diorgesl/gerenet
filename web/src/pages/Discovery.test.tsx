import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Discovery from "./Discovery";

const DEVICES = [{ id: 1, name: "ne8000-01" }];

const CANDIDATO_V4 = {
  device_id: 1,
  vrf: null,
  afi: "ipv4",
  remote_address: "100.64.10.1",
  asn_remote: 64512,
  descricao: "CLIENTE-ALFA",
  snapshot_id: 12,
  classificacao: "downstream",
  motivo: "Sem organização cadastrada para o ASN: classificação não confirmada.",
};

const PROPOSTA = {
  device_id: 1,
  vrf: null,
  subinterface: "Eth-Trunk127.1001",
  vid: 1001,
  stack: "dual",
  vlan_mode: "unica",
  p2p_v4_len: 31,
  qinq: true,
  organizacao_id: null,
  organizacao_sugerida: "CLIENTE-ALFA",
  site_id: 1,
  circuit_code_sugerido: "ADOC-64512-1001",
  vlans: [{ vid: 1001, kind: "vlan", family: null }],
  prefixos: [{ network: "100.64.10.0/31", ponta_local: "inferior" }],
  sessoes: [{ afi: "ipv4", remote_address: "100.64.10.1" }],
  candidatos: [CANDIDATO_V4],
  pendencias: [{ tipo: "organizacao_ausente", descricao: "Cadastre a organização do ASN 64512." }],
  conflitos: [],
  veredito: "adotavel_com_pendencias",
};

const DISCOVERY = {
  device_id: 1,
  snapshot_id: 12,
  aviso: null,
  gerado_em: "2026-09-14T00:00:00Z",
  propostas: [PROPOSTA],
};

// As duas famílias no mesmo enlace: um circuito dual stack, dois candidatos.
const DUAS_FAMILIAS = {
  ...DISCOVERY,
  propostas: [
    {
      ...PROPOSTA,
      candidatos: [CANDIDATO_V4, { ...CANDIDATO_V4, afi: "ipv6", remote_address: "2804:194c::1" }],
    },
  ],
};

const SEM_COLETA = {
  device_id: 1,
  snapshot_id: null,
  aviso: "O equipamento não tem coleta com a configuração salva. Colete antes de descobrir.",
  gerado_em: "2026-09-14T00:00:00Z",
  propostas: [],
};

// Candidato cujo endereço não casa com subinterface nenhuma: a proposta vem sem
// VLAN, sem code e sem candidato — não há peer identificado para ignorar.
const ORFA = {
  ...PROPOSTA,
  subinterface: null,
  vid: null,
  qinq: false,
  circuit_code_sugerido: null,
  candidatos: [],
  pendencias: [],
  conflitos: [
    {
      tipo: "endereco_sem_subinterface",
      descricao: "Nenhuma subinterface do equipamento tem 100.64.10.1 em um par p2p.",
    },
  ],
  veredito: "nao_adotavel",
};

const IGNORADO = {
  id: 7,
  device_id: 1,
  vrf: null,
  afi: "ipv4",
  remote_address: "100.64.10.1",
  motivo: "cliente saiu",
  autor: "admin",
};

function mockFetch(
  opts: { descoberta?: unknown; ignorados?: unknown[]; deleteStatus?: number; postFalhaPara?: string } = {},
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (corpo: unknown, status = 200) =>
        new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return json(DEVICES);
      if (url.startsWith("/api/v1/discovery/ignore")) {
        if (init?.method === "DELETE") {
          return opts.deleteStatus === 404
            ? json({ detail: "O peer 100.64.10.1 não está na lista de ignorados do equipamento 1." }, 404)
            : new Response(null, { status: 204 });
        }
        if (init?.method === "POST") {
          if (opts.postFalhaPara && String(init.body).includes(opts.postFalhaPara)) {
            return json({ detail: `O peer ${opts.postFalhaPara} não pôde ser ignorado.` }, 409);
          }
          return json(IGNORADO, 201);
        }
        return json(opts.ignorados ?? []);
      }
      if (url.startsWith("/api/v1/discovery")) return json(opts.descoberta ?? DISCOVERY);
      return json({ detail: "Não encontrado." }, 404);
    }),
  );
}

function renderDiscovery(entrada: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entrada]}>
        <Discovery />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function chamadas() {
  return vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
}

function corpoDoPost(indice = 0) {
  const posts = chamadas().filter((c) => c[1]?.method === "POST");
  const post = posts[indice];
  if (!post) throw new Error("a página não enviou esse POST.");
  return JSON.parse(String(post[1].body)) as Record<string, unknown>;
}

describe("Discovery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("mostra a proposta com veredito, peer e pendência", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByText("adotavel_com_pendencias")).toBeInTheDocument();
    expect(screen.getByText("100.64.10.1")).toBeInTheDocument();
    expect(screen.getByText("ADOC-64512-1001")).toBeInTheDocument();
    expect(screen.getByText("sim")).toBeInTheDocument(); // a coluna QinQ
    // A pendência mora no detalhe: a lista só diz que ela existe, pelo veredito.
    await userEvent.click(screen.getByRole("button", { name: "Detalhes" }));
    expect(screen.getByText(/Cadastre a organização/)).toBeInTheDocument();
    expect(screen.getByText(/100\.64\.10\.0\/31 \(ponta inferior\)/)).toBeInTheDocument();
  });

  it("sem device_id pede para escolher um equipamento", async () => {
    mockFetch();
    renderDiscovery("/discovery");
    expect(await screen.findByText("Selecione um equipamento.")).toBeInTheDocument();
  });

  it("botão de não adotar chama a API", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Não adotar" }));
    await userEvent.type(screen.getByLabelText(/^Motivo/), "cliente saiu");
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    // O peer sai identificado pela quádrupla inteira: família e VRF do mesmo
    // candidato a que o endereço pertence.
    expect(corpoDoPost()).toMatchObject({
      device_id: 1,
      vrf: null,
      afi: "ipv4",
      remote_address: "100.64.10.1",
      motivo: "cliente saiu",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("1 peer saiu da lista de ignorados.");
  });

  it("no enlace dual o botão retira os dois peers e o diálogo nomeia os dois", async () => {
    mockFetch({ descoberta: DUAS_FAMILIAS });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Não adotar" }));
    expect(
      screen.getByText("Saem da lista: 100.64.10.1 (ipv4), 2804:194c::1 (ipv6)."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("status")).toHaveTextContent("2 peers saíram da lista de ignorados.");
    const posts = chamadas().filter((c) => c[1]?.method === "POST");
    expect(posts).toHaveLength(2);
    expect(corpoDoPost(0)).toMatchObject({ afi: "ipv4", remote_address: "100.64.10.1" });
    expect(corpoDoPost(1)).toMatchObject({ afi: "ipv6", remote_address: "2804:194c::1" });
  });

  it("a falha no meio da sequência diz quantos saíram e não desfaz o que saiu", async () => {
    mockFetch({ descoberta: DUAS_FAMILIAS, postFalhaPara: "2804:194c::1" });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Não adotar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /1 de 2 peers foram ignorados e ficam fora: a operação não é atômica\./,
    );
    // O que saiu continua fora: nada de DELETE de compensação.
    expect(chamadas().filter((c) => c[1]?.method === "DELETE")).toHaveLength(0);
    expect(chamadas().filter((c) => c[1]?.method === "POST")).toHaveLength(2);
  });

  it("sem coleta não afirma que não há peer", async () => {
    mockFetch({ descoberta: SEM_COLETA });
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByText(SEM_COLETA.aviso)).toBeInTheDocument();
    expect(screen.getByText("Sem coleta com a configuração salva — não há o que comparar.")).toBeInTheDocument();
    expect(screen.queryByText("Nenhum peer fora da SoT neste equipamento.")).not.toBeInTheDocument();
  });

  it("a proposta órfã explica o conflito e não imprime null no título", async () => {
    mockFetch({ descoberta: { ...DISCOVERY, propostas: [ORFA] } });
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByRole("button", { name: "Não adotar" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Detalhes" }));
    expect(screen.getByText("Proposta sem enlace")).toBeInTheDocument();
    expect(screen.getByText(/endereco_sem_subinterface/)).toBeInTheDocument();
  });

  it("voltar a considerar manda a quádrupla e o 404 do DELETE aparece", async () => {
    mockFetch({ ignorados: [IGNORADO], deleteStatus: 404 });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Voltar a considerar" }));
    const del = chamadas().find((c) => c[1]?.method === "DELETE");
    expect(String(del?.[0])).toContain("device_id=1");
    expect(String(del?.[0])).toContain("afi=ipv4");
    expect(String(del?.[0])).toContain("remote_address=100.64.10.1");
    expect(await screen.findByRole("alert")).toHaveTextContent(/não está na lista de ignorados/);
  });
});
