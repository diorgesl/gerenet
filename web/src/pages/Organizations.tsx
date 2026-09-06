import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useOrganizationAtualizar, useOrganizationCriar, useOrganizations } from "@/api/hooks";
import { help } from "@/help";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import type { OrganizationOut } from "@/api/types";

const FORM_VAZIO = { name: "", legal_name: "", kind: "downstream" as "downstream" | "parceiro", asn: "", irr_as_set: "", notes: "" };

export default function Organizations() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useOrganizations({ includeDisabled: incluirInativos });
  const criar = useOrganizationCriar();
  const atualizar = useOrganizationAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<OrganizationOut | null>(null);
  const [reativando, setReativando] = useState<OrganizationOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<OrganizationOut | null>(null);
  const [formEdit, setFormEdit] = useState(FORM_VAZIO);
  const [erroEdit, setErroEdit] = useState<string | null>(null);

  function abrirEdicao(o: OrganizationOut) {
    setFormEdit({
      name: o.name,
      legal_name: o.legal_name ?? "",
      kind: o.kind as "downstream" | "parceiro",
      asn: o.asn === null ? "" : String(o.asn),
      irr_as_set: o.irr_as_set ?? "",
      notes: o.notes ?? "",
    });
    setErroEdit(null);
    setEditando(o);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        name: formEdit.name,
        legal_name: formEdit.legal_name || null,
        kind: formEdit.kind,
        asn: formEdit.asn === "" ? null : Number(formEdit.asn),
        irr_as_set: formEdit.irr_as_set || null,
        notes: formEdit.notes || null,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar a organização.");
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        legal_name: form.legal_name || null,
        kind: form.kind,
        asn: form.asn === "" ? null : Number(form.asn),
        irr_as_set: form.irr_as_set || null,
        notes: form.notes || null,
      });
      setForm({ ...FORM_VAZIO });
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar organização.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Organizações" />
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
          <FormField label="Nome *" help={help("organization.name")}>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="Razão social" help={help("organization.legal_name")}>
            <input value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} />
          </FormField>
          <FormField label="Tipo" help={help("organization.kind")}>
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as "downstream" | "parceiro" })}
            >
              <option value="downstream">downstream</option>
              <option value="parceiro">parceiro</option>
            </select>
          </FormField>
          <FormField label="ASN" help={help("organization.asn")}>
            <input type="number" value={form.asn} onChange={(e) => setForm({ ...form, asn: e.target.value })} />
          </FormField>
          <FormField label="IRR AS-SET" help={help("organization.irr_as_set")}>
            <input value={form.irr_as_set} onChange={(e) => setForm({ ...form, irr_as_set: e.target.value })} />
          </FormField>
          <FormField label="Observações" help={help("organization.notes")}>
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<OrganizationOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "legal_name", title: "Razão social", render: (o) => o.legal_name ?? "—" },
          { key: "kind", title: "Tipo", render: (o) => <StatusBadge estado={o.kind} /> },
          { key: "asn", title: "ASN", render: (o) => o.asn ?? "—" },
          { key: "irr_as_set", title: "IRR AS-SET", render: (o) => o.irr_as_set ?? "—" },
          { key: "notes", title: "Observações", render: (o) => o.notes ?? "—" },
          { key: "admin_status", title: "Situação", render: (o) => <StatusBadge estado={o.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(o) => (
          <>
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(o)}>
                Editar
              </button>
            )}
            {podeEscrever && o.admin_status ? (
              <button type="button" onClick={() => setDesativando(o)}>
                Desativar
              </button>
            ) : podeEscrever ? (
              <button type="button" onClick={() => setReativando(o)}>
                Reativar
              </button>
            ) : null}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="A organização fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar a organização."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.name ?? ""}?`}
        mensagem="A organização volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar a organização."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Nome *" help={help("organization.name")}>
              <input value={formEdit.name} onChange={(e) => setFormEdit({ ...formEdit, name: e.target.value })} required />
            </FormField>
            <FormField label="Razão social" help={help("organization.legal_name")}>
              <input value={formEdit.legal_name} onChange={(e) => setFormEdit({ ...formEdit, legal_name: e.target.value })} />
            </FormField>
            <FormField label="Tipo" help={help("organization.kind")}>
              <select
                value={formEdit.kind}
                onChange={(e) => setFormEdit({ ...formEdit, kind: e.target.value as "downstream" | "parceiro" })}
              >
                <option value="downstream">downstream</option>
                <option value="parceiro">parceiro</option>
              </select>
            </FormField>
            <FormField label="ASN" help={help("organization.asn")}>
              <input type="number" value={formEdit.asn} onChange={(e) => setFormEdit({ ...formEdit, asn: e.target.value })} />
            </FormField>
            <FormField label="IRR AS-SET" help={help("organization.irr_as_set")}>
              <input value={formEdit.irr_as_set} onChange={(e) => setFormEdit({ ...formEdit, irr_as_set: e.target.value })} />
            </FormField>
            <FormField label="Observações" help={help("organization.notes")}>
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
