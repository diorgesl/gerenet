"""CLI de sincronização de ROAs (RPKI) — espelho do lote do rpki-client (§7.5, F5/E4).

`gerenet rpki sync` espelha o lote JSON do rpki-client (`{"roas": [...]}`)
na tabela `roas` — idempotente, com remoção de órfãs — e, como efeito
colateral do `sincronizar_roas`, revalida consultivamente (§10.4) as
autorizações ativas de origem IRR/RPKI. A consulta IRR é comando do grupo
`gerenet irr query` (`gerenet.cli.irr`) — convenção do plano (T24).

Por ora síncrono: enfileirar a sincronização em job fica para a fase 6 (§22).
"""
import typer

from gerenet.automation.rpki import sincronizar_roas
from gerenet.config import get_settings
from gerenet.db import get_session
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(help="Sincronização de ROAs do rpki-client (§7.5).")


@app.command("sync")
def sync(
    file: str | None = typer.Option(
        None,
        "--file",
        help=(
            "Arquivo JSON do rpki-client com os ROAs "
            "(default: GERENET_RPKI_ROAS_FILE da configuração)."
        ),
    ),
) -> None:
    """Sincroniza as ROAs do rpki-client e revalida autorizações irr/rpki.

    Arquivo no formato `{"roas": [...]}` (rpki-client -j). Sem `--file`,
    usa `rpki_roas_file` da configuração; sem nenhum dos dois ⇒ erro.
    Ao final roda automaticamente a revalidação consultiva (§10.4) das
    autorizações de origem IRR/RPKI (efeito colateral do sync).
    """
    caminho = file or get_settings().rpki_roas_file
    if not caminho:
        typer.echo(
            "Erro: caminho do arquivo de ROAs ausente "
            "(use --file ou configure GERENET_RPKI_ROAS_FILE).",
            err=True,
        )
        raise typer.Exit(1)
    with get_session() as session:
        try:
            total = sincronizar_roas(session, caminho)
        except (ValueError, TypeError, GerenetError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"ROAs sincronizadas: {total}")
    typer.echo(
        "Revalidação automática das autorizações irr/rpki executada em "
        "seguida (§10.4)."
    )
