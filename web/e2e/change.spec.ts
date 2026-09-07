// Fumo do fluxo de mudança (ciclo D): equipamento+circuito+sessão novos (API)
// → solicitar pela UI → aprovar (outro usuário) → executar. Sem worker rodando
// ("jobs fake" do spec §10): o enqueue vai para a fila Redis e a CR fica
// `executando`. Rerun-safe: tudo derivado de Date.now().
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";
const API_KEY = process.env.GERENET_API_KEY ?? "dev-key-change-me";

const RODADA = Date.now();
// Dois octetos derivados do timestamp (~40 mil combos, no espaço 10.x): o
// `_colidente_par` é global às sessões ativas do banco e2e acumulado — com um
// só octeto (10.99.X) a chance de colisão seria de ~1/200 por rodada
// (efeito aniversário: ~1 colisão em ~20 execuções).
const REDE = `10.${(Math.floor(RODADA / 256) % 200) + 10}.${(RODADA % 200) + 10}`; // 10.10.10..209.10..209
const API = { "x-api-key": API_KEY, "content-type": "application/json" };

async function entrar(page: Page, usuario = "admin"): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuário").fill(usuario);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  // Pós-login a SPA volta para a página que originou o redirect do RequireAuth
  // (`location.state.from` — no fim do fluxo é /change-requests/<id>, não /):
  // não se assume o destino; espera-se o shell logado e navega-se ao Dashboard.
  await expect(page.getByRole("button", { name: "Sair" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

async function sair(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("fluxo de mudança: criar, solicitar, aprovar e executar", async ({ page }) => {
  // 0. Admin entra e cria um equipamento novo via API (X-Api-Key, como o
  //    globalSetup) — evita o colidente "2ª sessão ipv4 no mesmo device"
  //    entre execuções (bgp_sessions.py:133).
  await entrar(page);
  const respSite = await page.request.get("/api/v1/sites", { headers: API });
  expect(respSite.ok()).toBeTruthy();
  const sites = (await respSite.json()) as { id: number; name: string }[];
  const idSite = sites.find((s) => s.name === "e2e-site-01")?.id ?? 0;
  expect(idSite).toBeGreaterThan(0);

  const nomeDevice = `e2e-ne-${RODADA}`;
  const respDev = await page.request.post("/api/v1/devices", {
    headers: API,
    data: {
      name: nomeDevice,
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

  // 1. Circuito novo pela UI (form de Circuitos)
  const codigo = `e2e-change-${RODADA}`;
  await page.getByRole("link", { name: "Circuitos" }).click();
  await expect(page).toHaveURL(/\/circuits/);
  await page.getByLabel("Código *").fill(codigo);
  await page.getByLabel("Organização *").selectOption({ label: "e2e-cliente-downstream" });
  await page.getByLabel("Site *").selectOption({ label: "e2e-site-01" });
  await page.getByLabel("Equipamento de acesso *").selectOption({ label: nomeDevice });
  await page.getByLabel("Porta de acesso *").fill("GE0/0/22");
  await page.getByLabel("Edge *").selectOption({ label: nomeDevice });
  await page.getByRole("button", { name: "Cadastrar" }).click();
  const linha = page.getByRole("row", { name: codigo });
  await expect(linha).toBeVisible();
  await linha.getByRole("link", { name: codigo }).click();
  await expect(page).toHaveURL(/\/circuits\/\d+/);
  const idCircuito = Number(page.url().match(/\/circuits\/(\d+)/)?.[1] ?? 0);
  expect(idCircuito).toBeGreaterThan(0);

  // 2. Sessão BGP via API — é ela que dá origem aos steps do plano
  //    (plan_provision itera as sessões do circuito, T3:903). Endereços
  //    únicos por execução (dois octetos derivados de RODADA — evita
  //    _colidente_par entre rodadas).
  const respSess = await page.request.post("/api/v1/bgp-sessions", {
    headers: API,
    data: {
      circuit_id: idCircuito,
      device_id: idDevice,
      afi: "ipv4",
      local_address: `${REDE}.1`,
      remote_address: `${REDE}.2`,
      asn_local: 64600,
      asn_remote: 65001,
      description: `e2e ${codigo}`,
    },
  });
  expect(respSess.status()).toBe(201);

  // 3. Solicitar a mudança no detalhe do circuito
  await page.reload();
  await page.getByRole("button", { name: "Solicitar mudança" }).click();
  const dialogo = page.getByRole("dialog");
  await dialogo.getByLabel("Motivo *").fill(`e2e ${codigo} — aplicar configuração`);
  await dialogo.getByRole("button", { name: "Criar" }).click();
  await expect(page).toHaveURL(/\/change-requests\/\d+/);
  const urlCr = page.url();
  const idCr = Number(page.url().match(/\/change-requests\/(\d+)/)?.[1] ?? 0);
  expect(idCr).toBeGreaterThan(0);
  // O diff por bloco renderiza (pelo menos um <details> com comandos)
  await expect(page.locator("details").first()).toBeVisible();

  // 4. Enviar para aprovação
  await page.getByRole("button", { name: "Enviar para aprovação" }).click();
  await expect(page.getByText("aguardando_aprovacao")).toBeVisible();

  // 5. Aprovador (usuário distinto) aprova — o admin não pode aprovar o
  //    próprio pedido (T5) e o botão nem aparece para ele.
  await sair(page);
  await entrar(page, "e2e-aprovador");
  await page.goto(urlCr);
  await page.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("aprovado")).toBeVisible();

  // 6. Admin (administrador = executor) executa; sem worker o job fica na
  //    fila e a CR permanece `executando`.
  await sair(page);
  await entrar(page);
  await page.goto(urlCr);
  await page.getByRole("button", { name: "Executar" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("executando")).toBeVisible();
});
