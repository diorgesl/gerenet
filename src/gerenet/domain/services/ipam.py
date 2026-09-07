"""Alocador de enlace p2p (IPAM, §25.8).

Funções puras (sufixo IPv6, pontas, blocos); o serviço transacional
reservar_circuito entra na Task 9 — mesmo arquivo.
"""
import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.config import get_settings
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.circuits import get_circuit
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.validators import validar_vid


def bloco_v4(site: models.Site) -> ipaddress.IPv4Network:
    """Bloco de enlaces v4 do site (override) ou o default dos settings."""
    origem = site.p2p_ipv4_block or get_settings().p2p_ipv4_block
    return ipaddress.ip_network(origem, strict=False)


def _preserva_caixa(entrada: str, saida: str) -> str:
    """Espelha no texto canônico `saida` a caixa de `entrada`.

    O ipaddress normaliza o hex para minúsculas; se o texto de origem trouxer
    letra hex maiúscula (A-F), o resultado volta em maiúsculas — o golden do
    §25.8 usa '194C'. Entrada sem letra maiúscula sai como o ipaddress gera.
    """
    if any(c in "ABCDEF" for c in entrada):
        return saida.upper()
    return saida


def base_v6(site: models.Site) -> str:
    """Base v6 do site (override) ou o default; forma '2804:194C:1000::'.

    Remove o prefixo e os host bits (rede do bloco), devolvendo o texto
    canônico com a caixa do texto de origem (§25.8 usa '194C'; host bits não
    podem vazar para o sufixo montado por _addr_v6).
    """
    origem = site.p2p_ipv6_base or get_settings().p2p_ipv6_base
    rede = ipaddress.ip_network(origem, strict=False)
    return _preserva_caixa(origem, str(rede.network_address))


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
    """Pontas local/remota de um /126 (rede +1/+2), com prefixo no retorno."""
    rede = ipaddress.ip_network(network, strict=True)
    if rede.prefixlen != 126:
        raise ValidationError(f"Enlace p2p v6 deve ser /126: {network}.")
    base = int(rede.network_address)
    local = _preserva_caixa(network, str(ipaddress.IPv6Address(base + 1)))
    remota = _preserva_caixa(network, str(ipaddress.IPv6Address(base + 2)))
    return (f"{local}/126", f"{remota}/126")


def _primeiro_vid(session: Session, site_id: int, ignorar: set[int] | None = None) -> int:
    """Menor VID 2-4094 livre no site para circuitos (linhas MPLS — device_id NOT
    NULL — têm escopo de device e não contam; Ruling 6: só linhas existentes)."""
    ocupados = set(session.scalars(
        select(models.Vlan.vid).where(
            models.Vlan.site_id == site_id, models.Vlan.device_id.is_(None),
        )
    ))
    if ignorar:
        ocupados |= ignorar
    for vid in range(2, 4095):
        if vid not in ocupados:
            validar_vid(vid)
            return vid
    raise ConflictError("VLANs esgotadas neste site.")


def _primeiro_livre(session: Session, site: models.Site, comprimento: int) -> ipaddress.IPv4Network:
    """Próximo prefixo v4 livre no bloco do site (first-fit, sem sobreposição)."""
    bloco = bloco_v4(site)
    ocupadas = [
        ipaddress.ip_network(linha, strict=True)
        for linha in session.scalars(
            select(models.IpPrefix.network).where(models.IpPrefix.site_id == site.id)
        )
    ]
    for candidata in bloco.subnets(new_prefix=comprimento):
        if not any(candidata.overlaps(existente) for existente in ocupadas):
            return candidata
    raise ConflictError("Bloco p2p do site esgotado.")


def reservar_circuito(session: Session, circuit_id: int, *, actor: str) -> models.Circuit:
    """Reserva VLAN(s) e enlace(s) p2p do circuito — idempotente (§3.2).

    Circuito já reservado ⇒ devolve o estado atual e audita como no-op.
    stack: ipv4 ⇒ só v4; dual ⇒ v4 + v6 derivado; ipv6 ⇒ v4 interno de
    derivação (anotado em notes) + v6 (spec). Primeira alocação é
    transacional: falha antes do add_all ⇒ nenhuma linha parcial.
    """
    circ = get_circuit(session, circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe reservas.")
    ja_reservado = (
        session.scalars(
            select(models.Vlan.id).where(models.Vlan.circuit_id == circ.id).limit(1)
        ).first()
        is not None
    )
    if ja_reservado:
        registrar(
            session, tipo="circuit.reserve", ator=actor, objeto="circuit",
            objeto_id=circ.id, antes=None, depois={"repetida": True},
        )
        session.commit()
        return circ

    site = session.get(models.Site, circ.site_id)
    vlans: list[models.Vlan] = []
    prefixos: list[models.IpPrefix] = []

    # VLANs: 1 linha (unica) ou 2 por família (separada); kind s_vlan no QinQ
    familias: list[str | None] = [None]
    if circ.vlan_mode == "separada":
        familias = ["ipv4", "ipv6"]
    vids_reservados: set[int] = set()
    for familia in familias:
        vid = _primeiro_vid(session, circ.site_id, vids_reservados)
        vids_reservados.add(vid)
        vlans.append(
            models.Vlan(
                site_id=circ.site_id,
                vid=vid,
                kind="s_vlan" if circ.qinq else "vlan",
                family=familia,
                circuit_id=circ.id,
                status="reservada",
            )
        )

    # Enlace p2p v4 (+ v6 derivado quando dual/ipv6)
    precisa_v4 = circ.stack in ("ipv4", "dual", "ipv6")  # ipv6: só p/ derivar o sufixo
    rede_v4: ipaddress.IPv4Network | None = None
    if precisa_v4:
        rede_v4 = _primeiro_livre(session, site, circ.p2p_v4_len)
        prefixos.append(
            models.IpPrefix(
                site_id=circ.site_id,
                network=str(rede_v4),
                kind="p2p",
                circuit_id=circ.id,
                notes=(
                    "Par v4 interno — derivação do sufixo IPv6 (§25.8)."
                    if circ.stack == "ipv6"
                    else None
                ),
            )
        )
    if circ.stack in ("dual", "ipv6"):
        if rede_v4 is None:  # defesa: dual/ipv6 sempre passam pelo v4 acima
            raise ConflictError("Reserva v6 exige o par v4 de derivação.")
        sufixo = derivar_v6(str(rede_v4.network_address))
        rede_v6 = f"{_addr_v6(base_v6(site), sufixo, 0)}/126"
        # Ruling 7: concatenação decimal não é injetiva — falha clara em vez de UNIQUE
        ja_existe = (
            session.scalars(
                select(models.IpPrefix.network).where(
                    models.IpPrefix.site_id == circ.site_id,
                    models.IpPrefix.network == rede_v6,
                )
            ).first()
            is not None
        )
        if ja_existe:
            raise ConflictError(
                f"Enlace v6 {rede_v6} (derivado de {rede_v4.network_address}) já reservado "
                "neste site."
            )
        prefixos.append(
            models.IpPrefix(
                site_id=circ.site_id,
                network=rede_v6,
                kind="p2p",
                circuit_id=circ.id,
            )
        )

    session.add_all(vlans + prefixos)
    session.flush()
    registrar(
        session, tipo="circuit.reserve", ator=actor, objeto="circuit", objeto_id=circ.id,
        antes=None,
        depois={
            "vlans": [{"vid": v.vid, "kind": v.kind, "family": v.family} for v in vlans],
            "ip_prefixes": [{"network": p.network} for p in prefixos],
        },
    )
    session.commit()
    session.refresh(circ)
    return circ
