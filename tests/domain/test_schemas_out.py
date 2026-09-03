import pytest
from pydantic import ValidationError

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionOut,
    BgpSessionPasswordIn,
    CircuitDetailOut,
    CircuitOut,
    ContactUpdate,
    OrganizationOut,
    PrefixAuthorizationDisable,
    SiteOut,
)


def _site() -> models.Site:
    site = models.Site(name="POP-SP", city="São Paulo", uf="SP", admin_status=True)
    site.id = 1
    return site


def _sessao() -> models.BgpSession:
    sessao = models.BgpSession(
        circuit_id=1, device_id=1, afi="ipv4",
        local_address="100.64.0.1", remote_address="100.64.0.2",
        asn_local=64600, asn_remote=64512, bfd_enabled=False,
        graceful_restart=False, shutdown=False, allow_default_route=False,
        admin_status=True,
    )
    sessao.id = 1
    return sessao


def test_site_out_serializa_a_partir_do_modelo() -> None:
    dump = SiteOut.model_validate(_site()).model_dump()
    assert dump == {
        "id": 1, "name": "POP-SP", "city": "São Paulo", "uf": "SP",
        "p2p_ipv4_block": None, "p2p_ipv6_base": None, "admin_status": True,
    }


def test_organization_out_campos_minimos() -> None:
    org = models.Organization(name="Cliente X", asn=64500, kind="downstream", admin_status=True)
    org.id = 2
    dump = OrganizationOut.model_validate(org).model_dump()
    assert dump["name"] == "Cliente X"
    assert dump["asn"] == 64500
    assert dump["kind"] == "downstream"
    assert "created_at" not in dump


def test_circuit_detail_out_pontas_default_none() -> None:
    circ = models.Circuit(
        code="CIRC-1", organization_id=1, site_id=1, access_device_id=1,
        access_port="GE0/0/1", edge_device_id=2,
        stack="dual", vlan_mode="unica", qinq=False, bfd=False,
        p2p_v4_len=31, admin_status=True,
    )
    circ.id = 3
    dump = CircuitDetailOut.model_validate(circ).model_dump()
    for campo in ("ipv4_local", "ipv4_remote", "ipv6_local", "ipv6_remote"):
        assert dump[campo] is None
    # a lista (CircuitOut) não tem as pontas
    assert "ipv4_local" not in CircuitOut.model_validate(circ).model_dump()


def test_has_password_em_bgp_session_out() -> None:
    assert BgpSessionOut.model_validate(_sessao()).model_dump()["has_password"] is False
    sessao = _sessao()
    sessao.password_ref = "gerenet/bgp-sessions/1/password"
    assert BgpSessionOut.model_validate(sessao).model_dump()["has_password"] is True
    # password_ref nunca sai no schema de saída
    assert "password_ref" not in BgpSessionOut.model_validate(sessao).model_dump()


def test_updates_tem_admin_status_opcional() -> None:
    assert ContactUpdate().admin_status is None
    assert ContactUpdate(admin_status=False).admin_status is False


def test_prefix_authorization_disable_somente_false() -> None:
    assert PrefixAuthorizationDisable(admin_status=False).admin_status is False
    with pytest.raises(ValidationError):
        PrefixAuthorizationDisable(admin_status=True)
    with pytest.raises(ValidationError):
        PrefixAuthorizationDisable(admin_status=None)
    with pytest.raises(ValidationError):
        PrefixAuthorizationDisable(admin_status=False, notas="extra")  # extra="forbid"


def test_bgp_session_password_in_limites() -> None:
    assert BgpSessionPasswordIn(password="s").password == "s"
    with pytest.raises(ValidationError):
        BgpSessionPasswordIn(password="")
    with pytest.raises(ValidationError):
        BgpSessionPasswordIn(password="x" * 129)
