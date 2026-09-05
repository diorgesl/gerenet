import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { usePolicyProfiles, usePolicyProfileAtualizar } from "@/api/hooks";
import { help } from "@/help";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { MonoCode } from "@/components/MonoCode";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import type { PolicyProfileOut } from "@/api/types";

export default function PolicyProfiles() {
  const { podeEscrever } = useAuth();
  const [direcao, setDirecao] = useState("");
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [reativando, setReativando] = useState<PolicyProfileOut | null>(null);
  const [desativando, setDesativando] = useState<PolicyProfileOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<PolicyProfileOut | null>(null);
  const [formEdit, setFormEdit] = useState({ name: "", label: "", direction: "import" as "import" | "export", kind: "produto", prefixes: "", notes: "" });
  const [erroEdit, setErroEdit] = useState<string | null>(null);
  const { data, isLoading, error } = usePolicyProfiles({
    direction: direcao || undefined,
    include_disabled: incluirInativos,
  });
  const atualizar = usePolicyProfileAtualizar();

  function abrirEdicao(p: PolicyProfileOut) {
    setFormEdit({
      name: p.name,
      label: p.label,
      direction: p.direction,
      kind: p.kind,
      prefixes: (p.prefixes ?? []).join("\n"),
      notes: p.notes ?? "",
    });
    setErroEdit(null);
    setEditando(p);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        name: formEdit.name,
        label: formEdit.label,
        direction: formEdit.direction,
        kind: formEdit.kind,
        prefixes: formEdit.prefixes.split("\n").map((t) => t.trim()).filter(Boolean),
        notes: formEdit.notes || null,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar o perfil.");
    }
  }

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
        acoes={(p) => (
          <>
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(p)}>
                Editar
              </button>
            )}
            {podeEscrever && p.admin_status && (
              <button type="button" onClick={() => setDesativando(p)}>
                Desativar
              </button>
            )}
            {podeEscrever && !p.admin_status ? (
              <button type="button" onClick={() => setReativando(p)}>
                Reativar
              </button>
            ) : null}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O perfil fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar o perfil."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
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
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Nome *" help={help("policy.name")}>
              <input value={formEdit.name} onChange={(e) => setFormEdit({ ...formEdit, name: e.target.value })} required />
            </FormField>
            <FormField label="Produto" help={help("policy.product")}>
              <input value={formEdit.label} onChange={(e) => setFormEdit({ ...formEdit, label: e.target.value })} required />
            </FormField>
            <FormField label="Direção" help={help("policy.direction")}>
              <select
                value={formEdit.direction}
                onChange={(e) => setFormEdit({ ...formEdit, direction: e.target.value as "import" | "export" })}
              >
                <option value="import">import</option>
                <option value="export">export</option>
              </select>
            </FormField>
            <FormField label="Tipo" help={help("policy.kind")}>
              <select value={formEdit.kind} onChange={(e) => setFormEdit({ ...formEdit, kind: e.target.value })}>
                <option value="produto">produto</option>
              </select>
            </FormField>
            <FormField label="Prefixos" help={help("policy.prefixes")}>
              <textarea
                value={formEdit.prefixes}
                onChange={(e) => setFormEdit({ ...formEdit, prefixes: e.target.value })}
                rows={5}
              />
            </FormField>
            <FormField label="Observações" help={help("policy.notes")}>
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
