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
import { Modal } from "@/components/Modal";
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

const FORM_EDIT_VAZIO = {
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
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useCircuits({ includeDisabled: incluirInativos });
  const { data: organizations } = useOrganizations();
  const { data: sites } = useSites();
  const { data: devices } = useDevices();
  const criar = useCircuitCriar();
  const atualizar = useCircuitAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<CircuitOut | null>(null);
  const [reativando, setReativando] = useState<CircuitOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<CircuitOut | null>(null);
  const [formEdit, setFormEdit] = useState(FORM_EDIT_VAZIO);
  const [erroEdit, setErroEdit] = useState<string | null>(null);

  const num = (v: string) => (v === "" ? null : Number(v));

  function abrirEdicao(c: CircuitOut) {
    setFormEdit({
      organization_id: String(c.organization_id),
      site_id: String(c.site_id),
      access_device_id: String(c.access_device_id),
      access_port: c.access_port,
      edge_device_id: String(c.edge_device_id),
      backup_edge_device_id: c.backup_edge_device_id === null ? "" : String(c.backup_edge_device_id),
      stack: c.stack as "ipv4" | "ipv6" | "dual",
      vlan_mode: c.vlan_mode as "unica" | "separada",
      qinq: c.qinq,
      vrf: c.vrf ?? "",
      mtu: c.mtu === null ? "" : String(c.mtu),
      bandwidth: c.bandwidth ?? "",
      bfd: c.bfd,
      p2p_v4_len: String(c.p2p_v4_len) as "30" | "31",
      description: c.description ?? "",
      notes: c.notes ?? "",
      edge_trunk: c.edge_trunk ?? "",
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
        organization_id: Number(formEdit.organization_id),
        site_id: Number(formEdit.site_id),
        access_device_id: Number(formEdit.access_device_id),
        access_port: formEdit.access_port,
        edge_device_id: Number(formEdit.edge_device_id),
        backup_edge_device_id: formEdit.backup_edge_device_id === "" ? null : Number(formEdit.backup_edge_device_id),
        stack: formEdit.stack,
        vlan_mode: formEdit.vlan_mode,
        qinq: formEdit.qinq,
        vrf: formEdit.vrf || null,
        mtu: num(formEdit.mtu),
        bandwidth: formEdit.bandwidth || null,
        bfd: formEdit.bfd,
        p2p_v4_len: Number(formEdit.p2p_v4_len) as 30 | 31,
        description: formEdit.description || null,
        notes: formEdit.notes || null,
        edge_trunk: formEdit.edge_trunk || null,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar o circuito.");
    }
  }

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
        acoes={(c) => (
          <>
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(c)}>
                Editar
              </button>
            )}
            {podeEscrever && c.admin_status ? (
              <button type="button" onClick={() => setDesativando(c)}>
                Desativar
              </button>
            ) : podeEscrever ? (
              <button type="button" onClick={() => setReativando(c)}>
                Reativar
              </button>
            ) : null}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.code ?? ""}?`}
        mensagem="O circuito não recebe novas sessões; o registro permanece."
        onConfirmar={() => {
          if (desativando)
            void atualizar
              .mutateAsync({ id: desativando.id, admin_status: false })
              .then(() => setDesativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar o circuito."));
        }}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.code ?? ""}?`}
        mensagem="O circuito volta ao catálogo ativo."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar o circuito."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
      {editando && (
        <Modal aberto titulo={`Editar ${editando.code}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Organização *">
              <select value={formEdit.organization_id} onChange={(e) => setFormEdit({ ...formEdit, organization_id: e.target.value })} required>
                <option value="">—</option>
                {(organizations ?? []).map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Site *">
              <select value={formEdit.site_id} onChange={(e) => setFormEdit({ ...formEdit, site_id: e.target.value })} required>
                <option value="">—</option>
                {(sites ?? []).map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Equipamento de acesso *">
              <select value={formEdit.access_device_id} onChange={(e) => setFormEdit({ ...formEdit, access_device_id: e.target.value })} required>
                <option value="">—</option>
                {(devices ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Porta de acesso *">
              <input value={formEdit.access_port} onChange={(e) => setFormEdit({ ...formEdit, access_port: e.target.value })} required />
            </FormField>
            <FormField label="Edge *">
              <select value={formEdit.edge_device_id} onChange={(e) => setFormEdit({ ...formEdit, edge_device_id: e.target.value })} required>
                <option value="">—</option>
                {(devices ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Edge de contingência">
              <select value={formEdit.backup_edge_device_id} onChange={(e) => setFormEdit({ ...formEdit, backup_edge_device_id: e.target.value })}>
                <option value="">—</option>
                {(devices ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Stack">
              <select value={formEdit.stack} onChange={(e) => setFormEdit({ ...formEdit, stack: e.target.value as "ipv4" | "ipv6" | "dual" })}>
                <option value="ipv4">ipv4</option>
                <option value="ipv6">ipv6</option>
                <option value="dual">dual</option>
              </select>
            </FormField>
            <FormField label="VLAN">
              <select value={formEdit.vlan_mode} onChange={(e) => setFormEdit({ ...formEdit, vlan_mode: e.target.value as "unica" | "separada" })}>
                <option value="unica">única</option>
                <option value="separada">separada</option>
              </select>
            </FormField>
            <FormField label="QinQ">
              <input type="checkbox" checked={formEdit.qinq} onChange={(e) => setFormEdit({ ...formEdit, qinq: e.target.checked })} />
            </FormField>
            <FormField label="VRF">
              <input value={formEdit.vrf} onChange={(e) => setFormEdit({ ...formEdit, vrf: e.target.value })} />
            </FormField>
            <FormField label="MTU">
              <input type="number" value={formEdit.mtu} onChange={(e) => setFormEdit({ ...formEdit, mtu: e.target.value })} />
            </FormField>
            <FormField label="Banda">
              <input value={formEdit.bandwidth} onChange={(e) => setFormEdit({ ...formEdit, bandwidth: e.target.value })} />
            </FormField>
            <FormField label="BFD">
              <input type="checkbox" checked={formEdit.bfd} onChange={(e) => setFormEdit({ ...formEdit, bfd: e.target.checked })} />
            </FormField>
            <FormField label="Len /30 ou /31">
              <select value={formEdit.p2p_v4_len} onChange={(e) => setFormEdit({ ...formEdit, p2p_v4_len: e.target.value as "30" | "31" })}>
                <option value="31">/31</option>
                <option value="30">/30</option>
              </select>
            </FormField>
            <FormField label="Descrição">
              <input value={formEdit.description} onChange={(e) => setFormEdit({ ...formEdit, description: e.target.value })} />
            </FormField>
            <FormField label="Observações">
              <input value={formEdit.notes} onChange={(e) => setFormEdit({ ...formEdit, notes: e.target.value })} />
            </FormField>
            <FormField label="Eth-Trunk do edge">
              <input value={formEdit.edge_trunk} onChange={(e) => setFormEdit({ ...formEdit, edge_trunk: e.target.value })} />
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
