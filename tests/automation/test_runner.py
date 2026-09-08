from pathlib import Path

import pytest
from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation.netmiko_conn import ConnectionFailed
from gerenet.automation.runner import run_collection
from gerenet.config import Settings
from gerenet.domain.models import AuditEvent, CredentialGroup, DeviceSnapshot, JobRun
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.devices import create_device

VERSION_SAIDA = """Huawei Versatile Routing Platform Software
VRP (R) software, Version 8.210 (NE8000 V200R021C10SPC600)
Copyright (c) 2012-2019 Huawei Technologies Co., Ltd.
Huawei NE8000 uptime is 5 days, 2 hours, 10 minutes
"""

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _texto_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


# Saídas que o fake de conexão devolve, por comando — como o connect_and_run real,
# que só devolve o que recebeu na lista `commands`.
SAIDAS = {
    "display version": VERSION_SAIDA,
    "display current-configuration": "sysname r1\n#\n",
    "display interface brief": _texto_fixture("ne8000_display_interface_brief.txt"),
    "display ip interface brief": _texto_fixture("ne8000_display_ip_interface_brief.txt"),
    "display ipv6 interface brief": _texto_fixture("ne8000_display_ipv6_interface_brief.txt"),
    "display bgp peer": _texto_fixture("ne8000_display_bgp_peer.txt"),
    "display bgp ipv6 peer": _texto_fixture("ne8000_display_bgp_ipv6_peer.txt"),
    # MPLS (fase 4 T9): saída vazia nos fakes — parse de vazio tolerado ([]),
    # sem quebrar a coleta fake (KeyError em SAIDAS derruba o recurso).
    "display mpls ldp peer": "",
    "display l2vc": "",
    "display vsi": "",
}


class VaultFake:
    """Substitui o VaultSecretStore no teste — nunca tocar o Vault real aqui."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _dev_com_grupo(db_session: Session, nome: str, endereco: str):
    grupo = CredentialGroup(name="automacao", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao")
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(db_session, DeviceCreate(name=nome, management_address=endereco, credential_group_id=grupo.id), actor="cli")
    dev.host_key_fingerprint = "sha256:fake"
    db_session.commit()
    return dev


def test_coleta_version_atualiza_device_e_snapshot(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r1", "10.0.0.1")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    db_session.refresh(dev)
    assert dev.comm_status == "ok"
    assert dev.vrp_version == "8.210"
    assert dev.uptime == "5 days, 2 hours, 10 minutes"
    assert dev.last_collected_at is not None

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    assert snap is not None
    assert snap.status == "success"
    assert snap.resources["version"]["version"] == "8.210"
    assert snap.resources["config_backup"]["backup"] is True
    assert len(snap.raw_files["version"]) == 1
    assert len(snap.raw_files["config_backup"]) == 1
    assert sorted(p.name for p in tmp_path.glob("r1/*/version/*.txt")) == ["version.txt"]

    job_row = db_session.query(JobRun).filter_by(device_id=dev.id).first()
    assert job_row is not None
    assert job_row.status == "success"
    assert job_row.snapshot_id == snap.id


def test_run_collection_registra_anomalias_prefixos_no_snapshot(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B5 no coletor (§5): toda coleta grava resources["anomalias_prefixos"]
    (sem sessões de upstream conectadas ⇒ lista vazia; a conta é do job)."""
    dev = _dev_com_grupo(db_session, "r-anomalia", "10.0.0.10")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {
            cmd: SAIDAS[cmd] for cmd in commands
        },
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = (
        db_session.query(DeviceSnapshot)
        .filter_by(device_id=dev.id)
        .order_by(DeviceSnapshot.id.desc())
        .first()
    )
    assert snap is not None
    assert snap.resources["anomalias_prefixos"] == []


def test_falha_de_conexao_marca_device_como_fail(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r2", "10.0.0.2")

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)

    def _falha(device, username, password, commands, settings):
        raise ConnectionFailed("host inacessível")

    monkeypatch.setattr("gerenet.automation.runner._conectar_e_executar", _falha)
    resultado = run_collection(
        dev.id, settings=Settings(_env_file=None, backups_dir=Path("/tmp")), session_override=db_session
    )
    assert resultado["status"] == "error"
    db_session.refresh(dev)
    assert dev.comm_status == "fail"
    assert dev.consecutive_failures == 1


def test_sessao_autocriada_e_fechada(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r3", "10.0.0.3")
    settings = Settings(_env_file=None, backups_dir=tmp_path)
    fechadas: list[object] = []

    def _fabrica_sessao():
        from gerenet.db import SessionLocal as _SessionLocalReal

        sessao = _SessionLocalReal()
        _close_real = sessao.close

        def _close_rastreado():
            fechadas.append(sessao)
            _close_real()

        sessao.close = _close_rastreado
        return sessao

    monkeypatch.setattr("gerenet.automation.runner.SessionLocal", _fabrica_sessao)
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings)
    assert resultado["status"] == "success"
    assert len(fechadas) == 1


def test_redis_fora_do_ar_retorna_dict_e_fecha_sessao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis fora do ar antes do try interno: contrato dict mantido, sem exceção propagada,
    e a sessão autocriada é fechada (o fix anterior cobriu os caminhos dentro do try)."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    fechadas: list[object] = []

    def _fabrica_sessao():
        from gerenet.db import SessionLocal as _SessionLocalReal

        sessao = _SessionLocalReal()
        _close_real = sessao.close

        def _close_rastreado():
            fechadas.append(sessao)
            _close_real()

        sessao.close = _close_rastreado
        return sessao

    def _from_url_que_falha(*args, **kwargs):
        raise RedisConnectionError("redis fora do ar")

    monkeypatch.setattr("gerenet.automation.runner.SessionLocal", _fabrica_sessao)
    monkeypatch.setattr("gerenet.automation.runner.Redis.from_url", _from_url_que_falha)

    # A falha acontece antes de qualquer acesso ao banco: device inexistente basta.
    resultado = run_collection(9999, settings=Settings(_env_file=None))
    assert resultado["status"] == "error"
    assert resultado["snapshot_id"] is None
    assert resultado["error"]
    assert len(fechadas) == 1


def test_lock_alheio_nao_e_liberado(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    dev = _dev_com_grupo(db_session, "r4", "10.0.0.4")
    settings = Settings(_env_file=None, backups_dir=Path("/tmp"))
    redis = Redis.from_url(settings.redis_url)
    chave = f"gerenet:lock:device:{dev.id}"
    redis.set(chave, "token-de-outro", nx=True, ex=300)
    try:
        # Lock de outro worker ativo: o runner cai no early-return antes de conectar.
        resultado = run_collection(dev.id, settings=settings)
        assert resultado["status"] == "error"
        assert "lock" in resultado["error"]
        assert redis.get(chave) == b"token-de-outro"
    finally:
        redis.delete(chave)
        redis.close()


def test_lock_proprio_e_liberado(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r5", "10.0.0.5")
    settings = Settings(_env_file=None, backups_dir=tmp_path)
    redis = Redis.from_url(settings.redis_url)
    chave = f"gerenet:lock:device:{dev.id}"

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    try:
        resultado = run_collection(dev.id, settings=settings, session_override=db_session)
        assert resultado["status"] == "success"
        # Compare-and-delete no caminho feliz: o lock próprio foi liberado.
        assert redis.get(chave) is None
    finally:
        redis.delete(chave)
        redis.close()


def test_nome_do_arquivo_desambigua_comandos() -> None:
    from gerenet.automation.runner import _nome_do_arquivo

    assert _nome_do_arquivo("display version") == "version"
    assert _nome_do_arquivo("display current-configuration") == "current-configuration"
    assert _nome_do_arquivo("display interface brief") == "interface-brief"
    assert _nome_do_arquivo("display bgp peer") == "bgp-peer"
    assert _nome_do_arquivo("display bgp ipv6 peer") == "bgp-ipv6-peer"
    assert _nome_do_arquivo("display bgp peer 198.51.100.254 verbose") == "bgp-peer-198.51.100.254-verbose"
    # Comando patológico não pode virar um arquivo chamado "-.txt": fallback preservado.
    assert _nome_do_arquivo("display !!!") == "output"


def test_coleta_multicomando_mergeia_no_snapshot(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gerenet.domain.models import DeviceSnapshot

    dev = _dev_com_grupo(db_session, "r6", "10.0.0.6")
    settings = Settings(_env_file=None, backups_dir=tmp_path)
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    # Runner genérico: substitui o catálogo real por um coletor multicomando só.
    monkeypatch.setattr("gerenet.automation.runner.COLLECTORS", {"bgp_peers": {
        "commands": ["display bgp peer", "display bgp ipv6 peer"],
        "parsers": {"display bgp peer": "bgp_peer", "display bgp ipv6 peer": "bgp_peer"},
        "merge": "bgp_peers",
    }})
    monkeypatch.setitem(SAIDAS, "display bgp peer",
                        Path("tests/fixtures/huawei_vrp/ne8000_display_bgp_peer.txt").read_text(encoding="utf-8"))
    monkeypatch.setitem(SAIDAS, "display bgp ipv6 peer",
                        Path("tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer.txt").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    peers = snap.resources["bgp_peers"]
    assert len(peers) == 22  # 12 v4 + 10 v6
    assert peers[0] == {"afi": "ipv4", "peer": "10.30.70.1", "asn": 64526,
                        "estado": "Idle(Admin)", "pref_rcv": 0, "up_down": "0655h07m"}
    assert peers[-1]["afi"] == "ipv6"
    assert peers[-1]["asn"] == 64528
    assert sorted(Path(p).name for p in snap.raw_files["bgp_peers"]) == [
        "bgp-ipv6-peer.txt", "bgp-peer.txt",
    ]


def test_coleta_completa_registra_snapshot_estruturado(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r7", "10.0.0.7")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    # version/config_backup legados preservados; novos recursos adicionados.
    assert snap.resources["version"]["version"] == "8.210"
    assert snap.resources["config_backup"]["backup"] is True
    # O coletor dirigido pelo SoT (bgp_peers_verbose) chega na T9, junto com o
    # ramo alvo_sessoes do runner; sem sessões ativas o recurso é pulado (§4.1/§12).
    assert "bgp_peers_detalhes" not in snap.resources
    # MPLS: coletores novos presentes como listas vazias (saída vazia tolerada;
    # nunca "erro" nem KeyError). raw_files do catálogo completo em uma coleta.
    assert snap.resources["mpls_ldp_peer"] == []
    assert snap.resources["l2vc"] == []
    assert snap.resources["vsi"] == []
    assert set(snap.raw_files) == {
        "version", "config_backup", "interfaces", "bgp_peers",
        "mpls_ldp_peer", "l2vc", "vsi",
    }

    interfaces = snap.resources["interfaces"]
    assert len(interfaces) == 38  # união canônica das três tabelas das fixtures
    assert interfaces[0]["nome"] == "100GE0/1/53"  # ordenada por nome canônico
    por_nome = {interface["nome"]: interface for interface in interfaces}
    assert por_nome["LoopBack0"] == {
        "nome": "LoopBack0", "phy": "up", "protocolo": "up(s)",
        "enderecos_v4": ["203.0.113.1/32"], "enderecos_v6": ["2001:DB8::1/128"], "vpn": None,
    }
    assert por_nome["GigabitEthernet0/1/0.1003"] == {
        "nome": "GigabitEthernet0/1/0.1003", "phy": "down", "protocolo": "down",
        "enderecos_v4": ["10.254.101.29/30"], "enderecos_v6": ["2001:DB8:1111::51/126"],
        "vpn": None,
    }  # sufixo (10G) do interface brief não duplica a entrada
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["Eth-Trunk127.582"]["enderecos_v4"] == ["172.25.2.69/31"]
    assert por_nome["Eth-Trunk127.582"]["enderecos_v6"] == ["FC00::2B7/127"]
    assert por_nome["Eth-Trunk127.97653"]["enderecos_v4"] == []  # só no interface brief
    assert por_nome["Eth-Trunk127.97653"]["enderecos_v6"] == []

    peers = snap.resources["bgp_peers"]
    assert len(peers) == 22  # 12 v4 + 10 v6
    assert peers[0]["afi"] == "ipv4"
    assert peers[-1] == {"afi": "ipv6", "peer": "FDFF::198:18:255:0", "asn": 64528,
                         "estado": "Active", "pref_rcv": 0, "up_down": "0655h07m"}

    assert sorted(Path(p).name for p in snap.raw_files["interfaces"]) == [
        "interface-brief.txt", "ip-interface-brief.txt", "ipv6-interface-brief.txt",
    ]
    assert sorted(Path(p).name for p in snap.raw_files["bgp_peers"]) == [
        "bgp-ipv6-peer.txt", "bgp-peer.txt",
    ]


def test_coleta_recurso_falho_vira_status_parcial(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falha de parse num recurso não derruba a coleta: status parcial + erro por recurso (§4.3)."""
    dev = _dev_com_grupo(db_session, "r8", "10.0.0.8")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr("gerenet.automation.runner._conectar_e_executar",
                        lambda device, username, password, commands, settings: {
                            cmd: SAIDAS[cmd] for cmd in commands
                        })
    # Comando ausente do fake: o KeyError vira erro só do coletor bgp_peers.
    monkeypatch.delitem(SAIDAS, "display bgp ipv6 peer")

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "partial"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    assert "bgp_peers" in snap.errors
    assert snap.resources["interfaces"]  # os demais recursos sobreviveram
    assert "bgp_peers" not in snap.resources


def test_bgp_peers_verbose_so_sessoes_ativas_do_device(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O comando verbose nasce do SoT: 1 por sessão ativa (afi, endereço remoto),
    excluindo shutdown, em ordem ipv4 -> ipv6 (spec §4.1/§12)."""
    from gerenet.domain.models import BgpSession, Circuit, DeviceSnapshot, Organization, Site

    dev = _dev_com_grupo(db_session, "edge-t9", "10.0.0.99")
    site = Site(name="site-t9")
    org = Organization(name="org-t9", asn=64531)
    db_session.add_all([site, org])
    db_session.commit()
    # Circuito mínimo: só os NOT NULL do modelo; os demais campos têm default.
    circuito = Circuit(
        code="C-T9", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    )
    db_session.add(circuito)
    db_session.commit()

    def sessao(afi: str, remoto: str, shutdown: bool = False) -> BgpSession:
        # Só os NOT NULL de BgpSession (L349-353/356); asn_local fica None e o
        # serviço o resolveria pelo device — aqui o filtro não o consulta.
        return BgpSession(
            circuit_id=circuito.id, device_id=dev.id, afi=afi,
            local_address="203.0.113.1", remote_address=remoto,
            asn_remote=64531, shutdown=shutdown,
        )

    # 2 ativas (v4 e v6 — mesmos peers das fixtures verbose) + 1 em shutdown.
    db_session.add_all([
        sessao("ipv4", "198.51.100.254"),
        sessao("ipv6", "2001:DB8:8000:0:198:51:100:254"),
        sessao("ipv6", "2001:DB8::99", shutdown=True),
    ])
    db_session.commit()
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )
    monkeypatch.setitem(SAIDAS, "display bgp peer 198.51.100.254 verbose",
                        _texto_fixture("ne8000_display_bgp_peer_verbose.txt"))
    monkeypatch.setitem(SAIDAS, "display bgp ipv6 peer 2001:DB8:8000:0:198:51:100:254 verbose",
                        _texto_fixture("ne8000_display_bgp_ipv6_peer_verbose.txt"))

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    # Chave do recurso = nome do coletor no catálogo (regra de todos os recursos);
    # "bgp_peers_detalhes" é o nome do merge da T6 (contracto de shape), não a chave.
    assert snap.resources["bgp_peers_verbose"] == [
        {"afi": "ipv4", "peer": "198.51.100.254", "descricao": "UPSTREAM-FNA",
         "filtro_import": "ASN64531-V4-IMPORT", "filtro_export": "XPL-UPSTREAM-AS64531-V4-EXPORT"},
        {"afi": "ipv6", "peer": "2001:DB8:8000:0:198:51:100:254", "descricao": "UPSTREAM-v6",
         "filtro_import": "ASN64531-V6-IMPORT", "filtro_export": "XPL-UPSTREAM-AS64531-V6-EXPORT"},
    ]  # ordem do SoT: afi ipv4 antes de ipv6
    assert sorted(Path(p).name for p in snap.raw_files["bgp_peers_verbose"]) == [
        "bgp-ipv6-peer-2001-DB8-8000-0-198-51-100-254-verbose.txt",
        "bgp-peer-198.51.100.254-verbose.txt",
    ]


def test_comandos_verbose_respeita_o_cap_de_50(db_session: Session) -> None:
    """O cap do catálogo (§4.1) limita os comandos verbose: 51 sessões ativas com
    (afi, remote_address) distintos geram no máximo 50, sem colapsar no distinct()."""
    from gerenet.automation.collectors import COLLECTORS, comandos_verbose
    from gerenet.domain.models import BgpSession, Circuit, Organization, Site

    dev = _dev_com_grupo(db_session, "edge-cap", "10.0.0.100")
    site = Site(name="site-cap")
    org = Organization(name="org-cap", asn=64531)
    db_session.add_all([site, org])
    db_session.commit()
    # Circuito mínimo: só os NOT NULL do modelo; os demais campos têm default.
    circuito = Circuit(
        code="C-CAP", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    )
    db_session.add(circuito)
    db_session.commit()

    def sessao(afi: str, remoto: str) -> BgpSession:
        # Só os NOT NULL de BgpSession: admin_status/shutdown ficam nos defaults
        # (True/False) e passam no filtro de sessões ativas.
        return BgpSession(
            circuit_id=circuito.id, device_id=dev.id, afi=afi,
            local_address="203.0.113.1", remote_address=remoto,
            asn_remote=64531,
        )

    # 51 sessões ativas com pares (afi, remote_address) distintos — 50 é o teto.
    db_session.add_all([sessao("ipv4", f"10.99.0.{i}") for i in range(1, 52)])
    db_session.commit()

    comandos = comandos_verbose(COLLECTORS["bgp_peers_verbose"], dev.id, db_session)
    assert len(comandos) == 50
    assert len(set(comandos)) == 50  # comando por sessão distinta; o corte é o cap
    assert all(c.startswith("display bgp ") and c.endswith(" verbose") for c in comandos)


def test_falha_sem_grupo_registra_jobrun_error_e_audit(db_session: Session) -> None:
    """Falha pré-execução (grupo ausente) precisa de trilha: JobRun error + auditoria (§18)."""
    dev = create_device(db_session, DeviceCreate(name="sem-grupo-r", management_address="10.0.0.45"), actor="cli")

    resultado = run_collection(
        dev.id, settings=Settings(_env_file=None, backups_dir=Path("/tmp")), session_override=db_session
    )
    assert resultado["status"] == "error"
    assert "grupo de credencial" in resultado["error"]

    job = db_session.query(JobRun).filter_by(device_id=dev.id).one()
    assert job.status == "error"
    assert job.error is not None
    assert "grupo de credencial" in job.error
    assert job.finished_at is not None

    evento = db_session.query(AuditEvent).filter_by(type="collect.failed").one()
    assert evento.details["device_id"] == dev.id
    assert "grupo de credencial" in evento.details["error"]


def test_lock_ativo_registra_audit_skipped(db_session: Session) -> None:
    """Lock de outro job não é falha fatal de execução, mas deixa registro (por quê)."""
    dev = _dev_com_grupo(db_session, "r-lock", "10.0.0.46")
    r = Redis.from_url(Settings(_env_file=None).redis_url)
    chave = f"gerenet:lock:device:{dev.id}"
    try:
        assert r.set(chave, "outro-token", ex=60)
        resultado = run_collection(
            dev.id, settings=Settings(_env_file=None, backups_dir=Path("/tmp")), session_override=db_session
        )
    finally:
        r.delete(chave)

    assert resultado["status"] == "error"
    assert "lock" in resultado["error"]

    evento = db_session.query(AuditEvent).filter_by(type="collect.skipped").one()
    assert evento.details["device_id"] == dev.id
    # Nenhum JobRun novo criado: o dono do lock (outro job) é quem tem a execução.
    assert db_session.query(JobRun).filter_by(device_id=dev.id).count() == 0
