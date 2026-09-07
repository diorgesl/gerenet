"""Domínios MPLS (§9.1) — serviço transacional no padrão dos demais."""
import ipaddress

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import (
    MplsDomainCreate,
    MplsDomainOut,
    MplsDomainUpdate,
    MplsMemberIn,
    MplsMemberOut,
)
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.validators import validar_vid


def _dom(session: Session, domain_id: int) -> models.MplsDomain:
    dom = session.scalars(
        select(models.MplsDomain).options(
            selectinload(models.MplsDomain.members).selectinload(models.MplsDomainMember.device),
        ).where(models.MplsDomain.id == domain_id)
        .execution_options(populate_existing=True)
    ).first()
    if dom is None:
        raise NotFoundError(f"Domínio MPLS {domain_id} não encontrado.")
    return dom


def create_domain(session: Session, data: MplsDomainCreate, *, actor: str = "cli") -> models.MplsDomain:
    nome = data.name.strip()
    if not nome:
        raise ValidationError("Nome do domínio MPLS é obrigatório.")
    ja_existe = session.scalars(
        select(models.MplsDomain.id).where(models.MplsDomain.name == nome).limit(1)
    ).first()
    if ja_existe is not None:
        raise ConflictError(f"Domínio MPLS '{nome}' já existe.")
    dom = models.MplsDomain(name=nome, description=data.description)
    session.add(dom)
    try:
        session.flush()  # define dom.id e valida unicidade antes da auditoria
        registrar(session, tipo="mpls.domain.create", ator=actor, objeto="mpls_domain",
                  objeto_id=dom.id, antes=None, depois={"name": dom.name})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Domínio MPLS '{nome}' já existe.") from exc
    return _dom(session, dom.id)


def list_domains(session: Session, include_disabled: bool = False) -> list[models.MplsDomain]:
    q = select(models.MplsDomain).options(
        selectinload(models.MplsDomain.members).selectinload(models.MplsDomainMember.device),
    ).order_by(models.MplsDomain.name).execution_options(populate_existing=True)
    if not include_disabled:
        q = q.where(models.MplsDomain.admin_status.is_(True))
    return list(session.scalars(q))


def get_domain(session: Session, domain_id: int) -> models.MplsDomain:
    return _dom(session, domain_id)


def update_domain(session: Session, domain_id: int, data: MplsDomainUpdate, *, actor: str = "cli") -> models.MplsDomain:
    dom = _dom(session, domain_id)
    antes = {"name": dom.name, "admin_status": dom.admin_status, "description": dom.description}
    novo_nome = dom.name
    if data.name is not None:
        novo_nome = data.name.strip()
        if not novo_nome:
            raise ValidationError("Nome do domínio MPLS é obrigatório.")
        if novo_nome != dom.name:
            nomes = session.scalars(
                select(models.MplsDomain.id).where(
                    models.MplsDomain.name == novo_nome, models.MplsDomain.id != dom.id,
                ).limit(1)
            ).first()
            if nomes is not None:
                raise ConflictError(f"Domínio MPLS '{novo_nome}' já existe.")
            dom.name = novo_nome
    if data.description is not None:
        dom.description = data.description
    if data.admin_status is not None:
        dom.admin_status = data.admin_status
    try:
        session.flush()
        registrar(session, tipo="mpls.domain.update", ator=actor, objeto="mpls_domain", objeto_id=dom.id,
                  antes=antes, depois={
                      "name": dom.name, "admin_status": dom.admin_status,
                      "description": dom.description,
                  })
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Domínio MPLS '{novo_nome}' já existe.") from exc
    return _dom(session, dom.id)


def add_domain_member(session: Session, domain_id: int, data: MplsMemberIn, *, actor: str = "cli") -> models.MplsDomainMember:
    dom = _dom(session, domain_id)
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe membros.")
    device = get_device(session, data.device_id)  # NotFoundError propaga
    loopback = data.loopback_address.strip()
    if not loopback:
        raise ValidationError("Loopback LDP do membro é obrigatório.")
    try:
        ipaddress.ip_address(loopback)
    except ValueError:
        raise ValidationError(f"Loopback LDP inválido: {loopback}.") from None
    ja = session.scalars(
        select(models.MplsDomainMember.id).where(
            models.MplsDomainMember.domain_id == dom.id,
            models.MplsDomainMember.device_id == device.id,
        ).limit(1)
    ).first()
    if ja is not None:
        raise ConflictError(f"Equipamento {device.name} já é membro do domínio {dom.name}.")
    membro = models.MplsDomainMember(
        domain_id=dom.id, device_id=device.id, loopback_address=loopback, role=data.role,
    )
    session.add(membro)
    try:
        session.flush()
        registrar(session, tipo="mpls.domain.member_add", ator=actor, objeto="mpls_domain",
                  objeto_id=dom.id, antes=None,
                  depois={"device_id": device.id, "loopback_address": loopback, "role": data.role})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Equipamento {device.name} já é membro do domínio {dom.name}.") from exc
    return membro


def remove_domain_member(session: Session, domain_id: int, device_id: int, *, actor: str = "cli") -> None:
    dom = _dom(session, domain_id)
    membro = session.scalars(
        select(models.MplsDomainMember).where(
            models.MplsDomainMember.domain_id == dom.id,
            models.MplsDomainMember.device_id == device_id,
        )
    ).first()
    if membro is None:
        raise NotFoundError(f"Equipamento {device_id} não é membro do domínio {dom.name}.")
    session.delete(membro)
    session.flush()
    registrar(session, tipo="mpls.domain.member_remove", ator=actor, objeto="mpls_domain",
              objeto_id=dom.id, antes={"device_id": device_id}, depois={"device_id": None})
    session.commit()


# ---- Serialização para a API (padrão dashboard.py: Out explícito) -------

def _out_membro(m: models.MplsDomainMember) -> MplsMemberOut:
    return MplsMemberOut(
        device_id=m.device_id,
        device_name=m.device.name if m.device is not None else None,
        loopback_address=m.loopback_address,
        role=m.role,
    )


def out_domain(dom: models.MplsDomain) -> MplsDomainOut:
    return MplsDomainOut(
        id=dom.id,
        name=dom.name,
        description=dom.description,
        admin_status=dom.admin_status,
        created_at=dom.created_at,
        updated_at=dom.updated_at,
        members=[_out_membro(m) for m in dom.members],
    )


# ---- IDAM simples (§4): UNIQUEs garantem; helpers dão UX ---------------

def proximo_vc_id(session: Session, domain_id: int, *, inicio: int = 100) -> int:
    """Menor VC-ID livre no domínio a partir de `inicio` (conveniência — a UNIQUE garante)."""
    ocupados = set(
        session.scalars(select(models.L2vcService.vc_id).where(models.L2vcService.domain_id == domain_id))
    )
    vc = inicio
    while vc in ocupados:
        vc += 1
    return vc


def proximo_vsi_id(session: Session, domain_id: int, *, inicio: int = 500) -> int:
    """Menor VSI-ID livre no domínio a partir de `inicio` (conveniência — a UNIQUE garante)."""
    ocupados = set(
        session.scalars(select(models.VsiService.vsi_id).where(models.VsiService.domain_id == domain_id))
    )
    vsi = inicio
    while vsi in ocupados:
        vsi += 1
    return vsi


def _primeiro_vid_device(session: Session, device_id: int) -> int:
    """Menor VID 2-4094 livre **no device** (linhas mpls_ac + circuitos do device).
    Linhas de circuito são de site — não bloqueiam o device (escopo distinto)."""
    ocupados = set(
        session.scalars(
            select(models.Vlan.vid).where(models.Vlan.device_id == device_id)
        )
    )
    for vid in range(2, 4095):
        if vid not in ocupados:
            validar_vid(vid)
            return vid
    raise ConflictError("VLANs esgotadas neste equipamento.")


def reservar_vlan_ac(session: Session, *, device_id: int, vid: int | None = None,
                     notes: str | None = None, actor: str = "cli") -> models.Vlan:
    """Reserva a VLAN de AC do endpoint (§4) — idempotente; escopo por device.

    vid None ⇒ menor livre no device (helper acima). Repetição da mesma ponta
    devolve a linha existente (no-op auditado); (device, vid) ocupado por OUTRA
    linha mpls_ac ⇒ ConflictError (índice parcial uq_vlans_device_vid).
    Equipamento sem site é rejeitado: vlans.site_id é NOT NULL e vem do device.
    """
    device = get_device(session, device_id)
    if device.site_id is None:
        raise ValidationError(
            f"Equipamento {device.name} sem site não pode reservar VLAN de AC."
        )
    ja = session.scalars(
        select(models.Vlan).where(
            models.Vlan.device_id == device.id, models.Vlan.kind == "mpls_ac",
        )
    ).all()
    if vid is not None:
        validar_vid(vid)
        existente = next((v for v in ja if v.vid == vid), None)
    else:
        vid = _primeiro_vid_device(session, device.id)
        existente = None
    if existente is not None:
        registrar(session, tipo="mpls.vlan.reserve", ator=actor, objeto="vlan",
                  objeto_id=existente.id, antes=None, depois={"repetida": True, "vid": vid})
        session.commit()
        return existente
    linha = models.Vlan(
        site_id=device.site_id, device_id=device.id, vid=vid, kind="mpls_ac",
        circuit_id=None, status="reservada", notes=notes,
    )
    session.add(linha)
    try:
        session.flush()  # UNIQUE parcial uq_vlans_device_vid valida a corrida
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"VLAN {vid} já reservada neste equipamento.") from exc
    registrar(session, tipo="mpls.vlan.reserve", ator=actor, objeto="vlan",
              objeto_id=linha.id, antes=None,
              depois={"device_id": device.id, "vid": vid, "kind": "mpls_ac"})
    session.commit()
    return linha
