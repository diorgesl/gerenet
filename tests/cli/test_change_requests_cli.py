"""CLI do fluxo de mudança (spec ciclo D §8.1): smoke via CliRunner + DB real."""
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    L2vcCreate,
    L2vcEndpointIn,
    MplsDomainCreate,
    MplsMemberIn,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services import users as usvc
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.mpls import add_domain_member, create_domain, create_l2vc
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device

runner = CliRunner()


def _circuito(db_session: Session, *, com_sessao: bool = True) -> int:
    site = create_site(
        db_session, SiteCreate(name="pop-cr-cli", p2p_ipv4_block="10.0.0.0/24"), actor="cli"
    )
    dev = create_device(
        db_session,
        DeviceCreate(name="ne-cr-cli", management_address="10.0.0.1", asn=65000),
        actor="cli",
    )
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="cliente-cr-cli", asn=64512), actor="cli"
    )
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CR-CLI-1",
            organization_id=org.id,
            site_id=site.id,
            access_device_id=dev.id,
            access_port="GE0/0/1",
            edge_device_id=dev.id,
            edge_trunk="GE1/0/0",
            p2p_v4_len=31,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    if com_sessao:
        create_session(
            db_session,
            BgpSessionCreate(
                circuit_id=circ.id,
                device_id=dev.id,
                afi="ipv4",
                local_address="10.0.0.1",
                remote_address="10.0.0.2",
                asn_local=65000,
                asn_remote=64512,
            ),
            actor="cli",
        )
    # Snapshot com recursos (encontrado real, sem nada deste circuito): o
    # plano da ativação sai cheio, baseline congelado — sem ele o rollback do
    # CLI falharia com PlanoRollbackVazio (baseline ausente, §5.2).
    db_session.add(
        models.DeviceSnapshot(
            device_id=dev.id,
            status="success",
            resources={
                "version": {"version": "8.210", "uptime": "10 days"},
                "interfaces": [],
                "bgp_peers": [],
            },
        )
    )
    db_session.commit()
    return circ.id


def _aprovador(db_session: Session) -> None:
    """Usuário aprovador para o CLI (aprovar exige ator_id ≠ None, §4.3)."""
    usvc.create_user(
        db_session,
        username="aprovador-cli",
        password="senha-super-8",
        role="aprovador",
        actor="cli",
    )
    db_session.commit()


def _cr_id(add_output: str) -> int:
    return int(add_output.split("CR #")[1].split()[0])


def test_cli_add_list_show_erros(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    assert add.exit_code == 0, add.output
    assert "rascunho" in add.output
    cr_id = _cr_id(add.output)
    assert f"CR #{cr_id}" in runner.invoke(app, ["change-requests", "list"]).output

    show = runner.invoke(app, ["change-requests", "show", str(cr_id)])
    assert show.exit_code == 0, show.output
    assert "subinterface" in show.output
    assert "pendente" in show.output

    sem_circuito = runner.invoke(app, ["change-requests", "add", "--circuit-id", "9999", "--motivo", "X"])
    assert sem_circuito.exit_code == 1
    assert "Erro:" in sem_circuito.output
    inexistente = runner.invoke(app, ["change-requests", "show", "9999"])
    assert inexistente.exit_code == 1
    assert "não encontrada" in inexistente.output


def test_cli_send_approve_fluxo(db_session: Session) -> None:
    cid = _circuito(db_session)
    _aprovador(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    env = runner.invoke(app, ["change-requests", "send", str(cr_id)])
    assert env.exit_code == 0, env.output
    assert "aprova" in env.output
    ap = runner.invoke(
        app,
        ["change-requests", "approve", str(cr_id), "--comentario", "janela ok", "--aprovador", "aprovador-cli"],
    )
    assert ap.exit_code == 0, ap.output
    cr = db_session.get(models.ChangeRequest, cr_id)
    assert cr.status == "aprovado"
    assert cr.approvals[0].decisao == "aprovar"
    # aprovar de novo ⇒ erro de negócio (decisão única)
    de_novo = runner.invoke(
        app, ["change-requests", "approve", str(cr_id), "--aprovador", "aprovador-cli"]
    )
    assert de_novo.exit_code == 1
    assert "Erro:" in de_novo.output


def test_cli_execute_enfileira_e_marca_executando(db_session: Session) -> None:
    cid = _circuito(db_session)
    _aprovador(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    runner.invoke(app, ["change-requests", "send", str(cr_id)])
    runner.invoke(app, ["change-requests", "approve", str(cr_id), "--aprovador", "aprovador-cli"])

    with patch(
        "gerenet.cli.change_requests.enqueue_change",
        return_value={"queued": True, "job_id": "job-1", "message": "Mudança enfileirada."},
    ) as enfileirar:
        ok = runner.invoke(app, ["change-requests", "execute", str(cr_id)])
    assert ok.exit_code == 0, ok.output
    assert "enfileirada" in ok.output
    enfileirar.assert_called_once_with(cr_id, actor="cli", origin="cli")
    assert db_session.get(models.ChangeRequest, cr_id).status == "executando"


def test_cli_execute_sem_aprovacao_da_erro(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    erro = runner.invoke(app, ["change-requests", "execute", str(cr_id)])
    assert erro.exit_code == 1
    assert "Erro:" in erro.output
    assert "aprovada" in erro.output


def test_cli_rollback_gera_filho(db_session: Session) -> None:
    cid = _circuito(db_session)
    add = runner.invoke(app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."])
    cr_id = _cr_id(add.output)
    cr = db_session.get(models.ChangeRequest, cr_id)
    cr.status = "aplicado"
    cr.steps[0].status = "aplicado"  # gerar_rollback exige ≥1 step aplicado
    db_session.commit()
    rb = runner.invoke(app, ["change-requests", "rollback", str(cr_id)])
    assert rb.exit_code == 0, rb.output
    filho = db_session.scalar(
        select(models.ChangeRequest).where(models.ChangeRequest.rollback_de == cr_id)
    )
    assert filho is not None
    assert filho.acao == "remove"
    assert filho.status == "aguardando_aprovacao"
    assert "rollback" in rb.output


def test_add_motivo_vazio_erro_limpo(db_session: Session) -> None:
    """Fix A (revisão final): SchemaValidationError do create é erro limpo de CLI
    (exit 1 + "Erro:"), sem traceback — parity com circuits.py."""
    cid = _circuito(db_session)
    add = runner.invoke(
        app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", ""]
    )
    assert add.exit_code == 1
    assert "Erro:" in add.output
    assert "Traceback" not in add.output


def test_add_sem_sessoes_ativas_nao_cria_cr(db_session: Session) -> None:
    """Fix B (revisão final): circuito sem sessões ativas ⇒ erro limpo do serviço
    (exit 1) e nenhuma CR persistida."""
    cid = _circuito(db_session, com_sessao=False)
    add = runner.invoke(
        app, ["change-requests", "add", "--circuit-id", str(cid), "--motivo", "Ativação."]
    )
    assert add.exit_code == 1
    assert "Erro: Circuito sem sessões ativas" in add.output
    assert (
        db_session.scalar(
            select(models.ChangeRequest).where(models.ChangeRequest.circuit_id == cid)
        )
        is None
    )


def _l2vc_cli(db_session: Session) -> int:
    """L2VC com site + 2 switches (site_id em ambos — regra T3 da reserva de VLAN de AC)."""
    site = create_site(db_session, SiteCreate(name="pop-cr-cli-l2vc"), actor="cli")
    d1 = create_device(db_session, DeviceCreate(
        name="sw-cr-cli-a", management_address="10.0.0.71", site_id=site.id), actor="cli")
    d2 = create_device(db_session, DeviceCreate(
        name="sw-cr-cli-b", management_address="10.0.0.72", site_id=site.id), actor="cli")
    dom = create_domain(db_session, MplsDomainCreate(name="dom-cr-cli"), actor="cli")
    add_domain_member(db_session, dom.id,
                      MplsMemberIn(device_id=d1.id, loopback_address="10.255.9.1"), actor="cli")
    add_domain_member(db_session, dom.id,
                      MplsMemberIn(device_id=d2.id, loopback_address="10.255.9.2"), actor="cli")
    svc = create_l2vc(db_session, L2vcCreate(
        domain_id=dom.id, name="l2vc-cr-cli", vc_id=901,
        endpoints=[
            L2vcEndpointIn(device_id=d1.id, interface="10GE0/0/1", encapsulation="dot1q", vid=431),
            L2vcEndpointIn(device_id=d2.id, interface="10GE0/0/2", encapsulation="dot1q", vid=432),
        ],
    ), actor="cli")
    db_session.commit()
    return svc.id


def test_cli_add_escopo_l2vc(db_session: Session) -> None:
    """Fumo (T8, Step 4): change-requests add --escopo l2vc --l2vc-id N nasce rascunho
    com 2 steps (uma por ponta), como a CR de circuito."""
    l2vc_id = _l2vc_cli(db_session)
    add = runner.invoke(app, [
        "change-requests", "add", "--escopo", "l2vc", "--l2vc-id", str(l2vc_id),
        "--motivo", "Ativar L2VC do cliente.",
    ])
    assert add.exit_code == 0, add.output
    assert "rascunho" in add.output
    cr_id = _cr_id(add.output)
    cr = db_session.get(models.ChangeRequest, cr_id)
    assert cr is not None and cr.escopo == "l2vc"
    assert len(cr.steps) == 2
    assert cr.circuit_id is None and cr.l2vc_id == l2vc_id


def test_cli_add_list_show_escopo_upstream(db_session: Session,
                                           up_com_2_circuitos) -> None:
    """Task 15 (C4): add --escopo upstream --upstream-id N nasce rascunho com
    steps; list --escopo upstream e list sem filtro mostram "upstream N" no
    lugar de "circuito None"; show é escopo-independente (funciona como está)."""
    up = up_com_2_circuitos
    add = runner.invoke(app, [
        "change-requests", "add", "--escopo", "upstream", "--upstream-id", str(up.id),
        "--motivo", "Subir trânsito.",
    ])
    assert add.exit_code == 0, add.output
    assert "rascunho" in add.output
    cr_id = _cr_id(add.output)
    cr = db_session.get(models.ChangeRequest, cr_id)
    assert cr is not None and cr.escopo == "upstream"
    assert cr.upstream_id == up.id and cr.circuit_id is None
    assert cr.steps and all(s.plano_json for s in cr.steps)

    filtrada = runner.invoke(app, ["change-requests", "list", "--escopo", "upstream"])
    assert filtrada.exit_code == 0, filtrada.output
    linha = next(l for l in filtrada.output.splitlines() if f"CR #{cr_id}" in l)
    assert "upstream" in linha and str(up.id) in linha
    assert "circuito None" not in filtrada.output

    geral = runner.invoke(app, ["change-requests", "list"])
    assert geral.exit_code == 0, geral.output
    assert f"CR #{cr_id}" in geral.output

    show = runner.invoke(app, ["change-requests", "show", str(cr_id)])
    assert show.exit_code == 0, show.output
    assert "step" in show.output


def test_cli_add_upstream_sem_id_erro_limpo(db_session: Session) -> None:
    """Task 15 (C4): escopo upstream sem --upstream-id ⇒ erro do schema, exit 1."""
    add = runner.invoke(app, [
        "change-requests", "add", "--escopo", "upstream", "--motivo", "sem id",
    ])
    assert add.exit_code == 1
    assert "Erro:" in add.output
    assert "Traceback" not in add.output


def test_cli_add_upstream_sem_vinculos_nao_cria_cr(db_session: Session, up) -> None:
    """Task 15 (C4): upstream sem circuitos/sessões ativas ⇒ erro limpo do
    serviço (exit 1) e nenhuma CR persistida — sem órfão no banco."""
    add = runner.invoke(app, [
        "change-requests", "add", "--escopo", "upstream", "--upstream-id", str(up.id),
        "--motivo", "Plano vazio.",
    ])
    assert add.exit_code == 1
    assert "Erro:" in add.output
    assert "sem circuitos/sessões ativas" in add.output
    assert (
        db_session.scalar(
            select(models.ChangeRequest).where(models.ChangeRequest.upstream_id == up.id)
        )
        is None
    )
