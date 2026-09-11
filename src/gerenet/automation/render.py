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
from gerenet.domain.services.upstream_communities import list_upstream_communities
from gerenet.domain.services.upstreams import upstream_do_circuito

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
    "as_path_filter": 22,
    "community_filter": 25,
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
        select(models.Vlan).where(
            models.Vlan.circuit_id == circuito.id, models.Vlan.status == "reservada"
        ).order_by(models.Vlan.vid)
    ))
    prefixos = list(session.scalars(
        select(models.IpPrefix).where(
            models.IpPrefix.circuit_id == circuito.id,
            models.IpPrefix.status == "reservada",
        )
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


def _bloco_rp_export(
    sessao: models.BgpSession, nome_rp: str, afi: str, lista: str | None,
    aplicacoes: list[dict] | None = None,
) -> BlocoRender:
    """RP de exportação; no caminho do cliente `aplicacoes` fica vazio (B1 intacto)."""
    comandos = _render_template(
        "route_policy_export",
        {
            "nome": nome_rp, "afi": afi, "lista": lista,
            "med": sessao.med, "prepend": sessao.prepend or 0,
            "asn_local": sessao.asn_local,
            "aplicacoes": aplicacoes or [],
        },
    ).splitlines()
    return BlocoRender("route_policy_export", "session", sessao.id, comandos)


def _bloco_divida(texto: str) -> BlocoRender:
    """Comentário ao operador (sem comando executável) — ruling 13."""
    return BlocoRender("comentario", "session", 0, [f"# {texto}"])


def _bloco_export(
    session: Session, circuito: models.Circuit, sessao: models.BgpSession,
    definidas: dict[tuple[str, str], set[str]],
) -> tuple[list[BlocoRender], str | None]:
    """RP de exportação pelo produto §6.5/§25.5 (ruling 5); dívidas viram comentário.

    Prefix-list/RP de exportação passam pelo dedup de definições (texto já
    visto ⇒ 1 bloco; divergente ⇒ convivem, dívida §25.4/§25.5 ciclo C).
    Devolve também o nome da RP (§25.4) quando a definição EXISTE para a
    sessão (produto renderizável: full / default / cdn|personalizado com
    prefixos / default_internas / parcial com lista) — o peer referencia
    pelo critério de definição, independente do dedup (ruling R5); dívida
    (comentário) não gera referência. O produto "parcial" cai em dívida
    quando a lista combinada (internas + autorizadas da org) é vazia.
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
    if produto in ("default_internas", "parcial"):
        # Lista combinada: internas (B1) + autorizadas da org da sessão (mesma
        # família) — dedup por prefixo preservando ordem (dict.fromkeys) para
        # não repetir índice. "default_internas" soma a default (index 10);
        # "parcial" é só internas + autorizadas (produto §6.5).
        prefixo = "0.0.0.0/0" if afi == "ipv4" else "::/0"
        combinado = list(dict.fromkeys(
            internas_prefixos(session).get(afi, [])
            + [a.prefix for a in list_authorizations(
                session, organization_id=circuito.organization_id, family=afi)]
        ))
        if produto == "default_internas":
            combinado = list(dict.fromkeys([prefixo] + combinado))
        if not combinado:
            return [_bloco_divida(
                f"produto '{produto}': sem rotas internas nem autorizações "
                "para montar a lista de anúncio."
            )], None
        lista = naming.pfx_produto(produto, afi)
        entradas = [
            {"index": 10 * (i + 1), "prefixo": prefixo_lista}
            for i, prefixo_lista in enumerate(combinado)
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
    # produto desconhecido do catálogo — dívida documentada (sem definição de RP)
    return [_bloco_divida(
        f"produto '{produto}': rotas internas ainda não renderizáveis (ciclo C/F5)."
    )], None


def _eh_upstream(session: Session, sessao: models.BgpSession) -> models.Upstream | None:
    """Upstream que vincula o circuito da sessão (None = sessão de cliente).

    O despacho é pelo VÍNCULO circuito↔upstream (§7) — um circuito pertence a
    no máximo um upstream (BR-1) — e não pelo kind da organização: circuito de
    upstream tem org operadora, mas um circuito de cliente poderia ser de
    org "parceiro" e não deve cair neste caminho.
    """
    return upstream_do_circuito(session, sessao.circuit_id)


def _cf_bloco(sessao_id: int, nome_cf: str, valor: str) -> BlocoRender:
    """Community-filter `ip community-filter <nome> permit <valor>` (§4.1)."""
    return BlocoRender(
        "community_filter", "session", sessao_id,
        _render_template("community_filter", {"nome": nome_cf, "valor": valor}).splitlines(),
    )


def _fail_safe_import(
    sessao: models.BgpSession, nome_rp: str,
    definidas: dict[tuple[str, str], set[str]],
) -> tuple[list[BlocoRender], str]:
    """RP deny-all para sessão de upstream sem perfil válido de import (§4.1/R-09).

    Mesmo texto para "sem perfil" e "perfil de cliente" — o template B2 fixa o
    comentário; a CAUSA fica no comentário-dívida de quem chama. Passa pelo
    dedup: duas sessões fail-safe do mesmo ASN emitem a definição uma vez só.
    """
    blocos: list[BlocoRender] = []
    _apensa_definicao(
        blocos, definidas,
        BlocoRender(
            "route_policy_import", "session", sessao.id,
            _render_template("route_policy_import", {
                "nome": nome_rp, "afi": sessao.afi, "lista": None,
                "local_preference": sessao.local_preference,
                "produto": None, "deny_communities": [], "fail_safe": True,
            }).splitlines(),
        ),
        ("route_policy_import", nome_rp),
    )
    return blocos, nome_rp


def _autorizadas_clientes(
    session: Session, afi: str,
) -> list[models.BgpPrefixAuthorization]:
    """Autorizações ATIVAS de clientes (org de kind != operadora) na AFI (§4.1/§4.2).

    O pedido de proteção/anúncio é "prefixos de clientes": as organizações de
    kind operadora são provedores, não clientes — suas autorizações ficam de
    fora. BgpPrefixAuthorization não tem relationship de org (só
    organization_id), então os ids das operadoras são resolvidos uma vez.
    """
    ids_operadora = set(session.scalars(
        select(models.Organization.id).where(models.Organization.kind == "operadora")
    ))
    return [
        a for a in list_authorizations(session, family=afi)
        if a.organization_id not in ids_operadora
    ]


def _bloco_import_upstream(
    session: Session, sessao: models.BgpSession, up: models.Upstream,
    definidas: dict[tuple[str, str], set[str]], asn_local: int | None,
) -> tuple[list[BlocoRender], str | None]:
    """Importação da sessão de upstream (§4.1) — nunca accept-all implícito.

    up-full: accept-all do provedor EXCETO as proteções — default negada
    quando allow_default_route=false (index 5), prefix-list de proteção
    (internas + autorizações ativas de clientes, kind != operadora, na mesma
    AFI, via naming.pfx_in) em deny node 10, as-path-filter das rotas próprias
    (ASN local do device — naming.as_path_own; sem device.asn ⇒ sem filtro)
    em deny node 20, info-communities marcadas
    bloquear (direcao import/ambos) como nós deny separados (um por filter —
    o VRP faz E de if-match de tipos diferentes no mesmo nó), permit node 100
    com local-preference.
    up-parcial: default + rotas com a info-community de "parcial"
    (bloquear=False) — nós PERMIT no template B2; sem a community cadastrada
    ⇒ comentário-dívida, nunca política permissiva derivada de palpite.
    up-default: somente a rota default (prefix-list IP-PFX-DEFAULT-<AFI>).
    Sem import_profile_id ⇒ fail-safe deny-all. Perfil que NÃO seja up-*
    numa sessão de upstream ⇒ o MESMO deny-all (R-09) + comentário-dívida
    ("produto de cliente em sessão de upstream — negando tudo"): sem a
    route-policy o peer voltaria a accept-all, então o caminho seguro é
    negar, nunca aceitar.
    Nome dos community-filters: inline (naming.py não tem helper de CF):
    CF-<ASN do par>-BLK-<i> (bloqueio) / CF-<ASN do par>-PART-<i> (parcial).
    """
    afi = sessao.afi
    asn_par = sessao.asn_remote
    nome_rp = naming.rp_import(asn_par, afi)
    perfil = (
        get_policy_profile(session, sessao.import_profile_id)
        if sessao.import_profile_id else None
    )
    if perfil is None:
        # fail-safe §4.1: deny explícito, nunca accept-all
        return _fail_safe_import(sessao, nome_rp, definidas)
    produto = perfil.name
    if produto not in ("up-full", "up-parcial", "up-default"):
        # R-09: produto de CLIENTE em sessão de upstream — a config é
        # provavelmente incorreta; abandonar sem RP deixaria o peer accept-all
        # (violação do fail-safe), então o caminho seguro é o deny-all + aviso.
        blocos_fs, nome_fs = _fail_safe_import(sessao, nome_rp, definidas)
        return [_bloco_divida(
            f"produto '{produto}': perfil de cliente em sessão de upstream — negando tudo (fail-safe)."
        )] + blocos_fs, nome_fs

    info_import = [
        uc for uc in list_upstream_communities(session, up.id)
        if uc.purpose == "info" and uc.direcao in ("import", "ambos")
    ]
    deny_as_paths: list[str] = []
    if produto == "up-full":
        entradas: list[dict] = []
        if sessao.allow_default_route is False:
            entradas.append(
                {"index": 5, "prefixo": "0.0.0.0/0" if afi == "ipv4" else "::/0"}
            )
        protecoes = list(dict.fromkeys(
            internas_prefixos(session)[afi]
            + [a.prefix for a in _autorizadas_clientes(session, afi)]
        ))
        entradas += [
            {"index": 10 * (i + 1), "prefixo": p} for i, p in enumerate(protecoes)
        ]
        nome_pfx = naming.pfx_in(asn_par, afi)
        cfs = [uc for uc in info_import if uc.bloquear]
        sufixo_cf = "BLK"
        # item 1 da revisão: rotas próprias (AS-PATH com o ASN do device);
        # sem device.asn a proteção ficaria derivada de um ASN inexistente
        if asn_local is not None:
            deny_as_paths = [naming.as_path_own(asn_local)]
    elif produto == "up-parcial":
        cfs = [uc for uc in info_import if not uc.bloquear]
        if not cfs:
            return [_bloco_divida(
                "produto 'up-parcial': sem community de 'parcial' cadastrada para o upstream."
            )], None
        nome_pfx = naming.pfx_produto("default", afi)
        entradas = [
            {"index": 10, "prefixo": "0.0.0.0/0" if afi == "ipv4" else "::/0"}
        ]
        sufixo_cf = "PART"
    else:  # up-default
        cfs = []
        nome_pfx = naming.pfx_produto("default", afi)
        entradas = [
            {"index": 10, "prefixo": "0.0.0.0/0" if afi == "ipv4" else "::/0"}
        ]
        sufixo_cf = "PART"  # sem communities no up-default

    blocos = []
    for i, uc in enumerate(cfs):
        nome_cf = f"CF-{asn_par}-{sufixo_cf}-{i + 1}"
        _apensa_definicao(
            blocos, definidas, _cf_bloco(sessao.id, nome_cf, uc.value),
            ("community_filter", nome_cf),
        )
    # IMP-1: proteção VAZIA nunca é referenciada — prefix-list sem linhas não
    # existe no VRP e o if-match dela iria falhar no commit (fail-stop); sem
    # entradas, o template pula o nó de deny da proteção (o accept-all do
    # up-full permanece só com os nós de community, permit node 100).
    lista_protecao = nome_pfx if entradas else None
    for nome_aspath in deny_as_paths:
        _apensa_definicao(
            blocos, definidas,
            BlocoRender(
                "as_path_filter", "session", sessao.id,
                _render_template(
                    "as_path_filter",
                    {"nome": nome_aspath, "regex": f"_{asn_local}_"},
                ).splitlines(),
            ),
            ("as_path_filter", nome_aspath),
        )
    if entradas:
        _apensa_definicao(
            blocos, definidas,
            BlocoRender(
                "prefix_list", "session", sessao.id,
                _render_template(
                    "prefix_list", {"nome": nome_pfx, "afi": afi, "entradas": entradas}
                ).splitlines(),
            ),
            ("prefix_list", nome_pfx),
        )
    _apensa_definicao(
        blocos, definidas,
        BlocoRender(
            "route_policy_import", "session", sessao.id,
            _render_template("route_policy_import", {
                "nome": nome_rp, "afi": afi, "lista": lista_protecao,
                "local_preference": sessao.local_preference,
                "produto": produto, "deny_communities": [
                    f"CF-{asn_par}-{sufixo_cf}-{i + 1}" for i, _ in enumerate(cfs)
                ],
                "deny_as_paths": deny_as_paths,
                "fail_safe": False,
            }).splitlines(),
        ),
        ("route_policy_import", nome_rp),
    )
    return blocos, nome_rp


def _bloco_export_upstream(
    session: Session, sessao: models.BgpSession, up: models.Upstream,
    definidas: dict[tuple[str, str], set[str]],
) -> tuple[list[BlocoRender], str | None]:
    """Exportação da sessão de upstream (§4.2) — anúncio NÃO é produto.

    Anúncio = rotas internas (internas_prefixos) + autorizações ATIVAS de
    clientes (kind != operadora, mesma AFI), na prefix-list IP-PFX-<ASN>-
    EXPORT-<AFI> (naming.pfx_export; nome derivado do ASN do par, §25.4 —
    própria de cada upstream). Route_policy_export com
    aplicacoes = communities de AÇÃO da operadora (purpose prepend/lp/
    blackhole, direcao export/ambos), valores concretos direto de
    upstream_communities (§3.1 — sem associação intermediária); med/prepend/
    asn_local vêm da sessão. O template B2 mescla as aplicações em uma única
    linha `apply community` (apply múltiplo seria semântica de replace).
    Dedup de definições idêntico ao caminho do cliente; a referência no peer
    segue o critério de definição (Ruling R5).
    """
    afi = sessao.afi
    nome_rp = naming.rp_export(sessao.asn_remote, afi)
    nome_pfx = naming.pfx_export(sessao.asn_remote, afi)
    anuncio = list(dict.fromkeys(
        internas_prefixos(session)[afi]
        + [a.prefix for a in _autorizadas_clientes(session, afi)]
    ))
    aplicacoes = [
        {"tipo": uc.purpose, "valor": uc.value, "regiao": uc.regiao or ""}
        for uc in list_upstream_communities(session, up.id)
        if uc.purpose in ("prepend", "lp", "blackhole")
        and uc.direcao in ("export", "ambos")
    ]
    # Dívida (IMP-1 não vale aqui, por decisão): uma prefix-list VAZIA no
    # export NÃO é pulada — lista=None deixaria o permit node 10 sem if-match
    # = anunciar TUDO ao provedor (vazamento das rotas de outros vizinhos).
    # O fail-stop do VRP (if-match de objeto inexistente) é a opção segura.
    blocos: list[BlocoRender] = []
    _apensa_definicao(
        blocos, definidas,
        BlocoRender(
            "prefix_list", "session", sessao.id,
            _render_template("prefix_list", {
                "nome": nome_pfx, "afi": afi,
                "entradas": [
                    {"index": 10 * (i + 1), "prefixo": p}
                    for i, p in enumerate(anuncio)
                ],
            }).splitlines(),
        ),
        ("prefix_list", nome_pfx),
    )
    _apensa_definicao(
        blocos, definidas,
        _bloco_rp_export(sessao, nome_rp, afi, nome_pfx, aplicacoes),
        ("route_policy_export", nome_rp),
    )
    return blocos, nome_rp


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
            up = _eh_upstream(session, sessao)
            if up is not None:
                import_blocos, rp_import = _bloco_import_upstream(session, sessao, up, definidas, device.asn)
                export_blocos, rp_export = _bloco_export_upstream(session, sessao, up, definidas)
            else:
                import_blocos, rp_import = _bloco_import(session, circuito, sessao, definidas)
                export_blocos, rp_export = _bloco_export(session, circuito, sessao, definidas)
            blocos.extend(import_blocos)
            blocos.extend(export_blocos)
            blocos.append(_bloco_peer(sessao, rp_import, rp_export))
    blocos.sort(key=lambda b: TIPO_ORDEM[b.tipo])  # estável: preserva ordem intra-tipo
    texto = "\n".join(b.texto for b in blocos)
    return RenderResult(device_id=device.id, blocos=blocos, texto=texto)
