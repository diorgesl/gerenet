import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useBgpSessionAtualizar,
  useBgpSessionCriar,
  useBgpSessions,
  useCircuits,
  useDevices,
  usePolicyProfiles,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { BgpSessionOut } from "@/api/types";

const FORM_VAZIO = {
  circuit_id: "",
  device_id: "",
  afi: "ipv4" as "ipv4" | "ipv6",
  local_address: "",
  remote_address: "",
  source_address: "",
  asn_local: "",
  asn_remote: "",
  description: "",
  import_profile_id: "",
  export_profile_id: "",
  maximum_prefix: "",
  maximum_prefix_threshold: "",
  local_preference: "",
  med: "",
  prepend: "",
  keepalive: "",
  holdtime: "",
  bfd_enabled: false,
  graceful_restart: false,
  shutdown: false,
  allow_default_route: false,
};

export default function BgpSessions() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useBgpSessions({ include_disabled: incluirInativos });
  const { data: circuits } = useCircuits();
  const { data: devices } = useDevices();
  const { data: profiles } = usePolicyProfiles();
  const criar = useBgpSessionCriar();
  const atualizar = useBgpSessionAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<BgpSessionOut | null>(null);
  const [reativando, setReativando] = useState<BgpSessionOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const num = (v: string) => (v === "" ? null : Number(v));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        circuit_id: Number(form.circuit_id),
        device_id: Number(form.device_id),
        afi: form.afi,
        local_address: form.local_address,
        remote_address: form.remote_address,
        source_address: form.source_address || null,
        asn_local: num(form.asn_local),
        asn_remote: num(form.asn_remote),
        description: form.description || null,
        import_profile_id: form.import_profile_id === "" ? null : Number(form.import_profile_id),
        export_profile_id: form.export_profile_id === "" ? null : Number(form.export_profile_id),
        maximum_prefix: num(form.maximum_prefix),
        maximum_prefix_threshold: num(form.maximum_prefix_threshold),
        local_preference: num(form.local_preference),
        med: num(form.med),
        prepend: num(form.prepend),
        keepalive: num(form.keepalive),
        holdtime: num(form.holdtime),
        bfd_enabled: form.bfd_enabled,
        graceful_restart: form.graceful_restart,
        shutdown: form.shutdown,
        allow_default_route: form.allow_default_route,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar sessão BGP.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Sessões BGP" />
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
          <FormField label="Circuito *">
            <select value={form.circuit_id} onChange={(e) => setForm({ ...form, circuit_id: e.target.value })} required>
              <option value="">—</option>
              {(circuits ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.code}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Equipamento *">
            <select value={form.device_id} onChange={(e) => setForm({ ...form, device_id: e.target.value })} required>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Família">
            <select value={form.afi} onChange={(e) => setForm({ ...form, afi: e.target.value as "ipv4" | "ipv6" })}>
              <option value="ipv4">ipv4</option>
              <option value="ipv6">ipv6</option>
            </select>
          </FormField>
          <FormField label="Endereço local *">
            <input value={form.local_address} onChange={(e) => setForm({ ...form, local_address: e.target.value })} required />
          </FormField>
          <FormField label="Endereço remoto *">
            <input value={form.remote_address} onChange={(e) => setForm({ ...form, remote_address: e.target.value })} required />
          </FormField>
          <FormField label="Source address">
            <input value={form.source_address} onChange={(e) => setForm({ ...form, source_address: e.target.value })} />
          </FormField>
          <FormField label="ASN local">
            <input type="number" value={form.asn_local} onChange={(e) => setForm({ ...form, asn_local: e.target.value })} />
          </FormField>
          <FormField label="ASN remoto">
            <input type="number" value={form.asn_remote} onChange={(e) => setForm({ ...form, asn_remote: e.target.value })} />
          </FormField>
          <FormField label="Descrição">
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </FormField>
          <FormField label="Perfil de importação">
            <select value={form.import_profile_id} onChange={(e) => setForm({ ...form, import_profile_id: e.target.value })}>
              <option value="">—</option>
              {(profiles ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Perfil de exportação">
            <select value={form.export_profile_id} onChange={(e) => setForm({ ...form, export_profile_id: e.target.value })}>
              <option value="">—</option>
              {(profiles ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Maximum-prefix">
            <input type="number" value={form.maximum_prefix} onChange={(e) => setForm({ ...form, maximum_prefix: e.target.value })} />
          </FormField>
          <FormField label="Limiar (%)">
            <input type="number" value={form.maximum_prefix_threshold} onChange={(e) => setForm({ ...form, maximum_prefix_threshold: e.target.value })} />
          </FormField>
          <FormField label="Local-preference">
            <input type="number" value={form.local_preference} onChange={(e) => setForm({ ...form, local_preference: e.target.value })} />
          </FormField>
          <FormField label="MED">
            <input type="number" value={form.med} onChange={(e) => setForm({ ...form, med: e.target.value })} />
          </FormField>
          <FormField label="Prepend">
            <input type="number" value={form.prepend} onChange={(e) => setForm({ ...form, prepend: e.target.value })} />
          </FormField>
          <FormField label="Keepalive">
            <input type="number" value={form.keepalive} onChange={(e) => setForm({ ...form, keepalive: e.target.value })} />
          </FormField>
          <FormField label="Holdtime">
            <input type="number" value={form.holdtime} onChange={(e) => setForm({ ...form, holdtime: e.target.value })} />
          </FormField>
          <FormField label="BFD">
            <input type="checkbox" checked={form.bfd_enabled} onChange={(e) => setForm({ ...form, bfd_enabled: e.target.checked })} />
          </FormField>
          <FormField label="Graceful restart">
            <input type="checkbox" checked={form.graceful_restart} onChange={(e) => setForm({ ...form, graceful_restart: e.target.checked })} />
          </FormField>
          <FormField label="Shutdown">
            <input type="checkbox" checked={form.shutdown} onChange={(e) => setForm({ ...form, shutdown: e.target.checked })} />
          </FormField>
          <FormField label="Default route">
            <input type="checkbox" checked={form.allow_default_route} onChange={(e) => setForm({ ...form, allow_default_route: e.target.checked })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<BgpSessionOut>
        colunas={[
          { key: "circuit", title: "Circuito", render: (s) => circuits?.find((c) => c.id === s.circuit_id)?.code ?? "—" },
          { key: "device", title: "Equipamento", render: (s) => devices?.find((d) => d.id === s.device_id)?.name ?? "—" },
          { key: "afi", title: "Família", render: (s) => <StatusBadge estado={s.afi} /> },
          { key: "addresses", title: "Endereços", render: (s) => `${s.local_address} ↔ ${s.remote_address}` },
          { key: "asns", title: "ASNs", render: (s) => `${s.asn_local ?? "—"} ↔ ${s.asn_remote ?? "—"}` },
          { key: "shutdown", title: "Situação", render: (s) => <StatusBadge estado={s.shutdown ? "inativo" : "ativo"} /> },
          { key: "cadastro", title: "Cadastro", render: (s) => <StatusBadge estado={s.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(s) => (
          <>
            <Link to={`/bgp-sessions/${s.id}`}>Detalhe</Link>{" "}
            {podeEscrever && s.admin_status && (
              <button type="button" onClick={() => setDesativando(s)}>
                Desativar
              </button>
            )}
            {podeEscrever && !s.admin_status && (
              <button type="button" onClick={() => setReativando(s)}>
                Reativar
              </button>
            )}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar sessão ${desativando?.id ?? ""}?`}
        mensagem="A sessão fica indisponível para novas configurações; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar a sessão."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar sessão ${reativando?.id ?? ""}?`}
        mensagem="A sessão volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar a sessão."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
