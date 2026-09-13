"""Sincronização de estado MPLS a partir da coleta — fase 4, spec §8/§9."""
import pytest

from gerenet.domain import models
from gerenet.domain.schemas import (
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
    VsiEndpointIn,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import (
    add_domain_member,
    create_domain,
    create_l2vc,
    create_vsi,
    get_l2vc,
    get_vsi,
    sincronizar_mpls,
)
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def cenario(db_session):
    site = create_site(db_session, SiteCreate(name="pop-sync"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(name="sw-s1", management_address="10.0.0.95", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(name="sw-s2", management_address="10.0.0.96", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-sync"), actor="cli")
    for dev, lp in ((d1, "10.255.6.1"), (d2, "10.255.6.2")):
        add_domain_member(db_session, dom.id, MplsMemberIn(device_id=dev.id, loopback_address=lp), actor="cli")
    l2vc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="sync-l2vc", vc_id=900,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=601),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=602),
        ],
    ), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="sync vsi", vsi_id=610,
        endpoints=[VsiEndpointIn(device_id=d1.id), VsiEndpointIn(device_id=d2.id)],
    ), actor="cli")
    return d1, d2, l2vc, vsi


def _snap(db_session, dev, recursos):
    snap = models.DeviceSnapshot(device_id=dev.id, status="success", resources=recursos)
    db_session.add(snap)
    db_session.commit()
    return snap


def test_sync_l2vc_up_nas_duas_pontas(db_session, cenario):
    d1, d2, l2vc, _ = cenario
    _snap(db_session, d1, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1", "estado": "up"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d1.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1", "estado": "up"}]},
    ))
    _snap(db_session, d2, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2", "estado": "up"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d2.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2", "estado": "up"}]},
    ))
    svc = get_l2vc(db_session, l2vc.id)
    assert svc.operational_status == "up"
    assert svc.last_collected_at is not None
    assert all(ep.operational_status == "up" for ep in svc.endpoints)


def test_sync_l2vc_down_vira_down_e_misto_vira_partial(db_session, cenario):
    d1, d2, l2vc, _ = cenario
    _snap(db_session, d1, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1", "estado": "down"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d1.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/1", "estado": "down"}]},
    ))
    assert get_l2vc(db_session, l2vc.id).operational_status == "down"
    _snap(db_session, d2, {"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2", "estado": "up"}]})
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d2.id, status="success",
        resources={"l2vc": [{"vc_id": 900, "interface": "10GE0/0/2", "estado": "up"}]},
    ))
    assert get_l2vc(db_session, l2vc.id).operational_status == "partial"


def test_sync_vsi(db_session, cenario):
    d1, _, _, vsi = cenario
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d1.id, status="success",
        resources={"vsi": [{"name": "VSI-SYNC-VSI-610", "vsi_id": 610, "estado": "up"}]},
    ))
    assert get_vsi(db_session, vsi.id).operational_status == "up"


def test_sincronizar_mpls_atualiza_estado_do_ac_do_vsi(db_session):
    """O AC do VSI também é um ServiceEndpoint: o estado dele vem da coleta.

    O estado do SERVIÇO continua vindo do `VSI State` do equipamento; o do AC
    é por ponta. Um AC caído não rebaixa o serviço na SoT.

    A coleta é do device que vem DEPOIS na ordem dos endpoints e as duas pontas
    usam a mesma `Vlanif900` — o caso real do VSI multiponto (mesmo VID em PEs
    diferentes é legítimo no repo). Como `endpoints` é ordenado por `device_id`,
    sem o casamento por (device, interface) o `next()` pegaria a ponta do outro
    device e a assertiva do `unknown` abaixo cairia.
    """
    site = create_site(db_session, SiteCreate(name="pop-sync-vsi"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-sync-a", management_address="10.9.5.1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-sync-b", management_address="10.9.5.2", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-sync-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.4.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.4.2"), actor="cli")
    vsi = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="sync vsi", vsi_id=900,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=900),
                   VsiEndpointIn(device_id=d2.id, vid=900)],
    ), actor="cli")
    snap = models.DeviceSnapshot(
        device_id=d2.id, status="success", resources={"vsi": [{
            "name": vsi.vrp_name, "vsi_id": vsi.vsi_id, "estado": "up", "mtu": 1500,
            "peers": [{"peer": "10.255.4.1", "estado": "up"}],
            "acs": [{"interface": "Vlanif900", "estado": "down"}],
        }]}, errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    sincronizar_mpls(db_session, snap)
    por_device = {ep.device_id: ep for ep in vsi.endpoints}
    assert por_device[d2.id].operational_status == "down"
    assert por_device[d1.id].operational_status == "unknown"
    assert vsi.operational_status == "up"


def test_sincronizar_mpls_estado_desconhecido_vira_unknown(db_session, cenario):
    """`estado` None (coleta não soube o estado) grava `unknown`, não estoura o NOT NULL.

    O merge devolve `estado: None` quando o bloco não traz `VSI State`
    reconhecível; a coluna `operational_status` é NOT NULL, então quem grava é
    que traduz o desconhecido — `linha.get("estado", "unknown")` não bastava
    (o default do `.get` só vale para chave ausente).
    """
    d1, _, _, vsi = cenario
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=d1.id, status="success",
        resources={"vsi": [{"name": "VSI-SYNC-VSI-610", "vsi_id": 610, "estado": None,
                            "mtu": 1500, "peers": [], "acs": []}]},
    ))
    assert get_vsi(db_session, vsi.id).operational_status == "unknown"


def test_sync_sem_mpls_e_no_op(db_session, cenario):
    _, _, l2vc, _ = cenario
    dev3 = create_device(db_session, DeviceCreate(name="sw-r", management_address="10.0.0.97"), actor="cli")
    sincronizar_mpls(db_session, models.DeviceSnapshot(
        device_id=dev3.id, status="success", resources={"interfaces": []},
    ))
    assert get_l2vc(db_session, l2vc.id).operational_status == "unknown"
