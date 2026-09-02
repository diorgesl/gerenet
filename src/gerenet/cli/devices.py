import typer

from gerenet.db import get_session
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services import devices as svc
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Cadastro e consulta de equipamentos.")


def resolver(session, device: str):
    """Devolve o equipamento (ativo ou não) por ID ou nome; None se não existir.

    Helper compartilhado dos sub-comandos que recebem '<id|nome>'
    (devices disable, hostkey register, collect run).
    """
    if device.isdigit():
        try:
            return svc.get_device(session, int(device))
        except NotFoundError:
            return None
    return next((d for d in svc.list_devices(session, include_disabled=True) if d.name == device), None)


@app.command("add")
def add(
    name: str = typer.Option(..., help="Nome único do equipamento."),
    address: str = typer.Option(..., "--address", help="Endereço de gerenciamento."),
    ssh_port: int | None = typer.Option(None, "--ssh-port", min=1, max=65535, help="Porta SSH (default: 22)."),
    model: str | None = typer.Option(None, help="Modelo (ex.: NE8000-M8)."),
    family: str | None = typer.Option(None, help="Família (ex.: ne8000)."),
    role: str | None = typer.Option(None, help="Função (ex.: borda)."),
    site_id: int | None = typer.Option(None, "--site-id", help="ID do site/POP."),
    asn: int | None = typer.Option(None, "--asn", min=1, max=4294967295, help="ASN local do roteador."),
) -> None:
    """Cadastra um equipamento Huawei."""
    with get_session() as session:
        try:
            dev = svc.create_device(
                session,
                DeviceCreate(
                    name=name,
                    management_address=address,
                    ssh_port=ssh_port,
                    model=model,
                    family=family,
                    role=role,
                    site_id=site_id,
                    asn=asn,
                ),
                actor="cli",
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Equipamento {dev.id} criado: {dev.name} ({dev.management_address})")


@app.command("list")
def listar(include_disabled: bool = typer.Option(False, "--all", help="Inclui desativados.")) -> None:
    """Lista equipamentos cadastrados."""
    with get_session() as session:
        for dev in svc.list_devices(session, include_disabled=include_disabled):
            linha = f"{dev.id:>4}  {dev.name:<20} {dev.management_address:<16} {dev.comm_status}"
            typer.echo(linha)


@app.command("disable")
def disable(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Desativa um equipamento (mantém histórico e registro)."""
    with get_session() as session:
        dev = resolver(session, device)
        if dev is None:
            typer.echo("Equipamento não encontrado.", err=True)
            raise typer.Exit(1)
        svc.disable_device(session, dev.id, actor="cli")
    typer.echo(f"Equipamento {dev.name} desativado.")
