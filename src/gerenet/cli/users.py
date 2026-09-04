import typer

from gerenet.db import get_session
from gerenet.domain.services import users as svc
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Usuários e perfis do gerenet (§17).")


def _confere_senhas(senha1: str, senha2: str) -> str:
    if senha1 != senha2:
        typer.echo("Erro: As senhas não conferem.", err=True)
        raise typer.Exit(1)
    return senha1


@app.command("create")
def create(
    username: str = typer.Argument(..., help="Nome de usuário (case-sensitive)."),
    role: str = typer.Option(..., "--role", help="Perfil: visualizador/operador/aprovador/executor/administrador."),
) -> None:
    """Cria um usuário (senha por prompt oculto; nunca em argv)."""
    senha = typer.prompt("Senha", hide_input=True)
    confirmacao = typer.prompt("Confirme a senha", hide_input=True)
    senha = _confere_senhas(senha, confirmacao)
    with get_session() as session:
        try:
            usuario = svc.create_user(
                session, username=username, password=senha, role=role, actor="cli"
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Usuário {usuario.username} criado (id {usuario.id}, perfil {usuario.role}).")


@app.command("set-password")
def set_password(username: str = typer.Argument(..., help="Nome de usuário.")) -> None:
    """Redefine a senha de um usuário (invalida as sessões dele)."""
    senha = typer.prompt("Nova senha", hide_input=True)
    confirmacao = typer.prompt("Confirme", hide_input=True)
    senha = _confere_senhas(senha, confirmacao)
    with get_session() as session:
        target = next((u for u in svc.list_users(session, include_disabled=True) if u.username == username), None)
        if target is None:
            typer.echo("Usuário não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            svc.reset_password(session, target.id, password=senha, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Senha de {username} redefinida (sessões antigas invalidadas).")


@app.command("list")
def listar(include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados.")) -> None:
    """Lista usuários."""
    with get_session() as session:
        for u in svc.list_users(session, include_disabled=include_disabled):
            estado = "ativo" if u.is_active else "desativado"
            typer.echo(f"{u.id:>4}  {u.username:<16} {u.role:<14} {estado}")
