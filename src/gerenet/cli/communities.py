"""Communities (catálogo somente leitura) — spec ciclo B §8."""
import typer

from gerenet.db import get_session
from gerenet.domain.services import communities as svc

app = typer.Typer(help="Communities BGP (catálogo somente leitura).")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista o catálogo de communities."""
    with get_session() as session:
        for com in svc.list_communities(session, include_disabled=include_disabled):
            typer.echo(f"{com.id:>3}  {com.name:<16} {com.notes or ''}")
