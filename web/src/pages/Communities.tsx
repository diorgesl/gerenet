import { useState } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useCommunities, useCommunityAtualizar } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { CommunityOut } from "@/api/types";

export default function Communities() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [reativando, setReativando] = useState<CommunityOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [detalhe, setDetalhe] = useState<CommunityOut | null>(null);
  const { data, isLoading, error } = useCommunities({ includeDisabled: incluirInativos });
  const atualizar = useCommunityAtualizar();
  return (
    <main>
      <PageHeader titulo="Communities" />
      <label className="inline-check">
        <input
          type="checkbox"
          checked={incluirInativos}
          onChange={(e) => setIncluirInativos(e.target.checked)}
        />
        Ver desativados
      </label>
      {erro && <p role="alert">{erro}</p>}
      <DataTable<CommunityOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "notes", title: "Observações", render: (c) => c.notes ?? "—" },
          { key: "admin_status", title: "Situação", render: (c) => <StatusBadge estado={c.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(c) => (
          <>
            <button type="button" onClick={() => setDetalhe(c)}>
              Detalhar
            </button>
            {podeEscrever && !c.admin_status && (
              <button type="button" onClick={() => setReativando(c)}>
                Reativar
              </button>
            )}
          </>
        )}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.name ?? ""}?`}
        mensagem="A community volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar a community."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
      {detalhe && (
        <div role="dialog" aria-modal="true" aria-label={`Dados de ${detalhe.name}`}>
          <h2>{detalhe.name}</h2>
          <p>{detalhe.notes ?? "Sem observações."}</p>
          <button onClick={() => setDetalhe(null)}>Fechar</button>
        </div>
      )}
    </main>
  );
}
