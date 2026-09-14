"""Merge of parsed TextFSM rows per collection resource (spec §4.3 shape).

Parsers return strings only (contract); this module normalizes types, drops
VRP emptiness sentinels and combines the commands of one resource into the
structured `device_snapshots.resources` shape. Interface name (canonical, i.e.
without the cosmetic speed suffix) is the merge key between the three
interface-brief commands.
"""
import re

_SUFIXO_VELOCIDADE = re.compile(r"\(\d+(?:[GM])?\)$")
_SEM_ENDERECO_V4 = ("unassigned",)
_SEM_ENDERECO_V6 = ("Unassigned", "")


def _afi_de_comando(comando: str) -> str:
    """afi comes from the command (spec §3.9): `display bgp peer` is IPv4 and the
    ipv6 variants carry the word."""
    return "ipv6" if "ipv6" in comando else "ipv4"


def _nome_canonico(nome: str) -> str:
    """Interface name without the cosmetic speed suffix (`GE0/1/0.1003(10G)` ->
    `GE0/1/0.1003`); the ipv6 brief omits the suffix the interface brief shows."""
    return _SUFIXO_VELOCIDADE.sub("", nome)


def merge_interfaces(por_comando: dict[str, list[dict]]) -> list[dict]:
    """Combine interface brief, ip interface brief and ipv6 interface brief.

    phy/protocolo come from the first source in dict order (the collector sends
    interface brief first, then ip, then ipv6). `vpn` `--` becomes None; named
    VRFs are kept. Addresses drop the VRP emptiness sentinels (unassigned /
    Unassigned / the EOF-flush phantom row with endereco_v6 == "").
    Output sorted by canonical name, keys exactly:
    {nome, phy, protocolo, enderecos_v4, enderecos_v6, vpn}.
    """
    merged: dict[str, dict] = {}
    for linhas in por_comando.values():
        for linha in linhas:
            nome = _nome_canonico(linha["nome"])
            registro = merged.setdefault(
                nome,
                {"nome": nome, "phy": None, "protocolo": None,
                 "enderecos_v4": [], "enderecos_v6": [], "vpn": None},
            )
            if registro["phy"] is None:
                registro["phy"] = linha["phy"]
                registro["protocolo"] = linha["protocolo"]
            if "vpn" in linha and registro["vpn"] is None:
                registro["vpn"] = None if linha["vpn"] == "--" else linha["vpn"]
            if "endereco" in linha and linha["endereco"] not in _SEM_ENDERECO_V4:
                registro["enderecos_v4"].append(linha["endereco"])
            if "endereco_v6" in linha and linha["endereco_v6"] not in _SEM_ENDERECO_V6:
                registro["enderecos_v6"].append(linha["endereco_v6"])
    return [merged[k] for k in sorted(merged)]


def merge_bgp_peers(por_comando: dict[str, list[dict]]) -> list[dict]:
    """Combine the v4 and v6 peer tables into one list with afi and typed values.

    Order: commands in dict order (v4 before v6 in the collector), rows in table
    order. Keys: {afi, peer, asn, estado, pref_rcv, up_down} with asn cast to
    int and pref_rcv to int when numeric ("-" do VRP vira None).
    """
    return [
        {
            "afi": _afi_de_comando(comando),
            "peer": linha["peer"],
            "asn": int(linha["asn"]),
            "estado": linha["estado"],
            "pref_rcv": None if linha["pref_rcv"] == "-" else int(linha["pref_rcv"]),
            "up_down": linha["up_down"],
        }
        for comando, linhas in por_comando.items()
        for linha in linhas
    ]


def merge_bgp_peers_detalhes(por_comando: dict[str, list[dict]]) -> list[dict]:
    """Verbose rows (one command per peer) -> details with None for missing fields.

    Keys: {afi, peer, descricao, filtro_import, filtro_export}; descricao and
    filters are None when absent from the output.
    """
    return [
        {
            "afi": _afi_de_comando(comando),
            "peer": linha["peer"],
            "descricao": linha["descricao"] or None,
            "filtro_import": linha["filtro_import"] or None,
            "filtro_export": linha["filtro_export"] or None,
        }
        for comando, linhas in por_comando.items()
        for linha in linhas
    ]


def _primeiras_linhas(por_comando: dict[str, list[dict]]) -> list[dict]:
    """Um comando por recurso nos coletores MPLS: a única fonte do dict é a linha."""
    return next(iter(por_comando.values())) if por_comando else []


def normaliza_ldp(por_comando: dict[str, list[dict]]) -> list[dict]:
    """`display mpls ldp peer` + `display mpls ldp session` -> peers com estado.

    A tabela de peer da família S não imprime estado; ele vem da tabela de sessão
    (`Operational` = up). Peer listado pelo comando de peer sem linha na sessão
    fica `estado=None` (desconhecido) — nunca "down" por omissão. Quando o próprio
    comando de peer imprime estado (outras famílias), ele é o fallback. O sufixo
    `:0` do LDP ID sai dos dois lados. Keys: {peer_id, estado}; linhas sem
    peer_id são descartadas.
    """
    peers = por_comando.get("display mpls ldp peer")
    if peers is None:
        peers = _primeiras_linhas(por_comando)
    estados: dict[str, str | None] = {}
    for linha in por_comando.get("display mpls ldp session", []):
        peer = str(linha.get("peer_id", "")).split(":")[0].strip()
        if peer and linha.get("status"):
            estados[peer] = (
                "up" if str(linha["status"]).strip().lower() == "operational" else "down"
            )
    saida: list[dict] = []
    for linha in peers:
        peer = str(linha.get("peer_id", "")).split(":")[0].strip()
        if not peer:
            continue
        if peer in estados:
            estado: str | None = estados[peer]
        else:
            estado = {"up": "up", "down": "down"}.get(str(linha.get("estado") or "").lower())
        saida.append({"peer_id": peer, "estado": estado})
    return saida


def normaliza_l2vc(por_comando: dict[str, list[dict]]) -> list[dict]:
    """`display l2vc` -> vc_id int, interface, estado e os campos do §13.2.

    Keys: {vc_id, interface, estado, ac_status, mtu_local, mtu_remoto}; campo
    ausente no bloco vira None (não inventa valor) e linha sem vc_id é
    descartada. O MTU é int quando impresso (o VRP imprime `0` em VC down).
    """
    def _int(valor: object) -> int | None:
        return int(valor) if valor not in (None, "") else None

    saida: list[dict] = []
    for linha in _primeiras_linhas(por_comando):
        # `vc_id` vazio (não None) é o sentinel do TextFSM para valor não casado:
        # com o Record na linha do MTU, um bloco sem `VC ID` chega aqui em `''`.
        vc = linha.get("vc_id")
        if not vc:
            continue
        saida.append({
            "vc_id": int(vc),
            "interface": linha.get("interface"),
            "estado": "up" if str(linha.get("estado", "")).lower() == "up" else "down",
            "ac_status": linha.get("ac_status") or None,
            "mtu_local": _int(linha.get("mtu_local")),
            "mtu_remoto": _int(linha.get("mtu_remoto")),
        })
    return saida


def normaliza_vsi(por_comando: dict[str, list[dict]]) -> list[dict]:
    """`display vsi verbose` -> um dict por VSI com peers e ACs (§9.3).

    O parse devolve uma linha por nível (VSI, peer, AC); o `name` é o único
    valor preenchido ao longo do bloco e por isso é a chave do agrupamento. O
    `vsi_id` vem da linha do próprio VSI: grupo sem ID (bloco truncado, como o
    `VLAN653_INTECH]` da rede real) é descartado inteiro, e com ele o AC que
    porventura viesse depois, que não pode ser atribuído ao VSI anterior.

    Keys: {name, vsi_id, estado, mtu, peers, acs}; `estado` desconhecido vira
    None (nunca "down" por omissão) e campo ausente não inventa valor.
    """
    grupos: dict[str, dict] = {}
    for linha in _primeiras_linhas(por_comando):
        nome = linha.get("name")
        if not nome:
            continue
        grupo = grupos.setdefault(nome, {
            "name": nome, "vsi_id": None, "estado": None, "mtu": None,
            "peers": [], "acs": [],
        })
        if linha.get("vsi_id"):
            grupo["vsi_id"] = int(linha["vsi_id"])
            grupo["estado"] = (
                {"up": "up", "down": "down"}.get(str(linha.get("estado") or "").lower())
            )
            grupo["mtu"] = int(linha["mtu"]) if linha.get("mtu") else None
        if linha.get("peer"):
            grupo["peers"].append({
                "peer": linha["peer"],
                "estado": (
                    {"up": "up", "down": "down"}.get(
                        str(linha.get("peer_estado") or "").lower()
                    )
                ),
            })
        if linha.get("ac_if"):
            grupo["acs"].append({
                "interface": linha["ac_if"],
                "estado": (
                    {"up": "up", "down": "down"}.get(
                        str(linha.get("ac_estado") or "").lower()
                    )
                ),
            })
    return [g for g in grupos.values() if g["vsi_id"] is not None]


_MERGES = {
    "interfaces": merge_interfaces,
    "bgp_peers": merge_bgp_peers,
    "bgp_peers_detalhes": merge_bgp_peers_detalhes,
    "mpls_ldp_peer": normaliza_ldp,
    "l2vc": normaliza_l2vc,
    "vsi": normaliza_vsi,
}


def merge_parsed(nome: str, por_comando: dict[str, list[dict]]) -> list[dict]:
    """Dispatch the merge by the resource name declared in the collector spec."""
    if nome not in _MERGES:
        raise KeyError(f"Merge desconhecido: {nome!r}")
    return _MERGES[nome](por_comando)
