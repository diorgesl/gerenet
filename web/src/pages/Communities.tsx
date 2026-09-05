import { useState } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useCommunities, useCommunityAtualizar } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import type { CommunityOut } from "@/api/types";
import type { FormEvent } from "react";

export default function Communities() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [reativando, setReativando] = useState<CommunityOut | null>(null);
  const [desativando, setDesativando] = useState<CommunityOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [detalhe, setDetalhe] = useState<CommunityOut | null>(null);
  const [editando, setEditando] = useState<CommunityOut | null>(null);
  const [formEdit, setFormEdit] = useState({ name: "", notes: "" });
  const [erroEdit, setErroEdit] = useState<string | null>(null);
  const { data, isLoading, error } = useCommunities({ includeDisabled: incluirInativos });
  const atualizar = useCommunityAtualizar();

  function abrirEdicao(c: CommunityOut) {
    setFormEdit({ name: c.name, notes: c.notes ?? "" });
    setErroEdit(null);
    setEditando(c);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({ id: editando.id, name: formEdit.name, notes: formEdit.notes || null });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar a community.");
    }
  }

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
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(c)}>
                Editar
              </button>
            )}
            {podeEscrever && c.admin_status && (
              <button type="button" onClick={() => setDesativando(c)}>
                Desativar
              </button>
            )}
            {podeEscrever && !c.admin_status && (
              <button type="button" onClick={() => setReativando(c)}>
                Reativar
              </button>
            )}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="A community fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar a community."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
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
        <Modal aberto titulo={detalhe.name} onFechar={() => setDetalhe(null)}>
          <p>{detalhe.notes ?? "Sem observações."}</p>
          <div className="dialog-actions">
            <button type="button" onClick={() => setDetalhe(null)}>Fechar</button>
          </div>
        </Modal>
      )}
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Nome *">
              <input value={formEdit.name} onChange={(e) => setFormEdit({ ...formEdit, name: e.target.value })} required />
            </FormField>
            <FormField label="Observações">
              <input value={formEdit.notes} onChange={(e) => setFormEdit({ ...formEdit, notes: e.target.value })} />
            </FormField>
            <div className="dialog-actions">
              <button type="button" onClick={() => setEditando(null)} disabled={atualizar.isPending}>
                Cancelar
              </button>
              <button className="primary" type="submit" disabled={atualizar.isPending}>
                {atualizar.isPending ? "Salvando…" : "Salvar"}
              </button>
            </div>
          </form>
          {erroEdit && <p role="alert">{erroEdit}</p>}
        </Modal>
      )}
    </main>
  );
}
