import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useCredentialGroups,
  useDeviceAtualizar,
  useDeviceColetar,
  useDeviceCriar,
  useDevices,
  useSites,
} from "@/api/hooks";
import { help } from "@/help";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
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
  credential_group_id: "",
};

const FORM_EDIT_VAZIO = { ssh_port: "", model: "", family: "", role: "", site_id: "", asn: "", tags: "", credential_group_id: "" };

export default function Devices() {
  const { podeEscrever } = useAuth();
  const navigate = useNavigate();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useDevices({ includeDisabled: incluirInativos });
  const { data: sites } = useSites();
  const { data: grupos } = useCredentialGroups();
  const criar = useDeviceCriar();
  const atualizar = useDeviceAtualizar();
  const coletar = useDeviceColetar();

  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<DeviceOut | null>(null);
  const [reativando, setReativando] = useState<DeviceOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<DeviceOut | null>(null);
  const [formEdit, setFormEdit] = useState(FORM_EDIT_VAZIO);
  const [erroEdit, setErroEdit] = useState<string | null>(null);

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
        credential_group_id: form.credential_group_id === "" ? null : Number(form.credential_group_id),
      });
      setForm(FORM_VAZIO);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao cadastrar equipamento.");
    }
  }

  function abrirEdicao(d: DeviceOut) {
    setFormEdit({
      ssh_port: d.ssh_port === null ? "" : String(d.ssh_port),
      model: d.model ?? "",
      family: d.family ?? "",
      role: d.role ?? "",
      site_id: d.site_id === null ? "" : String(d.site_id),
      asn: d.asn === null ? "" : String(d.asn),
      tags: d.tags.join(", "),
      credential_group_id: d.credential_group_id === null ? "" : String(d.credential_group_id),
    });
    setErroEdit(null);
    setEditando(d);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        ssh_port: formEdit.ssh_port === "" ? null : Number(formEdit.ssh_port),
        model: formEdit.model || null,
        family: formEdit.family || null,
        role: formEdit.role || null,
        site_id: formEdit.site_id === "" ? null : Number(formEdit.site_id),
        asn: formEdit.asn === "" ? null : Number(formEdit.asn),
        tags: formEdit.tags.split(",").map((t) => t.trim()).filter(Boolean),
        credential_group_id: formEdit.credential_group_id === "" ? null : Number(formEdit.credential_group_id),
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar o equipamento.");
    }
  }

  function desativar() {
    if (!desativando) return;
    void atualizar
      .mutateAsync({ id: desativando.id, admin_status: false })
      .then(() => setDesativando(null))
      .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao desativar o equipamento."));
  }

  return (
    <main>
      <PageHeader titulo="Equipamentos" />
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
          <FormField label="Nome *" help={help("device.name")}>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </FormField>
          <FormField label="IP de gestão *" help={help("device.management_address")}>
            <input value={form.management_address} onChange={(e) => setForm({ ...form, management_address: e.target.value })} required />
          </FormField>
          <FormField label="Porta SSH" help={help("device.ssh_port")}>
            <input type="number" value={form.ssh_port} onChange={(e) => setForm({ ...form, ssh_port: e.target.value })} />
          </FormField>
          <FormField label="Modelo" help={help("device.model")}>
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </FormField>
          <FormField label="Família" help={help("device.family")}>
            <input value={form.family} onChange={(e) => setForm({ ...form, family: e.target.value })} />
          </FormField>
          <FormField label="Função" help={help("device.role")}>
            <input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
          </FormField>
          <FormField label="ASN" help={help("device.asn")}>
            <input type="number" value={form.asn} onChange={(e) => setForm({ ...form, asn: e.target.value })} />
          </FormField>
          <FormField label="Site" help={help("device.site")}>
            <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
              <option value="">—</option>
              {(sites ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Grupo de credencial" help={help("device.credential_group")}>
            <select value={form.credential_group_id} onChange={(e) => setForm({ ...form, credential_group_id: e.target.value })}>
              <option value="">—</option>
              {(grupos ?? []).map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Tags (separadas por vírgula)" help={help("device.tags")}>
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
          {
            key: "credential",
            title: "Credencial",
            render: (d) => grupos?.find((g) => g.id === d.credential_group_id)?.name ?? "—",
          },
          { key: "role", title: "Função", render: (d) => d.role ?? "—" },
          { key: "comm_status", title: "Comunicação", render: (d) => <StatusBadge estado={d.comm_status} /> },
          { key: "last_collected_at", title: "Última coleta", render: (d) => <TimeAgo iso={d.last_collected_at} /> },
          { key: "admin_status", title: "Situação", render: (d) => <StatusBadge estado={d.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os registros." : undefined}
        acoes={(d) => (
          <>
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(d)}>
                Editar
              </button>
            )}
            {podeEscrever && (
              <button
                type="button"
                onClick={() =>
                  void coletar
                    .mutateAsync(d.id)
                    .then(() => navigate(`/jobs?device_id=${d.id}`))
                    .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao coletar."))
                }
              >
                Coletar agora
              </button>
            )}
            {podeEscrever && d.admin_status && (
              <button type="button" onClick={() => setDesativando(d)}>
                Desativar
              </button>
            )}
            {podeEscrever && !d.admin_status && (
              <button type="button" onClick={() => setReativando(d)}>
                Reativar
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
      <ConfirmDialog
        aberto={reativando !== null}
        titulo={`Reativar ${reativando?.name ?? ""}?`}
        mensagem="Volta a ser gerenciado; a coleta será retomada."
        onConfirmar={() => {
          if (reativando)
            void atualizar
              .mutateAsync({ id: reativando.id, admin_status: true })
              .then(() => setReativando(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao reativar o equipamento."));
        }}
        onCancelar={() => setReativando(null)}
        confirmando={atualizar.isPending}
      />
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Porta SSH" help={help("device.ssh_port")}>
              <input type="number" value={formEdit.ssh_port} onChange={(e) => setFormEdit({ ...formEdit, ssh_port: e.target.value })} />
            </FormField>
            <FormField label="Modelo" help={help("device.model")}>
              <input value={formEdit.model} onChange={(e) => setFormEdit({ ...formEdit, model: e.target.value })} />
            </FormField>
            <FormField label="Família" help={help("device.family")}>
              <input value={formEdit.family} onChange={(e) => setFormEdit({ ...formEdit, family: e.target.value })} />
            </FormField>
            <FormField label="Função" help={help("device.role")}>
              <input value={formEdit.role} onChange={(e) => setFormEdit({ ...formEdit, role: e.target.value })} />
            </FormField>
            <FormField label="Site" help={help("device.site")}>
              <select value={formEdit.site_id} onChange={(e) => setFormEdit({ ...formEdit, site_id: e.target.value })}>
                <option value="">—</option>
                {(sites ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField label="Grupo de credencial" help={help("device.credential_group")}>
              <select value={formEdit.credential_group_id} onChange={(e) => setFormEdit({ ...formEdit, credential_group_id: e.target.value })}>
                <option value="">—</option>
                {(grupos ?? []).map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
                {formEdit.credential_group_id !== "" &&
                  !(grupos ?? []).some((g) => g.id === Number(formEdit.credential_group_id)) && (
                    <option value={formEdit.credential_group_id}>
                      {`(desativado) #${formEdit.credential_group_id}`}
                    </option>
                  )}
              </select>
            </FormField>
            <FormField label="ASN" help={help("device.asn")}>
              <input type="number" value={formEdit.asn} onChange={(e) => setFormEdit({ ...formEdit, asn: e.target.value })} />
            </FormField>
            <FormField label="Tags (separadas por vírgula)" help={help("device.tags")}>
              <input value={formEdit.tags} onChange={(e) => setFormEdit({ ...formEdit, tags: e.target.value })} />
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
