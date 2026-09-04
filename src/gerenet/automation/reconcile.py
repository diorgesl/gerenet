"""Divergência desejado × encontrado, read-only (spec ciclo B §6).

Renderiza o desejado do device (render_desejado) e compara com o snapshot
mais recente (ou o snapshot_id pedido). Sem tabela nova; sem efeitos no
equipamento. Itens tipados {tipo, severidade, esperado, encontrado, acao}.
"""
import ipaddress
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation.render import BlocoRender, render_desejado
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import NotFoundError, ValidationError

ESTABLISHED = "Established"


@dataclass
class ReconcileItem:
    tipo: str
    severidade: str  # critica | atencao | aviso
    esperado: str
    encontrado: str
    acao: str


@dataclass
class ReconcileResult:
    device_id: int
    snapshot_id: int | None
    aviso: str | None
    items: list[ReconcileItem] = field(default_factory=list)


def _item(tipo: str, severidade: str, esperado: str, encontrado: str, acao: str) -> ReconcileItem:
    return ReconcileItem(
        tipo=tipo, severidade=severidade, esperado=esperado,
        encontrado=encontrado, acao=acao,
    )


def _estado_efetivo(valor: str | None) -> bool:
    """True quando o valor NÃO indica down (up, up(s), administratively down, etc.)."""
    return valor is not None and "down" not in str(valor).lower()


def _esperado_subinterfaces(blocos: list[BlocoRender]) -> dict[str, dict[str, list[str]]]:
    """Subinterfaces esperadas a partir dos blocos renderizados (ruling 7).

    Devolve {nome: {"v4": [addr/len], "v6": [addr/126]}} — parse dos padrões de
    linha que o próprio render emite (contrato T3/T4).
    """
    esperadas: dict[str, dict[str, list[str]]] = {}
    for bloco in blocos:
        if bloco.tipo != "subinterface" or not bloco.comandos:
            continue
        nome = bloco.comandos[0].removeprefix("interface ")
        registro = esperadas.setdefault(nome, {"v4": [], "v6": []})
        for linha in bloco.comandos[1:]:
            if linha.startswith("ip address "):
                endereco, mascara = linha.removeprefix("ip address ").split()
                prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{mascara}").prefixlen
                registro["v4"].append(f"{endereco}/{prefixlen}")
            elif linha.startswith("ipv6 address "):
                registro["v6"].append(linha.removeprefix("ipv6 address "))
    return esperadas


def reconciliar_device(
    session: Session, device_id: int | None = None, *, snapshot_id: int | None = None
) -> ReconcileResult:
    """Compara o desejado renderizado do device com o snapshot (spec §6)."""
    if snapshot_id is not None:
        snap = session.get(models.DeviceSnapshot, snapshot_id)
        if snap is None:
            raise NotFoundError(f"Snapshot {snapshot_id} não encontrado.")
        if device_id is None:
            device_id = snap.device_id
        elif snap.device_id != device_id:
            raise ValidationError(f"Snapshot {snapshot_id} não pertence ao device {device_id}.")
    if device_id is None:
        raise ValidationError("Informe device_id ou snapshot_id para reconciliar.")
    get_device(session, device_id)  # NotFoundError propaga (404 na API)

    if snapshot_id is None:
        snap = session.scalars(
            select(models.DeviceSnapshot)
            .where(models.DeviceSnapshot.device_id == device_id)
            .order_by(models.DeviceSnapshot.id.desc())
            .limit(1)
        ).first()
    recursos = (snap.resources or {}) if snap is not None else {}
    render = render_desejado(session, device_id)
    items: list[ReconcileItem] = []
    avisos: list[str] = []

    if snap is None:
        avisos.append("Sem snapshot para comparar — colete o device antes (gerenet collect).")
    else:
        for recurso in ("interfaces", "bgp_peers", "bgp_peers_verbose"):
            if recurso not in recursos:
                avisos.append(f"Snapshot {snap.id} sem o recurso '{recurso}' — comparação parcial.")

    tem_interfaces = "interfaces" in recursos
    tem_peers = "bgp_peers" in recursos
    tem_verbose = "bgp_peers_verbose" in recursos

    por_peer_verbose = (
        {(linha["afi"], linha["peer"]): linha for linha in recursos.get("bgp_peers_verbose", [])}
        if snap is not None and tem_verbose else {}
    )
    por_peer_encontrado = (
        {(linha["afi"], linha["peer"]): linha for linha in recursos.get("bgp_peers", [])}
        if snap is not None and tem_peers else {}
    )

    # nomes de RP por sessão (esperados nos filtros): 1ª linha dos blocos
    rp_por_sessao: dict[int, dict[str, str]] = {}
    for bloco in render.blocos:
        if bloco.tipo in ("route_policy_import", "route_policy_export") and bloco.comandos:
            rp_por_sessao.setdefault(bloco.objeto_id, {})[bloco.tipo] = (
                bloco.comandos[0].removeprefix("route-policy ").split()[0]
            )

    # ---- subinterfaces e pontas (só com o recurso presente) ----
    if snap is not None and tem_interfaces:
        por_nome_interface = {i["nome"]: i for i in recursos.get("interfaces", [])}
        for nome, enderecos in sorted(_esperado_subinterfaces(render.blocos).items()):
            achada = por_nome_interface.get(nome)
            if achada is None:
                items.append(_item(
                    "subinterface.ausente", "critica", nome, "não listada",
                    "Recriar/verificar a subinterface no equipamento.",
                ))
                continue
            estado = f"{achada.get('phy')}/{achada.get('protocolo')}"
            if not _estado_efetivo(achada.get("phy")) or not _estado_efetivo(achada.get("protocolo")):
                items.append(_item(
                    "subinterface.estado", "atencao", "up", estado,
                    "Verificar o estado físico/protocolo da subinterface.",
                ))
            for ponta in enderecos["v4"]:
                if ponta not in achada.get("enderecos_v4", []):
                    items.append(_item(
                        "ponta.v4", "critica", ponta,
                        ", ".join(achada.get("enderecos_v4", []) or ["—"]),
                        "Endereço local v4 ausente na subinterface.",
                    ))
            for ponta in enderecos["v6"]:
                if ponta not in achada.get("enderecos_v6", []):
                    items.append(_item(
                        "ponta.v6", "critica", ponta,
                        ", ".join(achada.get("enderecos_v6", []) or ["—"]),
                        "Endereço local v6 ausente na subinterface.",
                    ))

    # ---- peers ----
    if snap is not None and tem_peers:
        circuitos_reservados: dict[int, models.Circuit] = {}
        for sessao in list_sessions(session, device_id=device_id):
            # reservado antes do peer.ausente: circuito sem trunk é aviso mesmo
            # quando o peer não aparece no snapshot (M2 da revisão final)
            circ = session.get(models.Circuit, sessao.circuit_id)
            if circ is not None:
                circuitos_reservados.setdefault(circ.id, circ)
            esperado = por_peer_encontrado.get((sessao.afi, sessao.remote_address))
            if esperado is None:
                items.append(_item(
                    "peer.ausente", "critica", sessao.remote_address, "não listado",
                    "Sessão ativa no SoT sem peer configurado/estabelecido no equipamento.",
                ))
                continue
            if esperado.get("asn") != sessao.asn_remote:
                items.append(_item(
                    "peer.asn", "critica", str(sessao.asn_remote), str(esperado.get("asn")),
                    "ASN do peer diverge do cadastrado.",
                ))
            estado = str(esperado.get("estado", ""))
            if sessao.shutdown:
                if estado == ESTABLISHED:
                    items.append(_item(
                        "peer.shutdown_admin", "atencao", "não Established", estado,
                        "Sessão em shutdown admin não deveria estar Established.",
                    ))
            elif estado != ESTABLISHED:
                items.append(_item(
                    "peer.estado", "atencao", ESTABLISHED, estado,
                    "Peer fora de Established — conferir se é transitório.",
                ))
            verbose = por_peer_verbose.get((sessao.afi, sessao.remote_address))
            rps = rp_por_sessao.get(sessao.id, {})
            if verbose is not None:
                for tipo_rp, campo in (
                    ("route_policy_import", "filtro_import"),
                    ("route_policy_export", "filtro_export"),
                ):
                    if tipo_rp in rps and verbose.get(campo) != rps[tipo_rp]:
                        items.append(_item(
                            "peer.filtros", "critica", rps[tipo_rp],
                            str(verbose.get(campo) or "—"),
                            "Filtro aplicado no equipamento diverge do renderizado (nomes §25.4).",
                        ))

        # circuito.sem_trunk: reservado (tem Vlan) + sessão ativa, sem edge_trunk
        if tem_interfaces:
            for circ in circuitos_reservados.values():
                tem_vlan = session.scalars(
                    select(models.Vlan.id).where(models.Vlan.circuit_id == circ.id).limit(1)
                ).first() is not None
                if circ.edge_trunk is None and tem_vlan:
                    items.append(_item(
                        "circuito.sem_trunk", "aviso", f"edge_trunk de {circ.code}",
                        "não cadastrado",
                        "Cadastrar circuits.edge_trunk para comparar a subinterface.",
                    ))

        # órfãos: peer no snapshot sem sessão ativa (afi, remote)
        ativos = {(s.afi, s.remote_address) for s in list_sessions(session, device_id=device_id)}
        for (afi, peer), linha in sorted(por_peer_encontrado.items()):
            if (afi, peer) not in ativos:
                items.append(_item(
                    "peer.orfaos", "atencao", "sessão no SoT", peer,
                    "Peer coletado sem sessão ativa cadastrada — órfão ou cadastro incompleto.",
                ))

    itens = sorted(items, key=lambda i: (i.tipo, i.esperado))
    return ReconcileResult(
        device_id=device_id,
        snapshot_id=snap.id if snap is not None else None,
        aviso="; ".join(avisos) if avisos else None,
        items=itens,
    )
