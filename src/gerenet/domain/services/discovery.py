"""Peers ignorados da descoberta (spec §11).

A lista guarda a quádrupla (device, VRF, família, endereço remoto) do peer que o
operador decidiu não adotar. O candidato adotado não precisa de linha aqui: ele
entra na SoT e sai da lista por consequência.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models, schemas
from gerenet.domain.audit import registrar
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.ipam import reservar_adocao
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.validators import endereco_canonico


def listar_ignorados(session: Session, device_id: int) -> list[models.DiscoveryIgnoredPeer]:
    return list(session.scalars(
        select(models.DiscoveryIgnoredPeer)
        .where(models.DiscoveryIgnoredPeer.device_id == device_id)
        .order_by(models.DiscoveryIgnoredPeer.id)
    ))


def _busca(session: Session, *, device_id: int, vrf: str | None, afi: str, remote_address: str):
    """A linha do peer, comparando pela forma canônica dos dois lados.

    O endereço é a identidade, e a caixa não faz parte dela: o equipamento
    escreve `2804:194C:...` e o operador digita minúsculo. Comparar texto cru
    deixaria as duas formas convivendo como peers diferentes, e o `unignore` de
    uma forma acharia que apagou enquanto a outra seguia escondendo o candidato.
    """
    canonico = endereco_canonico(remote_address)
    stmt = select(models.DiscoveryIgnoredPeer).where(
        models.DiscoveryIgnoredPeer.device_id == device_id,
        models.DiscoveryIgnoredPeer.afi == afi,
    )
    stmt = stmt.where(
        models.DiscoveryIgnoredPeer.vrf.is_(None) if vrf is None
        else models.DiscoveryIgnoredPeer.vrf == vrf
    )
    return next(
        (linha for linha in session.scalars(stmt)
         if endereco_canonico(linha.remote_address) == canonico),
        None,
    )


def ignorar_candidato(
    session: Session, *, device_id: int, vrf: str | None, afi: str,
    remote_address: str, motivo: str | None, actor: str,
) -> models.DiscoveryIgnoredPeer:
    """Marca o candidato como não adotar. Idempotente (§3.2)."""
    existente = _busca(session, device_id=device_id, vrf=vrf, afi=afi,
                       remote_address=remote_address)
    if existente is not None:
        return existente
    # Grava a forma canônica: é ela que o índice único do banco protege, e é o
    # que faz o mesmo peer escrito de duas formas não virar duas linhas.
    canonico = endereco_canonico(remote_address)
    linha = models.DiscoveryIgnoredPeer(
        device_id=device_id, vrf=vrf, afi=afi, remote_address=canonico,
        motivo=motivo, autor=actor,
    )
    session.add(linha)
    try:
        # O `flush` é quem valida: a chave estrangeira do equipamento e os dois
        # índices únicos parciais da quádrupla. A `_busca` acima cobre o caso
        # comum do re-ignorar; o que sobra para o banco recusar é corrida (o
        # equipamento apagado entre a conferência e o insert, ou duas
        # requisições simultâneas) — e o operador recebe o conflito, não um 500
        # com a sessão quebrada.
        session.flush()
        registrar(session, tipo="discovery.ignore", ator=actor,
                  objeto="discovery_ignored_peer", objeto_id=linha.id, antes=None,
                  depois={"device_id": device_id, "vrf": vrf, "afi": afi,
                          "remote_address": canonico, "motivo": motivo})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"O peer {remote_address} não pôde ser ignorado: o equipamento "
            f"{device_id} não existe mais ou a linha acabou de ser criada."
        ) from exc
    session.refresh(linha)
    return linha


def esquecer_ignorado(
    session: Session, *, device_id: int, vrf: str | None, afi: str,
    remote_address: str, actor: str,
) -> bool:
    """Tira o candidato da lista; `False` quando não havia o que tirar.

    O booleano existe para quem chama poder dizer o que aconteceu: sem ele o
    delete de quem não estava lá respondia sucesso, e o operador seguia
    acreditando que o peer tinha voltado a ser candidato.
    """
    existente = _busca(session, device_id=device_id, vrf=vrf, afi=afi,
                       remote_address=remote_address)
    if existente is None:
        return False
    antes = {"device_id": device_id, "vrf": vrf, "afi": afi,
             "remote_address": existente.remote_address, "motivo": existente.motivo}
    objeto_id = existente.id
    session.delete(existente)
    registrar(session, tipo="discovery.unignore", ator=actor,
              objeto="discovery_ignored_peer", objeto_id=objeto_id, antes=antes, depois=None)
    session.commit()
    return True


# Campos que o operador decide na revisão: saem do que a proposta leu, porque
# quem manda neles é a revisão (o `**base` repetiria o argumento e estouraria o
# construtor). `circuit_id` e `device_id` são do circuito que nasce na adoção.
_DO_OPERADOR = (
    "circuit_id", "device_id", "import_profile_id", "export_profile_id", "password_ref",
)


def _sessao_da_proposta(
    proposta, overrides: schemas.AdocaoSessaoIn, *, circuit_id: int, device_id: int
) -> schemas.BgpSessionCreate:
    """Junta o que a proposta leu da configuração com o que o operador decidiu.

    O dict da proposta usa nomes de coluna de `bgp_sessions`; só os campos que o
    schema de criação declara passam, para um nome a mais não estourar o
    construtor. Os dois ids entram por parâmetro porque são obrigatórios no
    `BgpSessionCreate` e a `Proposta` não os tem: o circuito só existe depois
    que a adoção o cria.
    """
    dados = next(s for s in proposta.sessoes if s["afi"] == overrides.afi)
    campos = set(schemas.BgpSessionCreate.model_fields)
    base = {k: v for k, v in dados.items() if k in campos and k not in _DO_OPERADOR}
    return schemas.BgpSessionCreate(
        **base,
        circuit_id=circuit_id,
        device_id=device_id,
        import_profile_id=overrides.import_profile_id,
        export_profile_id=overrides.export_profile_id,
        password_ref=overrides.password_ref,
    )


def adotar_proposta(session: Session, *, proposta, revisao: schemas.AdocaoIn, actor: str) -> int:
    """Grava a cadeia de uma proposta na SoT, numa transação (design §5).

    Uma transação só, e é por isso que os serviços de cadastro são chamados com
    `commit=False`: se qualquer passo recusar, nada fica gravado. Nenhum comando
    vai ao equipamento; mudar o roteador continua exigindo change request.
    """
    # Import tardio: `automation.discovery` importa este módulo (a lista de
    # ignorados), e no topo o ciclo derruba quem importa este módulo primeiro.
    from gerenet.automation.discovery import conferir_fidelidade

    if proposta.veredito == "nao_adotavel":
        raise ConflictError(
            "A proposta tem conflito: resolva antes de adotar ("
            + "; ".join(c.tipo for c in proposta.conflitos) + ")."
        )
    if proposta.vrf is not None:
        raise ConflictError(
            "Sessão em VRF não é reproduzível por esta versão do render: a adoção "
            "gravaria uma sessão que o equipamento não tem nessa instância."
        )
    # Os perfis revisados entram na conferência: sem eles o ensaio não renderiza
    # o corpo da política de exportação, que é justamente o que o operador
    # escolhe errado. A conferência compara o que a adoção VAI gravar.
    perfis = {
        s.afi: {"import_profile_id": s.import_profile_id,
                "export_profile_id": s.export_profile_id}
        for s in revisao.sessoes
    }
    difs = conferir_fidelidade(session, proposta, perfis=perfis)
    if any(d.contexto == "ensaio" for d in difs):
        raise ConflictError("A conferência não pôde ser feita para esta proposta.")
    if any(d.exige_ciente for d in difs) and not revisao.ciente:
        raise ValidationError(
            "Há diferenças que mudariam o equipamento: confirme o ciente para adotar."
        )
    if not proposta.candidatos:
        raise ValidationError("A proposta não tem candidato: nada a adotar.")
    if proposta.site_id is None:
        raise ValidationError("O equipamento não está vinculado a um site.")
    asn_remoto = proposta.candidatos[0].asn_remote
    if asn_remoto is None:
        raise ValidationError("A proposta não tem ASN remoto: não há sessão a criar.")

    organizacao_id = revisao.organizacao_id
    if organizacao_id is None and revisao.organizacao_nova is None:
        raise ValidationError(
            "Informe a organização: escolha uma existente ou crie a nova com o ASN "
            f"{asn_remoto}."
        )

    try:
        if organizacao_id is None:
            org = create_organization(
                session, revisao.organizacao_nova, actor=actor, commit=False
            )
            organizacao_id = org.id

        circuito = create_circuit(
            session,
            schemas.CircuitCreate(
                code=revisao.circuit_code, organization_id=organizacao_id,
                site_id=proposta.site_id,
                access_device_id=revisao.access_device_id, access_port=revisao.access_port,
                edge_device_id=proposta.device_id, edge_trunk=revisao.edge_trunk,
                stack=proposta.stack, vlan_mode=proposta.vlan_mode, qinq=proposta.qinq,
                p2p_v4_len=proposta.p2p_v4_len or 31, vrf=proposta.vrf,
            ),
            actor=actor, commit=False,
        )
        reservar_adocao(
            session, circuito.id, vlans=proposta.vlans, prefixos=proposta.prefixos,
            actor=actor, origem_snapshot_id=proposta.candidatos[0].snapshot_id, commit=False,
        )
        for overrides in revisao.sessoes:
            create_session(
                session,
                _sessao_da_proposta(proposta, overrides, circuit_id=circuito.id,
                                    device_id=proposta.device_id),
                actor=actor, commit=False,
            )
        registrar(
            session, tipo="discovery.adopt", ator=actor, objeto="circuit", objeto_id=circuito.id,
            antes=None,
            depois={
                "device_id": proposta.device_id, "vrf": proposta.vrf,
                "subinterface": proposta.subinterface,
                "snapshot_id": proposta.candidatos[0].snapshot_id,
                "ciente": revisao.ciente,
                "perfis": perfis,
                "diferencas": [
                    {"contexto": d.contexto, "sobrando": list(d.sobrando),
                     "faltando": list(d.faltando),
                     "nao_gerenciado": list(d.nao_gerenciado),
                     "explicacao": d.explicacao}
                    for d in difs if d.exige_ciente
                ],
            },
        )
        session.commit()
    except Exception:
        # Qualquer recusa no meio desfaz o que já foi gravado: sem isto, a
        # organização e o circuito ficariam pendentes na transação de quem
        # chamou — adoção parcial, o oposto do que a §5 promete. Os serviços de
        # cadastro só desfazem sozinhos quando é o banco que recusa (unicidade);
        # a guarda deles, como a do VRF ou a do ASN, sai antes de qualquer
        # `rollback`.
        session.rollback()
        raise
    return circuito.id
