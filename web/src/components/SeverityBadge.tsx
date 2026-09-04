export function SeverityBadge({ severidade }: { severidade: string }) {
  const cls = severidade === "critica" ? "danger" : severidade === "atencao" ? "warn" : "unknown";
  return <span className={`badge badge-${cls}`}>{severidade}</span>;
}
