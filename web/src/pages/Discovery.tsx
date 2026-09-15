import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import {
  useDevices,
  useDiscovery,
  useDiscoveryDesdesignorar,
  useDiscoveryIgnorados,
  useDiscoveryIgnorar,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { help } from "@/help";
import { AdocaoDialog } from "./DiscoveryAdopt";
import type { DiscoveryOut, DiscoveryPropostaOut } from "@/api/types";

// A conclusão chata ("não há peer fora da SoT") só sai quando a leitura
// aconteceu e não sobrou aviso nenhum: sem coleta a lista está vazia por falta
// de fonte, e com aviso a leitura pode ter deixado peer para trás. A regra é a
// do `list` do CLI, que só conclui com `aviso is None and not propostas`.
const VAZIO_SEM_COLETA = "Sem coleta com a configuração salva — não há o que comparar.";
const VAZIO_LEITURA_PARCIAL = "A leitura da configuração não entendeu tudo (veja o aviso acima): a lista pode estar incompleta.";
const VAZIO_SEM_PEER = "Nenhum peer fora da SoT neste equipamento.";
// Sem dado nenhum não há leitura a concluir: a frase de lista vazia afirmaria
// o que ninguém leu. Hoje a tela não chega a este estado, e a mensagem segue o
// mesmo cuidado das outras duas.
const VAZIO_SEM_LEITURA = "A leitura ainda não devolveu nada para este equipamento.";

export function vazioDaLista(data: DiscoveryOut | undefined): string {
  if (data === undefined) return VAZIO_SEM_LEITURA;
  if (data.snapshot_id === null) return VAZIO_SEM_COLETA;
  if (data.aviso !== null) return VAZIO_LEITURA_PARCIAL;
  return VAZIO_SEM_PEER;
}

function textoDeIgnorados(quantidade: number): string {
  return quantidade === 1
    ? "1 peer foi para a lista de ignorados."
    : `${quantidade} peers foram para a lista de ignorados.`;
}

/** O circuito que a adoção gravou. O diálogo fecha e a linha sai da lista: sem
 * o relato, o operador que acabou de escrever na SoT não vê confirmação nenhuma
 * — e ele gravou um circuito, não uma linha de lista. */
function textoDeAdocao(circuitId: number): string {
  return `Proposta adotada: o circuito ${circuitId} foi gravado na SoT.`;
}

export default function Discovery() {
  const [params, setParams] = useSearchParams();
  const { data: devices } = useDevices();
  const deviceParam = Number(params.get("device_id") ?? 0);
  const [deviceSel, setDeviceSel] = useState<number>(deviceParam);
  const [detalhe, setDetalhe] = useState<DiscoveryPropostaOut | null>(null);
  const [revisando, setRevisando] = useState<DiscoveryPropostaOut | null>(null);
  const [ignorando, setIgnorando] = useState<DiscoveryPropostaOut | null>(null);
  const [motivo, setMotivo] = useState("");
  const [resultado, setResultado] = useState<string | null>(null);

  useEffect(() => {
    setDeviceSel(deviceParam);
  }, [deviceParam]);

  const { data, isLoading, error } = useDiscovery(deviceSel);
  const { data: ignorados } = useDiscoveryIgnorados(deviceSel);
  const ignorar = useDiscoveryIgnorar();
  const desdesignorar = useDiscoveryDesdesignorar();
  const propostas = data?.propostas ?? [];
  const candidatos = ignorando?.candidatos ?? [];
  // A proposta órfã (endereço sem subinterface) não tem VLAN nem enlace: o
  // título diz o que a proposta é, em vez de imprimir "null" ao operador.
  const tituloDetalhe =
    detalhe === null
      ? "Proposta"
      : detalhe.subinterface === null
        ? "Proposta sem enlace"
        : `VLAN ${detalhe.vid ?? "sem enlace"} (${detalhe.subinterface})`;

  return (
    <main>
      <PageHeader
        titulo="Migrar"
        sub="O que a configuração do equipamento tem e a SoT ainda não conhece."
      />
      <FormField label="Equipamento" help={help("discovery.equipamento")}>
        <select
          value={deviceSel}
          onChange={(e) => {
            const v = Number(e.target.value);
            setDeviceSel(v);
            setParams(v > 0 ? { device_id: String(v) } : {});
          }}
        >
          <option value={0}>Selecione…</option>
          {(devices ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </FormField>

      {deviceSel === 0 && <p>Selecione um equipamento.</p>}
      {data?.aviso && <p role="status">{data.aviso}</p>}
      {error && (
        <p role="alert">
          {error instanceof ApiError ? error.message : "Falha ao ler a configuração."}
        </p>
      )}
      {/* As duas mensagens de escrita ficam fora dos diálogos: fechar o de
          ignorar (Cancelar, Escape ou clique no fundo) não pode levar embora o
          relato de uma sequência que parou no meio. */}
      {ignorar.error && (
        <p role="alert">{ignorar.error.message || "Falha ao ignorar os peers do enlace."}</p>
      )}
      {/* O 404 do DELETE diz que a linha da tela já não existe no servidor; a
          mensagem fica fora da lista para não sumir com ela. */}
      {desdesignorar.error && (
        <p role="alert">
          {desdesignorar.error instanceof ApiError
            ? desdesignorar.error.message
            : "Falha ao voltar a considerar o peer."}
        </p>
      )}
      {resultado && <p role="status">{resultado}</p>}

      {deviceSel > 0 && !error && (
        <DataTable<DiscoveryPropostaOut>
          colunas={[
            { key: "vid", title: "VLAN", render: (p) => (p.vid === null ? "sem enlace" : p.vid) },
            { key: "subinterface", title: "Subinterface", render: (p) => p.subinterface ?? "—" },
            { key: "stack", title: "Stack", render: (p) => p.stack },
            // O enlace empilhado reserva S-VLAN: sem a coluna, o QinQ só aparece
            // depois de adotar.
            { key: "qinq", title: "QinQ", render: (p) => (p.qinq ? "sim" : "—") },
            {
              key: "peers",
              title: "Peers",
              render: (p) => p.candidatos.map((c) => c.remote_address).join(", ") || "—",
            },
            { key: "circuit_code_sugerido", title: "Código sugerido", render: (p) => p.circuit_code_sugerido ?? "—" },
            {
              key: "veredito",
              title: "Veredito",
              // Cores próprias: o StatusBadge deixaria os três vereditos no cinza
              // de "unknown", e `nao_adotavel` de cinza lê como "não sei".
              render: (p) => (
                <span
                  className={
                    p.veredito === "adotavel"
                      ? "badge badge-ok"
                      : p.veredito === "nao_adotavel"
                        ? "badge badge-fail"
                        : "badge badge-warn"
                  }
                  title={help("discovery.veredito")}
                >
                  {p.veredito}
                </span>
              ),
            },
          ]}
          linhas={propostas}
          carregando={isLoading}
          vazio={vazioDaLista(data)}
          acoes={(p) => (
            <>
              <button type="button" onClick={() => setDetalhe(p)}>
                Detalhes
              </button>
              <button
                type="button"
                // A adoção é o fluxo da proposta sem conflito: a com conflito
                // não tem revisão a fazer (o serviço recusa), e o motivo está
                // nos conflitos do detalhe.
                disabled={p.veredito === "nao_adotavel"}
                title={
                  p.veredito === "nao_adotavel"
                    ? "A proposta não é adotável: veja os conflitos em Detalhes."
                    : undefined
                }
                onClick={() => {
                  setRevisando(p);
                  // Como no ignorar: o relato é do que acabou de ser gravado, e
                  // abrir outra revisão o deixaria contando outra história.
                  setResultado(null);
                }}
              >
                Adotar
              </button>
              <button
                type="button"
                // A proposta órfã (endereço sem subinterface) vem sem candidato:
                // sem peer identificado não há o que mandar à lista de ignorados.
                disabled={p.candidatos.length === 0}
                title={p.candidatos.length === 0 ? "A proposta não identifica o peer a ignorar." : undefined}
                onClick={() => {
                  setIgnorando(p);
                  setMotivo("");
                  setResultado(null);
                }}
              >
                Não adotar
              </button>
            </>
          )}
        />
      )}

      {ignorados && ignorados.length > 0 && (
        <>
          <h2>Ignorados</h2>
          <ul>
            {ignorados.map((i) => (
              <li key={i.id}>
                {i.remote_address} — {i.motivo ?? "sem motivo"}{" "}
                <button
                  type="button"
                  disabled={desdesignorar.isPending}
                  onClick={() =>
                    desdesignorar.mutate({
                      device_id: i.device_id,
                      vrf: i.vrf,
                      afi: i.afi,
                      remote_address: i.remote_address,
                    })
                  }
                >
                  Voltar a considerar
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <Modal
        aberto={detalhe !== null}
        titulo={tituloDetalhe}
        onFechar={() => setDetalhe(null)}
      >
        {detalhe && (
          <div>
            {detalhe.candidatos.map((c) => (
              <p key={c.remote_address}>
                <strong>{c.remote_address}</strong> AS{c.asn_remote} ({c.classificacao}) — {c.motivo}
              </p>
            ))}
            <h3>Reservas</h3>
            <ul>
              {detalhe.prefixos.map((p) => (
                <li key={p.network}>
                  {p.network} (ponta {p.ponta_local})
                </li>
              ))}
            </ul>
            <h3>Pendências</h3>
            <ul>
              {detalhe.pendencias.map((p, i) => (
                // O mesmo `tipo` pode vir duas vezes com textos diferentes (o
                // perfil de política sai uma vez por família), então a posição
                // entra na chave.
                <li key={`${i}-${p.tipo}`}>
                  {p.tipo}: {p.descricao}
                </li>
              ))}
            </ul>
            <h3>Conflitos</h3>
            <ul>
              {detalhe.conflitos.map((c, i) => (
                <li key={`${i}-${c.tipo}`}>
                  {c.tipo}: {c.descricao}
                </li>
              ))}
            </ul>
            <p>
              <Link to={`/devices/${detalhe.device_id}`}>Ver o equipamento</Link>
            </p>
          </div>
        )}
      </Modal>

      {/* A `key` por proposta é o que reabre o formulário do zero: sem ela o
          estado da revisão anterior sobrevive à troca de linha. */}
      {revisando && (
        <AdocaoDialog
          key={revisando.vid ?? revisando.subinterface}
          proposta={revisando}
          onFechar={() => setRevisando(null)}
          onAdotada={(circuitId) => setResultado(textoDeAdocao(circuitId))}
        />
      )}

      <Modal
        aberto={ignorando !== null}
        titulo="Não adotar este enlace"
        onFechar={() => setIgnorando(null)}
      >
        {/* A decisão é sobre o enlace, e um enlace dual stack tem dois peers:
            os dois saem. Dizer só o primeiro faria o operador acreditar que
            resolveu, e a leitura seguinte traria o outro de volta. */}
        {ignorando !== null && (
          <p>
            {candidatos.length > 1 ? "Saem da lista: " : "Sai da lista: "}
            {candidatos
              .map((c) => `${c.remote_address} (${c.afi}${c.vrf ? `, VRF ${c.vrf}` : ""})`)
              .join(", ")}
            .
          </p>
        )}
        <FormField label="Motivo" help={help("discovery.nao_adotar")}>
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </FormField>
        <div className="dialog-actions">
          <button type="button" onClick={() => setIgnorando(null)}>
            Cancelar
          </button>
          <button
            type="button"
            className="danger"
            disabled={ignorar.isPending}
            onClick={() => {
              if (ignorando === null || candidatos.length === 0) return;
              ignorar.mutate(
                candidatos.map((c) => ({
                  device_id: ignorando.device_id,
                  vrf: c.vrf,
                  afi: c.afi,
                  remote_address: c.remote_address,
                  motivo: motivo || null,
                })),
                {
                  // O diálogo fecha nos dois desfechos: o relato mora fora dele,
                  // e a lista já refeita mostra o estado real do enlace.
                  onSuccess: (criadas) => setResultado(textoDeIgnorados(criadas.length)),
                  onSettled: () => setIgnorando(null),
                },
              );
            }}
          >
            Confirmar
          </button>
        </div>
      </Modal>
    </main>
  );
}
