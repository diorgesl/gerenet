"""Descoberta de peers (spec §13) e a adoção da proposta (design §7).

A leitura é a lista de propostas e a de ignorados; os caminhos de escrita são a
lista de ignorados e a adoção, que grava na SoT a cadeia que a proposta leu.
Nenhum deles manda comando ao equipamento: mudar o roteador segue exigindo
change request.
"""
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.automation.discovery import Proposta, conferir_fidelidade, listar_propostas
from gerenet.db import get_db
from gerenet.domain import schemas
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.discovery import (
    adotar_proposta,
    esquecer_ignorado,
    ignorar_candidato,
    listar_ignorados,
)
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/discovery", tags=["discovery"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]
ActorDep = Annotated[Actor, Depends(require_actor)]


@router.get("", response_model=schemas.DiscoveryOut)
def listar(session: SessionDep, device_id: int) -> schemas.DiscoveryOut:
    """Propostas de adoção dos peers que a SoT não conhece."""
    try:
        resultado = listar_propostas(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return schemas.DiscoveryOut(
        device_id=resultado.device_id,
        snapshot_id=resultado.snapshot_id,
        aviso=resultado.aviso,
        gerado_em=datetime.now(UTC),
        propostas=[schemas.PropostaOut.model_validate(p) for p in resultado.propostas],
        internos=[schemas.CandidatoOut.model_validate(c) for c in resultado.internos],
        snapshot_age_seconds=resultado.snapshot_age_seconds,
    )


@router.get("/ignore", response_model=list[schemas.IgnoradoOut])
def listar_os_ignorados(session: SessionDep, device_id: int) -> list:
    try:
        get_device(session, device_id)  # 404 para equipamento inexistente
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [schemas.IgnoradoOut.model_validate(i) for i in listar_ignorados(session, device_id)]


@router.post("/ignore", response_model=schemas.IgnoradoOut, status_code=201)
def ignorar(payload: schemas.IgnorarIn, session: SessionDep, actor: ActorDep):
    """Marca o peer como não adotar. Idempotente.

    O `get_device` responde pelo caso comum (equipamento inexistente: 404 antes
    de qualquer escrita); a corrida com o equipamento apagado no meio sobra para
    o `ConflictError` do serviço, que é o 409 daqui.
    """
    try:
        get_device(session, payload.device_id)  # 404 antes de qualquer escrita
        return ignorar_candidato(
            session, device_id=payload.device_id, vrf=payload.vrf, afi=payload.afi,
            remote_address=payload.remote_address, motivo=payload.motivo, actor=actor.nome,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/ignore", status_code=204)
def esquecer(
    session: SessionDep, actor: ActorDep, device_id: int,
    afi: Literal["ipv4", "ipv6"], remote_address: str, vrf: str | None = None,
) -> None:
    try:
        get_device(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not esquecer_ignorado(
        session, device_id=device_id, vrf=vrf, afi=afi, remote_address=remote_address,
        actor=actor.nome,
    ):
        # 204 sem apagar nada é o sucesso falso que o operador não confere: o
        # peer segue fora da lista e a resposta dizia que tinha saído.
        raise HTTPException(
            status_code=404,
            detail=f"O peer {remote_address} não está na lista de ignorados do "
                   f"equipamento {device_id}.",
        )


def _busca_proposta(
    session: Session, *, device_id: int, subinterface: str | None, vrf: str | None
) -> Proposta:
    """A proposta da lista, pela identidade que veio no payload.

    O par (subinterface, VRF) não é chave única: a proposta órfã (o peer que não
    casa com subinterface nenhuma, em sub-rede compartilhada ou alcançado por
    rota) tem `subinterface=None`, e o NE8000 real tem dezenas delas. Com mais de
    uma candidata, devolver a primeira entregaria o diff de um peer e o conflito
    de outro, com a cara do peer revisado, então a resposta é a recusa: quem
    chamou recebe o motivo, e não uma proposta qualquer. O 409 e não o 422 porque
    o mesmo pedido passa quando só uma órfã existe — o que mudou foi o estado do
    equipamento, não o corpo da revisão. Fechar a identidade pelo endereço remoto
    (§7 do design: "a subinterface **ou o endereço que a identifica") só passa a
    ser necessário quando a órfã virar adotável.

    O 404 ecoa o `aviso` da lista quando ele existe: sem coleta com a
    configuração a proposta não está fora por adoção, e a frase de adoção
    afirmaria o que não aconteceu.
    """
    resultado = listar_propostas(session, device_id)
    casam = [
        p for p in resultado.propostas
        if p.subinterface == subinterface and p.vrf == vrf
    ]
    if len(casam) > 1:
        alvo = f"subinterface {subinterface}" if subinterface else "sem subinterface"
        raise HTTPException(
            status_code=409,
            detail=(
                f"A proposta é ambígua: {len(casam)} propostas deste equipamento casam "
                f"com a identidade informada ({alvo}, VRF {vrf or 'default'}). "
                "(subinterface, VRF) é a única identidade que a listagem e a revisão "
                "aceitam, e esta versão não tem controle de desambiguação: enquanto "
                "houver mais de uma candidata, a adoção por esta identidade fica "
                "barrada — a lista mostra todas, com os peers que as distinguem."
            ),
        )
    if not casam:
        raise HTTPException(
            status_code=404,
            detail=resultado.aviso or (
                "Proposta não encontrada: ela pode ter sido adotada por outra pessoa."
            ),
        )
    return casam[0]


def _blocos_do_query(autorizacoes: list[str] | None) -> list[tuple[str, str]] | None:
    """Os blocos da revisão, na forma `família:prefixo` que a query string aceita.

    É a mesma informação do `AdocaoAutorizacaoIn` do POST, e na mesma ordem de
    campos: `(prefixo, família)` é o que a conferência consome. O corte é no
    PRIMEIRO dois-pontos porque o prefixo de IPv6 é cheio deles
    (`ipv6:2804:2594::/32`) — cortar no último perderia a família.

    Bloco torto é 422 desta rota: o ensaio não tem o que fazer com ele, e deixá-lo
    virar uma diferença a mais faria a tela acusar o operador por um erro de
    digitação da própria tela.
    """
    if not autorizacoes:
        return None
    blocos: list[tuple[str, str]] = []
    for item in autorizacoes:
        family, separador, prefixo = item.partition(":")
        if not separador or family not in ("ipv4", "ipv6") or not prefixo:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bloco de prefixo inválido: {item!r}. A forma é "
                    "`ipv4:138.121.28.0/22` — a família primeiro, e o prefixo "
                    "depois dos dois-pontos."
                ),
            )
        blocos.append((prefixo, family))
    return blocos


@router.get("/fidelidade", response_model=schemas.FidelidadeOut)
def fidelidade(
    session: SessionDep, device_id: int, subinterface: str | None = None, vrf: str | None = None,
    edge_trunk: str | None = None,
    circuit_code: str | None = None,
    organizacao_id: int | None = None,
    organizacao_nome: str | None = None,
    velocidade_mbps: int | None = None,
    # O `Query()` explícito é o que faz a LISTA repetida ser lida da query string
    # nesta versão do FastAPI: sem o `Annotated`, `list[str]` chega sempre vazio
    # (conferido em sonda), e a conferência seguiria sem os blocos sem nada
    # acusar. É o único parâmetro desta assinatura que precisa dele.
    autorizacoes: Annotated[list[str] | None, Query()] = None,
    import_ipv4: int | None = None, export_ipv4: int | None = None,
    import_ipv6: int | None = None, export_ipv6: int | None = None,
) -> schemas.FidelidadeOut:
    """O diff de UMA proposta, sob demanda: cada conferência roda o render do
    equipamento inteiro num ensaio, então ela não vai embutida na lista (design §7).

    Os quatro parâmetros de perfil são os que o operador escolheu na revisão: sem
    eles o ensaio não renderiza o corpo da política de exportação, e a conferência
    estaria comparando algo diferente do que a adoção vai gravar.

    Os parâmetros de identidade (`edge_trunk`, `circuit_code`,
    `organizacao_id`/`organizacao_nome`, `velocidade_mbps`) são o que a revisão
    vai GRAVAR: o ensaio roda com eles para comparar exatamente o que a adoção
    produziria.

    `autorizacoes` são os blocos que a revisão marcou, um por entrada, na forma
    `família:prefixo` (`?autorizacoes=ipv4:138.121.28.0/22`): sem eles o ensaio
    renderiza o peer SEM o `import route-policy` que a adoção cria, e a prévia ao
    vivo acusa como faltando a linha que a própria escrita emite.
    """
    try:
        proposta = _busca_proposta(session, device_id=device_id,
                                   subinterface=subinterface, vrf=vrf)
        perfis = {
            "ipv4": {"import_profile_id": import_ipv4, "export_profile_id": export_ipv4},
            "ipv6": {"import_profile_id": import_ipv6, "export_profile_id": export_ipv6},
        }
        diferencas = conferir_fidelidade(
            session, proposta, perfis=perfis, edge_trunk=edge_trunk,
            circuit_code=circuit_code, organizacao_id=organizacao_id,
            organizacao_nome=organizacao_nome, velocidade_mbps=velocidade_mbps,
            autorizacoes=_blocos_do_query(autorizacoes),
        )
    except NotFoundError as exc:
        # O `try` cobre a conferência inteira, e não só a busca: o ensaio lê o
        # equipamento de dentro dela, e o equipamento apagado entre a listagem e o
        # render é o mesmo erro de domínio do POST — 404, não 500.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return schemas.FidelidadeOut(
        device_id=device_id, subinterface=subinterface,
        diferencas=[
            schemas.DiferencaOut(contexto=d.contexto, sobrando=list(d.sobrando),
                                 faltando=list(d.faltando),
                                 nao_gerenciado=list(d.nao_gerenciado),
                                 explicacao=d.explicacao, exige_ciente=d.exige_ciente)
            for d in diferencas
        ],
    )


@router.post("/adopt", response_model=schemas.AdocaoOut, status_code=201)
def adotar(payload: schemas.AdocaoIn, session: SessionDep, actor: ActorDep):
    """Grava a cadeia de uma proposta na SoT. Nada vai ao equipamento."""
    try:
        proposta = _busca_proposta(session, device_id=payload.device_id,
                                   subinterface=payload.subinterface, vrf=payload.vrf)
        circuit_id = adotar_proposta(session, proposta=proposta, revisao=payload,
                                     actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schemas.AdocaoOut(circuit_id=circuit_id)
