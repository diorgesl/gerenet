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
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_vsi, get_vsi
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
    # `l2 binding` e `mtu` saem indentados como no `display` do equipamento (são
    # sub-comandos da Vlanif), igual ao `description` da mesma interface.
    assert ac.comandos == [
        "vlan 700", "interface Vlanif700", " mtu 1500",
        " l2 binding vsi VSI-CLIENTE-ACME-700",
    ]
    assert [b.tipo for b in blocos] == ["vsi", "vsi_ac"]


def test_render_vsi_ac_emite_o_mtu_da_ponta(servico, db_session):
    """A ponta sem MTU próprio herda o do serviço (§9.3).

    É o que faz o `endpoints[].mtu` do formulário ter efeito no equipamento — a
    Vlanif sem a linha fica com o default do switch. A forma completa do bloco
    está no teste acima; aqui o que importa é a herança.
    """
    d1, _, _, svc = servico
    ac = next(b for b in vsi_auto.render_vsi(db_session, svc)[d1.id] if b.tipo == "vsi_ac")
    assert " mtu 1500" in ac.comandos


def test_render_vsi_ac_usa_o_mtu_proprio_da_ponta(servico, db_session):
    d1, d2, _, svc = servico
    outro = create_vsi(db_session, VsiCreate(
        domain_id=svc.domain_id, name="cliente mtu", vsi_id=800, mtu=1500,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=800, mtu=9000),
                   VsiEndpointIn(device_id=d2.id, vid=800)],
    ), actor="cli")
    blocos = vsi_auto.render_vsi(db_session, outro)
    ac_d1 = next(b for b in blocos[d1.id] if b.tipo == "vsi_ac")
    ac_d2 = next(b for b in blocos[d2.id] if b.tipo == "vsi_ac")
    assert " mtu 9000" in ac_d1.comandos
    assert " mtu 1500" in ac_d2.comandos


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


def _linha_vsi(svc, *, estado="up", mtu=1500, peers=(), acs=()):
    return {
        "name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": estado, "mtu": mtu,
        "peers": list(peers), "acs": list(acs),
    }


def _snap(db_session, dev, linhas):
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success", resources={"vsi": linhas},
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def test_pre_checks_vsi_ldp_e_binding(servico, db_session):
    d1, _, _, svc = servico
    # coleta presente e sem o peer: não listado é bloqueio, com o endereço na mensagem
    sem_peer = vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, {
        "vsi": [], "mpls_ldp_peer": [],
    })
    assert sem_peer is not None and "10.255.6.2" in sem_peer
    up = {"vsi": [], "mpls_ldp_peer": [
        {"peer_id": "10.255.6.2", "estado": "up"},
        {"peer_id": "10.255.6.3", "estado": "up"},
    ]}
    assert vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, up) is None
    conflito = {
        **up,
        "vsi": [{"name": "VSI-OUTRO-999", "acs": [{"interface": "Vlanif700"}]}],
    }
    conflito_msg = vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, conflito)
    assert conflito_msg is not None and "conflit" in conflito_msg.lower()
    # família S: `display mpls ldp peer` não imprime estado — desconhecido é bloqueio,
    # não "down" (mensagem própria, sem afirmar que o peer está down)
    desconhecido = {**up, "mpls_ldp_peer": [
        {"peer_id": "10.255.6.2", "estado": None},
        {"peer_id": "10.255.6.3", "estado": "up"},
    ]}
    desconhecido_msg = vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, desconhecido)
    assert desconhecido_msg is not None and "desconhecido" in desconhecido_msg
    down = {**up, "mpls_ldp_peer": [
        {"peer_id": "10.255.6.2", "estado": "down"},
        {"peer_id": "10.255.6.3", "estado": "up"},
    ]}
    down_msg = vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, down)
    assert down_msg is not None and "não está UP" in down_msg


def test_pre_check_vsi_barra_membro_sem_ponta(servico, db_session):
    d1, _, d3, svc = servico
    # drift da SoT: o membro continua no serviço, mas a ponta dele sumiu
    db_session.delete(next(e for e in svc.endpoints if e.device_id == d3.id))
    db_session.commit()
    # a sessão não expira no commit: o serviço é relido, como o runner faz
    svc = get_vsi(db_session, svc.id)
    msg = vsi_auto.valida_pre_checks_vsi(db_session, svc, d1, {
        "vsi": [], "mpls_ldp_peer": [
            {"peer_id": "10.255.6.2", "estado": "up"},
        ],
    })
    assert msg is not None and "revalide o serviço" in msg


def test_pos_check_vsi_ausente_estado_e_mtu(servico, db_session):
    d1, _, _, svc = servico
    ausente = vsi_auto.valida_pos_vsi(db_session, svc, _snap(db_session, d1, []))
    assert [i["tipo"] for i in ausente] == ["vsi.ausente"]
    assert ausente[0]["severidade"] == "critica"
    caido = vsi_auto.valida_pos_vsi(
        db_session, svc, _snap(db_session, d1, [_linha_vsi(svc, estado="down")])
    )
    assert any(i["tipo"] == "vsi.estado" and i["severidade"] == "critica" for i in caido)
    # o MTU é conferido mesmo com o VSI fora de up: o display imprime o MTU
    # configurado do VSI em ambos os casos (diferente do `local VC MTU` do L2VC)
    mtu = vsi_auto.valida_pos_vsi(
        db_session, svc, _snap(db_session, d1, [_linha_vsi(svc, estado="down", mtu=9000)])
    )
    assert any(i["tipo"] == "vsi.mtu" and i["severidade"] == "atencao" for i in mtu)


def test_plan_remocao_vsi_exige_snapshot_e_nomeia_o_equipamento(servico, db_session):
    _d1, _d2, _d3, svc = servico
    # sem coleta não sai plano de remoção, e a mensagem diz qual switch coletar
    with pytest.raises(ValidationError, match="sw-a"):
        vsi_auto.plan_remocao_vsi(db_session, svc)


def test_estado_bloco_vsi_nao_le_a_descricao_como_identidade(servico, db_session):
    """A `description` do serviço não é identidade de bloco (revisão final, F1).

    O `vsi.j2` renderiza ` description <texto>` dentro do bloco do VSI: varrer
    o texto inteiro por `Vlanif\\d+` fazia uma descrição que cita `Vlanif900`
    ser lida como o AC do bloco — o VSI era dado como "consta" quando aquela
    Vlanif pertence a OUTRO serviço, e a identidade real (nome VRP) nunca era
    consultada. O despacho é pelo `tipo` do bloco.
    """
    from gerenet.automation import changes

    d1, _d2, _d3, svc = servico
    svc.description = "AC na Vlanif900 do cliente"
    db_session.commit()
    bloco = next(b for b in vsi_auto.render_vsi(db_session, svc)[d1.id] if b.tipo == "vsi")
    item = changes._bloco_para_plano(bloco, "create")
    assert "Vlanif900" in " ".join(item["comandos"])  # a armadilha está no texto do bloco
    alheio = {"vsi": [{"name": "VSI-OUTRO-999", "vsi_id": 999,
                       "acs": [{"interface": "Vlanif900", "estado": "up"}]}]}
    assert vsi_auto.estado_bloco_vsi(item, alheio) == "ausente"
    # e o VSI que existe mesmo continua reconhecido (não é "ausente" sempre)
    proprio = {"vsi": [{"name": svc.vrp_name, "vsi_id": svc.vsi_id, "acs": []}]}
    assert vsi_auto.estado_bloco_vsi(item, proprio) == "consta"


def test_plan_provision_vsi_pula_o_presente_e_avisa_sem_coleta(servico, db_session):
    """Bloco presente ⇒ skip (§5.1); sem coleta ⇒ plano completo COM o aviso.

    O `aviso` é o que separa "nada a fazer" de "não sei o encontrado": os dois
    saem com os mesmos blocos do render quando não há coleta, e é por isso que
    o plano sem diff precisa carregar o texto de re-validação na execução.
    """
    d1, d2, d3, svc = servico
    sem_coleta = {p.device_id: p for p in vsi_auto.plan_provision_vsi(db_session, svc)}
    assert set(sem_coleta) == {d1.id, d2.id, d3.id}
    for item in sem_coleta.values():
        assert [b["tipo"] for b in item.blocos] == ["vsi", "vsi_ac"]
        assert item.aviso == vsi_auto._SEM_VSI_AVISO
        assert item.baseline_snapshot_id is None
    # coleta em que o VSI e a Vlanif da ponta já constam: nada a aplicar
    for dev in (d1, d2, d3):
        _snap(db_session, dev, [_linha_vsi(
            svc, acs=[{"interface": "Vlanif700", "estado": "up"}],
        )])
    aplicado = {p.device_id: p for p in vsi_auto.plan_provision_vsi(db_session, svc)}
    for item in aplicado.values():
        assert item.blocos == []
        assert item.aviso is None
        assert item.baseline_snapshot_id is not None
    # coleta nova do PE A com o VSI mas SEM o AC da ponta: sobra só o que falta
    _snap(db_session, d1, [_linha_vsi(svc, acs=[])])
    parcial = {p.device_id: p for p in vsi_auto.plan_provision_vsi(db_session, svc)}
    assert [b["tipo"] for b in parcial[d1.id].blocos] == ["vsi_ac"]
    assert parcial[d1.id].aviso is None
    assert parcial[d2.id].blocos == []
