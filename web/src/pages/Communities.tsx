import { useState } from "react";
import { useCommunities } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import type { CommunityOut } from "@/api/types";

export default function Communities() {
  const { data, isLoading } = useCommunities();
  const [detalhe, setDetalhe] = useState<CommunityOut | null>(null);
  return (
    <main>
      <PageHeader titulo="Communities" />
      <DataTable<CommunityOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "notes", title: "Observações", render: (c) => c.notes ?? "—" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(c) => (
          <button type="button" onClick={() => setDetalhe(c)}>
            Detalhar
          </button>
        )}
      />
      {detalhe && (
        <div role="dialog" aria-modal="true" aria-label={`Dados de ${detalhe.name}`}>
          <h2>{detalhe.name}</h2>
          <p>{detalhe.notes ?? "Sem observações."}</p>
          <button onClick={() => setDetalhe(null)}>Fechar</button>
        </div>
      )}
    </main>
  );
}
