from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GERENET_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://gerenet:gerenet@localhost:5432/gerenet"
    redis_url: str = "redis://localhost:6379/0"
    vault_url: str = "http://localhost:8200"
    vault_token: str = "gerenet-dev-root"
    api_key: str = "dev-key-change-me"
    backups_dir: Path = Path("data/backups")
    connect_timeout: float = 15.0
    read_timeout: float = 60.0
    lock_ttl_seconds: int = 300
    session_ttl_seconds: int = 28800  # TTL do cookie de sessão web (§4.2)
    cookie_secure: bool = False  # True em produção sob HTTPS
    static_dir: Path = Path("web/dist")  # build da SPA (ciclo C2)
    wiki_dir: Path = Path("docs/wiki")  # páginas do wiki operacional (ciclo E)

    # IPAM p2p (§25.8): bloco privado de enlaces v4 e base v6 por padrão;
    # cada site pode sobrescrever.
    p2p_ipv4_block: str = "100.64.0.0/10"
    p2p_ipv6_base: str = "2804:194C:1000::/48"


_override: Settings | None = None


def set_settings(s: Settings) -> None:
    """Substitui os settings do processo (usado apenas nos testes)."""
    global _override
    _override = s


def get_settings() -> Settings:
    return _override if _override is not None else Settings()
