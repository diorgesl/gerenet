# Fase 4 (parte 2) — pendências do L2VC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Destravar a execução do L2VC em switch real (coleta do estado do par LDP), habilitar rollback e reconciliação da CR de escopo `l2vc`, e completar o pós-check com MTU fim a fim e estado do AC.

**Architecture:** O recurso de coleta `mpls_ldp_peer` ganha um segundo comando (`display mpls ldp session`) e o merge passa a cruzar as duas tabelas por `PeerID`, sem mudar o gate de recursos nem o pré-check. O `gerar_rollback` e o `_replaneja` do serviço de change requests passam a conhecer o escopo `l2vc`, derivando o plano da coleta atual (não do baseline pré-mudança). O parser de L2VC passa a extrair `AC status` e os MTUs local/remoto, e o pós-check a validá-los.

**Tech Stack:** Python 3.13, SQLAlchemy, FastAPI, TextFSM, pytest, ruff, React + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-13-gerenet-fase4-l2vc-pendencias-design.md`

## Global Constraints

- Artefatos em português (PT-BR): nomes de teste, docstrings, mensagens de commit e comentários.
- Sem segredos em código, fixtures ou planos (regra §19 da spec do produto).
- Comandos de verificação: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build && npm run test`.
- Implementação em worktree isolada (regra do CLAUDE.md global), criada antes do primeiro commit de código.
- Never claim a test passes without running it.

---

### Task 1: Sessão LDP na coleta e no merge

**Files:**
- Create: `src/gerenet/automation/parsers/huawei_vrp/textfsm/mpls_ldp_session.template`
- Modify: `src/gerenet/automation/collectors.py` (bloco `mpls_ldp_peer`, linhas 43-47)
- Modify: `src/gerenet/automation/parsers/huawei_vrp/merge.py` (`normaliza_ldp`, linhas 104-122)
- Test: `tests/automation/test_parsers_mpls.py`

**Interfaces:**
- Consumes: fixture `tests/fixtures/huawei_vrp/s6730_display_mpls_ldp_session.txt` (já commitada).
- Produces: template `mpls_ldp_session`, cujas linhas são `{"peer_id": "100.127.90.251:0", "status": "Operational"}`. O recurso `mpls_ldp_peer` continua `list[{"peer_id": str, "estado": str | None}]`, agora com `estado` em `"up"`/`"down"`/`None`. Nada mais no repo lê esse recurso além de `valida_pre_checks_l2vc`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/automation/test_parsers_mpls.py`, adicione ao final do arquivo:

```python
def test_mpls_ldp_session_vazio() -> None:
    assert parse_template("mpls_ldp_session", "") == []


def test_mpls_ldp_session_real() -> None:
    """S6730: tabela PeerID/Status/LAM/SsnRole/SsnAge/KASent-Rcv, 8 sessões."""
    linhas = parse_template("mpls_ldp_session", _real("s6730_display_mpls_ldp_session.txt"))
    assert len(linhas) == 8
    assert {"peer_id": "100.127.90.251:0", "status": "Operational"} in linhas
    assert {"peer_id": "100.127.90.10:0", "status": "Operational"} in linhas


def test_mpls_ldp_session_sessao_em_remocao() -> None:
    """O `*` de sessão em deleção não entra no peer_id."""
    saida = (
        " PeerID             Status      LAM  SsnRole  SsnAge      KASent/Rcv\n"
        "*10.255.9.2:0       Operational DU   Passive  0000:00:02  5/5\n"
    )
    assert parse_template("mpls_ldp_session", saida) == [
        {"peer_id": "10.255.9.2:0", "status": "Operational"},
    ]


def test_merge_ldp_cruza_peer_e_sessao() -> None:
    """Sessão Operational ⇒ up; outro status ⇒ down; peer sem linha ⇒ None."""
    assert merge_parsed("mpls_ldp_peer", {
        "display mpls ldp peer": [
            {"peer_id": "100.127.90.251:0", "transport": "100.127.90.251", "discovery": "Eth-Trunk9"},
            {"peer_id": "100.127.90.253:0", "transport": "100.127.90.253", "discovery": "Remote Peer"},
            {"peer_id": "100.127.90.254:0", "transport": "100.127.90.254", "discovery": "Vlanif10"},
        ],
        "display mpls ldp session": [
            {"peer_id": "100.127.90.251:0", "status": "Operational"},
            {"peer_id": "100.127.90.253:0", "status": "Initialized"},
        ],
    }) == [
        {"peer_id": "100.127.90.251", "estado": "up"},
        {"peer_id": "100.127.90.253", "estado": "down"},
        {"peer_id": "100.127.90.254", "estado": None},
    ]


def test_merge_ldp_fixtures_reais_casam_por_peer() -> None:
    """As duas fixtures reais do S6730 têm os mesmos 8 peers, todos Operational."""
    linhas = merge_parsed("mpls_ldp_peer", {
        "display mpls ldp peer": parse_template("mpls_ldp_peer", _real("s6730_display_mpls_ldp_peer.txt")),
        "display mpls ldp session": parse_template("mpls_ldp_session", _real("s6730_display_mpls_ldp_session.txt")),
    })
    assert len(linhas) == 8
    assert {l["estado"] for l in linhas} == {"up"}
    assert {l["peer_id"] for l in linhas} == {
        "100.127.90.251", "100.127.90.253", "100.127.90.254", "100.127.90.255",
        "100.127.90.2", "100.127.90.3", "100.127.90.5", "100.127.90.10",
    }


def test_merge_ldp_sessao_sem_peer_na_tabela_e_ignorada() -> None:
    assert merge_parsed("mpls_ldp_peer", {
        "display mpls ldp peer": [
            {"peer_id": "10.255.9.2:0", "transport": "10.255.9.2", "discovery": "Vlanif10"},
        ],
        "display mpls ldp session": [
            {"peer_id": "10.255.9.2:0", "status": "Operational"},
            {"peer_id": "10.255.9.9:0", "status": "Operational"},
        ],
    }) == [{"peer_id": "10.255.9.2", "estado": "up"}]
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `uv run pytest tests/automation/test_parsers_mpls.py -q -k "ldp_session or cruza_peer or fixtures_reais or sem_peer_na_tabela"`
Expected: FAIL — `FileNotFoundError` para `mpls_ldp_session.template` e má comparação nos testes de merge (o merge atual devolve `estado: None` para todos).

- [ ] **Step 3: Criar o template**

Arquivo `src/gerenet/automation/parsers/huawei_vrp/textfsm/mpls_ldp_session.template`:

```
Value peer_id (\d+\.\d+\.\d+\.\d+:\d+)
Value status (\S+)

Start
  ^\s*\*?\s*${peer_id}\s+${status}(\s+.*)?$$ -> Record
```

- [ ] **Step 4: Implementar o merge cruzado**

Em `src/gerenet/automation/parsers/huawei_vrp/merge.py`, substitua a função `normaliza_ldp` inteira (linhas 104-122) por:

```python
def normaliza_ldp(por_comando: dict[str, list[dict]]) -> list[dict]:
    """`display mpls ldp peer` + `display mpls ldp session` -> peers com estado.

    A tabela de peer da família S não imprime estado; ele vem da tabela de sessão
    (`Operational` = up). Peer listado pelo comando de peer sem linha na sessão
    fica `estado=None` (desconhecido) — nunca "down" por omissão. Quando o próprio
    comando de peer imprime estado (outras famílias), ele é o fallback. O sufixo
    `:0` do LDP ID sai dos dois lados. Keys: {peer_id, estado}; linhas sem
    peer_id são descartadas.
    """
    peers = por_comando.get("display mpls ldp peer")
    if peers is None:
        peers = _primeiras_linhas(por_comando)
    estados: dict[str, str | None] = {}
    for linha in por_comando.get("display mpls ldp session", []):
        peer = str(linha.get("peer_id", "")).split(":")[0].strip()
        if peer and linha.get("status"):
            estados[peer] = (
                "up" if str(linha["status"]).strip().lower() == "operational" else "down"
            )
    saida: list[dict] = []
    for linha in peers:
        peer = str(linha.get("peer_id", "")).split(":")[0].strip()
        if not peer:
            continue
        if peer in estados:
            estado: str | None = estados[peer]
        else:
            estado = {"up": "up", "down": "down"}.get(str(linha.get("estado") or "").lower())
        saida.append({"peer_id": peer, "estado": estado})
    return saida
```

- [ ] **Step 5: Estender o coletor**

Em `src/gerenet/automation/collectors.py`, troque o bloco `mpls_ldp_peer` (linhas 43-47) por:

```python
    "mpls_ldp_peer": {
        "commands": ["display mpls ldp peer", "display mpls ldp session"],
        "parsers": {
            "display mpls ldp peer": "mpls_ldp_peer",
            "display mpls ldp session": "mpls_ldp_session",
        },
        "merge": "mpls_ldp_peer",
    },
```

- [ ] **Step 6: Rodar os testes do arquivo inteiro**

Run: `uv run pytest tests/automation/test_parsers_mpls.py -q`
Expected: PASS, incluindo os testes antigos `test_merge_ldp_tabela_sem_estado_vira_none` e `test_merge_ldp_normaliza_estado_impresso` (o fallback preserva os dois comportamentos).

- [ ] **Step 7: Rodar a suíte de automação e o lint**

Run: `uv run pytest tests/automation tests/worker -q && uv run ruff check src tests`
Expected: PASS e `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/automation/parsers/huawei_vrp/textfsm/mpls_ldp_session.template \
        src/gerenet/automation/parsers/huawei_vrp/merge.py \
        src/gerenet/automation/collectors.py tests/automation/test_parsers_mpls.py
git commit -m "feat(mpls): coleta e merge do estado do par LDP (display mpls ldp session)"
```

---

### Task 2: Rollback de CR de remoção com o plano certo (circuito e upstream)

**Files:**
- Modify: `src/gerenet/domain/services/change_requests.py` (`_replaneja`, linhas 325-348; `gerar_rollback`, linhas 410-438)
- Test: `tests/domain/test_change_requests.py`, `tests/domain/test_change_requests_upstream.py`

**Interfaces:**
- Produces: `_replaneja(session, cr, device_id, *, acao: str | None = None) -> changes.PlanoDevice` — com `acao=None` mantém o comportamento atual (usado pelo `reconciliar`); com `acao` explícito planeja a ação pedida. O `gerar_rollback` passa a chamar com a ação do filho.
- Consumes: `changes.plan_provision`, `changes.plan_remocao`, `up_auto.plan_provision_upstream`, `up_auto.plan_remocao_upstream`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/domain/test_change_requests.py`, adicione ao final:

```python
def test_rollback_de_remocao_gera_filho_provision_com_blocos_de_criacao(db_session, tmp_path):
    """Rollback de uma CR de remoção replaneja o provisionamento (§12.4).

    Regressão: o filho nascia com `acao="provision"` mas recebia os blocos
    `delete` do plano do pai (undo ...), executando remoção outra vez.
    """
    circ, dev = _circuito_reservado(db_session)
    _sessao(db_session, circ, dev)
    _snapshot_encontrado(db_session, dev, tmp_path)
    cr, _ = _cria_cr(db_session, circ, acao="remove")
    cr.status = "aplicado"
    cr.steps[0].status = "aplicado"
    db_session.commit()
    filho = crsvc.gerar_rollback(
        db_session, cr.id, ator_id=_usuario(db_session, "exe-rem", "executor").id, actor="executor",
    )
    assert filho.acao == "provision"
    assert filho.steps
    assert all(
        c["acao"] == "create" for s in filho.steps for c in s.plano_json
    )
```

Em `tests/domain/test_change_requests_upstream.py`, adicione ao final:

```python
def test_rollback_de_remocao_upstream_gera_filho_provision(
    db_session, up_com_2_circuitos, edge_device
):
    """Mesma correção do circuito: o filho do rollback recebe blocos de criação."""
    up = up_com_2_circuitos
    _snapshot_peers_up(db_session, edge_device, [])
    cr = _cr_upstream(db_session, up, acao="remove")
    cr.status = "aplicado"
    for step in cr.steps:
        step.status = "aplicado"
    db_session.commit()
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert filho.acao == "provision"
    assert filho.steps
    assert all(c["acao"] == "create" for s in filho.steps for c in s.plano_json)
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `uv run pytest tests/domain/test_change_requests.py -q -k rollback_de_remocao && uv run pytest tests/domain/test_change_requests_upstream.py -q -k rollback_de_remocao`
Expected: FAIL nos dois, com blocos de `acao` `"delete"` em vez de `"create"`.

- [ ] **Step 3: Parametrizar a ação no `_replaneja`**

Em `src/gerenet/domain/services/change_requests.py`, troque a assinatura e a primeira linha do corpo:

```python
def _replaneja(
    session: Session, cr: models.ChangeRequest, device_id: int, *, acao: str | None = None,
) -> changes.PlanoDevice:
    """Plano de um device na ação pedida (`acao=None` = ação da própria CR).

    O `gerar_rollback` passa a ação do filho: planejar o passo com a ação do pai
    entregava blocos `delete` a uma CR de provisionamento (§12.4).
    """
    acao = acao or cr.acao
```

E troque as três comparações de ação do corpo para usar a variável local:

```python
        plano = (
            up_auto.plan_provision_upstream(session, up)
            if acao == "provision"
            else up_auto.plan_remocao_upstream(session, up)
        )
```

```python
    if acao == "provision":
        plano = changes.plan_provision(session, circ)
    else:
        plano = changes.plan_remocao(session, circ)
```

- [ ] **Step 4: Usar a ação do filho no `gerar_rollback`**

No ramo `else` do laço de steps (o de CR pai `remove`), troque a chamada:

```python
        else:
            item = _replaneja(session, cr, step.device_id, acao=filho.acao)
```

- [ ] **Step 5: Rodar e confirmar que passam**

Run: `uv run pytest tests/domain/test_change_requests.py tests/domain/test_change_requests_upstream.py tests/domain/test_change_requests_l2vc.py -q`
Expected: PASS, inclusive `test_rollback_gera_cr_filho_inverso` (o caminho de `provision` não muda) e as reconciliações existentes.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/change_requests.py tests/domain/test_change_requests.py \
        tests/domain/test_change_requests_upstream.py
git commit -m "fix(changes): rollback de CR de remoção planeja o provisionamento do filho"
```

---

### Task 3: Rollback e reconciliação da CR de escopo `l2vc`

**Files:**
- Modify: `src/gerenet/domain/services/change_requests.py` (`_RECONCILIA_INDISPONIVEL` e `_ROLLBACK_INDISPONIVEL`, linhas 38-61; `_replaneja`, `gerar_rollback`)
- Test: `tests/domain/test_change_requests_l2vc.py`

**Interfaces:**
- Consumes: `_replaneja(..., acao=...)` da Task 2; `automation.l2vc.plan_provision_l2vc`, `plan_remocao_l2vc`; `domain.services.mpls.get_l2vc`.
- Produces: `reconciliar` e `gerar_rollback` funcionam para `escopo="l2vc"`; `escopo="vsi"` continua com `ValidationError` apontando a Frente B.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/domain/test_change_requests_l2vc.py`, adicione ao final (o arquivo já tem a fixture `l2vc`, que devolve `(d1, d2, svc)`):

```python
def _snapshot(db_session, dev, recursos):
    from gerenet.domain import models
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success", resources=recursos,
        errors={}, raw_files={}, duration_ms=0,
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def _recursos(interface, l2vc_linhas):
    return {"interfaces": [{"nome": interface, "phy": "up", "protocolo": "up"}],
            "l2vc": l2vc_linhas, "mpls_ldp_peer": [], "config_backup": ""}


def _cr_aplicada(db_session, svc, acao, device_ids):
    from gerenet.domain.services.change_requests import create_change_request
    cr = create_change_request(db_session, ChangeRequestCreate(
        escopo="l2vc", l2vc_id=svc.id, acao=acao, motivo="teste de rollback.",
    ), ator_id=None)
    cr.status = "aplicado"
    for step in cr.steps:
        step.status = "aplicado" if step.device_id in device_ids else "falhou"
    db_session.commit()
    return cr


def test_rollback_l2vc_provision_gera_filho_remove(db_session, l2vc):
    """Provision aplicado nas duas pontas ⇒ filho remove com `undo mpls l2vc` nas duas."""
    from gerenet.domain.services.change_requests import gerar_rollback
    d1, d2, svc = l2vc
    # o encontrado mostra o VC nas duas pontas: o rollback deriva da coleta atual
    _snapshot(db_session, d1, _recursos("10GE0/0/1", [
        {"vc_id": 500, "interface": "10GE0/0/1", "estado": "up"},
    ]))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", [
        {"vc_id": 500, "interface": "10GE0/0/2", "estado": "up"},
    ]))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id, d2.id})
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert filho.escopo == "l2vc"
    assert filho.l2vc_id == svc.id
    assert filho.circuit_id is None
    assert filho.acao == "remove"
    assert filho.status == "aguardando_aprovacao"
    assert filho.rollback_de == cr.id
    assert {s.device_id for s in filho.steps} == {d1.id, d2.id}
    comandos = [c for s in filho.steps for b in s.plano_json for c in b["comandos"]]
    assert comandos.count("undo mpls l2vc 10.255.8.2 500") == 1
    assert comandos.count("undo mpls l2vc 10.255.8.1 500") == 1


def test_rollback_l2vc_parcial_so_na_ponta_aplicada(db_session, l2vc):
    """Só a ponta aplicada ganha step: a outra não tem VC para remover."""
    from gerenet.domain.services.change_requests import gerar_rollback
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", [
        {"vc_id": 500, "interface": "10GE0/0/1", "estado": "up"},
    ]))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id})
    filho = gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
    assert [s.device_id for s in filho.steps] == [d1.id]


def test_rollback_l2vc_sem_encontrado_eh_plano_vazio(db_session, l2vc):
    """Nada do serviço consta na coleta: nada persiste (PlanoRollbackVazio)."""
    from gerenet.domain.services.change_requests import gerar_rollback
    from gerenet.domain.services.errors import PlanoRollbackVazio
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", []))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id, d2.id})
    with pytest.raises(PlanoRollbackVazio):
        gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")


def test_reconciliar_l2vc_recomputa_ponta_pendente(db_session, l2vc):
    """CR l2vc em erro volta a aguardando_aprovacao com o step pendente replanejado."""
    from gerenet.domain.services.change_requests import reconciliar
    d1, d2, svc = l2vc
    _snapshot(db_session, d1, _recursos("10GE0/0/1", []))
    _snapshot(db_session, d2, _recursos("10GE0/0/2", []))
    cr = _cr_aplicada(db_session, svc, "provision", {d1.id})
    cr.status = "erro"
    db_session.commit()
    cr = reconciliar(db_session, cr.id, actor="cli")
    assert cr.status == "aguardando_aprovacao"
    pendente = next(s for s in cr.steps if s.device_id == d2.id)
    assert pendente.status == "pendente"
    assert pendente.erro is None
    assert pendente.plano_json


def test_rollback_e_reconciliar_de_vsi_seguem_indisponiveis(db_session):
    """O escopo vsi continua barrado até a Frente B (mensagem própria)."""
    from gerenet.domain import models
    from gerenet.domain.services.change_requests import gerar_rollback, reconciliar
    from gerenet.domain.services.errors import ValidationError
    dom = create_domain(db_session, MplsDomainCreate(name="dom-vsi-msg"), actor="cli")
    vsi = models.VsiService(
        domain_id=dom.id, vsi_id=900, name="vsi-msg", vrp_name="VSI-MSG-900",
    )
    db_session.add(vsi)
    db_session.commit()
    cr = models.ChangeRequest(
        circuit_id=None, l2vc_id=None, escopo="vsi", acao="provision",
        status="erro", motivo="msg", solicitante_id=None,
    )
    db_session.add(cr)
    db_session.commit()
    with pytest.raises(ValidationError, match="fase posterior"):
        reconciliar(db_session, cr.id, actor="cli")
    with pytest.raises(ValidationError, match="fase posterior"):
        gerar_rollback(db_session, cr.id, ator_id=None, actor="cli")
```

Nota: o teste do VSI usa `models.ChangeRequest` direto porque não existe caminho de criação de CR de VSI (é o que a Frente B implementa).

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `uv run pytest tests/domain/test_change_requests_l2vc.py -q -k "rollback or reconciliar"`
Expected: FAIL com `ValidationError` "Rollback automático indisponível para CR de escopo l2vc" nos quatro primeiros; o teste do VSI já passa.

- [ ] **Step 3: Liberar o escopo no serviço**

Em `src/gerenet/domain/services/change_requests.py`, remova a chave `"l2vc"` dos dois dicionários e ajuste o comentário acima deles para:

```python
# Escopos SEM reconciliação/rollback automáticos (mensagem própria por escopo):
# o vsi é multiponto e o provisionamento entra na frente seguinte à fase 4.
_RECONCILIA_INDISPONIVEL = {
    "vsi": (
        "Reconciliação automática indisponível para CR de escopo vsi — "
        "provisionamento multiponto em fase posterior."
    ),
}
_ROLLBACK_INDISPONIVEL = {
    "vsi": (
        "Rollback automático indisponível para CR de escopo vsi — "
        "provisionamento multiponto em fase posterior."
    ),
}
```

- [ ] **Step 4: Adicionar o ramo l2vc ao `_replaneja`**

Logo depois do bloco `if cr.escopo == "upstream":` (que termina com o `return changes.PlanoDevice(...)`), insira:

```python
    if cr.escopo == "l2vc":
        from gerenet.automation import l2vc as l2vc_auto
        from gerenet.domain.services.mpls import get_l2vc

        svc = get_l2vc(session, cr.l2vc_id)
        plano = (
            l2vc_auto.plan_provision_l2vc(session, svc)
            if acao == "provision"
            else l2vc_auto.plan_remocao_l2vc(session, svc)
        )
        for item in plano:
            if item.device_id == device_id:
                return item
        return changes.PlanoDevice(device_id=device_id, blocos=[], baseline_snapshot_id=None)
```

- [ ] **Step 5: Adicionar o ramo l2vc ao `gerar_rollback`**

Entre o ramo `if cr.escopo == "upstream":` e o `else:` que trata circuito, insira:

```python
    elif cr.escopo == "l2vc":
        filho = models.ChangeRequest(
            circuit_id=None, l2vc_id=cr.l2vc_id, escopo="l2vc",
            acao="remove" if cr.acao == "provision" else "provision",
            criticidade=cr.criticidade, motivo=f"Rollback do CR #{cr.id}",
            solicitante_id=ator_id, status="aguardando_aprovacao", rollback_de=cr.id,
        )
```

E no laço de steps, antes do `if cr.acao == "provision":`, insira o ramo que deriva da coleta atual e descarta step sem bloco:

```python
        if cr.escopo == "l2vc":
            item = _replaneja(session, cr, step.device_id, acao=filho.acao)
            if not item.blocos:
                continue  # ponta sem o serviço no encontrado: nada a desfazer
            session.add(models.ChangeStep(
                change_request_id=filho.id, device_id=step.device_id, status="pendente",
                plano_json=item.blocos, baseline_snapshot_id=item.baseline_snapshot_id,
                aviso=item.aviso,
            ))
            continue
```

O `if not filho.steps: raise PlanoRollbackVazio(...)` que já existe cobre o caso de nenhuma ponta ter o serviço no encontrado.

- [ ] **Step 6: Rodar e confirmar que passam**

Run: `uv run pytest tests/domain/test_change_requests_l2vc.py -q`
Expected: PASS nos testes novos e nos antigos (`test_cr_l2vc_nasce_com_2_steps`, `test_cr_l2vc_exige_l2vc_id`, `test_cr_l2vc_desativado`, `test_cr_l2vc_remocao_plano_vazio_sem_snapshot_da_remocao`, `test_cr_circuito_default_inalterada`).

- [ ] **Step 7: Rodar a suíte de domínio, API e CLI**

Run: `uv run pytest tests/domain tests/api tests/cli -q`
Expected: PASS. Verificado em 2026-09-13: nenhum teste existente afirma que o escopo `l2vc` é barrado, então a mudança não deve quebrar API nem CLI.

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/domain/services/change_requests.py tests/domain/test_change_requests_l2vc.py
git commit -m "feat(changes): rollback e reconciliação para CR de escopo l2vc"
```

---

### Task 4: Parser de L2VC com AC e MTU, e pós-check do §13.2

**Files:**
- Modify: `src/gerenet/automation/parsers/huawei_vrp/textfsm/l2vc.template`
- Modify: `src/gerenet/automation/parsers/huawei_vrp/merge.py` (`normaliza_l2vc`)
- Modify: `src/gerenet/automation/l2vc.py` (`valida_pos_l2vc`)
- Test: `tests/automation/test_parsers_mpls.py`, `tests/automation/test_l2vc.py`

**Interfaces:**
- Produces: linhas do recurso `l2vc` passam a ser `{vc_id: int, interface: str | None, estado: str, ac_status: str | None, mtu_local: int | None, mtu_remoto: int | None}`; `valida_pos_l2vc` devolve itens `atencao` para AC não-up e divergência de MTU.
- Consumes: `l2vc_services.mtu` e `service_endpoints.mtu` via `service.endpoints`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/automation/test_parsers_mpls.py`, atualize `test_l2vc_blocos_reais` para as novas chaves e acrescente:

```python
def test_l2vc_blocos_reais() -> None:
    """S6730: bloco por VC com AC status e MTU local/remoto (fixture real)."""
    linhas = parse_template("l2vc", _real("s6730_display_mpls_l2vc.txt"))
    assert len(linhas) == 4
    assert {"vc_id": "21", "interface": "Vlanif21", "estado": "up", "ac_status": "up",
            "mtu_local": "9216", "mtu_remoto": "9216"} in linhas
    assert {"vc_id": "627", "interface": "Vlanif627", "estado": "down", "ac_status": "up",
            "mtu_local": "9216", "mtu_remoto": "0"} in linhas


def test_merge_l2vc_extrai_ac_e_mtu() -> None:
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "21", "interface": "Vlanif21", "estado": "up", "ac_status": "up",
         "mtu_local": "9216", "mtu_remoto": "9216"},
    ]}) == [{"vc_id": 21, "interface": "Vlanif21", "estado": "up",
             "ac_status": "up", "mtu_local": 9216, "mtu_remoto": 9216}]


def test_merge_l2vc_sem_mtu_fica_none() -> None:
    """Bloco sem as linhas de MTU/AC não inventa valor."""
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "1000", "interface": None, "estado": "Down"},
    ]}) == [{"vc_id": 1000, "interface": None, "estado": "down",
             "ac_status": None, "mtu_local": None, "mtu_remoto": None}]
```

E atualize o teste de merge existente `test_merge_l2vc_normaliza_blocos` para incluir as chaves novas (as duas entradas do assert passam a ser):

```python
    ]) == [
        {"vc_id": 21, "interface": "Vlanif21", "estado": "up",
         "ac_status": None, "mtu_local": None, "mtu_remoto": None},
        {"vc_id": 627, "interface": "Vlanif627", "estado": "down",
         "ac_status": None, "mtu_local": None, "mtu_remoto": None},
    ]
    assert merge_parsed("l2vc", {"display mpls l2vc": [
        {"vc_id": "1000", "interface": None, "estado": "Down"},
    ]}) == [{"vc_id": 1000, "interface": None, "estado": "down",
             "ac_status": None, "mtu_local": None, "mtu_remoto": None}]
```

Em `tests/automation/test_l2vc.py`, adicione ao final (o arquivo já tem a fixture `servico`, que devolve `(d1, d2, svc)` com `mtu=1500` nas duas pontas, e o helper `_snapshot(db_session, dev, recursos)`):

```python
def _pos_snapshot(db_session, dev, **campos):
    linha = {"vc_id": 1000, "interface": "10GE0/0/1", "estado": "up",
             "ac_status": "up", "mtu_local": 1500, "mtu_remoto": 1500}
    linha.update(campos)
    return _snapshot(db_session, dev, {
        "interfaces": [{"nome": "10GE0/0/1", "phy": "up", "protocolo": "up"}],
        "l2vc": [linha], "mpls_ldp_peer": [], "config_backup": "",
    })


def test_pos_check_mtu_divergente_e_atencao(servico, db_session):
    d1, _, svc = servico
    snap = _pos_snapshot(db_session, d1, mtu_local=9216, mtu_remoto=9216)
    itens = l2vc.valida_pos_l2vc(db_session, svc, snap)
    tipos = {i["tipo"]: i for i in itens}
    assert tipos["l2vc.mtu"].get("severidade") == "atencao"
    assert not any(i["severidade"] == "critica" for i in itens)


def test_pos_check_mtu_assimetrico_e_atencao(servico, db_session):
    d1, _, svc = servico
    snap = _pos_snapshot(db_session, d1, mtu_local=1500, mtu_remoto=9216)
    itens = l2vc.valida_pos_l2vc(db_session, svc, snap)
    assert any(i["tipo"] == "l2vc.mtu_simetria" and i["severidade"] == "atencao" for i in itens)


def test_pos_check_ac_fora_do_up_e_atencao(servico, db_session):
    d1, _, svc = servico
    snap = _pos_snapshot(db_session, d1, ac_status="down")
    itens = l2vc.valida_pos_l2vc(db_session, svc, snap)
    assert any(i["tipo"] == "l2vc.ac" and i["severidade"] == "atencao" for i in itens)


def test_pos_check_mtu_ignorado_com_vc_down(servico, db_session):
    """VC down já é item crítico; o MTU não gera ruído em cima dele."""
    d1, _, svc = servico
    snap = _pos_snapshot(db_session, d1, estado="down", mtu_remoto=0)
    itens = l2vc.valida_pos_l2vc(db_session, svc, snap)
    assert any(i["tipo"] == "l2vc.estado" and i["severidade"] == "critica" for i in itens)
    assert not any(i["tipo"].startswith("l2vc.mtu") for i in itens)
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `uv run pytest tests/automation/test_parsers_mpls.py tests/automation/test_l2vc.py -q -k "l2vc or pos_check"`
Expected: FAIL — chaves `ac_status`/`mtu_local`/`mtu_remoto` ausentes no parse e no merge, e os itens de pós-check inexistentes.

- [ ] **Step 3: Estender o template**

Arquivo `src/gerenet/automation/parsers/huawei_vrp/textfsm/l2vc.template`. O `Record` sai da linha do `VC ID` e passa para a linha do MTU, que é a última das que interessam e vem depois do `VC ID` no bloco. Premissa registrada: todo bloco imprime `local VC MTU` (verdade na fixture real do S6730, com os 4 VCs, inclusive os dois `down`); um bloco que não imprimisse essa linha não fecharia registro e o VC sumiria do snapshot. O runbook (Task 6) confere isso no equipamento, e é o sintoma a investigar se um VC aparecer como ausente para sempre.

```
Value vc_id (\d+)
Value interface (\S+)
Value estado (\S+)
Value ac_status (\S+)
Value mtu_local (\d+)
Value mtu_remoto (\d+)

Start
  ^\s*\*?\s*client interface\s*:\s*${interface}\s+is\s+\S+\s*$$ -> Continue
  ^\s*AC status\s*:\s*${ac_status}\s*$$ -> Continue
  ^\s*VC state\s*:\s*${estado}\s*$$ -> Continue
  ^\s*VC ID\s*:\s*${vc_id}\s*$$ -> Continue
  ^\s*local VC MTU\s*:\s*${mtu_local}\s+remote VC MTU\s*:\s*${mtu_remoto}\s*$$ -> Record
```

- [ ] **Step 4: Estender o merge**

Em `src/gerenet/automation/parsers/huawei_vrp/merge.py`, substitua `normaliza_l2vc` por:

```python
def normaliza_l2vc(por_comando: dict[str, list[dict]]) -> list[dict]:
    """`display l2vc` -> vc_id int, interface, estado e os campos do §13.2.

    Keys: {vc_id, interface, estado, ac_status, mtu_local, mtu_remoto}; campo
    ausente no bloco vira None (não inventa valor) e linha sem vc_id é
    descartada. O MTU é int quando impresso (o VRP imprime `0` em VC down).
    """
    def _int(valor: object) -> int | None:
        return int(valor) if valor not in (None, "") else None

    saida: list[dict] = []
    for linha in _primeiras_linhas(por_comando):
        vc = linha.get("vc_id")
        if vc is None:
            continue
        saida.append({
            "vc_id": int(vc),
            "interface": linha.get("interface"),
            "estado": "up" if str(linha.get("estado", "")).lower() == "up" else "down",
            "ac_status": linha.get("ac_status") or None,
            "mtu_local": _int(linha.get("mtu_local")),
            "mtu_remoto": _int(linha.get("mtu_remoto")),
        })
    return saida
```

- [ ] **Step 5: Estender o pós-check**

Em `src/gerenet/automation/l2vc.py`, substitua `valida_pos_l2vc` por:

```python
def valida_pos_l2vc(
    session: Session, service: models.L2vcService, snapshot: models.DeviceSnapshot,
) -> list[dict]:
    """Pós-check §13 — VC e AC na coleta pós-aplicação, com MTU fim a fim (§9.2).

    VC ausente ou fora de `up` é crítico. AC fora de `up` e MTU divergente do
    configurado ou assimétrico entre as pontas são `atencao` — o MTU só é
    conferido com o VC de pé, porque o VRP imprime `0` no remoto de um VC down.
    """
    recursos = snapshot.resources or {}
    linhas = [l for l in recursos.get("l2vc", []) if l.get("vc_id") == service.vc_id]
    achada = linhas[0] if linhas else None
    items: list[dict] = []
    if achada is None:
        items.append({
            "tipo": "l2vc.ausente", "severidade": "critica",
            "esperado": f"{service.name} (vc {service.vc_id})", "encontrado": "não listado",
            "acao": "Verificar config do AC e revalidar (display mpls l2vc).",
        })
        return items
    if str(achada.get("estado", "")).lower() != "up":
        items.append({
            "tipo": "l2vc.estado", "severidade": "critica",
            "esperado": "up", "encontrado": str(achada.get("estado")),
            "acao": "Verificar estado do pseudowire/AC (LDP up, MTU, encap simétrico).",
        })
        return items
    ac = achada.get("ac_status")
    if ac is not None and str(ac).lower() != "up":
        items.append({
            "tipo": "l2vc.ac", "severidade": "atencao",
            "esperado": "up", "encontrado": str(ac),
            "acao": "Conferir o AC desta ponta (display mpls l2vc).",
        })
    ep = next((e for e in service.endpoints if e.device_id == snapshot.device_id), None)
    esperado_mtu = (ep.mtu or service.mtu) if ep is not None else service.mtu
    local, remoto = achada.get("mtu_local"), achada.get("mtu_remoto")
    if local is not None and local != esperado_mtu:
        items.append({
            "tipo": "l2vc.mtu", "severidade": "atencao",
            "esperado": str(esperado_mtu), "encontrado": str(local),
            "acao": "Conferir o `mtu` do AC e reaplicar se preciso (§9.2).",
        })
    if local is not None and remoto is not None and local != remoto:
        items.append({
            "tipo": "l2vc.mtu_simetria", "severidade": "atencao",
            "esperado": f"MTU igual nas pontas ({local})", "encontrado": str(remoto),
            "acao": "Conferir o MTU da ponta remota (§9.2).",
        })
    return items
```

- [ ] **Step 6: Rodar e confirmar que passam**

Run: `uv run pytest tests/automation/test_parsers_mpls.py tests/automation/test_l2vc.py tests/automation/test_runner_l2vc.py tests/worker -q`
Expected: PASS. Se algum runner test quebrar, é por causa das chaves novas do recurso `l2vc`; ajuste o snapshot do teste, não o código.

- [ ] **Step 7: Lint e suíte completa de automação**

Run: `uv run pytest tests/automation -q && uv run ruff check src tests`
Expected: PASS e `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add src/gerenet/automation/parsers/huawei_vrp/textfsm/l2vc.template \
        src/gerenet/automation/parsers/huawei_vrp/merge.py src/gerenet/automation/l2vc.py \
        tests/automation/test_parsers_mpls.py tests/automation/test_l2vc.py
git commit -m "feat(l2vc): pós-check de MTU fim a fim e do estado do AC"
```

---

### Task 5: Web — liberar rollback e reconciliação para CR de escopo l2vc

**Files:**
- Modify: `web/src/pages/ChangeRequestDetail.tsx` (`escopoComFluxo`, ~linha 36; mensagem do diálogo de rollback, ~linha 58)
- Test: `web/src/pages/ChangeRequestDetail.test.tsx`

**Interfaces:**
- Consumes: `ChangeRequestOut.escopo` (`"circuito" | "l2vc" | "upstream" | "vsi"`); endpoints `POST /api/v1/change-requests/{id}/rollback` e `/reconciliar`.
- Produces: `escopoComFluxo` devolve `true` para `l2vc`; botões visíveis conforme status e papel.

- [ ] **Step 1: Escrever os testes que falham**

Em `web/src/pages/ChangeRequestDetail.test.tsx`, adicione dentro do `describe("ChangeRequestDetail", ...)`:

```tsx
  it("mostra Gerar rollback numa CR de escopo l2vc aplicada", async () => {
    crAtual = {
      ...crDe(2, "aplicado"),
      circuit_id: null, escopo: "l2vc", l2vc_id: 1, l2vc_name: "L2VC-0001",
    };
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.getByRole("button", { name: "Gerar rollback" })).toBeInTheDocument();
  });

  it("mostra Reconciliar numa CR de escopo l2vc com erro", async () => {
    crAtual = {
      ...crDe(2, "erro"),
      circuit_id: null, escopo: "l2vc", l2vc_id: 1, l2vc_name: "L2VC-0001",
    };
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.getByRole("button", { name: "Reconciliar" })).toBeInTheDocument();
  });

  it("não mostra Reconciliar numa CR de escopo vsi com erro", async () => {
    crAtual = {
      ...crDe(2, "erro"),
      circuit_id: null, escopo: "vsi", l2vc_id: null, l2vc_name: null,
    };
    renderDetail();
    await screen.findByText("Change request #1");
    expect(screen.queryByRole("button", { name: "Reconciliar" })).toBeNull();
  });
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd web && npx vitest run src/pages/ChangeRequestDetail.test.tsx`
Expected: FAIL nos dois primeiros (botão não encontrado) e PASS no terceiro.

- [ ] **Step 3: Liberar o escopo**

Em `web/src/pages/ChangeRequestDetail.tsx`, troque a função e o comentário:

```tsx
// Escopos com Reconciliar/Rollback: circuito, l2vc e upstream têm o fluxo no
// serviço, na API e na CLI. O vsi entra quando o provisionamento multiponto
// existir (frente seguinte à fase 4).
function escopoComFluxo(cr: ChangeRequestOut): boolean {
  return cr.escopo === "circuito" || cr.escopo === "l2vc" || cr.escopo === "upstream";
}
```

- [ ] **Step 4: Ajustar a mensagem do diálogo de rollback**

A mensagem atual promete "a partir do snapshot anterior à mudança", que não vale para o L2VC (deriva da coleta atual). Troque por:

```tsx
  rollback: {
    titulo: "Gerar rollback?",
    mensagem: "Uma nova CR inversa (aguardando_aprovacao) será criada para desfazer a mudança.",
  },
```

- [ ] **Step 5: Rodar os testes do arquivo e o build**

Run: `cd web && npx vitest run src/pages/ChangeRequestDetail.test.tsx && npm run build`
Expected: PASS nos testes e build sem erro de TypeScript.

- [ ] **Step 6: Rodar a suíte web inteira**

Run: `cd web && npm run test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/ChangeRequestDetail.tsx web/src/pages/ChangeRequestDetail.test.tsx
git commit -m "feat(web): rollback e reconciliação visíveis em CR de escopo l2vc"
```

---

### Task 6: Runbook e estado do repositório

**Files:**
- Modify: `docs/runbook-validacao-switch-mpls.md` (seção do rollback, ~linhas 215-230; roteiro da etapa 1)
- Modify: `CLAUDE.md` (seção "Estado do repositório")

**Interfaces:**
- Consumes: tudo que as Tasks 1 a 5 produziram.
- Produces: documentação alinhada ao comportamento novo.

- [ ] **Step 1: Atualizar a seção de rollback do runbook**

Substitua o parágrafo que diz que o rollback automatizado de CR de escopo `l2vc` não está implementado pelo texto abaixo, mantendo o tom do arquivo:

```markdown
O rollback e a reconciliação de CR de escopo `l2vc` **estão implementados**:
`gerenet change-requests rollback <cr>` cria a CR inversa em `aguardando_aprovacao`
com os blocos derivados da **coleta atual** (o filho remove as pontas onde o VC
consta no snapshot e não gera step para ponta ausente), e
`gerenet change-requests reconcile <cr>` recomputa as pontas pendentes de uma CR
em `erro`/`parcial`. A derivação por coleta atual (em vez do baseline pré-mudança,
como no circuito) é decisão registrada no design de 2026-09-13: num L2VC novo o
baseline não contém o VC e o plano sairia vazio.
```

- [ ] **Step 2: Acrescentar a conferência da etapa 1**

Na checklist da etapa 1 (somente leitura), junto da linha do `display mpls ldp peer`, adicione:

```markdown
- [ ] `display mpls ldp session`: a tabela `PeerID/Status` casa com os peers do comando anterior e o `estado` do peer no snapshot deixa de ser `None` (parser `mpls_ldp_session`).
- [ ] `local VC MTU` de um VC existente diz se o campo reflete o `mtu` configurado no AC ou o MTU físico — decisão registrada no design de 2026-09-13 (se for o físico, o check de MTU do pós-check vira só simetria entre pontas).
- [ ] Todo bloco de `display mpls l2vc` (incluindo VC `down`) imprime a linha `local VC MTU`/`remote VC MTU`: é a linha em que o parser fecha o registro. Bloco sem ela não entra no snapshot e o VC aparece como ausente na divergência — se isso acontecer, o parser precisa de outra âncora de registro.
```

- [ ] **Step 3: Atualizar o estado do repositório no CLAUDE.md**

Na seção "Estado do repositório", acrescente um bullet no mesmo estilo dos anteriores:

```markdown
- Fase 4, parte 2 (pendências do L2VC, 2026-09-13): a coleta do recurso
  `mpls_ldp_peer` passou a rodar também `display mpls ldp session` (parser
  `mpls_ldp_session`, merge cruzando por `PeerID` sem o `:0`), o que destrava o
  pré-check do L2VC que antes parava em "estado desconhecido"; o rollback e a
  reconciliação de CR de escopo `l2vc` passaram a existir (`gerar_rollback`
  deriva o plano da **coleta atual** e o `_replaneja` aceita a ação como
  parâmetro), e a web mostra os botões para esse escopo; o parser de L2VC passou
  a extrair `AC status` e MTU local/remoto e o pós-check a validá-los
  (`l2vc.ac`, `l2vc.mtu`, `l2vc.mtu_simetria`, todos `atencao`, com o MTU só
  conferido com o VC de pé). Corrigido de passagem: o rollback de CR de remoção
  (circuito e upstream) planejava o filho com a ação do pai e recebia blocos
  `delete`. O provisionamento VSI multiponto segue como frente seguinte
  (rollback/reconciliação de `vsi` continuam indisponíveis).
```

- [ ] **Step 4: Verificar que o build da wiki não quebra**

Run: `uv run pytest tests/api -q -k wiki`
Expected: PASS (as páginas da wiki carregam do `docs/wiki/`, que não muda nesta task; o teste garante que nada de markdown foi quebrado por engano).

- [ ] **Step 5: Commit**

```bash
git add docs/runbook-validacao-switch-mpls.md CLAUDE.md
git commit -m "docs(fase4): runbook e estado do repositório das pendências do L2VC"
```

---

## Verificação final

- [ ] `uv run pytest -q` — suíte completa verde.
- [ ] `uv run ruff check src tests` — sem avisos.
- [ ] `cd web && npm run build && npm run test` — build e Vitest verdes.
- [ ] Revisar o diff acumulado contra a spec, seção por seção (§3, §4, §5, §6).
