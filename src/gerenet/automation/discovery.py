"""Descoberta de peers: o que o equipamento tem e a SoT não conhece (spec §4–§5).

Somente leitura. O motor lê o `display current-configuration` já gravado no
snapshot, cruza com as sessões da SoT e a lista de ignorados, e devolve cada
peer desconhecido com o palpite de classificação e o motivo que o sustenta.
"""
import ipaddress
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import naming
from gerenet.automation.parsers.huawei_vrp.config_vrp import (
    ConfigVrp,
    PeerConfig,
    parse_config_vrp,
)
from gerenet.automation.snapshots import texto_backup
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.discovery import listar_ignorados
from gerenet.domain.services.ipam import pontas_v4, pontas_v6

AVISO_SEM_CONFIG = (
    "O equipamento não tem coleta com a configuração salva. Colete antes de descobrir."
)


@dataclass(frozen=True)
class Candidato:
    device_id: int
    vrf: str | None
    afi: str
    remote_address: str
    asn_remote: int | None
    descricao: str | None
    snapshot_id: int
    classificacao: str          # "downstream" | "upstream" (o interno vai para `internos`)
    motivo: str


@dataclass
class ResultadoDescoberta:
    device_id: int
    snapshot_id: int | None
    # Ou não há coleta com a configuração, ou a leitura dela não entendeu tudo —
    # nos dois casos a lista vazia não pode passar por "o equipamento não tem peer".
    aviso: str | None = None
    candidatos: list[Candidato] = field(default_factory=list)
    internos: list[Candidato] = field(default_factory=list)


def _normaliza(endereco: str) -> str:
    """Forma canônica do endereço: a config e a SoT podem escrever IPv6 em
    caixas diferentes, e a comparação da quádrupla não pode depender disso."""
    try:
        return str(ipaddress.ip_address(endereco))
    except ValueError:
        return endereco


def _snapshot_com_config(session: Session, device_id: int) -> models.DeviceSnapshot | None:
    """Snapshot mais recente que ainda tenha a configuração em disco.

    Uma coleta anterior a esta frente pode não trazer o recurso, então olhar só
    o último snapshot daria "sem configuração" com a configuração existindo.
    """
    snaps = session.scalars(
        select(models.DeviceSnapshot)
        .where(models.DeviceSnapshot.device_id == device_id)
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(5)
    ).all()
    for snap in snaps:
        if texto_backup(snap).strip():
            return snap
    return None


def _conhecidos(session: Session, device_id: int) -> set[tuple[str | None, str, str]]:
    """Quádruplas (VRF, família, endereço remoto) que a SoT já tem (§4).

    Sessão desativada conta como conhecida: desativar é o único caminho, e
    tratar a desativada como descoberta faria a lista ressuscitar sozinha.
    """
    sessoes = list_sessions(session, device_id=device_id, include_disabled=True)
    if not sessoes:
        return set()
    vrf_do_circuito = {
        c.id: c.vrf
        for c in session.scalars(
            select(models.Circuit).where(
                models.Circuit.id.in_([s.circuit_id for s in sessoes])
            )
        )
    }
    return {
        (vrf_do_circuito.get(s.circuit_id), s.afi, _normaliza(s.remote_address))
        for s in sessoes
    }


def _organizacao_por_asn(session: Session, asn: int | None) -> models.Organization | None:
    if asn is None:
        return None
    return session.scalars(
        select(models.Organization).where(models.Organization.asn == asn)
    ).first()


def _aviso_da_leitura(config: ConfigVrp) -> str | None:
    """O que a leitura da configuração não entendeu, num aviso só (§3).

    As mensagens do parser já são escritas para o operador; deixá-las lá dentro
    faria uma captura ilegível passar por "o equipamento não tem peer" — a lista
    vazia voltaria muda.
    """
    if not config.avisos:
        return None
    return "; ".join(config.avisos)


def _classificar(
    session: Session, device: models.Device, peer: PeerConfig,
) -> tuple[str, str]:
    """Palpite de classificação e o motivo que o sustenta (spec §5).

    Só dois sinais existem. O texto da linha do peer não distingue downstream de
    upstream: `naming.rp_import`/`rp_export` dependem apenas do ASN do par e da
    família, e o render usa as mesmas funções nos dois casos. O que separa os
    dois vive dentro do bloco da route-policy, que este parser não lê.
    """
    if peer.asn_remote is not None and device.asn is not None and peer.asn_remote == device.asn:
        return ("interno", f"ASN remoto {peer.asn_remote} é o mesmo do equipamento: iBGP.")
    org = _organizacao_por_asn(session, peer.asn_remote)
    if org is not None:
        if org.kind == "operadora":
            return ("upstream", f"Organização {org.name} tem o ASN {peer.asn_remote} e é operadora.")
        return ("downstream", f"Organização {org.name} tem o ASN {peer.asn_remote}.")
    return ("downstream", "Sem organização cadastrada para o ASN: classificação não confirmada.")


def listar_candidatos(session: Session, device_id: int) -> ResultadoDescoberta:
    """Peers da configuração que a SoT não conhece (spec §4)."""
    device = get_device(session, device_id)
    snap = _snapshot_com_config(session, device.id)
    if snap is None:
        return ResultadoDescoberta(device_id=device.id, snapshot_id=None, aviso=AVISO_SEM_CONFIG)

    config = parse_config_vrp(texto_backup(snap))
    conhecidos = _conhecidos(session, device.id)
    ignorados = {
        (i.vrf, i.afi, _normaliza(i.remote_address))
        for i in listar_ignorados(session, device.id)
    }

    resultado = ResultadoDescoberta(
        device_id=device.id, snapshot_id=snap.id, aviso=_aviso_da_leitura(config),
    )
    for peer in config.peers:
        chave = (peer.vrf, peer.afi, _normaliza(peer.address))
        if chave in conhecidos or chave in ignorados:
            continue
        classificacao, motivo = _classificar(session, device, peer)
        candidato = Candidato(
            device_id=device.id, vrf=peer.vrf, afi=peer.afi,
            remote_address=_normaliza(peer.address), asn_remote=peer.asn_remote,
            descricao=peer.descricao, snapshot_id=snap.id,
            classificacao=classificacao, motivo=motivo,
        )
        if classificacao == "interno":
            resultado.internos.append(candidato)
        else:
            resultado.candidatos.append(candidato)
    return resultado


_ENLACES_V4 = (30, 31)


@dataclass(frozen=True)
class Pendencia:
    tipo: str
    descricao: str


@dataclass(frozen=True)
class Conflito:
    tipo: str
    descricao: str


@dataclass
class Proposta:
    """A cadeia que nasceria para um enlace (spec §6)."""

    device_id: int
    vrf: str | None
    subinterface: str | None
    vid: int | None
    stack: str
    vlan_mode: str
    p2p_v4_len: int | None
    organizacao_id: int | None = None
    organizacao_sugerida: str | None = None
    site_id: int | None = None
    circuit_code_sugerido: str | None = None
    vlans: list[dict] = field(default_factory=list)
    prefixos: list[dict] = field(default_factory=list)
    sessoes: list[dict] = field(default_factory=list)
    candidatos: list[Candidato] = field(default_factory=list)
    pendencias: list[Pendencia] = field(default_factory=list)
    conflitos: list[Conflito] = field(default_factory=list)

    @property
    def veredito(self) -> str:
        if self.conflitos:
            return "nao_adotavel"
        if self.pendencias:
            return "adotavel_com_pendencias"
        return "adotavel"


@dataclass
class ResultadoPropostas:
    device_id: int
    snapshot_id: int | None
    aviso: str | None = None
    propostas: list[Proposta] = field(default_factory=list)


def _enlace(subs, afi: str, endereco_remoto: str):
    """(subinterface, rede, endereço local) da interface que contém o peer.

    Devolve a primeira que contenha o endereço, qualquer que seja o prefixo. A
    decisão de servir como par p2p é do chamador, que precisa separar "não achei
    o enlace" de "achei, mas não é par p2p".
    """
    alvo = ipaddress.ip_address(endereco_remoto)
    for sub in subs:
        pares = sub.enderecos_v4 if afi == "ipv4" else sub.enderecos_v6
        for endereco, comprimento in pares:
            rede = ipaddress.ip_network(f"{endereco}/{comprimento}", strict=False)
            if alvo in rede:
                return sub, rede, endereco
    return None


def _eh_par_p2p(rede) -> bool:
    """O IPAM só conhece enlace p2p: v4 em /30 ou /31 e v6 em /126.

    Uma sub-rede compartilhada (IX, por exemplo) não tem representação, e o
    operador precisa ver isso como conflito em vez de proposta incompleta.
    """
    if rede.version == 4:
        return rede.prefixlen in _ENLACES_V4
    return rede.prefixlen == 126


def _texto_rede(rede, endereco_de_origem: str) -> str:
    """O texto da rede com a caixa em que a configuração escreve o endereço.

    O `ipaddress` normaliza o hex do IPv6 para minúsculas e a configuração real
    escreve `2804:194C:...`. A reserva é gravada e conferida por texto, e a
    conferência de fidelidade compara o render com o que está no equipamento:
    usar a forma do equipamento é o que mantém os três casando (§25.8 — a mesma
    regra do `_preserva_caixa` do IPAM).
    """
    texto = str(rede)
    if rede.version == 6 and any(c in "ABCDEF" for c in endereco_de_origem):
        return texto.upper()
    return texto


def _orientacao(rede, endereco_local: str) -> str:
    """Qual ponta do par é o roteador (spec §7).

    A comparação é pela forma canônica: a configuração pode trazer o endereço
    IPv6 em maiúsculas e o `ipaddress` o devolve em minúsculas, então comparar
    os textos crus diria "superior" para o endereço de baixo.
    """
    if rede.version == 4:
        inferior = pontas_v4(str(rede), "inferior")[0]
    else:
        inferior = pontas_v6(str(rede), "inferior")[0].split("/")[0]
    return "inferior" if _normaliza(endereco_local) == _normaliza(inferior) else "superior"


def _sessao_de(peer: PeerConfig, candidato: Candidato, rede, orientacao: str) -> dict:
    """Campos da `bgp_sessions` que a configuração entrega.

    As chaves são as do modelo — o ensaio da fidelidade (Task 8) monta a sessão
    com este dicionário —, e os endereços saem na forma canônica, que é a mesma
    que a descoberta usa como identidade do peer.
    """
    if rede.version == 4:
        local = pontas_v4(str(rede), orientacao)[0]
    else:
        local = pontas_v6(str(rede), orientacao)[0].split("/")[0]
    return {
        "afi": candidato.afi,
        "local_address": local,
        "remote_address": candidato.remote_address,
        "asn_local": peer.asn_local,
        "asn_remote": peer.asn_remote,
        "description": peer.descricao,
        "maximum_prefix": peer.maximum_prefix,
        "maximum_prefix_threshold": peer.maximum_prefix_threshold,
        "keepalive": peer.keepalive,
        "holdtime": peer.holdtime,
        "bfd_enabled": peer.bfd,
        "graceful_restart": peer.graceful_restart,
        "shutdown": peer.shutdown,
    }


def _acrescenta(destino: list, novas: list) -> None:
    """Sem repetir o mesmo item: o enlace dual tem dois candidatos, e nem o mesmo
    aviso nem o mesmo conflito fazem sentido duas vezes."""
    vistos = {(i.tipo, i.descricao) for i in destino}
    for item in novas:
        if (item.tipo, item.descricao) not in vistos:
            destino.append(item)
            vistos.add((item.tipo, item.descricao))


def _pendencia_de_politica(peer: PeerConfig, afi: str) -> Pendencia:
    """O produto (full, parcial, default) não sai do nome da route-policy.

    `naming.rp_import` e `naming.rp_export` dependem só do ASN do par e da
    família, então dois produtos diferentes geram o mesmo nome. O que o texto
    diz é se a política segue o padrão deste sistema, não qual produto aplica.
    """
    nomes = sorted(n for n in (peer.import_route_policy, peer.export_route_policy) if n)
    if peer.asn_remote is None:
        # Sem o ASN do par não existe nome padrão com que comparar: dizer que a
        # política está fora do padrão afirmaria o que a configuração não diz.
        return Pendencia(
            "perfil_indeterminado",
            f"A política {nomes[0]} não pôde ser conferida contra o padrão de nome "
            "deste sistema, porque o peer não tem `as-number` lido na configuração: "
            "escolha os perfis na revisão.",
        )
    padrao = {naming.rp_import(peer.asn_remote, afi), naming.rp_export(peer.asn_remote, afi)}
    no_padrao = [n for n in nomes if n in padrao]
    if no_padrao:
        return Pendencia(
            "perfil_indeterminado",
            f"A política {no_padrao[0]} segue o padrão de nome deste sistema, mas o "
            "produto (full, parcial, default) não é recuperável do nome: escolha os "
            "perfis de importação e exportação na revisão.",
        )
    return Pendencia(
        "politica_fora_do_padrao",
        f"A política {nomes[0]} não segue o padrão de nome deste sistema: "
        "escolha os perfis na revisão, sabendo que o render emitirá nomes novos.",
    )


def _pendencias_de(
    session: Session, device: models.Device, peer: PeerConfig, candidato: Candidato,
    *, vid: int | None, descricao_do_enlace: str | None = None,
) -> list[Pendencia]:
    """O que depende de decisão humana e se resolve na revisão (spec §6).

    `descricao_do_enlace` é a descrição que o enlace sugere para a organização
    (a do primeiro candidato, a mesma que vira `organizacao_sugerida`). Os dois
    candidatos do enlace dual têm descrições próprias — `CLIENTE-ALFA` e
    `CLIENTE-ALFA-V6` —, e a pendência é uma só por ASN: citar a do candidato
    corrente faria o mesmo pedido aparecer duas vezes.
    """
    pendencias: list[Pendencia] = []
    if _organizacao_por_asn(session, peer.asn_remote) is None:
        if peer.asn_remote is None:
            # Sem `as-number` lido não há ASN para procurar: a mensagem diz o que
            # falta, em vez de pedir a organização de um "ASN None".
            descricao = (
                "O peer não tem `as-number` lido na configuração: informe o ASN do "
                "par e cadastre a organização"
            )
        else:
            descricao = f"Cadastre a organização do ASN {peer.asn_remote}"
        if descricao_do_enlace:
            descricao += f" (descrição no equipamento: {descricao_do_enlace})"
        pendencias.append(Pendencia("organizacao_ausente", descricao + "."))
        pendencias.append(Pendencia(
            "classificacao_nao_confirmada",
            "Sem organização cadastrada para este ASN: confirme se é downstream ou upstream.",
        ))
    if candidato.classificacao == "downstream":
        pendencias.append(Pendencia(
            "acesso_desconhecido",
            "A configuração do edge não diz de que switch e porta o cliente chega: "
            "preencha o acesso na revisão.",
        ))
    if vid is not None and peer.asn_remote is not None:
        codigo = f"ADOC-{peer.asn_remote}-{vid}"
        if session.scalar(select(models.Circuit.id).where(models.Circuit.code == codigo)):
            pendencias.append(Pendencia(
                "codigo_em_uso",
                f"O código sugerido {codigo} já existe: escolha outro na revisão.",
            ))
    if peer.tem_password:
        pendencias.append(Pendencia(
            "senha_nao_legivel",
            "O equipamento tem senha de peer configurada e o valor não é legível "
            "(cipher do VRP). Cadastre o segredo no Vault e informe o caminho, ou "
            "aceite que a SoT não conhece a senha.",
        ))
    if peer.import_route_policy or peer.export_route_policy:
        pendencias.append(_pendencia_de_politica(peer, candidato.afi))
    if device.asn is not None and peer.asn_local != device.asn:
        pendencias.append(Pendencia(
            "asn_do_equipamento",
            f"O bloco `bgp {peer.asn_local}` difere do ASN {device.asn} cadastrado para "
            "o equipamento: confirme qual está certo.",
        ))
    return pendencias


def _conflitos_de(session, *, site_id, vid, rede, local, remoto) -> list[Conflito]:
    """O que impede a adoção e precisa ser resolvido fora da revisão (§6).

    `rede` é o texto da rede como a proposta o mostra — a caixa com que o
    equipamento escreve o endereço —, porque é esse o texto que a reserva
    grava: comparar com a forma canônica do `ipaddress` deixaria um /126 já
    reservado invisível (o IPAM grava a caixa do bloco do site, e ela é
    `2804:194C::/48`).
    """
    conflitos: list[Conflito] = []
    if site_id is None:
        conflitos.append(Conflito(
            "sem_site", "O equipamento não está vinculado a um site: o IPAM é por site."))
        return conflitos
    if vid is not None:
        tomada = session.scalar(
            select(models.Vlan.id).where(
                models.Vlan.site_id == site_id, models.Vlan.device_id.is_(None),
                models.Vlan.vid == vid, models.Vlan.status == "reservada",
            )
        )
        if tomada:
            conflitos.append(Conflito(
                "vlan_tomada",
                f"A VLAN {vid} já está reservada para outro circuito neste site.",
            ))
    if rede is not None:
        prefixo_tomado = session.scalar(
            select(models.IpPrefix.id).where(
                models.IpPrefix.site_id == site_id,
                models.IpPrefix.network == rede,
                models.IpPrefix.status == "reservada",
            )
        )
        if prefixo_tomado:
            conflitos.append(Conflito(
                "prefixo_tomado",
                f"O prefixo {rede} já está reservado para outro circuito neste site.",
            ))
    em_uso = session.scalar(
        select(models.BgpSession.id).where(
            models.BgpSession.local_address == local,
            models.BgpSession.remote_address == remoto,
            models.BgpSession.admin_status.is_(True),
        )
    )
    if em_uso:
        conflitos.append(Conflito(
            "par_em_uso",
            f"Já existe sessão ativa entre {local} e {remoto}.",
        ))
    return conflitos


def _conflitos_de_coleta(
    snap: models.DeviceSnapshot, sub, local: str, vrf: str | None,
) -> list[Conflito]:
    """Conferência cruzada com o `display ip interface brief` da mesma coleta.

    A configuração é a fonte primária, porque só ela tem a VLAN, o MTU e a
    relação de peer. A interface brief confirma o endereço e traz a VRF a que o
    endereço pertence, que o parser da configuração não lê. Ausência do recurso
    não é divergência: coleta antiga simplesmente não é conferida.
    """
    recursos = (snap.resources or {}).get("interfaces")
    if not recursos:
        return []
    linha = next((i for i in recursos if i.get("nome") == sub.nome), None)
    if linha is None:
        return [Conflito(
            "interface_ausente_na_coleta",
            f"A coleta não tem a interface {sub.nome}: confira se a configuração "
            "salva corresponde ao equipamento.",
        )]
    conflitos: list[Conflito] = []
    enderecos = {
        endereco.split("/")[0].lower()
        for endereco in (linha.get("enderecos_v4") or []) + (linha.get("enderecos_v6") or [])
    }
    if local.lower() not in enderecos:
        conflitos.append(Conflito(
            "endereco_fora_da_coleta",
            f"O endereço {local} que a configuração mostra em {sub.nome} não aparece "
            "no `display ip interface brief` da mesma coleta.",
        ))
    if (linha.get("vpn") or None) != (vrf or None):
        conflitos.append(Conflito(
            "vrf_do_enlace_divergente",
            f"A interface {sub.nome} está na VRF {linha.get('vpn') or 'pública'} e o "
            f"peer está em {vrf or 'instância pública'}: confirme qual é a certa.",
        ))
    return conflitos


def _marca_mesmo_asn(por_enlace: dict) -> None:
    """Dois enlaces com o mesmo ASN no mesmo equipamento: o sistema não decide se
    são um dual stack com VLAN separada (um circuito) ou dois circuitos; ele avisa
    para o operador escolher (spec §6)."""
    por_asn: dict[tuple[str | None, int | None], list[Proposta]] = {}
    for proposta in por_enlace.values():
        if not proposta.candidatos:
            continue
        asn = proposta.candidatos[0].asn_remote
        por_asn.setdefault((proposta.vrf, asn), []).append(proposta)
    for propostas in por_asn.values():
        if len(propostas) < 2:
            continue
        for proposta in propostas:
            _acrescenta(proposta.pendencias, [Pendencia(
                "mesmo_asn_em_outro_enlace",
                "Outro enlace deste equipamento tem o mesmo ASN remoto: confirme se são "
                "um dual stack com VLAN separada (um circuito) ou dois circuitos.",
            )])


def listar_propostas(session: Session, device_id: int) -> ResultadoPropostas:
    """A cadeia que nasceria para cada enlace com peer desconhecido (spec §6).

    O agrupamento é por enlace, ou seja por (VRF, VLAN): os peers v4 e v6 que
    dividem a mesma subinterface são **um** circuito dual stack, e não dois.
    Candidato sem enlace resolvido vira proposta órfã, com o conflito que explica
    o motivo: ele aparece para o operador, não some da tela.
    """
    descoberta = listar_candidatos(session, device_id)
    resultado = ResultadoPropostas(
        device_id=descoberta.device_id, snapshot_id=descoberta.snapshot_id,
        aviso=descoberta.aviso,
    )
    # Quem manda parar é a AUSÊNCIA de coleta, não a presença de aviso: `aviso`
    # carrega dois estados (sem coleta e leitura parcial), e abortar por leitura
    # parcial devolveria zero propostas num equipamento cujos peers foram lidos
    # perfeitamente. O aviso segue no resultado e as superfícies o mostram ao
    # lado da lista.
    if descoberta.snapshot_id is None:
        return resultado

    device = get_device(session, descoberta.device_id)
    snap = session.get(models.DeviceSnapshot, descoberta.snapshot_id)
    config = parse_config_vrp(texto_backup(snap))

    por_enlace: dict[tuple[str | None, int | str | None], Proposta] = {}
    orfas: list[Proposta] = []

    for candidato in descoberta.candidatos:
        peer = next(
            p for p in config.peers
            if _normaliza(p.address) == candidato.remote_address and p.vrf == candidato.vrf
        )
        enlace = _enlace(config.subinterfaces, candidato.afi, candidato.remote_address)
        if enlace is None:
            proposta = Proposta(
                device_id=device.id, vrf=candidato.vrf, subinterface=None, vid=None,
                stack=candidato.afi, vlan_mode="unica", p2p_v4_len=None,
                site_id=device.site_id,
            )
            _acrescenta(proposta.conflitos, [Conflito(
                "endereco_sem_subinterface",
                f"Nenhuma subinterface do equipamento tem {candidato.remote_address} em "
                "um par p2p: sem o enlace não há VLAN nem prefixo a reservar.",
            )])
            orfas.append(proposta)
        else:
            sub, rede, local = enlace
            par_p2p = _eh_par_p2p(rede)
            # O enlace é a VLAN quando ela existe; sem VLAN (`/31` direto numa
            # porta, sem subinterface) ele é a própria interface — agrupar pelo
            # `vid`, que aí é `None` nos dois, juntaria dois enlaces distintos
            # num só.
            chave = (candidato.vrf, sub.vid if sub.vid is not None else sub.nome)
            proposta = por_enlace.get(chave)
            if proposta is None:
                proposta = Proposta(
                    device_id=device.id, vrf=candidato.vrf, subinterface=sub.nome,
                    vid=sub.vid, stack=candidato.afi, vlan_mode="unica",
                    p2p_v4_len=rede.prefixlen if (rede.version == 4 and par_p2p) else None,
                    site_id=device.site_id,
                    circuit_code_sugerido=(
                        f"ADOC-{candidato.asn_remote}-{sub.vid}"
                        if sub.vid is not None else None  # sem VLAN não há código a sugerir
                    ),
                )
                if sub.vid is not None:
                    proposta.vlans.append({"vid": sub.vid, "kind": "vlan", "family": None})
                por_enlace[chave] = proposta
            elif proposta.stack != candidato.afi:
                proposta.stack = "dual"
            if par_p2p:
                orientacao = _orientacao(rede, local)
                rede_texto = _texto_rede(rede, local)
                proposta.prefixos.append({"network": rede_texto, "ponta_local": orientacao})
                sessao = _sessao_de(peer, candidato, rede, orientacao)
                proposta.sessoes.append(sessao)
                _acrescenta(proposta.conflitos, _conflitos_de(
                    session, site_id=device.site_id, vid=sub.vid, rede=rede_texto,
                    local=sessao["local_address"], remoto=candidato.remote_address,
                ))
                _acrescenta(proposta.conflitos, _conflitos_de_coleta(
                    snap, sub, sessao["local_address"], candidato.vrf,
                ))
            else:
                # A proposta continua na lista, com a VLAN que existe, mas sem
                # reserva de prefixo: não há par p2p a reservar.
                _acrescenta(proposta.conflitos, [Conflito(
                    "enlace_nao_p2p",
                    f"O endereço {local} está em {_texto_rede(rede, local)}, que não é "
                    "um par p2p (/30, /31 ou /126): o IPAM não representa sub-rede "
                    "compartilhada.",
                )])

        proposta.candidatos.append(candidato)
        _acrescenta(proposta.pendencias, _pendencias_de(
            session, device, peer, candidato, vid=proposta.vid,
            descricao_do_enlace=proposta.organizacao_sugerida or peer.descricao,
        ))
        org = _organizacao_por_asn(session, candidato.asn_remote)
        if org is not None:
            proposta.organizacao_id = org.id
        elif proposta.organizacao_sugerida is None:
            proposta.organizacao_sugerida = peer.descricao

    _marca_mesmo_asn(por_enlace)
    resultado.propostas = list(por_enlace.values()) + orfas
    return resultado
