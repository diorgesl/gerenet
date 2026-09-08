"""CLI de RPKI (sync de ROAs) e consulta IRR (§7.5, F5/E4).

Molde: tests/cli/test_prefix_authorizations_cli.py — CliRunner sobre o app
completo; o banco é o da suíte (conftest aponta GERENET_DATABASE_URL para o
banco de teste e trunca a cada teste — `roas` e `irr_cache` estão na
truncagem). O sync escreve no banco pelo caminho real (arquivo via
`tmp_path`); `consultar` é monkeypatchado onde o CLI importa
(`gerenet.cli.rpki.consultar`) — a consulta IRR não toca rede nos testes.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.automation.irr import IrrError
from gerenet.cli import rpki as cli_rpki
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


def test_cli_irr_query_imprime_asns_e_prefixos(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`irr query AS64512` com `consultar` mockado ⇒ exit 0 com ASN e prefixos."""

    def _consulta_fake(source: str, key: str, *, ttl_horas: int = 24) -> dict:
        assert source == "radb"
        assert key == "AS64512"
        assert ttl_horas == 24  # default repassado à assinatura de consultar
        return {"asns": [64512], "prefixos": ["180.10.0.0/16"]}

    monkeypatch.setattr(cli_rpki, "consultar", _consulta_fake)

    resultado = runner.invoke(app, ["rpki", "query", "AS64512"])

    assert resultado.exit_code == 0, resultado.output
    assert "AS64512" in resultado.output
    assert "180.10.0.0/16" in resultado.output


def test_cli_irr_query_falha_sem_cache_erro(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`IrrError` (falha de rede sem cache vivo) ⇒ exit 1 e "Erro:". """

    def _consulta_erro(source: str, key: str, *, ttl_horas: int = 24) -> dict:
        raise IrrError(f"Consulta IRR {key!r} (source {source}) falhou e não há cache vivo.")

    monkeypatch.setattr(cli_rpki, "consultar", _consulta_erro)

    resultado = runner.invoke(app, ["rpki", "query", "AS64512"])

    assert resultado.exit_code == 1
    assert "Erro:" in resultado.output


def test_cli_irr_query_sem_dados_mostra_nenhum(monkeypatch: pytest.MonkeyPatch) -> None:
    """Payload vazio (as-set sem dados) ⇒ "(nenhum)" para ASNs e prefixos."""
    monkeypatch.setattr(
        cli_rpki,
        "consultar",
        lambda source, key, *, ttl_horas=24: {"asns": [], "prefixos": []},
    )

    resultado = runner.invoke(app, ["rpki", "query", "AS-SET-VAZIO"])

    assert resultado.exit_code == 0, resultado.output
    assert resultado.output.count("(nenhum)") == 2
