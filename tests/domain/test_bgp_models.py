"""Roundtrip das tabelas BGP e presença dos seeds das migrations (Tasks 1–2)."""
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


def _limpa_catalogo(db_session: Session) -> None:
    """Os catálogos não são truncados por teste (seeds de migration); este teste
    insere linhas próprias e as remove ao fim para não poluir os demais."""
    db_session.execute(
        text(
            "delete from bgp_policy_profiles where name like 'rt-%'; "
            "delete from communities where name like 'rt-%';"
        )
    )
    db_session.commit()


def _ambiente(db_session: Session) -> dict:
    """Org (ASN 64512), site e um NE8000 (ASN 64600) vinculado + circuito."""
    site = create_site(db_session, SiteCreate(name="pop-rt-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente RT", asn=64512), actor="cli"
    )
    ne = create_device(
        db_session, DeviceCreate(name="ne8k-rt", management_address="10.9.0.1", asn=64600),
        actor="cli",
    )
    sw = create_device(
        db_session, DeviceCreate(name="sw-rt", management_address="10.9.0.2"), actor="cli"
    )
    link_device(db_session, site.id, ne.id, actor="cli")
    link_device(db_session, site.id, sw.id, actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-RT", organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id,
        ),
        actor="cli",
    )
    return {"org_id": org.id, "site_id": site.id, "ne_id": ne.id, "circuit_id": circ.id}


def test_roundtrip_perfil_e_community(db_session: Session) -> None:
    _limpa_catalogo(db_session)
    try:
        perfil = models.PolicyProfile(
            name="rt-full", label="Roundtrip", direction="export", kind="produto"
        )
        com = models.Community(name="rt-blackhole", notes="roundtrip")
        db_session.add_all([perfil, com])
        db_session.commit()
        assert perfil.id and com.id

        relido = db_session.get(models.PolicyProfile, perfil.id)
        assert (relido.name, relido.direction, relido.kind) == ("rt-full", "export", "produto")
        assert relido.prefixes is None
        assert db_session.get(models.Community, com.id).name == "rt-blackhole"
    finally:
        _limpa_catalogo(db_session)


def test_seeds_dos_catalogos_presentes(db_session: Session) -> None:
    """Produtos §25.5 (exportação) e §3.6 (importação) e communities §25.6, inseridos pela migration."""
    nomes = set(db_session.scalars(select(models.PolicyProfile.name)).all())
    assert nomes == {
        "default", "default_internas", "parcial", "full", "cdn", "personalizado",
        "somente-autorizadas",
    }
    rotulos = dict(
        db_session.execute(
            select(models.PolicyProfile.name, models.PolicyProfile.label)
        ).all()
    )
    assert rotulos["default"] == "Somente default"
    assert rotulos["default_internas"] == "Default + internas"
    assert rotulos["parcial"] == "Tabela parcial"
    assert rotulos["full"] == "Full routing"
    assert rotulos["cdn"] == "CDN"
    assert rotulos["personalizado"] == "Personalizado"
    assert set(db_session.scalars(select(models.PolicyProfile.direction)).all()) == {"export", "import"}
    assert all(k == "produto" for k in db_session.scalars(
        select(models.PolicyProfile.kind)
    ).all())

    coms = set(db_session.scalars(select(models.Community.name)).all())
    assert coms == {"blackhole", "no-export", "no-advertise"}


def test_roundtrip_autorizacao(db_session: Session) -> None:
    org_id = _ambiente(db_session)["org_id"]
    auth = models.BgpPrefixAuthorization(
        organization_id=org_id, family="ipv4", prefix="200.160.0.0/22", origin="manual"
    )
    db_session.add(auth)
    db_session.commit()

    relida = db_session.get(models.BgpPrefixAuthorization, auth.id)
    assert (relida.family, relida.prefix, relida.origin) == ("ipv4", "200.160.0.0/22", "manual")


def test_roundtrip_sessao_e_associacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    sessao = models.BgpSession(
        circuit_id=env["circuit_id"], device_id=env["ne_id"], afi="ipv4",
        local_address="100.64.0.1", remote_address="100.64.0.2",
        asn_local=64600, asn_remote=64512,
    )
    db_session.add(sessao)
    db_session.commit()

    relida = db_session.get(models.BgpSession, sessao.id)
    assert relida.afi == "ipv4"
    assert relida.asn_local == 64600
    assert relida.bfd_enabled is False  # defaults do modelo

    com = db_session.scalars(
        select(models.Community).where(models.Community.name == "no-export")
    ).first()
    vinculo = models.BgpSessionCommunity(session_id=sessao.id, community_id=com.id)
    db_session.add(vinculo)
    db_session.commit()
    assert vinculo.id
