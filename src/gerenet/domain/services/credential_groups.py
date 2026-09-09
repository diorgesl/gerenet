from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models, schemas
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


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


def list_credential_groups(session: Session, include_disabled: bool = False) -> list[models.CredentialGroup]:
    stmt = select(models.CredentialGroup).order_by(models.CredentialGroup.name)
    if not include_disabled:
        stmt = stmt.where(models.CredentialGroup.admin_status.is_(True))
    return list(session.scalars(stmt))


def get_credential_group(session: Session, credential_group_id: int) -> models.CredentialGroup:
    grupo = session.get(models.CredentialGroup, credential_group_id)
    if grupo is None:
        raise NotFoundError(f"Grupo de credencial {credential_group_id} não encontrado.")
    return grupo


def update_credential_group(
    session: Session, credential_group_id: int, data: schemas.CredentialGroupUpdate, *, actor: str
) -> models.CredentialGroup:
    grupo = get_credential_group(session, credential_group_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return grupo
    antes = {campo: getattr(grupo, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(grupo, campo, valor)
    try:
        registrar(
            session, tipo="credential_group.update", ator=actor, objeto="credential_group",
            objeto_id=grupo.id, antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Já existe um grupo de credencial com esse nome.") from exc
    session.refresh(grupo)
    return grupo


def disable_credential_group(session: Session, credential_group_id: int, *, actor: str) -> models.CredentialGroup:
    grupo = get_credential_group(session, credential_group_id)
    if grupo.admin_status is False:
        return grupo
    grupo.admin_status = False
    registrar(
        session, tipo="credential_group.disable", ator=actor, objeto="credential_group",
        objeto_id=grupo.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return grupo


def enable_credential_group(session: Session, credential_group_id: int, *, actor: str) -> models.CredentialGroup:
    grupo = get_credential_group(session, credential_group_id)
    if grupo.admin_status is True:
        return grupo
    grupo.admin_status = True
    registrar(
        session, tipo="credential_group.enable", ator=actor, objeto="credential_group",
        objeto_id=grupo.id, antes={"admin_status": False}, depois={"admin_status": True},
    )
    session.commit()
    return grupo
