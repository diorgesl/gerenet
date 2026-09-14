"""CR de escopo vsi — fase 4, parte 3 (spec §5)."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from gerenet.domain.schemas import (
    ChangeRequestCreate,
    DeviceCreate,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
    VsiCreate,
    VsiEndpointIn,
)
from gerenet.domain.services.change_requests import (
    create_change_request,
    gerar_rollback,
    reconciliar,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, PlanoRollbackVazio, ValidationError
from gerenet.domain.services.mpls import (
    add_domain_member,
    create_domain,
    create_vsi,
    set_vsi_status,
)
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def vsi(db_session):
    site = create_site(db_session, SiteCreate(name="pop-cr-vsi"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.9.4.1", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.9.4.2", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cr-vsi"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.5.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.5.2"), actor="cli")
    svc = create_vsi(db_session, VsiCreate(
        domain_id=dom.id, name="cr-vsi", vsi_id=800,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=800),
                   VsiEndpointIn(device_id=d2.id, vid=800)],
    ), actor="cli")
    return d1, d2, svc


def _snapshot(db_session, dev, recursos):
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success", resources=recursos,
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _vsi_coletado(svc, device_id_and_if):
    return [{
        "name": svc.vrp_name, "vsi_id": svc.vsi_id, "estado": "up", "mtu": svc.mtu,
        "peers": [{"peer": "10.255.5.2", "estado": "up"}],
        "acs": [{"interface": interface, "estado": "up"} for interface in device_id_and_if],
    }]


def test_cr_vsi_nasce_com_um_step_por_pe(db_session, vsi):
    d1, d2, svc = vsi
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, acao="provision", motivo="Ativar VSI do cliente.",
    ), ator_id=None)
    assert cr.escopo == "vsi"
    assert cr.vsi_id == svc.id
    assert cr.circuit_id is None and cr.l2vc_id is None
    assert {s.device_id for s in cr.steps} == {d1.id, d2.id}
    assert cr.status == "rascunho"


def test_cr_vsi_exige_vsi_id_e_servico_ativo(db_session, vsi):
    _, _, svc = vsi
    with pytest.raises(PydanticValidationError):
        ChangeRequestCreate(escopo="vsi", motivo="sem id")
    set_vsi_status(db_session, svc.id, admin_status=False, actor="cli")
    with pytest.raises(ConflictError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="vsi", vsi_id=svc.id, motivo="desativado",
        ), ator_id=None)


def test_cr_vsi_com_uma_ponta_eh_recusada(db_session, vsi):
    """VSI multiponto sem par: não há o que provisionar (§9.3)."""
    d1, _, _ = vsi
    dom_id = create_domain(db_session, MplsDomainCreate(name="dom-cr-vsi-solo"), actor="cli").id
    add_domain_member(db_session, dom_id, MplsMemberIn(
        device_id=d1.id, loopback_address="10.255.5.1"), actor="cli")
    solo = create_vsi(db_session, VsiCreate(
        domain_id=dom_id, name="cr-vsi-solo", vsi_id=801,
        endpoints=[VsiEndpointIn(device_id=d1.id, vid=801)],
    ), actor="cli")
    with pytest.raises(ValidationError, match="duas pontas"):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="vsi", vsi_id=solo.id, motivo="solo",
        ), ator_id=None)


def test_reconciliar_vsi_recomputa_ponta_pendente(db_session, vsi):
    d1, d2, svc = vsi
    # coleta SEM o serviço: com o VSI já no encontrado o plano sai vazio (skip por
    # presença) e não haveria o que replanejar — é o que este teste quer exercitar
    vazio = {"vsi": [], "interfaces": [], "config_backup": ""}
    _snapshot(db_session, d1, vazio)
    _snapshot(db_session, d2, vazio)
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    cr.status = "erro"
    for step in cr.steps:
        step.status = "aplicado" if step.device_id == d1.id else "falhou"
    db_session.commit()
    cr = reconciliar(db_session, cr.id, actor="cli")
    assert cr.status == "aguardando_aprovacao"
    pendente = next(s for s in cr.steps if s.device_id == d2.id)
    assert pendente.status == "pendente" and pendente.plano_json


def test_rollback_vsi_provision_gera_filho_remove(db_session, vsi):
    d1, d2, svc = vsi
    # a CR nasce ANTES da coleta que já mostra o VSI: com ele no encontrado o
    # plano de provision sai vazio (skip por presença) e não haveria CR. É a
    # coleta do momento do rollback que dá o que desfazer.
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    _snapshot(db_session, d1, {"vsi": _vsi_coletado(svc, ["Vlanif800"]),
                               "interfaces": [], "config_backup": ""})
    _snapshot(db_session, d2, {"vsi": _vsi_coletado(svc, ["Vlanif800"]),
                               "interfaces": [], "config_backup": ""})
    cr.status = "aplicado"
    for step in cr.steps:
        step.status = "aplicado"
    db_session.commit()
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert filho.escopo == "vsi" and filho.vsi_id == svc.id
    assert filho.acao == "remove" and filho.rollback_de == cr.id
    assert filho.status == "aguardando_aprovacao"
    comandos = [c for s in filho.steps for b in s.plano_json for c in b["comandos"]]
    assert comandos.count(f"undo vsi {svc.vrp_name}") == 2
    assert comandos.count(f"undo l2 binding vsi {svc.vrp_name}") == 2


def test_rollback_vsi_sem_encontrado_eh_plano_vazio(db_session, vsi):
    d1, d2, svc = vsi
    vazio = {"vsi": [], "interfaces": [], "config_backup": ""}
    _snapshot(db_session, d1, vazio)
    _snapshot(db_session, d2, vazio)
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    cr.status = "aplicado"
    for step in cr.steps:
        step.status = "aplicado"
    db_session.commit()
    cr_id = cr.id  # o objeto antigo não importa: o serviço recarrega pelo id
    with pytest.raises(PlanoRollbackVazio):
        gerar_rollback(db_session, cr_id, ator_id=None, actor="cli")


def test_cr_vsi_desativado_nao_replaneja(db_session, vsi):
    """Serviço desativado não recebe mudanças na reconciliação (§5)."""
    d1, d2, svc = vsi
    _snapshot(db_session, d1, {"vsi": [], "interfaces": [], "config_backup": ""})
    _snapshot(db_session, d2, {"vsi": [], "interfaces": [], "config_backup": ""})
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="vsi", vsi_id=svc.id, motivo="ativar",
    ), ator_id=None)
    cr.status = "erro"
    db_session.commit()
    set_vsi_status(db_session, svc.id, admin_status=False, actor="cli")
    with pytest.raises(ConflictError):
        reconciliar(db_session, cr.id, actor="cli")
