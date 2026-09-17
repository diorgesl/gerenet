"""A adoção do plano (spec §9): transação única, idempotência e auditoria."""
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.automation.community_plan import PlanoLido, PortaoPlano, PropostaPlano
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate
from gerenet.domain.services.community_plan import (
    adotar_plano,
    obter_plano,
    propor_adocao,
    validar_plano,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, ValidationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _device_com_snapshot(
    db_session,
    nome: str,
    fixture: str | Path,
    *,
    asn: int | None = 61785,
    peers: list[dict] | None = None,
) -> models.Device:
    # `fixture` aceita caminho absoluto: o `Path` do `/` deixa ele vencer a raiz
    # das fixtures, que é como os testes de configuração sintética (`tmp_path`)
    # usam este mesmo helper.
    device = create_device(
        db_session, DeviceCreate(name=nome, management_address="10.0.0.9", asn=asn), actor="teste"
    )
    db_session.add(
        models.DeviceSnapshot(
            device_id=device.id, status="success",
            raw_files={"config_backup": [str(FIXTURES / fixture)]},
            # `bgp_peers` é o recurso que o `_peers_dos_snapshots` lê para o estado
            # do alvo (§9.3): sem ele o alvo sai em `parados` e o papel não roda.
            resources={"bgp_peers": peers} if peers is not None else None,
        )
    )
    db_session.commit()
    return device


def test_propoe_a_partir_do_snapshot_coletado(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-01", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    assert proposta.plano.asn_principal == 61785
    assert {c.nome for c in proposta.plano.classes} >= {"com-TRANSITO-FULL", "com-CLIENTES_PARCEIROS-CDN"}
    assert db_session.scalar(select(models.CommunityPlan)) is None  # propor não escreve


def test_adota_numa_transacao_e_audita(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-02", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    plano = adotar_plano(
        db_session, proposta, device_id=device.id, snapshot_id=proposta.plano.snapshot_id, actor="ana"
    )
    db_session.commit()

    assert plano.asn_principal == 61785
    assert plano.origem == "adotado"
    assert db_session.scalar(select(models.CommunityPlan).where(models.CommunityPlan.admin_status)) is not None
    classe = db_session.scalar(select(models.Community).where(models.Community.valor_v4 == 1010))
    assert classe is not None and classe.banda == "transito" and classe.origem == "adotado"
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    )
    assert evento is not None and evento.actor == "ana"


def test_adotar_duas_vezes_nao_duplica(db_session) -> None:
    """§13: idempotência — o mesmo snapshot adotado duas vezes não muda nada."""
    device = _device_com_snapshot(db_session, "ne-plano-03", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()
    eventos = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    ).all()

    proposta_de_novo = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta_de_novo, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    assert len(db_session.scalars(select(models.CommunityPlan)).all()) == 1
    assert len(db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    ).all()) == len(eventos)  # sem transição, sem evento (ruling 5)
    assert len(db_session.scalars(
        select(models.Community).where(models.Community.name == "com-TRANSITO-FULL")
    ).all()) == 1


def test_a_validacao_roda_sobre_o_plano_adotado(db_session) -> None:
    device = _device_com_snapshot(db_session, "ne-plano-04", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    achados = validar_plano(db_session, [device.id])
    assert obter_plano(db_session) is not None
    assert any(a.codigo == "classe_aplicada_nao_testada" and a.valor == "61785:3001" for a in achados)


def test_segunda_adocao_com_outro_asn_recusa(db_session) -> None:
    """R28: plano ativo de outro ASN principal recusa com `ConflictError`.

    Os filhos do plano não têm recorte por plano ativo: as UNIQUEs de
    `community_gates` (nome, papel, afi) e de `community_import_rules` (papel,
    afi) são do vocabulário inteiro, e a `CommunityImportRule` nem tem
    `admin_status` para desativar. Substituir o plano pediria mexer no modelo da
    T1, então a segunda adoção recusa **antes de escrever qualquer coisa** — o
    que mantém a transação única da §9 de pé.
    """
    device = _device_com_snapshot(db_session, "ne-plano-05", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    outra = replace(proposta, plano=replace(proposta.plano, asn_principal=65000))
    with pytest.raises(ConflictError) as erro:
        adotar_plano(db_session, outra, device_id=device.id, snapshot_id=None, actor="ana")
    assert "61785" in str(erro.value)  # a mensagem nomeia o ASN que está ativo

    ativo = db_session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.admin_status.is_(True))
    )
    assert ativo is not None and ativo.asn_principal == 61785
    assert db_session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.asn_principal == 65000)
    ) is None


def test_portao_guarda_os_membros_do_vocabulario(db_session) -> None:
    """R29: o membro do portão que só existe no vocabulário da §6.1 vira linha.

    Sem a linha, o `if n in ids` do `adotar_plano` descarta o membro em silêncio e
    o portão gravado não é o portão do equipamento.
    """
    device = _device_com_snapshot(db_session, "ne-plano-06", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    for nome, valor_v4, valor_v6 in (("com-TAMANHO-2", 7002, 7102), ("com-ONLY-CDN", 991, 991)):
        classe = db_session.scalar(
            select(models.Community).where(models.Community.name == nome)
        )
        assert classe is not None, f"{nome} não virou linha de `communities`"
        assert (classe.valor_v4, classe.valor_v6) == (valor_v4, valor_v6)

    portao = next(p for p in obter_plano(db_session).portoes if p.nome == "RouteExportCheck")
    # 7002 e 7102 são o mesmo `com-TAMANHO-2`: a lista do portão não repete
    assert portao.aceitas.count("com-TAMANHO-2") == 1
    assert "com-ONLY-CDN" in portao.recusadas


def test_membro_sem_classe_vira_achado(db_session) -> None:
    """R29b: o membro que mesmo assim não resolve não some, vira pendência."""
    device = _device_com_snapshot(db_session, "ne-plano-07", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    achado = next(
        a for a in proposta.divergencias
        if a.codigo == "portao_membro_sem_classe" and a.valor == "61785:7012"
    )
    assert achado.filtro == "RouteExportCheckV6"
    assert achado.severidade == "atencao"

    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()
    assert any(
        a.codigo == "portao_membro_sem_classe" and a.valor == "61785:7012"
        for a in validar_plano(db_session, [device.id])
    )


def test_contingencia_nao_estoura_o_papel(db_session) -> None:
    """R30: `Upstream.tipo` tem `contingencia` e o enum do alvo não.

    Sem o recorte, o papel sai da SoT como `contingencia` e o INSERT de
    `CommunityTarget` estoura no enum.
    """
    organizacao = models.Organization(name="Operadora F6", asn=61587, kind="operadora")
    db_session.add(organizacao)
    db_session.flush()
    db_session.add(
        models.Upstream(name="contingencia-f6", tipo="contingencia",
                        organization_id=organizacao.id)
    )
    device = _device_com_snapshot(
        db_session, "ne-plano-08", "comunidades_edge.txt",
        peers=[{"peer": "100.127.190.5", "afi": "ipv4", "asn": 61587, "estado": "Established"}],
    )
    db_session.commit()

    proposta = propor_adocao(db_session, device.id)
    alvo = next(a for a in proposta.plano.alvos if a.nome == "PARCEIROS_CDN")
    assert alvo.papel in models.TARGET_PAPEL

    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()
    gravado = db_session.scalar(
        select(models.CommunityTarget).where(models.CommunityTarget.nome == "PARCEIROS_CDN")
    )
    assert gravado is not None and gravado.papel in models.TARGET_PAPEL


def test_adocao_sem_asn_principal_recusa(db_session) -> None:
    """R31: proposta sem ASN principal recusa antes de escrever, não estoura o NOT NULL.

    O caso é o do equipamento sem `devices.asn` cuja configuração coletada também
    não declara `bgp <asn>` (o switch MPLS). A fixture declara (`bgp 61785`, linha
    91), então a proposta sai com o ASN da configuração e é o `replace` que monta a
    proposta que aquele switch daria: sem `devices.asn` e sem `bgp` na coleta, o
    ASN não vem de lugar nenhum.
    """
    device = _device_com_snapshot(db_session, "ne-plano-09", "comunidades_edge.txt", asn=None)
    proposta = propor_adocao(db_session, device.id)
    assert proposta.plano.asn_principal == 61785  # a configuração declara o ASN local

    sem_asn = replace(proposta, plano=replace(proposta.plano, asn_principal=None))
    with pytest.raises(ValidationError) as erro:
        adotar_plano(db_session, sem_asn, device_id=device.id, snapshot_id=None, actor="ana")
    assert str(device.id) in str(erro.value)

    assert db_session.scalar(select(models.CommunityPlan)) is None
    assert db_session.scalar(select(models.CommunityGate)) is None


def test_membro_citado_reaproveita_a_linha_de_communities(db_session) -> None:
    """R34: o nome citado que já tem linha de classe entra no portão, sem duplicar.

    A proposta é montada à mão — o serviço a recebe como dado. O portão cita três
    nomes: o `no-export` do catálogo semeado, um nome com linha própria e um que
    não resolve. Sem a busca por nome na materialização, o `if n in ids` do
    `adotar_plano` descartava os dois primeiros em silêncio (o mesmo
    desaparecimento do R29, por outro caminho) e a linha existente não é
    recriada: uma segunda linha com o mesmo `valor_v4` seria recusada pelo índice
    único parcial.
    """
    device = _device_com_snapshot(db_session, "ne-plano-10", "comunidades_edge.txt")
    semeada = db_session.scalar(
        select(models.Community).where(models.Community.name == "no-export")
    )
    assert semeada is not None  # a linha do catálogo, com origem `manual`
    linha = models.Community(name="com-REUSO-v4", valor_v4=6123, valor_v6=6124)
    db_session.add(linha)
    db_session.commit()

    proposta = PropostaPlano(
        plano=PlanoLido(
            asn_principal=61785,
            classes=(),
            portoes=(
                PortaoPlano(
                    nome="RouteExportCheck", papel="upstream", afi="ipv4",
                    aceitas=("no-export", "com-REUSO-v4", "com-FANTASMA"),
                ),
            ),
        )
    )
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="teste")
    db_session.commit()

    portao = db_session.scalar(select(models.CommunityGate))
    assert portao is not None
    # `com-FANTASMA` não tem linha e o vocabulário não o conhece: sem id ele não
    # entra na lista — e é isso que o achado da validação denuncia.
    assert portao.aceitas == [semeada.id, linha.id]

    assert len(db_session.scalars(
        select(models.Community).where(models.Community.name == "no-export")
    ).all()) == 1
    assert len(db_session.scalars(
        select(models.Community).where(models.Community.valor_v4 == 6123)
    ).all()) == 1
    assert db_session.scalar(
        select(models.Community).where(models.Community.name == "com-FANTASMA")
    ) is None

    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    )
    # R35: o número é o das linhas de classe que a adoção usou (`len(ids)`) e não
    # o das classes da proposta — que aqui é zero.
    assert evento is not None and evento.details["depois"]["classes"] == 2
    assert len(proposta.plano.classes) == 0


def test_o_evento_conta_as_classes_que_a_adocao_gravou(db_session) -> None:
    """R35: o `community_plan.adopt` conta as linhas de classe que a adoção usou.

    A fixture propõe 5 classes e a adoção grava 7 linhas de classe: as duas a
    mais são nomes que só o `VOCABULARIO` da §6.1 conhece (`com-TAMANHO-2`, no
    portão, e o `com-ONLY-CDN` da recusa dele), materializados desde o R29(a).
    O evento contava as classes da proposta e registrava 5.
    """
    device = _device_com_snapshot(db_session, "ne-plano-11", "comunidades_edge.txt")
    proposta = propor_adocao(db_session, device.id)
    assert len(proposta.plano.classes) == 5
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "community_plan.adopt")
    )
    assert evento is not None and evento.details["depois"]["classes"] == 7
    assert len(db_session.scalars(
        select(models.Community).where(
            models.Community.origem == "adotado", models.Community.codigo.is_(None)
        )
    ).all()) == 7


def test_membro_sem_codigo_nao_some_da_validacao(db_session, tmp_path) -> None:
    """R34: o valor sem código parseável que não resolve vira achado, não silêncio.

    `888` chega à validação como valor cru do `matches-any` — o formato que o
    `if codigo is None: continue` deixava passar sem achado nenhum, que é o
    desaparecimento do crítico na superfície que compara o plano com o que o
    equipamento testa. É o valor sem código que o leitor entrega (o `{nome solto}`
    o parser descarta, e o nome que só o catálogo tem chega pelo caminho da
    escrita, no teste do `no-export`): nenhuma linha tem esse nome, o
    `VOCABULARIO` não o conhece e o membro fica sem id para a lista do portão.
    """
    caminho = tmp_path / "comunidades_edge_sem_codigo.txt"
    caminho.write_text(
        (FIXTURES / "comunidades_edge.txt").read_text()
        + "\n#\nxpl route-filter RouteExportCheck-TESTE\n"
        " if not community matches-any {888} then\n  refuse\n endif\n end-filter\n"
    )
    device = _device_com_snapshot(db_session, "ne-plano-12", caminho)
    proposta = propor_adocao(db_session, device.id)
    adotar_plano(db_session, proposta, device_id=device.id, snapshot_id=None, actor="ana")
    db_session.commit()

    achado = next(
        a for a in validar_plano(db_session, [device.id])
        if a.codigo == "portao_membro_sem_classe" and a.valor == "888"
    )
    assert achado.filtro == "RouteExportCheck-TESTE"
    assert achado.severidade == "atencao"
