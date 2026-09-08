"""Sincronização de ROAs do rpki-client e validação consultiva de origem (§7.5).

Parse do arquivo inteiro antes do banco (JSON inválido não deixa rastros),
upsert idempotente por (prefix, origin_asn, max_length), remoção de órfãs do
source e preservação de outras sources; `validar_origem` nos três resultados
(ok/diverge/desconhecida) com a semântica RPKI do maxLength. Molde:
`tests/automation/test_irr.py` — fixture `session` do conftest (banco
truncado a cada teste)."""
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from gerenet.automation.rpki import sincronizar_roas, validar_origem
from gerenet.domain import models

ROA_V4_A = {  # maxLength autoriza more-specifics até /24
    "prefix": "180.10.0.0/16",
    "maxLength": 24,
    "asn": "AS64512",
    "validUntil": "2026-09-09T00:00:00Z",
}
ROA_V4_B = {"prefix": "180.20.0.0/16", "asn": 64513}  # sem maxLength/validUntil
ROA_V6_C = {  # extra: família IPv6, o par de A
    "prefix": "2001:db8:1::/48",
    "maxLength": 48,
    "asn": "AS64512",
    "validUntil": "2026-09-09T00:00:00Z",
}


def _escreve(caminho, roas: list[dict]) -> None:
    caminho.write_text(
        json.dumps({"roas": roas, "metadata": {"generated": "2026-09-08"}}),
        encoding="utf-8",
    )


def _por_prefixo(session, source: str = "rpki-client") -> dict[str, models.Roa]:
    linhas = session.scalars(
        select(models.Roa).where(models.Roa.source == source)
    ).all()
    return {linha.prefix: linha for linha in linhas}


def test_sincronizar_roas_idempotente_remove_orfas_e_preserva_outras_sources(
    session, tmp_path
):
    """Lote inicial de 3 ROAs → sync; mesma 2ª sync não duplica; lote seguinte
    (1 órfã) remove só a órfã, renova a existente e preserva a linha manual."""
    session.add(
        models.Roa(
            prefix="203.0.113.0/24",
            origin_asn=64599,
            max_length=24,
            source="manual",
        )
    )
    session.commit()
    arquivo = tmp_path / "roas.json"

    _escreve(arquivo, [ROA_V4_A, ROA_V4_B, ROA_V6_C])
    assert sincronizar_roas(session, str(arquivo)) == 3

    por_prefixo = _por_prefixo(session)
    assert set(por_prefixo) == {"180.10.0.0/16", "180.20.0.0/16", "2001:db8:1::/48"}
    # asn "AS64512" (string) e 64513 (int) normalizam para int; maxLength
    # ausente → null; validUntil vira datetime tz-aware (UTC)
    assert por_prefixo["180.10.0.0/16"].origin_asn == 64512
    assert por_prefixo["180.10.0.0/16"].max_length == 24
    assert por_prefixo["180.10.0.0/16"].valid_until == datetime(
        2026, 9, 9, 0, 0, tzinfo=UTC
    )
    assert por_prefixo["180.20.0.0/16"].origin_asn == 64513
    assert por_prefixo["180.20.0.0/16"].max_length is None
    assert por_prefixo["180.20.0.0/16"].valid_until is None
    assert por_prefixo["2001:db8:1::/48"].origin_asn == 64512

    # 2ª sync com o mesmo arquivo: idempotente (mesmo retorno e sem duplicar)
    assert sincronizar_roas(session, str(arquivo)) == 3
    assert len(_por_prefixo(session)) == 3

    # lote seguinte: renova o validUntil de A e deixa B (180.20.0.0/16) órfã
    _escreve(
        arquivo,
        [
            {**ROA_V4_A, "validUntil": "2026-10-01T00:00:00Z"},
            ROA_V6_C,
        ],
    )
    assert sincronizar_roas(session, str(arquivo)) == 2

    por_prefixo = _por_prefixo(session)
    assert set(por_prefixo) == {"180.10.0.0/16", "2001:db8:1::/48"}  # órfã removida
    assert por_prefixo["180.10.0.0/16"].valid_until == datetime(
        2026, 10, 1, 0, 0, tzinfo=UTC
    )
    # linha de outra source permanece intacta
    manual = session.scalars(
        select(models.Roa).where(models.Roa.source == "manual")
    ).one()
    assert (manual.prefix, manual.origin_asn, manual.max_length) == (
        "203.0.113.0/24",
        64599,
        24,
    )


def test_sincronizar_roas_lote_vazio_remove_tudo_do_source(session, tmp_path):
    """Sincronizar um lote vazio espelha o arquivo: remove as ROAs do source,
    preserva as demais (controle E2-2 — o arquivo é a fonte para `rpki-client`)."""
    session.add(
        models.Roa(
            prefix="180.10.0.0/16", origin_asn=64512, max_length=24,
            source="rpki-client",
        )
    )
    session.commit()
    arquivo = tmp_path / "roas.json"
    _escreve(arquivo, [])

    assert sincronizar_roas(session, str(arquivo)) == 0
    assert _por_prefixo(session) == {}


def test_sincronizar_roas_lote_com_duplicata_nao_quebra_ou_duplica(
    session, tmp_path
):
    """m-2 (revisão T22): ROA repetida no mesmo lote (mesma chave) era
    IntegrityError no commit — o dedup preserva a 1ª ocorrência e a sync conta
    as ROAs únicas."""
    arquivo = tmp_path / "roas.json"
    _escreve(arquivo, [ROA_V4_A, ROA_V4_A, ROA_V6_C])

    assert sincronizar_roas(session, str(arquivo)) == 2
    assert len(_por_prefixo(session)) == 2


def test_json_invalido_levanta_valor_error_sem_tocar_o_banco(session, tmp_path):
    """JSON malformado ⇒ ValueError com mensagem PT-BR e nenhuma escrita."""
    arquivo = tmp_path / "roas.json"
    arquivo.write_text('{"roas": [{"prefix": "180.10.0.0/16",}', encoding="utf-8")

    with pytest.raises(ValueError, match="JSON malformado"):
        sincronizar_roas(session, str(arquivo))

    assert session.scalars(select(models.Roa)).all() == []


def test_asn_string_e_int_normalizam_para_o_mesmo_valor(session, tmp_path):
    """Fato do controller: `asn` do rpki-client é string "AS8365" (aceita int
    também); ambos normalizam para 8365 — e validUntil ausente ⇒ None."""
    arquivo = tmp_path / "roas.json"
    _escreve(
        arquivo,
        [
            {"prefix": "180.10.0.0/16", "maxLength": 24, "asn": "AS8365"},
            {"prefix": "180.20.0.0/16", "maxLength": 24, "asn": 8365},
        ],
    )

    assert sincronizar_roas(session, str(arquivo)) == 2

    por_prefixo = _por_prefixo(session)
    assert {p: l.origin_asn for p, l in por_prefixo.items()} == {
        "180.10.0.0/16": 8365,
        "180.20.0.0/16": 8365,
    }
    assert all(l.valid_until is None for l in por_prefixo.values())


def _seeda_roas(session) -> None:
    session.add_all(
        [
            models.Roa(
                prefix="180.10.0.0/16", origin_asn=64512, max_length=24,
                source="rpki-client",
            ),
            models.Roa(
                prefix="180.20.0.0/16", origin_asn=64513,
                source="rpki-client",  # sem maxLength: limite = o próprio /16
            ),
        ]
    )
    session.commit()


def test_validar_origem_ok_exato(session):
    """Prefixo exatamente igual a uma ROA com o ASN correto ⇒ ok (mesmo com
    maxLength presente: /16 ≤ /24)."""
    _seeda_roas(session)

    assert validar_origem(session, "180.10.0.0/16", 64512) == "ok"
    assert validar_origem(session, "180.20.0.0/16", 64513) == "ok"  # sem maxLength


def test_validar_origem_ok_more_specific_dentro_do_maxlength(session):
    """Semântica RPKI: mais específico que o prefixo da ROA é ok até maxLength."""
    _seeda_roas(session)

    assert validar_origem(session, "180.10.5.0/24", 64512) == "ok"


def test_validar_origem_diverge_asn_errado(session):
    """ROA cobre mas anuncia outro ASN ⇒ diverge."""
    _seeda_roas(session)

    assert validar_origem(session, "180.10.0.0/16", 99999) == "diverge"
    assert validar_origem(session, "180.10.5.0/24", 99999) == "diverge"


def test_validar_origem_diverge_comprimento_acima_do_maxlength(session):
    """Mais específico que o maxLength (mesmo com ASN da ROA) ⇒ diverge;
    sem maxLength, mais específico diverge também (limite = o próprio ROA)."""
    _seeda_roas(session)

    assert validar_origem(session, "180.10.5.0/25", 64512) == "diverge"  # 25 > 24
    assert validar_origem(session, "180.20.0.0/24", 64513) == "diverge"  # 24 > 16


def test_validar_origem_desconhecida_sem_roa_cobrindo(session):
    """Nenhuma ROA cobre o prefixo ⇒ desconhecida (e famílias diferentes não
    lançam TypeError — versão do alvo vs. ROA)."""
    _seeda_roas(session)

    assert validar_origem(session, "203.0.113.0/24", 64512) == "desconhecida"
    assert validar_origem(session, "2001:db8:1::/48", 64512) == "desconhecida"


def test_validar_origem_prefixo_invalido_levanta_valor_error(session):
    """Prefixo que não parseia ⇒ ValueError com mensagem PT-BR."""
    _seeda_roas(session)

    with pytest.raises(ValueError, match="prefixo inválido"):
        validar_origem(session, "não-é-prefixo", 64512)
    with pytest.raises(ValueError, match="ASN inválido"):
        validar_origem(session, "180.10.0.0/16", "AS-errado")


def test_sincronizar_roas_revalida_autorizacoes_rpki(session, tmp_path):
    """E3 (hook): após o commit do lote, as autorizações ativas de origem
    IRR/RPKI são revalidadas — a autorização rpki saiu de `nao_verificada`
    para o resultado da validação (consultivo §10.4; import diferido no
    `sincronizar_roas` quebra o ciclo com o serviço)."""
    from gerenet.domain.schemas import OrganizationCreate, PrefixAuthorizationCreate
    from gerenet.domain.services.organizations import create_organization
    from gerenet.domain.services.prefix_authorizations import create_authorization

    org = create_organization(
        session, OrganizationCreate(name="Cliente ROA Sync", asn=64512), actor="cli"
    )
    auth = create_authorization(
        session,
        PrefixAuthorizationCreate(
            organization_id=org.id,
            family="ipv4",
            prefix="180.10.0.0/16",
            origin="rpki",
        ),
        actor="cli",
    )
    assert auth.validacao == "nao_verificada"

    arquivo = tmp_path / "roas.json"
    _escreve(arquivo, [ROA_V4_A])  # AS64512 cobre 180.10.0.0/16 (maxLength /24)

    assert sincronizar_roas(session, str(arquivo)) == 1

    session.refresh(auth)
    assert auth.validacao == "ok"
