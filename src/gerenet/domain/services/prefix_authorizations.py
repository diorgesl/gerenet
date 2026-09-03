"""Autorizações de prefixo de downstreams (§6.4) — origem manual neste ciclo."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import PrefixAuthorizationCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.validators import cidr_valido


def _organizacao_conflitante(
    session: Session, *, organization_id: int, family: str, prefix: str
) -> models.Organization | None:
    """Outra organização com autorização ATIVA que sobrepõe o prefixo (spec §4).

    A mesma organização pode listar blocos contíguos/sobrepostos; famílias
    diferentes nunca se comparam (versões distintas de ipaddress).
    """
    rede = cidr_valido(prefix, family)
    stmt = select(models.BgpPrefixAuthorization).where(
        models.BgpPrefixAuthorization.admin_status.is_(True),
        models.BgpPrefixAuthorization.family == family,
    )
    for linha in session.scalars(stmt):
        if linha.organization_id == organization_id:
            continue
        if rede.overlaps(cidr_valido(linha.prefix, family)):
            org = session.get(models.Organization, linha.organization_id)
            return org
    return None


def create_authorization(
    session: Session, data: PrefixAuthorizationCreate, *, actor: str
) -> models.BgpPrefixAuthorization:
    org = get_organization(session, data.organization_id)
    if org.admin_status is False:
        raise ConflictError(f"Organização {org.name} desativada não recebe autorizações.")
    cidr_valido(data.prefix, data.family)  # CIDR alinhado da família certa (mensagens PT)
    outra = _organizacao_conflitante(
        session, organization_id=data.organization_id, family=data.family, prefix=data.prefix
    )
    if outra is not None:
        raise ConflictError(f"Prefixo {data.prefix} sobrepõe autorização de {outra.name}.")
    dump = data.model_dump()
    auth = models.BgpPrefixAuthorization(**dump)
    session.add(auth)
    try:
        session.flush()  # valida a FK antes da auditoria
        registrar(
            session, tipo="authorization.create", ator=actor, objeto="authorization",
            objeto_id=auth.id, antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "Não foi possível criar a autorização de prefixo: conflito de integridade."
        ) from exc
    session.refresh(auth)
    return auth


def get_authorization(
    session: Session, authorization_id: int
) -> models.BgpPrefixAuthorization:
    auth = session.get(models.BgpPrefixAuthorization, authorization_id)
    if auth is None:
        raise NotFoundError(f"Autorização {authorization_id} não encontrada.")
    return auth


def list_authorizations(
    session: Session,
    organization_id: int | None = None,
    family: str | None = None,
    include_disabled: bool = False,
) -> list[models.BgpPrefixAuthorization]:
    if family is not None and family not in ("ipv4", "ipv6"):
        raise ValidationError(f"Família inválida: {family} (esperado ipv4 ou ipv6).")
    stmt = select(models.BgpPrefixAuthorization).order_by(
        models.BgpPrefixAuthorization.family, models.BgpPrefixAuthorization.prefix
    )
    if not include_disabled:
        stmt = stmt.where(models.BgpPrefixAuthorization.admin_status.is_(True))
    if organization_id is not None:
        stmt = stmt.where(models.BgpPrefixAuthorization.organization_id == organization_id)
    if family is not None:
        stmt = stmt.where(models.BgpPrefixAuthorization.family == family)
    return list(session.scalars(stmt))


def disable_authorization(
    session: Session, authorization_id: int, *, actor: str
) -> models.BgpPrefixAuthorization:
    """Desativa (sem excluir — §14.1). Mudar um prefixo = desativar + criar (ruling 3)."""
    auth = get_authorization(session, authorization_id)
    if auth.admin_status is False:
        return auth
    auth.admin_status = False
    registrar(
        session, tipo="authorization.disable", ator=actor, objeto="authorization",
        objeto_id=auth.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return auth
