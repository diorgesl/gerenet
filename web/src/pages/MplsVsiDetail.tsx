import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useVsiDetalhe } from "@/api/hooks";
import type { VsiMemberOut } from "@/api/types";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";

export default function MplsVsiDetail() {
  const { id } = useParams();
  const vsiId = Number(id);
  const { data, isLoading, error } = useVsiDetalhe(vsiId);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar o VSI."}</p>
      </main>
    );
  }

  const sim = (v: boolean) => (v ? "Sim" : "—");

  return (
    <main>
      <PageHeader
        titulo={`VSI ${data.name}`}
        sub={`${data.vrp_name} · VSI-ID ${data.vsi_id} · ${data.domain_name ?? `domínio #${data.domain_id}`}`}
        acoes={<Link to="/mpls/vsi">← Voltar</Link>}
      />
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
          <tr><th>Situação</th><td><StatusBadge estado={data.admin_status ? "ativo" : "inativo"} /></td></tr>
          <tr><th>Estado operacional</th><td><StatusBadge estado={data.operational_status} /></td></tr>
          <tr><th>Última coleta</th><td><TimeAgo iso={data.last_collected_at} /></td></tr>
        </tbody>
      </table>

      <h2>Membros</h2>
      <table>
        <thead>
          <tr><th>Equipamento</th></tr>
        </thead>
        <tbody>
          {data.members.map((m: VsiMemberOut) => (
            <tr key={m.device_id}>
              <td>{m.device_name ?? `Device #${m.device_id}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
