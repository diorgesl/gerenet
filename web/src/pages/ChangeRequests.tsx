import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useChangeRequestCriar, useChangeRequests, useCircuits } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { Modal } from "@/components/Modal";
import type { ChangeRequestOut } from "@/api/types";

const STATUS_OPCOES = [
  { valor: "", rotulo: "Todos" },
  { valor: "rascunho", rotulo: "Rascunho" },
  { valor: "aguardando_aprovacao", rotulo: "Aguardando aprovação" },
  { valor: "aprovado", rotulo: "Aprovado" },
  { valor: "executando", rotulo: "Executando" },
  { valor: "aplicado", rotulo: "Aplicado" },
  { valor: "com_divergencia", rotulo: "Com divergência" },
  { valor: "parcial", rotulo: "Parcial" },
  { valor: "erro", rotulo: "Erro" },
  { valor: "rejeitado", rotulo: "Rejeitado" },
  { valor: "cancelado", rotulo: "Cancelado" },
];

const FORM_VAZIO = {
  circuit_id: "",
  acao: "provision" as "provision" | "remove",
  criticidade: "media" as "baixa" | "media" | "alta",
  motivo: "",
  ticket: "",
};

const ACAO_LABELS: Record<ChangeRequestOut["acao"], string> = {
  provision: "Aplicar configuração",
  remove: "Remover configuração",
};

// Rótulo do objeto da CR quando o catálogo não tem o id: circuitos usam #N;
// CRs de escopo l2vc não têm circuito e exibem o nome do serviço (ou "—").
function rotuloObjeto(cr: ChangeRequestOut): string {
  return cr.circuit_id !== null ? `#${cr.circuit_id}` : (cr.l2vc_name ?? "—");
}

export default function ChangeRequests() {
  const { podeEscrever } = useAuth();
  const [status, setStatus] = useState("");
  const { data, isLoading, error } = useChangeRequests({ status: status || undefined });
  const { data: circuits } = useCircuits();
  const criar = useChangeRequestCriar();
  const [criando, setCriando] = useState(false);
  const [form, setForm] = useState(FORM_VAZIO);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({
        circuit_id: Number(form.circuit_id),
        acao: form.acao,
        criticidade: form.criticidade,
        motivo: form.motivo,
        ticket: form.ticket || null,
      });
      setForm(FORM_VAZIO);
      setCriando(false);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar a change request.");
    }
  }

  return (
    <main>
      <PageHeader titulo="Change requests" />
      <form className="form-inline">
        <label className="field">
          <span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPCOES.map((o) => (
              <option key={o.valor} value={o.valor}>{o.rotulo}</option>
            ))}
          </select>
        </label>
      </form>
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
          Solicitar mudança
        </button>
      )}
      <DataTable<ChangeRequestOut>
        colunas={[
          { key: "id", title: "ID", render: (cr) => <Link to={`/change-requests/${cr.id}`}>#{cr.id}</Link> },
          { key: "circuit", title: "Circuito", render: (cr) => circuits?.find((c) => c.id === cr.circuit_id)?.code ?? rotuloObjeto(cr) },
          { key: "acao", title: "Ação", render: (cr) => ACAO_LABELS[cr.acao] },
          { key: "criticidade", title: "Criticidade", render: (cr) => cr.criticidade },
          { key: "status", title: "Status", render: (cr) => <StatusBadge estado={cr.status} /> },
          { key: "motivo", title: "Motivo", render: (cr) => cr.motivo },
          { key: "created_at", title: "Criada em", render: (cr) => new Date(cr.created_at).toLocaleString("pt-BR") },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar as change requests." : undefined}
      />
      {criando && (
        <Modal aberto titulo="Solicitar mudança" onFechar={() => setCriando(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <FormField label="Circuito *">
              <select value={form.circuit_id} onChange={(e) => setForm({ ...form, circuit_id: e.target.value })} required>
                <option value="">—</option>
                {(circuits ?? []).map((c) => (
                  <option key={c.id} value={c.id}>{c.code}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Ação *">
              <select value={form.acao} onChange={(e) => setForm({ ...form, acao: e.target.value as "provision" | "remove" })}>
                <option value="provision">Aplicar configuração</option>
                <option value="remove">Remover configuração</option>
              </select>
            </FormField>
            <FormField label="Criticidade *">
              <select value={form.criticidade} onChange={(e) => setForm({ ...form, criticidade: e.target.value as "baixa" | "media" | "alta" })}>
                <option value="baixa">baixa</option>
                <option value="media">média</option>
                <option value="alta">alta</option>
              </select>
            </FormField>
            <FormField label="Motivo *">
              <textarea value={form.motivo} onChange={(e) => setForm({ ...form, motivo: e.target.value })} required rows={3} />
            </FormField>
            <FormField label="Ticket">
              <input value={form.ticket} onChange={(e) => setForm({ ...form, ticket: e.target.value })} />
            </FormField>
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
