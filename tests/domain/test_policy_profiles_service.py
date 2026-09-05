import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.services import policy_profiles as svc
from gerenet.domain.services.errors import NotFoundError, ValidationError


def test_catalogo_export_tem_os_seis_produtos(db_session: Session) -> None:
    assert [p.name for p in svc.list_policy_profiles(db_session)] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
        "somente-autorizadas",
    ]
    assert [p.name for p in svc.list_policy_profiles(db_session, direction="export")] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]


def test_lista_filtra_direction(db_session: Session) -> None:
    assert [p.name for p in svc.list_policy_profiles(db_session, direction="import")] == [
        "somente-autorizadas",
    ]
    assert [p.name for p in svc.list_policy_profiles(db_session, direction="export")] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]
    assert all(p.direction == "import" for p in svc.list_policy_profiles(db_session, direction="import"))
    assert all(p.label for p in svc.list_policy_profiles(db_session))  # label PT-BR em todos


def test_get_policy_profile_por_id(db_session: Session) -> None:
    perfil = svc.list_policy_profiles(db_session, direction="export")[0]
    assert svc.get_policy_profile(db_session, perfil.id).id == perfil.id


def test_direction_invalida_no_filtro_rejeitada(db_session: Session) -> None:
    with pytest.raises(ValidationError, match="Direção inválida"):
        svc.list_policy_profiles(db_session, direction="foo")


def test_policy_profile_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Perfil 9999 não encontrado"):
        svc.get_policy_profile(db_session, 9999)


def test_update_policy_profile_altera_e_valida(db_session: Session) -> None:
    from gerenet.domain.schemas import PolicyProfileUpdate

    perfil = models.PolicyProfile(
        name="c3-perfil-teste", label="Teste", direction="export", kind="produto", prefixes=None
    )
    db_session.add(perfil)
    db_session.commit()
    try:
        saida = svc.update_policy_profile(
            db_session,
            perfil.id,
            PolicyProfileUpdate(label="Teste atualizado", prefixes=["192.0.2.0/24"]),
            actor="cli",
        )
        assert saida.label == "Teste atualizado" and saida.prefixes == ["192.0.2.0/24"]
        # Direção só aceita import|export; nome vazio é rejeitado (ValidationError).
        with pytest.raises(ValidationError):
            svc.update_policy_profile(
                db_session, perfil.id, PolicyProfileUpdate(direction="entrada"), actor="cli"
            )
        with pytest.raises(ValidationError):
            svc.update_policy_profile(
                db_session, perfil.id, PolicyProfileUpdate(name="  "), actor="cli"
            )
    finally:
        perfil = db_session.get(models.PolicyProfile, perfil.id)
        if perfil is not None:
            db_session.delete(perfil)
            db_session.commit()


def test_disable_policy_profile_audita(db_session: Session) -> None:
    perfil = models.PolicyProfile(
        name="c3-perfil-off", label="Desliga", direction="export", kind="produto", prefixes=None
    )
    db_session.add(perfil)
    db_session.commit()
    try:
        svc.disable_policy_profile(db_session, perfil.id, actor="cli")
        assert perfil.admin_status is False
        evento = db_session.scalar(
            select(models.AuditEvent).where(models.AuditEvent.type == "policy_profile.disable")
        )
        assert evento is not None
        assert perfil not in svc.list_policy_profiles(db_session)
    finally:
        perfil = db_session.get(models.PolicyProfile, perfil.id)
        if perfil is not None:
            db_session.delete(perfil)
            db_session.commit()
