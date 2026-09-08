"""Autorizações de prefixo com origem IRR/RPKI e revalidação consultiva (§6.4/§10.4, F5 E3).

Criação com `origin` (teste de schema na prática, pelo serviço), o padrão
`manual` + `validacao is None`, e a revalidação de `revalidar_autorizacoes`
nos dois ramos (rpki via `validar_origem` real contra ROAs da SoT; irr via
`consultar` monkeypatchado — o serviço importa o nome real no módulo).
Molde: `tests/domain/test_prefix_authorizations_service.py`. Fixture
`db_session` do conftest (banco truncado a cada teste)."""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation.irr import IrrError
from gerenet.domain import models
from gerenet.domain.schemas import OrganizationCreate, PrefixAuthorizationCreate
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.prefix_authorizations import (
    create_authorization,
    disable_authorization,
    revalidar_autorizacoes,
)


def _org(db_session: Session, nome: str, asn: int | None = None) -> int:
    return create_organization(
        db_session, OrganizationCreate(name=nome, asn=asn), actor="cli"
    ).id


def _auth(
    db_session: Session, org_id: int, prefix: str, *, origin: str | None = None
) -> models.BgpPrefixAuthorization:
    """Cria com `origin` quando informado; sem ele vale o default do schema."""
    dados: dict = {"organization_id": org_id, "family": "ipv4", "prefix": prefix}
    if origin is not None:
        dados["origin"] = origin
    return create_authorization(
        db_session, PrefixAuthorizationCreate(**dados), actor="cli"
    )


def _por_prefixo(db_session: Session) -> dict[str, models.BgpPrefixAuthorization]:
    return {
        auth.prefix: auth
        for auth in db_session.scalars(select(models.BgpPrefixAuthorization)).all()
    }


def test_create_origin_irr_rpki_validacao_nao_verificada(db_session: Session) -> None:
    """Origem irr/rpki ⇒ a validação consultiva nasce `nao_verificada` (§10.4)."""
    org_irr = _org(db_session, "Cliente IRR", 64512)
    auth_irr = _auth(db_session, org_irr, "200.160.0.0/22", origin="irr")
    assert auth_irr.origin == "irr"
    assert auth_irr.validacao == "nao_verificada"

    org_rpki = _org(db_session, "Cliente RPKI", 64513)
    auth_rpki = _auth(db_session, org_rpki, "200.161.0.0/22", origin="rpki")
    assert auth_rpki.origin == "rpki"
    assert auth_rpki.validacao == "nao_verificada"


def test_create_sem_origin_default_manual_sem_validacao(db_session: Session) -> None:
    """Default do schema: origem manual, `validacao` fica `None` (sem validação)."""
    org_id = _org(db_session, "Cliente Manual", 64514)
    auth = _auth(db_session, org_id, "200.162.0.0/22")
    assert auth.origin == "manual"
    assert auth.validacao is None


def test_create_org_operadora_recusada(db_session: Session) -> None:
    """Design §3/§10.1 (G2/I-4): operadora não recebe autorização de prefixo —
    a autorização seria criada e depois apenas ignorada pelo render."""
    from gerenet.domain.services.errors import ValidationError
    from gerenet.domain.services.organizations import create_organization

    org_id = create_organization(
        db_session, OrganizationCreate(name="Operadora F5", asn=64512, kind="operadora"),
        actor="cli",
    ).id
    with pytest.raises(
        ValidationError, match="operadora não recebe autorizações de prefixo"
    ):
        create_authorization(
            db_session,
            PrefixAuthorizationCreate(
                organization_id=org_id, family="ipv4", prefix="180.10.0.0/16"
            ),
            actor="cli",
        )
    # autorização de downstream na mesma organização continua criando
    downstream_id = create_organization(
        db_session, OrganizationCreate(name="Cliente Pós-Guarda", asn=64515, kind="downstream"),
        actor="cli",
    ).id
    assert create_authorization(
        db_session,
        PrefixAuthorizationCreate(
            organization_id=downstream_id, family="ipv4", prefix="180.11.0.0/16"
        ),
        actor="cli",
    ).prefix == "180.11.0.0/16"


def test_revalida_rpki_ok_com_roa_cobrindo(db_session: Session) -> None:
    """ROA cobre o prefixo com o ASN da organização ⇒ `ok` (validação real)."""
    org_id = _org(db_session, "Cliente ROA Ok", 64512)
    _auth(db_session, org_id, "180.10.0.0/16", origin="rpki")
    db_session.add(
        models.Roa(
            prefix="180.10.0.0/16", origin_asn=64512, max_length=24,
            source="rpki-client",
        )
    )
    db_session.commit()

    assert revalidar_autorizacoes(db_session) == 1
    assert _por_prefixo(db_session)["180.10.0.0/16"].validacao == "ok"


def test_revalida_rpki_sem_roa_desconhecida(db_session: Session) -> None:
    """Nenhuma ROA cobre o prefixo ⇒ `desconhecida`."""
    org_id = _org(db_session, "Cliente ROA Desconhecida", 64512)
    _auth(db_session, org_id, "203.0.113.0/24", origin="rpki")

    assert revalidar_autorizacoes(db_session) == 1
    assert _por_prefixo(db_session)["203.0.113.0/24"].validacao == "desconhecida"


def test_revalida_irr_ok_e_diverge(db_session: Session, monkeypatch) -> None:
    """IRR: prefixo no payload ⇒ `ok`; ausente ⇒ `diverge` (um lote, dois
    resultados; o ASN chega ao consultar como string de dígitos). m-1
    (revisão T23): as duas autorizações são da MESMA org — uma só consulta
    IRR por ASN no lote (memo), não uma por autorização."""
    org_id = _org(db_session, "Cliente IRR", 64512)
    _auth(db_session, org_id, "200.160.0.0/22", origin="irr")
    _auth(db_session, org_id, "200.170.0.0/22", origin="irr")

    chamadas: list[tuple[str, str]] = []

    def fake_consultar(source: str, key: str, *, ttl_horas: int = 24) -> dict:
        chamadas.append((source, key))
        return {"asns": [64512], "prefixos": ["200.160.0.0/22"]}

    monkeypatch.setattr(
        "gerenet.domain.services.prefix_authorizations.consultar", fake_consultar
    )
    assert revalidar_autorizacoes(db_session) == 2
    assert chamadas == [("radb", "64512")]

    por_prefixo = _por_prefixo(db_session)
    assert por_prefixo["200.160.0.0/22"].validacao == "ok"
    assert por_prefixo["200.170.0.0/22"].validacao == "diverge"


def test_revalida_falha_irr_mantem_validacao(db_session: Session, monkeypatch) -> None:
    """IrrError (rede fora sem cache vivo) ⇒ fail-soft: mantém a `validacao`
    atual e não conta como revalidada (§10.4)."""
    org_id = _org(db_session, "Cliente IRR Falha", 64512)
    _auth(db_session, org_id, "200.160.0.0/22", origin="irr")

    def falha(*_args, **_kwargs) -> dict:
        raise IrrError("Consulta IRR '64512' (source radb) falhou e não há cache vivo.")

    monkeypatch.setattr(
        "gerenet.domain.services.prefix_authorizations.consultar", falha
    )
    assert revalidar_autorizacoes(db_session) == 0
    assert _por_prefixo(db_session)["200.160.0.0/22"].validacao == "nao_verificada"


def test_revalida_ignora_desativada(db_session: Session) -> None:
    """Autorização desativada não é revalidada (nem contada)."""
    org_id = _org(db_session, "Cliente Desativada", 64512)
    auth = _auth(db_session, org_id, "200.160.0.0/22", origin="rpki")
    disable_authorization(db_session, auth.id, actor="cli")

    assert revalidar_autorizacoes(db_session) == 0
    assert _por_prefixo(db_session)["200.160.0.0/22"].validacao == "nao_verificada"


def test_revalida_nao_toca_manual(db_session: Session) -> None:
    """Origem manual fica intocada: `validacao is None` e não contada."""
    org_id = _org(db_session, "Cliente Manual", 64512)
    _auth(db_session, org_id, "200.160.0.0/22")

    assert revalidar_autorizacoes(db_session) == 0
    auth = _por_prefixo(db_session)["200.160.0.0/22"]
    assert auth.origin == "manual"
    assert auth.validacao is None


def test_revalida_org_sem_asn_mantem_e_nao_conta(db_session: Session, monkeypatch) -> None:
    """Organização sem ASN ⇒ log.warning, `validacao` mantida e não contada —
    nenhuma validação externa é disparada."""
    org_id = _org(db_session, "Cliente Sem ASN", None)
    _auth(db_session, org_id, "200.160.0.0/22", origin="rpki")

    def explodir(*_args, **_kwargs):
        raise AssertionError("sem ASN não pode disparar validação externa")

    monkeypatch.setattr(
        "gerenet.domain.services.prefix_authorizations.consultar", explodir
    )
    # revisão final I-1: o lote reusa o índice (avaliar_origem) — o guard de
    # sem-ASN precede tanto o índice quanto a avaliação.
    monkeypatch.setattr(
        "gerenet.domain.services.prefix_authorizations.indice_roas", explodir
    )
    monkeypatch.setattr(
        "gerenet.domain.services.prefix_authorizations.avaliar_origem", explodir
    )

    assert revalidar_autorizacoes(db_session) == 0
    assert _por_prefixo(db_session)["200.160.0.0/22"].validacao == "nao_verificada"


def test_revalida_rpki_indice_carregado_uma_vez_por_lote(
    db_session: Session, monkeypatch
) -> None:
    """I-1 (revisão final T22 C1): o índice de ROAs é carregado UMA vez por
    lote — não por autorização (com o lote real do rpki-client ~400 mil ROAs,
    O(M×N) degenerava o `rpki sync`)."""
    org_ok = _org(db_session, "Cliente Índice Ok", 64512)
    _auth(db_session, org_ok, "200.160.0.0/22", origin="rpki")
    org_sem = _org(db_session, "Cliente Índice Sem ROA", 64513)
    _auth(db_session, org_sem, "200.161.0.0/22", origin="rpki")
    org_div = _org(db_session, "Cliente Índice Diverge", 64514)
    _auth(db_session, org_div, "200.163.0.0/23", origin="rpki")
    db_session.add_all([
        models.Roa(prefix="200.160.0.0/22", origin_asn=64512, max_length=24,
                   source="rpki-client"),
        models.Roa(prefix="200.163.0.0/23", origin_asn=64513, max_length=24,
                   source="rpki-client"),
    ])
    db_session.commit()

    chamadas: list[int] = []

    def conta_indice(session):
        chamadas.append(1)
        from gerenet.automation.rpki import indice_roas as real
        return real(session)

    monkeypatch.setattr(
        "gerenet.domain.services.prefix_authorizations.indice_roas", conta_indice
    )
    assert revalidar_autorizacoes(db_session) == 3
    assert chamadas == [1]

    por_prefixo = _por_prefixo(db_session)
    assert por_prefixo["200.160.0.0/22"].validacao == "ok"
    assert por_prefixo["200.161.0.0/22"].validacao == "desconhecida"
    assert por_prefixo["200.163.0.0/23"].validacao == "diverge"  # ASN 64514 ≠ ROA 64513
