export function SeverityBadge({ severidade }: { severidade: string }) {
  // "alerta" (anomalia de prefixos) compartilha o vermelho da "critica": é o
  // sinal mais urgente do feed de reconciliação — consistência > novidade.
  const cls =
    severidade === "critica" || severidade === "alerta" ? "danger" : severidade === "atencao" ? "warn" : "unknown";
  return <span className={`badge badge-${cls}`}>{severidade}</span>;
}
