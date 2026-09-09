import typer

from gerenet.db import get_session
from gerenet.domain.services import credential_groups as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Grupos de credencial (SoT).")


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Nome do grupo (ex.: automacao)."),
    vault_path: str = typer.Option(
        ...,
        "--vault-path",
        help="Caminho lógico no Vault (ex.: gerenet/credential-groups/automacao).",
    ),
    kind: str = typer.Option("tacacs_password", "--kind", help="Tipo de credencial."),
) -> None:
    """Registra um grupo no banco (o segredo em si vai ao Vault via `vault seed`/API)."""
    with get_session() as session:
        try:
            grupo = svc.create_credential_group(
                session, name=name, vault_path=vault_path, kind=kind, actor="cli"
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Grupo SoT criado: {grupo.name} → {grupo.vault_path}")


@app.command("list")
def listar(include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados.")) -> None:
    """Lista grupos de credencial registrados."""
    with get_session() as session:
        for grupo in svc.list_credential_groups(session, include_disabled=include_disabled):
            typer.echo(f"#{grupo.id:<3} {grupo.name:<24} {grupo.kind:<20} {grupo.vault_path}")
