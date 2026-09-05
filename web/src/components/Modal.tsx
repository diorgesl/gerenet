import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({
  aberto,
  titulo,
  onFechar,
  children,
  ariaLabel,
}: {
  aberto: boolean;
  titulo: string;
  onFechar: () => void;
  children: ReactNode;
  ariaLabel?: string;
}) {
  const tituloId = useId();
  const painelRef = useRef<HTMLDivElement>(null);
  // Ref para não re-executar o effect a cada render (onFechar é inline nos callers).
  const onFecharRef = useRef(onFechar);
  onFecharRef.current = onFechar;

  useEffect(() => {
    if (!aberto) return;
    const painel = painelRef.current;
    if (!painel) return;
    const anterior = document.activeElement as HTMLElement | null;
    const focaveis = () =>
      Array.from(painel.querySelectorAll<HTMLElement>(FOCUSABLE));
    (focaveis()[0] ?? painel).focus();

    function aoTeclar(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onFecharRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const els = focaveis();
      if (els.length === 0) {
        e.preventDefault();
        return;
      }
      const primeiro = els[0];
      const ultimo = els[els.length - 1];
      if (e.shiftKey && document.activeElement === primeiro) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primeiro.focus();
      }
    }
    document.addEventListener("keydown", aoTeclar);
    return () => {
      document.removeEventListener("keydown", aoTeclar);
      anterior?.focus();
    };
  }, [aberto]);

  if (!aberto) return null;
  return (
    <div
      className="dialog-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onFecharRef.current();
      }}
    >
      <div
        ref={painelRef}
        className="dialog dialog-scroll"
        role="dialog"
        aria-modal="true"
        aria-labelledby={tituloId}
        aria-label={ariaLabel}
        tabIndex={-1}
      >
        <h2 id={tituloId}>{titulo}</h2>
        {children}
      </div>
    </div>
  );
}
