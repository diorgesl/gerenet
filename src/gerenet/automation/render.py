"""Render da intenção em comandos VRP (spec ciclo B §5.2).

Orquestrador puro: decide QUAIS blocos (com quais nomes §25.4) por device e
delega o texto ao template Jinja2 atômico correspondente. Render é idempotente
por construção: deriva sempre do Source of Truth.
"""
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import naming
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.ipam import pontas_v4, pontas_v6
from gerenet.domain.services.policy_profiles import get_policy_profile
from gerenet.domain.services.prefix_authorizations import list_authorizations

TEMPLATES_DIR = Path(__file__).parent / "templates" / "huawei_vrp"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)

TIPO_ORDEM = {
    "subinterface": 10,
    "prefix_list": 20,
    "route_policy_import": 30,
    "route_policy_export": 40,
    "bgp_peer": 50,
    "comentario": 60,
}


def _render_template(nome: str, contexto: dict) -> str:
    """Renderiza o template `nome` (sem sufixo) com `contexto`; sem `\n` final."""
    return _env.get_template(nome + ".j2").render(**contexto).rstrip("\n")


@dataclass
class BlocoRender:
    """Bloco de comandos VRP anotado com o objeto SoT que o originou (ciclo C)."""

    tipo: str
    objeto: str  # "circuit" | "session"
    objeto_id: int
    comandos: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n".join(self.comandos)


@dataclass
class RenderResult:
    device_id: int
    blocos: list[BlocoRender]
    texto: str


def _reserva(session: Session, circuito: models.Circuit) -> dict[str, dict]:
    """Endereços locais da reserva do circuito por família.

    Devolve {"ipv4": {"vid", "endereco", "mascara"}, "ipv6": {"vid", "endereco"}}
    das pontas LOCAIS (IPAM §25.8). VLAN family None (unica) serve às duas
    famílias. O /len deriva do CIDR reservado (o IPAM respeita
    circuit.p2p_v4_len).

    Em stack=ipv6 o IpPrefix v4 nunca vira endereço de interface (Ruling 3):
    o ipam cria a linha apenas para derivar o sufixo do /126 (§25.8, notes
    "Par v4 interno …"), e o guard `circuito.stack != "ipv6"` espelha
    exatamente a condição em que essa linha existe — sem o guard, a
    subinterface IPv6-only receberia um `ip address` do par interno.
    """
    vlans = list(session.scalars(
        select(models.Vlan).where(models.Vlan.circuit_id == circuito.id).order_by(models.Vlan.vid)
    ))
    prefixos = list(session.scalars(
        select(models.IpPrefix).where(models.IpPrefix.circuit_id == circuito.id)
    ))
    por_versao: dict[int, str] = {
        ipaddress.ip_network(p.network).version: p.network for p in prefixos
    }
    local_v4: tuple[str, str] | None = None
    local_v6: str | None = None
    if 4 in por_versao and circuito.stack != "ipv6":
        rede = ipaddress.ip_network(por_versao[4])
        ponta_local, _ = pontas_v4(por_versao[4])
        local_v4 = (ponta_local, str(rede.netmask))
    if 6 in por_versao:
        local_v6 = pontas_v6(por_versao[6])[0]  # "address/126" (ponta local)

    familias: dict[str | None, int] = {}
    for vlan in vlans:
        for fam in [None] if vlan.family is None else [vlan.family]:
            familias.setdefault(fam, vlan.vid)

    saida: dict[str, dict] = {}
    for fam, vid in familias.items():
        if fam is None:
            if local_v4 is not None:
                saida["ipv4"] = {"vid": vid, "endereco": local_v4[0], "mascara": local_v4[1]}
            if local_v6 is not None:
                saida["ipv6"] = {"vid": vid, "endereco": local_v6}
        elif fam == "ipv4" and local_v4 is not None:
            saida["ipv4"] = {"vid": vid, "endereco": local_v4[0], "mascara": local_v4[1]}
        elif fam == "ipv6" and local_v6 is not None:
            saida["ipv6"] = {"vid": vid, "endereco": local_v6}
    return saida


def _comandos_sub(
    trunk: str, vid: int, qinq: bool, *, v4: dict | None, v6: str | None
) -> list[str]:
    """Linhas de comando da subinterface (description só via session no B — §5.1)."""
    contexto: dict = {
        "interface": naming.subinterface(trunk, vid),
        "descricao": None,
        "qinq": qinq,
        "vid": vid,
        "enderecos_v4": [v4] if v4 else [],
        "enderecos_v6": [v6] if v6 else [],
    }
    return _render_template("subinterface", contexto).splitlines()


def _bloco_sub(session: Session, circuito: models.Circuit, device_id: int) -> list[BlocoRender]:
    """Blocos de subinterface do circuito (unica: 1; separada: 1 por família).

    Só quando o device é o edge (ou backup) do circuito, com edge_trunk e
    reserva (ruling 3). Sem esses pré-requisitos, devolve lista vazia — a
    divergência acusa circuito.sem_trunk quando só falta o trunk.
    """
    if circuito.edge_device_id != device_id and circuito.backup_edge_device_id != device_id:
        return []
    if not circuito.edge_trunk:
        return []
    fams = _reserva(session, circuito)
    if not fams:
        return []
    if circuito.vlan_mode == "unica":
        vid = fams["ipv4"]["vid"] if "ipv4" in fams else fams["ipv6"]["vid"]
        comandos = _comandos_sub(
            circuito.edge_trunk, vid, circuito.qinq,
            v4=fams.get("ipv4"), v6=fams.get("ipv6", {}).get("endereco"),
        )
        return [BlocoRender("subinterface", "circuit", circuito.id, comandos)]
    blocos: list[BlocoRender] = []
    for fam in ("ipv4", "ipv6"):
        if fam not in fams:
            continue
        comandos = _comandos_sub(
            circuito.edge_trunk, fams[fam]["vid"], circuito.qinq,
            v4=fams[fam] if fam == "ipv4" else None,
            v6=fams[fam]["endereco"] if fam == "ipv6" else None,
        )
        blocos.append(BlocoRender("subinterface", "circuit", circuito.id, comandos))
    return blocos


def _apensa_definicao(
    blocos: list[BlocoRender],
    definidas: dict[tuple[str, str], set[str]],
    bloco: BlocoRender,
    chave: tuple[str, str],
) -> None:
    """Dedup de blocos de DEFINIÇÃO (prefix-list / route-policy) por (tipo, nome).

    Registra os TEXTOS já apensados por chave: texto já visto para a chave ⇒
    emite 1× (fica o 1º bloco, com o objeto_id da 1ª sessão); texto NOVO para
    a chave ⇒ apensa — mesmo nome com textos divergentes convive no render
    (dívida §25.4/§25.5, ciclo C) e a comparação de conteúdo da T5 acusa a
    maioria. Comparar com TODOS os textos (set) evita emitir o mesmo texto
    2× quando três sessões produzem A, B, B: o B apensa uma vez e a segunda
    ocorrência é reconhecida. O dedup poupa só a DEFINICAO — a referência no
    peer vem do critério de definição de _bloco_import/_bloco_export (R5).
    """
    textos = definidas.setdefault(chave, set())
    if bloco.texto in textos:
        return
    textos.add(bloco.texto)
    blocos.append(bloco)


def _bloco_import(
    session: Session, circuito: models.Circuit, sessao: models.BgpSession,
    definidas: dict[tuple[str, str], set[str]],
) -> tuple[list[BlocoRender], str | None]:
    """Prefix-list + RP de importação a partir das autorizações da org (§6.4).

    Só quando há autorização ativa da família; sem autorização, a sessão não
    tem filtro de importação para renderizar (ruling 4). Devolve também o
    nome da RP (§25.4 — sempre estável para ASN+AFI) quando a definição
    EXISTE para a sessão, mesmo que o bloco não seja apensado (dedup): o
    peer referencia a RP pela existência da definição, não pelo estado do
    dedup (ruling R5).
    """
    autorizadas = [
        a for a in list_authorizations(session, organization_id=circuito.organization_id)
        if a.family == sessao.afi
    ]
    if not autorizadas:
        return [], None
    afi = sessao.afi
    asn_par = sessao.asn_remote
    nome_pfx = naming.pfx_in(asn_par, afi)
    nome_rp = naming.rp_import(asn_par, afi)
    entradas: list[dict] = []
    if sessao.allow_default_route:
        entradas.append({"index": 5, "prefixo": "0.0.0.0/0" if afi == "ipv4" else "::/0"})
    entradas += [
        {"index": 10 * (i + 1), "prefixo": a.prefix} for i, a in enumerate(autorizadas)
    ]
    comandos = _render_template(
        "prefix_list", {"nome": nome_pfx, "afi": afi, "entradas": entradas}
    ).splitlines()
    blocos: list[BlocoRender] = []
    _apensa_definicao(
        blocos, definidas,
        BlocoRender("prefix_list", "session", sessao.id, comandos),
        ("prefix_list", nome_pfx),
    )
    comandos = _render_template(
        "route_policy_import",
        {"nome": nome_rp, "afi": afi, "lista": nome_pfx, "local_preference": sessao.local_preference},
    ).splitlines()
    _apensa_definicao(
        blocos, definidas,
        BlocoRender("route_policy_import", "session", sessao.id, comandos),
        ("route_policy_import", nome_rp),
    )
    return blocos, nome_rp


def _bloco_rp_export(sessao: models.BgpSession, nome_rp: str, afi: str, lista: str | None) -> BlocoRender:
    comandos = _render_template(
        "route_policy_export",
        {
            "nome": nome_rp, "afi": afi, "lista": lista,
            "med": sessao.med, "prepend": sessao.prepend or 0,
            "asn_local": sessao.asn_local,
        },
    ).splitlines()
    return BlocoRender("route_policy_export", "session", sessao.id, comandos)


def _bloco_divida(texto: str) -> BlocoRender:
    """Comentário ao operador (sem comando executável) — ruling 13."""
    return BlocoRender("comentario", "session", 0, [f"# {texto}"])


def _bloco_export(
    session: Session, sessao: models.BgpSession,
    definidas: dict[tuple[str, str], set[str]],
) -> tuple[list[BlocoRender], str | None]:
    """RP de exportação pelo produto §6.5/§25.5 (ruling 5); dívidas viram comentário.

    Prefix-list/RP de exportação passam pelo dedup de definições (texto já
    visto ⇒ 1 bloco; divergente ⇒ convivem, dívida §25.4/§25.5 ciclo C).
    Devolve também o nome da RP (§25.4) quando a definição EXISTE para a
    sessão (produto renderizável: full / default / cdn|personalizado com
    prefixos) — o peer referencia pelo critério de definição, independente
    do dedup (ruling R5); dívida (comentário) não gera referência.
    """
    if sessao.export_profile_id is None:
        return [], None
    perfil = get_policy_profile(session, sessao.export_profile_id)
    afi = sessao.afi
    nome_rp = naming.rp_export(sessao.asn_remote, afi)
    produto = perfil.name
    if produto == "full":
        blocos: list[BlocoRender] = []
        _apensa_definicao(
            blocos, definidas, _bloco_rp_export(sessao, nome_rp, afi, None),
            ("route_policy_export", nome_rp),
        )
        return blocos, nome_rp
    if produto == "default":
        lista = naming.pfx_produto("default", afi)
        prefixo = "0.0.0.0/0" if afi == "ipv4" else "::/0"
        comandos = _render_template(
            "prefix_list", {"nome": lista, "afi": afi, "entradas": [{"index": 10, "prefixo": prefixo}]}
        ).splitlines()
        blocos = []
        _apensa_definicao(
            blocos, definidas,
            BlocoRender("prefix_list", "session", sessao.id, comandos),
            ("prefix_list", lista),
        )
        _apensa_definicao(
            blocos, definidas, _bloco_rp_export(sessao, nome_rp, afi, lista),
            ("route_policy_export", nome_rp),
        )
        return blocos, nome_rp
    if produto in ("cdn", "personalizado"):
        if not perfil.prefixes:
            return [_bloco_divida(
                f"produto '{produto}': sem prefixos cadastrados para montar a lista de anúncio."
            )], None
        lista = naming.pfx_produto(produto, afi)
        entradas = [
            {"index": 10 * (i + 1), "prefixo": p} for i, p in enumerate(perfil.prefixes)
        ]
        comandos = _render_template(
            "prefix_list", {"nome": lista, "afi": afi, "entradas": entradas}
        ).splitlines()
        blocos = []
        _apensa_definicao(
            blocos, definidas,
            BlocoRender("prefix_list", "session", sessao.id, comandos),
            ("prefix_list", lista),
        )
        _apensa_definicao(
            blocos, definidas, _bloco_rp_export(sessao, nome_rp, afi, lista),
            ("route_policy_export", nome_rp),
        )
        return blocos, nome_rp
    # default_internas / parcial — dívida documentada (sem definição de RP)
    return [_bloco_divida(
        f"produto '{produto}': rotas internas ainda não renderizáveis (ciclo C/F5)."
    )], None


def _bloco_peer(sessao: models.BgpSession, rp_import: str | None, rp_export: str | None) -> BlocoRender:
    comandos = _render_template(
        "bgp_peer",
        {
            "asn_local": sessao.asn_local,
            "peer": sessao.remote_address,
            "asn_remote": sessao.asn_remote,
            "descricao": sessao.description,
            "has_password": sessao.has_password,
            "password_path": sessao.password_ref,
            "keepalive": sessao.keepalive if sessao.keepalive and sessao.holdtime else None,
            "holdtime": sessao.holdtime if sessao.keepalive and sessao.holdtime else None,
            "graceful_restart": sessao.graceful_restart,
            "bfd_enabled": sessao.bfd_enabled,
            "shutdown": sessao.shutdown,
            "afi": sessao.afi,
            "rp_import": rp_import,
            "rp_export": rp_export,
            "maximum_prefix": sessao.maximum_prefix,
            "maximum_prefix_threshold": sessao.maximum_prefix_threshold,
        },
    ).splitlines()
    return BlocoRender("bgp_peer", "session", sessao.id, comandos)


def internas_prefixos(session: Session) -> dict[str, list[str]]:
    """Prefixos próprios (rotas internas): loopbacks + enlaces p2p alocados ativos.

    Loopback de device ADMIN ATIVO vira /32 (v4) ou /128 (v6); p2p alocados
    (kind p2p, status reservada) entram pela rede CIDR como armazenada.
    Devolve {"ipv4": [...], "ipv6": [...]} ordenado e sem duplicatas.
    """
    saida: dict[str, list[str]] = {"ipv4": [], "ipv6": []}
    for dev in session.scalars(select(models.Device).where(models.Device.admin_status.is_(True))):
        if not dev.loopback:
            continue
        ip = ipaddress.ip_address(dev.loopback)
        afi = "ipv4" if ip.version == 4 else "ipv6"
        prefixo = f"{dev.loopback}/{'32' if ip.version == 4 else '128'}"
        saida[afi].append(str(ipaddress.ip_network(prefixo, strict=False)))
    for ip in session.scalars(
        select(models.IpPrefix).where(
            models.IpPrefix.kind == "p2p", models.IpPrefix.status == "reservada")
    ):
        rede = ipaddress.ip_network(ip.network)
        saida["ipv4" if rede.version == 4 else "ipv6"].append(str(rede))
    for afi, prefixos in saida.items():  # ordena e normaliza (sem dups)
        saida[afi] = sorted(set(prefixos))
    return saida


def render_desejado(session: Session, device_id: int) -> RenderResult:
    """Blocos VRP desejados do device (sessões ativas; §5.2). Idempotente."""
    device = get_device(session, device_id)
    circuitos: dict[int, models.Circuit] = {}
    for sessao in list_sessions(session, device_id=device_id):
        if sessao.circuit_id not in circuitos:
            circ = session.get(models.Circuit, sessao.circuit_id)
            if circ is not None:
                circuitos[sessao.circuit_id] = circ

    blocos: list[BlocoRender] = []
    definidas: dict[tuple[str, str], set[str]] = {}
    for circ_id in sorted(circuitos):
        circuito = circuitos[circ_id]
        blocos.extend(_bloco_sub(session, circuito, device_id))
        for sessao in sorted(
            list_sessions(session, circuit_id=circ_id, device_id=device_id),
            key=lambda s: (s.afi, s.remote_address),
        ):
            # As referências do peer vêm do critério de definição (nome §25.4),
            # NUNCA do que sobrou dos blocos: com dedup, a 2ª sessão da mesma
            # definição não apensa bloco, mas a referência continua (Ruling R5).
            import_blocos, rp_import = _bloco_import(session, circuito, sessao, definidas)
            export_blocos, rp_export = _bloco_export(session, sessao, definidas)
            blocos.extend(import_blocos)
            blocos.extend(export_blocos)
            blocos.append(_bloco_peer(sessao, rp_import, rp_export))
    blocos.sort(key=lambda b: TIPO_ORDEM[b.tipo])  # estável: preserva ordem intra-tipo
    texto = "\n".join(b.texto for b in blocos)
    return RenderResult(device_id=device.id, blocos=blocos, texto=texto)
