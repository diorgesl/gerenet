"""API de CR com escopo upstream (fase 5, §7) — contrato da Task 15 (C4).

Espelho de `test_change_requests_api.py` (circuito) e do fumo l2vc: POST
cria a CR já planejada (201 com steps por device), upstream sem vínculos ⇒
422 (PlanoVazio, sem CR órfã), GET `?escopo=upstream` filtra e expõe
`upstream_name`, e o `/executar` continua 202 (a rota é escopo-independente —
o enqueue é patched, sem worker real).
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.services import users as usvc


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _usuario(db_session: Session, username: str, role: str) -> None:
    usvc.create_user(db_session, username=username, password="senha-super-8", role=role, actor="cli")
    db_session.commit()


def _login(client: TestClient, username: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": "senha-super-8"})
    assert resp.status_code == 200, resp.text


def _cria_cr_upstream(client: TestClient, upstream_id: int) -> dict:
    resp = client.post(
        "/api/v1/change-requests",
        json={"escopo": "upstream", "upstream_id": upstream_id, "acao": "provision",
              "motivo": "Subir trânsito.", "criticidade": "alta"},
        headers=_auth(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cr_controle(db_session: Session) -> int:
    """CR de escopo circuito (controle do filtro de listagem), direto no banco."""
    cr = models.ChangeRequest(
        circuit_id=None, escopo="circuito", acao="provision",
        criticidade="media", motivo="controle de filtro", status="rascunho",
    )
    db_session.add(cr)
    db_session.commit()
    return cr.id


def test_criar_cr_escopo_upstream(client: TestClient, db_session: Session,
                                  up_com_2_circuitos: models.Upstream) -> None:
    """POST escopo upstream nasce rascunho com steps por device e upstream_name."""
    up = up_com_2_circuitos
    cr = _cria_cr_upstream(client, up.id)
    assert cr["escopo"] == "upstream"
    assert cr["upstream_id"] == up.id
    assert cr["circuit_id"] is None
    assert cr["status"] == "rascunho"
    assert cr["upstream_name"] == up.name
    assert cr["steps"] and all(s["plano_json"] for s in cr["steps"])


def test_criar_cr_upstream_sem_vinculos_422(client: TestClient, db_session: Session,
                                            up: models.Upstream) -> None:
    """Upstream sem circuitos/sessões ativas ⇒ 422 PlanoVazio, sem CR órfã.

    Idem circuito (§5): a rejeição é anterior ao commit — nada fica na lista.
    """
    resp = client.post(
        "/api/v1/change-requests",
        json={"escopo": "upstream", "upstream_id": up.id, "acao": "provision",
              "motivo": "Plano vazio.", "criticidade": "media"},
        headers=_auth(),
    )
    assert resp.status_code == 422, resp.text
    assert "sem circuitos/sessões ativas" in resp.json()["detail"].lower()
    assert client.get("/api/v1/change-requests", headers=_auth()).json() == []
    # incoerência do schema: escopo upstream sem upstream_id é rejeitado pela
    # validação (422), nunca chega ao serviço.
    sem_id = client.post(
        "/api/v1/change-requests",
        json={"escopo": "upstream", "acao": "provision", "motivo": "sem id"},
        headers=_auth(),
    )
    assert sem_id.status_code == 422


def test_listar_escopo_upstream_filtra_e_traz_nome(
    client: TestClient, db_session: Session, up_com_2_circuitos: models.Upstream
) -> None:
    """GET ?escopo=upstream traz só CR upstream e o corpo expõe upstream_name."""
    up = up_com_2_circuitos
    cr_up = _cria_cr_upstream(client, up.id)
    controle = _cr_controle(db_session)

    filtrada = client.get("/api/v1/change-requests?escopo=upstream", headers=_auth())
    assert filtrada.status_code == 200
    corpos = filtrada.json()
    assert [c["id"] for c in corpos] == [cr_up["id"]]
    assert corpos[0]["escopo"] == "upstream"
    assert corpos[0]["upstream_name"] == up.name
    assert corpos[0]["circuit_id"] is None

    geral = client.get("/api/v1/change-requests", headers=_auth())
    assert geral.status_code == 200
    assert {c["id"] for c in geral.json()} == {cr_up["id"], controle}


def test_executar_upstream_enfileira_e_marca_executando(
    client: TestClient, db_session: Session, up_com_2_circuitos: models.Upstream
) -> None:
    """Fumo do executar: a rota é escopo-independente — 202 + enqueue + status.

    (o enqueue real validaria no worker; aqui o patch segura a fila — mesmo
    padrão do fumo do circuito.)
    """
    up = up_com_2_circuitos
    cr = _cria_cr_upstream(client, up.id)
    _usuario(db_session, "executor-up", "executor")
    modelo = db_session.get(models.ChangeRequest, cr["id"])
    modelo.status = "aprovado"  # enqueue patched: estado coerente basta
    db_session.commit()
    _login(client, "executor-up")
    with patch(
        "gerenet.api.routers.change_requests.enqueue_change",
        return_value={"queued": True, "job_id": "abc123", "message": "Mudança enfileirada."},
    ) as enfileirar:
        exec = client.post(f"/api/v1/change-requests/{cr['id']}/executar")
    assert exec.status_code == 202, exec.text
    assert exec.json()["queued"] is True
    enfileirar.assert_called_once_with(cr["id"], actor="executor-up", origin="api")
    # expire_all: a sessão de teste tem o CR no identity map (status "aprovado")
    # e o SessionLocal usa expire_on_commit=False — relê do banco p/ ver a
    # transição do app.
    db_session.expire_all()
    assert db_session.get(models.ChangeRequest, cr["id"]).status == "executando"
