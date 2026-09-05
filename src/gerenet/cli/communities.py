"""Communities (catálogo) — list desde o ciclo B; update no C3 (spec §S1.2)."""
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import CommunityUpdate
from gerenet.domain.services import communities as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Communities BGP (catálogo).")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista o catálogo de communities."""
    with get_session() as session:
        for com in svc.list_communities(session, include_disabled=include_disabled):
            typer.echo(f"{com.id:>3}  {com.name:<16} {com.notes or ''}")


@app.command("update")
def atualizar(
    community_id: int = typer.Argument(..., help="ID da community."),
    name: str | None = typer.Option(None, "--name", help="Novo nome."),
    notes: str | None = typer.Option(None, "--notes", help="Novas observações."),
) -> None:
    """Atualiza nome/observações de uma community (evento community.update)."""
    dados: dict = {}
    if name is not None:
        dados["name"] = name
    if notes is not None:
        dados["notes"] = notes
    with get_session() as session:
        try:
            com = svc.update_community(session, community_id, CommunityUpdate(**dados), actor="cli")
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Community {com.id} atualizada: {com.name} ({com.notes or 'sem observações'}).")
