from gerenet.config import Settings


def test_settings_env_prefix() -> None:
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.connect_timeout == 15.0
    assert s.lock_ttl_seconds == 300
