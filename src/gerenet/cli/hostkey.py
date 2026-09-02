import typer

from gerenet.automation.hostkeys import normalize_fingerprint
from gerenet.cli.devices import resolver
from gerenet.db import get_session
from gerenet.domain.models import AuditEvent

app = typer.Typer(help="Host keys dos equipamentos.")


@app.command("register")
def register(
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
    fingerprint: str = typer.Argument(..., help="Fingerprint esperado (ex.: SHA256:abcd...)."),
) -> None:
    """Registra o fingerprint esperado (SHA-256) de um equipamento."""
    fp = normalize_fingerprint(fingerprint)
    with get_session() as session:
        dev = resolver(session, device)
        if dev is None:
            typer.echo("Equipamento não encontrado.", err=True)
            raise typer.Exit(1)
        dev.host_key_fingerprint = fp
        session.add(
            AuditEvent(
                type="hostkey.register",
                actor="cli",
                details={"device_id": dev.id, "fingerprint": fp},
            )
        )
    typer.echo(f"Host key registrada para {dev.name}.")
