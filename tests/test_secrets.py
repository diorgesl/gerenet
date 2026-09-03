from gerenet.config import Settings
from gerenet.secrets.vault_store import VaultSecretStore

CAMINHO = "gerenet/credential-groups/automacao"


def test_seed_e_leitura_roundtrip() -> None:
    s = Settings(_env_file=None)
    store = VaultSecretStore(s.vault_url, s.vault_token)
    store.seed_dev(username="gerenet-auto", password="senha-teste")
    cred = store.get_credential(CAMINHO)
    assert cred == {"username": "gerenet-auto", "password": "senha-teste"}


CAMINHO_BGP = "gerenet/bgp-sessions/1/password"


def test_set_e_get_secret_roundtrip() -> None:
    s = Settings(_env_file=None)
    store = VaultSecretStore(s.vault_url, s.vault_token)
    store.set_secret(CAMINHO_BGP, {"password": "md5-segredo"})
    assert store.get_secret(CAMINHO_BGP) == {"password": "md5-segredo"}


def test_set_secret_sobrescreve_valor() -> None:
    s = Settings(_env_file=None)
    store = VaultSecretStore(s.vault_url, s.vault_token)
    store.set_secret(CAMINHO_BGP, {"password": "md5-primeiro"})
    store.set_secret(CAMINHO_BGP, {"password": "md5-segundo"})
    assert store.get_secret(CAMINHO_BGP) == {"password": "md5-segundo"}
