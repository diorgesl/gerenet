import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Discovery, { vazioDaLista } from "./Discovery";

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

// Coleta que existe, mas cuja leitura não entendeu tudo: `aviso` preenchido e
// `snapshot_id` de pé. A lista que vier daqui pode estar incompleta.
const LEITURA_PARCIAL = {
  ...DISCOVERY,
  aviso: "A linha `peer 100.64.10.1 as-number` não foi reconhecida.",
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

// O diff da conferência de fidelidade. A linha de `faltando` é o que a SoT
// mudaria no equipamento (é ela que levanta o gate do aceite); a de
// `nao_gerenciado` é o que a SoT não emite — visível, e sem bloquear. As duas
// moram no MESMO contexto, como no `subinterface` do motor: `description` e
// `mtu` não gateiam nem quando o bloco tem diferença que gateia.
const DIFERENCA_MUDA = {
  contexto: "subinterface",
  sobrando: [],
  faltando: ["vlan-type dot1q vid 1001"],
  nao_gerenciado: ["description CLIENTE-ALFA"],
  explicacao: null,
  exige_ciente: true,
};

const DIFERENCA_SO_NAO_GERENCIADA = {
  contexto: "subinterface",
  sobrando: [],
  faltando: [],
  nao_gerenciado: ["description CLIENTE-ALFA"],
  explicacao: null,
  exige_ciente: false,
};

// A comparação que não pôde ser feita: o motivo mora na `explicacao`, com
// `sobrando`/`faltando` vazios de propósito (nada aqui muda o equipamento).
const DIFERENCA_ENSAIO = {
  contexto: "ensaio",
  sobrando: [],
  faltando: [],
  nao_gerenciado: [],
  explicacao:
    "uma restrição de unicidade recusou o ensaio (reserva já existente, por exemplo): "
    + "sem o ensaio, a comparação com a configuração não pôde ser feita.",
  exige_ciente: false,
};

function mockFetch(
  opts: {
    descoberta?: unknown;
    ignorados?: unknown[];
    /** O que a lista devolve depois do refetch: a linha fantasma já não está lá. */
    ignoradosApos?: unknown[];
    deleteStatus?: number;
    postFalhaPara?: string;
    /** O diff que o `GET /fidelidade` devolve para a revisão aberta. */
    diferencas?: unknown[];
  } = {},
) {
  let leituras = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (corpo: unknown, status = 200) =>
        new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return json(DEVICES);
      if (url.startsWith("/api/v1/discovery/fidelidade")) {
        return json({
          device_id: 1,
          subinterface: "Eth-Trunk127.1001",
          diferencas: opts.diferencas ?? [],
        });
      }
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
        leituras += 1;
        return json(leituras > 1 ? (opts.ignoradosApos ?? opts.ignorados ?? []) : (opts.ignorados ?? []));
      }
      if (url.startsWith("/api/v1/discovery")) return json(opts.descoberta ?? DISCOVERY);
      return json({ detail: "Não encontrado." }, 404);
    }),
  );
}

/** A revisão aberta, com o diff que o `GET /fidelidade` devolve.
 *
 * Com `exigeCiente` a conferência traz uma linha no grupo que muda o
 * equipamento (a que o aceite tem de assumir); sem ele, só o grupo que a SoT
 * não gerencia. Com `ensaio`, a comparação não pôde ser feita. */
function mockFetchComFidelidade({ exigeCiente = false, ensaio = false } = {}) {
  mockFetch({
    diferencas: ensaio
      ? [DIFERENCA_ENSAIO]
      : [exigeCiente ? DIFERENCA_MUDA : DIFERENCA_SO_NAO_GERENCIADA],
  });
}

/** O equipamento de acesso, a porta e o trunk: os campos que a configuração do
 * edge não tem e que a revisão preenche (o `code` já vem sugerido). */
async function preencheAcesso(dialog: HTMLElement) {
  await userEvent.selectOptions(
    within(dialog).getByRole("combobox", { name: /Equipamento de acesso/ }),
    "1",
  );
  await userEvent.type(within(dialog).getByRole("textbox", { name: /Porta de acesso/ }), "GE0/0/1");
  await userEvent.type(within(dialog).getByRole("textbox", { name: /Trunk do edge/ }), "Eth-Trunk127");
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
    expect(await screen.findByRole("status")).toHaveTextContent("1 peer foi para a lista de ignorados.");
  });

  it("no enlace dual o botão retira os dois peers e o diálogo nomeia os dois", async () => {
    mockFetch({ descoberta: DUAS_FAMILIAS });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Não adotar" }));
    expect(
      screen.getByText("Saem da lista: 100.64.10.1 (ipv4), 2804:194c::1 (ipv6)."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("status")).toHaveTextContent("2 peers foram para a lista de ignorados.");
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

  it("fechar o diálogo não leva o relato da falha embora", async () => {
    mockFetch({ descoberta: DUAS_FAMILIAS, postFalhaPara: "2804:194c::1" });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Não adotar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    // Escape durante a sequência (o pedido ainda não voltou) e depois o desfecho:
    await userEvent.keyboard("{Escape}");
    expect(await screen.findByRole("alert")).toHaveTextContent(/1 de 2 peers foram ignorados/);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a falha no primeiro POST diz que nenhum peer saiu", async () => {
    mockFetch({ descoberta: DUAS_FAMILIAS, postFalhaPara: "100.64.10.1" });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Não adotar" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Nenhum peer saiu da lista: .*100\.64\.10\.1 não pôde ser ignorado\./,
    );
    // A sequência para no primeiro erro: o segundo candidato nem é tentado.
    expect(chamadas().filter((c) => c[1]?.method === "POST")).toHaveLength(1);
  });

  it("sem coleta não afirma que não há peer", async () => {
    mockFetch({ descoberta: SEM_COLETA });
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByText(SEM_COLETA.aviso)).toBeInTheDocument();
    expect(screen.getByText("Sem coleta com a configuração salva — não há o que comparar.")).toBeInTheDocument();
    expect(screen.queryByText("Nenhum peer fora da SoT neste equipamento.")).not.toBeInTheDocument();
  });

  it("leitura parcial mostra o aviso sem esconder a lista", async () => {
    mockFetch({ descoberta: LEITURA_PARCIAL });
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByText(LEITURA_PARCIAL.aviso)).toBeInTheDocument();
    expect(screen.getByText("100.64.10.1")).toBeInTheDocument();
  });

  it("leitura parcial sem proposta não conclui que não há peer", async () => {
    mockFetch({ descoberta: { ...LEITURA_PARCIAL, propostas: [] } });
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByText(LEITURA_PARCIAL.aviso)).toBeInTheDocument();
    expect(screen.getByText(/pode estar incompleta/)).toBeInTheDocument();
    expect(screen.queryByText("Nenhum peer fora da SoT neste equipamento.")).not.toBeInTheDocument();
  });

  it("a mensagem de lista vazia não é a de sem dado nenhum", () => {
    // Inalcançável pela tela hoje (a query fica carregando ou dá erro antes de
    // existir este estado), mas a frase de lista vazia é a única das três que
    // afirma o que ninguém leu: sem dado nenhum, ela não pode sair.
    expect(vazioDaLista(undefined)).not.toContain("Nenhum peer fora da SoT");
    expect(vazioDaLista({ ...DISCOVERY, propostas: [] })).toBe(
      "Nenhum peer fora da SoT neste equipamento.",
    );
    expect(vazioDaLista(SEM_COLETA)).toBe("Sem coleta com a configuração salva — não há o que comparar.");
    expect(vazioDaLista({ ...DISCOVERY, propostas: [], aviso: "leitura parcial" })).toBe(
      "A leitura da configuração não entendeu tudo (veja o aviso acima): a lista pode estar incompleta.",
    );
  });

  it("a proposta órfã explica o conflito e não imprime null no título", async () => {
    mockFetch({ descoberta: { ...DISCOVERY, propostas: [ORFA] } });
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByRole("button", { name: "Não adotar" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Detalhes" }));
    expect(screen.getByText("Proposta sem enlace")).toBeInTheDocument();
    expect(screen.getByText(/endereco_sem_subinterface/)).toBeInTheDocument();
  });

  it("o botão Adotar fica habilitado na proposta adotável", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByRole("button", { name: "Adotar" })).toBeEnabled();
  });

  it("a proposta não adotável deixa o Adotar barrado", async () => {
    mockFetch({ descoberta: { ...DISCOVERY, propostas: [ORFA] } });
    renderDiscovery("/discovery?device_id=1");
    // O mesmo enlace cujo "Não adotar" já sai desabilitado: a adoção não é
    // caminho para uma proposta com conflito, e o motivo está em Detalhes.
    expect(await screen.findByRole("button", { name: "Não adotar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Adotar" })).toBeDisabled();
  });

  it("a revisão pede o aceite quando a diferença muda o equipamento", async () => {
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText(/mudariam o equipamento/)).toBeInTheDocument();
    expect(within(dialog).getByText("vlan-type dot1q vid 1001")).toBeInTheDocument();
    // O grupo que não gateia aparece junto, mesmo vindo do mesmo contexto: o
    // que a SoT não gerencia é informação, e a linha não some por haver
    // diferença que gateia no mesmo bloco.
    expect(await within(dialog).findByText(/não gerencia/)).toBeInTheDocument();
    expect(within(dialog).getByText("description CLIENTE-ALFA")).toBeInTheDocument();

    await preencheAcesso(dialog);
    // O trunk entra na conferência, então o diff é refeito com ele: esperar a
    // resposta nova é o que faz a asserção seguinte falar do gate do aceite.
    expect(await within(dialog).findByText(/mudariam o equipamento/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled();

    await userEvent.click(within(dialog).getByLabelText(/ciente/i));
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled();
  });

  it("o que a SoT não gerencia aparece sem pedir aceite", async () => {
    mockFetchComFidelidade();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText(/não gerencia/)).toBeInTheDocument();
    expect(within(dialog).getByText("description CLIENTE-ALFA")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/ciente/i)).not.toBeInTheDocument();

    await preencheAcesso(dialog);
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled();
  });

  it("o ensaio recusado bloqueia o aceite e diz por quê", async () => {
    mockFetchComFidelidade({ ensaio: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    // O motivo mora na `explicacao` — sem ela o operador não sabe o que resolver.
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/não pôde ser feita/);
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/restrição de unicidade/);

    await preencheAcesso(dialog);
    // O trunk entra na conferência, e o diff é refeito com ele: esperar a
    // resposta nova é o que faz a asserção seguinte falar do ensaio, e não do
    // carregamento.
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/não pôde ser feita/);
    // Sem comparação não há aceite que valha (§6): nem o ciente libera — e sem
    // grupo que muda não há sequer o que marcar.
    expect(within(dialog).queryByLabelText(/ciente/i)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled();
  });

  it("voltar a considerar manda a quádrupla e não fica com mensagem órfã", async () => {
    // O 404 diz que a linha da tela já não existe no servidor; a lista refeita
    // prova isso, e o alerta sai junto com ela.
    mockFetch({ ignorados: [IGNORADO], ignoradosApos: [], deleteStatus: 404 });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Voltar a considerar" }));
    const del = chamadas().find((c) => c[1]?.method === "DELETE");
    expect(String(del?.[0])).toContain("device_id=1");
    expect(String(del?.[0])).toContain("afi=ipv4");
    expect(String(del?.[0])).toContain("remote_address=100.64.10.1");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Voltar a considerar" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
