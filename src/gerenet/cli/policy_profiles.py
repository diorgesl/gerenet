import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import PolicyProfileUpdate
from gerenet.domain.services import policy_profiles as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Produtos de roteamento (catálogo).")


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


@app.command("update")
def atualizar(
    profile_id: int = typer.Argument(..., help="ID do perfil."),
    name: str | None = typer.Option(None, "--name", help="Novo nome (slug EN)."),
    label: str | None = typer.Option(None, "--label", help="Novo rótulo PT-BR."),
    direction: str | None = typer.Option(None, "--direction", help="Direção: import|export."),
    kind: str | None = typer.Option(None, "--kind", help="Tipo (produto)."),
    prefixes: str | None = typer.Option(None, "--prefixes", help="Novos prefixos, separados por vírgula."),
    notes: str | None = typer.Option(None, "--notes", help="Novas observações."),
) -> None:
    """Atualiza campos de um produto de roteamento (evento policy_profile.update)."""
    dados: dict = {}
    if name is not None:
        dados["name"] = name
    if label is not None:
        dados["label"] = label
    if direction is not None:
        dados["direction"] = direction
    if kind is not None:
        dados["kind"] = kind
    if prefixes is not None:
        dados["prefixes"] = [p.strip() for p in prefixes.split(",") if p.strip()]
    if notes is not None:
        dados["notes"] = notes
    if not dados:
        typer.echo("Nenhum campo informado.", err=True)
        raise typer.Exit(1)
    with get_session() as session:
        try:
            perfil = svc.update_policy_profile(
                session, profile_id, PolicyProfileUpdate(**dados), actor="cli"
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Perfil {perfil.id} atualizado: {perfil.name} ({perfil.label}).")
