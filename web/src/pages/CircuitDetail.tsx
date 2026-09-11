import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useBgpSessions, useCircuitDetail, useCircuitoLiberar, useCircuitoReservar, useDevices, useOrganizations, useSites } from "@/api/hooks";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import SolicitarMudanca from "@/components/SolicitarMudanca";

export default function CircuitDetail() {
  const { id } = useParams();
  const circuitId = Number(id);
  const { data, isLoading, error } = useCircuitDetail(circuitId);
  const { data: sessions } = useBgpSessions({ circuit_id: circuitId });
  const { data: devices } = useDevices();
  const { data: sites } = useSites();
  const { data: organizations } = useOrganizations();
  const reservar = useCircuitoReservar();
  const liberar = useCircuitoLiberar();
  const [confirmandoRemocao, setConfirmandoRemocao] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const temReservas = Boolean(data?.ipv4_local || data?.ipv6_local);

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
        acoes={
          <>
            <Link to="/circuits">← Voltar</Link>
            {data.upstream_id !== null ? (
              <SolicitarMudanca upstream_id={data.upstream_id} />
            ) : (
              <SolicitarMudanca circuit_id={data.id} />
            )}
          </>
        }
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
      </button>{" "}
      {temReservas && (
        <button
          type="button"
          disabled={liberar.isPending}
          onClick={() => {
            setErro(null);
            setConfirmandoRemocao(true);
          }}
        >
          Remover recursos
        </button>
      )}
      {reservar.error && <p role="alert">{String(reservar.error.message ?? "Falha ao reservar recursos.")}</p>}
      {liberar.error && <p role="alert">{String(liberar.error.message ?? "Falha ao liberar recursos.")}</p>}
      {erro && <p role="alert">{erro}</p>}
      <ConfirmDialog
        aberto={confirmandoRemocao}
        titulo="Remover recursos do circuito?"
        mensagem="As VLANs e os endereços p2p reservados voltam a ficar disponíveis. As linhas ficam liberadas no histórico; circuitos com sessão BGP ativa não podem ser liberados (desative a sessão antes)."
        confirmando={liberar.isPending}
        onCancelar={() => setConfirmandoRemocao(false)}
        onConfirmar={() => {
          void liberar
            .mutateAsync(circuitId)
            .then(() => setConfirmandoRemocao(false))
            .catch(() => setConfirmandoRemocao(false)); // a mensagem sai pelo liberar.error
        }}
      />
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
