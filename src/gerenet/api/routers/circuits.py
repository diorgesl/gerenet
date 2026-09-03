import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.deps import require_api_key
from gerenet.db import get_db
from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, CircuitDetailOut, CircuitOut, CircuitUpdate
from gerenet.domain.services import circuits as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito

router = APIRouter(prefix="/api/v1/circuits", tags=["circuits"], dependencies=[Depends(require_api_key)])

SessionDep = Annotated[Session, Depends(get_db)]


def _detalhe(session: Session, circ: models.Circuit) -> CircuitDetailOut:
    """CircuitDetailOut com as pontas derivadas dos enlaces reservados (ruling 4).

    Só famílias do stack: o par v4 interno de derivação (stack=ipv6) não sai.
    """
    linhas = list(
        session.scalars(
            select(models.IpPrefix).where(
                models.IpPrefix.circuit_id == circ.id,
                models.IpPrefix.status == "reservada",
            )
        )
    )
    por_versao = {ipaddress.ip_network(linha.network).version: linha.network for linha in linhas}
    pontas: dict[str, str | None] = {
        "ipv4_local": None,
        "ipv4_remote": None,
        "ipv6_local": None,
        "ipv6_remote": None,
    }
    if circ.stack in ("ipv4", "dual") and 4 in por_versao:
        pontas["ipv4_local"], pontas["ipv4_remote"] = pontas_v4(por_versao[4])
    if circ.stack in ("ipv6", "dual") and 6 in por_versao:
        pontas["ipv6_local"], pontas["ipv6_remote"] = pontas_v6(por_versao[6])
    return CircuitDetailOut.model_validate(circ).model_copy(update=pontas)


@router.get("", response_model=list[CircuitOut])
def listar(
    session: SessionDep,
    organization_id: int | None = None,
    site_id: int | None = None,
    include_disabled: bool = False,
) -> list:
    return svc.list_circuits(
        session,
        organization_id=organization_id,
        site_id=site_id,
        include_disabled=include_disabled,
    )


@router.post("", response_model=CircuitOut, status_code=201)
def criar(data: CircuitCreate, session: SessionDep) -> object:
    try:
        return svc.create_circuit(session, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{circuit_id}", response_model=CircuitDetailOut)
def detalhar(circuit_id: int, session: SessionDep) -> object:
    try:
        return _detalhe(session, svc.get_circuit(session, circuit_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{circuit_id}", response_model=CircuitOut)
def atualizar(circuit_id: int, data: CircuitUpdate, session: SessionDep) -> object:
    mudancas = data.model_dump(exclude_unset=True)
    if "admin_status" in mudancas and mudancas["admin_status"] is None:
        raise HTTPException(status_code=400, detail="admin_status não aceita null.")
    try:
        if mudancas == {"admin_status": False}:
            return svc.disable_circuit(session, circuit_id, actor="api")
        return svc.update_circuit(session, circuit_id, data, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{circuit_id}/reserve", response_model=CircuitDetailOut)
def reservar(circuit_id: int, session: SessionDep) -> object:
    """Reserva VLAN/enlaces p2p — idempotente (spec §9): repetida devolve o estado."""
    try:
        circ = svc.get_circuit(session, circuit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        reservar_circuito(session, circuit_id, actor="api")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _detalhe(session, circ)
