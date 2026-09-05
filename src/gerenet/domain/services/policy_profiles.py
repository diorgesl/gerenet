"""Catálogo de produtos de roteamento (§6.5/§25.5) — list no ciclo A; update/disable no C3."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import PolicyProfileUpdate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


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


def update_policy_profile(
    session: Session, profile_id: int, data: PolicyProfileUpdate, *, actor: str
) -> models.PolicyProfile:
    perfil = get_policy_profile(session, profile_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return perfil
    if "name" in mudancas:
        nome = mudancas["name"]
        if not nome.strip():
            raise ValidationError("Nome do perfil não pode ser vazio.")
        ocupado = session.scalar(
            select(models.PolicyProfile).where(
                models.PolicyProfile.name == nome, models.PolicyProfile.id != profile_id
            )
        )
        if ocupado is not None:
            raise ConflictError(f"Perfil já existe: {nome}.")
    if "label" in mudancas and not mudancas["label"].strip():
        raise ValidationError("Label do perfil não pode ser vazio.")
    if "direction" in mudancas and mudancas["direction"] not in models.DIRECTION:
        raise ValidationError(
            f"Direção inválida: {mudancas['direction']} (esperado {', '.join(models.DIRECTION)})."
        )
    if "kind" in mudancas and mudancas["kind"] not in models.PROFILE_KIND:
        raise ValidationError(
            f"Tipo inválido: {mudancas['kind']} (esperado {', '.join(models.PROFILE_KIND)})."
        )
    antes = {campo: getattr(perfil, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(perfil, campo, valor)
    registrar(
        session, tipo="policy_profile.update", ator=actor, objeto="policy_profile", objeto_id=perfil.id,
        antes=antes, depois=mudancas,
    )
    session.commit()
    session.refresh(perfil)
    return perfil


def disable_policy_profile(
    session: Session, profile_id: int, *, actor: str
) -> models.PolicyProfile:
    perfil = get_policy_profile(session, profile_id)
    if perfil.admin_status is False:
        return perfil  # idempotente: sem transição, sem evento (Ruling 5)
    perfil.admin_status = False
    registrar(
        session, tipo="policy_profile.disable", ator=actor, objeto="policy_profile", objeto_id=perfil.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return perfil
