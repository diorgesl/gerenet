import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.services import policy_profiles as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Produtos de roteamento (catálogo somente leitura).")


@app.command("list")
def listar(
    direction: str | None = typer.Option(None, "--direction", help="Filtra por direção (export)."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista o catálogo de policy-profiles."""
    with get_session() as session:
        try:
            perfis = svc.list_policy_profiles(
                session, direction=direction, include_disabled=include_disabled
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        for perfil in perfis:
            typer.echo(f"{perfil.id:>3}  {perfil.name:<16} {perfil.direction:<7} {perfil.label}")
