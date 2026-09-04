"""Fixtures comuns dos testes de API.

`static_dir_inexistente`: aponta o build da SPA para um diretório vazio — o
fallback de `/` nunca serve arquivos fora do build real, sem depender do
`web/dist` que existir na máquina.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from gerenet.config import Settings, set_settings


@pytest.fixture
def static_dir_inexistente(tmp_path: Path) -> Path:
    return tmp_path / "sem-build"


@pytest.fixture(scope="session", autouse=True)
def static_dir_sem_spa(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    # Correção R1 (Task 8): o set_settings de cada módulo substitui os settings
    # do processo inteiro, inclusive o static_dir default (Path("web/dist")),
    # então só o autouse spa_sem_build não basta — quando o pytest roda da raiz
    # do repositório com web/dist presente, montar_spa registraria o catch-all
    # e POST/PUT/PATCH/DELETE em rota sem o método devolveriam 404 (contrato
    # pré-fallback) em vez do 405 do Starlette. Pinando GERENET_STATIC_DIR na
    # sessão, todo Settings() sem static_dir explícito resolve para um diretório
    # vazio (sem index.html → fallback não é montado); test_static_spa.py segue
    # intacto porque seu client passa static_dir explícito (init vence env).
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GERENET_STATIC_DIR", str(tmp_path_factory.mktemp("gerenet-sem-spa")))
        yield


@pytest.fixture(autouse=True)
def spa_sem_build(static_dir_inexistente: Path) -> Iterator[None]:
    # Minor C1: os testes de API nunca devem depender do web/dist que existir
    # na máquina — com o build presente, montar_spa registra o catch-all e
    # POST/PUT/PATCH/DELETE em rota desconhecida devolvem 404 (contrato
    # pré-fallback) em vez do 405 natural do Starlette. Pinando um diretório
    # inexistente, o fallback não é montado; test_static_spa.py sobrepõe pelo
    # próprio set_settings no fixture client (ordem: autouse corre antes).
    set_settings(Settings(static_dir=static_dir_inexistente, _env_file=None))
    yield
