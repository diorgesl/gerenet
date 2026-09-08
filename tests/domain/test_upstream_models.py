"""Modelos da fase 5 (§3 do design) — defaults e unicidades."""
import pytest
from sqlalchemy.exc import IntegrityError

from gerenet.domain import models


def test_upstream_defaults_e_unicidade(session, org_operadora):
    up = models.Upstream(name="transito-acme", tipo="transito",
                         organization_id=org_operadora.id,
                         expected_prefixes_v4=900000, expected_prefixes_v6=300000)
    session.add(up)
    session.commit()
    assert up.max_prefix_margin_pct == 20
    assert up.rpki_enabled is True


def test_org_kind_operadora_disponivel(session):
    assert "operadora" in models.ORG_KIND
    assert models.AUTH_ORIGIN == ("manual", "irr", "rpki")
    assert models.CHANGE_ESCOPO == ("circuito", "l2vc", "vsi", "upstream")
    assert "none" in models.VLAN_MODE


def test_unicidade_upstream_circuit(session, org_operadora, circuito_up, up):
    session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=circuito_up.id))
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(models.UpstreamCircuit(upstream_id=up.id, circuit_id=circuito_up.id))
        session.commit()
    session.rollback()  # integridade da sessão pós-IntegrityError (padrão test_mpls_models:90)


def test_roa_unicidade(session):
    session.add(models.Roa(prefix="180.10.0.0/16", origin_asn=64512, max_length=24))
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(models.Roa(prefix="180.10.0.0/16", origin_asn=64512, max_length=24))
        session.commit()
    session.rollback()  # integridade da sessão pós-IntegrityError (padrão test_mpls_models:90)
