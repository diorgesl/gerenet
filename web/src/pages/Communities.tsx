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
// Espelha models.COMMUNITY_BANDA — a partição do plano de communities (§5).
const COMMUNITY_BANDA = ["local", "transito", "cliente", "parceiro", "conjunto", "tamanho", "especial", "instrucao"] as const;

/** Campo vazio é ausência de valor, e não zero: o serviço grava `None` na coluna. */
const num = (v: string) => (v === "" ? null : Number(v));

export default function Communities() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [reativando, setReativando] = useState<CommunityOut | null>(null);
  const [desativando, setDesativando] = useState<CommunityOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [detalhe, setDetalhe] = useState<CommunityOut | null>(null);
  const [editando, setEditando] = useState<CommunityOut | null>(null);
  const [formEdit, setFormEdit] = useState({ name: "", tipo: "padrao", notes: "", valor_v4: "", valor_v6: "", banda: "" });
  const [erroEdit, setErroEdit] = useState<string | null>(null);
  const [criando, setCriando] = useState(false);
  const [formNovo, setFormNovo] = useState({ name: "", tipo: "padrao", notes: "", valor_v4: "", valor_v6: "", banda: "" });
  const [erroNovo, setErroNovo] = useState<string | null>(null);
  const { data, isLoading, error } = useCommunities({ includeDisabled: incluirInativos });
  const criar = useCommunityCriar();
  const atualizar = useCommunityAtualizar();

  function abrirCriacao() {
    setFormNovo({ name: "", tipo: "padrao", notes: "", valor_v4: "", valor_v6: "", banda: "" });
    setErroNovo(null);
    setCriando(true);
  }

  async function salvarCriacao(e: FormEvent) {
    e.preventDefault();
    setErroNovo(null);
    try {
      await criar.mutateAsync({
        name: formNovo.name,
        tipo: formNovo.tipo,
        notes: formNovo.notes || null,
        valor_v4: num(formNovo.valor_v4),
        valor_v6: num(formNovo.valor_v6),
        banda: formNovo.banda || null,
      });
      setCriando(false);
    } catch (err) {
      setErroNovo(err instanceof ApiError ? err.message : "Falha ao criar a community.");
    }
  }

  function abrirEdicao(c: CommunityOut) {
    setFormEdit({
      name: c.name,
      tipo: c.tipo,
      notes: c.notes ?? "",
      valor_v4: c.valor_v4 === null ? "" : String(c.valor_v4),
      valor_v6: c.valor_v6 === null ? "" : String(c.valor_v6),
      banda: c.banda ?? "",
    });
    setErroEdit(null);
    setEditando(c);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        name: formEdit.name,
        tipo: formEdit.tipo,
        notes: formEdit.notes || null,
        valor_v4: num(formEdit.valor_v4),
        valor_v6: num(formEdit.valor_v6),
        banda: formEdit.banda || null,
      });
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
          { key: "valor_v4", title: "v4", render: (c) => c.valor_v4 ?? "—" },
          { key: "valor_v6", title: "v6", render: (c) => c.valor_v6 ?? "—" },
          { key: "banda", title: "Banda", render: (c) => c.banda ?? "—" },
          { key: "origem", title: "Origem", render: (c) => (c.origem === "adotado" ? "adotada" : "manual") },
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
            <FormField label="Valor v4" help={help("community.valor_v4")}>
              <input type="number" value={formNovo.valor_v4} onChange={(e) => setFormNovo({ ...formNovo, valor_v4: e.target.value })} />
            </FormField>
            <FormField label="Valor v6" help={help("community.valor_v6")}>
              <input type="number" value={formNovo.valor_v6} onChange={(e) => setFormNovo({ ...formNovo, valor_v6: e.target.value })} />
            </FormField>
            <FormField label="Banda" help={help("community.banda")}>
              <select value={formNovo.banda} onChange={(e) => setFormNovo({ ...formNovo, banda: e.target.value })}>
                <option value="">—</option>
                {COMMUNITY_BANDA.map((b) => (
                  <option key={b} value={b}>{b}</option>
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
            <FormField label="Valor v4" help={help("community.valor_v4")}>
              <input type="number" value={formEdit.valor_v4} onChange={(e) => setFormEdit({ ...formEdit, valor_v4: e.target.value })} />
            </FormField>
            <FormField label="Valor v6" help={help("community.valor_v6")}>
              <input type="number" value={formEdit.valor_v6} onChange={(e) => setFormEdit({ ...formEdit, valor_v6: e.target.value })} />
            </FormField>
            <FormField label="Banda" help={help("community.banda")}>
              <select value={formEdit.banda} onChange={(e) => setFormEdit({ ...formEdit, banda: e.target.value })}>
                <option value="">—</option>
                {COMMUNITY_BANDA.map((b) => (
                  <option key={b} value={b}>{b}</option>
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
