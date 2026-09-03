from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import ContactCreate, ContactUpdate
from gerenet.domain.services.errors import NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.validators import email_valido


def create_contact(session: Session, data: ContactCreate, *, actor: str) -> models.Contact:
    get_organization(session, data.organization_id)  # NotFoundError com mensagem PT
    if data.email and not email_valido(data.email):
        raise ValidationError(f"E-mail inválido: {data.email}.")
    dump = data.model_dump()
    contato = models.Contact(**dump)
    session.add(contato)
    session.flush()
    registrar(
        session, tipo="contact.create", ator=actor, objeto="contact", objeto_id=contato.id,
        antes=None, depois=dump,
    )
    session.commit()
    session.refresh(contato)
    return contato


def get_contact(session: Session, contact_id: int) -> models.Contact:
    contato = session.get(models.Contact, contact_id)
    if contato is None:
        raise NotFoundError(f"Contato {contact_id} não encontrado.")
    return contato


def list_contacts(session: Session, organization_id: int | None = None) -> list[models.Contact]:
    stmt = select(models.Contact).order_by(models.Contact.name)
    if organization_id is not None:
        stmt = stmt.where(models.Contact.organization_id == organization_id)
    stmt = stmt.where(models.Contact.admin_status.is_(True))
    return list(session.scalars(stmt))


def update_contact(session: Session, contact_id: int, data: ContactUpdate, *, actor: str) -> models.Contact:
    contato = get_contact(session, contact_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return contato
    # Presença explícita ("in" + None check), como em circuits: um id 0 explícito
    # segue para o check de existência e vira NotFoundError, em vez de pular a
    # validação e explodir como IntegrityError cru no commit (finding Task 7).
    if "organization_id" in mudancas:
        if mudancas["organization_id"] is None:
            raise ValidationError("organization_id é obrigatório.")
        get_organization(session, mudancas["organization_id"])
    if mudancas.get("email") and not email_valido(mudancas["email"]):
        raise ValidationError(f"E-mail inválido: {mudancas['email']}.")
    antes = {campo: getattr(contato, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(contato, campo, valor)
    registrar(
        session, tipo="contact.update", ator=actor, objeto="contact", objeto_id=contato.id,
        antes=antes, depois=mudancas,
    )
    session.commit()
    session.refresh(contato)
    return contato


def disable_contact(session: Session, contact_id: int, *, actor: str) -> models.Contact:
    contato = get_contact(session, contact_id)
    if contato.admin_status is False:
        return contato
    contato.admin_status = False
    registrar(
        session, tipo="contact.disable", ator=actor, objeto="contact", objeto_id=contato.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return contato
