"""Catálogo de communities (§25.6) — list no ciclo A; criação/update/disable desde a F5.

O tipo (§7/§25.6) categoriza a community e é validado contra models.COMMUNITY_TIPO.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import CommunityCreate, CommunityUpdate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


def _validar_tipo(tipo: str) -> None:
    if tipo not in models.COMMUNITY_TIPO:
        validos = ", ".join(models.COMMUNITY_TIPO)
        raise ValidationError(f"Tipo de community inválido: {tipo} (válidos: {validos}).")


def get_community(session: Session, community_id: int) -> models.Community:
    com = session.get(models.Community, community_id)
    if com is None:
        raise NotFoundError(f"Community {community_id} não encontrada.")
    return com


def create_community(
    session: Session, data: CommunityCreate, *, actor: str
) -> models.Community:
    """Cria comunidade do catálogo global (F5: antes era seed-only)."""
    _validar_tipo(data.tipo)
    nome = (data.name or "").strip()
    if not nome:
        raise ValidationError("Nome da community não pode ser vazio.")
    com = models.Community(name=nome, tipo=data.tipo, notes=data.notes)
    session.add(com)
    try:
        session.flush()
        registrar(
            session, tipo="community.create", ator=actor, objeto="community", objeto_id=com.id,
            antes=None, depois={"name": nome, "tipo": data.tipo, "notes": data.notes},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError(f"Community já existe: {nome}.") from None
    session.refresh(com)
    return com


def list_communities(
    session: Session, *, tipo: str | None = None, include_disabled: bool = False
) -> list[models.Community]:
    if tipo is not None:
        _validar_tipo(tipo)
    stmt = select(models.Community).order_by(models.Community.name)
    if not include_disabled:
        stmt = stmt.where(models.Community.admin_status.is_(True))
    if tipo is not None:
        stmt = stmt.where(models.Community.tipo == tipo)
    return list(session.scalars(stmt))


def update_community(
    session: Session, community_id: int, data: CommunityUpdate, *, actor: str
) -> models.Community:
    com = get_community(session, community_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return com
    if "name" in mudancas:
        nome = mudancas["name"]
        if not (nome or "").strip():
            raise ValidationError("Nome da community não pode ser vazio.")
        ocupado = session.scalar(
            select(models.Community).where(
                models.Community.name == nome, models.Community.id != community_id
            )
        )
        if ocupado is not None:
            raise ConflictError(f"Community já existe: {nome}.")
    if "tipo" in mudancas:
        _validar_tipo(mudancas["tipo"])
    antes = {campo: getattr(com, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(com, campo, valor)
    registrar(
        session, tipo="community.update", ator=actor, objeto="community", objeto_id=com.id,
        antes=antes, depois=mudancas,
    )
    session.commit()
    session.refresh(com)
    return com


def disable_community(session: Session, community_id: int, *, actor: str) -> models.Community:
    com = get_community(session, community_id)
    if com.admin_status is False:
        return com  # idempotente: sem transição, sem evento (Ruling 5)
    com.admin_status = False
    registrar(
        session, tipo="community.disable", ator=actor, objeto="community", objeto_id=com.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return com
