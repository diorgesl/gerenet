"""Communities por operadora (§7.1) — valor concreto por upstream (F5/A4).

O UNIQUE (upstream_id, purpose, value, regiao) do modelo é a regra de negócio:
a direcao não entra na chave — import/export exibem o mesmo valor de TE.
"""
import pytest
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.schemas import UpstreamCommunityCreate
from gerenet.domain.services import upstream_communities as ucomm
from gerenet.domain.services.errors import ConflictError, NotFoundError


def test_upstream_community_valor_concreto(session, up) -> None:
    s = UpstreamCommunityCreate(
        purpose="prepend", value="65530:20:0", regiao="sul", direcao="export"
    )
    uc = ucomm.add_upstream_community(session, up.id, s, actor="cli")
    assert uc.value == "65530:20:0"
    assert uc.purpose == "prepend" and uc.upstream_id == up.id
    # dupe sem direcao (default "ambos") colide no UNIQUE (upstream, purpose, value, regiao)
    dupe = UpstreamCommunityCreate(purpose="prepend", value="65530:20:0", regiao="sul")
    with pytest.raises(ConflictError, match="já cadastrada para este upstream"):
        ucomm.add_upstream_community(session, up.id, dupe, actor="cli")


def test_add_audita_e_lista_ordenada_por_purpose(session, up) -> None:
    ucomm.add_upstream_community(
        session, up.id,
        UpstreamCommunityCreate(purpose="lp", value="65530:21:0", regiao="norte"), actor="cli",
    )
    ucomm.add_upstream_community(
        session, up.id,
        UpstreamCommunityCreate(purpose="prepend", value="65530:20:0", regiao="sul"), actor="cli",
    )
    eventos = session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "upstream_community.create")
    ).all()
    assert len(eventos) == 2
    assert eventos[0].details["objeto"] == "upstream"
    # enum ucomm_purpose: prepend < lp → ordem estável por (purpose, value, regiao)
    lista = ucomm.list_upstream_communities(session, up.id)
    assert [(c.purpose, c.value) for c in lista] == [
        ("prepend", "65530:20:0"), ("lp", "65530:21:0"),
    ]


def test_add_em_upstream_desativado_conflito(session, up) -> None:
    up.admin_status = False
    session.commit()
    with pytest.raises(ConflictError, match="desativado não recebe communities"):
        ucomm.add_upstream_community(
            session, up.id,
            UpstreamCommunityCreate(purpose="blackhole", value="65530:30:0"), actor="cli",
        )


def test_list_include_disabled_e_upstream_inexistente(session, up) -> None:
    uc = ucomm.add_upstream_community(
        session, up.id,
        UpstreamCommunityCreate(purpose="info", value="65530:40:0"), actor="cli",
    )
    uc.admin_status = False
    session.commit()
    assert ucomm.list_upstream_communities(session, up.id) == []
    assert len(ucomm.list_upstream_communities(session, up.id, include_disabled=True)) == 1
    with pytest.raises(NotFoundError):
        ucomm.list_upstream_communities(session, 9999)


def test_remove_upstream_community(session, up) -> None:
    uc = ucomm.add_upstream_community(
        session, up.id,
        UpstreamCommunityCreate(purpose="prepend", value="65530:50:0", regiao="norte"), actor="cli",
    )
    ucomm.remove_upstream_community(session, up.id, uc.id, actor="cli")
    assert ucomm.list_upstream_communities(session, up.id, include_disabled=True) == []
    evento = session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "upstream_community.remove")
    )
    assert evento is not None
    # M-12 (revisão final): `direcao` é campo do objeto removido (§18) e
    # ficava fora do painel "antes".
    assert evento.details["antes"] == {
        "purpose": "prepend", "value": "65530:50:0", "regiao": "norte",
        "direcao": "ambos",
    }
    with pytest.raises(NotFoundError, match="não encontrada no upstream"):
        ucomm.remove_upstream_community(session, up.id, uc.id, actor="cli")
