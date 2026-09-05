import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useBgpSessions, useCircuitDetail, useCircuitoReservar, useDevices, useOrganizations, useSites } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";

export default function CircuitDetail() {
  const { id } = useParams();
  const circuitId = Number(id);
  const { data, isLoading, error } = useCircuitDetail(circuitId);
  const { data: sessions } = useBgpSessions({ circuit_id: circuitId });
  const { data: devices } = useDevices();
  const { data: sites } = useSites();
  const { data: organizations } = useOrganizations();
  const reservar = useCircuitoReservar();
  const [erro, setErro] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar o circuito."}</p>
      </main>
    );
  }

  return (
    <main>
      <PageHeader
        titulo={`Circuito ${data.code}`}
        acoes={<Link to="/circuits">← Voltar</Link>}
      />
      <table>
        <tbody>
          <tr><th>Organização</th><td>{organizations?.find((o) => o.id === data.organization_id)?.name ?? "—"}</td></tr>
          <tr><th>Site</th><td>{sites?.find((s) => s.id === data.site_id)?.name ?? "—"}</td></tr>
          <tr><th>Access → Edge</th><td>{devices?.find((d) => d.id === data.access_device_id)?.name ?? "—"} → {devices?.find((d) => d.id === data.edge_device_id)?.name ?? "—"}</td></tr>
          <tr><th>Stack</th><td><StatusBadge estado={data.stack} /></td></tr>
          <tr><th>VLAN</th><td>{data.vlan_mode}</td></tr>
          <tr><th>MTU</th><td>{data.mtu ?? "—"}</td></tr>
          <tr><th>BFD</th><td>{data.bfd ? "Sim" : "—"}</td></tr>
          {(data.stack === "ipv4" || data.stack === "dual") && (
            <>
              <tr><th>Pontas IPv4</th><td>{data.ipv4_local ?? "—"} ↔ {data.ipv4_remote ?? "—"}</td></tr>
            </>
          )}
          {(data.stack === "ipv6" || data.stack === "dual") && (
            <tr><th>Pontas IPv6</th><td>{data.ipv6_local ?? "—"} ↔ {data.ipv6_remote ?? "—"}</td></tr>
          )}
          <tr><th>Descrição</th><td>{data.description ?? "—"}</td></tr>
        </tbody>
      </table>
      <button
        className="primary"
        type="button"
        disabled={reservar.isPending}
        onClick={() => {
          setErro(null);
          void reservar.mutateAsync(circuitId).catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reservar recursos."));
        }}
      >
        {reservar.isPending ? "Reservando…" : "Reservar recursos"}
      </button>
      {reservar.error && <p role="alert">{String(reservar.error.message ?? "Falha ao reservar recursos.")}</p>}
      {erro && <p role="alert">{erro}</p>}
      <h2>Sessões BGP</h2>
      {sessions && sessions.length === 0 && <p>Nenhuma sessão vinculada.</p>}
      {sessions?.map((s) => (
        <p key={s.id}>
          <Link to={`/bgp-sessions/${s.id}`}>{s.afi}</Link> {s.local_address} ↔ {s.remote_address}
        </p>
      ))}
    </main>
  );
}
