import { useState } from "react";
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

/** A revisão de uma proposta (design §6). Montada pela página com `key` por
 * proposta, para o estado do formulário não vazar de uma para a outra.
 *
 * É a única superfície onde o `ciente` aparece: ele gateia o aceite, e não a
 * exibição do diff — as diferenças são para ler antes de decidir.
 */
export function AdocaoDialog({
  proposta,
  onFechar,
}: {
  proposta: DiscoveryPropostaOut;
  onFechar: () => void;
}) {
  const { data: devices } = useDevices();
  const { data: organizacoes } = useOrganizations();
  const { data: policyProfiles } = usePolicyProfiles();
  const adotar = useAdotar();
  const [code, setCode] = useState(proposta.circuit_code_sugerido ?? "");
  const [acesso, setAcesso] = useState<number>(0);
  const [porta, setPorta] = useState("");
  const [trunk, setTrunk] = useState("");
  const [orgId, setOrgId] = useState<number>(proposta.organizacao_id ?? 0);
  const [orgNome, setOrgNome] = useState(proposta.organizacao_sugerida ?? "");
  const [ciente, setCiente] = useState(false);
  // Os perfis vêm ANTES da conferência: ela é refeita quando eles mudam, porque
  // o corpo da política de exportação depende do produto escolhido.
  const [perfis, setPerfis] = useState<Record<string, { import?: number; export?: number }>>({});
  const { data: fidelidade, error: erroDaConferencia } = useFidelidade(
    proposta.device_id, proposta.vrf, proposta.subinterface, perfis, trunk || null,
  );

  const setPerfil = (afi: string, valores: { import?: number; export?: number }) =>
    setPerfis((atual) => ({ ...atual, [afi]: { ...atual[afi], ...valores } }));

  const diferencas = fidelidade?.diferencas ?? [];
  const mudam = diferencas.filter((d) => d.exige_ciente);
  // O grupo do que a SoT não gerencia é por LINHA, e não por contexto: o
  // contexto `subinterface` traz, no mesmo objeto, o que mudaria o equipamento
  // (`sobrando`/`faltando`) e o que ela não emite (`description` e `mtu`). O
  // segundo é visível e não bloqueia (§6 do design); um filtro por contexto o
  // esconderia justamente quando há mudança no mesmo bloco.
  const naoGerenciadas = diferencas.flatMap((d) => d.nao_gerenciado);
  const ensaio = diferencas.filter((d) => d.contexto === "ensaio");
  // O trunk é exigido quando a proposta tem subinterface: sem ele a SoT não
  // reproduz o bloco que a conferência acabou de validar, e a adoção recusa no
  // serviço com essa mesma razão — aqui é só para o botão não levar a um 422.
  const exigirTrunk = proposta.vid !== null && proposta.subinterface !== null;
  const faltaPreencher =
    code === "" || acesso === 0 || porta === "" || (exigirTrunk && trunk === "");
  // Sem a conferência não há aceite que valha (§6): o ensaio recusado devolve a
  // comparação que não pôde ser feita, e é o mesmo caso da consulta que não
  // voltou. O servidor recusa os dois de qualquer forma; aqui é o que impede o
  // operador de aceitar sobre uma comparação que nenhum dos lados viu, e o
  // ciente não libera nenhum deles — não há diferença que valha assumir.
  const semConferencia = fidelidade === undefined || ensaio.length > 0;
  const podeAdotar =
    !faltaPreencher && !semConferencia && (mudam.length === 0 || ciente) && !adotar.isPending;

  return (
    <Modal aberto titulo={`Adotar VLAN ${proposta.vid ?? "—"}`} onFechar={onFechar}>
      <section>
        <h3>O que será gravado</h3>
        <ul>
          {proposta.candidatos.map((c) => (
            <li key={`${c.afi}-${c.remote_address}`}>
              {c.remote_address} AS{c.asn_remote} ({c.classificacao})
            </li>
          ))}
          {proposta.prefixos.map((p) => (
            <li key={p.network}>
              {p.network} (ponta {p.ponta_local})
            </li>
          ))}
        </ul>
      </section>

      <FormField label="Código do circuito *">
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
      <FormField label="Porta de acesso *">
        <input value={porta} onChange={(e) => setPorta(e.target.value)} />
      </FormField>
      <FormField label={exigirTrunk ? "Trunk do edge *" : "Trunk do edge"} help={help("adocao.trunk")}>
        <input value={trunk} onChange={(e) => setTrunk(e.target.value)} />
      </FormField>
      <FormField label="Organização" help={help("adocao.organizacao")}>
        <select value={orgId} onChange={(e) => setOrgId(Number(e.target.value))}>
          <option value={0}>Criar a nova: {orgNome || "(informe o nome)"}</option>
          {(organizacoes ?? []).map((o) => (
            <option key={o.id} value={o.id}>{o.name} (AS{o.asn ?? "—"})</option>
          ))}
        </select>
      </FormField>
      {orgId === 0 && (
        <FormField label="Nome da organização nova">
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
        <button
          type="button"
          disabled={!podeAdotar}
          onClick={() =>
            adotar.mutate(
              {
                device_id: proposta.device_id, vrf: proposta.vrf,
                subinterface: proposta.subinterface, circuit_code: code,
                access_device_id: acesso, access_port: porta,
                edge_trunk: trunk || null,
                organizacao_id: orgId > 0 ? orgId : null,
                organizacao_nova: orgId > 0 ? null : {
                  name: orgNome, kind: "downstream",
                  asn: proposta.candidatos[0]?.asn_remote ?? 0,
                },
                sessoes: proposta.candidatos.map((c) => ({
                  afi: c.afi,
                  import_profile_id: perfis[c.afi]?.import || null,
                  export_profile_id: perfis[c.afi]?.export || null,
                })),
                ciente,
              },
              // A lista já refeita é o que mostra o desfecho: a proposta adotada
              // sai dela, como a linha do peer ignorado sai da de ignorados. Sem
              // fechar, o diálogo ficaria aberto sobre uma proposta que já não
              // existe — e o segundo clique responderia 404.
              { onSuccess: () => onFechar() },
            )
          }
        >
          Adotar
        </button>
      </div>
    </Modal>
  );
}
