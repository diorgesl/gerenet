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
        "interface Eth-Trunk127.2601\n"
        " vlan-type dot1q 2601\n"
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
        "interface Eth-Trunk127.2501\n"
        " vlan-type dot1q 2501\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "interface Eth-Trunk127.2502\n"
        " vlan-type dot1q 2502\n"
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
    assert "mesmo_asn_em_outro_enlace" in {p.tipo for p in por_vid[2501].pendencias}
    assert "mesmo_asn_em_outro_enlace" in {p.tipo for p in por_vid[2502].pendencias}


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


def _com_texto(db_session, dev, tmp_path: Path, texto: str):
    """Snapshot com a configuração escrita no próprio teste."""
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(texto, encoding="utf-8")
    snap = models.DeviceSnapshot(device_id=dev.id, status="success",
                                 raw_files={"config_backup": [str(arquivo)]})
    db_session.add(snap)
    db_session.commit()
    return snap


def _circuito_tomado(db_session, dev, *, code: str, vrf: str | None = None):
    """Circuito de outro cliente no mesmo site (o código já está em uso)."""
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    org = create_organization(db_session, OrganizationCreate(name="Outro Cliente", asn=64999),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    return create_circuit(db_session, CircuitCreate(
        code=code, organization_id=org.id, site_id=site.id, vrf=vrf,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")


def test_prefixo_tomado_nao_depende_da_caixa_do_cadastro(db_session, tmp_path) -> None:
    """O bloco v6 do site pode ter sido digitado em minúsculas: o IPAM grava a
    caixa do cadastro (`_preserva_caixa`) e o equipamento escreve a dele. O
    conflito é da reserva, não da grafia — sem isso um `/126` já reservado
    volta como adotável e colide no índice único do banco na hora da adoção."""
    dev = _ambiente(db_session)
    outro = _circuito_tomado(db_session, dev, code="CIRC-V6-MINUSCULO")
    site = db_session.scalar(select(models.Site))
    db_session.add(models.IpPrefix(site_id=site.id, network="2804:194c:1000::1100:73:0/126",
                                   kind="p2p", circuit_id=outro.id))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "prefixo_tomado" in {c.tipo for c in alfa.conflitos}
    assert alfa.veredito == "nao_adotavel"


def test_codigo_sugerido_em_uso_vira_pendencia(db_session, tmp_path) -> None:
    """`ADOC-<ASN>-<VID>` já cadastrado: o operador escolhe outro na revisão."""
    dev = _ambiente(db_session)
    _circuito_tomado(db_session, dev, code="ADOC-64512-1001")
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert alfa.circuit_code_sugerido == "ADOC-64512-1001"
    pendencia = next(p for p in alfa.pendencias if p.tipo == "codigo_em_uso")
    assert "ADOC-64512-1001" in pendencia.descricao


def test_equipamento_sem_site_e_conflito(db_session, tmp_path) -> None:
    """O IPAM é por site: sem site vinculado não há reserva possível."""
    dev = create_device(db_session, DeviceCreate(name="ne8000-sem-site",
                                                 management_address="10.0.0.8", asn=65001),
                        actor="cli")
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert {c.tipo for c in alfa.conflitos} == {"sem_site"}
    assert alfa.veredito == "nao_adotavel"


_SEM_ASN = (
    "interface Eth-Trunk127.2801\n"
    " vlan-type dot1q 2801\n"
    " ip address 100.64.10.0 255.255.255.254\n"
    "#\n"
    "bgp 65001\n"
    " peer 100.64.10.1 description CLIENTE-SEM-ASN\n"
    " peer 100.64.10.1 route-policy RP-64512-IMPORT-V4 import\n"
)


def test_peer_sem_as_number_nao_sugere_codigo(db_session, tmp_path) -> None:
    """Sem `as-number` lido não há ASN para o código — e o `codigo_em_uso` só
    confere o código que existe: `ADOC-None-2801` seria um código mostrado ao
    operador e nunca conferido contra a SoT."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, _SEM_ASN)
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert prop.vid == 2801  # o enlace tem VLAN: o `None` vem do ASN que falta
    assert prop.circuit_code_sugerido is None


def test_pendencia_da_organizacao_sem_asn_nao_imprime_none(db_session, tmp_path) -> None:
    """Sem ASN lido, a mensagem diz o que falta em vez de pedir a organização
    de um `ASN None`."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, _SEM_ASN)
    (prop,) = listar_propostas(db_session, dev.id).propostas
    pendencia = next(p for p in prop.pendencias if p.tipo == "organizacao_ausente")
    assert "None" not in pendencia.descricao
    assert "as-number" in pendencia.descricao


def test_politica_sem_asn_nao_afirma_que_esta_fora_do_padrao(db_session, tmp_path) -> None:
    """Sem o ASN do par não existe nome padrão com que comparar: dizer que a
    política "não segue o padrão" afirmaria o que a configuração não diz."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, _SEM_ASN)
    (prop,) = listar_propostas(db_session, dev.id).propostas
    pendencia = next(p for p in prop.pendencias if p.tipo == "perfil_indeterminado")
    assert "as-number" in pendencia.descricao
    assert "não segue o padrão" not in pendencia.descricao


def test_a_sessao_usa_as_chaves_do_modelo(db_session, tmp_path) -> None:
    """A conferência de fidelidade espalha este dicionário no modelo
    (`models.BgpSession(**dados)`): o campo do modelo é `description`, e
    `descricao` levantaria `TypeError` no flush."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    sessao = next(s for s in alfa.sessoes if s["afi"] == "ipv4")
    assert sessao["description"] == "CLIENTE-ALFA"
    assert set(sessao) <= {c.name for c in models.BgpSession.__table__.columns}


def test_pendencia_de_politica_nomeia_a_que_segue_o_padrao(db_session, tmp_path) -> None:
    """No enlace do CLIENTE-ALFA a importação é `RP-64512-IMPORT-V4` (o padrão
    de nome deste sistema) e a exportação é `IP-PFX-64512-EXPORT-V4` (fora
    dele): a mensagem cita a que segue o padrão, em vez de afirmar que as duas
    seguem."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    pendencia = next(p for p in alfa.pendencias if p.tipo == "perfil_indeterminado")
    assert "RP-64512-IMPORT-V4" in pendencia.descricao
    assert "IP-PFX-64512-EXPORT-V4" not in pendencia.descricao


def test_o_enlace_dual_nao_repete_a_pendencia(db_session, tmp_path) -> None:
    """Os dois candidatos do enlace dual têm descrições próprias no equipamento
    (`CLIENTE-ALFA` e `CLIENTE-ALFA-V6`): a pendência da organização é uma só,
    e cita a descrição do enlace — a mesma que vira `organizacao_sugerida`."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    pendencias = [p for p in alfa.pendencias if p.tipo == "organizacao_ausente"]
    assert len(pendencias) == 1
    assert "(descrição no equipamento: CLIENTE-ALFA)" in pendencias[0].descricao
    assert alfa.organizacao_sugerida == "CLIENTE-ALFA"


def test_duas_subinterfaces_com_o_mesmo_vid_sao_dois_enlaces(db_session, tmp_path) -> None:
    """Duas subinterfaces do mesmo equipamento com o mesmo VID são dois
    enlaces: agrupadas pelo VID viram **uma** proposta com dois pares e duas
    sessões, que não existe em equipamento nenhum."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.1001\n"
               " vlan-type dot1q 1001\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               "#\n"
               "interface GE0/0/1.1001\n"
               " vlan-type dot1q 1001\n"
               " ip address 100.64.11.0 255.255.255.254\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " peer 100.64.11.1 as-number 64513\n")
    propostas = listar_propostas(db_session, dev.id).propostas
    assert [p.subinterface for p in propostas] == ["Eth-Trunk127.1001", "GE0/0/1.1001"]
    assert [len(p.candidatos) for p in propostas] == [1, 1]
    assert [len(p.sessoes) for p in propostas] == [1, 1]


def test_enlace_qinq_propoe_s_vlan(db_session, tmp_path) -> None:
    """`vlan-type dot1q 0x88a8 vid 2701` é empilhado: a reserva nasce como
    S-VLAN (o IPAM criaria `kind='s_vlan'`) e o render só emite a linha
    empilhada com `Circuit.qinq` ligado. `vlan_mode` segue "unica": a mesma
    VLAN carrega as duas famílias — isso é outro eixo."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2701\n"
               " vlan-type dot1q 0x88a8 vid 2701\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert prop.qinq is True
    assert prop.vlans == [{"vid": 2701, "kind": "s_vlan", "family": None}]
    assert prop.vlan_mode == "unica"


def test_sessao_de_outro_equipamento_nao_e_o_mesmo_par(db_session, tmp_path) -> None:
    """O par p2p é único por domínio/site: dois POPs podem ter o mesmo `/31`
    privado, e a sessão do outro POP não fala deste enlace."""
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    outro_site = create_site(db_session, SiteCreate(name="pop-desc-2"), actor="cli")
    outro_dev = create_device(db_session, DeviceCreate(name="ne8000-desc-2",
                                                       management_address="10.0.0.2",
                                                       asn=65001), actor="cli")
    link_device(db_session, outro_site.id, outro_dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="Outro Cliente",
                                                             asn=64999), actor="cli")
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-OUTRO-POP", organization_id=org.id, site_id=outro_site.id,
        access_device_id=outro_dev.id, access_port="GE0/0/1", edge_device_id=outro_dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=outro_dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "par_em_uso" not in {c.tipo for c in alfa.conflitos}


def test_sessao_do_mesmo_equipamento_acha_o_par_em_outra_caixa(db_session, tmp_path) -> None:
    """A sessão da SoT guarda o endereço como foi digitado e o par vem da
    configuração: a conferência é pela forma canônica dos dois lados. Em SQL o
    par escrito em outra caixa não casaria, o aviso se perderia e o operador
    adotaria um enlace que a SoT já tem.

    A sessão vive em outra VRF de propósito: na instância pública ela tornaria o
    par `conhecido` e o candidato sairia da lista, e aí não haveria proposta para
    conferir. A conferência de `par_em_uso` olha o equipamento, não a VRF.
    """
    dev = _ambiente(db_session)
    circ = _circuito_tomado(db_session, dev, code="CIRC-DESC-V6-CAIXA", vrf="VPNA")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv6",
        local_address="2804:194C:1000::1100:73:1",
        remote_address="2804:194C:1000::1100:73:2",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    conflito = next(c for c in alfa.conflitos if c.tipo == "par_em_uso")
    assert "2804:194c:1000::1100:73:2" in conflito.descricao


def test_sessao_do_mesmo_equipamento_e_conflito(db_session, tmp_path) -> None:
    """A sessão do par já existe **neste** equipamento, em outra VRF: o
    conflito aparece, e a mensagem diz de que equipamento é a sessão — sem
    dizer o estado dela, que a conferência não leu."""
    dev = _ambiente(db_session)
    circ = _circuito_tomado(db_session, dev, code="CIRC-DESC-VRF-PAR", vrf="VPNA")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    conflito = next(c for c in alfa.conflitos if c.tipo == "par_em_uso")
    assert dev.name in conflito.descricao
    assert "ativa" not in conflito.descricao


from gerenet.automation.discovery import Proposta, conferir_fidelidade


def test_fidelidade_aponta_a_politica_que_o_render_nao_reproduz(db_session, tmp_path) -> None:
    """O peer tem route-policy no equipamento e o perfil ficou pendente: o render
    não emite essa linha, e a conferência diz exatamente isso."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    diferencas = conferir_fidelidade(db_session, alfa)
    peer = next(d for d in diferencas if d.contexto == "peer")
    assert peer.sobrando == ()
    assert any("route-policy RP-64512-IMPORT-V4" in linha for linha in peer.faltando)


def test_fidelidade_ignora_comentario_dentro_da_interface(db_session, tmp_path) -> None:
    """Comentário com texto na coluna 0 dentro do bloco da interface (a forma que
    o próprio render emite, `# second-dot1q ...`) some da comparação nos dois
    lados. Sem a regra, ele zerava o `dentro` e as linhas de endereço escritas
    depois dele ficavam de fora — o render as produzia e a conferência acusava
    sobra nelas."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2601\n"
               " vlan-type dot1q 2601\n"
               "# second-dot1q: encapsulamento interno duplo\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " ipv4-family unicast\n"
               "  peer 100.64.10.1 enable\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    sub = next(d for d in conferir_fidelidade(db_session, prop) if d.contexto == "subinterface")
    assert sub.sobrando == ()
    assert sub.faltando == ()


def test_fidelidade_do_peer_que_casa_com_o_render(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.2601\n"
        " vlan-type dot1q 2601\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    (prop,) = listar_propostas(db_session, dev.id).propostas
    peer = next(d for d in conferir_fidelidade(db_session, prop) if d.contexto == "peer")
    assert peer.sobrando == ()
    assert peer.faltando == ()


def test_fidelidade_mascara_a_linha_da_senha(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    diferencas = conferir_fidelidade(db_session, alfa)
    linhas = [linha for d in diferencas for linha in d.faltando + d.sobrando]
    senha = [linha for linha in linhas if "password" in linha]
    assert senha, "a linha da senha deveria aparecer como diferença"
    assert all("cipher" not in linha for linha in senha)
    # O que o §19 exige é que o valor não apareça: `%^%#` é o delimitador com
    # que o VRP escreve o hash, e uma máscara que o deixasse passaria na
    # asserção de cima.
    assert all("%^%#" not in linha for linha in senha)


def test_fidelidade_nao_grava_nada(db_session, tmp_path) -> None:
    """O ensaio cria objetos transitórios e desfaz: o banco fica como estava."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    antes = (
        db_session.query(models.Circuit).count(),
        db_session.query(models.BgpSession).count(),
        db_session.query(models.Vlan).count(),
        db_session.query(models.IpPrefix).count(),
    )
    conferir_fidelidade(db_session, alfa)
    depois = (
        db_session.query(models.Circuit).count(),
        db_session.query(models.BgpSession).count(),
        db_session.query(models.Vlan).count(),
        db_session.query(models.IpPrefix).count(),
    )
    assert antes == depois


def test_fidelidade_de_proposta_com_conflito_explica_em_vez_de_estourar(
    db_session, tmp_path,
) -> None:
    """A conferência não pode explodir: quando o ensaio não consegue reservar o
    que a proposta pede, o operador recebe a diferença que diz isso — nem lista
    vazia (que se lê como "está tudo fiel") nem exceção."""
    dev = _ambiente(db_session)
    outro = _circuito_tomado(db_session, dev, code="CIRC-DESC-TOMADO-FID")
    site = db_session.scalar(select(models.Site))
    db_session.add(models.Vlan(site_id=site.id, vid=1001, kind="vlan", circuit_id=outro.id))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "vlan_tomada" in {c.tipo for c in alfa.conflitos}

    diferencas = conferir_fidelidade(db_session, alfa)

    assert [d.contexto for d in diferencas] == ["ensaio"]
    assert diferencas[0].sobrando == ()
    assert diferencas[0].faltando == ()
    # A mensagem diz o que a função sabe (uma restrição de unicidade recusou o
    # ensaio), e não uma causa que ela não pode conhecer: qualquer colisão de
    # unicidade do ensaio cai na mesma captura, e o `prefixo_tomado` na mesma
    # grafia é só a mais provável.
    assert diferencas[0].explicacao is not None
    assert "restrição de unicidade" in diferencas[0].explicacao
    # O ensaio que morreu no meio (organização e circuito já tinham ido para a
    # transação) também é desfeito: sobra só o circuito tomado, com a VLAN dele.
    assert db_session.query(models.Circuit).count() == 1
    assert db_session.query(models.Vlan).count() == 1


def test_peer_em_vrf_e_conflito_de_render(db_session, tmp_path) -> None:
    """Esta versão do render emite toda sessão na instância pública (§25.3):
    uma sessão em VRF não é reproduzível, e adotá-la faria a renderização
    seguinte mudar a instância do peer no equipamento."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    propostas = listar_propostas(db_session, dev.id).propostas
    na_vrf = next(p for p in propostas if p.vrf == "VPNA")
    assert "vrf_nao_renderizavel" in {c.tipo for c in na_vrf.conflitos}
    assert na_vrf.veredito == "nao_adotavel"


def test_fidelidade_de_peer_em_vrf_avisa_que_a_comparacao_nao_vale(
    db_session, tmp_path,
) -> None:
    """Defesa em profundidade: a conferência é chamada para qualquer peer,
    inclusive o não adotável, e uma comparação em que o render mudaria a
    instância do peer não pode sair como fiel."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    propostas = listar_propostas(db_session, dev.id).propostas
    na_vrf = next(p for p in propostas if p.vrf == "VPNA")

    diferencas = conferir_fidelidade(db_session, na_vrf)

    assert [d.contexto for d in diferencas] == ["ensaio"]
    assert diferencas[0].sobrando == ()
    # A explicação sai do `faltando`: linha lá dentro faria a diferença de
    # `ensaio` exigir ciente de uma comparação que não aconteceu.
    assert diferencas[0].faltando == ()
    assert diferencas[0].explicacao is not None
    assert "VPNA" in diferencas[0].explicacao
    assert "instância pública" in diferencas[0].explicacao


def test_fidelidade_nao_acusa_as_duas_formas_da_mesma_linha(db_session, tmp_path) -> None:
    """`vlan-type dot1q 2601` e `vlan-type dot1q vid 2601` são a mesma linha, e
    o mesmo vale para `ipv6 address <endereço> 126` e `<endereço>/126`: o
    equipamento escreve a primeira forma, o render a segunda. Sem a
    equivalência, toda proposta com VLAN e IPv6 nasceria com dois falsos
    `sobrando` e dois falsos `faltando`, e o contexto da subinterface — onde a
    mudança de estado da interface tem de aparecer — ficaria sempre sujo."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2601\n"
               " vlan-type dot1q 2601\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               " ipv6 enable\n"
               " ipv6 address 2804:194C:1000::1100:73:1 126\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " peer 2804:194C:1000::1100:73:2 as-number 64512\n"
               " ipv4-family unicast\n"
               "  peer 100.64.10.1 enable\n"
               " ipv6-family unicast\n"
               "  peer 2804:194C:1000::1100:73:2 enable\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    sub = next(d for d in conferir_fidelidade(db_session, prop) if d.contexto == "subinterface")
    assert sub.sobrando == ()
    assert sub.faltando == ()


def test_fidelidade_de_prefixo_tomado_com_caixa_divergente_compara_normalmente(
    db_session, tmp_path,
) -> None:
    """O `prefixo_tomado` que só difere na caixa não derruba o ensaio: o índice
    único do banco é sensível à caixa e o `flush` passa. A conferência compara
    normalmente — quem impede a adoção é o conflito da proposta, não a
    conferência."""
    dev = _ambiente(db_session)
    outro = _circuito_tomado(db_session, dev, code="CIRC-V6-FID")
    site = db_session.scalar(select(models.Site))
    db_session.add(models.IpPrefix(site_id=site.id, network="2804:194c:1000::1100:73:0/126",
                                   kind="p2p", circuit_id=outro.id))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "prefixo_tomado" in {c.tipo for c in alfa.conflitos}

    diferencas = conferir_fidelidade(db_session, alfa)

    assert "ensaio" not in {d.contexto for d in diferencas}
    peer = next(d for d in diferencas if d.contexto == "peer")
    assert any("route-policy RP-64512-IMPORT-V4" in linha for linha in peer.faltando)


def test_fidelidade_preserva_o_trabalho_pendente_do_chamador(db_session, tmp_path) -> None:
    """O ensaio roda num SAVEPOINT: o que o chamador tem pendente na sessão
    sobrevive à conferência. A §10 chama isto dentro da transação de adoção, e
    um `rollback` da sessão inteira ali viraria adoção parcial silenciosa."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    pendente = models.Organization(name="Pendente do Chamador", asn=64998)
    db_session.add(pendente)

    conferir_fidelidade(db_session, alfa)

    # Sem `flush` do chamador de propósito: é o savepoint que devolve a ele o
    # que era dele, e o `commit` seguinte é quem escreve.
    db_session.commit()
    assert db_session.query(models.Organization).filter_by(
        name="Pendente do Chamador"
    ).count() == 1
    # e o ensaio não foi junto no commit
    assert db_session.query(models.Circuit).count() == 0
    assert db_session.query(models.Vlan).count() == 0


def test_peer_sem_as_number_e_conflito(db_session, tmp_path) -> None:
    """A leitura pegou o peer sem a definição de `as-number`: `bgp_sessions`
    exige o ASN remoto, então não há sessão a criar e a adoção não nasce."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path, _SEM_ASN)
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert "asn_remoto_ausente" in {c.tipo for c in prop.conflitos}
    assert prop.veredito == "nao_adotavel"


def test_endereco_fora_das_pontas_do_par_e_conflito(db_session, tmp_path) -> None:
    """O `/30` com o roteador no `.3` e o par no `.2`: o `.3` está dentro do
    prefixo, mas não é nenhuma das duas pontas que o IPAM representa (`.1` e
    `.2`). O `.2` do par é a outra ponta, então a proposta saía com
    `ponta_local: superior` e uma sessão de endereço local igual ao do par."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2903\n"
               " vlan-type dot1q 2903\n"
               " ip address 100.64.10.3 255.255.255.252\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.2 as-number 64512\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    conflito = next(c for c in prop.conflitos if c.tipo == "ponta_incoerente")
    assert "100.64.10.3" in conflito.descricao
    assert "100.64.10.1" in conflito.descricao  # a inferior, que o roteador não usa
    assert "100.64.10.2" in conflito.descricao  # a do par
    assert prop.prefixos == []
    assert prop.sessoes == []
    assert prop.veredito == "nao_adotavel"


def test_endereco_v6_fora_das_pontas_do_par_e_conflito(db_session, tmp_path) -> None:
    """O irmão v6: `...:3` está no /126 `...::0/126`, cujas pontas são `:1` e `:2`."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2904\n"
               " vlan-type dot1q 2904\n"
               " ipv6 address 2804:194C:1000::1100:73:3 126\n"
               "#\n"
               "bgp 65001\n"
               " peer 2804:194C:1000::1100:73:2 as-number 64512\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    conflito = next(c for c in prop.conflitos if c.tipo == "ponta_incoerente")
    assert "2804:194C:1000::1100:73:3" in conflito.descricao
    assert "2804:194c:1000::1100:73:1" in conflito.descricao  # a inferior, em minúsculas
    assert prop.prefixos == []
    assert prop.sessoes == []
    assert prop.veredito == "nao_adotavel"


def test_peer_sem_enable_em_nenhuma_familia_vira_pendencia(db_session, tmp_path) -> None:
    """O peer declarado e não habilitado é resto de configuração: o render emite
    `peer <endereço> enable` em toda sessão, então adotá-lo mandaria o
    equipamento habilitar o que ninguém pediu. Pendência, e não conflito — o
    operador pode estar a um passo de ativá-lo. O vizinho habilitado num
    `ipv4-family unicast` não recebe nada."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2901\n"
               " vlan-type dot1q 2901\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               "#\n"
               "interface Eth-Trunk127.2902\n"
               " vlan-type dot1q 2902\n"
               " ip address 100.64.20.0 255.255.255.254\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " peer 100.64.10.1 description CLIENTE-LEGADO\n"
               " peer 100.64.20.1 as-number 64513\n"
               " ipv4-family unicast\n"
               "  peer 100.64.20.1 enable\n")
    por_vid = _propostas(db_session, dev)
    pendencia = next(p for p in por_vid[2901].pendencias if p.tipo == "peer_nao_habilitado")
    assert "não o habilita em nenhuma família" in pendencia.descricao
    assert por_vid[2901].veredito == "adotavel_com_pendencias"
    assert "peer_nao_habilitado" not in {p.tipo for p in por_vid[2902].pendencias}


def test_veredito_adotavel_do_upstream_com_organizacao(db_session, tmp_path) -> None:
    """O GAMA da fixture: operadora cadastrada para o ASN, peer sem senha e sem
    política, habilitado no `ipv4-family unicast`. Sem pendência e sem conflito
    é o único caminho para `adotavel`, que os outros testes não pinam."""
    dev = _ambiente(db_session)
    create_organization(db_session, OrganizationCreate(name="Operadora Gama", asn=64515,
                                                       kind="operadora"), actor="cli")
    _com_config(db_session, dev, tmp_path)
    gama = _propostas(db_session, dev)[3001]
    assert gama.candidatos[0].classificacao == "upstream"
    assert gama.pendencias == []
    assert gama.conflitos == []
    assert gama.veredito == "adotavel"


def test_o_resultado_traz_os_internos_e_a_idade_da_coleta(db_session, tmp_path) -> None:
    """O `list` do CLI parava de parsear a config duas vezes só por causa disto."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_propostas(db_session, dev.id)
    assert [c.remote_address for c in resultado.internos] == ["10.0.0.9"]
    assert resultado.snapshot_age_seconds is not None
    assert resultado.snapshot_age_seconds >= 0


def test_diferenca_separa_o_que_a_sot_nao_gerencia(db_session, tmp_path) -> None:
    """Descrição e MTU da subinterface saem do que exige ciente (design §6)."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    diferencas = conferir_fidelidade(db_session, alfa)
    sub = next(d for d in diferencas if d.contexto == "subinterface")
    assert any("description" in linha for linha in sub.nao_gerenciado)
    assert not any("description" in linha for linha in sub.faltando + sub.sobrando)


def test_exige_ciente_so_quando_o_render_mudaria_o_equipamento(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    sub = next(d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "subinterface")
    assert sub.exige_ciente is False  # só descrição sobra, que não é gerenciada


def test_o_ensaio_nao_usa_faltando_para_explicar(db_session, tmp_path) -> None:
    """A explicação do ensaio vai no campo dela: `sobrando` e `faltando` vazios
    num contexto `ensaio` leriam como fidelidade."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    vpn = next(p for p in listar_propostas(db_session, dev.id).propostas if p.vrf == "VPNA")
    (diferenca,) = conferir_fidelidade(db_session, vpn)
    assert diferenca.contexto == "ensaio"
    assert diferenca.explicacao is not None
    assert diferenca.sobrando == ()
    assert diferenca.faltando == ()


def test_conferencia_de_proposta_sem_site_explica(db_session, tmp_path) -> None:
    """Sem site o circuito do ensaio nem nasce (a coluna é NOT NULL) e não há
    render a comparar. A conferência diz isso — sem o `explicacao`, o `return []`
    que a parte 1 devolvia leria como "está tudo fiel"."""
    dev = create_device(db_session, DeviceCreate(name="ne8000-sem-site-fid",
                                                 management_address="10.0.0.9", asn=65001),
                        actor="cli")
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]

    (diferenca,) = conferir_fidelidade(db_session, alfa)

    assert diferenca.contexto == "ensaio"
    assert diferenca.sobrando == ()
    assert diferenca.faltando == ()
    assert diferenca.explicacao is not None
    assert "site" in diferenca.explicacao


def test_conferencia_de_proposta_sem_candidato_explica(db_session) -> None:
    """Proposta sem candidato não tem endereço de peer nem coleta a ler. Hoje
    `listar_propostas` sempre põe um candidato em cada proposta, então o caminho
    só é alcançável por quem monta a `Proposta` à mão — e é o que a adoção (que
    confere antes de checar o candidato) faria."""
    proposta = Proposta(device_id=1, vrf=None, subinterface=None, vid=None,
                        stack="ipv4", vlan_mode="unica", p2p_v4_len=None)

    (diferenca,) = conferir_fidelidade(db_session, proposta)

    assert diferenca.contexto == "ensaio"
    assert diferenca.sobrando == ()
    assert diferenca.faltando == ()
    assert diferenca.explicacao is not None
    assert "candidato" in diferenca.explicacao


def test_mtu_da_subinterface_tambem_sai_do_que_gateia(db_session, tmp_path) -> None:
    """A fixture tem `description` e não tem `mtu`: sem este caso, o braço do
    `"mtu "` da tupla não é exercitado por teste nenhum e uma entrada apagada
    passaria na suíte inteira. Numa borda real o `mtu` está em toda subinterface,
    e no `faltando` ele faria toda proposta voltar a exigir ciente."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2601\n"
               " vlan-type dot1q 2601\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               " mtu 9000\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " ipv4-family unicast\n"
               "  peer 100.64.10.1 enable\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas

    sub = next(d for d in conferir_fidelidade(db_session, prop) if d.contexto == "subinterface")

    assert sub.nao_gerenciado == ("mtu 9000",)
    assert sub.faltando == ()
    assert sub.sobrando == ()
    assert sub.exige_ciente is False


def test_o_trunk_revisado_divergente_aparece_no_nome_da_interface(db_session, tmp_path) -> None:
    """O trunk da revisão é o que o render usa para NOMEAR a subinterface.

    A comparação olhava só o conteúdo do bloco — o cabeçalho `interface <nome>`
    saía dos dois lados como abre-contexto —, então um trunk digitado errado
    comparava igual e a conferência saía fiel: a adoção gravava um `edge_trunk`
    que o equipamento não tem, o render passava a intencionar uma subinterface
    num trunk inexistente, e a conferência que existe para pegar isso dizia que
    estava tudo certo. O nome entra na conta: o que o render emitiria contra o
    nome real do bloco da configuração.
    """
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]

    sub = next(
        d for d in conferir_fidelidade(db_session, alfa, edge_trunk="Eth-Trunk9")
        if d.contexto == "subinterface"
    )

    assert "interface Eth-Trunk9.1001" in sub.sobrando
    assert "interface Eth-Trunk127.1001" in sub.faltando
    assert sub.exige_ciente is True


def _com_prefixos_autorizados(db_session):
    """Cliente ALFA com os prefixos das duas famílias autorizados.

    É do que o render precisa para emitir as definições da sessão: sem
    autorização ativa não há prefix-list nem route-policy de importação a
    emitir, e sem elas o ensaio não tem corpo de definição a comparar. O
    ensaio não carrega perfil de exportação (a `Proposta` não tem esse campo),
    então a importação é o único caminho pelo qual ele gera definição.
    """
    from gerenet.domain.schemas import PrefixAuthorizationCreate
    from gerenet.domain.services.prefix_authorizations import create_authorization

    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    create_authorization(db_session, PrefixAuthorizationCreate(
        organization_id=org.id, family="ipv4", prefix="200.219.0.0/24"), actor="cli")
    create_authorization(db_session, PrefixAuthorizationCreate(
        organization_id=org.id, family="ipv6", prefix="2001:DB8::/32"), actor="cli")
    return org


def test_a_conferencia_compara_o_corpo_das_definicoes(db_session, tmp_path) -> None:
    """Escolher o produto errado rende linhas de peer idênticas com política
    diferente, e é isso que a comparação do corpo pega (design §6)."""
    dev = _ambiente(db_session)
    _com_prefixos_autorizados(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    contextos = {d.contexto for d in conferir_fidelidade(db_session, alfa)}
    assert "definicao" in contextos


def test_definicao_ausente_no_equipamento_aparece_como_sobrando(db_session, tmp_path) -> None:
    """O render define `IP-PFX-64512-IN-V4` e a configuração não tem esse bloco:
    ele aparece inteiro como sobra."""
    dev = _ambiente(db_session)
    _com_prefixos_autorizados(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    definicoes = [d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "definicao"]
    assert any(d.sobrando for d in definicoes)
    assert any(
        "IP-PFX-64512-IN-V4" in linha for d in definicoes for linha in d.sobrando
    )


def test_definicao_que_o_equipamento_ja_tem_nao_vira_diferenca(db_session, tmp_path) -> None:
    """O outro lado da comparação: com o corpo no equipamento, a definição sai
    vazia — e o comentário na coluna 0 dentro do bloco não pode fechar a leitura.

    O render deste projeto emite comentário com texto na coluna 0 dentro do
    bloco (`# up-full: ...`, `# TE: ...`), e a parte 1 corrigiu exatamente isso
    na leitura da interface: com o comentário fechando o bloco, o `if-match` que
    vem depois sai da comparação e o render o acusa como sobra — diferença que
    não existe, exigindo ciente de quem não mudaria nada.
    """
    dev = _ambiente(db_session)
    _com_prefixos_autorizados(db_session)
    _com_texto(db_session, dev, tmp_path, _config_com_definicoes())
    alfa = _propostas(db_session, dev)[1001]

    definicoes = [d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "definicao"]

    # Uma prefix-list e uma route-policy de importação por família: quatro
    # blocos de definição. A contagem fixa que a leitura do render não pulou
    # nenhum deles — sem ela, uma chave que deixasse de ser reconhecida sairia
    # como "nenhuma diferença" e o teste passaria vazio.
    assert len(definicoes) == 4
    assert all(d.sobrando == () and d.faltando == () for d in definicoes)


def _config_com_definicoes(corpo_v4: str = "if-match ip-prefix IP-PFX-64512-IN-V4") -> str:
    """A configuração do ALFA com os blocos de definição que o render emite.

    Os blocos saem na forma do VRP: cabeçalho na coluna 0 e corpo indentado. O
    `#` com texto na coluna 0 dentro do bloco é a forma que o render deste
    projeto emite (`# second-dot1q ...`, `# TE: ...`). O `corpo_v4` existe para
    o teste divergir o corpo sem mexer na chave.
    """
    return (
        "interface Eth-Trunk127.1001\n"
        " vlan-type dot1q 1001\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        " ipv6 enable\n"
        " ipv6 address 2804:194C:1000::1100:73:1 126\n"
        "#\n"
        "ip ip-prefix IP-PFX-64512-IN-V4 index 10 permit 200.219.0.0/24\n"
        "#\n"
        "route-policy RP-64512-IMPORT-V4 permit node 10\n"
        "# segundo nó não usado nesta borda\n"
        f" {corpo_v4}\n"
        "#\n"
        "ip ipv6-prefix IP-PFX-64512-IN-V6 index 10 permit 2001:DB8::/32\n"
        "#\n"
        "route-policy RP-64512-IMPORT-V6 permit node 10\n"
        " if-match ipv6 address prefix-list IP-PFX-64512-IN-V6\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " peer 100.64.10.1 description CLIENTE-ALFA\n"
        " peer 2804:194C:1000::1100:73:2 as-number 64512\n"
        " peer 2804:194C:1000::1100:73:2 description CLIENTE-ALFA-V6\n"
    )


def test_o_corpo_divergente_da_definicao_aparece_nos_dois_lados(db_session, tmp_path) -> None:
    """O caso que a tarefa existe para pegar: a chave é a mesma, o corpo do
    equipamento é outro — as linhas do peer saem idênticas byte a byte e a
    política que está lá não é a que o render emitiria. Sem a comparação do
    corpo, a conferência sairia fiel."""
    dev = _ambiente(db_session)
    _com_prefixos_autorizados(db_session)
    _com_texto(db_session, dev, tmp_path,
               _config_com_definicoes("if-match ip-prefix OUTRA-LISTA"))
    alfa = _propostas(db_session, dev)[1001]

    definicoes = [d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "definicao"]

    divergente = next(
        (d for d in definicoes if "if-match ip-prefix OUTRA-LISTA" in d.faltando), None
    )
    assert divergente is not None, "o corpo divergente não apareceu na conferência"
    assert divergente.sobrando == ("if-match ip-prefix IP-PFX-64512-IN-V4",)
    assert divergente.exige_ciente is True
    # O resto casa linha a linha: só o corpo trocado vira diferença, e uma
    # comparação que só olhasse o cabeçalho não acharia esta.
    assert all(d.sobrando == () and d.faltando == () for d in definicoes if d is not divergente)


def test_a_definicao_marcada_com_outra_sessao_pelo_dedup_e_conferida(
    db_session, tmp_path,
) -> None:
    """O dedup do render apensa a definição uma vez só, com o id da PRIMEIRA
    sessão que a produziu (`_apensa_definicao`). Num PE com dois enlaces do
    mesmo cliente, o bloco do segundo vem marcado com o id do primeiro, que já
    foi adotado: conferir pelo id deixaria a sessão do ensaio sem nada a
    comparar, e o operador adotaria achando que a SoT reproduz o bloco. Quem a
    sessão referencia, a conferência compara — esteja o bloco marcado com o id
    de quem estiver.
    """
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = _com_prefixos_autorizados(db_session)
    site = db_session.scalar(select(models.Site))
    # O primeiro enlace do cliente, já na SoT: mesmo ASN e, por isso, as mesmas
    # definições — o texto idêntico é o que faz o dedup do render pular o bloco.
    adotado = create_circuit(db_session, CircuitCreate(
        code="CIRC-ADOTADO-64512", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=adotado.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.140.0", remote_address="100.64.140.1",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]

    definicoes = [d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "definicao"]
    sobras = [linha for d in definicoes for linha in d.sobrando]

    assert any("IP-PFX-64512-IN-V4" in linha for linha in sobras)
    assert any("RP-64512-IMPORT-V4" in linha for linha in sobras)


def test_o_perfil_de_exportacao_da_revisao_entra_no_ensaio(db_session, tmp_path) -> None:
    """O produto de exportação é justamente o que o operador escolhe na revisão,
    e a `Proposta` não carrega perfil nenhum: sem o mapa, o `_bloco_export` sai
    cedo e a política que a SoT passaria a emitir fica fora da conferência — o
    caso nomeado no design §6, descoberto."""
    from gerenet.domain.services.policy_profiles import list_policy_profiles

    dev = _ambiente(db_session)
    _com_prefixos_autorizados(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    full_id = next(
        p.id for p in list_policy_profiles(db_session, direction="export") if p.name == "full"
    )

    sem = [d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "definicao"]
    com = [
        d for d in conferir_fidelidade(
            db_session, alfa, perfis={"ipv4": {"export_profile_id": full_id}},
        )
        if d.contexto == "definicao"
    ]

    assert not any("RP-64512-EXPORT-V4" in linha for d in sem for linha in d.sobrando)
    assert any("RP-64512-EXPORT-V4" in linha for d in com for linha in d.sobrando)
    assert len(com) == len(sem) + 1


def test_o_cabecalho_do_bloco_pula_o_comentario_de_abertura() -> None:
    """O import de upstream abre com `# up-full: ...` (e o fail-safe, com
    `# fail-safe: ...`) antes do `route-policy`: tomar a linha 0 como cabeçalho
    faria a chave sair nula e o bloco seria pulado sem diferença nenhuma. Hoje o
    ensaio não cria vínculo de upstream, então o caminho não é alcançável pela
    conferência, e o teste chama o helper direto — como os do runner já fazem.
    """
    from gerenet.automation.discovery import _cabecalho_do_bloco, _chave_definicao

    comandos = [
        "# up-full: accept-all do provedor, exceto as proteções",
        "route-policy RP-64512-IMPORT-V4 permit node 10",
        "if-match ip-prefix IP-PFX-64512-IN-V4",
    ]

    assert _chave_definicao(_cabecalho_do_bloco(comandos)) == "route-policy RP-64512-IMPORT-V4"
    assert _chave_definicao(_cabecalho_do_bloco(["# só comentário"])) is None


def test_as_referencias_incluem_os_filtros_do_corpo_da_politica() -> None:
    """Os filtros que só o caminho de upstream usa (`if-match as-path-filter` e
    `if-match community-filter`) não são alcançáveis pelo ensaio hoje, e a regra
    fica presa aqui em vez de ficar sem teste nenhum: um erro de digitação nela
    passaria despercebido até o dia em que o caminho existir — em silêncio, que
    é o modo de falha que esta conferência combate.
    """
    from gerenet.automation.discovery import _referencias

    assert _referencias([
        "peer 10.0.0.2 import route-policy RP-64501-IMPORT-V4",
        "peer 10.0.0.2 export route-policy RP-64501-EXPORT-V4",
    ]) == {"route-policy RP-64501-IMPORT-V4", "route-policy RP-64501-EXPORT-V4"}
    assert _referencias([
        "if-match as-path-filter AS-PATH-65001-OWN",
        "if-match community-filter CF-64501-BLK-1",
        "if-match ipv6 address prefix-list IP-PFX-64501-IN-V6",
    ]) == {
        "ip as-path-filter AS-PATH-65001-OWN",
        "ip community-filter CF-64501-BLK-1",
        "ip ipv6-prefix IP-PFX-64501-IN-V6",
    }
