import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useDevices, useL2vc, useL2vcCriar, useMplsDomains } from "@/api/hooks";
import type { L2vcEndpointIn, L2vcOut } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { Modal } from "@/components/Modal";

interface PontaForm {
  device_id: string;
  interface: string;
  encapsulation: "dot1q" | "qinq";
  vid: string;
  inner_vlan: string;
  mtu: string;
}

const PONTA_VAZIA: PontaForm = {
  device_id: "",
  interface: "",
  encapsulation: "dot1q",
  vid: "",
  inner_vlan: "",
  mtu: "",
};
const FORM_VAZIO = { domain_id: "", name: "", vc_id: "", pontaA: { ...PONTA_VAZIA }, pontaB: { ...PONTA_VAZIA } };

function numOrNull(v: string): number | null {
  return v === "" ? null : Number(v);
}

function endpoint(p: PontaForm): L2vcEndpointIn {
  return {
    device_id: Number(p.device_id),
    interface: p.interface,
    encapsulation: p.encapsulation,
    vid: numOrNull(p.vid),
    inner_vlan: p.encapsulation === "qinq" ? numOrNull(p.inner_vlan) : null,
    mtu: numOrNull(p.mtu),
  };
}

export default function MplsL2vc() {
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useL2vc();
  const { data: domains } = useMplsDomains();
  const { data: devices } = useDevices();
  const criar = useL2vcCriar();
  const [criando, setCriando] = useState(false);
  const [form, setForm] = useState(FORM_VAZIO);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        domain_id: Number(form.domain_id),
        name: form.name,
        vc_id: numOrNull(form.vc_id),
        endpoints: [endpoint(form.pontaA), endpoint(form.pontaB)],
      });
      setForm(FORM_VAZIO);
      setCriando(false);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar o serviço L2VC.");
    }
  }

  const setPonta = (ponta: "pontaA" | "pontaB", campo: keyof PontaForm, valor: string) =>
    setForm({ ...form, [ponta]: { ...form[ponta], [campo]: valor } });

  return (
    <main>
      <PageHeader titulo="Serviços L2VC" sub="Pseudowires ponto a ponto entre PEs do domínio MPLS." />
      {podeEscrever && (
        <button
          className="primary"
          type="button"
          onClick={() => {
            setForm(FORM_VAZIO);
            setErro(null);
            setCriando(true);
          }}
        >
          Novo L2VC
        </button>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<L2vcOut>
        colunas={[
          { key: "id", title: "ID", render: (l) => <Link to={`/mpls/l2vc/${l.id}`}>#{l.id}</Link> },
          { key: "name", title: "Nome", render: (l) => <Link to={`/mpls/l2vc/${l.id}`}>{l.name}</Link> },
          { key: "vc_id", title: "VC-ID" },
          { key: "domains", title: "Domínio", render: (l) => l.domain_name ?? domains?.find((d) => d.id === l.domain_id)?.name ?? "—" },
          { key: "admin_status", title: "Situação", render: (l) => <StatusBadge estado={l.admin_status ? "ativo" : "inativo"} /> },
          { key: "operational_status", title: "Estado operacional", render: (l) => <StatusBadge estado={l.operational_status} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os serviços L2VC." : undefined}
      />
      {criando && (
        <Modal aberto titulo="Novo L2VC" onFechar={() => setCriando(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <FormField label="Domínio *">
              <select value={form.domain_id} onChange={(e) => setForm({ ...form, domain_id: e.target.value })} required>
                <option value="">—</option>
                {(domains ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Nome *">
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </FormField>
            <FormField label="VC-ID">
              <input
                type="number"
                value={form.vc_id}
                onChange={(e) => setForm({ ...form, vc_id: e.target.value })}
                placeholder="vazio = próximo VC-ID"
              />
            </FormField>
            {(["pontaA", "pontaB"] as const).map((ponta, idx) => (
              <fieldset key={ponta}>
                <legend>Ponta {idx === 0 ? "A" : "B"}</legend>
                <FormField label="Equipamento *">
                  <select
                    value={form[ponta].device_id}
                    onChange={(e) => setPonta(ponta, "device_id", e.target.value)}
                    required
                  >
                    <option value="">—</option>
                    {(devices ?? []).map((d) => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </FormField>
                <FormField label="Interface *">
                  <input
                    value={form[ponta].interface}
                    onChange={(e) => setPonta(ponta, "interface", e.target.value)}
                    placeholder="Ex.: 10GE0/0/1"
                    required
                  />
                </FormField>
                <FormField label="Encapsulação">
                  <select
                    value={form[ponta].encapsulation}
                    onChange={(e) => setPonta(ponta, "encapsulation", e.target.value)}
                  >
                    <option value="dot1q">dot1q</option>
                    <option value="qinq">qinq</option>
                  </select>
                </FormField>
                <FormField label="VID">
                  <input
                    type="number"
                    value={form[ponta].vid}
                    onChange={(e) => setPonta(ponta, "vid", e.target.value)}
                    placeholder="vazio = auto-reserva"
                  />
                </FormField>
                {form[ponta].encapsulation === "qinq" && (
                  <FormField label="Inner VLAN">
                    <input
                      type="number"
                      value={form[ponta].inner_vlan}
                      onChange={(e) => setPonta(ponta, "inner_vlan", e.target.value)}
                    />
                  </FormField>
                )}
                <FormField label="MTU">
                  <input
                    type="number"
                    value={form[ponta].mtu}
                    onChange={(e) => setPonta(ponta, "mtu", e.target.value)}
                    placeholder="vazio = herda do serviço"
                  />
                </FormField>
              </fieldset>
            ))}
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
