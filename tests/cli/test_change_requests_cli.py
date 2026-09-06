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
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services import users as usvc
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device

runner = CliRunner()


def _circuito(db_session: Session) -> int:
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
