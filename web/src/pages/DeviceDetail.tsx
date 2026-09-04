import { Link, useNavigate, useParams } from "react-router-dom";
import { useDevice, useDeviceColetar, useSites, useSnapshots } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";

export default function DeviceDetail() {
  const { id } = useParams();
  const deviceId = Number(id);
  const navigate = useNavigate();
  const { data: device, isLoading } = useDevice(deviceId);
  const { data: sites } = useSites();
  const { data: snapshots } = useSnapshots(deviceId);
  const coletar = useDeviceColetar();
  const siteNome = sites?.find((s) => s.id === device?.site_id)?.name ?? null;
  const ultimoSnapshot = snapshots && snapshots.length > 0 ? snapshots[0] : null;

  if (isLoading) return <main><p aria-busy="true">Carregando…</p></main>;
  if (!device) return <main><p>Equipamento não encontrado.</p></main>;

  return (
    <main>
      <PageHeader titulo={device.name} acoes={<Link to="/devices">← Voltar</Link>} />
      <ul>
        <li>Endereço de gestão: <span>{device.management_address}</span></li>
        <li>Site: <span>{siteNome ?? "—"}</span></li>
        <li>Função: <span>{device.role ?? "—"}</span></li>
        <li>Modelo: <span>{device.model ?? "—"}</span> · Família: <span>{device.family ?? "—"}</span></li>
        <li>Versão VRP: <span>{device.vrp_version ?? "—"}</span></li>
        <li>ASN: <span>{device.asn ?? "—"}</span></li>
        <li>Comunicação: <StatusBadge estado={device.comm_status} /></li>
        <li>Situação: <StatusBadge estado={device.admin_status ? "ativo" : "inativo"} /></li>
        <li>Última coleta: <TimeAgo iso={device.last_collected_at} /></li>
      </ul>
      <p>
        <button
          className="primary"
          disabled={coletar.isPending}
          onClick={() => void coletar.mutateAsync(device.id).then(() => navigate(`/jobs?device_id=${device.id}`))}
        >
          Coletar agora
        </button>
        {coletar.error && (
          <span role="alert"> {String(coletar.error.message ?? "Falha ao coletar.")}</span>
        )}
      </p>
      <h2>Último snapshot</h2>
      <p>
        {ultimoSnapshot ? (
          <>
            #{ultimoSnapshot.id} · <StatusBadge estado={ultimoSnapshot.status} /> ·{" "}
            <TimeAgo iso={ultimoSnapshot.started_at} />
          </>
        ) : (
          "Nenhum snapshot."
        )}
      </p>
      <h2>Inspeção</h2>
      <p>
        <Link to={`/snapshots?device_id=${device.id}`}>Snapshots</Link>{" "}
        <Link to={`/desired-config?device_id=${device.id}`}>Config desejada</Link>{" "}
        <Link to={`/reconcile?device_id=${device.id}`}>Reconciliar</Link>
      </p>
    </main>
  );
}
