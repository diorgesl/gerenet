import { useParams } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";

// Stub do ciclo D1 — o detalhe real (circuitos vinculados, sessões BGP e
// communities de operadora) chega na D3 da fase 5 (spec §7).
export default function UpstreamDetail() {
  const { id } = useParams();
  return (
    <div>
      <PageHeader titulo={`Upstream #${id}`} sub="Detalhe de conectividade própria." />
      <p>Página em construção — a fase 5 (upstreams BGP) está em andamento.</p>
    </div>
  );
}
