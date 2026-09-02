import typer

from gerenet.cli import devices, hostkey, vault

app = typer.Typer(help="gerenet — Gerenciador de Rede Huawei VRP", no_args_is_help=True)
app.add_typer(devices.app, name="devices", help="Cadastro e consulta de equipamentos.")
app.add_typer(hostkey.app, name="hostkey", help="Host keys dos equipamentos.")
app.add_typer(vault.app, name="vault", help="Credenciais de automação no Vault.")
