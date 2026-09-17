"""API do plano de communities (spec §11/§13).

`GET /plan` é a consulta que a página usa; `GET /plan/validacao` compara o plano
com a configuração coletada; `POST /plan/adopt` grava. Nenhuma rota escreve em
equipamento (§3). Os códigos de erro são os da adoção de peer: 404 quando não há
coleta (a proposta já não existe), 409 de unicidade, 422 de campo.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.db import get_db
from gerenet.domain.schemas import AchadoOut, AdocaoPlanoIn, PlanoAdotadoOut, PlanoOut
from gerenet.domain.services import community_plan as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(
    prefix="/api/v1/communities/plan", tags=["communities"], dependencies=[Depends(require_actor)]
)

SessionDep = Annotated[Session, Depends(get_db)]
ActorDep = Annotated[Actor, Depends(require_actor)]


@router.get("", response_model=PlanoOut)
def consultar_plano(session: SessionDep) -> PlanoOut:
    """O plano ativo, com quem aplica e quem testa cada classe (§11)."""
    plano = svc.obter_plano(session)
    if plano is None:
        return PlanoOut()
    return svc.montar_plano_out(session, plano)


@router.get("/validacao", response_model=list[AchadoOut])
def validar(
    session: SessionDep, device_id: int | None = Query(default=None)
) -> list[AchadoOut]:
    """As oito checagens da §8 contra a configuração coletada.

    Sem `device_id`, valida contra todos os equipamentos que têm coleta — é o que
    a página mostra, porque a comparação que importa é entre a borda e o VS.
    """
    device_ids = [device_id] if device_id is not None else None
    return [AchadoOut(**a.__dict__) for a in svc.validar_plano(session, device_ids)]


@router.post("/adopt", response_model=PlanoAdotadoOut, status_code=status.HTTP_201_CREATED)
def adotar(payload: AdocaoPlanoIn, session: SessionDep, actor: ActorDep) -> PlanoAdotadoOut:
    """Grava na SoT o plano que a coleta do equipamento propõe. Idempotente.

    O corpo descreve o plano **em vigor**: com o mesmo ASN principal o serviço
    devolve o plano que já estava sem escrever, e aí a proposta deste equipamento
    não é o que está valendo — quem diz que nada foi gravado é o `ja_existia`.

    O 409 e o 422 são recusas do serviço, e não guardas desta rota (R28/R31): o
    plano ativo é um só e o cabeçalho exige o ASN principal, então substituir o
    plano de outro ASN ou gravar sem ASN nenhum para antes de escrever — a
    tradução para HTTP é o que mora aqui. O 404 é a coleta ausente: sem ela a
    proposta não existe para ser adotada.
    """
    try:
        plano_antes = svc.obter_plano(session)
        proposta = svc.propor_adocao(session, payload.device_id)
        plano = svc.adotar_plano(
            session, proposta, device_id=payload.device_id,
            snapshot_id=proposta.plano.snapshot_id, actor=actor.nome,
        )
    except NotFoundError as erro:
        raise HTTPException(status_code=404, detail=str(erro)) from erro
    except ConflictError as erro:
        raise HTTPException(status_code=409, detail=str(erro)) from erro
    except ValidationError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    # `adotar_plano` só volta daqui com um plano ativo (gravado agora, ou o que
    # já estava), então esta leitura nunca é vazia: é o mesmo plano que o
    # `GET /plan` devolve, e os números saem dele, não da proposta.
    em_vigor = svc.obter_plano(session)
    return PlanoAdotadoOut(
        plano_id=plano.id,
        asn_principal=plano.asn_principal,
        ja_existia=plano_antes is not None and plano_antes.asn_principal == plano.asn_principal,
        classes=len(em_vigor.classes),
        portoes=len(em_vigor.portoes),
        alvos=len(em_vigor.alvos),
        divergencias=[AchadoOut(**d.__dict__) for d in proposta.divergencias],
        parados=list(proposta.parados),
    )
