import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useChangeRequests, useDashboard } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import type { PerDeviceOut } from "@/api/types";

function led(total: number, ativos: number): string {
  if (total === 0) return "gray";
  return ativos === total ? "green" : "amber";
}

const IDADE_ALERTA_SEGUNDOS = 24 * 3600;

function formatarIdade(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 3 * 86400) return `${(seconds / 3600).toFixed(1)} h`; // até 72 h, em horas
  return `${(seconds / 86400).toFixed(1)} d`;
}

export default function Dashboard() {
  const { data, isLoading, error } = useDashboard();
  const { data: pendentes } = useChangeRequests({ status: "aguardando_aprovacao" });

  const idades = (data?.per_device ?? [])
    .map((d) => d.snapshot_age_seconds)
    .filter((x): x is number => x != null);
  const idadeMax = idades.length > 0 ? Math.max(...idades) : null;

  return (
    <main>
      <PageHeader titulo="Dashboard" sub="Estado atual dos equipamentos e serviços registrados." />
      {isLoading && <p aria-busy="true">Carregando…</p>}
      {error && !data && (
        <p role="alert" className="erro-banner">
          {error instanceof ApiError ? error.message : "Falha ao carregar o painel."}
        </p>
      )}
      {data && (
        <>
          <section className="health" aria-label="Saúde da rede">
            <div className="metric">
              <span className={`led ${led(data.devices.total, data.devices.active)}`} aria-hidden="true" />
              <span className="val">{data.devices.active}/{data.devices.total}</span>
              <span className="label">equipamentos<br />ativos</span>
            </div>
            <div className="metric">
              <span className={`led ${data.bgp_sessions.active > 0 ? "green" : "gray"}`} aria-hidden="true" />
              <span className="val">{data.bgp_sessions.active}</span>
              <span className="label">sessões BGP<br />ativas</span>
            </div>
            <div className="metric">
              <span className={`led ${data.circuits.active > 0 ? "green" : "gray"}`} aria-hidden="true" />
              <span className="val">{data.circuits.active}</span>
              <span className="label">circuitos<br />ativos</span>
            </div>
            <div className="metric">
              <span className={`led ${data.vlans.reserved > 0 ? "green" : "gray"}`} aria-hidden="true" />
              <span className="val">{data.vlans.reserved}</span>
              <span className="label">VLANs<br />reservadas</span>
            </div>
            <div className="metric">
              <span className={`led ${data.ip_prefixes.reserved > 0 ? "green" : "gray"}`} aria-hidden="true" />
              <span className="val">{data.ip_prefixes.reserved}</span>
              <span className="label">prefixos<br />reservados</span>
            </div>
            <div className="metric">
              <span
                className={`led ${idadeMax == null ? "gray" : idadeMax > IDADE_ALERTA_SEGUNDOS ? "amber" : "green"}`}
                aria-hidden="true"
              />
              <span className="val">{formatarIdade(idadeMax)}</span>
              <span className="label">idade da<br />última coleta</span>
            </div>
            <div className="metric">
              <span className={`led ${(pendentes?.length ?? 0) > 0 ? "amber" : "gray"}`} aria-hidden="true" />
              <span className="val">{pendentes?.length ?? 0}</span>
              <span className="label">mudanças<br />aguardando aprovação</span>
            </div>
          </section>
          <p className="estados-equipamentos">
            {data.devices.total} equipamento(s): {data.devices.by_comm_status.ok ?? 0} ok ·{" "}
            {data.devices.by_comm_status.fail ?? 0} com falha ·{" "}
            {data.devices.by_comm_status.unknown ?? 0} desconhecido
          </p>

          <h2>Equipamentos</h2>
          {data.per_device.length === 0 ? (
            <p className="vazio">
              Nenhum equipamento cadastrado ainda — comece por{" "}
              <Link to="/devices">Equipamentos</Link>.
            </p>
          ) : (
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
                    <td>
                      {d.latest_snapshot ? <StatusBadge estado={d.latest_snapshot.status} /> : "—"}
                      {d.latest_snapshot?.error && (
                        <div className="erro-curto" title={d.latest_snapshot.error}>
                          {d.latest_snapshot.error}
                        </div>
                      )}
                    </td>
                    <td>{d.active_job ? <StatusBadge estado={d.active_job.status} /> : "—"}</td>
                    <td>
                      <Link to={`/devices/${d.device_id}`}>Detalhe</Link>{" "}
                      <Link to={`/reconcile?device_id=${d.device_id}`}>Reconciliar</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2>Auditoria recente</h2>
          {data.recent_audit.length === 0 ? (
            <p className="vazio">Nenhum evento registrado até agora.</p>
          ) : (
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
          )}
        </>
      )}
    </main>
  );
}
