"""Motor de descoberta: candidatos e classificação (spec §4–§5). Read-only."""
from pathlib import Path

from sqlalchemy import select

from gerenet.automation.discovery import listar_candidatos
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import ignorar_candidato
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _ambiente(db_session, *, asn=65001):
    """Equipamento com site e a configuração da fixture salva em disco."""
    site = create_site(db_session, SiteCreate(name="pop-desc", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc",
                                                 management_address="10.0.0.1", asn=asn),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    return dev


def _com_config(db_session, dev, tmp_path: Path):
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    snap = models.DeviceSnapshot(device_id=dev.id, status="success",
                                 raw_files={"config_backup": [str(arquivo)]})
    db_session.add(snap)
    db_session.commit()
    return snap


def test_sem_snapshot_avisa_e_nao_devolve_lista_vazia_muda(db_session) -> None:
    dev = _ambiente(db_session)
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.candidatos == []
    assert resultado.snapshot_id is None
    assert resultado.aviso is not None
    assert "configuração" in resultado.aviso


def test_todos_os_peers_desconhecidos_sao_candidatos(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert {p.remote_address for p in resultado.candidatos} == {
        "100.64.10.1", "100.64.10.4", "100.64.10.3",
        "2804:194c:1000::1100:73:2", "10.99.0.1",
    }


def test_peer_interno_vai_para_a_lista_separada(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert [p.remote_address for p in resultado.internos] == ["10.0.0.9"]
    assert resultado.internos[0].classificacao == "interno"
    assert "65001" in resultado.internos[0].motivo


def test_peer_que_casa_com_sessao_da_sot_nao_e_candidato(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-001", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.1" not in {p.remote_address for p in resultado.candidatos}


def test_sessao_desativada_conta_como_conhecida(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-002", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512, admin_status=False,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.1" not in {p.remote_address for p in resultado.candidatos}


def test_ignorado_nao_e_candidato(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    ignorar_candidato(db_session, device_id=dev.id, vrf=None, afi="ipv4",
                      remote_address="100.64.10.4", motivo="cliente saiu", actor="cli")
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.4" not in {p.remote_address for p in resultado.candidatos}


def test_classificacao_por_organizacao(db_session, tmp_path) -> None:
    """O ASN é 64515, e não 64501: 64496-64511 é a faixa de documentação do
    RFC 5398 e o validador a recusa. A organização precisa ser criável pelo
    serviço, senão o teste afirma um ambiente que o produto não deixaria existir."""
    dev = _ambiente(db_session)
    create_organization(db_session, OrganizationCreate(name="Operadora Gama", asn=64515,
                                                       kind="operadora"), actor="cli")
    create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                        actor="cli")
    _com_config(db_session, dev, tmp_path)
    por_endereco = {p.remote_address: p for p in listar_candidatos(db_session, dev.id).candidatos}
    assert por_endereco["100.64.10.3"].classificacao == "upstream"
    assert "Operadora Gama" in por_endereco["100.64.10.3"].motivo
    assert por_endereco["100.64.10.1"].classificacao == "downstream"
    assert "Cliente Alfa" in por_endereco["100.64.10.1"].motivo


def test_sem_organizacao_fica_nao_confirmada(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    por_endereco = {p.remote_address: p for p in listar_candidatos(db_session, dev.id).candidatos}
    beta = por_endereco["100.64.10.4"]
    assert beta.classificacao == "downstream"
    assert "não confirmada" in beta.motivo


def test_snapshot_sem_config_devolve_aviso(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"interfaces": []}))
    db_session.commit()
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.candidatos == []
    assert resultado.aviso is not None


def test_captura_sem_bloco_bgp_avisa_o_que_nao_foi_lido(db_session, tmp_path) -> None:
    """Sem bloco `bgp` o parser avisa; a lista vem vazia, mas não muda (§3)."""
    dev = _ambiente(db_session)
    arquivo = tmp_path / "sem-bgp.txt"
    arquivo.write_text("sysname ne8000-desc\ninterface GE0/0/1\n description uplink\n",
                       encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.snapshot_id is not None
    assert resultado.aviso is not None
    assert "bgp" in resultado.aviso  # o aviso da leitura, não o de "sem coleta"
    assert resultado.candidatos == []
    assert resultado.internos == []


def test_endereco_ipv6_conhecido_independe_da_caixa(db_session, tmp_path) -> None:
    """O parser guarda a forma do equipamento (`2804:194C:1000::...` na fixture)
    e a SoT é digitada à mão: aqui em minúsculas e com os zeros expandidos."""
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-V6", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv6",
        local_address="2804:194c:1000:0:0:1100:73:1",
        remote_address="2804:194c:1000:0:0:1100:73:2",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)

    resultado = listar_candidatos(db_session, dev.id)
    assert {p.remote_address for p in resultado.candidatos} == {
        "100.64.10.1", "100.64.10.4", "100.64.10.3", "10.99.0.1",
    }


def test_vrf_faz_parte_da_identidade(db_session, tmp_path) -> None:
    """A VRF do peer sai do circuito da sessão: sessão fora da VRF não cobre."""
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    publico = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-VRF-1", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    na_vrf = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-VRF-2", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id, vrf="VPNA",
    ), actor="cli")
    # Cada sessão carrega o endereço remoto do peer que está do OUTRO lado.
    db_session.add(models.BgpSession(
        circuit_id=publico.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="10.99.0.1",
        asn_local=65001, asn_remote=64513,
    ))
    db_session.add(models.BgpSession(
        circuit_id=na_vrf.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)

    por_endereco = {p.remote_address: p for p in listar_candidatos(db_session, dev.id).candidatos}
    assert por_endereco["10.99.0.1"].vrf == "VPNA"   # sessão pública não cobre o peer da VRF
    assert por_endereco["100.64.10.1"].vrf is None   # sessão na VRF não cobre o peer público

    # A sessão na VRF do peer, essa sim, cobre.
    db_session.add(models.BgpSession(
        circuit_id=na_vrf.id, device_id=dev.id, afi="ipv4",
        local_address="10.99.0.254", remote_address="10.99.0.1",
        asn_local=65001, asn_remote=64513,
    ))
    db_session.commit()
    assert "10.99.0.1" not in {
        p.remote_address for p in listar_candidatos(db_session, dev.id).candidatos
    }


from gerenet.automation.discovery import listar_propostas


def _propostas(db_session, dev):
    return {p.vid: p for p in listar_propostas(db_session, dev.id).propostas}


def test_proposta_do_downstream_dual_monta_a_cadeia(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                        actor="cli")
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert alfa.stack == "dual"
    assert alfa.p2p_v4_len == 31
    assert alfa.vid == 1001
    assert alfa.vlans == [{"vid": 1001, "kind": "vlan", "family": None}]
    assert alfa.prefixos == [
        {"network": "100.64.10.0/31", "ponta_local": "inferior"},
        {"network": "2804:194C:1000::1100:73:0/126", "ponta_local": "inferior"},
    ]
    assert {s["afi"] for s in alfa.sessoes} == {"ipv4", "ipv6"}
    assert alfa.site_id is not None


def test_ponta_superior_do_cliente_beta(db_session, tmp_path) -> None:
    """`100.64.10.5` é a ponta de cima do /31 `100.64.10.4/31` (spec §7)."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    beta = _propostas(db_session, dev)[2001]
    assert beta.stack == "ipv4"
    assert beta.prefixos[0]["ponta_local"] == "superior"


def test_pendencias_obrigatorias_do_downstream(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    tipos = {p.tipo for p in alfa.pendencias}
    assert "organizacao_ausente" in tipos
    assert "acesso_desconhecido" in tipos
    assert "senha_nao_legivel" in tipos
    assert "perfil_indeterminado" in tipos
    assert alfa.organizacao_id is None
    assert alfa.organizacao_sugerida == "CLIENTE-ALFA"


def test_com_organizacao_cadastrada_a_pendencia_some(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert alfa.organizacao_id == org.id
    assert "organizacao_ausente" not in {p.tipo for p in alfa.pendencias}


def test_veredito_com_pendencia_e_nao_adotavel_com_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert alfa.veredito == "adotavel_com_pendencias"


def test_vlan_tomada_e_conflito(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Outro Cliente", asn=64999),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    outro = create_circuit(db_session, CircuitCreate(
        code="CIRC-TOMADO", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, vid=1001, kind="vlan", circuit_id=outro.id))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "vlan_tomada" in {c.tipo for c in alfa.conflitos}
    assert alfa.veredito == "nao_adotavel"


def test_endereco_fora_de_par_p2p_e_conflito(db_session, tmp_path) -> None:
    """IX com sub-rede compartilhada não cabe no IPAM, que só conhece p2p."""
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.4001\n"
        " vlan-type dot1q 4001\n"
        " ip address 200.219.0.1 255.255.255.240\n"
        "#\n"
        "bgp 65001\n"
        " peer 200.219.0.2 as-number 64999\n"
        " peer 200.219.0.2 description PEER-IX\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert "enlace_nao_p2p" in {c.tipo for c in prop.conflitos}


def test_endereco_sem_subinterface_e_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "bgp 65001\n peer 100.64.99.1 as-number 64999\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert "endereco_sem_subinterface" in {c.tipo for c in prop.conflitos}


def test_leitura_parcial_ainda_propoe(db_session, tmp_path) -> None:
    """Aviso de leitura parcial não pode zerar a lista: o que foi lido vale.

    Um cabeçalho de família fora do escopo faz o parser avisar e seguir; os peers
    da instância pública foram lidos inteiros e viram proposta normalmente.
    """
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.6001\n"
        " vlan-type dot1q 6001\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n"
        " ipv4-family multicast\n"
        "  peer 10.0.0.9 enable\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    resultado = listar_propostas(db_session, dev.id)
    assert resultado.aviso is not None
    assert resultado.snapshot_id is not None
    assert [c.remote_address for p in resultado.propostas for c in p.candidatos] == [
        "100.64.10.1",
    ]


def test_asn_divergente_do_cadastro_vira_pendencia(db_session, tmp_path) -> None:
    """A configuração diz `bgp 65001` e o cadastro do equipamento diz outro ASN."""
    dev = _ambiente(db_session, asn=65002)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "asn_do_equipamento" in {p.tipo for p in alfa.pendencias}


def test_mesmo_asn_em_enlaces_diferentes_vira_pendencia(db_session, tmp_path) -> None:
    """Dois enlaces com o mesmo ASN podem ser um dual stack com VLAN separada
    (um circuito) ou dois circuitos: o sistema não decide, ele avisa."""
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.5001\n"
        " vlan-type dot1q 5001\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "interface Eth-Trunk127.5002\n"
        " vlan-type dot1q 5002\n"
        " ipv6 address 2804:194C:1000::1100:73:1 126\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " peer 2804:194C:1000::1100:73:2 as-number 64512\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    por_vid = _propostas(db_session, dev)
    assert "mesmo_asn_em_outro_enlace" in {p.tipo for p in por_vid[5001].pendencias}
    assert "mesmo_asn_em_outro_enlace" in {p.tipo for p in por_vid[5002].pendencias}


def _com_config_e_interfaces(db_session, dev, tmp_path: Path, *, vpn: str | None = None):
    """Snapshot com a config da fixture e o recurso `interfaces` correspondente.

    O `display ip interface brief` já vai em toda coleta (collectors.py) e é a
    única fonte da VRF a que o endereço pertence.
    """
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success",
        raw_files={"config_backup": [str(arquivo)]},
        resources={"interfaces": [
            {"nome": "Eth-Trunk127.1001", "phy": "up", "protocolo": "up",
             "enderecos_v4": ["100.64.10.0/31"],
             "enderecos_v6": ["2804:194C:1000::1100:73:1/126"], "vpn": vpn},
            {"nome": "Eth-Trunk127.2001", "phy": "up", "protocolo": "up",
             "enderecos_v4": ["100.64.10.5/31"], "enderecos_v6": [], "vpn": vpn},
            {"nome": "Eth-Trunk127.3001", "phy": "up", "protocolo": "up",
             "enderecos_v4": ["100.64.10.2/31"], "enderecos_v6": [], "vpn": vpn},
        ]},
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def test_coleta_concordando_nao_gera_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config_e_interfaces(db_session, dev, tmp_path)
    tipos = {c.tipo for p in listar_propostas(db_session, dev.id).propostas
             for c in p.conflitos}
    assert "endereco_fora_da_coleta" not in tipos
    assert "vrf_do_enlace_divergente" not in tipos


def test_vrf_divergente_entre_config_e_coleta_e_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config_e_interfaces(db_session, dev, tmp_path, vpn="VPNA")
    alfa = _propostas(db_session, dev)[1001]
    assert "vrf_do_enlace_divergente" in {c.tipo for c in alfa.conflitos}


def test_sem_o_recurso_de_interfaces_nada_e_conferido(db_session, tmp_path) -> None:
    """Ausência de dado não é divergência: coleta antiga sem o recurso passa."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    tipos = {c.tipo for p in listar_propostas(db_session, dev.id).propostas
             for c in p.conflitos}
    assert "interface_ausente_na_coleta" not in tipos


def test_interface_ausente_na_coleta_e_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(
        device_id=dev.id, status="success",
        raw_files={"config_backup": [str(arquivo)]},
        resources={"interfaces": [{"nome": "LoopBack0", "phy": "up", "protocolo": "up",
                                   "enderecos_v4": ["10.0.0.1/32"],
                                   "enderecos_v6": [], "vpn": None}]},
    ))
    db_session.commit()
    tipos = {c.tipo for p in listar_propostas(db_session, dev.id).propostas
             for c in p.conflitos}
    assert "interface_ausente_na_coleta" in tipos


def test_enlace_sem_vlan_e_a_propria_interface(db_session, tmp_path) -> None:
    """Sem VLAN o enlace é a porta: dois `/31` em portas diferentes são dois
    circuitos, e não um agrupado pelo `vid` que não existe."""
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface GE0/0/1\n"
        " ip address 100.64.20.0 255.255.255.254\n"
        "#\n"
        "interface GE0/0/2\n"
        " ip address 100.64.21.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.20.1 as-number 64512\n"
        " peer 100.64.21.1 as-number 64513\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    propostas = listar_propostas(db_session, dev.id).propostas
    assert [p.subinterface for p in propostas] == ["GE0/0/1", "GE0/0/2"]
    assert [p.circuit_code_sugerido for p in propostas] == [None, None]


def test_prefixo_tomado_na_caixa_do_equipamento_e_conflito(db_session, tmp_path) -> None:
    """O IPAM grava o /126 com a caixa do bloco do site (`2804:194C:1000::/48`,
    o default dos settings): a conferência não pode depender da caixa."""
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Outro Cliente", asn=64999),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    outro = create_circuit(db_session, CircuitCreate(
        code="CIRC-V6-TOMADO", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.IpPrefix(site_id=site.id, network="2804:194C:1000::1100:73:0/126",
                                   kind="p2p", circuit_id=outro.id))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "prefixo_tomado" in {c.tipo for c in alfa.conflitos}
    assert alfa.veredito == "nao_adotavel"
