"""CLI de consulta IRR — ASN/AS-SET para ASNs e prefixos (§7.5, F5/E4).

`gerenet irr query` resolve um ASN ou AS-SET com cache (`irr_cache`, TTL
padrão de 24h e configurável com `--ttl-horas`), apoiando a aprovação
humana da autorização de prefixo (§6.4). A sincronização de ROAs fica no
grupo `gerenet rpki sync` (`gerenet.cli.rpki`).
"""
import typer

from gerenet.automation.irr import IrrError, consultar

app = typer.Typer(help="Consultas IRR (ASN/AS-SET) com cache (§7.5).")


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
