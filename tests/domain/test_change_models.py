"""Smoke dos modelos do fluxo de mudança — ciclo D, spec §4."""
from gerenet.domain import models


def test_enums_tem_os_valores_do_spec():
    assert models.CHANGE_ACTION == ("provision", "remove")
    assert models.CHANGE_CRITICALITY == ("baixa", "media", "alta")
    assert models.CHANGE_STATUS == (
        "rascunho", "aguardando_aprovacao", "aprovado", "executando",
        "aplicado", "com_divergencia", "parcial", "erro", "rejeitado", "cancelado",
    )
    assert models.CHANGE_STEP_STATUS == ("pendente", "aplicado", "pulado", "falhou", "rollback")
    assert models.APPROVAL_DECISION == ("aprovar", "rejeitar")


def test_modelos_existem_e_tabelas_esperadas():
    assert models.ChangeRequest.__tablename__ == "change_requests"
    assert models.ChangeStep.__tablename__ == "change_steps"
    assert models.Approval.__tablename__ == "approvals"


def test_criar_change_request_com_circuito(db_session):
    """FKs reais: circuito/device/organization + solicitante (aprovação exige usuário)."""
    from gerenet.domain.schemas import (
        CircuitCreate,
        DeviceCreate,
        OrganizationCreate,
        SiteCreate,
    )
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site
    from gerenet.domain.services.users import create_user

    site = create_site(db_session, SiteCreate(name="pop-teste"), actor="cli")
    # site_id no create_device: o serviço de circuito exige o edge no site do POP.
    dev = create_device(
        db_session,
        DeviceCreate(name="r1", management_address="10.0.0.1", asn=65000, site_id=site.id),
        actor="cli",
    )
    # 64512: ASN fora das faixas reservadas (§14.1) — 64500 é doc/uso de teste (RFC 5398).
    org = create_organization(db_session, OrganizationCreate(name="cliente", asn=64512), actor="cli")
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="circ-1", organization_id=org.id, site_id=site.id,
            access_device_id=dev.id, access_port="GE0/0/1",
            edge_device_id=dev.id, stack="ipv4", vlan_mode="unica",
        ),
        actor="cli",
    )
    sol = create_user(db_session, username="operador", password="senha12345", role="operador")
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao="provision", criticidade="media",
        motivo="Ativação do circuito.", solicitante_id=sol.id, status="rascunho",
    )
    db_session.add(cr)
    db_session.commit()
    assert cr.id is not None
    assert cr.status == "rascunho"

    step = models.ChangeStep(
        change_request_id=cr.id, device_id=dev.id, status="pendente",
        plano_json=[{"tipo": "subinterface", "objeto": "circuit", "objeto_id": circ.id,
                     "acao": "create", "comandos": ["interface GE0/0/1.100"]}],
    )
    db_session.add(step)
    db_session.commit()

    ap = models.Approval(
        change_request_id=cr.id, user_id=sol.id, decisao="aprovar", comentario="ok"
    )
    db_session.add(ap)
    db_session.commit()
    assert ap.id is not None
    assert cr.approvals[0].comentario == "ok"
