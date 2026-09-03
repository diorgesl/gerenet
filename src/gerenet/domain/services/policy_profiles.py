"""Catálogo de produtos de roteamento (§6.5/§25.5) — somente leitura no ciclo A."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.services.errors import NotFoundError, ValidationError


def get_policy_profile(session: Session, profile_id: int) -> models.PolicyProfile:
    perfil = session.get(models.PolicyProfile, profile_id)
    if perfil is None:
        raise NotFoundError(f"Perfil {profile_id} não encontrado.")
    return perfil


def list_policy_profiles(
    session: Session, direction: str | None = None, include_disabled: bool = False
) -> list[models.PolicyProfile]:
    """Catálogo completo de exportação (importações nascem no ciclo B)."""
    if direction is not None and direction not in ("import", "export"):
        raise ValidationError(f"Direção inválida: {direction} (esperado import ou export).")
    stmt = select(models.PolicyProfile).order_by(models.PolicyProfile.name)
    if not include_disabled:
        stmt = stmt.where(models.PolicyProfile.admin_status.is_(True))
    if direction:
        stmt = stmt.where(models.PolicyProfile.direction == direction)
    return list(session.scalars(stmt))
