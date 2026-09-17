"""O plano de communities na SoT: ler, propor, validar e adotar (spec §9).

A escrita é uma transação só, como a adoção de peer da descoberta: o plano é um
objeto coerente e uma adoção pela metade deixaria classes sem portão. Qualquer
recusa desfaz tudo. Nada aqui vai ao equipamento — o único caminho é o snapshot
já coletado, e mudar o roteador continua sendo change request.
"""
from collections.abc import Collection, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation.community_plan import (
    VOCABULARIO,
    Achado,
    AlvoPlano,
    ClassePlano,
    InstrucaoPlano,
    PlanoLido,
    PortaoPlano,
    PropostaPlano,
    RegraImportPlano,
    # "Quem aplica" e "quem testa" também são do motor, e pelo mesmo motivo: a
    # página (§11) e a checagem 1 (§8.1) têm de dizer a mesma coisa sobre o mesmo
    # filtro. O predicado é o prefixo (`aplica`/`aplica-large`, `testa`/`testa-large`)
    # e o corpo do corpus citado vem resolvido de lá.
    _aplicados_e_testados,
    # A leitura posicional do código (`<asn>:<codigo>`) é do motor, e é uma só: duas
    # respostas para a mesma pergunta já custou uma rodada de fix na T4.
    _codigo_do_valor,
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
from gerenet.domain.schemas import (
    AlvoPlanoOut,
    ClassePlanoOut,
    InstrucaoPlanoOut,
    PlanoOut,
    PortaoPlanoOut,
)
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


def equipamentos_com_coleta(session: Session) -> list[int]:
    """Os equipamentos com snapshot gravado — o universo da validação sem filtro.

    Ter snapshot **não** é ter leitura: o arquivo da configuração pode ter sumido
    depois da coleta (`texto_backup` devolve "" no `OSError`) e aí o
    `ler_do_snapshot` recusa. Quem precisa comparar chama o `ler_do_snapshot`;
    esta lista diz só onde procurar.
    """
    return list(session.scalars(select(models.DeviceSnapshot.device_id).distinct()).all())


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
    """ASN da organização → tipo do upstream, para o papel do alvo (Regra 5).

    Só passa o tipo que `TARGET_PAPEL` tem. O `Upstream.tipo` aceita
    `contingencia` e o enum de `community_targets.papel` não, então sem este
    recorte o papel sairia da SoT como `contingencia` e o INSERT do alvo
    estouraria no enum (500 na rota da T7). O alvo de um upstream de contingência
    fica sem papel da SoT e quem decide é o leitor, pelo nome do grupo: a cadeia
    `da_sot or do_nome or "transito"` já existe, e o `papel_duvidoso` continua
    avisando quando os dois discordam.
    """
    papeis: dict[int, str] = {}
    linhas = session.execute(
        select(models.Organization.asn, models.Upstream.tipo)
        .join(models.Upstream, models.Upstream.organization_id == models.Organization.id)
    ).all()
    for asn, tipo in linhas:
        if asn is not None and tipo in models.TARGET_PAPEL:
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
    """O que a adoção gravaria, lido do snapshot — sem escrever nada.

    Além das divergências do motor, a proposta carrega os membros de portão que
    não resolvem para classe nenhuma (R29): o que resolve aqui é o mesmo que a
    adoção materializa — as classes da proposta, o `VOCABULARIO` inteiro e o que
    já tem linha de classe em `communities` (R34). Assim a proposta e a escrita
    dizem a mesma coisa sobre quem entra no portão.
    """
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
    membros = [
        (portao.nome, (*portao.aceitas, *portao.recusadas))
        for portao in proposta.plano.portoes
    ]
    return PropostaPlano(
        plano=PlanoLido(**{**proposta.plano.__dict__, "snapshot_id": snap.id}),
        divergencias=proposta.divergencias + _membros_sem_classe(
            membros,
            nomes=_nomes_que_resolvem(session, proposta.plano.classes),
            codigos=_codigos_das_classes((*proposta.plano.classes, *VOCABULARIO)),
        ),
        parados=proposta.parados, avisos=proposta.avisos,
    )


def _asn_do_equipamento(session: Session, device_id: int) -> int | None:
    device = session.get(models.Device, device_id)
    return device.asn if device is not None else None


def validar_plano(session: Session, device_ids: list[int] | None = None) -> tuple[Achado, ...]:
    """As oito checagens sobre o plano ativo e a configuração coletada.

    Sem `device_ids`, valida contra todos os equipamentos que têm coleta — é o
    que a página mostra, porque a comparação que importa é entre a borda e o VS.

    Ao fim vêm os membros de portão que não têm classe (R29), a superfície durável
    do achado: o plano da SoT guarda a lista de **ids**, então o membro que se
    perdeu na adoção não está em lugar nenhum do plano para ser comparado — quem
    ainda o tem é a configuração, e é ela que a comparação percorre. O valor sem
    código parseável entra por aqui também (R34): ele é o `888` ou o nome solto
    que o `if codigo is None` deixava passar sem achado nenhum.
    """
    plano = obter_plano(session)
    if plano is None:
        return ()
    if device_ids is None:
        device_ids = equipamentos_com_coleta(session)
    leituras: list[LeituraCommunities] = []
    direcoes: dict[str, str] = {}
    for device_id in device_ids:
        leitura = _leitura_do_device(session, device_id)
        if leitura is None:
            continue
        leituras.append(leitura)
        direcoes.update(direcoes_do_device(session, device_id))
    achados = validar(
        plano, leituras, direcoes=direcoes,
        estados_alvo=estados_dos_alvos(session, leituras, device_ids),
    )
    membros = [
        (uso.filtro, uso.valores)
        for leitura in leituras
        for uso in leitura.usos
        if uso.operacao == "testa" and uso.filtro.startswith("RouteExportCheck")
    ]
    return achados + _membros_sem_classe(
        membros,
        nomes=_nomes_que_resolvem(session, plano.classes),
        codigos=_codigos_das_classes((*plano.classes, *VOCABULARIO)),
    )


def _id_da_classe(session: Session, classe: ClassePlano, *, snapshot_id: int | None) -> int:
    """O id da linha de `communities` da classe, criando-a se ela faltar.

    A busca é por nome e, não achando, por **valor** (namespace-agnóstico), como a
    do motor: `61785:3001` e `65000:3001` são a mesma classe (Regra 1). A segunda
    busca não é detalhe: o índice único parcial de `valor_v4` recusaria o INSERT se
    o valor já tivesse virado linha com outro nome.
    """
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
        return existente.id
    nova = models.Community(
        name=classe.nome, tipo=classe.tipo, banda=classe.banda, valor_v4=classe.valor_v4,
        valor_v6=classe.valor_v6, notes=classe.notas, origem="adotado",
        origem_snapshot_id=snapshot_id,
    )
    session.add(nova)
    session.flush()
    return nova.id


def _nomes_citados(plano: PlanoLido) -> list[str]:
    """Os nomes que os filhos do plano citam: os membros de portão e a importação."""
    return [
        *[n for portao in plano.portoes for n in (*portao.aceitas, *portao.recusadas)],
        *[alvo.classe_import for alvo in plano.alvos if alvo.classe_import],
    ]


def _codigos_das_classes(classes: Sequence[ClassePlano]) -> set[int]:
    """Os códigos que têm linha de classe, dos dois lados do par (`v4` e `v6`)."""
    return {v for c in classes for v in (c.valor_v4, c.valor_v6) if v is not None}


def _classes_com_linha(session: Session) -> dict[str, int]:
    """Nome → id das linhas de **classe** que já existem em `communities` (R34).

    A linha de instrução (`codigo` preenchido) fica de fora: a lista do portão
    guarda ids de classe, e um nome de instrução citado num portão não é membro
    que a adoção resolva — ele sai no `portao_membro_sem_classe` como qualquer
    outro que não resolva. O achado não pode dizer que a linha não existe (ela
    existe), só que ela não é classe.
    """
    return dict(
        session.execute(
            select(models.Community.name, models.Community.id).where(
                models.Community.codigo.is_(None)
            )
        ).all()
    )


def _nomes_que_resolvem(session: Session, classes: Sequence[ClassePlano]) -> set[str]:
    """Os nomes com destino na adoção: as classes, o `VOCABULARIO` e o já gravado.

    É a metade "nome" do predicado do R34; a metade "código" é o
    `_codigos_das_classes`. As duas superfícies montam o universo do mesmo jeito
    e só o alimentam com entradas diferentes: a proposta recebe da leitura os
    nomes que o motor já resolveu (`_nome_do_valor`) e a validação recebe os
    valores crus da configuração.
    """
    return (
        {classe.nome for classe in classes}
        | {classe.nome for classe in VOCABULARIO}
        | set(_classes_com_linha(session))
    )


def _membros_sem_classe(
    membros: Sequence[tuple[str, Sequence[str]]],
    *,
    nomes: Collection[str],
    codigos: Collection[int],
) -> tuple[Achado, ...]:
    """Os valores de portão que não resolvem para classe nenhuma (R29/R34).

    `membros` é (nome do portão, valores), `codigos` é o conjunto de códigos que
    já têm linha de classe e `nomes` é o dos nomes com destino — as classes, o
    `VOCABULARIO` e as linhas de classe já gravadas. Um membro **resolve** quando
    o código dele está em `codigos` ou quando o valor é um desses nomes; fora
    disso ele sai daqui.

    O achado existe porque a lista do portão guarda **ids** de `communities`
    (§4.4): sem linha não há id para gravar, e o membro sumiria do portão adotado
    sem que ninguém visse. O `codigo is None` era o terceiro jeito de sumir (R34):
    o valor sem código parseável não era nem procurado por nome, e um `888` ou um
    nome solto saía daqui sem virar nada. O caso dos literais crus da captura real
    (`61785:7012` e `61785:7112`, que a §5 registra como valores em migração para
    7101/7102/7103) segue sendo o do valor que não tem definição nenhuma no
    equipamento: não há nome por onde resolvê-lo.
    """
    achados: list[Achado] = []
    for nome, valores in membros:
        for valor in dict.fromkeys(valores):
            codigo = _codigo_do_valor(valor)
            if valor in nomes or (codigo is not None and codigo in codigos):
                continue
            achados.append(
                Achado(
                    codigo="portao_membro_sem_classe", severidade="atencao",
                    valor=valor, filtro=nome,
                    descricao=(
                        f"{valor} é testado por {nome} e não tem classe no vocabulário: "
                        "sem linha de classe em `communities` o membro não tem id para "
                        "gravar na lista do portão"
                    ),
                    acao="declarar a classe (a edição do plano é a F2) ou confirmar "
                         "que o valor sai do portão",
                )
            )
    return tuple(achados)


def _resolve_classes(
    session: Session,
    classes: tuple[ClassePlano, ...],
    citados: Sequence[str],
    *,
    snapshot_id: int | None,
) -> dict[str, int]:
    """Cria as classes que faltam e devolve nome → id.

    As classes da proposta entram primeiro. Depois vêm os **nomes citados** por
    portão e por alvo que ainda não resolveram: a §9.1 diz que `communities` vira o
    vocabulário, então nome citado sem linha é linha que falta. O `com-TAMANHO-2`
    do portão `RouteExportCheck` e o `com-ONLY-CDN` da recusa dele não estão nas
    classes da proposta (nenhuma definição do equipamento os nomeia) e, sem esta
    passada, o portão era gravado sem eles em silêncio (R29).

    O nome que **já tem linha de classe** reaproveita a linha em vez de ganhar
    outra (R34): era o último jeito de o membro sumir sem achado — o `no-export`
    do catálogo semeado não está no `VOCABULARIO` e era descartado aqui. Recriar
    a linha também não serviria: o índice único de `name` recusaria a segunda.
    """
    ids: dict[str, int] = {}
    for classe in classes:
        ids[classe.nome] = _id_da_classe(session, classe, snapshot_id=snapshot_id)
    do_vocabulario = {classe.nome: classe for classe in VOCABULARIO}
    com_linha = _classes_com_linha(session)
    for nome in citados:
        if nome in ids:
            continue
        if nome in com_linha:
            ids[nome] = com_linha[nome]
            continue
        classe = do_vocabulario.get(nome)
        if classe is None:
            continue  # literal sem vocabulário: sai em `portao_membro_sem_classe`
        ids[nome] = _id_da_classe(session, classe, snapshot_id=snapshot_id)
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

    Sem ASN principal na proposta recusa com `ValidationError`, também antes de
    escrever (R31): é o caso do equipamento sem `devices.asn` cuja configuração
    não declara `bgp <asn>`, e o `INSERT` do cabeçalho estouraria o NOT NULL.

    Os membros de portão que não resolvem para classe nenhuma ficam de fora da
    lista (R29): a §9 manda a adoção não decidir colisão sozinha nem renomear
    nada, e recusar por causa deles barraria a adoção do NE8000 real. Eles saem
    como `portao_membro_sem_classe` na proposta e na validação. O nome que já tem
    linha de classe, esse entra — reaproveitando a linha (R34), porque recriá-la
    esbarraria no índice único de `name`.
    """
    if proposta.plano.asn_principal is None:
        # Antes da guarda do plano ativo, e não junto dela: sem ASN o cabeçalho
        # não tem o que gravar, e a guarda responderia outra pergunta ("o plano
        # ativo é de outro ASN") com um `None` que não é ASN de ninguém.
        raise ValidationError(
            f"O equipamento {device_id} não tem ASN: preencha o ASN do equipamento "
            "antes de adotar o plano, porque o plano guarda o ASN principal."
        )

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
        session, proposta.plano.classes, _nomes_citados(proposta.plano),
        snapshot_id=snapshot_id,
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
                # `dict.fromkeys` sem repetir: dois valores do mesmo portão
                # podem ser a mesma classe (7002 e 7102 são `com-TAMANHO-2`), e
                # a lista de ids não guarda o valor que a gerou (R29c).
                aceitas=[ids[n] for n in dict.fromkeys(portao.aceitas) if n in ids],
                recusadas=[ids[n] for n in dict.fromkeys(portao.recusadas) if n in ids],
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
            # R35: as linhas de classe que a adoção usou, e não as classes da
            # proposta — os nomes citados que só o `VOCABULARIO` conhece também
            # viram linha (§9.1) e a trilha registrava menos do que foi gravado.
            "classes": len(ids),
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


def montar_plano_out(session: Session, plano: PlanoLido) -> PlanoOut:
    """O plano com quem aplica e quem testa cada classe (spec §11).

    A contagem sai da leitura da configuração: é a mesma verdade que a validação
    usa, apresentada onde ela é consultada. "A mesma verdade" é literal — quem
    separa os usos é o `_aplicados_e_testados` do motor, que já resolve o corpo do
    corpus citado (`apply community com-EXPORT-UPSTREAM-v4` aplica o `61785:3001`
    da lista, não o nome dela). Sem ele a tabela de classes diria "ninguém" para
    a classe que a checagem 1 acusa aplicada e não testada, e as duas superfícies
    da mesma tela se contradiriam sobre o mesmo plano.
    """
    device_ids = list(session.scalars(select(models.DeviceSnapshot.device_id).distinct()).all())
    aplicam: dict[str, list[str]] = {}
    testam: dict[str, list[str]] = {}
    # As leituras são lidas uma vez e servem às duas pontas: a contagem de quem
    # aplica/testa e o estado dos alvos (que sai dos membros que cada leitura achou).
    leituras = [
        leitura for leitura in (_leitura_do_device(session, i) for i in device_ids) if leitura
    ]
    estados = estados_dos_alvos(session, leituras, device_ids)
    aplicados, testados = _aplicados_e_testados(leituras)
    for usos, por_classe in ((aplicados, aplicam), (testados, testam)):
        for uso in usos:
            if not uso.valores:
                continue
            for valor in uso.valores:
                if valor.count(":") != 1:
                    continue
                _, _, campo = valor.partition(":")
                if not campo.isdigit():
                    continue  # valor nomeado (`AS-X:FOO`), que não é código de classe
                codigo = int(campo)
                for classe in plano.classes:
                    if codigo in (classe.valor_v4, classe.valor_v6):
                        por_classe.setdefault(classe.nome, []).append(uso.filtro)
    return PlanoOut(
        asn_principal=plano.asn_principal,
        asns_anunciados=[dict(a) for a in plano.asns_anunciados],
        observacoes=plano.observacoes, snapshot_id=plano.snapshot_id,
        classes=[
            ClassePlanoOut(
                nome=c.nome, banda=c.banda, tipo=c.tipo, valor_v4=c.valor_v4,
                valor_v6=c.valor_v6, id=c.id, notas=c.notas,
                aplicam=sorted(set(aplicam.get(c.nome, []))),
                testam=sorted(set(testam.get(c.nome, []))),
            )
            for c in plano.classes
        ],
        instrucoes=[InstrucaoPlanoOut(**i.__dict__) for i in plano.instrucoes],
        portoes=[
            PortaoPlanoOut(nome=g.nome, papel=g.papel, afi=g.afi, padrao=g.padrao,
                           aceitas=list(g.aceitas), recusadas=list(g.recusadas))
            for g in plano.portoes
        ],
        alvos=[
            AlvoPlanoOut(nome=a.nome, papel=a.papel, codigo_v4=a.codigo_v4, codigo_v6=a.codigo_v6,
                         gate_nome=a.gate_nome, classe_import=a.classe_import,
                         parametros=a.parametros, estado=estados.get(a.nome, "ausente"))
            for a in plano.alvos
        ],
    )


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
