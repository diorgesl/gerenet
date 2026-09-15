"""A adoção transacional (design §5): uma transação por proposta."""
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.automation.discovery import listar_propostas
from gerenet.domain import models
from gerenet.domain.schemas import AdocaoIn, AdocaoSessaoIn, DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import adotar_proposta
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")
# O peer v4 do enlace do CLIENTE-ALFA tem `password cipher` na fixture; o valor
# mora no Vault e o que a SoT guarda é o caminho.
CAMINHO_SENHA = "gerenet/bgp-sessions/adoc-1001/password"


def _ambiente(db_session, tmp_path: Path):
    site = create_site(db_session, SiteCreate(name="pop-adoc", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-adoc", management_address="10.0.0.1",
                                                 asn=65001), actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return site, dev


def _proposta(db_session, dev, *, vid=1001):
    return next(p for p in listar_propostas(db_session, dev.id).propostas if p.vid == vid)


def _revisao(dev, *, code="ADOC-64512-1001", ciente=True):
    """A revisão do enlace do CLIENTE-ALFA.

    O `ciente` nasce ligado porque este enlace TEM diferença no grupo que muda:
    o peer tem senha no equipamento (`password cipher`, mascarada na conferência)
    e a SoT não a reproduz — o render só comenta que ela está no Vault. Sem o
    aceite explícito, a adoção recusa, e é o que o teste do `ciente` prende.
    """
    return AdocaoIn(
        device_id=dev.id, vrf=None, subinterface="Eth-Trunk127.1001",
        circuit_code=code, access_device_id=dev.id, access_port="GE0/0/1",
        organizacao_nova={"name": "Cliente Alfa", "kind": "downstream", "asn": 64512},
        # Só o peer v4 do enlace tem senha no equipamento: o operador informa o
        # caminho do segredo no Vault para essa sessão, e não para a outra.
        sessoes=[AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA),
                 AdocaoSessaoIn(afi="ipv6")],
        ciente=ciente,
    )


def _tipos_auditados(db_session) -> list[str]:
    return [e.type for e in db_session.scalars(select(models.AuditEvent))]


def test_adota_a_cadeia_inteira_numa_transacao(db_session, tmp_path) -> None:
    _site, dev = _ambiente(db_session, tmp_path)
    circ_id = adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                              revisao=_revisao(dev), actor="cli")
    circ = db_session.get(models.Circuit, circ_id)
    assert circ.code == "ADOC-64512-1001"
    assert circ.organization_id is not None
    vlan = db_session.scalar(select(models.Vlan).where(models.Vlan.circuit_id == circ_id))
    assert vlan.vid == 1001
    sessoes = list(db_session.scalars(
        select(models.BgpSession).where(models.BgpSession.circuit_id == circ_id)
    ))
    assert len(sessoes) == 2
    # O caminho do segredo que a revisão informou chega à sessão (§5.4).
    assert next(s for s in sessoes if s.afi == "ipv4").password_ref == CAMINHO_SENHA
    tipos = [e.type for e in db_session.scalars(select(models.AuditEvent))]
    assert "discovery.adopt" in tipos


def test_conflito_de_reserva_nao_deixa_nada_gravado(db_session, tmp_path) -> None:
    """A asserção que a parte 1 não podia fazer: a transação é uma só.

    O `vlan_tomada` já entra na proposta como conflito, então quem recusa aqui é
    a guarda do veredito — antes de qualquer escrita. Quem prova o rollback com
    escrita pendente é o `test_recusa_da_sessao_desfaz_a_adocao_inteira`.
    """
    from gerenet.domain.schemas import CircuitCreate, OrganizationCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.organizations import create_organization

    site, dev = _ambiente(db_session, tmp_path)
    org = create_organization(db_session, OrganizationCreate(name="Dono da VLAN", asn=64999),
                              actor="cli")
    tomador = create_circuit(db_session, CircuitCreate(
        code="CIRC-TOMADOR", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, vid=1001, kind="vlan", circuit_id=tomador.id))
    db_session.commit()
    antes = db_session.query(models.Circuit).count()
    with pytest.raises(ConflictError):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                        actor="cli")
    assert db_session.query(models.Circuit).count() == antes
    assert db_session.scalar(
        select(models.Organization).where(models.Organization.name == "Cliente Alfa")
    ) is None


def test_sem_organizacao_bloqueia(db_session, tmp_path) -> None:
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova = None
    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")
    # A mensagem prende QUAL guarda recusou: o `ciente` também levanta
    # `ValidationError`, e é antes desta.
    assert "Informe a organização" in str(exc.value)


def test_adotar_de_novo_encontra_a_lista_vazia(db_session, tmp_path) -> None:
    """O objeto passou a existir na SoT, então a proposta sai da lista sozinha."""
    _site, dev = _ambiente(db_session, tmp_path)
    adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                    actor="cli")
    assert 1001 not in {p.vid for p in listar_propostas(db_session, dev.id).propostas}


def test_diferenca_no_grupo_que_muda_exige_ciente(db_session, tmp_path) -> None:
    """Sem o aceite explícito, a adoção recusa a diferença que mudaria o
    equipamento — e não grava nada (design §6/§9)."""
    _site, dev = _ambiente(db_session, tmp_path)
    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                        revisao=_revisao(dev, ciente=False), actor="cli")
    assert "ciente" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0
    assert "discovery.adopt" not in _tipos_auditados(db_session)


def test_recusa_da_sessao_desfaz_a_adocao_inteira(db_session, tmp_path) -> None:
    """A recusa chega com a organização, o circuito e as reservas já gravados:
    é o rollback da adoção que faz não sobrar adoção parcial (design §9)."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova.asn = 64999  # o ASN do par é 64512

    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert "64512" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0
    assert db_session.query(models.Organization).count() == 0
    assert db_session.query(models.Vlan).count() == 0
    assert db_session.query(models.IpPrefix).count() == 0
    assert db_session.query(models.BgpSession).count() == 0
    # A trilha é da mesma transação: o que o rollback desfez não deixa evento.
    assert "circuit.create" not in _tipos_auditados(db_session)
    assert "discovery.adopt" not in _tipos_auditados(db_session)
