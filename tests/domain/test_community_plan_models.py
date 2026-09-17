"""Modelos do plano de communities (spec §4) — o vocabulário e as quatro tabelas."""
from sqlalchemy.orm import Session

from gerenet.domain import models


def test_vocabulario_guarda_valor_codigo_e_banda(session: Session) -> None:
    com = models.Community(
        name="com-TECMAIS-v4", tipo="tag_produto", banda="cliente",
        valor_v4=3001, valor_v6=3101,
        notes="namespace XPL: com-EXPORT-UPSTREAM-v4 (61785:3001)",
    )
    session.add(com)
    session.commit()

    lido = session.get(models.Community, com.id)
    assert lido is not None
    assert (lido.valor_v4, lido.valor_v6, lido.banda) == (3001, 3101, "cliente")
    assert lido.origem == "manual"
    assert lido.origem_snapshot_id is None
    assert lido.codigo is None


def test_plano_cabecalho_com_alvos_e_portoes(session: Session) -> None:
    import json

    classe = models.Community(name="com-EXPORT-UPSTREAM-v4", tipo="tag_produto", banda="cliente", valor_v4=3001)
    session.add(classe)
    session.flush()
    plano = models.CommunityPlan(
        asn_principal=61785,
        asns_anunciados=[{"asn": 61785, "papel": "principal"}],
        origem="adotado",
        observacoes="leitura da borda",
    )
    session.add(plano)
    session.flush()
    session.add(
        models.CommunityGate(
            nome="RouteExportCheck", papel="upstream", afi="ipv4", padrao="recusar",
            aceitas=[classe.id], recusadas=[], origem="adotado",
        )
    )
    session.add(
        models.CommunityTarget(
            nome="MSD-CDN-v4", papel="cdn", codigo_v4=53062, gate_nome="RouteExportCheck",
            classe_import_id=classe.id, parametros={"tamanho_max_v4": 24}, origem="adotado",
        )
    )
    session.add(
        models.CommunityImportRule(papel="cliente", afi="ipv4", classe_id=classe.id, condicao={"tamanho_max": 24})
    )
    session.commit()

    assert plano.id is not None
    assert json.loads(json.dumps(plano.asns_anunciados))[0]["asn"] == 61785
    portao = session.query(models.CommunityGate).one()
    assert portao.aceitas == [classe.id] and portao.padrao == "recusar"
    alvo = session.query(models.CommunityTarget).one()
    assert alvo.parametros["tamanho_max_v4"] == 24
    assert session.query(models.CommunityImportRule).one().condicao["tamanho_max"] == 24
