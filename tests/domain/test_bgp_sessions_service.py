import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services.bgp_sessions import (
    create_session,
    get_session,
    list_sessions,
)
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> dict:
    """Org (ASN 64512), site, switch e 2 NE8000 (ASNs 64600/64601) no site."""
    site = create_site(db_session, SiteCreate(name="pop-bgp-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente BGP", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-bgp", management_address="10.8.0.2"), actor="cli")
    ne1 = create_device(
        db_session, DeviceCreate(name="ne8k-bgp1", management_address="10.8.0.1", asn=64600),
        actor="cli",
    )
    ne2 = create_device(
        db_session, DeviceCreate(name="ne8k-bgp2", management_address="10.8.0.3", asn=64601),
        actor="cli",
    )
    for dev in (sw, ne1, ne2):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne1_id": ne1.id, "ne2_id": ne2.id}


def _circuito(db_session: Session, env: dict, *, code: str, edge_id: int, vrf: str | None = None) -> int:
    """Circuito no ambiente padrão; devolve o id."""
    return create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1", edge_device_id=edge_id,
            vrf=vrf,
        ),
        actor="cli",
    ).id


def _sessao_data(
    env: dict, circuit_id: int, edge_id: int, *, afi: str = "ipv4",
    local: str = "100.64.0.1", remote: str = "100.64.0.2", **extra,
) -> BgpSessionCreate:
    base = {
        "circuit_id": circuit_id,
        "device_id": edge_id,
        "afi": afi,
        "local_address": local,
        "remote_address": remote,
    }
    base.update(extra)
    return BgpSessionCreate(**base)


def test_cria_sessao_com_defaults_de_asn(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0001", edge_id=env["ne1_id"])
    sessao = create_session(
        db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli"
    )
    # defaults: asn_local = device.asn (64600); asn_remote = organization.asn (64512)
    assert sessao.asn_local == 64600
    assert sessao.asn_remote == 64512
    assert sessao.bfd_enabled is False
    assert [s.id for s in list_sessions(db_session)] == [sessao.id]


def test_cria_com_overrides_e_filtros_de_lista(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0002", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ2 = _circuito(db_session, env, code="CIRC-0003", edge_id=env["ne2_id"], vrf="CLIENTE-B")
    export = list_policy_profiles(db_session, direction="export")[0]  # "cdn" (order by name)
    sessao = create_session(
        db_session,
        _sessao_data(
            env, circ1, env["ne1_id"], afi="ipv6",
            local="2804:194C::1", remote="2804:194C::2",
            asn_local=64650, maximum_prefix=1000, maximum_prefix_threshold=80,
            prepend=2, shutdown=True, export_profile_id=export.id,
            description="sessão v6",
        ),
        actor="cli",
    )
    assert sessao.asn_local == 64650
    assert sessao.export_profile_id == export.id
    assert [s.id for s in list_sessions(db_session, device_id=env["ne1_id"])] == [sessao.id]
    assert list_sessions(db_session, circuit_id=circ2) == []


def test_device_fora_do_circuito_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0004", edge_id=env["ne1_id"])
    # ne2 não é edge/backup_edge do circuito
    with pytest.raises(ValidationError, match="não é edge/backup_edge"):
        create_session(db_session, _sessao_data(env, circ_id, env["ne2_id"]), actor="cli")


def test_backup_edge_aceito(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0005", organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne1_id"], backup_edge_device_id=env["ne2_id"],
        ),
        actor="cli",
    ).id
    sessao = create_session(
        db_session, _sessao_data(env, circ_id, env["ne2_id"], local="100.64.1.1", remote="100.64.1.2"),
        actor="cli",
    )
    assert sessao.device_id == env["ne2_id"]


def test_endereco_de_familia_errada_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0006", edge_id=env["ne1_id"])
    with pytest.raises(ValidationError, match="não é um endereço ipv4"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], remote="2804:194C::2"),
            actor="cli",
        )
    with pytest.raises(ValidationError, match="local_address inválido"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], local="banana"), actor="cli"
        )
    with pytest.raises(ValidationError, match="não é um endereço ipv6"):
        create_session(
            db_session,
            _sessao_data(
                env, circ_id, env["ne1_id"], afi="ipv6",
                local="2804:194C::1", remote="200.160.0.2",
            ),
            actor="cli",
        )
    with pytest.raises(ValidationError, match="não é um endereço ipv6"):
        create_session(
            db_session,
            _sessao_data(
                env, circ_id, env["ne1_id"], afi="ipv6", local="2804:194C::1",
                remote="2804:194C::2", source_address="200.160.0.1",
            ),
            actor="cli",
        )


def test_duplicidade_mesmo_device_vrf_afi(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0007", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    # mesmo device+VRF+afi em outro circuito → conflito
    circ2 = _circuito(db_session, env, code="CIRC-0008", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    with pytest.raises(ConflictError, match="Já existe sessão ipv4 ativa no equipamento ne8k-bgp1"):
        create_session(db_session, _sessao_data(env, circ2, env["ne1_id"]), actor="cli")


def test_vrfs_diferentes_convivem_no_mesmo_device(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_pub = _circuito(db_session, env, code="CIRC-0009", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ_pub, env["ne1_id"]), actor="cli")
    circ_vrf = _circuito(db_session, env, code="CIRC-0010", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    sessao = create_session(
        db_session, _sessao_data(env, circ_vrf, env["ne1_id"], local="100.64.0.5", remote="100.64.0.6"),
        actor="cli",
    )
    assert sessao.id  # VRF diferente não colide com a pública


def test_duplicidade_mensagem_vrf_publica(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0011", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    circ2 = _circuito(db_session, env, code="CIRC-0012", edge_id=env["ne1_id"])
    with pytest.raises(ConflictError, match=r"VRF pública"):
        create_session(db_session, _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.9", remote="100.64.0.10"), actor="cli")


def test_duplicidade_do_par_e_global_inclusive_invertido(db_session: Session) -> None:
    env = _ambiente(db_session)
    # par em devices diferentes: não colide por linha, colide por par (global)
    circ1 = _circuito(db_session, env, code="CIRC-0013", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    circ2 = _circuito(db_session, env, code="CIRC-0014", edge_id=env["ne2_id"])
    with pytest.raises(ConflictError, match="Já existe sessão ativa entre 100.64.0.1 e 100.64.0.2"):
        create_session(db_session, _sessao_data(env, circ2, env["ne2_id"]), actor="cli")
    # par invertido (local/remoto trocados) também colide
    with pytest.raises(ConflictError, match="Já existe sessão ativa entre 100.64.0.2 e 100.64.0.1"):
        create_session(
            db_session,
            _sessao_data(env, circ2, env["ne2_id"], local="100.64.0.2", remote="100.64.0.1"),
            actor="cli",
        )


def test_afi_diferente_nao_colide(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0015", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(
            env, circ1, env["ne1_id"], afi="ipv6", local="2804:194C::1", remote="2804:194C::2",
        ),
        actor="cli",
    )
    assert sessao.afi == "ipv6"  # dual stack = 2 registros (spec §6.3)


def test_asn_local_do_device_ausente_exige_override(db_session: Session) -> None:
    env = _ambiente(db_session)
    ne_sem_asn = create_device(
        db_session, DeviceCreate(name="ne8k-semasn", management_address="10.8.0.9"), actor="cli"
    )
    link_device(db_session, env["site_id"], ne_sem_asn.id, actor="cli")
    circ_id = _circuito(db_session, env, code="CIRC-0016", edge_id=ne_sem_asn.id)
    with pytest.raises(ValidationError, match="não possui ASN; informe asn_local"):
        create_session(db_session, _sessao_data(env, circ_id, ne_sem_asn.id), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_id, ne_sem_asn.id, asn_local=64699, local="100.64.0.13", remote="100.64.0.14"),
        actor="cli",
    )
    assert sessao.asn_local == 64699


def test_organizacao_sem_asn_exige_asn_remote(db_session: Session) -> None:
    env = _ambiente(db_session)
    org_sem_asn = create_organization(
        db_session, OrganizationCreate(name="Cliente Sem ASN"), actor="cli"
    )
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0017", organization_id=org_sem_asn.id, site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1", edge_device_id=env["ne1_id"],
        ),
        actor="cli",
    ).id
    with pytest.raises(ValidationError, match="não possui ASN; informe asn_remote"):
        create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], asn_remote=64530, local="100.64.0.17", remote="100.64.0.18"),
        actor="cli",
    )
    assert sessao.asn_remote == 64530


def test_asn_remote_diverge_da_organizacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0018", edge_id=env["ne1_id"])
    with pytest.raises(ValidationError, match="difere do ASN 64512"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], asn_remote=64599), actor="cli"
        )


def test_asn_invalido_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0019", edge_id=env["ne1_id"])
    with pytest.raises(ValidationError, match="ASN inválido ou reservado: 23456"):
        create_session(
            db_session,
            _sessao_data(env, circ_id, env["ne1_id"], asn_local=23456, local="100.64.0.21", remote="100.64.0.22"),
            actor="cli",
        )


def test_perfil_de_direction_errada_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0020", edge_id=env["ne1_id"])
    export = list_policy_profiles(db_session, direction="export")[0]
    # catálogo só tem exportações no ciclo A → import_profile_id nunca aceita export
    with pytest.raises(ValidationError, match="não pode ser o perfil de importação"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], import_profile_id=export.id),
            actor="cli",
        )
    with pytest.raises(NotFoundError, match="Perfil 9999 não encontrado"):
        create_session(
            db_session, _sessao_data(env, circ_id, env["ne1_id"], export_profile_id=9999),
            actor="cli",
        )


def test_circuito_desativado_nao_recebe_sessao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0021", edge_id=env["ne1_id"])
    from gerenet.domain.services.circuits import disable_circuit

    disable_circuit(db_session, circ_id, actor="cli")
    with pytest.raises(ConflictError, match="desativado não recebe sessões"):
        create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")


def test_audita_criacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0022", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.create"
    assert evento.details["objeto_id"] == sessao.id
    assert evento.details["depois"]["asn_remote"] == 64512  # default resolvido no dump


def test_get_e_sessao_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Sessão BGP 9999 não encontrada"):
        get_session(db_session, 9999)
