// Fumo da adoção (descoberta, parte 2): a proposta lida da configuração SALVA
// vira circuito na SoT pela revisão da página Migrar. O seed (e2e/setup.ts)
// grava o snapshot com a configuração sintética da rodada — sem ele a página
// não teria proposta nenhuma para adotar, e o fumo não teria o que exercitar.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { primeiroOctetoLivre } from "./discovery-walk";

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
  // ativo volta como 409 e deixa o diálogo aberto. A lista de autorizações é a
  // autoridade sobre o que está ocupado — o mesmo cuidado que o seed toma antes
  // de criar a dele (e2e/setup.ts) —, então o octeto sai do relógio e anda até
  // o primeiro livre nos dois /16 do RFC 2544. A caminhada mora em
  // `discovery-walk.ts` (função pura, com o porquê dela), e os três caminhos
  // dela estão presos no `test` do fim deste arquivo.
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
  const { octeto, passos } = primeiroOctetoLivre(rodada & 0xff, ocupados);
  expect(
    passos,
    "198.18.0.0/15 sem octeto livre: a faixa acumulada acabou — recrie o banco `gerenet_e2e`.",
  ).toBeLessThan(256);
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

  // A conferência é refeita quando a identidade muda, e o aceite caduca junto:
  // um `ciente` marcado contra um diff volta a falso quando chega outro. O
  // "Buscar no registro" acima mexeu no nome da organização, que é identidade —
  // então a consulta nova ainda está no ar, e o diff na tela ainda é o da
  // anterior. A descrição da subinterface passou a ser gerenciada nesta frente
  // (o render a deriva do código, do nome da organização e da velocidade), e
  // esperar pela linha derivada do nome que o REGISTRO devolveu é o que garante
  // que a conferência parou neste nome. Sem isso o `ciente` era marcado contra o
  // diff velho, desmarcado pelo novo, e o "Adotar" ficava desabilitado sem que
  // nada falhasse.
  await expect(
    dialogo.getByText(`description ${codigo} ${nomeDoRegistro.toUpperCase()}`),
  ).toBeVisible();

  await dialogo.getByLabel("Equipamento de acesso *").selectOption({ label: "ne8000-disco-01" });
  await dialogo.getByLabel("Porta de acesso *").fill("GE0/0/1");

  // O diff cai no grupo que MUDA o equipamento, e é o único grupo desenhado
  // aqui: o que a SoT não gerencia ficou vazio quando o `description` passou a
  // ser dela, e a página não desenha cabeçalho de grupo vazio.
  await expect(dialogo.getByText("Diferenças que mudariam o equipamento")).toBeVisible();
  // O `ciente` é exigido, e não "se aparecer": é o aceite desta frente, e
  // deixá-lo condicional era o que permitia ao fumo fechar verde por um caminho
  // que nunca exercitava o gate.
  const ciente = dialogo.getByLabel("Estou ciente destas diferenças");
  await ciente.check();

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

// A caminhada do octeto, sem navegador: o que se prende aqui é a REGRA do
// arquivo `discovery-walk.ts`. O ramo de avanço do fumo é o que existe porque um
// mecanismo anterior estava errado, e nas rodadas registradas ele nunca
// executou — o octeto do relógio caiu livre nas quatro —, então "verificado por
// leitura" era toda a evidência que ele tinha. Estes três casos são o que o
// executa de verdade.
test("a caminhada do octeto avança até o primeiro /24 livre dos dois /16", () => {
  // Partida livre: não anda (o caso das rodadas registradas).
  expect(primeiroOctetoLivre(7, new Set(["198.18.9.0/24"]))).toEqual({ octeto: 7, passos: 0 });

  // Um dos dois /16 ocupado já fecha o octeto inteiro — a recusa do serviço é
  // por sobreposição, e o bloco do stub sai nas duas famílias. Anda UM passo e
  // para no primeiro livre, seja qual for o lado ocupado.
  const umLado = new Set(["198.18.5.0/24", "198.19.7.0/24"]);
  expect(primeiroOctetoLivre(5, umLado)).toEqual({ octeto: 6, passos: 1 });
  expect(primeiroOctetoLivre(7, umLado)).toEqual({ octeto: 8, passos: 1 });

  // Faixa inteira ocupada: `passos = 256` é o valor que o assert do chamador
  // pega (`toBeLessThan(256)`), com o octeto de volta na partida.
  const cheia = new Set<string>();
  for (let octeto = 0; octeto < 256; octeto += 1) {
    cheia.add(`198.18.${octeto}.0/24`);
    cheia.add(`198.19.${octeto}.0/24`);
  }
  expect(primeiroOctetoLivre(0, cheia)).toEqual({ octeto: 0, passos: 256 });
});
