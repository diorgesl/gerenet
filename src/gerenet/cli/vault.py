import typer

from gerenet.config import get_settings
from gerenet.db import get_session
from gerenet.domain.services import credential_groups as svc
from gerenet.secrets.vault_store import VaultSecretStore

app = typer.Typer(help="Credenciais de automação no Vault.")


@app.command("seed")
def seed(
    username: str = typer.Option("gerenet-auto", help="Usuário da conta de automação."),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Senha da conta de automação."),
) -> None:
    """Grava a credencial do grupo 'automacao' no Vault (dev) e o registra no SoT.

    O grupo SoT é o que os devices referenciam: sem ele, a coleta não sabe de
    que caminho do Vault tirar a credencial. Idempotente (re-seed apenas grava).
    """
    s = get_settings()
    VaultSecretStore(s.vault_url, s.vault_token).seed_dev(username, password)
    with get_session() as session:
        svc.get_or_create_credential_group(
            session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
        )
    typer.echo("Credencial gravada em gerenet/credential-groups/automacao.")
    typer.echo("Grupo SoT 'automacao' garantido (criado ou já existente).")
