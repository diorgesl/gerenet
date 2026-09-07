"""Domínios MPLS (§9.1) — serviço transacional no padrão dos demais."""
import ipaddress

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import (
    L2vcCreate,
    L2vcOut,
    MplsDomainCreate,
    MplsDomainOut,
    MplsDomainUpdate,
    MplsMemberIn,
    MplsMemberOut,
    ServiceEndpointOut,
    VsiCreate,
    VsiMemberOut,
    VsiOut,
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

    vid None ⇒ menor VID livre no device (helper acima). Repetição da mesma
    ponta com vid explícito devolve a linha existente (no-op auditado);
    (device, vid) ocupado por OUTRA linha mpls_ac ⇒ ConflictError (índice
    parcial uq_vlans_device_vid). Equipamento sem site é rejeitado:
    vlans.site_id é NOT NULL e vem do device. A idempotência vale para vid
    explícito; com vid=None cada chamada aloca o menor VID livre no device
    daquele momento, sem re-idempotência. Os consumidores (T4/T5) chamam com
    o vid da ponta quando o têm.

    A função NÃO commita: o chamador fecha a transação (o visitante do
    create_l2vc precisa de atomicidade — o flush das duas pontas falha junto
    ou não falha nada).
    """
    device = get_device(session, device_id)
    if device.site_id is None:
        raise ValidationError(
            f"Equipamento {device.name} sem site não pode reservar VLAN de AC."
        )
    if vid is not None:
        validar_vid(vid)
        ja = session.scalars(
            select(models.Vlan).where(
                models.Vlan.device_id == device.id, models.Vlan.kind == "mpls_ac",
            )
        ).all()
        existente = next((v for v in ja if v.vid == vid), None)
    else:
        vid = _primeiro_vid_device(session, device.id)
        existente = None
    if existente is not None:
        registrar(session, tipo="mpls.vlan.reserve", ator=actor, objeto="vlan",
                  objeto_id=existente.id, antes=None, depois={"repetida": True, "vid": vid})
        session.flush()
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
    session.flush()
    return linha


# ---- Serviços L2VC (§9.2) ---------------------------------------------------

def _l2vc(session: Session, l2vc_id: int) -> models.L2vcService:
    svc = session.scalars(
        select(models.L2vcService)
        .options(
            selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.vlan),
            selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.device),
            selectinload(models.L2vcService.domain),
        )
        .where(models.L2vcService.id == l2vc_id)
        .execution_options(populate_existing=True)
    ).first()
    if svc is None:
        raise NotFoundError(f"Serviço L2VC {l2vc_id} não encontrado.")
    return svc


def _membro_loopback(session: Session, domain_id: int, device_id: int) -> str | None:
    linha = session.scalars(
        select(models.MplsDomainMember.loopback_address).where(
            models.MplsDomainMember.domain_id == domain_id,
            models.MplsDomainMember.device_id == device_id,
        ).limit(1)
    ).first()
    return linha


def create_l2vc(session: Session, data: L2vcCreate, *, actor: str = "cli") -> models.L2vcService:
    dom = _dom(session, data.domain_id)  # NotFound/desativado? _dom não checa status — checar abaixo
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe serviços.")

    a, b = data.endpoints
    if a.device_id == b.device_id:
        raise ValidationError("As duas pontas do L2VC devem ser equipamentos distintos.")
    if a.encapsulation != b.encapsulation:
        raise ValidationError("Encapsulamento das pontas deve ser simétrico (ambas dot1q ou ambas qinq).")
    mtu_a = a.mtu or data.mtu
    mtu_b = b.mtu or data.mtu
    if mtu_a != mtu_b:
        raise ValidationError(f"MTU das pontas diverge ({mtu_a} × {mtu_b}); ajuste o MTU do serviço ou das pontas.")
    for ep in (a, b):
        if not ep.interface.strip():
            raise ValidationError(f"Ponta {ep.device_id}: interface é obrigatória.")
        if ep.interface.upper().startswith("VLANIF"):
            numero = ep.interface[6:].strip()
            if not numero.isdigit() or int(numero) != ep.vid:
                raise ValidationError(
                    f"Ponta {ep.interface}: AC em Vlanif precisa terminar o vid reservado "
                    f"(Vlanif{ep.vid})."
                )
            if ep.encapsulation == "qinq":
                raise ValidationError(
                    f"Ponta {ep.interface}: Vlanif não suporta QinQ — use subinterface."
                )
        if ep.encapsulation == "qinq" and ep.inner_vlan is None:
            raise ValidationError(f"Ponta {ep.interface}: encapsulamento qinq exige inner-vlan.")
        if _membro_loopback(session, dom.id, ep.device_id) is None:
            raise ValidationError(f"Equipamento {ep.device_id} sem loopback LDP no domínio (membro inexistente).")
    if data.redundancy not in (None, "none", "single", "dual"):
        raise ValidationError(f"Redundância inválida: {data.redundancy} (use none/single/dual).")

    vc_id = data.vc_id or proximo_vc_id(session, dom.id)
    nome = data.name.strip()
    if not nome:
        raise ValidationError("Nome do serviço L2VC é obrigatório.")
    qtd = session.scalars(
        select(models.L2vcService.id).where(
            models.L2vcService.domain_id == dom.id,
            models.L2vcService.name == nome,
        ).limit(1)
    ).first()
    if qtd is not None:
        raise ConflictError(f"Serviço L2VC '{nome}' já existe no domínio {dom.name}.")
    duplicado = session.scalars(
        select(models.L2vcService.id).where(
            models.L2vcService.domain_id == dom.id, models.L2vcService.vc_id == vc_id,
        ).limit(1)
    ).first()
    if duplicado is not None:
        raise ConflictError(f"VC-ID {vc_id} já usado no domínio {dom.name}.")

    svc = models.L2vcService(
        domain_id=dom.id, vc_id=vc_id, name=nome, organization_id=data.organization_id,
        mtu=data.mtu, control_word=data.control_word, flow_label=data.flow_label,
        redundancy=data.redundancy, description=data.description,
    )
    session.add(svc)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Nome ou VC-ID já em uso no domínio {dom.name}.") from exc
    for ep in (a, b):
        vlan = reservar_vlan_ac(session, device_id=ep.device_id, vid=ep.vid, actor=actor)
        # Idempotência do helper só serve ao re-run do MESMO serviço: VLAN
        # de outro service_endpoint bloqueia (a ponta não pode ser compartilhada).
        dono = session.scalars(
            select(models.ServiceEndpoint.l2vc_id).where(
                models.ServiceEndpoint.vlan_id == vlan.id,
                models.ServiceEndpoint.l2vc_id != svc.id,
            ).limit(1)
        ).first()
        if dono is not None:
            session.rollback()
            raise ConflictError(f"VLAN {vlan.vid} já pertence ao serviço L2VC {dono}.")
        session.add(models.ServiceEndpoint(
            kind="l2vc", l2vc_id=svc.id, device_id=ep.device_id, interface=ep.interface.strip(),
            encapsulation=ep.encapsulation, vlan_id=vlan.id, inner_vlan=ep.inner_vlan,
            mtu=ep.mtu or data.mtu,
        ))
    session.flush()
    registrar(session, tipo="mpls.l2vc.create", ator=actor, objeto="l2vc", objeto_id=svc.id,
              antes=None, depois={"vc_id": vc_id, "name": nome, "domain_id": dom.id})
    session.commit()
    return _l2vc(session, svc.id)


def list_l2vc(session: Session, domain_id: int | None = None, include_disabled: bool = False) -> list[models.L2vcService]:
    q = select(models.L2vcService).options(
        selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.vlan),
        selectinload(models.L2vcService.endpoints).selectinload(models.ServiceEndpoint.device),
        selectinload(models.L2vcService.domain),
    ).order_by(models.L2vcService.domain_id, models.L2vcService.vc_id).execution_options(populate_existing=True)
    if domain_id is not None:
        q = q.where(models.L2vcService.domain_id == domain_id)
    if not include_disabled:
        q = q.where(models.L2vcService.admin_status.is_(True))
    return list(session.scalars(q))


def get_l2vc(session: Session, l2vc_id: int) -> models.L2vcService:
    return _l2vc(session, l2vc_id)


def set_l2vc_status(session: Session, l2vc_id: int, *, admin_status: bool, actor: str = "cli") -> models.L2vcService:
    svc = _l2vc(session, l2vc_id)
    antes, svc.admin_status = svc.admin_status, admin_status
    session.flush()
    registrar(session, tipo="mpls.l2vc.status", ator=actor, objeto="l2vc", objeto_id=svc.id,
              antes={"admin_status": antes}, depois={"admin_status": admin_status})
    session.commit()
    return _l2vc(session, svc.id)


# ---- Serialização L2VC (padrão dashboard.py: Out explícito) ----------------

def _out_endpoint(ep: models.ServiceEndpoint) -> ServiceEndpointOut:
    return ServiceEndpointOut(
        id=ep.id,
        kind=ep.kind,
        device_id=ep.device_id,
        device_name=ep.device.name if ep.device is not None else None,
        interface=ep.interface,
        encapsulation=ep.encapsulation,
        vlan_id=ep.vlan_id,
        vid=ep.vlan.vid if ep.vlan is not None else None,
        inner_vlan=ep.inner_vlan,
        mtu=ep.mtu,
        operational_status=ep.operational_status,
    )


def out_l2vc(svc: models.L2vcService) -> L2vcOut:
    return L2vcOut(
        id=svc.id,
        domain_id=svc.domain_id,
        vc_id=svc.vc_id,
        name=svc.name,
        organization_id=svc.organization_id,
        mtu=svc.mtu,
        control_word=svc.control_word,
        flow_label=svc.flow_label,
        redundancy=svc.redundancy,
        description=svc.description,
        admin_status=svc.admin_status,
        operational_status=svc.operational_status,
        last_collected_at=svc.last_collected_at,
        created_at=svc.created_at,
        endpoints=[_out_endpoint(e) for e in svc.endpoints],
        domain_name=svc.domain.name if svc.domain is not None else None,
    )


# ---- Serviços VSI (§9.3: modelo + consulta; sem render/CR neste ciclo) --

def _vsi(session: Session, vsi_id: int) -> models.VsiService:
    svc = session.scalars(
        select(models.VsiService)
        .options(
            selectinload(models.VsiService.members).selectinload(models.VsiMember.device),
            selectinload(models.VsiService.domain),
        )
        .where(models.VsiService.id == vsi_id)
        .execution_options(populate_existing=True)
    ).first()
    if svc is None:
        raise NotFoundError(f"VSI {vsi_id} não encontrado.")
    return svc


def create_vsi(session: Session, data: VsiCreate, *, actor: str = "cli") -> models.VsiService:
    from gerenet.automation.naming import vsi_nome
    dom = _dom(session, data.domain_id)
    if not dom.admin_status:
        raise ConflictError(f"Domínio MPLS {dom.name} desativado não recebe serviços.")
    vsi_id = data.vsi_id or proximo_vsi_id(session, dom.id)
    nome = data.name.strip()
    if not nome:
        raise ValidationError("Nome do VSI é obrigatório.")
    ja_nome = session.scalars(
        select(models.VsiService.id).where(
            models.VsiService.domain_id == dom.id, models.VsiService.name == nome,
        ).limit(1)
    ).first()
    if ja_nome is not None:
        raise ConflictError(f"VSI '{nome}' já existe no domínio {dom.name}.")
    ja_id = session.scalars(
        select(models.VsiService.id).where(
            models.VsiService.domain_id == dom.id, models.VsiService.vsi_id == vsi_id,
        ).limit(1)
    ).first()
    if ja_id is not None:
        raise ConflictError(f"VSI-ID {vsi_id} já usado no domínio {dom.name}.")
    vrp = vsi_nome(nome, vsi_id)
    # Defensivo — redundante com (domain_id, vsi_id): mesma sigla + mesmo ID
    # já colide no pre-check/acima e no UNIQUE; siglas iguais com IDs distintos
    # geram vrps distintos.
    ja_vrp = session.scalars(
        select(models.VsiService.id).where(
            models.VsiService.domain_id == dom.id, models.VsiService.vrp_name == vrp,
        ).limit(1)
    ).first()
    if ja_vrp is not None:
        raise ConflictError(f"Nome VRP {vrp} já usado no domínio {dom.name}.")
    devices = [get_device(session, did) for did in dict.fromkeys(data.members)]
    for dev in devices:
        if _membro_loopback(session, dom.id, dev.id) is None:
            raise ValidationError(f"Equipamento {dev.name} sem loopback LDP no domínio (membro inexistente).")
    vsi = models.VsiService(
        domain_id=dom.id, vsi_id=vsi_id, name=nome, vrp_name=vrp,
        mtu=data.mtu, split_horizon=data.split_horizon, mac_learning=data.mac_learning,
        mac_limit=data.mac_limit,
    )
    session.add(vsi)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"VSI-ID ou nome já em uso no domínio {dom.name}.") from exc
    for dev in devices:
        session.add(models.VsiMember(vsi_id=vsi.id, device_id=dev.id))
    session.flush()
    registrar(session, tipo="mpls.vsi.create", ator=actor, objeto="vsi", objeto_id=vsi.id,
              antes=None, depois={"vsi_id": vsi_id, "name": nome, "vrp_name": vrp})
    session.commit()
    return _vsi(session, vsi.id)


def list_vsi(session: Session, domain_id: int | None = None, include_disabled: bool = False) -> list[models.VsiService]:
    q = select(models.VsiService).options(
        selectinload(models.VsiService.members).selectinload(models.VsiMember.device),
        selectinload(models.VsiService.domain),
    ).order_by(models.VsiService.domain_id, models.VsiService.vsi_id).execution_options(populate_existing=True)
    if domain_id is not None:
        q = q.where(models.VsiService.domain_id == domain_id)
    if not include_disabled:
        q = q.where(models.VsiService.admin_status.is_(True))
    return list(session.scalars(q))


def get_vsi(session: Session, vsi_id: int) -> models.VsiService:
    return _vsi(session, vsi_id)


# ---- Serialização VSI (padrão dashboard.py: Out explícito) --------------

def _out_vsi_membro(m: models.VsiMember) -> VsiMemberOut:
    return VsiMemberOut(
        device_id=m.device_id,
        device_name=m.device.name if m.device is not None else None,
    )


def out_vsi(svc: models.VsiService) -> VsiOut:
    return VsiOut(
        id=svc.id,
        domain_id=svc.domain_id,
        vsi_id=svc.vsi_id,
        name=svc.name,
        vrp_name=svc.vrp_name,
        signaling=svc.signaling,
        mtu=svc.mtu,
        split_horizon=svc.split_horizon,
        mac_learning=svc.mac_learning,
        mac_limit=svc.mac_limit,
        admin_status=svc.admin_status,
        operational_status=svc.operational_status,
        last_collected_at=svc.last_collected_at,
        created_at=svc.created_at,
        members=[_out_vsi_membro(m) for m in svc.members],
        domain_name=svc.domain.name if svc.domain is not None else None,
    )
