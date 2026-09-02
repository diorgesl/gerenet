from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import CircuitCreate, CircuitUpdate
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization
from gerenet.domain.services.sites import get_site

_CAMPOS_DEVICE = ("access_device_id", "edge_device_id", "backup_edge_device_id")


def _valida_vinculos(session: Session, site_id: int, dump: dict) -> None:
    """access/edge/backup devem pertencer ao site do circuito (spec)."""
    get_site(session, site_id)  # NotFoundError com mensagem PT
    for campo in _CAMPOS_DEVICE:
        if campo not in dump or dump[campo] is None:
            continue
        dev = get_device(session, dump[campo])
        if dev.site_id != site_id:
            raise ValidationError(f"Equipamento {dev.name} não pertence ao site {site_id}.")


def create_circuit(session: Session, data: CircuitCreate, *, actor: str) -> models.Circuit:
    get_organization(session, data.organization_id)
    dump = data.model_dump()
    _valida_vinculos(session, data.site_id, dump)
    circ = models.Circuit(**dump)
    session.add(circ)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(
            session, tipo="circuit.create", ator=actor, objeto="circuit", objeto_id=circ.id,
            antes=None, depois=dump,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um circuito com o código {data.code}.") from exc
    session.refresh(circ)
    return circ


def get_circuit(session: Session, circuit_id: int) -> models.Circuit:
    circ = session.get(models.Circuit, circuit_id)
    if circ is None:
        raise NotFoundError(f"Circuito {circuit_id} não encontrado.")
    return circ


def list_circuits(
    session: Session,
    organization_id: int | None = None,
    site_id: int | None = None,
    include_disabled: bool = False,
) -> list[models.Circuit]:
    stmt = select(models.Circuit).order_by(models.Circuit.code)
    if not include_disabled:
        stmt = stmt.where(models.Circuit.admin_status.is_(True))
    if organization_id is not None:
        stmt = stmt.where(models.Circuit.organization_id == organization_id)
    if site_id is not None:
        stmt = stmt.where(models.Circuit.site_id == site_id)
    return list(session.scalars(stmt))


def update_circuit(session: Session, circuit_id: int, data: CircuitUpdate, *, actor: str) -> models.Circuit:
    circ = get_circuit(session, circuit_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return circ
    # Testes de presença explícitos ("in" + "is not None"): um id 0 explícito
    # segue para o check de existência e vira NotFoundError, em vez de pular a
    # validação e explodir como IntegrityError cru no commit (finding Task 7).
    if "organization_id" in mudancas and mudancas["organization_id"] is not None:
        get_organization(session, mudancas["organization_id"])
    novo_site_id = circ.site_id
    if "site_id" in mudancas and mudancas["site_id"] is not None:
        novo_site_id = mudancas["site_id"]
    vinculos = dict(mudancas)
    if novo_site_id != circ.site_id:
        # troca de site: revalida também os devices atuais contra o novo site
        for campo in _CAMPOS_DEVICE:
            vinculos.setdefault(campo, getattr(circ, campo))
    _valida_vinculos(session, novo_site_id, vinculos)
    antes = {campo: getattr(circ, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(circ, campo, valor)
    try:
        registrar(
            session, tipo="circuit.update", ator=actor, objeto="circuit", objeto_id=circ.id,
            antes=antes, depois=mudancas,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe um circuito com o código {mudancas.get('code')}.") from exc
    session.refresh(circ)
    return circ


def disable_circuit(session: Session, circuit_id: int, *, actor: str) -> models.Circuit:
    circ = get_circuit(session, circuit_id)
    if circ.admin_status is False:
        return circ
    circ.admin_status = False
    registrar(
        session, tipo="circuit.disable", ator=actor, objeto="circuit", objeto_id=circ.id,
        antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return circ
