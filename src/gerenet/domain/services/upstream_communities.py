"""Communities por operadora (§7.1) — valor concreto por upstream (F5/A4).

A chave de unicidade é (upstream_id, purpose, value, regiao): a mesma community
de TE vale para import e export — a direcao não entra na chave.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import UpstreamCommunityCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError
from gerenet.domain.services.upstreams import get_upstream


def add_upstream_community(
    session: Session, upstream_id: int, data: UpstreamCommunityCreate, *, actor: str
) -> models.UpstreamCommunity:
    """Cadastra uma community de operadora com valor concreto (purpose/value/regiao)."""
    up = get_upstream(session, upstream_id)
    if not up.admin_status:
        raise ConflictError(f"Upstream {up.name} desativado não recebe communities.")
    uc = models.UpstreamCommunity(upstream_id=up.id, **data.model_dump())
    session.add(uc)
    try:
        session.flush()
        registrar(
            session, tipo="upstream_community.create", ator=actor,
            objeto="upstream", objeto_id=up.id,
            antes=None, depois={"community": data.value, "purpose": data.purpose},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("Community já cadastrada para este upstream (purpose/value/regiao).") from None
    session.refresh(uc)
    return uc


def list_upstream_communities(
    session: Session, upstream_id: int, *, include_disabled: bool = False
) -> list[models.UpstreamCommunity]:
    """Communities de um upstream, na ordem (purpose, value, regiao)."""
    get_upstream(session, upstream_id)
    stmt = (
        select(models.UpstreamCommunity)
        .where(models.UpstreamCommunity.upstream_id == upstream_id)
        .order_by(
            models.UpstreamCommunity.purpose,
            models.UpstreamCommunity.value,
            models.UpstreamCommunity.regiao,
        )
    )
    if not include_disabled:
        stmt = stmt.where(models.UpstreamCommunity.admin_status.is_(True))
    return list(session.scalars(stmt))


def remove_upstream_community(
    session: Session, upstream_id: int, community_id: int, *, actor: str
) -> None:
    """Remove uma community de operadora (evento upstream_community.remove)."""
    uc = session.scalar(
        select(models.UpstreamCommunity).where(
            models.UpstreamCommunity.upstream_id == upstream_id,
            models.UpstreamCommunity.id == community_id,
        )
    )
    if uc is None:
        raise NotFoundError(
            f"Community {community_id} não encontrada no upstream {upstream_id}."
        )
    antes = {"purpose": uc.purpose, "value": uc.value, "regiao": uc.regiao}
    session.delete(uc)
    registrar(
        session, tipo="upstream_community.remove", ator=actor,
        objeto="upstream", objeto_id=upstream_id,
        antes=antes, depois=None,
    )
    session.commit()
