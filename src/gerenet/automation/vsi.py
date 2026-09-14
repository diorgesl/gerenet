"""Automação VSI multiponto (spec §9.3): render, planos e pré/pós-checks.

Usa o maquinário de `changes.py` (PlanoDevice, snapshot da última coleta) e de
`render.py` (BlocoRender, templates). Dois blocos por PE, na ordem em que o VRP
aceita: o VSI primeiro e o AC depois; a remoção inverte.
"""
import re

from sqlalchemy.orm import Session

from gerenet.automation import changes
from gerenet.automation.render import BlocoRender, _render_template
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError
from gerenet.domain.services.mpls import _membro_loopback, get_vsi

_SEM_VSI_AVISO = (
    "Sem coleta do recurso 'vsi' — plano gerado sem diff confiável; "
    "a execução re-valida (gate §5.3) e pode pular blocos já presentes."
)
_RECURSOS_VSI = ("vsi",)


def _peers(session: Session, service: models.VsiService, device_id: int) -> list[str]:
    """Loopbacks LDP dos OUTROS membros — é o que cada PE usa como peer."""
    peers: list[str] = []
    for ep in service.endpoints:
        if ep.device_id == device_id:
            continue
        loopback = _membro_loopback(session, service.domain_id, ep.device_id)
        if loopback is None:
            raise ValidationError(
                f"Par {ep.device_id} sem loopback LDP no domínio — revalide o serviço."
            )
        peers.append(loopback)
    if not peers:
        raise ValidationError("VSI sem peers: precisa de pelo menos dois membros.")
    return sorted(peers)


def render_vsi(session: Session, service: models.VsiService) -> dict[int, list[BlocoRender]]:
    """Blocos por device: `vsi` (o serviço) e `vsi_ac` (a ponta), nessa ordem."""
    service = get_vsi(session, service.id)
    por_device: dict[int, list[BlocoRender]] = {}
    for ep in service.endpoints:
        vlan = session.get(models.Vlan, ep.vlan_id) if ep.vlan_id else None
        if vlan is None:
            raise ValidationError(
                f"Ponta {ep.interface} do VSI {service.name} sem VLAN reservada."
            )
        dev = session.get(models.Device, ep.device_id)
        suporta_fc = "mpls_flow_label" in (dev.capabilities or [])
        comandos_vsi = _render_template("vsi", {
            "vrp_name": service.vrp_name,
            "description": service.description,
            "vsi_id": service.vsi_id,
            "flow_label": service.flow_label and suporta_fc,
            "peers": _peers(session, service, ep.device_id),
            "mtu": service.mtu,
        }).splitlines()
        comandos_ac = _render_template("vsi_ac", {
            "vid": vlan.vid,
            "description": service.description,
            "vrp_name": service.vrp_name,
        }).splitlines()
        por_device.setdefault(ep.device_id, []).extend([
            BlocoRender(tipo="vsi", objeto="vsi", objeto_id=service.id, comandos=comandos_vsi),
            BlocoRender(tipo="vsi_ac", objeto="vsi", objeto_id=service.id, comandos=comandos_ac),
        ])
    return por_device


def estado_bloco_vsi(bloco: dict, recursos: dict) -> str:
    """Presença do bloco no encontrado, por identidade (nome VRP e Vlanif).

    O bloco do AC é identificado pela `Vlanif<vid>` e o do VSI pelo nome VRP,
    tanto na criação quanto na remoção, e o despacho é pelo `tipo` do bloco
    (`changes._bloco_para_plano` o grava e o `plano_json` do runner o carrega).
    O despacho importa: a `description` do serviço sai nos DOIS blocos (o
    `vsi.j2` a renderiza dentro do bloco do VSI), então varrer o texto inteiro
    por `Vlanif\\d+` lia a descrição como se fosse o AC — uma descrição citando
    `Vlanif900` fazia o bloco do VSI ser julgado pelo AC de OUTRO serviço, e a
    identidade real (nome VRP) nunca era consultada (revisão final, I1). Sem
    `tipo` — bloco de chamada antiga —, o fallback varre o texto todo, na ordem
    antiga.

    O snapshot não guarda o nome do VSI ligado ao AC (o `display` não o mostra),
    então um binding de outro serviço aparece aqui como "consta"; quem barra
    esse caso é o pré-check.
    """
    comandos = bloco.get("comandos") or []
    if not comandos:
        return "ausente"
    linhas = recursos.get("vsi", []) or []
    if bloco.get("tipo") == "vsi":
        # identidade = nome VRP da 1ª linha: `vsi <nome> static` ou `undo vsi <nome>`
        partes = comandos[0].split()
        if partes[:1] == ["undo"]:
            nome = partes[2] if len(partes) >= 3 and partes[1] == "vsi" else None
        else:
            nome = partes[1] if len(partes) >= 2 and partes[0] == "vsi" else None
        if nome is None:  # fora do render conhecido: não inventa identidade
            return "ausente"
        return "consta" if any(l.get("name") == nome for l in linhas) else "ausente"
    # AC: a `Vlanif<vid>` da linha `interface` — no `vsi_ac.j2` ela vem ANTES do
    # `description`, então o primeiro match do texto é a identidade do bloco.
    texto = " ".join(comandos)
    m_if = re.search(r"\b(Vlanif\d+)\b", texto)
    if m_if is not None:
        iface = m_if.group(1)
        return "consta" if any(
            ac.get("interface") == iface for l in linhas for ac in (l.get("acs") or [])
        ) else "ausente"
    m_vsi = re.search(r"\bvsi (\S+)", texto)  # fallback: bloco sem `tipo`
    if m_vsi is not None:
        return "consta" if any(l.get("name") == m_vsi.group(1) for l in linhas) else "ausente"
    return "ausente"


def _recursos_snapshot(snap: models.DeviceSnapshot | None) -> tuple[dict, bool]:
    if snap is None or snap.resources is None:
        return {}, False
    return snap.resources, all(k in snap.resources for k in _RECURSOS_VSI)


def plan_provision_vsi(session: Session, service: models.VsiService) -> list[changes.PlanoDevice]:
    """Plano de criação por PE — blocos do render, menos os já presentes (§5.1)."""
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_vsi(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if tem:
            a_aplicar = [
                changes._bloco_para_plano(b, "create")
                for b in blocos
                if estado_bloco_vsi(changes._bloco_para_plano(b, "create"), recursos) != "consta"
            ]
        else:
            a_aplicar = [changes._bloco_para_plano(b, "create") for b in blocos]
        plano.append(changes.PlanoDevice(
            device_id=device_id, blocos=a_aplicar,
            baseline_snapshot_id=snap.id if snap is not None and tem else None,
            aviso=None if tem else _SEM_VSI_AVISO,
        ))
    return plano


def plan_remocao_vsi(session: Session, service: models.VsiService) -> list[changes.PlanoDevice]:
    """Blocos delete por PE, do AC para o VSI (o VRP recusa remover VSI com AC ligado)."""
    plano: list[changes.PlanoDevice] = []
    for device_id, blocos in render_vsi(session, service).items():
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos, tem = _recursos_snapshot(snap)
        if not tem:
            # com 3+ PEs a mensagem sem o nome não diz QUAL switch coletar
            dev = session.get(models.Device, device_id)
            nome = dev.name if dev is not None else f"device {device_id}"
            raise ValidationError(
                f"Sem snapshot recente com 'vsi' no {nome} para gerar a remoção — "
                "colete antes (§5.2)."
            )
        a_remover: list[dict] = []
        por_tipo = {b.tipo: b for b in blocos}
        for tipo in ("vsi_ac", "vsi"):
            bloco = por_tipo.get(tipo)
            if bloco is None:
                continue
            item = changes._bloco_para_plano(bloco, "delete")
            if tipo == "vsi":
                # `undo vsi` roda na visão de sistema: sem linha de contexto
                item["comandos"] = [f"undo vsi {service.vrp_name}"]
            else:
                # o binding mora dentro da interface: contexto + undo
                item["comandos"] = [
                    bloco.comandos[1],
                    f"undo l2 binding vsi {service.vrp_name}",
                ]
            if estado_bloco_vsi(item, recursos) == "consta":
                a_remover.append(item)
        plano.append(changes.PlanoDevice(
            device_id=device_id, blocos=a_remover, baseline_snapshot_id=snap.id,
        ))
    return plano


def valida_pre_checks_vsi(
    session: Session, service: models.VsiService, device: models.Device, recursos: dict,
) -> str | None:
    """§12.2/§9.2 — sessão LDP UP com cada peer, sem binding alheio na Vlanif.

    A simetria da SoT vem antes das checagens de equipamento (no L2VC ela fica
    no fim): aqui ela é a cobertura de membros, e é ela que dá a mensagem certa
    quando o serviço está malformado — sem isso o `_peers` abaixo estouraria
    antes, com um erro de outra natureza.
    """
    # simetria (SoT §6): todo membro do serviço tem a sua ponta, e são pelo
    # menos dois. O MTU fica fora da comparação: no VSI ele é campo do serviço
    # (um só, não um por ponta) e o AC não o renderiza, então não há o par de
    # MTUs do L2VC — quem compara com o coletado é o pós-check.
    if len(service.members) < 2:
        return "VSI com menos de dois membros — revalide o serviço."
    if len(service.endpoints) != len(service.members):
        return "VSI com membro sem ponta — revalide o serviço."
    peers = _peers(session, service, device.id)
    ldp = recursos.get("mpls_ldp_peer")
    if ldp is None:
        return "Coleta sem 'mpls_ldp_peer' — colete antes de executar (§5.3)."
    for peer in peers:
        achado = next((l for l in ldp if l.get("peer_id") == peer), None)
        if achado is None:
            return f"Par LDP {peer} não listado na coleta do {device.name} (§9.2)."
        if achado.get("estado") is None:
            return (f"Estado do par LDP {peer} desconhecido na coleta do {device.name} — "
                    f"cole e a sessão LDP (§9.2).")
        if achado.get("estado") != "up":
            return f"Par LDP {peer} não está UP na coleta do {device.name} (§9.2)."
    ep = next((e for e in service.endpoints if e.device_id == device.id), None)
    if ep is None:
        return "VSI sem ponta neste equipamento — revalide o serviço."
    for linha in recursos.get("vsi", []) or []:
        if linha.get("name") == service.vrp_name:
            continue
        for ac in linha.get("acs", []) or []:
            if ac.get("interface") == ep.interface:
                return (f"Binding conflitante: {ep.interface} já serve o VSI "
                        f"{linha.get('name')}.")
    return None


def valida_pos_vsi(
    session: Session, service: models.VsiService, snapshot: models.DeviceSnapshot,
) -> list[dict]:
    """Pós-check §13 — VSI, cada pseudowire e o AC da ponta desta coleta."""
    recursos = snapshot.resources or {}
    linhas = [l for l in recursos.get("vsi", []) if l.get("name") == service.vrp_name]
    achado = linhas[0] if linhas else None
    items: list[dict] = []
    if achado is None:
        items.append({
            "tipo": "vsi.ausente", "severidade": "critica",
            "esperado": f"{service.name} ({service.vrp_name})", "encontrado": "não listado",
            "acao": "Verificar a config do VSI (display vsi verbose).",
        })
        return items
    if str(achado.get("estado", "")).lower() != "up":
        items.append({
            "tipo": "vsi.estado", "severidade": "critica",
            "esperado": "up", "encontrado": str(achado.get("estado")),
            "acao": "Verificar LDP, peers e MTU do VSI (§9.3).",
        })
    for peer in achado.get("peers", []) or []:
        if str(peer.get("estado") or "").lower() != "up":
            items.append({
                "tipo": "vsi.peer", "severidade": "critica",
                "esperado": "up", "encontrado": f"{peer.get('peer')}: {peer.get('estado')}",
                "acao": "Conferir o pseudowire e a sessão LDP com o outro PE (§9.3).",
            })
    ep = next((e for e in service.endpoints if e.device_id == snapshot.device_id), None)
    if ep is not None:
        for ac in achado.get("acs", []) or []:
            if ac.get("interface") != ep.interface:
                continue
            if str(ac.get("estado") or "").lower() != "up":
                items.append({
                    "tipo": "vsi.ac", "severidade": "atencao",
                    "esperado": "up", "encontrado": str(ac.get("estado")),
                    "acao": "Conferir o l2 binding e a Vlanif desta ponta.",
                })
    if achado.get("mtu") is not None and int(achado["mtu"]) != service.mtu:
        items.append({
            "tipo": "vsi.mtu", "severidade": "atencao",
            "esperado": str(service.mtu), "encontrado": str(achado["mtu"]),
            "acao": "Conferir o mtu do VSI e reaplicar (§9.3).",
        })
    return items
