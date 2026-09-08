"""CLI de RPKI/IRR — sincronização de ROAs e consulta IRR (§7.5, F5/E4).

`gerenet rpki sync` espelha o lote JSON do rpki-client (`{"roas": [...]}`)
na tabela `roas` — idempotente, com remoção de órfãs — e, como efeito
colateral do `sincronizar_roas`, revalida consultivamente (§10.4) as
autorizações ativas de origem IRR/RPKI. `gerenet irr query` resolve um ASN
ou AS-SET para ASNs/prefixos com cache (`irr_cache`), apoiando a aprovação
humana da autorização (§6.4).

Por ora síncrono: enfileirar a sincronização em job fica para a fase 6 (§22).
"""
import typer

from gerenet.automation.irr import IrrError, consultar
from gerenet.automation.rpki import sincronizar_roas
from gerenet.config import get_settings
from gerenet.db import get_session
from gerenet.domain.services.errors import GerenetError

app = typer.Typer(
    help="Sincronização de ROAs (RPKI) e consulta IRR (§7.5)."
)


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


@app.command("query")
def query(
    key: str = typer.Argument(
        ..., help="ASN (ex.: 64512) ou AS-SET (ex.: AS-CLIENTE)."
    ),
    source: str = typer.Option(
        "radb", "--source", help="Fonte IRR: radb, altdb ou lacnic."
    ),
    ttl_horas: int = typer.Option(
        24, "--ttl-horas", help="TTL do cache em horas (default 24)."
    ),
) -> None:
    """Resolve um ASN/AS-SET no IRR — ASNs e prefixos com cache.

    Saída humano-legível (PT-BR): uma linha com os ASNs encontrados (ou
    "(nenhum)") e cada prefixo em linha própria (ou "(nenhum)"). A rede é
    consultada só quando o cache venceu.
    """
    try:
        resultado = consultar(source, key, ttl_horas=ttl_horas)
    except IrrError as exc:
        typer.echo(f"Erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    asns = ", ".join(f"AS{asn}" for asn in resultado["asns"]) or "(nenhum)"
    typer.echo(f"ASNs: {asns}")
    if resultado["prefixos"]:
        typer.echo("Prefixos:")
        for prefixo in resultado["prefixos"]:
            typer.echo(f"  {prefixo}")
    else:
        typer.echo("Prefixos: (nenhum)")
