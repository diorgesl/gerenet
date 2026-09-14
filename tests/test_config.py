import pytest
from pydantic import ValidationError

from gerenet.config import Settings


def test_settings_env_prefix() -> None:
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.connect_timeout == 15.0
    assert s.lock_ttl_seconds == 300


def test_metrics_token_vazio_e_recusado() -> None:
    """'' é falsy: o /metrics ficaria aberto com quem instalou achando que autenticou."""
    with pytest.raises(ValidationError):
        Settings(metrics_token="", _env_file=None)


def test_metrics_token_ausente_desliga_a_autenticacao() -> None:
    assert Settings(_env_file=None).metrics_token is None
