"""Divergência desejado × encontrado (spec ciclo B §6) — snapshot sintético."""
import ipaddress

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import NotFoundError, ValidationError
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> dict:
    """Site default + org ASN 64512 + switch + NE8000 ASN 64600 no site."""
    site = create_site(db_session, SiteCreate(name="pop-rec-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Reconcilia", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-rec", management_address="10.31.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-rec", management_address="10.31.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _circuito_completo(db_session: Session, env: dict, *, code: str = "CIRC-REC-1") -> int:
    """Circuito dual reservado com edge_trunk; devolve o id."""
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne_id"], edge_trunk="Eth-Trunk127",
        ),
        actor="cli",
    ).id
    reservar_circuito(db_session, circ_id, actor="cli")
    return circ_id


def _circuito_sem_trunk(db_session: Session, env: dict) -> int:
    """Circuito dual reservado SEM edge_trunk; devolve o id."""
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-REC-NT", organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne_id"],
        ),
        actor="cli",
    ).id
    reservar_circuito(db_session, circ_id, actor="cli")
    return circ_id


def _pontas(db_session: Session, circ_id: int) -> dict:
    redes = {
        ipaddress.ip_network(l.network).version: l.network
        for l in db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    }
    v4_l, v4_r = pontas_v4(redes[4])
    v4_len = ipaddress.ip_network(redes[4]).prefixlen
    v6_l, v6_r = pontas_v6(redes[6])  # "address/126"
    return {
        "v4_l": v4_l, "v4_r": v4_r, "v4_len": v4_len,
        "v6_l": v6_l, "v6_r": v6_r,
        "v4_sub": f"{v4_l}/{v4_len}",
    }


def _sessao(db_session: Session, env: dict, circ_id: int, *, afi: str, **extra) -> int:
    p = _pontas(db_session, circ_id)
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ_id, device_id=env["ne_id"], afi=afi,
            local_address=p["v4_l"] if afi == "ipv4" else p["v6_l"].removesuffix("/126"),
            remote_address=p["v4_r"] if afi == "ipv4" else p["v6_r"].removesuffix("/126"),
            **extra,
        ),
        actor="cli",
    ).id


def _autoriza(db_session: Session, env: dict, *, v6: bool = False) -> None:
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=env["org_id"],
            family="ipv6" if v6 else "ipv4",
            prefix="2001:DB8::/32" if v6 else "192.0.2.0/24",
        ),
        actor="cli",
    )


def _perfil_export(db_session: Session, nome: str) -> int:
    return next(p.id for p in list_policy_profiles(db_session, direction="export") if p.name == nome)


def _snapshot(
    db_session: Session, env: dict, *, status: str = "success",
    interfaces: list[dict] | None = None,
    bgp_peers: list[dict] | None = None,
    bgp_peers_verbose: list[dict] | None = None,
    sem: tuple[str, ...] = (),
) -> int:
    """Snapshot sintético do device; devolve o id. `sem` omite chaves de resources."""
    recursos: dict = {
        "version": {"version": "8.210"},
        "interfaces": interfaces if interfaces is not None else [],
        "bgp_peers": bgp_peers if bgp_peers is not None else [],
        "bgp_peers_verbose": bgp_peers_verbose if bgp_peers_verbose is not None else [],
    }
    for chave in sem:
        recursos.pop(chave, None)
    snap = models.DeviceSnapshot(
        device_id=env["ne_id"], status=status, resources=recursos,
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap.id


def _recursos_perfeitos(db_session: Session, env: dict) -> dict:
    """interfaces/peers/verbose perfeitamente conformes (para _ambiente_dual)."""
    p = _pontas(db_session, _circ_id(db_session, env))
    return {
        "interfaces": [{
            "nome": "Eth-Trunk127.2", "phy": "up", "protocolo": "up",
            "enderecos_v4": [p["v4_sub"]],
            "enderecos_v6": [p["v6_l"]], "vpn": None,
        }],
        "bgp_peers": [
            {"afi": "ipv4", "peer": p["v4_r"], "asn": 64512, "estado": "Established",
             "pref_rcv": 2, "up_down": "1d02h"},
            {"afi": "ipv6", "peer": p["v6_r"].removesuffix("/126"), "asn": 64512,
             "estado": "Established", "pref_rcv": 0, "up_down": "1d02h"},
        ],
        "bgp_peers_verbose": [
            {"afi": "ipv4", "peer": p["v4_r"], "descricao": None,
             "filtro_import": "RP-64512-IMPORT-V4", "filtro_export": "RP-64512-EXPORT-V4"},
            {"afi": "ipv6", "peer": p["v6_r"].removesuffix("/126"), "descricao": None,
             "filtro_import": "RP-64512-IMPORT-V6", "filtro_export": "RP-64512-EXPORT-V6"},
        ],
    }


def _circ_id(db_session: Session, env: dict) -> int:
    circ = db_session.scalar(
        select(models.Circuit).where(
            models.Circuit.edge_device_id == env["ne_id"], models.Circuit.code == "CIRC-REC-1"
        )
    )
    return circ.id


def _ambiente_dual(db_session: Session) -> tuple[dict, dict]:
    """Env completo (circuito dual + autorizações v4/v6 + sessões com perfil full).

    Devolve (env, p) — p são as pontas locais/remotas do circuito, usadas
    pelos esperados dos itens de divergência.
    """
    env = _ambiente(db_session)
    circ_id = _circuito_completo(db_session, env)
    _autoriza(db_session, env)
    _autoriza(db_session, env, v6=True)
    full = _perfil_export(db_session, "full")
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=full)
    _sessao(db_session, env, circ_id, afi="ipv6", export_profile_id=full)
    p = _pontas(db_session, circ_id)
    return env, p


def test_conformidade_silenciosa(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    _snapshot(db_session, env, **_recursos_perfeitos(db_session, env))
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert resultado.items == []
    assert resultado.aviso is None
    assert resultado.snapshot_id is not None


def test_sem_snapshot_devolve_aviso(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert resultado.snapshot_id is None
    assert resultado.items == []
    assert resultado.aviso is not None and "snapshot" in resultado.aviso.lower()


def test_peer_ausente_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, p = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"] = [linha for linha in perfeito["bgp_peers"] if linha["afi"] != "ipv6"]
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.ausente"]
    assert itens[0].severidade == "critica"
    assert itens[0].esperado == p["v6_r"].removesuffix("/126")


def test_peer_estado_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"][0]["estado"] = "Active"
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.estado"]
    assert itens[0].esperado == "Established"
    assert itens[0].encontrado == "Active"
    assert itens[0].severidade == "atencao"


def test_peer_shutdown_admin_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env = _ambiente(db_session)
    circ_id = _circuito_completo(db_session, env, code="CIRC-REC-SD")
    _sessao(db_session, env, circ_id, afi="ipv4", shutdown=True)
    p = _pontas(db_session, circ_id)
    _snapshot(
        db_session, env, sem=("interfaces",),
        bgp_peers=[{"afi": "ipv4", "peer": p["v4_r"], "asn": 64512, "estado": "Established",
                "pref_rcv": 1, "up_down": "1d02h"}],
    )
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.shutdown_admin"]
    assert itens[0].esperado == "não Established"
    assert itens[0].encontrado == "Established"
    assert itens[0].severidade == "atencao"


def test_peer_asn_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"][0]["asn"] = 64599
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.asn"]
    assert itens[0].esperado == "64512"
    assert itens[0].encontrado == "64599"
    assert itens[0].severidade == "critica"


def test_peer_filtros_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers_verbose"][0]["filtro_import"] = "ASN64512-V4-IMPORT"  # legado em produção
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.filtros"]
    assert itens[0].esperado == "RP-64512-IMPORT-V4"
    assert itens[0].encontrado == "ASN64512-V4-IMPORT"
    assert itens[0].severidade == "critica"


def test_produto_export_em_divida_nao_gera_filtros(db_session: Session) -> None:
    """Produto de exportação em dívida (personalizado sem prefixos): o render
    emite bloco comentário (objeto="session", objeto_id=0) que o parse de
    filtros ignora — linha verbose divergente não vira item peer.filtros
    (T5-M4). default_internas deixou de ser exemplar: o B4 o tornou renderizável."""
    from gerenet.automation.reconcile import reconciliar_device

    env = _ambiente(db_session)
    circ_id = _circuito_completo(db_session, env)
    _autoriza(db_session, env)  # import continua renderizável (RP-64512-IMPORT-V4)
    perfil = _perfil_export(db_session, "personalizado")
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=perfil)
    p = _pontas(db_session, circ_id)
    _snapshot(
        db_session, env, sem=("interfaces",),
        bgp_peers=[{"afi": "ipv4", "peer": p["v4_r"], "asn": 64512, "estado": "Established",
                "pref_rcv": 1, "up_down": "1d02h"}],
        bgp_peers_verbose=[{
            "afi": "ipv4", "peer": p["v4_r"], "descricao": None,
            "filtro_import": "RP-64512-IMPORT-V4", "filtro_export": "ASN64512-V4-EXPORT",
        }],
    )
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert not any(i.tipo == "peer.filtros" for i in itens)
    assert itens == []


def test_peer_orfao_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["bgp_peers"].append({
        "afi": "ipv4", "peer": "203.0.113.9", "asn": 64512,
        "estado": "Established", "pref_rcv": 1, "up_down": "1d02h",
    })
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.orfaos"]
    assert itens[0].esperado == "sessão no SoT"
    assert itens[0].encontrado == "203.0.113.9"
    assert itens[0].severidade == "atencao"


def test_subinterface_ausente_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["interfaces"] = []
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["subinterface.ausente"]
    assert itens[0].esperado == "Eth-Trunk127.2"
    assert itens[0].severidade == "critica"


def test_subinterface_estado_atencao(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["interfaces"][0]["phy"] = "*down"
    perfeito["interfaces"][0]["protocolo"] = "down"
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["subinterface.estado"]
    assert itens[0].esperado == "up"
    assert itens[0].encontrado == "*down/down"
    assert itens[0].severidade == "atencao"


def test_subinterface_up_s_nao_vira_estado(db_session: Session) -> None:
    """`up(s)` (spoofing, spec §4.2) é estado legítimo — não gera item."""
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["interfaces"][0]["phy"] = "up(s)"
    _snapshot(db_session, env, **perfeito)
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert [i.tipo for i in resultado.items] == []
    assert resultado.aviso is None


def test_pontas_v4_e_v6_critico(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, p = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    perfeito["interfaces"][0]["enderecos_v4"] = []
    _snapshot(db_session, env, **perfeito)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["ponta.v4"]
    assert itens[0].esperado == p["v4_sub"]
    assert itens[0].encontrado == "—"
    assert itens[0].severidade == "critica"

    perfeito2 = _recursos_perfeitos(db_session, env)
    perfeito2["interfaces"][0]["enderecos_v6"] = []
    _snapshot(db_session, env, **perfeito2)
    itens2 = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens2] == ["ponta.v6"]
    assert itens2[0].esperado == p["v6_l"]
    assert itens2[0].encontrado == "—"
    assert itens2[0].severidade == "critica"


def test_circuito_sem_trunk_vira_aviso(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env = _ambiente(db_session)
    circ_id = _circuito_sem_trunk(db_session, env)
    _sessao(db_session, env, circ_id, afi="ipv4")
    p = _pontas(db_session, circ_id)
    _snapshot(
        db_session, env,
        bgp_peers=[{"afi": "ipv4", "peer": p["v4_r"], "asn": 64512, "estado": "Established",
                "pref_rcv": 1, "up_down": "1d02h"}],
    )
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["circuito.sem_trunk"]
    assert itens[0].severidade == "aviso"


def test_sem_trunk_com_peer_ausente_tambem_avisa(db_session: Session) -> None:
    """Circuito reservado sem edge_trunk avisa mesmo quando o peer não aparece
    no snapshot — o registro do circuito precede o continue de peer.ausente."""
    from gerenet.automation.reconcile import reconciliar_device

    env = _ambiente(db_session)
    circ_id = _circuito_sem_trunk(db_session, env)
    _sessao(db_session, env, circ_id, afi="ipv4")
    _snapshot(db_session, env, bgp_peers=[])  # sem o peer no snapshot
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["circuito.sem_trunk", "peer.ausente"]
    assert next(i for i in itens if i.tipo == "circuito.sem_trunk").severidade == "aviso"
    assert next(i for i in itens if i.tipo == "peer.ausente").severidade == "critica"


def test_sessao_desativada_nao_gera_peer_ausente(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device
    from gerenet.domain.services.bgp_sessions import disable_session

    env = _ambiente(db_session)
    circ_id = _circuito_completo(db_session, env)
    sessao_id = _sessao(db_session, env, circ_id, afi="ipv4")
    disable_session(db_session, sessao_id, actor="cli")
    _snapshot(db_session, env)
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert itens == []  # sem sessões ativas, nada a comparar


def test_snapshot_resources_nulo_nao_derruba(db_session: Session) -> None:
    """Coluna JSON aceita NULL (row legado): recursos vira {} e o snap
    parcial avisa em vez de TypeError no reconcile."""
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    snap = models.DeviceSnapshot(
        device_id=env["ne_id"], status="success", resources=None,
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert resultado.items == []
    assert resultado.aviso is not None and "interfaces" in resultado.aviso


def test_snapshot_parcial_omite_recurso_e_avisa(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    _snapshot(db_session, env, status="partial", sem=("interfaces",), **perfeito)
    resultado = reconciliar_device(db_session, env["ne_id"])
    assert resultado.aviso is not None and "interfaces" in resultado.aviso
    assert not any(i.tipo.startswith("subinterface") or i.tipo.startswith("ponta") for i in resultado.items)


def test_snapshot_de_outro_device_rejeitado(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    snap_id = _snapshot(db_session, env)
    with pytest.raises(ValidationError, match="pertence ao device"):
        reconciliar_device(db_session, env["sw_id"], snapshot_id=snap_id)
    with pytest.raises(NotFoundError):
        reconciliar_device(db_session, env["ne_id"], snapshot_id=9999)
    # só snapshot_id: device derivado do snapshot
    assert reconciliar_device(db_session, None, snapshot_id=snap_id).device_id == env["ne_id"]


def test_reconciliar_usa_o_snapshot_mais_recente(db_session: Session) -> None:
    from gerenet.automation.reconcile import reconciliar_device

    env, _ = _ambiente_dual(db_session)
    perfeito = _recursos_perfeitos(db_session, env)
    _snapshot(db_session, env, **perfeito)  # perfeito
    ruim = dict(perfeito)
    ruim["bgp_peers"] = [linha for linha in perfeito["bgp_peers"] if linha["afi"] == "ipv4"]
    _snapshot(db_session, env, **ruim)  # mais recente: sem o peer v6
    itens = reconciliar_device(db_session, env["ne_id"]).items
    assert [i.tipo for i in itens] == ["peer.ausente"]
