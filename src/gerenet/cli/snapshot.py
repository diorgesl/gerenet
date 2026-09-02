import typer

from gerenet.db import get_session
from gerenet.domain.models import DeviceSnapshot

app = typer.Typer(help="Snapshots de coleta.")


@app.command("show")
def show(
    snapshot_id: int = typer.Argument(..., help="ID do snapshot."),
    recurso: str | None = typer.Option(None, "--resource", help="Mostra só um recurso."),
) -> None:
    """Exibe um snapshot (resumo ou um recurso específico)."""
    with get_session() as session:
        snap = session.get(DeviceSnapshot, snapshot_id)
        if snap is None:
            typer.echo("Snapshot não encontrado.", err=True)
            raise typer.Exit(1)
        if recurso:
            typer.echo(snap.resources.get(recurso))
            return
        typer.echo(f"#{snap.id} device={snap.device_id} status={snap.status} duração={snap.duration_ms}ms")
        typer.echo("Recursos: " + ", ".join(snap.resources.keys()))
        typer.echo("Brutos: " + ", ".join(str(p) for ps in snap.raw_files.values() for p in ps))
