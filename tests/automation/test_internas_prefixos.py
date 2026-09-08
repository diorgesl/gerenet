"""Helper de rotas internas (Fase 5/B1): prefixos próprios — loopbacks + p2p alocados."""
import pytest

from gerenet.automation.naming import pfx_export
from gerenet.automation.render import internas_prefixos
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError


def test_internas_prefixos_loopback_e_p2p(session, edge_device, circuito_com_p2p):
    edge_device.loopback = "10.99.0.253"
    session.commit()
    out = internas_prefixos(session)
    assert "100.64.10.0/31" in out["ipv4"]  # p2p reservado do circuito
    assert "10.99.0.253/32" in out["ipv4"]
    assert out["ipv6"] == []


def test_internas_prefixos_v6(session, site_f5, edge_device):
    edge_device.loopback = "2001:db8::1"
    session.add(models.IpPrefix(site_id=site_f5.id, network="2001:db8:0:1::/126"))
    session.commit()
    out = internas_prefixos(session)
    assert "2001:db8::1/128" in out["ipv6"]  # /128, nunca /32 (seria rede errada)
    assert "2001:db8:0:1::/126" in out["ipv6"]
    assert out["ipv4"] == []


def test_internas_prefixos_ordena_evita_dups_e_filtra(session, site_f5, edge_device):
    edge_device.loopback = "10.99.0.253"
    session.add(models.Device(
        name="edge-f5-2", management_address="10.99.0.2", site_id=site_f5.id,
        asn=65002, loopback="10.0.0.1"))
    # device desativado: loopback não conta como rota interna
    session.add(models.Device(
        name="edge-f5-3", management_address="10.99.0.3", site_id=site_f5.id,
        asn=65003, loopback="10.99.0.254", admin_status=False))
    # mesmo CIDR do loopback reservado como p2p → dedup no resultado
    session.add(models.IpPrefix(site_id=site_f5.id, network="10.99.0.253/32"))
    # p2p liberado: não é rota interna ativa
    session.add(models.IpPrefix(site_id=site_f5.id, network="100.64.11.0/31", status="liberada"))
    session.commit()
    out = internas_prefixos(session)
    assert out["ipv4"] == ["10.0.0.1/32", "10.99.0.253/32"]
    assert out["ipv6"] == []


def test_pfx_export_nome() -> None:
    # §25.4: o nome deriva do ASN do par (IP-PFX-<ASN>-EXPORT-<AFI>) — nunca
    # global; a mesma lista não é compartilhada entre upstreams.
    assert pfx_export(64501, "ipv4") == "IP-PFX-64501-EXPORT-V4"
    assert pfx_export(64501, "ipv6") == "IP-PFX-64501-EXPORT-V6"
    with pytest.raises(ValidationError):
        pfx_export(64501, "vpn")
