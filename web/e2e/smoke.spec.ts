// Fumos do núcleo web (ciclo C2): cadastro/desativação de site e abertura da
// Reconciliação com o device seedado (ne8000-01 — seed do globalSetup).
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

test("criar e desativar site", async ({ page }) => {
  await entrar(page);
  await page.getByRole("link", { name: "Sites" }).click();
  await expect(page).toHaveURL(/\/sites/);

  const nome = `site-e2e-${Date.now()}`;
  await page.getByLabel("Nome *").fill(nome);
  await page.getByRole("button", { name: "Cadastrar" }).click();

  const linha = page.getByRole("row", { name: nome });
  await expect(linha).toBeVisible();
  await linha.getByRole("button", { name: "Desativar" }).click();

  await page.getByRole("dialog").getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByRole("cell", { name: nome })).toHaveCount(0);
});

test("abrir Reconcile com device seedado", async ({ page }) => {
  await entrar(page);
  await page.goto("/reconcile");
  // "Equipamento" também casa (como substring) com o select de "Modo" (cuja
  // opção é "Equipamento"/"Snapshot"): restrinjo ao select que tem a opção
  // ne8000-01 — o de dispositivo.
  await page
    .getByLabel("Equipamento")
    .filter({ has: page.getByRole("option", { name: "ne8000-01" }) })
    .selectOption({ label: "ne8000-01" });

  // Superfície do Reconcile: qualquer um dos estados esperados renderiza
  // (aviso role="status" · tabela · "Nenhuma divergência encontrada.").
  // Um `role="alert"` (erro inesperado do backend) NÃO conta — o teste falha.
  await expect
    .poll(async () => {
      if ((await page.getByRole("alert").count()) > 0) return "erro-do-backend";
      const aviso = await page.getByRole("status").count();
      const tabela = await page.locator("table").count();
      const vazio = await page.getByText("Nenhuma divergência encontrada.").count();
      return aviso + tabela + vazio > 0 ? "renderizou" : "aguardando";
    })
    .toBe("renderizou");
});
