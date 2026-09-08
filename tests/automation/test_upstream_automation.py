"""Automação de upstream (spec §7): plano agregado de provision/remoção e
pré/pós-checks BGP do fluxo de CR (espelho de `tests/automation/test_l2vc.py`)."""
import pytest
from sqlalchemy import select

from gerenet.automation.upstream import (
    plan_provision_upstream,
    plan_remocao_upstream,
    valida_pos_upstream,
    valida_pre_upstream,
)
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.errors import ConflictError, ValidationError

# ---- helpers (shape do parser merge.py: afi/peer/asn/estado/pref_rcv/up_down) ----

def _peers_up(
    *,
    afi: str = "ipv4",
    peer: str = "100.64.10.2",
    asn: int = 64501,
    estado: str = "Established",
    pref_rcv: int = 1000,
) -> list[dict]:
    """Linha `bgp_peers` no shape real do parser (NÃO a chave morta 'prefixos')."""
    return [{"afi": afi, "peer": peer, "asn": asn, "estado": estado,
             "pref_rcv": pref_rcv, "up_down": "1d02h"}]


def _snapshot_up(session, edge_device: models.Device, peers: list[dict]) -> models.DeviceSnapshot:
    """Snapshot success do edge com recursos mínimos (interfaces vazias; §5.1)."""
    snap = models.DeviceSnapshot(
        device_id=edge_device.id, status="success", resources={"interfaces": [], "bgp_peers": peers},
        errors={}, raw_files={}, duration_ms=0,
    )
    session.add(snap)
    session.commit()
    return snap


def _ids_up(session, up: models.Upstream) -> set[int]:
    """Ids esperados no provision: sessões dos circuitos vinculados + circuitos (R-18)."""
    ids: set[int] = {vin.circuit_id for vin in up.circuitos}
    for vin in up.circuitos:
        ids |= {s.id for s in list_sessions(session, circuit_id=vin.circuit_id)}
    return ids


# ---- plan_provision_upstream ----

def test_plan_provision_upstream_agrega_por_device(session, up_com_2_circuitos, edge_device):
    """2 circuitos no mesmo edge ⇒ 1 PlanoDevice com os blocos dos 2 (sem hard-code)."""
    plano = plan_provision_upstream(session, up_com_2_circuitos)
    assert len(plano) == 1  # 2 circuitos no mesmo edge
    plano_edge = plano[0]
    assert plano_edge.device_id == edge_device.id
    assert plano_edge.blocos  # sessões dos 2 circuitos renderizam (fail-safe §4.1)
    ids = _ids_up(session, up_com_2_circuitos)
    assert all(
        b["objeto_id"] in ids or b["tipo"] == "community_filter" for b in plano_edge.blocos
    )
    # tipo::session do peer do circuito 2 também entrou (filtro por sessão)
    assert "bgp_peer" in {b["tipo"] for b in plano_edge.blocos}


def test_plan_provision_upstream_desativado_conflita(session, up_com_2_circuitos):
    """admin_status False ⇒ ConflictError antes de planejar (§7)."""
    up_com_2_circuitos.admin_status = False
    session.commit()
    with pytest.raises(ConflictError):
        plan_provision_upstream(session, up_com_2_circuitos)


def test_plan_provision_upstream_vinculo_sem_sessoes_invalida(session, up_com_circuito):
    """Vínculo existe mas sem sessão ativa ⇒ ValidationError (não só `ids` —
    R-18 inclui circuit_id em ids, o gate tem que ser por sessões)."""
    with pytest.raises(ValidationError):
        plan_provision_upstream(session, up_com_circuito)


def test_plan_provision_upstream_sem_vinculos_invalida(session, up):
    """Upstream sem nenhum vínculo ⇒ ValidationError."""
    with pytest.raises(ValidationError):
        plan_provision_upstream(session, up)


# ---- plan_remocao_upstream ----

def test_plan_remocao_upstream_mistura_por_device(session, up_com_2_circuitos, edge_device):
    """2 circuitos no mesmo edge ⇒ 1 PlanoDevice; blocos na ordem dos vínculos."""
    circuitos = [vin.circuito for vin in up_com_2_circuitos.circuitos]
    [s1] = list_sessions(session, circuit_id=circuitos[0].id)
    [s2] = list_sessions(session, circuit_id=circuitos[1].id)
    peers = _peers_up(peer=s1.remote_address) + _peers_up(peer=s2.remote_address)
    _snapshot_up(session, edge_device, peers)

    plano = plan_remocao_upstream(session, up_com_2_circuitos)
    assert len(plano) == 1  # mistura por device: sem plano parcial
    plano_edge = plano[0]
    assert plano_edge.device_id == edge_device.id
    # ordem dos vínculos (ordem 1 antes de ordem 2) preservada na concatenação
    assert [b["objeto_id"] for b in plano_edge.blocos] == [s1.id, s2.id]
    assert all(b["tipo"] == "bgp_peer" and b["acao"] == "delete" for b in plano_edge.blocos)


def test_plan_remocao_upstream_vinculo_sem_sessoes_invalida(session, up_com_circuito):
    """Circuito vinculado sem sessões ⇒ ValidationError propagada (sem plano parcial)."""
    with pytest.raises(ValidationError):
        plan_remocao_upstream(session, up_com_circuito)


def test_plan_remocao_upstream_sem_vinculos_invalida(session, up):
    """Upstream sem vínculos ⇒ ValidationError (plano vazio silencioso é inexplicável)."""
    with pytest.raises(ValidationError):
        plan_remocao_upstream(session, up)


# ---- valida_pre_upstream (shape do runner: (session, up, device, recursos) -> str | None) ----

def test_valida_pre_upstream_sem_coleta_informa_erro(session, up_com_2_circuitos, edge_device):
    """Sem 'bgp_peers' no encontrado ⇒ erro de coleta (§5.3)."""
    erro = valida_pre_upstream(session, up_com_2_circuitos, edge_device, {})
    assert erro == "Coleta sem 'bgp_peers' — colete antes de executar (§5.3)."


def test_valida_pre_upstream_peer_com_asn_conflitante_informa_erro(
    session, up_com_2_circuitos, edge_device
):
    """Mesmo peer/afi no encontrado com ASN diferente do cadastrado ⇒ conflito."""
    recursos = {"bgp_peers": _peers_up(asn=64599)}
    erro = valida_pre_upstream(session, up_com_2_circuitos, edge_device, recursos)
    assert "Peer 100.64.10.2 (ipv4)" in erro
    assert "ASN 64599 (esperado 64501)" in erro


def test_valida_pre_upstream_coerente_retorna_none(session, up_com_2_circuitos, edge_device):
    """Peers encontrados com o ASN cadastrado ⇒ None (pré-check aprovado)."""
    recursos = {"bgp_peers": _peers_up() + _peers_up(peer="100.64.10.6")}
    assert valida_pre_upstream(session, up_com_2_circuitos, edge_device, recursos) is None


def _sessoes_vinculos_desativadas(session, up):
    sessoes = session.scalars(
        select(models.BgpSession).where(
            models.BgpSession.circuit_id.in_([vin.circuit_id for vin in up.circuitos])
        )
    )
    for sessao in sessoes:
        sessao.admin_status = False
    session.commit()


def test_valida_pre_upstream_sessoes_todas_desativadas_reclama_por_default(
    session, up_com_2_circuitos, edge_device
):
    """Regressão: o default (provision) mantém a exigência de sessão ativa —
    upstream com 100% das sessões desativadas ⇒ "sem sessão BGP" (R-22)."""
    _sessoes_vinculos_desativadas(session, up_com_2_circuitos)
    recursos = {"bgp_peers": _peers_up() + _peers_up(peer="100.64.10.6")}
    erro = valida_pre_upstream(session, up_com_2_circuitos, edge_device, recursos)
    assert erro == "Upstream transito-f5 sem sessão BGP neste equipamento — revalide o upstream."


def test_valida_pre_upstream_include_disabled_aceita_sessoes_desativadas(
    session, up_com_2_circuitos, edge_device
):
    """Com include_disabled=True (execução de CR de remoção, R-22) as sessões
    desativadas contam — pré-check aprovado (None)."""
    _sessoes_vinculos_desativadas(session, up_com_2_circuitos)
    recursos = {"bgp_peers": _peers_up() + _peers_up(peer="100.64.10.6")}
    assert (
        valida_pre_upstream(
            session, up_com_2_circuitos, edge_device, recursos, include_disabled=True
        )
        is None
    )


def test_valida_pre_upstream_include_disabled_mantem_check_de_asn(
    session, up_com_2_circuitos, edge_device
):
    """A flag não desliga o check de conflito: peer desativado ainda no
    equipamento com ASN divergente do cadastrado ⇒ conflito (R-22)."""
    _sessoes_vinculos_desativadas(session, up_com_2_circuitos)
    recursos = {"bgp_peers": _peers_up(asn=64599)}
    erro = valida_pre_upstream(
        session, up_com_2_circuitos, edge_device, recursos, include_disabled=True
    )
    assert "Peer 100.64.10.2 (ipv4)" in erro
    assert "ASN 64599 (esperado 64501)" in erro


# ---- valida_pos_upstream (R-17/R-19) ----

def test_valida_pos_upstream_peer_ausente_item_critico(session, up_com_2_circuitos, edge_device):
    """Nenhuma linha do peer no snapshot ⇒ item crítico por sessão (§13)."""
    snap = _snapshot_up(session, edge_device, [])
    itens = valida_pos_upstream(session, up_com_2_circuitos, snap)
    assert [i["tipo"] for i in itens] == ["upstream.peer_ausente", "upstream.peer_ausente"]
    assert all(i["severidade"] == "critica" for i in itens)
    assert all(i["encontrado"] == "não listado" for i in itens)
    assert all("transito-f5" in i["esperado"] for i in itens)
    assert all("transito-f5" in i["acao"] for i in itens)


def test_valida_pos_upstream_peer_nao_estabelecido_item_critico(
    session, up_com_2_circuitos, edge_device
):
    """Peer listado em estado != established ⇒ item crítico."""
    peers = _peers_up(estado="Idle") + _peers_up(peer="100.64.10.6", estado="Idle")
    snap = _snapshot_up(session, edge_device, peers)
    itens = valida_pos_upstream(session, up_com_2_circuitos, snap)
    assert [i["tipo"] for i in itens] == [
        "upstream.peer_nao_estabelecido", "upstream.peer_nao_estabelecido",
    ]
    assert all(i["severidade"] == "critica" for i in itens)
    assert all(i["esperado"] == "established" and i["encontrado"] == "Idle" for i in itens)


def test_valida_pos_upstream_contagem_acima_do_esperado_item_alerta(
    session, up_com_2_circuitos, edge_device
):
    """pref_rcv fora de esperado×(1±margem) ⇒ item alerta (§7.1)."""
    peers = _peers_up(pref_rcv=1200) + _peers_up(peer="100.64.10.6", pref_rcv=1200)
    snap = _snapshot_up(session, edge_device, peers)
    itens = valida_pos_upstream(session, up_com_2_circuitos, snap)
    assert [i["tipo"] for i in itens] == [
        "upstream.contagem_fora_esperado", "upstream.contagem_fora_esperado",
    ]
    assert all(i["severidade"] == "alerta" for i in itens)
    assert all(i["esperado"] == "1000 ±10%" for i in itens)  # up fixture: v4=1000, margem=10
    assert all(i["encontrado"] == "1200" for i in itens)
    assert all("transito-f5" in i["acao"] for i in itens)


def test_valida_pos_upstream_contagem_dentro_da_margem_sem_itens(
    session, up_com_2_circuitos, edge_device
):
    """pref_rcv dentro de esperado×margem ⇒ nenhum item de contagem."""
    peers = _peers_up(pref_rcv=1050) + _peers_up(peer="100.64.10.6", pref_rcv=1050)
    snap = _snapshot_up(session, edge_device, peers)
    assert valida_pos_upstream(session, up_com_2_circuitos, snap) == []


def test_valida_pos_upstream_sem_esperado_cadastrado_sem_item_contagem(
    session, up_com_2_circuitos, edge_device
):
    """expected_prefixes_v4/v6 None ⇒ nenhum item de contagem (R-13)."""
    up_com_2_circuitos.expected_prefixes_v4 = None
    up_com_2_circuitos.expected_prefixes_v6 = None
    session.commit()
    peers = _peers_up(pref_rcv=99999) + _peers_up(peer="100.64.10.6", pref_rcv=99999)
    snap = _snapshot_up(session, edge_device, peers)
    assert valida_pos_upstream(session, up_com_2_circuitos, snap) == []


def test_valida_pos_upstream_pref_rcv_string_numerica_converte(
    session, up_com_2_circuitos, edge_device
):
    """M-11 (revisão final): `pref_rcv` como string numérica (snapshot parcial)
    não vira TypeError — é convertida e a contagem segue comparada."""
    peers = _peers_up(pref_rcv="1200") + _peers_up(peer="100.64.10.6", pref_rcv="1200")
    snap = _snapshot_up(session, edge_device, peers)
    itens = valida_pos_upstream(session, up_com_2_circuitos, snap)
    assert [i["tipo"] for i in itens] == [
        "upstream.contagem_fora_esperado", "upstream.contagem_fora_esperado",
    ]
    assert all(i["encontrado"] == "1200" for i in itens)


def test_valida_pos_upstream_pref_rcv_malformada_sem_typeerror(
    session, up_com_2_circuitos, edge_device
):
    """M-11: `pref_rcv` não numérico (snapshot corrompido) é descartado — a
    contagem deixa de contar em vez de derrubar o pós-check com TypeError."""
    peers = _peers_up(pref_rcv="?") + _peers_up(peer="100.64.10.6", pref_rcv="?")
    snap = _snapshot_up(session, edge_device, peers)
    assert valida_pos_upstream(session, up_com_2_circuitos, snap) == []
