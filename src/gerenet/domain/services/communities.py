"""Catálogo de communities (§25.6) — somente leitura no ciclo A."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.services.errors import NotFoundError


def get_community(session: Session, community_id: int) -> models.Community:
    com = session.get(models.Community, community_id)
    if com is None:
        raise NotFoundError(f"Community {community_id} não encontrada.")
    return com


def list_communities(
    session: Session, include_disabled: bool = False
) -> list[models.Community]:
    stmt = select(models.Community).order_by(models.Community.name)
    if not include_disabled:
        stmt = stmt.where(models.Community.admin_status.is_(True))
    return list(session.scalars(stmt))
