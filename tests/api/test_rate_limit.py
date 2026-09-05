from redis.exceptions import ConnectionError as RedisConnectionError

from gerenet.api import rate_limit


class FakeRedis:
    """Subset duck-typed do Redis (get/incr/expire/delete) para os testes."""

    def __init__(self) -> None:
        self._valores: dict[str, int] = {}
        self._expirados: set[str] = set()

    def get(self, chave: str) -> int | None:
        return self._valores.get(chave)

    def incr(self, chave: str) -> int:
        self._valores[chave] = self._valores.get(chave, 0) + 1
        return self._valores[chave]

    def expire(self, chave: str, _segundos: int) -> bool:
        self._expirados.add(chave)
        return True

    def delete(self, chave: str) -> int:
        return 1 if self._valores.pop(chave, None) is not None else 0


class RedisForaDoAr:
    """Redis que levanta em todo comando — simula a indisponibilidade."""

    def get(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")

    def incr(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")

    def expire(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")

    def delete(self, *_args, **_kwargs):
        raise RedisConnectionError("redis fora do ar")


def test_chave_formato() -> None:
    assert rate_limit.chave("10.0.0.1", "op1") == "gerenet:login:fail:10.0.0.1:op1"


def test_registrar_falha_incrementa_e_expira_na_primeira() -> None:
    redis = FakeRedis()
    assert rate_limit.registrar_falha(redis, "10.0.0.1", "op1") == 1
    assert redis._expirados == {"gerenet:login:fail:10.0.0.1:op1"}
    assert rate_limit.registrar_falha(redis, "10.0.0.1", "op1") == 2


def test_permitir_bloqueia_apos_5_falhas() -> None:
    redis = FakeRedis()
    for _ in range(4):
        rate_limit.registrar_falha(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is True
    rate_limit.registrar_falha(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is False


def test_limpar_zera_contador() -> None:
    redis = FakeRedis()
    for _ in range(5):
        rate_limit.registrar_falha(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is False
    rate_limit.limpar(redis, "10.0.0.1", "op1")
    assert rate_limit.permitir(redis, "10.0.0.1", "op1") is True


def test_fail_open_quando_redis_fora_do_ar() -> None:
    sem_redis = RedisForaDoAr()
    assert rate_limit.permitir(sem_redis, "10.0.0.1", "op1") is True
    assert rate_limit.registrar_falha(sem_redis, "10.0.0.1", "op1") == 0
    rate_limit.limpar(sem_redis, "10.0.0.1", "op1")  # não levanta
