import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  // Sem sugestão de velocidade: a leitura não achou `qos car` neste
  // equipamento, e é o campo vazio que os testes da revisão preenchem à mão.
  velocidade_mbps: null,
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

// O enlace empilhado reserva uma S-VLAN (`vlan-type dot1q 0x88a8` no
// equipamento), e o `kind` da reserva é o que diz isso: a coluna QinQ da lista
// diz que há empilhamento, não qual dos dois VIDs é a S-VLAN.
const EMPILHADO = {
  ...DISCOVERY,
  propostas: [{ ...PROPOSTA, vlans: [{ vid: 1001, kind: "s_vlan", family: null }] }],
};

// O dual stack com uma família fora da representação do IPAM: o peer existe no
// equipamento (é candidato, e a revisão tem os campos dele), mas o endereço não
// é nenhuma das duas pontas do par — `ponta_incoerente` no motor —, então não há
// sessão a montar para ela. As duas listas que a tela recebe divergem aqui: os
// candidatos são dois, a sessão é uma.
const PONTA_INCOERENTE = {
  ...DISCOVERY,
  propostas: [
    {
      ...PROPOSTA,
      candidatos: [CANDIDATO_V4, { ...CANDIDATO_V4, afi: "ipv6", remote_address: "2804:194c::9" }],
      conflitos: [
        {
          tipo: "ponta_incoerente",
          descricao: "O endereço 2804:194c::9 está na rede, mas não é uma das duas pontas do par.",
        },
      ],
    },
  ],
};

// Dois enlaces do MESMO equipamento na mesma VLAN: VRFs e portas diferentes
// (`Eth-Trunk127` e `Eth-Trunk200`). O `vid` não distingue os dois — o nome da
// subinterface, que é o que o equipamento tem, distingue.
const MESMO_VID = {
  ...DISCOVERY,
  propostas: [
    { ...PROPOSTA, vrf: "VPNA" },
    {
      ...PROPOSTA,
      vrf: "VPNB",
      subinterface: "Eth-Trunk200.1001",
      circuit_code_sugerido: "ADOC-64511-1001",
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

// A organização desativada entra na lista com o rótulo: uma proposta pode
// apontar para ela, e o seletor precisa da opção para não exibir a primeira
// ("Criar a nova") enquanto o POST manda o id da invisível.
const ORGANIZACAO_DESATIVADA = {
  id: 3,
  name: "CLIENTE-ANTIGO",
  legal_name: null,
  kind: "downstream",
  asn: 64500,
  irr_as_set: null,
  notes: null,
  admin_status: false,
};

const ORGANIZACOES = [
  ORGANIZACAO_DESATIVADA,
  { ...ORGANIZACAO_DESATIVADA, id: 2, name: "CLIENTE-ALFA", asn: 64512, admin_status: true },
];

// O cadastro lido do registro. O segundo bloco já tem dono na SoT: é ele que
// nasce desmarcado e desabilitado na lista da revisão.
const PREFILL = {
  asn: 64512,
  nome: "CLIENTEALFA-AS",
  razao_social: "Cliente Alfa Ltda",
  documento: "13.172.064/0001-11",
  pais: "BR",
  as_set_sugerido: "AS-64512",
  as_sets: ["AS-64512"],
  blocos: [
    { prefix: "203.0.113.0/24", family: "ipv4", fonte: "registro", conflito: null },
    { prefix: "198.51.100.0/24", family: "ipv4", fonte: "registro", conflito: "Cliente Beta" },
  ],
  fontes: { nome: "radb", blocos: "registro" },
  avisos: [],
};

// O perfil que a revisão escolhe: é ele que muda o corpo da política de
// exportação, e é por isso que trocá-lo refaz a conferência.
const PERFIL_EXPORT = {
  id: 5,
  name: "up-full",
  label: "Full (export)",
  direction: "export",
  kind: "export",
  prefixes: null,
  notes: null,
  admin_status: true,
};

const POLICY_PROFILES = [PERFIL_EXPORT];

// O upstream da SoT que a revisão pode vincular (§5.2): o vínculo é por id, e
// o resto dos campos é do cadastro que já existe — por isso o `<select>` os
// pede pelo nome, e não digita nenhum.
const UPSTREAMS = [
  {
    id: 4,
    name: "OPERADORA-ALFA",
    tipo: "transito",
    capacity: null,
    priority: null,
    cost: null,
    organization_id: 5,
    expected_prefixes_v4: null,
    expected_prefixes_v6: null,
    max_prefix_margin_pct: 20,
    rpki_enabled: true,
    entrada_local_preference: null,
    contingencia_local_preference: null,
    contingencia_prepend: null,
    contingencia_notes: null,
    admin_status: true,
    organization_kind: "operadora",
    organization_name: "OPERADORA-ALFA",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  },
];

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

// O diff refeito depois de trocar o perfil de exportação: outra linha no grupo
// que gateia — o corpo da política, que o perfil escolhido decide. O aceite
// marcado sobre o diff anterior não cobre esta.
const DIFERENCA_MUDA_COM_OUTRO_PERFIL = {
  contexto: "policy",
  sobrando: [],
  faltando: ["route-policy RP-64512-EXPORT-V4 permit node 10"],
  nao_gerenciado: [],
  explicacao: null,
  exige_ciente: true,
};

/** A proposta com o nome da política lido no equipamento, em cada família (§4.3).
 *
 * O nome sai da configuração lida (o `_sessao_de` da descoberta o devolve), e a
 * revisão o mostra em cada família: adotar é decidir mantê-lo ou limpá-lo. */
function propostaComPolitica(importRoutePolicy: string) {
  return {
    ...PROPOSTA,
    sessoes: [{ ...PROPOSTA.sessoes[0], import_route_policy: importRoutePolicy }],
  };
}

function mockFetch(
  opts: {
    descoberta?: unknown;
    ignorados?: unknown[];
    /** O que a lista devolve depois do refetch: a linha fantasma já não está lá. */
    ignoradosApos?: unknown[];
    deleteStatus?: number;
    postFalhaPara?: string;
    /** O diff que o `GET /fidelidade` devolve para a revisão aberta. Com
     * `diferencasApos`, a partir da segunda conferência (o diff refeito depois
     * de trocar o perfil ou o trunk). */
    diferencas?: unknown[];
    diferencasApos?: unknown[];
  } = {},
) {
  let leituras = 0;
  let conferencias = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (corpo: unknown, status = 200) =>
        new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return json(DEVICES);
      if (url.startsWith("/api/v1/organizations/prefill")) return json(PREFILL);
      if (url.startsWith("/api/v1/organizations")) {
        // O mock responde conforme o pedido, como o serviço: sem a flag, a lista
        // é a das vivas. Um mock que devolvesse sempre as duas deixaria a
        // asserção do rótulo passar mesmo sem o `include_disabled` na URL.
        const comDesativadas =
          new URL(url, "http://local").searchParams.get("include_disabled") === "true";
        return json(comDesativadas ? ORGANIZACOES : ORGANIZACOES.filter((o) => o.admin_status));
      }
      if (url === "/api/v1/policy-profiles") return json(POLICY_PROFILES);
      if (url.startsWith("/api/v1/upstreams")) return json(UPSTREAMS);
      if (url.startsWith("/api/v1/discovery/fidelidade")) {
        conferencias += 1;
        return json({
          device_id: 1,
          subinterface: "Eth-Trunk127.1001",
          diferencas: (conferencias > 1 ? opts.diferencasApos : undefined) ?? opts.diferencas ?? [],
        });
      }
      if (url === "/api/v1/discovery/adopt") return json({ circuit_id: 9 }, 201);
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
 * não gerencia. Com `ensaio`, a comparação não pôde ser feita. `depois` é o
 * diff das conferências seguintes — o refeito. */
function mockFetchComFidelidade({
  exigeCiente = false,
  ensaio = false,
  depois,
}: { exigeCiente?: boolean; ensaio?: boolean; depois?: unknown[] } = {}) {
  mockFetch({
    diferencas: ensaio
      ? [DIFERENCA_ENSAIO]
      : [exigeCiente ? DIFERENCA_MUDA : DIFERENCA_SO_NAO_GERENCIADA],
    diferencasApos: depois,
  });
}

/** O equipamento de acesso e a porta: os campos que a configuração do edge não
 * tem e que a revisão preenche — o código já vem sugerido e o trunk, derivado
 * do nome da subinterface. */
async function preencheAcesso(dialog: HTMLElement) {
  await userEvent.selectOptions(
    within(dialog).getByRole("combobox", { name: /Equipamento de acesso/ }),
    "1",
  );
  await userEvent.type(within(dialog).getByRole("textbox", { name: /Porta de acesso/ }), "GE0/0/1");
}

/** Os pedidos de conferência já feitos ao servidor (o `GET /fidelidade`). */
function conferencias(): string[] {
  return chamadas()
    .map((c) => String(c[0]))
    .filter((url) => url.startsWith("/api/v1/discovery/fidelidade"));
}

/** Espera uma conferência NOVA — a que ainda não tinha sido pedida.
 *
 * Sem a espera, a asserção seguinte fala do diff anterior: o mock responde
 * igual nas duas, e o teste passaria sem provar nada. O prazo é folgado porque
 * o trunk tem a espera curta antes de entrar na consulta. */
async function esperaConferenciaNova(antes: number) {
  await waitFor(() => expect(conferencias().length).toBeGreaterThan(antes), { timeout: 2000 });
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
    // A espera é o que faz a asserção falar do gate do aceite, e não da
    // conferência em voo (com o diff ainda não respondido o botão fica barrado
    // pelo mesmo motivo).
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled(),
    );

    await userEvent.click(within(dialog).getByLabelText(/ciente/i));
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
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
    // Aguardado como as irmãs: sem a espera a asserção dependeria de a
    // conferência já ter voltado, e é isso que fica no fio sob carga.
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
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
    // Sem comparação não há aceite que valha (§6): nem o ciente libera — e sem
    // grupo que muda não há sequer o que marcar.
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled(),
    );
    expect(within(dialog).queryByLabelText(/ciente/i)).not.toBeInTheDocument();
  });

  it("o trunk sai do nome da subinterface e a conferência já nasce com ele", async () => {
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    // `Eth-Trunk127.1001` → `Eth-Trunk127`, a mesma regra do
    // `_trunk_da_subinterface` do serviço: o campo nasce preenchido e a primeira
    // conferência já é a do trunk certo, sem uma tecla digitada — cada tecla
    // refaria o render do equipamento inteiro no servidor.
    expect(within(dialog).getByRole("textbox", { name: /Trunk do edge/ })).toHaveValue(
      "Eth-Trunk127",
    );
    await waitFor(() => expect(conferencias().length).toBeGreaterThan(0));
    expect(conferencias().every((url) => url.includes("edge_trunk=Eth-Trunk127"))).toBe(true);
  });

  it("trocar o trunk refaz a conferência com o valor novo, sem uma consulta por tecla", async () => {
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(conferencias().length).toBeGreaterThan(0));
    const antes = conferencias().length;

    const campoDoTrunk = within(dialog).getByRole("textbox", { name: /Trunk do edge/ });
    await userEvent.clear(campoDoTrunk);
    await userEvent.type(campoDoTrunk, "Eth-Trunk200");
    // O valor só entra na consulta depois da última tecla: a conferência que
    // chega é a do valor final. O limite é folgado de propósito — a contagem
    // exata depende do relógio da máquina (sem a espera seriam as doze teclas).
    await esperaConferenciaNova(antes);
    expect(conferencias()[conferencias().length - 1]).toContain("edge_trunk=Eth-Trunk200");
    expect(conferencias().length - antes).toBeLessThan(5);
  });

  it("a conferência leva a velocidade digitada para o servidor", async () => {
    // A taxa entra no ensaio: sem ela, o render não emite o `qos car` e a
    // conferência acusaria uma diferença de QoS que a adoção não cria (§7).
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(conferencias().length).toBeGreaterThan(0));
    const antes = conferencias().length;

    await userEvent.type(within(dialog).getByLabelText(/^Velocidade \(Mbps\)/), "1024");

    await esperaConferenciaNova(antes);
    expect(conferencias()[conferencias().length - 1]).toContain("velocidade_mbps=1024");
  });

  it("mudar o código refaz a conferência com a identidade da revisão", async () => {
    // O código entra na descrição da subinterface (§4): mudá-lo muda o que o
    // ensaio produz, e o aceite marcado contra o diff antigo não vale para o
    // novo. A conferência refeita leva a identidade INTEIRA — e não só o campo
    // mexido: o ensaio roda com o que a adoção vai gravar, e um render sem o
    // resto da identidade compara uma configuração que não é a do circuito que
    // nasce.
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    // A velocidade primeiro, e a conferência dela aguardada: assim o que refaz a
    // consulta na segunda metade do teste é o CÓDIGO, e não o número digitado.
    await userEvent.type(within(dialog).getByLabelText(/^Velocidade \(Mbps\)/), "1024");
    await waitFor(
      () => expect(conferencias().some((u) => u.includes("velocidade_mbps=1024"))).toBe(true),
      { timeout: 2000 },
    );
    const antes = conferencias().length;

    const campoDoCodigo = within(dialog).getByRole("textbox", { name: /Código do circuito/ });
    await userEvent.clear(campoDoCodigo);
    await userEvent.type(campoDoCodigo, "CIRC-2");

    await esperaConferenciaNova(antes);
    const nova = conferencias()[conferencias().length - 1];
    expect(nova).toContain("circuit_code=CIRC-2");
    expect(nova).toContain("edge_trunk=Eth-Trunk127");
    expect(nova).toContain("organizacao_nome=CLIENTE-ALFA");
    expect(nova).toContain("velocidade_mbps=1024");

    // A outra metade do par da organização é a id: escolhida uma existente, o
    // ensaio troca o nome por ela — o mesmo par exclusivo que o corpo da adoção
    // monta (o `criarOrg` decide qual dos dois vai).
    const antesDaOrg = conferencias().length;
    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: /Organização/ }),
      "2",
    );
    await esperaConferenciaNova(antesDaOrg);
    const comOrg = conferencias()[conferencias().length - 1];
    expect(comOrg).toContain("organizacao_id=2");
    expect(comOrg).not.toContain("organizacao_nome=");
  });

  it("a velocidade sugerida nasce no campo, e fora da faixa o aceite barra com o motivo", async () => {
    // A sugestão vem do `qos car` que a leitura achou no equipamento (§7): o
    // campo nasce preenchido, e é essa taxa que a adoção grava se ninguém mexer.
    mockFetch({
      descoberta: { ...DISCOVERY, propostas: [{ ...PROPOSTA, velocidade_mbps: 1024 }] },
      diferencas: [DIFERENCA_SO_NAO_GERENCIADA],
    });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    const campo = within(dialog).getByLabelText(/^Velocidade \(Mbps\)/);
    expect(campo).toHaveValue(1024);
    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );

    // Zero é uma taxa que o schema recusa (`> 0`): o campo diz isso em
    // português, em vez de deixar o botão barrado sem motivo.
    await userEvent.clear(campo);
    await userEvent.type(campo, "0");
    expect(
      within(dialog).getByText(/A velocidade aceita de 1 a 100000 Mbps\./),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled(),
    );

    // De volta à faixa, o caminho reabre: quem barrava era a taxa.
    await userEvent.clear(campo);
    await userEvent.type(campo, "2048");
    await waitFor(
      () => expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
      { timeout: 2000 },
    );
  });

  it("a velocidade fora da forma de dígitos barra na tela, e o `0100` continua valendo", async () => {
    // O campo manda o TEXTO cru para a query e o servidor o lê como `int`: `1e3`
    // é literal que o `type="number"` mantém e o `Number()` aceita, mas o `int()`
    // recusa — o gate antigo deixava o Adotar habilitado, o 422 voltava no alerta
    // genérico e o operador ficava sem saber qual campo corrigir (item 18). O
    // gate da forma vem antes do da faixa.
    mockFetchComFidelidade();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    const campo = within(dialog).getByLabelText(/^Velocidade \(Mbps\)/);
    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );

    // `fireEvent.change` e não o `userEvent.type` das outras cenas, de propósito:
    // o `user-event` escreve num `type="number"` pelo `valueAsNumber`, e `1e3`
    // chegaria como `1000` — que é o que o campo NÃO faz. Medido: o `value` cru
    // mantém `1e3`, `1.0` e `0100` (só o intermediário `1e` é que o navegador
    // descarta), e é esse o estado que o operador vê antes do 422.
    fireEvent.change(campo, { target: { value: "1e3" } });
    expect((campo as HTMLInputElement).value).toBe("1e3");
    expect(
      within(dialog).getByText(/A velocidade aceita de 1 a 100000 Mbps\./),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled(),
    );

    // O zero à esquerda continua texto válido, de propósito: `0100` e `100` são a
    // mesma taxa e assinaturas diferentes, e é a grafia digitada que viaja — o
    // conserto é da FORMA, e não uma conversão para número.
    fireEvent.change(campo, { target: { value: "0100" } });
    await waitFor(
      () => expect(conferencias().some((u) => u.includes("velocidade_mbps=0100"))).toBe(true),
      { timeout: 2000 },
    );
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
  });

  it("o aceite não atravessa a espera do trunk: o botão exige a conferência do valor digitado", async () => {
    // A espera do trunk abre a janela que este teste fecha: a tela mostra o diff
    // do valor anterior e o campo já tem o novo. O `ciente` é um booleano sem
    // vínculo com o diff que assumiu, então ele valeria contra o diff velho e o
    // corpo levaria o trunk novo — o servidor recalcula o diff, mas não sabe
    // contra qual deles o aceite foi dado.
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await preencheAcesso(dialog);
    await userEvent.click(await within(dialog).findByLabelText(/ciente/i));
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );

    // A tecla é do operador e a consulta ainda não saiu: o diff na tela é o do
    // trunk anterior, e é só ele que o aceite cobre.
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Trunk do edge/ }), "9");
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled();

    // Chegada a conferência do valor novo, com o mesmo diff, o caminho reabre
    // sem tocar no aceite: a espera não é um diff diferente, e o que o operador
    // marcou continua valendo — zerá-lo aqui pediria a marca de novo a cada
    // tecla do trunk, mesmo quando nada mudou na comparação.
    await waitFor(
      () => expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
      { timeout: 2000 },
    );
    expect(within(dialog).getByLabelText(/ciente/i)).toBeChecked();
  });

  it("trocar o perfil de exportação zera o aceite: o diff é outro", async () => {
    mockFetchComFidelidade({ exigeCiente: true, depois: [DIFERENCA_MUDA_COM_OUTRO_PERFIL] });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await preencheAcesso(dialog);
    await userEvent.click(await within(dialog).findByLabelText(/ciente/i));
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );

    const antes = conferencias().length;
    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: /Perfil de exportação \(ipv4\)/ }),
      "5",
    );
    await esperaConferenciaNova(antes);
    // O corpo da política mudou com o perfil: a linha nova que o aceite
    // assumiria ninguém leu, e o §6 não deixa o "estou ciente" atravessar.
    expect(
      await within(dialog).findByText("route-policy RP-64512-EXPORT-V4 permit node 10"),
    ).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByLabelText(/ciente/i)).not.toBeChecked());
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled();
  });

  it("o Adotar grava a revisão inteira e fecha o diálogo", async () => {
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await preencheAcesso(dialog);
    await userEvent.type(within(dialog).getByLabelText(/^Velocidade \(Mbps\)/), "1024");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: /Caminho do segredo no Vault \(ipv4\)/ }),
      "gerenet/bgp/100.64.10.1",
    );
    await userEvent.click(within(dialog).getByLabelText(/ciente/i));
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    // O corpo é a revisão inteira: a identidade da proposta (a que o serviço
    // confere, e a que faz a revisão de um enlace não valer no outro), o
    // circuito com o acesso, o trunk derivado e a velocidade digitada, a
    // organização nova com o `kind` e o ASN do candidato, a sessão com o caminho
    // do segredo — nunca o valor — e o ciente.
    await waitFor(() =>
      expect(corpoDoPost()).toEqual({
        device_id: 1,
        vrf: null,
        subinterface: "Eth-Trunk127.1001",
        circuit_code: "ADOC-64512-1001",
        access_device_id: 1,
        access_port: "GE0/0/1",
        edge_trunk: "Eth-Trunk127",
        velocidade_mbps: 1024,
        organizacao_id: null,
        organizacao_nova: {
          name: "CLIENTE-ALFA",
          kind: "downstream",
          asn: 64512,
          legal_name: null,
          document: null,
          irr_as_set: null,
        },
        autorizacoes: [],
        sessoes: [
          {
            afi: "ipv4",
            import_profile_id: null,
            export_profile_id: null,
            password_ref: "gerenet/bgp/100.64.10.1",
          },
        ],
        ciente: true,
      }),
    );

    // O diálogo fecha no sucesso: sem isso ficaria aberto sobre uma proposta que
    // já não existe, e o segundo clique responderia 404. O relato do circuito
    // fica na página, como o dos ignorados.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Proposta adotada: o circuito 9 foi gravado na SoT.",
    );
  });

  it("deixa escolher o kind da organização", async () => {
    mockFetch({});
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");

    // O select abre no palpite do `_classificar` (a proposta sem organização
    // sai como "downstream") e é o operador quem decide.
    const kind = within(dialog).getByRole("combobox", { name: /^Tipo de organização/ });
    expect(kind).toHaveValue("downstream");
    // O bloco de upstream só existe no enlace de operadora (§5.1): o campo é
    // consultado pela legenda, que é o nome acessível do `fieldset`.
    expect(within(dialog).queryByRole("group", { name: "Upstream" })).not.toBeInTheDocument();

    await userEvent.selectOptions(kind, "operadora");
    expect(within(dialog).getByRole("group", { name: "Upstream" })).toBeInTheDocument();
  });

  it("mostra o nome da política lido em cada família", async () => {
    mockFetch({
      descoberta: { ...DISCOVERY, propostas: [propostaComPolitica("RP-LIDA-IMPORT")] },
    });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");

    expect(await within(dialog).findByDisplayValue("RP-LIDA-IMPORT")).toBeInTheDocument();
  });

  it("recusa adotar operadora sem o bloco de upstream", async () => {
    mockFetch({});
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");

    // Preenche o que a adoção exige ANTES de escolher a operadora: sem isto o
    // botão já estaria barrado pelo acesso em falta, e o teste não diria nada
    // sobre a guarda do §5.1.
    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );

    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: /^Tipo de organização/ }),
      "operadora",
    );
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled();
    // A frase é a do serviço, e a asserção vai pelo papel porque a DICA do
    // `help("adocao.kind")` também fala do bloco de upstream: um `getByText`
    // casaria as duas e o teste passaria sem a mensagem existir.
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/bloco de upstream/i);
  });

  it("o Adotar manda o bloco do upstream criado e a organização operadora", async () => {
    mockFetch({});
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    const escolhe = (nome: RegExp, valor: string) =>
      userEvent.selectOptions(within(dialog).getByRole("combobox", { name: nome }), valor);

    await escolhe(/^Tipo de organização/, "operadora");
    await escolhe(/^Modo do upstream/, "criar");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: /^Nome do upstream/ }),
      "OPERADORA-BETA",
    );
    await escolhe(/^Tipo do upstream/, "ix");
    await escolhe(/^Tipo de policy/, "parcial");
    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );

    // A conferência roda com o MESMO bloco que a escrita vai gravar (§5.4):
    // sem ele o ensaio renderiza pelo caminho de cliente e acusa diferença em
    // tudo — e o `kind` é o outro lado da mesma moeda (§5.1).
    await waitFor(
      () =>
        expect(
          conferencias().some(
            (url) =>
              url.includes("organizacao_kind=operadora") &&
              url.includes("upstream_tipo=ix") &&
              url.includes("upstream_produto=parcial"),
          ),
        ).toBe(true),
      { timeout: 2000 },
    );

    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));
    await waitFor(() =>
      expect(corpoDoPost()).toMatchObject({
        organizacao_nova: { name: "CLIENTE-ALFA", kind: "operadora", asn: 64512 },
        upstream: {
          name: "OPERADORA-BETA",
          tipo: "ix",
          produto_import: "parcial",
          papel: "principal",
        },
      }),
    );
  });

  it("o vínculo manda só o upstream_id, sem os campos de criação", async () => {
    mockFetch({});
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    const escolhe = (nome: RegExp, valor: string) =>
      userEvent.selectOptions(within(dialog).getByRole("combobox", { name: nome }), valor);

    await escolhe(/^Tipo de organização/, "operadora");
    await escolhe(/^Modo do upstream/, "vincular");
    // O vínculo é por id: o resto é o upstream da SoT, e o serviço recusa os
    // campos de criação junto com ele (`_uma_das_formas`).
    await escolhe(/^Upstream existente/, "4");
    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    await waitFor(() =>
      expect(corpoDoPost().upstream).toEqual({ upstream_id: 4, papel: "principal" }),
    );
  });

  it("limpar o nome lido devolve a sessão ao nome padrão do gerenet", async () => {
    mockFetch({
      descoberta: { ...DISCOVERY, propostas: [propostaComPolitica("RP-LIDA-IMPORT")] },
    });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    const campo = await within(dialog).findByDisplayValue("RP-LIDA-IMPORT");

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Limpar a route-policy de importação (ipv4)" }),
    );
    expect(campo).toHaveValue("");

    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    // Sem o nome no corpo, a sessão nasce com o nome do §25.4: é o "limpar" que
    // devolve o padrão, e não um nome vazio gravado por engano.
    await waitFor(() =>
      expect(corpoDoPost().sessoes).toEqual([
        { afi: "ipv4", import_profile_id: null, export_profile_id: null, password_ref: null },
      ]),
    );
  });

  it("o botão do registro preenche a organização nova e manda só os blocos livres", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");

    await userEvent.click(within(dialog).getByRole("button", { name: "Buscar no registro" }));

    expect(await within(dialog).findByLabelText(/Nome da organização nova/)).toHaveValue(
      "CLIENTEALFA-AS",
    );
    // O `getByLabelText` casa o texto do rótulo inteiro, e o `help` do campo
    // entra nele (a dica e o "?"): o regex é o mesmo caminho dos irmãos com
    // ajuda, como o `Caminho do segredo no Vault (ipv4)`.
    expect(within(dialog).getByLabelText(/^Documento \(CNPJ\/ownerid\)/)).toHaveValue(
      "13.172.064/0001-11",
    );
    // A lista nasce marcada, e o bloco em uso por outra organização nasce
    // desmarcado e desabilitado (§7): o operador vê antes do clique em vez de
    // receber o 409 depois.
    expect(within(dialog).getByLabelText("Incluir 203.0.113.0/24")).toBeChecked();
    const conflitante = within(dialog).getByLabelText("Incluir 198.51.100.0/24");
    expect(conflitante).not.toBeChecked();
    expect(conflitante).toBeDisabled();
    expect(within(dialog).getByText(/em uso por Cliente Beta/)).toBeInTheDocument();

    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    await waitFor(() =>
      expect(corpoDoPost()).toMatchObject({
        organizacao_nova: {
          name: "CLIENTEALFA-AS",
          kind: "downstream",
          asn: 64512,
          document: "13.172.064/0001-11",
          irr_as_set: "AS-64512",
        },
        autorizacoes: [{ prefix: "203.0.113.0/24", family: "ipv4" }],
      }),
    );
  });

  it("desmarcar um bloco do registro tira ele do payload", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Buscar no registro" }));
    await within(dialog).findByLabelText("Incluir 203.0.113.0/24");

    await userEvent.click(within(dialog).getByLabelText("Incluir 203.0.113.0/24"));

    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    await waitFor(() => expect(corpoDoPost().autorizacoes).toEqual([]));
  });

  it("a conferência leva os blocos marcados da revisão, e só eles", async () => {
    // A conferência é o que o operador lê antes de aceitar: sem os blocos o
    // ensaio renderiza o peer sem o filtro de importação e acusa como faltando a
    // linha que a adoção grava — o `ciente` cobrado por uma diferença que a
    // própria tela cria (item 14). A lista é a MESMA do POST, na forma do query
    // string.
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    // Sem bloco nenhum o parâmetro não vai vazio: ele não vai.
    expect(new URL(conferencias().at(-1) ?? "", "http://local").searchParams.getAll(
      "autorizacoes",
    )).toEqual([]);

    const antesDoRegistro = conferencias().length;
    await userEvent.click(within(dialog).getByRole("button", { name: "Buscar no registro" }));
    expect(await within(dialog).findByLabelText("Incluir 203.0.113.0/24")).toBeChecked();

    // Os blocos entram na assinatura que o aceite observa: a consulta é refeita
    // depois da espera, e o diff que volta é o do render com a autorização.
    await esperaConferenciaNova(antesDoRegistro);
    expect(new URL(conferencias().at(-1) ?? "", "http://local").searchParams.getAll(
      "autorizacoes",
    )).toEqual(["ipv4:203.0.113.0/24"]);

    // Desmarcar também refaz: o render do ensaio muda com a lista, então o diff
    // na tela já não é o que o operador leu.
    const antesDeDesmarcar = conferencias().length;
    await userEvent.click(within(dialog).getByLabelText("Incluir 203.0.113.0/24"));
    await esperaConferenciaNova(antesDeDesmarcar);
    expect(new URL(conferencias().at(-1) ?? "", "http://local").searchParams.getAll(
      "autorizacoes",
    )).toEqual([]);
  });

  it("o que será gravado abre pelas reservas e nomeia a S-VLAN", async () => {
    // As reservas são o que a adoção grava sem passar por campo nenhum da tela —
    // não há o que revisar, e sem a lista o operador adota um VID que nunca leu
    // (§6 do design). A S-VLAN é o caso que só existe aqui: a coluna QinQ diz
    // que o enlace empilha, não qual dos VIDs é a S-VLAN.
    mockFetch({ descoberta: EMPILHADO, diferencas: [DIFERENCA_SO_NAO_GERENCIADA] });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");

    const itens = within(dialog).getAllByRole("listitem");
    expect(itens[0]).toHaveTextContent("S-VLAN 1001");
    expect(itens[1]).toHaveTextContent("100.64.10.0/31 (ponta inferior)");
    expect(itens[2]).toHaveTextContent("100.64.10.1 AS64512 (downstream)");
  });

  it("o corpo manda as sessões da proposta, e não uma por candidato", async () => {
    // Quem casa a revisão com o que a leitura entregou é o `_sessao_da_proposta`
    // do serviço, pela família: o payload tem de seguir a lista que essa guarda
    // confere. Com a lista dos candidatos, a família sem sessão — a que o
    // endereço não é nenhuma das duas pontas do par — viajaria como sessão, e o
    // serviço a recusaria inteira ("a revisão não cobre").
    mockFetch({ descoberta: PONTA_INCOERENTE, diferencas: [DIFERENCA_SO_NAO_GERENCIADA] });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await preencheAcesso(dialog);
    await userEvent.click(within(dialog).getByRole("button", { name: "Adotar" }));

    await waitFor(() =>
      expect(corpoDoPost().sessoes).toEqual([
        { afi: "ipv4", import_profile_id: null, export_profile_id: null, password_ref: null },
      ]),
    );
  });

  it("a organização desativada aparece com o rótulo, e não como se a tela criasse a nova", async () => {
    // A proposta aponta para uma organização desativada: sem a opção na lista, o
    // `<select>` exibiria a primeira ("Criar a nova") e o POST mandaria o id da
    // invisível — a tela diria uma coisa e o circuito nasceria em outra.
    mockFetch({
      descoberta: { ...DISCOVERY, propostas: [{ ...PROPOSTA, organizacao_id: 3 }] },
      diferencas: [DIFERENCA_SO_NAO_GERENCIADA],
    });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await waitFor(() =>
      expect(within(dialog).getByRole("combobox", { name: /Organização/ })).toHaveValue("3"),
    );
    expect(
      within(dialog).getByRole("option", { name: "CLIENTE-ANTIGO (AS64500) (desativada)" }),
    ).toBeInTheDocument();
    // Quem traz a opção é o pedido das desativadas. O mock responde conforme o
    // pedido, então as duas metades da verificação (a URL e o rótulo) caem
    // juntas se a flag sair do hook.
    expect(
      chamadas().some(([url]) => String(url) === "/api/v1/organizations?include_disabled=true"),
    ).toBe(true);
  });

  it("o nome da organização nova e a porta fora do padrão barram o aceite na tela", async () => {
    // O peer sem `description` na configuração chega sem nome sugerido: o campo
    // nasce vazio, e o clique não pode sair daqui como o 422 do Pydantic.
    mockFetch({
      descoberta: { ...DISCOVERY, propostas: [{ ...PROPOSTA, organizacao_sugerida: null }] },
      diferencas: [DIFERENCA_SO_NAO_GERENCIADA],
    });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await preencheAcesso(dialog);
    // Todo o resto está preenchido: quem barra é o nome que falta, e o campo diz
    // isso em português.
    expect(within(dialog).getByText("Informe o nome da organização nova.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled();

    await userEvent.type(
      within(dialog).getByRole("textbox", { name: /Nome da organização nova/ }),
      "CLIENTE-BETA",
    );
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );

    // Um ponto não é porta (o padrão do schema é `[A-Za-z0-9/-]`): o campo avisa
    // e o botão volta a barrar, sem 422 em inglês.
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Porta de acesso/ }), ".");
    expect(within(dialog).getByText(/A porta aceita só letras/)).toBeInTheDocument();
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled(),
    );
  });

  it("o valor acima do teto do schema barra o aceite e diz qual é o teto", async () => {
    // Os tetos são os do schema do serviço. Um campo que os passa devolve o 422
    // do Pydantic, em inglês: é o mesmo caso do nome vazio e do ponto na porta,
    // por outra porta de entrada.
    mockFetch({
      descoberta: { ...DISCOVERY, propostas: [{ ...PROPOSTA, organizacao_sugerida: null }] },
      diferencas: [DIFERENCA_SO_NAO_GERENCIADA],
    });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await preencheAcesso(dialog);
    const botao = () => within(dialog).getByRole("button", { name: "Adotar" });
    // A colagem é como um valor comprido chega de verdade (o operador copia da
    // documentação), e uma tecla por vez custaria 129 eventos só no nome.
    const colar = (nome: RegExp, valor: string) =>
      fireEvent.change(within(dialog).getByRole("textbox", { name: nome }), {
        target: { value: valor },
      });

    colar(/Nome da organização nova/, "A".repeat(129));
    expect(
      within(dialog).getByText("O nome da organização aceita até 128 caracteres."),
    ).toBeInTheDocument();
    expect(botao()).toBeDisabled();
    colar(/Nome da organização nova/, "CLIENTE-BETA");
    await waitFor(() => expect(botao()).toBeEnabled());

    colar(/Código do circuito/, "C".repeat(65));
    expect(
      within(dialog).getByText("O código do circuito aceita até 64 caracteres."),
    ).toBeInTheDocument();
    expect(botao()).toBeDisabled();
    colar(/Código do circuito/, "CIRC-1");

    colar(/Caminho do segredo no Vault \(ipv4\)/, "v".repeat(256));
    expect(
      within(dialog).getByText("O caminho do segredo aceita até 255 caracteres."),
    ).toBeInTheDocument();
    expect(botao()).toBeDisabled();
    colar(/Caminho do segredo no Vault \(ipv4\)/, "");
    await waitFor(() => expect(botao()).toBeEnabled());

    // O trunk fecha a lista, e a volta ao valor derivado pode ter de esperar a
    // conferência dele: o `waitFor` cobre a espera do campo.
    colar(/Trunk do edge/, "T".repeat(65));
    expect(
      within(dialog).getByText("O trunk do edge aceita até 64 caracteres."),
    ).toBeInTheDocument();
    expect(botao()).toBeDisabled();
    colar(/Trunk do edge/, "Eth-Trunk127");
    await waitFor(() => expect(botao()).toBeEnabled(), { timeout: 2000 });
  });

  it("a proposta sem ASN remoto não manda ASN sentinela no corpo", async () => {
    // Estado que a listagem não produz — sem ASN remoto o peer é conflito, e a
    // revisão nem abre. O teste é do que não pode sair daqui (como o
    // `vazioDaLista(undefined)` acima): o corpo não leva `asn: 0`, um valor que
    // o serviço recusaria por conta própria. O gate é só da organização NOVA,
    // que é quem precisa do ASN; escolhendo uma existente, ele libera.
    mockFetch({
      descoberta: {
        ...DISCOVERY,
        propostas: [{ ...PROPOSTA, candidatos: [{ ...CANDIDATO_V4, asn_remote: null }] }],
      },
      diferencas: [DIFERENCA_SO_NAO_GERENCIADA],
    });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    const dialog = screen.getByRole("dialog");
    await preencheAcesso(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeDisabled(),
    );

    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: /Organização/ }),
      "2",
    );
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Adotar" })).toBeEnabled(),
    );
  });

  it("trocar de proposta no mesmo vid não herda o formulário da anterior", async () => {
    // A `key` do diálogo é a identidade da revisão, e o `vid` não identifica uma
    // proposta: dois enlaces do mesmo equipamento podem estar na MESMA VLAN
    // (outra VRF, outra porta). Com o vid na frente, o React reaproveita a
    // instância no troco — o código, a porta digitada, o trunk e o aceite da
    // primeira revisão chegariam inteiros sobre a segunda, que é outro enlace.
    mockFetch({ descoberta: MESMO_VID, diferencas: [DIFERENCA_SO_NAO_GERENCIADA] });
    renderDiscovery("/discovery?device_id=1");
    const linhas = await screen.findAllByRole("button", { name: "Adotar" });
    expect(linhas).toHaveLength(2);

    await userEvent.click(linhas[0]);
    const dialog = () => screen.getByRole("dialog");
    expect(within(dialog()).getByRole("textbox", { name: /Código do circuito/ })).toHaveValue(
      "ADOC-64512-1001",
    );
    await userEvent.type(
      within(dialog()).getByRole("textbox", { name: /Porta de acesso/ }),
      "GE0/0/9",
    );

    // A outra linha é a troca de revisão: o botão continua no DOM por baixo do
    // diálogo, e é por ele que a página passa de uma proposta para a outra.
    fireEvent.click(linhas[1]);

    expect(within(dialog()).getByRole("textbox", { name: /Código do circuito/ })).toHaveValue(
      "ADOC-64511-1001",
    );
    expect(within(dialog()).getByRole("textbox", { name: /Porta de acesso/ })).toHaveValue("");
    // O trunk é derivado do nome da subinterface, e o nome é o da outra linha.
    expect(within(dialog()).getByRole("textbox", { name: /Trunk do edge/ })).toHaveValue(
      "Eth-Trunk200",
    );
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
