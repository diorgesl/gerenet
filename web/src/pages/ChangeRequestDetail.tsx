import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import {
  useChangeRequest,
  useChangeRequestAprovar,
  useChangeRequestCancelar,
  useChangeRequestEnviar,
  useChangeRequestExecutar,
  useChangeRequestReconciliar,
  useChangeRequestRollback,
  useCircuits,
  useDevices,
} from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { ChangeRequestOut } from "@/api/types";

const ACAO_LABELS: Record<ChangeRequestOut["acao"], string> = {
  provision: "Aplicar configuração",
  remove: "Remover configuração",
};

// Rótulo do objeto da CR sem vínculo com circuito: circuitos usam #N;
// CRs de escopo l2vc exibem o nome do serviço e as de escopo upstream o nome
// do upstream (ou "—" quando ausente).
function rotuloObjeto(cr: ChangeRequestOut): string {
  return cr.circuit_id !== null ? `#${cr.circuit_id}` : (cr.l2vc_name ?? cr.upstream_name ?? "—");
}

const CONFIRMACOES: Record<string, { titulo: string; mensagem: string }> = {
  cancelar: {
    titulo: "Cancelar a change request?",
    mensagem: "A CR vai a cancelado e não pode mais ser aprovada nem executada (o registro permanece).",
  },
  rejeitar: {
    titulo: "Rejeitar a change request?",
    mensagem: "A CR vai a rejeitado; para voltar ao fluxo, crie uma nova.",
  },
  executar: {
    titulo: "Executar a change request?",
    mensagem: "A mudança será aplicada nos equipamentos pelo worker — confira o diff abaixo antes de confirmar.",
  },
  reconciliar: {
    titulo: "Reconciliar a change request?",
    mensagem: "Steps não aplicados serão replanejados com base no estado atual e a CR volta à aprovação.",
  },
  rollback: {
    titulo: "Gerar rollback?",
    mensagem: "Uma nova CR inversa (aguardando_aprovacao) será criada a partir do snapshot anterior à mudança.",
  },
};

export default function ChangeRequestDetail() {
  const { id } = useParams();
  const crId = Number(id);
  const navigate = useNavigate();
  const { usuario, podeEscrever } = useAuth();
  const { data: cr, isLoading, error } = useChangeRequest(crId);
  const { data: circuits } = useCircuits();
  const { data: devices } = useDevices();
  const enviar = useChangeRequestEnviar();
  const cancelar = useChangeRequestCancelar();
  const aprovar = useChangeRequestAprovar();
  const executar = useChangeRequestExecutar();
  const reconciliar = useChangeRequestReconciliar();
  const rollback = useChangeRequestRollback();
  const [dialogo, setDialogo] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  if (isLoading) return <p aria-busy="true">Carregando…</p>;
  if (!cr) {
    return (
      <main>
        <p role="alert">{error instanceof ApiError ? error.message : "Falha ao carregar a change request."}</p>
      </main>
    );
  }

  const ehAprovador = usuario !== null && (usuario.role === "aprovador" || usuario.role === "administrador");
  const ehExecutor = usuario !== null && (usuario.role === "executor" || usuario.role === "administrador");
  const ehSolicitante = cr.solicitante_id !== null && usuario !== null && cr.solicitante_id === usuario.id;
  const status = cr.status;
  const circuito = circuits?.find((c) => c.id === cr.circuit_id);

  const executarAcao = (fn: () => Promise<unknown>) => {
    setErro(null);
    fn().catch((err) => setErro(err instanceof ApiError ? err.message : "Falha ao executar a ação."));
  };

  const confirmarAcao = () => {
    if (dialogo === null) return;
    const acao =
      dialogo === "cancelar" ? () => cancelar.mutateAsync(cr.id)
      : dialogo === "rejeitar" ? () => aprovar.mutateAsync({ id: cr.id, decisao: "rejeitar" })
      : dialogo === "executar" ? () => executar.mutateAsync(cr.id)
      : dialogo === "reconciliar" ? () => reconciliar.mutateAsync(cr.id)
      : () => rollback.mutateAsync(cr.id).then((filho) => navigate(`/change-requests/${filho.id}`));
    setDialogo(null);
    executarAcao(acao);
  };

  const confirmando =
    cancelar.isPending || aprovar.isPending || executar.isPending || reconciliar.isPending || rollback.isPending;

  return (
    <main>
      <PageHeader
        titulo={`Change request #${cr.id}`}
        sub={`${ACAO_LABELS[cr.acao]} · ${cr.criticidade} · ${new Date(cr.created_at).toLocaleString("pt-BR")}`}
        acoes={
          <>
            <Link to="/change-requests">← Voltar</Link>
            {status === "rascunho" && podeEscrever && (
              <button type="button" disabled={enviar.isPending} onClick={() => executarAcao(() => enviar.mutateAsync(cr.id))}>
                Enviar para aprovação
              </button>
            )}
            {(status === "rascunho" || status === "aguardando_aprovacao") && podeEscrever && (
              <button type="button" onClick={() => setDialogo("cancelar")}>Cancelar</button>
            )}
            {status === "aguardando_aprovacao" && ehAprovador && !ehSolicitante && (
              <>
                <button className="primary" type="button" disabled={aprovar.isPending} onClick={() => executarAcao(() => aprovar.mutateAsync({ id: cr.id, decisao: "aprovar" }))}>
                  Aprovar
                </button>
                <button type="button" onClick={() => setDialogo("rejeitar")}>Rejeitar</button>
              </>
            )}
            {status === "aprovado" && ehExecutor && (
              <button className="primary" type="button" onClick={() => setDialogo("executar")}>Executar</button>
            )}
            {(status === "erro" || status === "parcial") && podeEscrever && cr.escopo === "circuito" && (
              <button type="button" onClick={() => setDialogo("reconciliar")}>Reconciliar</button>
            )}
            {(status === "aplicado" || status === "com_divergencia" || status === "parcial") && podeEscrever && cr.escopo === "circuito" && (
              <button type="button" onClick={() => setDialogo("rollback")}>Gerar rollback</button>
            )}
          </>
        }
      />
      {erro && <p role="alert">{erro}</p>}
      <table>
        <tbody>
          <tr><th>Status</th><td><StatusBadge estado={status} /></td></tr>
          <tr><th>Circuito</th><td>{circuito ? <Link to={`/circuits/${circuito.id}`}>{circuito.code}</Link> : rotuloObjeto(cr)}</td></tr>
          <tr><th>Solicitante</th><td>{cr.solicitante_id ?? "API/CLI"}</td></tr>
          <tr><th>Ticket</th><td>{cr.ticket ?? "—"}</td></tr>
          <tr><th>Rollback de</th><td>{cr.rollback_de ? <Link to={`/change-requests/${cr.rollback_de}`}>#{cr.rollback_de}</Link> : "—"}</td></tr>
          <tr><th>Motivo</th><td>{cr.motivo}</td></tr>
        </tbody>
      </table>

      <h2>Aprovações</h2>
      {cr.approvals.length === 0 && <p>Nenhuma aprovação registrada.</p>}
      {cr.approvals.length > 0 && (
        <table>
          <tbody>
            {cr.approvals.map((a) => (
              <tr key={a.id}>
                <td><StatusBadge estado={a.decisao} /></td>
                <td>por usuário #{a.user_id}</td>
                <td>{a.comentario ?? "—"}</td>
                <td>{new Date(a.created_at).toLocaleString("pt-BR")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Steps por equipamento</h2>
      {cr.steps.length === 0 && <p>Sem steps ainda — envie a CR para aprovação para gerar o plano.</p>}
      {cr.steps.map((step) => (
        <section key={step.id}>
          <h3>{devices?.find((d) => d.id === step.device_id)?.name ?? `Device #${step.device_id}`} <StatusBadge estado={step.status} /></h3>
          {step.aviso && <p role="alert">{step.aviso}</p>}
          {step.erro && <p role="alert">{step.erro}</p>}
          <p>
            Baseline: {step.baseline_snapshot_id ?? "—"} · Backup pré-mudança: {step.backup_snapshot_id ?? "—"}
            {step.finished_at && <> · Fim: {new Date(step.finished_at).toLocaleString("pt-BR")}</>}
          </p>
          {step.plano_json.length === 0 && <p>Nenhum comando planejado para o estado atual.</p>}
          {step.plano_json.map((bloco) => (
            <details key={`${bloco.tipo}-${bloco.objeto_id}-${bloco.comandos[0] ?? ""}`}>
              <summary>{bloco.acao} · {bloco.objeto} #{bloco.objeto_id}</summary>
              <pre>{bloco.comandos.join("\n")}</pre>
            </details>
          ))}
          {step.post_check_json && step.post_check_json.items.length > 0 && (
            <>
              <p>Pós-check (snapshot #{step.post_check_json.snapshot_id} — escopo do equipamento):</p>
              <ul>
                {step.post_check_json.items.map((item, idx) => (
                  <li key={idx}>
                    <StatusBadge estado={item.severidade} /> {item.esperado} — encontrado: {item.encontrado}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ))}

      {dialogo !== null && (
        <ConfirmDialog
          aberto
          titulo={CONFIRMACOES[dialogo].titulo}
          mensagem={CONFIRMACOES[dialogo].mensagem}
          onConfirmar={confirmarAcao}
          onCancelar={() => setDialogo(null)}
          confirmando={confirmando}
        />
      )}
    </main>
  );
}
