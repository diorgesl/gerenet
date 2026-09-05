export function TimeAgo({ iso }: { iso: string | null }) {
  if (!iso) return <span>—</span>;
  const dt = new Date(iso);
  const s = Math.round((dt.getTime() - Date.now()) / 1000);
  const abs = Math.abs(s);
  const texto =
    abs < 60 ? "agora"
    : abs < 3600 ? `há ${Math.round(abs / 60)}min`
    : abs < 86400 ? `há ${Math.round(abs / 3600)}h`
    : `há ${Math.round(abs / 86400)}d`;
  return <span title={dt.toLocaleString("pt-BR")}>{texto}</span>;
}
