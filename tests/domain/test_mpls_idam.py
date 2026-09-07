"""IDAM MPLS — fase 4, spec §4 (sem tabela allocations: UNIQUE + helpers)."""
import pytest

from gerenet.domain.schemas import DeviceCreate, MplsDomainCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError
from gerenet.domain.services.ipam import _primeiro_vid
from gerenet.domain.services.mpls import (
    create_domain,
    proximo_vc_id,
    proximo_vsi_id,
    reservar_vlan_ac,
)
from gerenet.domain.services.sites import create_site


def _dominio(db_session):
    return create_domain(db_session, MplsDomainCreate(name="idam"), actor="cli")


def test_proximo_vc_id_sequencial(db_session):
    dom = _dominio(db_session)
    assert proximo_vc_id(db_session, dom.id) == 100
    assert proximo_vc_id(db_session, dom.id, inicio=200) == 200
    assert proximo_vc_id(db_session, dom.id, inicio=200) == 200  # helper é imutável por construção


def test_proximo_vc_id_pula_ocupados(db_session):
    from gerenet.domain import models
    dom = _dominio(db_session)
    db_session.add(models.L2vcService(domain_id=dom.id, vc_id=101, name="a"))
    db_session.add(models.L2vcService(domain_id=dom.id, vc_id=103, name="b"))
    db_session.commit()
    assert proximo_vc_id(db_session, dom.id, inicio=100) in (100, 102, 104)


def test_proximo_vsi_id(db_session):
    dom = _dominio(db_session)
    assert proximo_vsi_id(db_session, dom.id, inicio=500) == 500


def test_reservar_vlan_ac_por_device(db_session):
    site = create_site(db_session, SiteCreate(name="pop-idam"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-id", management_address="10.0.0.41", site_id=site.id), actor="cli")
    vlan = reservar_vlan_ac(db_session, device_id=dev.id, vid=777, actor="cli")
    assert vlan.kind == "mpls_ac"
    assert vlan.site_id == site.id
    assert vlan.device_id == dev.id
    assert vlan.circuit_id is None
    assert vlan.status == "reservada"

    # idempotente: mesma ponta não duplica, devolve a existente
    de_novo = reservar_vlan_ac(db_session, device_id=dev.id, vid=777, actor="cli")
    assert de_novo.id == vlan.id

    # mesmo device + mesmo vid = conflito (índice parcial uq_vlans_device_vid)
    dev2 = create_device(db_session, DeviceCreate(name="sw-id2", management_address="10.0.0.42", site_id=site.id), actor="cli")
    outra = reservar_vlan_ac(db_session, device_id=dev2.id, vid=777, actor="cli")
    assert outra.id != vlan.id  # mesmo POP, mesmo VID, switch diferente = legítimo

    from gerenet.domain.services.errors import ValidationError
    with pytest.raises(ValidationError):
        reservar_vlan_ac(db_session, device_id=dev.id, vid=1, actor="cli")  # VID fora do range 2-4094


def test_reservar_vlan_ac_sem_vid_pega_menor_livre_no_device(db_session):
    """vid=None ⇒ menor livre no device; VID 777 ocupado em outro switch não cola aqui."""
    site = create_site(db_session, SiteCreate(name="pop-livre"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-livre", management_address="10.0.0.45", site_id=site.id), actor="cli")
    reservar_vlan_ac(db_session, device_id=dev.id, vid=2, actor="cli")
    livre = reservar_vlan_ac(db_session, device_id=dev.id, actor="cli")
    assert livre.vid == 3


def test_reservar_vlan_ac_corrida_vira_conflito(db_session):
    """Corrida (correção do controller T3): linha NÃO mpls_ac ocupa o (device, vid).

    O pre-check só vê linhas mpls_ac, mas a UNIQUE parcial uq_vlans_device_vid
    barra a inserção — o serviço deve converter em ConflictError (padrão
    devices.py), não vazar IntegrityError.
    """
    from gerenet.domain import models
    site = create_site(db_session, SiteCreate(name="pop-corrida"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-corrida", management_address="10.0.0.46", site_id=site.id), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, device_id=dev.id, vid=555, kind="vlan", status="reservada"))
    db_session.commit()
    with pytest.raises(ConflictError):
        reservar_vlan_ac(db_session, device_id=dev.id, vid=555, actor="cli")


def test_primeiro_vid_de_circuito_ignora_linhas_mpls(db_session):
    """§3/Q2: reserva de circuito não enxerga VLAN mpls_ac (device_id NOT NULL)."""
    site = create_site(db_session, SiteCreate(name="pop-filtro"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="sw-f", management_address="10.0.0.43",
                                                 site_id=site.id), actor="cli")
    reservar_vlan_ac(db_session, device_id=dev.id, vid=2, actor="cli")
    assert _primeiro_vid(db_session, site.id) == 2  # 2 continua livre para o circuito
