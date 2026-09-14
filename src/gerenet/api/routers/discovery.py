"""Descoberta de peers (spec §13): leitura da proposta e lista de ignorados.

O único caminho de escrita da parte 1 é a lista de ignorados; a adoção é a
parte 2 e mora no mesmo prefixo quando chegar.
"""
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.automation.discovery import listar_propostas
from gerenet.db import get_db
from gerenet.domain import schemas
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.discovery import (
    esquecer_ignorado,
    ignorar_candidato,
    listar_ignorados,
)
from gerenet.domain.services.errors import ConflictError, NotFoundError

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
