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

  // Os blocos do stub precisam ser únicos ao longo da vida do banco e2e, que é
  // persistente e acumula autorizações: prefixo que outra organização já tem
  // ativo volta como 409 e deixa o diálogo aberto. O relógio sozinho não
  // sustenta isso. Uma faixa de bits fica parada pelo tempo do seu bit mais
  // baixo — os bits 24-31 viram a cada ~4,7 h, então duas rodadas na mesma tarde
  // derivam o mesmo /24 —, e as faixas que viram rápido repetem a cada 256 ms.
  // E a recusa do serviço é por SOBREPOSIÇÃO: um /32 ou um bloco menor dentro de
  // um /24 ocupado não escapa da conta. A lista de autorizações é a autoridade
  // sobre o que está ocupado — o mesmo cuidado que o seed toma antes de criar a
  // dele (e2e/setup.ts) —, então o octeto sai do relógio e anda até o primeiro
  // livre nos dois /16 do RFC 2544.
  const respostaAutorizacoes = await page.request.get("/api/v1/prefix-authorizations?family=ipv4");
  expect(respostaAutorizacoes.ok()).toBe(true);
  // Sem `include_disabled`, a lista traz exatamente as ativas — as que o serviço
  // compara ao recusar um bloco.
  const autorizacoes = (await respostaAutorizacoes.json()) as { prefix: string }[];
  // A comparação abaixo é por igualdade de /24, o que pressupõe que toda
  // autorização do banco seja um /24 alinhado (só o seed e este fumo criam
  // autorização). Um bloco mais largo cobriria o candidato sem casar aqui: ele
  // quebra nesta linha, em vez de virar um 409 sem explicação.
  expect(autorizacoes.every((a) => /^\d{1,3}\.\d{1,3}\.\d{1,3}\.0\/24$/.test(a.prefix))).toBe(
    true,
  );
  const ocupados = new Set(autorizacoes.map((a) => a.prefix));

  const rodada = Date.now();
  const nomeDoRegistro = `Provedor E2E Registro ${rodada}`;
  let octeto = rodada & 0xff;
  let passos = 0;
  while (
    passos < 256 &&
    (ocupados.has(`198.18.${octeto}.0/24`) || ocupados.has(`198.19.${octeto}.0/24`))
  ) {
    octeto = (octeto + 1) % 256;
    passos += 1;
  }
  expect(passos, "198.18.0.0/15 sem octeto livre: a faixa acumulada acabou.").toBeLessThan(256);
  const blocoA = `198.18.${octeto}.0/24`;
  const blocoB = `198.19.${octeto}.0/24`;

  // O prefill stubado: o botão, a lista de blocos e o payload são o que o fumo
  // exercita; a leitura do registro tem os testes dela, e o whois real não é
  // determinístico no CI.
  await page.route("**/api/v1/organizations/prefill*", (rota) =>
    rota.fulfill({
      json: {
        asn: 64512,
        nome: nomeDoRegistro,
        razao_social: "Provedor E2E Ltda",
        documento: "12.345.678/0001-99",
        pais: "BR",
        as_set_sugerido: "AS-64512",
        as_sets: ["AS-64512"],
        blocos: [
          { prefix: blocoA, family: "ipv4", fonte: "registro", conflito: null },
          { prefix: blocoB, family: "ipv4", fonte: "registro", conflito: null },
        ],
        fontes: { nome: "radb", blocos: "registro" },
        avisos: [],
      },
    }),
  );
  await dialogo.getByRole("button", { name: "Buscar no registro" }).click();
  await expect(dialogo.getByLabel("Nome da organização nova *")).toHaveValue(nomeDoRegistro);
  await expect(dialogo.getByLabel("Documento (CNPJ/ownerid)")).toHaveValue("12.345.678/0001-99");
  await expect(dialogo.getByLabel(`Incluir ${blocoA}`)).toBeChecked();
  await expect(dialogo.getByLabel(`Incluir ${blocoB}`)).toBeChecked();

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

  // As autorizações do registro nasceram junto com o circuito (§6.4): os dois
  // blocos que o operador deixou marcados estão na lista de autorizações.
  await page.goto("/prefix-authorizations");
  await expect(page.getByText(blocoA)).toBeVisible();
  await expect(page.getByText(blocoB)).toBeVisible();
});
