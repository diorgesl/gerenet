"""Descoberta de peers: o que o equipamento tem e a SoT não conhece (§13).

Somente leitura NO EQUIPAMENTO: a lista de ignorados e a adoção escrevem na SoT,
e nenhuma delas manda comando ao roteador — mudar o equipamento continua sendo
change request.
"""
from pathlib import Path

import typer
from pydantic import ValidationError as SchemaValidationError
from sqlalchemy.orm import Session

from gerenet.automation.discovery import (
    Candidato,
    Diferenca,
    conferir_fidelidade,
    listar_propostas,
)
from gerenet.db import get_session
from gerenet.domain import schemas
from gerenet.domain.services import devices as dev_svc
from gerenet.domain.services.discovery import (
    adotar_proposta,
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


def _ignorado(session: Session, device_id: int, endereco: str) -> bool:
    """O peer está na lista de ignorados deste equipamento (qualquer família)."""
    canonico = endereco_canonico(endereco)
    return any(endereco_canonico(linha.remote_address) == canonico
               for linha in listar_ignorados(session, device_id))


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


def _idade_da_coleta(segundos: float) -> str:
    """Idade da coleta em texto curto (mesma escala da tela do dashboard).

    A descoberta recua para um snapshot mais antigo quando os recentes não têm a
    configuração, e é a idade que diz se o operador está lendo dez minutos ou
    três dias: em segundos crus os dois números se parecem.
    """
    if segundos < 60:
        return f"{segundos:.0f} s"
    if segundos < 3600:
        return f"{segundos / 60:.0f} min"
    if segundos < 3 * 86400:
        return f"{segundos / 3600:.1f} h"
    return f"{segundos / 86400:.1f} d"


def _imprime_fidelidade(diferencas: list[Diferenca]) -> None:
    """O diff da conferência, com o que a SoT não gerencia num bloco próprio.

    O `ensaio` guarda o motivo fora de `sobrando`/`faltando` (§6 do design), e o
    `nao_gerenciado` é informação, não diferença: cada um tem a sua linha aqui.
    Contexto que ficou sem nada não imprime cabeçalho — um cabeçalho sozinho é
    onde o operador não lê por que a adoção está barrada.
    """
    for diferenca in diferencas:
        if not (diferenca.sobrando or diferenca.faltando
                or diferenca.nao_gerenciado or diferenca.explicacao):
            continue
        typer.echo(f"  fidelidade {diferenca.contexto}:")
        if diferenca.explicacao:
            typer.echo(f"    {diferenca.explicacao}")
        for linha in diferenca.sobrando:
            typer.echo(f"    sobra no render: {linha}")
        for linha in diferenca.faltando:
            typer.echo(f"    falta no render: {linha}")
        if diferenca.nao_gerenciado:
            typer.echo("    o que a SoT não gerencia (não exige ciente):")
            for linha in diferenca.nao_gerenciado:
                typer.echo(f"      {linha}")


@app.command("list")
def listar(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Mostra as propostas de adoção do equipamento."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = listar_propostas(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        if resultado.aviso:
            typer.echo(f"Aviso: {resultado.aviso}")
        if resultado.snapshot_age_seconds is not None:
            typer.echo(f"Coleta usada: há {_idade_da_coleta(resultado.snapshot_age_seconds)}.")
        _imprime_propostas(resultado.propostas)
        if resultado.aviso is None and not resultado.propostas and not resultado.internos:
            # Sem coleta a lista vazia não sustenta conclusão nenhuma: quem diz
            # que não há peer é a leitura, e ela não aconteceu. E com internos a
            # frase seria falsa: eles estão fora da SoT por definição, e o bloco
            # logo abaixo os mostra.
            typer.echo("Nenhum peer fora da SoT.")
        _imprime_internos(encontrado.name, resultado.internos)
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
        if resultado.aviso:
            # Sem coleta não há candidato lido: "não está entre os candidatos"
            # mandaria o operador procurar o que ninguém leu ainda.
            typer.echo(f"Aviso: {resultado.aviso}")
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
            if _ignorado(session, encontrado.id, alvo):
                typer.echo(
                    f"O peer {peer} está na lista de ignorados do equipamento "
                    f"{encontrado.name}: use `discovery unignore` para desfazer.",
                    err=True,
                )
            elif resultado.aviso is None:
                # A frase é a mesma regra do `list` e da página: só a leitura
                # inteira sustenta "não está entre os candidatos". Com aviso —
                # sem coleta ou leitura parcial — a lista pode não ter o peer
                # por falta de fonte, e aí quem responde é o aviso.
                typer.echo("Peer não está entre os candidatos.", err=True)
            raise typer.Exit(1)
        _imprime_propostas([proposta])
        _imprime_fidelidade(conferir_fidelidade(session, proposta))


@app.command("adopt")
def adotar(
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
    peer: str = typer.Argument(..., help="Endereço remoto de um dos peers do enlace."),
    json_revisao: str = typer.Option(..., "--json", help="Arquivo com a revisão (AdocaoIn)."),
    ciente: bool = typer.Option(
        False, "--ciente",
        help="Assume as diferenças que mudariam o equipamento (o arquivo pode trazê-las).",
    ),
) -> None:
    """Grava a cadeia da proposta na SoT. Nada é enviado ao equipamento."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        # A comparação é pela forma canônica, como no `show`: o IPv6 sai do
        # equipamento em maiúsculas e o operador digita o que copiou da tela.
        alvo = endereco_canonico(peer)
        try:
            revisao = schemas.AdocaoIn.model_validate_json(
                Path(json_revisao).read_text(encoding="utf-8")
            )
            if ciente and not revisao.ciente:
                # A flag do terminal cobre o caso do runbook: o aceite da mesma
                # sessão, sem editar o arquivo. O `ciente` do arquivo já basta.
                revisao = revisao.model_copy(update={"ciente": True})
            resultado = listar_propostas(session, encontrado.id)
            if resultado.aviso:
                # O sinal sai antes da busca e mesmo com a proposta achada: aqui
                # a escrita vai para a SoT, e gravar a partir de uma leitura que a
                # ferramenta marca sem dizer nada é o que mais custa (a regra do
                # `show`, que imprime o aviso sempre).
                typer.echo(f"Aviso: {resultado.aviso}")
            proposta = next(
                (p for p in resultado.propostas
                 if any(c.remote_address == alvo for c in p.candidatos)),
                None,
            )
            if proposta is None:
                if resultado.aviso is None:
                    # "Não está entre os candidatos" é conclusão, e sem leitura
                    # inteira (ou com a parcial) ela conclui o que nenhuma leitura
                    # sustenta.
                    typer.echo("Peer não está entre os candidatos.", err=True)
                raise typer.Exit(1)
            circuit_id = adotar_proposta(session, proposta=proposta, revisao=revisao,
                                         actor="cli")
        except (GerenetError, SchemaValidationError) as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        except UnicodeDecodeError as exc:
            # `ValueError`, e não `OSError`: sem este ramo a revisão regravada em
            # latin-1 chegava ao terminal como pilha.
            typer.echo(f"Erro ao ler {json_revisao}: o arquivo precisa estar em UTF-8 "
                       f"({exc}).", err=True)
            raise typer.Exit(1) from exc
        except OSError as exc:
            typer.echo(f"Erro ao ler {json_revisao}: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {revisao.circuit_code} criado (id {circuit_id}).")


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
