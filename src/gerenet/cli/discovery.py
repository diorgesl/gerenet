"""Descoberta de peers: o que o equipamento tem e a SoT não conhece (§13).

Somente leitura, mais a lista de ignorados. A adoção é a parte 2.
"""
import typer
from sqlalchemy.orm import Session

from gerenet.automation.discovery import (
    Candidato,
    conferir_fidelidade,
    listar_candidatos,
    listar_propostas,
)
from gerenet.db import get_session
from gerenet.domain.services import devices as dev_svc
from gerenet.domain.services.discovery import (
    esquecer_ignorado,
    ignorar_candidato,
    listar_ignorados,
)
from gerenet.domain.services.errors import GerenetError, NotFoundError
from gerenet.domain.validators import endereco_canonico

app = typer.Typer(help="Descoberta de peers na configuração do equipamento.")

# A mesma família fechada do `IgnorarIn.afi` da API: o valor fora da lista
# chegaria ao Postgres e voltaria como `DataError`, um traceback no operador.
_AFI = ("ipv4", "ipv6")


def _device(session: Session, device: str):
    """Equipamento por ID ou nome; None se não existir."""
    if device.isdigit():
        try:
            return dev_svc.get_device(session, int(device))
        except NotFoundError:
            return None
    return next(
        (d for d in dev_svc.list_devices(session, include_disabled=True) if d.name == device),
        None,
    )


def _resolve(session: Session, device: str):
    encontrado = _device(session, device)
    if encontrado is None:
        typer.echo("Equipamento não encontrado.", err=True)
        raise typer.Exit(1)
    return encontrado


def _exige_afi(afi: str) -> None:
    if afi not in _AFI:
        typer.echo(f"Família inválida: '{afi}'. Use ipv4 ou ipv6.", err=True)
        raise typer.Exit(1)


def _imprime_propostas(propostas) -> None:
    for proposta in propostas:
        alvo = proposta.subinterface or "sem enlace"
        typer.echo(
            f"[{proposta.veredito}] VLAN {proposta.vid or '-'} ({alvo}) "
            f"stack {proposta.stack} código sugerido {proposta.circuit_code_sugerido or '-'}"
        )
        for candidato in proposta.candidatos:
            typer.echo(
                f"  peer {candidato.remote_address} AS{candidato.asn_remote} "
                f"({candidato.classificacao}) — {candidato.motivo}"
            )
        for pendencia in proposta.pendencias:
            typer.echo(f"  pendência: {pendencia.tipo} — {pendencia.descricao}")
        for conflito in proposta.conflitos:
            typer.echo(f"  conflito: {conflito.tipo} — {conflito.descricao}")


def _comando_ignore(device: str, candidato: Candidato) -> str:
    """O `ignore` que tira este candidato da lista, na família e VRF dele."""
    comando = f"gerenet discovery ignore {device} {candidato.remote_address}"
    if candidato.afi != "ipv4":
        comando += f" --afi {candidato.afi}"
    if candidato.vrf:
        comando += f" --vrf {candidato.vrf}"
    return comando


def _imprime_internos(device: str, internos: list[Candidato]) -> None:
    """A lista separada do §5: iBGP não é downstream nem upstream, e o destino
    natural dele é a lista de ignorados."""
    if not internos:
        return
    typer.echo(f"Internos (iBGP), {len(internos)}:")
    for candidato in internos:
        typer.echo(
            f"  peer {candidato.remote_address} AS{candidato.asn_remote} "
            f"({candidato.classificacao}) — {candidato.motivo}"
        )
        typer.echo(f"    sugerido ignorar: {_comando_ignore(device, candidato)}")


@app.command("list")
def listar(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Mostra as propostas de adoção do equipamento."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = listar_propostas(session, encontrado.id)
            # `listar_propostas` monta a proposta dos adotáveis e deixa os
            # internos fora do resultado, onde só `listar_candidatos` os
            # alcança. A leitura é repetida porque esta parte não mexe no
            # motor; ela é pura e lê a configuração já gravada.
            internos = listar_candidatos(session, encontrado.id).internos
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        if resultado.aviso:
            typer.echo(f"Aviso: {resultado.aviso}")
        _imprime_propostas(resultado.propostas)
        if not resultado.propostas and not internos:
            typer.echo("Nenhum peer fora da SoT.")
        _imprime_internos(encontrado.name, internos)
        ignorados = listar_ignorados(session, encontrado.id)
    if ignorados:
        # Só a contagem: a linha com os endereços devolveria à tela o peer que
        # o operador acabou de tirar dela com o `ignore`.
        typer.echo(f"{len(ignorados)} peer(s) ignorado(s) fora da lista.")


@app.command("show")
def mostrar(
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
    peer: str = typer.Argument(..., help="Endereço remoto do peer."),
) -> None:
    """Detalha uma proposta, com a conferência de fidelidade."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = listar_propostas(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        # A comparação é pela forma canônica: o endereço do IPv6 sai do
        # equipamento em maiúsculas e o operador digita o que copiou da tela,
        # e os dois são o mesmo peer.
        alvo = endereco_canonico(peer)
        proposta = next(
            (p for p in resultado.propostas
             if any(c.remote_address == alvo for c in p.candidatos)),
            None,
        )
        if proposta is None:
            typer.echo("Peer não está entre os candidatos.", err=True)
            raise typer.Exit(1)
        _imprime_propostas([proposta])
        for diferenca in conferir_fidelidade(session, proposta):
            typer.echo(f"  fidelidade {diferenca.contexto}:")
            for linha in diferenca.sobrando:
                typer.echo(f"    sobra no render: {linha}")
            for linha in diferenca.faltando:
                typer.echo(f"    falta no render: {linha}")


@app.command("ignore")
def ignorar(
    device: str = typer.Argument(...),
    peer: str = typer.Argument(..., help="Endereço remoto do peer."),
    motivo: str | None = typer.Option(None, "--motivo", help="Por que não adotar."),
    afi: str = typer.Option("ipv4", "--afi", help="ipv4 ou ipv6."),
    vrf: str | None = typer.Option(None, "--vrf", help="VRF; vazio é a instância pública."),
) -> None:
    """Marca o peer como não adotar."""
    _exige_afi(afi)
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            ignorar_candidato(
                session, device_id=encontrado.id, vrf=vrf, afi=afi, remote_address=peer,
                motivo=motivo, actor="cli",
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"{peer} marcado como ignorado.")


@app.command("unignore")
def designorar(
    device: str = typer.Argument(...),
    peer: str = typer.Argument(...),
    afi: str = typer.Option("ipv4", "--afi"),
    vrf: str | None = typer.Option(None, "--vrf"),
) -> None:
    """Tira o peer da lista de ignorados."""
    _exige_afi(afi)
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            removido = esquecer_ignorado(
                session, device_id=encontrado.id, vrf=vrf, afi=afi, remote_address=peer,
                actor="cli",
            )
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
    if removido:
        typer.echo(f"{peer} voltou a ser candidato.")
    else:
        typer.echo(f"{peer} não estava na lista de ignorados.")
