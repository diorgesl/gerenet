"""Automação de upstreams (spec §7): plano de provision/remoção agregado por
circuito vinculado + pré/pós-checks BGP do fluxo de CR.

Molde: `changes.py` (plano por device a partir do render do device, §5.1/§5.2)
e `l2vc.py` — o upstream agrega os circuitos vinculados num único plano por
device, e os checks de escopo têm o shape consumido pelo runner
(`valida_pre_upstream` retorna a primeira string de erro ou None).
"""
from sqlalchemy.orm import Session

from gerenet.automation import changes, removal, render
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.errors import ConflictError, ValidationError


def _sessoes_circuitos(session: Session, up: models.Upstream) -> list[models.BgpSession]:
    """Sessões ATIVAS dos circuitos vinculados (na ordem dos vínculos, `ordem`)."""
    return [s for vin in up.circuitos for s in list_sessions(session, circuit_id=vin.circuit_id)]


def _ids_upstream(session: Session, up: models.Upstream) -> set[int]:
    """Ids dos blocos do upstream: sessões dos circuitos vinculados + circuitos.

    R-18: blocos de subinterface têm `objeto_id = circuito.id` — sem os
    circuitos os blocos de subinterface (vlan dot1q/qinq) sairiam do plano de
    provision. Espelho de `changes.plan_provision` ({circuito.id} | ids das
    sessões).
    """
    ids: set[int] = set()
    for vin in up.circuitos:
        ids.add(vin.circuit_id)
        for s in list_sessions(session, circuit_id=vin.circuit_id):
            ids.add(s.id)
    return ids


def plan_provision_upstream(session: Session, up: models.Upstream) -> list[changes.PlanoDevice]:
    """Plano de criação por device — blocos dos circuitos vinculados no render
    do device, menos os já presentes (§5.1), agregados em um plano por device.

    Upstream desativado ⇒ ConflictError (neutro de mutação, §19); sem sessões
    ativas nos circuitos vinculados ⇒ ValidationError (plano vazio é
    inexplicável — a criação de CR de upstream exige sessões).
    """
    if not up.admin_status:
        raise ConflictError(
            f"Upstream {up.name} desativado — reative antes de planejar a mudança."
        )
    sessoes = _sessoes_circuitos(session, up)
    if not sessoes:
        raise ValidationError(
            "Upstream sem sessões ativas — cadastre circuitos e sessões antes de planejar."
        )
    ids = _ids_upstream(session, up)
    plano: list[changes.PlanoDevice] = []
    for device_id in sorted({s.device_id for s in sessoes}):
        resultado = render.render_desejado(session, device_id)
        snap = changes._ultimo_snapshot_ok(session, device_id)
        recursos = (snap.resources or {}) if snap is not None else {}
        texto = removal.texto_backup(snap)
        tem_recursos = all(k in recursos for k in changes._RECURSOS_MINIMOS)
        blocos = [
            changes._bloco_para_plano(b, "create")
            for b in resultado.blocos
            if b.tipo != "comentario"
            and (b.objeto_id in ids or b.tipo == "community_filter")
            and (not tem_recursos or not changes._ja_existe(b, recursos, texto))
        ]
        plano.append(changes.PlanoDevice(
            device_id=device_id,
            blocos=blocos,
            baseline_snapshot_id=snap.id if snap is not None and tem_recursos else None,
            aviso=None if tem_recursos else changes._SEM_RECURSOS_AVISO,
        ))
    return plano


def plan_remocao_upstream(session: Session, up: models.Upstream) -> list[changes.PlanoDevice]:
    """Plano de remoção agregado por device — inversos por circuito vinculado,
    na ordem dos vínculos (uma CR remove o upstream inteiro).

    Circuito sem sessões ou sem snapshot recente ⇒ ValidationError propagada
    de `changes.plan_remocao` (nunca plano parcial: a validação é a do
    circuito); vínculos por device são misturados num único PlanoDevice,
    preservando `baseline_snapshot_id`/`aviso` do primeiro plano por device.
    """
    if not up.circuitos:
        raise ValidationError("Upstream sem circuitos vinculados — não há o que remover.")
    misturado: dict[int, changes.PlanoDevice] = {}
    for vin in up.circuitos:  # relationship ordenada por `ordem`
        for plano_dev in changes.plan_remocao(session, vin.circuito):
            if plano_dev.device_id in misturado:
                misturado[plano_dev.device_id].blocos.extend(plano_dev.blocos)
            else:
                misturado[plano_dev.device_id] = plano_dev
    return list(misturado.values())


def valida_pre_upstream(session: Session, up: models.Upstream, device: models.Device,
                        recursos: dict, *, include_disabled: bool = False) -> str | None:
    """§12.2/§7 — recursos coletados, peers sem ASN conflitante e ao menos uma
    sessão do upstream no equipamento (shape do runner: None = ok).

    `include_disabled=True` é usado na execução de CRs de remoção (a ação é o
    contexto do chamador — o runner passa `include_disabled=(cr.acao ==
    "remove")`; a superfície não conhece a CR): sessões desativadas ainda
    cadastradas na SoT e/ou no encontrado contam como sessões. O default
    False preserva a exigência de sessão ativa para provision.

    O runner consome exatamente `pre_erro = valida_pre_upstream(...); if
    pre_erro is not None: raise ValueError(pre_erro)` (espelho de
    `valida_pre_checks_l2vc`).
    """
    if recursos.get("bgp_peers") is None:
        return "Coleta sem 'bgp_peers' — colete antes de executar (§5.3)."
    sessoes = [
        s for vin in up.circuitos
        for s in list_sessions(session, circuit_id=vin.circuit_id, device_id=device.id,
                               include_disabled=include_disabled)
    ]
    for s in sessoes:
        linha = next(
            (l for l in recursos.get("bgp_peers")
             if l.get("peer") == s.remote_address and l.get("afi") == s.afi),
            None,
        )
        if linha is not None and linha.get("asn") != s.asn_remote:
            return (
                f"Peer {s.remote_address} ({s.afi}) já consta com ASN {linha.get('asn')} "
                f"(esperado {s.asn_remote}) — configuração conflitante, revalide o circuito."
            )
    if not sessoes:
        return f"Upstream {up.name} sem sessão BGP neste equipamento — revalide o upstream."
    return None


def prefixos_recebidos(session: Session, up: models.Upstream,
                       recursos: dict, *, include_disabled: bool = False) -> dict[str, int]:
    """Soma `pref_rcv` por família nas sessões do upstream (§7.1).

    Alimenta o registro antes/depois da CR (design §5): casa cada sessão dos
    vínculos com a linha do recurso `bgp_peers` (peer + afi) e soma a
    contagem recebida. Sessão sem linha no recurso (outro device, peer
    ausente) ou com `pref_rcv` não numérico não conta; famílias sem nenhuma
    contagem ficam de fora do retorno.

    `include_disabled=True` (execução de CR de REMOÇÃO — o plano delete inclui
    as sessões desativadas, R-22/C1) faz sessões com admin_status False
    contarem; o default preserva o registro de provision (só ativas).
    """
    totais: dict[str, int] = {}
    for vin in up.circuitos:
        for s in list_sessions(session, circuit_id=vin.circuit_id,
                               include_disabled=include_disabled):
            linha = next(
                (l for l in (recursos or {}).get("bgp_peers", [])
                 if l.get("peer") == s.remote_address
                 and str(l.get("afi", "")) == s.afi),
                None,
            )
            if linha is None:
                continue
            try:
                contagem = int(linha.get("pref_rcv"))
            except (TypeError, ValueError):
                continue
            totais[s.afi] = totais.get(s.afi, 0) + contagem
    return totais


def valida_pos_upstream(session: Session, up: models.Upstream,
                        snapshot: models.DeviceSnapshot) -> list[dict]:
    """§13 pós-check upstream — por sessão no device do snapshot: peer listado,
    Established e contagem dentro de esperado×(1±margem) (§7.1).

    Pref_rcv é a chave real do parser (`merge.py`); esperado vem do upstream
    (R-13), não do maximum_prefix da sessão (proteção VRP, não alvo).
    """
    recursos = snapshot.resources or {}
    itens: list[dict] = []
    for vin in up.circuitos:  # ordem de preferência dos vínculos
        sessoes = sorted(
            (s for s in list_sessions(session, circuit_id=vin.circuit_id)
             if s.device_id == snapshot.device_id),
            key=lambda s: (s.afi, s.remote_address),
        )
        for s in sessoes:
            linha = next(
                (l for l in recursos.get("bgp_peers", [])
                 if l.get("peer") == s.remote_address and str(l.get("afi", "")) == s.afi),
                None,
            )
            if linha is None:
                itens.append({
                    "tipo": "upstream.peer_ausente", "severidade": "critica",
                    "esperado": f"{s.remote_address} ({s.afi}) — {up.name}",
                    "encontrado": "não listado",
                    "acao": f"Verificar o upstream {up.name} — peer {s.remote_address} "
                            "não listado no equipamento (display bgp peer).",
                })
                continue
            if str(linha.get("estado", "")).lower() != "established":
                itens.append({
                    "tipo": "upstream.peer_nao_estabelecido", "severidade": "critica",
                    "esperado": "established", "encontrado": str(linha.get("estado")),
                    "acao": f"Verificar o upstream {up.name} — peer {s.remote_address} "
                            "fora de established (display bgp peer).",
                })
            contagem = linha.get("pref_rcv")
            # M-11 (revisão final): snapshot parcial/corrompido pode trazer
            # `pref_rcv` como string não numérica — a contagem deixa de contar
            # em vez de TypeError derrubar o pós-check (alinhado a reconcile.py).
            if contagem is not None:
                try:
                    contagem = int(contagem)
                except (TypeError, ValueError):
                    contagem = None
            esperado = (
                up.expected_prefixes_v4 if s.afi == "ipv4" else up.expected_prefixes_v6
            )
            margem = up.max_prefix_margin_pct or 20
            if (esperado is not None and contagem is not None
                    and abs(contagem - esperado) > esperado * margem / 100):
                itens.append({
                    "tipo": "upstream.contagem_fora_esperado", "severidade": "alerta",
                    "esperado": f"{esperado} ±{margem}%", "encontrado": str(contagem),
                    "acao": f"Revalide o upstream {up.name} — contagem de rotas "
                            "recebidas acima da margem esperada.",
                })
    return itens
