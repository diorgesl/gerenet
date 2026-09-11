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


def test_tipo_ordem_contem_community_filter() -> None:
    from gerenet.automation.render import TIPO_ORDEM

    # B3 define os community-filters antes das RPs de import/export no mesmo render
    nomes = [t for t, _ in sorted(TIPO_ORDEM.items(), key=lambda item: item[1])]
    assert "community_filter" in nomes
    assert nomes.index("community_filter") < nomes.index("route_policy_import")
    assert nomes.index("community_filter") < nomes.index("route_policy_export")


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
    # default_internas renderiza (dívida paga): prefix-list de default+internas.
    # A RP tem o mesmo nome da parte 1 (RP-64512-EXPORT-V4 — §25.4: estável
    # para ASN+AFI), mas os corpos diferem no if-match ⇒ os 2 blocos CONVIVEM
    # (dívida de colisão de nomes §25.4/§25.5, pré-existente — não deduplicar)
    assert "# produto 'default_internas'" not in texto2
    assert "ip ip-prefix IP-PFX-DEFAULT-INTERNAS-V4 index 10 permit 0.0.0.0/0" in texto2
    assert "if-match ip-prefix IP-PFX-DEFAULT-INTERNAS-V4" in texto2
    assert texto2.count("route-policy RP-64512-EXPORT-V4 permit node 10") == 2


def test_render_export_default_internas_com_internas_e_autorizadas(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    # loopback do edge ⇒ rota interna (B1); o p2p /31 reservado do circuito
    # entra junto (rede da alocação, kind p2p status reservada)
    ne = db_session.get(models.Device, env["ne_id"])
    ne.loopback = "10.99.0.253"
    db_session.commit()
    perfis = {p.name: p.id for p in list_policy_profiles(db_session, direction="export")}
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-15", stack="ipv4")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=perfis["default_internas"])

    texto = render_desejado(db_session, env["ne_id"]).texto
    # default no index 10; internas (loopback antes do p2p — ordenadas) e
    # autorizada da org em seguida, um índice por prefixo (sem duplicar)
    assert "ip ip-prefix IP-PFX-DEFAULT-INTERNAS-V4 index 10 permit 0.0.0.0/0" in texto
    assert "ip ip-prefix IP-PFX-DEFAULT-INTERNAS-V4 index 20 permit 10.99.0.253/32" in texto
    assert "ip ip-prefix IP-PFX-DEFAULT-INTERNAS-V4 index 30 permit 100.64.0.0/31" in texto
    assert "ip ip-prefix IP-PFX-DEFAULT-INTERNAS-V4 index 40 permit 192.0.2.0/24" in texto
    assert "if-match ip-prefix IP-PFX-DEFAULT-INTERNAS-V4" in texto
    assert "route-policy RP-64512-EXPORT-V4 permit node 10" in texto
    # R5: a definição existe ⇒ o peer referencia a RP de export
    assert "export route-policy RP-64512-EXPORT-V4" in texto
    assert "# produto 'default_internas'" not in texto


def test_render_export_parcial_com_internas_sem_default(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    ne = db_session.get(models.Device, env["ne_id"])
    ne.loopback = "10.99.0.253"
    db_session.commit()
    perfis = {p.name: p.id for p in list_policy_profiles(db_session, direction="export")}
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-16", stack="ipv4")
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    _sessao(db_session, env, circ_id, afi="ipv4", export_profile_id=perfis["parcial"])

    texto = render_desejado(db_session, env["ne_id"]).texto
    # produto "parcial" = internas + autorizadas, SEM default
    assert "ip ip-prefix IP-PFX-PARCIAL-V4 index 10 permit 10.99.0.253/32" in texto
    assert "ip ip-prefix IP-PFX-PARCIAL-V4 index 20 permit 100.64.0.0/31" in texto
    assert "ip ip-prefix IP-PFX-PARCIAL-V4 index 30 permit 192.0.2.0/24" in texto
    assert "if-match ip-prefix IP-PFX-PARCIAL-V4" in texto
    assert "0.0.0.0/0" not in texto


def test_render_export_parcial_sem_conteudo_vai_divida(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    perfis = {p.name: p.id for p in list_policy_profiles(db_session, direction="export")}
    # circuito SEM reserva IPAM (sem p2p alocado ⇒ internas vazia) e sem
    # autorizações da org ⇒ lista de anúncio do "parcial" fica vazia
    circ_id = create_circuit(
        db_session,
        CircuitCreate(
            code="CIRC-R-17", organization_id=env["org_id"], site_id=env["site_id"],
            access_device_id=env["sw_id"], access_port="GE0/0/1",
            edge_device_id=env["ne_id"], edge_trunk="Eth-Trunk127",
        ),
        actor="cli",
    ).id
    sessoes_svc.create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ_id, device_id=env["ne_id"], afi="ipv4",
            local_address="192.0.2.1", remote_address="192.0.2.2",
            export_profile_id=perfis["parcial"],
        ),
        actor="cli",
    )

    texto = render_desejado(db_session, env["ne_id"]).texto
    # sem lista para montar ⇒ comentário-dívida; sem definição ⇒ o peer NÃO
    # referencia RP de export (R5)
    assert ("# produto 'parcial': sem rotas internas nem autorizações "
            "para montar a lista de anúncio.") in texto
    assert "IP-PFX-PARCIAL-V4" not in texto
    assert "export route-policy" not in texto


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


def test_render_stack_ipv6_nao_emite_par_v4_interno(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-12", stack="ipv6", vlan_mode="separada")
    _sessao(db_session, env, circ_id, afi="ipv6")

    resultado = render_desejado(db_session, env["ne_id"])
    sub = next(b for b in resultado.blocos if b.tipo == "subinterface")
    # Ruling 3: o par v4 interno (notes "Par v4 interno — derivação do sufixo")
    # nunca vira endereço de interface numa interface IPv6-only
    assert "interface Eth-Trunk127.3" in sub.comandos
    assert not any(l.startswith("ip address") for l in sub.comandos)
    assert "ipv6 enable" in sub.comandos
    assert "ipv6 address 2804:194C:1000::6400:1/126" in sub.comandos


def test_render_duas_sessoes_mesmo_asn_afi_deduplica_definicoes(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    perfis = {p.name: p.id for p in list_policy_profiles(db_session, direction="export")}
    create_authorization(
        db_session, PrefixAuthorizationCreate(
            organization_id=env["org_id"], family="ipv4", prefix="192.0.2.0/24",
        ), actor="cli",
    )
    circ_a = _circuito_reservado(db_session, env, code="CIRC-R-13", stack="ipv4")
    _sessao(db_session, env, circ_a, afi="ipv4", export_profile_id=perfis["default"])
    # vrf próprio: o serviço só permite 1 ipv4 ativo por (device, VRF)
    circ_b = _circuito_reservado(db_session, env, code="CIRC-R-14", stack="ipv4", vrf="vpn-b")
    _sessao(db_session, env, circ_b, afi="ipv4", export_profile_id=perfis["default"])

    resultado = render_desejado(db_session, env["ne_id"])
    # mesmas autorizações + mesmo produto ⇒ cada DEFINICAO (por nome) 1× só:
    # 2 prefix-lists diferentes (IN-V4 da import + DEFAULT-V4 da export), 1 RP
    # de import + 1 RP de export, embora haja 2 sessões ativas
    assert sum(1 for b in resultado.blocos if b.tipo == "prefix_list") == 2
    assert sum(1 for b in resultado.blocos if b.tipo == "route_policy_import") == 1
    assert sum(1 for b in resultado.blocos if b.tipo == "route_policy_export") == 1
    assert sum(1 for b in resultado.blocos if b.tipo == "bgp_peer") == 2
    assert resultado.texto.count("ip ip-prefix IP-PFX-64512-IN-V4 index 10 permit 192.0.2.0/24") == 1
    assert resultado.texto.count("ip ip-prefix IP-PFX-DEFAULT-V4 index 10 permit 0.0.0.0/0") == 1
    assert resultado.texto.count("route-policy RP-64512-IMPORT-V4 permit node 10") == 1
    assert resultado.texto.count("route-policy RP-64512-EXPORT-V4 permit node 10") == 1
    # Ruling R5: as referências dos 2 peers não somem com o dedup — cada
    # sessão (mesmo ASN+AFI) referencia a RP dela, uma por peer
    assert resultado.texto.count("import route-policy RP-64512-IMPORT-V4") == 2
    assert resultado.texto.count("export route-policy RP-64512-EXPORT-V4") == 2
    # a definição fica anotada com a 1ª sessão que a gerou
    import_bloco = next(b for b in resultado.blocos if b.tipo == "route_policy_import")
    assert import_bloco.objeto == "session"


def test_render_qinq_emite_vlan_type_dot1q_088a8(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-11", stack="ipv4", qinq=True)
    _sessao(db_session, env, circ_id, afi="ipv4")

    texto = render_desejado(db_session, env["ne_id"]).texto
    assert "vlan-type dot1q 0x88a8 vid 2" in texto
    assert "vlan-type dot1q vid 2" not in texto


def test_render_subinterface_no_backup_edge(db_session: Session) -> None:
    from gerenet.automation.render import render_desejado

    env = _ambiente(db_session)
    ne_bkp = create_device(
        db_session, DeviceCreate(name="ne-render-bkp", management_address="10.30.0.3", asn=64600),
        actor="cli",
    )
    link_device(db_session, env["site_id"], ne_bkp.id, actor="cli")
    base: dict = {
        "code": "CIRC-R-10", "organization_id": env["org_id"], "site_id": env["site_id"],
        "access_device_id": env["sw_id"], "access_port": "GE0/0/1",
        "edge_device_id": env["ne_id"], "backup_edge_device_id": ne_bkp.id,
        "edge_trunk": "Eth-Trunk127",
    }
    circ_id = create_circuit(db_session, CircuitCreate(**base), actor="cli").id
    reservar_circuito(db_session, circ_id, actor="cli")
    p = _pontas(db_session, circ_id)
    sessoes_svc.create_session(
        db_session, BgpSessionCreate(
            circuit_id=circ_id, device_id=ne_bkp.id, afi="ipv4",
            local_address=p["v4_l"], remote_address=p["v4_r"],
        ), actor="cli",
    )

    resultado = render_desejado(db_session, ne_bkp.id)
    # Ruling 3: o backup também recebe a subinterface do circuito
    assert [b.tipo for b in resultado.blocos] == ["subinterface", "bgp_peer"]
    assert resultado.blocos[0].objeto == "circuit"
    assert resultado.blocos[0].objeto_id == circ_id


def test_circuito_liberado_nao_renderiza_subinterface(db_session: Session) -> None:
    """Reserva liberada não volta ao render, mesmo com sessão ativa nova no circuito."""
    from gerenet.automation.render import render_desejado
    from gerenet.domain.services.ipam import liberar_circuito

    env = _ambiente(db_session)
    circ_id = _circuito_reservado(db_session, env, code="CIRC-R-LIB")
    liberar_circuito(db_session, circ_id, actor="cli")
    # create_session não valida reserva: é por aqui que o circuito liberado alcança
    # o render (os endereços das linhas liberadas seguem legíveis por circuit_id).
    _sessao(db_session, env, circ_id, afi="ipv4")

    resultado = render_desejado(db_session, env["ne_id"])
    assert [b.tipo for b in resultado.blocos] == ["bgp_peer"], resultado.texto
