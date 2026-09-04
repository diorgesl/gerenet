"""Fixtures comuns dos testes de API.

`static_dir_inexistente`: aponta o build da SPA para um diretório vazio — o
fallback de `/` nunca serve arquivos fora do build real, sem depender do
`web/dist` que existir na máquina.
"""

from pathlib import Path

import pytest


@pytest.fixture
def static_dir_inexistente(tmp_path: Path) -> Path:
    return tmp_path / "sem-build"
