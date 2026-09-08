import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useOrganizations, useUpstreamAtualizar, useUpstreamCriar, useUpstreams } from "@/api/hooks";
import type { OrganizationOut, UpstreamCreateIn, UpstreamOut, UpstreamTipo } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import { help } from "@/help";

export const TIPO_LABEL: Record<UpstreamTipo, string> = {
  transito: "Trânsito",
  ix: "IX",
  pni: "PNI",
  contingencia: "Contingência",
};

// Campos do UpstreamCreate (schemas.py:756-770) — strings vazias para os
// numéricos (mesmo padrão do Circuits.tsx: num() converte na submissão).
type FormUpstream = {
  name: string;
  tipo: UpstreamTipo;
  organization_id: string;
  capacity: string;
  priority: string;
  cost: string;
  expected_prefixes_v4: string;
  expected_prefixes_v6: string;
  max_prefix_margin_pct: string;
  rpki_enabled: boolean;
  entrada_local_preference: string;
  contingencia_local_preference: string;
  contingencia_prepend: string;
  contingencia_notes: string;
};

const FORM_VAZIO: FormUpstream = {
  name: "",
  tipo: "transito",
  organization_id: "",
  capacity: "",
  priority: "",
  cost: "",
  expected_prefixes_v4: "",
  expected_prefixes_v6: "",
  max_prefix_margin_pct: "20", // default do UpstreamCreate
  rpki_enabled: true,
  entrada_local_preference: "",
  contingencia_local_preference: "",
  contingencia_prepend: "",
  contingencia_notes: "",
};

const num = (v: string) => (v === "" ? null : Number(v));

function paraPayload(f: FormUpstream): UpstreamCreateIn {
  return {
    name: f.name,
    tipo: f.tipo,
    capacity: f.capacity || null,
    priority: num(f.priority),
    cost: f.cost || null,
    organization_id: Number(f.organization_id),
    expected_prefixes_v4: num(f.expected_prefixes_v4),
    expected_prefixes_v6: num(f.expected_prefixes_v6),
    max_prefix_margin_pct: num(f.max_prefix_margin_pct) ?? 20,
    rpki_enabled: f.rpki_enabled,
    entrada_local_preference: num(f.entrada_local_preference),
    contingencia_local_preference: num(f.contingencia_local_preference),
    contingencia_prepend: num(f.contingencia_prepend),
    contingencia_notes: f.contingencia_notes || null,
  };
}

// Campos do formulário compartilhados entre o dialog de criação e o de edição
// (mesmos campos do UpstreamCreate — uma única fonte de verdade no JSX).
function CamposUpstream({
  form,
  onChange,
  operadoras,
}: {
  form: FormUpstream;
  onChange: (f: FormUpstream) => void;
  operadoras: OrganizationOut[];
}) {
  const set = <K extends keyof FormUpstream>(campo: K, valor: FormUpstream[K]) => onChange({ ...form, [campo]: valor });
  return (
    <>
      <FormField label="Nome *" help={help("upstream.name")}>
        <input value={form.name} onChange={(e) => set("name", e.target.value)} required />
      </FormField>
      <FormField label="Tipo *" help={help("upstream.tipo")}>
        <select value={form.tipo} onChange={(e) => set("tipo", e.target.value as UpstreamTipo)} required>
          <option value="transito">Trânsito</option>
          <option value="ix">IX</option>
          <option value="pni">PNI</option>
          <option value="contingencia">Contingência</option>
        </select>
      </FormField>
      <FormField label="Operadora *" help={help("upstream.organization_id")}>
        <select value={form.organization_id} onChange={(e) => set("organization_id", e.target.value)} required>
          <option value="">—</option>
          {operadoras.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </FormField>
      <FormField label="Capacidade" help={help("upstream.capacity")}>
        <input value={form.capacity} onChange={(e) => set("capacity", e.target.value)} />
      </FormField>
      <FormField label="Prioridade" help={help("upstream.priority")}>
        <input type="number" min={1} value={form.priority} onChange={(e) => set("priority", e.target.value)} />
      </FormField>
      <FormField label="Custo" help={help("upstream.cost")}>
        <input value={form.cost} onChange={(e) => set("cost", e.target.value)} />
      </FormField>
      <FormField label="Prefixos esperados V4" help={help("upstream.expected_prefixes_v4")}>
        <input type="number" min={0} value={form.expected_prefixes_v4} onChange={(e) => set("expected_prefixes_v4", e.target.value)} />
      </FormField>
      <FormField label="Prefixos esperados V6" help={help("upstream.expected_prefixes_v6")}>
        <input type="number" min={0} value={form.expected_prefixes_v6} onChange={(e) => set("expected_prefixes_v6", e.target.value)} />
      </FormField>
      <FormField label="Margem (%)" help={help("upstream.max_prefix_margin_pct")}>
        <input
          type="number"
          min={0}
          max={100}
          value={form.max_prefix_margin_pct}
          onChange={(e) => set("max_prefix_margin_pct", e.target.value)}
        />
      </FormField>
      <FormField label="RPKI" help={help("upstream.rpki_enabled")}>
        <input type="checkbox" checked={form.rpki_enabled} onChange={(e) => set("rpki_enabled", e.target.checked)} />
      </FormField>
      <FormField label="Local-preference de entrada" help={help("upstream.entrada_local_preference")}>
        <input
          type="number"
          value={form.entrada_local_preference}
          onChange={(e) => set("entrada_local_preference", e.target.value)}
        />
      </FormField>
      <FormField label="Local-preference da contingência" help={help("upstream.contingencia_local_preference")}>
        <input
          type="number"
          value={form.contingencia_local_preference}
          onChange={(e) => set("contingencia_local_preference", e.target.value)}
        />
      </FormField>
      <FormField label="Prepend da contingência" help={help("upstream.contingencia_prepend")}>
        <input
          type="number"
          min={0}
          max={10}
          value={form.contingencia_prepend}
          onChange={(e) => set("contingencia_prepend", e.target.value)}
        />
      </FormField>
      <FormField label="Observações da contingência" help={help("upstream.contingencia_notes")}>
        <textarea rows={2} value={form.contingencia_notes} onChange={(e) => set("contingencia_notes", e.target.value)} />
      </FormField>
    </>
  );
}

export default function Upstreams() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useUpstreams({ includeDisabled: incluirInativos });
  const { data: organizations } = useOrganizations();
  const criar = useUpstreamCriar();
  const atualizar = useUpstreamAtualizar();

  const [criando, setCriando] = useState(false);
  const [form, setForm] = useState<FormUpstream>(FORM_VAZIO);
  const [editando, setEditando] = useState<UpstreamOut | null>(null);
  const [formEdit, setFormEdit] = useState<FormUpstream>(FORM_VAZIO);
  const [desativando, setDesativando] = useState<UpstreamOut | null>(null);
  const [reativando, setReativando] = useState<UpstreamOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [erroEdit, setErroEdit] = useState<string | null>(null);

  const operadoras = (organizations ?? []).filter((o) => o.kind === "operadora");

  const nomeOperadora = (u: UpstreamOut) =>
    u.organization_name ?? operadoras.find((o) => o.id === u.organization_id)?.name ?? "—";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync(paraPayload(form));
      setForm(FORM_VAZIO);
      setCriando(false);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar o upstream.");
    }
  }

  function abrirEdicao(u: UpstreamOut) {
    setFormEdit({
      name: u.name,
      tipo: u.tipo,
      organization_id: String(u.organization_id),
      capacity: u.capacity ?? "",
      priority: u.priority === null ? "" : String(u.priority),
      cost: u.cost ?? "",
      expected_prefixes_v4: u.expected_prefixes_v4 === null ? "" : String(u.expected_prefixes_v4),
      expected_prefixes_v6: u.expected_prefixes_v6 === null ? "" : String(u.expected_prefixes_v6),
      max_prefix_margin_pct: String(u.max_prefix_margin_pct),
      rpki_enabled: u.rpki_enabled,
      entrada_local_preference: u.entrada_local_preference === null ? "" : String(u.entrada_local_preference),
      contingencia_local_preference:
        u.contingencia_local_preference === null ? "" : String(u.contingencia_local_preference),
      contingencia_prepend: u.contingencia_prepend === null ? "" : String(u.contingencia_prepend),
      contingencia_notes: u.contingencia_notes ?? "",
    });
    setErroEdit(null);
    setEditando(u);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({ id: editando.id, ...paraPayload(formEdit) });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar o upstream.");
    }
  }

  function confirmarStatus(u: UpstreamOut, valor: boolean) {
    setErro(null);
    void atualizar
      .mutateAsync({ id: u.id, admin_status: valor })
      .then(() => {
        if (valor) setReativando(null);
        else setDesativando(null);
      })
      .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao atualizar o upstream."));
  }

  const dialogoDesativar = (
    <ConfirmDialog
      aberto={desativando !== null}
      titulo={`Desativar ${desativando?.name ?? ""}?`}
      mensagem="O upstream fica indisponível para novos vínculos; o registro permanece."
      onConfirmar={() => desativando && confirmarStatus(desativando, false)}
      onCancelar={() => setDesativando(null)}
      confirmando={atualizar.isPending}
    />
  );
  const dialogoReativar = (
    <ConfirmDialog
      aberto={reativando !== null}
      titulo={`Reativar ${reativando?.name ?? ""}?`}
      mensagem="O upstream volta ao catálogo ativo."
      onConfirmar={() => reativando && confirmarStatus(reativando, true)}
      onCancelar={() => setReativando(null)}
      confirmando={atualizar.isPending}
    />
  );

  return (
    <main>
      <PageHeader titulo="Upstreams" sub="Conectividade própria — trânsito, IX, PNI e contingência." />
      <label className="inline-check">
        <input
          type="checkbox"
          checked={incluirInativos}
          onChange={(e) => setIncluirInativos(e.target.checked)}
        />
        Ver desativados
      </label>
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
          Novo upstream
        </button>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<UpstreamOut>
        colunas={[
          { key: "name", title: "Nome", render: (u) => <Link to={`/upstreams/${u.id}`}>{u.name}</Link> },
          { key: "organization_name", title: "Operadora", render: (u) => nomeOperadora(u) },
          { key: "tipo", title: "Tipo", render: (u) => <StatusBadge estado={TIPO_LABEL[u.tipo]} /> },
          { key: "expected_prefixes_v4", title: "Esperado V4", render: (u) => u.expected_prefixes_v4 ?? "—" },
          { key: "expected_prefixes_v6", title: "Esperado V6", render: (u) => u.expected_prefixes_v6 ?? "—" },
          { key: "admin_status", title: "Situação", render: (u) => <StatusBadge estado={u.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os upstreams." : undefined}
        acoes={(u) =>
          podeEscrever ? (
            <>
              <button type="button" onClick={() => abrirEdicao(u)}>
                Editar
              </button>
              {u.admin_status ? (
                <button type="button" onClick={() => setDesativando(u)}>
                  Desativar
                </button>
              ) : (
                <button type="button" onClick={() => setReativando(u)}>
                  Reativar
                </button>
              )}
            </>
          ) : null
        }
      />
      {criando && (
        <Modal aberto titulo="Novo upstream" onFechar={() => setCriando(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <CamposUpstream form={form} onChange={setForm} operadoras={operadoras} />
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
      {editando && (
        <Modal aberto titulo={`Editar ${editando.name}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <CamposUpstream form={formEdit} onChange={setFormEdit} operadoras={operadoras} />
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
      {dialogoDesativar}
      {dialogoReativar}
    </main>
  );
}
