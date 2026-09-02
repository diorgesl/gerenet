import pytest
from sqlalchemy.orm import Session

from gerenet.domain.schemas import (
    CircuitCreate,
    CircuitUpdate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services.circuits import (
    create_circuit,
    disable_circuit,
    get_circuit,
    list_circuits,
    update_circuit,
)
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device


def _ambiente(db_session: Session) -> tuple[int, int, int, int, int]:
    """Site + organização + switch e 2 NE8000 vinculados; devolve os ids."""
    site = create_site(db_session, SiteCreate(name="pop-spo-01"), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="Cliente X", asn=64512), actor="cli")
    sw = create_device(db_session, DeviceCreate(name="sw1", management_address="10.0.0.2"), actor="cli")
    ne = create_device(db_session, DeviceCreate(name="ne8k", management_address="10.0.0.1"), actor="cli")
    ne8k2 = create_device(db_session, DeviceCreate(name="ne8k2", management_address="10.0.0.3"), actor="cli")
    link_device(db_session, site.id, sw.id, actor="cli")
    link_device(db_session, site.id, ne.id, actor="cli")
    link_device(db_session, site.id, ne8k2.id, actor="cli")
    return org.id, site.id, sw.id, ne.id, ne8k2.id


def _circuito(
    site_id: int, org_id: int, sw_id: int, ne_id: int, *, code: str = "CIRC-0001", **extra,
) -> CircuitCreate:
    base = {
        "code": code, "organization_id": org_id, "site_id": site_id,
        "access_device_id": sw_id, "access_port": "GE0/0/1", "edge_device_id": ne_id,
    }
    base.update(extra)
    return CircuitCreate(**base)


def test_cria_lista_e_desativa_circuito(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    circ = create_circuit(
        db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli"
    )
    assert circ.stack == "dual"
    assert [c.code for c in list_circuits(db_session)] == ["CIRC-0001"]

    disable_circuit(db_session, circ.id, actor="cli")
    assert list_circuits(db_session) == []
    assert [c.code for c in list_circuits(db_session, include_disabled=True)] == ["CIRC-0001"]


def test_circuito_code_duplicado_vira_conflito(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    create_circuit(db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli")
    with pytest.raises(ConflictError, match="CIRC-0001"):
        create_circuit(db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli")


def test_device_fora_do_site_rejeitado(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    outro_site = create_site(db_session, SiteCreate(name="pop-rj-01"), actor="cli")
    ne_fora = create_device(db_session, DeviceCreate(name="ne8k-fora", management_address="10.0.0.4"), actor="cli")
    link_device(db_session, outro_site.id, ne_fora.id, actor="cli")
    dados = _circuito(site_id, org_id, sw_id, ne_id, backup_edge_device_id=ne_fora.id)
    with pytest.raises(ValidationError, match="não pertence ao site"):
        create_circuit(db_session, dados, actor="cli")


def test_device_sem_site_rejeitado(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    solto = create_device(db_session, DeviceCreate(name="ne8k-solto", management_address="10.0.0.5"), actor="cli")
    dados = _circuito(site_id, org_id, sw_id, ne_id, backup_edge_device_id=solto.id)
    with pytest.raises(ValidationError, match="não pertence ao site"):
        create_circuit(db_session, dados, actor="cli")


def test_update_circuito_revalida_vinculos(db_session: Session) -> None:
    org_id, site_id, sw_id, ne_id, ne8k2_id = _ambiente(db_session)
    circ = create_circuit(db_session, _circuito(site_id, org_id, sw_id, ne_id), actor="cli")
    atualizado = update_circuit(
        db_session, circ.id,
        CircuitUpdate(edge_device_id=ne8k2_id, description="circuito principal"),
        actor="cli",
    )
    assert atualizado.edge_device_id == ne8k2_id
    # troca de site exige devices do novo site — os atuais ficam de fora → erro
    outro_site = create_site(db_session, SiteCreate(name="pop-rj-02"), actor="cli")
    with pytest.raises(ValidationError, match="não pertence ao site"):
        update_circuit(db_session, circ.id, CircuitUpdate(site_id=outro_site.id), actor="cli")


def test_get_circuito_inexistente(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        get_circuit(db_session, 9999)
