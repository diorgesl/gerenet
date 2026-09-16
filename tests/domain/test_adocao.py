"""A adoção transacional (design §5): uma transação por proposta."""
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.automation.discovery import conferir_fidelidade, listar_propostas
from gerenet.domain import models
from gerenet.domain.schemas import (
    AdocaoAutorizacaoIn,
    AdocaoIn,
    AdocaoSessaoIn,
    DeviceCreate,
    OrganizationCreate,
    PrefixAuthorizationCreate,
    SiteCreate,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import adotar_proposta
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")
# O peer v4 do enlace do CLIENTE-ALFA tem `password cipher` na fixture; o valor
# mora no Vault e o que a SoT guarda é o caminho.
CAMINHO_SENHA = "gerenet/bgp-sessions/adoc-1001/password"
# Um enlace que o render reproduz linha a linha: sem senha de peer, sem QoS e
# sem política, a conferência não tem diferença no grupo que muda. A
# `description` FAZ parte do texto porque o render passou a emiti-la (§4) e a
# SoT a gerencia (§7): é a identidade da revisão que a reproduz, e é isso que
# estes testes medem.
_CONFIG_FIEL = (
    "interface Eth-Trunk127.601\n"
    " vlan-type dot1q 601\n"
    " description ADOC-64512-601 CLIENTE ALFA\n"
    " ip address 100.64.10.0 255.255.255.254\n"
    " statistic enable\n"
    "#\n"
    "bgp 65001\n"
    " peer 100.64.10.1 as-number 64512\n"
    " ipv4-family unicast\n"
    "  peer 100.64.10.1 enable\n"
)


def _ambiente(db_session, tmp_path: Path, *, texto: str | None = None):
    site = create_site(db_session, SiteCreate(name="pop-adoc", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-adoc", management_address="10.0.0.1",
                                                 asn=65001), actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(texto or FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return site, dev


def _proposta(db_session, dev, *, vid=1001):
    return next(p for p in listar_propostas(db_session, dev.id).propostas if p.vid == vid)


def _revisao(dev, *, vid=1001, ciente=True, edge_trunk="Eth-Trunk127", sessoes=None,
             autorizacoes=None, velocidade_mbps=None):
    """A revisão do enlace do CLIENTE-ALFA (o vid 1001 da fixture).

    O `ciente` nasce ligado porque este enlace TEM diferença no grupo que muda:
    o peer tem senha no equipamento (`password cipher`, mascarada na conferência)
    e a SoT não a reproduz — o render só comenta que ela está no Vault. Sem o
    aceite explícito, a adoção recusa, e é o que o teste do `ciente` prende. O
    `edge_trunk` é o que o ensaio derivaria do nome da subinterface, e a adoção
    recusa a revisão que não o traga.

    `velocidade_mbps` é o campo que a frente da velocidade acrescentou (§7): o
    que a adoção grava e o que a `description` e o `qos car` do ensaio derivam.
    """
    return AdocaoIn(
        device_id=dev.id, vrf=None, subinterface=f"Eth-Trunk127.{vid}",
        circuit_code=f"ADOC-64512-{vid}", access_device_id=dev.id, access_port="GE0/0/1",
        edge_trunk=edge_trunk,
        velocidade_mbps=velocidade_mbps,
        organizacao_nova={"name": "Cliente Alfa", "kind": "downstream", "asn": 64512},
        # Só o peer v4 do enlace tem senha no equipamento: o operador informa o
        # caminho do segredo no Vault para essa sessão, e não para a outra.
        sessoes=sessoes if sessoes is not None else [
            AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA),
            AdocaoSessaoIn(afi="ipv6"),
        ],
        autorizacoes=autorizacoes or [],
        ciente=ciente,
    )


def _tipos_auditados(db_session) -> list[str]:
    return [e.type for e in db_session.scalars(select(models.AuditEvent))]


def test_adota_a_cadeia_inteira_numa_transacao(db_session, tmp_path) -> None:
    _site, dev = _ambiente(db_session, tmp_path)
    circ_id = adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                              revisao=_revisao(dev), actor="cli")
    circ = db_session.get(models.Circuit, circ_id)
    assert circ.code == "ADOC-64512-1001"
    assert circ.organization_id is not None
    vlan = db_session.scalar(select(models.Vlan).where(models.Vlan.circuit_id == circ_id))
    assert vlan.vid == 1001
    sessoes = list(db_session.scalars(
        select(models.BgpSession).where(models.BgpSession.circuit_id == circ_id)
    ))
    assert len(sessoes) == 2
    # O caminho do segredo que a revisão informou chega à sessão (§5.4).
    assert next(s for s in sessoes if s.afi == "ipv4").password_ref == CAMINHO_SENHA
    tipos = [e.type for e in db_session.scalars(select(models.AuditEvent))]
    assert "discovery.adopt" in tipos


def test_conflito_de_reserva_nao_deixa_nada_gravado(db_session, tmp_path) -> None:
    """A asserção que a parte 1 não podia fazer: a transação é uma só.

    O `vlan_tomada` já entra na proposta como conflito, então quem recusa aqui é
    a guarda do veredito — antes de qualquer escrita. Quem prova o rollback com
    escrita pendente é o `test_recusa_da_sessao_desfaz_a_adocao_inteira`.
    """
    from gerenet.domain.schemas import CircuitCreate, OrganizationCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.organizations import create_organization

    site, dev = _ambiente(db_session, tmp_path)
    org = create_organization(db_session, OrganizationCreate(name="Dono da VLAN", asn=64999),
                              actor="cli")
    tomador = create_circuit(db_session, CircuitCreate(
        code="CIRC-TOMADOR", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, vid=1001, kind="vlan", circuit_id=tomador.id))
    db_session.commit()
    antes = db_session.query(models.Circuit).count()
    with pytest.raises(ConflictError):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                        actor="cli")
    assert db_session.query(models.Circuit).count() == antes
    assert db_session.scalar(
        select(models.Organization).where(models.Organization.name == "Cliente Alfa")
    ) is None


def test_sem_organizacao_bloqueia(db_session, tmp_path) -> None:
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova = None
    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")
    # A mensagem prende QUAL guarda recusou: o `ciente` também levanta
    # `ValidationError`, e é antes desta.
    assert "Informe a organização" in str(exc.value)


def test_adotar_de_novo_encontra_a_lista_vazia(db_session, tmp_path) -> None:
    """O objeto passou a existir na SoT, então a proposta sai da lista sozinha."""
    _site, dev = _ambiente(db_session, tmp_path)
    adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                    actor="cli")
    assert 1001 not in {p.vid for p in listar_propostas(db_session, dev.id).propostas}


def test_diferenca_no_grupo_que_muda_exige_ciente(db_session, tmp_path) -> None:
    """Sem o aceite explícito, a adoção recusa a diferença que mudaria o
    equipamento — e não grava nada (design §6/§9)."""
    _site, dev = _ambiente(db_session, tmp_path)
    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                        revisao=_revisao(dev, ciente=False), actor="cli")
    assert "ciente" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0
    assert "discovery.adopt" not in _tipos_auditados(db_session)


def test_ensaio_fiel_aceita_sem_ciente(db_session, tmp_path) -> None:
    """O outro lado do gate: com o grupo que muda vazio, o aceite é direto
    (design §6). A fixture do ALFA sempre exige `ciente`, então sem este teste
    uma regressão que passasse a exigi-lo sempre deixaria a suíte verde."""
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    prop = _proposta(db_session, dev, vid=601)

    assert not any(
        d.exige_ciente
        for d in conferir_fidelidade(
            db_session, prop, circuit_code="ADOC-64512-601",
            organizacao_nome="Cliente Alfa",
        )
    )

    circ_id = adotar_proposta(
        db_session, proposta=prop, actor="cli",
        revisao=_revisao(dev, vid=601, ciente=False, sessoes=[AdocaoSessaoIn(afi="ipv4")]),
    )
    circ = db_session.get(models.Circuit, circ_id)
    # O `stack` sai das sessões que nasceram: aqui, uma família só.
    assert circ.stack == "ipv4"
    assert circ.edge_trunk == "Eth-Trunk127"
    assert db_session.query(models.BgpSession).count() == 1


def test_a_auditoria_leva_todas_as_diferencas(db_session, tmp_path) -> None:
    """O payload é trilha, não decisão: leva os quatro grupos de todo contexto,
    inclusive os vazios (design §17.1). A descrição da subinterface deixou de
    ser "não gerenciada" na frente da velocidade (§7): o equipamento tem a do
    CLIENTE-ALFA e a adoção grava a do código novo, então ela aparece dos dois
    lados — e é por isso que `_revisao` nasce com o `ciente` ligado."""
    _site, dev = _ambiente(db_session, tmp_path)
    adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                    actor="cli")
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "discovery.adopt")
    )
    payload = evento.details["depois"]
    campos = {"contexto", "sobrando", "faltando", "nao_gerenciado", "explicacao"}
    assert all(set(d) == campos for d in payload["diferencas"])
    assert payload["edge_trunk"] == "Eth-Trunk127"
    sub = next(d for d in payload["diferencas"] if d["contexto"] == "subinterface")
    # O `sobrando` é o que o RENDER produz e a configuração não tem, e o
    # `faltando` é o contrário: a descrição do equipamento é `CLIENTE-ALFA` e a
    # que a adoção grava é `ADOC-64512-1001 CLIENTE ALFA`.
    assert any("CLIENTE-ALFA" in linha for linha in sub["faltando"])
    assert any("ADOC-64512-1001 CLIENTE ALFA" in linha for linha in sub["sobrando"])
    assert sub["nao_gerenciado"] == []


def test_revisao_de_outro_enlace_recusa(db_session, tmp_path) -> None:
    """A identidade da revisão é conferida contra a da proposta, campo a campo.

    Pelo CLI a proposta sai dos argumentos e o arquivo é livre: sem a guarda, a
    revisão de um equipamento adota no outro com o `ciente` dela liberando o gate
    das diferenças deste, e a identidade errada fica gravada (design §6)."""
    _site, dev = _ambiente(db_session, tmp_path)
    outro = create_device(db_session, DeviceCreate(name="ne8000-adoc-outro",
                                                   management_address="10.0.0.2", asn=65001),
                          actor="cli")
    db_session.commit()

    for campo, valor in (("device_id", outro.id), ("vrf", "VPNA"),
                         ("subinterface", "Eth-Trunk127.9999")):
        revisao = _revisao(dev)
        setattr(revisao, campo, valor)
        with pytest.raises(ValidationError) as exc:
            adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                            revisao=revisao, actor="cli")
        # A mensagem prende QUAL campo divergiu: os outros três campos da
        # identidade estão iguais, e um recado genérico não diria qual corrigir.
        assert campo in str(exc.value), campo
    assert db_session.query(models.Circuit).count() == 0


def test_revisao_sem_trunk_recusa(db_session, tmp_path) -> None:
    """O ensaio deriva o trunk do nome da subinterface e a escrita grava o da
    revisão: sem ele o circuito nasce sem o bloco da subinterface conferida."""
    _site, dev = _ambiente(db_session, tmp_path)
    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                        revisao=_revisao(dev, edge_trunk=None), actor="cli")
    assert "Eth-Trunk127" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0


def test_trunk_so_de_espacos_recusa_como_o_vazio(db_session, tmp_path) -> None:
    """Só espaços é vazio com outra roupa, e a guarda do serviço olha falsy: sem
    o aparo o valor passa, é gravado como veio, e todo render seguinte monta
    `interface <espaços>.<vid>` — um nome que o equipamento não tem."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, edge_trunk="   ")
    assert revisao.edge_trunk is None  # o aparo é do schema, no caminho todo

    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                        revisao=revisao, actor="cli")
    assert "Eth-Trunk127" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0


def test_a_conferencia_usa_o_trunk_da_revisao(db_session, tmp_path) -> None:
    """O ensaio monta o circuito com o trunk da revisão, e não com o derivado do
    nome: com outro trunk o circuito que nasceria tem outro bloco, e a diferença
    tem de aparecer em vez de a comparação sair fiel.

    O `_CONFIG_FIEL` entra porque a `description` da subinterface é gerenciada
    desde a frente da velocidade (§7): só no enlace sem QoS, e com o código e a
    organização da revisão, o bloco bate linha a linha."""
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    prop = _proposta(db_session, dev, vid=601)
    identidade = {"circuit_code": "ADOC-64512-601", "organizacao_nome": "Cliente Alfa"}

    derivado = next(d for d in conferir_fidelidade(db_session, prop, **identidade)
                    if d.contexto == "subinterface")
    revisado = next(d for d in conferir_fidelidade(db_session, prop, edge_trunk="Eth-Trunk9",
                                                   **identidade)
                    if d.contexto == "subinterface")

    assert derivado.exige_ciente is False
    assert revisado.exige_ciente is True


def test_revisao_sem_uma_familia_recusa(db_session, tmp_path) -> None:
    """Sessão a menos é peer que nunca entra no `_conhecidos`: a descoberta
    devolveria a mesma subinterface para sempre, agora com `vlan_tomada`."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, sessoes=[AdocaoSessaoIn(afi="ipv4", password_ref=CAMINHO_SENHA)])
    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")
    assert "ipv6" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0


def test_familia_a_mais_na_revisao_recusa(db_session, tmp_path) -> None:
    """A revisão pediu uma família que o enlace não tem: `ValidationError` do
    serviço (400), e não um `StopIteration` no meio da escrita."""
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    revisao = _revisao(dev, vid=601, ciente=False,
                       sessoes=[AdocaoSessaoIn(afi="ipv4"), AdocaoSessaoIn(afi="ipv6")])
    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev, vid=601),
                        revisao=revisao, actor="cli")
    assert "ipv6" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0


def test_recusa_da_sessao_desfaz_a_adocao_inteira(db_session, tmp_path) -> None:
    """A recusa chega com a organização, o circuito e as reservas já gravados:
    é o rollback da adoção que faz não sobrar adoção parcial (design §9)."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova.asn = 64999  # o ASN do par é 64512

    with pytest.raises(ValidationError) as exc:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert "64512" in str(exc.value)
    assert db_session.query(models.Circuit).count() == 0
    assert db_session.query(models.Organization).count() == 0
    assert db_session.query(models.Vlan).count() == 0
    assert db_session.query(models.IpPrefix).count() == 0
    assert db_session.query(models.BgpSession).count() == 0
    # A trilha é da mesma transação: o que o rollback desfez não deixa evento.
    assert "circuit.create" not in _tipos_auditados(db_session)
    assert "discovery.adopt" not in _tipos_auditados(db_session)


# ---- as autorizações do registro na transação da adoção (design §6) ----

def _autorizacoes(db_session) -> list[models.BgpPrefixAuthorization]:
    return list(db_session.scalars(
        select(models.BgpPrefixAuthorization).order_by(models.BgpPrefixAuthorization.prefix)
    ))


def test_adota_gravando_as_autorizacoes_do_registro(db_session, tmp_path) -> None:
    """Os blocos entram na MESMA transação da organização e do circuito, com a
    procedência gravada: é o que deixa uma auditoria futura saber quais
    autorizações foram preenchidas pela máquina."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
        AdocaoAutorizacaoIn(prefix="2804:2594::/32", family="ipv6"),
    ])

    adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao, actor="cli")

    auths = _autorizacoes(db_session)
    assert [a.prefix for a in auths] == ["138.121.28.0/22", "2804:2594::/32"]
    org = db_session.scalars(select(models.Organization)).one()
    assert {a.organization_id for a in auths} == {org.id}
    assert {a.origin for a in auths} == {"registro"}
    assert {a.validacao for a in auths} == {None}
    assert all("AS64512" in a.notes for a in auths)
    assert [e.type for e in db_session.scalars(select(models.AuditEvent))].count(
        "authorization.create"
    ) == 2


def test_bloco_conflitante_desfaz_a_adocao_inteira(db_session, tmp_path) -> None:
    """O conflito de sobreposição é por bloco (§7), e a guarda é de defesa em
    profundidade: se um bloco conflitante chegar pela API, quem recusa é o
    `create_authorization`, com o nome das duas organizações — e a transação
    inteira desfaz, no mesmo estilo das outras guardas da adoção."""
    outra = create_organization(
        db_session, OrganizationCreate(name="Cliente Beta", asn=64513), actor="cli"
    )
    create_authorization(db_session, PrefixAuthorizationCreate(
        organization_id=outra.id, family="ipv4", prefix="138.121.28.0/24"), actor="cli")
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])

    with pytest.raises(ConflictError) as excinfo:
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert "Cliente Beta" in str(excinfo.value)
    assert "Cliente Alfa" in str(excinfo.value)
    # Nada ficou: nem a organização nova, nem a autorização dela, nem o
    # circuito. A autorização do Beta é a única que resta — ela nasceu com o
    # `commit` do próprio serviço, antes da adoção, e o par (prefixo, dono)
    # prova que o bloco /22 da adoção não passou.
    assert db_session.scalars(select(models.Organization)).all() == [outra]
    assert [(a.prefix, a.organization_id) for a in _autorizacoes(db_session)] == [
        ("138.121.28.0/24", outra.id)
    ]
    assert db_session.scalars(select(models.Circuit)).all() == []


def test_autorizacoes_com_organizacao_existente_sao_recusadas(db_session, tmp_path) -> None:
    """A lista só vale com a organização nova: para uma existente, os blocos
    dela se cadastram na página da organização — e somá-los calado aqui
    autorizaria prefixo que ninguém revisou nesta tela."""
    existente = create_organization(
        db_session, OrganizationCreate(name="Cliente Existente", asn=64514), actor="cli"
    )
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])
    revisao.organizacao_nova = None
    revisao.organizacao_id = existente.id

    with pytest.raises(ValidationError, match="organização nova"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert _autorizacoes(db_session) == []


def test_autorizacoes_com_os_dois_campos_sao_recusadas(db_session, tmp_path) -> None:
    """O corpo com `organizacao_id` E `organizacao_nova` é contraditório, e sem
    esta guarda ele passava: a organização nova nem era criada (o id não é nulo)
    e os blocos caiam calados na existente — a escrita que esta guarda existe
    para proibir, e o caminho que o `--json` do CLI alcança."""
    existente = create_organization(
        db_session, OrganizationCreate(name="Cliente Existente", asn=64512), actor="cli"
    )
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])
    revisao.organizacao_id = existente.id  # e `organizacao_nova` fica como veio

    with pytest.raises(ValidationError, match="organização nova"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert _autorizacoes(db_session) == []
    assert db_session.scalars(select(models.Organization)).all() == [existente]


def test_operadora_nao_recebe_as_autorizacoes_da_adoção(db_session, tmp_path) -> None:
    """Autorização de prefixo é de cliente: o operador tem
    `expected_prefixes_v4`/`v6` no upstream, que são outra coisa. A guarda do
    `create_authorization` continua valendo sem alteração."""
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])
    revisao.organizacao_nova.kind = "operadora"

    with pytest.raises(ValidationError, match="operadora"):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")

    assert db_session.scalars(select(models.Organization)).all() == []
    assert _autorizacoes(db_session) == []


def test_adotar_de_novo_nao_cria_nada(db_session, tmp_path) -> None:
    """A segunda tentativa com a mesma revisão esbarra no nome da organização,
    que já existe — e não deixa autorização nem circuito para trás."""
    _site, dev = _ambiente(db_session, tmp_path)
    proposta = _proposta(db_session, dev)
    revisao = _revisao(dev, autorizacoes=[
        AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
    ])
    adotar_proposta(db_session, proposta=proposta, revisao=revisao, actor="cli")
    antes = (len(_autorizacoes(db_session)), len(list(db_session.scalars(select(models.Circuit)))))

    with pytest.raises(ConflictError):
        adotar_proposta(db_session, proposta=proposta, revisao=revisao, actor="cli")

    assert (len(_autorizacoes(db_session)),
            len(list(db_session.scalars(select(models.Circuit))))) == antes


# ---- a velocidade e a identidade do ensaio (design §7) ----

def test_a_velocidade_da_revisao_vai_para_o_circuito(db_session, tmp_path) -> None:
    """A velocidade entra por `AdocaoIn` e é gravada (§7). O par vem do texto
    porque é ele que traz o `qos car` de onde a sugestão sai."""
    _site, dev = _ambiente(
        db_session, tmp_path,
        texto=(
            "interface Eth-Trunk127.601\n"
            " vlan-type dot1q 601\n"
            " ip address 100.64.10.0 255.255.255.254\n"
            " statistic enable\n"
            " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
            " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
            "#\n"
            "bgp 65001\n"
            " peer 100.64.10.1 as-number 64512\n"
            " ipv4-family unicast\n"
            "  peer 100.64.10.1 enable\n"
        ),
    )
    prop = _proposta(db_session, dev, vid=601)
    assert prop.velocidade_mbps == 1024  # a sugestão veio do equipamento

    circ_id = adotar_proposta(
        db_session, proposta=prop, actor="cli",
        revisao=_revisao(dev, vid=601, velocidade_mbps=1024, ciente=True,
                         sessoes=[AdocaoSessaoIn(afi="ipv4")]),
    )

    assert db_session.get(models.Circuit, circ_id).velocidade_mbps == 1024


def test_a_identidade_da_revisao_tira_a_diferenca_falsa_de_descricao(
    db_session, tmp_path,
) -> None:
    """Sem isto, TODA adoção mostraria uma descrição falsa nos dois lados e
    pediria `ciente`: o ensaio montava o circuito com código `ENSAIO-...` e uma
    organização de mentira, e o render derivava a descrição desses dois (§7)."""
    _site, dev = _ambiente(
        db_session, tmp_path,
        texto=(
            "interface Eth-Trunk127.601\n"
            " vlan-type dot1q 601\n"
            " description ADOC-64512-601 CLIENTE ALFA\n"
            " ip address 100.64.10.0 255.255.255.254\n"
            " statistic enable\n"
            "#\n"
            "bgp 65001\n"
            " peer 100.64.10.1 as-number 64512\n"
            " ipv4-family unicast\n"
            "  peer 100.64.10.1 enable\n"
        ),
    )
    prop = _proposta(db_session, dev, vid=601)

    sem_identidade = next(
        d for d in conferir_fidelidade(db_session, prop) if d.contexto == "subinterface"
    )
    com_identidade = next(
        d for d in conferir_fidelidade(
            db_session, prop, circuit_code="ADOC-64512-601",
            organizacao_nome="Cliente Alfa",
        )
        if d.contexto == "subinterface"
    )

    assert sem_identidade.exige_ciente is True
    assert com_identidade.sobrando == ()
    assert com_identidade.faltando == ()
    assert com_identidade.exige_ciente is False


def test_a_organizacao_escolhida_na_lista_vence_a_da_proposta(db_session, tmp_path) -> None:
    """A revisão que escolhe uma organização JÁ cadastrada manda só o
    `organizacao_id` (sem nome novo), e é o nome DELA que a `description` do
    ensaio tem de carregar.

    A classificação por ASN da proposta é heurística: aqui ela aponta para a
    organização que já tinha o ASN 64512, e o operador escolhe outra na lista.
    Com a escolha fora do ensaio, a conferência compararia a descrição da
    primeira e acusaria a mesma diferença falsa que o código de mentira acusava
    — por outro caminho."""
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    provedor = create_organization(
        db_session, OrganizationCreate(name="Provedor X", asn=64512), actor="cli"
    )
    alfa = create_organization(db_session, OrganizationCreate(name="Cliente Alfa"), actor="cli")
    prop = _proposta(db_session, dev, vid=601)
    assert prop.organizacao_id == provedor.id  # a heurística do ASN

    escolhida = next(
        d for d in conferir_fidelidade(db_session, prop, circuit_code="ADOC-64512-601",
                                       organizacao_id=alfa.id)
        if d.contexto == "subinterface"
    )
    da_proposta = next(
        d for d in conferir_fidelidade(db_session, prop, circuit_code="ADOC-64512-601",
                                       organizacao_id=provedor.id)
        if d.contexto == "subinterface"
    )

    assert escolhida.sobrando == ()
    assert escolhida.faltando == ()
    assert escolhida.exige_ciente is False
    # A outra organização, no mesmo ensaio, é quem faz a diferença aparecer: é o
    # nome dela que o render põe na descrição.
    assert any("ADOC-64512-601 PROVEDOR X" in linha for linha in da_proposta.sobrando)


def test_a_organizacao_nova_da_revisao_nao_e_sombreada_pela_da_proposta(
    db_session, tmp_path,
) -> None:
    """A revisão que CRIA a organização manda o nome e não manda id nenhum, e é
    esse nome que a `description` do ensaio tem de carregar.

    A proposta casa uma organização pelo ASN (o cliente já cadastrado), e a
    adoção não consulta essa organização: ela cria a da revisão. Um ensaio que
    ficasse com a da proposta compararia uma descrição que a escrita não produz
    — e, na direção espelhada, com os dois nomes iguais, esconderia a diferença
    real e a adoção deixaria de pedir o `ciente`."""
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    create_organization(db_session, OrganizationCreate(name="Provedor X", asn=64512),
                        actor="cli")
    prop = _proposta(db_session, dev, vid=601)
    assert prop.organizacao_id is not None  # a heurística do ASN casou a Provedor X

    com_o_nome_da_revisao = [
        d for d in conferir_fidelidade(db_session, prop, circuit_code="ADOC-64512-601",
                                       organizacao_nome="Cliente Alfa")
    ]
    com_outro_nome = [
        d for d in conferir_fidelidade(db_session, prop, circuit_code="ADOC-64512-601",
                                       organizacao_nome="Outro Nome")
    ]

    # A conferência ACONTECEU (o contexto `ensaio` é a recusa a COMPARAR, e uma
    # recusa não tem linha de subinterface nenhuma: sem esta asserção as de
    # baixo passariam sem medir nada) e não achou diferença nenhuma: o ensaio
    # emitiu a descrição que o `_CONFIG_FIEL` traz, e não a da organização da
    # proposta.
    assert [d for d in com_o_nome_da_revisao if d.contexto == "ensaio"] == []
    sub_revisao = next(d for d in com_o_nome_da_revisao if d.contexto == "subinterface")
    assert sub_revisao.sobrando == ()
    assert sub_revisao.faltando == ()
    assert sub_revisao.nao_gerenciado == ()
    assert sub_revisao.exige_ciente is False
    # O nome que sai no render é o da revisão, e não o da proposta: com outro
    # nome, a linha aparece com ele.
    diferenciais = [d for d in com_outro_nome if d.contexto == "subinterface"]
    assert diferenciais[0].exige_ciente is True
    assert any("description ADOC-64512-601 OUTRO NOME" in linha
               for linha in diferenciais[0].sobrando)


# ---- as autorizações da revisão na conferência (design §6.4) ----

# A mesma configuração do `_CONFIG_FIEL` com o que as autorizações produzem: o
# `import route-policy` do peer e as duas definições que ele referencia, na forma
# EXATA do render. A fixture do NE8000 não serve para esta pergunta — lá o import
# está na ordem antiga do VRP (`peer ... route-policy ... import`), que difere do
# render com ou sem autorização, e a pergunta ficaria confundida.
_CONFIG_COM_AUTORIZACAO = (
    "interface Eth-Trunk127.601\n"
    " vlan-type dot1q 601\n"
    " description ADOC-64512-601 CLIENTE ALFA\n"
    " ip address 100.64.10.0 255.255.255.254\n"
    " statistic enable\n"
    "#\n"
    "ip ip-prefix IP-PFX-64512-IN-V4 index 10 permit 138.121.28.0/22\n"
    "#\n"
    "route-policy RP-64512-IMPORT-V4 permit node 10\n"
    " if-match ip-prefix IP-PFX-64512-IN-V4\n"
    "#\n"
    "bgp 65001\n"
    " peer 100.64.10.1 as-number 64512\n"
    " ipv4-family unicast\n"
    "  peer 100.64.10.1 enable\n"
    "  peer 100.64.10.1 import route-policy RP-64512-IMPORT-V4\n"
)


# O mesmo enlace com as DUAS autorizações já no equipamento (os índices 10 e 20
# da prefix-list): é o estado em que a adoção da lista `[A, B, A]` deixa o
# equipamento, e o texto precisa ter os dois blocos — sem o segundo, a
# conferência acusaria a linha que o ensaio emite como sobra e a cena deixaria
# de medir a dedup (o `ciente=False` passaria a falhar por outro motivo).
_CONFIG_COM_AUTORIZACAO_DUPLA = _CONFIG_COM_AUTORIZACAO.replace(
    "ip ip-prefix IP-PFX-64512-IN-V4 index 10 permit 138.121.28.0/22\n",
    "ip ip-prefix IP-PFX-64512-IN-V4 index 10 permit 138.121.28.0/22\n"
    "ip ip-prefix IP-PFX-64512-IN-V4 index 20 permit 198.51.100.0/24\n",
)


def test_a_conferencia_ve_as_autorizacoes_da_revisao(db_session, tmp_path) -> None:
    """A conferência tem de enxergar as autorizações que a PRÓPRIA adoção cria.

    Sem elas o `_bloco_import` do render sai cedo (ruling 4): o peer é renderizado
    sem o `import route-policy` que o equipamento tem, a linha do equipamento
    aparece como `faltando` e a adoção exige `ciente` para assumir uma linha que
    a escrita desta mesma adoção cria — o aceite sobre a linha escrita.

    O cenário é o da revisão que CRIA a organização e traz os blocos do registro,
    com `ciente=False`: a adoção só passa se a conferência não tiver nada a
    assumir.
    """
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_COM_AUTORIZACAO)
    prop = _proposta(db_session, dev, vid=601)

    circ_id = adotar_proposta(
        db_session, proposta=prop, actor="cli",
        revisao=_revisao(dev, vid=601, ciente=False,
                         sessoes=[AdocaoSessaoIn(afi="ipv4")],
                         autorizacoes=[AdocaoAutorizacaoIn(prefix="138.121.28.0/22",
                                                           family="ipv4")]),
    )

    # O `ciente=False` da revisão passou: é o gate do aceite dizendo que nenhuma
    # diferença mudaria o equipamento.
    assert db_session.get(models.Circuit, circ_id) is not None
    # O diff inteiro ficou na auditoria (é ele que o `ciente` assume ou não), e
    # os contextos que a conferência compara estão todos lá — as DUAS definições
    # que a autorização produz (a prefix-list e a route-policy de importação)
    # entram uma a uma, e o `definicao` ausente seria uma conferência que não
    # chegou a comparar o corpo da política.
    evento = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "discovery.adopt")
    ).one()
    diferencas = evento.details["depois"]["diferencas"]
    assert [d["contexto"] for d in diferencas] == [
        "peer", "subinterface", "definicao", "definicao",
    ]
    assert [(d["contexto"], d["sobrando"], d["faltando"])
            for d in diferencas if d["sobrando"] or d["faltando"]] == []
    # A autorização que a conferência viu é a que a escrita gravou.
    assert [(a.prefix, a.family, a.origin) for a in _autorizacoes(db_session)] == [
        ("138.121.28.0/22", "ipv4", "registro")
    ]


def test_a_conferencia_nao_duplica_a_autorizacao_repetida(db_session, tmp_path) -> None:
    """A lista que repete o mesmo prefixo vira UMA linha, no ensaio como na escrita.

    A escrita é idempotente pela chave `(organização, família, prefixo)` com
    `admin_status` ligado: o `create_authorization` acha a linha que o primeiro
    bloco criou e devolve ela (§3.2, e a guarda existe justamente porque a lista
    da adoção pode trazer o mesmo bloco duas vezes). O ensaio inseria uma linha
    por par recebido, então a lista com o prefixo repetido renderizava o bloco
    duplicado: o ensaio emitia uma linha a mais do que a adoção grava, a
    conferência acusava `sobrando` no `definicao` e a adoção recusava o
    `ciente=False` por causa de uma linha que ela mesma não escreveria.

    Com um bloco só a cena passa, e é por isso que a duplicação passou despercebida
    até aqui: o que este teste mede é o ensaio e a escrita concordando sobre
    QUANTAS linhas a lista vira, e não só sobre os blocos chegarem.

    A repetição é NÃO ADJACENTE (`[A, B, A]`, item 15): o prefill do registro
    pode repetir um bloco com outro no meio, e o `--json` aceita qualquer ordem
    — a promessa ("vira UMA linha") não é sobre vizinhos, e com uma dedup contra
    o vizinho imediato a cena de `[A, A]` seguia verde. Aqui o estrago é maior
    que o da cena original: além da linha repetida, o bloco seguinte é
    re-indexado, e a escrita do prefixo certo passa a divergir de índice.
    """
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_COM_AUTORIZACAO_DUPLA)
    prop = _proposta(db_session, dev, vid=601)

    circ_id = adotar_proposta(
        db_session, proposta=prop, actor="cli",
        revisao=_revisao(dev, vid=601, ciente=False,
                         sessoes=[AdocaoSessaoIn(afi="ipv4")],
                         autorizacoes=[
                             AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
                             AdocaoAutorizacaoIn(prefix="198.51.100.0/24", family="ipv4"),
                             AdocaoAutorizacaoIn(prefix="138.121.28.0/22", family="ipv4"),
                         ]),
    )

    # O `ciente=False` passou: nenhuma diferença que mudaria o equipamento.
    assert db_session.get(models.Circuit, circ_id) is not None
    evento = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "discovery.adopt")
    ).one()
    diferencas = evento.details["depois"]["diferencas"]
    assert [d["contexto"] for d in diferencas] == [
        "peer", "subinterface", "definicao", "definicao",
    ]
    assert [(d["contexto"], d["sobrando"], d["faltando"])
            for d in diferencas if d["sobrando"] or d["faltando"]] == []
    # Duas linhas, e não três: o prefixo repetido não vira uma segunda linha, e o
    # que veio no meio continua sendo gravado uma vez.
    assert [(a.prefix, a.family, a.origin) for a in _autorizacoes(db_session)] == [
        ("138.121.28.0/22", "ipv4", "registro"),
        ("198.51.100.0/24", "ipv4", "registro"),
    ]


def test_a_colisao_de_nome_da_organizacao_diz_o_motivo(db_session, tmp_path) -> None:
    """A organização nova que repete um nome já cadastrado é recusada com a mesma
    frase do `create_organization` — e não com o `AVISO_SEM_ENSAIO`.

    O ensaio CRIA a organização descartável com o nome da revisão (é ele que a
    `description` da subinterface carrega) e o `flush` dele bate na unicidade do
    §14.1 ANTES de a escrita chegar lá: sem a guarda, a recusa saía como "a
    conferência não pôde ser feita", uma frase que manda o operador procurar
    reserva de VLAN e de endereço — e o dono do nome, que é a causa, ficava de
    fora do diagnóstico. Nada é gravado nos dois casos.
    """
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    dona = create_organization(db_session, OrganizationCreate(name="Cliente Alfa"), actor="cli")
    prop = _proposta(db_session, dev, vid=601)

    with pytest.raises(ConflictError) as recusa:
        adotar_proposta(db_session, proposta=prop, actor="cli",
                        revisao=_revisao(dev, vid=601, ciente=True,
                                         sessoes=[AdocaoSessaoIn(afi="ipv4")]))

    assert str(recusa.value) == "Já existe organização com o nome Cliente Alfa."
    assert db_session.scalars(select(models.Organization)).all() == [dona]
    assert db_session.query(models.Circuit).count() == 0
