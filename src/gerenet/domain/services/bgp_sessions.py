"""Sessões BGP por família (§6.3) — SoT da intenção de downstreams.

Regras de unicidade do §14.1 em serviço (sem constraints UNIQUE — spec §5):
linha (device+VRF+afi) e par (local, remoto). A Task 5 acrescenta
update_session/disable_session/add_community/remove_community a este arquivo.
"""
import ipaddress

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import BgpSessionCreate
from gerenet.domain.services.circuits import get_circuit
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.services.policy_profiles import get_policy_profile
from gerenet.domain.validators import asn_valido


def _valida_endereco(afi: str, campo: str, valor: str) -> None:
    """Endereço IP válido e da família do afi (mensagens PT-BR)."""
    try:
        endereco = ipaddress.ip_address(valor)
    except ValueError as exc:
        raise ValidationError(f"{campo} inválido: {valor}.") from exc
    familia = "ipv4" if isinstance(endereco, ipaddress.IPv4Address) else "ipv6"
    if familia != afi:
        raise ValidationError(f"{campo} {valor} não é um endereço {afi}.")


def _valida_asn(valor: int | None) -> None:
    if valor is not None and not asn_valido(valor):
        raise ValidationError(f"ASN inválido ou reservado: {valor}.")


def _valida_perfil(session: Session, perfil_id: int, uso: str) -> None:
    """uso = "importação" | "exportação"; perfil precisa da direção correspondente."""
    perfil = get_policy_profile(session, perfil_id)
    esperado = "import" if uso == "importação" else "export"
    if perfil.direction != esperado:
        raise ValidationError(
            f"Perfil {perfil.name} tem direção {perfil.direction} e não pode ser "
            f"o perfil de {uso} da sessão."
        )


def _vrf_texto(circuito: models.Circuit) -> str:
    return circuito.vrf or "pública"


def _colidente_linha(
    session: Session, *, device_id: int, afi: str, vrf: str | None, ignorar_id: int | None = None
) -> models.BgpSession | None:
    """Outra sessão ativa no mesmo (device, VRF do circuito, afi) — spec §4."""
    stmt = (
        select(models.BgpSession, models.Circuit)
        .join(models.Circuit, models.BgpSession.circuit_id == models.Circuit.id)
        .where(
            models.BgpSession.admin_status.is_(True),
            models.BgpSession.device_id == device_id,
            models.BgpSession.afi == afi,
        )
    )
    for outra, circ in session.execute(stmt):
        if outra.id == ignorar_id:
            continue
        if circ.vrf == vrf:
            return outra
    return None


def _colidente_par(
    session: Session, *, local_address: str, remote_address: str, ignorar_id: int | None = None
) -> models.BgpSession | None:
    """Outra sessão ativa com o mesmo par (local, remoto) — global, par invertido inclui."""
    objetivo = frozenset(
        {int(ipaddress.ip_address(local_address)), int(ipaddress.ip_address(remote_address))}
    )
    stmt = select(models.BgpSession).where(models.BgpSession.admin_status.is_(True))
    for outra in session.scalars(stmt):
        if outra.id == ignorar_id:
            continue
        par = frozenset(
            {int(ipaddress.ip_address(outra.local_address)), int(ipaddress.ip_address(outra.remote_address))}
        )
        if par == objetivo:
            return outra
    return None


def create_session(session: Session, data: BgpSessionCreate, *, actor: str) -> models.BgpSession:
    circ = get_circuit(session, data.circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe sessões.")
    device = get_device(session, data.device_id)
    if data.device_id not in (circ.edge_device_id, circ.backup_edge_device_id):
        raise ValidationError(
            f"Equipamento {device.name} não é edge/backup_edge do circuito {circ.code}."
        )
    org = get_organization(session, circ.organization_id)

    _valida_endereco(data.afi, "local_address", data.local_address)
    _valida_endereco(data.afi, "remote_address", data.remote_address)
    if data.source_address is not None:
        _valida_endereco(data.afi, "source_address", data.source_address)

    asn_local = data.asn_local if data.asn_local is not None else device.asn
    if asn_local is None:
        raise ValidationError(f"Equipamento {device.name} não possui ASN; informe asn_local.")
    _valida_asn(asn_local)
    if data.asn_remote is not None:
        if org.asn is not None and data.asn_remote != org.asn:
            raise ValidationError(
                f"asn_remote {data.asn_remote} difere do ASN {org.asn} da organização {org.name}."
            )
        asn_remote = data.asn_remote
    elif org.asn is not None:
        asn_remote = org.asn
    else:
        raise ValidationError(f"Organização {org.name} não possui ASN; informe asn_remote.")
    _valida_asn(asn_remote)

    if data.import_profile_id is not None:
        _valida_perfil(session, data.import_profile_id, "importação")
    if data.export_profile_id is not None:
        _valida_perfil(session, data.export_profile_id, "exportação")

    if _colidente_linha(
        session, device_id=data.device_id, afi=data.afi, vrf=circ.vrf
    ) is not None:
        raise ConflictError(
            f"Já existe sessão {data.afi} ativa no equipamento {device.name} "
            f"(VRF {_vrf_texto(circ)})."
        )
    if _colidente_par(
        session, local_address=data.local_address, remote_address=data.remote_address
    ) is not None:
        raise ConflictError(
            f"Já existe sessão ativa entre {data.local_address} e {data.remote_address}."
        )

    dump = data.model_dump()
    dump["asn_local"] = asn_local
    dump["asn_remote"] = asn_remote
    sessao = models.BgpSession(**dump)
    session.add(sessao)
    try:
        session.flush()  # valida as FKs antes da auditoria
        registrar(
            session, tipo="bgp_session.create", ator=actor, objeto="bgp_session",
            objeto_id=sessao.id, antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "Não foi possível criar a sessão BGP: conflito de integridade."
        ) from exc
    session.refresh(sessao)
    return sessao


def get_session(session: Session, session_id: int) -> models.BgpSession:
    sessao = session.get(models.BgpSession, session_id)
    if sessao is None:
        raise NotFoundError(f"Sessão BGP {session_id} não encontrada.")
    return sessao


def list_sessions(
    session: Session,
    circuit_id: int | None = None,
    device_id: int | None = None,
    include_disabled: bool = False,
) -> list[models.BgpSession]:
    stmt = select(models.BgpSession).order_by(models.BgpSession.id)
    if not include_disabled:
        stmt = stmt.where(models.BgpSession.admin_status.is_(True))
    if circuit_id is not None:
        stmt = stmt.where(models.BgpSession.circuit_id == circuit_id)
    if device_id is not None:
        stmt = stmt.where(models.BgpSession.device_id == device_id)
    return list(session.scalars(stmt))
