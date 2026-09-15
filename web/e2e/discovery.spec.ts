// Fumo da adoção (descoberta, parte 2): a proposta lida da configuração SALVA
// vira circuito na SoT pela revisão da página Migrar. O seed (e2e/setup.ts)
// grava o snapshot com a configuração sintética da rodada — sem ele a página
// não teria proposta nenhuma para adotar, e o fumo não teria o que exercitar.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const SENHA = process.env.E2E_PASSWORD ?? "e2e-super-8";

async function entrar(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuário").fill("admin");
  await page.getByLabel("Senha").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("adotar a proposta da configuração e conferir o circuito na lista", async ({ page }) => {
  await entrar(page);

  // Pelo caminho do operador: o equipamento e o "Migrar" da página dele. A
  // sidebar tem um "Migrar" também (item de menu), então o clique é escopado ao
  // `main` — sem isso o seletor casa com os dois.
  // O equipamento do fumo é o `ne8000-disco-01` (seed) — não o `ne8000-01`, que
  // já tem sessão ativa do circuito da operadora e recusaria a adoção.
  await page.goto("/devices");
  await page.getByRole("link", { name: "ne8000-disco-01", exact: true }).click();
  await expect(page.getByRole("heading", { name: "ne8000-disco-01" })).toBeVisible();
  await page.getByRole("main").getByRole("link", { name: "Migrar" }).click();
  await expect(page).toHaveURL(/\/discovery\?device_id=\d+/);

  // A proposta que o seed escreveu na configuração: uma linha com o "Adotar"
  // (a proposta com conflito tem esse botão desabilitado, e a tabela teria a
  // linha mesmo assim).
  const linha = page
    .getByRole("row")
    .filter({ has: page.getByRole("button", { name: "Adotar", exact: true }) });
  await expect(linha).toHaveCount(1);
  await expect(linha.getByRole("button", { name: "Adotar", exact: true })).toBeEnabled();
  await linha.getByRole("button", { name: "Adotar", exact: true }).click();

  // A revisão. O "Adotar" do diálogo só habilita com a conferência de
  // fidelidade de volta (e com os campos obrigatórios preenchidos), então o
  // clique do fim espera por ela.
  const dialogo = page.getByRole("dialog");
  await expect(dialogo.getByRole("heading", { name: /^Adotar VLAN \d+$/ })).toBeVisible();

  // O código, o trunk e o nome da organização já vêm sugeridos da proposta — o
  // trunk sai do nome da subinterface (`Eth-Trunk127.<vid>`), a organização da
  // descrição do peer — e é o operador quem confere. Só o acesso a configuração
  // do edge não tem: é o que a revisão preenche (pendência `acesso_desconhecido`).
  const codigo = await dialogo.getByLabel("Código do circuito *").inputValue();
  expect(codigo).not.toBe("");
  await expect(dialogo.getByLabel("Trunk do edge *")).toHaveValue("Eth-Trunk127");
  await expect(dialogo.getByLabel("Nome da organização nova *")).not.toHaveValue("");
  await dialogo.getByLabel("Equipamento de acesso *").selectOption({ label: "ne8000-disco-01" });
  await dialogo.getByLabel("Porta de acesso *").fill("GE0/0/1");

  // Os dois grupos do diff. A fixture deixa a SoT sem gerar o `description` da
  // subinterface: grupo de informação, que não gateia nada. O `ciente` aparece
  // só quando há diferença que MUDARIA o equipamento (esta não tem) — a
  // marcação fica aqui porque é o passo do runbook, e a página o exige quando
  // ele aparece.
  await expect(dialogo.getByText("O que a SoT não gerencia")).toBeVisible();
  const ciente = dialogo.getByLabel("Estou ciente destas diferenças");
  if ((await ciente.count()) > 0) {
    await ciente.check();
  }

  await dialogo.getByRole("button", { name: "Adotar", exact: true }).click();

  // O relato do que foi gravado mora fora do diálogo, que fecha no sucesso.
  await expect(
    page.getByText(/Proposta adotada: o circuito \d+ foi gravado na SoT\./),
  ).toBeVisible();
  // A lista refeita já não tem o peer: ele entrou na SoT.
  await expect(page.getByText("Nenhum peer fora da SoT neste equipamento.")).toBeVisible();

  // E o circuito está na lista de circuitos, com o código que a revisão gravou.
  await page.goto("/circuits");
  await expect(page.getByRole("link", { name: codigo })).toBeVisible();
});
