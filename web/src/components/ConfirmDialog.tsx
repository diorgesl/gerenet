export function ConfirmDialog({
  aberto,
  titulo,
  mensagem,
  onConfirmar,
  onCancelar,
  confirmando,
}: {
  aberto: boolean;
  titulo: string;
  mensagem: string;
  onConfirmar: () => void;
  onCancelar: () => void;
  confirmando?: boolean;
}) {
  if (!aberto) return null;
  return (
    <div role="dialog" aria-modal="true" aria-label={titulo} className="dialog-backdrop">
      <div className="dialog">
        <h2>{titulo}</h2>
        <p>{mensagem}</p>
        <div className="dialog-actions">
          <button onClick={onCancelar} disabled={confirmando}>
            Cancelar
          </button>
          <button className="danger" onClick={onConfirmar} disabled={confirmando}>
            {confirmando ? "Aguarde…" : "Confirmar"}
          </button>
        </div>
      </div>
    </div>
  );
}
