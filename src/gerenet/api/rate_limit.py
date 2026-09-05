"""Rate limit de login — fixed window por IP+username no Redis (fail-open).

Decisão C3 §3.7: conta apenas falhas (5 → bloqueio de 5 min com 429 +
Retry-After). Redis fora do ar → o login segue sem bloqueio (fail-open,
decisão reversível e documentada); login com sucesso limpa a chave.
"""
import logging

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

MAX_FALHAS = 5
JANELA_SEGUNDOS = 300


def chave(ip: str, username: str) -> str:
    return f"gerenet:login:fail:{ip}:{username}"


def conectar(settings) -> Redis:
    """Cliente Redis — função separada para os testes injetarem um fake."""
    return Redis.from_url(settings.redis_url)


def permitir(redis: Redis, ip: str, username: str) -> bool:
    """True enquanto o par ip+username acumula menos de MAX_FALHAS falhas."""
    try:
        return int(redis.get(chave(ip, username)) or 0) < MAX_FALHAS
    except RedisError:
        logger.warning("Redis indisponível no rate limit de login; permitindo (fail-open).", exc_info=True)
        return True


def registrar_falha(redis: Redis, ip: str, username: str) -> int:
    """INCR + EXPIRE na primeira falha; devolve o total acumulado na janela."""
    try:
        total = int(redis.incr(chave(ip, username)))
        if total == 1:
            redis.expire(chave(ip, username), JANELA_SEGUNDOS)
        return total
    except RedisError:
        logger.warning("Redis indisponível no rate limit de login; seguindo (fail-open).", exc_info=True)
        return 0


def limpar(redis: Redis, ip: str, username: str) -> None:
    """Login com sucesso zera o contador de falhas."""
    try:
        redis.delete(chave(ip, username))
    except RedisError:
        logger.warning("Redis indisponível ao limpar rate limit de login (fail-open).", exc_info=True)
