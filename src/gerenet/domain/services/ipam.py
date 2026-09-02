"""Alocador de enlace p2p (IPAM, §25.8).

Funções puras (sufixo IPv6, pontas, blocos); o serviço transacional
reservar_circuito entra na Task 9 — mesmo arquivo.
"""
import ipaddress

from gerenet.config import get_settings
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError


def bloco_v4(site: models.Site) -> ipaddress.IPv4Network:
    """Bloco de enlaces v4 do site (override) ou o default dos settings."""
    origem = site.p2p_ipv4_block or get_settings().p2p_ipv4_block
    return ipaddress.ip_network(origem, strict=False)


def base_v6(site: models.Site) -> str:
    """Base v6 do site (override) ou o default; forma '2804:194C:1000::'.

    Mantém o texto do endereço como cadastrado, apenas sem o prefixo
    (ipaddress normalizaria o hex para minúsculas e o golden do §25.8 usa
    '194C'); o ip_network acima valida a forma antes do corte.
    """
    origem = site.p2p_ipv6_base or get_settings().p2p_ipv6_base
    ipaddress.ip_network(origem, strict=False)  # valida antes de usar o texto
    return origem.split("/", 1)[0]


def derivar_v6(ipv4: str) -> str:
    """Sufixo do §25.8 a partir de um IPv4 de enlace.

    Octetos 2-4 concatenados sem zero-padding, relidos como dígitos hex e
    agrupados em hextets: grupo 1 = 4 primeiros dígitos, grupo 2 = o restante;
    grupo vazio é omitido. Ex.: 100.110.0.73 → "110.0.73" → dígitos "110073"
    → hextets "1100:73".
    """
    octetos = ipv4.split(".")
    if len(octetos) != 4:
        raise ValidationError(f"IPv4 inválido para derivação do sufixo: {ipv4}.")
    digitos = "".join(octetos[1:4])
    if len(digitos) > 8:
        raise ValidationError(
            f"O sufixo IPv6 derivado de {ipv4} excede 8 dígitos hex (limite de 2 hextets)."
        )
    if len(digitos) <= 4:
        return digitos
    return f"{digitos[:4]}:{digitos[4:]}"


def _addr_v6(base: str, sufixo: str, host: int) -> str:
    """Monta o endereço v6: base + hextets do sufixo + hextet de host.

    base termina em '::' (ex.: '2804:194C:1000::'). host = 0 produz a rede do
    /126 (bits de host zerados); host 1/2 produzem as pontas. Hextet final
    carrega os host bits nos 2 LSBs (spec §25.8).
    """
    corpo = f"{sufixo}:{host}" if sufixo else str(host)
    return f"{base}{corpo}"


def pontas_v4(network: str) -> tuple[str, str]:
    """Pontas local/remota de um enlace v4 (/31: .0/.1; /30: .1/.2)."""
    rede = ipaddress.ip_network(network, strict=True)
    base = int(rede.network_address)
    if rede.prefixlen == 31:
        return (str(ipaddress.IPv4Address(base)), str(ipaddress.IPv4Address(base + 1)))
    if rede.prefixlen == 30:
        return (str(ipaddress.IPv4Address(base + 1)), str(ipaddress.IPv4Address(base + 2)))
    raise ValidationError(f"Enlace p2p v4 deve ser /30 ou /31: {network}.")


def pontas_v6(network: str) -> tuple[str, str]:
    """Pontas local/remota de um /126 (rede +1/+2), com prefixo no retorno.

    Preserva a caixa do texto informado (o golden do §25.8 usa '194C';
    ipaddress normalizaria o hex para minúsculas).
    """
    rede = ipaddress.ip_network(network, strict=True)
    if rede.prefixlen != 126:
        raise ValidationError(f"Enlace p2p v6 deve ser /126: {network}.")
    base = int(rede.network_address)
    local = str(ipaddress.IPv6Address(base + 1))
    remota = str(ipaddress.IPv6Address(base + 2))
    if any(c in "ABCDEF" for c in network):
        local, remota = local.upper(), remota.upper()
    return (f"{local}/126", f"{remota}/126")
