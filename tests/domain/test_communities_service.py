import pytest
from sqlalchemy.orm import Session

from gerenet.domain.services.communities import get_community, list_communities
from gerenet.domain.services.errors import NotFoundError


def test_catalogo_communities_tem_as_tres_sementes(db_session: Session) -> None:
    nomes = [c.name for c in list_communities(db_session)]
    assert nomes == ["blackhole", "no-advertise", "no-export"]  # order by name


def test_get_community_por_id(db_session: Session) -> None:
    com = list_communities(db_session)[0]
    assert get_community(db_session, com.id).id == com.id


def test_community_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Community 9999 não encontrada"):
        get_community(db_session, 9999)
