from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import CAMPO_SENSIVEL, mascarar, registrar


def test_mascarar_remove_segredos_e_marca_mudanca() -> None:
    saida = mascarar(
        {
            "antes": {"nome": "antigo", "password": "segredo1"},
            "depois": {"nome": "novo", "password": "segredo2", "token": "abc"},
        }
    )
    assert saida["depois"] == {"nome": "novo", "password": "[mascarado]", "token": "[mascarado]"}
    assert saida["antes"] == {"nome": "antigo"}  # segredo removido, sem marca (não está no depois)
    assert "segredo" not in str(saida)


def test_mascarar_chave_sensivel_apenas_no_antes() -> None:
    saida = mascarar({"antes": {"senha_antiga": "x"}, "depois": {}})
    assert saida["antes"] == {}


def test_mascarar_nao_altera_os_dicts_originais() -> None:
    antes = {"password": "segredo"}
    depois = {"password": "outro"}
    saida = mascarar({"antes": antes, "depois": depois})
    assert saida["antes"] == {}
    assert saida["depois"] == {"password": "[mascarado]"}
    assert antes == {"password": "segredo"}
    assert depois == {"password": "outro"}


def test_registrar_grava_evento_com_details(db_session: Session) -> None:
    registrar(
        db_session,
        tipo="site.create",
        ator="cli",
        objeto="site",
        objeto_id=7,
        antes=None,
        depois={"name": "pop-spo-01"},
    )
    db_session.commit()

    (evento,) = db_session.scalars(select(models.AuditEvent))
    assert evento.type == "site.create"
    assert evento.actor == "cli"
    assert evento.details == {
        "objeto": "site",
        "objeto_id": 7,
        "antes": None,
        "depois": {"name": "pop-spo-01"},
    }


def test_registrar_mascara_sem_alterar_chamada_original(db_session: Session) -> None:
    depois = {"password": "outro"}
    registrar(db_session, tipo="x", ator="api", objeto="y", objeto_id=1, antes=None, depois=depois)
    db_session.commit()
    (evento,) = db_session.scalars(select(models.AuditEvent))
    assert evento.details["depois"] == {"password": "[mascarado]"}
    assert depois == {"password": "outro"}  # original intacto (mascarar copia)


def test_mascarar_preserva_bool_em_chave_sensivel() -> None:
    saida = mascarar(
        {
            "antes": {"has_password": False},
            "depois": {"has_password": True},
        }
    )
    assert saida["antes"] == {"has_password": False}
    assert saida["depois"] == {"has_password": True}


def test_mascarar_mascara_sensivel_nao_bool_nao_string() -> None:
    saida = mascarar(
        {
            "antes": {"password": ["a", "b"]},
            "depois": {"token_id": 5},
        }
    )
    assert saida["antes"] == {}
    assert saida["depois"] == {"token_id": "[mascarado]"}


def test_campos_sensiveis_listados() -> None:
    assert set(CAMPO_SENSIVEL) == {"password", "senha", "secret", "token"}
