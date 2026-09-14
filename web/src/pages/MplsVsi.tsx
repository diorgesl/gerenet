import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useDevices, useMplsDomains, useVsi, useVsiCriar } from "@/api/hooks";
import type { VsiEndpointIn, VsiOut } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { Modal } from "@/components/Modal";
import { help } from "@/help";

interface PeForm {
  device_id: string;
  vid: string;
  mtu: string;
}

const PE_VAZIO: PeForm = { device_id: "", vid: "", mtu: "" };

function formVazio() {
  return {
    domain_id: "",
    name: "",
    vsi_id: "",
    mtu: "1500",
    description: "",
    flow_label: false,
    pes: [{ ...PE_VAZIO }],
  };
}

function numOrNull(v: string): number | null {
  return v === "" ? null : Number(v);
}

function endpoint(p: PeForm): VsiEndpointIn {
  return { device_id: Number(p.device_id), vid: numOrNull(p.vid), mtu: numOrNull(p.mtu) };
}

export default function MplsVsi() {
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useVsi();
  const { data: domains } = useMplsDomains();
  const { data: devices } = useDevices();
  const criar = useVsiCriar();
  const [criando, setCriando] = useState(false);
  const [form, setForm] = useState(formVazio);
  const [erro, setErro] = useState<string | null>(null);

  const setPe = (idx: number, campo: keyof PeForm, valor: string) =>
    setForm({ ...form, pes: form.pes.map((p, i) => (i === idx ? { ...p, [campo]: valor } : p)) });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        domain_id: Number(form.domain_id),
        name: form.name,
        vsi_id: numOrNull(form.vsi_id),
        mtu: numOrNull(form.mtu) ?? 1500,
        description: form.description === "" ? null : form.description,
        flow_label: form.flow_label,
        endpoints: form.pes.map(endpoint),
      });
      setForm(formVazio());
      setCriando(false);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar o VSI.");
    }
  }

  return (
    <main>
      <PageHeader titulo="VSIs" sub="Serviços multiponto (VPLS) no domínio MPLS — um AC por PE, provisionados pelo fluxo de change request." />
      {podeEscrever && (
        <button
          className="primary"
          type="button"
          onClick={() => {
            setForm(formVazio());
            setCriando(true);
          }}
        >
          Novo VSI
        </button>
      )}
      <DataTable<VsiOut>
        colunas={[
          { key: "id", title: "ID", render: (v) => <Link to={`/mpls/vsi/${v.id}`}>#{v.id}</Link> },
          { key: "name", title: "Nome", render: (v) => <Link to={`/mpls/vsi/${v.id}`}>{v.name}</Link> },
          { key: "vrp_name", title: "Nome VRP", render: (v) => v.vrp_name },
          { key: "vsi_id", title: "VSI-ID" },
          { key: "domains", title: "Domínio", render: (v) => v.domain_name ?? `#${v.domain_id}` },
          { key: "endpoints", title: "PEs", render: (v) => v.endpoints.length },
          { key: "admin_status", title: "Situação", render: (v) => <StatusBadge estado={v.admin_status ? "ativo" : "inativo"} /> },
          { key: "operational_status", title: "Estado operacional", render: (v) => <StatusBadge estado={v.operational_status} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os VSIs." : undefined}
      />
      {criando && (
        <Modal aberto titulo="Novo VSI" onFechar={() => setCriando(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <FormField label="Domínio *" help={help("vsi.domain")}>
              <select
                value={form.domain_id}
                onChange={(e) => setForm({ ...form, domain_id: e.target.value })}
                required
              >
                <option value="">—</option>
                {(domains ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Nome *" help={help("vsi.name")}>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </FormField>
            <FormField label="VSI-ID" help={help("vsi.vsi_id")}>
              <input
                type="number"
                value={form.vsi_id}
                onChange={(e) => setForm({ ...form, vsi_id: e.target.value })}
                placeholder="vazio = próximo VSI-ID do domínio"
              />
            </FormField>
            <FormField label="MTU do serviço" help={help("vsi.mtu")}>
              <input
                type="number"
                value={form.mtu}
                onChange={(e) => setForm({ ...form, mtu: e.target.value })}
              />
            </FormField>
            <FormField label="Descrição" help={help("vsi.description")}>
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                maxLength={255}
              />
            </FormField>
            <FormField label="Flow-label" help={help("vsi.flow_label")}>
              <input
                type="checkbox"
                checked={form.flow_label}
                onChange={(e) => setForm({ ...form, flow_label: e.target.checked })}
              />
            </FormField>
            {form.pes.map((pe, idx) => (
              <fieldset key={idx}>
                <legend>PE {idx + 1}</legend>
                <FormField label="Equipamento *" help={help("vsi.endpoint.device")}>
                  <select
                    value={pe.device_id}
                    onChange={(e) => setPe(idx, "device_id", e.target.value)}
                    required
                  >
                    <option value="">—</option>
                    {(devices ?? []).map((d) => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </FormField>
                <FormField label="VID" help={help("vsi.endpoint.vid")}>
                  <input
                    type="number"
                    value={pe.vid}
                    onChange={(e) => setPe(idx, "vid", e.target.value)}
                    placeholder="vazio = assume o VSI-ID"
                  />
                </FormField>
                <FormField label="MTU" help={help("vsi.endpoint.mtu")}>
                  <input
                    type="number"
                    value={pe.mtu}
                    onChange={(e) => setPe(idx, "mtu", e.target.value)}
                    placeholder="vazio = herda do serviço"
                  />
                </FormField>
                <button
                  type="button"
                  disabled={form.pes.length === 1}
                  onClick={() => setForm({ ...form, pes: form.pes.filter((_, i) => i !== idx) })}
                >
                  Remover PE
                </button>
              </fieldset>
            ))}
            <p className="aviso">
              O cadastro aceita um PE; o provisionamento exige dois ou mais.
            </p>
            <button
              type="button"
              onClick={() => setForm({ ...form, pes: [...form.pes, { ...PE_VAZIO }] })}
            >
              Adicionar PE
            </button>
            <div className="dialog-actions">
              <button type="button" onClick={() => setCriando(false)} disabled={criar.isPending}>
                Cancelar
              </button>
              <button className="primary" type="submit" disabled={criar.isPending}>
                {criar.isPending ? "Criando…" : "Criar"}
              </button>
            </div>
          </form>
          {erro && <p role="alert">{erro}</p>}
        </Modal>
      )}
    </main>
  );
}
