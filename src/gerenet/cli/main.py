import typer

from gerenet.cli import vault

app = typer.Typer(help="gerenet — Gerenciador de Rede Huawei VRP", no_args_is_help=True)
app.add_typer(vault.app, name="vault", help="Credenciais de automação no Vault.")
