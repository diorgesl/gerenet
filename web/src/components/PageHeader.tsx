import type { ReactNode } from "react";

export function PageHeader({ titulo, sub, acoes }: { titulo: string; sub?: string; acoes?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{titulo}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {acoes}
    </header>
  );
}
