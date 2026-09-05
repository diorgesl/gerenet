import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useContactAtualizar, useContactCriar, useContacts, useOrganizations } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ContactOut } from "@/api/types";

const FORM_VAZIO = { organization_id: "", name: "", email: "", phone: "", kind: "tecnico" as "tecnico" | "noc" | "admin" };

export default function Contacts() {
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useContacts();
  const { data: organizations } = useOrganizations();
  const criar = useContactCriar();
  const atualizar = useContactAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<ContactOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    if (form.organization_id === "") return;
    try {
      await criar.mutateAsync({
        organization_id: Number(form.organization_id),
        name: form.name,
        email: form.email || null,
        phone: form.phone || null,
        kind: form.kind,
      });
      setForm({ ...FORM_VAZIO });
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar contato.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Contatos" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Organização *">
            <select
              value={form.organization_id}
              onChange={(e) => setForm({ ...form, organization_id: e.target.value })}
              required
            >
              <option value="">—</option>
              {(organizations ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="E-mail">
            <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </FormField>
          <FormField label="Telefone">
            <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </FormField>
          <FormField label="Tipo">
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as "tecnico" | "noc" | "admin" })}
            >
              <option value="tecnico">tecnico</option>
              <option value="noc">noc</option>
              <option value="admin">admin</option>
            </select>
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<ContactOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "email", title: "E-mail", render: (c) => c.email ?? "—" },
          { key: "phone", title: "Telefone", render: (c) => c.phone ?? "—" },
          { key: "kind", title: "Tipo" },
          {
            key: "organization",
            title: "Organização",
            render: (c) => organizations?.find((o) => o.id === c.organization_id)?.name ?? "—",
          },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(c) =>
          podeEscrever && c.admin_status ? (
            <button type="button" onClick={() => setDesativando(c)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O contato fica indisponível para novos cadastros; o registro permanece."
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
