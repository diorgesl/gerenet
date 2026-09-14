"""CR de L2VC — fase 4, spec §5 (escopo generalizado)."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from gerenet.domain.schemas import (
    ChangeRequestCreate,
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    SiteCreate,
)
from gerenet.domain.services.change_requests import create_change_request
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.sites import create_site


@pytest.fixture()
def l2vc(db_session):
    site = create_site(db_session, SiteCreate(name="pop-cr"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-a", management_address="10.0.0.81", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-b", management_address="10.0.0.82", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cr"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d1.id, loopback_address="10.255.8.1"), actor="cli")
    add_domain_member(db_session, dom.id, MplsMemberIn(device_id=d2.id, loopback_address="10.255.8.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="cr-test", vc_id=500,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=301),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=302),
        ],
    ), actor="cli")
    return d1, d2, svc


def test_cr_l2vc_nasce_com_2_steps(db_session, l2vc):
    d1, d2, svc = l2vc
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", motivo="Ativar L2VC do cliente.",
    ), ator_id=None)
    assert cr.escopo == "l2vc"
    assert cr.l2vc_id == svc.id
    assert cr.circuit_id is None
    assert {s.device_id for s in cr.steps} == {d1.id, d2.id}
    assert cr.status == "rascunho"


def test_cr_l2vc_exige_l2vc_id(db_session):
    # o schema valida o escopo (model_validator) na CONSTRUÇÃO — PydanticValidationError
    with pytest.raises(PydanticValidationError):
        ChangeRequestCreate(escopo="l2vc", motivo="sem id")


def test_cr_l2vc_desativado(db_session, l2vc):
    from gerenet.domain.services.mpls import set_l2vc_status
    _, _, svc = l2vc
    set_l2vc_status(db_session, svc.id, admin_status=False, actor="cli")
    from gerenet.domain.services.errors import ConflictError
    with pytest.raises(ConflictError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="l2vc", l2vc_id=svc.id, motivo="off",
        ), ator_id=None)


def test_cr_l2vc_remocao_plano_vazio_sem_snapshot_da_remocao(db_session, l2vc):
    """Sem snapshot: provision ainda gera plano (aviso), mas a remoção exige coleta (§5.2)."""
    _, _, svc = l2vc
    create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao="provision", motivo="provisionar primeiro",
    ), ator_id=None)
    # remoção sem snapshot fresco: ValidationError (mesma regra do circuito)
    with pytest.raises(ValidationError):
        create_change_request(db_session, ChangeRequestCreate(
            escopo="l2vc", l2vc_id=svc.id, acao="remove", motivo="remover sem coleta",
        ), ator_id=None)


def test_cr_circuito_default_inalterada(db_session):
    """Regressão: CR de circuito continua com escopo default e circuit_id obrigatório."""
    from gerenet.domain.schemas import BgpSessionCreate, CircuitCreate, OrganizationCreate
    from gerenet.domain.services.bgp_sessions import create_session
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.ipam import reservar_circuito
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site, link_device

    site = create_site(db_session, SiteCreate(name="pop-reg"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="r-reg", management_address="10.0.0.83"), actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="reg", asn=64512), actor="cli")
    circ = create_circuit(db_session, CircuitCreate(
        code="reg-1", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1",
        edge_device_id=dev.id, stack="ipv4", vlan_mode="unica",
    ), actor="cli")
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(db_session, BgpSessionCreate(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.1.1", remote_address="100.64.1.2",
        asn_local=65000, asn_remote=64512,
    ), actor="cli")
    cr = create_change_request(db_session, ChangeRequestCreate(
        circuit_id=circ.id, acao="provision", motivo="regressão circuito",
    ), ator_id=None)
    assert cr.escopo == "circuito"
    assert cr.circuit_id == circ.id


def _snapshot(db_session, dev, recursos):
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success", resources=recursos,
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _recursos(interface, l2vc_linhas):
    return {"interfaces": [{"nome": interface, "phy": "up", "protocolo": "up"}],
            "l2vc": l2vc_linhas, "mpls_ldp_peer": [], "config_backup": ""}


def _cr_aplicada(db_session, svc, acao, device_ids):
    from gerenet.domain.services.change_requests import create_change_request
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao=acao, motivo="teste de rollback.",
    ), ator_id=None)
    cr.status = "aplicado"
    for step in cr.steps:
        step.status = "aplicado" if step.device_id in device_ids else "falhou"
    db_session.commit()
    return cr


def test_rollback_l2vc_provision_gera_filho_remove(db_session, l2vc):
    """Provision aplicado nas duas pontas ⇒ filho remove com `undo mpls l2vc` nas duas."""
    from gerenet.domain.services.change_requests import gerar_rollback
    d1, d2, svc = l2vc
    # o encontrado mostra o VC nas duas pontas: o rollback deriva da coleta atual
    _snapshot(db_session, d1, _recursos("10GE0/0/1", [
        {"vc_id": 500, "interface": "10GE0/0/1", "estado": "up"},
    ]))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", [
        {"vc_id": 500, "interface": "10GE0/0/2", "estado": "up"},
    ]))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id, d2.id})
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert filho.escopo == "l2vc"
    assert filho.l2vc_id == svc.id
    assert filho.circuit_id is None
    assert filho.acao == "remove"
    assert filho.status == "aguardando_aprovacao"
    assert filho.rollback_de == cr.id
    assert {s.device_id for s in filho.steps} == {d1.id, d2.id}
    comandos = [c for s in filho.steps for b in s.plano_json for c in b["comandos"]]
    assert comandos.count("undo mpls l2vc 10.255.8.2 500") == 1
    assert comandos.count("undo mpls l2vc 10.255.8.1 500") == 1


def test_rollback_l2vc_parcial_so_na_ponta_aplicada(db_session, l2vc):
    """Só a ponta aplicada ganha step: a outra não tem VC para remover."""
    from gerenet.domain.services.change_requests import gerar_rollback
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", [
        {"vc_id": 500, "interface": "10GE0/0/1", "estado": "up"},
    ]))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id})
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert [s.device_id for s in filho.steps] == [d1.id]


def test_rollback_l2vc_remocao_gera_filho_provision(db_session, l2vc):
    """Remoção aplicada nas duas pontas ⇒ filho provision com blocos `create`.

    O filho replaneja o desejado pela coleta ATUAL (pós-remoção), não pela ação
    do pai: herdar o `remove` entregaria blocos `delete` a uma CR de provision
    (o defeito do Task 2).
    """
    from gerenet.domain.services.change_requests import gerar_rollback
    d1, d2, svc = l2vc
    # coleta em que a CR de remoção nasceu: o VC consta nas duas pontas
    _snapshot(db_session, d1, _recursos("10GE0/0/1", [
        {"vc_id": 500, "interface": "10GE0/0/1", "estado": "up"},
    ]))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", [
        {"vc_id": 500, "interface": "10GE0/0/2", "estado": "up"},
    ]))
    cr = _cr_aplicada(db_session, svc, "remove", {d1.id, d2.id})
    # coleta pós-execução: o VC sumiu do encontrado
    _snapshot(db_session, d1, _recursos("10GE0/0/1", []))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert filho.escopo == "l2vc"
    assert filho.l2vc_id == svc.id
    assert filho.circuit_id is None
    assert filho.acao == "provision"
    assert filho.status == "aguardando_aprovacao"
    assert filho.rollback_de == cr.id
    assert {s.device_id for s in filho.steps} == {d1.id, d2.id}
    blocos = [b for s in filho.steps for b in s.plano_json]
    assert len(blocos) == 2  # não-vazio explícito: o all() abaixo não passa vazio
    assert all(b["acao"] == "create" for b in blocos)
    comandos = [c for b in blocos for c in b["comandos"]]
    assert comandos.count("mpls l2vc 10.255.8.2 500") == 1
    assert comandos.count("mpls l2vc 10.255.8.1 500") == 1


def test_rollback_l2vc_sem_encontrado_eh_plano_vazio(db_session, l2vc):
    """Nada do serviço consta na coleta: nada persiste (PlanoRollbackVazio).

    F5 (revisão final): a mensagem é do escopo — no l2vc a causa é a coleta
    atual, não um baseline ausente (o filho deriva do encontrado).
    """
    from gerenet.domain.services.change_requests import gerar_rollback
    from gerenet.domain.services.errors import PlanoRollbackVazio
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", []))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id, d2.id})
    with pytest.raises(PlanoRollbackVazio, match="Nada do serviço consta na coleta atual"):
        gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")


def test_reconciliar_l2vc_recomputa_ponta_pendente(db_session, l2vc):
    """CR l2vc em erro volta a aguardando_aprovacao com o step pendente replanejado."""
    from gerenet.domain.services.change_requests import reconciliar
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", []))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id})
    cr.status = "erro"
    db_session.commit()
    cr = reconciliar(db_session, cr.id, actor="cli")
    assert cr.status == "aguardando_aprovacao"
    pendente = next(s for s in cr.steps if s.device_id == d2.id)
    assert pendente.status == "pendente"
    assert pendente.erro is None
    assert pendente.plano_json


def test_reconciliar_l2vc_barra_servico_desativado(db_session, l2vc):
    """F2 (revisão final): serviço desativado depois do plano ⇒ reconciliação recusa.

    Sem o guard, `_replaneja` replanejava o desejado de um serviço que o
    operador considera desligado — mesmo ConflictError da criação de CR.
    """
    from gerenet.domain.services.change_requests import reconciliar
    from gerenet.domain.services.errors import ConflictError
    from gerenet.domain.services.mpls import set_l2vc_status
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", []))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id})  # d2 ficou pendente
    cr.status = "erro"
    db_session.commit()
    set_l2vc_status(db_session, svc.id, admin_status=False, actor="cli")
    with pytest.raises(ConflictError, match="Serviço L2VC desativado não recebe mudanças"):
        reconciliar(db_session, cr.id, actor="cli")


def test_rollback_l2vc_barra_servico_desativado(db_session, l2vc):
    """F2 (revisão final): o filho do rollback não recria o VC de um serviço off.

    Sequência do achado: CR criada com o serviço ativo → serviço desativado →
    CR de remoção aplicada → rollback. Sem o guard, o filho provisionava o AC
    de volta num serviço que o operador acredita desligado.
    """
    from gerenet.domain.services.change_requests import gerar_rollback
    from gerenet.domain.services.errors import ConflictError
    from gerenet.domain.services.mpls import set_l2vc_status
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", [
        {"vc_id": 500, "interface": "10GE0/0/1", "estado": "up"},
    ]))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", [
        {"vc_id": 500, "interface": "10GE0/0/2", "estado": "up"},
    ]))
    cr = _cr_aplicada(db_session, svc, "remove", {d1.id, d2.id})
    # coleta pós-execução (o VC sumiu): o filho provision tem o que criar
    _snapshot(db_session, d1, _recursos("10GE0/0/1", []))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    set_l2vc_status(db_session, svc.id, admin_status=False, actor="cli")
    with pytest.raises(ConflictError, match="Serviço L2VC desativado não recebe mudanças"):
        gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")


def test_rollback_l2vc_barra_dominio_desativado(db_session, l2vc):
    """F2: o domínio desativado também barra o filho (mesma guarda da criação)."""
    from gerenet.domain.services.change_requests import gerar_rollback
    from gerenet.domain.services.errors import ConflictError
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", [
        {"vc_id": 500, "interface": "10GE0/0/1", "estado": "up"},
    ]))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", [
        {"vc_id": 500, "interface": "10GE0/0/2", "estado": "up"},
    ]))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id, d2.id})
    svc.domain.admin_status = False  # desativado depois do plano
    db_session.commit()
    with pytest.raises(ConflictError, match="Domínio MPLS dom-cr desativado não recebe mudanças"):
        gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")


# O teste do bloqueio temporário do escopo vsi ("fase posterior") saiu na
# frente do VSI multiponto, que ligou reconciliação e rollback do escopo: a
# cobertura dele vive em tests/domain/test_change_requests_vsi.py.
