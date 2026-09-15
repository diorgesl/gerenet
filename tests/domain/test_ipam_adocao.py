"""A reserva por valores reais (design §4): grava o que o equipamento tem."""
import pytest
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.ipam import pontas_v4, reservar_adocao
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


def _por_nome(db_session, modelo, nome: str):
    return db_session.scalar(select(modelo).where(modelo.name == nome))


def _ambiente(db_session) -> tuple[models.Site, models.Organization, models.Device, models.Device]:
    """Site, organização e o par de equipamentos, criados uma vez por teste.

    Os três serviços recusam nome repetido e o ASN da organização é único
    (§14.1), então um teste que cria dois circuitos precisa reusar o ambiente.
    O site é um só de propósito: a unicidade de VLAN e de prefixo é por site, e
    é dentro dele que o conflito do teste de unicidade existe.
    """
    site = _por_nome(db_session, models.Site, "pop-adoc")
    if site is None:
        site = create_site(
            db_session,
            SiteCreate(name="pop-adoc", p2p_ipv4_block="100.64.70.0/24"),
            actor="cli",
        )
    org = _por_nome(db_session, models.Organization, "Org Adoc")
    if org is None:
        org = create_organization(
            db_session, OrganizationCreate(name="Org Adoc", asn=64701), actor="cli"
        )
    devices = []
    for nome, endereco in (("adoc-sw", "10.0.0.2"), ("adoc-ne", "10.0.0.1")):
        dev = _por_nome(db_session, models.Device, nome)
        if dev is None:
            dev = create_device(
                db_session,
                DeviceCreate(name=nome, management_address=endereco, site_id=site.id),
                actor="cli",
            )
        devices.append(dev)
    return (site, org, *devices)


def _circuito(db_session, *, code="CIRC-ADOC") -> models.Circuit:
    """Circuito no ambiente do arquivo: `CircuitCreate` exige device de acesso e de edge."""
    site, org, sw, ne = _ambiente(db_session)
    return create_circuit(
        db_session,
        CircuitCreate(code=code, organization_id=org.id, site_id=site.id,
                      access_device_id=sw.id, access_port="GE0/0/1", edge_device_id=ne.id),
        actor="cli",
    )


def test_grava_os_valores_reais_inclusive_o_v6_nao_derivado(db_session) -> None:
    """O v6 legado não segue a derivação do §25.8, e é o valor do equipamento
    que precisa ser preservado."""
    circ = _circuito(db_session)
    reservar_adocao(
        db_session, circ.id,
        vlans=[{"vid": 625, "kind": "vlan", "family": None}],
        prefixos=[{"network": "100.110.0.0/30", "ponta_local": "inferior"},
                  {"network": "2804:194C:1000::1100:0:0/126", "ponta_local": "inferior"}],
        actor="cli", origem_snapshot_id=7,
    )
    vlan = db_session.scalar(select(models.Vlan).where(models.Vlan.circuit_id == circ.id))
    assert vlan.vid == 625
    prefixos = list(db_session.scalars(
        select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ.id)
    ))
    assert {p.network for p in prefixos} == {"100.110.0.0/30", "2804:194C:1000::1100:0:0/126"}
    assert all(p.ponta_local == "inferior" for p in prefixos)


def test_grava_a_ponta_superior_quando_e_a_do_equipamento(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-SUP")
    reservar_adocao(
        db_session, circ.id,
        vlans=[{"vid": 626, "kind": "vlan", "family": None}],
        prefixos=[{"network": "100.64.70.0/31", "ponta_local": "superior"}],
        actor="cli",
    )
    prefixo = db_session.scalar(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ.id))
    assert prefixo.ponta_local == "superior"
    assert pontas_v4(prefixo.network, prefixo.ponta_local)[0] == "100.64.70.1"


def test_conflito_de_vlan_vira_conflict_error_nomeado(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-A")
    reservar_adocao(db_session, circ.id, vlans=[{"vid": 627, "kind": "vlan", "family": None}],
                    prefixos=[], actor="cli")
    outro = _circuito(db_session, code="CIRC-ADOC-B")
    with pytest.raises(ConflictError) as exc:
        reservar_adocao(db_session, outro.id, vlans=[{"vid": 627, "kind": "vlan", "family": None}],
                        prefixos=[], actor="cli")
    assert "627" in str(exc.value)


def test_conflito_de_prefixo_vira_conflict_error_nomeado(db_session) -> None:
    """A irmã da VLAN: a pré-checagem existe para NOMEAR o que está tomado (§4),
    e o prefixo era o único caminho de recusa da adoção sem teste próprio — se
    ela sumisse, quem recusava era o `flush`, com a mensagem genérica e sem
    dizer qual prefixo é."""
    circ = _circuito(db_session, code="CIRC-ADOC-PFX-A")
    reservar_adocao(db_session, circ.id, vlans=[],
                    prefixos=[{"network": "100.64.70.0/31", "ponta_local": "inferior"}],
                    actor="cli")
    outro = _circuito(db_session, code="CIRC-ADOC-PFX-B")
    with pytest.raises(ConflictError) as exc:
        reservar_adocao(db_session, outro.id, vlans=[],
                        prefixos=[{"network": "100.64.70.0/31", "ponta_local": "inferior"}],
                        actor="cli")
    assert "100.64.70.0/31" in str(exc.value)


def test_conflito_de_prefixo_acha_a_caixa_divergente(db_session) -> None:
    """O `/126` do IPv6 sai do equipamento em maiúsculas (`194C`) e o cadastro
    guarda a caixa que veio: dois textos que só divergem na caixa são o MESMO
    prefixo. Comparando texto cru a pré-checagem ficava calada, e o índice do
    banco — que é sensível à caixa — deixava a segunda reserva passar em
    silêncio, com o mesmo prefixo reservado duas vezes."""
    circ = _circuito(db_session, code="CIRC-ADOC-PFX-CAIXA-A")
    reservar_adocao(
        db_session, circ.id, vlans=[],
        prefixos=[{"network": "2804:194C:1000::1100:0:0/126", "ponta_local": "inferior"}],
        actor="cli",
    )
    outro = _circuito(db_session, code="CIRC-ADOC-PFX-CAIXA-B")
    with pytest.raises(ConflictError) as exc:
        reservar_adocao(
            db_session, outro.id, vlans=[],
            prefixos=[{"network": "2804:194c:1000::1100:0:0/126", "ponta_local": "inferior"}],
            actor="cli",
        )
    assert "2804:194c:1000::1100:0:0/126" in str(exc.value)


def test_valor_fora_de_faixa_e_validation_error(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-V")
    with pytest.raises(ValidationError):
        reservar_adocao(db_session, circ.id, vlans=[{"vid": 1, "kind": "vlan", "family": None}],
                        prefixos=[], actor="cli")
    with pytest.raises(ValidationError):
        reservar_adocao(db_session, circ.id,
                        vlans=[],
                        prefixos=[{"network": "100.64.70.0/24", "ponta_local": "inferior"}],
                        actor="cli")


def test_e_idempotente(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-IDEM")
    for _ in range(2):
        reservar_adocao(db_session, circ.id, vlans=[{"vid": 628, "kind": "vlan", "family": None}],
                        prefixos=[{"network": "100.64.70.0/31", "ponta_local": "inferior"}],
                        actor="cli")
    vlan = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ.id)))
    assert len(vlan) == 1


def test_audita_com_origem_adocao_e_o_snapshot(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-AUD")
    reservar_adocao(db_session, circ.id, vlans=[{"vid": 629, "kind": "vlan", "family": None}],
                    prefixos=[], actor="cli", origem_snapshot_id=42)
    evento = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "circuit.reserve")
        .order_by(models.AuditEvent.id.desc())
    ).first()
    # a coluna do payload de auditoria é `details`, e a origem vive no painel `depois`
    assert evento is not None
    assert evento.details["depois"]["origem"] == "adocao"
    assert evento.details["depois"]["snapshot_id"] == 42
