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
from gerenet.domain.services.errors import ConflictError


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
    assert esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                             remote_address="10.0.0.9", actor="cli") is True
    assert listar_ignorados(db_session, edge_device.id) == []


def test_esquecer_o_que_nao_existe_e_no_op_e_devolve_falso(db_session, edge_device) -> None:
    """O `False` é o que impede o sucesso falso: as duas superfícies dizem que
    nada foi apagado em vez de responder 204/mensagem de sucesso."""
    assert esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                             remote_address="10.0.0.9", actor="cli") is False
    assert listar_ignorados(db_session, edge_device.id) == []


def test_o_mesmo_ipv6_em_duas_caixas_e_uma_linha_so(db_session, edge_device) -> None:
    """O endereço é a identidade do peer e a caixa não faz parte dela: o
    equipamento escreve `2804:194C:...`, o cadastro à mão escreve minúsculo, e
    as duas linhas conviveriam — escondendo o candidato por dois motivos e
    obrigando o `unignore` a acertar a caixa para desfazer."""
    for endereco in ("2804:194C:1000::1100:73:2", "2804:194c:1000::1100:73:2"):
        ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv6",
                          remote_address=endereco, motivo=None, actor="cli")
    linhas = listar_ignorados(db_session, edge_device.id)
    assert len(linhas) == 1
    assert linhas[0].remote_address == "2804:194c:1000::1100:73:2"  # forma canônica


def test_esquecer_com_caixa_diferente_da_gravada_remove(db_session, edge_device) -> None:
    ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv6",
                      remote_address="2804:194C:1000::1100:73:2", motivo=None, actor="cli")
    assert esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv6",
                             remote_address="2804:194c:1000::1100:73:2", actor="cli") is True
    assert listar_ignorados(db_session, edge_device.id) == []


def test_busca_acha_a_linha_gravada_antes_da_canonicalizacao(db_session, edge_device) -> None:
    """Linha gravada direto no banco (fora do serviço) em outra caixa: a busca
    canonicaliza os dois lados, então ela ainda é encontrada e o `unignore`
    da forma exata não responde sucesso à toa."""
    db_session.add(models.DiscoveryIgnoredPeer(
        device_id=edge_device.id, vrf=None, afi="ipv6",
        remote_address="2804:194C:1000::1100:73:2", autor="cli"))
    db_session.commit()
    assert esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv6",
                             remote_address="2804:194c:1000::1100:73:2", actor="cli") is True
    assert listar_ignorados(db_session, edge_device.id) == []


def test_ignorar_equipamento_inexistente_e_conflito(db_session) -> None:
    """Equipamento que não existe: quem recusa é a chave estrangeira do banco, e
    o serviço responde por ela com `ConflictError` — 409 na API, como todo
    caminho de escrita do repositório — em vez de `IntegrityError` cru (500).

    A segunda metade é a que importa tanto quanto a primeira: sem o `rollback`,
    a sessão fica numa transação falhada e o 500 seguinte vem da mesma chamada.
    """
    with pytest.raises(ConflictError):
        ignorar_candidato(db_session, device_id=9999, vrf=None, afi="ipv4",
                          remote_address="10.0.0.9", motivo=None, actor="cli")
    assert listar_ignorados(db_session, 9999) == []


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
