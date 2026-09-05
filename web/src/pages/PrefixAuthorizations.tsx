import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useOrganizations,
  usePrefixAuthorizationCriar,
  usePrefixAuthorizationDesativar,
  usePrefixAuthorizations,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { PrefixAuthorizationOut } from "@/api/types";

const FORM_VAZIO = { organization_id: "", family: "ipv4" as "ipv4" | "ipv6", prefix: "", notes: "" };

export default function PrefixAuthorizations() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = usePrefixAuthorizations({ include_disabled: incluirInativos });
  const { data: organizations } = useOrganizations();
  const criar = usePrefixAuthorizationCriar();
  const desativar = usePrefixAuthorizationDesativar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<PrefixAuthorizationOut | null>(null);
  const [reativando, setReativando] = useState<PrefixAuthorizationOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        organization_id: Number(form.organization_id),
        family: form.family,
        prefix: form.prefix,
        notes: form.notes || null,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar autorização.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Prefixos autorizados" />
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
          <FormField label="Organização *">
            <select value={form.organization_id} onChange={(e) => setForm({ ...form, organization_id: e.target.value })} required>
              <option value="">—</option>
              {(organizations ?? []).map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Família">
            <select value={form.family} onChange={(e) => setForm({ ...form, family: e.target.value as "ipv4" | "ipv6" })}>
              <option value="ipv4">ipv4</option>
              <option value="ipv6">ipv6</option>
            </select>
          </FormField>
          <FormField label="Prefixo *">
            <input value={form.prefix} onChange={(e) => setForm({ ...form, prefix: e.target.value })} required />
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
      <DataTable<PrefixAuthorizationOut>
        colunas={[
          { key: "organization", title: "Organização", render: (z) => organizations?.find((o) => o.id === z.organization_id)?.name ?? "—" },
          { key: "family", title: "Família" },
          { key: "prefix", title: "Prefixo" },
          { key: "origin", title: "Origem" },
          { key: "notes", title: "Observações", render: (z) => z.notes ?? "—" },
          { key: "admin_status", title: "Situação", render: (z) => <StatusBadge estado={z.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(z) =>
          podeEscrever && z.admin_status ? (
            <button type="button" onClick={() => setDesativando(z)}>
              Desativar
            </button>
          ) : podeEscrever ? (
            <button type="button" onClick={() => setReativando(z)}>
              Reativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.prefix ?? ""}?`}
        mensagem="Para alterar um prefixo autorizado, desative e cadastre um novo."
        onConfirmar={() => {
          if (desativando)
            void desativar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar a autorização."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={desativar.isPending}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.prefix ?? ""}?`}
        mensagem="O prefixo volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void desativar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar a autorização."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={desativar.isPending}
      />
    </main>
  );
}
