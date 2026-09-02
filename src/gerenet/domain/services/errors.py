class GerenetError(Exception):
    """Erro de domínio com mensagem amigável em PT-BR."""


class NotFoundError(GerenetError):
    pass


class ConflictError(GerenetError):
    pass
