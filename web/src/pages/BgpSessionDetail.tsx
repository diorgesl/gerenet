import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useBgpSession, useCircuitDetail, useCommunities, useSessionCommunities, useSessionCommunity, useSessionSenha } from "@/api/hooks";
import { help } from "@/help";
import { StatusBadge } from "@/components/StatusBadge";
import { FormField } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import SolicitarMudanca from "@/components/SolicitarMudanca";

export default function BgpSessionDetail() {
  const { id } = useParams();
  const sessionId = Number(id);
  const { data, isLoading, error } = useBgpSession(sessionId);
  // Detalhe do circuito do peer — o upstream_id derivado (R-25) decide o escopo
  // da mudança: sessão de circuito vinculado a upstream muda pelo upstream
  // (matriz inteira), não por circuito. enabled: id>0 segura o fetch pré-carga.
  const { data: circuito } = useCircuitDetail(data?.circuit_id ?? 0);
  const { data: comunidades } = useSessionCommunities(sessionId);
  const { data: catalogo } = useCommunities();
  const assoc = useSessionCommunity();
  const senha = useSessionSenha();
  const [communityId, setCommunityId] = useState("");
  const [senhaNova, setSenhaNova] = useState("");
  const [erro, setErro] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar a sessão BGP."}</p>
      </main>
    );
  }

  return (
    <main>
      <PageHeader
        titulo={`Sessão BGP #${data.id}`}
        acoes={
          circuito?.upstream_id != null ? (
            <SolicitarMudanca upstream_id={circuito.upstream_id} />
          ) : (
            <SolicitarMudanca circuit_id={data.circuit_id} />
          )
        }
      />
      <table>
        <tbody>
          <tr><th>Família</th><td><StatusBadge estado={data.afi} /></td></tr>
          <tr><th>Endereços</th><td>{data.local_address} ↔ {data.remote_address}</td></tr>
          <tr><th>ASNs</th><td>{data.asn_local ?? "—"} ↔ {data.asn_remote ?? "—"}</td></tr>
          <tr><th>Maximum-prefix</th><td>{data.maximum_prefix ?? "—"} ({data.maximum_prefix_threshold ?? "—"}%)</td></tr>
          <tr><th>BFD</th><td>{data.bfd_enabled ? "Sim" : "—"}</td></tr>
          <tr><th>Descrição</th><td>{data.description ?? "—"}</td></tr>
          <tr><th>Shutdown</th><td>{data.shutdown ? "Sim" : "Não"}</td></tr>
        </tbody>
      </table>
      <h2>Communities</h2>
      {comunidades?.map((c) => (
        <p key={c.id}>
          {c.name}{" "}
          <button type="button" onClick={() => void assoc.mutate({ sessionId, communityId: c.id, associa: false })}>
            Remover
          </button>
        </p>
      ))}
      <form
        className="form-inline"
        onSubmit={(e) => {
          e.preventDefault();
          setErro(null);
          if (communityId === "") return;
          void assoc
            .mutateAsync({ sessionId, communityId: Number(communityId), associa: true })
            .then(() => setCommunityId(""))
            .catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao associar community."));
        }}
      >
        <FormField label="Community" help={help("community.name")}>
          <select value={communityId} onChange={(e) => setCommunityId(e.target.value)}>
            <option value="">—</option>
            {(catalogo ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </FormField>
        <button className="primary" type="submit" disabled={assoc.isPending}>
          Associar
        </button>
      </form>
      {erro && <p role="alert">{erro}</p>}
      {assoc.error && <p role="alert">{String(assoc.error.message ?? "Falha ao associar community.")}</p>}
      <h2>Senha MD5</h2>
      <p>Situação: {data.has_password ? "Sim" : "Não"}</p>
      <form
        className="form-inline"
        onSubmit={(e) => {
          e.preventDefault();
          setErro(null);
          void senha.mutateAsync({ sessionId, password: senhaNova }).then(() => setSenhaNova("")).catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao definir senha."));
        }}
      >
        <FormField label="Senha MD5" help={help("bgp.password")}>
          <input
            type="password"
            value={senhaNova}
            onChange={(e) => setSenhaNova(e.target.value)}
            autoComplete="new-password"
            required
          />
        </FormField>
        <button className="primary" type="submit" disabled={senha.isPending}>
          Definir senha
        </button>
      </form>
    </main>
  );
}
