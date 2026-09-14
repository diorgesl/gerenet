"""Lista de ignorados da descoberta (spec §11) — a única escrita da parte 1."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from gerenet.domain import models
from gerenet.domain.services.discovery import (
    esquecer_ignorado,
    ignorar_candidato,
    listar_ignorados,
)


def test_ignora_e_lista(db_session, edge_device) -> None:
    ignorar_candidato(
        db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
        remote_address="10.0.0.9", motivo="iBGP com route reflector", actor="cli",
    )
    linhas = listar_ignorados(db_session, edge_device.id)
    assert len(linhas) == 1
    assert linhas[0].remote_address == "10.0.0.9"
    assert linhas[0].motivo == "iBGP com route reflector"
    assert linhas[0].autor == "cli"


def test_ignorar_de_novo_e_idempotente(db_session, edge_device) -> None:
    for _ in range(2):
        ignorar_candidato(
            db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
            remote_address="10.0.0.9", motivo=None, actor="cli",
        )
    assert len(listar_ignorados(db_session, edge_device.id)) == 1


def test_ignorado_na_instancia_publica_e_distinto_do_da_vrf(db_session, edge_device) -> None:
    """NULL não colide em índice único no Postgres: a exclusividade da
    instância pública precisa de índice parcial próprio."""
    ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", motivo=None, actor="cli")
    ignorar_candidato(db_session, device_id=edge_device.id, vrf="VPNA", afi="ipv4",
                      remote_address="10.0.0.9", motivo=None, actor="cli")
    assert len(listar_ignorados(db_session, edge_device.id)) == 2

    # A convivência acima não prova os índices — uma UNIQUE composta comum
    # também a permitiria (NULL não colide com NULL). Quem segura cada metade é
    # o índice parcial respectivo, então a duplicata vai direto (sem o serviço,
    # que responderia pela busca antes de chegar ao banco).
    for vrf in (None, "VPNA"):
        with pytest.raises(IntegrityError):
            db_session.add(models.DiscoveryIgnoredPeer(
                device_id=edge_device.id, vrf=vrf, afi="ipv4",
                remote_address="10.0.0.9", autor="cli"))
            db_session.flush()
        db_session.rollback()


def test_esquecer_remove(db_session, edge_device) -> None:
    ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", motivo=None, actor="cli")
    esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", actor="cli")
    assert listar_ignorados(db_session, edge_device.id) == []


def test_esquecer_o_que_nao_existe_e_no_op(db_session, edge_device) -> None:
    esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", actor="cli")
    assert listar_ignorados(db_session, edge_device.id) == []


def test_audita_ignorar_e_esquecer(db_session, edge_device) -> None:
    ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", motivo="interno", actor="cli")
    esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", actor="cli")
    tipos = [e.type for e in db_session.scalars(
        select(models.AuditEvent).order_by(models.AuditEvent.id)
    )]
    assert "discovery.ignore" in tipos
    assert "discovery.unignore" in tipos
