"""Render inverso (remoção) para o fluxo de mudança (spec ciclo D §5.2).

Gera blocos `delete` a partir do ENCONTRADO no snapshot (nunca do desejado):
`undo peer`, `undo route-policy`, `undo ip-prefix`, `undo interface`, na ordem
inversa à criação (peer → RP export → RP import → prefix-list → subinterface).
Regras de segurança:
- `undo peer <ip>` completo só quando NENHUMA outra sessão de outro circuito
  referencia o mesmo remote no device; senão undo por família
  (`undo peer <ip> enable`) — não derruba o par alheio. Qualquer sessão de
  outro circuito (ativa OU desativada) protege: a config dela pode existir.
- `undo route-policy`/`undo ip-prefix` só quando nenhuma outra sessão do mesmo
  (asn_remote, afi) os referencia no device — nomes §25.4 derivam do ASN.
- Definições §25.4 e peers são deduplicados por (tipo, nome)/(afi, remote):
  re-peering (sessão ativa + legada desativada no mesmo circuito) gera um UNDO
  por definição, espelhando o `_apensa_definicao` do render forward.
- Sem snapshot com os recursos `bgp_peers` E `interfaces` ⇒ [] (exige coleta
  fresca antes do planejamento §5.2; recursos vazios não inventam plano).
"""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation import naming
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions


def texto_backup(snapshot: models.DeviceSnapshot | None) -> str:
    """Texto do `display current-configuration` salvo no snapshot (ou "")."""
    if snapshot is None:
        return ""
    arquivos = (snapshot.raw_files or {}).get("config_backup", [])
    if not arquivos:
        return ""
    try:
        return Path(str(arquivos[0])).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tem_prefix_list(texto: str, afi: str, nome: str) -> bool:
    cmd = "ip ipv6-prefix" if afi == "ipv6" else "ip ip-prefix"
    return f"{cmd} {nome} index" in texto


def _tem_route_policy(texto: str, nome: str) -> bool:
    return f"route-policy {nome} permit node" in texto


def _tem_peer(recursos: dict, remote: str) -> bool:
    return any(linha.get("peer") == remote for linha in recursos.get("bgp_peers", []))


def _outras_sessoes(
    session: Session, device_id: int, circuito_id: int
) -> list[models.BgpSession]:
    """Sessões de OUTROS circuitos no mesmo device (ativas ou desativadas)."""
    return [
        s for s in list_sessions(session, device_id=device_id, include_disabled=True)
        if s.circuit_id != circuito_id
    ]


def blocos_remocao(
    session: Session, circuito: models.Circuit, device_id: int, *,
    snapshot: models.DeviceSnapshot | None,
) -> list[dict]:
    """Blocos delete do circuito num device, a partir do snapshot (ver docstring)."""
    recursos = (snapshot.resources or {}) if snapshot is not None else {}
    # Gate total: sem os recursos coletados ESTRUTURADAMENTE não há plano — o
    # texto do backup sozinho geraria um plano parcial (RP/prefix sem o peer).
    if recursos.get("bgp_peers") is None or recursos.get("interfaces") is None:
        return []
    texto = texto_backup(snapshot)
    sessoes = [
        s for s in list_sessions(session, circuit_id=circuito.id, include_disabled=True)
        if s.device_id == device_id
    ]
    outras = _outras_sessoes(session, device_id, circuito.id)
    blocos: list[dict] = []
    ja_undo_completo: set[str] = set()
    ja_undo_por_familia: set[tuple[str, str]] = set()  # (afi, remote)

    # 1) peers (ordem por afi/remote; 1 bloco por sessão — dedup por "undo")
    for sessao in sorted(sessoes, key=lambda s: (s.afi, s.remote_address)):
        if not _tem_peer(recursos, sessao.remote_address):
            continue
        compartilhado = any(
            outra.remote_address == sessao.remote_address for outra in outras
        )
        if compartilhado:
            chave = (sessao.afi, sessao.remote_address)
            if chave in ja_undo_por_familia:
                continue
            ja_undo_por_familia.add(chave)
            blocos.append({
                "tipo": "bgp_peer", "objeto": "session", "objeto_id": sessao.id,
                "acao": "delete",
                "comandos": [
                    f"bgp {sessao.asn_local}",
                    f"{sessao.afi}-family unicast",
                    f"undo peer {sessao.remote_address} enable",
                ],
            })
        elif sessao.remote_address not in ja_undo_completo:
            ja_undo_completo.add(sessao.remote_address)
            blocos.append({
                "tipo": "bgp_peer", "objeto": "session", "objeto_id": sessao.id,
                "acao": "delete",
                "comandos": [f"bgp {sessao.asn_local}", f"undo peer {sessao.remote_address}"],
            })

    # 2) route-policy export/import + prefix-lists (nome por ASN+afi §25.4).
    # Dedup por (tipo, nome)/(afi, nome): re-peering no mesmo circuito gera UM
    # undo por definição — espelha o _apensa_definicao do render forward.
    prefix_lists: dict[tuple[str, str], int] = {}  # (afi, nome) -> id da 1ª sessão
    definicoes_vistas: set[tuple[str, str]] = set()  # (tipo, nome) já emitidos
    for sessao in sorted(sessoes, key=lambda s: (s.afi, s.remote_address)):
        if sessao.asn_remote is None:
            continue
        nomes_compartilhados = any(
            outra.asn_remote == sessao.asn_remote and outra.afi == sessao.afi
            for outra in outras
        )
        if nomes_compartilhados:
            continue
        afi = sessao.afi
        nome_export = naming.rp_export(sessao.asn_remote, afi)
        if (
            _tem_route_policy(texto, nome_export)
            and ("route_policy_export", nome_export) not in definicoes_vistas
        ):
            definicoes_vistas.add(("route_policy_export", nome_export))
            blocos.append({
                "tipo": "route_policy_export", "objeto": "session",
                "objeto_id": sessao.id, "acao": "delete",
                "comandos": [f"undo route-policy {nome_export}"],
            })
        nome_import = naming.rp_import(sessao.asn_remote, afi)
        if (
            _tem_route_policy(texto, nome_import)
            and ("route_policy_import", nome_import) not in definicoes_vistas
        ):
            definicoes_vistas.add(("route_policy_import", nome_import))
            blocos.append({
                "tipo": "route_policy_import", "objeto": "session",
                "objeto_id": sessao.id, "acao": "delete",
                "comandos": [f"undo route-policy {nome_import}"],
            })
        nome_pfx = naming.pfx_in(sessao.asn_remote, afi)
        if _tem_prefix_list(texto, afi, nome_pfx) and (afi, nome_pfx) not in prefix_lists:
            prefix_lists[(afi, nome_pfx)] = sessao.id

    # 3) prefix-lists (1 undo por nome, atribuído à 1ª sessão que o referencia)
    for (afi, nome), sessao_id in sorted(prefix_lists.items()):
        cmd = "undo ip ipv6-prefix" if afi == "ipv6" else "undo ip ip-prefix"
        blocos.append({
            "tipo": "prefix_list", "objeto": "session", "objeto_id": sessao_id,
            "acao": "delete", "comandos": [f"{cmd} {nome}"],
        })

    # 4) subinterfaces (1 undo por nome existente no snapshot)
    if circuito.edge_trunk and (
        circuito.edge_device_id == device_id or circuito.backup_edge_device_id == device_id
    ):
        nomes = {
            naming.subinterface(circuito.edge_trunk, vlan.vid)
            for vlan in session.scalars(
                select(models.Vlan).where(models.Vlan.circuit_id == circuito.id)
            )
        }
        existentes = {i["nome"] for i in recursos.get("interfaces", [])}
        for nome in sorted(nomes & existentes):
            blocos.append({
                "tipo": "subinterface", "objeto": "circuit",
                "objeto_id": circuito.id, "acao": "delete",
                "comandos": [f"undo interface {nome}"],
            })
    return blocos
