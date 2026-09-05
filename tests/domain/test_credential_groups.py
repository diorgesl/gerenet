import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gerenet.domain.models import AuditEvent, CredentialGroup
from gerenet.domain.services.credential_groups import (
    create_credential_group,
    get_or_create_credential_group,
)
from gerenet.domain.services.errors import ConflictError


def test_cria_grupo_e_registra_auditoria(db_session: Session) -> None:
    grupo = create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    assert grupo.id is not None
    assert grupo.kind == "tacacs_password"

    evento = db_session.query(AuditEvent).filter_by(type="credential_group.create").one()
    assert evento.actor == "cli"
    assert evento.details["objeto"] == "credential_group"
    assert evento.details["objeto_id"] == grupo.id
    assert evento.details["depois"] == {
        "name": "automacao",
        "kind": "tacacs_password",
        "vault_path": "gerenet/credential-groups/automacao",
    }


def test_nome_duplicado_levanta_conflito(db_session: Session) -> None:
    create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    with pytest.raises(ConflictError, match="grupo de credencial com esse nome"):
        create_credential_group(
            db_session, name="automacao", vault_path="outro/caminho", actor="cli"
        )


def test_get_or_create_nao_duplica_e_eh_idempotente(db_session: Session) -> None:
    primeira = get_or_create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    segunda = get_or_create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    assert primeira.id == segunda.id
    assert db_session.scalar(select(func.count()).select_from(CredentialGroup)) == 1
