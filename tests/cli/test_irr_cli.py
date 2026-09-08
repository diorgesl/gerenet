"""CLI de consulta IRR — `gerenet irr query` (ASN/AS-SET, §7.5, F5/E4).

Molde: tests/cli/test_prefix_authorizations_cli.py — CliRunner sobre o app
completo. `consultar` é monkeypatchado onde o CLI importa
(`gerenet.cli.irr.consultar`): a consulta IRR não toca rede nos testes.
"""
import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from gerenet.automation.irr import IrrError
from gerenet.cli import irr as cli_irr
from gerenet.cli.main import app

runner = CliRunner()


def test_cli_irr_query_imprime_asns_e_prefixos(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`irr query AS64512` com `consultar` mockado ⇒ exit 0 com ASN e prefixos."""

    def _consulta_fake(source: str, key: str, *, ttl_horas: int = 24) -> dict:
        assert source == "radb"
        assert key == "AS64512"
        assert ttl_horas == 24  # default repassado à assinatura de consultar
        return {"asns": [64512], "prefixos": ["180.10.0.0/16"]}

    monkeypatch.setattr(cli_irr, "consultar", _consulta_fake)

    resultado = runner.invoke(app, ["irr", "query", "AS64512"])

    assert resultado.exit_code == 0, resultado.output
    assert "AS64512" in resultado.output
    assert "180.10.0.0/16" in resultado.output


def test_cli_irr_query_aceita_asn_numerico_e_ttl(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ASN só de dígitos e `--ttl-horas` repassados ao `consultar`."""

    def _consulta_fake(source: str, key: str, *, ttl_horas: int = 24) -> dict:
        assert source == "radb"
        assert key == "64512"
        assert ttl_horas == 48
        return {"asns": [64512], "prefixos": []}

    monkeypatch.setattr(cli_irr, "consultar", _consulta_fake)

    resultado = runner.invoke(
        app, ["irr", "query", "64512", "--ttl-horas", "48"]
    )

    assert resultado.exit_code == 0, resultado.output
    assert "AS64512" in resultado.output


def test_cli_irr_query_falha_sem_cache_erro(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`IrrError` (falha de rede sem cache vivo) ⇒ exit 1 e "Erro:"."""
    def _consulta_erro(source: str, key: str, *, ttl_horas: int = 24) -> dict:
        raise IrrError(f"Consulta IRR {key!r} (source {source}) falhou e não há cache vivo.")

    monkeypatch.setattr(cli_irr, "consultar", _consulta_erro)

    resultado = runner.invoke(app, ["irr", "query", "AS64512"])

    assert resultado.exit_code == 1
    assert "Erro:" in resultado.output


def test_cli_irr_query_sem_dados_mostra_nenhum(monkeypatch: pytest.MonkeyPatch) -> None:
    """Payload vazio (as-set sem dados) ⇒ "(nenhum)" para ASNs e prefixos."""
    monkeypatch.setattr(
        cli_irr,
        "consultar",
        lambda source, key, *, ttl_horas=24: {"asns": [], "prefixos": []},
    )

    resultado = runner.invoke(app, ["irr", "query", "AS-SET-VAZIO"])

    assert resultado.exit_code == 0, resultado.output
    assert resultado.output.count("(nenhum)") == 2
