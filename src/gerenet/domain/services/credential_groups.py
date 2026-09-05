from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import ConflictError, ValidationError


def create_credential_group(
    session: Session, *, name: str, vault_path: str, kind: str = "tacacs_password", actor: str
) -> models.CredentialGroup:
    """Registra um grupo de credencial no SoT (o segredo vai ao Vault à parte)."""
    nome = name.strip()
    caminho = vault_path.strip()
    if not nome or not caminho:
        raise ValidationError("Nome e caminho no Vault são obrigatórios.")
    grupo = models.CredentialGroup(name=nome, kind=kind, vault_path=caminho)
    session.add(grupo)
    try:
        session.flush()  # define grupo.id e valida unicidade antes da auditoria
        registrar(
            session,
            tipo="credential_group.create",
            ator=actor,
            objeto="credential_group",
            objeto_id=grupo.id,
            antes=None,
            depois={"name": grupo.name, "kind": grupo.kind, "vault_path": grupo.vault_path},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Já existe um grupo de credencial com esse nome.") from exc
    session.refresh(grupo)
    return grupo


def get_or_create_credential_group(
    session: Session, *, name: str, vault_path: str, kind: str = "tacacs_password", actor: str
) -> models.CredentialGroup:
    """Acha por nome ou cria — usado pelo `vault seed`, que precisa ser idempotente."""
    existente = session.scalar(
        select(models.CredentialGroup).where(models.CredentialGroup.name == name)
    )
    if existente is not None:
        return existente
    return create_credential_group(
        session, name=name, vault_path=vault_path, kind=kind, actor=actor
    )


def list_credential_groups(session: Session) -> list[models.CredentialGroup]:
    return list(
        session.scalars(select(models.CredentialGroup).order_by(models.CredentialGroup.name))
    )
