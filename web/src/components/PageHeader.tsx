import type { ReactNode } from "react";

export function PageHeader({ titulo, acoes }: { titulo: string; acoes?: ReactNode }) {
  return (
    <header className="page-header">
      <h1>{titulo}</h1>
      {acoes}
    </header>
  );
}
