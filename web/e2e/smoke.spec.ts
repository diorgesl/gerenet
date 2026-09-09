// Fumos do núcleo web (ciclo C2): cadastro/desativação de site e abertura da
// Reconciliação com o device seedado (ne8000-01 — seed do globalSetup).
// Ciclo E: wiki operacional (menu Ajuda, sidebar por seção, badge "em breve")
// e tooltip de campo no hover (FormField/help).
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
  await page.getByRole("button", { name: "Infraestrutura" }).click();
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

test("wiki abre pelo menu Ajuda e tooltip aparece em campo de formulário", async ({ page }) => {
  await entrar(page);

  // Wiki: menu Ajuda → índice renderiza a página "Visão geral"
  await page.getByRole("link", { name: "Wiki" }).click();
  await expect(page).toHaveURL(/\/wiki/);
  await expect(page.getByRole("heading", { name: "Visão geral e conceitos" })).toBeVisible();

  // Navega pela sidebar para uma página "em breve" e vê o badge de aviso.
  // A página "Serviços MPLS (L2VC e VSI)" saiu do "(em breve)" na fase 4
  // (virou conteúdo real — título sem badge). O alvo passou a ser "Mudanças
  // controladas nos equipamentos", que ainda tem em_breve: true (badge na
  // sidebar + aviso na página). O nome acessível do link é título + badge
  // ("... (em breve)"); a tabela "Navegação rápida" do índice usa nomes curtos
  // sem badge ("Mudanças controladas", "Serviços MPLS…") — usar o nome
  // completo com "(em breve)" isola o link da sidebar (evita violação de
  // strict mode do Playwright).
  await page.getByRole("link", { name: "Mudanças controladas nos equipamentos (em breve)" }).click();
  await expect(page.getByText("Recurso planejado — não disponível ainda.")).toBeVisible();

  // Tooltip: o ícone de ajuda do campo "Nome *" mostra a dica no hover
  // (primeiro label.field do form de Sites é "Nome *" — todos têm help()).
  await page.goto("/sites");
  await page.locator("label.field").first().locator(".field-help").hover();
  await expect(page.locator(".field-help-dica").first()).toBeVisible();
});
