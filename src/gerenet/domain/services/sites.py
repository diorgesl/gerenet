from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import SiteCreate, SiteUpdate
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError
from gerenet.domain.validators import cidr_valido


def _valida_blocos(dump: dict) -> None:
    if dump.get("p2p_ipv4_block"):
        cidr_valido(dump["p2p_ipv4_block"], familia="ipv4")
    if dump.get("p2p_ipv6_base"):
        cidr_valido(dump["p2p_ipv6_base"], familia="ipv6")


def create_site(session: Session, data: SiteCreate, *, actor: str) -> models.Site:
    dump = data.model_dump()
    _valida_blocos(dump)
    site = models.Site(**dump)
    session.add(site)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(
            session, tipo="site.create", ator=actor, objeto="site", objeto_id=site.id,
            antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um site com o nome {data.name}.") from exc
    session.refresh(site)
    return site


def get_site(session: Session, site_id: int) -> models.Site:
    site = session.get(models.Site, site_id)
    if site is None:
        raise NotFoundError(f"Site {site_id} não encontrado.")
    return site


def list_sites(session: Session, include_disabled: bool = False) -> list[models.Site]:
    stmt = select(models.Site).order_by(models.Site.name)
    if not include_disabled:
        stmt = stmt.where(models.Site.admin_status.is_(True))
    return list(session.scalars(stmt))


def update_site(session: Session, site_id: int, data: SiteUpdate, *, actor: str) -> models.Site:
    site = get_site(session, site_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return site
    _valida_blocos(mudancas)
    antes = {campo: getattr(site, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(site, campo, valor)
    try:
        registrar(
            session, tipo="site.update", ator=actor, objeto="site", objeto_id=site.id,
            antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um site com o nome {mudancas.get('name')}.") from exc
    session.refresh(site)
    return site


def disable_site(session: Session, site_id: int, *, actor: str) -> models.Site:
    site = get_site(session, site_id)
    if site.admin_status is False:
        return site
    site.admin_status = False
    registrar(
        session, tipo="site.disable", ator=actor, objeto="site", objeto_id=site.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return site


def link_device(session: Session, site_id: int, device_id: int, *, actor: str) -> models.Device:
    """Vincula um device ao site (idempotente; audita a intenção)."""
    site = get_site(session, site_id)
    dev = get_device(session, device_id)
    antes = {"site_id": dev.site_id}
    dev.site_id = site.id
    registrar(
        session, tipo="site.link_device", ator=actor, objeto="site", objeto_id=site.id,
        antes=antes, depois={"site_id": dev.site_id},
    )
    session.commit()
    session.refresh(dev)
    return dev
