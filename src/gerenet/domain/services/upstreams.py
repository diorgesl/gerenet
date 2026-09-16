"""Upstreams (§7) — CRUD, vínculo com circuitos e propagação de defaults às sessões."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models, schemas
from gerenet.domain.audit import registrar
from gerenet.domain.schemas import UpstreamCreate, UpstreamUpdate
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.circuits import create_circuit, get_circuit
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError
from gerenet.domain.services.organizations import get_organization

PRODUTO_IMPORT_POR_TIPO = {"transito": "up-full", "ix": "up-full",
                           "pni": "up-parcial", "contingencia": "up-default"}

# O nome do perfil de importação de cada produto (§7). São vocabulários
# diferentes: `produto_import` guarda "full"/"parcial"/"default" e o catálogo
# chama os perfis de "up-full"/"up-parcial"/"up-default".
PERFIL_DO_PRODUTO = {"full": "up-full", "parcial": "up-parcial",
                     "default": "up-default"}

# Campos do upstream que alimentam a propagação (§3.1): mudou algum ⇒ repropagar
# defaults às sessões dos circuitos vinculados no update_upstream.
_CAMPOS_PROPAGACAO = frozenset((
    "tipo", "expected_prefixes_v4", "expected_prefixes_v6", "max_prefix_margin_pct",
    "entrada_local_preference", "contingencia_local_preference", "contingencia_prepend",
    "produto_import",
))


def _perfil_import(session: Session, nome: str) -> models.PolicyProfile | None:
    return session.scalar(
        select(models.PolicyProfile).where(
            models.PolicyProfile.name == nome,
            models.PolicyProfile.direction == "import",
            models.PolicyProfile.admin_status.is_(True),
        ))


def get_upstream(session: Session, upstream_id: int) -> models.Upstream:
    up = session.get(models.Upstream, upstream_id)
    if up is None:
        raise NotFoundError(f"Upstream {upstream_id} não encontrado.")
    return up


def list_upstreams(session: Session, *, organization_id: int | None = None,
                   include_disabled: bool = False) -> list[models.Upstream]:
    stmt = select(models.Upstream).order_by(models.Upstream.name)
    if not include_disabled:
        stmt = stmt.where(models.Upstream.admin_status.is_(True))
    if organization_id is not None:
        stmt = stmt.where(models.Upstream.organization_id == organization_id)
    return list(session.scalars(stmt))


def _validar_org_operadora(session: Session, organization_id: int) -> models.Organization:
    org = get_organization(session, organization_id)
    if org.kind != "operadora":
        raise ValidationError(f"Organização {org.id} não é operadora (kind={org.kind}).")
    return org


def _valida_nomes(nome: str | None) -> None:
    if nome is None:
        raise ValidationError("Nome do upstream não pode ser nulo.")
    if len(nome) < 2 or len(nome) > 128:
        raise ValidationError("Nome do upstream deve ter entre 2 e 128 caracteres.")


def create_upstream(session: Session, data: UpstreamCreate, *, actor: str,
                    commit: bool = True) -> models.Upstream:
    """Cadastra o upstream; `commit=False` é para a adoção encadear a cadeia
    inteira numa transação (design §5.3)."""
    _validar_org_operadora(session, data.organization_id)
    _valida_nomes(data.name)
    dump = data.model_dump()
    up = models.Upstream(**dump)
    session.add(up)
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(session, tipo="upstream.create", ator=actor, objeto="upstream",
                  objeto_id=up.id, antes=None, depois=dump)
        if commit:
            session.commit()  # propagação às sessões ocorre no vínculo de circuitos
            # (vincular_circuito/update_upstream chamam propagar_defaults — §3.1)
    except IntegrityError:
        session.rollback()
        raise ConflictError(f"Já existe um upstream com o nome {data.name}.") from None
    if commit:
        session.refresh(up)
    return up


def criar_com_circuito(
    session: Session, data: schemas.UpstreamCreate,
    circuito: schemas.UpstreamCircuitoIn | None = None, *, actor: str, commit: bool = True,
) -> models.Upstream:
    """Cadastra o upstream e, com o bloco de acesso, o circuito vinculado (§6).

    Uma transação: o upstream, o circuito e o vínculo principal nascem juntos,
    ou nada nasce. O circuito nasce sem reserva — quem reserva VLAN e endereços é
    a página do circuito.
    """
    up = create_upstream(session, data, actor=actor, commit=False)
    if circuito is None:
        if commit:
            session.commit()
            session.refresh(up)
        return up
    try:
        circ = create_circuit(
            session,
            schemas.CircuitCreate(
                code=circuito.code, organization_id=data.organization_id,
                site_id=circuito.site_id, access_device_id=circuito.access_device_id,
                access_port=circuito.access_port, edge_device_id=circuito.edge_device_id,
                edge_trunk=circuito.edge_trunk, velocidade_mbps=circuito.velocidade_mbps,
            ),
            actor=actor, commit=False,
        )
        vincular_circuito(session, up.id, circ.id, papel="principal", ordem=1,
                          actor=actor, commit=False)
        if commit:
            session.commit()
            session.refresh(up)
    except Exception:
        # Qualquer recusa depois do upstream desfaz o que já foi gravado: sem
        # isto o upstream ficaria pendente na transação de quem chamou. O
        # `if commit` é o que impede esta limpeza de levar junto a transação de
        # um chamador que compôs com `commit=False` — a mesma fronteira dos
        # outros serviços.
        if commit:
            session.rollback()
        raise
    return up


def update_upstream(session: Session, upstream_id: int, data: UpstreamUpdate, *,
                    actor: str) -> models.Upstream:
    """Atualiza um upstream; mudou o dataset ⇒ re-propaga defaults às sessões (§3.1)."""
    up = get_upstream(session, upstream_id)
    mudancas = data.model_dump(exclude_unset=True)
    if not mudancas:
        return up
    if "organization_id" in mudancas:
        if mudancas["organization_id"] is None:
            # M-9 (revisão final): null explícito passava o guard e o NOT NULL
            # estourava IntegrityError → ConflictError "nome None" enganosa.
            raise ValidationError("Organização do upstream não pode ser nula.")
        _validar_org_operadora(session, mudancas["organization_id"])
    if "name" in mudancas:
        _valida_nomes(mudancas["name"])
    antes = {campo: getattr(up, campo) for campo in mudancas}
    for campo, valor in mudancas.items():
        setattr(up, campo, valor)
    try:
        registrar(session, tipo="upstream.update", ator=actor, objeto="upstream",
                  objeto_id=up.id, antes=antes, depois=mudancas)
        if _CAMPOS_PROPAGACAO & set(mudancas):
            propagar_defaults(session, up)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError(f"Já existe um upstream com o nome {mudancas.get('name')}.") from None
    session.refresh(up)
    return up


def disable_upstream(session: Session, upstream_id: int, *, actor: str) -> models.Upstream:
    up = get_upstream(session, upstream_id)
    if up.admin_status is False:
        return up  # idempotente: sem transição, sem evento
    up.admin_status = False
    registrar(
        session, tipo="upstream.disable", ator=actor, objeto="upstream",
        objeto_id=up.id, antes={"admin_status": True}, depois={"admin_status": False},
    )
    session.commit()
    return up


def _principal_existente(session: Session, upstream_id: int) -> bool:
    """Existe vínculo com papel principal para o upstream? (transição R-01)"""
    return session.scalar(
        select(models.UpstreamCircuit.id).where(
            models.UpstreamCircuit.upstream_id == upstream_id,
            models.UpstreamCircuit.papel == "principal",
        ).limit(1)
    ) is not None


def _valida_conjunto_sem_principal(session: Session, up: models.Upstream, *,
                                   excluir_id: int | None = None,
                                   novo_papel: str | None = None) -> None:
    """R-01 — upstream ativo com circuitos vinculados exige ≥1 principal.

    Valida o conjunto de vínculos na perspectiva do RESULTADO da operação:
    vincular exige principal existente quando o novo vínculo não é principal;
    desvincular exige outro principal quando restarem circuitos. Upstream sem
    vínculos é válido (a criação sem circuitos permanece permitida).
    """
    if not up.admin_status:
        return
    if novo_papel is not None:
        if novo_papel == "principal" or _principal_existente(session, up.id):
            return
    else:
        restantes = list(session.scalars(select(models.UpstreamCircuit).where(
            models.UpstreamCircuit.upstream_id == up.id,
            models.UpstreamCircuit.circuit_id != excluir_id,
        )))
        if not restantes or any(v.papel == "principal" for v in restantes):
            return
    raise ValidationError("Upstream ativo precisa de ao menos um circuito principal.")


def vincular_circuito(session: Session, upstream_id: int, circuit_id: int, *, papel: str,
                      ordem: int, actor: str, commit: bool = True) -> models.Upstream:
    """Vincula um circuito ao upstream (§7) — os defaults caem nas sessões aqui.

    Regras: circuito deve existir e estar ativo; um circuito só tem um upstream
    (BR-1); transição registrada na auditoria; propagação de defaults às sessões
    dos circuitos vinculados em seguida (§3.1).
    """
    up = get_upstream(session, upstream_id)
    if up.admin_status is False:
        raise ConflictError(f"Upstream {up.name} desativado não recebe circuitos.")
    circ = get_circuit(session, circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe vínculo de upstream.")
    ja_linkado = session.scalar(
        select(models.UpstreamCircuit).where(models.UpstreamCircuit.circuit_id == circuit_id)
    )
    if ja_linkado is not None:
        raise ConflictError("Circuito já vinculado a um upstream.")
    _valida_conjunto_sem_principal(session, up, novo_papel=papel)

    session.add(models.UpstreamCircuit(
        upstream_id=up.id, circuit_id=circ.id, papel=papel, ordem=ordem))
    try:
        session.flush()  # valida a unicidade (upstream, circuito) antes da auditoria
        session.refresh(up, ["circuitos"])
        registrar(
            session, tipo="upstream.vincular_circuito", ator=actor, objeto="upstream",
            objeto_id=up.id, antes=None,
            depois={"circuito_id": circ.id, "circuito": circ.code, "papel": papel,
                    "ordem": ordem},
        )
        propagar_defaults(session, up)
        if commit:
            session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("Circuito já vinculado a um upstream.") from None
    if commit:
        session.refresh(up)
    return up


def desvincular_circuito(session: Session, upstream_id: int, circuit_id: int, *,
                         actor: str) -> models.Upstream:
    """Remove o vínculo circuito ↔ upstream (linha deletável; trilha na auditoria)."""
    up = get_upstream(session, upstream_id)
    vinculo = session.scalar(select(models.UpstreamCircuit).where(
        models.UpstreamCircuit.upstream_id == upstream_id,
        models.UpstreamCircuit.circuit_id == circuit_id,
    ))
    if vinculo is None:
        return up  # sem transição, sem evento
    _valida_conjunto_sem_principal(session, up, excluir_id=circuit_id)
    antes = {"circuito_id": vinculo.circuit_id, "circuito": vinculo.circuito.code,
             "papel": vinculo.papel, "ordem": vinculo.ordem}
    session.delete(vinculo)
    registrar(
        session, tipo="upstream.desvincular_circuito", ator=actor, objeto="upstream",
        objeto_id=up.id, antes=antes, depois=None,
    )
    session.commit()
    session.refresh(up)
    return up


def upstream_do_circuito(session: Session, circuit_id: int) -> models.Upstream | None:
    """Upstream que vincula o circuito (§7) — usado por B3 para links de upstream."""
    vinculo = session.scalar(
        select(models.UpstreamCircuit).where(models.UpstreamCircuit.circuit_id == circuit_id)
    )
    return vinculo.upstream if vinculo is not None else None


def propagar_defaults(session: Session, up: models.Upstream) -> list[int]:
    """Aplica defaults do upstream às sessões dos circuitos vinculados (§3.1).

    Sessões com campo explícito NÃO são sobrescritas (campo vence), salvo
    maximum_prefix quando veio da propagação anterior — ver regra:
    maximum_prefix/maximum_prefix_threshold são RECALCULADOS sempre
    (derivam do esperado×margem); LP/prepend/import_profile só quando
    a sessão está com o valor default do render (None).
    """
    alterados: list[int] = []
    for vinculo in up.circuitos:
        cir = vinculo.circuito
        margem = up.max_prefix_margin_pct / 100
        esperado = {"ipv4": up.expected_prefixes_v4, "ipv6": up.expected_prefixes_v6}
        for sessao in list_sessions(session, circuit_id=cir.id, include_disabled=False):
            esperado_afi = esperado.get(sessao.afi)
            if esperado_afi is not None:
                max_p = int(esperado_afi * (1 + margem))
                if sessao.maximum_prefix != max_p:
                    sessao.maximum_prefix = max_p
                    if sessao.maximum_prefix_threshold is None:
                        sessao.maximum_prefix_threshold = 80
                    alterados.append(sessao.id)
            if vinculo.papel == "contingencia":
                if up.contingencia_local_preference is not None and sessao.local_preference is None:
                    sessao.local_preference = up.contingencia_local_preference
                if up.contingencia_prepend is not None and sessao.prepend is None:
                    sessao.prepend = up.contingencia_prepend
            else:
                if up.entrada_local_preference is not None and sessao.local_preference is None:
                    sessao.local_preference = up.entrada_local_preference
            if sessao.import_profile_id is None:
                nome_perfil = (
                    PERFIL_DO_PRODUTO[up.produto_import] if up.produto_import
                    else PRODUTO_IMPORT_POR_TIPO[up.tipo]
                )
                perfil = _perfil_import(session, nome_perfil)
                if perfil is not None:
                    sessao.import_profile_id = perfil.id
                    alterados.append(sessao.id)
    return alterados
