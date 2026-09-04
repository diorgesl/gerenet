"""Render da configuração desejada e divergência (somente leitura) — spec §8."""
import typer
from sqlalchemy.orm import Session

from gerenet.automation.reconcile import reconciliar_device
from gerenet.automation.render import render_desejado
from gerenet.db import get_session
from gerenet.domain.services import devices as dev_svc
from gerenet.domain.services.errors import GerenetError, NotFoundError


def _device(session: Session, device: str):
    """Device por ID ou nome; None se não existir."""
    if device.isdigit():
        try:
            return dev_svc.get_device(session, int(device))
        except NotFoundError:
            return None
    return next(
        (d for d in dev_svc.list_devices(session, include_disabled=True) if d.name == device),
        None,
    )


def _resolve(session: Session, device: str):
    encontrado = _device(session, device)
    if encontrado is None:
        typer.echo("Equipamento não encontrado.", err=True)
        raise typer.Exit(1)
    return encontrado


def render_config(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Mostra os blocos de configuração desejada do device."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = render_desejado(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    if not resultado.blocos:
        typer.echo(f"{encontrado.name}: nada a renderizar.")
        return
    for i, bloco in enumerate(resultado.blocos, start=1):
        typer.echo(f"# bloco {i}: {bloco.tipo} ({bloco.objeto} {bloco.objeto_id})")
        for linha in bloco.comandos:
            typer.echo(linha)


def reconcile(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Compara o desejado renderizado com o snapshot (divergência read-only)."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = reconciliar_device(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Equipamento {encontrado.name}:")
    if resultado.aviso:
        typer.echo(f"Aviso: {resultado.aviso}")
    if not resultado.items:
        typer.echo("Sem divergências.")
        return
    for item in resultado.items:
        typer.echo(
            f"[{item.severidade.upper()}] {item.tipo}: esperado {item.esperado} "
            f"| encontrado {item.encontrado} — {item.acao}"
        )
