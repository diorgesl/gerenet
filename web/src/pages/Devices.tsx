import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useDeviceAtualizar,
  useDeviceColetar,
  useDeviceCriar,
  useDevices,
  useSites,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { DeviceOut } from "@/api/types";

const FORM_VAZIO = {
  name: "",
  management_address: "",
  ssh_port: "",
  model: "",
  family: "",
  role: "",
  asn: "",
  tags: "",
  site_id: "",
};

export default function Devices() {
  const { podeEscrever } = useAuth();
  const navigate = useNavigate();
  const { data, isLoading } = useDevices();
  const { data: sites } = useSites();
  const criar = useDeviceCriar();
  const atualizar = useDeviceAtualizar();
  const coletar = useDeviceColetar();

  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<DeviceOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        name: form.name,
        management_address: form.management_address,
        ssh_port: form.ssh_port === "" ? null : Number(form.ssh_port),
        model: form.model || null,
        family: form.family || null,
        role: form.role || null,
        asn: form.asn === "" ? null : Number(form.asn),
        tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
        site_id: form.site_id === "" ? null : Number(form.site_id),
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar equipamento.");
    }
  }

  function desativar() {
    if (!desativando) return;
    void atualizar
      .mutateAsync({ id: desativando.id, admin_status: false })
      .then(() => setDesativando(null));
  }

  return (
    <main>
      <PageHeader titulo="Equipamentos" />
      {podeEscrever && (
        <form onSubmit={onSubmit} className="grid-form">
          <FormField label="Nome *">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="IP de gestão *">
            <input value={form.management_address} onChange={(e) => setForm({ ...form, management_address: e.target.value })} required />
          </FormField>
          <FormField label="Porta SSH">
            <input type="number" value={form.ssh_port} onChange={(e) => setForm({ ...form, ssh_port: e.target.value })} />
          </FormField>
          <FormField label="Modelo">
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </FormField>
          <FormField label="Família">
            <input value={form.family} onChange={(e) => setForm({ ...form, family: e.target.value })} />
          </FormField>
          <FormField label="Função">
            <input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
          </FormField>
          <FormField label="ASN">
            <input type="number" value={form.asn} onChange={(e) => setForm({ ...form, asn: e.target.value })} />
          </FormField>
          <FormField label="Site">
            <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
              <option value="">—</option>
              {(sites ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Tags (separadas por vírgula)">
            <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </FormField>
          <button className="primary" type="submit" disabled={criar.isPending}>
            Cadastrar
          </button>
        </form>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<DeviceOut>
        colunas={[
          { key: "name", title: "Nome", render: (d) => <Link to={`/devices/${d.id}`}>{d.name}</Link> },
          { key: "management_address", title: "IP" },
          { key: "site", title: "Site", render: (d) => sites?.find((s) => s.id === d.site_id)?.name ?? "—" },
          { key: "role", title: "Função", render: (d) => d.role ?? "—" },
          { key: "comm_status", title: "Comunicação", render: (d) => <StatusBadge estado={d.comm_status} /> },
          { key: "last_collected_at", title: "Última coleta", render: (d) => <TimeAgo iso={d.last_collected_at} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(d) => (
          <>
            {podeEscrever && (
              <button
                type="button"
                onClick={() => void coletar.mutateAsync(d.id).then(() => navigate(`/jobs?device_id=${d.id}`))}
              >
                Coletar agora
              </button>
            )}
            {podeEscrever && d.admin_status && (
              <button type="button" onClick={() => setDesativando(d)}>
                Desativar
              </button>
            )}
          </>
        )}
      />
      <ConfirmDialog
        aberto={desativando !== null}
        titulo={`Desativar ${desativando?.name ?? ""}?`}
        mensagem="Não exclui o registro: só desativa a administração."
        onConfirmar={desativar}
        onCancelar={() => setDesativando(null)}
        confirmando={atualizar.isPending}
      />
    </main>
  );
}
