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
        dados = self.get_secret(vault_path)
        return {"username": dados["username"], "password": dados["password"]}

    def get_secret(self, path: str) -> dict[str, str]:
        """Lê o conteúdo de um caminho KV v2 (falha vira RuntimeError)."""
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(path=path)
        except Exception as exc:  # conexão, token, permissão, caminho inexistente
            raise RuntimeError(f"Falha ao ler o segredo {path}: {exc}") from exc
        return dict(resp["data"]["data"])

    def set_secret(self, path: str, dados: dict[str, str]) -> None:
        """Grava/substitui o segredo no caminho KV v2 (idempotente; falha vira RuntimeError)."""
        try:
            self._client.secrets.kv.v2.create_or_update_secret(path=path, secret=dados)
        except Exception as exc:
            raise RuntimeError(f"Falha ao gravar o segredo {path}: {exc}") from exc
