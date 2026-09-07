"""Automação L2VC (spec §6): render dos ACs, planos e pré/pós-checks.

Usa o maquinário de `changes.py` (PlanoDevice, snapshot da última coleta)
e `render.py` (BlocoRender, templates), sem tocar no fluxo de circuito.
"""
import re

from sqlalchemy.orm import Session

from gerenet.automation import changes
from gerenet.automation.naming import subinterface
from gerenet.automation.render import BlocoRender, _render_template
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import _membro_loopback, get_l2vc

_SEM_L2VC_AVISO = (
    "Sem coleta do recurso 'l2vc' — plano gerado sem diff confiável; "
    "a execução re-valida (gate §5.3) e pode pular blocos já presentes."
)


def _par_loopback(session: Session, service: models.L2vcService, device_id: int) -> str:
    """Loopback LDP do PAR do endpoint (membro do domínio; exigido na criação)."""
    for ep in service.endpoints:
        if ep.device_id == device_id:
            continue
        loopback = _membro_loopback(session, service.domain_id, ep.device_id)
        if loopback is None:
            raise ValidationError(
                f"Par {ep.device_id} sem loopback LDP no domínio — revalide o serviço."
            )
        return loopback
    raise ValidationError("Serviço L2VC sem pontas — revalide o serviço.")


def render_l2vc(session: Session, service: models.L2vcService) -> dict[int, list[BlocoRender]]:
    """Blocos create por device (A/B) derivados da SoT via template."""
    service = get_l2vc(session, service.id)  # endpoints carregados
    por_device: dict[int, list[BlocoRender]] = {}
    loopbacks = {ep.device_id: _par_loopback(session, service, ep.device_id) for ep in service.endpoints}
    devices = {ep.device_id: session.get(models.Device, ep.device_id) for ep in service.endpoints}
    for ep in service.endpoints:
        vlan = session.get(models.Vlan, ep.vlan_id) if ep.vlan_id else None
        if vlan is None:
            raise ValidationError(
                f"Ponta {ep.interface} do serviço {service.name} sem VLAN reservada."
            )
        dev = devices[ep.device_id]
        support_fc = "mpls_flow_label" in (dev.capabilities or [])
        comandos = _render_template("l2vc_ac", {
            "interface": subinterface(ep.interface, vlan.vid),
            "vid": vlan.vid,
            "inner_vlan": ep.inner_vlan,
            "encapsulation": ep.encapsulation,
            "vc_id": service.vc_id,
            "remote_loopback": loopbacks[ep.device_id],
            "control_word": service.control_word,
            "flow_label": service.flow_label and support_fc,
            "mtu": ep.mtu or service.mtu,
        }).splitlines()  # _render_template devolve str; callers fazem .splitlines() (padrão _bloco_sub)
        por_device.setdefault(ep.device_id, []).append(BlocoRender(
            tipo="l2vc_ac", objeto="l2vc", objeto_id=service.id, comandos=comandos,
        ))
    return por_device


def estado_bloco_l2vc(bloco: dict, recursos: dict) -> str:
    """Presença do AC no encontrado, por identidade (vc-id + subinterface)."""
    comandos = bloco.get("comandos") or []
    if not comandos:
        return "ausente"
    partes = comandos[0].split(None, 1)
    if len(partes) < 2:
        return "ausente"
    nome = partes[1]
    if partes[0] == "undo":
        nome = nome.split(" ", 1)[1] if " " in nome else nome
    encontradas = [i for i in recursos.get("interfaces", []) if i.get("nome") == nome]
    vc_id = None
    for cmd in comandos:
        m = re.search(r"mpls l2vc (\d+)", cmd)
        if m:
            vc_id = int(m.group(1))
            break
    if bloco.get("acao", "create") == "delete":
        return "consta" if encontradas else "ausente"
    if not encontradas:
        return "ausente"
    if vc_id is None:
        return "conflito"
    linhas = [l for l in recursos.get("l2vc", []) if l.get("vc_id") == vc_id]
    if not linhas:
        return "conflito"  # subinterface presente sem o VC: parcial/mudada desde o plano
    if linhas[0].get("interface") not in (None, nome):
        return "conflito"
    return "consta"


_RECURSOS_L2VC = ("interfaces", "l2vc")
"""Recursos mínimos para diff confiável de um AC (espelho de `_RECURSOS_MINIMOS`)."""


def _recursos_snapshot(snap: models.DeviceSnapshot | None) -> tuple[dict, bool]:
    """(recursos, tem_l2vc) — recursos do snapshot ok, ou ({}, False) se vazio."""
    if snap is None or snap.resources is None:
        return {}, False
    return snap.resources, all(k in snap.resources for k in _RECURSOS_L2VC)


def plan_provision_l2vc(session: Session, service: models.L2vcService) -> list[changes.PlanoDevice]:
    """Plano de criação por ponta — blocos do render, menos os já presentes (§5.1)."""
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_l2vc(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if tem:
            a_aplicar = [
                changes._bloco_para_plano(b, "create")
                for b in blocos
                if estado_bloco_l2vc(changes._bloco_para_plano(b, "create"), recursos) != "consta"
            ]
        else:
            a_aplicar = [changes._bloco_para_plano(b, "create") for b in blocos]
        plano.append(changes.PlanoDevice(
            device_id=device_id,
            blocos=a_aplicar,
            baseline_snapshot_id=snap.id if snap is not None and tem else None,
            aviso=None if tem else _SEM_L2VC_AVISO,
        ))
    return plano


def plan_remocao_l2vc(session: Session, service: models.L2vcService) -> list[changes.PlanoDevice]:
    """Blocos delete por ponta; snapshot fresco obrigatório (padrão plan_remocao, §5.2).

    A identidade da remoção é a subinterface no recurso `interfaces` (o AC inteiro
    cai com `undo interface <sub>`), sem precisar do texto do backup.
    """
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_l2vc(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if not tem:
            raise ValidationError(
                "Sem snapshot recente com 'l2vc' para gerar a remoção — colete antes de remover (§5.2)."
            )
        a_remover: list[dict] = []
        for bloco in blocos:
            item = changes._bloco_para_plano(bloco, "delete")
            if bloco.comandos:
                item["comandos"] = [f"undo {bloco.comandos[0]}"]  # "interface X" -> "undo interface X"
            if estado_bloco_l2vc(item, recursos) == "consta":
                a_remover.append(item)
        plano.append(changes.PlanoDevice(
            device_id=device_id, blocos=a_remover, baseline_snapshot_id=snap.id,
        ))
    return plano


def valida_pre_checks_l2vc(session: Session, service: models.L2vcService, device: models.Device,
                           recursos: dict) -> str | None:
    """§12.2/§9.2 — peer LDP UP, sem binding conflitante, simetria (SoT)."""
    par_loopback = _par_loopback(session, service, device.id)
    ldp = recursos.get("mpls_ldp_peer")
    if ldp is None:
        return ("Coleta sem 'mpls_ldp_peer' — colete antes de executar (§5.3).")
    achado = next((l for l in ldp if l.get("peer_id") == par_loopback), None)
    if achado is None or str(achado.get("estado", "")).lower() != "up":
        return f"Par LDP {par_loopback} não está UP na coleta do {device.name} (§9.2)."
    ep = next((e for e in service.endpoints if e.device_id == device.id), None)
    if ep is None:
        return "Serviço L2VC sem ponta neste equipamento — revalide o serviço."
    vlan = session.get(models.Vlan, ep.vlan_id) if ep.vlan_id is not None else None
    esperado = subinterface(ep.interface, vlan.vid) if vlan is not None else ep.interface
    vc_linhas = [l for l in recursos.get("l2vc", []) if l.get("vc_id") == service.vc_id]
    if vc_linhas and vc_linhas[0].get("interface") not in (None, esperado):
        return (f"Binding conflitante: VC {service.vc_id} já está na interface "
                f"{vc_linhas[0].get('interface')} (esperado {esperado}).")
    # simetria (SoT): regex já imposta na criação; re-verifica aqui (§6)
    if len(service.endpoints) != 2:
        return "Serviço L2VC sem as duas pontas — revalide o serviço."
    e0, e1 = service.endpoints
    if e0.encapsulation != e1.encapsulation or (e0.mtu or service.mtu) != (e1.mtu or service.mtu):
        return "Pontas do L2VC assimétricas (encap/MTU) — revalide o serviço."
    return None


def valida_pos_l2vc(session: Session, service: models.L2vcService, snapshot: models.DeviceSnapshot) -> list[dict]:
    """Pós-check §13 — VC presente e UP na coleta pós-aplicação."""
    recursos = snapshot.resources or {}
    linhas = [l for l in recursos.get("l2vc", []) if l.get("vc_id") == service.vc_id]
    achada = linhas[0] if linhas else None
    items: list[dict] = []
    if achada is None:
        items.append({
            "tipo": "l2vc.ausente", "severidade": "critica",
            "esperado": f"{service.name} (vc {service.vc_id})", "encontrado": "nao listado",
            "acao": "Verificar config do AC e revalidar (display l2vc).",
        })
    elif str(achada.get("estado", "")).lower() != "up":
        items.append({
            "tipo": "l2vc.estado", "severidade": "critica",
            "esperado": "up", "encontrado": str(achada.get("estado")),
            "acao": "Verificar estado do pseudowire/AC (LDP up, MTU, encap simétrico).",
        })
    return items
