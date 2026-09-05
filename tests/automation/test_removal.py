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


def _circuito(db_session, ambiente, *, code="circ-001", stack="ipv4"):
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.ipam import reservar_circuito

    circ = create_circuit(
        db_session,
        CircuitCreate(
            code=code, organization_id=ambiente["org"].id, site_id=ambiente["site"].id,
            access_device_id=ambiente["dev"].id, access_port="GE0/0/1",
            edge_device_id=ambiente["dev"].id, stack=stack, vlan_mode="unica",
            edge_trunk="GE1/0/0", p2p_v4_len=31,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    return circ


def _sessao(db_session, circ, dev, *, afi="ipv4", remote="100.64.1.2", local=None, ativa=True):
    from gerenet.domain.schemas import BgpSessionCreate
    from gerenet.domain.services.bgp_sessions import create_session, disable_session

    local_address = local or ("100.64.1.1" if afi == "ipv4" else "2001:db8::1")
    sessao = create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=dev.id, afi=afi,
            local_address=local_address, remote_address=remote,
            asn_local=65000, asn_remote=64512,
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
