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
from gerenet.domain.services.organizations import _confere_nome_livre, create_organization
from gerenet.domain.services.prefix_authorizations import create_authorization
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
    dados = next((s for s in proposta.sessoes if s["afi"] == overrides.afi), None)
    if dados is None:
        # A revisão pediu uma família que o enlace não tem: `ValidationError` (400)
        # e não um `StopIteration` no meio da escrita.
        raise ValidationError(
            f"A proposta não tem sessão {overrides.afi}: a revisão pediu uma família "
            "que o enlace não tem."
        )
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


def perfis_da_revisao(revisao: schemas.AdocaoIn) -> dict[str, dict[str, int | None]]:
    """Os perfis que a revisão escolheu, por família (o mapa que o ensaio lê).

    Quem mostra o diff tem de montar este mapa com os MESMOS valores: o corpo da
    política de exportação que o ensaio emite sai daqui, e uma conferência
    feita com outro mapa compara algo que a adoção não vai gravar — o
    `adopt` do CLI imprime o diff antes de escrever, e imprime o que ele
    próprio vai usar.
    """
    return {
        s.afi: {"import_profile_id": s.import_profile_id,
                "export_profile_id": s.export_profile_id}
        for s in revisao.sessoes
    }


def adotar_proposta(session: Session, *, proposta, revisao: schemas.AdocaoIn, actor: str) -> int:
    """Grava a cadeia de uma proposta na SoT, numa transação (design §5).

    Uma transação só, e é por isso que os serviços de cadastro são chamados com
    `commit=False`: se qualquer passo recusar, nada fica gravado. Nenhum comando
    vai ao equipamento; mudar o roteador continua exigindo change request.

    Quatro guardas são defesa em profundidade: VRF, candidato, site e ASN remoto.
    Numa proposta vinda de `listar_propostas` cada um desses casos já virou
    conflito (ou diferença de contexto `ensaio`) e quem recusa é uma guarda
    anterior, então nenhuma delas é caminho vivo na listagem.

    A guarda da identidade é outra coisa: pelo CLI a proposta sai dos argumentos
    e o arquivo é livre, então ela é caminho vivo — a revisão de um equipamento
    adotada no outro passaria com o `ciente` dela liberando o gate das diferenças
    deste, e é a identidade errada que ficaria gravada (§6). Ela vem primeiro
    porque é do pedido, e não do estado da proposta.
    """
    # Import tardio: `automation.discovery` importa este módulo (a lista de
    # ignorados), e no topo o ciclo derruba quem importa este módulo primeiro.
    from gerenet.automation.discovery import _trunk_da_subinterface, conferir_fidelidade

    for campo, do_arquivo, da_proposta in (
        ("device_id", revisao.device_id, proposta.device_id),
        ("vrf", revisao.vrf, proposta.vrf),
        ("subinterface", revisao.subinterface, proposta.subinterface),
    ):
        if do_arquivo != da_proposta:
            raise ValidationError(
                f"A revisão não é desta proposta: {campo} do arquivo é "
                f"{do_arquivo!r} e o da proposta é {da_proposta!r}. A revisão de um "
                "enlace não vale no outro."
            )
    if proposta.veredito == "nao_adotavel":
        raise ConflictError(
            "A proposta tem conflito: resolva antes de adotar ("
            + "; ".join(f"{c.tipo}: {c.descricao}" for c in proposta.conflitos) + ")."
        )
    if proposta.vrf is not None:
        # Sombreada: o peer em VRF já chega como `vrf_nao_renderizavel`.
        raise ConflictError(
            "Sessão em VRF não é reproduzível por esta versão do render: a adoção "
            "gravaria uma sessão que o equipamento não tem nessa instância."
        )
    # O trunk é recusado antes da conferência: o ensaio deriva `<trunk>.<vid>` do
    # nome da subinterface e a escrita grava o `edge_trunk` da revisão. Vazio, o
    # circuito nasce sem o bloco da subinterface que o operador acabou de
    # conferir — a conferência precisa dos dois lados iguais (design §6).
    trunk = _trunk_da_subinterface(proposta)
    if trunk is not None and not revisao.edge_trunk:
        raise ValidationError(
            f"A revisão precisa do trunk de acesso: informe edge_trunk como {trunk}. "
            f"Sem ele o circuito nasce sem o bloco da subinterface {trunk}.{proposta.vid}, "
            "que é o que a conferência comparou."
        )
    # Sessão a menos é peer que nunca entra no `_conhecidos`: a descoberta
    # devolveria a mesma subinterface para sempre, agora com `vlan_tomada`.
    faltando = sorted({s["afi"] for s in proposta.sessoes} - {s.afi for s in revisao.sessoes})
    if faltando:
        raise ValidationError(
            "A revisão não cobre " + ", ".join(faltando) + " do enlace: sem a sessão, o "
            "peer fica fora da SoT e a descoberta devolve o mesmo enlace para sempre."
        )
    # O nome da organização nova é conferido ANTES da conferência de fidelidade:
    # o ensaio cria a organização descartável com esse nome (é ele que a
    # `description` da subinterface carrega) e o `flush` dele bate na unicidade
    # do §14.1 quando o nome já tem dono. Sem esta guarda a recusa chegava como
    # `AVISO_SEM_ENSAIO` — a frase que manda o operador procurar reserva de VLAN
    # e de endereço —, e a escrita, que é quem recusa de verdade, nunca era
    # alcançada para dizer o nome do conflito. O `create_organization` confere o
    # mesmo antes do `flush` dele; aqui a adoção não passa pelo serviço antes da
    # conferência, então a checagem é feita por ela.
    if revisao.organizacao_id is None and revisao.organizacao_nova is not None:
        _confere_nome_livre(session, revisao.organizacao_nova.name)
    # O que o operador escolheu entra na conferência: sem os perfis o ensaio não
    # renderiza o corpo da política de exportação, que é justamente o que ele
    # escolhe errado; sem o trunk, a comparação não vale para o que vai gravar.
    # A identidade (o código, a organização, a velocidade e o `kind` dela) entra
    # pela mesma razão: é dela que a `description` da subinterface e o `qos car`
    # saem, e um ensaio com a identidade do `ENSAIO-...` acusaria diferença em
    # toda adoção. As autorizações entram porque são elas que fazem o ensaio
    # emitir o filtro de importação: sem elas, o `import route-policy` que o
    # equipamento tem apareceria como diferença e o `ciente` seria cobrado sobre
    # a linha que esta mesma escrita cria.
    perfis = perfis_da_revisao(revisao)
    difs = conferir_fidelidade(
        session, proposta, perfis=perfis, edge_trunk=revisao.edge_trunk,
        circuit_code=revisao.circuit_code, organizacao_id=revisao.organizacao_id,
        organizacao_nome=revisao.organizacao_nova.name if revisao.organizacao_nova else None,
        organizacao_kind=revisao.organizacao_nova.kind if revisao.organizacao_nova else None,
        autorizacoes=[(b.prefix, b.family) for b in revisao.autorizacoes],
        velocidade_mbps=revisao.velocidade_mbps,
    )
    ensaio = [d for d in difs if d.contexto == "ensaio"]
    if ensaio:
        # A `explicacao` é a frase escrita para o operador (o ensaio recusado, o
        # peer em VRF, a proposta sem site): sem ela a recusa não diz o que fazer.
        detalhe = "; ".join(d.explicacao for d in ensaio if d.explicacao)
        raise ConflictError(
            "A conferência não pôde ser feita para esta proposta"
            + (f": {detalhe}" if detalhe else ".")
        )
    if any(d.exige_ciente for d in difs) and not revisao.ciente:
        raise ValidationError(
            "Há diferenças que mudariam o equipamento: confirme o ciente para adotar."
        )
    if not proposta.candidatos:
        # Sombreada: proposta sem candidato é órfã, e a órfã nasce com conflito.
        raise ValidationError("A proposta não tem candidato: nada a adotar.")
    if proposta.site_id is None:
        # Sombreada: sem site a conferência devolve a diferença de `ensaio`.
        raise ValidationError("O equipamento não está vinculado a um site.")
    asn_remoto = proposta.candidatos[0].asn_remote
    if asn_remoto is None:
        # Sombreada: o ASN que falta já vira conflito na classificação do peer.
        raise ValidationError("A proposta não tem ASN remoto: não há sessão a criar.")

    organizacao_id = revisao.organizacao_id
    if organizacao_id is None and revisao.organizacao_nova is None:
        raise ValidationError(
            "Informe a organização: escolha uma existente ou crie a nova com o ASN "
            f"{asn_remoto}."
        )
    if revisao.autorizacoes and revisao.organizacao_id is not None:
        raise ValidationError(
            "As autorizações de prefixo só entram com a organização nova: para uma "
            "organização existente, cadastre os blocos na página dela."
        )

    # O `stack` sai das sessões que vão nascer, e não do que a proposta sugeriu: o
    # circuito gravado não pode afirmar uma família que não tem sessão. Para a
    # proposta da listagem a guarda das famílias acima já garante que os dois
    # valores coincidem, então isto é defesa em profundidade, como as guardas
    # seguintes. Sem sessão nenhuma (proposta montada à mão) não há o que derivar.
    afis = sorted({s.afi for s in revisao.sessoes})
    if not afis:
        stack = proposta.stack
    elif len(afis) > 1:
        stack = "dual"
    else:
        stack = afis[0]

    try:
        if organizacao_id is None:
            org = create_organization(
                session, revisao.organizacao_nova, actor=actor, commit=False
            )
            organizacao_id = org.id

        # Os blocos do registro entram na MESMA transação (§6 do design): a
        # organização nova e o que ela pode anunciar nascem juntos, e o clique
        # que aprovou a lista é o aceite humano do §6.4. A procedência fica
        # gravada para uma auditoria futura saber o que veio da máquina.
        for bloco in revisao.autorizacoes:
            create_authorization(
                session,
                schemas.PrefixAuthorizationCreate(
                    organization_id=organizacao_id,
                    family=bloco.family,
                    prefix=bloco.prefix,
                    origin="registro",
                    notes=f"Bloco do registro para AS{asn_remoto}, lido na adoção.",
                ),
                actor=actor,
                commit=False,
            )

        circuito = create_circuit(
            session,
            schemas.CircuitCreate(
                code=revisao.circuit_code, organization_id=organizacao_id,
                site_id=proposta.site_id,
                access_device_id=revisao.access_device_id, access_port=revisao.access_port,
                edge_device_id=proposta.device_id, edge_trunk=revisao.edge_trunk,
                stack=stack, vlan_mode=proposta.vlan_mode, qinq=proposta.qinq,
                p2p_v4_len=proposta.p2p_v4_len or 31, vrf=proposta.vrf,
                velocidade_mbps=revisao.velocidade_mbps,
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
                "edge_trunk": revisao.edge_trunk,
                "snapshot_id": proposta.candidatos[0].snapshot_id,
                "ciente": revisao.ciente,
                "perfis": perfis,
                # A lista que o operador aprovou no clique, para a trilha do
                # aceite (§6.4) — cada autorização tem o `authorization.create`
                # dela, e isto é o que amarra a lista ao que a originou.
                "autorizacoes": [
                    {"prefix": b.prefix, "family": b.family} for b in revisao.autorizacoes
                ],
                # Todas as diferenças, e não só as que o `ciente` assumiu: o grupo
                # que a SoT não gerencia é o que o operador viu e não precisou
                # aceitar, e o payload é trilha, não decisão (design §17.1). Quem
                # gateia o aceite continua sendo só o `exige_ciente`.
                "diferencas": [
                    {"contexto": d.contexto, "sobrando": list(d.sobrando),
                     "faltando": list(d.faltando),
                     "nao_gerenciado": list(d.nao_gerenciado),
                     "explicacao": d.explicacao}
                    for d in difs
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
