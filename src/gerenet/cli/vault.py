import typer

from gerenet.config import get_settings
from gerenet.secrets.vault_store import VaultSecretStore

app = typer.Typer(help="Credenciais de automação no Vault.")


@app.command("seed")
def seed(
    username: str = typer.Option("gerenet-auto", help="Usuário da conta de automação."),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Senha da conta de automação."),
) -> None:
    """Grava a credencial do grupo 'automacao' no Vault (dev)."""
    s = get_settings()
    VaultSecretStore(s.vault_url, s.vault_token).seed_dev(username, password)
    typer.echo("Credencial gravada em gerenet/credential-groups/automacao.")
