"""API do fluxo de mudança (spec §8): contratos, papéis e transições."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
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


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _cria_cenario(
    db_session: Session, *, com_sessao: bool = True, com_snapshot: bool = True
) -> int:
    """Circuito reservado com sessão BGP v4 — retorna circuit_id."""
    site = create_site(
        db_session, SiteCreate(name="pop-cr-api", p2p_ipv4_block="10.60.0.0/24"), actor="cli"
    )
    ne = create_device(
        db_session,
        DeviceCreate(name="ne-cr-api", management_address="10.60.0.1", asn=65000),
        actor="cli",
    )
    link_device(db_session, site.id, ne.id, actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="cliente-cr-api", asn=64512), actor="cli"
    )
    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CR-API-1",
            organization_id=org.id,
            site_id=site.id,
            access_device_id=ne.id,
            access_port="GE0/0/1",
            edge_device_id=ne.id,
            edge_trunk="GE1/0/0",
            stack="ipv4",
            vlan_mode="unica",
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    if com_sessao:
        create_session(
            db_session,
            BgpSessionCreate(
                circuit_id=circ.id,
                device_id=ne.id,
                afi="ipv4",
                local_address="10.0.0.1",
                remote_address="10.0.0.2",
                asn_local=65000,
                asn_remote=64512,
            ),
            actor="cli",
        )
    if com_snapshot:
        # Snapshot com recursos (encontrado real, sem nada deste circuito): o
        # plano da ativação sai cheio, baseline congelado e aviso None (T3:
        # tem_recursos).
        db_session.add(
            models.DeviceSnapshot(
                device_id=ne.id,
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


def _usuario(db_session: Session, username: str, role: str) -> None:
    usvc.create_user(db_session, username=username, password="senha-super-8", role=role, actor="cli")
    db_session.commit()


def _login(client: TestClient, username: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": "senha-super-8"})
    assert resp.status_code == 200, resp.text


def _cria_cr(client: TestClient, circuit_id: int) -> dict:
    resp = client.post(
        "/api/v1/change-requests",
        json={"circuit_id": circuit_id, "acao": "provision", "motivo": "Ativação.", "criticidade": "media"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_criar_listar_detalhar_404(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    assert cr["status"] == "rascunho"
    assert len(cr["steps"]) == 1
    assert cr["steps"][0]["plano_json"]
    assert cr["approvals"] == []
    assert cr["steps"][0]["aviso"] is None
    assert "password" not in str(cr)  # nada de segredo no payload (spreadcheck)

    lista = client.get("/api/v1/change-requests", headers=_auth())
    assert lista.status_code == 200
    assert [c["id"] for c in lista.json()] == [cr["id"]]
    assert client.get("/api/v1/change-requests?status=aprovado", headers=_auth()).json() == []
    assert client.get("/api/v1/change-requests/9999", headers=_auth()).status_code == 404


def test_fluxo_enviar_transicao_invalida_cancelar(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    env = client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth())
    assert env.status_code == 200
    assert env.json()["status"] == "aguardando_aprovacao"
    # repetido → 400 (transição inválida)
    assert client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth()).status_code == 400
    # cancelamento de aguardando_aprovacao
    can = client.post(f"/api/v1/change-requests/{cr['id']}/cancelar", headers=_auth())
    assert can.json()["status"] == "cancelado"


def test_approve_somente_papel_e_uma_vez(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    _usuario(db_session, "aprovador-api", "aprovador")
    _usuario(db_session, "operador-api", "operador")
    client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth())

    # chave de API não é pessoa → 403
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}, headers=_auth()
    ).status_code == 403
    # operador não aprova → 403
    _login(client, "operador-api")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 403
    # aprovador aprova
    client.post("/api/v1/auth/logout")
    _login(client, "aprovador-api")
    ok = client.post(
        f"/api/v1/change-requests/{cr['id']}/approve",
        json={"decisao": "aprovar", "comentario": "janela ok"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "aprovado"
    assert ok.json()["approvals"][0]["comentario"] == "janela ok"
    # duplicada → 400
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 400


def test_executar_marca_executando(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    _usuario(db_session, "aprovador-ex", "aprovador")
    _usuario(db_session, "executor-ex", "executor")
    client.post(f"/api/v1/change-requests/{cr['id']}/enviar", headers=_auth())
    _login(client, "aprovador-ex")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 200
    client.post("/api/v1/auth/logout")
    # executor não aprova, mas executa
    _login(client, "executor-ex")
    assert client.post(
        f"/api/v1/change-requests/{cr['id']}/approve", json={"decisao": "aprovar"}
    ).status_code == 403
    exec = client.post(f"/api/v1/change-requests/{cr['id']}/executar")
    assert exec.status_code == 200
    assert exec.json()["status"] == "executando"


def test_rollback_gera_cr_filho_inverso(client: TestClient, db_session: Session) -> None:
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    modelo = db_session.get(models.ChangeRequest, cr["id"])
    modelo.status = "aplicado"
    modelo.steps[0].status = "aplicado"  # gerar_rollback exige ≥1 step aplicado
    db_session.commit()
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/rollback", headers=_auth())
    assert resp.status_code == 200
    filho = resp.json()
    assert filho["acao"] == "remove"
    assert filho["rollback_de"] == cr["id"]
    assert filho["status"] == "aguardando_aprovacao"
    # Baseline congelado ⇒ filho NASCE com steps; blocos vêm do encontrado do
    # baseline (aqui não tem nada deste circuito: evidência honesta, §5.2).
    assert len(filho["steps"]) == 1
    assert filho["steps"][0]["plano_json"] == []


def test_criar_provision_sem_sessoes_rejeita_422(client: TestClient, db_session: Session) -> None:
    """Nota mandatória T3: CR vazia é inexplicável — a API rejeita a criação."""
    cid = _cria_cenario(db_session, com_sessao=False, com_snapshot=False)
    resp = client.post(
        "/api/v1/change-requests",
        json={"circuit_id": cid, "acao": "provision", "motivo": "Plano vazio.", "criticidade": "media"},
        headers=_auth(),
    )
    assert resp.status_code == 422
    body = resp.json()["detail"].lower()
    assert "sem sessões" in body
    assert "cadastre" in body
    # nada órfão: a rejeição é anterior à criação (pre-check por sessões ativas)
    assert client.get("/api/v1/change-requests", headers=_auth()).json() == []


def test_rollback_sem_baseline_rejeita_422(client: TestClient, db_session: Session) -> None:
    """Nota mandatória T4: filho sem steps (sem baseline) = rollback não automático.

    A rejeição acontece no serviço ANTES do commit — nenhum filho órfão
    persiste (revisão T5).
    """
    cid = _cria_cenario(db_session)
    cr = _cria_cr(client, cid)
    modelo = db_session.get(models.ChangeRequest, cr["id"])
    modelo.status = "aplicado"
    modelo.steps[0].status = "aplicado"
    modelo.steps[0].baseline_snapshot_id = None
    db_session.commit()
    antes = len(db_session.scalars(select(models.ChangeRequest)).all())
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/rollback", headers=_auth())
    assert resp.status_code == 422
    assert "baseline" in resp.json()["detail"].lower()
    assert "manual" in resp.json()["detail"].lower()
    # sem CR filho: rollback_de em outro objeto, sequência id inalterada
    filhos = db_session.scalars(select(models.ChangeRequest).where(models.ChangeRequest.rollback_de == cr["id"])).all()
    assert filhos == []
    assert len(db_session.scalars(select(models.ChangeRequest)).all()) == antes
