import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useCircuitAtualizar, useCircuitCriar, useCircuits, useDevices, useOrganizations, useSites } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { CircuitOut } from "@/api/types";

const FORM_VAZIO = {
  code: "",
  organization_id: "",
  site_id: "",
  access_device_id: "",
  access_port: "",
  edge_device_id: "",
  backup_edge_device_id: "",
  stack: "dual" as "ipv4" | "ipv6" | "dual",
  vlan_mode: "unica" as "unica" | "separada",
  qinq: false,
  vrf: "",
  mtu: "",
  bandwidth: "",
  bfd: false,
  p2p_v4_len: "31" as "30" | "31",
  description: "",
  notes: "",
  edge_trunk: "",
};

export default function Circuits() {
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useCircuits();
  const { data: organizations } = useOrganizations();
  const { data: sites } = useSites();
  const { data: devices } = useDevices();
  const criar = useCircuitCriar();
  const atualizar = useCircuitAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<CircuitOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const num = (v: string) => (v === "" ? null : Number(v));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        code: form.code,
        organization_id: Number(form.organization_id),
        site_id: Number(form.site_id),
        access_device_id: Number(form.access_device_id),
        access_port: form.access_port,
        edge_device_id: Number(form.edge_device_id),
        backup_edge_device_id: form.backup_edge_device_id === "" ? null : Number(form.backup_edge_device_id),
        stack: form.stack,
        vlan_mode: form.vlan_mode,
        qinq: form.qinq,
        vrf: form.vrf || null,
        mtu: num(form.mtu),
        bandwidth: form.bandwidth || null,
        bfd: form.bfd,
        p2p_v4_len: Number(form.p2p_v4_len) as 30 | 31,
        description: form.description || null,
        notes: form.notes || null,
        edge_trunk: form.edge_trunk || null,
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar circuito.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Circuitos" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Código *">
            <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </FormField>
          <FormField label="Organização *">
            <select value={form.organization_id} onChange={(e) => setForm({ ...form, organization_id: e.target.value })} required>
              <option value="">—</option>
              {(organizations ?? []).map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Site *">
            <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })} required>
              <option value="">—</option>
              {(sites ?? []).map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Equipamento de acesso *">
            <select value={form.access_device_id} onChange={(e) => setForm({ ...form, access_device_id: e.target.value })} required>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Porta de acesso *">
            <input value={form.access_port} onChange={(e) => setForm({ ...form, access_port: e.target.value })} required />
          </FormField>
          <FormField label="Edge *">
            <select value={form.edge_device_id} onChange={(e) => setForm({ ...form, edge_device_id: e.target.value })} required>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Edge de contingência">
            <select value={form.backup_edge_device_id} onChange={(e) => setForm({ ...form, backup_edge_device_id: e.target.value })}>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Stack">
            <select value={form.stack} onChange={(e) => setForm({ ...form, stack: e.target.value as "ipv4" | "ipv6" | "dual" })}>
              <option value="ipv4">ipv4</option>
              <option value="ipv6">ipv6</option>
              <option value="dual">dual</option>
            </select>
          </FormField>
          <FormField label="VLAN">
            <select value={form.vlan_mode} onChange={(e) => setForm({ ...form, vlan_mode: e.target.value as "unica" | "separada" })}>
              <option value="unica">única</option>
              <option value="separada">separada</option>
            </select>
          </FormField>
          <FormField label="QinQ">
            <input type="checkbox" checked={form.qinq} onChange={(e) => setForm({ ...form, qinq: e.target.checked })} />
          </FormField>
          <FormField label="VRF">
            <input value={form.vrf} onChange={(e) => setForm({ ...form, vrf: e.target.value })} />
          </FormField>
          <FormField label="MTU">
            <input type="number" value={form.mtu} onChange={(e) => setForm({ ...form, mtu: e.target.value })} />
          </FormField>
          <FormField label="Banda">
            <input value={form.bandwidth} onChange={(e) => setForm({ ...form, bandwidth: e.target.value })} />
          </FormField>
          <FormField label="BFD">
            <input type="checkbox" checked={form.bfd} onChange={(e) => setForm({ ...form, bfd: e.target.checked })} />
          </FormField>
          <FormField label="Len /30 ou /31">
            <select value={form.p2p_v4_len} onChange={(e) => setForm({ ...form, p2p_v4_len: e.target.value as "30" | "31" })}>
              <option value="31">/31</option>
              <option value="30">/30</option>
            </select>
          </FormField>
          <FormField label="Descrição">
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </FormField>
          <FormField label="Observações">
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </FormField>
          <FormField label="Eth-Trunk do edge">
            <input value={form.edge_trunk} onChange={(e) => setForm({ ...form, edge_trunk: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<CircuitOut>
        colunas={[
          { key: "code", title: "Código", render: (c) => <Link to={`/circuits/${c.id}`}>{c.code}</Link> },
          { key: "organization", title: "Organização", render: (c) => organizations?.find((o) => o.id === c.organization_id)?.name ?? "—" },
          { key: "site", title: "Site", render: (c) => sites?.find((s) => s.id === c.site_id)?.name ?? "—" },
          {
            key: "devices",
            title: "Access → Edge",
            render: (c) => `${devices?.find((d) => d.id === c.access_device_id)?.name ?? "—"} → ${devices?.find((d) => d.id === c.edge_device_id)?.name ?? "—"}`,
          },
          { key: "stack", title: "Stack", render: (c) => <StatusBadge estado={c.stack} /> },
          { key: "bfd", title: "BFD", render: (c) => (c.bfd ? "Sim" : "—") },
          { key: "admin_status", title: "Situação", render: (c) => <StatusBadge estado={c.admin_status ? "ativo" : "inativo"} /> },
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
        titulo={`Desativar ${desativando?.code ?? ""}?`}
        mensagem="O circuito não recebe novas sessões; o registro permanece."
        onConfirmar={() => {
          if (desativando) void atualizar.mutateAsync({ id: desativando.id, admin_status: false }).then(() => setDesativando(null));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
