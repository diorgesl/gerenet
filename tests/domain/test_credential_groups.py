import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gerenet.domain.models import AuditEvent, CredentialGroup
from gerenet.domain.schemas import CredentialGroupUpdate
from gerenet.domain.services.credential_groups import (
    create_credential_group,
    disable_credential_group,
    enable_credential_group,
    get_credential_group,
    get_or_create_credential_group,
    list_credential_groups,
    update_credential_group,
)
from gerenet.domain.services.errors import ConflictError, NotFoundError


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


def test_get_e_list_filtram_desativados(db_session: Session) -> None:
    grupo = create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    assert get_credential_group(db_session, grupo.id).name == "automacao"
    assert list_credential_groups(db_session) == [grupo]

    disable_credential_group(db_session, grupo.id, actor="cli")
    assert list_credential_groups(db_session) == []
    assert [g.name for g in list_credential_groups(db_session, include_disabled=True)] == ["automacao"]


def test_get_inexistente_levanta_not_found(db_session: Session) -> None:
    with pytest.raises(NotFoundError, match="Grupo de credencial 999 não encontrado"):
        get_credential_group(db_session, 999)


def test_update_grupo_renomeia_e_audita(db_session: Session) -> None:
    grupo = create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    atualizado = update_credential_group(
        db_session, grupo.id, CredentialGroupUpdate(vault_path="gerenet/credential-groups/automacao2"), actor="cli"
    )
    assert atualizado.vault_path == "gerenet/credential-groups/automacao2"
    assert db_session.scalar(select(AuditEvent).filter_by(type="credential_group.update")) is not None


def test_update_nome_duplicado_levanta_conflito(db_session: Session) -> None:
    create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    outro = create_credential_group(
        db_session, name="outro", vault_path="gerenet/credential-groups/outro", actor="cli"
    )
    with pytest.raises(ConflictError, match="grupo de credencial com esse nome"):
        update_credential_group(
            db_session, outro.id, CredentialGroupUpdate(name="automacao"), actor="cli"
        )


def test_disable_enable_sao_idempotentes_e_auditam(db_session: Session) -> None:
    grupo = create_credential_group(
        db_session, name="automacao", vault_path="gerenet/credential-groups/automacao", actor="cli"
    )
    disable_credential_group(db_session, grupo.id, actor="cli")
    disable_credential_group(db_session, grupo.id, actor="cli")  # segunda vez: sem novo evento
    enable_credential_group(db_session, grupo.id, actor="cli")
    assert db_session.query(AuditEvent).filter_by(type="credential_group.disable").count() == 1
    assert db_session.query(AuditEvent).filter_by(type="credential_group.enable").count() == 1
    assert grupo.admin_status is True
