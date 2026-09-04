import { useState } from "react";
import { useAuditEvents } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import type { AuditEventOut } from "@/api/types";

export default function AuditEvents() {
  const [tipo, setTipo] = useState("");
  const [objeto, setObjeto] = useState("");
  const { data, isLoading } = useAuditEvents({
    ...(tipo ? { tipo } : {}),
    ...(objeto ? { objeto } : {}),
  });
  return (
    <main>
      <PageHeader titulo="Auditoria" />
      <form className="form-inline">
        <label className="field">
          <span>Tipo</span>
          <input value={tipo} onChange={(e) => setTipo(e.target.value)} />
        </label>
        <label className="field">
          <span>Objeto</span>
          <input value={objeto} onChange={(e) => setObjeto(e.target.value)} />
        </label>
      </form>
      <DataTable<AuditEventOut>
        colunas={[
          { key: "created_at", title: "Quando", render: (e) => <TimeAgo iso={e.created_at} /> },
          { key: "type", title: "Ação" },
          { key: "actor", title: "Autor" },
          {
            key: "details",
            title: "Detalhes",
            render: (e) => (
              <details>
                <summary>Exibir</summary>
                <pre>{JSON.stringify(e.details, null, 2)}</pre>
              </details>
            ),
          },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
      />
    </main>
  );
}
