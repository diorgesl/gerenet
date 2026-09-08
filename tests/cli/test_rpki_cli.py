"""CLI de RPKI — `gerenet rpki sync` (espelho do lote do rpki-client, §7.5, F5/E4).

Molde: tests/cli/test_prefix_authorizations_cli.py — CliRunner sobre o app
completo; o banco é o da suíte (conftest aponta GERENET_DATABASE_URL para o
banco de teste e trunca a cada teste — `roas` está na truncagem). O sync
escreve no banco pelo caminho real (arquivo via `tmp_path`). A consulta IRR
é testada em tests/cli/test_irr_cli.py (grupo `irr` próprio).
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.cli.main import app
from gerenet.config import Settings, set_settings

runner = CliRunner()

_ROAS_PADRAO = [
    {"prefix": "180.10.0.0/16", "maxLength": 24, "asn": "AS64512"},
    {"prefix": "2001:db8:1::/48", "asn": "AS64512"},
]


def _arquivo_roas(dir_raiz: Path, roas: list[dict]) -> str:
    """Escreve o JSON do rpki-client (`{"roas": [...]}`) em `dir_raiz`."""
    caminho = dir_raiz / "roas.json"
    caminho.write_text(json.dumps({"roas": roas}), encoding="utf-8")
    return str(caminho)


def test_cli_rpki_sync_de_arquivo_valido_imprime_total(
    db_session: Session, tmp_path: Path
) -> None:
    """`rpki sync --file` com lote válido ⇒ exit 0 e total no stdout (+ revalidação)."""
    caminho = _arquivo_roas(tmp_path, _ROAS_PADRAO)

    resultado = runner.invoke(app, ["rpki", "sync", "--file", caminho])

    assert resultado.exit_code == 0, resultado.output
    assert "ROAs sincronizadas: 2" in resultado.output
    # a revalidação consultiva é efeito colateral do sync — mencionada, sem número
    assert "revalidação automática" in resultado.output.lower()


def test_cli_rpki_sync_arquivo_inexistente_erro(db_session: Session, tmp_path: Path) -> None:
    """Caminho inexistente ⇒ erro do parse da sync (exit 1, "Erro:")."""
    resultado = runner.invoke(
        app, ["rpki", "sync", "--file", str(tmp_path / "nao-existe.json")]
    )

    assert resultado.exit_code == 1
    assert "Erro:" in resultado.output


def test_cli_rpki_sync_arquivo_estrutura_invalida_erro(
    db_session: Session, tmp_path: Path
) -> None:
    """Arquivo existente com `roas` não-lista (`{"roas": {}}`) ⇒ TypeError ⇒ exit 1."""
    caminho = tmp_path / "roas-invalido.json"
    caminho.write_text(json.dumps({"roas": {}}), encoding="utf-8")

    resultado = runner.invoke(app, ["rpki", "sync", "--file", str(caminho)])

    assert resultado.exit_code == 1
    assert "Erro:" in resultado.output


def test_cli_rpki_sync_sem_arquivo_e_sem_config_erro(db_session: Session) -> None:
    """Sem `--file` e sem `rpki_roas_file` na config ⇒ erro com orientação."""
    resultado = runner.invoke(app, ["rpki", "sync"])

    assert resultado.exit_code == 1
    assert "Erro:" in resultado.output


def test_cli_rpki_sync_usa_default_da_config(db_session: Session, tmp_path: Path) -> None:
    """`--file` ausente usa `rpki_roas_file` da configuração (GERENET_RPKI_ROAS_FILE)."""
    caminho = _arquivo_roas(tmp_path, _ROAS_PADRAO)
    set_settings(Settings(rpki_roas_file=caminho))

    resultado = runner.invoke(app, ["rpki", "sync"])

    assert resultado.exit_code == 0, resultado.output
    assert "ROAs sincronizadas: 2" in resultado.output
