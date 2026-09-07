"""API MPLS (spec §9): domínios, L2VC e VSI — cadastro e consulta.

Escrita via require_actor no router (padrão de change_requests.py: criar é
ação de operador e o Visualizador já é bloqueado pelo require_actor — sem
gate require_papel, não é o padrão de cadastro do repo). A rota de plano é
read-only (plan_provision_l2vc não altera estado).
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.automation import l2vc as l2vc_auto
from gerenet.db import get_db
from gerenet.domain.schemas import (
    L2vcCreate,
    L2vcOut,
    MplsDomainCreate,
    MplsDomainOut,
    MplsDomainUpdate,
    MplsMemberIn,
    VsiCreate,
    VsiOut,
)
from gerenet.domain.services import mpls as svc
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/mpls", tags=["mpls"], dependencies=[Depends(require_actor)])

SessionDep = Annotated[Session, Depends(get_db)]


class L2vcStatusIn(BaseModel):
    admin_status: bool


# ---- Domínios (§9.1) ------------------------------------------------------


@router.get("/domains", response_model=list[MplsDomainOut])
def listar_domains(session: SessionDep, include_disabled: bool = False) -> list:
    return [svc.out_domain(d) for d in svc.list_domains(session, include_disabled=include_disabled)]


@router.post("/domains", response_model=MplsDomainOut, status_code=201)
def criar_domain(
    data: MplsDomainCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.out_domain(svc.create_domain(session, data, actor=actor.nome))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/domains/{domain_id}", response_model=MplsDomainOut)
def detalhar_domain(domain_id: int, session: SessionDep) -> object:
    try:
        return svc.out_domain(svc.get_domain(session, domain_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/domains/{domain_id}", response_model=MplsDomainOut)
def atualizar_domain(
    domain_id: int,
    data: MplsDomainUpdate,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    try:
        return svc.out_domain(svc.update_domain(session, domain_id, data, actor=actor.nome))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/members", response_model=MplsDomainOut, status_code=201)
def add_member(
    domain_id: int,
    data: MplsMemberIn,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    """Adiciona um membro e devolve o domínio atualizado (members com device_name)."""
    try:
        svc.add_domain_member(session, domain_id, data, actor=actor.nome)
        return svc.out_domain(svc.get_domain(session, domain_id))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/domains/{domain_id}/members/{device_id}", status_code=204)
def remove_member(
    domain_id: int, device_id: int, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> None:
    try:
        svc.remove_domain_member(session, domain_id, device_id, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- L2VC (§9.2) -----------------------------------------------------------


@router.get("/l2vc", response_model=list[L2vcOut])
def listar_l2vc(
    session: SessionDep, domain_id: int | None = None, include_disabled: bool = False
) -> list:
    return [
        svc.out_l2vc(s)
        for s in svc.list_l2vc(session, domain_id=domain_id, include_disabled=include_disabled)
    ]


@router.post("/l2vc", response_model=L2vcOut, status_code=201)
def criar_l2vc(
    data: L2vcCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.out_l2vc(svc.create_l2vc(session, data, actor=actor.nome))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/l2vc/{l2vc_id}", response_model=L2vcOut)
def detalhar_l2vc(l2vc_id: int, session: SessionDep) -> object:
    try:
        return svc.out_l2vc(svc.get_l2vc(session, l2vc_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/l2vc/{l2vc_id}/status", response_model=L2vcOut)
def set_l2vc_status(
    l2vc_id: int,
    data: L2vcStatusIn,
    session: SessionDep,
    actor: Annotated[Actor, Depends(require_actor)],
) -> object:
    try:
        return svc.out_l2vc(
            svc.set_l2vc_status(session, l2vc_id, admin_status=data.admin_status, actor=actor.nome)
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/l2vc/{l2vc_id}/plano")
def plano_l2vc(l2vc_id: int, session: SessionDep) -> list[dict]:
    """Plano de provision por ponta (read-only — o tipo PlanoL2vcOut é do ciclo T11)."""
    try:
        servico = svc.get_l2vc(session, l2vc_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        itens = l2vc_auto.plan_provision_l2vc(session, servico)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        {
            "device_id": item.device_id,
            "blocos": item.blocos,
            "aviso": item.aviso,
            "baseline_snapshot_id": item.baseline_snapshot_id,
        }
        for item in itens
    ]


# ---- VSI (§9.3: modelo + consulta) ----------------------------------------


@router.get("/vsi", response_model=list[VsiOut])
def listar_vsi(
    session: SessionDep, domain_id: int | None = None, include_disabled: bool = False
) -> list:
    return [
        svc.out_vsi(s)
        for s in svc.list_vsi(session, domain_id=domain_id, include_disabled=include_disabled)
    ]


@router.post("/vsi", response_model=VsiOut, status_code=201)
def criar_vsi(
    data: VsiCreate, session: SessionDep, actor: Annotated[Actor, Depends(require_actor)]
) -> object:
    try:
        return svc.out_vsi(svc.create_vsi(session, data, actor=actor.nome))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/vsi/{vsi_id}", response_model=VsiOut)
def detalhar_vsi(vsi_id: int, session: SessionDep) -> object:
    try:
        return svc.out_vsi(svc.get_vsi(session, vsi_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
