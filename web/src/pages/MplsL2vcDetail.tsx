import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useDevices, useL2vcDetalhe, useL2vcPlano } from "@/api/hooks";
import type { ServiceEndpointOut } from "@/api/types";
import { StatusBadge } from "@/components/StatusBadge";
import { TimeAgo } from "@/components/TimeAgo";
import { PageHeader } from "@/components/PageHeader";
import { MonoCode } from "@/components/MonoCode";
import SolicitarMudanca from "@/components/SolicitarMudanca";

export default function MplsL2vcDetail() {
  const { id } = useParams();
  const l2vcId = Number(id);
  const { data, isLoading, error } = useL2vcDetalhe(l2vcId);
  const { data: plano } = useL2vcPlano(l2vcId);
  const { data: devices } = useDevices();

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!data) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar o serviço L2VC."}</p>
      </main>
    );
  }

  const sim = (v: boolean) => (v ? "Sim" : "—");

  return (
    <main>
      <PageHeader
        titulo={`L2VC ${data.name}`}
        sub={`VC-ID ${data.vc_id} · ${data.domain_name ?? `domínio #${data.domain_id}`}`}
        acoes={
          <>
            <Link to="/mpls/l2vc">← Voltar</Link>
            <Link to="/change-requests">Change requests</Link>
            <SolicitarMudanca l2vc_id={data.id} />
          </>
        }
      />
      <table>
        <tbody>
          <tr><th>Domínio</th><td>{data.domain_name ?? `#${data.domain_id}`}</td></tr>
          <tr><th>VC-ID</th><td>{data.vc_id}</td></tr>
          <tr><th>MTU</th><td>{data.mtu}</td></tr>
          <tr><th>Control-word</th><td>{sim(data.control_word)}</td></tr>
          <tr><th>Flow-label</th><td>{sim(data.flow_label)}</td></tr>
          <tr><th>Redundância</th><td>{data.redundancy ?? "—"}</td></tr>
          <tr><th>Descrição</th><td>{data.description ?? "—"}</td></tr>
          <tr><th>Situação</th><td><StatusBadge estado={data.admin_status ? "ativo" : "inativo"} /></td></tr>
          <tr><th>Estado operacional</th><td><StatusBadge estado={data.operational_status} /></td></tr>
          <tr><th>Última coleta</th><td><TimeAgo iso={data.last_collected_at} /></td></tr>
        </tbody>
      </table>

      <h2>Pontas</h2>
      <table>
        <thead>
          <tr><th>Equipamento</th><th>Interface</th><th>Encapsulação</th><th>VID</th><th>Inner VLAN</th><th>MTU</th><th>Estado</th></tr>
        </thead>
        <tbody>
          {data.endpoints.map((ep: ServiceEndpointOut) => (
            <tr key={ep.id}>
              <td>{ep.device_name ?? devices?.find((d) => d.id === ep.device_id)?.name ?? `Device #${ep.device_id}`}</td>
              <td>{ep.interface}</td>
              <td>{ep.encapsulation}</td>
              <td>{ep.vid ?? ep.vlan_id ?? "—"}</td>
              <td>{ep.inner_vlan ?? "—"}</td>
              <td>{ep.mtu ?? "—"}</td>
              <td><StatusBadge estado={ep.operational_status} /></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Plano previsto</h2>
      {!plano && <p aria-busy="true">Calculando o diff da última coleta…</p>}
      {plano && plano.length === 0 && <p>Nenhum comando previsto para o estado atual — a configuração está em conformidade.</p>}
      {plano?.map((item) => (
        <section key={item.device_id}>
          <h3>{devices?.find((d) => d.id === item.device_id)?.name ?? `Device #${item.device_id}`}</h3>
          {item.aviso && <p role="alert">{item.aviso}</p>}
          <p>Baseline: {item.baseline_snapshot_id ?? "sem coleta de recursos"}</p>
          {item.blocos.length === 0 && <p>Esse equipamento não precisa de mudanças.</p>}
          {item.blocos.map((bloco, idx) => (
            <div key={idx}>
              <p>
                {bloco.acao} · {bloco.tipo} {bloco.objeto} #{bloco.objeto_id}
              </p>
              <MonoCode texto={bloco.comandos.join("\n")} />
            </div>
          ))}
        </section>
      ))}
    </main>
  );
}
