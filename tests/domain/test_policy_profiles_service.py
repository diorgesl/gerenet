import pytest
from sqlalchemy.orm import Session

from gerenet.domain.services.errors import NotFoundError
from gerenet.domain.services.policy_profiles import (
    get_policy_profile,
    list_policy_profiles,
)


def test_catalogo_export_tem_os_seis_produtos(db_session: Session) -> None:
    nomes = [p.name for p in list_policy_profiles(db_session)]
    assert nomes == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
    ]  # order by name


def test_lista_filtra_direction(db_session: Session) -> None:
    assert len(list_policy_profiles(db_session, direction="export")) == 6
    assert list_policy_profiles(db_session, direction="import") == []


def test_get_policy_profile_por_id(db_session: Session) -> None:
    perfil = list_policy_profiles(db_session, direction="export")[0]
    assert get_policy_profile(db_session, perfil.id).id == perfil.id


def test_policy_profile_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Perfil 9999 não encontrado"):
        get_policy_profile(db_session, 9999)
