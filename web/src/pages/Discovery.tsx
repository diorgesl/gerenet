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
import type { DiscoveryPropostaOut } from "@/api/types";

// `snapshot_id` nulo é "não há coleta com a configuração salva": a lista vem
// vazia por falta de fonte, e não por o equipamento não ter peer fora da SoT.
const VAZIO_SEM_COLETA = "Sem coleta com a configuração salva — não há o que comparar.";
const VAZIO_SEM_PEER = "Nenhum peer fora da SoT neste equipamento.";

function textoDeIgnorados(quantidade: number): string {
  return quantidade === 1
    ? "1 peer saiu da lista de ignorados."
    : `${quantidade} peers saíram da lista de ignorados.`;
}

export default function Discovery() {
  const [params, setParams] = useSearchParams();
  const { data: devices } = useDevices();
  const deviceParam = Number(params.get("device_id") ?? 0);
  const [deviceSel, setDeviceSel] = useState<number>(deviceParam);
  const [detalhe, setDetalhe] = useState<DiscoveryPropostaOut | null>(null);
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
          vazio={data?.snapshot_id === null ? VAZIO_SEM_COLETA : VAZIO_SEM_PEER}
          acoes={(p) => (
            <>
              <button type="button" onClick={() => setDetalhe(p)}>
                Detalhes
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
              {detalhe.pendencias.map((p) => (
                <li key={p.tipo}>
                  {p.tipo}: {p.descricao}
                </li>
              ))}
            </ul>
            <h3>Conflitos</h3>
            <ul>
              {detalhe.conflitos.map((c) => (
                <li key={c.tipo}>
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
        {ignorar.error && (
          <p role="alert">
            {ignorar.error.message || "Falha ao ignorar os peers do enlace."}
          </p>
        )}
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
                  onSuccess: (criadas) => {
                    setIgnorando(null);
                    setResultado(textoDeIgnorados(criadas.length));
                  },
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
