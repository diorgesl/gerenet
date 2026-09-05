"""Máquina de estados + regras de aprovação do fluxo de mudança (spec §4/§7)."""
import pytest
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.services import change_requests as crsvc
from gerenet.domain.services.errors import ValidationError


def _usuario(db_session, username, role):
    from gerenet.domain.services.users import create_user
    return create_user(db_session, username=username, password="senha12345", role=role)


def _circuito_reservado(db_session):
    from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.ipam import reservar_circuito
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site, link_device

    site = create_site(db_session, SiteCreate(name="pop-t", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    dev = create_device(
        db_session, DeviceCreate(name="ne1", management_address="10.0.0.1", asn=65000), actor="cli"
    )
    # _valida_vinculos (circuits.py) exige access/edge no site do circuito
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente", asn=64512), actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="c1", organization_id=org.id, site_id=site.id,
            access_device_id=dev.id, access_port="GE0/0/1",
            edge_device_id=dev.id, stack="ipv4", vlan_mode="unica", edge_trunk="GE1/0/0",
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    return circ, dev


def _sessao(db_session, circ, dev):
    from gerenet.domain.schemas import BgpSessionCreate
    from gerenet.domain.services.bgp_sessions import create_session
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=dev.id, afi="ipv4",
            local_address="10.0.0.1", remote_address="10.0.0.2",
            asn_local=65000, asn_remote=64512,
        ),
        actor="cli",
    )


def _cria_cr(db_session, circ, *, acao="provision", usuario="operador"):
    from gerenet.domain.schemas import ChangeRequestCreate
    sol = _usuario(db_session, usuario, "operador")
    cr = crsvc.create_change_request(
        db_session,
        ChangeRequestCreate(circuit_id=circ.id, acao=acao, motivo="Ativação.", criticidade="media"),
        ator_id=sol.id, actor="operador",
    )
    return cr, sol


def _snapshot_encontrado(db_session, dev, tmp_path):
    """Snapshot cujo ENCONTRADO é o render do desejado (para o path real do rollback)."""
    from gerenet.automation import render
    r = render.render_desejado(db_session, dev.id)
    arquivo = tmp_path / "cfg.txt"
    arquivo.write_text(r.texto + "\n", encoding="utf-8")
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success",
        resources={
            "interfaces": [
                {"nome": b.comandos[0].split(None, 1)[1]}
                for b in r.blocos if b.tipo == "subinterface"
            ],
            "bgp_peers": [
                {"afi": "ipv4", "peer": b.comandos[1].split()[1], "asn": 64512}
                for b in r.blocos if b.tipo == "bgp_peer"
            ],
        },
        raw_files={"config_backup": [str(arquivo)]},
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def test_criar_gera_steps_e_auditoria(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    assert cr.status == "rascunho"
    assert len(cr.steps) == 1
    assert cr.steps[0].device_id == dev.id
    assert cr.steps[0].plano_json
    tipo = db_session.scalar(
        select(models.AuditEvent.type).where(models.AuditEvent.actor == "operador").order_by(models.AuditEvent.id.desc()).limit(1)
    )
    assert tipo == "change.created"


def test_transicao_invalida_levanta_validation(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    with pytest.raises(ValidationError, match="inválida"):
        crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")


def test_aprovacao_regras_papel_e_duplicidade(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, sol = _cria_cr(db_session, circ)
    # solicitante não pode aprovar (spec §3.3)
    with pytest.raises(ValidationError, match="solicitante"):
        crsvc.aprovar(db_session, cr.id, ator_id=sol.id, actor="operador", decisao="aprovar")
    crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    aprovador = _usuario(db_session, "aprovador", "aprovador")
    cr_ok = crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="aprovar")
    assert cr_ok.status == "aprovado"
    assert cr_ok.approvals[0].decisao == "aprovar"
    # duplicada ⇒ ValidationError (spec §4.3)
    with pytest.raises(ValidationError, match="já decidid"):
        crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="aprovar")


def test_rejeitar_termina_cr(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    aprovador = _usuario(db_session, "aprov2", "aprovador")
    cr_final = crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="rejeitar", comentario="janela")
    assert cr_final.status == "rejeitado"
    assert cr_final.approvals[0].decisao == "rejeitar"


def test_cancelar_de_rascunho_e_de_aprovado(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    crsvc.cancelar(db_session, cr.id, actor="operador")
    assert cr.status == "cancelado"
    # leg "de aprovado": §4.1 permite aprovado → cancelado
    cr2, _ = _cria_cr(db_session, circ, usuario="operador2")
    crsvc.enviar_para_aprovacao(db_session, cr2.id, actor="operador")
    aprovador = _usuario(db_session, "aprovador-c", "aprovador")
    crsvc.aprovar(db_session, cr2.id, ator_id=aprovador.id, actor="aprovador", decisao="aprovar")
    crsvc.cancelar(db_session, cr2.id, actor="operador")
    assert cr2.status == "cancelado"


def test_reaprovar_apos_reconciliar(db_session):
    """§4.1: reconciliar devolve a CR a aguardando_aprovacao — nova aprovação
    (ciclo novo); a duplicidade (§4.3) vale por ciclo."""
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    crsvc.enviar_para_aprovacao(db_session, cr.id, actor="operador")
    aprovador = _usuario(db_session, "aprovador", "aprovador")
    cr = crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="aprovar")
    crsvc.marcar_executando(db_session, cr.id, actor="executor")
    cr.steps[0].status = "falhou"
    cr.steps[0].erro = "VRP: % Error"
    cr.status = "parcial"
    db_session.commit()
    cr = crsvc.reconciliar(db_session, cr.id, actor="operador")
    assert cr.status == "aguardando_aprovacao"
    cr = crsvc.aprovar(db_session, cr.id, ator_id=aprovador.id, actor="aprovador", decisao="aprovar")
    assert cr.status == "aprovado"
    assert len(cr.approvals) == 2


def test_reconciliar_de_parcial_recomputa_steps(db_session):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    cr, _ = _cria_cr(db_session, circ)
    cr.steps[0].status = "falhou"
    cr.steps[0].erro = "VRP: % Error"
    cr.status = "parcial"
    db_session.commit()
    cr_final = crsvc.reconciliar(db_session, cr.id, actor="operador")
    assert cr_final.status == "aguardando_aprovacao"
    assert cr_final.steps[0].status == "pendente"
    assert cr_final.steps[0].erro is None


def test_rollback_gera_cr_filho_inverso(db_session, tmp_path):
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    _snapshot_encontrado(db_session, dev, tmp_path)
    cr, _ = _cria_cr(db_session, circ)
    cr.status = "aplicado"
    cr.steps[0].status = "aplicado"  # gerar_rollback exige ≥1 step aplicado
    db_session.commit()
    filho = crsvc.gerar_rollback(db_session, cr.id, ator_id=_usuario(db_session, "exe", "executor").id, actor="executor")
    assert filho.acao == "remove"
    assert filho.rollback_de == cr.id
    assert filho.status == "aguardando_aprovacao"
    assert filho.motivo == f"Rollback do CR #{cr.id}"
    assert all(any(c["acao"] == "delete" for c in s.plano_json) for s in filho.steps)
