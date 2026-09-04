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

    resp_api = client.get("/api")  # exato: também é rota de API, nunca HTML da SPA
    assert resp_api.status_code == 404
    assert resp_api.text.strip().startswith("{")


@pytest.mark.parametrize(
    "rota",
    [
        # %2e%2e = ".." decodificado pelo uvicorn ao chegar no {path:path}
        "/%2e%2e/%2e%2e/segredo.txt",
        "/%2e%2e/segredo-vizinho.txt",
        # separadores percent-encodados: os ".." chegam decodificados
        "/..%2f..%2fsegredo.txt",
        "/%2e%2e%2f%2e%2e%2fsegredo.txt",
        # separador %2f apenas (um nível)
        "/%2e%2e%2fsegredo-vizinho.txt",
    ],
)
def test_nao_sirve_arquivos_fora_do_static_dir(
    client: TestClient, tmp_path: Path, rota: str
) -> None:
    # Segredos FORA do static_dir (tmp_path/web/dist): um nível acima e na raiz do tmp_path.
    (tmp_path / "segredo.txt").write_text("GRANA=1234", encoding="utf-8")
    (tmp_path / "web" / "segredo-vizinho.txt").write_text("TOKEN=xy", encoding="utf-8")
    resp = client.get(rota)
    assert resp.status_code == 404, f"{rota} -> {resp.status_code} {resp.text[:60]!r}"


def test_nao_get_em_rota_inexistente_e_404(client: TestClient) -> None:
    for metodo in ("post", "put", "patch", "delete", "head", "options"):
        resp = getattr(client, metodo)("/api/v1/nao-existe")
        assert resp.status_code == 404, metodo

    resp = client.post("/reconcile")  # rota do client sem POST
    assert resp.status_code == 404


def test_rota_real_vence_para_get(client: TestClient) -> None:
    # Rota real de API registrada antes do fallback: GET não pode cair no SPA
    # nem no 404 do catch-all (sem auth → 401, nunca HTML/404 de rota inexistente).
    resp = client.get("/api/v1/devices")
    assert resp.status_code == 401


def test_sem_build_nao_registra(tmp_path: Path) -> None:
    # O app só é criado depois de set_settings: o fallback é registrado em
    # create_app(), então mudar settings depois do TestClient não tem efeito.
    # Subdiretório NUNCA criado — sem build, nada é montado.
    dist_inexistente = tmp_path / "dist-inexistente"
    set_settings(
        Settings(api_key="teste-key", static_dir=dist_inexistente, _env_file=None)
    )
    resp = TestClient(create_app()).get("/")
    assert resp.status_code == 404
