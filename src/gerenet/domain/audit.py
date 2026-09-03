"""Auditoria de CRUD — trilha imutável, sem segredos (§18).

Cada evento é um AuditEvent com type "<objeto>.<acao>" (ex.: "circuit.create",
"device.disable", "circuit.reserve") e details = {objeto, objeto_id, antes, depois}.
antes/depois carregam apenas os campos alterados; campos sensíveis (password,
senha, secret, token) nunca são gravados — quando alterados, viram "[mascarado]".
Exceção: valor bool sob chave sensível (flag como has_password) atravessa intacto
nos dois painéis — bool não carrega segredo; "[mascarado]" na trilha significa que
um valor real de segredo esteve ali, e fabricá-lo para uma flag seria enganoso.
A tabela audit_events não recebe UPDATE nem DELETE em nenhum caminho de código.
"""
from collections.abc import Mapping

from sqlalchemy.orm import Session

from gerenet.domain import models

CAMPO_SENSIVEL = ("password", "senha", "secret", "token")


def mascarar(paineis: Mapping[str, dict | None]) -> dict[str, dict | None]:
    """Remove valores de campos sensíveis de antes/depois, sem alterar o input.

    Cada painel é copiado; chave sensível (substring case-insensitive de
    CAMPO_SENSIVEL) é removida de "antes" e vira "[mascarado]" em "depois"
    (sinaliza a mudança sem revelar o valor). Exceção: valor bool (flag como
    has_password) atravessa intacto nos dois painéis — segredos são strings
    ou estruturas; bool não carrega segredo.
    """
    saida: dict[str, dict | None] = {}
    for painel, valores in paineis.items():
        if valores is None:
            saida[painel] = None
            continue
        copia = dict(valores)
        for chave in list(copia):
            if any(termo in chave.lower() for termo in CAMPO_SENSIVEL):
                if isinstance(copia[chave], bool):
                    continue
                copia.pop(chave)
                if painel == "depois":
                    copia[chave] = "[mascarado]"
        saida[painel] = copia
    return saida


def registrar(
    session: Session,
    *,
    tipo: str,
    ator: str,
    objeto: str,
    objeto_id: int,
    antes: dict | None = None,
    depois: dict | None = None,
) -> None:
    """Grava um evento de auditoria (sem commit — roda na transação da mudança)."""
    paineis = mascarar({"antes": antes, "depois": depois})
    session.add(
        models.AuditEvent(
            type=tipo,
            actor=ator,
            details={
                "objeto": objeto,
                "objeto_id": objeto_id,
                "antes": paineis["antes"],
                "depois": paineis["depois"],
            },
        )
    )
