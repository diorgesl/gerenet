import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useChangeRequestCriar } from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";

const FORM_VAZIO = {
  acao: "provision" as "provision" | "remove",
  criticidade: "media" as "baixa" | "media" | "alta",
  motivo: "",
  ticket: "",
};

export default function SolicitarMudanca({
  circuit_id,
  l2vc_id,
  upstream_id,
}: {
  circuit_id?: number;
  l2vc_id?: number;
  upstream_id?: number;
}) {
  const { podeEscrever } = useAuth();
  const navigate = useNavigate();
  const criar = useChangeRequestCriar();
  const [aberto, setAberto] = useState(false);
  const [form, setForm] = useState(FORM_VAZIO);
  const [erro, setErro] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      const cr = await criar.mutateAsync({
        escopo: upstream_id ? "upstream" : l2vc_id ? "l2vc" : "circuito",
        circuit_id: circuit_id ?? null,
        l2vc_id: l2vc_id ?? null,
        upstream_id: upstream_id ?? null,
        acao: form.acao,
        criticidade: form.criticidade,
        motivo: form.motivo,
        ticket: form.ticket || null,
      });
      setForm(FORM_VAZIO);
      setAberto(false);
      navigate(`/change-requests/${cr.id}`);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar a change request.");
    }
  }

  if (!podeEscrever) return null;

  return (
    <>
      <button
        className="primary"
        type="button"
        onClick={() => {
          setForm(FORM_VAZIO);
          setErro(null);
          setAberto(true);
        }}
      >
        {upstream_id ? "Solicitar mudança no upstream" : l2vc_id ? "Solicitar mudança no L2VC" : "Solicitar mudança"}
      </button>
      {aberto && (
        <Modal aberto titulo="Solicitar mudança" onFechar={() => setAberto(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <FormField label="Ação *">
              <select value={form.acao} onChange={(e) => setForm({ ...form, acao: e.target.value as "provision" | "remove" })}>
                <option value="provision">provision — aplicar configuração</option>
                <option value="remove">remove — remover configuração</option>
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
              <button type="button" onClick={() => setAberto(false)} disabled={criar.isPending}>
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
    </>
  );
}
