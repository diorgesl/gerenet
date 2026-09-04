"""Derivador de nomes VRP §25.4 (spec ciclo B, §5.1).

Nomes ≤ 63 chars, maiúsculas, separador '-', base = ASN do par em decimal
sem padding. Ex.: rp_import(64500, "ipv4") -> "RP-64500-IMPORT-V4".
Prefix-list por produto (IP-PFX-DEFAULT-V4 etc.) usada em T4/T5.
"""
from gerenet.domain.services.errors import ValidationError

_AFIS = {"ipv4": "V4", "ipv6": "V6"}


def _asn_valido(asn: int) -> str:
    if not 1 <= asn <= 4294967295:
        raise ValidationError(f"ASN inválido para nome VRP: {asn}.")
    return str(asn)


def _afi_valida(afi: str) -> str:
    if afi not in _AFIS:
        raise ValidationError(f"Família inválida: {afi} (esperado ipv4 ou ipv6).")
    return _AFIS[afi]


def rp_import(asn: int, afi: str) -> str:
    """Route-policy de importação: RP-<ASN>-IMPORT-<AFI>."""
    return f"RP-{_asn_valido(asn)}-IMPORT-{_afi_valida(afi)}"


def rp_export(asn: int, afi: str) -> str:
    """Route-policy de exportação: RP-<ASN>-EXPORT-<AFI>."""
    return f"RP-{_asn_valido(asn)}-EXPORT-{_afi_valida(afi)}"


def pfx_in(asn: int, afi: str) -> str:
    """Prefix-list de entrada (autorizações): IP-PFX-<ASN>-IN-<AFI>."""
    return f"IP-PFX-{_asn_valido(asn)}-IN-{_afi_valida(afi)}"


def pfx_produto(produto: str, afi: str) -> str:
    """Prefix-list de produto de exportação: IP-PFX-<PRODUTO>-<AFI>."""
    base = produto.upper().replace(" ", "-")
    if len(base) > 20:  # folga para o nome completo ficar ≤ 63
        raise ValidationError(f"Produto longo demais para nome VRP: {produto}.")
    return f"IP-PFX-{base}-{_afi_valida(afi)}"


def subinterface(trunk: str, vid: int) -> str:
    """Nome de subinterface dot1q: <trunk>.<vid>."""
    return f"{trunk}.{vid}"
