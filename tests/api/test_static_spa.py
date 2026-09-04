from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings

DIST = Path("/tmp/gerenet-spa-fake")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "web" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>gerenet</html>", encoding="utf-8")
    (assets / "app.abc123.js").write_text("console.log(1)", encoding="utf-8")
    set_settings(Settings(api_key="teste-key", static_dir=dist, _env_file=None))
    return TestClient(create_app())


def test_servira_index_e_assets(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == "<html>gerenet</html>"

    rota_client = client.get("/reconcile")
    assert rota_client.status_code == 200 and rota_client.text == "<html>gerenet</html>"

    asset = client.get("/assets/app.abc123.js")
    assert asset.status_code == 200
    assert asset.headers.get("cache-control") == "public,max-age=31536000,immutable"


def test_rotas_api_nao_caem_no_fallback(client: TestClient) -> None:
    resp = client.get("/api/v1/nao-existe")
    assert resp.status_code == 404
    assert resp.text.strip().startswith("{")  # erro JSON, não index.html


def test_sem_build_nao_registra() -> None:
    # O app só é criado depois de set_settings: o fallback é registrado em
    # create_app(), então mudar settings depois do TestClient não tem efeito.
    set_settings(Settings(api_key="teste-key", static_dir=Path("/tmp/nao-existe-dist-xyz"), _env_file=None))
    resp = TestClient(create_app()).get("/")
    assert resp.status_code == 404
