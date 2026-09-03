import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import PrefixAuthorizationCreate
from gerenet.domain.services import prefix_authorizations as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Prefixos autorizados por organização (origem manual).")


@app.command("add")
def add(
    organization_id: int = typer.Option(..., "--organization-id", help="ID da organização."),
    family: str = typer.Option(..., help="ipv4 ou ipv6."),
    prefix: str = typer.Option(..., help="CIDR alinhado (ex.: 203.0.113.0/24)."),
    notes: str | None = typer.Option(None, help="Observações."),
) -> None:
    """Autoriza um prefixo para um downstream."""
    with get_session() as session:
        try:
            auth = svc.create_authorization(
                session,
                PrefixAuthorizationCreate(
                    organization_id=organization_id, family=family, prefix=prefix, notes=notes
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Autorização {auth.id} criada: {auth.family} {auth.prefix}")


@app.command("list")
def listar(
    organization_id: int | None = typer.Option(None, "--organization-id", help="Filtra por organização."),
    family: str | None = typer.Option(None, help="Filtra por família (ipv4/ipv6)."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista autorizações de prefixo."""
    with get_session() as session:
        try:
            autorizacoes = svc.list_authorizations(
                session,
                organization_id=organization_id,
                family=family,
                include_disabled=include_disabled,
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        for auth in autorizacoes:
            typer.echo(f"{auth.id:>4}  {auth.family:<4} {auth.prefix:<20} org {auth.organization_id}")


@app.command("disable")
def disable(authorization_id: int = typer.Argument(..., help="ID da autorização.")) -> None:
    """Desativa uma autorização (sem excluir). Mudar prefixo = desativar + criar."""
    with get_session() as session:
        try:
            svc.disable_authorization(session, authorization_id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Autorização de prefixo {authorization_id} desativada.")
