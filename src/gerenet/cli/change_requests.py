"""Change requests no CLI (spec ciclo D §8.1): cria, lista, envia, aprova, executa.

A CLI não tem identidade de usuário: ator_id fica None na CRIACÃO (auditoria
actor="cli"); como aprovar registra um Approval com FK para users.id, a
aprovação exige `--aprovador` (ID ou username de um usuário ativo) — o papel
de aprovador é garantido na API/web (T5), a CLI só exige que o aprovador
exista; `aprovador ≠ solicitante` não se aplica (solicitante é None no CLI).
"""
from typing import Literal

import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import ChangeRequestCreate
from gerenet.domain.services import change_requests as svc
from gerenet.domain.services import users as user_svc
from gerenet.domain.services.errors import GerenetError, NotFoundError
from gerenet.worker.tasks import enqueue_change

app = typer.Typer(help="Change requests (fluxo de mudança controlada).")


def _pelo_id(session, cr_id: int):
    """CR por ID com erro de CLI amigável; aborta com exit 1 se não existir."""
    try:
        return svc.get_change_request(session, cr_id)
    except NotFoundError as exc:
        typer.echo(f"Change request não encontrada: {cr_id}.", err=True)
        raise typer.Exit(1) from exc


def _resolver_aprovador(session, aprovador: str) -> int:
    """ID do usuário aprovador (por ID ou username de usuário ativo)."""
    alvo = next(
        (u for u in user_svc.list_users(session) if str(u.id) == aprovador or u.username == aprovador),
        None,
    )
    if alvo is None:
        typer.echo(f"Erro: Aprovador não encontrado: {aprovador} (usuário ativo).", err=True)
        raise typer.Exit(1)
    return alvo.id


@app.command("add")
def add(
    circuit_id: int = typer.Option(..., "--circuit-id", help="ID do circuito."),
    motivo: str = typer.Option(..., help="Motivo da mudança."),
    ticket: str | None = typer.Option(None, help="Ticket de referência."),
    acao: Literal["provision", "remove"] = typer.Option("provision", "--acao", help="provision ou remove."),
    criticidade: Literal["baixa", "media", "alta"] = typer.Option(
        "media", "--criticidade", help="baixa, media ou alta."
    ),
) -> None:
    """Cria uma change request (plano congelado; nasce rascunho)."""
    with get_session() as session:
        try:
            cr = svc.create_change_request(
                session,
                ChangeRequestCreate(
                    circuit_id=circuit_id, acao=acao, criticidade=criticidade,
                    motivo=motivo, ticket=ticket,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        # steps contados dentro da sessão (lazy): após o close, viraria
        # DetachedInstanceError no eco final.
        n_steps = len(cr.steps)
        n_blocos = sum(len(s.plano_json) for s in cr.steps)
    typer.echo(
        f"CR #{cr.id} criada (rascunho): {n_steps} step(s), {n_blocos} bloco(s)."
    )


@app.command("list")
def listar(
    status: str | None = typer.Option(None, "--status", help="Filtra por status."),
    circuit_id: int | None = typer.Option(None, "--circuit-id", help="Filtra por circuito."),
) -> None:
    """Lista change requests (mais recentes primeiro)."""
    with get_session() as session:
        for cr in svc.list_change_requests(session, status=status, circuit_id=circuit_id):
            typer.echo(
                f"CR #{cr.id}  {cr.acao:<9} {cr.status:<18} "
                f"circuito {cr.circuit_id:>4}  {cr.criticidade:<5}  {cr.motivo[:48]}"
            )


@app.command("show")
def show(cr_id: int = typer.Argument(..., help="ID da CR.")) -> None:
    """Mostra uma CR: status, steps e primeiro comando de cada bloco."""
    with get_session() as session:
        cr = _pelo_id(session, cr_id)
        typer.echo(f"CR #{cr.id}: {cr.acao} — {cr.status} (criticidade {cr.criticidade})")
        typer.echo(f"Motivo: {cr.motivo}")
        if cr.ticket:
            typer.echo(f"Ticket: {cr.ticket}")
        for step in cr.steps:
            typer.echo(
                f"  step {step.id} — device {step.device_id}: {step.status} "
                f"({len(step.plano_json)} bloco(s))"
            )
            for bloco in step.plano_json:
                primeiro = bloco["comandos"][0] if bloco["comandos"] else "(sem comandos)"
                typer.echo(f"    {bloco['tipo']} {bloco['acao']} #{bloco['objeto_id']}: {primeiro}")


@app.command("send")
def enviar(cr_id: int = typer.Argument(..., help="ID da CR.")) -> None:
    """Envia para aprovação (rascunho → aguardando_aprovacao)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            cr = svc.enviar_para_aprovacao(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} enviada para aprovação.")


@app.command("approve")
def aprovar(
    cr_id: int = typer.Argument(..., help="ID da CR."),
    aprovador: str = typer.Option(
        ..., "--aprovador", help="Usuário aprovador (ID ou username de usuário ativo)."
    ),
    decisao: Literal["aprovar", "rejeitar"] = typer.Option(
        "aprovar", "--decisao", help="aprovar ou rejeitar."
    ),
    comentario: str | None = typer.Option(None, "--comentario", help="Comentário do aprovador."),
) -> None:
    """Registra a decisão de aprovação (única por CR)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        ator_id = _resolver_aprovador(session, aprovador)
        try:
            cr = svc.aprovar(
                session, cr_id, ator_id=ator_id, actor="cli",
                decisao=decisao, comentario=comentario,
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} agora está {cr.status}.")


@app.command("cancel")
def cancelar(cr_id: int = typer.Argument(..., help="ID da CR.")) -> None:
    """Cancela a CR (de rascunho ou aguardando_aprovacao)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            cr = svc.cancelar(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} cancelada.")


@app.command("execute")
def executar(cr_id: int = typer.Argument(..., help="ID da CR aprovada.")) -> None:
    """Enfileira a execução aprovada (fila gerenet-change) e marca executando.

    Ordem espelho do endpoint API: o enqueue valida (aprovado, sem lock/job
    pendente) ANTES da transição; enfileirado ⇒ marcar_executando; se o
    enqueue recusar, a mensagem dele vira erro sem tocar no status.
    """
    with get_session() as session:
        _pelo_id(session, cr_id)
        enfileirado = enqueue_change(cr_id, actor="cli", origin="cli")
        if not enfileirado["queued"]:
            typer.echo(f"Erro: {enfileirado['message']}", err=True)
            raise typer.Exit(1)
        try:
            svc.marcar_executando(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr_id} enfileirada ({enfileirado['job_id']}) — status executando.")


@app.command("rollback")
def rollback(cr_id: int = typer.Argument(..., help="ID da CR aplicada.")) -> None:
    """Gera a CR inversa (aguardando_aprovacao) a partir do baseline (§7)."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            filho = svc.gerar_rollback(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{filho.id} de rollback criada ({filho.status}) a partir do CR #{cr_id}.")


@app.command("reconcile")
def reconciliar(cr_id: int = typer.Argument(..., help="ID da CR em erro/parcial.")) -> None:
    """Replaneja steps não aplicados e devolve a CR à aprovação."""
    with get_session() as session:
        _pelo_id(session, cr_id)
        try:
            cr = svc.reconciliar(session, cr_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"CR #{cr.id} reconciliada — {cr.status}.")
