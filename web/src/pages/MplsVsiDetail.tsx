import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useVsiDetalhe, useVsiStatus } from "@/api/hooks";
import type { VsiEndpointOut } from "@/api/types";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import SolicitarMudanca from "@/components/SolicitarMudanca";

export default function MplsVsiDetail() {
  const { id } = useParams();
  const vsiId = Number(id);
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useVsiDetalhe(vsiId);
  const atualizarStatus = useVsiStatus();
  // null = sem diálogo; false = desativando; true = reativando
  const [confirmandoStatus, setConfirmandoStatus] = useState<boolean | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar o VSI."}</p>
      </main>
    );
  }

  const sim = (v: boolean) => (v ? "Sim" : "—");

  const confirmarStatus = () => {
    if (confirmandoStatus === null) return;
    const valor = confirmandoStatus;
    setErro(null);
    atualizarStatus
      .mutateAsync({ id: data.id, admin_status: valor })
      .then(() => setConfirmandoStatus(null))
      .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao atualizar o VSI."));
  };

  return (
    <main>
      <PageHeader
        titulo={`VSI ${data.name}`}
        sub={`${data.vrp_name} · VSI-ID ${data.vsi_id} · ${data.domain_name ?? `domínio #${data.domain_id}`}`}
        acoes={
          <>
            <Link to="/mpls/vsi">← Voltar</Link>
            <Link to="/change-requests">Change requests</Link>
            {podeEscrever && (
              data.admin_status ? (
                <button type="button" onClick={() => setConfirmandoStatus(false)}>Desativar</button>
              ) : (
                <button type="button" onClick={() => setConfirmandoStatus(true)}>Reativar</button>
              )
            )}
            <SolicitarMudanca vsi_id={data.id} />
          </>
        }
      />
      {erro && <p role="alert">{erro}</p>}
      <table>
        <tbody>
          <tr><th>Domínio</th><td>{data.domain_name ?? `#${data.domain_id}`}</td></tr>
          <tr><th>VSI-ID</th><td>{data.vsi_id}</td></tr>
          <tr><th>Nome VRP</th><td>{data.vrp_name}</td></tr>
          <tr><th>Sinalização</th><td>{data.signaling}</td></tr>
          <tr><th>MTU</th><td>{data.mtu}</td></tr>
          <tr><th>Split-horizon</th><td>{sim(data.split_horizon)}</td></tr>
          <tr><th>MAC learning</th><td>{sim(data.mac_learning)}</td></tr>
          <tr><th>Limite de MACs</th><td>{data.mac_limit ?? "—"}</td></tr>
          <tr><th>Flow-label</th><td>{sim(data.flow_label)}</td></tr>
          <tr><th>Descrição</th><td>{data.description ?? "—"}</td></tr>
          <tr><th>Situação</th><td><StatusBadge estado={data.admin_status ? "ativo" : "inativo"} /></td></tr>
          <tr><th>Estado operacional</th><td><StatusBadge estado={data.operational_status} /></td></tr>
          <tr><th>Última coleta</th><td><TimeAgo iso={data.last_collected_at} /></td></tr>
        </tbody>
      </table>

      <h2>ACs (attachment circuits)</h2>
      {data.endpoints.length === 0 && <p>Nenhum AC cadastrado neste VSI.</p>}
      {/* O estado por pseudowire não vem no VsiOut: a página mostra o estado do
          VSI (VSI State da última coleta) e o de cada AC. */}
      {data.endpoints.length > 0 && (
        <table>
          <thead>
            <tr><th>Equipamento</th><th>Vlanif</th><th>VLAN</th><th>MTU</th><th>Estado</th></tr>
          </thead>
          <tbody>
            {data.endpoints.map((ep: VsiEndpointOut) => (
              <tr key={ep.device_id}>
                <td>{ep.device_name ?? `Device #${ep.device_id}`}</td>
                <td>{ep.interface}</td>
                <td>{ep.vid ?? "—"}</td>
                <td>{ep.mtu ?? "—"}</td>
                <td><StatusBadge estado={ep.operational_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {confirmandoStatus !== null && (
        <ConfirmDialog
          aberto
          titulo={`${confirmandoStatus ? "Reativar" : "Desativar"} ${data.name}?`}
          mensagem={
            confirmandoStatus
              ? "O VSI volta ao catálogo ativo e pode receber mudanças."
              : "O VSI fica indisponível para mudanças; o registro permanece."
          }
          onConfirmar={confirmarStatus}
          onCancelar={() => setConfirmandoStatus(null)}
          confirmando={atualizarStatus.isPending}
        />
      )}
    </main>
  );
}
