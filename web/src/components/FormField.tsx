import type { ReactNode } from "react";

interface Props {
  label: string;
  erro?: string;
  help?: string;
  children: ReactNode;
}

export function FormField({ label, erro, help, children }: Props) {
  return (
    <label className="field">
      <span>
        {label}
        {help && (
          <span className="field-help" tabIndex={0} aria-label={help}>
            <span className="field-help-dica" role="tooltip">
              {help}
            </span>
            ?
          </span>
        )}
      </span>
      {children}
      {erro && <em role="alert">{erro}</em>}
    </label>
  );
}
