import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useCredentialGroupAtualizar,
  useCredentialGroupCriar,
  useCredentialGroups,
} from "@/api/hooks";
import { help } from "@/help";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import type { CredentialGroupOut } from "@/api/types";

const FORM_VAZIO = { name: "", vault_path: "", kind: "tacacs_password" };

export default function CredentialGroups() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useCredentialGroups({ includeDisabled: incluirInativos });
  const criar = useCredentialGroupCriar();
  const atualizar = useCredentialGroupAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<CredentialGroupOut | null>(null);
  const [reativando, setReativando] = useState<CredentialGroupOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<CredentialGroupOut | null>(null);
  const [formEdit, setFormEdit] = useState(FORM_VAZIO);
  const [erroEdit, setErroEdit] = useState<string | null>(null);

  function abrirEdicao(g: CredentialGroupOut) {
    setFormEdit({ name: g.name, vault_path: g.vault_path, kind: g.kind });
    setErroEdit(null);
    setEditando(g);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        name: formEdit.name,
        vault_path: formEdit.vault_path,
        kind: formEdit.kind,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar o grupo.");
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        vault_path: form.vault_path,
        kind: form.kind,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar o grupo.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Grupos de credencial" />
      <label className="inline-check">
        <input
          type="checkbox"
          checked={incluirInativos}
          onChange={(e) => setIncluirInativos(e.target.checked)}
        />
        Ver desativados
      </label>
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Nome *" help={help("credential_group.name")}>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="Caminho no Vault *" help={help("credential_group.vault_path")}>
            <input value={form.vault_path} onChange={(e) => setForm({ ...form, vault_path: e.target.value })} required />
          </FormField>
          <FormField label="Tipo" help={help("credential_group.kind")}>
            <input value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<CredentialGroupOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "kind", title: "Tipo" },
          { key: "vault_path", title: "Caminho no Vault" },
          {
            key: "admin_status",
            title: "Situação",
            render: (g) => <StatusBadge estado={g.admin_status ? "ativo" : "inativo"} />,
          },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(g) => (
          <>
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(g)}>
                Editar
              </button>
            )}
            {podeEscrever && g.admin_status ? (
              <button type="button" onClick={() => setDesativando(g)}>
                Desativar
              </button>
            ) : podeEscrever ? (
              <button type="button" onClick={() => setReativando(g)}>
                Reativar
              </button>
            ) : null}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O grupo fica indisponível para novos vínculos; equipamentos já vínculados mantêm o grupo."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar o grupo."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.name ?? ""}?`}
        mensagem="O grupo volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar o grupo."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Nome *" help={help("credential_group.name")}>
              <input value={formEdit.name} onChange={(e) => setFormEdit({ ...formEdit, name: e.target.value })} required />
            </FormField>
            <FormField label="Caminho no Vault *" help={help("credential_group.vault_path")}>
              <input value={formEdit.vault_path} onChange={(e) => setFormEdit({ ...formEdit, vault_path: e.target.value })} required />
            </FormField>
            <FormField label="Tipo" help={help("credential_group.kind")}>
              <input value={formEdit.kind} onChange={(e) => setFormEdit({ ...formEdit, kind: e.target.value })} />
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
