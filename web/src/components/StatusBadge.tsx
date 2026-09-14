type Estado =
  | "ok" | "fail" | "unknown"
  | "success" | "partial" | "error"
  | "queued" | "running"
  | "ativo" | "inativo"
  | string;

export function StatusBadge({ estado }: { estado: Estado }) {
  // "up"/"down" são o estado operacional dos serviços MPLS (§9.3): sem eles
  // aqui, VSI e L2VC de pé saíam no mesmo cinza de "unknown".
  const cls =
    ["ok", "success", "ativo", "aprovado", "aplicado", "aprovar", "principal", "up"].includes(estado) ? "ok"
    : ["fail", "error", "erro", "rejeitado", "cancelado", "falhou", "critica", "rejeitar", "down"].includes(estado) ? "fail"
    : ["running", "queued", "aguardando_aprovacao", "executando", "pendente", "parcial", "com_divergencia", "contingencia", "diverge"].includes(estado) ? "warn"
    : "unknown";
  return <span className={`badge badge-${cls}`}>{estado}</span>;
}
