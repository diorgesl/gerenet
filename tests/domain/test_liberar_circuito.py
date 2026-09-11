import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError
from gerenet.domain.services.ipam import liberar_circuito, reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session, bloco: str = '100.64.0.0/24') -> tuple[int, int]:
    """Site (bloco p2p override) + org + switch/NE8000 vinculados + circuito; devolve (site_id, circuit_id)."""
    site = create_site(db_session, SiteCreate(name='pop-spo-01', p2p_ipv4_block=bloco), actor='cli')
    org = create_organization(db_session, OrganizationCreate(name='Cliente X', asn=64512), actor='cli')
    sw = create_device(db_session, DeviceCreate(name='sw1', management_address='10.0.0.2'), actor='cli')
    ne = create_device(db_session, DeviceCreate(name='ne8k', management_address='10.0.0.1'), actor='cli')
    link_device(db_session, site.id, sw.id, actor='cli')
    link_device(db_session, site.id, ne.id, actor='cli')
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code='CIRC-0001', organization_id=org.id, site_id=site.id,
            access_device_id=sw.id, access_port='GE0/0/1', edge_device_id=ne.id,
        ),
        actor='cli',
    )
    return site.id, circ.id


def _reservas(db_session: Session, circ_id: int) -> tuple[list[models.Vlan], list[models.IpPrefix]]:
    vlans = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id)))
    prefixos = list(
        db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    )
    return vlans, prefixos


def test_liberar_marca_reservas_como_liberadas(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')

    circ = liberar_circuito(db_session, circ_id, actor='cli')

    vlans, prefixos = _reservas(db_session, circ_id)
    assert circ.id == circ_id
    assert vlans and all(v.status == 'liberada' for v in vlans)
    assert prefixos and all(p.status == 'liberada' for p in prefixos)
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == 'circuit.unreserve')
    )
    assert evento is not None
    assert evento.details['antes']  # vlans/prefixos liberados registrados


def test_liberar_sem_reservas_e_noop_auditado(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)

    liberar_circuito(db_session, circ_id, actor='cli')

    eventos = list(
        db_session.scalars(
            select(models.AuditEvent).where(models.AuditEvent.type == 'circuit.unreserve')
        )
    )
    assert len(eventos) == 1
    assert eventos[0].details['depois'] == {'repetida': True}


def test_liberar_idempotente(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')

    liberar_circuito(db_session, circ_id, actor='cli')
    liberar_circuito(db_session, circ_id, actor='cli')  # 2ª chamada: no-op

    vlans, prefixos = _reservas(db_session, circ_id)
    assert len(vlans) == 1 and len(prefixos) == 2
    assert all(v.status == 'liberada' for v in vlans)
    eventos = list(
        db_session.scalars(
            select(models.AuditEvent)
            .where(models.AuditEvent.type == 'circuit.unreserve')
            .order_by(models.AuditEvent.id)
        )
    )
    assert len(eventos) == 2
    assert eventos[1].details['depois'] == {'repetida': True}


def test_liberar_bloqueia_com_sessao_bgp_vinculada(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')
    circ = db_session.get(models.Circuit, circ_id)
    db_session.add(
        models.BgpSession(
            circuit_id=circ_id, device_id=circ.edge_device_id, afi='ipv4',
            local_address='100.64.0.1', remote_address='100.64.0.2', asn_remote=64512,
        )
    )
    db_session.commit()

    with pytest.raises(ConflictError, match='sess'):
        liberar_circuito(db_session, circ_id, actor='cli')

    vlans, prefixos = _reservas(db_session, circ_id)
    assert all(v.status == 'reservada' for v in vlans)  # nada foi liberado
    assert all(p.status == 'reservada' for p in prefixos)


def _sessao_bgp(
    db_session: Session, circ_id: int, *, admin_status: bool = True, remote: str = '100.64.0.2'
) -> models.BgpSession:
    circ = db_session.get(models.Circuit, circ_id)
    sessao = models.BgpSession(
        circuit_id=circ_id, device_id=circ.edge_device_id, afi='ipv4',
        local_address='100.64.0.1', remote_address=remote, asn_remote=64512,
        admin_status=admin_status,
    )
    db_session.add(sessao)
    db_session.commit()
    return sessao


def test_liberar_permitido_com_sessao_bgp_desativada(db_session: Session) -> None:
    """Desativar é o caminho possível (não há remoção de sessão): não pode bloquear."""
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')
    _sessao_bgp(db_session, circ_id, admin_status=False)

    liberar_circuito(db_session, circ_id, actor='cli')

    vlans, prefixos = _reservas(db_session, circ_id)
    assert vlans and all(v.status == 'liberada' for v in vlans)
    assert prefixos and all(p.status == 'liberada' for p in prefixos)


def test_liberar_bloqueia_com_sessao_ativa_entre_desativadas(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')
    _sessao_bgp(db_session, circ_id, admin_status=False, remote='100.64.0.2')
    _sessao_bgp(db_session, circ_id, admin_status=True, remote='100.64.0.6')

    with pytest.raises(ConflictError, match='ativa'):
        liberar_circuito(db_session, circ_id, actor='cli')

    vlans, prefixos = _reservas(db_session, circ_id)
    assert all(v.status == 'reservada' for v in vlans)
    assert all(p.status == 'reservada' for p in prefixos)


def test_liberar_permite_reuso_do_vid_e_do_par_v4(db_session: Session) -> None:
    site_id, circ1_id = _ambiente(db_session)
    reservar_circuito(db_session, circ1_id, actor='cli')
    (vlan_antiga,) = db_session.scalars(
        select(models.Vlan).where(models.Vlan.circuit_id == circ1_id)
    )
    (v4_antigo,) = db_session.scalars(
        select(models.IpPrefix).where(
            models.IpPrefix.circuit_id == circ1_id, models.IpPrefix.network.like('100.64.%')
        )
    )
    liberar_circuito(db_session, circ1_id, actor='cli')

    sw2 = create_device(db_session, DeviceCreate(name='sw2', management_address='10.0.0.6'), actor='cli')
    ne3 = create_device(db_session, DeviceCreate(name='ne8k3', management_address='10.0.0.7'), actor='cli')
    link_device(db_session, site_id, sw2.id, actor='cli')
    link_device(db_session, site_id, ne3.id, actor='cli')
    org_id = db_session.get(models.Circuit, circ1_id).organization_id
    circ2 = create_circuit(
        db_session,
        CircuitCreate(
            code='CIRC-0002', organization_id=org_id,
            site_id=site_id, access_device_id=sw2.id, access_port='GE0/0/2',
            edge_device_id=ne3.id,
        ),
        actor='cli',
    )
    reservar_circuito(db_session, circ2.id, actor='cli')

    # Mesmo VID e mesmo par v4 voltam a ser alocados (linhas liberadas ignoradas).
    (vlan_nova,) = db_session.scalars(
        select(models.Vlan).where(models.Vlan.circuit_id == circ2.id)
    )
    (v4_novo,) = db_session.scalars(
        select(models.IpPrefix).where(
            models.IpPrefix.circuit_id == circ2.id, models.IpPrefix.network.like('100.64.%')
        )
    )
    assert vlan_nova.vid == vlan_antiga.vid
    assert vlan_nova.status == 'reservada'
    assert v4_novo.network == v4_antigo.network
    # As linhas antigas continuam existindo (rastro), apenas liberadas.
    assert vlan_antiga.status == 'liberada'


def test_re_reserva_apos_liberar_cria_linhas_novas(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')
    liberar_circuito(db_session, circ_id, actor='cli')

    reservar_circuito(db_session, circ_id, actor='cli')  # não é no-op

    vlans, prefixos = _reservas(db_session, circ_id)
    assert len(vlans) == 2  # 1 liberada + 1 nova reservada
    assert len(prefixos) == 4
    assert sum(1 for v in vlans if v.status == 'reservada') == 1
    eventos = list(
        db_session.scalars(
            select(models.AuditEvent)
            .where(models.AuditEvent.type == 'circuit.reserve')
            .order_by(models.AuditEvent.id)
        )
    )
    assert len(eventos) == 2
    assert 'repetida' not in eventos[1].details.get('depois', {})
