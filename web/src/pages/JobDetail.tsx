import { Link, useParams } from "react-router-dom";
import { useJobPoll } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";

export default function JobDetail() {
  const { id } = useParams();
  const jobId = Number(id);
  const { data, isLoading } = useJobPoll(jobId);

  return (
    <main>
      <PageHeader titulo={`Job #${data ? data.id : (id ?? "")}`} acoes={<Link to="/jobs">← Voltar</Link>} />
      {isLoading && <p aria-busy="true">Carregando…</p>}
      {!data && !isLoading && <p>Job não encontrado.</p>}
      {data && (
        <>
          <dl>
            <dt>Equipamento</dt>
            <dd>{data.device_id ?? "—"}</dd>
            <dt>Origem</dt>
            <dd>{data.origin}</dd>
            <dt>Autor</dt>
            <dd>{data.actor}</dd>
            <dt>Tipo</dt>
            <dd>{data.kind}</dd>
            <dt>Status</dt>
            <dd><StatusBadge estado={data.status} /></dd>
            <dt>Início</dt>
            <dd><TimeAgo iso={data.started_at} /></dd>
            <dt>Fim</dt>
            <dd>{data.finished_at ? <TimeAgo iso={data.finished_at} /> : "—"}</dd>
            <dt>Duração</dt>
            <dd>{data.duration_ms} ms</dd>
          </dl>
          {data.snapshot_id !== null && (
            <p>
              <Link to={`/reconcile?snapshot_id=${data.snapshot_id}`}>
                Ver reconcile do snapshot #{data.snapshot_id}
              </Link>
            </p>
          )}
        </>
      )}
    </main>
  );
}
