"""Validações puras compartilhadas pelos serviços (mensagens PT-BR)."""
import ipaddress
import re

from gerenet.domain.services.errors import ValidationError

# Faixas reservadas que nunca podem ser ASN de organização/par (§14.1, spec ciclo A):
# 0, 23456 (AS_TRANS), 64496-64511 e 65536-65551 (documentação RFC 5398),
# 65535 (reservado), 4200000000-4294967294 (documentação 32 bits).
_ASN_RESERVADAS: tuple[tuple[int, int], ...] = (
    (0, 0),
    (23456, 23456),
    (64496, 64511),
    (65535, 65551),
    (4200000000, 4294967294),
)

# Mensagem do ipaddress quando os host bits estão setados ("100.64.0.1/31 has host
# bits set") — estável entre versões; distingue "desalinhado" de "não é CIDR".
_HOST_BITS_SET = re.compile(r"has host bits set")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def asn_valido(asn: int) -> bool:
    """ASN válido de 32 bits e fora das faixas reservadas."""
    if not (1 <= asn <= 4294967295):
        return False
    return not any(inicio <= asn <= fim for inicio, fim in _ASN_RESERVADAS)


def cidr_valido(cidr: str, familia: str | None = None) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Valida um CIDR alinhado ao prefixo (host bits zerados).

    familia: "ipv4" | "ipv6" — quando informada, exige essa versão.
    """
    try:
        rede = ipaddress.ip_network(cidr, strict=True)
    except ValueError as exc:
        if _HOST_BITS_SET.search(str(exc)):
            raise ValidationError(f"CIDR {cidr} não está alinhado ao prefixo.") from exc
        raise ValidationError(f"CIDR inválido: {cidr}.") from exc
    if familia == "ipv4" and rede.version != 4:
        raise ValidationError(f"O CIDR {cidr} não é um prefixo IPv4.")
    if familia == "ipv6" and rede.version != 6:
        raise ValidationError(f"O CIDR {cidr} não é um prefixo IPv6.")
    return rede


def validar_vid(vid: int) -> None:
    """VID de VLAN: 2–4094 (1 é a nativa; 0/4095 reservados)."""
    if not 2 <= vid <= 4094:
        raise ValidationError(f"VID fora do intervalo permitido (2–4094): {vid}.")


def email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.fullmatch(email))
