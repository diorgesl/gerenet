"""Orquestrador render_desejado — blocos completos por device (spec ciclo B §5.2)."""
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
from gerenet.domain.services import bgp_sessions as sessoes_svc
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import NotFoundError
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.policy_profiles import list_policy_profiles
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> dict:
    """Site default + org ASN 64512 + switch + NE8000 ASN 64600 no site."""
    site = create_site(db_session, SiteCreate(name="pop-render-01"), actor="cli")
    org = create_organization(
        db_session, OrganizationCreate(name="Cliente Render", asn=64512), actor="cli"
    )
    sw = create_device(db_session, DeviceCreate(name="sw-render", management_address="10.30.0.2"), actor="cli")
    ne = create_device(
        db_session, DeviceCreate(name="ne-render", management_address="10.30.0.1", asn=64600),
        actor="cli",
    )
    for dev in (sw, ne):
        link_device(db_session, site.id, dev.id, actor="cli")
    return {"org_id": org.id, "site_id": site.id, "sw_id": sw.id, "ne_id": ne.id}


def _circuito_reservado(db_session: Session, env: dict, *, code: str, **extra) -> int:
    """Circuito no edge do ambiente com edge_trunk, reservado; devolve o id."""
    base: dict = {
        "code": code, "organization_id": env["org_id"], "site_id": env["site_id"],
        "access_device_id": env["sw_id"], "access_port": "GE0/0/1",
        "edge_device_id": env["ne_id"], "edge_trunk": "Eth-Trunk127",
    }
    base.update(extra)
    circ_id = create_circuit(db_session, CircuitCreate(**base), actor="cli").id
    reservar_circuito(db_session, circ_id, actor="cli")
    return circ_id


def _pontas(db_session: Session, circ_id: int) -> dict:
    """Pontas locais/remotas v4/v6 do circuito reservado (via IPAM)."""
    redes = {
        ipaddress.ip_network(l.network).version: l.network
        for l in db_session.scalars(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ_id))
    }
    v4_l, v4_r = pontas_v4(redes[4])
    if 6 in redes:
        v6_l, v6_r = pontas_v6(redes[6])  # "address/126"
        return {"v4_l": v4_l, "v4_r": v4_r, "v6_l": v6_l[:-4], "v6_r": v6_r[:-4]}
    return {"v4_l": v4_l, "v4_r": v4_r, "v6_l": None, "v6_r": None}


def _sessao(db_session: Session, env: dict, circ_id: int, *, afi: str, **extra) -> int:
    p = _pontas(db_session, circ_id)
    dados: dict = {
        "afi": afi,
        "local_address": p["v4_l"] if afi == "ipv4" else p["v6_l"],
        "remote_address": p["v4_r"] if afi == "ipv4" else p["v6_r"],
    }
    dados.update(extra)
    return sessoes_svc.create_session(
        db_session, BgpSessionCreate(circuit_id=circ_id, device_id=env["ne_id"], **dados), actor="cli"
    ).id


def test_render_dual_completo_ordenado(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    full_id = next(p.id for p in list_policy_profiles(db_session, direction="export") if p.name == "full")
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-1")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv6", prefix="2001:DB8::/32",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=full_id)
    _sessao(db_session, env, circ_id, afi="ipv6", export_profile_id=full_id)

    resultado = render_desejado(db_session, env["ne_id"])
    # TIPO_ORDEM (Ruling 2): sort estável agrupa por tipo — as duas famílias
    # geram prefix_list/route_policy_import/route_policy_export/bgp_peer adjacentes
    assert [b.tipo for b in resultado.blocos] == [
        "subinterface",
        "prefix_list", "prefix_list",
        "route_policy_import", "route_policy_import",
        "route_policy_export", "route_policy_export",
        "bgp_peer", "bgp_peer",
    ]
    # anotação do objeto SoT que originou cada bloco (ciclo C mapeia diff/rollback)
    assert resultado.blocos[0].objeto == "circuit"
    assert resultado.blocos[0].objeto_id == circ_id
    assert all(b.objeto == "session" for b in resultado.blocos[1:])

    sub = resultado.blocos[0]
    assert sub.comandos[0] == "interface Eth-Trunk127.2"
    assert sub.comandos[1] == "vlan-type dot1q vid 2"
    assert "ip address 100.64.0.0 255.255.255.254" in sub.comandos
    assert "ipv6 enable" in sub.comandos
    assert "ipv6 address 2804:194C:1000::6400:1/126" in sub.comandos

    assert resultado.texto == "\n".join(b.texto for b in resultado.blocos)


def test_render_v4_sem_autorizacao_so_peer(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-2", stack="ipv4", vlan_mode="separada")
    _sessao(db_session, env, circ_id, afi="ipv4")

    resultado = render_desejado(db_session, env["ne_id"])
    # sem autorizações ⇒ sem prefix_list/RP import; sem perfil ⇒ sem export
    assert [b.tipo for b in resultado.blocos] == ["subinterface", "bgp_peer"]
    assert resultado.blocos[0].comandos[0].startswith("interface Eth-Trunk127.")
    assert not any("ipv6" in linha for linha in resultado.blocos[0].comandos)
    texto = resultado.texto
    assert "peer 100.64.0.1 as-number 64512" in texto  # org = ASN do par (default)
    assert "import route-policy" not in texto
    assert "export route-policy" not in texto


def test_render_sem_edge_trunk_nao_gera_subinterface(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    base: dict = {
        "code": "CIRC-R-3", "organization_id": env["org_id"], "site_id": env["site_id"],
        "access_device_id": env["sw_id"], "access_port": "GE0/0/1",
        "edge_device_id": env["ne_id"],
    }
    circ_id = create_circuit(db_session, CircuitCreate(**base), actor="cli").id
    reservar_circuito(db_session, circ_id, actor="cli")
    _sessao(db_session, env, circ_id, afi="ipv4")

    resultado = render_desejado(db_session, env["ne_id"])
    assert [b.tipo for b in resultado.blocos] == ["bgp_peer"]


def test_render_export_default_med_prepend_e_dividas(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    perfis = {p.name: p.id for p in list_policy_profiles(db_session, direction="export")}
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-4", stack="ipv4")
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=perfis["default"], med=50, prepend=2)

    texto = render_desejado(db_session, env["ne_id"]).texto
    assert "ip ip-prefix IP-PFX-DEFAULT-V4 index 10 permit 0.0.0.0/0" in texto
    assert "route-policy RP-64512-EXPORT-V4 permit node 10" in texto
    assert "if-match ip-prefix IP-PFX-DEFAULT-V4" in texto
    assert "apply med 50" in texto
    assert "apply as-path 64600 64600 additive" in texto  # asn_local = ASN do device

    # vrf próprio evita a regra de singularidade (device+VRF+afi) no segundo
    # ipv4 ativo do mesmo edge; o render não diferencia VRF (§25.3)
    circ_d = _circuito_reservado(db_session, env, code="CIRC-R-5", stack="ipv4", vrf="vpn-render")
    _sessao(db_session, env, circ_d, afi="ipv4", export_profile_id=perfis["default_internas"])
    texto2 = render_desejado(db_session, env["ne_id"]).texto
    assert "# produto 'default_internas'" in texto2  # dívida documentada (ruling 13)


def test_render_import_com_default_autorizada(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-6", stack="ipv4")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", allow_default_route=True)

    texto = render_desejado(db_session, env["ne_id"]).texto
    assert "index 5 permit 0.0.0.0/0" in texto
    assert "index 10 permit 192.0.2.0/24" in texto
    assert "if-match ip-prefix IP-PFX-64512-IN-V4" in texto


def test_render_sessao_shutdown_emite_peer_shutdown(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-7", stack="ipv4")
    _sessao(db_session, env, circ_id, afi="ipv4", shutdown=True)
    texto = render_desejado(db_session, env["ne_id"]).texto.replace("\n", "|")
    assert "peer 100.64.0.1 shutdown" in texto


def test_render_senha_vira_so_comentario(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-8", stack="ipv4")
    sessao_id = _sessao(db_session, env, circ_id, afi="ipv4")
    sessoes_svc.set_password(db_session, sessao_id, actor="cli", path="gerenet/bgp-sessions/1/password")
    texto = render_desejado(db_session, env["ne_id"]).texto
    # única linha com "password" é o comentário (§3 segredos) — 2 ocorrências
    # na própria linha: o rótulo e o path no Vault; o valor nunca é emitido
    assert [l for l in texto.splitlines() if "password" in l] == [
        "# password no Vault (gerenet/bgp-sessions/1/password)"
    ]
    assert "# password no Vault (gerenet/bgp-sessions/1/password)" in texto


def test_render_idempotente(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-9", stack="ipv4")
    _sessao(db_session, env, circ_id, afi="ipv4")
    assert render_desejado(db_session, env["ne_id"]).texto == render_desejado(
        db_session, env["ne_id"]
    ).texto


def test_render_device_inexistente(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    with pytest.raises(NotFoundError):
        render_desejado(db_session, 9999)
