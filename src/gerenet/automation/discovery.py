"""Descoberta de peers: o que o equipamento tem e a SoT não conhece (spec §4–§5).

Somente leitura. O motor lê o `display current-configuration` já gravado no
snapshot, cruza com as sessões da SoT e a lista de ignorados, e devolve cada
peer desconhecido com o palpite de classificação e o motivo que o sustenta.
"""
import ipaddress
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.automation import naming
from gerenet.automation.parsers.huawei_vrp.config_vrp import (
    ConfigVrp,
    PeerConfig,
    parse_config_vrp,
)
from gerenet.automation.render import TIPO_ORDEM, RenderResult, render_desejado
from gerenet.automation.snapshots import texto_backup
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.discovery import listar_ignorados
from gerenet.domain.services.ipam import pontas_v4, pontas_v6
from gerenet.domain.validators import endereco_canonico

AVISO_SEM_CONFIG = (
    "O equipamento não tem coleta com a configuração salva. Colete antes de descobrir."
)

# A proposta que não consegue nem ser ensaiada não tem comparação a fazer: esta
# mensagem vira a diferença de contexto `ensaio`. Não nomeia causa porque a
# captura não a conhece: qualquer restrição de unicidade do ensaio cai aqui.
AVISO_SEM_ENSAIO = (
    "uma restrição de unicidade recusou o ensaio (reserva já existente, por exemplo): "
    "sem o ensaio, a comparação com a configuração não pôde ser feita."
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


def _snapshot_com_config(
    session: Session, device_id: int,
) -> tuple[models.DeviceSnapshot | None, str]:
    """Snapshot mais recente que ainda tenha a configuração, e o texto dele.

    Uma coleta anterior a esta frente pode não trazer o recurso, então olhar só
    o último snapshot daria "sem configuração" com a configuração existindo. O
    texto vem junto porque quem chama precisa dele para parsear, e ler o
    arquivo de novo seria uma segunda leitura do mesmo disco.
    """
    snaps = session.scalars(
        select(models.DeviceSnapshot)
        .where(models.DeviceSnapshot.device_id == device_id)
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(5)
    ).all()
    for snap in snaps:
        texto = texto_backup(snap)
        if texto.strip():
            return snap, texto
    return None, ""


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
        (vrf_do_circuito.get(s.circuit_id), s.afi, endereco_canonico(s.remote_address))
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
    snap, texto = _snapshot_com_config(session, device.id)
    if snap is None:
        return ResultadoDescoberta(device_id=device.id, snapshot_id=None, aviso=AVISO_SEM_CONFIG)

    config = parse_config_vrp(texto)
    conhecidos = _conhecidos(session, device.id)
    ignorados = {
        (i.vrf, i.afi, endereco_canonico(i.remote_address))
        for i in listar_ignorados(session, device.id)
    }

    resultado = ResultadoDescoberta(
        device_id=device.id, snapshot_id=snap.id, aviso=_aviso_da_leitura(config),
    )
    for peer in config.peers:
        chave = (peer.vrf, peer.afi, endereco_canonico(peer.address))
        if chave in conhecidos or chave in ignorados:
            continue
        classificacao, motivo = _classificar(session, device, peer)
        candidato = Candidato(
            device_id=device.id, vrf=peer.vrf, afi=peer.afi,
            remote_address=endereco_canonico(peer.address), asn_remote=peer.asn_remote,
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
    qinq: bool = False
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
    # Os iBGP vêm de `listar_candidatos` e não têm proposta: sem eles aqui, quem
    # mostra a lista teria de ler e parsear a configuração de novo.
    internos: list[Candidato] = field(default_factory=list)
    # A idade do texto usado: o motor recua para um snapshot mais antigo quando
    # os recentes não têm a configuração, e uma resposta de dez minutos atrás e
    # uma de três dias atrás não valem o mesmo (§8 do design).
    snapshot_age_seconds: float | None = None


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


def _pontas(rede) -> tuple[str, str]:
    """As duas pontas do par, na forma de `_sessao_de` (v6 sem o `/126`).

    É a única fonte da orientação e da conferência: a reserva representa duas
    pontas e só duas, e o endereço que não seja nenhuma delas não tem como
    virar sessão.
    """
    if rede.version == 4:
        return pontas_v4(str(rede), "inferior")
    inferior, superior = pontas_v6(str(rede), "inferior")
    return inferior.split("/")[0], superior.split("/")[0]


def _orientacao(rede, endereco_local: str) -> str | None:
    """Qual ponta do par é o roteador (spec §7); None se não é nenhuma delas.

    A comparação é pela forma canônica: a configuração pode trazer o endereço
    IPv6 em maiúsculas e o `ipaddress` o devolve em minúsculas, então comparar
    os textos crus diria "superior" para o endereço de baixo.

    `None` é o endereço que existe dentro do prefixo sem ser uma das duas
    pontas — o `/30` com o roteador no `.3`, por exemplo. A orientação supõe
    duas pontas, e responder "superior" para ele faria a sessão nascer com o
    endereço local igual ao do par.
    """
    alvo = endereco_canonico(endereco_local)
    inferior, superior = _pontas(rede)
    if alvo == endereco_canonico(inferior):
        return "inferior"
    if alvo == endereco_canonico(superior):
        return "superior"
    return None


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
    *, codigo_sugerido: str | None, descricao_do_enlace: str | None = None,
) -> list[Pendencia]:
    """O que depende de decisão humana e se resolve na revisão (spec §6).

    `descricao_do_enlace` é a descrição que o enlace sugere para a organização
    (a do primeiro candidato, a mesma que vira `organizacao_sugerida`). Os dois
    candidatos do enlace dual têm descrições próprias — `CLIENTE-ALFA` e
    `CLIENTE-ALFA-V6` —, e a pendência é uma só por ASN: citar a do candidato
    corrente faria o mesmo pedido aparecer duas vezes.

    `codigo_sugerido` é o código da própria proposta, e não um recalculado
    aqui: o que o operador lê e o que é conferido contra a SoT têm de ser o
    mesmo texto — um código que a proposta mostra sem conferir passaria a
    colidir só na adoção.
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
    if codigo_sugerido is not None and session.scalar(
        select(models.Circuit.id).where(models.Circuit.code == codigo_sugerido)
    ):
        pendencias.append(Pendencia(
            "codigo_em_uso",
            f"O código sugerido {codigo_sugerido} já existe: escolha outro na revisão.",
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
    if not peer.habilitado:
        # Resto de configuração, e não peer ativo: o render emite
        # `peer <endereço> enable` em toda sessão, então adotá-lo mandaria o
        # equipamento habilitar o que ninguém pediu para habilitar. Pendência, e
        # não conflito: o operador pode estar a um passo de ativá-lo.
        pendencias.append(Pendencia(
            "peer_nao_habilitado",
            "O equipamento declara este peer, mas não o habilita em nenhuma família "
            "(`peer ... enable`): adotá-lo transforma um resto de configuração em "
            "sessão ativa, e a renderização seguinte mandaria habilitá-lo no "
            "equipamento.",
        ))
    return pendencias


def _conflitos_de(
    session, *, device: models.Device, vid, rede, local, remoto,
) -> list[Conflito]:
    """O que impede a adoção e precisa ser resolvido fora da revisão (§6).

    `rede` é o texto da rede com a caixa do equipamento, mas a conferência é
    sem caixa: o IPAM grava a caixa do bloco do site — `2804:194C::/48` no
    default dos settings, minúsculas se o cadastro foi digitado assim — e o
    equipamento escreve a dele. Exigir que as duas coincidam deixaria um /126
    já reservado invisível, e o operador adotaria um par que colide no índice
    único do banco.

    O par de endereços é único por domínio/site, não por equipamento: dois POPs
    podem ter o mesmo `/31` privado legitimamente, então a sessão que conta é a
    DESTE equipamento — a de outro POP não fala deste enlace.

    A conferência do par é pela forma canônica dos dois lados, e em Python:
    `bgp_sessions` guarda o endereço como foi digitado (a escrita de sessão não
    canonicaliza) e o par vem da configuração. Em SQL, um par escrito em outra
    caixa não casaria e o aviso se perderia — o operador adotaria um enlace que
    a SoT já tem. As sessões de um equipamento são poucas dezenas.
    """
    conflitos: list[Conflito] = []
    site_id = device.site_id
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
                func.lower(models.IpPrefix.network) == rede.lower(),
                models.IpPrefix.status == "reservada",
            )
        )
        if prefixo_tomado:
            conflitos.append(Conflito(
                "prefixo_tomado",
                f"O prefixo {rede} já está reservado para outro circuito neste site.",
            ))
    alvo_local = endereco_canonico(local)
    alvo_remoto = endereco_canonico(remoto)
    em_uso = next((
        sessao for sessao in session.scalars(
            select(models.BgpSession).where(
                models.BgpSession.device_id == device.id,
                models.BgpSession.admin_status.is_(True),
            )
        )
        if endereco_canonico(sessao.local_address) == alvo_local
        and endereco_canonico(sessao.remote_address) == alvo_remoto
    ), None)
    if em_uso:
        # Sem qualificar o estado: a conferência olha a sessão da SoT, não o
        # `shutdown` do equipamento, e "ativa" afirmaria o que não foi lido.
        conflitos.append(Conflito(
            "par_em_uso",
            f"O equipamento {device.name} já tem uma sessão entre {local} e {remoto} "
            "na SoT: confirme se este enlace é o mesmo antes de adotar.",
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


def _conflitos_da_leitura(peer: PeerConfig, vrf: str | None) -> list[Conflito]:
    """O que a leitura não entrega e a adoção exige (§6.3, §25.3).

    A VRF: esta versão do render emite toda sessão na instância pública, então
    uma sessão em VRF não é reproduzível — adotá-la faria a renderização
    seguinte mandar o equipamento mudar a instância do peer, que é o estado que
    ninguém pediu. O `as-number`: sem ele não há sessão a criar, porque
    `bgp_sessions.asn_remote` é NOT NULL.

    Nenhum dos dois se resolve na revisão (o primeiro depende do render e o
    segundo, do equipamento), então os dois são conflito, e não pendência.
    """
    conflitos: list[Conflito] = []
    if vrf is not None:
        conflitos.append(Conflito(
            "vrf_nao_renderizavel",
            f"O peer está na VRF {vrf} e esta versão do render emite as sessões na "
            "instância pública: uma sessão em VRF não é reproduzível. Adotá-la faria "
            "a renderização seguinte mudar a instância do peer no equipamento, então "
            "ela não é adotável hoje.",
        ))
    if peer.asn_remote is None:
        conflitos.append(Conflito(
            "asn_remoto_ausente",
            "A leitura da configuração pegou o peer sem a definição de `as-number`: "
            "a sessão na SoT exige o ASN remoto, então não há sessão a criar. Resolva "
            "o `as-number` no equipamento e colete de novo.",
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

    O agrupamento é por enlace, ou seja por (VRF, subinterface): os peers v4 e
    v6 que dividem a mesma subinterface são **um** circuito dual stack, e não
    dois. Duas subinterfaces com o mesmo VID (`Eth-Trunk127.1001` e
    `GE0/0/1.1001` no mesmo equipamento) são dois enlaces, e agrupar pelo VID
    apresentaria um circuito só com os dois pares. Candidato sem enlace
    resolvido vira proposta órfã, com o conflito que explica o motivo: ele
    aparece para o operador, não some da tela.
    """
    descoberta = listar_candidatos(session, device_id)
    resultado = ResultadoPropostas(
        device_id=descoberta.device_id, snapshot_id=descoberta.snapshot_id,
        aviso=descoberta.aviso, internos=descoberta.internos,
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
    resultado.snapshot_age_seconds = (datetime.now(UTC) - snap.started_at).total_seconds()
    config = parse_config_vrp(texto_backup(snap))

    por_enlace: dict[tuple[str | None, str], Proposta] = {}
    orfas: list[Proposta] = []

    for candidato in descoberta.candidatos:
        peer = next(
            p for p in config.peers
            if endereco_canonico(p.address) == candidato.remote_address and p.vrf == candidato.vrf
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
            # O enlace é a subinterface, sempre — com VLAN ou sem (`/31` direto
            # numa porta). Pelo `vid`, duas subinterfaces do mesmo equipamento
            # com o mesmo VID seriam uma proposta só, com dois pares e duas
            # sessões, e sem VLAN (`vid=None` nos dois) o mesmo valeria para
            # duas portas.
            chave = (candidato.vrf, sub.nome)
            proposta = por_enlace.get(chave)
            if proposta is None:
                proposta = Proposta(
                    device_id=device.id, vrf=candidato.vrf, subinterface=sub.nome,
                    vid=sub.vid, stack=candidato.afi, vlan_mode="unica",
                    # `vlan_mode` é "unica" nos dois casos: a mesma VLAN carrega
                    # as duas famílias ou uma por família — o empilhamento é
                    # outro eixo, e o render só o emite com `Circuit.qinq`.
                    qinq=sub.qinq,
                    p2p_v4_len=rede.prefixlen if (rede.version == 4 and par_p2p) else None,
                    site_id=device.site_id,
                    circuit_code_sugerido=(
                        f"ADOC-{candidato.asn_remote}-{sub.vid}"
                        # Sem VLAN ou sem ASN lido não há código a sugerir (e o
                        # `codigo_em_uso` só confere o código que existe).
                        if sub.vid is not None and candidato.asn_remote is not None
                        else None
                    ),
                )
                if sub.vid is not None:
                    proposta.vlans.append({
                        "vid": sub.vid,
                        # Empilhado (`vlan-type dot1q 0x88a8`) reserva S-VLAN.
                        "kind": "s_vlan" if sub.qinq else "vlan",
                        "family": None,
                    })
                por_enlace[chave] = proposta
            elif proposta.stack != candidato.afi:
                proposta.stack = "dual"
            orientacao = _orientacao(rede, local) if par_p2p else None
            if orientacao is not None:
                rede_texto = _texto_rede(rede, local)
                proposta.prefixos.append({"network": rede_texto, "ponta_local": orientacao})
                sessao = _sessao_de(peer, candidato, rede, orientacao)
                proposta.sessoes.append(sessao)
                _acrescenta(proposta.conflitos, _conflitos_de(
                    session, device=device, vid=sub.vid, rede=rede_texto,
                    local=sessao["local_address"], remoto=candidato.remote_address,
                ))
                _acrescenta(proposta.conflitos, _conflitos_de_coleta(
                    snap, sub, sessao["local_address"], candidato.vrf,
                ))
            elif par_p2p:
                # O endereço existe dentro do prefixo e não é nenhuma das duas
                # pontas que o IPAM representa (`pontas_v4`/`pontas_v6`): sem
                # ponta não há reserva, e a sessão nasceria com o endereço local
                # igual ao do par. A proposta continua na lista, com a VLAN que
                # existe, como no `enlace_nao_p2p` logo abaixo.
                inferior, superior = _pontas(rede)
                _acrescenta(proposta.conflitos, [Conflito(
                    "ponta_incoerente",
                    f"O endereço {local} está em {_texto_rede(rede, local)}, mas não é "
                    f"nenhuma das duas pontas que o IPAM representa para esse par "
                    f"({inferior} e {superior}): sem ponta não há reserva nem sessão "
                    "a montar para este enlace.",
                )])
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
        _acrescenta(proposta.conflitos, _conflitos_da_leitura(peer, candidato.vrf))
        _acrescenta(proposta.pendencias, _pendencias_de(
            session, device, peer, candidato,
            codigo_sugerido=proposta.circuit_code_sugerido,
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


@dataclass(frozen=True)
class Diferenca:
    contexto: str                  # "peer" | "subinterface" | "definicao" | "ensaio"
    sobrando: tuple[str, ...] = ()      # o render produz e a configuração não tem
    faltando: tuple[str, ...] = ()      # a configuração tem e o render não produz
    nao_gerenciado: tuple[str, ...] = ()   # a SoT não emite isto, e não é divergência
    explicacao: str | None = None          # quando a comparação não pôde ser feita

    @property
    def exige_ciente(self) -> bool:
        """Só o que a SoT VAI MUDAR no equipamento gateia o aceite (design §6)."""
        return bool(self.sobrando or self.faltando)


def _equivalencia_vrp(texto: str) -> str:
    """Duas linhas que o VRP escreve de duas formas, na forma do render.

    `vlan-type dot1q 1001` e `vlan-type dot1q vid 1001` são a mesma linha, e o
    mesmo vale para `ipv6 address <endereço> 126` e `<endereço>/126`. O parser
    lê as duas formas e o render escreve a segunda, então sem a equivalência
    toda proposta com VLAN e IPv6 nasce com dois falsos `sobrando` e dois falsos
    `faltando` no contexto da subinterface, que é onde a mudança de estado da
    interface tem de aparecer. São a mesma linha escrita de dois jeitos, não
    dois estados: por isso é equivalência, e não normalização de conveniência.
    """
    partes = texto.split()
    if len(partes) == 3 and partes[:2] == ["vlan-type", "dot1q"] and partes[2].isdigit():
        return f"vlan-type dot1q vid {partes[2]}"
    if len(partes) == 4 and partes[:2] == ["ipv6", "address"] and partes[3].isdigit():
        return f"ipv6 address {partes[2]}/{partes[3]}"
    return texto


def _contexto_interface(texto: str, nome: str) -> set[str]:
    """Linhas da configuração dentro do bloco `interface <nome>`.

    O cabeçalho fica de fora: ele abre o contexto, não é linha dele — e o lado
    do render o descarta pelo mesmo motivo (`conferir_fidelidade`), para a
    comparação não começar com o cabeçalho presente de um lado só.

    Comentário (`#`, com ou sem texto) também fica de fora, e antes da regra de
    contexto: o `_normaliza_linhas` já descarta os dois do lado do render, e um
    comentário com texto na coluna 0 zerava o `dentro` aqui — as linhas de
    endereço que vinham depois ficavam de fora da comparação e o render as
    acusava como sobra.
    """
    linhas: set[str] = set()
    dentro = False
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if not bruta[:1].isspace():
            dentro = linha == f"interface {nome}"
            continue
        if dentro:
            linhas.add(_equivalencia_vrp(linha))
    return linhas


def _contexto_peer(texto: str, endereco: str) -> set[str]:
    """Todas as linhas `peer <endereço> ...`, venham do bloco do bgp ou da seção
    de família (a indentação do contexto não interessa à comparação).

    A busca e a reescrita são sem caixa: a identidade do peer é o endereço na
    forma canônica (`endereco_canonico`, minúsculas) e a configuração escreve o hex do
    IPv6 como digitado (`2804:194C:...`, a mesma caixa que o `_texto_rede`
    preserva no outro lado). Sem isso todo peer v6 apareceria inteiro como
    diferença — e a diferença de verdade ficaria escondida no meio.
    """
    prefixo = f"peer {endereco} "
    linhas: set[str] = set()
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if linha.lower().startswith(prefixo.lower()):
            linhas.add(_mascara_senha(prefixo + linha[len(prefixo):], endereco))
    return linhas


def _mascara_senha(linha: str, endereco: str) -> str:
    """A senha do VRP nunca é exibida, nem numa diferença (§19).

    A linha é `peer <endereço> password <algoritmo> <valor>`: saem o algoritmo
    e o valor, e o que fica diz que o equipamento tem senha de peer e que a
    SoT não a conhece. A palavra-chave é reconhecida na posição dela, e não em
    qualquer lugar da linha: uma descrição que por acaso a contivesse viraria
    uma linha de senha falsa e sumiria do lugar de diferença de verdade.
    """
    prefixo = f"peer {endereco} "
    if linha[len(prefixo):].startswith("password "):
        return f"{prefixo}password [mascarado]"
    return linha


# Blocos de DEFINIÇÃO: o render os emite para a sessão, e o filtro por linha de
# peer os descarta. A chave é o cabeçalho sem o corpo, e as duas pontas usam a
# MESMA regra, porque a premissa da comparação é que o texto é o mesmo comando.
#
# Derivados do `TIPO_ORDEM` do render em vez de repetidos aqui: um tipo de
# definição novo lá passa a ser conferido sem ninguém precisar lembrar, e o que
# não é definição sai por nome — a subinterface, o bloco do peer e o
# comentário-dívida, que não tem corpo a comparar.
_NAO_DEFINICAO = ("subinterface", "bgp_peer", "comentario")
_TIPOS_DEFINICAO = tuple(t for t in TIPO_ORDEM if t not in _NAO_DEFINICAO)


def _chave_definicao(linha: str) -> str | None:
    """Chave do bloco de definição a partir da linha de cabeçalho.

    `route-policy NOME permit|deny node N` → `route-policy NOME`; os demais são
    `ip ip-prefix NOME`, `ip ipv6-prefix NOME`, `ip as-path-filter NOME` e
    `ip community-filter NOME`, todos com o nome no terceiro token.
    """
    partes = linha.split()
    if not partes:
        return None
    if partes[0] == "route-policy" and len(partes) >= 2:
        return f"route-policy {partes[1]}"
    if partes[0] == "ip" and len(partes) >= 3 and partes[1] in (
        "ip-prefix", "ipv6-prefix", "as-path-filter", "community-filter"
    ):
        return f"ip {partes[1]} {partes[2]}"
    return None


def _cabecalho_do_bloco(comandos: list[str]) -> str:
    """O primeiro comando que não é comentário: o cabeçalho do bloco.

    O import de upstream abre com `# up-full: ...` (e o fail-safe, com
    `# fail-safe: ...`) antes do `route-policy`. Tomar a linha 0 como cabeçalho
    faria a chave sair nula e o bloco seria pulado sem diferença nenhuma — o
    modo de falha silencioso que esta conferência existe para fechar. Sem
    comando nenhum, devolve o texto vazio, que não casa chave alguma.
    """
    return next((linha for linha in comandos if not linha.strip().startswith("#")), "")


def _referencias(linhas: list[str]) -> set[str]:
    """Chaves de definição que estas linhas de comando referenciam.

    O bloco do peer nomeia a route-policy (`peer <endereço> import route-policy
    <nome>` e `peer <endereço> export route-policy <nome>`), e o corpo de uma
    route-policy nomeia os filtros que ela usa (`if-match ip-prefix <lista>`,
    `if-match ipv6 address prefix-list <lista>`, `if-match as-path-filter
    <nome>` e `if-match community-filter <nome>`). As chaves saem na mesma forma
    que `_chave_definicao` reconhece no cabeçalho, que é como as duas pontas da
    comparação se encontram.
    """
    saida: set[str] = set()
    for bruta in linhas:
        partes = bruta.split()
        if "route-policy" in partes:
            posicao = partes.index("route-policy") + 1
            if posicao < len(partes):
                saida.add(f"route-policy {partes[posicao]}")
            continue
        if len(partes) >= 3 and partes[0] == "if-match":
            if partes[1] in ("ip-prefix", "as-path-filter", "community-filter"):
                saida.add(f"ip {partes[1]} {partes[2]}")
            elif len(partes) >= 5 and partes[1:4] == ["ipv6", "address", "prefix-list"]:
                saida.add(f"ip ipv6-prefix {partes[4]}")
    return saida


def _chaves_do_ensaio(render: RenderResult, ids_sessoes: set[int]) -> set[str]:
    """Chaves de definição que o ensaio referencia, em dois níveis.

    O bloco do peer da sessão do ensaio nomeia as route-policies, e o corpo
    delas nomeia os filtros. O `objeto_id` do bloco de definição NÃO serve de
    critério: `_apensa_definicao` apensa a definição uma vez só, com o id da
    PRIMEIRA sessão que a produziu, então num PE com dois enlaces do mesmo
    cliente o bloco do segundo vem marcado com o id do primeiro — que a adoção
    anterior já criou — e conferir por id deixaria a sessão do ensaio sem nada
    a comparar, em silêncio. O bloco está no render; quem o referencia é que
    decide se ele entra.
    """
    por_chave: dict[str, list[str]] = {}
    for bloco in render.blocos:
        if bloco.tipo not in _TIPOS_DEFINICAO:
            continue
        chave = _chave_definicao(_cabecalho_do_bloco(bloco.comandos))
        if chave is not None:
            por_chave.setdefault(chave, []).extend(bloco.comandos)
    politicas = {
        chave
        for bloco in render.blocos
        if bloco.objeto == "session" and bloco.objeto_id in ids_sessoes
        for chave in _referencias(bloco.comandos)
    }
    return politicas | {
        chave
        for politica in politicas
        for chave in _referencias(por_chave.get(politica, []))
    }


def _indice_definicoes(texto: str) -> dict[str, tuple[str, ...]]:
    """Blocos de definição da configuração, indexados pela chave.

    Um bloco começa numa linha sem indentação cujo cabeçalho casa
    `_chave_definicao` e vai até a próxima linha sem indentação — e a chave é
    que reúne o objeto: a prefix-list de várias entradas é um bloco só, uma
    linha de cabeçalho por entrada.

    Comentário é qualquer linha começando com `#`, e não só o separador
    sozinho, e ele some ANTES da regra de contexto — como no
    `_contexto_interface` e no parser da configuração. O render deste projeto
    emite comentário com texto na coluna 0 dentro do bloco (`# up-full: ...`,
    `# TE: ...`), e tratá-lo como linha de topo fecharia o bloco ali mesmo: as
    linhas seguintes sairiam da leitura em silêncio e o render as acusaria como
    sobra. É a lição que a parte 1 pagou para aprender.
    """
    indice: dict[str, list[str]] = {}
    chave: str | None = None
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if not bruta[:1].isspace():
            chave = _chave_definicao(linha)
            if chave is not None:
                indice.setdefault(chave, []).append(linha)
            continue
        if chave is not None:
            indice[chave].append(linha)
    return {c: tuple(linhas) for c, linhas in indice.items()}


def _normaliza_linhas(linhas: list[str]) -> set[str]:
    """Compara por conjunto dentro do contexto: a ordem do render e a da
    configuração não é a mesma, e `undo ...` é negação de default, não ajuste."""
    saida: set[str] = set()
    for linha in linhas:
        texto = " ".join(linha.split())
        if not texto or texto.startswith(("#", "undo ")):
            continue
        saida.add(_equivalencia_vrp(texto))
    return saida


def _trunk_da_subinterface(proposta: Proposta) -> str | None:
    """O trunk do circuito, derivado do nome da subinterface do equipamento.

    O render nomeia a subinterface como `<trunk>.<vid>` (`naming.subinterface`)
    e quem carrega o trunk é o `edge_trunk` do circuito: sem ele o render não
    emite bloco de subinterface nenhum e a conferência acusaria uma diferença
    que a adoção não criaria. Nome que não é `<trunk>.<vid>` não tem trunk a
    derivar — e aí a diferença é real: o render não reproduz esse nome.
    """
    if proposta.subinterface is None or proposta.vid is None:
        return None
    sufixo = f".{proposta.vid}"
    if not proposta.subinterface.endswith(sufixo):
        return None
    return proposta.subinterface[: -len(sufixo)]


def _ensaio(
    session: Session, proposta: Proposta,
    perfis: dict[str, dict[str, int | None]] | None = None,
) -> dict:
    """Objetos transitórios com a forma do que a adoção criaria.

    Sem passar pelos serviços, que commitam: aqui nada pode virar escrito. O
    chamador desfaz a transação.

    `perfis` é o mapa {afi: {"import_profile_id", "export_profile_id"}} do que o
    operador escolheu na revisão. A `Proposta` não carrega perfil nenhum, e sem
    ele o `_bloco_export` sai cedo: a política de exportação nem existiria no
    ensaio, e é o produto dela que a revisão decide (design §6).
    """
    device = get_device(session, proposta.device_id)
    org_id = proposta.organizacao_id
    if org_id is None:
        org = models.Organization(
            name=f"ENSAIO-{device.name}-{proposta.vid}",
            asn=proposta.candidatos[0].asn_remote if proposta.candidatos else None,
        )
        session.add(org)
        session.flush()
        org_id = org.id
    circ = models.Circuit(
        code=f"ENSAIO-{device.name}-{proposta.vid}", organization_id=org_id,
        site_id=proposta.site_id or device.site_id, access_port="ensaio",
        edge_device_id=device.id, edge_trunk=_trunk_da_subinterface(proposta),
        stack=proposta.stack, vlan_mode=proposta.vlan_mode,
        qinq=proposta.qinq,          # sem isto a fidelidade acusa diferença em todo QinQ
        p2p_v4_len=proposta.p2p_v4_len or 31,
    )
    session.add(circ)
    session.flush()
    for vlan in proposta.vlans:
        session.add(models.Vlan(site_id=circ.site_id, vid=vlan["vid"], kind=vlan["kind"],
                                family=vlan["family"], circuit_id=circ.id))
    for prefixo in proposta.prefixos:
        session.add(models.IpPrefix(site_id=circ.site_id, network=prefixo["network"],
                                    kind="p2p", circuit_id=circ.id,
                                    ponta_local=prefixo["ponta_local"]))
    session.flush()
    sessoes = []
    for dados in proposta.sessoes:
        # `asn_remote` é NOT NULL em `bgp_sessions`, e a adoção também não
        # conseguiria criá-la: o ensaio espelha apenas o que nasceria de verdade.
        if dados.get("asn_remote") is None:
            continue
        # Cópia porque o `**campos` não pode repetir argumento se a leitura um
        # dia passar a preencher os perfis no dict da proposta: o que veio da
        # revisão vence, e o resto passa como veio.
        campos = dict(dados)
        campos.update({
            nome: valor
            for nome, valor in (perfis or {}).get(dados.get("afi"), {}).items()
            if nome in ("import_profile_id", "export_profile_id")
        })
        sessao = models.BgpSession(circuit_id=circ.id, device_id=device.id, **campos)
        session.add(sessao)
        sessoes.append(sessao)
    session.flush()
    return {"circuito": circ, "sessoes": sessoes}


# Linhas de subinterface que o render não emite: o slot `description` do
# template existe e nada o preenche, e não há `mtu` de subinterface.
_NAO_GERENCIADAS_SUBINTERFACE = ("description ", "mtu ")


def _particiona_subinterface(linhas: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separa o que a SoT gerencia do que ela só não emite (design §17.1).

    O render não tem `description` de subinterface (o slot existe no template e
    nada o preenche) nem `mtu`, e numa borda real os dois estão em toda
    subinterface. Deixá-los no `faltando` faria "diferença exige ciente"
    degenerar em "marque sempre".
    """
    gerenciadas, nao_gerenciadas = [], []
    for linha in linhas:
        alvo = nao_gerenciadas if linha.startswith(_NAO_GERENCIADAS_SUBINTERFACE) else gerenciadas
        alvo.append(linha)
    return tuple(sorted(gerenciadas)), tuple(sorted(nao_gerenciadas))


def conferir_fidelidade(
    session: Session, proposta: Proposta,
    *, perfis: dict[str, dict[str, int | None]] | None = None,
) -> list[Diferenca]:
    """O que a SoT reproduziria × o que a configuração tem (spec §9).

    `perfis` é o que o operador escolheu na revisão, no mapa {afi:
    {"import_profile_id", "export_profile_id"}}, e é o que faz o ensaio emitir a
    definição de exportação — o produto dela é justamente o que a revisão
    decide. Sem o mapa, o ensaio fica sem perfil nenhum, como antes desta
    interface existir.

    O ensaio roda o render de verdade, e não uma reimplementação da montagem
    dos comandos: é o mesmo código que a adoção usaria, então a conferência não
    pode divergir do que ela produziria.

    O ensaio roda num SAVEPOINT e o que é desfeito no fim é só ele. Um
    `rollback` da sessão inteira levaria junto o que o chamador tem pendente —
    a §10 chama esta conferência dentro da transação da adoção, e o descarte
    silencioso de um `commit` posterior viraria adoção parcial — e deixaria a
    transação externa morta depois de um `IntegrityError` do ensaio. Com o
    savepoint, o que o chamador tinha pendente continua sendo escrito pelo
    `commit` dele (conferido nos dois caminhos, o de sucesso e o do estouro) e
    nada do ensaio escapa.

    Proposta que não consegue ser ensaiada, ou cuja comparação não vale (peer
    em VRF, que o render não reproduz), devolve a diferença de contexto
    `ensaio` dizendo isso, em vez de estourar: uma exceção aqui chegaria a quem
    chamou esperando uma lista de diferenças, e uma lista vazia leria como
    "está tudo fiel". O que a diferença diz vai em `explicacao`, com `sobrando`
    e `faltando` vazios: eles são o que a SoT mudaria no equipamento, e uma
    linha dentro deles faria um `ensaio` gatear o aceite de uma comparação que
    não aconteceu (design §6).
    """
    if not proposta.candidatos:
        # Sem candidato não há endereço de peer nem snapshot a ler: a comparação
        # não tem por onde começar, e a lista vazia leria como fidelidade.
        return [Diferenca(
            contexto="ensaio",
            explicacao=(
                "a proposta não tem candidato: sem o peer lido na configuração não "
                "há endereço nem coleta com que comparar."
            ),
        )]
    if proposta.site_id is None:
        # O circuito do ensaio precisa do site (a coluna é NOT NULL) e é dele
        # que sai o render a comparar: sem site, a reserva não acontece.
        return [Diferenca(
            contexto="ensaio",
            explicacao=(
                "o equipamento não está vinculado a um site, e o IPAM reserva por "
                "site: sem a reserva o ensaio não tem como acontecer, e sem ele não "
                "há comparação com a configuração."
            ),
        )]
    if proposta.vrf is not None:
        # Defesa em profundidade: a proposta já carrega o conflito
        # `vrf_nao_renderizavel`, mas a conferência é chamada para qualquer
        # peer, inclusive os não adotáveis, e uma comparação que ignorasse a
        # instância sairia como fiel.
        mensagem = (
            f"o peer está na VRF {proposta.vrf} e esta versão do render emite as "
            "sessões na instância pública: a comparação não é confiável para uma "
            "sessão em VRF."
        )
        return [Diferenca(contexto="ensaio", explicacao=mensagem)]
    snap = session.get(models.DeviceSnapshot, proposta.candidatos[0].snapshot_id)
    texto = texto_backup(snap)
    resultado: list[Diferenca] = []
    ensaio = session.begin_nested()
    try:
        try:
            criados = _ensaio(session, proposta, perfis)
        except IntegrityError:
            # Uma restrição de unicidade recusou o ensaio (a reserva que a
            # proposta pede já existe, na mesma grafia, é o caso comum): sem
            # ensaio não há comparação a fazer, e é isso que a diferença diz.
            return [Diferenca(contexto="ensaio", explicacao=AVISO_SEM_ENSAIO)]
        render = render_desejado(session, proposta.device_id)
        id_circuito = criados["circuito"].id
        ids_sessoes = {s.id for s in criados["sessoes"]}

        comandos_peer = [
            linha for bloco in render.blocos
            if bloco.objeto == "session" and bloco.objeto_id in ids_sessoes
            for linha in bloco.comandos
        ]
        comandos_sub = [
            linha for bloco in render.blocos
            if bloco.objeto == "circuit" and bloco.objeto_id == id_circuito
            for linha in bloco.comandos
        ]
        for endereco in sorted({c.remote_address for c in proposta.candidatos}):
            esperado = _normaliza_linhas(
                [linha for linha in comandos_peer if f"peer {endereco} " in f" {linha} "]
            )
            encontrado = _contexto_peer(texto, endereco)
            resultado.append(Diferenca(
                contexto="peer",
                sobrando=tuple(sorted(esperado - encontrado)),
                faltando=tuple(sorted(encontrado - esperado)),
            ))
        if proposta.subinterface is not None:
            esperado = _normaliza_linhas(comandos_sub)
            esperado.discard(f"interface {proposta.subinterface}")
            encontrado = _contexto_interface(texto, proposta.subinterface)
            gerenciadas, nao_gerenciadas = _particiona_subinterface(
                tuple(sorted(encontrado - esperado))
            )
            resultado.append(Diferenca(
                contexto="subinterface",
                sobrando=tuple(sorted(esperado - encontrado)),
                faltando=gerenciadas,
                nao_gerenciado=nao_gerenciadas,
            ))
        # O corpo das definições que a sessão do ensaio referencia (design §6).
        # O índice é construído UMA vez para os blocos todos: dentro do laço,
        # cada definição re-varreria a configuração inteira — a de uma borda
        # real são centenas de KB por definição de cada sessão.
        chaves = _chaves_do_ensaio(render, ids_sessoes)
        indice = _indice_definicoes(texto)
        for bloco in render.blocos:
            if bloco.tipo not in _TIPOS_DEFINICAO or not bloco.comandos:
                continue
            chave = _chave_definicao(_cabecalho_do_bloco(bloco.comandos))
            if chave is None or chave not in chaves:
                continue
            esperado = _normaliza_linhas(bloco.comandos)
            encontrado = _normaliza_linhas(list(indice.get(chave, ())))
            resultado.append(Diferenca(
                contexto="definicao",
                sobrando=tuple(sorted(esperado - encontrado)),
                faltando=tuple(sorted(encontrado - esperado)),
            ))
    finally:
        # Desfaz só o ensaio (o SAVEPOINT), pela razão da docstring: o
        # `rollback` da sessão levaria o pendente do chamador junto.
        ensaio.rollback()
    return resultado
