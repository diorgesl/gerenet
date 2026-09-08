// Fumo da fase 5 (upstreams, §7): organização operadora criada pela página de
// Organizações (R-27 — kind "operadora" no select) + upstream criado pelo
// dialog da lista + device/circuito/sessão novos (API, rerun-safe) + vínculo
// de circuito pela UI (matriz principal × contingência) + community de
// operadora (prepend, Região Sul) pelo dialog + CR de escopo `upstream`
// solicitada pelo admin e APROVADA pelo e2e-aprovador (usuário distinto).
// Rerun-safe: tudo derivado de Date.now() (org/upstream/device/circuito/
// endereços únicos por rodada — o banco e2e acumula).
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";
const API_KEY = process.env.GERENET_API_KEY ?? "dev-key-change-me";

const RODADA = Date.now();
// Dois octetos derivados do timestamp (~40 mil combos, no espaço 10.x): o
// par colidente é global às sessões ativas do banco e2e acumulado — mesmo
// padrão do change.spec.ts/mpls.spec.ts.
const REDE = `10.${(Math.floor(RODADA / 256) % 200) + 10}.${(RODADA % 200) + 10}`; // 10.10.10..209.10..209
const NOME_ORG = `e2e-operadora-${RODADA}`;
const NOME_UPSTREAM = `e2e-upstream-${RODADA}`;
const NOME_DEVICE = `e2e-ne-upstream-${RODADA}`;
const CODIGO_CIRC = `e2e-upstr-circ-${RODADA}`;
// m-1 (revisão T20): metades de community clássica são 16-bit (teto 65535) —
// o resto anterior chegava a 85499; o backend não valida faixa hoje, mas uma
// validação 32-bit futura não pode quebrar o fumo.
const VALOR_COMM = `65530:${20000 + (RODADA % 45536)}`; // 20000..65535
const API = { "x-api-key": API_KEY, "content-type": "application/json" };

async function entrar(page: Page, usuario = "admin"): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuário").fill(usuario);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  // Pós-login a SPA volta para a página que originou o redirect do RequireAuth:
  // não se assume o destino; espera-se o shell logado e navega-se ao Dashboard.
  await expect(page.getByRole("button", { name: "Sair" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

async function sair(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("upstream: operadora + upstream + vínculo + community + CR aprovada", async ({ page }) => {
  // 0. Admin entra e cria a organização operadora pela página (R-27: a opção
  //    "operadora" existe no select de kind do form de Organizações).
  await entrar(page);
  await page.getByRole("link", { name: "Organizações" }).click();
  await expect(page).toHaveURL(/\/organizations/);
  await expect(page.getByRole("heading", { name: "Organizações" })).toBeVisible();
  await page.getByLabel("Nome *").fill(NOME_ORG);
  // getByLabel("Tipo") é ambíguo: o tooltip de ajuda (aria-label "Tipo: ...")
  // também o contém — o combobox é o único select do form de criação.
  await page.getByRole("combobox").selectOption("operadora");
  await page.getByRole("button", { name: "Cadastrar" }).click();
  await expect(page.getByRole("row", { name: NOME_ORG })).toBeVisible();

  // Id da org criada pela UI (necessário para o circuito/sessão via API).
  const respOrgs = await page.request.get("/api/v1/organizations", { headers: API });
  expect(respOrgs.ok()).toBeTruthy();
  const orgs = (await respOrgs.json()) as { id: number; name: string }[];
  const idOrg = orgs.find((o) => o.name === NOME_ORG)?.id ?? 0;
  expect(idOrg).toBeGreaterThan(0);

  // 1. Upstream criado pelo dialog da lista (o seed `e2e-upstream-tier1`
  //    confirma que o setup rodou; o nosso é único por rodada).
  await page.getByRole("link", { name: "Upstreams" }).click();
  await expect(page).toHaveURL(/\/upstreams/);
  await expect(page.getByRole("heading", { name: "Upstreams" })).toBeVisible();
  await expect(page.getByRole("link", { name: "e2e-upstream-tier1" })).toBeVisible();
  await page.getByRole("button", { name: "Novo upstream" }).click();
  const dialogo = page.getByRole("dialog");
  await dialogo.getByLabel("Nome *").fill(NOME_UPSTREAM);
  await dialogo.getByLabel("Tipo *").selectOption("transito");
  await dialogo.getByLabel("Operadora *").selectOption({ label: NOME_ORG });
  await dialogo.getByLabel("Prefixos esperados V4").fill("700");
  await dialogo.getByLabel("Prefixos esperados V6").fill("200");
  await dialogo.getByRole("button", { name: "Criar" }).click();

  // 2. Abre o detalhe do upstream: título, subtítulo da operadora e a matriz
  //    vazia antes do vínculo.
  await page.getByRole("link", { name: NOME_UPSTREAM }).click();
  await expect(page).toHaveURL(/\/upstreams\/\d+/);
  const idUpstream = Number(page.url().match(/\/upstreams\/(\d+)/)?.[1] ?? 0);
  expect(idUpstream).toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: NOME_UPSTREAM })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Matriz principal × contingência" })).toBeVisible();
  await expect(
    page.getByText("Nenhum circuito vinculado — a matriz de conectividade fica vazia até vincular um circuito."),
  ).toBeVisible();

  // 3. Setup via API (X-Api-Key, como o change.spec.ts): site do seed +
  //    device/circuito/sessão únicos por rodada — a sessão dá origem aos
  //    steps do plano (plan_provision_upstream exige ≥1 sessão ativa).
  const respSites = await page.request.get("/api/v1/sites", { headers: API });
  expect(respSites.ok()).toBeTruthy();
  const sites = (await respSites.json()) as { id: number; name: string }[];
  const idSite = sites.find((s) => s.name === "e2e-site-01")?.id ?? 0;
  expect(idSite).toBeGreaterThan(0);

  const respDev = await page.request.post("/api/v1/devices", {
    headers: API,
    data: {
      name: NOME_DEVICE,
      management_address: `${REDE}.3`,
      vendor: "huawei",
      model: "NE8000M12",
      family: "NE8000",
      role: "edge",
      site_id: idSite,
    },
  });
  expect(respDev.status()).toBe(201);
  const idDevice = ((await respDev.json()) as { id: number }).id;
  expect(idDevice).toBeGreaterThan(0);

  const respCirc = await page.request.post("/api/v1/circuits", {
    headers: API,
    data: {
      code: CODIGO_CIRC,
      organization_id: idOrg,
      site_id: idSite,
      access_device_id: idDevice,
      access_port: "GE0/0/22",
      edge_device_id: idDevice,
      stack: "ipv4",
      vlan_mode: "unica",
      p2p_v4_len: 31,
    },
  });
  expect(respCirc.status()).toBe(201);
  const idCircuito = ((await respCirc.json()) as { id: number }).id;
  expect(idCircuito).toBeGreaterThan(0);

  const respSess = await page.request.post("/api/v1/bgp-sessions", {
    headers: API,
    data: {
      circuit_id: idCircuito,
      device_id: idDevice,
      afi: "ipv4",
      local_address: `${REDE}.1`,
      remote_address: `${REDE}.2`,
      asn_local: 64600,
      asn_remote: 65120,
      description: `e2e upstream ${RODADA}`,
    },
  });
  expect(respSess.status()).toBe(201);

  // 4. Vínculo pela UI (recarrega para a lista de circuitos disponíveis
  //    enxergar o circuito criado via API) — a matriz passa a exibir a linha.
  await page.reload();
  await expect(page.getByRole("heading", { name: NOME_UPSTREAM })).toBeVisible();
  await page
    .getByLabel("Vincular circuito")
    .selectOption({ label: `Circuito #${idCircuito} — ${CODIGO_CIRC}` });
  await page.getByRole("button", { name: "Vincular" }).click();
  const tabelaMatriz = page.locator("table").filter({ hasText: `Circuito #${idCircuito}` });
  await expect(tabelaMatriz.getByRole("link", { name: `Circuito #${idCircuito}` })).toBeVisible();
  await expect(tabelaMatriz.getByText("principal", { exact: true })).toBeVisible();
  // Sessão do circuito vinculado aparece na matriz (afi + endereços).
  await expect(page.getByText(`${REDE}.1 ↔ ${REDE}.2`)).toBeVisible();

  // 5. Community de operadora pelo dialog (purpose prepend, Região Sul).
  await page.getByRole("button", { name: "Nova community" }).click();
  const dialogoComm = page.getByRole("dialog");
  await dialogoComm.getByLabel("Purpose *").selectOption("prepend");
  await dialogoComm.getByLabel("Valor *").fill(VALOR_COMM);
  await dialogoComm.getByLabel("Região").fill("sul");
  await dialogoComm.getByRole("button", { name: "Criar" }).click();
  await expect(page.getByRole("cell", { name: "prepend" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "sul" })).toBeVisible();
  await expect(page.getByText(VALOR_COMM, { exact: true })).toBeVisible();

  // 6. Solicitar a mudança no upstream (escopo `upstream`): CR nasce
  //    rascunho com o step do device e o diff por bloco renderizado.
  await page.getByRole("button", { name: "Solicitar mudança no upstream" }).click();
  const dialogoCr = page.getByRole("dialog");
  await dialogoCr.getByLabel("Motivo *").fill(`upstream e2e ${RODADA} — aplicar config`);
  await dialogoCr.getByRole("button", { name: "Criar" }).click();
  await expect(page).toHaveURL(/\/change-requests\/\d+/);
  const urlCr = page.url();
  const idCr = Number(page.url().match(/\/change-requests\/(\d+)/)?.[1] ?? 0);
  expect(idCr).toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: `Change request #${idCr}` })).toBeVisible();
  await expect(page.getByText("rascunho")).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: new RegExp(NOME_DEVICE) })).toBeVisible();
  // O diff por bloco vem colapsado (comandos em <pre> hidden dentro do
  // <details> fechado): o summary é o alvo visível e o bloco do peer se
  // confere por texto do conteúdo (toContainText não exige visibilidade,
  // getByText/toContainText com toBeVisible falharia no pre hidden).
  await expect(page.locator("details").first()).toBeVisible();
  const detalhePeer = page.locator("details").filter({
    hasText: new RegExp(`peer ${REDE}\\.2 as-number 65120`),
  });
  expect(await detalhePeer.count()).toBeGreaterThan(0);
  await expect(detalhePeer.first()).toContainText(`peer ${REDE}.2 as-number 65120`);
  // O objeto da CR de escopo upstream na linha "Circuito" é o NOME do
  // upstream — upstream_name vindo do backend (a linha "—" é a regressão
  // #null do l2vc, morta aqui com o mesmo teste de pin).
  const celulaCircuito = page.locator("tr", { hasText: "Circuito" }).locator("td");
  await expect(celulaCircuito).toBeVisible();
  await expect(celulaCircuito).toHaveText(NOME_UPSTREAM);

  // 7. Enviar para aprovação.
  await page.getByRole("button", { name: "Enviar para aprovação" }).click();
  await expect(page.getByText("aguardando_aprovacao")).toBeVisible();

  // 8. Aprovador (usuário distinto) aprova — o admin não pode aprovar o
  //    próprio pedido (T5) e o botão nem aparece para ele.
  await sair(page);
  await entrar(page, "e2e-aprovador");
  await page.goto(urlCr);
  await page.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("aprovado")).toBeVisible();
  // O detalhe continua acessível após a aprovação (via de auditoria).
  await expect(page.getByRole("heading", { name: `Change request #${idCr}` })).toBeVisible();
});
