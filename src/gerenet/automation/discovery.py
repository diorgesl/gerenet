"""Descoberta de peers: o que o equipamento tem e a SoT não conhece (spec §4–§5).

Somente leitura. O motor lê o `display current-configuration` já gravado no
snapshot, cruza com as sessões da SoT e a lista de ignorados, e devolve cada
peer desconhecido com o palpite de classificação e o motivo que o sustenta.
"""
import ipaddress
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

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
