import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import create_circuit, disable_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError
from gerenet.domain.services.ipam import reservar_circuito
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


def test_reserva_dual_cria_vlan_e_p2p_v4_v6(db_session: Session) -> None:
    site_id, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')

    vlans = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id)))
    prefixos = list(
        db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    )
    assert len(vlans) == 1
    assert vlans[0].site_id == site_id
    assert 2 <= vlans[0].vid <= 4094
    assert vlans[0].family is None  # unica: VLAN sem família

    v4 = [p for p in prefixos if '.' in p.network]
    v6 = [p for p in prefixos if ':' in p.network]
    assert len(v4) == 1 and len(v6) == 1
    assert v4[0].network.endswith('/31')
    assert v6[0].network.endswith('/126')


def test_reserva_v6_deriva_do_v4_escolhido(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')

    (rede_v4,) = db_session.scalars(
        select(models.IpPrefix).where(
            models.IpPrefix.circuit_id == circ_id, models.IpPrefix.network.like('100.64.%')
        )
    )
    (rede_v6,) = db_session.scalars(
        select(models.IpPrefix).where(
            models.IpPrefix.circuit_id == circ_id, models.IpPrefix.network.like('%:%/%')
        )
    )
    # v4 primeiro livre do bloco 100.64.0.0/24 = 100.64.0.0/31 → sufixo "6400"
    assert rede_v4.network == '100.64.0.0/31'
    assert rede_v6.network == '2804:194C:1000::6400:0/126'


def test_reserva_idempotente_nao_duplica(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    reservar_circuito(db_session, circ_id, actor='cli')
    reservar_circuito(db_session, circ_id, actor='cli')  # 2ª chamada: no-op

    vlans = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id)))
    prefixos = list(
        db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    )
    assert len(vlans) == 1 and len(prefixos) == 2
    eventos = list(
        db_session.scalars(
            select(models.AuditEvent)
            .where(models.AuditEvent.type == 'circuit.reserve')
            .order_by(models.AuditEvent.id)
        )
    )
    assert len(eventos) == 2
    assert eventos[1].details['depois'] == {'repetida': True}


def test_reserva_vlan_separada_cria_duas_vlans_por_familia(db_session: Session) -> None:
    site_id, circ_id = _ambiente(db_session)
    circ = db_session.get(models.Circuit, circ_id)
    circ.vlan_mode = 'separada'
    db_session.commit()
    reservar_circuito(db_session, circ_id, actor='cli')

    vlans = list(
        db_session.scalars(
            select(models.Vlan)
            .where(models.Vlan.circuit_id == circ_id)
            .order_by(models.Vlan.family)
        )
    )
    assert [v.family for v in vlans] == ['ipv4', 'ipv6']
    assert len({v.vid for v in vlans}) == 2
    assert vlans[0].site_id == site_id


def test_reserva_qinq_marca_s_vlan(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    circ = db_session.get(models.Circuit, circ_id)
    circ.qinq = True
    db_session.commit()
    reservar_circuito(db_session, circ_id, actor='cli')
    (vlan,) = db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ_id))
    assert vlan.kind == 's_vlan'


def test_reserva_stack_ipv6_reserva_v4_de_derivacao(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    circ = db_session.get(models.Circuit, circ_id)
    circ.stack = 'ipv6'
    db_session.commit()
    reservar_circuito(db_session, circ_id, actor='cli')

    prefixos = list(
        db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    )
    assert len(prefixos) == 2  # v4 (derivação) + v6
    v4 = next(p for p in prefixos if '.' in p.network)
    assert 'deriva' in (v4.notes or '').lower()
    v6 = next(p for p in prefixos if ':' in p.network)
    assert v6.network.endswith('/126')


def test_reserva_esgota_bloco_do_site(db_session: Session) -> None:
    """Bloco /30 do site comporta 2 enlaces /31; a 3ª reserva estoura."""
    site_id, circ1_id = _ambiente(db_session, bloco='100.64.0.0/30')
    org_id = db_session.get(models.Circuit, circ1_id).organization_id
    sw2 = create_device(db_session, DeviceCreate(name='sw2', management_address='10.0.0.6'), actor='cli')
    ne3 = create_device(db_session, DeviceCreate(name='ne8k3', management_address='10.0.0.7'), actor='cli')
    link_device(db_session, site_id, sw2.id, actor='cli')
    link_device(db_session, site_id, ne3.id, actor='cli')
    circ2 = create_circuit(
        db_session,
        CircuitCreate(
            code='CIRC-0002', organization_id=org_id, site_id=site_id,
            access_device_id=sw2.id, access_port='GE0/0/2', edge_device_id=ne3.id,
        ),
        actor='cli',
    )
    circ3 = create_circuit(
        db_session,
        CircuitCreate(
            code='CIRC-0003', organization_id=org_id, site_id=site_id,
            access_device_id=sw2.id, access_port='GE0/0/3', edge_device_id=ne3.id,
        ),
        actor='cli',
    )
    reservar_circuito(db_session, circ2.id, actor='cli')
    reservar_circuito(db_session, circ3.id, actor='cli')
    with pytest.raises(ConflictError, match='esgotado'):
        reservar_circuito(db_session, circ1_id, actor='cli')


def test_reserva_circuito_desativado_rejeitado(db_session: Session) -> None:
    _, circ_id = _ambiente(db_session)
    disable_circuit(db_session, circ_id, actor='cli')
    with pytest.raises(ConflictError, match='desativado'):
        reservar_circuito(db_session, circ_id, actor='cli')


def test_reserva_v6_derivada_duplicada_rejeitada(db_session: Session) -> None:
    """Ruling 7: sufixo v6 já reservado no site falha com erro claro.

    O primeiro v4 livre de 100.64.0.0/24 é 100.64.0.0/31 → sufixo "6400" →
    rede ...::6400:0/126. Pré-ocupamos essa rede v6 e a reserva deve falhar
    em vez de violar o UNIQUE(site_id, network).
    """
    site_id, circ_id = _ambiente(db_session)
    derivada = '2804:194C:1000::6400:0/126'
    db_session.add(models.IpPrefix(site_id=site_id, network=derivada, kind='p2p'))
    db_session.commit()
    with pytest.raises(ConflictError, match='já reservado'):
        reservar_circuito(db_session, circ_id, actor='cli')
