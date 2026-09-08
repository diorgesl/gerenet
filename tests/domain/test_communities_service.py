import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.services import communities as svc
from gerenet.domain.services.errors import NotFoundError, ValidationError


def test_catalogo_communities_tem_as_tres_sementes(db_session: Session) -> None:
    nomes = [c.name for c in svc.list_communities(db_session)]
    assert nomes == ["blackhole", "no-advertise", "no-export"]  # order by name


def test_get_community_por_id(db_session: Session) -> None:
    com = svc.list_communities(db_session)[0]
    assert svc.get_community(db_session, com.id).id == com.id


def test_community_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Community 9999 não encontrada"):
        svc.get_community(db_session, 9999)


def test_update_community_altera_e_audita(db_session: Session) -> None:
    from gerenet.domain.schemas import CommunityUpdate

    com = models.Community(name="c3-teste-upd", notes="antes")
    db_session.add(com)
    db_session.commit()
    try:
        saida = svc.update_community(
            db_session, com.id, CommunityUpdate(name="c3-teste-novo", notes="depois"), actor="cli"
        )
        assert saida.name == "c3-teste-novo" and saida.notes == "depois"
        evento = db_session.scalar(
            select(models.AuditEvent).where(models.AuditEvent.type == "community.update")
        )
        assert evento is not None
        assert evento.details["antes"] == {"name": "c3-teste-upd", "notes": "antes"}
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def test_update_community_rejeita_nome_nulo(db_session: Session) -> None:
    from gerenet.domain.schemas import CommunityUpdate

    com = models.Community(name="c3-com-nulo")
    db_session.add(com)
    db_session.commit()
    try:
        # None explícito chega ao serviço via model_dump(exclude_unset=True)
        # e deve dar o mesmo ValidationError que nome vazio — não AttributeError.
        with pytest.raises(ValidationError, match="Nome da community não pode ser vazio"):
            svc.update_community(db_session, com.id, CommunityUpdate(name=None), actor="cli")
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def test_update_community_rejeita_nome_duplicado(db_session: Session) -> None:
    from gerenet.domain.schemas import CommunityUpdate
    from gerenet.domain.services.errors import ConflictError

    a = models.Community(name="c3-com-a")
    b = models.Community(name="c3-com-b")
    db_session.add_all([a, b])
    db_session.commit()
    try:
        with pytest.raises(ConflictError):
            svc.update_community(db_session, b.id, CommunityUpdate(name="c3-com-a"), actor="cli")
    finally:
        for obj in (a, b):
            obj = db_session.get(models.Community, obj.id)
            if obj is not None:
                db_session.delete(obj)
        db_session.commit()


def test_disable_community_idempotente(db_session: Session) -> None:
    com = models.Community(name="c3-com-off")
    db_session.add(com)
    db_session.commit()
    try:
        svc.disable_community(db_session, com.id, actor="cli")
        db_session.commit()
        assert com.admin_status is False
        svc.disable_community(db_session, com.id, actor="cli")  # repetição: sem evento (Ruling 5)
        eventos = db_session.scalars(
            select(models.AuditEvent).where(models.AuditEvent.type == "community.disable")
        ).all()
        assert len(eventos) == 1
        assert [c.name for c in svc.list_communities(db_session)] == [
            "blackhole", "no-advertise", "no-export",
        ]
        com_tudo = svc.list_communities(db_session, include_disabled=True)
        assert "c3-com-off" in [c.name for c in com_tudo]
    finally:
        com = db_session.get(models.Community, com.id)
        if com is not None:
            db_session.delete(com)
            db_session.commit()


def _apaga_comunidade(session: Session, nome: str) -> None:
    com = session.scalar(select(models.Community).where(models.Community.name == nome))
    if com is not None:
        session.delete(com)
        session.commit()


def test_cria_comunidade_global_com_tipo(session: Session) -> None:
    from gerenet.domain.schemas import CommunityCreate

    # F5/A4: catálogo permitiu criação desde a fase 5; tipo categoriza (§7/§25.6).
    com = svc.create_community(
        session,
        CommunityCreate(name="blackhole-sul", tipo="acao_blackhole", notes="v6/32 p/ Sul"),
        actor="cli",
    )
    assert com.tipo == "acao_blackhole"
    assert com.notes == "v6/32 p/ Sul"
    evento = session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "community.create")
    )
    assert evento is not None
    assert evento.details["depois"] == {"name": "blackhole-sul", "tipo": "acao_blackhole"}
    try:
        assert "blackhole-sul" in [c.name for c in svc.list_communities(session)]
    finally:
        _apaga_comunidade(session, "blackhole-sul")


def test_cria_comunidade_rejeita_tipo_invalido(session: Session) -> None:
    from gerenet.domain.schemas import CommunityCreate

    with pytest.raises(ValidationError, match="Tipo de community inválido"):
        svc.create_community(
            session, CommunityCreate(name="x-com-tipo", tipo="nao-existe"), actor="cli"
        )


def test_cria_comunidade_nome_duplicado_conflito(session: Session) -> None:
    from gerenet.domain.schemas import CommunityCreate
    from gerenet.domain.services.errors import ConflictError

    svc.create_community(session, CommunityCreate(name="c5-com-dupe"), actor="cli")
    try:
        with pytest.raises(ConflictError, match="Community já existe: c5-com-dupe"):
            svc.create_community(
                session, CommunityCreate(name="c5-com-dupe", tipo="acao_lp"), actor="cli"
            )
    finally:
        _apaga_comunidade(session, "c5-com-dupe")


def test_list_communities_filtra_por_tipo(session: Session) -> None:
    from gerenet.domain.schemas import CommunityCreate

    svc.create_community(session, CommunityCreate(name="c5-com-lp", tipo="acao_lp"), actor="cli")
    try:
        nomes_lp = [c.name for c in svc.list_communities(session, tipo="acao_lp")]
        assert nomes_lp == ["c5-com-lp"]
        # tipo inválido → ValidationError (não lista o catálogo inteiro)
        with pytest.raises(ValidationError, match="Tipo de community inválido"):
            svc.list_communities(session, tipo="nao-existe")
    finally:
        _apaga_comunidade(session, "c5-com-lp")


def test_update_community_aceita_tipo(session: Session) -> None:
    from gerenet.domain.schemas import CommunityCreate, CommunityUpdate

    com = svc.create_community(session, CommunityCreate(name="c5-com-up-tipo"), actor="cli")
    try:
        saida = svc.update_community(
            session, com.id, CommunityUpdate(tipo="tag_produto"), actor="cli"
        )
        assert saida.tipo == "tag_produto"
        with pytest.raises(ValidationError, match="Tipo de community inválido"):
            svc.update_community(session, com.id, CommunityUpdate(tipo="nao"), actor="cli")
    finally:
        _apaga_comunidade(session, "c5-com-up-tipo")
