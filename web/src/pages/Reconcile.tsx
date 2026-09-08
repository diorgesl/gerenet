import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useDevices, useReconcile } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { SeverityBadge } from "@/components/SeverityBadge";
import type { ReconcileItemOut } from "@/api/types";

// Severidades do backend (reconcile.py:27) — "alerta" é a dos itens de
// anomalia de prefixos (bgp.anomalia_prefixos, reconcile.py:253).
const SEVERIDADES = ["todas", "critica", "atencao", "aviso", "alerta"] as const;

export default function Reconcile() {
  const [params, setParams] = useSearchParams();
  const { data: devices } = useDevices();
  const deviceParam = Number(params.get("device_id") ?? 0);
  const snapshotParam = Number(params.get("snapshot_id") ?? 0);
  const [modo, setModo] = useState<"device" | "snapshot">(snapshotParam > 0 ? "snapshot" : "device");
  const [deviceSel, setDeviceSel] = useState<number>(deviceParam);
  const [snapInput, setSnapInput] = useState<string>(snapshotParam > 0 ? String(snapshotParam) : "");
  const [severidade, setSeveridade] = useState<string>("todas");

  const filtro =
    modo === "device"
      ? { device_id: deviceSel > 0 ? deviceSel : undefined, snapshot_id: undefined }
      : { device_id: undefined, snapshot_id: Number(snapInput) > 0 ? Number(snapInput) : undefined };
  const { data, isLoading, error } = useReconcile(filtro);
  const items = (data?.items ?? []).filter((i) => severidade === "todas" || i.severidade === severidade);

  return (
    <main>
      <PageHeader titulo="Reconciliação" />
      <FormField label="Modo">
        <select value={modo} onChange={(e) => setModo(e.target.value as "device" | "snapshot")}>
          <option value="device">Equipamento</option>
          <option value="snapshot">Snapshot</option>
        </select>
      </FormField>
      {modo === "device" && (
        <FormField label="Equipamento">
          <select
            value={deviceSel}
            onChange={(e) => {
              const v = Number(e.target.value);
              setDeviceSel(v);
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
      )}
      {modo === "snapshot" && (
        <FormField label="Snapshot (id)">
          <input type="number" min={1} value={snapInput} onChange={(e) => setSnapInput(e.target.value)} />
        </FormField>
      )}
      <FormField label="Severidade">
        <select value={severidade} onChange={(e) => setSeveridade(e.target.value)}>
          {SEVERIDADES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </FormField>
      {data?.aviso && <p role="status">{data.aviso}</p>}
      {error && <p role="alert">{error instanceof ApiError ? error.message : "Falha ao reconciliar."}</p>}
      {(modo === "device" ? deviceSel === 0 : snapInput === "") && (
        <p>Selecione um equipamento ou informe um snapshot.</p>
      )}
      <DataTable<ReconcileItemOut>
        colunas={[
          { key: "tipo", title: "Tipo" },
          { key: "severidade", title: "Severidade", render: (i) => <SeverityBadge severidade={i.severidade} /> },
          { key: "esperado", title: "Esperado" },
          { key: "encontrado", title: "Encontrado" },
          { key: "acao", title: "Ação recomendada" },
        ]}
        linhas={items}
        carregando={isLoading}
        vazio="Nenhuma divergência encontrada."
      />
    </main>
  );
}
