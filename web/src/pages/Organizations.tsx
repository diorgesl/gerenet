import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useOrganizationAtualizar, useOrganizationCriar, useOrganizations } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { OrganizationOut } from "@/api/types";

const FORM_VAZIO = { name: "", legal_name: "", kind: "downstream" as "downstream" | "parceiro", asn: "", irr_as_set: "", notes: "" };

export default function Organizations() {
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useOrganizations();
  const criar = useOrganizationCriar();
  const atualizar = useOrganizationAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<OrganizationOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

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
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="Razão social">
            <input value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} />
          </FormField>
          <FormField label="Tipo">
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as "downstream" | "parceiro" })}
            >
              <option value="downstream">downstream</option>
              <option value="parceiro">parceiro</option>
            </select>
          </FormField>
          <FormField label="ASN">
            <input type="number" value={form.asn} onChange={(e) => setForm({ ...form, asn: e.target.value })} />
          </FormField>
          <FormField label="IRR AS-SET">
            <input value={form.irr_as_set} onChange={(e) => setForm({ ...form, irr_as_set: e.target.value })} />
          </FormField>
          <FormField label="Observações">
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
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(o) =>
          podeEscrever && o.admin_status ? (
            <button type="button" onClick={() => setDesativando(o)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="A organização fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
