from gerenet.config import Settings
from gerenet.secrets.vault_store import VaultSecretStore

CAMINHO = "gerenet/credential-groups/automacao"


def test_seed_e_leitura_roundtrip() -> None:
    s = Settings(_env_file=None)
    store = VaultSecretStore(s.vault_url, s.vault_token)
    store.seed_dev(username="gerenet-auto", password="senha-teste")
    cred = store.get_credential(CAMINHO)
    assert cred == {"username": "gerenet-auto", "password": "senha-teste"}
