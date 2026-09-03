import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import OrganizationCreate
from gerenet.domain.services import organizations as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Organizações (downstreams e parceiros).")


def resolver(session, organization: str):
    """Devolve a organização (ativa ou não) por ID ou nome; None se não existir."""
    if organization.isdigit():
        try:
            return svc.get_organization(session, int(organization))
        except NotFoundError:
            return None
    todas = svc.list_organizations(session, include_disabled=True)
    return next((o for o in todas if o.name == organization), None)


@app.command("add")
def add(
    name: str = typer.Option(..., help="Nome único da organização."),
    legal_name: str | None = typer.Option(None, "--legal-name", help="Razão social."),
    kind: str = typer.Option(
        "downstream", help="Tipo: downstream ou parceiro."
    ),
    asn: int | None = typer.Option(None, min=1, max=4294967295, help="ASN da organização."),
    irr_as_set: str | None = typer.Option(None, "--irr-as-set", help="IRR AS-SET."),
    notes: str | None = typer.Option(None, help="Observações."),
) -> None:
    """Cadastra uma organização."""
    with get_session() as session:
        try:
            org = svc.create_organization(
                session,
                OrganizationCreate(
                    name=name, legal_name=legal_name, kind=kind,
                    asn=asn, irr_as_set=irr_as_set, notes=notes,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Organização {org.id} criada: {org.name} ({org.kind})")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativadas."),
) -> None:
    """Lista organizações."""
    with get_session() as session:
        for org in svc.list_organizations(session, include_disabled=include_disabled):
            asn = str(org.asn) if org.asn is not None else "-"
            typer.echo(f"{org.id:>4}  {org.name:<28} {asn:<10} {org.kind}")


@app.command("disable")
def disable(organization: str = typer.Argument(..., help="ID ou nome da organização.")) -> None:
    """Desativa uma organização (mantém histórico e registro)."""
    with get_session() as session:
        encontrada = resolver(session, organization)
        if encontrada is None:
            typer.echo("Organização não encontrada.", err=True)
            raise typer.Exit(1)
        svc.disable_organization(session, encontrada.id, actor="cli")
    typer.echo(f"Organização {encontrada.name} desativada.")
