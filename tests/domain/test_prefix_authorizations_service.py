import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import OrganizationCreate, PrefixAuthorizationCreate
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import (
    create_authorization,
    disable_authorization,
    get_authorization,
    list_authorizations,
)


def _org(db_session: Session, nome: str, asn: int) -> int:
    return create_organization(db_session, OrganizationCreate(name=nome, asn=asn), actor="cli").id


def _ultimo_evento(db_session: Session) -> models.AuditEvent:
    eventos = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()
    assert eventos, "nenhum evento de auditoria"
    return eventos[0]


def test_cria_lista_filtra_e_desativa(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Alfa", 64512)
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.160.0.0/22"
        ),
        actor="cli",
    )
    assert auth.origin == "manual"
    assert [a.prefix for a in list_authorizations(db_session, organization_id=org_id)] == [
        "200.160.0.0/22"
    ]
    assert list_authorizations(db_session, family="ipv6", organization_id=org_id) == []

    disable_authorization(db_session, auth.id, actor="cli")
    assert list_authorizations(db_session, organization_id=org_id) == []
    assert [
        a.prefix
        for a in list_authorizations(db_session, organization_id=org_id, include_disabled=True)
    ] == ["200.160.0.0/22"]


def test_mesma_organizacao_pode_sobrepor(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Beta", 64513)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.160.0.0/22"
        ),
        actor="cli",
    )
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.160.0.0/24"
        ),
        actor="cli",
    )
    assert auth.prefix == "200.160.0.0/24"


def test_sobreposicao_entre_organizacoes_vira_conflito(db_session: Session) -> None:
    org_a = _org(db_session, "Cliente Gama", 64514)
    org_b = _org(db_session, "Cliente Delta", 64515)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_a, family="ipv4", prefix="200.160.0.0/22"
        ),
        actor="cli",
    )
    # mais específico dentro do bloco do outro → sobrepõe
    with pytest.raises(ConflictError, match="sobrepõe autorização de Cliente Gama"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_b, family="ipv4", prefix="200.160.0.0/24"
            ),
            actor="cli",
        )
    # contíguo não sobrepõe
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_b, family="ipv4", prefix="200.160.4.0/22"
        ),
        actor="cli",
    )


def test_autorizacao_desativada_nao_bloqueia_outra_organizacao(db_session: Session) -> None:
    org_a = _org(db_session, "Cliente Épsilon", 64516)
    org_b = _org(db_session, "Cliente Zeta", 64517)
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_a, family="ipv4", prefix="200.161.0.0/22"
        ),
        actor="cli",
    )
    disable_authorization(db_session, auth.id, actor="cli")
    nova = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_b, family="ipv4", prefix="200.161.0.0/24"
        ),
        actor="cli",
    )
    assert nova.prefix == "200.161.0.0/24"


def test_familias_diferentes_nao_conflitam(db_session: Session) -> None:
    org_a = _org(db_session, "Cliente Eta", 64518)
    org_b = _org(db_session, "Cliente Teta", 64519)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_a, family="ipv6", prefix="2804:194C::/32"
        ),
        actor="cli",
    )
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_b, family="ipv4", prefix="200.162.0.0/22"
        ),
        actor="cli",
    )  # sem conflito


def test_cidr_desalinhado_ou_de_outra_familia_rejeitado(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Iota", 64520)
    with pytest.raises(ValidationError, match="não está alinhado"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_id, family="ipv4", prefix="200.160.0.1/22"
            ),
            actor="cli",
        )
    with pytest.raises(ValidationError, match="não é um prefixo IPv6"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_id, family="ipv6", prefix="200.160.0.0/22"
            ),
            actor="cli",
        )


def test_organizacao_desativada_nao_recebe_autorizacao(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Kappa", 64521)
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.163.0.0/22"
        ),
        actor="cli",
    )
    # desativa a organização pelo serviço do P1 (o helper só cria)
    from gerenet.domain.services.organizations import disable_organization

    disable_organization(db_session, org_id, actor="cli")
    with pytest.raises(ConflictError, match="desativada não recebe autorizações"):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_id, family="ipv4", prefix="200.164.0.0/22"
            ),
            actor="cli",
        )


def test_audita_criacao_e_desativacao(db_session: Session) -> None:
    org_id = _org(db_session, "Cliente Lambda", 64522)
    auth = create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=org_id, family="ipv4", prefix="200.165.0.0/22", notes="bloco do cliente"
        ),
        actor="cli",
    )
    evento = _ultimo_evento(db_session)
    assert evento.type == "authorization.create"
    assert evento.details["objeto_id"] == auth.id
    assert evento.details["depois"]["prefix"] == "200.165.0.0/22"

    disable_authorization(db_session, auth.id, actor="cli")
    evento = _ultimo_evento(db_session)
    assert evento.type == "authorization.disable"
    assert evento.details["antes"] == {"admin_status": True}
    assert evento.details["depois"] == {"admin_status": False}

    # disable repetido é no-op sem novo evento
    disable_authorization(db_session, auth.id, actor="cli")
    desativacoes = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "authorization.disable")
    ).all()
    assert len(desativacoes) == 1


def test_get_e_autorizacao_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Autorização 9999 não encontrada"):
        get_authorization(db_session, 9999)
