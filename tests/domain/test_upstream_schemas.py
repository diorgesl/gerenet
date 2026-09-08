"""Schemas da fase 5 (upstreams): escopo upstream na CR e validações de campo."""

import pytest


def test_change_request_upstream_escopo_valida() -> None:
    from gerenet.domain.schemas import ChangeRequestCreate

    with pytest.raises(ValueError, match="upstream_id"):
        ChangeRequestCreate(escopo="upstream", motivo="m")
    ok = ChangeRequestCreate(escopo="upstream", upstream_id=1, motivo="m", criticidade="media")
    assert ok.upstream_id == 1


def test_upstream_create_valida_campos() -> None:
    from gerenet.domain.schemas import UpstreamCreate

    s = UpstreamCreate(name="transito-x", tipo="transito", organization_id=1)
    assert s.max_prefix_margin_pct == 20
    with pytest.raises(ValueError, match="margem"):
        UpstreamCreate(name="x", tipo="ix", organization_id=1, max_prefix_margin_pct=101)


def test_upstream_create_margem_como_string_sem_typeerror() -> None:
    """M-1 (revisão final): `max_prefix_margin_pct: "101"` (JSON string via
    API) chegava cru ao validator e `0 <= "101"` levantava TypeError — pydantic
    v2 não converte TypeError em ValidationError e virava 500."""
    from gerenet.domain.schemas import UpstreamCreate

    # string numérica dentro da faixa é aceita (coerção)
    assert UpstreamCreate(name="t1", tipo="ix", organization_id=1,
                          max_prefix_margin_pct="20").max_prefix_margin_pct == 20
    # fora da faixa: ValidationError PT-BR, nunca TypeError
    with pytest.raises(ValueError, match="margem"):
        UpstreamCreate(name="t1", tipo="ix", organization_id=1, max_prefix_margin_pct="101")
    with pytest.raises(ValueError, match="inteiro entre 0 e 100"):
        UpstreamCreate(name="t1", tipo="ix", organization_id=1, max_prefix_margin_pct="ab")


def test_upstream_update_limites_margem_e_prepend() -> None:
    """M-2 (revisão final): o Update/PATCH/CLI também valida margem 0-100 e
    prepend 0-10 (o Create já tinha; sem os limites, valores absurdos iam
    direto ao banco — design §9)."""
    from gerenet.domain.schemas import UpstreamUpdate

    with pytest.raises(ValueError, match="margem"):
        UpstreamUpdate(max_prefix_margin_pct=101)
    # string numérica no Update também passa pelo _margem (sem TypeError)
    assert UpstreamUpdate(max_prefix_margin_pct="20").max_prefix_margin_pct == 20
    with pytest.raises(ValueError, match="margem"):
        UpstreamUpdate(max_prefix_margin_pct="101")
    # limites do prepend: o Create tem 0-10; o Update agora também
    with pytest.raises(ValueError, match="contingencia_prepend"):
        UpstreamUpdate(contingencia_prepend=11)
    with pytest.raises(ValueError, match="contingencia_prepend"):
        UpstreamUpdate(contingencia_prepend=-1)
    assert UpstreamUpdate(contingencia_prepend=10).contingencia_prepend == 10
    assert UpstreamUpdate(contingencia_prepend=None).contingencia_prepend is None

