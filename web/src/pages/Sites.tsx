import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useSiteAtualizar, useSiteCriar, useSites } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { SiteOut } from "@/api/types";

const FORM_VAZIO = { name: "", city: "", uf: "", p2p_ipv4_block: "", p2p_ipv6_base: "" };

export default function Sites() {
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useSites();
  const criar = useSiteCriar();
  const atualizar = useSiteAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<SiteOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        city: form.city || null,
        uf: form.uf || null,
        p2p_ipv4_block: form.p2p_ipv4_block || null,
        p2p_ipv6_base: form.p2p_ipv6_base || null,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar site.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Sites" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="Cidade">
            <input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
          </FormField>
          <FormField label="UF">
            <input value={form.uf} onChange={(e) => setForm({ ...form, uf: e.target.value })} />
          </FormField>
          <FormField label="Bloco IPv4 p2p">
            <input value={form.p2p_ipv4_block} onChange={(e) => setForm({ ...form, p2p_ipv4_block: e.target.value })} />
          </FormField>
          <FormField label="Base IPv6 p2p">
            <input value={form.p2p_ipv6_base} onChange={(e) => setForm({ ...form, p2p_ipv6_base: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<SiteOut>
        colunas={[
          { key: "name", title: "Nome" },
          { key: "city", title: "Cidade", render: (s) => s.city ?? "—" },
          { key: "uf", title: "UF", render: (s) => s.uf ?? "—" },
          { key: "p2p_ipv4_block", title: "Bloco v4 p2p", render: (s) => s.p2p_ipv4_block ?? "—" },
          { key: "p2p_ipv6_base", title: "Base v6 p2p", render: (s) => s.p2p_ipv6_base ?? "—" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(s) =>
          podeEscrever && s.admin_status ? (
            <button type="button" onClick={() => setDesativando(s)}>
              Desativar
            </button>
          ) : null
        }
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="O site fica indisponível para novos cadastros; o registro permanece."
        onConfirmar={() => {
          if (desativando) void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
