import { useState } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { usePolicyProfiles, usePolicyProfileAtualizar } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { MonoCode } from "@/components/MonoCode";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { PolicyProfileOut } from "@/api/types";

export default function PolicyProfiles() {
  const { podeEscrever } = useAuth();
  const [direcao, setDirecao] = useState("");
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [reativando, setReativando] = useState<PolicyProfileOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const { data, isLoading, error } = usePolicyProfiles({
    direction: direcao || undefined,
    include_disabled: incluirInativos,
  });
  const atualizar = usePolicyProfileAtualizar();
  return (
    <main>
      <PageHeader
        titulo="Perfis de política"
        acoes={
          <select value={direcao} onChange={(e) => setDirecao(e.target.value)} aria-label="Direção">
            <option value="">todas</option>
            <option value="import">import</option>
            <option value="export">export</option>
          </select>
        }
      />
      <label className="inline-check">
        <input
          type="checkbox"
          checked={incluirInativos}
          onChange={(e) => setIncluirInativos(e.target.checked)}
        />
        Ver desativados
      </label>
      {erro && <p role="alert">{erro}</p>}
      <DataTable<PolicyProfileOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "label", title: "Produto" },
          { key: "direction", title: "Direção", render: (p) => <StatusBadge estado={p.direction} /> },
          { key: "kind", title: "Tipo" },
          { key: "prefixes", title: "Prefixos", render: (p) => (p.prefixes && p.prefixes.length > 0 ? <MonoCode texto={p.prefixes.join("\n")} /> : "—") },
          { key: "notes", title: "Observações", render: (p) => p.notes ?? "—" },
          { key: "admin_status", title: "Situação", render: (p) => <StatusBadge estado={p.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(p) =>
          podeEscrever && !p.admin_status ? (
            <button type="button" onClick={() => setReativando(p)}>
              Reativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.name ?? ""}?`}
        mensagem="O perfil volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar o perfil."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
