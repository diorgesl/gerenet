import { Link } from "react-router-dom";
import { useDashboard } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import type { PerDeviceOut } from "@/api/types";

export default function Dashboard() {
  const { data, isLoading } = useDashboard();

  return (
    <main>
      <PageHeader titulo="Dashboard" />
      {isLoading && <p aria-busy="true">Carregando…</p>}
      {data && (
        <>
          <section className="cards">
            <div className="card"><strong>{data.devices.total}</strong> equipamentos</div>
            <div className="card"><strong>{data.devices.active}</strong> ativos</div>
            <div className="card"><strong>{data.bgp_sessions.active}</strong> sessões BGP ativas</div>
            <div className="card"><strong>{data.circuits.active}</strong> circuitos ativos</div>
            <div className="card"><strong>{data.vlans.reserved}</strong> VLANs reservadas</div>
            <div className="card"><strong>{data.ip_prefixes.reserved}</strong> prefixos reservados</div>
          </section>
          <h2>Equipamentos</h2>
          <table>
            <thead>
              <tr>
                <th>Nome</th><th>Site</th><th>Status</th><th>Última coleta</th><th>Snapshot</th><th>Job</th><th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {data.per_device.map((d: PerDeviceOut) => (
                <tr key={d.device_id}>
                  <td><Link to={`/devices/${d.device_id}`}>{d.name}</Link></td>
                  <td>{d.site_name ?? "—"}</td>
                  <td><StatusBadge estado={d.comm_status} /></td>
                  <td><TimeAgo iso={d.last_collected_at} /></td>
                  <td>{d.latest_snapshot ? <StatusBadge estado={d.latest_snapshot.status} /> : "—"}</td>
                  <td>{d.active_job ? <StatusBadge estado={d.active_job.status} /> : "—"}</td>
                  <td>
                    <Link to={`/devices/${d.device_id}`}>Detalhe</Link>{" "}
                    <Link to={`/devices/${d.device_id}`}>Coletar</Link>{" "}
                    <Link to={`/reconcile?device_id=${d.device_id}`}>Reconciliar</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>Auditoria recente</h2>
          <table>
            <thead><tr><th>Quando</th><th>Ação</th><th>Autor</th></tr></thead>
            <tbody>
              {data.recent_audit.map((e) => (
                <tr key={e.id}>
                  <td><TimeAgo iso={e.created_at} /></td>
                  <td>{e.type}</td>
                  <td>{e.actor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
