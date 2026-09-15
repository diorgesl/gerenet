import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import {
  useAdotar,
  useDevices,
  useFidelidade,
  useOrganizations,
  usePolicyProfiles,
} from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { help } from "@/help";
import type { DiscoveryPropostaOut } from "@/api/types";

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

/** O trunk é digitado: a espera é o que segura a enxurrada de consultas. */
const ESPERA_DO_TRUNK_MS = 300;

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
  const adotar = useAdotar();
  const [code, setCode] = useState(proposta.circuit_code_sugerido ?? "");
  const [acesso, setAcesso] = useState<number>(0);
  const [porta, setPorta] = useState("");
  const [trunk, setTrunk] = useState(trunkDoNome(proposta));
  const [trunkDaConferencia, setTrunkDaConferencia] = useState(trunkDoNome(proposta));
  const [orgId, setOrgId] = useState<number>(proposta.organizacao_id ?? 0);
  const [orgNome, setOrgNome] = useState(proposta.organizacao_sugerida ?? "");
  const [ciente, setCiente] = useState(false);
  // Os perfis vêm ANTES da conferência: ela é refeita quando eles mudam, porque
  // o corpo da política de exportação depende do produto escolhido.
  const [perfis, setPerfis] = useState<Record<string, { import?: number; export?: number }>>({});
  // O caminho do segredo, por família. Fica FORA dos perfis de propósito: ele
  // não entra na conferência — o ensaio não tem o valor da senha, e a SoT
  // guarda o caminho no Vault, nunca o valor.
  const [caminhos, setCaminhos] = useState<Record<string, string>>({});
  const { data: fidelidade, error: erroDaConferencia } = useFidelidade(
    proposta.device_id, proposta.vrf, proposta.subinterface, perfis, trunkDaConferencia || null,
  );

  // O trunk digitado só entra na consulta depois da última tecla.
  useEffect(() => {
    const timer = setTimeout(() => setTrunkDaConferencia(trunk), ESPERA_DO_TRUNK_MS);
    return () => clearTimeout(timer);
  }, [trunk]);

  const setPerfil = (afi: string, valores: { import?: number; export?: number }) =>
    setPerfis((atual) => ({ ...atual, [afi]: { ...atual[afi], ...valores } }));
  const setCaminho = (afi: string, valor: string) =>
    setCaminhos((atual) => ({ ...atual, [afi]: valor }));

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
  const criarOrg = orgId === 0;
  // A proposta sem ASN remoto chega com conflito e o Adotar da lista fica
  // barrado: aqui é defesa em profundidade, para o corpo não mandar um ASN
  // sentinela que o serviço recusaria.
  const asnRemoto = proposta.candidatos[0]?.asn_remote ?? null;
  const portaInvalida =
    porta !== "" && (porta.length > LIMITE_DA_PORTA || !PORTA_VALIDA.test(porta));
  const nomeLongo = orgNome.trim().length > LIMITE_DO_NOME;
  const caminhoLongo = (afi: string) =>
    (caminhos[afi] ?? "").trim().length > LIMITE_DO_CAMINHO;
  // O trunk digitado e o da conferência têm de ser o mesmo. Entre a tecla e a
  // consulta nova vai a espera inteira, e nela o diff na tela ainda é o do valor
  // anterior; o `ciente` é um booleano sem vínculo com o diff que assumiu, então
  // um aceite marcado contra o diff velho viajaria idêntico com o trunk novo. O
  // servidor recalcula o diff e recusa o que ninguém assumiu, mas não tem como
  // saber contra qual deles o aceite foi dado.
  const trunkConferido = trunk === trunkDaConferencia;
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
    (criarOrg && (orgNome.trim() === "" || nomeLongo || asnRemoto === null)) ||
    proposta.candidatos.some((c) => caminhoLongo(c.afi));
  // Sem a conferência não há aceite que valha (§6): o ensaio recusado devolve a
  // comparação que não pôde ser feita, e é o mesmo caso da consulta que não
  // voltou. O servidor recusa os dois de qualquer forma; aqui é o que impede o
  // operador de aceitar sobre uma comparação que nenhum dos dois lados viu, e o
  // ciente não libera nenhum deles — não há diferença que valha assumir.
  const semConferencia = fidelidade === undefined || ensaio.length > 0;
  const podeAdotar =
    !revisaoIncompleta &&
    !semConferencia &&
    trunkConferido &&
    (mudam.length === 0 || ciente) &&
    !adotar.isPending;

  const adotarProposta = () => {
    let organizacaoNova: { name: string; kind: string; asn: number } | null = null;
    if (criarOrg) {
      // Inalcançável pela tela: a proposta sem ASN remoto é conflito e nem abre
      // esta revisão. O early return é o gate explícito do ASN que o corpo
      // precisa — sem ele o valor só existiria como 0, e o serviço o recusaria
      // por conta própria ("A proposta não tem ASN remoto").
      if (asnRemoto === null) return;
      // O nome vai aparado: é ele que o gate mede quando diz que está
      // preenchido, e um espaço invisível faz uma organização repetida passar
      // por nova.
      organizacaoNova = { name: orgNome.trim(), kind: "downstream", asn: asnRemoto };
    }
    adotar.mutate(
      {
        device_id: proposta.device_id, vrf: proposta.vrf,
        subinterface: proposta.subinterface, circuit_code: code,
        access_device_id: acesso, access_port: porta,
        edge_trunk: trunk || null,
        organizacao_id: criarOrg ? null : orgId,
        organizacao_nova: organizacaoNova,
        // A lista sai das SESSÕES da proposta, e não dos candidatos: quem casa a
        // revisão com o que a leitura entregou é o `_sessao_da_proposta` do
        // serviço, pela família, e uma família sem sessão — o endereço que não é
        // nenhuma das duas pontas do par, `ponta_incoerente` no motor — viajaria
        // como uma sessão que não existe. É aí que as duas listas divergem, e o
        // payload segue a que a guarda do serviço confere.
        sessoes: proposta.sessoes.map((s) => ({
          afi: s.afi,
          import_profile_id: perfis[s.afi]?.import || null,
          export_profile_id: perfis[s.afi]?.export || null,
          // Só o caminho: o valor do segredo nunca passa por esta tela.
          password_ref: caminhos[s.afi]?.trim() || null,
        })),
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
      {criarOrg && (
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
      )}

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
