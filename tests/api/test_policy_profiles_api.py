import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_lista_catalogo_so_leitura(client: TestClient) -> None:
    lista = client.get("/api/v1/policy-profiles", headers=_auth()).json()
    assert [p["name"] for p in lista] == [
        "cdn", "default", "default_internas", "full", "parcial", "personalizado",
        "somente-autorizadas",
    ]
    so_export = client.get("/api/v1/policy-profiles?direction=export", headers=_auth()).json()
    assert len(so_export) == 6 and all(p["direction"] == "export" for p in so_export)
    so_import = client.get("/api/v1/policy-profiles?direction=import", headers=_auth()).json()
    assert [p["name"] for p in so_import] == ["somente-autorizadas"]
    assert client.post("/api/v1/policy-profiles", json={}, headers=_auth()).status_code == 405


def test_direction_invalida_da_400(client: TestClient) -> None:
    resp = client.get("/api/v1/policy-profiles?direction=foo", headers=_auth())
    assert resp.status_code == 400
    assert "Direção inválida" in resp.json()["detail"]


def test_patch_policy_profile_ruling_1(client: TestClient, db_session: Session) -> None:
    perfil = models.PolicyProfile(
        name="api-c3-perfil", label="Perfil API", direction="export", kind="produto", prefixes=None
    )
    db_session.add(perfil)
    db_session.commit()
    try:
        off = client.patch(
            f"/api/v1/policy-profiles/{perfil.id}", json={"admin_status": False}, headers=_auth()
        )
        assert off.status_code == 200 and off.json()["admin_status"] is False
        assert perfil.id not in [
            p["id"] for p in client.get("/api/v1/policy-profiles", headers=_auth()).json()
        ]
        on = client.patch(
            f"/api/v1/policy-profiles/{perfil.id}", json={"admin_status": True}, headers=_auth()
        )
        assert on.status_code == 200 and on.json()["admin_status"] is True
        assert on.json()["id"] == perfil.id  # id no schema de resposta
        edit = client.patch(
            f"/api/v1/policy-profiles/{perfil.id}",
            json={"label": "Perfil API 2", "direction": "import"},
            headers=_auth(),
        )
        assert edit.status_code == 200 and edit.json()["label"] == "Perfil API 2"
        assert edit.json()["direction"] == "import"
        # 404 e sem auth
        assert client.patch("/api/v1/policy-profiles/99999", json={"label": "x"}, headers=_auth()).status_code == 404
        assert client.patch(f"/api/v1/policy-profiles/{perfil.id}", json={"label": "x"}).status_code == 401
    finally:
        perfil = db_session.get(models.PolicyProfile, perfil.id)
        if perfil is not None:
            db_session.delete(perfil)
            db_session.commit()
