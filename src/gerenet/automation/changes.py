"""Geração de plano do fluxo de mudança (spec ciclo D §5): diff do render vs.
encontrado (provision) e inversos a partir do encontrado (remove).

`PlanoDevice` carrega o que um step aplica num device + o baseline congelado
(tudo que a web/CLI exibem vem daqui; a execução re-checa §5.3 — mudou o
encontrado entre o plano e a execução ⇒ aborta).
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import removal, render
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.errors import ValidationError

_RECURSOS_MINIMOS = ("interfaces", "bgp_peers")
_SEM_RECURSOS_AVISO = (
    "Snapshot sem recursos de interfaces/peers: skip do diff vazio; "
    "a execução re-coleta antes do re-diff (§5.1)."
)


@dataclass
class PlanoDevice:
    device_id: int
    blocos: list[dict]
    baseline_snapshot_id: int | None = None
    aviso: str | None = None


def _ultimo_snapshot_ok(session: Session, device_id: int) -> models.DeviceSnapshot | None:
    return session.scalars(
        select(models.DeviceSnapshot)
        .where(
            models.DeviceSnapshot.device_id == device_id,
            models.DeviceSnapshot.status == "success",
        )
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(1)
    ).first()


def _bloco_para_plano(bloco: render.BlocoRender, acao: str) -> dict:
    return {
        "tipo": bloco.tipo, "objeto": bloco.objeto, "objeto_id": bloco.objeto_id,
        "acao": acao, "comandos": bloco.comandos,
    }


def _peer_remote(comandos: list[str]) -> str | None:
    for cmd in comandos:
        partes = cmd.split()
        if len(partes) >= 2 and partes[0] == "peer":
            return partes[1]
    return None


def _ja_existe(bloco: render.BlocoRender, recursos: dict, texto: str) -> bool:
    """§5.1 passo 3 — bloco cujos comandos já constam do encontrado (skip)."""
    if bloco.tipo == "subinterface":
        comandos = bloco.comandos or [""]
        nome = comandos[0].split(None, 1)[1] if " " in comandos[0] else ""
        return nome in {i.get("nome") for i in recursos.get("interfaces", [])}
    if bloco.tipo == "prefix_list":
        partes = bloco.comandos[0].split() if bloco.comandos else []
        if len(partes) >= 3 and partes[0] == "ip" and partes[1].endswith("-prefix"):
            return f"{partes[0]} {partes[1]} {partes[2]} index" in texto
        return False
    if bloco.tipo in ("route_policy_import", "route_policy_export"):
        partes = bloco.comandos[0].split() if bloco.comandos else []
        if len(partes) >= 2:
            return f"route-policy {partes[1]} permit node" in texto
        return False
    if bloco.tipo == "bgp_peer":
        remote = _peer_remote(bloco.comandos)
        return remote is not None and any(
            linha.get("peer") == remote for linha in recursos.get("bgp_peers", [])
        )
    return False


def plan_provision(session: Session, circuito: models.Circuit) -> list[PlanoDevice]:
    """Plano de criação por device — blocos do circuito no render, menos os já presentes."""
    sessoes = list_sessions(session, circuit_id=circuito.id)  # ativas (padrão)
    ids = {circuito.id} | {s.id for s in sessoes}
    plano: list[PlanoDevice] = []
    for device_id in sorted({s.device_id for s in sessoes}):
        resultado = render.render_desejado(session, device_id)
        snap = _ultimo_snapshot_ok(session, device_id)
        recursos = (snap.resources or {}) if snap is not None else {}
        texto = removal.texto_backup(snap)
        tem_recursos = all(k in recursos for k in _RECURSOS_MINIMOS)
        blocos = [
            _bloco_para_plano(b, "create")
            for b in resultado.blocos
            if b.tipo != "comentario"
            and b.objeto_id in ids
            and (not tem_recursos or not _ja_existe(b, recursos, texto))
        ]
        plano.append(PlanoDevice(
            device_id=device_id,
            blocos=blocos,
            baseline_snapshot_id=snap.id if snap is not None and tem_recursos else None,
            aviso=None if tem_recursos else _SEM_RECURSOS_AVISO,
        ))
    return plano


def plan_remocao(session: Session, circuito: models.Circuit) -> list[PlanoDevice]:
    """Plano de remoção por device — inversos a partir do ENCONTRADO (§5.2,
    todas as sessões do circuito, ativas ou desativadas).

    Exige snapshot success com recursos por device: sem ele, ValidationError
    (colete antes — nunca um plano de remoção otimista).
    """
    sessoes = list_sessions(session, circuit_id=circuito.id, include_disabled=True)
    devices = sorted({s.device_id for s in sessoes})
    if not devices:
        raise ValidationError(f"Circuito {circuito.code} sem sessões BGP — não há o que remover.")
    plano: list[PlanoDevice] = []
    for device_id in devices:
        snap = _ultimo_snapshot_ok(session, device_id)
        recursos = (snap.resources or {}) if snap is not None else {}
        sem_recursos = snap is None or not all(k in recursos for k in _RECURSOS_MINIMOS)
        if sem_recursos:
            raise ValidationError(
                f"Circuito {circuito.code}: sem snapshot recente com recursos no device "
                f"{device_id} — colete antes de planejar a remoção (§5.2)."
            )
        plano.append(PlanoDevice(
            device_id=device_id,
            blocos=removal.blocos_remocao(session, circuito, device_id, snapshot=snap),
            baseline_snapshot_id=snap.id,
        ))
    return plano
