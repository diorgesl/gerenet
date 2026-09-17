"""CLI do plano de communities (§11): consultar, validar e adotar.

A adoção lê a configuração já coletada e escreve na SoT. Nada vai ao
equipamento — mudar o roteador continua sendo change request.

A saída é uma linha por registro (`typer.echo`), como o resto do CLI: o valor
longo (`com-TRANSITO-FULL`) e a lista de portões não cabem numa tabela de 80
colunas sem truncar o que o operador veio ler.
"""
import typer

from gerenet.db import get_session
from gerenet.domain.services import community_plan as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

app = typer.Typer(help="Plano de communities (classes, instruções, portões e alvos).")


def _numero(valor: int | None) -> str:
    return "—" if valor is None else str(valor)


def _lista(nomes: list[str]) -> str:
    return f"[{', '.join(nomes)}]"


@app.command("show")
def mostrar() -> None:
    """Mostra o plano ativo da SoT."""
    with get_session() as session:
        plano = svc.obter_plano(session)
        if plano is None:
            typer.echo("Nenhum plano de communities adotado ainda.")
            raise typer.Exit(code=0)
        # O `PlanoOut` e não o `PlanoLido`: "quem aplica" e "quem testa" saem da
        # leitura da configuração (com o corpo do corpus citado resolvido), e o
        # estado do alvo também — o plano da SoT não tem nenhum dos dois.
        out = svc.montar_plano_out(session, plano)

    typer.echo(f"ASN principal: {out.asn_principal}")
    if out.observacoes:
        typer.echo(out.observacoes)
    typer.echo(f"Classes ({len(out.classes)}):")
    for classe in out.classes:
        typer.echo(
            f"  {classe.nome}  banda={classe.banda or '—'}  v4={_numero(classe.valor_v4)}  "
            f"v6={_numero(classe.valor_v6)}  aplicam={_lista(classe.aplicam)}  "
            f"testam={_lista(classe.testam)}"
        )
    typer.echo(f"Instruções ({len(out.instrucoes)}):")
    for instrucao in out.instrucoes:
        typer.echo(f"  {instrucao.nome}  codigo={_numero(instrucao.codigo)}")
    typer.echo(f"Portões ({len(out.portoes)}):")
    for portao in out.portoes:
        typer.echo(
            f"  {portao.nome}  papel={portao.papel}  afi={portao.afi}  "
            f"padrao={portao.padrao}  aceitas={_lista(portao.aceitas)}  "
            f"recusadas={_lista(portao.recusadas)}"
        )
    typer.echo(f"Alvos ({len(out.alvos)}):")
    for alvo in out.alvos:
        typer.echo(
            f"  {alvo.nome}  papel={alvo.papel}  v4={_numero(alvo.codigo_v4)}  "
            f"v6={_numero(alvo.codigo_v6)}  portao={alvo.gate_nome or '—'}  "
            f"estado={alvo.estado}"
        )


@app.command("validar")
def validar(
    device_id: int | None = typer.Option(None, "--device", help="Valida contra um equipamento só."),
) -> None:
    """Compara o plano com a configuração coletada (as oito checagens da §8)."""
    with get_session() as session:
        # Sem plano não há comparação nenhuma, e `validar_plano` devolve vazio
        # nos dois casos (plano ausente e plano sem achado): a frase de "está
        # alinhado" seria conclusão sem leitura — a mesma regra da lista vazia
        # do `discovery`.
        if svc.obter_plano(session) is None:
            typer.echo("Nenhum plano de communities adotado ainda: nada a validar.")
            raise typer.Exit(code=0)
        achados = svc.validar_plano(session, [device_id] if device_id is not None else None)

    if not achados:
        typer.echo("Nenhum achado: o plano e a configuração estão alinhados.")
        raise typer.Exit(code=0)
    typer.echo(f"Achados ({len(achados)}):")
    for achado in achados:
        typer.echo(f"  {achado.codigo} [{achado.severidade}] {achado.descricao}")
        local = (
            f"valor={achado.valor or '—'} filtro={achado.filtro or '—'} "
            f"linha={_numero(achado.linha)}"
        )
        typer.echo(f"    {local} — {achado.acao or 'sem ação sugerida'}")
    # O achado crítico é o que barra a publicação do plano: o roteiro de
    # verificação lê o código de saída, e não a lista.
    if any(a.severidade == "critico" for a in achados):
        raise typer.Exit(code=1)


@app.command("adotar")
def adotar(
    device_id: int = typer.Argument(..., help="Equipamento cuja coleta é a origem do plano."),
    actor: str = typer.Option("cli", help="Quem está adotando (vai para a auditoria)."),
) -> None:
    """Adota o plano a partir da configuração já coletada do equipamento."""
    with get_session() as session:
        try:
            # O plano de antes e o de depois: com o mesmo ASN principal o serviço
            # é idempotente e devolve o que já estava **sem gravar**, e aí os
            # números da proposta deste equipamento não descrevem o que está em
            # vigor. Quem diz se houve escrita é o `ja_existia` (R40, como na
            # API: `api/routers/community_plan.py`).
            plano_antes = svc.obter_plano(session)
            proposta = svc.propor_adocao(session, device_id)
            plano = svc.adotar_plano(
                session, proposta, device_id=device_id,
                snapshot_id=proposta.plano.snapshot_id, actor=actor,
            )
        except (NotFoundError, ConflictError, ValidationError) as erro:
            # A coleta ausente (NotFound), o plano ativo de outro ASN principal
            # (Conflict) e a proposta sem ASN (Validation) saem como mensagem:
            # traceback no operador não é resposta.
            typer.echo(f"Erro: {erro}", err=True)
            raise typer.Exit(code=1) from erro
        # O resumo sai daqui de dentro: o `plano` é ORM e o `get_session` commita
        # (e expira) no fim do bloco — lido depois, o atributo viria de uma
        # instância destacada.
        em_vigor = svc.obter_plano(session)
        resumo = (
            f"ASN {plano.asn_principal}, {len(em_vigor.classes)} classes, "
            f"{len(em_vigor.portoes)} portões, {len(em_vigor.alvos)} alvos"
        )
        ja_existia = plano_antes is not None and plano_antes.asn_principal == plano.asn_principal
        if ja_existia:
            typer.echo(f"Plano já existia (id {plano.id}): {resumo} — nada foi gravado.")
        else:
            typer.echo(f"Plano adotado (id {plano.id}): {resumo}.")
        # As divergências e os parados são da proposta deste equipamento:
        # descrevem a configuração dele, e não a escrita.
        for divergencia in proposta.divergencias:
            typer.echo(f"divergência {divergencia.codigo}: {divergencia.descricao}")
        if proposta.parados:
            typer.echo(f"Configurado e parado (fora do plano): {', '.join(proposta.parados)}")
