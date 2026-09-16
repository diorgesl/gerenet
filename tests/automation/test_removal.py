"""Render inverso (remove) — blocos a partir do ENCONTRADO no snapshot (spec §5.2)."""
from pathlib import Path

from sqlalchemy import select

from gerenet.automation import naming, removal
from gerenet.domain import models


def _snapshot(db_session, device, *, interfaces=None, peers=None, backup="", tmp_path: Path):
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(backup, encoding="utf-8")
    snap = models.DeviceSnapshot(
        device_id=device.id, status="success",
        resources={"interfaces": interfaces or [], "bgp_peers": peers or []},
        raw_files={"config_backup": [str(arquivo)]},
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _ambiente(db_session):
    """site (com bloco p2p) + device (ASN 65000) + org (ASN 64512)."""
    from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
    from gerenet.domain.services.devices import create_device
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.sites import create_site, link_device

    site = create_site(
        db_session, SiteCreate(name="pop-rm", p2p_ipv4_block="10.0.0.0/24"), actor="cli"
    )
    dev = create_device(
        db_session, DeviceCreate(name="ne8000-rm", management_address="10.0.0.1", asn=65000),
        actor="cli",
    )
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-x", asn=64512), actor="cli")
    return {"site": site, "dev": dev, "org": org}


def _circuito(db_session, ambiente, *, code="circ-001", stack="ipv4", org=None, vrf=None):
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.ipam import reservar_circuito

    circ = create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=(org or ambiente["org"]).id,
            site_id=ambiente["site"].id,
            access_device_id=ambiente["dev"].id, access_port="GE0/0/1",
            edge_device_id=ambiente["dev"].id, stack=stack, vlan_mode="unica",
            edge_trunk="GE1/0/0", p2p_v4_len=31, vrf=vrf,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    return circ


def _sessao(
    db_session, circ, dev, *, afi="ipv4", remote="100.64.1.2", local=None, ativa=True,
    asn_remote=64512, import_route_policy=None, export_route_policy=None,
):
    from gerenet.domain.schemas import BgpSessionCreate
    from gerenet.domain.services.bgp_sessions import create_session, disable_session

    local_address = local or ("100.64.1.1" if afi == "ipv4" else "2001:db8::1")
    sessao = create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=dev.id, afi=afi,
            local_address=local_address, remote_address=remote,
            asn_local=65000, asn_remote=asn_remote,
            import_route_policy=import_route_policy,
            export_route_policy=export_route_policy,
        ),
        actor="cli",
    )
    if not ativa:
        disable_session(db_session, sessao.id, actor="cli")
    return sessao


def _vid(db_session, circ):
    return db_session.scalar(
        select(models.Vlan.vid).where(models.Vlan.circuit_id == circ.id)
    )


def test_remocao_v4_ordem_e_comandos(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb["dev"])
    vid = _vid(db_session, circ)
    subif = naming.subinterface("GE1/0/0", vid)
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"ip ip-prefix {naming.pfx_in(64512, 'ipv4')} index 10 permit 192.0.2.0/24\n"
            f"route-policy {naming.rp_import(64512, 'ipv4')} permit node 10\n"
            f"route-policy {naming.rp_export(64512, 'ipv4')} permit node 10\n"
            f"interface {subif}\n"
            f" vlan-type dot1q vid {vid}\n"
            f" ip address 100.64.1.1 255.255.255.254\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[{"nome": subif, "phy": "up", "protocolo": "up",
                     "enderecos_v4": ["100.64.1.1/31"], "enderecos_v6": []}],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    assert [b["tipo"] for b in blocos] == [
        "bgp_peer", "route_policy_export", "route_policy_import", "prefix_list", "subinterface",
    ]
    assert all(b["acao"] == "delete" for b in blocos)
    assert blocos[0]["comandos"] == ["bgp 65000", "undo peer 100.64.1.2"]
    assert blocos[1]["comandos"] == [f"undo route-policy {naming.rp_export(64512, 'ipv4')}"]
    assert blocos[2]["comandos"] == [f"undo route-policy {naming.rp_import(64512, 'ipv4')}"]
    assert blocos[3]["comandos"] == [f"undo ip ip-prefix {naming.pfx_in(64512, 'ipv4')}"]
    assert blocos[-1]["comandos"] == [f"undo interface {subif}"]


def test_remocao_peer_compartilhado_usa_undo_por_familia(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    circ2 = _circuito(db_session, amb, code="circ-002")
    # Mesmo remote, local diferente (evita _colidente_par). Criada ANTES da
    # sessão do circuito alvo e desativada — o serviço conflita (device, afi)
    # apenas com sessões ativas, e a config do peer pode existir no equipamento.
    _sessao(db_session, circ2, amb["dev"], remote="100.64.1.2", local="100.64.2.1", ativa=False)
    sessao = _sessao(db_session, circ, amb["dev"])
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup="#",
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    peers_blocks = [b for b in blocos if b["tipo"] == "bgp_peer"]
    assert peers_blocks == [{
        "tipo": "bgp_peer", "objeto": "session", "objeto_id": sessao.id,
        "acao": "delete",
        "comandos": ["bgp 65000", "ipv4-family unicast", "undo peer 100.64.1.2 enable"],
    }]


def test_remocao_nao_remove_definicao_em_uso(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    circ2 = _circuito(db_session, amb, code="circ-002")
    # Outra sessão com o MESMO (asn_remote, afi) => mesmos nomes de RP/prefix-list;
    # remote DIFERENTE para isolar esta regra (o peer do teste 1 continua completo).
    # Criada antes da sessão do circuito alvo e desativada (conflito de linha ativa).
    _sessao(db_session, circ2, amb["dev"], remote="100.64.1.99", local="100.64.2.1", ativa=False)
    _sessao(db_session, circ, amb["dev"])
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"ip ip-prefix {naming.pfx_in(64512, 'ipv4')} index 10 permit 192.0.2.0/24\n"
            f"route-policy {naming.rp_import(64512, 'ipv4')} permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    assert {b["tipo"] for b in blocos} == {"bgp_peer"}


def test_remocao_sem_snapshot_nao_gera_plano(db_session):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb["dev"])
    assert removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=None) == []


def test_remocao_dedupe_sessoes_do_mesmo_circuito(db_session, tmp_path):
    """Re-peering (1 ativa + 1 desativada no mesmo circuito, mesmos ASN/afi/remote)
    => UMA definição undo RP/prefix e UM undo peer por família (espelha
    _apensa_definicao do render forward)."""
    from gerenet.domain.schemas import OrganizationCreate
    from gerenet.domain.services.organizations import create_organization

    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    org2 = create_organization(
        db_session, OrganizationCreate(name="cliente-y", asn=64513), actor="cli"
    )
    # Outro circuito/org ASN 64513: compartilha o REMOTE (protege o peer) sem
    # compartilhar os nomes §25.4 de 64512. Criada e desativada antes.
    circ2 = _circuito(db_session, amb, code="circ-002", org=org2)
    _sessao(
        db_session, circ2, amb["dev"], remote="100.64.1.2", local="100.64.3.1",
        ativa=False, asn_remote=64513,
    )
    # Sessão legada desativada (mesmo remote/nomes) antes da ativa: o serviço
    # conflita (device+afi) apenas com sessões ativas.
    s_legada = _sessao(
        db_session, circ, amb["dev"], remote="100.64.1.2", local="100.64.2.1",
        ativa=False,
    )
    _sessao(db_session, circ, amb["dev"], remote="100.64.1.2", local="100.64.1.1")
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"ip ip-prefix {naming.pfx_in(64512, 'ipv4')} index 10 permit 192.0.2.0/24\n"
            f"route-policy {naming.rp_import(64512, 'ipv4')} permit node 10\n"
            f"route-policy {naming.rp_export(64512, 'ipv4')} permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    peers = [b for b in blocos if b["tipo"] == "bgp_peer"]
    assert peers == [{
        "tipo": "bgp_peer", "objeto": "session", "objeto_id": s_legada.id,
        "acao": "delete",
        "comandos": ["bgp 65000", "ipv4-family unicast", "undo peer 100.64.1.2 enable"],
    }]
    assert [b["tipo"] for b in blocos] == [
        "bgp_peer", "route_policy_export", "route_policy_import", "prefix_list",
    ]
    # dedup: cada definição §25.4 entra UMA vez, mesmo com duas sessões no circuito
    assert sum(b["tipo"] == "route_policy_export" for b in blocos) == 1
    assert sum(b["tipo"] == "route_policy_import" for b in blocos) == 1
    assert sum(b["tipo"] == "prefix_list" for b in blocos) == 1


def test_remocao_usa_o_nome_importado_da_politica(db_session, tmp_path):
    """§4.1: o undo da RP sai com o nome lido no equipamento, não com o do §25.4.

    O portão `_tem_route_policy` confere o nome contra o backup coletado: com o
    nome do §25.4 o bloco nem era emitido, e a definição ficava órfã na caixa.
    """
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(
        db_session, circ, amb["dev"],
        import_route_policy="RP-DO-EQUIPAMENTO-IN",
        export_route_policy="RP-DO-EQUIPAMENTO-OUT",
    )
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            "route-policy RP-DO-EQUIPAMENTO-IN permit node 10\n"
            "route-policy RP-DO-EQUIPAMENTO-OUT permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    assert [b["tipo"] for b in blocos] == [
        "bgp_peer", "route_policy_export", "route_policy_import",
    ]
    por_tipo = {b["tipo"]: b["comandos"] for b in blocos}
    assert por_tipo["route_policy_import"] == ["undo route-policy RP-DO-EQUIPAMENTO-IN"]
    assert por_tipo["route_policy_export"] == ["undo route-policy RP-DO-EQUIPAMENTO-OUT"]
    # o nome do §25.4 não sobra em bloco nenhum
    emitido = " ".join(c for b in blocos for c in b["comandos"])
    assert naming.rp_import(64512, "ipv4") not in emitido
    assert naming.rp_export(64512, "ipv4") not in emitido


def test_remocao_mesmo_asn_com_nome_efetivo_diferente_ainda_desfaz_a_politica(
    db_session, tmp_path,
):
    """§4.1: o compartilhamento é o NOME efetivo, não o par (asn_remote, afi).

    A sessão do outro circuito tem o mesmo ASN+afi, mas política própria (a do
    §25.4, porque as colunas dela são nulas): são definições diferentes no
    equipamento. Tratar o ASN+afi como se fosse o nome engolia o undo e deixava
    a definição importada órfã na caixa.
    """
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    circ2 = _circuito(db_session, amb, code="circ-002")
    # mesmo ASN+afi, nome efetivo diferente; desativada e criada antes (o serviço
    # conflita device+afi só com sessão ativa), remote diferente do alvo.
    _sessao(db_session, circ2, amb["dev"], remote="100.64.1.99", local="100.64.2.1", ativa=False)
    _sessao(db_session, circ, amb["dev"], import_route_policy="RP-DO-EQUIPAMENTO-IN")
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"ip ip-prefix {naming.pfx_in(64512, 'ipv4')} index 10 permit 192.0.2.0/24\n"
            "route-policy RP-DO-EQUIPAMENTO-IN permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    por_tipo = {b["tipo"]: b["comandos"] for b in blocos}
    assert por_tipo["route_policy_import"] == ["undo route-policy RP-DO-EQUIPAMENTO-IN"]
    # A prefix-list fica de fora: o nome dela continua saindo do ASN do par
    # (§25.4), e a sessão do circ-002 referencia a mesma `IP-PFX-64512-IN-V4`.
    assert "prefix_list" not in por_tipo


def test_remocao_nao_desfaz_politica_de_outro_asn_com_o_mesmo_nome(db_session, tmp_path):
    """§4.1: nome efetivo igual em ASN diferente = uma definição, um dono.

    Dois peers de operadoras distintas podem carregar a mesma política de
    operadora (é para isso que a coluna importada existe). Derrubá-la no
    `continue` do par antigo (asn_remote, afi) mandaria `undo route-policy` para
    uma definição que o outro circuito ainda referencia.
    """
    from gerenet.domain.schemas import OrganizationCreate
    from gerenet.domain.services.organizations import create_organization

    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    org2 = create_organization(
        db_session, OrganizationCreate(name="operadora-y", asn=64513), actor="cli"
    )
    circ2 = _circuito(db_session, amb, code="circ-002", org=org2)
    # ASN diferente, mesmo nome lido: a guarda tem que olhar o NOME.
    _sessao(
        db_session, circ2, amb["dev"], remote="100.64.1.99", local="100.64.2.1",
        ativa=False, asn_remote=64513,
        import_route_policy="RP-OPERADORA-IN", export_route_policy="RP-OPERADORA-OUT",
    )
    _sessao(
        db_session, circ, amb["dev"],
        import_route_policy="RP-OPERADORA-IN", export_route_policy="RP-OPERADORA-OUT",
    )
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"ip ip-prefix {naming.pfx_in(64512, 'ipv4')} index 10 permit 192.0.2.0/24\n"
            "route-policy RP-OPERADORA-IN permit node 10\n"
            "route-policy RP-OPERADORA-OUT permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    tipos = [b["tipo"] for b in blocos]
    # Controle: o laço passou pela sessão e a prefix-list do ASN local saiu — a
    # guarda segurou só a definição que o outro circuito referencia.
    assert "prefix_list" in tipos
    assert "route_policy_import" not in tipos
    assert "route_policy_export" not in tipos
    emitido = " ".join(c for b in blocos for c in b["comandos"])
    assert "undo route-policy RP-OPERADORA-IN" not in emitido
    assert "undo route-policy RP-OPERADORA-OUT" not in emitido


def test_remocao_cruzada_nao_derruba_a_politica_da_outra_direcao(db_session, tmp_path):
    """§4.1: a definição é uma só no VRP — a guarda cruza import e export.

    O controle vem primeiro: esta sessão, este backup e nenhuma sessão cruzada
    no device, e os dois undos saem. Depois entra a sessão de outro circuito
    (ASN diferente e VRF própria, que é o que a deixa ativa sem conflitar com a
    linha do alvo) usando o nome do import no EXPORT e o nome do export no
    IMPORT: nenhum dos dois undos pode sair, porque nos dois casos a definição
    derrubada seria a mesma que a outra sessão referencia.
    """
    from gerenet.domain.schemas import OrganizationCreate
    from gerenet.domain.services.organizations import create_organization

    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(
        db_session, circ, amb["dev"],
        import_route_policy="RP-OPERADORA-IN", export_route_policy="RP-OPERADORA-OUT",
    )
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            "route-policy RP-OPERADORA-IN permit node 10\n"
            "route-policy RP-OPERADORA-OUT permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    por_tipo = {b["tipo"]: b["comandos"] for b in blocos}
    assert por_tipo["route_policy_import"] == ["undo route-policy RP-OPERADORA-IN"]
    assert por_tipo["route_policy_export"] == ["undo route-policy RP-OPERADORA-OUT"]

    # A sessão cruzada: outro circuito, outro ASN, e os nomes trocados de direção.
    org2 = create_organization(
        db_session, OrganizationCreate(name="operadora-y", asn=64513), actor="cli"
    )
    circ2 = _circuito(db_session, amb, code="circ-002", org=org2, vrf="vpn-cruzada")
    _sessao(
        db_session, circ2, amb["dev"], remote="100.64.1.99", local="100.64.2.1",
        asn_remote=64513,
        import_route_policy="RP-OPERADORA-OUT", export_route_policy="RP-OPERADORA-IN",
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    # O bloco do peer continua saindo: o laço passou pela sessão.
    assert [b["tipo"] for b in blocos] == ["bgp_peer"]
    emitido = " ".join(c for b in blocos for c in b["comandos"])
    assert "undo route-policy RP-OPERADORA-IN" not in emitido
    assert "undo route-policy RP-OPERADORA-OUT" not in emitido


def test_remocao_sem_politica_importada_mantem_o_nome_do_25_4(db_session, tmp_path):
    """§4.1: com as duas colunas nulas, o undo segue com o nome derivado do ASN."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb["dev"])
    snap = _snapshot(
        db_session, amb["dev"], tmp_path=tmp_path,
        backup=(
            f"route-policy {naming.rp_import(64512, 'ipv4')} permit node 10\n"
            f"route-policy {naming.rp_export(64512, 'ipv4')} permit node 10\n"
        ),
        peers=[{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512, "estado": "Established"}],
        interfaces=[],
    )
    blocos = removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap)
    por_tipo = {b["tipo"]: b["comandos"] for b in blocos}
    assert por_tipo["route_policy_import"] == [
        f"undo route-policy {naming.rp_import(64512, 'ipv4')}"
    ]
    assert por_tipo["route_policy_export"] == [
        f"undo route-policy {naming.rp_export(64512, 'ipv4')}"
    ]


def test_remocao_recursos_incompletos_nao_gera_plano(db_session, tmp_path):
    """resources={} (ou sem as chaves) com backup presente => [] (coleta fresca)."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb["dev"])
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        f"route-policy {naming.rp_import(64512, 'ipv4')} permit node 10\n",
        encoding="utf-8",
    )
    snap = models.DeviceSnapshot(
        device_id=amb["dev"].id, status="success", resources={},
        raw_files={"config_backup": [str(arquivo)]},
    )
    db_session.add(snap)
    db_session.commit()
    assert removal.blocos_remocao(db_session, circ, amb["dev"].id, snapshot=snap) == []


def test_circuito_liberado_nao_derruba_subinterface_realocada(db_session, tmp_path):
    """Reserva liberada não manda `undo interface` do VID que outro circuito pegou."""
    from gerenet.domain.services.ipam import liberar_circuito

    amb = _ambiente(db_session)
    circ_a = _circuito(db_session, amb, code="circ-lib-a")
    (vlan_a,) = db_session.scalars(
        select(models.Vlan).where(models.Vlan.circuit_id == circ_a.id)
    )
    liberar_circuito(db_session, circ_a.id, actor="cli")
    circ_b = _circuito(db_session, amb, code="circ-lib-b")  # first-fit devolve o VID liberado
    (vlan_b,) = db_session.scalars(
        select(models.Vlan).where(models.Vlan.circuit_id == circ_b.id)
    )
    assert vlan_b.vid == vlan_a.vid

    nome = naming.subinterface(circ_a.edge_trunk, vlan_a.vid)
    snap = _snapshot(db_session, amb["dev"], interfaces=[{"nome": nome}], tmp_path=tmp_path)

    blocos_a = removal.blocos_remocao(db_session, circ_a, amb["dev"].id, snapshot=snap)
    assert [b["tipo"] for b in blocos_a if b["tipo"] == "subinterface"] == []
    # o dono atual continua removendo a própria subinterface
    blocos_b = removal.blocos_remocao(db_session, circ_b, amb["dev"].id, snapshot=snap)
    assert any(b["tipo"] == "subinterface" for b in blocos_b)
