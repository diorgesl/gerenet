"""Communities (catálogo) — list desde o ciclo B; update no C3 (spec §S1.2)."""
import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.cli.community_plan import app as plan_app
from gerenet.db import get_session
from gerenet.domain.schemas import CommunityUpdate
from gerenet.domain.services import communities as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Communities BGP (catálogo).")
app.add_typer(plan_app, name="plan", help="Plano de communities.")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista o catálogo de communities (valor e banda vêm do plano central)."""
    with get_session() as session:
        communities = svc.list_communities(session, include_disabled=include_disabled)
        # A largura das colunas sai do próprio catálogo: um nome novo mais longo
        # que o número mágico de antes (`com-CLIENTES_PARCEIROS-CDN`) empurrava as
        # colunas da linha dele e só dela.
        largura_nome = max((len(com.name) for com in communities), default=0)
        largura_banda = max((len(com.banda or "—") for com in communities), default=0)
        for com in communities:
            v4 = com.valor_v4 if com.valor_v4 is not None else "—"
            v6 = com.valor_v6 if com.valor_v6 is not None else "—"
            typer.echo(
                f"{com.id:>3}  {com.name:<{largura_nome}} v4={v4} v6={v6} "
                f"{com.banda or '—':<{largura_banda}} {com.notes or ''}"
            )


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
    if not dados:
        typer.echo("Nenhum campo informado.", err=True)
        raise typer.Exit(1)
    with get_session() as session:
        try:
            com = svc.update_community(session, community_id, CommunityUpdate(**dados), actor="cli")
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Community {com.id} atualizada: {com.name} ({com.notes or 'sem observações'}).")
