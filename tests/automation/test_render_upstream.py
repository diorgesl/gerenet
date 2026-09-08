"""Render do desejado para sessões de upstream (F5/B3) — spec §4.1/§4.2.

Caminhos novos: import com proteções (up-full), parcial (community de
"parcial"), up-default e fail-safe (deny-all sem perfil); export de
internas+clientes com aplicações (prepend/lp/blackhole). O caminho de
CLIENTE permanece intacto — golden do caminho existente em
test_render_upstream_nao_afasta_caminho_do_cliente.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation.render import render_desejado
from gerenet.domain import models


def _perfil(db_session: Session, nome: str, *, direction: str) -> models.PolicyProfile:
    perfil = db_session.scalar(select(models.PolicyProfile).where(
        models.PolicyProfile.name == nome,
        models.PolicyProfile.direction == direction,
        models.PolicyProfile.admin_status.is_(True),
    ))
    assert perfil is not None, f"perfil '{nome}' do catálogo ausente no banco de teste"
    return perfil


def _link_upstream(db_session: Session, up: models.Upstream, device: models.Device, *,
                   code: str, import_profile_id: int | None, **extra) -> models.BgpSession:
    """Circuito no edge + vínculo ao upstream + sessão V4 (composição direta, estilo conftest)."""
    circ = models.Circuit(
        code=code, organization_id=up.organization_id, site_id=device.site_id,
        access_device_id=None, access_port="GE0/0/0", edge_device_id=device.id,
        vlan_mode="none",
    )
    db_session.add(circ)
    db_session.flush()
    db_session.add(models.UpstreamCircuit(
        upstream_id=up.id, circuit_id=circ.id, papel="principal", ordem=1))
    dados: dict = {
        "circuit_id": circ.id, "device_id": device.id, "afi": "ipv4",
        "local_address": "100.64.10.1", "remote_address": "100.64.10.2",
        "asn_local": device.asn or 65001, "asn_remote": up.organization.asn,
        "import_profile_id": import_profile_id,
    }
    dados.update(extra)
    sessao = models.BgpSession(**dados)
    db_session.add(sessao)
    db_session.commit()
    return sessao


def test_render_upstream_full_import_com_protecoes(session, up_com_sessao_upfull,
                                                   edge_device, org_downstream):
    # produto up-full; info-community bloquear cadastrada + autorização de cliente
    up = up_com_sessao_upfull
    session.add_all([
        models.UpstreamCommunity(upstream_id=up.id, purpose="info", value="65530:20:0",
                                 direcao="import", bloquear=True),
        models.BgpPrefixAuthorization(organization_id=org_downstream.id, family="ipv4",
                                      prefix="192.0.2.0/24"),
    ])
    session.commit()

    resultado = render_desejado(session, edge_device.id)
    texto = resultado.texto
    # community-filter de bloqueio + prefix-list de proteção (default negado +
    # internas + autorizados de clientes, na mesma AFI)
    assert "ip community-filter CF-64501-BLK-1 permit 65530:20:0" in texto
    assert "ip ip-prefix IP-PFX-64501-IN-V4 index 5 permit 0.0.0.0/0" in texto
    assert "ip ip-prefix IP-PFX-64501-IN-V4 index 10 permit 192.0.2.0/24" in texto
    rp = next(b.texto for b in resultado.blocos
              if b.tipo == "route_policy_import" and "RP-64501-IMPORT-V4" in b.texto)
    assert "route-policy RP-64501-IMPORT-V4 deny node 10" in rp
    assert "if-match ip-prefix IP-PFX-64501-IN-V4" in rp
    assert "route-policy RP-64501-IMPORT-V4 deny node 20" in rp
    assert "if-match community-filter CF-64501-BLK-1" in rp
    assert "route-policy RP-64501-IMPORT-V4 permit node 100" in rp
    # o peer referencia a RP de import definida para a sessão de upstream
    assert texto.count("import route-policy RP-64501-IMPORT-V4") == 1


def test_render_upstream_full_sem_protecoes_nao_referencia_lista_vazia(
        session, up_com_sessao_upfull, bgp_session_principal, edge_device):
    # up-full sem default negada, sem internas (sem loopback/p2p) e sem
    # autorizações ⇒ SEM prefix-list de proteção (vazia referenciada = fail-stop
    # VRP) e RP sem o if-match da proteção — permit node 100 puro
    bgp_session_principal.allow_default_route = True
    session.commit()

    resultado = render_desejado(session, edge_device.id)
    assert "IP-PFX-64501-IN-V4" not in resultado.texto
    rp = next(b.texto for b in resultado.blocos
              if b.tipo == "route_policy_import" and "RP-64501-IMPORT-V4" in b.texto)
    assert "if-match ip-prefix" not in rp
    assert "route-policy RP-64501-IMPORT-V4 permit node 100" in rp
    # R5: o peer continua referenciando a RP (a definição existe)
    assert resultado.texto.count("import route-policy RP-64501-IMPORT-V4") == 1


def test_render_upstream_perfil_de_cliente_vira_fail_safe(session, up, edge_device):
    # R-09: produto de CLIENTE (não up-*) numa sessão de upstream ⇒ fail-safe
    # deny-all com aviso — nunca accept-all implícito, nunca abandono sem RP
    perfil_cli = _perfil(session, "default_internas", direction="export")
    _link_upstream(session, up, edge_device, code="CIRC-UP-CLI",
                   import_profile_id=perfil_cli.id)

    resultado = render_desejado(session, edge_device.id)
    texto = resultado.texto
    rp = next(b.texto for b in resultado.blocos
              if b.tipo == "route_policy_import" and "RP-64501-IMPORT-V4" in b.texto)
    assert "# fail-safe: sessão de upstream sem perfil de import — deny-all (nunca accept-all)" in rp
    assert "route-policy RP-64501-IMPORT-V4 deny node 10" in rp
    assert "permit" not in rp
    assert "default_internas" in texto  # comentário-dívida anota o produto indevido
    assert texto.count("import route-policy RP-64501-IMPORT-V4") == 1  # R5: peer referencia


def test_render_upstream_export_anuncia_internas(session, up_com_sessao_upfull,
                                                 edge_device, circuito_com_p2p):
    resultado = render_desejado(session, edge_device.id)
    texto = resultado.texto
    # anúncio = rotas internas (p2p alocado do circuito_com_p2p) + autorizadas
    assert "ip ip-prefix IP-PFX-INTERNAS-V4 index 10 permit 100.64.10.0/31" in texto
    assert "route-policy RP-64501-EXPORT-V4 permit node 10" in texto
    assert "if-match ip-prefix IP-PFX-INTERNAS-V4" in texto
    assert texto.count("export route-policy RP-64501-EXPORT-V4") == 1


def test_render_upstream_parcial_import_aceita_community(session, up2, edge_device):
    _link_upstream(session, up2, edge_device, code="CIRC-UP-PART",
                   import_profile_id=_perfil(session, "up-parcial", direction="import").id)
    session.add(models.UpstreamCommunity(upstream_id=up2.id, purpose="info",
                                         value="65530:20:1", direcao="import"))
    session.commit()

    texto = render_desejado(session, edge_device.id).texto
    # default + rotas portadoras da community de "parcial" (nós de aceite)
    assert "ip ip-prefix IP-PFX-DEFAULT-V4 index 10 permit 0.0.0.0/0" in texto
    assert "ip community-filter CF-64501-PART-1 permit 65530:20:1" in texto
    assert "route-policy RP-64501-IMPORT-V4 permit node 10" in texto
    assert "if-match ip-prefix IP-PFX-DEFAULT-V4" in texto
    assert "route-policy RP-64501-IMPORT-V4 permit node 20" in texto
    assert "if-match community-filter CF-64501-PART-1" in texto


def test_render_upstream_parcial_sem_community_vira_divida(session, up2, edge_device):
    _link_upstream(session, up2, edge_device, code="CIRC-UP-PART-DIV",
                   import_profile_id=_perfil(session, "up-parcial", direction="import").id)
    texto = render_desejado(session, edge_device.id).texto
    # §4.1: sem a community de "parcial" cadastrada ⇒ comentário-dívida, nunca
    # uma política permissiva derivada de palpite
    assert "# produto 'up-parcial'" in texto
    assert "import route-policy" not in texto


def test_render_upstream_default_import_so_default(session, org_operadora, edge_device):
    up = models.Upstream(name="contig-f5", tipo="contingencia",
                         organization_id=org_operadora.id)
    session.add(up)
    session.flush()
    _link_upstream(session, up, edge_device, code="CIRC-UP-DEF",
                   import_profile_id=_perfil(session, "up-default", direction="import").id)

    texto = render_desejado(session, edge_device.id).texto
    assert "ip ip-prefix IP-PFX-DEFAULT-V4 index 10 permit 0.0.0.0/0" in texto
    assert "route-policy RP-64501-IMPORT-V4 permit node 10" in texto
    assert "if-match ip-prefix IP-PFX-DEFAULT-V4" in texto
    assert "community-filter" not in texto


def test_render_upstream_fail_safe_deny_all_sem_perfil(session, up, edge_device):
    _link_upstream(session, up, edge_device, code="CIRC-UP-FS", import_profile_id=None)

    resultado = render_desejado(session, edge_device.id)
    rp = next(b.texto for b in resultado.blocos
              if b.tipo == "route_policy_import" and "RP-64501-IMPORT-V4" in b.texto)
    # §4.1: sessão de upstream sem perfil ⇒ deny explícito, nunca accept-all
    assert "# fail-safe: sessão de upstream sem perfil de import — deny-all (nunca accept-all)" in rp
    assert "route-policy RP-64501-IMPORT-V4 deny node 10" in rp
    assert "permit" not in rp
    assert resultado.texto.count("import route-policy RP-64501-IMPORT-V4") == 1


def test_render_upstream_export_com_aplicacoes(session, up_com_sessao_upfull,
                                               bgp_session_principal, edge_device):
    up = up_com_sessao_upfull
    session.add_all([
        models.UpstreamCommunity(upstream_id=up.id, purpose="prepend", value="65530:20:2",
                                 regiao="SP", direcao="export"),
        models.UpstreamCommunity(upstream_id=up.id, purpose="blackhole", value="65530:666:0",
                                 direcao="export"),
        models.UpstreamCommunity(upstream_id=up.id, purpose="lp", value="65530:70:150",
                                 direcao="ambos"),
        # info de bloqueio: entra no import (CF de deny), nunca no apply do export
        models.UpstreamCommunity(upstream_id=up.id, purpose="info", value="65530:20:1",
                                 direcao="import", bloquear=True),
    ])
    bgp_session_principal.med = 50
    bgp_session_principal.prepend = 2
    session.commit()

    texto = render_desejado(session, edge_device.id).texto
    # aplicações em uma ÚNICA linha apply community (merge do template B2)
    assert "route-policy RP-64501-EXPORT-V4 permit node 10" in texto
    assert "# TE: prepend (SP - if-match na camada de render)" in texto
    assert "# TE: blackhole" in texto
    assert "# TE: lp" in texto
    # ordem (purpose, value, regiao) do serviço — o enum do PG vale na ordem
    # dos labels (blackhole < prepend < lp), não lexicográfica
    assert "apply community 65530:666:0 65530:20:2 65530:70:150" in texto
    assert texto.count("apply community ") == 1
    # med/prepend/asn_local vêm da sessão (asn_local = ASN do device)
    assert "apply med 50" in texto
    assert "apply as-path 65001 65001 additive" in texto


def test_render_upstream_dedup_definicoes_entre_sessoes_mesmo_asn(
        session, up_com_2_circuitos, edge_device, org_downstream):
    up = up_com_2_circuitos
    perfil = _perfil(session, "up-full", direction="import")
    for sessao in session.scalars(select(models.BgpSession).where(
            models.BgpSession.circuit_id.in_([
                uc.circuit_id for uc in session.scalars(
                    select(models.UpstreamCircuit).where(
                        models.UpstreamCircuit.upstream_id == up.id))]
            ))):
        sessao.import_profile_id = perfil.id
    session.add(models.BgpPrefixAuthorization(organization_id=org_downstream.id,
                                              family="ipv4", prefix="203.0.113.0/24"))
    session.commit()

    resultado = render_desejado(session, edge_device.id)
    tipos = [b.tipo for b in resultado.blocos]
    # duas sessões com o MESMO ASN+AFI ⇒ cada definição (por nome) sai 1×
    assert tipos.count("prefix_list") == 2          # proteção (IN) + internas
    assert tipos.count("community_filter") == 0
    assert tipos.count("route_policy_import") == 1
    assert tipos.count("route_policy_export") == 1
    assert tipos.count("bgp_peer") == 2
    # Ruling R5: a referência dos peers não some com o dedup
    assert resultado.texto.count("import route-policy RP-64501-IMPORT-V4") == 2
    assert resultado.texto.count("export route-policy RP-64501-EXPORT-V4") == 2


def test_render_upstream_nao_afasta_caminho_do_cliente(session, up_com_sessao_upfull,
                                                       edge_device, org_downstream):
    session.add(models.BgpPrefixAuthorization(organization_id=org_downstream.id,
                                              family="ipv4", prefix="192.0.2.0/24"))
    circ = models.Circuit(code="CIRC-CLI-1", organization_id=org_downstream.id,
                          site_id=edge_device.site_id, access_device_id=None,
                          access_port="GE0/0/1", edge_device_id=edge_device.id,
                          vlan_mode="none")
    session.add(circ)
    session.flush()
    session.add(models.BgpSession(
        circuit_id=circ.id, device_id=edge_device.id, afi="ipv4",
        local_address="100.64.20.1", remote_address="100.64.20.2",
        asn_local=65001, asn_remote=64512, allow_default_route=True,
        export_profile_id=_perfil(session, "default", direction="export").id))
    session.commit()

    resultado = render_desejado(session, edge_device.id)
    texto = resultado.texto
    # golden do caminho de CLIENTE: allowlist de autorizações com default
    assert "ip ip-prefix IP-PFX-64512-IN-V4 index 5 permit 0.0.0.0/0" in texto
    assert "ip ip-prefix IP-PFX-64512-IN-V4 index 10 permit 192.0.2.0/24" in texto
    assert ("route-policy RP-64512-IMPORT-V4 permit node 10\n"
            "if-match ip-prefix IP-PFX-64512-IN-V4") in texto
    assert "route-policy RP-64512-EXPORT-V4 permit node 10" in texto
    assert "peer 100.64.20.2 as-number 64512" in texto
    # e o caminho de upstream no MESMO device, com o ASN do provedor (64501)
    assert "route-policy RP-64501-IMPORT-V4 deny node 10" in texto
    assert "peer 100.64.10.2 as-number 64501" in texto
