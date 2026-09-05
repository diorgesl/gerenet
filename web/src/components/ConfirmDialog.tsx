import { Modal } from "@/components/Modal";

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
  // API preservada (spec S2.1): a implementação passa a ser o Modal com a11y.
  return (
    <Modal aberto={aberto} titulo={titulo} onFechar={onCancelar}>
      <p>{mensagem}</p>
      <div className="dialog-actions">
        <button onClick={onCancelar} disabled={confirmando}>
          Cancelar
        </button>
        <button className="danger" onClick={onConfirmar} disabled={confirmando}>
          {confirmando ? "Aguarde…" : "Confirmar"}
        </button>
      </div>
    </Modal>
  );
}
