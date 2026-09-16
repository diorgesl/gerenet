"""run_change (spec §6/§5.3): execução de CR aprovada com fake de coleta/aplicação."""
import ipaddress
from pathlib import Path
from types import SimpleNamespace

import pytest
from redis import Redis
from sqlalchemy.orm import Session

from gerenet.automation import changes, render
from gerenet.automation.runner import (
    _enderecos_do_bloco,
    _estado_do_bloco,
    _mascarar_texto,
    _peer_familia,
    _re_diff,
    _verifica_aplicados,
    run_change,
)
from gerenet.config import Settings
from gerenet.domain import models
from gerenet.domain.models import CredentialGroup
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.ipam import reservar_circuito
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


class VaultFake:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_credential(self, vault_path: str) -> dict[str, str]:
        return {"username": "gerenet-auto", "password": "devpass"}


def _ambiente(db_session: Session) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-cr", p2p_ipv4_block="10.0.0.0/24"), actor="cli")
    # Grupo de credencial para o device (como _dev_com_grupo do test_runner):
    # sem ele o step falharia em "não possui grupo de credencial" antes do lock.
    grupo = CredentialGroup(
        name="automacao-cr", kind="tacacs_password", vault_path="gerenet/credential-groups/automacao-cr"
    )
    db_session.add(grupo)
    db_session.commit()
    dev = create_device(
        db_session,
        DeviceCreate(name="ne-cr", management_address="10.0.0.1", asn=65000, credential_group_id=grupo.id),
        actor="cli",
    )
    link_device(db_session, site.id, dev.id, actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="cliente-cr", asn=64512), actor="cli")

    return {"site": site, "dev": dev, "org": org}


def _circuito(db_session: Session, amb: dict):
    from gerenet.domain.schemas import BgpSessionCreate, CircuitCreate

    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="CR-RUN-1", organization_id=amb["org"].id, site_id=amb["site"].id,
            access_device_id=amb["dev"].id, access_port="GE0/0/1",
            edge_device_id=amb["dev"].id, stack="ipv4", vlan_mode="unica",
            edge_trunk="GE1/0/0", p2p_v4_len=31,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=amb["dev"].id, afi="ipv4",
            local_address="100.64.1.1", remote_address="100.64.1.2",
            asn_local=65000, asn_remote=64512,
        ),
        actor="cli",
    )
    db_session.commit()
    return circ


def _cr_aprovada(db_session: Session, circ, dev) -> models.ChangeRequest:
    """CR aprovada direto (setup de teste: o plano real vem do render do circuito)."""
    from gerenet.automation.changes import plan_provision

    plano = plan_provision(db_session, circ)
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao="provision", criticidade="media",
        motivo="Ativação.", status="aprovado",
    )
    db_session.add(cr)
    db_session.flush()
    for item in plano:
        db_session.add(models.ChangeStep(
            change_request_id=cr.id, device_id=item.device_id, status="pendente",
            plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
            aviso=item.aviso,
        ))
    db_session.commit()
    db_session.refresh(cr)
    return cr


def _recursos_vazios(db_session: Session, dev) -> dict:
    """Encontrado sem nada do circuito — re-diff não vê skip, aplica tudo.

    Shape completo (merge.py): recursos ausentes do circuito têm as chaves
    presentes (listas []), como a coleta real produz — o re-diff e o
    reconciliador (§13) distinguem "vazio" de "não coletado".
    """
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [], "bgp_peers": [], "bgp_peers_verbose": [],
        "config_backup": {"backup": True},
    }


def _interfaces_do_render(db_session: Session, dev, *, com_enderecos: bool = True) -> list[dict]:
    """Encontrado realista de subinterfaces: nomes + enderecos no formato do merge
    (merge.py: enderecos_v4/v6 sempre presentes, possivelmente []). É o shape
    que o re-diff e o reconciliar_device (§13) consomem — sem enderecos não há
    como distinguir "sem o endereço esperado" (§5.3) de "só nomes" (fixture
    irreal que gerava ponta.v4 crítica indevida).
    """
    r = render.render_desejado(db_session, dev.id)
    por_nome: dict[str, dict] = {}
    for b in r.blocos:
        if b.tipo != "subinterface":
            continue
        nome = b.comandos[0].split(None, 1)[1]
        end_v4: list[str] = []
        end_v6: list[str] = []
        if com_enderecos:
            for linha in b.comandos[1:]:
                if linha.startswith("ip address "):
                    endereco, mascara = linha.removeprefix("ip address ").split()
                    prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{mascara}").prefixlen
                    end_v4.append(f"{endereco}/{prefixlen}")
                elif linha.startswith("ipv6 address "):
                    end_v6.append(linha.removeprefix("ipv6 address "))
        por_nome[nome] = {
            "nome": nome, "phy": "up", "protocolo": "up",
            "enderecos_v4": end_v4, "enderecos_v6": end_v6, "vpn": None,
        }
    return [por_nome[n] for n in sorted(por_nome)]


def _peers_aplicados(db_session: Session, dev) -> list[dict]:
    """Peers do render: (afi, peer, asn) com estado Established (sem crítica §13)."""
    r = render.render_desejado(db_session, dev.id)
    linhas = []
    for b in r.blocos:
        if b.tipo != "bgp_peer":
            continue
        afi = "ipv6" if any(c.startswith("ipv6-family") for c in b.comandos) else "ipv4"
        peer = b.comandos[1].split()[1]
        achado: str | None = None
        for p in b.comandos:
            tokens = p.split()
            if "as-number" in tokens:
                achado = tokens[tokens.index("as-number") + 1]
        assert achado is not None, b.comandos
        asn = int(achado)
        linhas.append({
            "afi": afi, "peer": peer, "asn": asn, "estado": "Established",
            "pref_rcv": 0, "up_down": "00:12:34",
        })
    return linhas


def _verbose_aplicados(db_session: Session, dev) -> list[dict]:
    """Linhas verbose por sessão (sem filtros: o circuito de teste não tem RP)."""
    r = render.render_desejado(db_session, dev.id)
    linhas = []
    for b in r.blocos:
        if b.tipo != "bgp_peer":
            continue
        afi = "ipv6" if any(c.startswith("ipv6-family") for c in b.comandos) else "ipv4"
        linhas.append({
            "afi": afi, "peer": b.comandos[1].split()[1], "descricao": None,
            "filtro_import": None, "filtro_export": None,
        })
    return linhas


def _recursos_aplicados(db_session: Session, dev) -> dict:
    """Encontrado = desejado (render aplicado) — re-diff sem skip nem crítica."""
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": _interfaces_do_render(db_session, dev),
        "bgp_peers": _peers_aplicados(db_session, dev),
        "bgp_peers_verbose": _verbose_aplicados(db_session, dev),
        "config_backup": {"backup": True},
    }


def _backup_do_render(db_session: Session, dev, tmp_path: Path) -> str:
    """`display current-configuration` do desejado (o render aplicado), em arquivo.

    Devolve o CAMINHO do arquivo — o que o snapshot guarda em `raw_files`. A
    forma é a do equipamento: cabeçalho na coluna 0 e sub-comandos indentados,
    que é o que `linhas_da_interface` lê. Sem este texto a subinterface presente
    por nome e endereços não tem `description` para conferir e o estado é
    `atualizar` (§6) — o par com `_recursos_aplicados` é que dá o "já
    aplicado" completo que estes testes medem.
    """
    r = render.render_desejado(db_session, dev.id)
    arquivo = tmp_path / "cfg-runner.txt"
    corpo = "\n#\n".join(
        "\n".join([b.comandos[0], *(f" {c}" for c in b.comandos[1:])])
        for b in r.blocos
    )
    arquivo.write_text(corpo + "\n", encoding="utf-8")
    return str(arquivo)


def _estado_subif_presenca(db_session: Session, dev) -> dict:
    """Encontrado com a subinterface do plano (nome real do render) presente,
    SEM o endereço esperado (§5.3 literal) e sem mais nada.

    A identidade de subinterface é o nome, mas o endereço faz parte — presente
    com endereço ausente/diferente do plano congelado é divergência, não "já
    presente" (§5.3; revisão T6 F1).
    """
    r = render.render_desejado(db_session, dev.id)
    nome = next(b.comandos[0].split(None, 1)[1] for b in r.blocos if b.tipo == "subinterface")
    return {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": [{
            "nome": nome, "phy": "up", "protocolo": "up",
            "enderecos_v4": [], "enderecos_v6": [], "vpn": None,
        }],
        "bgp_peers": [], "bgp_peers_verbose": [],
        "config_backup": {"backup": True},
    }


def _fakes_de_mudanca(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, dev,
    colas: list[dict], aplicacoes: list[list[str]] | None = None,
    backups: list[str] | None = None,
):
    """Orquestra as fakes: cola retorna uma coleção por chamada (pré → pós).

    `aplicacoes` (opcional) recebe os comandos de cada bloco aplicado
    (para os testes do caminho remove contarem as aplicações).

    `backups` (opcional) é o caminho do arquivo de `display
    current-configuration` de cada coleta, uma por chamada (pré → pós), e a
    última vale para as seguintes — como as `colas`. Sem ele a coleta sai sem
    backup, e a subinterface presente por nome e endereços não tem a
    `description` para conferir: vira `atualizar` (§6), o caso que a maior
    parte destes testes não quer medir.
    """
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    ultimo: list[dict | None] = [None]
    ultimo_backup: list[str | None] = [None]
    pendentes = list(backups) if backups is not None else []

    def _coleta(session, device, cred, settings, base):
        recursos = colas.pop(0) if colas else ultimo[0]
        ultimo[0] = recursos
        if pendentes:
            ultimo_backup[0] = pendentes.pop(0)
        arquivos = {"config_backup": [ultimo_backup[0]]} if ultimo_backup[0] else {}
        return dict(recursos), {}, arquivos

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_aplicar",
        lambda device, username, password, commands, settings: (
            (aplicacoes.append(list(commands)) if aplicacoes is not None else None)
            or {"config": ("\n".join(commands) + "\n")}
        ),
    )


def test_run_change_fluxo_ok_cr_aplicada(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    colas = [_recursos_vazios(db_session, amb["dev"]), _recursos_aplicados(db_session, amb["dev"])]
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"

    db_session.refresh(cr)
    assert cr.status == "aplicado"
    step = cr.steps[0]
    assert step.status == "aplicado"
    assert step.backup_snapshot_id is not None
    assert step.post_check_json and "items" in step.post_check_json
    assert step.erro is None
    jobs = db_session.query(models.JobRun).filter_by(kind="change", device_id=amb["dev"].id).all()
    assert len(jobs) == 1
    assert jobs[0].status == "success"
    eventos = db_session.query(models.AuditEvent).filter_by(type="change.applied").all()
    assert len(eventos) == 1


def test_run_change_erro_vrp_no_meio_marca_cr_erro(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._coleta_recursos",
        lambda session, device, cred, settings, base: (_recursos_vazios(db_session, amb["dev"]), {}, {}),
    )

    def _falha(device, username, password, commands, settings):
        return {"config": f"{commands[0]}\n% Error: Incomplete command found"}

    monkeypatch.setattr("gerenet.automation.runner._conectar_e_aplicar", _falha)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.status == "erro"
    assert cr.steps[0].status == "falhou"
    assert "Error" in (cr.steps[0].erro or "")
    job = db_session.query(models.JobRun).filter_by(kind="change").first()
    assert job.status == "error"
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_failed").count() == 1


def test_run_change_bloco_ja_presente_marca_step_pulado(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tudo já aplicado ⇒ nada a fazer (§3.2). O backup acompanha o encontrado:
    sem ele a `description` do bloco não se confirma e a subinterface viraria
    `atualizar` (§6), que é outro caminho."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [_recursos_aplicados(db_session, amb["dev"])],
                      backups=[_backup_do_render(db_session, amb["dev"], tmp_path)])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"
    db_session.refresh(cr)
    assert cr.steps[0].status == "pulado"
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_skipped").count() == 1


def test_run_change_estado_divergente_aborta(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Subinterface do plano existe SEM o endereço esperado (§5.3 literal) ⇒ aborta."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    # subinterface do plano PRESENTE por nome, mas SEM o endereço esperado e
    # sem o peer — identidade difere do plano congelado ⇒ conflito ⇒ aborta.
    recursos_divergentes = _estado_subif_presenca(db_session, amb["dev"])
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [recursos_divergentes])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    assert "divergente" in (cr.steps[0].erro or "")
    # conexão de aplicação nunca aconteceu
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_failed").count() == 1


def test_run_change_post_check_critica_vira_com_divergencia(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    # PÓS: subinterface sem o endereço esperado e sem o peer — o reconcile
    # (§13, pós-check do provision) acusa ponta.v4/peer.ausente críticas.
    recursos_que_nao_incluem_peer = _estado_subif_presenca(db_session, amb["dev"])
    # PRÉ vazio (aplica tudo); PÓS divergente — pós-check crítico ⇒ com_divergencia.
    colas = [_recursos_vazios(db_session, amb["dev"]), recursos_que_nao_incluem_peer]
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], colas)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "com_divergencia"
    db_session.refresh(cr)
    assert cr.status == "com_divergencia"
    assert cr.steps[0].status == "aplicado"
    assert any(i["severidade"] == "critica" for i in cr.steps[0].post_check_json["items"])
    assert db_session.query(models.AuditEvent).filter_by(type="change.com_divergencia").count() == 1


def test_run_change_lock_por_device_impede_etapa(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    # sem fake de coleta: deve falhar ANTES, no lock.
    redis = Redis.from_url(Settings(_env_file=None, backups_dir=tmp_path).redis_url)
    chave = f"gerenet:lock:device:{amb['dev'].id}"
    redis.set(chave, "outro", nx=True, ex=300)
    try:
        resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
        assert resultado["status"] == "erro"
        db_session.refresh(cr)
        assert cr.status == "erro"
        assert "lock" in (cr.steps[0].erro or "")
    finally:
        redis.delete(chave)
        redis.close()


# ---------------------------------------------------------------------------
# Fix round 1 (revisão T6): F1 (identidade com endereços/bindings) e M2–M5
# ---------------------------------------------------------------------------

def test_mascarar_texto_esconde_segredos() -> None:
    """M2 — nenhuma palavra-chave sensível (com valor) sobrevive na saída."""
    saida = _mascarar_texto(
        "peer 10.0.0.2 password hunter2; | community-filter COM-CLIENTE | "
        "token t0k3n | peer 10.0.0.2 maximum-prefix 100"
    )
    assert "hunter2" not in saida
    assert "COM-CLIENTE" not in saida
    assert "t0k3n" not in saida
    assert saida.count("[mascarado]") == 3
    assert "maximum-prefix 100" in saida  # comando benigno não é mascarado


_SUB_BLOCO = {
    "tipo": "subinterface", "objeto": "circuit", "objeto_id": 1, "acao": "create",
    "comandos": ["interface GE1/0/0.2", "vlan-type dot1q vid 2",
                 "ip address 10.0.0.0 255.255.255.254"],
}


def _encontrado_subif(enderecos_v4: list[str]) -> list[dict]:
    return [{
        "nome": "GE1/0/0.2", "phy": "up", "protocolo": "up",
        "enderecos_v4": enderecos_v4, "enderecos_v6": [], "vpn": None,
    }]


def test_estado_subif_consta_somente_com_endereco_esperado() -> None:
    """F1 — identidade da subinterface é nome + endereços do plano."""
    assert _estado_do_bloco(_SUB_BLOCO, {"interfaces": _encontrado_subif(["10.0.0.0/31"])}, "") == "consta"


def test_estado_subif_sem_endereco_esperado_vira_conflito() -> None:
    """F1 — §5.3 literal: subinterface existe sem o endereço esperado ⇒ conflito (aborta)."""
    assert _estado_do_bloco(_SUB_BLOCO, {"interfaces": _encontrado_subif([])}, "") == "conflito"


def test_estado_subif_endereco_diferente_vira_conflito() -> None:
    """F1 — mesma subinterface com endereço diferente do plano ⇒ conflito (aborta)."""
    assert _estado_do_bloco(_SUB_BLOCO, {"interfaces": _encontrado_subif(["10.0.0.2/31"])}, "") == "conflito"


_BLOCO_PEER_COM_RP = {
    "tipo": "bgp_peer", "objeto": "session", "objeto_id": 1, "acao": "create",
    "comandos": [
        "bgp 65000", "peer 100.64.1.2 as-number 64512", "ipv4-family unicast",
        "  peer 100.64.1.2 enable",
        "  peer 100.64.1.2 import route-policy RP-64512-IMPORT-V4",
    ],
}


def _recursos_com_peer(filtro_import=None, *, com_linha_verbose: bool = True) -> dict:
    return {
        "bgp_peers": [{"afi": "ipv4", "peer": "100.64.1.2", "asn": 64512}],
        "bgp_peers_verbose": [{
            "afi": "ipv4", "peer": "100.64.1.2", "descricao": None,
            "filtro_import": filtro_import, "filtro_export": None,
        }] if com_linha_verbose else [],
    }


def test_estado_peer_consta_com_binding_do_plano() -> None:
    """F1 — mesmo (afi, peer, asn) + binding idêntico ao plano ⇒ consta."""
    assert _estado_do_bloco(
        _BLOCO_PEER_COM_RP, _recursos_com_peer("RP-64512-IMPORT-V4"), ""
    ) == "consta"


@pytest.mark.parametrize(
    "filtro_import, com_linha_verbose",
    [(None, True), ("RP-OUTRA-V4", True), (None, False)],
)
def test_estado_peer_binding_divergente_vira_conflito(filtro_import, com_linha_verbose) -> None:
    """F1 — binding do plano ausente/diferente no encontrado ⇒ conflito (aborta):
    a config mudou desde o plano (o binding não foi aplicado) — nunca "consta"."""
    assert _estado_do_bloco(
        _BLOCO_PEER_COM_RP,
        _recursos_com_peer(filtro_import, com_linha_verbose=com_linha_verbose),
        "",
    ) == "conflito"


def test_estado_peer_maximum_prefix_conferido_no_backup() -> None:
    """F1 — maximum-prefix do plano conferido no texto do backup."""
    bloco = {
        "tipo": "bgp_peer", "objeto": "session", "objeto_id": 1, "acao": "create",
        "comandos": [
            "bgp 65000", "peer 100.64.1.2 as-number 64512", "ipv4-family unicast",
            "  peer 100.64.1.2 enable", "  peer 100.64.1.2 maximum-prefix 100 90",
        ],
    }
    recursos = _recursos_com_peer(None)
    assert _estado_do_bloco(
        bloco, recursos, "peer 100.64.1.2 maximum-prefix 100 90\n"
    ) == "consta"
    assert _estado_do_bloco(bloco, recursos, "") == "conflito"


def test_estado_as_path_filter_consta_por_conteudo() -> None:
    """Item 1 — bloco de as-path-filter: consta só quando o texto tem a linha."""
    bloco = {
        "tipo": "as_path_filter", "objeto": "session", "objeto_id": 1,
        "acao": "create", "comandos": ["ip as-path-filter AS-PATH-65001-OWN permit _65001_"],
    }
    assert _estado_do_bloco(bloco, {}, "") == "ausente"
    assert _estado_do_bloco(
        bloco, {}, "ip as-path-filter AS-PATH-65001-OWN permit _65001_"
    ) == "consta"


def test_run_change_create_misto_consta_ausente_aborta(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F1 — subinterface consta (com endereço certo), peer ausente: só parte do
    plano existe ⇒ aborta (§12.2) sem aplicar (regra do create misto).

    O backup acompanha o encontrado: para a subinterface constar ela precisa da
    `description` confirmada no texto (§6), e é o contraste com o peer ausente
    que faz este teste medir o abort.
    """
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    encontrado = _recursos_aplicados(db_session, amb["dev"])
    encontrado["bgp_peers"] = []
    encontrado["bgp_peers_verbose"] = []
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [encontrado],
                      backups=[_backup_do_render(db_session, amb["dev"], tmp_path)])

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    # As DUAS mensagens de `_re_diff` começam com "Estado divergente" — a outra é
    # a da identidade que não confere (§5.3) —, então o assert antigo
    # (`"divergente" in ...`) casava com qualquer uma delas e uma regressão que
    # trocasse o motivo do abort passava despercebida (item 5). A frase inteira
    # do plano misto, com o `subinterface` que `constam[0]` nomeia: o id fica de
    # fora porque é do plano congelado.
    erro = cr.steps[0].erro or ""
    assert erro.startswith("Estado divergente no objeto subinterface (#")
    assert erro.endswith(
        "apenas parte do plano consta do encontrado (config inalterada? §12.2) — "
        "reexecute com plano atualizado."
    )
    assert db_session.query(models.AuditEvent).filter_by(type="change.step_failed").count() == 1


def test_run_change_coleta_pre_parcial_nao_aplica(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M3 — coleta pré parcial (bgp_peers falhou) não aplica: o re-diff veria
    "objeto ausente" em tudo e quebraria o §12.2/§5.3."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    aplicacoes: list[list[str]] = []
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)

    def _coleta(session, device, cred, settings, base):
        return (
            {
                "version": {"version": "8.210", "uptime": "5 days"},
                "interfaces": _interfaces_do_render(db_session, amb["dev"]),
                "config_backup": {"backup": True},
            },
            {"bgp_peers": "falha ao coletar o peer"},
            {},
        )

    monkeypatch.setattr("gerenet.automation.runner._coleta_recursos", _coleta)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_aplicar",
        lambda device, username, password, commands, settings: (
            aplicacoes.append(list(commands)) or {"config": ""}
        ),
    )

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "erro"
    db_session.refresh(cr)
    assert cr.steps[0].status == "falhou"
    assert "Coleta pré-mudança incompleta" in (cr.steps[0].erro or "")
    assert aplicacoes == []
    job = db_session.query(models.JobRun).filter_by(kind="change", device_id=amb["dev"].id).first()
    assert job.status == "error"


def test_run_change_reexecucao_sem_pendentes_classifica_dos_steps(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M4 — re-execução sobre CR com steps já processados (job interrompido):
    classifica dos steps existentes em vez de "erro sem transitar"."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    cr = _cr_aprovada(db_session, circ, amb["dev"])
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [
        _recursos_vazios(db_session, amb["dev"]),
        _recursos_aplicados(db_session, amb["dev"]),
    ])
    primeiro = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert primeiro["status"] == "aplicado"

    # o job caiu depois de aplicar: CR abre ainda "executando", nada pendente.
    cr.status = "executando"
    db_session.commit()

    segundo = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert segundo["status"] == "aplicado"
    db_session.refresh(cr)
    assert cr.status == "aplicado"
    assert cr.steps[0].status == "aplicado"
    assert db_session.query(models.AuditEvent).filter_by(type="change.applied").count() == 2


def _snapshot_do_estado(db_session: Session, dev, interfaces: list[dict], peers: list[dict]) -> models.DeviceSnapshot:
    """Snapshot success do estado atual do device — a base do plan_remocao (§5.2)."""
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success",
        resources={
            "interfaces": interfaces, "bgp_peers": peers,
            "config_backup": {"backup": True},
        },
        errors={}, raw_files={"config_backup": []},
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _blocos_remocao_do_circuito(db_session: Session, circ, dev) -> list[dict]:
    from gerenet.automation import changes

    return next(
        (item.blocos for item in changes.plan_remocao(db_session, circ) if item.device_id == dev.id),
        [],
    )


def _cr_remocao(db_session: Session, circ, dev, blocos: list[dict]) -> models.ChangeRequest:
    """CR de remoção aprovada com os blocos delete planejados."""
    cr = models.ChangeRequest(
        circuit_id=circ.id, acao="remove", criticidade="media", motivo="Retirada.", status="aprovado",
    )
    db_session.add(cr)
    db_session.flush()
    db_session.add(models.ChangeStep(
        change_request_id=cr.id, device_id=dev.id, status="pendente", plano_json=blocos,
    ))
    db_session.commit()
    db_session.refresh(cr)
    return cr


def test_run_change_remocao_mista_idempotente(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M5 — remove com parte já removida (peer ausente, subinterface presente):
    sem abort (§3.2); aplica só o que existe; pós-check por ausência."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _peers = _peers_aplicados(db_session, amb["dev"])
    _snapshot_do_estado(db_session, amb["dev"], _interfaces_do_render(db_session, amb["dev"]), _peers)
    blocos = _blocos_remocao_do_circuito(db_session, circ, amb["dev"])
    assert any(b["tipo"] == "subinterface" for b in blocos)
    assert any(b["tipo"] == "bgp_peer" for b in blocos)
    cr = _cr_remocao(db_session, circ, amb["dev"], blocos)

    # PRÉ: subinterface ainda presente, peer já removido ⇒ remove mista.
    pre = {
        "version": {"version": "8.210", "uptime": "5 days"},
        "interfaces": _interfaces_do_render(db_session, amb["dev"]),
        "bgp_peers": [], "bgp_peers_verbose": [],
        "config_backup": {"backup": True},
    }
    aplicacoes: list[list[str]] = []
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [
        pre, _recursos_vazios(db_session, amb["dev"]),
    ], aplicacoes)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"
    assert len(aplicacoes) == 1
    assert aplicacoes[0][0] == "undo interface " + _interfaces_do_render(db_session, amb["dev"])[0]["nome"]
    db_session.refresh(cr)
    assert cr.steps[0].status == "aplicado"
    assert cr.steps[0].post_check_json["items"] == []  # pós-check por ausência


def test_run_change_remocao_completa_aplica_os_dois_e_remeve(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M5 — remove com tudo presente aplica os deletes na ordem do plano (peer → sub)."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _snapshot_do_estado(db_session, amb["dev"], _interfaces_do_render(db_session, amb["dev"]), _peers_aplicados(db_session, amb["dev"]))
    blocos = _blocos_remocao_do_circuito(db_session, circ, amb["dev"])
    cr = _cr_remocao(db_session, circ, amb["dev"], blocos)
    aplicacoes: list[list[str]] = []
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [
        _recursos_aplicados(db_session, amb["dev"]),
        _recursos_vazios(db_session, amb["dev"]),
    ], aplicacoes)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"
    assert aplicacoes[0][0].startswith("bgp ")
    assert aplicacoes[1][0].startswith("undo interface")
    db_session.refresh(cr)
    assert cr.steps[0].status == "aplicado"
    assert cr.steps[0].post_check_json["items"] == []


def test_run_change_remocao_ja_ausente_vira_pulado(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M5 — remove com tudo já ausente pulou tudo (idempotência) sem aplicar nada."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _snapshot_do_estado(db_session, amb["dev"], _interfaces_do_render(db_session, amb["dev"]), _peers_aplicados(db_session, amb["dev"]))
    blocos = _blocos_remocao_do_circuito(db_session, circ, amb["dev"])
    cr = _cr_remocao(db_session, circ, amb["dev"], blocos)
    aplicacoes: list[list[str]] = []
    _fakes_de_mudanca(monkeypatch, db_session, amb["dev"], [
        _recursos_vazios(db_session, amb["dev"]),
    ], aplicacoes)

    resultado = run_change(cr.id, settings=Settings(_env_file=None, backups_dir=tmp_path), session_override=db_session)
    assert resultado["status"] == "aplicado"
    assert aplicacoes == []
    db_session.refresh(cr)
    assert cr.steps[0].status == "pulado"


# ---------------------------------------------------------------------------
# O estado `atualizar` (design §6): nome e endereços no lugar, conteúdo não
# ---------------------------------------------------------------------------

_SUB_COM_DESCRICAO = {
    "tipo": "subinterface", "objeto": "circuit", "objeto_id": 1, "acao": "create",
    "comandos": ["interface GE1/0/0.2", "description CIRC-2 ACME [1G]",
                 "vlan-type dot1q vid 2", "ip address 10.0.0.0 255.255.255.254",
                 "statistic enable", "qos car cir 1024000 inbound",
                 "qos car cir 1024000 outbound"],
}

# O que o VRP grava depois de aplicar a forma curta (§2).
_BACKUP_CONFORME = (
    "#\n"
    "interface GE1/0/0.2\n"
    " description CIRC-2 ACME [1G]\n"
    " vlan-type dot1q 2\n"
    " ip address 10.0.0.0 255.255.255.254\n"
    " statistic enable\n"
    " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
    " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
    "#\n"
)


def _recursos_com_subif(*enderecos_v4: str) -> dict:
    """Recursos no formato da coleta, com a subinterface do bloco presente.

    O nome sai do próprio bloco (`interface GE1/0/0.2` → `GE1/0/0.2`), como
    `_estado_subif_presenca` faz — os dois helpers ficam lado a lado no mesmo
    formato de dicionário.
    """
    nome = _SUB_COM_DESCRICAO["comandos"][0].split(None, 1)[1]
    return {
        "interfaces": [{
            "nome": nome, "phy": "up", "protocolo": "up",
            "enderecos_v4": list(enderecos_v4), "enderecos_v6": [], "vpn": None,
        }],
    }


# Endereço do bloco no formato do merge (`addr/prefixlen`, o que
# `_enderecos_do_bloco` devolve e compara) — e não a forma crua da CLI
# (`ip address 10.0.0.0 255.255.255.254`), que é a do texto do backup.
_ENDERECO_DO_BLOCO = "10.0.0.0/31"


def test_estado_subinterface_com_descricao_e_qos_consta() -> None:
    estado = _estado_do_bloco(
        _SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), _BACKUP_CONFORME
    )
    assert estado == "consta"


def test_estado_subinterface_sem_a_descricao_e_atualizar() -> None:
    """Nome e endereços batem e falta a descrição: é o caso do parque que já
    existe, que sem isto sairia "nada a aplicar" e nunca convergiria (§6)."""
    backup = _BACKUP_CONFORME.replace(" description CIRC-2 ACME [1G]\n", "")
    estado = _estado_do_bloco(_SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), backup)
    assert estado == "atualizar"


def test_estado_subinterface_sem_o_qos_e_atualizar() -> None:
    backup = _BACKUP_CONFORME.replace(
        " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n", ""
    )
    estado = _estado_do_bloco(_SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), backup)
    assert estado == "atualizar"


def test_estado_subinterface_com_outra_taxa_e_atualizar() -> None:
    """Taxa diferente não é "já presente": o plano pede 1 Gbps e o equipamento
    tem 500 Mbps."""
    backup = _BACKUP_CONFORME.replace("1024000", "500000")
    estado = _estado_do_bloco(_SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), backup)
    assert estado == "atualizar"


def test_re_diff_aplica_o_atualizar_e_nao_aborta_com_um_completo() -> None:
    """O abort de "apenas parte do plano consta" olha só os creates que constam.
    Um plano com um bloco completo e outro a atualizar abortaria em falso se o
    `atualizar` caísse no `a_pular` (§6)."""
    completo = dict(_SUB_COM_DESCRICAO)
    a_atualizar = {
        **_SUB_COM_DESCRICAO, "objeto_id": 2,
        "comandos": [*_SUB_COM_DESCRICAO["comandos"]],
    }
    a_atualizar["comandos"][1] = "description CIRC-3 OUTRA [1G]"
    a_aplicar, a_pular, erro = _re_diff(
        [completo, a_atualizar], _recursos_com_subif(_ENDERECO_DO_BLOCO), _BACKUP_CONFORME
    )
    assert erro is None
    assert a_pular == [completo]
    assert a_aplicar == [a_atualizar]


def test_pos_check_marca_atualizar_como_atencao_e_nao_como_critica(tmp_path: Path) -> None:
    """O pós-check confere presença por identidade; o conteúdo que não chegou
    inteiro é atenção (§6) — o bloco está lá, e é isso que o pós-check sabe
    medir.

    O backup vai sem a descrição: é o estado que o `atualizar` deixa quando o
    VRP recusa a linha, e é ele que o pós-check lê de verdade
    (`removal.texto_backup`) em vez de um `raw_files` vazio.
    """
    arquivo = tmp_path / "cfg.txt"
    arquivo.write_text(_BACKUP_CONFORME.replace(" description CIRC-2 ACME [1G]\n", ""),
                       encoding="utf-8")
    step = SimpleNamespace(plano_json=[_SUB_COM_DESCRICAO])
    snap = SimpleNamespace(
        resources=_recursos_com_subif(_ENDERECO_DO_BLOCO),
        raw_files={"config_backup": [str(arquivo)]},
    )
    items = _verifica_aplicados(step, snap)
    assert [i["severidade"] for i in items] == ["atencao"]
    assert items[0]["tipo"] == "subinterface.conteudo"


# ---------------------------------------------------------------------------
# C1 — os leitores do bloco são imunes à indentação do render
# ---------------------------------------------------------------------------

def test_enderecos_do_bloco_le_a_linha_indentada() -> None:
    """C1 — o bloco do render pode vir indentado, e os DOIS `re.match` são
    âncora no início: sem a normalização o helper devolve `{}` e a identidade
    por endereços (§5.3) deixa de existir — um bloco cujo endereço o
    equipamento não tem passa a "consta"."""
    comandos = [
        "interface GE1/0/0.2",
        " vlan-type dot1q vid 2",
        " ip address 10.0.0.0 255.255.255.254",
        " ipv6 address 2804:194C::1/126",
    ]
    assert _enderecos_do_bloco(comandos) == {"v4": ["10.0.0.0/31"], "v6": ["2804:194C::1/126"]}
    # a forma plana responde o mesmo (a normalização é a mesma regra)
    assert _enderecos_do_bloco([" ".join(c.split()) for c in comandos]) == {
        "v4": ["10.0.0.0/31"], "v6": ["2804:194C::1/126"],
    }


def test_as_duas_peer_familia_concordam_no_bloco_indentado() -> None:
    """C1 — a paridade entre as duas cópias de `_peer_familia`.

    A função existe duas vezes, de propósito: o plano (`changes._ja_existe`) e a
    execução (`runner._estado_do_bloco`) fazem a mesma pergunta em módulos
    diferentes, e consolidá-las alargaria o diff de uma frente que não as criou.
    O que as impede de divergir é este teste: ele exercita AS DUAS sobre a mesma
    lista, então consertar uma e esquecer a outra quebra aqui — e não no
    equipamento, quando o plano e a execução discordarem sobre a família do peer.
    """
    v4 = [
        "bgp 61785",
        " peer 100.110.0.74 as-number 270620",
        " ipv4-family unicast",
        "  peer 100.110.0.74 enable",
    ]
    v6 = [c.replace("ipv4-family", "ipv6-family") for c in v4]
    for comandos, esperado in ((v4, "ipv4"), (v6, "ipv6")):
        assert _peer_familia(comandos) == esperado
        assert changes._peer_familia(comandos) == esperado
