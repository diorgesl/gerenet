import pytest
from sqlalchemy.orm import Session

from gerenet.config import get_settings
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.ipam import (
    _addr_v6,
    base_v6,
    bloco_v4,
    derivar_v6,
    pontas_v4,
    pontas_v6,
)


def test_bloco_v4_usa_override_do_site_e_settings() -> None:
    site = models.Site(name="pop-a", p2p_ipv4_block="100.64.0.0/24")
    assert str(bloco_v4(site)) == "100.64.0.0/24"
    assert str(bloco_v4(models.Site(name="pop-b"))) == "100.64.0.0/10"  # settings default
    assert get_settings().p2p_ipv6_base == "2804:194C:1000::/48"


def test_base_v6_sem_prefixo() -> None:
    site = models.Site(name="pop-a", p2p_ipv6_base="2804:194C:2000::/48")
    assert base_v6(site) == "2804:194C:2000::"


def test_derivar_v6_golden_da_spec() -> None:
    # §25.8 verbatim: 100.110.0.73 → octetos 2-4 = 110.0.73 → "110073" → "1100:73"
    assert derivar_v6("100.110.0.73") == "1100:73"


def test_derivar_v6_sufixo_curto_sem_zero_padding() -> None:
    assert derivar_v6("100.10.0.5") == "1005"    # "10"+"0"+"5" = "1005" (4 dígitos → 1 hextet)
    assert derivar_v6("100.2.3.4") == "234"      # "2"+"3"+"4" = "234" (hextet único)
    assert derivar_v6("100.64.0.1") == "6401"    # "64"+"0"+"1" = "6401" (4 dígitos → hextet único)


def test_derivar_v6_overflow_levanta_erro() -> None:
    # Ruling 4: 9 dígitos não cabem em 2 hextets (ex.: 100.127.255.255 → "127255255")
    with pytest.raises(ValidationError):
        derivar_v6("100.127.255.255")


def test_addr_v6_monta_enderecos_do_golden() -> None:
    assert _addr_v6("2804:194C:1000::", "1100:73", 1) == "2804:194C:1000::1100:73:1"
    assert _addr_v6("2804:194C:1000::", "1100:73", 2) == "2804:194C:1000::1100:73:2"
    assert _addr_v6("2804:194C:1000::", "", 1) == "2804:194C:1000::1"
    assert _addr_v6("2804:194C:1000::", "1005", 1) == "2804:194C:1000::1005:1"


def test_pontas_v4_31_e_30() -> None:
    assert pontas_v4("100.64.0.0/31") == ("100.64.0.0", "100.64.0.1")
    assert pontas_v4("100.64.0.2/31") == ("100.64.0.2", "100.64.0.3")
    assert pontas_v4("100.64.0.0/30") == ("100.64.0.1", "100.64.0.2")


def test_pontas_v6_derivam_dentro_do_126() -> None:
    local, remota = pontas_v6("2804:194C:1000::1100:73:0/126")
    assert local == "2804:194C:1000::1100:73:1/126"
    assert remota == "2804:194C:1000::1100:73:2/126"


def test_base_v6_remove_host_bits_preservando_caixa() -> None:
    # host bits do texto de origem não podem vazar para o sufixo montado
    site = models.Site(name="pop-hb", p2p_ipv6_base="2804:194C:1000::5/48")
    assert base_v6(site) == "2804:194C:1000::"
    site_lc = models.Site(name="pop-hb-lc", p2p_ipv6_base="2804:194c:1000::5/48")
    assert base_v6(site_lc) == "2804:194c:1000::"


def test_pontas_v6_roundtrip_golden_completo() -> None:
    """Do IPv4 do golden à rede v6 e às duas pontas (spec §6/§25.8)."""
    ipv4 = "100.110.0.73"
    sufixo = derivar_v6(ipv4)
    rede = f"{_addr_v6(base_v6(models.Site(name='pop')), sufixo, 0)}/126"
    assert rede == "2804:194C:1000::1100:73:0/126"
    local, remota = pontas_v6(rede)
    assert local == "2804:194C:1000::1100:73:1/126"
    assert remota == "2804:194C:1000::1100:73:2/126"
