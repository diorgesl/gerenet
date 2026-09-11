import typer
from pydantic import ValidationError as SchemaValidationError

from gerenet.db import get_session
from gerenet.domain.schemas import CircuitCreate
from gerenet.domain.services import circuits as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError
from gerenet.domain.services.ipam import liberar_circuito, reservar_circuito

app = typer.Typer(help="Circuitos de acesso de downstreams.")


def resolver(session, circuito: str):
    """Devolve o circuito (ativo ou não) por ID ou código; None se não existir."""
    if circuito.isdigit():
        try:
            return svc.get_circuit(session, int(circuito))
        except NotFoundError:
            return None
    return next(
        (c for c in svc.list_circuits(session, include_disabled=True) if c.code == circuito),
        None,
    )


@app.command("add")
def add(
    code: str = typer.Option(..., help="Código único do circuito."),
    organization_id: int = typer.Option(..., "--organization-id", help="ID da organização."),
    site_id: int = typer.Option(..., "--site-id", help="ID do site/POP."),
    access_device_id: int = typer.Option(..., "--access-device-id", help="ID do switch de acesso."),
    access_port: str = typer.Option(..., "--access-port", help="Porta de acesso (ex.: GE0/0/1)."),
    edge_device_id: int = typer.Option(..., "--edge-device-id", help="ID do edge (NE8000)."),
    backup_edge_device_id: int | None = typer.Option(
        None, "--backup-edge-device-id", help="ID do edge de contingência."
    ),
    edge_trunk: str | None = typer.Option(
        None, "--edge-trunk", help="Trunk do edge que carrega as subinterfaces (ex.: Eth-Trunk127)."
    ),
    stack: str = typer.Option("dual", help="ipv4, ipv6 ou dual."),
    vlan_mode: str = typer.Option("unica", "--vlan-mode", help="unica ou separada."),
    qinq: bool = typer.Option(False, "--qinq", help="Habilita QinQ."),
    vrf: str | None = typer.Option(None, help="VRF (default: instância pública)."),
    mtu: int | None = typer.Option(None, min=576, max=9600, help="MTU."),
    bandwidth: str | None = typer.Option(None, help="Banda (ex.: 1Gbps)."),
    bfd: bool = typer.Option(False, "--bfd", help="Habilita BFD."),
    p2p_v4_len: int = typer.Option(
        31, "--p2p-v4-len", min=30, max=31, help="Máscara p2p v4 (30 ou 31)."
    ),
    description: str | None = typer.Option(None, help="Descrição."),
) -> None:
    """Cadastra um circuito de acesso."""
    with get_session() as session:
        try:
            circ = svc.create_circuit(
                session,
                CircuitCreate(
                    code=code,
                    organization_id=organization_id,
                    site_id=site_id,
                    access_device_id=access_device_id,
                    access_port=access_port,
                    edge_device_id=edge_device_id,
                    backup_edge_device_id=backup_edge_device_id,
                    edge_trunk=edge_trunk,
                    stack=stack,
                    vlan_mode=vlan_mode,
                    qinq=qinq,
                    vrf=vrf,
                    mtu=mtu,
                    bandwidth=bandwidth,
                    bfd=bfd,
                    p2p_v4_len=p2p_v4_len,
                    description=description,
                ),
                actor="cli",
            )
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {circ.id} criado: {circ.code}")


@app.command("list")
def listar(
    organization_id: int | None = typer.Option(None, "--organization-id", help="Filtra por organização."),
    site_id: int | None = typer.Option(None, "--site-id", help="Filtra por site."),
    include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados."),
) -> None:
    """Lista circuitos."""
    with get_session() as session:
        for circ in svc.list_circuits(
            session, organization_id=organization_id, site_id=site_id,
            include_disabled=include_disabled,
        ):
            vrf = circ.vrf or "-"
            typer.echo(
                f"{circ.id:>4}  {circ.code:<14} org {circ.organization_id:>4} "
                f"site {circ.site_id:>3} stack {circ.stack:<5} vrf {vrf}"
            )


@app.command("reserve")
def reserve(circuito: str = typer.Argument(..., help="ID ou código do circuito.")) -> None:
    """Reserva VLAN e enlaces p2p do circuito (idempotente)."""
    with get_session() as session:
        encontrado = resolver(session, circuito)
        if encontrado is None:
            typer.echo("Circuito não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            reservar_circuito(session, encontrado.id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {encontrado.code} reservado (idempotente).")


@app.command("unreserve")
def unreserve(circuito: str = typer.Argument(..., help="ID ou código do circuito.")) -> None:
    """Libera VLAN e enlaces p2p do circuito (idempotente; linhas ficam liberadas)."""
    with get_session() as session:
        encontrado = resolver(session, circuito)
        if encontrado is None:
            typer.echo("Circuito não encontrado.", err=True)
            raise typer.Exit(1)
        try:
            liberar_circuito(session, encontrado.id, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {encontrado.code} liberado (idempotente).")


@app.command("disable")
def disable(circuito: str = typer.Argument(..., help="ID ou código do circuito.")) -> None:
    """Desativa um circuito (mantém histórico e registro)."""
    with get_session() as session:
        encontrado = resolver(session, circuito)
        if encontrado is None:
            typer.echo("Circuito não encontrado.", err=True)
            raise typer.Exit(1)
        svc.disable_circuit(session, encontrado.id, actor="cli")
    typer.echo(f"Circuito {encontrado.code} desativado.")
