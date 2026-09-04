import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useDevices, useSnapshot, useSnapshots } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import type { SnapshotOut } from "@/api/types";

const LIMITE_ARRAY = 60;

function JsonValor({ valor }: { valor: unknown }) {
  if (valor === null || typeof valor !== "object") return <>{String(valor)}</>;
  if (Array.isArray(valor)) return <JsonArray itens={valor} />;
  return (
    <ul>
      {Object.entries(valor as Record<string, unknown>).map(([k, v]) => (
        <li key={k}>
          {k}: <JsonValor valor={v} />
        </li>
      ))}
    </ul>
  );
}

function JsonArray({ itens }: { itens: unknown[] }) {
  const [corte, setCorte] = useState(LIMITE_ARRAY);
  const visiveis = itens.slice(0, corte);
  const restante = itens.length - visiveis.length;
  return (
    <>
      <ol>
        {visiveis.map((item, i) => (
          <li key={i}>
            <JsonValor valor={item} />
          </li>
        ))}
      </ol>
      {restante > 0 && (
        <button type="button" onClick={() => setCorte((c) => c + LIMITE_ARRAY)}>
          Mostrar mais ({restante})
        </button>
      )}
    </>
  );
}

function JsonTree({ recursos }: { recursos: Record<string, unknown> }) {
  return (
    <ul>
      {Object.entries(recursos).map(([chave, valor]) => (
        <li key={chave}>
          <details>
            <summary>{chave}</summary>
            <JsonValor valor={valor} />
          </details>
        </li>
      ))}
    </ul>
  );
}

export default function Snapshots() {
  const [params, setParams] = useSearchParams();
  const { data: devices, isLoading: carregandoDevices } = useDevices();
  const [deviceId, setDeviceId] = useState<number>(Number(params.get("device_id") ?? 0));
  const { data: snapshots, isLoading } = useSnapshots(deviceId);
  const [selecionado, setSelecionado] = useState<number | null>(null);
  const detalhe = useSnapshot(selecionado ?? 0);

  return (
    <main>
      <PageHeader titulo="Snapshots" />
      <FormField label="Equipamento">
        <select
          value={deviceId}
          onChange={(e) => {
            const v = Number(e.target.value);
            setDeviceId(v);
            setSelecionado(null);
            setParams(v > 0 ? { device_id: String(v) } : {});
          }}
        >
          <option value={0}>Selecione…</option>
          {(devices ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </FormField>
      {deviceId === 0 && <p>Selecione um equipamento.</p>}
      {deviceId > 0 && (
        <DataTable<SnapshotOut>
          colunas={[
            { key: "id", title: "Snapshot" },
            { key: "started_at", title: "Início", render: (s) => <TimeAgo iso={s.started_at} /> },
            { key: "status", title: "Status", render: (s) => <StatusBadge estado={s.status} /> },
            { key: "duration_ms", title: "Duração (ms)" },
          ]}
          linhas={snapshots ?? []}
          carregando={carregandoDevices || isLoading}
          vazio="Nenhum snapshot deste equipamento."
          acoes={(s) => (
            <button type="button" onClick={() => setSelecionado(s.id)}>
              Ver
            </button>
          )}
        />
      )}
      {detalhe.data && (
        <section>
          <h2>
            Snapshot #{detalhe.data.id} ({detalhe.data.status})
          </h2>
          <p>
            Início: <TimeAgo iso={detalhe.data.started_at} /> · duração: {detalhe.data.duration_ms} ms
          </p>
          <h3>resources</h3>
          <JsonTree recursos={detalhe.data.resources} />
          {Object.keys(detalhe.data.errors).length > 0 && (
            <>
              <h3>errors</h3>
              <JsonTree recursos={detalhe.data.errors} />
            </>
          )}
        </section>
      )}
      {detalhe.isError && (
        <p role="alert">{detalhe.error instanceof ApiError ? detalhe.error.message : "Falha ao carregar o snapshot."}</p>
      )}
    </main>
  );
}
