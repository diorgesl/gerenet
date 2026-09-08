import { useState } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useCommunities, useCommunityAtualizar, useCommunityCriar } from "@/api/hooks";
import { help } from "@/help";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import type { CommunityOut } from "@/api/types";
import type { FormEvent } from "react";

// Espelha models.COMMUNITY_TIPO (models.py:53) — os 6 valores efetivos do VRP/back-end.
const COMMUNITY_TIPO = ["padrao", "acao_blackhole", "acao_prepend", "acao_lp", "informacao", "tag_produto"] as const;
const COMMUNITY_TIPO_LABEL: Record<(typeof COMMUNITY_TIPO)[number], string> = {
  padrao: "Padrão",
  acao_blackhole: "Blackhole",
  acao_prepend: "Prepend",
  acao_lp: "Local-pref",
  informacao: "Informação",
  tag_produto: "Tag de produto",
};

export default function Communities() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [reativando, setReativando] = useState<CommunityOut | null>(null);
  const [desativando, setDesativando] = useState<CommunityOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [detalhe, setDetalhe] = useState<CommunityOut | null>(null);
  const [editando, setEditando] = useState<CommunityOut | null>(null);
  const [formEdit, setFormEdit] = useState({ name: "", tipo: "padrao", notes: "" });
  const [erroEdit, setErroEdit] = useState<string | null>(null);
  const [criando, setCriando] = useState(false);
  const [formNovo, setFormNovo] = useState({ name: "", tipo: "padrao", notes: "" });
  const [erroNovo, setErroNovo] = useState<string | null>(null);
  const { data, isLoading, error } = useCommunities({ includeDisabled: incluirInativos });
  const criar = useCommunityCriar();
  const atualizar = useCommunityAtualizar();

  function abrirCriacao() {
    setFormNovo({ name: "", tipo: "padrao", notes: "" });
    setErroNovo(null);
    setCriando(true);
  }

  async function salvarCriacao(e: FormEvent) {
    e.preventDefault();
    setErroNovo(null);
    try {
      await criar.mutateAsync({ name: formNovo.name, tipo: formNovo.tipo, notes: formNovo.notes || null });
      setCriando(false);
    } catch (err) {
      setErroNovo(err instanceof ApiError ? err.message : "Falha ao criar a community.");
    }
  }

  function abrirEdicao(c: CommunityOut) {
    setFormEdit({ name: c.name, tipo: c.tipo, notes: c.notes ?? "" });
    setErroEdit(null);
    setEditando(c);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({ id: editando.id, name: formEdit.name, tipo: formEdit.tipo, notes: formEdit.notes || null });
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
      {podeEscrever && (
        <button className="primary" type="button" onClick={abrirCriacao}>
          Nova community
        </button>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<CommunityOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "tipo", title: "Tipo", render: (c) => COMMUNITY_TIPO_LABEL[c.tipo as (typeof COMMUNITY_TIPO)[number]] ?? c.tipo },
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
      {criando && (
        <Modal aberto titulo="Nova community" onFechar={() => setCriando(false)}>
          <form onSubmit={salvarCriacao} className="grid-form">
            <FormField label="Nome *" help={help("community.name")}>
              <input value={formNovo.name} onChange={(e) => setFormNovo({ ...formNovo, name: e.target.value })} required />
            </FormField>
            <FormField label="Tipo" help={help("community.tipo")}>
              <select value={formNovo.tipo} onChange={(e) => setFormNovo({ ...formNovo, tipo: e.target.value })}>
                {COMMUNITY_TIPO.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Observações" help={help("community.notes")}>
              <input value={formNovo.notes} onChange={(e) => setFormNovo({ ...formNovo, notes: e.target.value })} />
            </FormField>
            <div className="dialog-actions">
              <button type="button" onClick={() => setCriando(false)} disabled={criar.isPending}>
                Cancelar
              </button>
              <button className="primary" type="submit" disabled={criar.isPending}>
                {criar.isPending ? "Criando…" : "Criar"}
              </button>
            </div>
          </form>
          {erroNovo && <p role="alert">{erroNovo}</p>}
        </Modal>
      )}
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Nome *" help={help("community.name")}>
              <input value={formEdit.name} onChange={(e) => setFormEdit({ ...formEdit, name: e.target.value })} required />
            </FormField>
            <FormField label="Tipo" help={help("community.tipo")}>
              <select value={formEdit.tipo} onChange={(e) => setFormEdit({ ...formEdit, tipo: e.target.value })}>
                {COMMUNITY_TIPO.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Observações" help={help("community.notes")}>
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
