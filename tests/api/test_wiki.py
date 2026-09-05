import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings


@pytest.fixture()
def client(tmp_path) -> TestClient:
    (tmp_path / "index.md").write_text(
        "---\ntitle: Visão geral\nsecao: Começando\norder: 1\n---\n# Visão geral\n\nOlá, operador.\n"
    )
    em_breve = tmp_path / "em-breve"
    em_breve.mkdir()
    (em_breve / "mpls.md").write_text(
        "---\ntitle: Serviços MPLS\nsecao: Em breve\norder: 2\nem_breve: true\n---\n# Serviços MPLS\n\nPlanejado.\n"
    )
    set_settings(Settings(wiki_dir=tmp_path, api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_indice_ordena_por_order_e_traz_em_breve(client: TestClient) -> None:
    resp = client.get("/api/v1/wiki", headers=_auth())
    assert resp.status_code == 200
    paginas = resp.json()
    assert [p["slug"] for p in paginas] == ["index", "mpls"]
    assert paginas[0]["secao"] == "Começando"
    assert paginas[1]["em_breve"] is True


def test_pagina_retorna_html_renderizado(client: TestClient) -> None:
    corpo = client.get("/api/v1/wiki/index", headers=_auth()).json()
    assert corpo["titulo"] == "Visão geral"
    assert "<h1>Visão geral</h1>" in corpo["html"]
    assert "<p>Olá, operador.</p>" in corpo["html"]


def test_rota_requer_autenticacao(client: TestClient) -> None:
    assert client.get("/api/v1/wiki").status_code == 401
    assert client.get("/api/v1/wiki/index").status_code == 401


def test_slug_invalido_da_404(client: TestClient) -> None:
    assert client.get("/api/v1/wiki/nao-existe", headers=_auth()).status_code == 404
    assert client.get("/api/v1/wiki/..%2F..%2Fetc", headers=_auth()).status_code == 404


def test_script_e_javascript_url_neutralizados(client: TestClient, tmp_path) -> None:
    (tmp_path / "index.md").write_text(
        "# Título\n\n<script>alert(1)</script>\n\n[clique](javascript:alert(1))\n"
    )
    corpo = client.get("/api/v1/wiki/index", headers=_auth()).json()
    assert "<script>" not in corpo["html"]
    assert "javascript:" not in corpo["html"]


def test_titulo_fallback_sem_frontmatter(client: TestClient, tmp_path) -> None:
    (tmp_path / "index.md").write_text("# Só título\n\ncorpo.\n")
    corpo = client.get("/api/v1/wiki/index", headers=_auth()).json()
    assert corpo["titulo"] == "Só título"


def test_docs_wiki_ausente_lista_vazia(client: TestClient, tmp_path) -> None:
    set_settings(Settings(wiki_dir=tmp_path / "sem-wiki", api_key="teste-key", _env_file=None))
    assert client.get("/api/v1/wiki", headers=_auth()).json() == []
