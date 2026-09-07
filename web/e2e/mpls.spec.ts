// Fumo da fase 4 (MPLS): site + 2 switches + domínio MPLS + membros + L2VC
// (API, rerun-safe) → web: /mpls/l2vc → detalhe → "Solicitar mudança no L2VC"
// (CR de escopo l2vc nasce rascunho com 2 steps) → enviar para aprovação →
// aprovador (usuário distinto) rejeita. Rerun-safe: tudo derivado de
// Date.now() (site/device/domínio/L2VC/loopbacks/vc-id/vids únicos por
// rodada — o banco e2e acumula).
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";
const API_KEY = process.env.GERENET_API_KEY ?? "dev-key-change-me";

const RODADA = Date.now();
// Dois octetos derivados do timestamp (~40 mil combos, no espaço 10.x): o
// par colidente é global às sessões ativas do banco e2e acumulado — com um
// só octeto (10.99.X) a chance de colisão entre rodadas seria de ~1/200
// (efeito aniversário: ~1 colisão em ~20 execuções). Mesmo padrão do
// change.spec.ts.
const REDE = `10.${(Math.floor(RODADA / 256) % 200) + 10}.${(RODADA % 200) + 10}`; // 10.10.10..209.10..209
const API = { "x-api-key": API_KEY, "content-type": "application/json" };

async function entrar(page: Page, usuario = "admin"): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuário").fill(usuario);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("button", { name: "Sair" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

async function sair(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("mpls: domínio + L2VC + solicitar mudança (rejeitada pelo aprovador)", async ({ page }) => {
  // 1. Setup via API (X-Api-Key), como o change.spec.ts — tudo único por rodada.
  await entrar(page);
  const respSite = await page.request.post("/api/v1/sites", {
    headers: API,
    data: { name: `e2e-mpls-site-${RODADA}` },
  });
  expect(respSite.status()).toBe(201);
  const idSite = ((await respSite.json()) as { id: number }).id;
  expect(idSite).toBeGreaterThan(0);

  const nomeA = `sw-a-${RODADA}`;
  const nomeB = `sw-b-${RODADA}`;
  const respDevA = await page.request.post("/api/v1/devices", {
    headers: API,
    data: {
      name: nomeA,
      management_address: `${REDE}.3`,
      vendor: "huawei",
      model: "S6730",
      family: "S6730",
      role: "edge",
      site_id: idSite,
    },
  });
  expect(respDevA.status()).toBe(201);
  const idDevA = ((await respDevA.json()) as { id: number }).id;
  expect(idDevA).toBeGreaterThan(0);

  const respDevB = await page.request.post("/api/v1/devices", {
    headers: API,
    data: {
      name: nomeB,
      management_address: `${REDE}.4`,
      vendor: "huawei",
      model: "S6730",
      family: "S6730",
      role: "edge",
      site_id: idSite,
    },
  });
  expect(respDevB.status()).toBe(201);
  const idDevB = ((await respDevB.json()) as { id: number }).id;
  expect(idDevB).toBeGreaterThan(0);

  const respDom = await page.request.post("/api/v1/mpls/domains", {
    headers: API,
    data: { name: `dom-e2e-${RODADA}` },
  });
  expect(respDom.status()).toBe(201);
  const idDom = ((await respDom.json()) as { id: number }).id;
  expect(idDom).toBeGreaterThan(0);

  // Loopbacks únicos por rodada (derivados dos mesmos dois octetos do REDE).
  const respMemA = await page.request.post(`/api/v1/mpls/domains/${idDom}/members`, {
    headers: API,
    data: { device_id: idDevA, loopback_address: `${REDE}.1` },
  });
  expect(respMemA.status()).toBe(201);

  const respMemB = await page.request.post(`/api/v1/mpls/domains/${idDom}/members`, {
    headers: API,
    data: { device_id: idDevB, loopback_address: `${REDE}.2` },
  });
  expect(respMemB.status()).toBe(201);

  const nomeL2vc = `e2e-mpls-ld-${RODADA}`;
  const respL2vc = await page.request.post("/api/v1/mpls/l2vc", {
    headers: API,
    data: {
      domain_id: idDom,
      name: nomeL2vc,
      vc_id: 1000 + (RODADA % 10000),
      endpoints: [
        { device_id: idDevA, interface: "10GE0/0/1", encapsulation: "dot1q", vid: 600 + (RODADA % 300) },
        { device_id: idDevB, interface: "10GE0/0/2", encapsulation: "dot1q", vid: 700 + (RODADA % 300) },
      ],
    },
  });
  expect(respL2vc.status()).toBe(201);
  const l2vc = (await respL2vc.json()) as { id: number; name: string; vc_id: number };
  expect(l2vc.name).toBe(nomeL2vc);
  expect(l2vc.vc_id).toBe(1000 + (RODADA % 10000));

  // 2. Web: lista /mpls/l2vc → detalhe do serviço recém-criado.
  await page.goto("/mpls/l2vc");
  await expect(page.getByRole("heading", { name: "Serviços L2VC" })).toBeVisible();
  await page.getByRole("link", { name: nomeL2vc }).click();
  await expect(page).toHaveURL(/\/mpls\/l2vc\/\d+/);
  await expect(page.getByRole("heading", { name: `L2VC ${nomeL2vc}` })).toBeVisible();
  // As duas pontas aparecem no detalhe (tabela de endpoints).
  await expect(page.getByRole("heading", { name: "Pontas" })).toBeVisible();
  await expect(page.locator("table").getByText(nomeA, { exact: true })).toBeVisible();
  await expect(page.locator("table").getByText(nomeB, { exact: true })).toBeVisible();

  // 3. Solicitar mudança (o diálogo cuida do POST escopo=l2vc + l2vc_id).
  await page.getByRole("button", { name: "Solicitar mudança no L2VC" }).click();
  const dialogo = page.getByRole("dialog");
  await dialogo.getByLabel("Motivo *").fill(`mount via e2e ${RODADA}`);
  await dialogo.getByLabel("Criticidade *").selectOption("baixa");
  await dialogo.getByRole("button", { name: "Criar" }).click();
  await expect(page).toHaveURL(/\/change-requests\/\d+/);
  const urlCr = page.url();
  const idCr = Number(page.url().match(/\/change-requests\/(\d+)/)?.[1] ?? 0);
  expect(idCr).toBeGreaterThan(0);

  // CR nasce rascunho com os 2 steps (1 por ponta) e o diff por bloco renderizado.
  await expect(page.getByText("rascunho")).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: new RegExp(nomeA) })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: new RegExp(nomeB) })).toBeVisible();
  await expect(page.locator("details").first()).toBeVisible();
  // O objeto da CR de escopo l2vc na linha "Circuito" é o NOME do serviço —
  // l2vc_name vindo do backend (fix R1 T12; a linha "—" morreu com o bug
  // #null). Pin exato: o td renderiza rotuloObjeto(cr) = cr.l2vc_name ?? "—",
  // sem wrappers extras no DOM (ChangeRequestDetail.tsx) — regride se o
  // backend parar de popular o campo.
  const celulaCircuito = page.locator("tr", { hasText: "Circuito" }).locator("td");
  await expect(celulaCircuito).toBeVisible();
  await expect(celulaCircuito).toHaveText(nomeL2vc);

  // 4. Enviar para aprovação (pré-condição da rejeição).
  await page.getByRole("button", { name: "Enviar para aprovação" }).click();
  await expect(page.getByText("aguardando_aprovacao")).toBeVisible();

  // 5. Aprovador (usuário distinto) rejeita — o admin não pode aprovar o
  //    próprio pedido (T5) e o botão nem aparece para ele.
  await sair(page);
  await entrar(page, "e2e-aprovador");
  await page.goto(urlCr);
  await page.getByRole("button", { name: "Rejeitar" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("rejeitado")).toBeVisible();
  // O detalhe continua acessível após a rejeição (via de auditoria).
  await expect(page.getByText(`Change request #${idCr}`)).toBeVisible();
});
