import type { ReactNode } from "react";

interface Props {
  label: string;
  erro?: string;
  children: ReactNode;
}

export function FormField({ label, erro, children }: Props) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {erro && <em role="alert">{erro}</em>}
    </label>
  );
}
