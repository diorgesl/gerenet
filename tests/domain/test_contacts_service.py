import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import ContactCreate, ContactUpdate, OrganizationCreate
from gerenet.domain.services.contacts import (
    create_contact,
    disable_contact,
    get_contact,
    list_contacts,
    update_contact,
)
from gerenet.domain.services.errors import NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization


def _org(db_session: Session) -> int:
    return create_organization(db_session, OrganizationCreate(name="Org C", asn=64513), actor="cli").id


def test_cria_lista_por_organizacao_e_desativa(db_session: Session) -> None:
    org_id = _org(db_session)
    contato = create_contact(
        db_session,
        ContactCreate(organization_id=org_id, name="Fulano", email="noc@x.com.br"),
        actor="cli",
    )
    assert [c.name for c in list_contacts(db_session, organization_id=org_id)] == ["Fulano"]
    disable_contact(db_session, contato.id, actor="cli")
    assert get_contact(db_session, contato.id).admin_status is False


def test_contato_exige_organizacao_existente(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        create_contact(db_session, ContactCreate(organization_id=9999, name="X"), actor="cli")


def test_email_invalido_rejeitado(db_session: Session) -> None:
    org_id = _org(db_session)
    with pytest.raises(ValidationError, match="E-mail inválido"):
        create_contact(
            db_session, ContactCreate(organization_id=org_id, name="X", email="invalido"), actor="cli"
        )


def test_update_contact_muda_organizacao(db_session: Session) -> None:
    org_a = _org(db_session)
    org_b = create_organization(db_session, OrganizationCreate(name="Org D", asn=64514), actor="cli").id
    contato = create_contact(db_session, ContactCreate(organization_id=org_a, name="Fulano"), actor="cli")
    atualizado = update_contact(
        db_session, contato.id, ContactUpdate(organization_id=org_b, phone="11 99999-0000"), actor="cli"
    )
    assert atualizado.organization_id == org_b
    assert atualizado.phone == "11 99999-0000"
