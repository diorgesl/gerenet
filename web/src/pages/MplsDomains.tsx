import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useDevices,
  useMplsDomainAtualizar,
  useMplsDomainCriar,
  useMplsDomains,
  useMplsMemberAdicionar,
  useMplsMemberRemover,
} from "@/api/hooks";
import type { MplsDomainOut, MplsMemberOut } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Modal } from "@/components/Modal";

const FORM_VAZIO = { name: "", description: "" };
const MEMBRO_VAZIO = { device_id: "", loopback_address: "", role: "pe" as "pe" | "core" };

export default function MplsDomains() {
  const { id } = useParams();
  const domainId = Number(id);
  const modoDetalhe = Number.isInteger(domainId) && domainId > 0;
  const { podeEscrever } = useAuth();
  const [incluirInativos, setIncluirInativos] = useState(false);
  const { data, isLoading, error } = useMplsDomains({ includeDisabled: incluirInativos || modoDetalhe });
  const { data: devices } = useDevices();
  const criar = useMplsDomainCriar();
  const atualizar = useMplsDomainAtualizar();
  const adicionarMembro = useMplsMemberAdicionar();
  const removerMembro = useMplsMemberRemover();

  const [criando, setCriando] = useState(false);
  const [form, setForm] = useState(FORM_VAZIO);
  const [desativando, setDesativando] = useState<MplsDomainOut | null>(null);
  const [reativando, setReativando] = useState<MplsDomainOut | null>(null);
  const [adicionandoMembro, setAdicionandoMembro] = useState<MplsDomainOut | null>(null);
  const [membroForm, setMembroForm] = useState(MEMBRO_VAZIO);
  const [removendo, setRemovendo] = useState<MplsMemberOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const dominio = modoDetalhe ? data?.find((d) => d.id === domainId) : undefined;

  const nomeDevice = (deviceId: number) => devices?.find((d) => d.id === deviceId)?.name;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({ name: form.name, description: form.description || null });
      setForm(FORM_VAZIO);
      setCriando(false);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar o domínio MPLS.");
    }
  }

  async function onSubmitMembro(e: FormEvent) {
    e.preventDefault();
    if (!adicionandoMembro) return;
    setErro(null);
    try {
      await adicionarMembro.mutateAsync({
        domainId: adicionandoMembro.id,
        device_id: Number(membroForm.device_id),
        loopback_address: membroForm.loopback_address,
        role: membroForm.role,
      });
      setMembroForm(MEMBRO_VAZIO);
      setAdicionandoMembro(null);
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao adicionar o membro.");
    }
  }

  function confirmarStatus(d: MplsDomainOut, valor: boolean) {
    setErro(null);
    void atualizar
      .mutateAsync({ id: d.id, admin_status: valor })
      .then(() => {
        if (valor) setReativando(null);
        else setDesativando(null);
      })
      .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao atualizar o domínio MPLS."));
  }

  const botoesStatus = (d: MplsDomainOut) =>
    podeEscrever ? (
      d.admin_status ? (
        <button type="button" onClick={() => setDesativando(d)}>Desativar</button>
      ) : (
        <button type="button" onClick={() => setReativando(d)}>Reativar</button>
      )
    ) : null;

  const dialogoDesativar = (
    <ConfirmDialog
      aberto={desativando !== null}
      titulo={`Desativar ${desativando?.name ?? ""}?`}
      mensagem="O domínio fica indisponível para novos serviços; o registro permanece."
      onConfirmar={() => desativando && confirmarStatus(desativando, false)}
      onCancelar={() => setDesativando(null)}
      confirmando={atualizar.isPending}
    />
  );
  const dialogoReativar = (
    <ConfirmDialog
      aberto={reativando !== null}
      titulo={`Reativar ${reativando?.name ?? ""}?`}
      mensagem="O domínio volta ao catálogo ativo."
      onConfirmar={() => reativando && confirmarStatus(reativando, true)}
      onCancelar={() => setReativando(null)}
      confirmando={atualizar.isPending}
    />
  );

  if (modoDetalhe) {
    if (isLoading) return <p aria-busy="true">Carregando…</p>;
    if (!dominio) {
      return (
        <main>
          <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar o domínio MPLS."}</p>
        </main>
      );
    }
    return (
      <main>
        <PageHeader
          titulo={`Domínio ${dominio.name}`}
          acoes={
            <>
              <Link to="/mpls/domains">← Voltar</Link>
              {botoesStatus(dominio)}
            </>
          }
        />
        {erro && <p role="alert">{erro}</p>}
        <table>
          <tbody>
            <tr><th>Situação</th><td><StatusBadge estado={dominio.admin_status ? "ativo" : "inativo"} /></td></tr>
            <tr><th>Descrição</th><td>{dominio.description ?? "—"}</td></tr>
            <tr><th>Membros</th><td>{dominio.members.length}</td></tr>
          </tbody>
        </table>

        <h2>Membros</h2>
        {podeEscrever && (
          <button
            className="primary"
            type="button"
            onClick={() => {
              setMembroForm(MEMBRO_VAZIO);
              setErro(null);
              setAdicionandoMembro(dominio);
            }}
          >
            Adicionar membro
          </button>
        )}
        <DataTable<MplsMemberOut>
          colunas={[
            { key: "device_name", title: "Equipamento", render: (m) => nomeDevice(m.device_id) ?? m.device_name ?? `Device #${m.device_id}` },
            { key: "loopback_address", title: "Loopback" },
            { key: "role", title: "Função", render: (m) => (m.role === "pe" ? "PE" : "core") },
          ]}
          linhas={dominio.members}
          vazio="Nenhum membro no domínio."
          acoes={(m) =>
            podeEscrever ? <button type="button" onClick={() => setRemovendo(m)}>Remover</button> : null
          }
        />
        <ConfirmDialog
          aberto={removendo !== null}
          titulo={`Remover ${nomeDevice(removendo?.device_id ?? -1) ?? `o membro #${removendo?.device_id ?? ""}`}?`}
          mensagem="O equipamento sai do domínio MPLS; o registro do equipamento permanece."
          onConfirmar={() => {
            if (!removendo || !dominio) return;
            setErro(null);
            void removerMembro
              .mutateAsync({ domainId: dominio.id, deviceId: removendo.device_id })
              .then(() => setRemovendo(null))
              .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao remover o membro."));
          }}
          onCancelar={() => setRemovendo(null)}
          confirmando={removerMembro.isPending}
        />

        {adicionandoMembro && (
          <Modal aberto titulo={`Adicionar membro em ${adicionandoMembro.name}`} onFechar={() => setAdicionandoMembro(null)}>
            <form onSubmit={onSubmitMembro} className="grid-form">
              <FormField label="Equipamento *">
                <select value={membroForm.device_id} onChange={(e) => setMembroForm({ ...membroForm, device_id: e.target.value })} required>
                  <option value="">—</option>
                  {(devices ?? []).map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Loopback *">
                <input
                  value={membroForm.loopback_address}
                  onChange={(e) => setMembroForm({ ...membroForm, loopback_address: e.target.value })}
                  placeholder="192.0.2.1"
                  required
                />
              </FormField>
              <FormField label="Função *">
                <select value={membroForm.role} onChange={(e) => setMembroForm({ ...membroForm, role: e.target.value as "pe" | "core" })}>
                  <option value="pe">PE</option>
                  <option value="core">core</option>
                </select>
              </FormField>
              <div className="dialog-actions">
                <button type="button" onClick={() => setAdicionandoMembro(null)} disabled={adicionarMembro.isPending}>
                  Cancelar
                </button>
                <button className="primary" type="submit" disabled={adicionarMembro.isPending}>
                  {adicionarMembro.isPending ? "Adicionando…" : "Adicionar"}
                </button>
              </div>
            </form>
            {erro && <p role="alert">{erro}</p>}
          </Modal>
        )}
        {dialogoDesativar}
        {dialogoReativar}
      </main>
    );
  }

  return (
    <main>
      <PageHeader titulo="Domínios MPLS" sub="Agrupamento de equipamentos que formam um domínio MPLS (PEs e core)." />
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
          Novo domínio
        </button>
      )}
      {erro && <p role="alert">{erro}</p>}
      <DataTable<MplsDomainOut>
        colunas={[
          { key: "name", title: "Nome", render: (d) => <Link to={`/mpls/domains/${d.id}`}>{d.name}</Link> },
          { key: "description", title: "Descrição", render: (d) => d.description ?? "—" },
          { key: "members", title: "Membros", render: (d) => d.members.length },
          { key: "admin_status", title: "Situação", render: (d) => <StatusBadge estado={d.admin_status ? "ativo" : "inativo"} /> },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        erro={error instanceof ApiError ? error.message : error ? "Falha ao carregar os domínios MPLS." : undefined}
        acoes={botoesStatus}
      />
      {criando && (
        <Modal aberto titulo="Novo domínio MPLS" onFechar={() => setCriando(false)}>
          <form onSubmit={onSubmit} className="grid-form">
            <FormField label="Nome *">
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </FormField>
            <FormField label="Descrição">
              <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2} />
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
      {dialogoDesativar}
      {dialogoReativar}
    </main>
  );
}
