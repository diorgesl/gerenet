import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    BgpSessionUpdate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
    UpstreamCreate,
)
from gerenet.domain.services.bgp_sessions import (
    add_community,
    create_session,
    disable_session,
    get_session,
    list_sessions,
    remove_community,
    set_password,
    update_session,
)
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.communities import list_communities
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.sites import create_site, link_device
from gerenet.domain.services.upstreams import create_upstream, vincular_circuito


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


def test_varias_sessoes_no_mesmo_device_vrf_familia(db_session: Session) -> None:
    """Dois enlaces no mesmo equipamento, VRF e família, com peers distintos."""
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0007", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ2 = _circuito(db_session, env, code="CIRC-0008", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    a = create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    b = create_session(
        db_session,
        _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.5", remote="100.64.0.6"),
        actor="cli",
    )
    ativas = {s.id for s in list_sessions(db_session, device_id=env["ne1_id"])}
    assert ativas == {a.id, b.id}


def test_mesmo_peer_no_mesmo_device_vrf_colide(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0040", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ2 = _circuito(db_session, env, code="CIRC-0041", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    # o mesmo endereço remoto, em outro circuito e na mesma VRF, é o mesmo peer
    with pytest.raises(
        ConflictError,
        match=r"Já existe sessão ativa no equipamento ne8k-bgp1 para o peer 100\.64\.0\.2",
    ):
        create_session(
            db_session,
            _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.9", remote="100.64.0.2"),
            actor="cli",
        )


def test_mesmo_peer_em_vrf_diferente_convive(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_a = _circuito(db_session, env, code="CIRC-0042", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ_b = _circuito(db_session, env, code="CIRC-0043", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ_a, env["ne1_id"]), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_b, env["ne1_id"], local="100.64.0.9", remote="100.64.0.2"),
        actor="cli",
    )
    assert sessao.id  # a VRF é parte da identidade do peer no VRP


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
    with pytest.raises(
        ConflictError,
        match=r"Já existe sessão ativa no equipamento ne8k-bgp1 para o peer 100\.64\.0\.2 "
        r"\(VRF pública\)",
    ):
        create_session(
            db_session,
            _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.9", remote="100.64.0.2"),
            actor="cli",
        )


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


def test_update_altera_campos_e_audita_delta(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0030", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    atualizada = update_session(
        db_session, sessao.id, BgpSessionUpdate(description="sessão principal", med=50),
        actor="cli",
    )
    assert atualizada.description == "sessão principal"
    assert atualizada.med == 50
    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.update"
    assert evento.details["antes"] == {"description": None, "med": None}
    assert evento.details["depois"] == {"description": "sessão principal", "med": 50}


def test_update_null_explicito_em_campo_obrigatorio_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0031", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    for campo in ("circuit_id", "device_id", "afi", "local_address", "remote_address", "asn_local", "asn_remote"):
        with pytest.raises(ValidationError, match=f"{campo} é obrigatório"):
            update_session(db_session, sessao.id, BgpSessionUpdate(**{campo: None}), actor="cli")


def test_update_null_explicito_limpa_campo_opcional(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0032", edge_id=env["ne1_id"])
    sessao = create_session(
        db_session,
        _sessao_data(
            env, circ_id, env["ne1_id"], description="com descrição",
            source_address="100.64.0.1", maximum_prefix=500,
        ),
        actor="cli",
    )
    atualizada = update_session(
        db_session, sessao.id,
        BgpSessionUpdate(description=None, source_address=None, maximum_prefix=None),
        actor="cli",
    )
    assert atualizada.description is None
    assert atualizada.source_address is None
    assert atualizada.maximum_prefix is None


def test_update_troca_device_para_backup_e_revalida(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-0033", organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne1_id"], backup_edge_device_id=env["ne2_id"],
        ),
        actor="cli",
    ).id
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    atualizada = update_session(db_session, sessao.id, BgpSessionUpdate(device_id=env["ne2_id"]), actor="cli")
    assert atualizada.device_id == env["ne2_id"]
    # asn_local continua o da criação (64600) — snapshot da intenção, não re-deriva


def test_update_para_device_fora_do_circuito_rejeitado(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0034", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    with pytest.raises(ValidationError, match="não é edge/backup_edge"):
        update_session(db_session, sessao.id, BgpSessionUpdate(device_id=env["ne2_id"]), actor="cli")


def test_update_colide_com_outra_sessao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_a = _circuito(db_session, env, code="CIRC-0035", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    create_session(db_session, _sessao_data(env, circ_a, env["ne1_id"]), actor="cli")
    # segunda sessão, mesmo equipamento e VRF, com peer próprio
    circ_b = _circuito(db_session, env, code="CIRC-0036", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    sessao_b = create_session(
        db_session,
        _sessao_data(env, circ_b, env["ne1_id"], local="100.64.2.1", remote="100.64.2.2"),
        actor="cli",
    )
    # …mudar o peer da sessão B para o da sessão A colide
    with pytest.raises(
        ConflictError,
        match=r"Já existe sessão ativa no equipamento ne8k-bgp1 para o peer 100\.64\.0\.2",
    ):
        update_session(
            db_session, sessao_b.id, BgpSessionUpdate(remote_address="100.64.0.2"), actor="cli"
        )


def test_update_mantem_a_propria_sessao_fora_da_colisao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0037", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    # reenviar os próprios valores não colide consigo mesma
    atualizada = update_session(
        db_session, sessao.id,
        BgpSessionUpdate(local_address="100.64.0.1", remote_address="100.64.0.2",
                         description="no-op de conteúdo"),
        actor="cli",
    )
    assert atualizada.description == "no-op de conteúdo"


def test_disable_idempotente_audita_uma_transicao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0038", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    disable_session(db_session, sessao.id, actor="cli")
    assert get_session(db_session, sessao.id).admin_status is False
    assert list_sessions(db_session) == []
    assert [s.id for s in list_sessions(db_session, include_disabled=True)] == [sessao.id]

    disable_session(db_session, sessao.id, actor="cli")  # repetido: no-op sem evento
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "bgp_session.disable")
    ).all()
    assert len(eventos) == 1


def test_add_remove_community_com_auditoria(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0039", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    com = list_communities(db_session)[0]

    add_community(db_session, sessao.id, com.id, actor="cli")
    add_community(db_session, sessao.id, com.id, actor="cli")  # repetida: no-op sem evento
    vinculos = db_session.scalars(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == sessao.id
        )
    ).all()
    assert len(vinculos) == 1

    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.add_community"
    assert evento.details["depois"] == {"community_id": com.id, "community": com.name}

    remove_community(db_session, sessao.id, com.id, actor="cli")
    assert db_session.scalars(
        select(models.BgpSessionCommunity).where(
            models.BgpSessionCommunity.session_id == sessao.id
        )
    ).all() == []
    remove_community(db_session, sessao.id, com.id, actor="cli")  # repetido: no-op
    evento = db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id.desc())
    ).all()[0]
    assert evento.type == "bgp_session.remove_community"
    assert evento.details["antes"] == {"community_id": com.id, "community": com.name}
    assert evento.details["depois"] is None


def test_community_inexistente_na_associacao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-0040", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    with pytest.raises(NotFoundError, match="Community 9999 não encontrada"):
        add_community(db_session, sessao.id, 9999, actor="cli")


def test_update_muda_para_org_sem_asn_exige_asn_remote(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-A", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")

    org_sem_asn = create_organization(
        db_session, OrganizationCreate(name="Cliente Sem ASN"), actor="cli"
    )
    circ2 = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-B",
            organization_id=org_sem_asn.id,
            site_id=env["site_id"],
            access_device_id=env["sw_id"],
            access_port="GE0/0/2",
            edge_device_id=env["ne1_id"],
        ),
        actor="cli",
    ).id
    with pytest.raises(ValidationError, match="não possui ASN; informe asn_remote"):
        update_session(db_session, sessao.id, BgpSessionUpdate(circuit_id=circ2), actor="cli")
    # com asn_remote explícito a troca passa
    atualizada = update_session(
        db_session,
        sessao.id,
        BgpSessionUpdate(circuit_id=circ2, asn_remote=64530),
        actor="cli",
    )
    assert atualizada.circuit_id == circ2
    assert atualizada.asn_remote == 64530


def test_set_password_registra_ref_e_audita(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-PW", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    assert sessao.has_password is False
    caminho = f"gerenet/bgp-sessions/{sessao.id}/password"

    atualizada = set_password(db_session, sessao.id, actor="cli", path=caminho)
    assert atualizada.password_ref == caminho
    assert atualizada.has_password is True

    tipos = [
        e.type
        for e in db_session.scalars(
            select(models.AuditEvent)
            .where(models.AuditEvent.type.in_(["bgp_session.create", "bgp_session.password_set"]))
            .order_by(models.AuditEvent.id)
        )
    ]
    assert tipos == ["bgp_session.create", "bgp_session.password_set"]
    (evento,) = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "bgp_session.password_set")
    )
    assert evento.details["antes"] == {"has_password": False}
    assert evento.details["depois"] == {"has_password": True}


def test_set_password_troca_audita_novamente(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-PW2", edge_id=env["ne1_id"])
    sessao = create_session(db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli")
    caminho = f"gerenet/bgp-sessions/{sessao.id}/password"
    set_password(db_session, sessao.id, actor="cli", path=caminho)
    set_password(db_session, sessao.id, actor="cli", path=caminho)
    tipos = [
        e.type
        for e in db_session.scalars(
            select(models.AuditEvent)
            .where(models.AuditEvent.type.in_(["bgp_session.create", "bgp_session.password_set"]))
            .order_by(models.AuditEvent.id)
        )
    ]
    assert tipos == [
        "bgp_session.create", "bgp_session.password_set", "bgp_session.password_set",
    ]
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "bgp_session.password_set")
    ).all()
    assert [e.details["antes"] for e in eventos] == [{"has_password": False}, {"has_password": True}]
    assert [e.details["depois"] for e in eventos] == [{"has_password": True}, {"has_password": True}]


def test_set_password_sessao_inexistente_da_404(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="não encontrada"):
        set_password(db_session, 9999, actor="cli", path="gerenet/bgp-sessions/9999/password")


def test_sessao_aceita_perfil_de_importacao_seedado(db_session: Session) -> None:
    from gerenet.domain.services.policy_profiles import list_policy_profiles

    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-IMP-SEED", edge_id=env["ne1_id"])
    perfil_import = list_policy_profiles(db_session, direction="import")[0]
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], import_profile_id=perfil_import.id),
        actor="cli",
    )
    assert sessao.import_profile_id == perfil_import.id


def test_sessao_de_circuito_com_upstream_nao_anuncia_a_default(db_session: Session) -> None:
    """§3.5: o anúncio é do caminho de cliente. O render despacha pelo vínculo,
    e numa sessão de upstream o comando significaria anunciar a default à
    operadora — o inverso do que o campo quer dizer ali."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-DRA", edge_id=env["ne1_id"])
    operadora = create_organization(
        db_session, OrganizationCreate(name="Operadora DRA", asn=64513, kind="operadora"),
        actor="cli",
    )
    up = create_upstream(
        db_session, UpstreamCreate(name="up-dra", tipo="transito", organization_id=operadora.id),
        actor="cli",
    )
    vincular_circuito(db_session, up.id, circ_id, papel="principal", ordem=1, actor="cli")

    with pytest.raises(ValidationError, match="default-route-advertise"):
        create_session(
            db_session,
            _sessao_data(env, circ_id, env["ne1_id"], default_route_advertise=True),
            actor="cli",
        )
    # E o caminho de cliente continua aceitando o anúncio.
    sessao_id = create_session(
        db_session,
        _sessao_data(env, _circuito(db_session, env, code="CIRC-DRA-OK", edge_id=env["ne1_id"]),
                     env["ne1_id"], default_route_advertise=True),
        actor="cli",
    ).id
    assert db_session.get(models.BgpSession, sessao_id).default_route_advertise is True


def test_nao_anuncia_default_em_upstream_nem_pelo_update(db_session: Session) -> None:
    """A guarda vale para o PATCH também: o caminho de volta é desmarcar antes."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-DRA-UP", edge_id=env["ne1_id"])
    sessao_id = create_session(
        db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli"
    ).id
    operadora = create_organization(
        db_session, OrganizationCreate(name="Operadora DRA2", asn=64514, kind="operadora"),
        actor="cli",
    )
    up = create_upstream(
        db_session, UpstreamCreate(name="up-dra2", tipo="transito", organization_id=operadora.id),
        actor="cli",
    )
    vincular_circuito(db_session, up.id, circ_id, papel="principal", ordem=1, actor="cli")

    with pytest.raises(ValidationError, match="default-route-advertise"):
        update_session(
            db_session, sessao_id, BgpSessionUpdate(default_route_advertise=True), actor="cli"
        )


def _operadora_e_upstream(db_session: Session, *, nome: str, asn: int) -> int:
    """Operadora com upstream criado; devolve o id do upstream."""
    operadora = create_organization(
        db_session, OrganizationCreate(name=nome, asn=asn, kind="operadora"), actor="cli"
    )
    return create_upstream(
        db_session, UpstreamCreate(name=f"up-{asn}", tipo="transito",
                                   organization_id=operadora.id),
        actor="cli",
    ).id


def test_reparo_desliga_o_anuncio_e_destrava_o_vinculo(db_session: Session) -> None:
    """A saída existe de verdade: com a sessão anunciando, o vínculo é recusado, e
    enquanto o vínculo não existe o anúncio é editável — desmarcá-lo passa pela
    guarda, que só recusa ligar, e o vínculo então fecha. Nada é normalizado em
    silêncio: quem desliga é o operador."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-DRA-REPARO", edge_id=env["ne1_id"])
    sessao_id = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], default_route_advertise=True),
        actor="cli",
    ).id
    up_id = _operadora_e_upstream(db_session, nome="Operadora DRA-REPARO", asn=64517)

    with pytest.raises(ValidationError, match="default-route-advertise"):
        vincular_circuito(db_session, up_id, circ_id, papel="principal", ordem=1, actor="cli")

    update_session(
        db_session, sessao_id, BgpSessionUpdate(default_route_advertise=False), actor="cli"
    )
    vincular_circuito(db_session, up_id, circ_id, papel="principal", ordem=1, actor="cli")

    assert db_session.get(models.BgpSession, sessao_id).default_route_advertise is False
    assert db_session.scalar(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.circuit_id == circ_id)) is not None


def test_patch_de_outro_campo_em_sessao_que_anuncia_nao_e_recusado(db_session: Session) -> None:
    """I-1: a guarda decide sobre o estado resultante, mas só quando o payload pode
    mudá-lo. A sessão que anuncia e foi parar num circuito vinculado depois — o
    vínculo não olhava para ela — tem de continuar editável; antes, o PATCH de
    qualquer campo morria na guarda e a sessão ficava congelada."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-DRA-EDIT", edge_id=env["ne1_id"])
    sessao_id = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], default_route_advertise=True),
        actor="cli",
    ).id
    # o estado pré-existente nasce direto no banco: o serviço agora o recusa
    up_id = _operadora_e_upstream(db_session, nome="Operadora DRA-EDIT", asn=64515)
    db_session.add(models.UpstreamCircuit(upstream_id=up_id, circuit_id=circ_id,
                                          papel="principal", ordem=1))
    db_session.commit()

    update_session(db_session, sessao_id, BgpSessionUpdate(description="depois"), actor="cli")

    assert db_session.get(models.BgpSession, sessao_id).description == "depois"


def test_patch_que_move_a_sessao_para_circuito_vinculado_e_recusado(db_session: Session) -> None:
    """O `or "circuit_id" in mudancas` da guarda não é folga: sem ele um PATCH que
    só move a sessão, com o anúncio gravado, criaria o estado proibido sem passar
    pela guarda."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-DRA-MOVE", edge_id=env["ne1_id"])
    circ_up = _circuito(db_session, env, code="CIRC-DRA-MOVE-UP", edge_id=env["ne1_id"],
                        vrf="CLIENTE-MOVE")
    sessao_id = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], default_route_advertise=True),
        actor="cli",
    ).id
    up_id = _operadora_e_upstream(db_session, nome="Operadora DRA-MOVE", asn=64516)
    vincular_circuito(db_session, up_id, circ_up, papel="principal", ordem=1, actor="cli")

    with pytest.raises(ValidationError, match="default-route-advertise"):
        update_session(db_session, sessao_id, BgpSessionUpdate(circuit_id=circ_up), actor="cli")


def test_updates_de_default_route_e_politica(db_session: Session) -> None:
    """§3.6/§4.3: os três campos entram pelo PATCH, e `null` explícito limpa o
    nome importado (a revisão da adoção conta com isso para voltar ao §25.4)."""
    env = _ambiente(db_session)
    sessao_id = create_session(
        db_session,
        _sessao_data(env, _circuito(db_session, env, code="CIRC-POL", edge_id=env["ne1_id"]),
                     env["ne1_id"]),
        actor="cli",
    ).id

    update_session(
        db_session, sessao_id,
        BgpSessionUpdate(import_route_policy="RP-LIDO", export_route_policy="RP-LIDO-OUT"),
        actor="cli",
    )
    sessao = db_session.get(models.BgpSession, sessao_id)
    assert (sessao.import_route_policy, sessao.export_route_policy) == ("RP-LIDO", "RP-LIDO-OUT")

    update_session(db_session, sessao_id, BgpSessionUpdate(import_route_policy=None), actor="cli")
    assert db_session.get(models.BgpSession, sessao_id).import_route_policy is None


def test_o_nome_de_politica_recusa_o_que_o_vrp_nao_aceita(db_session: Session) -> None:
    """§4.5: o limite de 63 e a grafia são validados no schema."""
    env = _ambiente(db_session)
    for invalido in ("RP-COM-ESPAÇO", "X" * 64, "RP/INVALIDA"):
        with pytest.raises(PydanticValidationError):
            _sessao_data(
                env, _circuito(db_session, env, code=f"CIRC-{len(invalido)}",
                               edge_id=env["ne1_id"]),
                env["ne1_id"], import_route_policy=invalido,
            )


def test_recusa_o_mesmo_nome_nas_duas_politicas(db_session: Session) -> None:
    """R2: `route-policy <nome>` é UM objeto no VRP, sem direção. O mesmo nome
    no import e no export faz o render emitir duas definições sob o mesmo
    cabeçalho com corpos que se somam no nó 10 — config errada e silenciosa,
    que a guarda fecha na entrada."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-POLIGUAL", edge_id=env["ne1_id"])
    with pytest.raises(ValidationError, match="dois nomes distintos"):
        create_session(
            db_session,
            _sessao_data(env, circ_id, env["ne1_id"],
                         import_route_policy="RP-MESMA", export_route_policy="RP-MESMA"),
            actor="cli",
        )


def test_update_recusa_o_mesmo_nome_contra_o_valor_guardado(db_session: Session) -> None:
    """R2: o PATCH julga o nome que chega contra o OUTRO lado guardado — o
    namespace é da sessão mesclada, não do payload."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-POLIGUAL-UP", edge_id=env["ne1_id"])
    sessao_id = create_session(
        db_session,
        _sessao_data(env, circ_id, env["ne1_id"], export_route_policy="RP-MESMA-UP"),
        actor="cli",
    ).id

    with pytest.raises(ValidationError, match="dois nomes distintos"):
        update_session(
            db_session, sessao_id, BgpSessionUpdate(import_route_policy="RP-MESMA-UP"),
            actor="cli",
        )
    assert db_session.get(models.BgpSession, sessao_id).import_route_policy is None


def test_limpar_uma_das_politicas_nao_esbarra_na_guarda(db_session: Session) -> None:
    """R2: a guarda só olha nomes preenchidos — `null` explícito num dos lados é
    o caminho de volta de quem tem os dois iguais e continua passando."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-POLLIMPA", edge_id=env["ne1_id"])
    sessao_id = create_session(
        db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli"
    ).id
    # estado que a guarda não deixa nascer pelo serviço, escrito à mão
    sessao = db_session.get(models.BgpSession, sessao_id)
    sessao.import_route_policy = "RP-IGUAL"
    sessao.export_route_policy = "RP-IGUAL"
    db_session.commit()

    update_session(db_session, sessao_id, BgpSessionUpdate(import_route_policy=None), actor="cli")
    sessao = db_session.get(models.BgpSession, sessao_id)
    assert (sessao.import_route_policy, sessao.export_route_policy) == (None, "RP-IGUAL")


def test_politicas_sem_colisao_nao_disparam_a_guarda(db_session: Session) -> None:
    """R2: o caso comum — as duas nulas — e o de uma só por direção passam."""
    env = _ambiente(db_session)
    circ_id = _circuito(db_session, env, code="CIRC-POLSOUMA", edge_id=env["ne1_id"])
    sessao_id = create_session(
        db_session, _sessao_data(env, circ_id, env["ne1_id"]), actor="cli"
    ).id
    assert db_session.get(models.BgpSession, sessao_id).import_route_policy is None

    update_session(
        db_session, sessao_id, BgpSessionUpdate(import_route_policy="RP-SO-IMPORT"), actor="cli"
    )
    update_session(
        db_session, sessao_id, BgpSessionUpdate(export_route_policy="RP-SO-EXPORT"), actor="cli"
    )
    sessao = db_session.get(models.BgpSession, sessao_id)
    assert (sessao.import_route_policy, sessao.export_route_policy) == (
        "RP-SO-IMPORT", "RP-SO-EXPORT",
    )
