import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useAddUpstreamCommunity,
  useCircuits,
  useDesvincularCircuito,
  usePrefixAuthorizations,
  useRemoveUpstreamCommunity,
  useUpstreamDetail,
  useVincularCircuito,
} from "@/api/hooks";
import type { UpstreamCommunityOut } from "@/api/types";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { TimeAgo } from "@/components/TimeAgo";
import SolicitarMudanca from "@/components/SolicitarMudanca";
import { TIPO_LABEL } from "./Upstreams";

const FORM_COMMUNITY_VAZIO = {
  purpose: "blackhole" as UpstreamCommunityOut["purpose"],
  value: "",
  direcao: "ambos" as UpstreamCommunityOut["direcao"],
  regiao: "",
  bloquear: false,
  notes: "",
};

const sim = (v: boolean) => (v ? "Sim" : "—");

export default function UpstreamDetail() {
  const { id } = useParams();
  const upstreamId = Number(id);
  const { podeEscrever } = useAuth();
  const { data, isLoading, error } = useUpstreamDetail(upstreamId);
  const { data: circuits } = useCircuits();
  // enabled: não busca antes do detalhe chegar (evita fetch sem o filtro de org).
  const { data: autorizacoes } = usePrefixAuthorizations(
    { organization_id: data?.organization_id },
    Boolean(data),
  );
  const vincular = useVincularCircuito();
  const desvincular = useDesvincularCircuito();
  const addCommunity = useAddUpstreamCommunity();
  const removeCommunity = useRemoveUpstreamCommunity();

  const [circuitoForm, setCircuitoForm] = useState({ circuit_id: "", papel: "principal", ordem: "" });
  const [modalCommunity, setModalCommunity] = useState(false);
  const [formCommunity, setFormCommunity] = useState(FORM_COMMUNITY_VAZIO);
  const [erroVinculo, setErroVinculo] = useState<string | null>(null);
  const [erroCommunity, setErroCommunity] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar o upstream."}</p>
      </main>
    );
  }

  const vinculados = new Set(data.circuitos.map((c) => c.circuit_id));
  const disponveis = (circuits ?? []).filter((c) => !vinculados.has(c.id));

  const sessoesDoCircuito = (circuitId: number) => data.sessoes.filter((s) => s.circuit_id === circuitId);

  async function onSubmitVinculo(e: FormEvent) {
    e.preventDefault();
    setErroVinculo(null);
    if (circuitoForm.circuit_id === "") return;
    try {
      await vincular.mutateAsync({
        upstreamId,
        circuit_id: Number(circuitoForm.circuit_id),
        papel: circuitoForm.papel as "principal" | "contingencia",
        ordem: circuitoForm.ordem === "" ? 1 : Number(circuitoForm.ordem),
      });
      setCircuitoForm({ circuit_id: "", papel: "principal", ordem: "" });
    } catch (err) {
      setErroVinculo(err instanceof ApiError ? err.message : "Falha ao vincular o circuito.");
    }
  }

  function desvincularCircuito(circuitId: number) {
    setErroVinculo(null);
    void desvincular
      .mutateAsync({ upstreamId, circuitId })
      .catch((err) => setErroVinculo(err instanceof ApiError ? err.message : "Falha ao desvincular o circuito."));
  }

  async function onSubmitCommunity(e: FormEvent) {
    e.preventDefault();
    setErroCommunity(null);
    try {
      await addCommunity.mutateAsync({
        upstreamId,
        purpose: formCommunity.purpose,
        value: formCommunity.value,
        direcao: formCommunity.direcao,
        regiao: formCommunity.regiao || null,
        bloquear: formCommunity.bloquear,
        notes: formCommunity.notes || null,
      });
      setFormCommunity(FORM_COMMUNITY_VAZIO);
      setModalCommunity(false);
    } catch (err) {
      setErroCommunity(err instanceof ApiError ? err.message : "Falha ao cadastrar a community.");
    }
  }

  return (
    <main>
      <PageHeader
        titulo={data.name}
        sub={`${TIPO_LABEL[data.tipo]} · ${data.capacity ?? "capacidade —"} · ${data.organization_name ??
          `organização #${data.organization_id}`}`}
        acoes={
          <>
            <Link to="/upstreams">← Voltar</Link>
            <SolicitarMudanca upstream_id={data.id} />
          </>
        }
      />
      <table>
        <tbody>
          <tr><th>Tipo</th><td>{TIPO_LABEL[data.tipo]}</td></tr>
          <tr><th>Operadora</th><td>{data.organization_name ?? `#${data.organization_id}`}</td></tr>
          <tr><th>Capacidade</th><td>{data.capacity ?? "—"}</td></tr>
          <tr><th>Prioridade</th><td>{data.priority ?? "—"}</td></tr>
          <tr><th>Custo</th><td>{data.cost ?? "—"}</td></tr>
          <tr><th>Prefixos esperados</th><td>V4: {data.expected_prefixes_v4 ?? "—"} · V6: {data.expected_prefixes_v6 ?? "—"}</td></tr>
          <tr><th>Margem (%)</th><td>{data.max_prefix_margin_pct}</td></tr>
          <tr><th>RPKI</th><td>{sim(data.rpki_enabled)}</td></tr>
          <tr><th>Local-preference de entrada</th><td>{data.entrada_local_preference ?? "—"}</td></tr>
          <tr><th>Local-preference da contingência</th><td>{data.contingencia_local_preference ?? "—"}</td></tr>
          <tr><th>Prepend da contingência</th><td>{data.contingencia_prepend ?? "—"}</td></tr>
          <tr><th>Observações da contingência</th><td>{data.contingencia_notes ?? "—"}</td></tr>
          <tr><th>Situação</th><td><StatusBadge estado={data.admin_status ? "ativo" : "inativo"} /></td></tr>
          <tr><th>Criado em</th><td><TimeAgo iso={data.created_at} /></td></tr>
        </tbody>
      </table>

      <h2>Matriz principal × contingência</h2>
      {data.circuitos.length === 0 && (
        <p>Nenhum circuito vinculado — a matriz de conectividade fica vazia até vincular um circuito.</p>
      )}
      {data.circuitos.length > 0 && (
        <table>
          <thead>
            <tr><th>Circuito</th><th>Papel</th><th>Ordem</th><th>Sessões</th>{podeEscrever && <th />}</tr>
          </thead>
          <tbody>
            {data.circuitos.map((v) => (
              <tr key={v.id}>
                <td>
                  <Link to={`/circuits/${v.circuit_id}`}>Circuito #{v.circuit_id}</Link>
                </td>
                <td><StatusBadge estado={v.papel} /></td>
                <td>{v.ordem}</td>
                <td>
                  {sessoesDoCircuito(v.circuit_id).length === 0 && <p>Sem sessões BGP.</p>}
                  {sessoesDoCircuito(v.circuit_id).length > 0 && (
                    <table>
                      <thead>
                        <tr><th>Afi</th><th>Endereços</th><th>Situação</th><th>Cadastro</th></tr>
                      </thead>
                      <tbody>
                        {sessoesDoCircuito(v.circuit_id).map((s) => (
                          <tr key={s.id}>
                            <td><StatusBadge estado={s.afi} /></td>
                            <td>{s.local_address} ↔ {s.remote_address}</td>
                            <td><StatusBadge estado={s.shutdown ? "inativo" : "ativo"} /></td>
                            <td><StatusBadge estado={s.admin_status ? "ativo" : "inativo"} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </td>
                {podeEscrever && (
                  <td>
                    <button
                      type="button"
                      disabled={desvincular.isPending}
                      onClick={() => desvincularCircuito(v.circuit_id)}
                    >
                      Desvincular
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {podeEscrever && (
        <form className="form-inline" onSubmit={onSubmitVinculo}>
          <FormField label="Vincular circuito">
            <select
              value={circuitoForm.circuit_id}
              onChange={(e) => setCircuitoForm({ ...circuitoForm, circuit_id: e.target.value })}
            >
              <option value="">—</option>
              {disponveis.map((c) => (
                <option key={c.id} value={c.id}>Circuito #{c.id} — {c.code}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Papel">
            <select value={circuitoForm.papel} onChange={(e) => setCircuitoForm({ ...circuitoForm, papel: e.target.value })}>
              <option value="principal">principal</option>
              <option value="contingencia">contingência</option>
            </select>
          </FormField>
          <FormField label="Ordem">
            <input
              type="number"
              min={1}
              value={circuitoForm.ordem}
              onChange={(e) => setCircuitoForm({ ...circuitoForm, ordem: e.target.value })}
            />
          </FormField>
          <button className="primary" type="submit" disabled={vincular.isPending}>
            {vincular.isPending ? "Vinculando…" : "Vincular"}
          </button>
        </form>
      )}
      {erroVinculo && <p role="alert">{erroVinculo}</p>}

      <h2>Communities da operadora</h2>
      {data.comunidades.length === 0 && <p>Nenhuma community cadastrada.</p>}
      {data.comunidades.length > 0 && (
        <table>
          <thead>
            <tr><th>Purpose</th><th>Valor</th><th>Direção</th><th>Região</th><th>Bloquear</th><th>Descrição</th><th>Situação</th></tr>
          </thead>
          <tbody>
            {data.comunidades.map((c) => (
              <tr key={c.id}>
                <td>{c.purpose}</td>
                <td>{c.value}</td>
                <td>{c.direcao}</td>
                <td>{c.regiao ?? "—"}</td>
                <td>{sim(c.bloquear)}</td>
                <td>{c.notes ?? "—"}</td>
                <td><StatusBadge estado={c.admin_status ? "ativo" : "inativo"} /></td>
                {podeEscrever && (
                  <td>
                    <button
                      type="button"
                      disabled={removeCommunity.isPending}
                      onClick={() => {
                        setErroCommunity(null);
                        void removeCommunity
                          .mutateAsync({ upstreamId, communityId: c.id })
                          .catch((err) =>
                            setErroCommunity(err instanceof ApiError ? err.message : "Falha ao remover a community."),
                          );
                      }}
                    >
                      Remover
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {podeEscrever && (
        <button
          className="primary"
          type="button"
          onClick={() => {
            setFormCommunity(FORM_COMMUNITY_VAZIO);
            setErroCommunity(null);
            setModalCommunity(true);
          }}
        >
          Nova community
        </button>
      )}
      {modalCommunity && (
        <Modal aberto titulo="Nova community de operadora" onFechar={() => setModalCommunity(false)}>
          <form onSubmit={onSubmitCommunity} className="grid-form">
            <FormField label="Purpose *">
              <select
                value={formCommunity.purpose}
                onChange={(e) => setFormCommunity({ ...formCommunity, purpose: e.target.value as UpstreamCommunityOut["purpose"] })}
                required
              >
                <option value="blackhole">blackhole</option>
                <option value="prepend">prepend</option>
                <option value="lp">lp</option>
                <option value="info">info</option>
              </select>
            </FormField>
            <FormField label="Valor *">
              <input
                value={formCommunity.value}
                onChange={(e) => setFormCommunity({ ...formCommunity, value: e.target.value })}
                required
              />
            </FormField>
            <FormField label="Direção">
              <select
                value={formCommunity.direcao}
                onChange={(e) => setFormCommunity({ ...formCommunity, direcao: e.target.value as UpstreamCommunityOut["direcao"] })}
              >
                <option value="import">import</option>
                <option value="export">export</option>
                <option value="ambos">ambos</option>
              </select>
            </FormField>
            <FormField label="Região">
              <input
                value={formCommunity.regiao}
                onChange={(e) => setFormCommunity({ ...formCommunity, regiao: e.target.value })}
              />
            </FormField>
            <FormField label="Bloquear">
              <input
                type="checkbox"
                checked={formCommunity.bloquear}
                onChange={(e) => setFormCommunity({ ...formCommunity, bloquear: e.target.checked })}
              />
            </FormField>
            <FormField label="Descrição">
              <textarea
                rows={2}
                value={formCommunity.notes}
                onChange={(e) => setFormCommunity({ ...formCommunity, notes: e.target.value })}
              />
            </FormField>
            <div className="dialog-actions">
              <button type="button" onClick={() => setModalCommunity(false)} disabled={addCommunity.isPending}>
                Cancelar
              </button>
              <button className="primary" type="submit" disabled={addCommunity.isPending}>
                {addCommunity.isPending ? "Criando…" : "Criar"}
              </button>
            </div>
          </form>
          {erroCommunity && <p role="alert">{erroCommunity}</p>}
        </Modal>
      )}
      {!modalCommunity && erroCommunity && <p role="alert">{erroCommunity}</p>}

      <h2>Autorizações BGP da organização</h2>
      {!autorizacoes && <p aria-busy="true">Carregando autorizações…</p>}
      {autorizacoes && autorizacoes.length === 0 && (
        <p>Nenhuma autorização de prefixo cadastrada para a organização.</p>
      )}
      {autorizacoes && autorizacoes.length > 0 && (
        <table>
          <thead>
            <tr><th>Família</th><th>Prefixo</th><th>Origem</th><th>Validação</th><th>Situação</th></tr>
          </thead>
          <tbody>
            {autorizacoes.map((a) => (
              <tr key={a.id}>
                <td><StatusBadge estado={a.family} /></td>
                <td>{a.prefix}</td>
                <td>{a.origin}</td>
                <td><StatusBadge estado={a.validacao ?? "nao_verificada"} /></td>
                <td><StatusBadge estado={a.admin_status ? "ativo" : "inativo"} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
