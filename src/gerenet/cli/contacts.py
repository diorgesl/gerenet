import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import ContactCreate
from gerenet.domain.services import contacts as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Contatos de organizações.")


@app.command("add")
def add(
    organization_id: int = typer.Option(..., "--organization-id", help="ID da organização."),
    name: str = typer.Option(..., help="Nome do contato."),
    email: str | None = typer.Option(None, help="E-mail."),
    phone: str | None = typer.Option(None, help="Telefone."),
    kind: str = typer.Option("tecnico", help="Tipo: tecnico, noc ou admin."),
) -> None:
    """Cadastra um contato."""
    with get_session() as session:
        try:
            contato = svc.create_contact(
                session,
                ContactCreate(
                    organization_id=organization_id,
                    name=name,
                    email=email,
                    phone=phone,
                    kind=kind,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Contato {contato.id} criado: {contato.name}")


@app.command("list")
def listar(
    organization_id: int | None = typer.Option(
        None, "--organization-id", help="Filtra por organização."
    ),
) -> None:
    """Lista contatos ativos (sem --all: o serviço esconde desativados)."""
    with get_session() as session:
        for contato in svc.list_contacts(session, organization_id=organization_id):
            typer.echo(
                f"{contato.id:>4}  {contato.name:<28} {contato.kind:<8} "
                f"{contato.email or '-':<32} {contato.phone or '-'}"
            )


@app.command("disable")
def disable(contact_id: int = typer.Argument(..., help="ID do contato.")) -> None:
    """Desativa um contato (mantém histórico e registro)."""
    with get_session() as session:
        try:
            svc.disable_contact(session, contact_id, actor="cli")
        except NotFoundError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Contato {contact_id} desativado.")
