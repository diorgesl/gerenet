from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import OrganizationCreate, OrganizationUpdate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.validators import asn_valido


def _valida_asn(asn: int | None) -> None:
    if asn is not None and not asn_valido(asn):
        raise ValidationError(f"ASN inválido ou reservado: {asn}.")


def _confere_asn_livre(session: Session, asn: int | None, ignorando_id: int | None = None) -> None:
    """ASN é único mesmo entre desativados (§14.1)."""
    if asn is None:
        return
    stmt = select(models.Organization).where(models.Organization.asn == asn)
    if ignorando_id is not None:
        stmt = stmt.where(models.Organization.id != ignorando_id)
    if session.scalars(stmt).first() is not None:
        raise ConflictError(f"Já existe organização com ASN {asn}.")


def _confere_nome_livre(session: Session, nome: str | None, ignorando_id: int | None = None) -> None:
    """Nome único mesmo entre desativados, como o ASN (§14.1).

    A frase é a MESMA do `IntegrityError` do `create_organization`: quem chama
    fora do serviço — a adoção, que não passa por ele para conferir — devolve o
    mesmo diagnóstico, e não um "conflito de integridade" genérico. A checagem
    vem antes do `flush` porque o `flush` falho deixa a transação inutilizável
    (o `rollback` do serviço levaria a transação de quem chamou junto).
    """
    if nome is None:
        return
    stmt = select(models.Organization).where(models.Organization.name == nome)
    if ignorando_id is not None:
        stmt = stmt.where(models.Organization.id != ignorando_id)
    if session.scalars(stmt).first() is not None:
        raise ConflictError(f"Já existe organização com o nome {nome}.")


def create_organization(
    session: Session, data: OrganizationCreate, *, actor: str, commit: bool = True
) -> models.Organization:
    """Cria a organização; `commit=False` é para a adoção encadear os três numa transação (design §3)."""
    dump = data.model_dump()
    _valida_asn(dump.get("asn"))
    _confere_asn_livre(session, dump.get("asn"))
    _confere_nome_livre(session, data.name)
    org = models.Organization(**dump)
    session.add(org)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(
            session, tipo="organization.create", ator=actor, objeto="organization",
            objeto_id=org.id, antes=None, depois=dump,
        )
        if commit:
            session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe organização com o nome {data.name}.") from exc
    if commit:
        session.refresh(org)
    return org


def get_organization(session: Session, organization_id: int) -> models.Organization:
    org = session.get(models.Organization, organization_id)
    if org is None:
        raise NotFoundError(f"Organização {organization_id} não encontrada.")
    return org


def list_organizations(
    session: Session, include_disabled: bool = False, kind: str | None = None
) -> list[models.Organization]:
    stmt = select(models.Organization).order_by(models.Organization.name)
    if not include_disabled:
        stmt = stmt.where(models.Organization.admin_status.is_(True))
    if kind:
        stmt = stmt.where(models.Organization.kind == kind)
    return list(session.scalars(stmt))


def update_organization(
    session: Session, organization_id: int, data: OrganizationUpdate, *, actor: str
) -> models.Organization:
    org = get_organization(session, organization_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return org
    if "asn" in mudancas:
        _valida_asn(mudancas["asn"])
        _confere_asn_livre(session, mudancas["asn"], ignorando_id=org.id)
    antes = {campo: getattr(org, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(org, campo, valor)
    try:
        registrar(
            session, tipo="organization.update", ator=actor, objeto="organization",
            objeto_id=org.id, antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe organização com o nome {mudancas.get('name')}.") from exc
    session.refresh(org)
    return org


def disable_organization(session: Session, organization_id: int, *, actor: str) -> models.Organization:
    org = get_organization(session, organization_id)
    if org.admin_status is False:
        return org
    org.admin_status = False
    registrar(
        session, tipo="organization.disable", ator=actor, objeto="organization",
        objeto_id=org.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return org
