import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import OrganizationCreate, OrganizationUpdate
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.organizations import (
    create_organization,
    disable_organization,
    list_organizations,
    update_organization,
)


def test_cria_lista_filtra_kind_e_desativa(db_session: Session) -> None:
    down = create_organization(
        db_session, OrganizationCreate(name="Provedor A", asn=64512), actor="cli"
    )
    create_organization(db_session, OrganizationCreate(name="Parceiro B", kind="parceiro"), actor="cli")
    assert [o.name for o in list_organizations(db_session, kind="downstream")] == ["Provedor A"]
    # ordem alfabética
    assert [o.name for o in list_organizations(db_session)] == ["Parceiro B", "Provedor A"]

    disable_organization(db_session, down.id, actor="cli")
    assert list_organizations(db_session, kind="downstream") == []


def test_asn_invalido_ou_reservado_rejeitado(db_session: Session) -> None:
    for asn in (23456, 4294967296):
        with pytest.raises(ValidationError):
            create_organization(db_session, OrganizationCreate(name="Org X", asn=asn), actor="cli")


def test_asn_duplicado_mesmo_desativado_vira_conflito(db_session: Session) -> None:
    org = create_organization(db_session, OrganizationCreate(name="Org A", asn=64512), actor="cli")
    disable_organization(db_session, org.id, actor="cli")
    with pytest.raises(ConflictError, match="ASN 64512"):
        create_organization(db_session, OrganizationCreate(name="Org B", asn=64512), actor="cli")


def test_update_organization_altera_e_rejeita_asn_em_uso(db_session: Session) -> None:
    org = create_organization(db_session, OrganizationCreate(name="Org A", asn=64512), actor="cli")
    atualizada = update_organization(
        db_session, org.id, OrganizationUpdate(legal_name="Provedor A LTDA"), actor="cli"
    )
    assert atualizada.legal_name == "Provedor A LTDA"

    create_organization(db_session, OrganizationCreate(name="Outra", asn=65001), actor="cli")
    with pytest.raises(ConflictError, match="ASN 65001"):
        update_organization(db_session, org.id, OrganizationUpdate(asn=65001), actor="cli")
