"""O plano de communities na SoT: ler, propor, validar e adotar (spec §9).

A escrita é uma transação só, como a adoção de peer da descoberta: o plano é um
objeto coerente e uma adoção pela metade deixaria classes sem portão. Qualquer
recusa desfaz tudo. Nada aqui vai ao equipamento — o único caminho é o snapshot
já coletado, e mudar o roteador continua sendo change request.
"""
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation.community_plan import (
    Achado,
    AlvoPlano,
    ClassePlano,
    InstrucaoPlano,
    PlanoLido,
    PortaoPlano,
    PropostaPlano,
    RegraImportPlano,
    propor_plano,
    validar,
)
from gerenet.automation.discovery import _snapshot_com_config
from gerenet.automation.parsers.huawei_vrp.communities_vrp import (
    LeituraCommunities,
    parse_communities_vrp,
)
from gerenet.domain import models
from gerenet.domain.audit import registrar
from gerenet.domain.services.errors import ConflictError, NotFoundError, ValidationError


def _leitura_do_device(session: Session, device_id: int) -> LeituraCommunities | None:
    snap, texto = _snapshot_com_config(session, device_id)
    if snap is None or not texto.strip():
        return None
    leitura = parse_communities_vrp(texto)
    return leitura


def ler_do_snapshot(session: Session, device_id: int) -> LeituraCommunities:
    """A leitura da configuração coletada de um equipamento (somente leitura)."""
    leitura = _leitura_do_device(session, device_id)
    if leitura is None:
        raise NotFoundError(
            f"Equipamento {device_id} não tem coleta com a configuração salva. "
            "Colete antes de ler o plano."
        )
    return leitura


def direcoes_do_device(session: Session, device_id: int) -> dict[str, str]:
    """O mapa filtro → direção, do vínculo real da sessão (Regra 4 do plano)."""
    direcoes: dict[str, str] = {}
    sessoes = session.scalars(
        select(models.BgpSession).where(models.BgpSession.device_id == device_id)
    ).all()
    for sessao in sessoes:
        if sessao.import_route_policy:
            direcoes.setdefault(sessao.import_route_policy, "import")
        if sessao.export_route_policy:
            direcoes.setdefault(sessao.export_route_policy, "export")
    return direcoes


def _peers_dos_snapshots(
    session: Session, device_ids: Sequence[int]
) -> dict[str, str]:
    """Endereço do peer → estado, da coleta mais recente de cada equipamento.

    O estado é do **equipamento**, não da SoT: a SoT guarda a intenção, e um
    `bgp_sessions` sem `shutdown` não é um peer de pé (§3). O recurso `bgp_peers`
    é o que tem o estado real, com uma linha por peer e família
    (`{afi, peer, asn, estado, pref_rcv, up_down}` — o `merge_bgp_peers`).
    """
    consulta = (
        select(models.DeviceSnapshot)
        .order_by(models.DeviceSnapshot.id.desc())
    )
    if device_ids:
        consulta = consulta.where(models.DeviceSnapshot.device_id.in_(list(device_ids)))
    vistos: set[int] = set()
    estados: dict[str, str] = {}
    for snap in session.scalars(consulta):
        if snap.device_id in vistos:
            continue
        linhas = (snap.resources or {}).get("bgp_peers")
        if not linhas:
            continue  # coleta sem a tabela de peers: a anterior ainda pode ter
        vistos.add(snap.device_id)
        for linha in linhas:
            endereco = linha.get("peer")
            if endereco:
                # `setdefault` pelo mesmo motivo do merge: a v4 vem antes da v6,
                # e o alvo de pé em qualquer uma das duas está de pé.
                estados.setdefault(endereco, linha.get("estado") or "ausente")
    return estados


def estados_dos_alvos(
    session: Session,
    leituras: Sequence[LeituraCommunities],
    device_ids: Sequence[int] = (),
) -> dict[str, str]:
    """O estado de cada alvo do plano, para a poda (§9.3) e a checagem 7 (§8).

    O alvo é um **grupo** de `peer` da configuração (`peer MSD-CDN-v4 as-number
    53062`) e o estado está por endereço, então o nome vira endereço pelos
    membros que o próprio leitor achou (`peer 45.227.2.253 group IX-CG`). Basta
    um membro Established para o alvo estar de pé; sem nenhum membro conhecido o
    alvo **não** entra no mapa, e a checagem 7 o trata como `ausente` — que é o
    que ele é para esta leitura.
    """
    coletados = _peers_dos_snapshots(session, device_ids)
    estados: dict[str, str] = {}
    for leitura in leituras:
        for alvo in leitura.alvos:
            vistos = [coletados[m] for m in alvo.membros if m in coletados]
            if not vistos:
                continue
            de_pe = next((e for e in vistos if e.lower().startswith("estab")), None)
            estados[alvo.nome] = "established" if de_pe else vistos[0]
    return estados


def papeis_da_sot(session: Session) -> dict[int, str]:
    """ASN da organização → tipo do upstream, para o papel do alvo (Regra 5)."""
    papeis: dict[int, str] = {}
    linhas = session.execute(
        select(models.Organization.asn, models.Upstream.tipo)
        .join(models.Upstream, models.Upstream.organization_id == models.Organization.id)
    ).all()
    for asn, tipo in linhas:
        if asn is not None:
            papeis[int(asn)] = tipo
    return papeis


def obter_plano(session: Session) -> PlanoLido | None:
    """O plano ativo da SoT, no mesmo formato que a proposta produz."""
    plano = session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.admin_status.is_(True))
    )
    if plano is None:
        return None
    # Um só dicionário por id, com as classes **e** as instruções: as duas
    # partilham a tabela (`codigo` nulo é classe, preenchido é instrução) e o
    # `nome_por_id` daí sai — é ele que traduz `classe_import_id` e `classe_id`
    # de volta para o nome que a leitura usa.
    por_id = {c.id: c for c in session.scalars(select(models.Community))}
    nome_por_id = {c.id: c.name for c in por_id.values()}

    def _nomes(ids) -> tuple[str, ...]:
        return tuple(nome_por_id.get(i, str(i)) for i in (ids or ()))

    return PlanoLido(
        asn_principal=plano.asn_principal,
        asns_anunciados=tuple(plano.asns_anunciados or ()),
        classes=tuple(
            ClassePlano(nome=c.name, banda=c.banda, tipo=c.tipo, valor_v4=c.valor_v4,
                        valor_v6=c.valor_v6, id=c.id, notas=c.notes)
            for c in por_id.values() if c.codigo is None
        ),
        instrucoes=tuple(
            InstrucaoPlano(nome=c.name, codigo=c.codigo, tipo=c.tipo, id=c.id, notas=c.notes)
            for c in por_id.values() if c.codigo is not None
        ),
        portoes=tuple(
            PortaoPlano(nome=g.nome, papel=g.papel, afi=g.afi, padrao=g.padrao,
                        aceitas=_nomes(g.aceitas), recusadas=_nomes(g.recusadas), id=g.id)
            for g in session.scalars(select(models.CommunityGate))
        ),
        alvos=tuple(
            AlvoPlano(nome=t.nome, papel=t.papel, codigo_v4=t.codigo_v4, codigo_v6=t.codigo_v6,
                      gate_nome=t.gate_nome, classe_import=nome_por_id.get(t.classe_import_id),
                      upstream_id=t.upstream_id, organization_id=t.organization_id,
                      parametros=t.parametros or {}, id=t.id)
            for t in session.scalars(select(models.CommunityTarget))
        ),
        regras_import=tuple(
            RegraImportPlano(papel=r.papel, afi=r.afi, classe=nome_por_id.get(r.classe_id, ""),
                             condicao=r.condicao or {}, notas=r.notas)
            for r in session.scalars(select(models.CommunityImportRule))
        ),
        snapshot_id=plano.origem_snapshot_id,
        observacoes=plano.observacoes,
    )


def propor_adocao(session: Session, device_id: int) -> PropostaPlano:
    """O que a adoção gravaria, lido do snapshot — sem escrever nada."""
    snap, texto = _snapshot_com_config(session, device_id)
    if snap is None or not texto.strip():
        raise NotFoundError(
            f"Equipamento {device_id} não tem coleta com a configuração salva. "
            "Colete antes de adotar o plano."
        )
    leitura = parse_communities_vrp(texto)
    proposta = propor_plano(
        [leitura],
        asn_principal=leitura.asn_local or _asn_do_equipamento(session, device_id),
        estados_alvo=estados_dos_alvos(session, [leitura], [device_id]),
        papeis_da_sot=papeis_da_sot(session),
    )
    return PropostaPlano(
        plano=PlanoLido(**{**proposta.plano.__dict__, "snapshot_id": snap.id}),
        divergencias=proposta.divergencias, parados=proposta.parados, avisos=proposta.avisos,
    )


def _asn_do_equipamento(session: Session, device_id: int) -> int | None:
    device = session.get(models.Device, device_id)
    return device.asn if device is not None else None


def validar_plano(session: Session, device_ids: list[int] | None = None) -> tuple[Achado, ...]:
    """As oito checagens sobre o plano ativo e a configuração coletada.

    Sem `device_ids`, valida contra todos os equipamentos que têm coleta — é o
    que a página mostra, porque a comparação que importa é entre a borda e o VS.
    """
    plano = obter_plano(session)
    if plano is None:
        return ()
    if device_ids is None:
        device_ids = list(session.scalars(
            select(models.DeviceSnapshot.device_id).distinct()
        ).all())
    leituras: list[LeituraCommunities] = []
    direcoes: dict[str, str] = {}
    for device_id in device_ids:
        leitura = _leitura_do_device(session, device_id)
        if leitura is None:
            continue
        leituras.append(leitura)
        direcoes.update(direcoes_do_device(session, device_id))
    return validar(
        plano, leituras, direcoes=direcoes,
        estados_alvo=estados_dos_alvos(session, leituras, device_ids),
    )


def _resolve_classes(
    session: Session, classes: tuple[ClassePlano, ...], *, snapshot_id: int | None
) -> dict[str, int]:
    """Cria as classes que faltam e devolve nome → id.

    A busca é pelo valor (namespace-agnóstico), como a do motor: `61785:3001` e
    `65000:3001` são a mesma classe (Regra 1). Nome já existente é reaproveitado.
    """
    ids: dict[str, int] = {}
    for classe in classes:
        existente = session.scalar(
            select(models.Community).where(models.Community.name == classe.nome)
        )
        for campo, valor in (("valor_v4", classe.valor_v4), ("valor_v6", classe.valor_v6)):
            if existente is None and valor is not None:
                existente = session.scalar(
                    select(models.Community).where(
                        getattr(models.Community, campo) == valor
                    )
                )
        if existente is not None:
            ids[classe.nome] = existente.id
            continue
        nova = models.Community(
            name=classe.nome, tipo=classe.tipo, banda=classe.banda, valor_v4=classe.valor_v4,
            valor_v6=classe.valor_v6, notes=classe.notas, origem="adotado",
            origem_snapshot_id=snapshot_id,
        )
        session.add(nova)
        session.flush()
        ids[classe.nome] = nova.id
    return ids


def adotar_plano(
    session: Session,
    proposta: PropostaPlano,
    *,
    device_id: int,
    snapshot_id: int | None,
    actor: str,
) -> models.CommunityPlan:
    """Grava o plano numa transação só, com auditoria. Idempotente.

    Adotar duas vezes o mesmo plano não cria linha nova nem evento novo: o
    segundo `POST` devolve o plano que já está lá (ruling 5 do repositório, o
    mesmo do `disable_community`).

    Plano ativo de **outro** ASN principal recusa com `ConflictError`, antes de
    escrever qualquer coisa (R28): os filhos não têm recorte por plano ativo (as
    UNIQUEs de `community_gates` e de `community_import_rules` valem para o
    vocabulário inteiro e a `CommunityImportRule` nem tem `admin_status`), então
    substituir o plano pediria mudar o modelo. A recusa mantém a transação
    única da §9: nada é gravado, nem desativado.
    """
    existente = session.scalar(
        select(models.CommunityPlan).where(models.CommunityPlan.admin_status.is_(True))
    )
    if existente is not None:
        if existente.asn_principal == proposta.plano.asn_principal:
            # Mesmo ASN principal: o plano é o mesmo; nada a transicionar, nada a auditar.
            return existente
        raise ConflictError(
            f"Já existe plano ativo para o ASN principal {existente.asn_principal}; "
            f"desative-o antes de adotar o plano do ASN {proposta.plano.asn_principal}."
        )

    ids = _resolve_classes(
        session, proposta.plano.classes, snapshot_id=snapshot_id
    )
    ids_instrucoes = _resolve_instrucoes(
        session, proposta.plano.instrucoes, snapshot_id=snapshot_id
    )

    plano = models.CommunityPlan(
        asn_principal=proposta.plano.asn_principal,
        asns_anunciados=[dict(a) for a in proposta.plano.asns_anunciados],
        origem="adotado", origem_snapshot_id=snapshot_id,
        observacoes=f"adotado da coleta do equipamento {device_id}",
    )
    session.add(plano)
    session.flush()

    for portao in proposta.plano.portoes:
        session.add(
            models.CommunityGate(
                nome=portao.nome, papel=portao.papel, afi=portao.afi, padrao=portao.padrao,
                aceitas=[ids[n] for n in portao.aceitas if n in ids],
                recusadas=[ids[n] for n in portao.recusadas if n in ids],
                origem="adotado", origem_snapshot_id=snapshot_id,
            )
        )
    for alvo in proposta.plano.alvos:
        session.add(
            models.CommunityTarget(
                nome=alvo.nome, papel=alvo.papel, codigo_v4=alvo.codigo_v4,
                codigo_v6=alvo.codigo_v6, gate_nome=alvo.gate_nome,
                classe_import_id=ids.get(alvo.classe_import or ""),
                parametros=alvo.parametros or None,
                origem="adotado", origem_snapshot_id=snapshot_id,
            )
        )
    for regra in proposta.plano.regras_import:
        if regra.classe not in ids:
            raise ValidationError(
                f"A regra de importação do papel `{regra.papel}` aponta para a classe "
                f"`{regra.classe}`, que não está na proposta."
            )
        session.add(
            models.CommunityImportRule(
                papel=regra.papel, afi=regra.afi, classe_id=ids[regra.classe],
                condicao=regra.condicao, notas=regra.notas,
                origem="adotado", origem_snapshot_id=snapshot_id,
            )
        )

    registrar(
        session, tipo="community_plan.adopt", ator=actor, objeto="community_plan",
        objeto_id=plano.id, antes=None,
        depois={
            "asn_principal": plano.asn_principal,
            "device_id": device_id, "snapshot_id": snapshot_id,
            "classes": len(proposta.plano.classes),
            "instrucoes": len(ids_instrucoes),
            "portoes": len(proposta.plano.portoes),
            "alvos": [a.nome for a in proposta.plano.alvos],
            "parados": list(proposta.parados),
            "divergencias": [d.codigo for d in proposta.divergencias],
        },
    )
    session.commit()
    session.refresh(plano)
    return plano


def _resolve_instrucoes(
    session: Session, instrucoes: tuple[InstrucaoPlano, ...], *, snapshot_id: int | None
) -> dict[int, int]:
    """Cria as instruções que faltam e devolve código → id."""
    ids: dict[int, int] = {}
    for instrucao in instrucoes:
        existente = session.scalar(
            select(models.Community).where(models.Community.codigo == instrucao.codigo)
        )
        if existente is not None:
            ids[instrucao.codigo] = existente.id
            continue
        nova = models.Community(
            name=instrucao.nome, tipo=instrucao.tipo, banda="instrucao",
            codigo=instrucao.codigo, notes=instrucao.notas, origem="adotado",
            origem_snapshot_id=snapshot_id,
        )
        session.add(nova)
        session.flush()
        ids[instrucao.codigo] = nova.id
    return ids
