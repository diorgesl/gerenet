"""Golden do derivador de nomes §25.4/§8 — nomes ≤ 63 chars, maiúsculas, base = ASN do par."""
import pytest

from gerenet.automation.naming import as_path_own, pfx_in, pfx_produto, rp_export, rp_import, subinterface
from gerenet.domain.services.errors import ValidationError


def test_rp_import_export_pfx_por_afi() -> None:
    assert rp_import(64500, "ipv4") == "RP-64500-IMPORT-V4"
    assert rp_import(64500, "ipv6") == "RP-64500-IMPORT-V6"
    assert rp_export(64500, "ipv4") == "RP-64500-EXPORT-V4"
    assert rp_export(64500, "ipv6") == "RP-64500-EXPORT-V6"
    assert pfx_in(64500, "ipv4") == "IP-PFX-64500-IN-V4"
    assert pfx_in(64500, "ipv6") == "IP-PFX-64500-IN-V6"


def test_pfx_produto_e_subinterface() -> None:
    assert pfx_produto("default", "ipv4") == "IP-PFX-DEFAULT-V4"
    assert pfx_produto("cdn", "ipv6") == "IP-PFX-CDN-V6"
    assert subinterface("Eth-Trunk127", 4024) == "Eth-Trunk127.4024"
    assert subinterface("GE0/0/1", 100) == "GE0/0/1.100"


def test_as_path_own_nome() -> None:
    # §4.1/item 1 da revisão: as-path-filter de rotas próprias (AS-PATH-<ASN>-OWN)
    assert as_path_own(65001) == "AS-PATH-65001-OWN"
    assert len(as_path_own(4294967295)) <= 63
    with pytest.raises(ValidationError, match="ASN"):
        as_path_own(0)


def test_asn_sem_padding_e_limites_de_tamanho() -> None:
    # §25.4: decimal sem padding; 32 bits sem sinal; nenhum nome passa de 63 chars.
    assert rp_import(1, "ipv4") == "RP-1-IMPORT-V4"
    assert rp_import(4294967295, "ipv4") == "RP-4294967295-IMPORT-V4"
    for nome in (
        rp_import(4294967295, "ipv6"),
        rp_export(4294967295, "ipv6"),
        pfx_in(4294967295, "ipv6"),
    ):
        assert len(nome) <= 63


@pytest.mark.parametrize("asn", [0, -1, 4294967296])
def test_asn_invalido_rejeitado(asn: int) -> None:
    with pytest.raises(ValidationError, match="ASN"):
        rp_import(asn, "ipv4")


@pytest.mark.parametrize("afi", ["foo", "ipv3", ""])
def test_afi_invalida_rejeitada(afi: str) -> None:
    with pytest.raises(ValidationError, match="Família inválida"):
        rp_import(64500, afi)
