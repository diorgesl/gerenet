type Estado =
  | "ok" | "fail" | "unknown"
  | "success" | "partial" | "error"
  | "queued" | "running"
  | "ativo" | "inativo"
  | string;

export function StatusBadge({ estado }: { estado: Estado }) {
  const cls =
    ["ok", "success", "ativo"].includes(estado) ? "ok"
    : ["fail", "error"].includes(estado) ? "fail"
    : ["running", "queued"].includes(estado) ? "warn"
    : "unknown";
  return <span className={`badge badge-${cls}`}>{estado}</span>;
}
