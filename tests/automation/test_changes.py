"""Plano do ciclo D (spec §5): diff do render vs encontrado (provision) e inverso (remove)."""
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.automation import changes, removal, render
from gerenet.domain import models
from gerenet.domain.services.errors import ValidationError


def _ambiente(db_session):
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


def _circuito(db_session, amb, *, velocidade_mbps: int | None = None):
    from gerenet.domain.schemas import CircuitCreate, PrefixAuthorizationCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.ipam import reservar_circuito
    from gerenet.domain.services.prefix_authorizations import create_authorization

    circ = create_circuit(
        db_session,
        CircuitCreate(
            code="circ-001", organization_id=amb["org"].id, site_id=amb["site"].id,
            access_device_id=amb["dev"].id, access_port="GE0/0/1",
            edge_device_id=amb["dev"].id, stack="ipv4", vlan_mode="unica",
            edge_trunk="GE1/0/0", p2p_v4_len=31, velocidade_mbps=velocidade_mbps,
        ),
        actor="cli",
    )
    reservar_circuito(db_session, circ.id, actor="cli")
    create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=amb["org"].id, family="ipv4", prefix="192.0.2.0/24"
        ),
        actor="cli",
    )
    return circ


def _sessao(db_session, circ, amb, *, perfil_full=True):
    from gerenet.domain.schemas import BgpSessionCreate
    from gerenet.domain.services.bgp_sessions import create_session

    perfil_id = None
    if perfil_full:
        perfil = db_session.scalar(
            select(models.PolicyProfile).where(models.PolicyProfile.name == "full")
        )
        assert perfil is not None, "catálogo de produtos não seedado?"
        perfil_id = perfil.id
    return create_session(
        db_session,
        BgpSessionCreate(
            circuit_id=circ.id, device_id=amb["dev"].id, afi="ipv4",
            local_address="100.64.1.1", remote_address="100.64.1.2",
            asn_local=65000, asn_remote=64512, export_profile_id=perfil_id,
        ),
        actor="cli",
    )


def _snapshot_encontrado(db_session, amb, tmp_path: Path, *, asn_peer=64512, com_backup=True):
    """Snapshot cujo estado ENCONTRADO é exatamente o desejado (render aplicado).

    `asn_peer` permite divergir o ASN do peer encontrado (negative control do
    skip §5.1.3: mesmo IP com ASN diferente NÃO consta do encontrado).

    `com_backup=False` monta o snapshot SEM o recurso `config_backup` — a
    coleta que não produziu o texto da configuração (o gate do plano o exige
    desde o I2). A chave em `resources` é a que o coletor grava junto com o
    arquivo (`recursos[nome] = {"backup": True}`), e sem ela o snapshot não é
    a forma que uma coleta bem-sucedida produz.
    """
    r = render.render_desejado(db_session, amb["dev"].id)
    arquivo = tmp_path / "cfg.txt"
    # A forma do `display current-configuration`: cabeçalho na coluna 0 e
    # sub-comandos indentados. O `RenderResult.texto` é plano, e escrevê-lo
    # como veio daria um backup em que nenhum bloco de interface existe — o
    # plano deixaria de pular o que já está lá e o teste mediria outra coisa.
    corpo = "\n#\n".join(
        "\n".join([b.comandos[0], *(f" {c}" for c in b.comandos[1:])])
        for b in r.blocos
    )
    arquivo.write_text(corpo + "\n", encoding="utf-8")
    snap = models.DeviceSnapshot(
        device_id=amb["dev"].id, status="success",
        resources={
            "interfaces": [
                {"nome": b.comandos[0].split(None, 1)[1]}
                for b in r.blocos if b.tipo == "subinterface"
            ],
            "bgp_peers": [
                {"afi": "ipv4", "peer": b.comandos[1].split()[1], "asn": asn_peer}
                for b in r.blocos if b.tipo == "bgp_peer"
            ],
            **({"config_backup": {"backup": True}} if com_backup else {}),
        },
        raw_files={"config_backup": [str(arquivo)]} if com_backup else {},
    )
    db_session.add(snap)
    db_session.commit()
    return snap


TIPOS_ESPERADOS = ["subinterface", "prefix_list", "route_policy_import", "route_policy_export", "bgp_peer"]


def test_plan_provision_gera_blocos_create_na_ordem_do_render(db_session):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    plano = changes.plan_provision(db_session, circ)
    assert [p.device_id for p in plano] == [amb["dev"].id]
    assert [b["tipo"] for b in plano[0].blocos] == TIPOS_ESPERADOS
    assert all(b["acao"] == "create" for b in plano[0].blocos)
    assert plano[0].baseline_snapshot_id is None
    assert plano[0].aviso is not None  # sem snapshot: skip vazio, aviso §5.1


def test_ja_existe_as_path_filter_pelo_encontrado() -> None:
    """Item 1 — o bloco de as-path-filter já presente no backup é pulado no plano
    (idempotência: reexecutar a CR não re-aplica a mesma definição)."""
    bloco = render.BlocoRender(
        "as_path_filter", "session", 1,
        ["ip as-path-filter AS-PATH-65001-OWN permit _65001_"],
    )
    assert changes._ja_existe(
        bloco, {}, "ip as-path-filter AS-PATH-65001-OWN permit _65001_"
    )
    assert not changes._ja_existe(bloco, {}, "")


def test_plan_provision_pula_blocos_ja_presentes(db_session, tmp_path):
    """Item 1 — com QoS no circuito, o bloco com `description` e `qos car` é
    pulado quando o encontrado já tem os dois.

    É a junção que faltava: dobra do `qos car` (`equivalencia_vrp`) e
    `_ja_existe` tinham teste cada uma, e nenhum teste as ligava. Sem a dobra, o
    `qos car cir 1024000 inbound` do bloco nunca casaria o
    `qos car cir 1024000 cbs … inbound` do VRP e o plano reaplicaria o parque.
    """
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb, velocidade_mbps=1024)
    _sessao(db_session, circ, amb)
    snap = _snapshot_encontrado(db_session, amb, tmp_path)
    # A cena só mede a junção se o backup realmente carregar o QoS; sem isto,
    # tirar a velocidade do circuito deixaria o teste verde sem medir nada.
    assert "qos car cir 1024000 inbound" in removal.texto_backup(snap)
    plano = changes.plan_provision(db_session, circ)
    assert plano[0].blocos == []
    assert plano[0].baseline_snapshot_id == snap.id
    assert plano[0].aviso is None


def test_plan_provision_sem_config_backup_cai_no_caminho_sem_recursos(db_session, tmp_path):
    """I2 — o gate do plano tem de exigir o texto da configuração.

    O `_ja_existe` da subinterface lê o texto (`removal.texto_backup`): sem o
    recurso `config_backup` o diff não conferiu nada e ainda assim diria ter
    conferido — o bloco que já está no equipamento entra no plano como `create`
    e, na execução, com a coleta boa, o re-diff §5.3 aborta com "apenas parte do
    plano consta", mandando o operador procurar no equipamento um problema que
    veio do plano.

    Com o recurso no gate, o plano cai no caminho que já existe para recurso
    faltando: os blocos vão inteiros, com o aviso, e SEM baseline — a execução
    re-coleta antes do re-diff, em vez de o plano fingir que conferiu.
    """
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    _snapshot_encontrado(db_session, amb, tmp_path, com_backup=False)
    plano = changes.plan_provision(db_session, circ)
    assert plano[0].aviso == changes._SEM_RECURSOS_AVISO
    assert plano[0].baseline_snapshot_id is None
    assert [b["tipo"] for b in plano[0].blocos] == TIPOS_ESPERADOS
    assert all(b["acao"] == "create" for b in plano[0].blocos)


def test_plan_provision_ignora_comentarios(db_session, tmp_path):
    """Divergências viram bloco `comentario` (render.py:254) — nunca comandos."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    # remove uma autorização depois de planejar? Não: o cenário é render com dívida.
    # Simular dívida: política é estável; o filtro `b.tipo != "comentario"` é o alvo.
    plano = changes.plan_provision(db_session, circ)
    assert all(b["tipo"] != "comentario" for p in plano for b in p.blocos)


def test_plan_provision_nao_pula_peer_com_asn_divergente(db_session, tmp_path):
    """§5.1.3: mesmo IP com ASN diferente NÃO consta do encontrado — o bloco do
    peer permanece no plano (mesmo recurso/chave em que reconcile marca
    `peer.asn` como crítica)."""
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    _snapshot_encontrado(db_session, amb, tmp_path, asn_peer=64513)
    plano = changes.plan_provision(db_session, circ)
    assert [b["tipo"] for b in plano[0].blocos] == ["bgp_peer"]
    assert all(b["acao"] == "create" for b in plano[0].blocos)


def test_plan_remocao_usa_ordem_inversa_do_encontrado(db_session, tmp_path):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    _snapshot_encontrado(db_session, amb, tmp_path)
    plano = changes.plan_remocao(db_session, circ)
    assert [b["tipo"] for b in plano[0].blocos] == list(reversed(TIPOS_ESPERADOS))
    assert all(b["acao"] == "delete" for b in plano[0].blocos)
    assert plano[0].baseline_snapshot_id is not None
    assert plano[0].aviso is None


def test_plan_remocao_exige_snapshot_com_recursos(db_session):
    amb = _ambiente(db_session)
    circ = _circuito(db_session, amb)
    _sessao(db_session, circ, amb)
    with pytest.raises(ValidationError, match="colete antes"):
        changes.plan_remocao(db_session, circ)
