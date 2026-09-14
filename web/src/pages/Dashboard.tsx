import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useChangeRequests, useDashboard, useL2vc, useUpstreams, useVsi } from "@/api/hooks";
import { SeverityBadge } from "@/components/SeverityBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import type { DivergenciasAggOut, PerDeviceOut } from "@/api/types";

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

const SEVERIDADES_DASH = ["critica", "atencao", "aviso", "alerta"] as const;

// "alerta" (anomalia de prefixos, Fase 5) compartilha o vermelho de "critica":
// é o mesmo critério do SeverityBadge, e o LED segue a faixa de saúde do topo.
// Verde só vale com a comparação inteira feita: "sem divergência" em quem não
// foi comparado por completo (snapshot sem resumo, coleta parcial) ou nunca foi
// coletado é o zero enganoso que a frente evita. O agregado da API só não conta
// os dois últimos casos — daí os parâmetros.
function ledDivergencias(dv: DivergenciasAggOut, parciais: number, nuncaColetados: number): string {
  if (dv.critica + dv.alerta > 0) return "red";
  if (dv.atencao + dv.aviso > 0 || dv.devices_sem_resumo > 0 || parciais > 0 || nuncaColetados > 0) {
    return "amber";
  }
  return "green";
}

export default function Dashboard() {
  const { data, isLoading, error } = useDashboard();
  const { data: pendentes } = useChangeRequests({ status: "aguardando_aprovacao" });
  const { data: l2vc } = useL2vc();
  const { data: vsi } = useVsi();
  // R-28: o detalhe das divergências/anomalias vive na página de Reconciliação;
  // o dashboard fica com a contagem de upstreams ativos (mesmo shape dos cards).
  const { data: upstreams } = useUpstreams();
  const upstreamsAtivos = (upstreams ?? []).filter((u) => u.admin_status).length;

  const idades = (data?.per_device ?? [])
    .map((d) => d.snapshot_age_seconds)
    .filter((x): x is number => x != null);
  const idadeMax = idades.length > 0 ? Math.max(...idades) : null;

  // "alerta" entra no filtro junto com "critica": os dois pintam a faixa de
  // vermelho, e sem ele o operador veria o LED vermelho e nenhum equipamento
  // listado para onde olhar.
  const criticos = (data?.per_device ?? []).filter(
    (d) => (d.divergencias?.critica ?? 0) + (d.divergencias?.alerta ?? 0) > 0,
  );
  // A coleta parcial não tem roll-up no agregado da API: é derivada aqui, no
  // cliente, para o card não ler uma comparação incompleta como "sem
  // divergências".
  const parciais = (data?.per_device ?? []).filter((d) => d.divergencias?.parcial ?? false).length;
  // Nunca coletado também não entra em contagem nenhuma do agregado (o
  // `devices_sem_resumo` conta só quem tem snapshot): sem isso, instalação nova
  // — equipamentos cadastrados, nenhum coletado — leria "0 divergências" verde.
  const nuncaColetados = Math.max(0, (data?.devices.total ?? 0) - (data?.devices.with_snapshot ?? 0));

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
            <div className="metric">
              <span className={`led ${((l2vc?.length ?? 0) + (vsi?.length ?? 0)) > 0 ? "green" : "gray"}`} aria-hidden="true" />
              <span className="val">{(l2vc?.length ?? 0) + (vsi?.length ?? 0)}</span>
              <span className="label">serviços<br />MPLS</span>
            </div>
            <div className="metric">
              <span className={`led ${upstreamsAtivos > 0 ? "green" : "gray"}`} aria-hidden="true" />
              <span className="val">{upstreamsAtivos}</span>
              <span className="label">upstreams<br />ativos</span>
            </div>
            <div className="metric">
              <span
                className={`led ${ledDivergencias(data.divergencias, parciais, nuncaColetados)}`}
                aria-hidden="true"
              />
              <span className="val">{data.divergencias.total}</span>
              <span className="label">divergências<br />na última coleta</span>
            </div>
          </section>
          <p className="estados-equipamentos">
            {data.devices.total} equipamento(s): {data.devices.by_comm_status.ok ?? 0} ok ·{" "}
            {data.devices.by_comm_status.fail ?? 0} com falha ·{" "}
            {data.devices.by_comm_status.unknown ?? 0} desconhecido
          </p>

          <section className="divergencias" aria-label="Divergências da última coleta">
            <h2>Divergências da última coleta</h2>
            <p className="sub">
              Contagem do desejado × encontrado gravada em cada coleta; o detalhe fica na{" "}
              <Link to="/reconcile">Reconciliação</Link>.
              {data.divergencias.devices_sem_resumo > 0 &&
                ` ${data.divergencias.devices_sem_resumo} equipamento(s) sem resumo (coleta anterior a esta versão ou coleta sem snapshot).`}
              {parciais > 0 &&
                ` ${parciais} equipamento(s) com comparação parcial (a coleta não trouxe tudo que a comparação precisa).`}
              {nuncaColetados > 0 &&
                ` ${nuncaColetados} equipamento(s) sem coleta (nunca coletados, sem dado para comparar).`}
            </p>
            <p className="severidades">
              {SEVERIDADES_DASH.map((s) => (
                <span key={s} className="severidade-contagem">
                  <SeverityBadge severidade={s} /> {data.divergencias[s]}
                </span>
              ))}
              {data.divergencias.idade_max_seconds != null && (
                <span className="sub">resumo mais antigo há {formatarIdade(data.divergencias.idade_max_seconds)}</span>
              )}
            </p>
            {criticos.length > 0 && (
              <p>
                Com divergência crítica ou alerta:{" "}
                {criticos.map((d: PerDeviceOut) => (
                  <span key={d.device_id}>
                    <Link to={`/reconcile?device_id=${d.device_id}`} aria-label={`Reconciliar ${d.name}`}>
                      {d.name}
                    </Link>{" "}
                  </span>
                ))}
              </p>
            )}
          </section>

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
                  <th>Nome</th><th>Site</th><th>Status</th><th>Divergências</th><th>Última coleta</th><th>Snapshot</th><th>Job</th><th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {data.per_device.map((d: PerDeviceOut) => (
                  <tr key={d.device_id}>
                    <td><Link to={`/devices/${d.device_id}`}>{d.name}</Link></td>
                    <td>{d.site_name ?? "—"}</td>
                    <td><StatusBadge estado={d.comm_status} /></td>
                    <td>
                      {d.divergencias ? (
                        <Link
                          to={`/reconcile?device_id=${d.device_id}`}
                          aria-label={`Divergências de ${d.name}: ${d.divergencias.total}`}
                        >
                          {d.divergencias.total}
                        </Link>
                      ) : d.latest_snapshot ? (
                        "sem resumo"
                      ) : (
                        "—"
                      )}
                    </td>
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
