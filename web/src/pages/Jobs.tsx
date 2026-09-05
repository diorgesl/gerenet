import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useDevices, useJobs } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import type { JobRunOut } from "@/api/types";

const STATUS = ["queued", "running", "success", "partial", "error"] as const;

export default function Jobs() {
  const { data: devices } = useDevices();
  const [params, setParams] = useSearchParams();
  const [deviceId, setDeviceId] = useState<number>(Number(params.get("device_id") ?? 0));
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [limite, setLimite] = useState(100);
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error } = useJobs({
    device_id: deviceId > 0 ? deviceId : undefined,
    status: status || undefined,
    kind: kind || undefined,
    limit: limite,
    offset,
  });

  return (
    <main>
      <PageHeader titulo="Jobs" />
      <div className="form-inline">
        <FormField label="Equipamento">
          <select
            value={deviceId}
            onChange={(e) => {
              const v = Number(e.target.value);
              setDeviceId(v);
              setOffset(0);
              setParams(v > 0 ? { device_id: String(v) } : {});
            }}
          >
            <option value={0}>Todos</option>
            {(devices ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Status">
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Todos</option>
            {STATUS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Tipo">
          <input value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }} />
        </FormField>
        <FormField label="Limite">
          <select
            value={limite}
            onChange={(e) => {
              setLimite(Number(e.target.value));
              setOffset(0);
            }}
          >
            {[10, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </FormField>
      </div>
      <DataTable<JobRunOut>
        colunas={[
          {
            key: "id",
            title: "Job",
            render: (j) => <Link to={`/jobs/${j.id}`}>#{j.id}</Link>,
          },
          { key: "device_id", title: "Equipamento", render: (j) => j.device_id ?? "—" },
          { key: "kind", title: "Tipo" },
          { key: "actor", title: "Autor" },
          { key: "status", title: "Status", render: (j) => <StatusBadge estado={j.status} /> },
          { key: "started_at", title: "Início", render: (j) => <TimeAgo iso={j.started_at} /> },
          { key: "duration_ms", title: "Duração (ms)" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        vazio="Nenhum job."
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
      />
      <p>
        <button type="button" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - limite))}>
          Anterior
        </button>{" "}
        <button type="button" onClick={() => setOffset((o) => o + limite)}>
          Próximo
        </button>
      </p>
    </main>
  );
}
