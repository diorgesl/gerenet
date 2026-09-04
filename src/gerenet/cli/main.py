import typer

from gerenet.cli import (
    bgp_sessions,
    circuits,
    collect,
    communities,
    contacts,
    devices,
    hostkey,
    organizations,
    policy_profiles,
    prefix_authorizations,
    reconcile,
    sites,
    snapshot,
    vault,
)

app = typer.Typer(help="gerenet — Gerenciador de Rede Huawei VRP", no_args_is_help=True)
app.add_typer(devices.app, name="devices", help="Cadastro e consulta de equipamentos.")
app.add_typer(sites.app, name="sites", help="Sites/POPs.")
app.add_typer(organizations.app, name="organizations", help="Organizações.")
app.add_typer(contacts.app, name="contacts", help="Contatos de organizações.")
app.add_typer(circuits.app, name="circuits", help="Circuitos de acesso.")
app.add_typer(bgp_sessions.app, name="bgp-sessions", help="Sessões BGP.")
app.add_typer(prefix_authorizations.app, name="prefix-authorizations", help="Autorizações de prefixo.")
app.add_typer(policy_profiles.app, name="policy-profiles", help="Produtos de roteamento.")
app.add_typer(hostkey.app, name="hostkey", help="Host keys dos equipamentos.")
app.add_typer(vault.app, name="vault", help="Credenciais de automação no Vault.")
app.add_typer(collect.app, name="collect", help="Coleta read-only.")
app.add_typer(snapshot.app, name="snapshot", help="Snapshots de coleta.")
app.add_typer(communities.app, name="communities", help="Communities BGP.")
app.command(name="render-config")(reconcile.render_config)
app.command(name="reconcile")(reconcile.reconcile)
