class GerenetError(Exception):
    """Erro de domínio do gerenet (mensagens em PT-BR)."""


class NotFoundError(GerenetError):
    """Objeto não encontrado (HTTP 404)."""


class ConflictError(GerenetError):
    """Conflito com o estado atual (HTTP 409)."""


class ValidationError(GerenetError):
    """Dado inválido, sem conflito com o estado (HTTP 400 no Plano 3)."""


class PlanoRollbackVazio(ValidationError):
    """Plano de rollback vazio — tudo pulado por baseline ausente (§5.2).

    Sinaliza rollback automático indisponível SEM persistir o CR inverso
    (a exceção sobe antes do commit; HTTP 422).
    """
