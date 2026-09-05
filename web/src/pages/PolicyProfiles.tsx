import { useState } from "react";
import { ApiError } from "@/api/client";
import { usePolicyProfiles } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { MonoCode } from "@/components/MonoCode";
import type { PolicyProfileOut } from "@/api/types";

export default function PolicyProfiles() {
  const [direcao, setDirecao] = useState("");
  const { data, isLoading, error } = usePolicyProfiles(direcao ? { direction: direcao } : {});
  return (
    <main>
      <PageHeader
        titulo="Perfis de política"
        acoes={
          <select value={direcao} onChange={(e) => setDirecao(e.target.value)} aria-label="Direção">
            <option value="">todas</option>
            <option value="import">import</option>
            <option value="export">export</option>
          </select>
        }
      />
      <DataTable<PolicyProfileOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "label", title: "Produto" },
          { key: "direction", title: "Direção", render: (p) => <StatusBadge estado={p.direction} /> },
          { key: "kind", title: "Tipo" },
          { key: "prefixes", title: "Prefixos", render: (p) => (p.prefixes && p.prefixes.length > 0 ? <MonoCode texto={p.prefixes.join("\n")} /> : "—") },
          { key: "notes", title: "Observações", render: (p) => p.notes ?? "—" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
      />
    </main>
  );
}
