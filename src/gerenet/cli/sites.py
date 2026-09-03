import typer

from gerenet.cli.devices import resolver as resolver_device
from gerenet.db import get_session
from gerenet.domain.schemas import SiteCreate
from gerenet.domain.services import sites as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Sites/POPs.")


def resolver(session, site: str):
    """Devolve o site (ativo ou não) por ID ou nome; None se não existir."""
    if site.isdigit():
        try:
            return svc.get_site(session, int(site))
        except NotFoundError:
            return None
    return next(
        (s for s in svc.list_sites(session, include_disabled=True) if s.name == site), None
    )


@app.command("add")
def add(
    name: str = typer.Option(..., help="Nome único do site/POP."),
    city: str | None = typer.Option(None, help="Cidade."),
    uf: str | None = typer.Option(None, help="UF (2 letras)."),
    p2p_ipv4_block: str | None = typer.Option(
        None, "--p2p-ipv4-block", help="Bloco p2p v4 do site (CIDR)."
    ),
    p2p_ipv6_base: str | None = typer.Option(
        None, "--p2p-ipv6-base", help="Base p2p v6 do site (CIDR)."
    ),
) -> None:
    """Cadastra um site/POP."""
    with get_session() as session:
        try:
            site = svc.create_site(
                session,
                SiteCreate(
                    name=name,
                    city=city,
                    uf=uf,
                    p2p_ipv4_block=p2p_ipv4_block,
                    p2p_ipv6_base=p2p_ipv6_base,
                ),
                actor="cli",
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Site {site.id} criado: {site.name}")


@app.command("list")
def listar(
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista sites/POPs."""
    with get_session() as session:
        for site in svc.list_sites(session, include_disabled=include_disabled):
            typer.echo(f"{site.id:>4}  {site.name:<24} {site.city or '-':<20} {site.uf or '-'}")


@app.command("disable")
def disable(site: str = typer.Argument(..., help="ID ou nome do site.")) -> None:
    """Desativa um site (mantém histórico e registro)."""
    with get_session() as session:
        encontrado = resolver(session, site)
        if encontrado is None:
            typer.echo("Site não encontrado.", err=True)
            raise typer.Exit(1)
        svc.disable_site(session, encontrado.id, actor="cli")
    typer.echo(f"Site {encontrado.name} desativado.")


@app.command("link-device")
def link_device(
    site: str = typer.Argument(..., help="ID ou nome do site."),
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
) -> None:
    """Vincula um equipamento ao site."""
    with get_session() as session:
        encontrado = resolver(session, site)
        if encontrado is None:
            typer.echo("Site não encontrado.", err=True)
            raise typer.Exit(1)
        dev = resolver_device(session, device)
        if dev is None:
            typer.echo("Equipamento não encontrado.", err=True)
            raise typer.Exit(1)
        svc.link_device(session, encontrado.id, dev.id, actor="cli")
    typer.echo(f"Equipamento {dev.name} vinculado ao site {encontrado.name}.")
