import hvac


class VaultSecretStore:
    """Credenciais de grupos em Vault KV v2, caminho lógico gerenet/credential-groups/<nome>.

    O mount dev do compose é 'secret/' (KV v2): o hvac resolve o caminho
    'gerenet/credential-groups/automacao' para secret/data/gerenet/credential-groups/automacao.
    """

    def __init__(self, url: str, token: str) -> None:
        self._client = hvac.Client(url=url, token=token)
        if not self._client.is_authenticated():
            raise RuntimeError("Não foi possível autenticar no Vault (token inválido?).")

    def seed_dev(self, username: str, password: str) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path="gerenet/credential-groups/automacao",
            secret={"username": username, "password": password},
        )

    def get_credential(self, vault_path: str) -> dict[str, str]:
        resp = self._client.secrets.kv.v2.read_secret_version(path=vault_path)
        dados = resp["data"]["data"]
        return {"username": dados["username"], "password": dados["password"]}
