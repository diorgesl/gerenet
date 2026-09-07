"""Render/planos/pré-pós-checks L2VC — fase 4, spec §6."""
import pytest

from gerenet.automation import l2vc
from gerenet.automation.changes import PlanoDevice
from gerenet.domain.schemas import (
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def servico(db_session):
    site = create_site(db_session, SiteCreate(name="pop-aut"), actor="cli")
    d1 = create_device(
        db_session, DeviceCreate(name="sw-a", management_address="10.0.0.71", site_id=site.id), actor="cli"
    )
    d2 = create_device(
        db_session, DeviceCreate(name="sw-b", management_address="10.0.0.72", site_id=site.id), actor="cli"
    )
    dom = create_domain(db_session, MplsDomainCreate(name="dom-aut"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.9.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.9.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="cliente-acme", vc_id=1000,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=101, mtu=1500),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=202, mtu=1500),
        ],
    ), actor="cli")
    return d1, d2, svc


def _snapshot(db_session, dev, recursos):
    from gerenet.domain import models
    snap = models.DeviceSnapshot(device_id=dev.id, status="success", resources=recursos)
    db_session.add(snap)
    db_session.commit()
    return snap


def _recursos_vazios(interface: str):
    return {
        "interfaces": [{"nome": interface, "phy": "up", "protocolo": "up"}],
        "l2vc": [],
        "mpls_ldp_peer": [],
        "config_backup": "",
    }


def test_render_l2vc_dot1q(servico, db_session):
    d1, d2, svc = servico
    por_device = l2vc.render_l2vc(db_session, svc)
    assert set(por_device) == {d1.id, d2.id}
    blocos = por_device[d1.id]
    assert len(blocos) == 1
    bloco = blocos[0]
    assert bloco.tipo == "l2vc_ac"
    assert bloco.objeto == "l2vc" and bloco.objeto_id == svc.id
    comandos = bloco.comandos
    assert comandos[0] == "interface 10GE0/0/1.101"
    assert any(c.startswith("mpls l2vc 1000 encapsulation vlan remote 10.255.9.2") for c in comandos)
    assert any("control-word" in c for c in comandos) is False
    # ponta B aponta para o loopback da ponta A
    comandos_b = por_device[d2.id][0].comandos
    assert any("remote 10.255.9.1" in c for c in comandos_b)


def test_render_qinq_control_word_e_mtu(servico, db_session):
    d1, _d2, svc = servico
    svc.control_word = True
    svc.mtu = 1600
    for ep in svc.endpoints:
        ep.encapsulation = "qinq"
        ep.inner_vlan = 31
        ep.mtu = None
    db_session.commit()
    por_device = l2vc.render_l2vc(db_session, svc)
    comandos = por_device[d1.id][0].comandos
    linha = next(c for c in comandos if c.startswith("mpls l2vc 1000"))
    assert "encapsulation vlan-vpls" in linha
    assert "control-word" in linha
    assert "mtu 1600" in linha
    assert any("inner-vlan" in c.upper() or "encapsulation qinq" in c.lower() for c in comandos)


def test_flow_label_so_com_capacidade(servico, db_session):
    d1, _d2, svc = servico
    svc.flow_label = True
    db_session.commit()
    por_device = l2vc.render_l2vc(db_session, svc)
    assert all("flow-label" not in " ".join(b.comandos) for b in por_device[d1.id])
    d1.capabilities = ["mpls_flow_label"]
    db_session.commit()
    por_device = l2vc.render_l2vc(db_session, svc)
    assert any("flow-label" in " ".join(b.comandos) for b in por_device[d1.id])


def test_estado_bloco_l2vc(servico):
    _d1, _d2, svc = servico
    bloco = {
        "tipo": "l2vc_ac", "objeto": "l2vc", "objeto_id": svc.id, "acao": "create",
        "comandos": ["interface 10GE0/0/1.101", "mpls l2vc 1000 encapsulation vlan remote 10.255.9.2"],
    }
    ausente = l2vc.estado_bloco_l2vc(bloco, _recursos_vazios("10GE0/0/9.999"))
    assert ausente == "ausente"
    presente = l2vc.estado_bloco_l2vc(bloco, {
        "interfaces": [{"nome": "10GE0/0/1.101"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    assert presente == "consta"
    conflito = l2vc.estado_bloco_l2vc(bloco, {
        "interfaces": [{"nome": "10GE0/0/1.101"}],
        "l2vc": [],  # subinterface existe sem o l2vc: config parcial/mudada desde o plano
    })
    assert conflito == "conflito"
    remocao = l2vc.estado_bloco_l2vc({**bloco, "acao": "delete"}, {
        "interfaces": [{"nome": "10GE0/0/1.101"}], "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    assert remocao == "consta"
    remocao_ausente = l2vc.estado_bloco_l2vc({**bloco, "acao": "delete"}, _recursos_vazios("10GE0/0/9.999"))
    assert remocao_ausente == "ausente"


def test_plan_provision_idempotente(servico, db_session):
    d1, d2, svc = servico
    _snapshot(db_session, d1, _recursos_vazios("10GE0/0/1.101"))
    _snapshot(db_session, d2, _recursos_vazios("10GE0/0/2.202"))
    plano = l2vc.plan_provision_l2vc(db_session, svc)
    assert len(plano) == 2
    assert all(isinstance(p, PlanoDevice) for p in plano)
    assert all(len(p.blocos) == 1 for p in plano)
    # segunda chamada: ainda cenário divergente ('conflito') — diffs estáveis (nenhum write)
    plano2 = l2vc.plan_provision_l2vc(db_session, svc)
    assert [len(p.blocos) for p in plano2] == [1, 1]
    # aplicado na coleta ⇒ plano vazio (skip de tudo)
    _snapshot(db_session, d1, {
        "interfaces": [{"nome": "10GE0/0/1.101", "phy": "up", "protocolo": "up"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    plano3 = l2vc.plan_provision_l2vc(db_session, svc)
    por_dev = {p.device_id: p for p in plano3}
    assert por_dev[d1.id].blocos == []


def test_plan_remocao_exige_snapshot_novo(servico, db_session):
    d1, d2, svc = servico
    with pytest.raises(ValidationError):
        l2vc.plan_remocao_l2vc(db_session, svc)
    _snapshot(db_session, d1, _recursos_vazios("10GE0/0/1.101"))
    _snapshot(db_session, d2, _recursos_vazios("10GE0/0/2.202"))
    plano = l2vc.plan_remocao_l2vc(db_session, svc)
    assert len(plano) == 2
    bloco = plano[0].blocos[0]
    assert bloco["acao"] == "delete"
    assert bloco["comandos"] == ["undo interface 10GE0/0/1.101"]


def test_pre_checks_ldp_e_binding(servico, db_session):
    _d1, _d2, svc = servico
    sem_ldp = l2vc.valida_pre_checks_l2vc(db_session, svc, svc.endpoints[0].device, {
        **_recursos_vazios("10GE0/0/1.101"), "mpls_ldp_peer": [],
    })
    assert sem_ldp is not None and "10.255.9.2" in sem_ldp
    ok = l2vc.valida_pre_checks_l2vc(db_session, svc, svc.endpoints[0].device, {
        **_recursos_vazios("10GE0/0/1.101"),
        "mpls_ldp_peer": [{"peer_id": "10.255.9.2", "estado": "up"}],
    })
    assert ok is None
    conflito = l2vc.valida_pre_checks_l2vc(db_session, svc, svc.endpoints[0].device, {
        "interfaces": [{"nome": "10GE0/0/1.101"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1", "estado": "up"}],
        "mpls_ldp_peer": [{"peer_id": "10.255.9.2", "estado": "up"}],
    })
    assert conflito is not None and "conflit" in conflito.lower()


def test_pos_check_up_e_down(servico, db_session):
    d1, _d2, svc = servico
    snap_up = _snapshot(db_session, d1, {
        "interfaces": [{"nome": "10GE0/0/1.101", "phy": "up", "protocolo": "up"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "up"}],
    })
    assert l2vc.valida_pos_l2vc(db_session, svc, snap_up) == []
    snap_down = _snapshot(db_session, d1, {
        "interfaces": [{"nome": "10GE0/0/1.101", "phy": "up", "protocolo": "up"}],
        "l2vc": [{"vc_id": 1000, "interface": "10GE0/0/1.101", "estado": "down"}],
    })
    items = l2vc.valida_pos_l2vc(db_session, svc, snap_down)
    assert any(i["tipo"] == "l2vc.estado" and i["severidade"] == "critica" for i in items)
