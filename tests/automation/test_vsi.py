"""Render, planos e pré/pós-checks do VSI multiponto — fase 4, spec §9.3."""
import pytest

from gerenet.automation import vsi as vsi_auto
from gerenet.domain.schemas import (
    DeviceCreate,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
    VsiEndpointIn,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_vsi
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def servico(db_session):
    site = create_site(db_session, SiteCreate(name="pop-vsi-aut"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.9.3.1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.9.3.2", site_id=site.id), actor="cli")
    d3 = create_device(db_session, DeviceCreate(
        name="sw-c", management_address="10.9.3.3", site_id=site.id), actor="cli")
    # DeviceCreate não expõe capabilities: grava direto no device (a coluna é JSON)
    d3.capabilities = ["mpls_flow_label"]
    db_session.commit()
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi-aut"), actor="cli")
    for dev, lb in ((d1, "10.255.6.1"), (d2, "10.255.6.2"), (d3, "10.255.6.3")):
        add_domain_member(db_session, dom.id,
                          MplsMemberIn(device_id=dev.id, loopback_address=lb), actor="cli")
    svc = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cliente acme", vsi_id=700, flow_label=True, mtu=1500,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=700),
                   VsiEndpointIn(device_id=d2.id, vid=700),
                   VsiEndpointIn(device_id=d3.id, vid=700)],
    ), actor="cli")
    return d1, d2, d3, svc


def test_render_vsi_um_bloco_por_pe_com_os_peers_dos_outros(servico, db_session):
    d1, d2, d3, svc = servico
    por_device = vsi_auto.render_vsi(db_session, svc)
    assert set(por_device) == {d1.id, d2.id, d3.id}
    texto_d1 = "\n".join(c for b in por_device[d1.id] for c in b.comandos)
    assert "vsi VSI-CLIENTE-ACME-700 static" in texto_d1
    assert "  peer 10.255.6.2" in texto_d1
    assert "  peer 10.255.6.3" in texto_d1
    assert "  peer 10.255.6.1" not in texto_d1
    assert texto_d1.count("  peer ") == 2


def test_render_vsi_flow_label_so_com_capability(servico, db_session):
    d1, _, d3, svc = servico
    por_device = vsi_auto.render_vsi(db_session, svc)
    texto_d1 = "\n".join(c for b in por_device[d1.id] for c in b.comandos)
    texto_d3 = "\n".join(c for b in por_device[d3.id] for c in b.comandos)
    assert "flow-label both" not in texto_d1  # d1 não declara a capability
    assert "flow-label both" in texto_d3


def test_render_vsi_ac_com_vlan_e_binding(servico, db_session):
    d1, _, _, svc = servico
    blocos = vsi_auto.render_vsi(db_session, svc)[d1.id]
    ac = next(b for b in blocos if b.tipo == "vsi_ac")
    # `l2 binding` sai indentado como no `display` do equipamento (o comando é
    # sub-comando da Vlanif), igual ao `description` da mesma interface.
    assert ac.comandos == [
        "vlan 700", "interface Vlanif700", " l2 binding vsi VSI-CLIENTE-ACME-700",
    ]
    assert [b.tipo for b in blocos] == ["vsi", "vsi_ac"]


def test_plan_remocao_vsi_desfaz_binding_antes_do_vsi(servico, db_session):
    d1, d2, d3, svc = servico
    from gerenet.domain import models
    # a remoção exige coleta em CADA PE: sem snapshot de um deles o plano não
    # sai (nunca um plano de remoção otimista, §5.2)
    for dev in (d1, d2, d3):
        db_session.add(models.DeviceSnapshot(
            device_id=dev.id, status="success", resources={"vsi": [{
                "name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": "up", "mtu": 1500,
                "peers": [{"peer": "10.255.6.2", "estado": "up"}],
                "acs": [{"interface": "Vlanif700", "estado": "up"}],
            }]}, errors={}, raw_files={}, duration_ms=0,
        ))
    db_session.commit()
    plano = vsi_auto.plan_remocao_vsi(db_session, svc)
    item = next(p for p in plano if p.device_id == d1.id)
    tipos = [b["tipo"] for b in item.blocos]
    assert tipos == ["vsi_ac", "vsi"]
    assert item.blocos[0]["comandos"][-1] == "undo l2 binding vsi VSI-CLIENTE-ACME-700"
    assert item.blocos[1]["comandos"] == ["undo vsi VSI-CLIENTE-ACME-700"]


def test_pre_check_vsi_bloqueia_sem_coleta_de_ldp(servico, db_session):
    d1, _, _, svc = servico
    assert vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, {}) is not None


def test_pos_check_vsi_marca_pseudowire_e_ac(servico, db_session):
    d1, _, _, svc = servico
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=d1.id, status="success", resources={"vsi": [{
            "name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": "up", "mtu": 1500,
            "peers": [{"peer": "10.255.6.2", "estado": "down"}],
            "acs": [{"interface": "Vlanif700", "estado": "down"}],
        }]}, errors={}, raw_files={}, duration_ms=0,
    )
    itens = vsi_auto.valida_pos_vsi(db_session, svc, snap)
    por_tipo = {i["tipo"]: i for i in itens}
    assert por_tipo["vsi.peer"]["severidade"] == "critica"
    assert por_tipo["vsi.ac"]["severidade"] == "atencao"
