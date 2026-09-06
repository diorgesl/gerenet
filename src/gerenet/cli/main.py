import typer

from gerenet.cli import (
    bgp_sessions,
    change_requests,
    circuits,
    collect,
    communities,
    contacts,
    credential_groups,
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
from gerenet.cli import users as cli_users

app = typer.Typer(help="gerenet — Gerenciador de Rede Huawei VRP", no_args_is_help=True)
app.add_typer(devices.app, name="devices", help="Cadastro e consulta de equipamentos.")
app.add_typer(sites.app, name="sites", help="Sites/POPs.")
app.add_typer(organizations.app, name="organizations", help="Organizações.")
app.add_typer(contacts.app, name="contacts", help="Contatos de organizações.")
app.add_typer(circuits.app, name="circuits", help="Circuitos de acesso.")
app.add_typer(bgp_sessions.app, name="bgp-sessions", help="Sessões BGP.")
app.add_typer(change_requests.app, name="change-requests", help="Change requests (fluxo de mudança).")
app.add_typer(prefix_authorizations.app, name="prefix-authorizations", help="Autorizações de prefixo.")
app.add_typer(policy_profiles.app, name="policy-profiles", help="Produtos de roteamento.")
app.add_typer(hostkey.app, name="hostkey", help="Host keys dos equipamentos.")
app.add_typer(vault.app, name="vault", help="Credenciais de automação no Vault.")
app.add_typer(credential_groups.app, name="credential-groups", help="Grupos de credencial (SoT).")
app.add_typer(collect.app, name="collect", help="Coleta read-only.")
app.add_typer(snapshot.app, name="snapshot", help="Snapshots de coleta.")
app.add_typer(communities.app, name="communities", help="Communities BGP.")
app.command(name="render-config")(reconcile.render_config)
app.command(name="reconcile")(reconcile.reconcile)
app.add_typer(cli_users.app, name="users", help="Usuários e perfis.")
