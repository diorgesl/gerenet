"""Parser do `display current-configuration` do VRP (spec §3).

Diferente dos parsers de `display`, que leem saída tabular em TextFSM, a
configuração é uma árvore: o bloco `bgp <asn>` contém seções de família e é
dentro delas que vivem os peers, e a interface carrega `vlan-type` e endereços.
Ler isso com TextFSM produz um template ilegível, então aqui a leitura é linha a
linha mantendo o contexto do bloco.

O valor de `password cipher` NUNCA é lido: o parser registra que existe senha e
segue (§19).

Tolerância a linha desconhecida: a captura de um equipamento real traz comandos
que este parser não modela. Linha que não casa com nenhum ramo é ignorada, e os
endereços só entram quando são endereço de verdade — perder a captura inteira por
causa de uma linha (`ip address unnumbered ...`) seria pior do que ignorá-la.
"""
import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class PeerConfig:
    address: str
    afi: str                      # do endereço: "ipv4" | "ipv6"
    vrf: str | None               # None = instância pública
    asn_local: int
    asn_remote: int | None
    descricao: str | None
    tem_password: bool
    import_route_policy: str | None
    export_route_policy: str | None
    import_prefix_list: str | None
    maximum_prefix: int | None
    maximum_prefix_threshold: int | None
    keepalive: int | None
    holdtime: int | None
    bfd: bool
    graceful_restart: bool
    shutdown: bool
    habilitado: bool


@dataclass(frozen=True)
class Subinterface:
    nome: str
    vid: int | None               # None na interface principal
    qinq: bool
    descricao: str | None
    mtu: int | None
    enderecos_v4: tuple[tuple[str, str], ...]
    enderecos_v6: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ConfigVrp:
    peers: tuple[PeerConfig, ...] = ()
    subinterfaces: tuple[Subinterface, ...] = ()


def _novo_peer(endereco: str, vrf: str | None, asn_local: int) -> dict:
    return {
        "address": endereco,
        "afi": "ipv6" if ":" in endereco else "ipv4",
        "vrf": vrf,
        "asn_local": asn_local,
        "asn_remote": None,
        "descricao": None,
        "tem_password": False,
        "import_route_policy": None,
        "export_route_policy": None,
        "import_prefix_list": None,
        "maximum_prefix": None,
        "maximum_prefix_threshold": None,
        "keepalive": None,
        "holdtime": None,
        "bfd": False,
        "graceful_restart": False,
        "shutdown": False,
        "habilitado": False,
    }


def _aplica_peer(reg: dict, resto: list[str], linha: str) -> None:
    """Aplica uma linha `peer <endereço> ...` ao registro acumulado."""
    if not resto:
        return
    if resto[0] == "as-number" and len(resto) >= 2:
        reg["asn_remote"] = int(resto[1])
    elif resto[0] == "description":
        reg["descricao"] = linha.split("description", 1)[1].strip()
    elif resto[0] == "password":
        # O valor (cipher) não é lido: só a presença interessa (§19).
        reg["tem_password"] = True
    elif resto[:2] == ["timer", "keepalive"] and len(resto) >= 3:
        reg["keepalive"] = int(resto[2])
        if "hold" in resto:
            reg["holdtime"] = int(resto[resto.index("hold") + 1])
    elif "route-policy" in resto and resto.index("route-policy") + 1 < len(resto):
        nome = resto[resto.index("route-policy") + 1]
        if "export" in resto:
            reg["export_route_policy"] = nome
        else:
            reg["import_route_policy"] = nome
    elif "ip-prefix" in resto and resto.index("ip-prefix") + 1 < len(resto):
        reg["import_prefix_list"] = resto[resto.index("ip-prefix") + 1]
    elif resto[0] == "maximum-prefix" and len(resto) >= 2:
        reg["maximum_prefix"] = int(resto[1])
        if len(resto) >= 3:
            reg["maximum_prefix_threshold"] = int(resto[2])
    elif resto[:2] == ["bfd", "enable"]:
        reg["bfd"] = True
    elif resto[0] == "graceful-restart":
        reg["graceful_restart"] = True
    elif resto[0] == "shutdown":
        reg["shutdown"] = True
    elif resto[0] == "enable":
        reg["habilitado"] = True


def _par_v4(partes: list[str]) -> tuple[str, str] | None:
    """O par `<endereço> <máscara>` de uma linha `ip address`.

    O `sub` do endereço secundário vem depois e fica de fora. Linha que não é
    par de endereço (`ip address unnumbered interface LoopBack0`, por exemplo)
    devolve `None`: ela existe na configuração e não é endereço desta interface.
    """
    if len(partes) < 4:
        return None
    endereco, mascara = partes[2], partes[3]
    try:
        ipaddress.IPv4Address(endereco)
        ipaddress.IPv4Network(f"0.0.0.0/{mascara}")  # a máscara é decimal pontuada
    except ValueError:
        return None
    return endereco, mascara


def _par_v6(partes: list[str]) -> tuple[str, int] | None:
    """O par `<endereço> <comprimento>` de uma linha `ipv6 address`.

    O VRP aceita as duas grafias — `<endereço> <comprimento>` e
    `<endereço>/<comprimento>` — e a captura pode trazer qualquer uma delas, então
    as duas são lidas. As demais formas (`ipv6 address auto link-local`,
    `eui-64`) não são par de endereço e devolvem `None`.
    """
    if len(partes) < 3:
        return None
    texto = partes[2]
    if "/" in texto:
        endereco, _, comprimento = texto.partition("/")
    elif len(partes) >= 4:
        endereco, comprimento = texto, partes[3]
    else:
        return None
    try:
        ipaddress.IPv6Address(endereco)
        comprimento_v6 = int(comprimento)
    except ValueError:
        return None
    if not 0 <= comprimento_v6 <= 128:
        return None
    return endereco, comprimento_v6


def _aplica_sub(reg: dict, linha: str) -> None:
    if linha.startswith("vlan-type dot1q "):
        reg["vid"] = int(linha.split()[-1])
        # QinQ: o TPID externo 0x88a8 é o que separa a linha empilhada da
        # simples (`vlan-type dot1q 0x88a8 vid <vid>`, o que o render emite).
        reg["qinq"] = "0x88a8" in linha.split()
    elif linha.startswith("vlan-type qinq "):
        reg["vid"] = int(linha.split()[-1])
        reg["qinq"] = True
    elif linha.startswith("description "):
        reg["descricao"] = linha.split(" ", 1)[1].strip()
    elif linha.startswith("mtu "):
        reg["mtu"] = int(linha.split()[1])
    elif linha.startswith("ip address ") and not linha.startswith("ip address 0.0.0.0"):
        par = _par_v4(linha.split())
        if par is not None:
            reg["v4"].append(par)
    elif linha.startswith("ipv6 address "):
        par_v6 = _par_v6(linha.split())
        if par_v6 is not None:
            reg["v6"].append(par_v6)


def _monta_sub(reg: dict) -> Subinterface:
    return Subinterface(
        nome=reg["nome"], vid=reg["vid"], qinq=reg["qinq"], descricao=reg["descricao"],
        mtu=reg["mtu"], enderecos_v4=tuple(reg["v4"]), enderecos_v6=tuple(reg["v6"]),
    )


def _monta_peer(reg: dict) -> PeerConfig:
    return PeerConfig(**reg)


def parse_config_vrp(texto: str) -> ConfigVrp:
    """Leem a configuração inteira e devolve peers e subinterfaces tipados.

    Regras de contexto: linha sem indentação abre bloco novo; dentro de
    `interface`, as linhas indentadas são sub-comandos; dentro de `bgp`, uma
    seção `ipvN-family unicast` traz os ajustes por família da instância pública
    e uma seção `ipvN-family vpn-instance <nome>` traz os peers daquela VRF.
    """
    peers: dict[tuple[str, str | None], dict] = {}
    subs: list[Subinterface] = []
    asn_bloco: int | None = None
    vrf_atual: str | None = None
    iface: dict | None = None

    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha == "#":
            continue
        indentado = bruta[:1] in (" ", "\t")

        if not indentado:
            if iface is not None:
                subs.append(_monta_sub(iface))
                iface = None
            asn_bloco = None
            vrf_atual = None
            if linha.startswith("interface "):
                iface = {"nome": linha.split(" ", 1)[1], "vid": None, "qinq": False,
                         "descricao": None, "mtu": None, "v4": [], "v6": []}
            elif linha.startswith("bgp "):
                asn_bloco = int(linha.split(" ", 1)[1].split()[0])
            continue

        if iface is not None:
            _aplica_sub(iface, linha)
            continue
        if asn_bloco is None:
            continue

        if linha.startswith(("ipv4-family vpn-instance ", "ipv6-family vpn-instance ")):
            vrf_atual = linha.split(" ", 2)[2].strip()
            continue
        if linha.endswith("-family unicast"):
            vrf_atual = None
            continue
        if linha.startswith("peer "):
            _, endereco, *resto = linha.split()
            try:
                ipaddress.ip_address(endereco)
            except ValueError:
                continue  # `peer <nome-de-grupo>` não é endereço: fora do escopo
            reg = peers.setdefault((endereco, vrf_atual), _novo_peer(endereco, vrf_atual, asn_bloco))
            _aplica_peer(reg, resto, linha)

    if iface is not None:
        subs.append(_monta_sub(iface))
    return ConfigVrp(peers=tuple(_monta_peer(r) for r in peers.values()), subinterfaces=tuple(subs))
