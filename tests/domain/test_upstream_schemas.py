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
