# Fim da colisão de linha: sessões BGP por peer — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A colisão de sessões BGP deixa de ser "quantas sessões o equipamento e a VRF carregam" e passa a ser o peer: outra sessão ativa com o mesmo endereço remoto na mesma VRF do equipamento.

**Architecture:** Uma função do serviço de sessões muda de nome e de chave (`_colidente_linha` → `_colidente_peer`), com os mesmos dois chamadores (`create_session` e `update_session`), e a mensagem de conflito ganha a redação nova. O `_colidente_par` e o `_vrf_texto` ficam como estão. Sem migração, sem schema novo, sem dependência nova: a regra sempre foi de serviço. Depois do código, os quatro textos que descrevem a regra (spec §14.1, wiki, tooltip da web, CLAUDE.md) acompanham.

**Tech Stack:** Python 3 (SQLAlchemy 2, pytest, ruff); React + Vite só para o texto do tooltip.

**Spec:** `docs/superpowers/specs/2026-09-16-gerenet-sessao-bgp-por-equipamento-design.md`

## Global Constraints

- Idioma dos artefatos: português (PT-BR), inclusive mensagens de erro.
- Sem dependência nova, sem migração alembic e sem mudança de schema.
- A mensagem de conflito nova, verbatim:
  `Já existe sessão ativa no equipamento {device.name} para o peer {endereço remoto} (VRF {_vrf_texto(circ)}).`
- `_colidente_par` e `_vrf_texto` não mudam.
- A comparação do endereço remoto é pela forma canônica (`int(ipaddress.ip_address(...))`), como o `_colidente_par` já faz.
- Verificação: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build && npm run test`.
- Commits em PT-BR, terminando com `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

---

### Task 1: O serviço de sessões colide por peer

**Files:**
- Modify: `src/gerenet/domain/services/bgp_sessions.py` (a função em `:52-75`, os dois chamadores em `:184` e `:324`)
- Test: `tests/domain/test_bgp_sessions_service.py` (`:177`, `:199`, `:416`, `:434`)

**Interfaces:**
- Consumes: `models.BgpSession`, `models.Circuit`, `select`, `ipaddress`, `ConflictError`, todos já importados no módulo; as fixtures `db_session` e os helpers `_ambiente`, `_circuito`, `_sessao_data`, `list_sessions` do arquivo de teste.
- Produces: `_colidente_peer(session, *, device_id: int, vrf: str | None, remote_address: str, ignorar_id: int | None = None) -> models.BgpSession | None`.

- [ ] **Step 1: Reescrever os testes**

No `tests/domain/test_bgp_sessions_service.py`, substituir o bloco do `test_duplicidade_mesmo_device_vrf_afi` (`:177-184`) por estes três testes:

```python
def test_varias_sessoes_no_mesmo_device_vrf_familia(db_session: Session) -> None:
    """Dois enlaces no mesmo equipamento, VRF e família, com peers distintos."""
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0007", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ2 = _circuito(db_session, env, code="CIRC-0008", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    a = create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    b = create_session(
        db_session,
        _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.5", remote="100.64.0.6"),
        actor="cli",
    )
    ativas = {s.id for s in list_sessions(db_session, device_id=env["ne1_id"])}
    assert ativas == {a.id, b.id}


def test_mesmo_peer_no_mesmo_device_vrf_colide(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0040", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ2 = _circuito(db_session, env, code="CIRC-0041", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    # o mesmo endereço remoto, em outro circuito e na mesma VRF, é o mesmo peer
    with pytest.raises(
        ConflictError,
        match=r"Já existe sessão ativa no equipamento ne8k-bgp1 para o peer 100\.64\.0\.2",
    ):
        create_session(
            db_session,
            _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.9", remote="100.64.0.2"),
            actor="cli",
        )


def test_mesmo_peer_em_vrf_diferente_convive(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_a = _circuito(db_session, env, code="CIRC-0042", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    circ_b = _circuito(db_session, env, code="CIRC-0043", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ_a, env["ne1_id"]), actor="cli")
    sessao = create_session(
        db_session,
        _sessao_data(env, circ_b, env["ne1_id"], local="100.64.0.9", remote="100.64.0.2"),
        actor="cli",
    )
    assert sessao.id  # a VRF é parte da identidade do peer no VRP
```

(`test_mesmo_peer_em_vrf_diferente_convive` passa antes e depois da correção: com o `_colidente_peer` sem o filtro de VRF ele quebra, e é esse o erro que ele guarda.)

Substituir o corpo do `test_duplicidade_mensagem_vrf_publica` (`:199-205`) por:

```python
def test_duplicidade_mensagem_vrf_publica(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ1 = _circuito(db_session, env, code="CIRC-0011", edge_id=env["ne1_id"])
    create_session(db_session, _sessao_data(env, circ1, env["ne1_id"]), actor="cli")
    circ2 = _circuito(db_session, env, code="CIRC-0012", edge_id=env["ne1_id"])
    with pytest.raises(
        ConflictError,
        match=r"Já existe sessão ativa no equipamento ne8k-bgp1 para o peer 100\.64\.0\.2 "
        r"\(VRF pública\)",
    ):
        create_session(
            db_session,
            _sessao_data(env, circ2, env["ne1_id"], local="100.64.0.9", remote="100.64.0.2"),
            actor="cli",
        )
```

Substituir o corpo do `test_update_colide_com_outra_sessao` (`:416-431`) por:

```python
def test_update_colide_com_outra_sessao(db_session: Session) -> None:
    env = _ambiente(db_session)
    circ_a = _circuito(db_session, env, code="CIRC-0035", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    create_session(db_session, _sessao_data(env, circ_a, env["ne1_id"]), actor="cli")
    # segunda sessão, mesmo equipamento e VRF, com peer próprio
    circ_b = _circuito(db_session, env, code="CIRC-0036", edge_id=env["ne1_id"], vrf="CLIENTE-A")
    sessao_b = create_session(
        db_session,
        _sessao_data(env, circ_b, env["ne1_id"], local="100.64.2.1", remote="100.64.2.2"),
        actor="cli",
    )
    # …mudar o peer da sessão B para o da sessão A colide
    with pytest.raises(
        ConflictError,
        match=r"Já existe sessão ativa no equipamento ne8k-bgp1 para o peer 100\.64\.0\.2",
    ):
        update_session(
            db_session, sessao_b.id, BgpSessionUpdate(remote_address="100.64.0.2"), actor="cli"
        )
```

Renomear `test_update_mantem_a_propria_linha_fora_da_colisao` (`:434`) para `test_update_mantem_a_propria_sessao_fora_da_colisao`; o corpo não muda.

Dois apontamentos sobre nomes, para a revisão não tropeçar neles: o `test_duplicidade_mesmo_device_vrf_afi` sai do lugar do `test_mesmo_peer_no_mesmo_device_vrf_colide` porque o nome antigo afirma a chave que a frente derruba (device+VRF+família já admite duas sessões), e o `_afi` do nome ficaria mentindo. A spec §5 descreve o comportamento ("passa a pinar o peer repetido"), não o nome.

Ficam como estão, sem tocar: `test_vrfs_diferentes_convivem_no_mesmo_device` (`:187`), `test_duplicidade_do_par_e_global_inclusive_invertido` (`:208`) e `test_afi_diferente_nao_colide` (`:225`) — este último cria v4 e v6 com endereços remotos diferentes, então segue verde com a chave nova.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -q`

Esperado: 4 falhas.

- `test_varias_sessoes_no_mesmo_device_vrf_familia` estoura `ConflictError` na segunda criação (a regra de linha ainda está lá);
- `test_update_colide_com_outra_sessao` estoura `ConflictError` já na criação da sessão B, que hoje é proibida no mesmo device+VRF;
- `test_mesmo_peer_no_mesmo_device_vrf_colide` e `test_duplicidade_mensagem_vrf_publica` recebem a mensagem antiga (`Já existe sessão ipv4 ativa no equipamento ne8k-bgp1 …`) e não casam com o `match` novo.

`test_mesmo_peer_em_vrf_diferente_convive` passa nos dois estados, de propósito (a nota acima).

- [ ] **Step 3: Implementar o `_colidente_peer`**

Em `src/gerenet/domain/services/bgp_sessions.py`, trocar o docstring do módulo (`:3-5`), que hoje diz `linha (device+VRF+afi) e par (local, remoto)`, por:

```python
Regras de unicidade do §14.1 em serviço (sem constraints UNIQUE — spec §5):
peer (device+VRF, pelo endereço remoto) e par (local, remoto). A Task 5
acrescenta update_session/disable_session/add_community/remove_community a
este arquivo.
```

No mesmo arquivo, trocar o `_colidente_linha` (de `def _colidente_linha(` até o `return None` dele) por:

```python
def _colidente_peer(
    session: Session,
    *,
    device_id: int,
    vrf: str | None,
    remote_address: str,
    ignorar_id: int | None = None,
) -> models.BgpSession | None:
    """Outra sessão ativa com o mesmo peer no mesmo (device, VRF do circuito).

    Spec §14.1: no VRP o peer é o endereço do vizinho dentro da instância, e a
    instância é a VRF. Dois blocos `peer <ip>` no mesmo contexto viram um peer
    só, configurado pelo último; a família fica implícita no endereço.
    """
    alvo = int(ipaddress.ip_address(remote_address))
    stmt = (
        select(models.BgpSession, models.Circuit)
        .join(models.Circuit, models.BgpSession.circuit_id == models.Circuit.id)
        .where(
            models.BgpSession.admin_status.is_(True),
            models.BgpSession.device_id == device_id,
        )
    )
    for outra, circ in session.execute(stmt):
        if outra.id == ignorar_id:
            continue
        if circ.vrf != vrf:
            continue
        if int(ipaddress.ip_address(outra.remote_address)) == alvo:
            return outra
    return None
```

O `_vrf_texto` (`:52`) fica como está.

No `create_session`, trocar a chamada do `_colidente_linha` (`:184`) por:

```python
    if _colidente_peer(
        session, device_id=data.device_id, vrf=circ.vrf, remote_address=data.remote_address
    ) is not None:
        raise ConflictError(
            f"Já existe sessão ativa no equipamento {device.name} para o peer "
            f"{data.remote_address} (VRF {_vrf_texto(circ)})."
        )
```

No `update_session`, trocar a chamada do `_colidente_linha` (`:324`) por:

```python
    if _colidente_peer(
        session, device_id=device_id, vrf=circ.vrf, remote_address=remote, ignorar_id=sessao.id
    ) is not None:
        raise ConflictError(
            f"Já existe sessão ativa no equipamento {device.name} para o peer "
            f"{remote} (VRF {_vrf_texto(circ)})."
        )
```

O `_colidente_par` de cada chamador logo abaixo não muda.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/domain/test_bgp_sessions_service.py -q`
Esperado: PASS, sem falha.

- [ ] **Step 5: A suíte inteira e o lint**

Run: `uv run pytest -q && uv run ruff check src tests`
Esperado: verde. Se a suíte do worker falhar por Redis, é o flake conhecido (`tests/worker/` divide o Redis DB 0 com a stack de dev); rodar com outro DB.

Run: `grep -rn "sessão ipv4 ativa\|sessão ipv6 ativa\|_colidente_linha" src tests`
Esperado: nenhuma linha (nenhum chamador ou teste ficou para trás).

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/services/bgp_sessions.py tests/domain/test_bgp_sessions_service.py
git commit -m "fix(bgp): a colisão de sessão passa a ser o peer na mesma VRF

O número de sessões por equipamento/VRF/família não é propriedade da SoT:
clientes e upstreams têm vários enlaces no mesmo roteador. O que colide é o
peer repetido, o mesmo endereço remoto na mesma VRF do equipamento."
```

---

### Task 2: Os textos da regra

**Files:**
- Modify: `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md:625`
- Modify: `docs/wiki/roteamento.md:15-17`
- Modify: `web/src/help.ts:69`
- Modify: `CLAUDE.md:437-439`

**Interfaces:**
- Consumes: nada do código; só os textos de §4 da spec.
- Produces: nada para outras tarefas.

- [ ] **Step 1: A §14.1**

Em `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`, trocar a linha 625

```markdown
- uma sessão BGP não poderá ser duplicada no mesmo equipamento, VRF/VS e família;
```

por

```markdown
- uma sessão BGP não poderá ser duplicada: o mesmo peer (endereço remoto) não
  pode estar ativo duas vezes na mesma VRF de um equipamento, nem o par
  local/remoto ativo em dois lugares; mais de uma sessão no mesmo equipamento e
  família é legítima, o que as distingue é o peer;
```

- [ ] **Step 2: A wiki**

Em `docs/wiki/roteamento.md`, trocar o bullet

```markdown
- **Uma sessão por equipamento + família + VRF** (a duplicidade é barrada:
  "Já existe sessão ipv4 ativa no equipamento X (VRF …)"). O par
  local/remoto também não pode se repetir.
```

por

```markdown
- **O peer não se repete na mesma VRF do equipamento** (a duplicidade é barrada:
  "Já existe sessão ativa no equipamento X para o peer Y (VRF …)"), e o par
  local/remoto também não pode estar ativo em dois lugares. Mais de uma sessão
  no mesmo equipamento e família é legítima: cada enlace chega por um peer
  próprio.
```

- [ ] **Step 3: O tooltip**

Em `web/src/help.ts`, trocar a linha

```ts
  "bgp.afi": "Família da sessão: ipv4 ou ipv6 — uma sessão por família; sem duplicar device+VRF+família.",
```

por

```ts
  "bgp.afi": "Família da sessão: ipv4 ou ipv6, uma sessão por família. Várias sessões podem conviver no mesmo equipamento e VRF; o que não se repete é o peer (o endereço remoto) na mesma VRF.",
```

- [ ] **Step 4: A nota do seed**

Em `CLAUDE.md`, trocar

```markdown
  equipamento próprio (`ne8000-disco-01` — o `ne8000-01` já tem sessão ativa e a
  §14.1 admite uma por device/VRF/família), e desativa as sessões desse
  equipamento antes de cada rodada.
```

por

```markdown
  equipamento próprio (`ne8000-disco-01`, só do seed: o `ne8000-01` tem sessão
  ativa e a rodada desativa as sessões do equipamento da descoberta), e desativa
  as sessões desse equipamento antes de cada rodada.
```

- [ ] **Step 5: Conferir e verificar**

Run: `grep -rn "uma por device/VRF/família\|Já existe sessão ipv4 ativa\|Uma sessão por equipamento" --include='*.md' --include='*.ts' . | grep -v docs/superpowers/`
Esperado: nenhuma linha (os planos e designs antigos ficam como registro histórico).

Run: `cd web && npm run build && npm run test`
Esperado: verde (o build valida as chaves do `help.ts`).

- [ ] **Step 6: Commit**

```bash
git add ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md docs/wiki/roteamento.md web/src/help.ts CLAUDE.md
git commit -m "docs: a regra de duplicidade da sessão BGP passa a ser o peer na VRF"
```
