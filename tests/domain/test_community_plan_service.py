"""A adoção do plano (spec §9): transação única, idempotência e auditoria."""
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.community_plan import (
    adotar_plano,
    obter_plano,
    propor_adocao,
    validar_plano,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _device_com_snapshot(db_session, nome: str, fixture: str) -> models.Device:
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.9", asn=61785), actor="teste"
    )
    db_session.add(
        models.DeviceSnapshot(
            device_id=device.id, status="success",
            raw_files={"config_backup": [str(FIXTURES / fixture)]},
        )
    )
    db_session.commit()
    return device


def test_propoe_a_partir_do_snapshot_coletado(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-01", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    assert proposta.plano.asn_principal == 61785
    assert {c.nome for c in proposta.plano.classes} >= {"com-TRANSITO-FULL", "com-CLIENTES_PARCEIROS-CDN"}
    assert db_session.scalar(select(models.CommunityPlan)) is None  # propor não escreve


def test_adota_numa_transacao_e_audita(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-02", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    plano = adotar_plano(
        db_session, proposta, device_id=device.id, snapshot_id=proposta.plano.snapshot_id, actor="ana"
    )
    db_session.commit()

    assert plano.asn_principal == 61785
    assert plano.origem == "adotado"
    assert db_session.scalar(select(models.CommunityPlan).where(models.CommunityPlan.admin_status)) is not None
    classe = db_session.scalar(select(models.Community).where(models.Community.valor_v4 == 1010))
    assert classe is not None and classe.banda == "transito" and classe.origem == "adotado"
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    )
    assert evento is not None and evento.actor == "ana"


def test_adotar_duas_vezes_nao_duplica(db_session) -> None:
    """§13: idempotência — o mesmo snapshot adotado duas vezes não muda nada."""
    device = _device_com_snapshot(db_session, "ne-plano-03", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    ).all()

    proposta_de_novo = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta_de_novo, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    assert len(db_session.scalars(select(models.CommunityPlan)).all()) == 1
    assert len(db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    ).all()) == len(eventos)  # sem transição, sem evento (ruling 5)
    assert len(db_session.scalars(
        select(models.Community).where(models.Community.name == "com-TRANSITO-FULL")
    ).all()) == 1


def test_a_validacao_roda_sobre_o_plano_adotado(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-04", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    achados = validar_plano(db_session, [device.id])
    assert obter_plano(db_session) is not None
    assert any(a.codigo == "classe_aplicada_nao_testada" and a.valor == "61785:3001" for a in achados)


def test_segunda_adocao_com_outro_asn_recusa(db_session) -> None:
    """R28: plano ativo de outro ASN principal recusa com `ConflictError`.

    Os filhos do plano não têm recorte por plano ativo: as UNIQUEs de
    `community_gates` (nome, papel, afi) e de `community_import_rules` (papel,
    afi) são do vocabulário inteiro, e a `CommunityImportRule` nem tem
    `admin_status` para desativar. Substituir o plano pediria mexer no modelo da
    T1, então a segunda adoção recusa **antes de escrever qualquer coisa** — o
    que mantém a transação única da §9 de pé.
    """
    device = _device_com_snapshot(db_session, "ne-plano-05", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    outra = replace(proposta, plano=replace(proposta.plano, asn_principal=65000))
    with pytest.raises(ConflictError) as erro:
        adotar_plano(db_session, outra, device_id=device.id, snapshot_id=None, actor="ana")
    assert "61785" in str(erro.value)  # a mensagem nomeia o ASN que está ativo

    ativo = db_session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.admin_status.is_(True))
    )
    assert ativo is not None and ativo.asn_principal == 61785
    assert db_session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.asn_principal == 65000)
    ) is None
