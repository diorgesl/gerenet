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
causa de uma linha (`ip address unnumbered ...`) seria pior do que ignorá-la. O
que a leitura não entendeu (seção de família fora do escopo, valor que não
converte, captura sem bloco `bgp`) sai em `ConfigVrp.avisos`, para "não entendi o
formato" não ficar idêntico a "o equipamento não tem peer".
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
    # O que a leitura não entendeu. Sem isso, uma captura em formato
    # desconhecido devolve zero peers igual a um equipamento sem BGP.
    avisos: tuple[str, ...] = ()


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


def _int_tolerante(valor: str, avisos: list[str], linha: str) -> int | None:
    """Converte o número de uma linha da configuração.

    Configuração real traz linha que este parser não modela, e um número que não
    converte derruba a leitura da captura inteira. O valor ruim vira aviso e o
    campo fica como estava, em vez de a captura se perder.
    """
    try:
        return int(valor)
    except ValueError:
        avisos.append(f"valor não numérico em `{linha}`: {valor!r}")
        return None


def _aplica_peer(reg: dict, resto: list[str], linha: str, avisos: list[str]) -> None:
    """Aplica uma linha `peer <endereço> ...` ao registro acumulado."""
    if not resto:
        return
    if resto[0] == "as-number" and len(resto) >= 2:
        asn_remoto = _int_tolerante(resto[1], avisos, linha)
        if asn_remoto is not None:
            reg["asn_remote"] = asn_remoto
    elif resto[0] == "description":
        reg["descricao"] = linha.split("description", 1)[1].strip()
    elif resto[0] == "password":
        # O valor (cipher) não é lido: só a presença interessa (§19).
        reg["tem_password"] = True
    elif resto[:2] == ["timer", "keepalive"] and len(resto) >= 3:
        keepalive = _int_tolerante(resto[2], avisos, linha)
        if keepalive is not None:
            reg["keepalive"] = keepalive
        if "hold" in resto and resto.index("hold") + 1 < len(resto):
            holdtime = _int_tolerante(resto[resto.index("hold") + 1], avisos, linha)
            if holdtime is not None:
                reg["holdtime"] = holdtime
    elif "route-policy" in resto and resto.index("route-policy") + 1 < len(resto):
        nome = resto[resto.index("route-policy") + 1]
        if "export" in resto:
            reg["export_route_policy"] = nome
        else:
            reg["import_route_policy"] = nome
    elif "ip-prefix" in resto and resto.index("ip-prefix") + 1 < len(resto):
        reg["import_prefix_list"] = resto[resto.index("ip-prefix") + 1]
    elif resto[0] == "maximum-prefix" and len(resto) >= 2:
        maximo = _int_tolerante(resto[1], avisos, linha)
        if maximo is not None:
            reg["maximum_prefix"] = maximo
        if len(resto) >= 3:
            limiar = _int_tolerante(resto[2], avisos, linha)
            if limiar is not None:
                reg["maximum_prefix_threshold"] = limiar
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


def _vid_da_linha(partes: list[str], chave: str, linha: str, avisos: list[str]) -> int | None:
    """O VID de uma linha `vlan-type`, o primeiro número depois da chave.

    À frente do VID pode vir o TPID externo do QinQ (`0x88a8`) e, depois dele, o
    `second-dot1q`: o último número da linha seria justamente o CE-VLAN interno,
    que não é a VLAN da subinterface. Sem número depois da chave, a linha vira
    aviso e o VID fica de fora.
    """
    if chave in partes:
        for token in partes[partes.index(chave) + 1:]:
            try:
                return int(token)
            except ValueError:
                continue
    avisos.append(f"VID não reconhecido em `{linha}`")
    return None


def _aplica_sub(reg: dict, linha: str, avisos: list[str]) -> None:
    partes = linha.split()
    if linha.startswith("vlan-type dot1q "):
        reg["vid"] = _vid_da_linha(partes, "dot1q", linha, avisos)
        # QinQ: o TPID externo 0x88a8 é o que separa a linha empilhada da
        # simples (`vlan-type dot1q 0x88a8 vid <vid>`, o que o render emite).
        reg["qinq"] = "0x88a8" in partes
    elif linha.startswith("vlan-type qinq "):
        reg["vid"] = _vid_da_linha(partes, "qinq", linha, avisos)
        reg["qinq"] = True
    elif linha.startswith("description "):
        reg["descricao"] = linha.split(" ", 1)[1].strip()
    elif linha.startswith("mtu "):
        mtu = _int_tolerante(partes[1], avisos, linha)
        if mtu is not None:
            reg["mtu"] = mtu
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
    """Lê a configuração inteira e devolve peers e subinterfaces tipados.

    Regras de contexto: linha sem indentação abre bloco novo; dentro de
    `interface`, as linhas indentadas são sub-comandos; dentro de `bgp`, uma
    seção `ipvN-family unicast` traz os ajustes por família da instância pública
    e uma seção `ipvN-family vpn-instance <nome>` traz os peers daquela VRF.

    Seção de família que não seja nenhuma dessas duas (`multicast`, `vpnv4`...)
    não tem os peers lidos: eles iriam para a VRF anterior ou sobrescreveriam o
    registro da instância pública, e o cabeçalho fica registrado em `avisos`.
    """
    peers: dict[tuple[str, str | None], dict] = {}
    subs: list[Subinterface] = []
    avisos: list[str] = []
    asn_bloco: int | None = None
    vrf_atual: str | None = None
    secao_desconhecida = False
    viu_bgp = False
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
            secao_desconhecida = False
            if linha.startswith("interface "):
                iface = {"nome": linha.split(" ", 1)[1], "vid": None, "qinq": False,
                         "descricao": None, "mtu": None, "v4": [], "v6": []}
            elif linha.startswith("bgp "):
                viu_bgp = True
                asn_bloco = _int_tolerante(linha.split(" ", 1)[1].split()[0], avisos, linha)
            continue

        if iface is not None:
            _aplica_sub(iface, linha, avisos)
            continue
        if asn_bloco is None:
            continue

        if linha.split()[0].endswith("-family"):
            if linha.startswith(("ipv4-family vpn-instance ", "ipv6-family vpn-instance ")):
                vrf_atual = linha.split(" ", 2)[2].strip()
                secao_desconhecida = False
            elif linha.startswith(("ipv4-family ", "ipv6-family ")) and linha.endswith(" unicast"):
                vrf_atual = None
                secao_desconhecida = False
            else:
                # `ipv4-family multicast`, `l2vpn-family evpn`, `vpnv4`...: os
                # peers daqui não são sessão desta instância, e atribuí-los à
                # VRF anterior (ou ao registro público) seria inventar.
                vrf_atual = None
                secao_desconhecida = True
                avisos.append(f"seção de família não reconhecida, peers ignorados: `{linha}`")
            continue

        if secao_desconhecida:
            continue
        if linha.startswith("peer "):
            _, endereco, *resto = linha.split()
            try:
                ipaddress.ip_address(endereco)
            except ValueError:
                continue  # `peer <nome-de-grupo>` não é endereço: fora do escopo
            reg = peers.setdefault((endereco, vrf_atual), _novo_peer(endereco, vrf_atual, asn_bloco))
            _aplica_peer(reg, resto, linha, avisos)

    if iface is not None:
        subs.append(_monta_sub(iface))
    if texto and not viu_bgp:
        avisos.append(
            "nenhum bloco `bgp` encontrado: confira se a captura é o "
            "`display current-configuration` inteiro"
        )
    return ConfigVrp(
        peers=tuple(_monta_peer(r) for r in peers.values()),
        subinterfaces=tuple(subs),
        avisos=tuple(avisos),
    )
