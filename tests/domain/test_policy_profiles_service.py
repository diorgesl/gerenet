import pytest
from sqlalchemy.orm import Session

from gerenet.domain.services.errors import NotFoundError, ValidationError
from gerenet.domain.services.policy_profiles import (
    get_policy_profile,
    list_policy_profiles,
)


def test_catalogo_export_tem_os_seis_produtos(db_session: Session) -> None:
    assert [p.name for p in list_policy_profiles(db_session)] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
        "somente-autorizadas",
    ]
    assert [p.name for p in list_policy_profiles(db_session, direction="export")] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]


def test_lista_filtra_direction(db_session: Session) -> None:
    assert [p.name for p in list_policy_profiles(db_session, direction="import")] == [
        "somente-autorizadas",
    ]
    assert [p.name for p in list_policy_profiles(db_session, direction="export")] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]
    assert all(p.direction == "import" for p in list_policy_profiles(db_session, direction="import"))
    assert all(p.label for p in list_policy_profiles(db_session))  # label PT-BR em todos


def test_get_policy_profile_por_id(db_session: Session) -> None:
    perfil = list_policy_profiles(db_session, direction="export")[0]
    assert get_policy_profile(db_session, perfil.id).id == perfil.id


def test_direction_invalida_no_filtro_rejeitada(db_session: Session) -> None:
    with pytest.raises(ValidationError, match="Direção inválida"):
        list_policy_profiles(db_session, direction="foo")


def test_policy_profile_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Perfil 9999 não encontrado"):
        get_policy_profile(db_session, 9999)
