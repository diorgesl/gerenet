type Estado =
  | "ok" | "fail" | "unknown"
  | "success" | "partial" | "error"
  | "queued" | "running"
  | "ativo" | "inativo"
  | string;

export function StatusBadge({ estado }: { estado: Estado }) {
  const cls =
    ["ok", "success", "ativo", "aprovado", "aplicado", "aprovar", "principal"].includes(estado) ? "ok"
    : ["fail", "error", "erro", "rejeitado", "cancelado", "falhou", "critica", "rejeitar"].includes(estado) ? "fail"
    : ["running", "queued", "aguardando_aprovacao", "executando", "pendente", "parcial", "com_divergencia", "contingencia", "diverge"].includes(estado) ? "warn"
    : "unknown";
  return <span className={`badge badge-${cls}`}>{estado}</span>;
}
