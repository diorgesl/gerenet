import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import {
  useAdotar,
  useDevices,
  useFidelidade,
  useOrganizations,
  usePolicyProfiles,
  usePrefill,
  useUpstreams,
  type IdentidadeDaConferencia,
} from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { help } from "@/help";
import type { DiscoveryPropostaOut, OrganizationPrefillOut, UpstreamTipo } from "@/api/types";

/** O trunk do circuito, derivado do nome da subinterface.
 *
 * O render nomeia a subinterface como `<trunk>.<vid>` (`naming.subinterface`),
 * e é a mesma regra do `_trunk_da_subinterface` do serviço. Derivado, o campo
 * nasce preenchido: sem isso cada tecla do trunk entra na consulta — um render
 * do equipamento inteiro no servidor por tecla, com o diff piscando a cada
 * resposta. Nome que não é `<trunk>.<vid>` não tem trunk a derivar (a diferença
 * é real: o render não reproduz esse nome) e o operador preenche à mão.
 */
function trunkDoNome(proposta: DiscoveryPropostaOut): string {
  if (proposta.subinterface === null || proposta.vid === null) return "";
  const sufixo = `.${proposta.vid}`;
  return proposta.subinterface.endsWith(sufixo)
    ? proposta.subinterface.slice(0, -sufixo.length)
    : "";
}

/** A regra do `AdocaoIn.access_port` no backend, palavra por palavra: o campo
 * vale o mesmo que o gate recusa. Sem ela, um espaço no fim ou um ponto saem no
 * 422 do Pydantic — em inglês — numa tela em português. */
const PORTA_VALIDA = /^[A-Za-z0-9/-]+$/;

/** Os tetos do schema, espelhados campo a campo (`AdocaoIn.circuit_code`,
 * `AdocaoIn.access_port`, `AdocaoIn.edge_trunk`, `OrganizationCreate.name`,
 * `AdocaoSessaoIn.password_ref`). Acima deles o serviço devolve o mesmo 422 do
 * Pydantic, e o número mora aqui para a frase do campo não divergir do gate. */
const LIMITE_DA_PORTA = 64;
const LIMITE_DO_CODE = 64;
const LIMITE_DO_TRUNK = 64;
const LIMITE_DO_NOME = 128;
const LIMITE_DO_CAMINHO = 255;

/** O teto do schema (`CircuitCreate.velocidade_mbps`), espelhado. */
const LIMITE_DA_VELOCIDADE = 100000;

/** A forma do texto que a conferência manda na query (`velocidade_mbps`) e que o
 * servidor parseia como `int`: só dígitos. O campo é `type="number"` e mantém
 * `1e3` e `1.0` — o `Number()` os lê como 1000 e 1, mas o `int` os recusa com
 * 422, e a tela ficava sem dizer qual campo corrigir. Com só dígitos, `0100`
 * continua sendo texto válido e distinto de `100` na assinatura, porque o que a
 * assinatura compara é o que o operador digitou. */
const VELOCIDADE_VALIDA = /^\d+$/;

/** O trunk, o código e a velocidade são digitados: a espera é o que segura a
 * enxurrada de consultas — cada conferência roda um render do equipamento
 * inteiro no servidor. */
const ESPERA_DA_IDENTIDADE_MS = 300;

/** Os tetos e o piso do `AdocaoUpstreamIn.name`, espelhados do schema. */
const MINIMO_DO_NOME_DO_UPSTREAM = 2;
const LIMITE_DO_NOME_DO_UPSTREAM = 128;

/** A regra do `NOME_DE_POLITICA_RE` do serviço (`schemas.py`, §25.4), palavra
 * por palavra: o nome vai para a configuração do equipamento, e o que o serviço
 * recusa tem de ser recusado aqui antes — com a frase desta tela, e não com o
 * 422 do Pydantic em inglês. */
const NOME_DE_POLITICA = /^[A-Za-z0-9_.\-]{1,63}$/;
const LIMITE_DO_NOME_DE_POLITICA = 63;
const MENSAGEM_DA_POLITICA =
  `O nome da route-policy aceita até ${LIMITE_DO_NOME_DE_POLITICA} caracteres, `
  + "com letras, números, ponto, hífen e sublinhado.";

/** O tipo da organização na revisão (§5.5): o palpite do `_classificar` abre o
 * select, e é o operador quem decide. */
type KindDaOrganizacao = "downstream" | "parceiro" | "operadora";

/** O modo do bloco de upstream (§5.2): o enlace de cliente não tem bloco. */
type ModoDoUpstream = "nenhum" | "vincular" | "criar";

/** O produto da importação (`AdocaoUpstreamIn.produto_import`): vazio é o
 * mesmo `null`, e o produto sai do tipo do upstream. */
type ProdutoDoUpstream = "" | "full" | "parcial" | "default";

/** O papel do vínculo (`upstream_circuits.papel`). */
type PapelDoUpstream = "principal" | "contingencia";

/** Os campos que compõem o bloco `upstream` da revisão — o que o helper lê. */
type FormDoUpstream = {
  upstreamModo: ModoDoUpstream;
  /** O id como o operador o escolheu (o `<select>` devolve texto): vazio é
   * "nenhum vínculo escolhido", e é o que o helper recusa. */
  upstreamId: string;
  upstreamNome: string;
  upstreamTipo: UpstreamTipo;
  upstreamProduto: ProdutoDoUpstream;
  upstreamPapel: PapelDoUpstream;
};

/** O bloco `upstream` da revisão, ou `undefined` quando não há bloco.
 *
 * Nos dois modos: vincular manda só o `upstream_id` (o resto é o upstream da
 * SoT, e o serviço recusa os campos de criação junto com ele); criar manda os
 * campos digitados. `nenhum` não manda nada — é o enlace de cliente. */
function blocoDoUpstream(form: FormDoUpstream) {
  if (form.upstreamModo === "vincular") {
    // Sem id não há vínculo, e `Number("")` seria 0: o id sentinela viajaria à
    // conferência como um upstream de verdade, e o ensaio compararia o enlace
    // de outro.
    if (!/^\d+$/.test(form.upstreamId)) return undefined;
    return { upstream_id: Number(form.upstreamId), papel: form.upstreamPapel };
  }
  if (form.upstreamModo === "criar") {
    return {
      name: form.upstreamNome.trim(),
      tipo: form.upstreamTipo,
      produto_import: form.upstreamProduto || null,
      papel: form.upstreamPapel,
    };
  }
  return undefined;
}

/** O nome de política que a proposta leu do equipamento, como texto.
 *
 * O campo das sessões da proposta é genérico (`Record<string, unknown>`): a
 * leitura pode não ter achado a diretiva na configuração, e ausente é o mesmo
 * que vazio — a revisão abre o campo em branco, e a adoção grava o nome padrão
 * do gerenet. */
const nomeLido = (valor: unknown) => (typeof valor === "string" ? valor : "");

/** Um bloco do registro na lista da revisão: o `marcado` é a escolha do
 * operador e o `conflito` é o estado do bloco na SoT (§7). */
type BlocoDoRegistro = {
  prefix: string;
  family: string;
  conflito: string | null;
  marcado: boolean;
};

/** A revisão de uma proposta (design §6). Montada pela página com `key` por
 * proposta, para o estado do formulário não vazar de uma para a outra.
 *
 * É a única superfície onde o `ciente` aparece: ele gateia o aceite, e não a
 * exibição do diff — as diferenças são para ler antes de decidir.
 */
export function AdocaoDialog({
  proposta,
  onFechar,
  onAdotada,
}: {
  proposta: DiscoveryPropostaOut;
  onFechar: () => void;
  /** O circuito que nasceu da proposta: o relato mora fora do diálogo, que
   * fecha no sucesso (como o dos ignorados). */
  onAdotada: (circuitId: number) => void;
}) {
  const { data: devices } = useDevices();
  // As desativadas aparecem, com o rótulo: a proposta pode apontar para uma
  // organização que não está mais ativa, e escondê-la deixaria o `<select>`
  // exibindo a primeira opção ("Criar a nova") enquanto o POST manda o id da
  // invisível — o operador leria "criar" e o circuito nasceria pendurado numa
  // organização que a tela nunca mostrou.
  const { data: organizacoes } = useOrganizations({ includeDisabled: true });
  const { data: policyProfiles } = usePolicyProfiles();
  // Os upstreams da SoT: o vínculo do §5.2 escolhe um deles pelo id.
  const { data: upstreams } = useUpstreams();
  const adotar = useAdotar();
  const prefill = usePrefill();
  const [code, setCode] = useState(proposta.circuit_code_sugerido ?? "");
  const [acesso, setAcesso] = useState<number>(0);
  const [porta, setPorta] = useState("");
  const [trunk, setTrunk] = useState(trunkDoNome(proposta));
  const [orgId, setOrgId] = useState<number>(proposta.organizacao_id ?? 0);
  const [orgNome, setOrgNome] = useState(proposta.organizacao_sugerida ?? "");
  // O palpite do `_classificar` (§5.5) abre o select, e é só isso que ele faz:
  // quem decide o tipo da organização é o operador. A classificação é por
  // CANDIDATO, e a proposta traz a lista deles — o enlace de upstream é o que
  // tem um peer classificado assim.
  const [kind, setKind] = useState<KindDaOrganizacao>(() =>
    proposta.candidatos.some((c) => c.classificacao === "upstream") ? "operadora" : "downstream",
  );
  // O bloco do upstream (§5.2). Nasce em `nenhum`: o enlace de cliente é o caso
  // comum, e o select do `kind` é que abre o bloco quando a organização é
  // operadora.
  const [upstreamModo, setUpstreamModo] = useState<ModoDoUpstream>("nenhum");
  const [upstreamId, setUpstreamId] = useState("");
  const [upstreamNome, setUpstreamNome] = useState("");
  const [upstreamTipo, setUpstreamTipo] = useState<UpstreamTipo>("transito");
  const [upstreamProduto, setUpstreamProduto] = useState<ProdutoDoUpstream>("");
  const [upstreamPapel, setUpstreamPapel] = useState<PapelDoUpstream>("principal");
  const [velocidade, setVelocidade] = useState(
    proposta.velocidade_mbps === null ? "" : String(proposta.velocidade_mbps),
  );
  const [blocosDoRegistro, setBlocosDoRegistro] = useState<BlocoDoRegistro[]>([]);
  const [avisosDoRegistro, setAvisosDoRegistro] = useState<string[]>([]);
  // A `criarOrg` sobe para cá porque a assinatura abaixo a lê: ela é quem decide
  // qual das duas metades da organização — o nome da nova ou a id da existente —
  // entra na conferência.
  const criarOrg = orgId === 0;
  // Os blocos livres e marcados são uma lista só para as duas pontas que a
  // consomem: o POST da adoção e o ensaio. O `_bloco_import` só emite o filtro
  // de importação para as autorizações ativas da organização, então marcar ou
  // desmarcar uma caixa muda o render — e o diff ao vivo tem de ser o do que a
  // escrita vai gravar, não o de outra lista parecida (item 14).
  const blocosMarcados = criarOrg
    ? blocosDoRegistro.filter((b) => b.marcado && b.conflito === null)
    : [];
  // O bloco do upstream, montado UMA vez: é ele que o corpo da adoção manda e é
  // ele que a conferência recebe (§5.4), e dois objetos iguais montados em dois
  // lugares divergem no primeiro campo que um dos dois ganhar.
  const upstreamDaRevisao = blocoDoUpstream({
    upstreamModo, upstreamId, upstreamNome, upstreamTipo, upstreamProduto, upstreamPapel,
  });
  // O que o operador digitou, como assinatura: é ela que a espera observa e é
  // dela que sai o objeto da conferência. Comparar o objeto direto refaria a
  // consulta a cada render, porque cada render cria um objeto novo.
  const assinaturaDaIdentidade = JSON.stringify({
    edgeTrunk: trunk,
    circuitCode: code,
    organizacaoId: criarOrg ? 0 : orgId,
    organizacaoNome: criarOrg ? orgNome.trim() : "",
    // O `kind` e o bloco entram na identidade pela mesma razão que a
    // organização: o ensaio monta a organização descartável com esse tipo e
    // despacha o enlace pelo vínculo — o diff de um enlace de operadora não é o
    // de um de cliente, e o aceite não viaja entre os dois.
    organizacaoKind: kind,
    upstream: upstreamDaRevisao,
    velocidade,
    // A forma `família:prefixo` é a do query string (a mesma ordem dos campos do
    // `AdocaoAutorizacaoIn`, com os dois-pontos no meio): o prefixo de IPv6 é
    // cheio deles, e é a rota que faz o corte no primeiro.
    autorizacoes: blocosMarcados.map((b) => `${b.family}:${b.prefix}`),
  });
  const [identidadeDaConferencia, setIdentidadeDaConferencia] = useState<IdentidadeDaConferencia>(
    () => JSON.parse(assinaturaDaIdentidade) as IdentidadeDaConferencia,
  );
  const [razaoSocial, setRazaoSocial] = useState("");
  const [documento, setDocumento] = useState("");
  const [asSet, setAsSet] = useState("");
  const [ciente, setCiente] = useState(false);
  // Os perfis vêm ANTES da conferência: ela é refeita quando eles mudam, porque
  // o corpo da política de exportação depende do produto escolhido.
  const [perfis, setPerfis] = useState<Record<string, { import?: number; export?: number }>>({});
  // O caminho do segredo, por família. Fica FORA dos perfis de propósito: ele
  // não entra na conferência — o ensaio não tem o valor da senha, e a SoT
  // guarda o caminho no Vault, nunca o valor.
  const [caminhos, setCaminhos] = useState<Record<string, string>>({});
  // O nome da route-policy lido no equipamento, por família (§4.3): a revisão o
  // mostra com o botão de limpar, e adotar é decidir mantê-lo ou limpá-lo.
  // Vazio não é um nome vazio no corpo — é o campo AUSENTE, e o serviço o lê
  // como "o nome padrão do gerenet" (`_DO_OPERADOR`).
  //
  // A semente sai de um estado inicial, e não de um efeito: o diálogo é montado
  // com `key` por proposta (`Discovery.tsx`), então este estado nasce uma vez
  // por revisão — que é o mesmo que o efeito prometeria, sem o render extra.
  const [politicas, setPoliticas] = useState<Record<string, { import: string; export: string }>>(
    () =>
      Object.fromEntries(
        proposta.sessoes.map((s) => [
          s.afi,
          { import: nomeLido(s.import_route_policy), export: nomeLido(s.export_route_policy) },
        ]),
      ),
  );
  const { data: fidelidade, error: erroDaConferencia } = useFidelidade(
    proposta.device_id, proposta.vrf, proposta.subinterface, perfis, identidadeDaConferencia,
  );

  // A identidade digitada só entra na consulta depois da última tecla.
  useEffect(() => {
    const timer = setTimeout(
      () => setIdentidadeDaConferencia(JSON.parse(assinaturaDaIdentidade) as IdentidadeDaConferencia),
      ESPERA_DA_IDENTIDADE_MS,
    );
    return () => clearTimeout(timer);
  }, [assinaturaDaIdentidade]);

  const setPerfil = (afi: string, valores: { import?: number; export?: number }) =>
    setPerfis((atual) => ({ ...atual, [afi]: { ...atual[afi], ...valores } }));
  const setCaminho = (afi: string, valor: string) =>
    setCaminhos((atual) => ({ ...atual, [afi]: valor }));
  const setPolitica = (afi: string, campo: "import" | "export", valor: string) =>
    setPoliticas((atual) => ({
      ...atual,
      [afi]: { ...(atual[afi] ?? { import: "", export: "" }), [campo]: valor },
    }));
  /** O botão de limpar: o campo volta ao nome padrão do gerenet. */
  const limparPolitica = (afi: string, campo: "import" | "export") =>
    setPolitica(afi, campo, "");

  const diferencas = fidelidade?.diferencas ?? [];
  const mudam = diferencas.filter((d) => d.exige_ciente);
  // O grupo do que a SoT não gerencia é por LINHA, e não por contexto: o
  // contexto `subinterface` traz, no mesmo objeto, o que mudaria o equipamento
  // (`sobrando`/`faltando`) e o que ela não emite (`description` e `mtu`). O
  // segundo é visível e não bloqueia (§6 do design); um filtro por contexto o
  // esconderia justamente quando há mudança no mesmo bloco.
  const naoGerenciadas = diferencas.flatMap((d) => d.nao_gerenciado);
  const ensaio = diferencas.filter((d) => d.contexto === "ensaio");
  // O aceite é sobre ESTAS diferenças (§6): refeita a conferência — outro
  // perfil de exportação, outro trunk —, o que está na tela já não é o que o
  // operador leu, e a caixa marcada assumiria linhas que ninguém viu. Só o que
  // gateia entra na assinatura: o que a SoT não gerencia não é assumido por
  // ninguém, e sozinho não invalida o aceite.
  //
  // `null` é a consulta em voo, e não um diff vazio: a conferência antiga sai da
  // tela enquanto a nova não chega (sem `placeholderData`), e ler esse intervalo
  // como "as diferenças mudaram" zeraria o aceite a cada tecla do trunk, mesmo
  // quando o diff que volta é o mesmo. O que zera é a assinatura DIFERENTE da
  // última que a tela mostrou.
  const assinaturaDoAceite =
    fidelidade === undefined
      ? null
      : mudam.flatMap((d) => [d.contexto, ...d.sobrando, ...d.faltando]).join("|");
  const ultimaAssinatura = useRef<string | null>(null);
  useEffect(() => {
    if (assinaturaDoAceite === null || assinaturaDoAceite === ultimaAssinatura.current) return;
    ultimaAssinatura.current = assinaturaDoAceite;
    setCiente(false);
  }, [assinaturaDoAceite]);

  // O trunk é exigido sempre que a proposta tem vid e subinterface. O serviço só
  // o exige quando o nome deriva um (`_trunk_da_subinterface`), então num nome
  // de subinterface fora da convenção a tela pede um valor que ele não pediria.
  // Nunca é beco sem saída (qualquer valor serve, e nome livre é legítimo), e o
  // desencontro fica registrado no relatório, para o runbook.
  const exigirTrunk = proposta.vid !== null && proposta.subinterface !== null;
  // A proposta sem ASN remoto chega com conflito e o Adotar da lista fica
  // barrado: aqui é defesa em profundidade, para o corpo não mandar um ASN
  // sentinela que o serviço recusaria.
  const asnRemoto = proposta.candidatos[0]?.asn_remote ?? null;
  const portaInvalida =
    porta !== "" && (porta.length > LIMITE_DA_PORTA || !PORTA_VALIDA.test(porta));
  const nomeLongo = orgNome.trim().length > LIMITE_DO_NOME;
  const caminhoLongo = (afi: string) =>
    (caminhos[afi] ?? "").trim().length > LIMITE_DO_CAMINHO;
  // O nome do upstream criado tem o piso e o teto do schema (§5.2): um nome de
  // uma letra o `AdocaoUpstreamIn` recusa, e é a mesma frase da tela.
  const nomeDoUpstream = upstreamNome.trim();
  const nomeDoUpstreamInvalido =
    nomeDoUpstream.length < MINIMO_DO_NOME_DO_UPSTREAM ||
    nomeDoUpstream.length > LIMITE_DO_NOME_DO_UPSTREAM;
  // O nome lido só entra na revisão pela mão do operador: se ele mantém um nome
  // fora da regra do serviço, a adoção seria recusada depois do clique — e o
  // campo não diria qual dos dois nomes corrigir.
  const politicaInvalida = (afi: string, campo: "import" | "export") => {
    const nome = (politicas[afi]?.[campo] ?? "").trim();
    return nome !== "" && !NOME_DE_POLITICA.test(nome);
  };
  // A forma vem antes da faixa: com o `Number()` decidindo sozinho, `1e3` e
  // `1.0` passavam como 1000 e 1 — inteiros e dentro da faixa —, mas o `int` do
  // servidor recusava o texto cru que a conferência manda, e o operador ficava
  // preso sem saber qual campo corrigir (item 18). As bordas são aparadas
  // porque o `int()` do Python também as apara; com só dígitos a faixa é lida
  // sem risco de `NaN`.
  const velocidadeTexto = velocidade.trim();
  const velocidadeNumero = velocidadeTexto === "" ? null : Number(velocidadeTexto);
  const velocidadeInvalida =
    velocidade !== "" &&
    (!VELOCIDADE_VALIDA.test(velocidadeTexto) ||
      (velocidadeNumero as number) <= 0 ||
      (velocidadeNumero as number) > LIMITE_DA_VELOCIDADE);
  // A identidade digitada e a da conferência têm de ser a mesma. Entre a tecla e
  // a consulta nova vai a espera inteira, e nela o diff na tela ainda é o da
  // identidade anterior — o trunk, o código, a organização e a velocidade entram
  // todos no ensaio, então qualquer um deles muda o que o render produz. E o
  // `ciente` é um booleano sem vínculo com o diff que assumiu: um aceite marcado
  // contra o diff velho viajaria idêntico com a identidade nova. O servidor
  // recalcula o diff e recusa o que ninguém assumiu, mas não tem como saber
  // contra qual deles o aceite foi dado.
  const identidadeConferida =
    assinaturaDaIdentidade === JSON.stringify(identidadeDaConferencia);
  // O que o formulário exige antes do aceite: os campos que a configuração do
  // edge não tem e que, vazios, fora da forma ou acima do tamanho do schema,
  // voltariam como o 422 do Pydantic em vez de uma frase desta tela.
  const revisaoIncompleta =
    code === "" ||
    code.length > LIMITE_DO_CODE ||
    acesso === 0 ||
    porta === "" ||
    portaInvalida ||
    (exigirTrunk && trunk === "") ||
    trunk.length > LIMITE_DO_TRUNK ||
    velocidadeInvalida ||
    (criarOrg && (orgNome.trim() === "" || nomeLongo || asnRemoto === null)) ||
    (kind === "operadora" &&
      ((upstreamModo === "vincular" && upstreamDaRevisao === undefined) ||
        (upstreamModo === "criar" && nomeDoUpstreamInvalido))) ||
    proposta.candidatos.some((c) => caminhoLongo(c.afi)) ||
    proposta.candidatos.some((c) => politicaInvalida(c.afi, "import") || politicaInvalida(c.afi, "export"));
  // Sem a conferência não há aceite que valha (§6): o ensaio recusado devolve a
  // comparação que não pôde ser feita, e é o mesmo caso da consulta que não
  // voltou. O servidor recusa os dois de qualquer forma; aqui é o que impede o
  // operador de aceitar sobre uma comparação que nenhum dos dois lados viu, e o
  // ciente não libera nenhum deles — não há diferença que valha assumir.
  const semConferencia = fidelidade === undefined || ensaio.length > 0;
  // O par de frases do §5.1, o mesmo do serviço — sem as crases, que aqui são
  // ruído. O `kind` e o bloco andam juntos: a operadora sem vínculo é o estado
  // em que o render despacha o enlace como cliente enquanto o conjunto de
  // autorizações sai do caminho da operadora. Quem recusa é o backend (a guarda
  // roda antes da conferência); isto é a cortesia que evita o 422 depois do
  // clique.
  const recusaDoUpstream =
    kind === "operadora" && upstreamDaRevisao === undefined
      ? "A organização é operadora e a revisão não traz o bloco de upstream."
      : kind !== "operadora" && upstreamDaRevisao !== undefined
        ? "O bloco de upstream exige organização operadora."
        : null;
  const podeAdotar =
    !revisaoIncompleta &&
    !semConferencia &&
    identidadeConferida &&
    recusaDoUpstream === null &&
    (mudam.length === 0 || ciente) &&
    !adotar.isPending;

  // Depois de uma consulta explícita os três campos abaixo mostram o que o
  // registro disse: um CNPJ vazio diz, com honestidade, que o registro não tem
  // CNPJ para este ASN — manter um valor que o registro acabou de não confirmar
  // seria uma mentira que o operador adotaria junto. O nome é a exceção: ele já
  // chega sugerido pela descoberta, e apagá-lo jogaria fora um valor que o
  // operador nunca digitou.
  const buscarNoRegistro = () => {
    if (asnRemoto === null) return;
    prefill.mutate(asnRemoto, {
      onSuccess: (dados: OrganizationPrefillOut) => {
        const nome = dados.nome ?? dados.razao_social ?? "";
        if (nome !== "") setOrgNome(nome);
        setRazaoSocial(dados.razao_social ?? "");
        setDocumento(dados.documento ?? "");
        setAsSet(dados.as_set_sugerido ?? "");
        setBlocosDoRegistro(
          dados.blocos.map((b) => ({
            prefix: b.prefix,
            family: b.family,
            conflito: b.conflito,
            // O bloco em uso por outra organização nasce desmarcado (§7).
            marcado: b.conflito === null,
          })),
        );
        setAvisosDoRegistro(dados.avisos);
      },
    });
  };

  const adotarProposta = () => {
    let organizacaoNova: {
      name: string; kind: KindDaOrganizacao; asn: number;
      legal_name: string | null; document: string | null; irr_as_set: string | null;
    } | null = null;
    if (criarOrg) {
      // Inalcançável pela tela: a proposta sem ASN remoto é conflito e nem abre
      // esta revisão. O early return é o gate explícito do ASN que o corpo
      // precisa — sem ele o valor só existiria como 0, e o serviço o recusaria
      // por conta própria ("A proposta não tem ASN remoto").
      if (asnRemoto === null) return;
      // O nome vai aparado: é ele que o gate mede quando diz que está
      // preenchido, e um espaço invisível faz uma organização repetida passar
      // por nova.
      organizacaoNova = {
        // O tipo é a escolha da revisão (§5.5), e não mais um `downstream`
        // fixo: é ela que diz ao serviço se o enlace tem bloco de upstream.
        name: orgNome.trim(), kind, asn: asnRemoto,
        legal_name: razaoSocial.trim() || null,
        document: documento.trim() || null,
        irr_as_set: asSet.trim() || null,
      };
    }
    adotar.mutate(
      {
        device_id: proposta.device_id, vrf: proposta.vrf,
        subinterface: proposta.subinterface, circuit_code: code,
        access_device_id: acesso, access_port: porta,
        edge_trunk: trunk || null,
        velocidade_mbps: velocidadeNumero,
        organizacao_id: criarOrg ? null : orgId,
        organizacao_nova: organizacaoNova,
        // O MESMO bloco que a conferência recebeu: montá-lo de novo aqui é
        // como os dois divergem — e o diff que o operador leu deixaria de ser o
        // da escrita.
        upstream: upstreamDaRevisao,
        // Só os blocos livres e marcados: o conflitante a API recusaria, e o
        // desmarcado o operador não quis. É a lista que a conferência já
        // recebeu, na forma do corpo.
        autorizacoes: blocosMarcados.map((b) => ({ prefix: b.prefix, family: b.family })),
        // A lista sai das SESSÕES da proposta, e não dos candidatos: quem casa a
        // revisão com o que a leitura entregou é o `_sessao_da_proposta` do
        // serviço, pela família, e uma família sem sessão — o endereço que não é
        // nenhuma das duas pontas do par, `ponta_incoerente` no motor — viajaria
        // como uma sessão que não existe. É aí que as duas listas divergem, e o
        // payload segue a que a guarda do serviço confere.
        sessoes: proposta.sessoes.map((s) => {
          const politica = politicas[s.afi];
          const importada = politica?.import.trim() ?? "";
          const exportada = politica?.export.trim() ?? "";
          return {
            afi: s.afi,
            import_profile_id: perfis[s.afi]?.import || null,
            export_profile_id: perfis[s.afi]?.export || null,
            // Só o caminho: o valor do segredo nunca passa por esta tela.
            password_ref: caminhos[s.afi]?.trim() || null,
            // O nome lido só viaja quando o operador o mantém; ausente, o
            // serviço grava o nome padrão do gerenet (§25.4) — que é o que o
            // botão de limpar promete. Um nome vazio mandado como `""` seria
            // outra coisa, e a chave só aparece quando há o que gravar.
            ...(importada === "" ? {} : { import_route_policy: importada }),
            ...(exportada === "" ? {} : { export_route_policy: exportada }),
          };
        }),
        ciente,
      },
      {
        // A lista já refeita é o que mostra o desfecho: a proposta adotada sai
        // dela, como a linha do peer ignorado sai da de ignorados. Sem fechar, o
        // diálogo ficaria aberto sobre uma proposta que já não existe — e o
        // segundo clique responderia 404. O relato do circuito que nasceu fica
        // fora dele, com o dos ignorados.
        onSuccess: (adocao) => {
          onAdotada(adocao.circuit_id);
          onFechar();
        },
      },
    );
  };

  return (
    <Modal aberto titulo={`Adotar VLAN ${proposta.vid ?? "—"}`} onFechar={onFechar}>
      <section>
        <h3>O que será gravado</h3>
        <ul>
          {/* As reservas primeiro (§6 do design: VID, rede e ponta): a VLAN sai
              com o `kind` porque o enlace empilhado reserva uma **S-VLAN**, e
              isso não aparece em nenhum outro lugar da revisão — nem no título,
              que diz só o número. */}
          {proposta.vlans.map((v) => (
            <li key={`vlan-${v.vid}`}>
              {v.kind === "s_vlan" ? "S-VLAN" : "VLAN"} {v.vid}
            </li>
          ))}
          {proposta.prefixos.map((p) => (
            <li key={p.network}>
              {p.network} (ponta {p.ponta_local})
            </li>
          ))}
          {proposta.candidatos.map((c) => (
            <li key={`${c.afi}-${c.remote_address}`}>
              {c.remote_address} AS{c.asn_remote} ({c.classificacao})
            </li>
          ))}
        </ul>
      </section>

      <FormField
        label="Código do circuito *"
        erro={code.length > LIMITE_DO_CODE ? `O código do circuito aceita até ${LIMITE_DO_CODE} caracteres.` : undefined}
      >
        <input value={code} onChange={(e) => setCode(e.target.value)} />
      </FormField>
      <FormField label="Equipamento de acesso *" help={help("adocao.acesso")}>
        <select value={acesso} onChange={(e) => setAcesso(Number(e.target.value))}>
          <option value={0}>Selecione…</option>
          {(devices ?? []).map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </FormField>
      <FormField
        label="Porta de acesso *"
        erro={portaInvalida ? `A porta aceita só letras, números, / e - (até ${LIMITE_DA_PORTA} caracteres).` : undefined}
      >
        <input value={porta} onChange={(e) => setPorta(e.target.value)} />
      </FormField>
      <FormField
        label={exigirTrunk ? "Trunk do edge *" : "Trunk do edge"}
        help={help("adocao.trunk")}
        erro={trunk.length > LIMITE_DO_TRUNK ? `O trunk do edge aceita até ${LIMITE_DO_TRUNK} caracteres.` : undefined}
      >
        <input value={trunk} onChange={(e) => setTrunk(e.target.value)} />
      </FormField>
      {/* O campo nasce com a velocidade que a leitura achou no `qos car` do
          equipamento: é ela que a adoção grava se ninguém mexer, e é ela que
          entra no ensaio. */}
      <FormField
        label="Velocidade (Mbps)"
        help={help("adocao.velocidade")}
        erro={
          velocidadeInvalida
            ? `A velocidade aceita de 1 a ${LIMITE_DA_VELOCIDADE} Mbps.`
            : undefined
        }
      >
        <input
          type="number"
          min={1}
          max={LIMITE_DA_VELOCIDADE}
          value={velocidade}
          onChange={(e) => setVelocidade(e.target.value)}
        />
      </FormField>
      <FormField label="Organização" help={help("adocao.organizacao")}>
        <select value={orgId} onChange={(e) => setOrgId(Number(e.target.value))}>
          <option value={0}>Criar a nova: {orgNome || "(informe o nome)"}</option>
          {(organizacoes ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.name} (AS{o.asn ?? "—"}){o.admin_status ? "" : " (desativada)"}
            </option>
          ))}
        </select>
      </FormField>
      {/* O tipo da organização vale para as duas metades do campo acima: criar
          a nova (o `kind` vai no corpo) ou escolher uma da lista (o tipo é o
          dela na SoT, e o serviço o lê de lá — aqui o select diz ao operador
          qual enlace ele está montando, e é ele que o ensaio recebe). */}
      <FormField label="Tipo de organização" help={help("adocao.kind")}>
        <select value={kind} onChange={(e) => setKind(e.target.value as KindDaOrganizacao)}>
          <option value="downstream">downstream</option>
          <option value="parceiro">parceiro</option>
          <option value="operadora">operadora</option>
        </select>
      </FormField>
      {criarOrg && (
        <>
          <FormField
            label="Nome da organização nova *"
            erro={
              orgNome.trim() === ""
                ? "Informe o nome da organização nova."
                : nomeLongo
                  ? `O nome da organização aceita até ${LIMITE_DO_NOME} caracteres.`
                  : undefined
            }
          >
            <input value={orgNome} onChange={(e) => setOrgNome(e.target.value)} />
          </FormField>
          <section>
            <button
              type="button"
              onClick={buscarNoRegistro}
              disabled={prefill.isPending || asnRemoto === null}
            >
              {prefill.isPending ? "Consultando o registro…" : "Buscar no registro"}
            </button>
            {/* O que o registro devolve é sugestão: os campos acima seguem
                editáveis, e nada é gravado antes do Adotar. */}
            {prefill.error && (
              <p role="alert">
                {prefill.error instanceof ApiError
                  ? prefill.error.message
                  : "Falha ao consultar o registro."}
              </p>
            )}
            {avisosDoRegistro.map((aviso, i) => (
              <p key={`aviso-${i}`} role="status">{aviso}</p>
            ))}
          </section>
          <FormField label="Razão social" help={help("adocao.razao_social")}>
            <input value={razaoSocial} onChange={(e) => setRazaoSocial(e.target.value)} />
          </FormField>
          <FormField label="Documento (CNPJ/ownerid)" help={help("adocao.documento")}>
            <input value={documento} onChange={(e) => setDocumento(e.target.value)} />
          </FormField>
          <FormField label="AS-SET (IRR)" help={help("adocao.as_set")}>
            <input value={asSet} onChange={(e) => setAsSet(e.target.value)} />
          </FormField>
          {blocosDoRegistro.length > 0 && (
            <section>
              <h3>Blocos alocados no registro</h3>
              <ul>
                {blocosDoRegistro.map((b, i) => (
                  // A chave é a posição: o prefixo é editável, e uma chave que
                  // muda a cada tecla remontaria o input e perderia o foco. A
                  // lista não reordena.
                  <li key={i}>
                    <input
                      type="checkbox"
                      aria-label={`Incluir ${b.prefix}`}
                      checked={b.marcado}
                      disabled={b.conflito !== null}
                      onChange={() =>
                        setBlocosDoRegistro((atual) =>
                          atual.map((x) => (x === b ? { ...x, marcado: !x.marcado } : x)),
                        )
                      }
                    />
                    <input
                      aria-label={`Prefixo do bloco ${i + 1}`}
                      value={b.prefix}
                      disabled={b.conflito !== null}
                      onChange={(e) =>
                        setBlocosDoRegistro((atual) =>
                          atual.map((x) => (x === b ? { ...x, prefix: e.target.value } : x)),
                        )
                      }
                    />
                    <span> ({b.family})</span>
                    {b.conflito !== null && <span> — em uso por {b.conflito}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {/* O bloco do upstream (§5.2): o enlace de operadora vincula um upstream
          da SoT ou cria o novo. Ele aparece com a operadora — e continua
          visível se o operador trocou o tipo depois de preenchê-lo: escondido,
          a revisão travada pela recusa do §5.1 não diria o que desfazer, e o
          único caminho de volta seria adivinhar. */}
      {(kind === "operadora" || upstreamModo !== "nenhum") && (
        <fieldset>
          <legend>Upstream</legend>
          <FormField label="Modo do upstream" help={help("adocao.upstream")}>
            <select
              value={upstreamModo}
              onChange={(e) => setUpstreamModo(e.target.value as ModoDoUpstream)}
            >
              <option value="nenhum">—</option>
              <option value="vincular">Vincular a um existente</option>
              <option value="criar">Criar o novo</option>
            </select>
          </FormField>
          {upstreamModo === "vincular" && (
            <FormField
              label="Upstream existente *"
              erro={
                upstreamId === "" ? "Escolha o upstream a vincular." : undefined
              }
            >
              <select value={upstreamId} onChange={(e) => setUpstreamId(e.target.value)}>
                <option value="">Selecione…</option>
                {/* O vínculo é por id, e é só o id que vai no corpo: o resto é
                    o cadastro do upstream, que a SoT já tem. */}
                {(upstreams ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    #{u.id} — {u.name}
                  </option>
                ))}
              </select>
            </FormField>
          )}
          {upstreamModo === "criar" && (
            <>
              <FormField
                label="Nome do upstream *"
                erro={
                  nomeDoUpstreamInvalido
                    ? `O nome do upstream aceita de ${MINIMO_DO_NOME_DO_UPSTREAM} a ${LIMITE_DO_NOME_DO_UPSTREAM} caracteres.`
                    : undefined
                }
              >
                <input
                  value={upstreamNome}
                  onChange={(e) => setUpstreamNome(e.target.value)}
                />
              </FormField>
              <FormField label="Tipo do upstream">
                <select
                  value={upstreamTipo}
                  onChange={(e) => setUpstreamTipo(e.target.value as UpstreamTipo)}
                >
                  <option value="transito">Trânsito</option>
                  <option value="ix">IX</option>
                  <option value="pni">PNI</option>
                  <option value="contingencia">Contingência</option>
                </select>
              </FormField>
              {/* Os mesmos rótulos do cadastro do upstream: "Tipo de policy" é
                  o produto da importação, e "Papel" é o do vínculo. */}
              <FormField label="Tipo de policy" help={help("adocao.produto_import")}>
                <select
                  value={upstreamProduto}
                  onChange={(e) => setUpstreamProduto(e.target.value as ProdutoDoUpstream)}
                >
                  <option value="">—</option>
                  <option value="full">Full</option>
                  <option value="parcial">Parcial</option>
                  <option value="default">Default</option>
                </select>
              </FormField>
              <FormField label="Papel">
                <select
                  value={upstreamPapel}
                  onChange={(e) => setUpstreamPapel(e.target.value as PapelDoUpstream)}
                >
                  <option value="principal">Principal</option>
                  <option value="contingencia">Contingência</option>
                </select>
              </FormField>
            </>
          )}
        </fieldset>
      )}
      {/* Fora do `fieldset`: a recusa do segundo caso só existe com o bloco
          preenchido e o tipo já trocado — e aí o bloco está à vista, logo
          acima, com o modo a corrigir. */}
      {recusaDoUpstream !== null && <p role="alert">{recusaDoUpstream}</p>}

      {proposta.candidatos.map((c) => (
        <div key={`${c.afi}-${c.remote_address}`}>
          <FormField label={`Perfil de importação (${c.afi})`}>
            <select
              value={perfis[c.afi]?.import ?? 0}
              onChange={(e) => setPerfil(c.afi, { import: Number(e.target.value) })}
            >
              <option value={0}>—</option>
              {(policyProfiles ?? []).filter((p) => p.direction === "import").map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </FormField>
          <FormField label={`Perfil de exportação (${c.afi})`}>
            <select
              value={perfis[c.afi]?.export ?? 0}
              onChange={(e) => setPerfil(c.afi, { export: Number(e.target.value) })}
            >
              <option value={0}>—</option>
              {(policyProfiles ?? []).filter((p) => p.direction === "export").map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </FormField>
          {/* O nome que a leitura achou no equipamento, por família (§4.3): o
              campo nasce com ele, e o botão ao lado o limpa — adotar é decidir
              manter o nome ou devolver o padrão do gerenet (§25.4). O nome não
              entra na conferência (a rota do `fidelidade` não o recebe): o diff
              da política continua sendo o do caminho de hoje. */}
          <FormField
            label={`Route-policy de importação (${c.afi})`}
            help={help("adocao.politica_import")}
            erro={politicaInvalida(c.afi, "import") ? MENSAGEM_DA_POLITICA : undefined}
          >
            <div className="politica-linha">
              <input
                value={politicas[c.afi]?.import ?? ""}
                onChange={(e) => setPolitica(c.afi, "import", e.target.value)}
              />
              <button
                type="button"
                aria-label={`Limpar a route-policy de importação (${c.afi})`}
                onClick={() => limparPolitica(c.afi, "import")}
              >
                Limpar
              </button>
            </div>
          </FormField>
          <FormField
            label={`Route-policy de exportação (${c.afi})`}
            help={help("adocao.politica_export")}
            erro={politicaInvalida(c.afi, "export") ? MENSAGEM_DA_POLITICA : undefined}
          >
            <div className="politica-linha">
              <input
                value={politicas[c.afi]?.export ?? ""}
                onChange={(e) => setPolitica(c.afi, "export", e.target.value)}
              />
              <button
                type="button"
                aria-label={`Limpar a route-policy de exportação (${c.afi})`}
                onClick={() => limparPolitica(c.afi, "export")}
              >
                Limpar
              </button>
            </div>
          </FormField>
          {/* O rótulo diz "caminho" antes do hover: um campo chamado "segredo"
              convida a colar a senha, e ela iria parar no render da
              configuração desejada, que é o que este campo existe para evitar. */}
          <FormField
            label={`Caminho do segredo no Vault (${c.afi})`}
            help={help("adocao.segredo")}
            erro={caminhoLongo(c.afi) ? `O caminho do segredo aceita até ${LIMITE_DO_CAMINHO} caracteres.` : undefined}
          >
            <input
              value={caminhos[c.afi] ?? ""}
              onChange={(e) => setCaminho(c.afi, e.target.value)}
            />
          </FormField>
        </div>
      ))}

      {mudam.length > 0 && (
        <section>
          <h3>Diferenças que mudariam o equipamento</h3>
          <ul>
            {mudam
              .flatMap((d) => d.sobrando.concat(d.faltando))
              // A mesma linha pode sair em dois contextos; a posição entra na
              // chave, como na lista de pendências do detalhe.
              .map((linha, i) => (
                <li key={`${i}-${linha}`}>{linha}</li>
              ))}
          </ul>
          <FormField label="Estou ciente destas diferenças" help={help("adocao.ciente")}>
            <input
              type="checkbox"
              checked={ciente}
              onChange={(e) => setCiente(e.target.checked)}
            />
          </FormField>
        </section>
      )}
      {naoGerenciadas.length > 0 && (
        <section>
          <h3>O que a SoT não gerencia</h3>
          <ul>
            {naoGerenciadas.map((linha, i) => (
              <li key={`${i}-${linha}`}>{linha}</li>
            ))}
          </ul>
        </section>
      )}
      {ensaio.length > 0 && (
        <p role="alert">
          A comparação não pôde ser feita para esta proposta, e sem ela não há aceite que valha.
          {/* O motivo é o que diz o que resolver: sem ele a recusa não instrui. */}
          {ensaio.map((d) => (d.explicacao === null ? "" : ` ${d.explicacao}`)).join("")}
        </p>
      )}
      {erroDaConferencia && (
        <p role="alert">
          {erroDaConferencia instanceof ApiError
            ? erroDaConferencia.message
            : "Falha ao conferir a fidelidade da proposta."}
        </p>
      )}

      {adotar.error && (
        <p role="alert">
          {adotar.error instanceof ApiError ? adotar.error.message : "Falha ao adotar."}
        </p>
      )}
      <div className="dialog-actions">
        <button type="button" onClick={onFechar}>Cancelar</button>
        <button type="button" disabled={!podeAdotar} onClick={adotarProposta}>
          Adotar
        </button>
      </div>
    </Modal>
  );
}
