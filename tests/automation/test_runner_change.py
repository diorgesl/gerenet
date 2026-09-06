"""run_change (spec §6/§5.3): execução de CR aprovada com fake de coleta/aplicação."""
from pathlib import Path

import pytest
from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation import render
from gerenet.automation.runner import run_change
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.models import CredentialGroup
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


class VaultFake:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _ambiente(db_session: Session) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-cr", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    # Grupo de credencial para o device (como _dev_com_grupo do test_runner):
    # sem ele o step falharia em "não possui grupo de credencial" antes do lock.
    grupo = CredentialGroup(
        name="automacao-cr", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao-cr"
    )
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(
        db_session,
        DeviceCreate(name="ne-cr", management_address="10.0.0.1", asn=65000, credential_group_id=grupo.id),
        actor="cli",
    )
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-cr", asn=64512), actor="cli")

    return {"site": site, "dev": dev, "org": org}


def _circuito(db_session: Session, amb: dict):
    from gerenet.domain.schemas import BgpSessionCreate, CircuitCreate

    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CR-RUN-1", organization_id=amb["org"].id, site_id=amb["site"].id,
            access_device_id=amb["dev"].id, access_port="GE0/0/1",
            edge_device_id=amb["dev"].id, stack="ipv4", vlan_mode="unica",
            edge_trunk="GE1/0/0", p2p_v4_len=31,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=amb["dev"].id, afi="ipv4",
            local_address="100.64.1.1", remote_address="100.64.1.2",
            asn_local=65000, asn_remote=64512,
        ),
        actor="cli",
    )
    db_session.commit()
    return circ


def _cr_aprovada(db_session: Session, circ, dev) -> models.ChangeRequest:
    """CR aprovada direto (setup de teste: o plano real vem do render do circuito)."""
    from gerenet.automation.changes import plan_provision

    plano = plan_provision(db_session, circ)
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao="provision", criticidade="media",
        motivo="Ativação.", status="aprovado",
    )
    db_session.add(cr)
    db_session.flush()
    for item in plano:
        db_session.add(models.ChangeStep(
            change_request_id=cr.id, device_id=item.device_id, status="pendente",
            plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
            aviso=item.aviso,
        ))
    db_session.commit()
    db_session.refresh(cr)
    return cr


def _recursos_vazios(db_session: Session, dev) -> dict:
    """Encontrado sem nada do circuito — re-diff não vê skip, aplica tudo."""
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [], "bgp_peers": [],
    }


def _recursos_aplicados(db_session: Session, dev) -> dict:
    """Encontrado = desejado (render aplicado) — reconciliador pós-mudança sem critica."""
    r = render.render_desejado(db_session, dev.id)
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [
            {"nome": b.comandos[0].split(None, 1)[1]} for b in r.blocos if b.tipo == "subinterface"
        ],
        "bgp_peers": [
            {"afi": "ipv4", "peer": b.comandos[1].split()[1], "asn": 64512}
            for b in r.blocos if b.tipo == "bgp_peer"
        ],
    }


def _estado_subif_presenca(db_session: Session, dev) -> dict:
    """Encontrado com a subinterface do plano (nome real do render) presente, sem mais nada.

    A identidade de subinterface é o NOME (§5.1): presente no encontrado sem o
    restante do esperado ⇒ estado divergente (o plano congelado ficou desatualizado).
    """
    r = render.render_desejado(db_session, dev.id)
    nome = next(b.comandos[0].split(None, 1)[1] for b in r.blocos if b.tipo == "subinterface")
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [{"nome": nome}],
        "bgp_peers": [],
    }


def _fakes_de_mudanca(monkeypatch: pytest.MonkeyPatch, db_session: Session, dev, colas: list[dict]):
    """Orquestra as fakes: cola retorna uma coleção por chamada (pré → pós)."""
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    ultimo: list[dict | None] = [None]

    def _coleta(session, device, cred, settings, base):
        recursos = colas.pop(0) if colas else ultimo[0]
        ultimo[0] = recursos
        return dict(recursos), {}, {}

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_aplicar",
        lambda device, username, password, commands, settings: {"config": ("\n".join(commands) + "\n")},
    )


def test_run_change_fluxo_ok_cr_aplicada(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    colas = [_recursos_vazios(db_session, amb["dev"]), _recursos_aplicados(db_session, amb["dev"])]
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"

    db_session.refresh(cr)
    assert cr.status == "aplicado"
    step = cr.steps[0]
    assert step.status == "aplicado"
    assert step.backup_snapshot_id is not None
    assert step.post_check_json and "items" in step.post_check_json
    assert step.erro is None
    jobs = db_session.query(models.JobRun).filter_by(kind="change", device_id=amb["dev"].id).all()
    assert len(jobs) == 1
    assert jobs[0].status == "success"
    eventos = db_session.query(models.AuditEvent).filter_by(type="change.applied").all()
    assert len(eventos) == 1


def test_run_change_erro_vrp_no_meio_marca_cr_erro(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._coleta_recursos",
        lambda session, device, cred, settings, base: (_recursos_vazios(db_session, amb["dev"]), {}, {}),
    )

    def _falha(device, username, password, commands, settings):
        return {"config": f"{commands[0]}\n% Error: Incomplete command found"}

    monkeypatch.setattr("gerenet.automation.runner._conectar_e_aplicar", _falha)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.status == "erro"
    assert cr.steps[0].status == "falhou"
    assert "Error" in (cr.steps[0].erro or "")
    job = db_session.query(models.JobRun).filter_by(kind="change").first()
    assert job.status == "error"
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_failed").count() == 1


def test_run_change_bloco_ja_presente_marca_step_pulado(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [_recursos_aplicados(db_session, amb["dev"])])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert cr.steps[0].status == "pulado"
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_skipped").count() == 1


def test_run_change_estado_divergente_aborta(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Subinterface existe com endereço diferente do plano congelado ⇒ aborta (§5.3)."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    # subinterface do plano PRESENTE (por nome), sem o restante do esperado —
    # o peer do circuito ainda não existe ⇒ parte do plano consta, parte não.
    recursos_divergentes = _estado_subif_presenca(db_session, amb["dev"])
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [recursos_divergentes])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    assert "divergente" in (cr.steps[0].erro or "")
    # conexão de aplicação nunca aconteceu
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_failed").count() == 1


def test_run_change_post_check_critica_vira_com_divergencia(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    # aplicado, mas o peer ainda não consta do pós-coleta (subinterface consta).
    recursos_que_nao_incluem_peer = _estado_subif_presenca(db_session, amb["dev"])
    # PRÉ vazio (aplica tudo); PÓS sem o peer — pós-check crítico ⇒ com_divergencia.
    colas = [_recursos_vazios(db_session, amb["dev"]), recursos_que_nao_incluem_peer]
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "com_divergencia"
    db_session.refresh(cr)
    assert cr.status == "com_divergencia"
    assert cr.steps[0].status == "aplicado"
    assert any(i["severidade"] == "critica" for i in cr.steps[0].post_check_json["items"])
    assert db_session.query(models.AuditEvent).filter_by(type="change.com_divergencia").count() == 1


def test_run_change_lock_por_device_impede_etapa(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    # sem fake de coleta: deve falhar ANTES, no lock.
    redis = Redis.from_url(Settings(_env_file=None, backups_dir=tmp_path).redis_url)
    chave = f"gerenet:lock:device:{amb['dev'].id}"
    redis.set(chave, "outro", nx=True, ex=300)
    try:
        resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
        assert resultado["status"] == "erro"
        db_session.refresh(cr)
        assert cr.status == "erro"
        assert "lock" in (cr.steps[0].erro or "")
    finally:
        redis.delete(chave)
        redis.close()
