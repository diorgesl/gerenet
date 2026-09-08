"""Serviço de upstreams (A3) — CRUD, vínculo de circuitos e propagação de defaults (§7)."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from gerenet.domain import models
from gerenet.domain.schemas import UpstreamCreate, UpstreamUpdate
from gerenet.domain.services import upstreams as svc
from gerenet.domain.services.circuits import disable_circuit
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


def _audit_tipos(session) -> list[str]:
    """Tipos dos eventos de auditoria gravados, na ordem de criação."""
    return list(session.scalars(
        select(models.AuditEvent.type).order_by(models.AuditEvent.id)))


def test_cria_upstream_exige_operadora(session, org_downstream):
    """Organização downstream não é operadora — criação de upstream é rejeitada (§7)."""
    with pytest.raises(ValidationError, match="operadora"):
        svc.create_upstream(
            session,
            UpstreamCreate(name="x-up", tipo="transito", organization_id=org_downstream.id),
            actor="cli",
        )


def test_cria_lista_desativa_upstream_com_auditoria(session, org_operadora):
    up = svc.create_upstream(
        session,
        UpstreamCreate(name="transito-y", tipo="ix", organization_id=org_operadora.id,
                       capacity="100G"),
        actor="cli",
    )
    assert up.tipo == "ix"
    assert up.capacity == "100G"
    assert up.admin_status is True
    assert [u.name for u in svc.list_upstreams(session)] == ["transito-y"]

    svc.disable_upstream(session, up.id, actor="cli")
    assert up.admin_status is False
    assert svc.list_upstreams(session) == []
    assert [u.name for u in svc.list_upstreams(session, include_disabled=True)] == ["transito-y"]
    assert _audit_tipos(session)[:2] == ["upstream.create", "upstream.disable"]


def test_cria_upstream_nome_duplicado_vira_conflito(session, org_operadora):
    dados = UpstreamCreate(name="transito-z", tipo="transito", organization_id=org_operadora.id)
    svc.create_upstream(session, dados, actor="cli")
    with pytest.raises(ConflictError, match="transito-z"):
        svc.create_upstream(session, dados, actor="cli")


def test_list_upstreams_filtra_por_organizacao(session, org_operadora):
    svc.create_upstream(session, UpstreamCreate(name="t1", tipo="transito",
                                                organization_id=org_operadora.id), actor="cli")
    assert len(svc.list_upstreams(session, organization_id=org_operadora.id)) == 1
    assert svc.list_upstreams(session, organization_id=999) == []


def test_get_upstream_nao_encontrado(session):
    with pytest.raises(NotFoundError, match="não encontrado"):
        svc.get_upstream(session, 999)


def test_update_upstream_valida_nome_e_org(session, org_operadora, org_downstream):
    up = svc.create_upstream(session, UpstreamCreate(name="transito-v", tipo="transito",
                                                     organization_id=org_operadora.id), actor="cli")
    with pytest.raises(ValidationError, match="operadora"):
        svc.update_upstream(session, up.id,
                            UpstreamUpdate(organization_id=org_downstream.id), actor="cli")
    with pytest.raises(ValidationError, match="entre 2 e 128"):
        svc.update_upstream(session, up.id, UpstreamUpdate(name="x"), actor="cli")
    atualizado = svc.update_upstream(session, up.id, UpstreamUpdate(name="transito-v2"), actor="cli")
    assert atualizado.name == "transito-v2"


def test_update_upstream_reproupa_defaults(session, org_operadora, circuito_up,
                                           bgp_session_principal):
    up = svc.create_upstream(session, UpstreamCreate(
        name="transito-up", tipo="transito", organization_id=org_operadora.id,
        expected_prefixes_v4=1000, max_prefix_margin_pct=10, entrada_local_preference=100),
        actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1, actor="cli")
    sess = session.get(models.BgpSession, bgp_session_principal.id)
    assert sess.maximum_prefix == 1100

    svc.update_upstream(session, up.id, UpstreamUpdate(expected_prefixes_v4=2000), actor="cli")
    session.refresh(sess)
    assert sess.maximum_prefix == 2200  # 2000 * 1.10 — repropagado no update


def test_propagacao_aplica_defaults_e_sessoes_vencem(session, org_operadora, circuito_up,
                                                     bgp_session_principal):
    up = svc.create_upstream(
        session,
        UpstreamCreate(name="transito-x", tipo="transito", organization_id=org_operadora.id,
                       expected_prefixes_v4=1000, expected_prefixes_v6=200,
                       entrada_local_preference=100, contingencia_local_preference=60,
                       contingencia_prepend=3, max_prefix_margin_pct=10),
        actor="cli",
    )
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1, actor="cli")
    sess = session.get(models.BgpSession, bgp_session_principal.id)
    assert sess.maximum_prefix == 1100  # 1000 * 1.10
    assert sess.maximum_prefix_threshold == 80
    assert sess.local_preference == 100
    # sessão explícita vence: edita e repropaga
    sess.local_preference = 150
    session.commit()
    svc.propagar_defaults(session, up)
    session.refresh(sess)
    assert sess.local_preference == 150


def test_propagacao_recalcula_maximum_prefix_sempre(session, org_operadora, circuito_up,
                                                    bgp_session_principal):
    up = svc.create_upstream(session, UpstreamCreate(
        name="transito-m", tipo="transito", organization_id=org_operadora.id,
        expected_prefixes_v4=1000, max_prefix_margin_pct=10), actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1, actor="cli")
    sess = session.get(models.BgpSession, bgp_session_principal.id)
    sess.maximum_prefix = 9999  # ajuste "manual" não vence o derivado (esperado × margem)
    session.commit()
    svc.propagar_defaults(session, up)
    session.commit()
    session.refresh(sess)
    assert sess.maximum_prefix == 1100


def test_propagacao_define_perfil_de_import_pelo_tipo(session, org_operadora, site_f5,
                                                      edge_device):
    circ = models.Circuit(code="CIRC-UP-PNI1", organization_id=org_operadora.id,
                          site_id=site_f5.id, access_device_id=None, access_port="GE0/0/9",
                          edge_device_id=edge_device.id, vlan_mode="none")
    session.add(circ)
    session.flush()
    sess = models.BgpSession(circuit_id=circ.id, device_id=edge_device.id, afi="ipv4",
                             local_address="100.64.10.9", remote_address="100.64.10.10",
                             asn_local=65001, asn_remote=64501)
    session.add(sess)
    session.commit()

    up = svc.create_upstream(session, UpstreamCreate(
        name="pni-x", tipo="pni", organization_id=org_operadora.id, entrada_local_preference=50),
        actor="cli")
    svc.vincular_circuito(session, up.id, circ.id, papel="principal", ordem=1, actor="cli")
    session.refresh(sess)
    perfil = session.scalar(select(models.PolicyProfile).where(
        models.PolicyProfile.name == "up-parcial",
        models.PolicyProfile.direction == "import"))
    assert sess.import_profile_id == perfil.id  # pni ⇒ up-parcial (§3.1)
    assert sess.local_preference == 50
    assert sess.maximum_prefix is None  # sem esperado, sem máximo derivado


def test_propagacao_contingencia_aplica_lp_e_prepend(session, up_com_2_circuitos):
    vinculados = list(session.scalars(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.upstream_id == up_com_2_circuitos.id).order_by(
            models.UpstreamCircuit.id)))
    principal = next(v for v in vinculados if v.papel == "principal")
    conting = next(v for v in vinculados if v.papel == "contingencia")
    s_princ = session.scalar(select(models.BgpSession).where(
        models.BgpSession.circuit_id == principal.circuit_id))
    s_cont = session.scalar(select(models.BgpSession).where(
        models.BgpSession.circuit_id == conting.circuit_id))

    alteradas = svc.propagar_defaults(session, up_com_2_circuitos)
    assert sorted(set(alteradas)) == [s_princ.id, s_cont.id]
    session.refresh(s_princ)
    session.refresh(s_cont)
    assert s_princ.local_preference == 100  # entrada do fixture up (principal)
    assert s_cont.local_preference == 60   # contingência
    assert s_cont.prepend == 3
    assert s_princ.maximum_prefix == 1100  # 1000 * 1.10
    assert s_cont.maximum_prefix == 1100
    assert s_cont.maximum_prefix_threshold == 80


def test_upstream_do_circuito(session, up, up2, circuito_up):
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1, actor="cli")
    assert svc.upstream_do_circuito(session, circuito_up.id).id == up.id
    assert svc.upstream_do_circuito(session, circuito_up.id).id != up2.id


def test_upstream_do_circuito_sem_vinculo(session, circuito_up):
    assert svc.upstream_do_circuito(session, circuito_up.id) is None


def test_vincular_circuito_vinculado_a_outro_upstream_vira_conflito(session, up, up2, circuito_up):
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1, actor="cli")
    with pytest.raises(ConflictError, match="já vinculado"):
        svc.vincular_circuito(session, up2.id, circuito_up.id, papel="principal", ordem=1,
                              actor="cli")


def test_vincular_circuito_upstream_desativado_vira_conflito(session, up, circuito_up):
    svc.disable_upstream(session, up.id, actor="cli")
    with pytest.raises(ConflictError, match="desativado"):
        svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1,
                              actor="cli")


def test_vincular_circuito_circuito_desativado_vira_conflito(session, up, circuito_up):
    disable_circuit(session, circuito_up.id, actor="cli")
    with pytest.raises(ConflictError, match="desativado"):
        svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1,
                              actor="cli")


def test_vincular_circuito_inexistente(session, up):
    with pytest.raises(NotFoundError, match="não encontrado"):
        svc.vincular_circuito(session, up.id, 9999, papel="principal", ordem=1, actor="cli")


def test_vincular_propaga_e_audita(session, org_operadora, circuito_up, bgp_session_principal):
    up = svc.create_upstream(session, UpstreamCreate(
        name="transito-aud", tipo="transito", organization_id=org_operadora.id,
        expected_prefixes_v4=1000, max_prefix_margin_pct=10), actor="cli")
    svc.vincular_circuito(session, up.id, circuito_up.id, papel="principal", ordem=1, actor="cli")
    sess = session.get(models.BgpSession, bgp_session_principal.id)
    assert sess.maximum_prefix == 1100
    assert "upstream.vincular_circuito" in _audit_tipos(session)


def test_r01_upstream_ativo_nao_fica_sem_principal_ao_vinculizar(session, org_operadora,
                                                                 circuito_up):
    up = svc.create_upstream(session, UpstreamCreate(
        name="cont-x", tipo="transito", organization_id=org_operadora.id), actor="cli")
    with pytest.raises(ValidationError, match="principal"):
        svc.vincular_circuito(session, up.id, circuito_up.id, papel="contingencia", ordem=1,
                              actor="cli")
    assert svc.upstream_do_circuito(session, circuito_up.id) is None  # nada persistido


def test_r01_desvincular_ultimo_principal_vira_erro(session, up_com_2_circuitos):
    vinculados = list(session.scalars(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.upstream_id == up_com_2_circuitos.id).order_by(
            models.UpstreamCircuit.id)))
    principal = next(v for v in vinculados if v.papel == "principal")
    with pytest.raises(ValidationError, match="principal"):
        svc.desvincular_circuito(session, up_com_2_circuitos.id, principal.circuit_id, actor="cli")
    # vínculo preservado na sessão do teste (erro antes de remover)
    assert svc.upstream_do_circuito(session, principal.circuit_id).id == up_com_2_circuitos.id


def test_desvincular_circuito_remove_e_audita(session, up_com_circuito, circuito_up):
    svc.desvincular_circuito(session, up_com_circuito.id, circuito_up.id, actor="cli")
    assert svc.upstream_do_circuito(session, circuito_up.id) is None
    assert "upstream.desvincular_circuito" in _audit_tipos(session)


def test_circuito_nao_se_repetir_em_outro_upstream(session, up, up2, circuito_up):
    """BR-1 no banco: UNIQUE(circuit_id) barra circuito em dois upstreams (R-07)."""
    session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=circuito_up.id))
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(models.UpstreamCircuit(upstream_id=up2.id, circuit_id=circuito_up.id))
        session.commit()
    session.rollback()  # integridade da sessão pós-IntegrityError (padrão test_upstream_models:31)


def test_update_upstream_nome_nulo_vira_erro_de_validacao(session, up):
    """name explicitamente None não pode estourar TypeError — 400 ValidationError."""
    with pytest.raises(ValidationError, match="Nome do upstream"):
        svc.update_upstream(session, up.id, UpstreamUpdate(name=None), actor="cli")
