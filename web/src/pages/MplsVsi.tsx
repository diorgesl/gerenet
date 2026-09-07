import { Link } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useVsi } from "@/api/hooks";
import type { VsiOut } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";

export default function MplsVsi() {
  const { data, isLoading, error } = useVsi();

  return (
    <main>
      <PageHeader titulo="VSIs" sub="Serviços multiponto (VPLS) no domínio MPLS — consulta, sem provisionamento automático neste ciclo." />
      <DataTable<VsiOut>
        colunas={[
          { key: "id", title: "ID", render: (v) => <Link to={`/mpls/vsi/${v.id}`}>#{v.id}</Link> },
          { key: "name", title: "Nome", render: (v) => <Link to={`/mpls/vsi/${v.id}`}>{v.name}</Link> },
          { key: "vrp_name", title: "Nome VRP", render: (v) => v.vrp_name },
          { key: "vsi_id", title: "VSI-ID" },
          { key: "domains", title: "Domínio", render: (v) => v.domain_name ?? `#${v.domain_id}` },
          { key: "admin_status", title: "Situação", render: (v) => <StatusBadge estado={v.admin_status ? "ativo" : "inativo"} /> },
          { key: "operational_status", title: "Estado operacional", render: (v) => <StatusBadge estado={v.operational_status} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os VSIs." : undefined}
      />
    </main>
  );
}
