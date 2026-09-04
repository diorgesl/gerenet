import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useDesiredConfig, useDevices } from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { MonoCode } from "@/components/MonoCode";
import { PageHeader } from "@/components/PageHeader";

export default function DesiredConfig() {
  const [params, setParams] = useSearchParams();
  const { data: devices } = useDevices();
  const [deviceId, setDeviceId] = useState<number>(Number(params.get("device_id") ?? 0));
  const { data, isLoading } = useDesiredConfig(deviceId > 0 ? deviceId : null);

  return (
    <main>
      <PageHeader titulo="Configuração desejada" />
      <FormField label="Equipamento">
        <select
          value={deviceId}
          onChange={(e) => {
            const v = Number(e.target.value);
            setDeviceId(v);
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
      {isLoading && <p aria-busy="true">Carregando…</p>}
      {data && (
        <>
          <p>Gerada em {new Date(data.gerado_em).toLocaleString("pt-BR")}</p>
          <MonoCode texto={data.texto} />
          <h2>Blocos</h2>
          {data.blocos.length === 0 && <p>Nenhum bloco renderizado.</p>}
          {data.blocos.map((b) => (
            <details key={`${b.tipo}-${b.objeto}-${b.objeto_id}`}>
              <summary>
                {b.tipo} · {b.objeto} #{b.objeto_id}
              </summary>
              <pre>{b.comandos.join("\n")}</pre>
            </details>
          ))}
        </>
      )}
    </main>
  );
}
