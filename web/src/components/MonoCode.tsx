import { useState } from "react";

export function MonoCode({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  async function copiar() {
    await navigator.clipboard.writeText(texto);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 1500);
  }
  return (
    <div className="mono-block">
      <button type="button" onClick={copiar}>
        {copiado ? "Copiado ✓" : "Copiar"}
      </button>
      <pre>{texto}</pre>
    </div>
  );
}
