import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useBgpSessionAtualizar,
  useBgpSessionCriar,
  useBgpSessions,
  useCircuitDetail,
  useCircuits,
  useDevices,
  useOrganizations,
  usePolicyProfiles,
} from "@/api/hooks";
import { help } from "@/help";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";
import type { BgpSessionOut, CircuitDetailOut, CircuitOut } from "@/api/types";

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

type FormEdit = typeof FORM_VAZIO;

export default function BgpSessions() {
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useBgpSessions({ include_disabled: incluirInativos });
  const { data: circuits } = useCircuits();
  const { data: devices } = useDevices();
  const { data: organizations } = useOrganizations({ includeDisabled: true });
  const { data: profiles } = usePolicyProfiles();
  const criar = useBgpSessionCriar();
  const atualizar = useBgpSessionAtualizar();
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<BgpSessionOut | null>(null);
  const [reativando, setReativando] = useState<BgpSessionOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [editando, setEditando] = useState<BgpSessionOut | null>(null);
  const [formEdit, setFormEdit] = useState<FormEdit>(FORM_VAZIO);
  const [erroEdit, setErroEdit] = useState<string | null>(null);
  // Autopreenchimento a partir do circuito escolhido:
  // preencherDoCircuito é síncrono (device/ASNs das listas); as pontas vêm do
  // detalhe (useCircuitDetail) e só valem para o formulário onde a troca ocorreu.
  const origemRef = useRef<"criar" | "editar" | null>(null);
  const [circuitoSelecionado, setCircuitoSelecionado] = useState<number | null>(null);
  const [troca, setTroca] = useState(0);
  const [detalhe, setDetalhe] = useState<CircuitDetailOut | null>(null);
  const { data: detalheApi } = useCircuitDetail(circuitoSelecionado ?? 0);

  const num = (v: string) => (v === "" ? null : Number(v));

  function preencherDoCircuito(f: FormEdit, circ: CircuitOut | undefined): FormEdit {
    if (!circ) return { ...f, device_id: "", asn_local: "", asn_remote: "" };
    const devSel = (devices ?? []).find((d) => d.id === circ.edge_device_id);
    const org = (organizations ?? []).find((o) => o.id === circ.organization_id);
    return {
      ...f,
      device_id: String(circ.edge_device_id),
      asn_local: devSel?.asn != null ? String(devSel.asn) : "",
      asn_remote: org?.asn != null ? String(org.asn) : "",
    };
  }

  function comPontasDe(f: FormEdit, d: CircuitDetailOut | null): FormEdit {
    // Só preenche pontas quando o circuito tem reserva da família; sem reserva (ou
    // com detalhe de outro circuito) não toca no formulário.
    if (!d || Number(f.circuit_id) !== d.id) return f;
    const [local, remoto] = f.afi === "ipv4" ? [d.ipv4_local, d.ipv4_remote] : [d.ipv6_local, d.ipv6_remote];
    if (local === null && remoto === null) return f;
    const semMascara = (v: string | null) => (v === null ? "" : v.split("/")[0]);
    return { ...f, local_address: semMascara(local), remote_address: semMascara(remoto) };
  }

  function aoMudarCircuito(valor: string, origem: "criar" | "editar") {
    const id = valor === "" ? null : Number(valor);
    origemRef.current = id === null ? null : origem;
    setCircuitoSelecionado(id);
    setTroca((n) => n + 1);
    setDetalhe(null); // próximo detalhe é do circuito recém-escolhido
    const circ = (circuits ?? []).find((c) => c.id === id);
    if (origem === "editar")
      setFormEdit((f) => preencherDoCircuito({ ...f, circuit_id: valor, local_address: "", remote_address: "" }, circ));
    else setForm((f) => preencherDoCircuito({ ...f, circuit_id: valor, local_address: "", remote_address: "" }, circ));
  }

  useEffect(() => {
    if (!detalheApi || circuitoSelecionado !== detalheApi.id) return;
    setDetalhe(detalheApi);
    if (origemRef.current === "editar") setFormEdit((f) => comPontasDe(f, detalheApi));
    else if (origemRef.current === "criar") setForm((f) => comPontasDe(f, detalheApi));
  }, [detalheApi, circuitoSelecionado, troca]);

  function aoMudarAfiCriar(afi: "ipv4" | "ipv6") {
    setForm((f) => comPontasDe({ ...f, afi }, detalhe));
  }

  function aoMudarAfiEditar(afi: "ipv4" | "ipv6") {
    setFormEdit((f) => comPontasDe({ ...f, afi }, detalhe));
  }

  function abrirEdicao(s: BgpSessionOut) {
    setFormEdit({
      circuit_id: String(s.circuit_id),
      device_id: String(s.device_id),
      afi: s.afi,
      local_address: s.local_address,
      remote_address: s.remote_address,
      source_address: s.source_address ?? "",
      asn_local: s.asn_local === null ? "" : String(s.asn_local),
      asn_remote: s.asn_remote === null ? "" : String(s.asn_remote),
      description: s.description ?? "",
      import_profile_id: s.import_profile_id === null ? "" : String(s.import_profile_id),
      export_profile_id: s.export_profile_id === null ? "" : String(s.export_profile_id),
      maximum_prefix: s.maximum_prefix === null ? "" : String(s.maximum_prefix),
      maximum_prefix_threshold: s.maximum_prefix_threshold === null ? "" : String(s.maximum_prefix_threshold),
      local_preference: s.local_preference === null ? "" : String(s.local_preference),
      med: s.med === null ? "" : String(s.med),
      prepend: s.prepend === null ? "" : String(s.prepend),
      keepalive: s.keepalive === null ? "" : String(s.keepalive),
      holdtime: s.holdtime === null ? "" : String(s.holdtime),
      bfd_enabled: s.bfd_enabled,
      graceful_restart: s.graceful_restart,
      shutdown: s.shutdown,
      allow_default_route: s.allow_default_route,
    });
    setErroEdit(null);
    setEditando(s);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    setErroEdit(null);
    try {
      await atualizar.mutateAsync({
        id: editando.id,
        circuit_id: Number(formEdit.circuit_id),
        device_id: Number(formEdit.device_id),
        afi: formEdit.afi,
        local_address: formEdit.local_address,
        remote_address: formEdit.remote_address,
        source_address: formEdit.source_address || null,
        asn_local: num(formEdit.asn_local),
        asn_remote: num(formEdit.asn_remote),
        description: formEdit.description || null,
        import_profile_id: formEdit.import_profile_id === "" ? null : Number(formEdit.import_profile_id),
        export_profile_id: formEdit.export_profile_id === "" ? null : Number(formEdit.export_profile_id),
        maximum_prefix: num(formEdit.maximum_prefix),
        maximum_prefix_threshold: num(formEdit.maximum_prefix_threshold),
        local_preference: num(formEdit.local_preference),
        med: num(formEdit.med),
        prepend: num(formEdit.prepend),
        keepalive: num(formEdit.keepalive),
        holdtime: num(formEdit.holdtime),
        bfd_enabled: formEdit.bfd_enabled,
        graceful_restart: formEdit.graceful_restart,
        shutdown: formEdit.shutdown,
        allow_default_route: formEdit.allow_default_route,
      });
      setEditando(null);
    } catch (err) {
      setErroEdit(err instanceof ApiError ? err.message : "Falha ao salvar a sessão BGP.");
    }
  }

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
          <FormField label="Circuito *" help={help("bgp.circuit_id")}>
            <select value={form.circuit_id} onChange={(e) => aoMudarCircuito(e.target.value, "criar")} required>
              <option value="">—</option>
              {(circuits ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.code}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Equipamento *" help={help("bgp.device_id")}>
            <select value={form.device_id} onChange={(e) => setForm({ ...form, device_id: e.target.value })} required>
              <option value="">—</option>
              {(devices ?? []).map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Família" help={help("bgp.afi")}>
            <select value={form.afi} onChange={(e) => aoMudarAfiCriar(e.target.value as "ipv4" | "ipv6")}>
              <option value="ipv4">ipv4</option>
              <option value="ipv6">ipv6</option>
            </select>
          </FormField>
          <FormField label="Endereço local *" help={help("bgp.local_address")}>
            <input value={form.local_address} onChange={(e) => setForm({ ...form, local_address: e.target.value })} required />
          </FormField>
          <FormField label="Endereço remoto *" help={help("bgp.remote_address")}>
            <input value={form.remote_address} onChange={(e) => setForm({ ...form, remote_address: e.target.value })} required />
          </FormField>
          <FormField label="Source address" help={help("bgp.source_address")}>
            <input value={form.source_address} onChange={(e) => setForm({ ...form, source_address: e.target.value })} />
          </FormField>
          <FormField label="ASN local" help={help("bgp.asn_local")}>
            <input type="number" value={form.asn_local} onChange={(e) => setForm({ ...form, asn_local: e.target.value })} />
          </FormField>
          <FormField label="ASN remoto" help={help("bgp.asn_remote")}>
            <input type="number" value={form.asn_remote} onChange={(e) => setForm({ ...form, asn_remote: e.target.value })} />
          </FormField>
          <FormField label="Descrição" help={help("bgp.description")}>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </FormField>
          <FormField label="Perfil de importação" help={help("bgp.import_profile_id")}>
            <select value={form.import_profile_id} onChange={(e) => setForm({ ...form, import_profile_id: e.target.value })}>
              <option value="">—</option>
              {(profiles ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Perfil de exportação" help={help("bgp.export_profile_id")}>
            <select value={form.export_profile_id} onChange={(e) => setForm({ ...form, export_profile_id: e.target.value })}>
              <option value="">—</option>
              {(profiles ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Maximum-prefix" help={help("bgp.maximum_prefix")}>
            <input type="number" value={form.maximum_prefix} onChange={(e) => setForm({ ...form, maximum_prefix: e.target.value })} />
          </FormField>
          <FormField label="Limiar (%)" help={help("bgp.maximum_prefix_threshold")}>
            <input type="number" value={form.maximum_prefix_threshold} onChange={(e) => setForm({ ...form, maximum_prefix_threshold: e.target.value })} />
          </FormField>
          <FormField label="Local-preference" help={help("bgp.local_preference")}>
            <input type="number" value={form.local_preference} onChange={(e) => setForm({ ...form, local_preference: e.target.value })} />
          </FormField>
          <FormField label="MED" help={help("bgp.med")}>
            <input type="number" value={form.med} onChange={(e) => setForm({ ...form, med: e.target.value })} />
          </FormField>
          <FormField label="Prepend" help={help("bgp.prepend")}>
            <input type="number" value={form.prepend} onChange={(e) => setForm({ ...form, prepend: e.target.value })} />
          </FormField>
          <FormField label="Keepalive" help={help("bgp.keepalive")}>
            <input type="number" value={form.keepalive} onChange={(e) => setForm({ ...form, keepalive: e.target.value })} />
          </FormField>
          <FormField label="Holdtime" help={help("bgp.holdtime")}>
            <input type="number" value={form.holdtime} onChange={(e) => setForm({ ...form, holdtime: e.target.value })} />
          </FormField>
          <FormField label="BFD" help={help("bgp.bfd_enabled")}>
            <input type="checkbox" checked={form.bfd_enabled} onChange={(e) => setForm({ ...form, bfd_enabled: e.target.checked })} />
          </FormField>
          <FormField label="Graceful restart" help={help("bgp.graceful_restart")}>
            <input type="checkbox" checked={form.graceful_restart} onChange={(e) => setForm({ ...form, graceful_restart: e.target.checked })} />
          </FormField>
          <FormField label="Shutdown" help={help("bgp.shutdown")}>
            <input type="checkbox" checked={form.shutdown} onChange={(e) => setForm({ ...form, shutdown: e.target.checked })} />
          </FormField>
          <FormField label="Default route" help={help("bgp.allow_default_route")}>
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
          {
            key: "circuit",
            title: "Circuito",
            render: (s) => (
              <>
                {circuits?.find((c) => c.id === s.circuit_id)?.code ?? "—"}
                {s.organization_kind === "operadora" && <span className="badge-upstream">upstream</span>}
              </>
            ),
          },
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
            {podeEscrever && (
              <button type="button" onClick={() => abrirEdicao(s)}>
                Editar
              </button>
            )}
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
      {editando && (
        <Modal aberto titulo={`Editar sessão BGP #${editando.id}`} onFechar={() => setEditando(null)}>
          <form onSubmit={salvarEdicao} className="grid-form">
            <FormField label="Circuito *" help={help("bgp.circuit_id")}>
              <select value={formEdit.circuit_id} onChange={(e) => aoMudarCircuito(e.target.value, "editar")} required>
                <option value="">—</option>
                {(circuits ?? []).map((c) => (
                  <option key={c.id} value={c.id}>{c.code}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Equipamento *" help={help("bgp.device_id")}>
              <select value={formEdit.device_id} onChange={(e) => setFormEdit({ ...formEdit, device_id: e.target.value })} required>
                <option value="">—</option>
                {(devices ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Família" help={help("bgp.afi")}>
              <select value={formEdit.afi} onChange={(e) => aoMudarAfiEditar(e.target.value as "ipv4" | "ipv6")}>
                <option value="ipv4">ipv4</option>
                <option value="ipv6">ipv6</option>
              </select>
            </FormField>
            <FormField label="Endereço local *" help={help("bgp.local_address")}>
              <input value={formEdit.local_address} onChange={(e) => setFormEdit({ ...formEdit, local_address: e.target.value })} required />
            </FormField>
            <FormField label="Endereço remoto *" help={help("bgp.remote_address")}>
              <input value={formEdit.remote_address} onChange={(e) => setFormEdit({ ...formEdit, remote_address: e.target.value })} required />
            </FormField>
            <FormField label="Source address" help={help("bgp.source_address")}>
              <input value={formEdit.source_address} onChange={(e) => setFormEdit({ ...formEdit, source_address: e.target.value })} />
            </FormField>
            <FormField label="ASN local" help={help("bgp.asn_local")}>
              <input type="number" value={formEdit.asn_local} onChange={(e) => setFormEdit({ ...formEdit, asn_local: e.target.value })} />
            </FormField>
            <FormField label="ASN remoto" help={help("bgp.asn_remote")}>
              <input type="number" value={formEdit.asn_remote} onChange={(e) => setFormEdit({ ...formEdit, asn_remote: e.target.value })} />
            </FormField>
            <FormField label="Descrição" help={help("bgp.description")}>
              <input value={formEdit.description} onChange={(e) => setFormEdit({ ...formEdit, description: e.target.value })} />
            </FormField>
            <FormField label="Perfil de importação" help={help("bgp.import_profile_id")}>
              <select value={formEdit.import_profile_id} onChange={(e) => setFormEdit({ ...formEdit, import_profile_id: e.target.value })}>
                <option value="">—</option>
                {(profiles ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Perfil de exportação" help={help("bgp.export_profile_id")}>
              <select value={formEdit.export_profile_id} onChange={(e) => setFormEdit({ ...formEdit, export_profile_id: e.target.value })}>
                <option value="">—</option>
                {(profiles ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </FormField>
            <FormField label="Maximum-prefix" help={help("bgp.maximum_prefix")}>
              <input type="number" value={formEdit.maximum_prefix} onChange={(e) => setFormEdit({ ...formEdit, maximum_prefix: e.target.value })} />
            </FormField>
            <FormField label="Limiar (%)" help={help("bgp.maximum_prefix_threshold")}>
              <input type="number" value={formEdit.maximum_prefix_threshold} onChange={(e) => setFormEdit({ ...formEdit, maximum_prefix_threshold: e.target.value })} />
            </FormField>
            <FormField label="Local-preference" help={help("bgp.local_preference")}>
              <input type="number" value={formEdit.local_preference} onChange={(e) => setFormEdit({ ...formEdit, local_preference: e.target.value })} />
            </FormField>
            <FormField label="MED" help={help("bgp.med")}>
              <input type="number" value={formEdit.med} onChange={(e) => setFormEdit({ ...formEdit, med: e.target.value })} />
            </FormField>
            <FormField label="Prepend" help={help("bgp.prepend")}>
              <input type="number" value={formEdit.prepend} onChange={(e) => setFormEdit({ ...formEdit, prepend: e.target.value })} />
            </FormField>
            <FormField label="Keepalive" help={help("bgp.keepalive")}>
              <input type="number" value={formEdit.keepalive} onChange={(e) => setFormEdit({ ...formEdit, keepalive: e.target.value })} />
            </FormField>
            <FormField label="Holdtime" help={help("bgp.holdtime")}>
              <input type="number" value={formEdit.holdtime} onChange={(e) => setFormEdit({ ...formEdit, holdtime: e.target.value })} />
            </FormField>
            <FormField label="BFD" help={help("bgp.bfd_enabled")}>
              <input type="checkbox" checked={formEdit.bfd_enabled} onChange={(e) => setFormEdit({ ...formEdit, bfd_enabled: e.target.checked })} />
            </FormField>
            <FormField label="Graceful restart" help={help("bgp.graceful_restart")}>
              <input type="checkbox" checked={formEdit.graceful_restart} onChange={(e) => setFormEdit({ ...formEdit, graceful_restart: e.target.checked })} />
            </FormField>
            <FormField label="Shutdown" help={help("bgp.shutdown")}>
              <input type="checkbox" checked={formEdit.shutdown} onChange={(e) => setFormEdit({ ...formEdit, shutdown: e.target.checked })} />
            </FormField>
            <FormField label="Default route" help={help("bgp.allow_default_route")}>
              <input type="checkbox" checked={formEdit.allow_default_route} onChange={(e) => setFormEdit({ ...formEdit, allow_default_route: e.target.checked })} />
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
