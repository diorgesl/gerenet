// Fumo: grupo de credencial criado pela página de Credenciais (T7) + vínculo
// ao equipamento seed ne8000-01 pela página de Equipamentos (Editar > select
// "Grupo de credencial", T8) exercitando também a coluna "Credencial".
// Rerun-safe: grupo único por rodada (Date.now()) — o banco e2e acumula.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";
const RODADA = Date.now();
const NOME_GRUPO = `e2e-credencial-${RODADA}`;

async function entrar(page: Page, usuario = "admin"): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuário").fill(usuario);
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("button", { name: "Sair" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("credential-groups: cria grupo pela UI e vincula ao equipamento", async ({ page }) => {
  // 0. Admin entra.
  await entrar(page);

  // 1. Cria o grupo pela página de Credenciais. A nav é sanfonada (commit
  //    2252e96): "Credenciais" e "Equipamentos" ficam no grupo
  //    "Infraestrutura", que começa FECHADO — abrir antes de clicar no link
  //    (mesmo padrão dos fumos adaptados smoke/change/upstream.spec.ts).
  await page.getByRole("button", { name: "Infraestrutura" }).click();
  await page.getByRole("link", { name: "Credenciais" }).click();
  await expect(page).toHaveURL(/\/credential-groups/);
  await expect(page.getByRole("heading", { name: "Grupos de credencial" })).toBeVisible();
  await page.getByLabel("Nome *").fill(NOME_GRUPO);
  await page.getByLabel("Caminho no Vault *").fill(`gerenet/credential-groups/${NOME_GRUPO}`);
  await page.getByRole("button", { name: "Cadastrar" }).click();
  await expect(page.getByRole("row", { name: NOME_GRUPO })).toBeVisible();

  // 2. Vincula o grupo ao equipamento seed ne8000-01 via Editar. A sanfona do
  //    grupo atual fica aberta durante a navegação SPA (o Layout não fecha o
  //    grupo ao trocar de item do mesmo grupo — e o useEffect reabre o grupo
  //    do item atual se necessário): o link "Equipamentos" segue visível.
  await page.getByRole("link", { name: "Equipamentos" }).click();
  await expect(page).toHaveURL(/\/devices/);
  const linhaDevice = page.getByRole("row", { name: /ne8000-01/ });
  await expect(linhaDevice).toBeVisible();
  await linhaDevice.getByRole("button", { name: "Editar" }).click();
  const dialogo = page.getByRole("dialog");
  // getByLabel("Grupo de credencial") é ambíguo (caso do "Tipo" de
  // upstream.spec.ts:61-63): o tooltip de ajuda do FormField tem aria-label
  // começando com o mesmo texto — e, com o modal aberto, o select do form de
  // cadastro (na página atrás do backdrop) também casa. O combobox cujo nome
  // contém "Grupo de credencial" DENTRO do dialog é único (o outro select é o
  // "Site").
  await dialogo
    .getByRole("combobox", { name: /Grupo de credencial/ })
    .selectOption({ label: NOME_GRUPO });
  await dialogo.getByRole("button", { name: "Salvar" }).click();
  await expect(dialogo).toBeHidden();

  // 3. A coluna "Credencial" da linha mostra o nome do grupo (o vínculo
  //    registrado pela edição — nunca o segredo, que segue no Vault).
  await expect(
    page.getByRole("row", { name: /ne8000-01/ }).getByText(NOME_GRUPO),
  ).toBeVisible();
});
