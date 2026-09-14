"""Peers ignorados da descoberta (spec §11).

A lista guarda a quádrupla (device, VRF, família, endereço remoto) do peer que o
operador decidiu não adotar. O candidato adotado não precisa de linha aqui: ele
entra na SoT e sai da lista por consequência.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import ConflictError
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
