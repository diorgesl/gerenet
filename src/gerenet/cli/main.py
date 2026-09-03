import typer

from gerenet.cli import collect, devices, hostkey, sites, snapshot, vault

app = typer.Typer(help="gerenet — Gerenciador de Rede Huawei VRP", no_args_is_help=True)
app.add_typer(devices.app, name="devices", help="Cadastro e consulta de equipamentos.")
app.add_typer(sites.app, name="sites", help="Sites/POPs.")
app.add_typer(hostkey.app, name="hostkey", help="Host keys dos equipamentos.")
app.add_typer(vault.app, name="vault", help="Credenciais de automação no Vault.")
app.add_typer(collect.app, name="collect", help="Coleta read-only.")
app.add_typer(snapshot.app, name="snapshot", help="Snapshots de coleta.")
