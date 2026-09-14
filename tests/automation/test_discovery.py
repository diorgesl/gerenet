"""Motor de descoberta: candidatos e classificação (spec §4–§5). Read-only."""
from pathlib import Path

from sqlalchemy import select

from gerenet.automation.discovery import listar_candidatos
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import ignorar_candidato
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _ambiente(db_session, *, asn=65001):
    """Equipamento com site e a configuração da fixture salva em disco."""
    site = create_site(db_session, SiteCreate(name="pop-desc", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc",
                                                 management_address="10.0.0.1", asn=asn),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    return dev


def _com_config(db_session, dev, tmp_path: Path):
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    snap = models.DeviceSnapshot(device_id=dev.id, status="success",
                                 raw_files={"config_backup": [str(arquivo)]})
    db_session.add(snap)
    db_session.commit()
    return snap


def test_sem_snapshot_avisa_e_nao_devolve_lista_vazia_muda(db_session) -> None:
    dev = _ambiente(db_session)
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.candidatos == []
    assert resultado.snapshot_id is None
    assert resultado.aviso is not None
    assert "configuração" in resultado.aviso


def test_todos_os_peers_desconhecidos_sao_candidatos(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert {p.remote_address for p in resultado.candidatos} == {
        "100.64.10.1", "100.64.10.4", "100.64.10.3",
        "2804:194c:1000::1100:73:2", "10.99.0.1",
    }


def test_peer_interno_vai_para_a_lista_separada(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert [p.remote_address for p in resultado.internos] == ["10.0.0.9"]
    assert resultado.internos[0].classificacao == "interno"
    assert "65001" in resultado.internos[0].motivo


def test_peer_que_casa_com_sessao_da_sot_nao_e_candidato(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-001", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.1" not in {p.remote_address for p in resultado.candidatos}


def test_sessao_desativada_conta_como_conhecida(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-002", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512, admin_status=False,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.1" not in {p.remote_address for p in resultado.candidatos}


def test_ignorado_nao_e_candidato(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    ignorar_candidato(db_session, device_id=dev.id, vrf=None, afi="ipv4",
                      remote_address="100.64.10.4", motivo="cliente saiu", actor="cli")
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.4" not in {p.remote_address for p in resultado.candidatos}


def test_classificacao_por_organizacao(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    # 64501 é o ASN do par TRANSITO-GAMA da fixture, mas cai na faixa de
    # documentação (64496-64511) e `create_organization` o recusa; a organização
    # entra por ORM, como no `org_operadora` do conftest.
    db_session.add(models.Organization(name="Operadora Gama", asn=64501, kind="operadora"))
    db_session.commit()
    create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                        actor="cli")
    _com_config(db_session, dev, tmp_path)
    por_endereco = {p.remote_address: p for p in listar_candidatos(db_session, dev.id).candidatos}
    assert por_endereco["100.64.10.3"].classificacao == "upstream"
    assert "Operadora Gama" in por_endereco["100.64.10.3"].motivo
    assert por_endereco["100.64.10.1"].classificacao == "downstream"
    assert "Cliente Alfa" in por_endereco["100.64.10.1"].motivo


def test_sem_organizacao_fica_nao_confirmada(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    por_endereco = {p.remote_address: p for p in listar_candidatos(db_session, dev.id).candidatos}
    beta = por_endereco["100.64.10.4"]
    assert beta.classificacao == "downstream"
    assert "não confirmada" in beta.motivo


def test_snapshot_sem_config_devolve_aviso(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"interfaces": []}))
    db_session.commit()
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.candidatos == []
    assert resultado.aviso is not None


def test_captura_sem_bloco_bgp_avisa_o_que_nao_foi_lido(db_session, tmp_path) -> None:
    """Sem bloco `bgp` o parser avisa; a lista vem vazia, mas não muda (§3)."""
    dev = _ambiente(db_session)
    arquivo = tmp_path / "sem-bgp.txt"
    arquivo.write_text("sysname ne8000-desc\ninterface GE0/0/1\n description uplink\n",
                       encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.snapshot_id is not None
    assert resultado.aviso is not None
    assert "bgp" in resultado.aviso  # o aviso da leitura, não o de "sem coleta"
    assert resultado.candidatos == []
    assert resultado.internos == []
