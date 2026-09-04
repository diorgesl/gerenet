import type { ReactNode } from "react";

export interface Coluna<T> {
  key: string;
  title: string;
  render?: (linha: T) => ReactNode;
}

interface Props<T> {
  colunas: Coluna<T>[];
  linhas: T[];
  carregando?: boolean;
  vazio?: string;
  acoes?: (linha: T) => ReactNode;
}

export function DataTable<T>({ colunas, linhas, carregando, vazio = "Nenhum registro.", acoes }: Props<T>) {
  if (carregando) return <p aria-busy="true">Carregando…</p>;
  const vazioMsg = linhas.length === 0 ? <p>{vazio}</p> : null;
  return (
    <>
      <table>
        <thead>
          <tr>
            {colunas.map((c) => (
              <th key={c.key}>{c.title}</th>
            ))}
            {acoes && <th>Ações</th>}
          </tr>
        </thead>
        <tbody>
          {linhas.map((linha, i) => (
            <tr key={i}>
              {colunas.map((c) => (
                <td key={c.key}>{c.render ? c.render(linha) : String((linha as Record<string, unknown>)[c.key] ?? "")}</td>
              ))}
              {acoes && <td>{acoes(linha)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {vazioMsg}
    </>
  );
}
