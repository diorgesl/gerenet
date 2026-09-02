import typer

from gerenet.cli.devices import resolver
from gerenet.db import get_session
from gerenet.domain.services import devices as svc
from gerenet.worker.tasks import enqueue_collect

app = typer.Typer(help="Coleta read-only.")


@app.command("run")
def run(
    device: str | None = typer.Option(None, "--device", help="ID ou nome do equipamento."),
    todos: bool = typer.Option(False, "--all", help="Enfileira coleta de todos os equipamentos ativos."),
) -> None:
    """Dispara coleta read-only via fila (1 job por equipamento)."""
    with get_session() as session:
        if todos:
            alvos = svc.list_devices(session)
            if not alvos:
                typer.echo("Nenhum equipamento ativo cadastrado.")
                raise typer.Exit(1)
        else:
            if device is None:
                typer.echo("Informe --device <id|nome> ou --all.", err=True)
                raise typer.Exit(2)
            alvo = resolver(session, device)
            alvos = [] if alvo is None else [alvo]
            if not alvos:
                typer.echo("Equipamento não encontrado.", err=True)
                raise typer.Exit(1)
        for dev in alvos:
            if not dev.admin_status:
                typer.echo(f"{dev.name}: desativado — reative antes de coletar.")
                continue
            resultado = enqueue_collect(dev.id, actor="cli", origin="cli")
            typer.echo(f"{dev.name}: {resultado['message']}")
