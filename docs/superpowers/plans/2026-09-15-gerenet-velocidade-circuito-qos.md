# Velocidade do circuito, descrição da subinterface e QoS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar `circuits.velocidade_mbps` como dado do circuito, derivar dela a `description` da subinterface e o limitador de taxa (`qos car`) do render, e fazer os circuitos já provisionados convergirem sem remoção nem reprovisionamento.

**Architecture:** A velocidade é uma coluna nova na SoT; a descrição e o QoS são derivados dela na hora do render (`naming.descricao_subinterface` + `subinterface.j2`), sem estado intermediário. A convergência do parque mora em três pontos do motor de mudança, apoiados num módulo novo `automation/subinterface.py` que passa a ser a única resposta para "este bloco já está no equipamento?" — a pergunta que o plano (`changes._ja_existe`) e a execução (`runner._estado_do_bloco`) precisam responder igual, sob pena de o plano pular um bloco que a execução mandaria aplicar. Na descoberta, a `description` sai do grupo "a SoT não gerencia" e entra na comparação, e o ensaio da conferência passa a carregar a identidade da revisão para comparar o que a adoção realmente gravaria.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.x + Alembic + PostgreSQL + Typer + Jinja2 + pytest/ruff; React 18 + Vite + TypeScript + TanStack Query + Vitest + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-15-gerenet-velocidade-circuito-qos-design.md`

## Global Constraints

- **Idioma dos artefatos: português (PT-BR).** Comentários, docstrings, mensagens de erro, nomes de teste e mensagens de commit. Nomes de código que já existem em inglês ficam como estão (`bandwidth`, `description`).
- **Convenção de unidade: 1 Gbps = 1024 Mbps.** `1024` produz `cir 1024000` kbps (`velocidade_mbps × 1000`).
- **Validação da velocidade: `> 0` e `≤ 100000`** (100 Gbps). Fora disso é erro de digitação, não taxa.
- **Nunca usar `git stash` / `git stash pop`** nesta worktree: a pilha é compartilhada com o checkout principal e outras sessões. Para pôr trabalho de lado, commit WIP.
- **Nada de segredo em log, snapshot, auditoria, YAML ou Git** (§19). A senha de peer continua mascarada.
- **Idempotência (§3.2)**: reexecutar a mesma operação não duplica nada; um bloco já conforme não entra no plano.
- **A fixture `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt` é derivada dos templates deste projeto**, não uma captura real — o que o render passa a emitir entra nela.
- **A ordem das linhas do bloco da subinterface é a do template** (`interface`, `description`, `vlan-type`, `ip address`, `ipv6 enable`, `ipv6 address`, `statistic enable`, `qos car inbound`, `qos car outbound`) — é o que os goldens de `test_templates.py` pinam. O equipamento escreve `vlan-type` antes de `description` (spec §2), e a diferença não importa: a comparação com a coleta é por **conjunto** (`subinterface.linhas_da_interface` devolve `set`), não por ordem. Não reordene o template para casar com a captura.

> **Ruling do pré-voo, 1 de 2.** Esta linha listava a ordem do equipamento como se fosse a do render. O template emite `description` **antes** do `vlan-type` desde antes desta frente (`subinterface.j2:2-9`), e `test_subinterface_v4_descricao_sem_ipv6` pina isso. Seguir a lista antiga quebraria dois goldens existentes para ganhar nada — a comparação é por conjunto. **Custo se estiver errado:** o bloco sai numa ordem diferente da captura, o que é cosmético; nenhum teste de fidelidade depende disso.

---

## File Structure

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `src/gerenet/automation/subinterface.py` | A pergunta "o bloco da subinterface já está no equipamento?": equivalência das formas do VRP, leitura das linhas do bloco na configuração, e a conferência do conteúdo (descrição e QoS). |
| `alembic/versions/f2b7d4a91c3e_velocidade_mbps_do_circuito.py` | A coluna nova, com downgrade. |

**Modificar (núcleo):**

| Arquivo | O que muda |
|---|---|
| `src/gerenet/automation/naming.py` | `descricao_subinterface()` — a função pura do §4. |
| `src/gerenet/automation/templates/huawei_vrp/subinterface.j2` | A linha `qos car` depois do `statistic enable`. |
| `src/gerenet/automation/render.py` | `_comandos_sub` passa a receber a velocidade e a preencher `descricao`; `_bloco_sub` a repassa. |
| `src/gerenet/automation/changes.py` | `_ja_existe` da subinterface passa a exigir o conteúdo, não só o nome. |
| `src/gerenet/automation/runner.py` | Estado `atualizar` em `_estado_do_bloco`; `_re_diff` o aplica sem contaminar o abort de plano velho; `_verifica_aplicados` ganha o item de atenção. |
| `src/gerenet/automation/discovery.py` | `_equivalencia_vrp`/`_contexto_interface` saem para o módulo novo; `_NAO_GERENCIADAS_SUBINTERFACE` vira `("mtu ",)`; `Proposta.velocidade_mbps`; `_ensaio` recebe a identidade da revisão. |
| `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py` | `Subinterface.qos_cir` e a leitura do `qos car cir`. |
| `src/gerenet/domain/models.py` | `Circuit.velocidade_mbps`. |
| `src/gerenet/domain/schemas.py` | `velocidade_mbps` em `CircuitCreate`/`CircuitUpdate`/`CircuitOut`; `AdocaoIn.velocidade_mbps`; `PropostaOut.velocidade_mbps`. |
| `src/gerenet/domain/services/discovery.py` | A conferência e a criação do circuito recebem a velocidade da revisão. |
| `src/gerenet/api/routers/discovery.py` | `GET /fidelidade` ganha os quatro parâmetros da identidade. |
| `src/gerenet/cli/circuits.py` | `--velocidade-mbps` no `add`. |

**Modificar (web):**

| Arquivo | O que muda |
|---|---|
| `web/src/help.ts` | Duas chaves novas. |
| `web/src/api/types.ts` | `CircuitOut.velocidade_mbps`, `DiscoveryPropostaOut.velocidade_mbps`, `DiscoveryAdocaoIn.velocidade_mbps`. |
| `web/src/api/hooks.ts` | `CircuitCreateIn.velocidade_mbps`; `useFidelidade` com a identidade da conferência. |
| `web/src/pages/Circuits.tsx` | Campo "Velocidade (Mbps)" no cadastro e na edição. |
| `web/src/pages/DiscoveryAdopt.tsx` | Campo da velocidade e a identidade da conferência no lugar do trunk sozinho. |
| `docs/wiki/circuitos.md` | A velocidade, o formato da descrição e o QoS. |

**Modificar (testes e fixtures):**

`tests/automation/test_naming.py`, `tests/automation/test_templates.py`, `tests/automation/test_changes.py`, `tests/automation/test_runner_change.py`, `tests/automation/test_discovery.py`, `tests/automation/test_config_vrp.py`, `tests/domain/test_circuits_service.py`, `tests/domain/test_adocao.py`, `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt`, `web/src/pages/Circuits.test.tsx`, `web/src/pages/Discovery.test.tsx`.

**Ordem das tarefas.** A 1 (função pura) e a 2 (coluna + superfícies) são independentes. A 3 depende da 1 e da 2. A 4 depende da 3 (é o conteúdo que ela confere). A 5 depende da 4. A 6 depende da 3. A 7 depende da 2 e da 6. As tarefas 8 e 9 dependem da 2 e da 7. A 10 é documentação e fecha.

---

### Task 1: `naming.descricao_subinterface`

A função pura do §4, com entradas fixas e sem banco: é onde o corte, a dobra de acento e a forma da velocidade são testados sozinhos.

**Files:**
- Modify: `src/gerenet/automation/naming.py`
- Test: `tests/automation/test_naming.py`

**Interfaces:**
- Consumes: nada.
- Produces: `naming.descricao_subinterface(code: str, nome_organizacao: str | None, velocidade_mbps: int | None) -> str | None` — o texto da `description` **sem** a palavra-chave (o template escreve `description <valor>`), ou `None` quando não há organização. Constantes `naming.LIMITE_DESCRICAO = 80`.

- [ ] **Step 1: Write the failing test**

Acrescentar ao fim de `tests/automation/test_naming.py`:

```python
def test_descricao_subinterface_com_velocidade_em_g() -> None:
    assert naming.descricao_subinterface("CIRC-626", "NETMAC", 1024) == "CIRC-626 NETMAC [1G]"


def test_descricao_subinterface_com_velocidade_em_m() -> None:
    assert naming.descricao_subinterface("CIRC-500", "Acme Telecom", 100) == "CIRC-500 ACME TELECOM [100M]"


def test_descricao_subinterface_sem_velocidade_nao_emite_colchetes() -> None:
    assert naming.descricao_subinterface("CIRC-500", "ACME", None) == "CIRC-500 ACME"


def test_descricao_subinterface_nao_multiplo_de_1024_fica_em_m() -> None:
    """3000 Mbps são 2,93 G: arredondar para `3G` mentiria a taxa no rótulo."""
    assert naming.descricao_subinterface("CIRC-7", "ACME", 3000) == "CIRC-7 ACME [3000M]"


def test_descricao_subinterface_dobra_acento_e_sobe_caixa() -> None:
    assert naming.descricao_subinterface("CIRC-1", "Ação Comunicações", 2048) == "CIRC-1 ACAO COMUNICACOES [2G]"


def test_descricao_subinterface_corta_o_nome_no_orcamento() -> None:
    nome = "A" * 200
    linha = naming.descricao_subinterface("CIRC-1", nome, 1024)
    assert linha is not None
    assert len(linha) == naming.LIMITE_DESCRICAO
    assert linha.endswith(" [1G]")
    assert linha.startswith("CIRC-1 A")


def test_descricao_subinterface_sem_espaco_para_o_nome_perde_o_nome() -> None:
    """O teto do código (64) nunca chega aqui na prática — 80 - 64 - 8 - 1 = 7 —
    mas o helper não pode produzir `CIRC-...  [1G]`, com dois espaços."""
    linha = naming.descricao_subinterface("C" * 80, "ACME", 99999)
    assert linha == "C" * 80 + " [99999M]"


def test_descricao_subinterface_sem_organizacao_nao_e_emitida() -> None:
    """`organization_id` é NOT NULL, então não acontece — mas o template escreve
    a linha sempre que o valor é uma string, e `None` é o freio."""
    assert naming.descricao_subinterface("CIRC-1", None, 1024) is None
    assert naming.descricao_subinterface("CIRC-1", "   ", 1024) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_naming.py -q -k descricao_subinterface`
Expected: FAIL com `AttributeError: module 'gerenet.automation.naming' has no attribute 'descricao_subinterface'`.

- [ ] **Step 3: Write minimal implementation**

Em `src/gerenet/automation/naming.py`, trocar a linha `import re` por:

```python
import re
import unicodedata
```

E acrescentar ao fim do arquivo:

```python
# Orçamento da `description` da subinterface (§4). O limite real desta versão do
# VRP entra no checklist do runbook; se ele for menor que 80, o número desce
# aqui e a função continua correta, porque o corte é derivado dele.
LIMITE_DESCRICAO = 80


def _dobra_ascii(texto: str) -> str:
    """Maiúsculas e sem acento, com os espaços preservados (§4).

    A convenção observada no equipamento é ASCII (§2): um acento que chegasse
    torto viraria divergência permanente contra a coleta, porque a SoT
    intencionaria uma linha que o VRP nunca escreve igual.
    """
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").upper()


def _velocidade_legivel(velocidade_mbps: int) -> str:
    """Múltiplo de 1024 em `G`, o resto em `M` (§4)."""
    if velocidade_mbps % 1024 == 0:
        return f"{velocidade_mbps // 1024}G"
    return f"{velocidade_mbps}M"


def descricao_subinterface(
    code: str, nome_organizacao: str | None, velocidade_mbps: int | None
) -> str | None:
    """A `description` da subinterface: `<CÓDIGO> <NOME DA ORG> [<VELOCIDADE>]` (§4).

    Devolve o texto SEM a palavra-chave `description` — quem a escreve é o
    template. `None` quando não há nome de organização: a linha não é emitida,
    e não emitida é diferente de emitida com o campo vazio.

    Quem cede no orçamento é o nome da organização, cortado seco. Sobrando menos
    de um caractere para ele, a linha sai como `<CÓDIGO> [<VELOCIDADE>]`, sem
    espaço dobrado.
    """
    nome = _dobra_ascii(nome_organizacao or "").strip()
    if not nome:
        return None
    sufixo = f" [{_velocidade_legivel(velocidade_mbps)}]" if velocidade_mbps is not None else ""
    espaco = LIMITE_DESCRICAO - len(code) - len(sufixo) - 1
    if espaco < 1:
        return f"{code}{sufixo}"
    return f"{code} {nome[:espaco]}{sufixo}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/automation/test_naming.py -q`
Expected: PASS (todos, inclusive os que já existiam).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/naming.py tests/automation/test_naming.py
git commit -m "feat(naming): a descrição da subinterface deriva do código, da organização e da velocidade

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: `circuits.velocidade_mbps` — coluna, migração, schemas e CLI

**Files:**
- Modify: `src/gerenet/domain/models.py` (bloco `Circuit`, perto da linha 262)
- Create: `alembic/versions/f2b7d4a91c3e_velocidade_mbps_do_circuito.py`
- Modify: `src/gerenet/domain/schemas.py` (`CircuitCreate`, `CircuitUpdate`, `CircuitOut`)
- Modify: `src/gerenet/cli/circuits.py` (comando `add`)
- Test: `tests/domain/test_circuits_service.py`

**Interfaces:**
- Consumes: nada.
- Produces: `models.Circuit.velocidade_mbps: int | None`; `schemas.CircuitCreate.velocidade_mbps`, `schemas.CircuitUpdate.velocidade_mbps`, `schemas.CircuitOut.velocidade_mbps` (todos `int | None`, com `gt=0, le=100000` nos de entrada). É esta coluna que a Task 3 lê no render.

- [ ] **Step 1: Write the failing test**

Primeiro os imports, em `tests/domain/test_circuits_service.py`. O do pydantic
vai junto do `import pytest`, no topo:

```python
from pydantic import ValidationError as PydanticValidationError
```

(o alias é o padrão do repositório — `tests/domain/test_l2vc_service.py` e
`test_vsi_service.py` fazem igual — e é necessário porque este arquivo já
importa o `ValidationError` de domínio, de `gerenet.domain.services.errors`.)

E `CircuitOut` entra na lista de `gerenet.domain.schemas`.

Depois, ao fim do arquivo — os helpers da casa são `_ambiente(db_session)`, que
devolve `(org_id, site_id, sw_id, ne_id, ne8k2_id)`, e `_circuito(site_id,
org_id, sw_id, ne_id, *, code=..., **extra)`:

```python
def test_velocidade_mbps_entra_e_sai_do_circuito(db_session: Session) -> None:
    """O campo é do circuito, e não do render: é ele que a descrição e o QoS
    derivam depois (§3)."""
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    circ = create_circuit(
        db_session,
        _circuito(site_id, org_id, sw_id, ne_id, code="CIRC-VEL-1", velocidade_mbps=1024),
        actor="cli",
    )
    assert circ.velocidade_mbps == 1024
    assert CircuitOut.model_validate(circ).velocidade_mbps == 1024


def test_velocidade_mbps_nula_nao_e_zero(db_session: Session) -> None:
    """Nula é "não sei a velocidade", e é o estado de todo circuito que já
    existe (§3). Zero seria uma taxa."""
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    circ = create_circuit(
        db_session, _circuito(site_id, org_id, sw_id, ne_id, code="CIRC-VEL-2"), actor="cli"
    )
    assert circ.velocidade_mbps is None


def test_velocidade_mbps_recusa_valor_fora_da_faixa(db_session: Session) -> None:
    """Um valor fora disso é erro de digitação, não uma taxa (§3). O erro é do
    pydantic: a restrição mora no schema, antes de qualquer serviço."""
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    for invalido in (0, -1, 100001):
        with pytest.raises(PydanticValidationError):
            _circuito(site_id, org_id, sw_id, ne_id, velocidade_mbps=invalido)


def test_velocidade_mbps_sobrevive_ao_update(db_session: Session) -> None:
    """`update_circuit` faz `model_dump(exclude_unset=True)`: o campo precisa
    estar nos dois schemas, senão o PATCH da web não o alcança (§8)."""
    org_id, site_id, sw_id, ne_id, _ = _ambiente(db_session)
    circ = create_circuit(
        db_session, _circuito(site_id, org_id, sw_id, ne_id, code="CIRC-VEL-3"), actor="cli"
    )
    atualizado = update_circuit(
        db_session, circ.id, CircuitUpdate(velocidade_mbps=500), actor="cli"
    )
    assert atualizado.velocidade_mbps == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_circuits_service.py -q -k velocidade_mbps`
Expected: FAIL com `TypeError: CircuitCreate.__init__() got an unexpected keyword argument 'velocidade_mbps'`.

- [ ] **Step 3: Write minimal implementation**

**3a.** Em `src/gerenet/domain/models.py`, logo depois de `bandwidth` (linha ~262):

```python
    velocidade_mbps: Mapped[int | None] = mapped_column(Integer)  # taxa contratada em Mbps (§3)
```

**3b.** Criar `alembic/versions/f2b7d4a91c3e_velocidade_mbps_do_circuito.py`:

```python
"""velocidade do circuito em Mbps

Revision ID: f2b7d4a91c3e
Revises: c4a8e1f0b7d3
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = "f2b7d4a91c3e"
down_revision = "c4a8e1f0b7d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """A velocidade contratada, em Mbps (§3 do design).

    Nula em todo circuito que já existe: nula é "não sei a velocidade", e o
    render não emite descrição de velocidade nem QoS enquanto for assim.
    """
    op.add_column("circuits", sa.Column("velocidade_mbps", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("circuits", "velocidade_mbps")
```

**3c.** Em `src/gerenet/domain/schemas.py`, acrescentar a linha depois de `bandwidth` em `CircuitCreate` e em `CircuitUpdate`:

```python
    velocidade_mbps: int | None = Field(default=None, gt=0, le=100000)
```

E depois de `bandwidth` em `CircuitOut`:

```python
    velocidade_mbps: int | None
```

**3d.** Em `src/gerenet/cli/circuits.py`, acrescentar o parâmetro depois de `bandwidth` e repassá-lo ao `CircuitCreate`:

```python
    velocidade_mbps: int | None = typer.Option(
        None, "--velocidade-mbps", min=1, max=100000,
        help="Velocidade contratada em Mbps (ex.: 1024 = 1 Gbps).",
    ),
```

```python
                    velocidade_mbps=velocidade_mbps,
```

> **Desvio registrado da spec §8.** A spec pede "`gerenet circuits add
> --velocidade-mbps`, e o mesmo no `update`". O grupo `circuits` do CLI **não
> tem** comando `update` (só `add`, `list`, `reserve`, `unreserve`, `disable`).
> Criar um `update` completo está fora do escopo desta frente — a API PATCH
> (`CircuitUpdate`) já carrega o campo, e é por ela que a web edita. O `update`
> do CLI entra na dívida registrada da spec. Não invente um `update` parcial só
> com a velocidade.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_circuits_service.py tests/domain/test_schemas_out.py -q`
Expected: PASS.

- [ ] **Step 5: Aplicar e conferir a migração (manual, sem harness)**

O repositório não tem harness de migração, então a conferência é manual, num banco descartável.

> **Ruling do pré-voo, 3.** Esta linha dizia que `tests/conftest.py` cria o schema pelo metadata e que o banco de teste não tem `alembic_version`, e por isso mandava **nunca** migrar o `gerenet_test`. As duas metades estão erradas, e a execução da Task 2 provou: o `conftest.py` só faz `TRUNCATE` (linha 41) e o `gerenet_test` **tem** `alembic_version` — estava em `c4a8e1f0b7d3`, o head anterior, sem a coluna nova. Migrar o banco de teste não estoura: é exatamente o que a frente precisa, e é a convenção já registrada do projeto (o protocolo de rebase do B2 manda migrar o `gerenet_test` depois de mexer no `down_revision`). **Custo se estiver errado:** sem o `alembic upgrade head` no `gerenet_test`, toda tarefa seguinte roda contra um schema sem a coluna e a suíte fica vermelha por um motivo que não é código. O banco de teste foi migrado para `f2b7d4a91c3e` durante a execução.

```bash
createdb gerenet_mig_velocidade
GERENET_DATABASE_URL=postgresql+psycopg://localhost/gerenet_mig_velocidade uv run alembic upgrade head
GERENET_DATABASE_URL=postgresql+psycopg://localhost/gerenet_mig_velocidade uv run alembic downgrade -1
GERENET_DATABASE_URL=postgresql+psycopg://localhost/gerenet_mig_velocidade uv run alembic upgrade head
dropdb gerenet_mig_velocidade
```

Se a URL do banco de dev divergir (usuário, host, porta), copie dela a parte da conexão: o que importa é o banco ser descartável. O `upgrade` no banco de dev (`uv run alembic upgrade head`) roda depois, no fecho da frente. Esperado: os três comandos sem erro.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/domain/models.py src/gerenet/domain/schemas.py src/gerenet/cli/circuits.py \
        alembic/versions/f2b7d4a91c3e_velocidade_mbps_do_circuito.py tests/domain/test_circuits_service.py
git commit -m "feat(circuitos): a velocidade contratada vira coluna em Mbps

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: O render emite a descrição e o QoS

**Files:**
- Modify: `src/gerenet/automation/templates/huawei_vrp/subinterface.j2`
- Modify: `src/gerenet/automation/render.py:131-177` (`_comandos_sub`, `_bloco_sub`)
- Test: `tests/automation/test_templates.py`, `tests/automation/test_rendering.py`

**Interfaces:**
- Consumes: `naming.descricao_subinterface` (Task 1); `models.Circuit.velocidade_mbps` (Task 2).
- Produces: bloco de subinterface com as linhas `description <...>` (depois do `vlan-type`) e `qos car cir <velocidade_mbps × 1000> inbound|outbound` (depois do `statistic enable`). O contrato do template é `_render_template("subinterface", contexto)`, com a chave nova `cir_kbps: int | None` e `descricao` deixando de ser sempre `None`.

- [ ] **Step 1: Write the failing test**

Trocar `test_subinterface_v4_descricao_sem_ipv6` em `tests/automation/test_templates.py` por:

```python
def test_subinterface_v4_descricao_sem_ipv6() -> None:
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.4023", descricao="CIRC-4023 ACME [1G]", qinq=False, vid=4023,
        enderecos_v4=[{"endereco": "100.64.0.1", "mascara": "255.255.255.254"}],
        enderecos_v6=[],
    ) == "interface Eth-Trunk127.4023\ndescription CIRC-4023 ACME [1G]\nvlan-type dot1q vid 4023\nip address 100.64.0.1 255.255.255.254\nstatistic enable"
```

E acrescentar:

```python
def test_subinterface_com_qos_nas_duas_direcoes() -> None:
    """O `cir` sai de `velocidade_mbps × 1000` (kbps) e a direção sai por
    extenso: é a forma que o VRP ecoa (§5)."""
    assert _render(
        "subinterface",
        interface="Eth-Trunk127.626", descricao="CIRC-626 NETMAC [1G]", qinq=False, vid=626,
        enderecos_v4=[{"endereco": "100.110.0.13", "mascara": "255.255.255.252"}],
        enderecos_v6=[], cir_kbps=1024000,
    ) == (
        "interface Eth-Trunk127.626\n"
        "description CIRC-626 NETMAC [1G]\n"
        "vlan-type dot1q vid 626\n"
        "ip address 100.110.0.13 255.255.255.252\n"
        "statistic enable\n"
        "qos car cir 1024000 inbound\n"
        "qos car cir 1024000 outbound"
    )


def test_subinterface_sem_velocidade_nao_emite_qos() -> None:
    texto = _render(
        "subinterface",
        interface="Eth-Trunk127.4024", descricao=None, qinq=False, vid=4024,
        enderecos_v4=[{"endereco": "100.64.0.1", "mascara": "255.255.255.254"}],
        enderecos_v6=[], cir_kbps=None,
    )
    assert "qos car" not in texto
```

> **Atenção:** as chamadas existentes de `_render("subinterface", ...)` que não
> passam `cir_kbps` continuam válidas — o template trata ausente como `None`.
> Não é preciso tocar nas outras.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_templates.py -q -k subinterface`
Expected: FAIL em `test_subinterface_com_qos_nas_duas_direcoes` (o texto renderizado não tem as linhas `qos car`) e em `test_subinterface_v4_descricao_sem_ipv6` (a linha `description` está lá, mas o teste é o mesmo e passa — o que falha é o do QoS).

- [ ] **Step 3: Write minimal implementation**

**3a.** Em `src/gerenet/automation/templates/huawei_vrp/subinterface.j2`, acrescentar ao fim:

```jinja
statistic enable
{% if cir_kbps %}
qos car cir {{ cir_kbps }} inbound
qos car cir {{ cir_kbps }} outbound
{% endif %}
```

(o `statistic enable` já existe na linha final; a mudança é o bloco `{% if %}`
depois dele.)

**3b.** Em `src/gerenet/automation/render.py`, trocar `_comandos_sub` inteira por:

```python
def _comandos_sub(
    trunk: str,
    vid: int,
    qinq: bool,
    *,
    v4: dict | None,
    v6: str | None,
    descricao: str | None,
    velocidade_mbps: int | None,
) -> list[str]:
    """Linhas de comando da subinterface (§4/§5).

    A `description` e o `qos car` derivam do circuito: o código e a organização
    para a primeira, a velocidade contratada para o segundo. Velocidade nula não
    emite QoS nenhum — o `cir` não tem de onde sair.
    """
    contexto: dict = {
        "interface": naming.subinterface(trunk, vid),
        "descricao": descricao,
        "qinq": qinq,
        "vid": vid,
        "enderecos_v4": [v4] if v4 else [],
        "enderecos_v6": [v6] if v6 else [],
        # `cir` é kbps: 1024 Mbps viram 1024000, a mesma conta da operação (§2).
        "cir_kbps": velocidade_mbps * 1000 if velocidade_mbps is not None else None,
    }
    return _render_template("subinterface", contexto).splitlines()
```

**3c.** Em `_bloco_sub`, calcular a descrição uma vez e repassá-la nas duas chamadas. Substituir o corpo a partir de `if circuito.vlan_mode == "unica":` por:

```python
    descricao = naming.descricao_subinterface(
        circuito.code, circuito.organization.name, circuito.velocidade_mbps
    )
    if circuito.vlan_mode == "unica":
        vid = fams["ipv4"]["vid"] if "ipv4" in fams else fams["ipv6"]["vid"]
        comandos = _comandos_sub(
            circuito.edge_trunk, vid, circuito.qinq,
            v4=fams.get("ipv4"), v6=fams.get("ipv6", {}).get("endereco"),
            descricao=descricao, velocidade_mbps=circuito.velocidade_mbps,
        )
        return [BlocoRender("subinterface", "circuit", circuito.id, comandos)]
    blocos: list[BlocoRender] = []
    for fam in ("ipv4", "ipv6"):
        if fam not in fams:
            continue
        comandos = _comandos_sub(
            circuito.edge_trunk, fams[fam]["vid"], circuito.qinq,
            v4=fams[fam] if fam == "ipv4" else None,
            v6=fams[fam]["endereco"] if fam == "ipv6" else None,
            descricao=descricao, velocidade_mbps=circuito.velocidade_mbps,
        )
        blocos.append(BlocoRender("subinterface", "circuit", circuito.id, comandos))
    return blocos
```

> `circuito.organization` já é o relacionamento do modelo (`models.Circuit.organization`),
> e o circuito vem carregado da sessão — nenhuma consulta nova. `circuito.code` é
> o código do circuito, o mesmo que a adoção grava.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/automation/test_templates.py tests/automation/test_rendering.py -q`
Expected: PASS. Se algum teste de `test_rendering.py` pinar o texto do render de um circuito, a linha `description` aparece nele agora — ajuste a expectativa para o formato do §4 (o código e o nome da organização da fixture daquele teste).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/templates/huawei_vrp/subinterface.j2 \
        src/gerenet/automation/render.py tests/automation/test_templates.py tests/automation/test_rendering.py
git commit -m "feat(render): a subinterface ganha descrição e limitador de taxa

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: `automation/subinterface.py` e o plano que não pula mais o bloco pela metade

**Files:**
- Create: `src/gerenet/automation/subinterface.py`
- Modify: `src/gerenet/automation/discovery.py` (remover `_equivalencia_vrp` e `_contexto_interface`; importar do módulo novo)
- Modify: `src/gerenet/automation/changes.py:79-84` (`_ja_existe`)
- Test: `tests/automation/test_subinterface.py` (novo), `tests/automation/test_changes.py`

**Interfaces:**
- Consumes: `render.BlocoRender` (via `bloco.comandos`).
- Produces:
  - `subinterface.equivalencia_vrp(texto: str) -> str`
  - `subinterface.linhas_da_interface(texto: str, nome: str) -> set[str]`
  - `subinterface.conteudo_conforme(comandos: list[str], linhas: set[str]) -> bool`
  - `subinterface.LINHAS_DE_CONTEUDO = ("description ", "qos car ")`
  A Task 5 consome `equiv…`, `linhas_da_interface` e `conteudo_conforme` do runner.

- [ ] **Step 1: Write the failing test**

Criar `tests/automation/test_subinterface.py`:

```python
"""O bloco da subinterface contra a configuração do equipamento (§6).

A pergunta é a mesma no plano e na execução: duas cópias dela divergiriam, e o
plano pularia um bloco que a execução mandaria aplicar — ou o contrário.
"""
from gerenet.automation import subinterface

# A forma curta que o render emite, e a forma longa que o VRP ecoa (§2).
_CURTA = "qos car cir 1024000 inbound"
_LONGA = "qos car cir 1024000 cbs 18700000 green pass red discard inbound"

_CONFIG = """#
interface Eth-Trunk127.626
 vlan-type dot1q 626
 description CIRC-626 NETMAC [1G]
 ip address 100.110.0.13 255.255.255.252
 statistic enable
 qos car cir 1024000 cbs 18700000 green pass red discard inbound
 qos car cir 1024000 cbs 18700000 green pass red discard outbound
#
"""


def test_o_car_completo_do_vrp_e_a_mesma_linha_da_forma_curta() -> None:
    assert subinterface.equivalencia_vrp(_LONGA) == _CURTA
    assert subinterface.equivalencia_vrp(_CURTA) == _CURTA


def test_outra_taxa_nao_e_a_mesma_linha() -> None:
    assert subinterface.equivalencia_vrp(
        "qos car cir 500000 cbs 18700000 green pass red discard inbound"
    ) == "qos car cir 500000 inbound"


def test_as_duas_formas_da_vlan_e_do_ipv6_continuam_equivalentes() -> None:
    assert subinterface.equivalencia_vrp("vlan-type dot1q 1001") == "vlan-type dot1q vid 1001"
    assert subinterface.equivalencia_vrp("ipv6 address 2804:194C::1 126") == "ipv6 address 2804:194C::1/126"


def test_linhas_da_interface_so_pega_o_bloco_e_na_forma_do_render() -> None:
    linhas = subinterface.linhas_da_interface(_CONFIG, "Eth-Trunk127.626")
    assert "description CIRC-626 NETMAC [1G]" in linhas
    assert "vlan-type dot1q vid 626" in linhas
    assert _CURTA in linhas
    assert "qos car cir 1024000 outbound" in linhas
    assert "interface Eth-Trunk127.626" not in linhas  # cabeçalho abre o contexto


def test_linhas_da_interface_nao_vaza_para_o_bloco_vizinho() -> None:
    texto = _CONFIG + "interface Eth-Trunk127.627\n description OUTRO\n"
    assert "description OUTRO" not in subinterface.linhas_da_interface(texto, "Eth-Trunk127.626")


def test_conteudo_conforme_aceita_o_bloco_sem_descricao_e_sem_qos() -> None:
    """Bloco sem as duas linhas não tem o que conferir: conforme. É o caso dos
    blocos escritos à mão nos testes e dos circuitos de antes desta frente —
    marcá-los inconformes faria todo plano congelado reaplicar o parque."""
    assert subinterface.conteudo_conforme(
        ["interface GE1/0/0.2", "vlan-type dot1q vid 2", "ip address 10.0.0.0 255.255.255.254"],
        set(),
    )


def test_conteudo_conforme_recusa_o_bloco_com_descricao_ausente() -> None:
    comandos = ["interface GE1/0/0.2", "description CIRC-2 ACME [1G]", "statistic enable"]
    linhas = subinterface.linhas_da_interface(_CONFIG, "Eth-Trunk127.626")
    assert not subinterface.conteudo_conforme(comandos, linhas)
    assert subinterface.conteudo_conforme(
        comandos, linhas | {"description CIRC-2 ACME [1G]"}
    )


def test_conteudo_conforme_recusa_o_qos_ausente() -> None:
    comandos = ["interface GE1/0/0.2", "statistic enable", _CURTA, "qos car cir 1024000 outbound"]
    linhas = {"description CIRC-2 ACME [1G]"}
    assert not subinterface.conteudo_conforme(comandos, linhas)


def test_conteudo_conforme_confere_a_taxa_e_nao_so_a_presenca() -> None:
    """Taxa diferente é divergência: o bloco entra no plano para convergir."""
    comandos = ["interface GE1/0/0.2", "qos car cir 500000 inbound"]
    assert not subinterface.conteudo_conforme(comandos, {_CURTA})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_subinterface.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'gerenet.automation.subinterface'`.

- [ ] **Step 3: Write minimal implementation**

Criar `src/gerenet/automation/subinterface.py`:

```python
"""O bloco da subinterface contra a configuração do equipamento (design §6).

O plano (`changes._ja_existe`) e a execução (`runner._estado_do_bloco`) fazem a
MESMA pergunta — "este bloco já está no equipamento?" — e por isso ela mora
aqui, uma vez só. Duas cópias divergiriam, e a divergência é silenciosa: o
plano pularia um bloco que a execução mandaria aplicar, ou o contrário, e o
operador veria "nada a aplicar" numa mudança que o equipamento não tem.
"""

# As linhas do bloco que a identidade por nome + endereços não cobre. O
# `vlan-type`, os endereços e o `statistic enable` já são cobertos por ela; o
# que falta é a `description` e o QoS (§6).
LINHAS_DE_CONTEUDO = ("description ", "qos car ")


def equivalencia_vrp(texto: str) -> str:
    """Duas linhas que o VRP escreve de duas formas, na forma do render.

    `vlan-type dot1q 1001` e `vlan-type dot1q vid 1001` são a mesma linha, e o
    mesmo vale para `ipv6 address <endereço> 126` e `<endereço>/126`. O parser
    lê as duas formas e o render escreve a segunda, então sem a equivalência
    toda proposta com VLAN e IPv6 nasce com dois falsos `sobrando` e dois falsos
    `faltando`. São a mesma linha escrita de dois jeitos, não dois estados: por
    isso é equivalência, e não normalização de conveniência.

    O `qos car` entrou pela mesma razão, e é o caso mais extremo dos três: o
    render emite `qos car cir 1024000 inbound` e o VRP grava
    `qos car cir 1024000 cbs 18700000 green pass red discard inbound` (§2). Sem
    a dobra, toda subinterface com QoS divergiria para sempre.
    """
    partes = texto.split()
    if len(partes) == 3 and partes[:2] == ["vlan-type", "dot1q"] and partes[2].isdigit():
        return f"vlan-type dot1q vid {partes[2]}"
    if len(partes) == 4 and partes[:2] == ["ipv6", "address"] and partes[3].isdigit():
        return f"ipv6 address {partes[2]}/{partes[3]}"
    if len(partes) >= 5 and partes[:3] == ["qos", "car", "cir"] and partes[-1] in ("inbound", "outbound"):
        # O `cir` está na quarta posição nas duas formas; o `cbs` e as ações
        # caem, e a direção fica porque é ela que separa uma linha da outra.
        return f"qos car cir {partes[3]} {partes[-1]}"
    return texto


def linhas_da_interface(texto: str, nome: str) -> set[str]:
    """Linhas da configuração dentro do bloco `interface <nome>`.

    O cabeçalho fica de fora: ele abre o contexto, não é linha dele. Quem
    compara o nome é a conferência, e por fora — ela põe `interface <nome>` nos
    dois lados (`conferir_fidelidade`), porque o `<trunk>.<vid>` do render
    contra o nome do bloco lido é a única linha que denuncia um trunk errado.

    O contexto é a INDENTAÇÃO (`display current-configuration` escreve os
    sub-comandos com um espaço e os blocos na coluna 0), e não a proximidade
    das linhas: sem ela, um bloco vizinho entraria na conta.

    Comentário (`#`, com ou sem texto) também fica de fora, e antes da regra de
    contexto: o `_normaliza_linhas` já descarta os dois do lado do render, e um
    comentário com texto na coluna 0 zerava o `dentro` aqui — as linhas de
    endereço que vinham depois ficavam de fora da comparação e o render as
    acusava como sobra.
    """
    linhas: set[str] = set()
    dentro = False
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if not bruta[:1].isspace():
            dentro = linha == f"interface {nome}"
            continue
        if dentro:
            linhas.add(equivalencia_vrp(linha))
    return linhas


def conteudo_conforme(comandos: list[str], linhas: set[str]) -> bool:
    """As linhas de conteúdo do bloco estão no que a configuração tem (§6).

    Só `description` e `qos car` entram na conta (`LINHAS_DE_CONTEUDO`). Um
    bloco sem nenhuma delas é conforme: não há o que conferir.

    A comparação é linha a linha e na forma do render, pela `equivalencia_vrp`
    — é ela que faz o `qos car cir 1024000 inbound` do bloco casar com o
    `qos car cir 1024000 cbs 18700000 green pass red discard inbound` do
    equipamento. O espaço interno é normalizado pela mesma regra do
    `_normaliza_linhas`, porque a coluna que separa os tokens não é informação.
    """
    extras = [c for c in comandos if c.startswith(LINHAS_DE_CONTEUDO)]
    return all(equivalencia_vrp(" ".join(c.split())) in linhas for c in extras)
```

**3b.** Em `src/gerenet/automation/discovery.py`:

- Apagar as funções `_equivalencia_vrp` (linhas 801-817) e `_contexto_interface` (linhas 820-845).
- Acrescentar o import junto dos outros de `gerenet.automation`, no topo:

```python
from gerenet.automation import subinterface
```

- Trocar os dois usos:
  - em `_contexto_peer`, `linhas.add(_mascara_senha(...))` fica como está; o que muda é o `_normaliza_linhas`, que passa a chamar `subinterface.equivalencia_vrp(texto)`;
  - em `conferir_fidelidade`, `_contexto_interface(texto, proposta.subinterface)` vira `subinterface.linhas_da_interface(texto, proposta.subinterface)`.

Para localizar todos os usos:

```bash
grep -n "_equivalencia_vrp\|_contexto_interface" src/gerenet/automation/discovery.py
```

Cada ocorrência vira `subinterface.equivalencia_vrp` ou `subinterface.linhas_da_interface`, respectivamente.

**3c.** Em `src/gerenet/automation/changes.py`, trocar o ramo da subinterface em `_ja_existe` por:

```python
    if bloco.tipo == "subinterface":
        comandos = bloco.comandos or [""]
        nome = comandos[0].split(None, 1)[1] if " " in comandos[0] else ""
        if nome not in {i.get("nome") for i in recursos.get("interfaces", [])}:
            return False
        # O nome está lá, mas o bloco pode estar sem a `description` e o QoS
        # desta frente (§6): quem responde é o texto da configuração coletada.
        # Backup ausente devolve conjunto vazio, e daí o bloco ENTRA no plano —
        # é a direção conservadora: refazer um bloco idempotente é melhor do que
        # dar por presente o que ninguém conseguiu conferir.
        return subinterface.conteudo_conforme(
            bloco.comandos, subinterface.linhas_da_interface(texto, nome)
        )
```

E acrescentar o import no topo de `changes.py`, junto dos de `gerenet.automation`:

```python
from gerenet.automation import subinterface
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/automation/test_subinterface.py tests/automation/test_changes.py tests/automation/test_discovery.py -q`
Expected: PASS. Em `test_changes.py`, o helper `_snapshot_encontrado` escreve `r.texto` no arquivo do backup — e `BlocoRender.texto` é **plano, sem indentação**, então `linhas_da_interface` não encontra bloco nenhum ali e `test_plan_provision_pula_blocos_ja_presentes` passa a falhar. O conserto é o helper escrever a configuração com a forma do equipamento (cabeçalho na coluna 0, sub-comandos indentados com um espaço). Substituir a linha do `write_text` em `_snapshot_encontrado` por:

```python
    # A forma do `display current-configuration`: cabeçalho na coluna 0 e
    # sub-comandos indentados. O `RenderResult.texto` é plano, e escrevê-lo
    # como veio daria um backup em que nenhum bloco de interface existe — o
    # plano deixaria de pular o que já está lá e o teste mediria outra coisa.
    corpo = "\n#\n".join(
        "\n".join([b.comandos[0], *(f" {c}" for c in b.comandos[1:])])
        for b in r.blocos
    )
    arquivo.write_text(corpo + "\n", encoding="utf-8")
```

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/subinterface.py src/gerenet/automation/discovery.py \
        src/gerenet/automation/changes.py tests/automation/test_subinterface.py \
        tests/automation/test_changes.py
git commit -m "feat(plano): o bloco da subinterface só é pulado por inteiro

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: O estado `atualizar` na execução

**Files:**
- Modify: `src/gerenet/automation/runner.py:452-475` (`_estado_do_bloco`), `567-601` (`_re_diff`), `618-640` (`_verifica_aplicados`)
- Test: `tests/automation/test_runner_change.py`

**Interfaces:**
- Consumes: `subinterface.linhas_da_interface`, `subinterface.conteudo_conforme` (Task 4).
- Produces: `_estado_do_bloco` passa a poder devolver a string `"atualizar"`. É o quarto valor possível, ao lado de `ausente`/`consta`/`conflito`.

- [ ] **Step 1: Write the failing test**

Primeiro os imports. `tests/automation/test_runner_change.py` já traz
`from gerenet.automation.runner import _estado_do_bloco, _mascarar_texto, run_change`
e `from pathlib import Path`; `_re_diff` e `_verifica_aplicados` entram nessa
mesma linha do runner, e o `SimpleNamespace` vai junto dos imports da biblioteca:

```python
from types import SimpleNamespace

from gerenet.automation.runner import (
    _estado_do_bloco, _mascarar_texto, _re_diff, _verifica_aplicados, run_change,
)
```

Depois, ao fim do arquivo:

```python
_SUB_COM_DESCRICAO = {
    "tipo": "subinterface", "objeto": "circuit", "objeto_id": 1, "acao": "create",
    "comandos": ["interface GE1/0/0.2", "description CIRC-2 ACME [1G]",
                 "vlan-type dot1q vid 2", "ip address 10.0.0.0 255.255.255.254",
                 "statistic enable", "qos car cir 1024000 inbound",
                 "qos car cir 1024000 outbound"],
}

# O que o VRP grava depois de aplicar a forma curta (§2).
_BACKUP_CONFORME = (
    "#\n"
    "interface GE1/0/0.2\n"
    " description CIRC-2 ACME [1G]\n"
    " vlan-type dot1q 2\n"
    " ip address 10.0.0.0 255.255.255.254\n"
    " statistic enable\n"
    " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
    " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
    "#\n"
)


def _recursos_com_subif(*enderecos_v4: str) -> dict:
    """Recursos no formato da coleta, com a subinterface do bloco presente.

    O nome sai do próprio bloco (`interface GE1/0/0.2` → `GE1/0/0.2`), como
    `_estado_subif_presenca` faz — os dois helpers ficam lado a lado no mesmo
    formato de dicionário.
    """
    nome = _SUB_COM_DESCRICAO["comandos"][0].split(None, 1)[1]
    return {
        "interfaces": [{
            "nome": nome, "phy": "up", "protocolo": "up",
            "enderecos_v4": list(enderecos_v4), "enderecos_v6": [], "vpn": None,
        }],
    }


_ENDERECO_DO_BLOCO = "10.0.0.0/31"

> **Ruling do pré-voo, 5.** Esta linha trazia `"10.0.0.0 255.255.255.254"`, a
> forma como o comando aparece no bloco do render. Mas o valor alimenta o lado
> **encontrado** (`_recursos_com_subif`), que é o formato do merge:
> `_enderecos_do_bloco` normaliza para `addr/prefixlen`
> (`runner.py:402` — `f"{endereco}/{prefixlen}"`), e é contra ele que a
> identidade do bloco é conferida. Com o literal antigo a conferência compara
> `"10.0.0.0/31"` contra `["10.0.0.0 255.255.255.254"]`, não acha, e devolve
> `conflito` — cinco dos seis testes novos não teriam como passar, e o próprio
> Step 2 desta tarefa dizia que o RED esperado era os vizinhos devolverem
> `consta`. O Step 2 estava certo e o Step 1 estava errado. O valor correto é o
> mesmo formato de `test_runner.py:348`. — **Custo se errado:** a tarefa não
> fecha; o implementer ou para em `BLOCKED` ou gasta uma rodada descobrindo que
> o defeito é do dado de teste, não do código. Levantado pela execução da
> Task 5, e emendado no commit seguinte.


def test_estado_subinterface_com_descricao_e_qos_consta() -> None:
    estado = _estado_do_bloco(
        _SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), _BACKUP_CONFORME
    )
    assert estado == "consta"


def test_estado_subinterface_sem_a_descricao_e_atualizar() -> None:
    """Nome e endereços batem e falta a descrição: é o caso do parque que já
    existe, que sem isto sairia "nada a aplicar" e nunca convergiria (§6)."""
    backup = _BACKUP_CONFORME.replace(" description CIRC-2 ACME [1G]\n", "")
    estado = _estado_do_bloco(_SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), backup)
    assert estado == "atualizar"


def test_estado_subinterface_sem_o_qos_e_atualizar() -> None:
    backup = _BACKUP_CONFORME.replace(
        " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n", ""
    )
    estado = _estado_do_bloco(_SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), backup)
    assert estado == "atualizar"


def test_estado_subinterface_com_outra_taxa_e_atualizar() -> None:
    """Taxa diferente não é "já presente": o plano pede 1 Gbps e o equipamento
    tem 500 Mbps."""
    backup = _BACKUP_CONFORME.replace("1024000", "500000")
    estado = _estado_do_bloco(_SUB_COM_DESCRICAO, _recursos_com_subif(_ENDERECO_DO_BLOCO), backup)
    assert estado == "atualizar"


def test_re_diff_aplica_o_atualizar_e_nao_aborta_com_um_completo() -> None:
    """O abort de "apenas parte do plano consta" olha só os creates que constam.
    Um plano com um bloco completo e outro a atualizar abortaria em falso se o
    `atualizar` caísse no `a_pular` (§6)."""
    completo = dict(_SUB_COM_DESCRICAO)
    a_atualizar = {
        **_SUB_COM_DESCRICAO, "objeto_id": 2,
        "comandos": [*_SUB_COM_DESCRICAO["comandos"]],
    }
    a_atualizar["comandos"][1] = "description CIRC-3 OUTRA [1G]"
    a_aplicar, a_pular, erro = _re_diff(
        [completo, a_atualizar], _recursos_com_subif(_ENDERECO_DO_BLOCO), _BACKUP_CONFORME
    )
    assert erro is None
    assert a_pular == [completo]
    assert a_aplicar == [a_atualizar]


def test_pos_check_marca_atualizar_como_atencao_e_nao_como_critica(tmp_path: Path) -> None:
    """O pós-check confere presença por identidade; o conteúdo que não chegou
    inteiro é atenção (§6) — o bloco está lá, e é isso que o pós-check sabe
    medir.

    O backup vai sem a descrição: é o estado que o `atualizar` deixa quando o
    VRP recusa a linha, e é ele que o pós-check lê de verdade
    (`removal.texto_backup`) em vez de um `raw_files` vazio.
    """
    arquivo = tmp_path / "cfg.txt"
    arquivo.write_text(_BACKUP_CONFORME.replace(" description CIRC-2 ACME [1G]\n", ""),
                       encoding="utf-8")
    step = SimpleNamespace(plano_json=[_SUB_COM_DESCRICAO])
    snap = SimpleNamespace(
        resources=_recursos_com_subif(_ENDERECO_DO_BLOCO),
        raw_files={"config_backup": [str(arquivo)]},
    )
    items = _verifica_aplicados(step, snap)
    assert [i["severidade"] for i in items] == ["atencao"]
    assert items[0]["tipo"] == "subinterface.conteudo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_runner_change.py -q -k "atualizar or conteudo"`
Expected: FAIL — `test_estado_subinterface_sem_a_descricao_e_atualizar` e os vizinhos devolvem `"consta"`, e `_verifica_aplicados` devolve lista vazia.

- [ ] **Step 3: Write minimal implementation**

**3a.** O import, no topo de `src/gerenet/automation/runner.py`, junto dos de `gerenet.automation`:

```python
from gerenet.automation import subinterface
```

**3b.** Em `_estado_do_bloco`, no ramo `if tipo == "subinterface":`, trocar o trecho entre `esperados = _enderecos_do_bloco(comandos)` e o `return "consta"` final do ramo por:

```python
        # create: identidade é nome + endereços que o plano congelado promete —
        # nome presente SEM o endereço esperado é a divergência do §5.3, nunca
        # "já presente" (revisão T6 F1).
        esperados = _enderecos_do_bloco(comandos)
        encontrada = encontradas[0]
        for chave, coluna in (("v4", "enderecos_v4"), ("v6", "enderecos_v6")):
            if any(esperado not in encontrada.get(coluna, []) for esperado in esperados.get(chave, [])):
                return "conflito"
        # Nome e endereços batem; falta saber se a `description` e o QoS do
        # bloco estão lá — é o que separa "consta" de "atualizar" (§6).
        if subinterface.conteudo_conforme(
            comandos, subinterface.linhas_da_interface(texto, nome)
        ):
            return "consta"
        return "atualizar"
```

(o `if not esperados: return "consta"` original sai: com `esperados` vazio o laço
não itera e a decisão passa a ser do conteúdo, que devolve `consta` quando o
bloco também não tem `description` nem `qos car` — o mesmo resultado de antes
para os blocos dos testes, sem um caminho a menos.)

Atualizar também a docstring da função, na lista de estados que ela devolve:

```
    prefix_list e route-policy pelo padrão de texto no backup. Subinterface com
    nome e endereços no lugar mas sem a `description` ou o QoS do bloco é
    "atualizar": o bloco vai inteiro ao equipamento (§6).
```

**3c.** Em `_re_diff`, trocar o corpo **inteiro** da função a partir de
`a_aplicar: list[dict] = []` e incluindo a condição do abort por:

> **Ruling do pré-voo, 2 de 2 — leia antes de escrever.** A versão anterior
> deste passo mandava só acrescentar `elif estado == "atualizar": a_aplicar.append(bloco)`
> ao laço, e deixava a condição do abort como estava:
> `if a_aplicar and any(bloco.get("acao", "create") == "create" for bloco in a_pular)`.
> **Isso não funciona, e o Step 1 desta tarefa prende a falha**:
> `test_re_diff_aplica_o_atualizar_e_nao_aborta_com_um_completo` monta um plano com
> um bloco completo (create → `consta` → `a_pular`) e outro a atualizar
> (create → `atualizar` → `a_aplicar`), e a condição antiga lê exatamente isso
> como "parte do plano consta" e aborta. O teste espera `erro is None`.
>
> O que a §6 pede é que `atualizar` **não conte** como evidência de plano velho —
> e a condição antiga conta, porque o lado dela que mede "há algo a aplicar" é o
> `a_aplicar` inteiro. O abort precisa dos dois lados separados por estado: os
> creates que **constam** e os blocos que a aplicação manda por o objeto
> **faltar ou haver remoção**. `atualizar` não é nenhum dos dois.
> **Custo se estiver errado:** sem esta correção o teste falha e a tarefa não
> fecha; corrigindo só o lado do teste (afrouxar o `assert`), o parque que já
> existe continuaria sem convergir em planos mistos.

```python
    a_aplicar: list[dict] = []
    a_pular: list[dict] = []
    # Os dois lados do abort de plano velho (§12.2): `constam` são os creates que
    # o plano prometia criar e já estão completos; `por_ausencia` é o que a
    # aplicação manda por o objeto faltar ou por haver remoção a fazer. Só os
    # blocos que NÃO são delete entram em `constam`, então ele é só de creates.
    constam: list[dict] = []
    por_ausencia: list[dict] = []
    for bloco in blocos:
        estado = _estado_do_bloco(bloco, recursos, texto)
        if estado == "conflito":
            return [], [], (
                f"Estado divergente no objeto {bloco['tipo']} (#{bloco.get('objeto_id')}): "
                "identidade do encontrado não confere com o plano (§5.3)."
            )
        if bloco.get("acao", "create") == "delete":
            if estado == "ausente":
                a_pular.append(bloco)
            else:
                a_aplicar.append(bloco)
                por_ausencia.append(bloco)
        elif estado == "atualizar":
            # §6: nome e endereços batem e falta descrição ou QoS. Vai para a
            # APLICAÇÃO — e fica FORA dos dois lados do abort logo abaixo. O
            # objeto está no equipamento (não é ausente) e o que falta é
            # conteúdo desta frente (não é consta). Contá-lo de qualquer um dos
            # lados abortaria um plano legítimo com um circuito completo e outro
            # para atualizar, que são dois creates.
            a_aplicar.append(bloco)
        elif estado == "consta":
            a_pular.append(bloco)
            constam.append(bloco)
        else:
            a_aplicar.append(bloco)
            por_ausencia.append(bloco)
    if por_ausencia and constam:
        # Só create consta+ausente no mesmo plano é divergência (plano congelado
        # desatualizado, §12.2). Remove (delete) parcial é natural: pular o que
        # já não existe e remover o que existe é a própria idempotência (§3.2) —
        # sem abort, o step reexecutável converge sem reconciliar o plano.
        bloco = constam[0]
        return [], [], (
            f"Estado divergente no objeto {bloco['tipo']} (#{bloco.get('objeto_id')}): apenas "
            "parte do plano consta do encontrado (config inalterada? §12.2) — "
            "reexecute com plano atualizado."
        )
    return a_aplicar, a_pular, None
```

As duas listas novas preservam o comportamento anterior **exatamente** para os
estados que já existiam: antes do `atualizar`, `a_aplicar` continha os creates
ausentes mais os deletes presentes, e `a_pular` os creates constam — que é
exatamente `por_ausencia` e `constam`. `atualizar` é o único estado novo, e é o
único que fica de fora.

E atualizar a docstring da função, acrescentando à lista de regras:

```
    Regras: conflito de identidade (ex.: mesmo (afi, peer) com ASN diferente)
    ⇒ aborta; tudo consta ⇒ pulado; tudo ausente ⇒ aplica; mistura de constas
    e ausentes entre creates ⇒ aborta — o plano congelado ficou desatualizado
    (config inalterada? §12.2). `atualizar` aplica e NÃO conta como evidência
    de plano velho (§6). Devolve (a_aplicar, a_pular, erro_divergencia).
```

**3d.** Em `_verifica_aplicados`, acrescentar o ramo depois do `elif estado in ("ausente", "conflito"):`:

```python
        elif estado == "atualizar":
            # §6: o bloco está lá pelo que o pós-check mede (nome + endereços);
            # o que não chegou foi a descrição ou o QoS. Atenção, e não crítica:
            # o que é crítico é o objeto não estar no equipamento.
            items.append({
                "tipo": f"{bloco['tipo']}.conteudo", "severidade": "atencao",
                "esperado": f"{objeto} com a descrição e o QoS do plano",
                "encontrado": f"{objeto} sem a descrição ou o QoS",
                "acao": "Conferir a configuração da subinterface no equipamento.",
            })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/automation/test_runner_change.py tests/automation/test_runner.py -q`
Expected: PASS. Os três testes F1 de `_SUB_BLOCO` (`consta`/`conflito`/`conflito`) continuam passando sem tocar neles: aquele bloco não tem `description` nem `qos car`, então `conteudo_conforme` devolve `True` e o estado segue `consta`.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/runner.py tests/automation/test_runner_change.py
git commit -m "feat(execução): a subinterface pela metade vira estado 'atualizar'

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: O parser lê o `qos car`, e a descrição passa a ser gerenciada

**Files:**
- Modify: `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py` (dataclass `Subinterface`, `_aplica_sub`, `_monta_sub`, e o dict do bloco de interface)
- Modify: `src/gerenet/automation/discovery.py` (`_NAO_GERENCIADAS_SUBINTERFACE`, `Proposta`, `_velocidade_do_qos`, a montagem da proposta)
- Modify: `src/gerenet/domain/schemas.py` (`PropostaOut`)
- Modify: `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt`
- Test: `tests/automation/test_config_vrp.py`, `tests/automation/test_discovery.py`
- Test: `tests/cli/test_discovery_cli.py` (a asserção que pinava a `description` no grupo "não gerenciado" — Ruling do pré-voo, 7)

> **Ruling do pré-voo, 7 — o `Files:` desta tarefa estava curto de um arquivo.**
> `tests/cli/test_discovery_cli.py` pina a `description` no bloco do grupo que
> **não** gateia, e é exatamente o que esta tarefa muda: a `description` sai de
> `_NAO_GERENCIADAS_SUBINTERFACE` e passa a exigir ciente. O arquivo quebra, e
> nenhuma outra tarefa do plano o lista. A asserção passa a apontar para o bloco
> das que exigem ciente.
> **Custo se errado:** a frente fecharia com um teste de CLI vermelho, fora do
> conjunto conhecido de descoberta/adoção — e o vermelho seria lido como
> regressão da Task 6 em vez de lacuna da lista de arquivos.

**Interfaces:**
- Consumes: nada das tarefas anteriores (é leitura pura).
- Produces: `config_vrp.Subinterface.qos_cir: int | None`; `Proposta.velocidade_mbps: int | None`; `PropostaOut.velocidade_mbps`. A Task 7 consome `Proposta.velocidade_mbps` para sugerir a taxa na revisão da adoção.

- [ ] **Step 1: Write the failing test**

Acrescentar ao fim de `tests/automation/test_config_vrp.py`:

```python
def test_le_o_qos_car_da_subinterface() -> None:
    """O `cir` é a taxa que o equipamento aplica; a revisão da adoção a sugere
    como velocidade do circuito (§7)."""
    config = parse_config_vrp(
        "interface Eth-Trunk127.626\n"
        " vlan-type dot1q 626\n"
        " description CIRC-626 NETMAC [1G]\n"
        " statistic enable\n"
        " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
        " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
    )
    (sub,) = config.subinterfaces
    assert sub.qos_cir == 1024000


def test_subinterface_sem_qos_nao_tem_cir() -> None:
    config = parse_config_vrp(
        "interface Eth-Trunk127.100\n vlan-type dot1q 100\n statistic enable\n"
    )
    (sub,) = config.subinterfaces
    assert sub.qos_cir is None


def test_qos_car_com_valor_torto_vira_aviso() -> None:
    """A mesma tolerância do `mtu`: a leitura avisa e segue, em vez de estourar
    na configuração inteira por causa de uma linha."""
    config = parse_config_vrp(
        "interface Eth-Trunk127.100\n vlan-type dot1q 100\n qos car cir xyz inbound\n"
    )
    (sub,) = config.subinterfaces
    assert sub.qos_cir is None
    assert any("qos car" in a for a in config.avisos)
```

E acrescentar ao fim de `tests/automation/test_discovery.py`:

> **Ruling do pré-voo, 8 — o literal de um destes testes era impossível.** A
> versão anterior do `test_cir_nao_multiplo_de_mil_nao_sugere_velocidade` trazia
> `cir 1500000` no texto e no docstring, mas `1500000 % 1000 == 0` e
> `1500000 // 1000 == 1500`: a `_velocidade_do_qos` do próprio plano devolve
> `1500`, e o `assert ... is None` não tem como passar. O docstring dizia o
> motivo em voz alta — "são 1,5 Gbps" — e 1,5 Gbps em kbps é um número inteiro
> de Mbps; o guard é `% 1000` (Mbps exato), não "Gbps redondo". O literal passa
> a `1536500` (1536,5 Mbps), que é o caso que o nome do teste descreve.
> **Custo se errado:** um teste que nunca passa não é cobertura do caminho de
> recusa — ele fica vermelho, alguém troca o `assert` por `== 1500` para
> "consertar" e a guarda do divisor inexato perde o único teste que tinha.

```python
def test_a_velocidade_vem_do_qos_do_equipamento(db_session, tmp_path) -> None:
    """Num enlace que já tem QoS ninguém digita a taxa à mão (§7)."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2701\n"
               " vlan-type dot1q 2701\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               " statistic enable\n"
               " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
               " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " ipv4-family unicast\n"
               "  peer 100.64.10.1 enable\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert prop.velocidade_mbps == 1024


def test_cir_nao_multiplo_de_mil_nao_sugere_velocidade(db_session, tmp_path) -> None:
    """O divisor é inteiro: `cir 1536500` são 1536,5 Mbps, e arredondar aqui vira
    QoS errado no equipamento mais adiante (§7). A sugestão fica vazia."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2702\n"
               " vlan-type dot1q 2702\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               " qos car cir 1536500 inbound\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " ipv4-family unicast\n"
               "  peer 100.64.10.1 enable\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert prop.velocidade_mbps is None
```

E substituir `test_diferenca_separa_o_que_a_sot_nao_gerencia` por:

```python
def test_a_descricao_da_subinterface_passa_a_gatear(db_session, tmp_path) -> None:
    """A descrição saiu do grupo que não gateia (§7): a SoT passou a emiti-la, e
    o que o equipamento tem de diferente é mudança que a adoção faria."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    diferencas = conferir_fidelidade(db_session, alfa)
    sub = next(d for d in diferencas if d.contexto == "subinterface")
    assert any("description" in linha for linha in sub.faltando + sub.sobrando)
    assert not any("description" in linha for linha in sub.nao_gerenciado)
    assert sub.exige_ciente is True
```

E substituir `test_exige_ciente_so_quando_o_render_mudaria_o_equipamento` por duas:

```python
def test_a_conferencia_casa_quando_a_revisao_traz_a_identidade(db_session, tmp_path) -> None:
    """Com o código e a organização da revisão, o render emite exatamente a
    descrição que o equipamento tem — e aí não sobra diferença nenhuma.

    É o que faz a revisão da adoção não pedir `ciente` para um enlace cuja
    descrição já segue o formato do §4."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2801\n"
               " vlan-type dot1q 2801\n"
               " description CIRC-2801 NETMAC [1G]\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               " statistic enable\n"
               " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
               " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " ipv4-family unicast\n"
               "  peer 100.64.10.1 enable\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas
    sub = next(
        d for d in conferir_fidelidade(
            db_session, prop, circuit_code="CIRC-2801", organizacao_nome="NETMAC",
            velocidade_mbps=1024,
        )
        if d.contexto == "subinterface"
    )
    assert sub.faltando == ()
    assert sub.sobrando == ()
    assert sub.exige_ciente is False
```

E, no lugar de `test_mtu_da_subinterface_tambem_sai_do_que_gateia`, manter a intenção original (o `mtu` não gateia) com a identidade que zera o resto:

```python
def test_mtu_da_subinterface_tambem_sai_do_que_gateia(db_session, tmp_path) -> None:
    """A subinterface tem `mtu` e a SoT não o emite: sozinho, ele não pode
    exigir ciente. Com a descrição casando pela revisão, o que sobra é só ele —
    e é este teste que exercita o braço do `"mtu "` da tupla. Sem ele, uma
    entrada apagada passaria na suíte inteira."""
    dev = _ambiente(db_session)
    _com_texto(db_session, dev, tmp_path,
               "interface Eth-Trunk127.2601\n"
               " vlan-type dot1q 2601\n"
               " description CIRC-2601 NETMAC [1G]\n"
               " ip address 100.64.10.0 255.255.255.254\n"
               " mtu 9000\n"
               " statistic enable\n"
               " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
               " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
               "#\n"
               "bgp 65001\n"
               " peer 100.64.10.1 as-number 64512\n"
               " ipv4-family unicast\n"
               "  peer 100.64.10.1 enable\n")
    (prop,) = listar_propostas(db_session, dev.id).propostas

    sub = next(
        d for d in conferir_fidelidade(
            db_session, prop, circuit_code="CIRC-2601", organizacao_nome="NETMAC",
            velocidade_mbps=1024,
        )
        if d.contexto == "subinterface"
    )

    assert sub.nao_gerenciado == ("mtu 9000",)
    assert sub.faltando == ()
    assert sub.sobrando == ()
    assert sub.exige_ciente is False
```

> `conferir_fidelidade` ganha os três parâmetros de identidade na Task 7. Se a
> Task 6 for executada antes dela, os dois testes acima falham com
> `TypeError: conferir_fidelidade() got an unexpected keyword argument`. **Se
> isso acontecer, os dois testes entram no commit da Task 7** e não no da 6 —
> a Task 6 entrega o resto da suíte verde.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_config_vrp.py tests/automation/test_discovery.py -q -k "qos or velocidade or descricao or mtu or ciente"`
Expected: FAIL — `Subinterface` não tem `qos_cir`, `Proposta` não tem `velocidade_mbps`.

- [ ] **Step 3: Write minimal implementation**

**3a.** Em `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py`, na dataclass `Subinterface`:

```python
    descricao: str | None
    mtu: int | None
    qos_cir: int | None           # `cir` do `qos car`, em kbps (None sem QoS)
```

**3b.** No dict que abre o bloco de interface, acrescentar a chave (a linha que hoje tem `"descricao": None, "mtu": None, "v4": [], "v6": []`):

```python
                         "descricao": None, "mtu": None, "qos_cir": None, "v4": [], "v6": []}
```

**3c.** Em `_aplica_sub`, acrescentar o ramo depois do `elif linha.startswith("mtu ")`:

```python
    elif linha.startswith("qos car cir "):
        # `qos car cir <cir> [cbs <...> green pass red discard] inbound|outbound`:
        # o `cir` é o quarto token nas duas formas, e as duas direções carregam o
        # mesmo valor. A primeira ocorrência vence.
        if reg["qos_cir"] is None and len(partes) > 3:
            cir = _int_tolerante(partes[3], avisos, linha)
            if cir is not None:
                reg["qos_cir"] = cir
```

**3d.** Em `_monta_sub`:

```python
        mtu=reg["mtu"], qos_cir=reg["qos_cir"],
        enderecos_v4=tuple(reg["v4"]), enderecos_v6=tuple(reg["v6"]),
```

**3e.** Em `src/gerenet/automation/discovery.py`, trocar as duas linhas de `_NAO_GERENCIADAS_SUBINTERFACE` por:

```python
# Linhas de subinterface que o render não emite. A `description` SAIU daqui: o
# render passou a emiti-la (§4) e a SoT passou a gerenciá-la, então uma
# descrição diferente no equipamento é diferença que exige ciente (§7). O `mtu`
# fica: não há MTU de subinterface no modelo nem no template.
_NAO_GERENCIADAS_SUBINTERFACE = ("mtu ",)
```

E atualizar a docstring de `_particiona_subinterface`, que ainda diz que o render não tem descrição:

```python
    """Separa o que a SoT gerencia do que ela só não emite (design §17.1).

    O que sobra é o `mtu`, que não existe no modelo nem no template, e numa
    borda real está em toda subinterface. Deixá-lo no `faltando` faria
    "diferença exige ciente" degenerar em "marque sempre". A `description`
    esteve aqui até a frente da velocidade; hoje a SoT a emite (§4), e uma
    descrição divergente é mudança de verdade.
    """
```

**3f.** Na dataclass `Proposta`, depois de `qinq: bool = False`:

```python
    velocidade_mbps: int | None = None
```

**3g.** Acrescentar a função perto de `_trunk_da_subinterface`:

```python
def _velocidade_do_qos(sub) -> int | None:
    """O `cir` do equipamento na unidade do campo, só quando o divisor é exato (§7).

    `cir` é kbps e a velocidade é Mbps: `1024000` vira `1024`. Não múltiplo de
    1000 é captura estranha, e a sugestão fica vazia em vez de arredondar —
    um número inventado aqui vira QoS errado no equipamento mais adiante.
    """
    if sub.qos_cir is None or sub.qos_cir <= 0 or sub.qos_cir % 1000:
        return None
    return sub.qos_cir // 1000
```

**3h.** Na montagem da proposta nova (o bloco `proposta = Proposta(` que hoje termina em `circuit_code_sugerido=...`), acrescentar o campo logo depois de `qinq=sub.qinq,`:

```python
                    velocidade_mbps=_velocidade_do_qos(sub),
```

**3i.** Em `src/gerenet/domain/schemas.py`, em `PropostaOut`, depois de `qinq: bool`:

```python
    velocidade_mbps: int | None
```

**3j.** Na fixture `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt`, na subinterface `.1001`, acrescentar as duas linhas do QoS depois do `statistic enable` (a fixture é derivada dos templates deste projeto, e o render passou a emiti-las):

```
 statistic enable
 qos car cir 1024000 cbs 18700000 green pass red discard inbound
 qos car cir 1024000 cbs 18700000 green pass red discard outbound
#
```

São as linhas **na forma do VRP**, com o `cbs` e as ações que ele completa — a
fixture imita o que o equipamento grava, não o que o render manda.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/automation/test_config_vrp.py tests/automation/test_discovery.py tests/automation/test_parsers_golden.py -q`
Expected: PASS nos testes novos. **Os testes existentes de `test_discovery.py` que pinam a descrição como não gerenciada vão falhar** — a lista deles saiu do Step 1. Se algum outro falhar, é porque pina o mesmo comportamento antigo (a descrição fora do gate); ajuste a expectativa para o novo, sem afrouxar a asserção: a descrição agora aparece em `faltando`/`sobrando` e conta para `exige_ciente`.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/parsers/huawei_vrp/config_vrp.py src/gerenet/automation/discovery.py \
        src/gerenet/domain/schemas.py tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt \
        tests/automation/test_config_vrp.py tests/automation/test_discovery.py
git commit -m "feat(descoberta): a descrição da subinterface passa a ser gerenciada, e o QoS é lido

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: A adoção leva a velocidade, e o ensaio leva a identidade da revisão

**Files:**
- Modify: `src/gerenet/automation/discovery.py` (`_ensaio`, `conferir_fidelidade`)
- Modify: `src/gerenet/domain/schemas.py` (`AdocaoIn`)
- Modify: `src/gerenet/domain/services/discovery.py` (`adotar_proposta`)
- Modify: `src/gerenet/api/routers/discovery.py` (`GET /fidelidade`)
- Test: `tests/domain/test_adocao.py`
- Test: `tests/api/test_discovery_adopt_api.py` (`test_fidelidade_sob_demanda` — Ruling do pré-voo, 4)

**Interfaces:**
- Consumes: `Proposta.velocidade_mbps` (Task 6).
- Produces:
  - `conferir_fidelidade(session, proposta, *, perfis=None, edge_trunk=None, circuit_code=None, organizacao_id=None, organizacao_nome=None, velocidade_mbps=None)` — os quatro últimos são a identidade da revisão.
  - `schemas.AdocaoIn.velocidade_mbps: int | None`.
  - `GET /api/v1/discovery/fidelidade` com os query params `circuit_code`, `organizacao_id`, `organizacao_nome`, `velocidade_mbps`.
  A Task 9 consome os quatro params na web.

> **Ruling do pré-voo, 10 — a lista de testes quebrados estava certa, mas o
> `Files:` desta tarefa não virava dois deles em passo nenhum.** O Ruling do
> pré-voo, 4 já dizia que `test_a_conferencia_usa_o_trunk_da_revisao` "precisa
> passar a identidade" e que `tests/api/test_discovery_adopt_api.py` entra nesta
> tarefa. Nenhum dos dois tinha passo, e o `git add` do Step 5 não levava o
> arquivo da API. Medido agora, antes de despachar: os cinco vermelhos de hoje
> são os quatro de `tests/domain/test_adocao.py`
> (`test_ensaio_fiel_aceita_sem_ciente`,
> `test_a_auditoria_leva_todas_as_diferencas`,
> `test_a_conferencia_usa_o_trunk_da_revisao`,
> `test_familia_a_mais_na_revisao_recusa`) e o
> `test_fidelidade_sob_demanda` da API. Os Steps 1b, 1c e 1d fecham três; os
> passos 1f e 1g abaixo fecham os dois que faltavam.
>
> E a identidade sozinha **não** bastava para o do trunk: no enlace da fixture a
> descrição do equipamento é `CLIENTE-ALFA` e o render nunca a emite nessa forma
> (ele monta `<CÓDIGO> <ORG>`, `naming.descricao_subinterface`), então o
> `derivado.exige_ciente is False` continua inalcançável com aquele texto. O 1f
> passa a usar o `_CONFIG_FIEL`, que é o único dos dois textos onde o bloco bate
> linha a linha — o mesmo movimento que o 1b já faz.
> **Custo se errado:** a frente fecharia com dois vermelhos sem dono, e um deles
> é o único teste do endpoint que a Task 9 consome.

- [ ] **Step 1: Write the failing test**

Esta tarefa mexe em quatro testes que já existem, e a ordem importa: os que
dependem dos parâmetros novos de `conferir_fidelidade` só passam depois do
Step 3.

**1a. `_revisao` ganha a velocidade.** Em `tests/domain/test_adocao.py`, a
assinatura do helper:

```python
def _revisao(dev, *, vid=1001, ciente=True, edge_trunk="Eth-Trunk127", sessoes=None,
             autorizacoes=None, velocidade_mbps=None):
```

e o `AdocaoIn` que ele monta ganha, depois de `edge_trunk=edge_trunk,`:

```python
        velocidade_mbps=velocidade_mbps,
```

**1b. `_CONFIG_FIEL` ganha a descrição.** O comentário acima do constante diz
que é "um enlace que o render reproduz linha a linha", e isso deixa de ser
verdade quando o render passa a emitir a `description` (§4). Sem a linha aqui,
o ensaio acusa `faltando` de descrição nos dois testes que usam este texto, e o
`ciente=False` de um deles estoura com a mensagem errada — a recusa viria do
`ciente`, e não da família que o teste quer exercitar.

A linha sai de `naming.descricao_subinterface("ADOC-64512-601", "Cliente Alfa", None)`,
a identidade que `_revisao(dev, vid=601)` grava:

```python
_CONFIG_FIEL = (
    "interface Eth-Trunk127.601\n"
    " vlan-type dot1q 601\n"
    " description ADOC-64512-601 CLIENTE ALFA\n"
    " ip address 100.64.10.0 255.255.255.254\n"
    " statistic enable\n"
    "#\n"
    "bgp 65001\n"
    " peer 100.64.10.1 as-number 64512\n"
    " ipv4-family unicast\n"
    "  peer 100.64.10.1 enable\n"
)
```

**1c. `test_ensaio_fiel_aceita_sem_ciente`** passa a conferir com a identidade
da revisão (o `conferir_fidelidade` direto da segunda linha, que hoje vai sem
parâmetro nenhum):

```python
def test_ensaio_fiel_aceita_sem_ciente(db_session, tmp_path) -> None:
    """O outro lado do gate: com o grupo que muda vazio, o aceite é direto
    (design §6). A fixture do ALFA sempre exige `ciente`, então sem este teste
    uma regressão que passasse a exigi-lo sempre deixaria a suíte verde."""
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    prop = _proposta(db_session, dev, vid=601)

    assert not any(
        d.exige_ciente
        for d in conferir_fidelidade(
            db_session, prop, circuit_code="ADOC-64512-601",
            organizacao_nome="Cliente Alfa",
        )
    )

    circ_id = adotar_proposta(
        db_session, proposta=prop, actor="cli",
        revisao=_revisao(dev, vid=601, ciente=False, sessoes=[AdocaoSessaoIn(afi="ipv4")]),
    )
    circ = db_session.get(models.Circuit, circ_id)
    # O `stack` sai das sessões que nasceram: aqui, uma família só.
    assert circ.stack == "ipv4"
    assert circ.edge_trunk == "Eth-Trunk127"
    assert db_session.query(models.BgpSession).count() == 1
```

**1d. `test_a_auditoria_leva_todas_as_diferencas`** prende hoje que o payload
leva o grupo que NÃO gateia, e usa a descrição da subinterface para isso
(`any("description CLIENTE-ALFA" in linha for linha in sub["nao_gerenciado"])`).
Com a descrição gerenciada (§7), o grupo que não gateia é só o `mtu` — e o
enlace do ALFA não tem `mtu`. O teste passa a prender o que continua verdade: o
payload leva os quatro grupos em todo contexto, e a descrição do ALFA aparece
nos dois lados da comparação, porque a adoção grava um código e uma organização
diferentes dos que o equipamento tem.

```python
def test_a_auditoria_leva_todas_as_diferencas(db_session, tmp_path) -> None:
    """O payload é trilha, não decisão: leva os quatro grupos de todo contexto,
    inclusive os vazios (design §17.1). A descrição da subinterface deixou de
    ser "não gerenciada" na frente da velocidade (§7): o equipamento tem a do
    CLIENTE-ALFA e a adoção grava a do código novo, então ela aparece dos dois
    lados — e é por isso que `_revisao` nasce com o `ciente` ligado."""
    _site, dev = _ambiente(db_session, tmp_path)
    adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                    actor="cli")
    evento = db_session.scalar(
        select(models.AuditEvent).where(models.AuditEvent.type == "discovery.adopt")
    )
    payload = evento.details["depois"]
    campos = {"contexto", "sobrando", "faltando", "nao_gerenciado", "explicacao"}
    assert all(set(d) == campos for d in payload["diferencas"])
    assert payload["edge_trunk"] == "Eth-Trunk127"
    sub = next(d for d in payload["diferencas"] if d["contexto"] == "subinterface")
    assert any("CLIENTE-ALFA" in linha for linha in sub["faltando"])
    assert any("ADOC-64512-1001 CLIENTE ALFA" in linha for linha in sub["sobrando"])
    assert sub["nao_gerenciado"] == []
```

> `_revisao(dev)` usa `organizacao_nova={"name": "Cliente Alfa", ...}` e
> `circuit_code="ADOC-64512-1001"`: a descrição que o ensaio emite é
> `ADOC-64512-1001 CLIENTE ALFA` (sem velocidade, que nasce `None`), e a do
> equipamento é `CLIENTE-ALFA`.
>
> **Ruling 20 — os dois lados estavam trocados, e a prosa acima sempre esteve
> certa.** `Diferenca` monta `sobrando=esperado - encontrado` e
> `faltando=encontrado - esperado` (`src/gerenet/automation/discovery.py:1265-1266`),
> com `esperado` sendo o que o **render** produz: logo `sobrando` é o que o render
> emite e o equipamento não tem, e `faltando` é o inverso. O snippet prende
> `CLIENTE-ALFA` (do equipamento) no `sobrando` e `ADOC-64512-1001 CLIENTE ALFA`
> (do render) no `faltando` — exatamente ao contrário do que a prosa do bloco
> logo abaixo descreve, e ao contrário do Step 1g deste mesmo documento, que
> está certo (`description CLIENTE-ALFA` no `faltando`, `description ENSAIO-` no
> `sobrando`, `interface Eth-Trunk9.1001` no `sobrando`). O implementer mediu
> antes de escrever, viu `Left contains one more item: 'description
> ENSAIO-ne8000-adoc-1001 ENSAIO-NE8000-ADOC-1001'` com o lado esquerdo sendo o
> `sobrando`, e escreveu as duas asserções certas — a única divergência
> deliberada do texto literal do brief. Emendado aqui para que a próxima pessoa
> que leia o Step 1d não troque de novo. — **Custo se errado:** nenhum; a
> emenda alinha o snippet à prosa que já estava no mesmo passo e ao Step 1g.

**1e. Os testes novos**, ao fim do arquivo — com os helpers da casa
(`_ambiente(db_session, tmp_path, *, texto=None)` devolve `(site, dev)`,
`_proposta(db_session, dev, *, vid=1001)`, `_revisao(dev, ...)`,
`adotar_proposta(db_session, proposta=..., revisao=..., actor=...)`):

```python
def test_a_velocidade_da_revisao_vai_para_o_circuito(db_session, tmp_path) -> None:
    """A velocidade entra por `AdocaoIn` e é gravada (§7). O par vem do texto
    porque é ele que traz o `qos car` de onde a sugestão sai."""
    _site, dev = _ambiente(
        db_session, tmp_path,
        texto=(
            "interface Eth-Trunk127.601\n"
            " vlan-type dot1q 601\n"
            " ip address 100.64.10.0 255.255.255.254\n"
            " statistic enable\n"
            " qos car cir 1024000 cbs 18700000 green pass red discard inbound\n"
            " qos car cir 1024000 cbs 18700000 green pass red discard outbound\n"
            "#\n"
            "bgp 65001\n"
            " peer 100.64.10.1 as-number 64512\n"
            " ipv4-family unicast\n"
            "  peer 100.64.10.1 enable\n"
        ),
    )
    prop = _proposta(db_session, dev, vid=601)
    assert prop.velocidade_mbps == 1024  # a sugestão veio do equipamento

    circ_id = adotar_proposta(
        db_session, proposta=prop, actor="cli",
        revisao=_revisao(dev, vid=601, velocidade_mbps=1024, ciente=True,
                         sessoes=[AdocaoSessaoIn(afi="ipv4")]),
    )

    assert db_session.get(models.Circuit, circ_id).velocidade_mbps == 1024


def test_a_identidade_da_revisao_tira_a_diferenca_falsa_de_descricao(
    db_session, tmp_path,
) -> None:
    """Sem isto, TODA adoção mostraria uma descrição falsa nos dois lados e
    pediria `ciente`: o ensaio montava o circuito com código `ENSAIO-...` e uma
    organização de mentira, e o render derivava a descrição desses dois (§7)."""
    _site, dev = _ambiente(
        db_session, tmp_path,
        texto=(
            "interface Eth-Trunk127.601\n"
            " vlan-type dot1q 601\n"
            " description ADOC-64512-601 CLIENTE ALFA\n"
            " ip address 100.64.10.0 255.255.255.254\n"
            " statistic enable\n"
            "#\n"
            "bgp 65001\n"
            " peer 100.64.10.1 as-number 64512\n"
            " ipv4-family unicast\n"
            "  peer 100.64.10.1 enable\n"
        ),
    )
    prop = _proposta(db_session, dev, vid=601)

    sem_identidade = next(
        d for d in conferir_fidelidade(db_session, prop) if d.contexto == "subinterface"
    )
    com_identidade = next(
        d for d in conferir_fidelidade(
            db_session, prop, circuit_code="ADOC-64512-601",
            organizacao_nome="Cliente Alfa",
        )
        if d.contexto == "subinterface"
    )

    assert sem_identidade.exige_ciente is True
    assert com_identidade.sobrando == ()
    assert com_identidade.faltando == ()
    assert com_identidade.exige_ciente is False
```

**1f. `test_a_conferencia_usa_o_trunk_da_revisao`** passa a conferir com o
`_CONFIG_FIEL` e com a identidade da revisão. Os dois são necessários e por
motivos diferentes: sem o texto do 601 a descrição do equipamento é
`CLIENTE-ALFA` e o bloco nunca bate, e sem a identidade o ensaio emite a do
`ENSAIO-...`. Só com os dois o `is False` mede o trunk, que é o que o nome do
teste promete.

```python
def test_a_conferencia_usa_o_trunk_da_revisao(db_session, tmp_path) -> None:
    """O ensaio monta o circuito com o trunk da revisão, e não com o derivado do
    nome: com outro trunk o circuito que nasceria tem outro bloco, e a diferença
    tem de aparecer em vez de a comparação sair fiel.

    O `_CONFIG_FIEL` entra porque a `description` da subinterface é gerenciada
    desde a frente da velocidade (§7): só no enlace sem QoS, e com o código e a
    organização da revisão, o bloco bate linha a linha."""
    _site, dev = _ambiente(db_session, tmp_path, texto=_CONFIG_FIEL)
    prop = _proposta(db_session, dev, vid=601)
    identidade = {"circuit_code": "ADOC-64512-601", "organizacao_nome": "Cliente Alfa"}

    derivado = next(d for d in conferir_fidelidade(db_session, prop, **identidade)
                    if d.contexto == "subinterface")
    revisado = next(d for d in conferir_fidelidade(db_session, prop, edge_trunk="Eth-Trunk9",
                                                   **identidade)
                    if d.contexto == "subinterface")

    assert derivado.exige_ciente is False
    assert revisado.exige_ciente is True
```

**1g. `test_fidelidade_sob_demanda`** (`tests/api/test_discovery_adopt_api.py`)
prende hoje que a descrição do ALFA está no grupo que **não** gateia, e a Task 6
tirou-a de lá. O enlace da fixture continua sendo o certo aqui — é o único com
`qos car` dos dois lados, e é ele que dá o que medir da velocidade. O que muda é
o que se prende: a descrição aparece nos dois lados da comparação (o
equipamento tem uma, o ensaio sem identidade emite a do `ENSAIO-...`), o grupo
que não gateia fica vazio, e a velocidade da revisão tira as duas linhas de
`qos car` do diff.

```python
def test_fidelidade_sob_demanda(client, db_session, tmp_path) -> None:
    """A conferência de UMA proposta, sob demanda, com os parâmetros que a revisão
    escolheu: a lista não a traz embutida, porque cada conferência roda um ensaio
    do render inteiro."""
    ambiente = _ambiente(db_session, tmp_path)
    url = (f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}"
           "&subinterface=Eth-Trunk127.1001")
    resposta = client.get(url, headers=_auth())
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["device_id"] == ambiente["dev"].id
    assert corpo["subinterface"] == "Eth-Trunk127.1001"
    assert isinstance(corpo["diferencas"], list)
    assert all({"contexto", "sobrando", "faltando", "nao_gerenciado"} <= set(d)
               for d in corpo["diferencas"])
    # A lista vazia é o outro jeito de este teste passar sem conferir nada: é a
    # descrição da subinterface do ALFA que diz que a proposta comparada é a 1001.
    assert {"peer", "subinterface"} <= {d["contexto"] for d in corpo["diferencas"]}
    sub = next(d for d in corpo["diferencas"] if d["contexto"] == "subinterface")
    # A descrição passou a ser gerenciada (§7), então ela aparece nos DOIS lados
    # quando o ensaio vai sem identidade: a do `ENSAIO-...` sobra no render e a do
    # equipamento falta nele. É essa diferença que exige o ciente.
    assert any("description CLIENTE-ALFA" in linha for linha in sub["faltando"])
    assert any("description ENSAIO-" in linha for linha in sub["sobrando"])
    # O grupo que não gateia é só o `mtu` desde a frente da velocidade, e esta
    # subinterface não tem nenhum: ele sai vazio, e não com a descrição dentro.
    assert sub["nao_gerenciado"] == []
    # O gate do aceite viaja na resposta: é ele que a tela usa para exigir o ciente.
    assert any(d["exige_ciente"] for d in corpo["diferencas"])

    # Sem o trunk a conferência deriva o da subinterface, e o nome do bloco bate
    # dos dois lados; com OUTRO trunk o bloco que nasceria é outro, e o nome
    # divergente aparece dos dois lados. É o parâmetro que a tela manda junto.
    revisado = client.get(f"{url}&edge_trunk=Eth-Trunk9", headers=_auth()).json()
    sub9 = next(d for d in revisado["diferencas"] if d["contexto"] == "subinterface")
    assert "interface Eth-Trunk9.1001" in sub9["sobrando"]
    assert "interface Eth-Trunk127.1001" in sub9["faltando"]
    assert "interface Eth-Trunk127.1001" not in sub["sobrando"] + sub["faltando"]

    # A velocidade da revisão entra na conta do QoS (§5): o equipamento tem
    # `qos car cir 1024000` nas duas direções (a fixture os traz) e o ensaio sem
    # ela não emite taxa nenhuma. Com ela, a dobra do `equivalencia_vrp` casa a
    # forma curta do render com a longa do VRP e as duas somem do diff.
    assert "qos car cir 1024000 inbound" in sub["faltando"]
    com_taxa = client.get(f"{url}&velocidade_mbps=1024", headers=_auth()).json()
    sub_taxa = next(d for d in com_taxa["diferencas"] if d["contexto"] == "subinterface")
    assert not any("qos car" in linha
                   for linha in sub_taxa["sobrando"] + sub_taxa["faltando"])

    # Sem perfil nenhum o ensaio não emite o corpo da política de exportação; com o
    # produto que o operador escolheu na tela, o corpo entra na comparação — e a
    # consulta leva os perfis justamente para a conferência valer sobre eles.
    assert "definicao" not in {d["contexto"] for d in corpo["diferencas"]}
    full = db_session.scalar(select(models.PolicyProfile).where(
        models.PolicyProfile.name == "full", models.PolicyProfile.direction == "export"))
    com_perfil = client.get(f"{url}&export_ipv4={full.id}", headers=_auth()).json()
    definicao = next(d for d in com_perfil["diferencas"] if d["contexto"] == "definicao")
    assert any("RP-64512-EXPORT-V4" in linha for linha in definicao["sobrando"])
    assert definicao["exige_ciente"] is True
```

> O `sub` e o `sub9` vêm do `corpo`/`revisado` **sem** identidade, de propósito:
> o que este teste mede no `subinterface` é que a diferença existe e por que, e
> não que ela some — some só no `1e`, que é do domínio e passa a identidade.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_adocao.py -q -k "velocidade or identidade"`
Expected: FAIL com `TypeError: conferir_fidelidade() got an unexpected keyword argument 'circuit_code'`.

- [ ] **Step 3: Write minimal implementation**

**3a.** Em `src/gerenet/automation/discovery.py`, trocar a assinatura e o começo do corpo de `_ensaio`:

```python
def _ensaio(
    session: Session, proposta: Proposta,
    perfis: dict[str, dict[str, int | None]] | None = None,
    edge_trunk: str | None = None,
    *,
    circuit_code: str | None = None,
    organizacao_id: int | None = None,
    organizacao_nome: str | None = None,
    velocidade_mbps: int | None = None,
) -> dict:
```

e, no corpo, trocar as duas primeiras linhas (`device = ...` / `org_id = proposta.organizacao_id`) e a criação da organização por:

```python
    device = get_device(session, proposta.device_id)
    org_id = organizacao_id or proposta.organizacao_id
    if org_id is None:
        # Sem id, a organização ainda nasceria: é o caso da revisão que cria uma
        # nova. O nome dela vem da revisão, e não do `ENSAIO-...`, porque é ele
        # que a `description` da subinterface carrega — e um nome de mentira
        # aqui faria toda adoção acusar uma diferença de descrição que a escrita
        # não cria (§7).
        org = models.Organization(
            name=organizacao_nome or f"ENSAIO-{device.name}-{proposta.vid}",
            asn=proposta.candidatos[0].asn_remote if proposta.candidatos else None,
        )
        session.add(org)
        session.flush()
        org_id = org.id
```

e a criação do circuito por:

```python
    circ = models.Circuit(
        # O código da revisão: a `description` sai dele (§4), e um código de
        # mentira acusaria diferença em toda adoção.
        code=circuit_code or f"ENSAIO-{device.name}-{proposta.vid}",
        organization_id=org_id,
        site_id=proposta.site_id or device.site_id, access_port="ensaio",
        edge_device_id=device.id,
        # O trunk da revisão vence; sem ela, o derivado do nome da subinterface.
        edge_trunk=edge_trunk if edge_trunk is not None else _trunk_da_subinterface(proposta),
        stack=proposta.stack, vlan_mode=proposta.vlan_mode,
        qinq=proposta.qinq,          # sem isto a fidelidade acusa diferença em todo QinQ
        velocidade_mbps=velocidade_mbps,
        p2p_v4_len=proposta.p2p_v4_len or 31,
    )
```

E acrescentar à docstring de `_ensaio`, depois do parágrafo do `edge_trunk`:

```
    `circuit_code`, `organizacao_id`, `organizacao_nome` e `velocidade_mbps`
    são a identidade que a revisão vai gravar, e entram pela mesma razão do
    trunk: a `description` da subinterface deriva do código do circuito, do nome
    da organização e da velocidade (§4). Sem eles, o ensaio emitiria a descrição
    do código `ENSAIO-...` com a organização de mentira, e TODA adoção acusaria
    uma diferença de descrição que a escrita não cria — pedindo `ciente` para
    assumir uma linha que ninguém mudou.
```

**3b.** Em `conferir_fidelidade`, trocar a assinatura por:

```python
def conferir_fidelidade(
    session: Session, proposta: Proposta,
    *, perfis: dict[str, dict[str, int | None]] | None = None,
    edge_trunk: str | None = None,
    circuit_code: str | None = None,
    organizacao_id: int | None = None,
    organizacao_nome: str | None = None,
    velocidade_mbps: int | None = None,
) -> list[Diferenca]:
```

E a chamada interna do ensaio por:

```python
            criados = _ensaio(
                session, proposta, perfis, edge_trunk,
                circuit_code=circuit_code, organizacao_id=organizacao_id,
                organizacao_nome=organizacao_nome, velocidade_mbps=velocidade_mbps,
            )
```

E acrescentar à docstring, depois do parágrafo do `edge_trunk`:

```
    `circuit_code`, `organizacao_id`, `organizacao_nome` e `velocidade_mbps` são
    o resto da identidade que a adoção vai gravar. A `description` da
    subinterface deriva dos três primeiros (§4) e o `qos car` do quarto (§5):
    com a identidade errada, o ensaio acusa diferença de descrição e de taxa em
    toda adoção, e a revisão degenera em "marque o ciente sempre".
```

**3c.** Em `src/gerenet/domain/schemas.py`, em `AdocaoIn`, depois de `edge_trunk`:

```python
    velocidade_mbps: int | None = Field(default=None, gt=0, le=100000)
```

**3d.** Em `src/gerenet/domain/services/discovery.py`, na chamada de `conferir_fidelidade` dentro de `adotar_proposta`:

```python
    difs = conferir_fidelidade(
        session, proposta, perfis=perfis, edge_trunk=revisao.edge_trunk,
        circuit_code=revisao.circuit_code, organizacao_id=revisao.organizacao_id,
        organizacao_nome=revisao.organizacao_nova.name if revisao.organizacao_nova else None,
        velocidade_mbps=revisao.velocidade_mbps,
    )
```

E, na criação do circuito, acrescentar o campo ao `CircuitCreate`:

```python
                p2p_v4_len=proposta.p2p_v4_len or 31, vrf=proposta.vrf,
                velocidade_mbps=revisao.velocidade_mbps,
```

**3e.** Em `src/gerenet/api/routers/discovery.py`, na assinatura de `fidelidade`:

```python
    edge_trunk: str | None = None,
    circuit_code: str | None = None,
    organizacao_id: int | None = None,
    organizacao_nome: str | None = None,
    velocidade_mbps: int | None = None,
```

e na chamada:

```python
        diferencas = conferir_fidelidade(
            session, proposta, perfis=perfis, edge_trunk=edge_trunk,
            circuit_code=circuit_code, organizacao_id=organizacao_id,
            organizacao_nome=organizacao_nome, velocidade_mbps=velocidade_mbps,
        )
```

Atualizar a docstring da rota, acrescentando:

```
    Os parâmetros de identidade (`edge_trunk`, `circuit_code`,
    `organizacao_id`/`organizacao_nome`, `velocidade_mbps`) são o que a revisão
    vai GRAVAR: o ensaio roda com eles para comparar exatamente o que a adoção
    produziria.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_adocao.py tests/automation/test_discovery.py tests/api -q`
Expected: PASS. Se `tests/api` não tiver esse nome, rode `uv run pytest -q` e confira a suíte inteira.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/discovery.py src/gerenet/domain/schemas.py \
        src/gerenet/domain/services/discovery.py src/gerenet/api/routers/discovery.py \
        tests/domain/test_adocao.py tests/api/test_discovery_adopt_api.py
git commit -m "feat(adoção): o ensaio roda com a identidade que a revisão vai gravar, e a velocidade é gravada

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: O campo da velocidade no cadastro e na edição de circuito

**Files:**
- Modify: `web/src/help.ts`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/hooks.ts`
- Modify: `web/src/pages/Circuits.tsx`
- Test: `web/src/pages/Circuits.test.tsx`

**Interfaces:**
- Consumes: `velocidade_mbps` na API (Task 2).
- Produces: `help("circuit.velocidade_mbps")`; `CircuitOut.velocidade_mbps: number | null`; `CircuitCreateIn.velocidade_mbps?: number | null`. A Task 9 consome a chave nova de ajuda e o tipo.

- [ ] **Step 1: Write the failing test**

Acrescentar ao fim de `web/src/pages/Circuits.test.tsx`:

```tsx
it("manda a velocidade no cadastro e a mostra na edição", async () => {
  mockFetch();
  render(<Circuits />);
  await userEvent.click(await screen.findByRole("button", { name: /novo circuito/i }));
  await userEvent.type(screen.getByLabelText("Velocidade (Mbps)"), "1024");
  // O corpo do POST é o que a SoT grava: a velocidade vai como número, e não
  // como o texto do campo (§8).
  expect(corpoDoPost()).toMatchObject({ velocidade_mbps: 1024 });
});

it("campo de velocidade vazio vai como null e não como zero", async () => {
  // Nula é "não sei a velocidade"; zero seria uma taxa (§3).
  mockFetch();
  render(<Circuits />);
  await userEvent.click(await screen.findByRole("button", { name: /novo circuito/i }));
  expect(corpoDoPost()).toMatchObject({ velocidade_mbps: null });
});
```

> **Nota para quem executa:** `mockFetch`, `userEvent` e a montagem do
> formulário são os helpers que `Circuits.test.tsx` já tem — siga os nomes do
> arquivo. Se não existir um `corpoDoPost()`, capture o corpo como os testes
> vizinhos deste arquivo capturam. As fixtures de circuito do arquivo
> (`const circ = {...}`) ganham `velocidade_mbps: 1024` para o TypeScript não
> reclamar do tipo.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- Circuits`
Expected: FAIL — não existe campo "Velocidade (Mbps)".

- [ ] **Step 3: Write minimal implementation**

**3a.** Em `web/src/help.ts`, depois da linha `"circuit.bandwidth"`:

```ts
  "circuit.velocidade_mbps": "Velocidade contratada em Mbps (ex.: 1024 = 1 Gbps). Entra na descrição da subinterface e no limitador de taxa (qos car). Uma taxa fora de 1–100000 Mbps é recusada.",
```

**3b.** Em `web/src/api/types.ts`, em `CircuitOut`, depois de `bandwidth`:

```ts
  velocidade_mbps: number | null;
```

**3c.** Em `web/src/api/hooks.ts`, em `CircuitCreateIn`, depois de `bandwidth`:

```ts
  velocidade_mbps?: number | null;
```

**3d.** Em `web/src/pages/Circuits.tsx`:

- nos dois formulários (`FORM_VAZIO` e `FORM_EDIT_VAZIO`), depois de `bandwidth: "",`:

```tsx
  velocidade_mbps: "",
```

- em `abrirEdicao`, depois de `bandwidth: c.bandwidth ?? "",`:

```tsx
      velocidade_mbps: c.velocidade_mbps === null ? "" : String(c.velocidade_mbps),
```

- em `salvarEdicao` e em `onSubmit`, depois de `bandwidth: ...`:

```tsx
        velocidade_mbps: num(formEdit.velocidade_mbps),
```

(no `onSubmit`, `num(form.velocidade_mbps)`.)

- e o campo, depois do `FormField` da Banda nos dois formulários (o `num` já
  existe no arquivo e é ele que faz o vazio virar `null`):

```tsx
          <FormField label="Velocidade (Mbps)" help={help("circuit.velocidade_mbps")}>
            <input
              type="number"
              min={1}
              max={100000}
              value={form.velocidade_mbps}
              onChange={(e) => setForm({ ...form, velocidade_mbps: e.target.value })}
            />
          </FormField>
```

(no formulário de edição, `formEdit`/`setFormEdit`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run build && npm run test`
Expected: PASS. O `npm run build` é obrigatório aqui: o `tsc -b` é quem valida a chave nova do `help.ts` e o campo novo dos tipos.

- [ ] **Step 5: Commit**

```bash
git add web/src/help.ts web/src/api/types.ts web/src/api/hooks.ts \
        web/src/pages/Circuits.tsx web/src/pages/Circuits.test.tsx
git commit -m "feat(web): a velocidade contratada no cadastro e na edição de circuito

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: A velocidade e a identidade da conferência na revisão da adoção

**Files:**
- Modify: `web/src/api/types.ts` (`DiscoveryPropostaOut`, `DiscoveryAdocaoIn`)
- Modify: `web/src/api/hooks.ts` (`useFidelidade`)
- Modify: `web/src/help.ts`
- Modify: `web/src/pages/DiscoveryAdopt.tsx`
- Test: `web/src/pages/Discovery.test.tsx`

**Interfaces:**
- Consumes: os query params novos de `GET /fidelidade` (Task 7); `PropostaOut.velocidade_mbps` (Task 6); `help("circuit.velocidade_mbps")` (Task 8).
- Produces: `IdentidadeDaConferencia` exportado por `hooks.ts`; `useFidelidade(deviceId, vrf, subinterface, perfis, identidade)`.

- [ ] **Step 1: Write the failing test**

No `web/src/pages/Discovery.test.tsx`, atualizar a asserção do corpo do POST
(o `expect(corpoDoPost()).toEqual({...})` do fluxo de adoção) acrescentando:

```tsx
        velocidade_mbps: 1024,
```

e, no `preencheAcesso` (ou no preenchimento da revisão), o passo que digita a
velocidade — é o que faz o `1024` do corpo acima ser o que o operador digitou:

```tsx
  await userEvent.type(screen.getByLabelText("Velocidade (Mbps)"), "1024");
```

E acrescentar os dois testes:

```tsx
it("a conferência leva a velocidade digitada para o servidor", async () => {
  // A taxa entra no ensaio: sem ela, o render não emite o `qos car` e a
  // conferência acusaria uma diferença de QoS que a adoção não cria (§7).
  const urls: string[] = [];
  mockFetch({ aoBuscar: (url) => urls.push(url) });
  render(<Discovery />);
  ... // abre a revisão como os testes vizinhos abrem
  await userEvent.type(screen.getByLabelText("Velocidade (Mbps)"), "1024");
  await waitFor(() => expect(
    urls.some((u) => u.includes("velocidade_mbps=1024")),
  ).toBe(true));
});

it("mudar o código refaz a conferência", async () => {
  // O código entra na descrição da subinterface (§4): mudá-lo muda o que o
  // ensaio produz, e o aceite marcado contra o diff antigo não vale para o novo.
  ...
});
```

> **Nota para quem executa:** `mockFetch` ganha um parâmetro opcional
> `aoBuscar` que recebe cada URL consultada — os testes vizinhos já contam as
> chamadas a `/api/v1/discovery/fidelidade`; a URL é o que falta para separar
> "refez" de "refez com o valor novo". Se o arquivo já guarda as URLs, use o que
> ele tem. Os testes acima seguem o mesmo preâmbulo (abertura da revisão) dos
> vizinhos: copie-o em vez de reescrever.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- Discovery`
Expected: FAIL — não existe campo "Velocidade (Mbps)" e o corpo do POST não tem `velocidade_mbps`.

- [ ] **Step 3: Write minimal implementation**

**3a.** Em `web/src/api/types.ts`, em `DiscoveryPropostaOut`, depois de `qinq`:

```ts
  /** A velocidade sugerida, lida do `qos car cir` do equipamento (§7). */
  velocidade_mbps: number | null;
```

E em `DiscoveryAdocaoIn`, depois de `edge_trunk`:

```ts
  velocidade_mbps: number | null;
```

**3b.** Em `web/src/help.ts`, acrescentar junto das chaves `adocao.*`:

```ts
  "adocao.velocidade": "Velocidade contratada em Mbps, sugerida do QoS que o equipamento já tem. Vazio deixa o circuito sem taxa: sem ela não há descrição de velocidade nem qos car.",
```

**3c.** Em `web/src/api/hooks.ts`, trocar `useFidelidade` inteira por:

```ts
/** A identidade que a conferência usa: o que a adoção VAI gravar e que o ensaio
 * precisa ter para a comparação valer (§6 do design da velocidade).
 *
 * Tudo texto (menos o id da organização) de propósito: a assinatura que
 * invalida o aceite compara o que o operador DIGITOU. Com o número já
 * normalizado, `0100` e `100` seriam a mesma coisa, e o aceite viajaria contra
 * um diff que a tela nunca mostrou. */
export type IdentidadeDaConferencia = {
  edgeTrunk: string;
  circuitCode: string;
  organizacaoId: number;
  organizacaoNome: string;
  velocidade: string;
};

/** Os perfis entram na chave de propósito: trocar um `select` de perfil refaz a
 * conferência, porque o corpo da política de exportação muda com ele. */
export const useFidelidade = (
  deviceId: number,
  vrf: string | null,
  subinterface: string | null,
  perfis: Record<string, { import?: number; export?: number }> = {},
  identidade: IdentidadeDaConferencia | null = null,
) =>
  useQuery({
    queryKey: ["fidelidade", deviceId, vrf, subinterface, perfis, identidade],
    queryFn: () => {
      const qs = new URLSearchParams({ device_id: String(deviceId) });
      if (vrf) qs.set("vrf", vrf);
      if (subinterface) qs.set("subinterface", subinterface);
      if (identidade) {
        if (identidade.edgeTrunk) qs.set("edge_trunk", identidade.edgeTrunk);
        if (identidade.circuitCode) qs.set("circuit_code", identidade.circuitCode);
        if (identidade.organizacaoId > 0) {
          qs.set("organizacao_id", String(identidade.organizacaoId));
        }
        if (identidade.organizacaoNome) qs.set("organizacao_nome", identidade.organizacaoNome);
        if (identidade.velocidade) qs.set("velocidade_mbps", identidade.velocidade);
      }
      for (const [afi, p] of Object.entries(perfis)) {
        if (p.import) qs.set(`import_${afi}`, String(p.import));
        if (p.export) qs.set(`export_${afi}`, String(p.export));
      }
      return apiFetch<DiscoveryFidelidadeOut>(`/api/v1/discovery/fidelidade?${qs.toString()}`);
    },
    enabled: deviceId > 0 && subinterface !== null,
    retry: false,
  });
```

**3d.** Em `web/src/pages/DiscoveryAdopt.tsx`:

- trocar o import `useFidelidade` por `useFidelidade` + `type IdentidadeDaConferencia`.
- trocar a constante de espera e o comentário:

```tsx
/** O trunk, o código e a velocidade são digitados: a espera é o que segura a
 * enxurrada de consultas — cada conferência roda um render do equipamento
 * inteiro no servidor. */
const ESPERA_DA_IDENTIDADE_MS = 300;
```

- trocar o estado `trunkDaConferencia` por:

```tsx
  const [velocidade, setVelocidade] = useState(
    proposta.velocidade_mbps === null ? "" : String(proposta.velocidade_mbps),
  );
  // O que o operador digitou, como assinatura: é ela que a espera observa e é
  // dela que sai o objeto da conferência. Comparar o objeto direto refaria a
  // consulta a cada render, porque cada render cria um objeto novo.
  const assinaturaDaIdentidade = JSON.stringify({
    edgeTrunk: trunk,
    circuitCode: code,
    organizacaoId: criarOrg ? 0 : orgId,
    organizacaoNome: criarOrg ? orgNome.trim() : "",
    velocidade,
  });
  const [identidadeDaConferencia, setIdentidadeDaConferencia] = useState<IdentidadeDaConferencia>(
    () => JSON.parse(assinaturaDaIdentidade) as IdentidadeDaConferencia,
  );
```

> A `criarOrg` é declarada mais abaixo no componente; mova a linha
> `const criarOrg = orgId === 0;` para **antes** deste bloco — ela não depende de
> nada além de `orgId`, que já está declarado.

- trocar o efeito do debounce por:

```tsx
  // A identidade digitada só entra na consulta depois da última tecla.
  useEffect(() => {
    const timer = setTimeout(
      () => setIdentidadeDaConferencia(JSON.parse(assinaturaDaIdentidade) as IdentidadeDaConferencia),
      ESPERA_DA_IDENTIDADE_MS,
    );
    return () => clearTimeout(timer);
  }, [assinaturaDaIdentidade]);
```

- trocar a chamada do hook por:

```tsx
  const { data: fidelidade, error: erroDaConferencia } = useFidelidade(
    proposta.device_id, proposta.vrf, proposta.subinterface, perfis, identidadeDaConferencia,
  );
```

- trocar `const trunkConferido = trunk === trunkDaConferencia;` por:

```tsx
  const identidadeConferida = assinaturaDaIdentidade === JSON.stringify(identidadeDaConferencia);
```

e o comentário acima dele passa a explicar a identidade inteira: o diff na tela
é o da identidade anterior enquanto a nova não volta, e o `ciente` é um booleano
sem vínculo com o diff que assumiu — por isso o gate é a igualdade dos dois.

- trocar `trunkConferido &&` por `identidadeConferida &&` em `podeAdotar`.

- acrescentar a validação, junto das outras:

```tsx
  const velocidadeNumero = velocidade === "" ? null : Number(velocidade);
  const velocidadeInvalida =
    velocidade !== "" &&
    (!Number.isInteger(velocidadeNumero) ||
      (velocidadeNumero as number) <= 0 ||
      (velocidadeNumero as number) > LIMITE_DA_VELOCIDADE);
```

com a constante, junto das outras:

```tsx
/** O teto do schema (`CircuitCreate.velocidade_mbps`), espelhado. */
const LIMITE_DA_VELOCIDADE = 100000;
```

- acrescentar `velocidadeInvalida ||` ao `revisaoIncompleta`.
- no corpo do `adotar.mutate`, depois de `edge_trunk: trunk || null,`:

```tsx
        velocidade_mbps: velocidadeNumero,
```

- e o campo, junto do de trunk:

```tsx
      <FormField label="Velocidade (Mbps)" help={help("adocao.velocidade")}>
        <input
          type="number"
          min={1}
          max={LIMITE_DA_VELOCIDADE}
          value={velocidade}
          onChange={(e) => setVelocidade(e.target.value)}
        />
      </FormField>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run build && npm run test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/types.ts web/src/api/hooks.ts web/src/help.ts \
        web/src/pages/DiscoveryAdopt.tsx web/src/pages/Discovery.test.tsx
git commit -m "feat(web): a velocidade e a identidade da revisão na adoção

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: A wiki e o runbook

**Files:**
- Modify: `docs/wiki/circuitos.md`
- Modify: `docs/wiki/descoberta.md` (a frase que ficou falsa na Task 6 — Ruling do pré-voo, 9)
- Modify: `docs/runbook-validacao-ne8000.md`

> **Ruling do pré-voo, 9 — esta tarefa não estava consertando duas frases que a
> frente tornou mentirosas.** As duas dizem que o `description` da subinterface
> está no grupo "o que a SoT não gerencia", e isso deixou de ser verdade na
> Task 6: a `description` passou a ser gerenciada e a **exigir ciente**. São
> `docs/wiki/descoberta.md:150-152` e `docs/runbook-validacao-ne8000.md:271`
> (o parêntese "o `description` e o MTU da subinterface"). A página
> `docs/wiki/descoberta.md` **não estava no `Files:` de tarefa nenhuma** — só
> esta a alcança, e sem ela a frase sobrevive à frente inteira. O conserto nas
> duas é o mesmo: o grupo que não gateia hoje é só o `mtu`.
> **Custo se errado:** quem for validar no equipamento lê a wiki e o runbook,
> espera que a descrição divergente não peça `ciente`, e marca o `ciente` como
> ruído em vez de tratá-lo como o aviso de que a SoT vai reescrever a linha.

**Interfaces:**
- Consumes: tudo o que as tarefas anteriores entregaram.
- Produces: nada de código.

- [ ] **Step 1: A wiki**

Em `docs/wiki/circuitos.md`, na tabela "O cadastro de circuito", trocar a linha da Banda e acrescentar a nova logo depois:

```markdown
| Banda | Texto (ex.: 1G, 10G, 500M) — a nota que o humano lê. |
| Velocidade (Mbps) | A taxa contratada, em Mbps, que a máquina usa (ex.: `1024` = 1 Gbps). Vazio = "não sei a velocidade", e é o estado de todo circuito anterior a este campo. |
```

E acrescentar, depois da seção "Endereçamento p2p derivado (IPAM)":

```markdown
## A descrição e o QoS da subinterface

A `description` da subinterface deriva do circuito:

```
description <CÓDIGO> <NOME DA ORGANIZAÇÃO> [<VELOCIDADE>]
```

| Velocidade | Linha |
|---|---|
| 1024 | `description CIRC-626 NETMAC [1G]` |
| 100 | `description CIRC-500 ACME TELECOMUNICACOES [100M]` |
| vazia | `description CIRC-500 ACME TELECOMUNICACOES` |

O nome da organização vai em maiúsculas e sem acento, e cede no orçamento de 80
caracteres se não couber — cortado seco. Velocidade múltipla de 1024 sai em
`G`; qualquer outra sai em `M`.

Com a velocidade preenchida, o render emite também o limitador de taxa nas duas
direções, depois do `statistic enable`:

```
qos car cir <velocidade_mbps × 1000> inbound
qos car cir <velocidade_mbps × 1000> outbound
```

O `cir` é em kbps: `1024` Mbps produzem `cir 1024000`. O `cbs`, o `green pass`
e o `red discard` **não** são emitidos — o VRP os completa ao aplicar.

**Circuito que já está provisionado converge numa mudança nova.** Até esta
frente, o plano pulava a subinterface inteira pelo nome; agora ele confere
também a descrição e o QoS, e o que faltar entra no plano como "atualizar". O
bloco vai inteiro ao equipamento (reemitir endereço com o mesmo valor é
inócuo no VRP), e o que a mudança registra é o estado desejado daquele pedaço.

A descrição é **derivada**: renomear a organização reescreve a descrição de
todas as subinterfaces dela no próximo provisionamento.
```

- [ ] **Step 1b: A página da descoberta**

Em `docs/wiki/descoberta.md`, na seção "O diff, em dois grupos — e só um
bloqueia", o segundo grupo ainda lista a `description`:

```markdown
- **O que a SoT não gerencia**: linha que o equipamento tem e o render não emite
  de propósito — hoje o `description` e o `mtu` da subinterface. Numa borda real
  elas estão em toda proposta, e "diferença exige `ciente`" degeneraria em
  "marque sempre". Ficam visíveis, para leitura, e não gateiam nada.
```

A `description` saiu deste grupo na frente da velocidade (§4 do design): a SoT
passou a emiti-la e a **gerenciá-la**, então uma descrição diferente no
equipamento é diferença de verdade e exige o `ciente`. O grupo passa a ter só o
`mtu`:

```markdown
- **O que a SoT não gerencia**: linha que o equipamento tem e o render não emite
  de propósito — hoje só o `mtu` da subinterface. Numa borda real ele está em
  toda proposta, e "diferença exige `ciente`" degeneraria em "marque sempre".
  Fica visível, para leitura, e não gateia nada.

  A `description` **esteve** aqui até a frente da velocidade: hoje a SoT a
  deriva do circuito e a emite, então uma descrição divergente é mudança de
  verdade — e uma proposta cuja descrição fuja do formato
  `<CÓDIGO> <ORG> [<VELOCIDADE>]` pede o `ciente`.
```

- [ ] **Step 2: O runbook**

Em `docs/runbook-validacao-ne8000.md`, primeiro o parêntese que ficou falso na
mesma seção da Etapa 3 — o item do grupo que não gateia lista a `description`,
que hoje gateia:

```markdown
- o grupo **O que a SoT não gerencia** (só o `mtu` da subinterface) é o
  esperado, e não gateia nada;
```

E, no mesmo lugar, acrescentar os itens novos ao checklist:

```markdown
- [ ] **A `description` da subinterface agora é gerenciada.** Adotar um enlace
      cuja descrição fuja do formato `<CÓDIGO> <ORG> [<VELOCIDADE>]` passa a
      pedir o `ciente` — é a SoT avisando que vai reescrever a linha. A revisão
      já traz o código e a organização; com eles a descrição casa e o `ciente`
      não é pedido.
- [ ] **Conferir o limite real do `description` nesta versão do VRP**
      (`V800R024C00SPC500`). O orçamento do §4 é de 80 caracteres por adoção
      desta frente; se o equipamento recusar ou truncar antes disso, o número
      desce em `naming.LIMITE_DESCRICAO` e o corte acompanha sozinho.
- [ ] **Reaplicar o bloco inteiro numa subinterface que já está de pé.** É o que
      o `atualizar` faz, e o endereço vai junto com os mesmos valores. Confirmar
      em equipamento não crítico que o VRP aceita a reemissão sem derrubar a
      subinterface, **antes** de soltar no parque.
```

- [ ] **Step 3: Rodar a suíte inteira**

Run: `uv run pytest -q && uv run ruff check src tests && cd web && npm run build && npm run test`
Expected: `pytest` verde (as seis falhas de `tests/worker/` são o flake do Redis DB 0, alheio a esta frente — confira com `GERENET_REDIS_URL` apontando para outro DB se aparecerem) e o build do `web` sem erro.

- [ ] **Step 4: Commit**

```bash
git add docs/wiki/circuitos.md docs/wiki/descoberta.md docs/runbook-validacao-ne8000.md
git commit -m "docs: a velocidade, o formato da descrição e o QoS na wiki e no runbook

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: O fumo de ponta a ponta

**Files:**
- Modify: `web/e2e/discovery.spec.ts` (só se necessário)

**Interfaces:**
- Consumes: tudo.
- Produces: nada de código.

- [ ] **Step 1: Parar a stack de dev antes do fumo**

O `npm run test:e2e` sobe o próprio `uvicorn` em `:8000` com `reuseExistingServer: false`, e porta ocupada é falha dura no boot. O `docker compose stop` de dentro de uma worktree é no-op — pare pelos nomes dos contêineres:

```bash
docker ps --format '{{.Names}}' | grep gerenet
docker stop <nomes>
```

- [ ] **Step 2: Rodar o fumo**

```bash
cd web && npm run test:e2e -- discovery
```

Expected: verde. O fumo já marca o `ciente` quando ele aparece
(`if ((await ciente.count()) > 0) await ciente.check();`), então a descrição
passar a gatear não o quebra. Se ele falhar no diálogo da adoção, o campo novo
ou a identidade da conferência mudaram o comportamento da revisão — conserte a
tela, não o teste.

- [ ] **Step 3: Restaurar a stack**

```bash
docker start <nomes>
```

- [ ] **Step 4: Registrar o que o fumo mostrou**

Se o fumo passou sem alteração, não há commit. Se ele exigiu ajuste em
`web/e2e/discovery.spec.ts` ou em `web/e2e/setup.ts`, commite junto com o
motivo:

```bash
git add web/e2e/
git commit -m "test(e2e): o fumo da descoberta acompanha a descrição gerenciada

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-review

**Cobertura da spec.** §3 → Task 2. §4 → Task 1 (a função) e Task 3 (o template). §5 → Task 3 e Task 6 (`equivalencia_vrp` dobra o `qos car`). §6 → Task 4 (plano) e Task 5 (execução, re-diff e pós-check). §7 → Task 6 (descrição gerenciada, parser e sugestão) e Task 7 (velocidade na adoção, identidade do ensaio). §8 → Task 2 (API e CLI), Task 8 e Task 9 (web), Task 10 (wiki). §9 → os testes de cada tarefa, mais a Task 10 Step 3 (suíte inteira) e a Task 11 (fumo). §10 (riscos) → Task 10 Step 2 (runbook). §11 (dívidas) → nenhuma tarefa, como deve ser.

**Desvios registrados.**
1. **CLI sem `update`** (Task 2): a spec §8 pede `--velocidade-mbps` "e o mesmo no `update`", e o grupo `circuits` do CLI não tem comando `update`. O campo entra no `add`; o `update` fica como dívida. A API PATCH e a web já cobrem a edição.
2. **Migração sem teste automatizado** (Task 2 Step 5): a spec §9 pede "upgrade e downgrade", e o repositório não tem harness de migração — o `conftest.py` só faz `TRUNCATE`, e o schema do banco de teste vem do Alembic (Ruling do pré-voo, 3, na Task 2). A verificação é manual, num banco descartável, **mais** o `alembic upgrade head` no `gerenet_test`, sem o qual a suíte roda contra um schema velho. O harness entra como dívida.

**Consistência de tipos.** `descricao_subinterface(code, nome_organizacao, velocidade_mbps) -> str | None` (T1) é chamada em `_bloco_sub` (T3) com `circuito.code`, `circuito.organization.name`, `circuito.velocidade_mbps` — os mesmos três que `_ensaio` (T7) alimenta com a identidade da revisão. `naming.LIMITE_DESCRICAO` (T1) é o mesmo número do orçamento citado no runbook (T10). `subinterface.conteudo_conforme(comandos, linhas)` e `subinterface.linhas_da_interface(texto, nome)` (T4) são chamadas com a mesma assinatura em `changes._ja_existe` (T4) e em `runner._estado_do_bloco` (T5). `cir_kbps` é o nome da chave do template (T3) e sai de `velocidade_mbps * 1000` (T2). `Proposta.velocidade_mbps` (T6) é o que `PropostaOut.velocidade_mbps` expõe, e `_velocidade_do_qos` é a única conta `cir → Mbps` no backend. Os quatro parâmetros da identidade (T7: `circuit_code`, `organizacao_id`, `organizacao_nome`, `velocidade_mbps`) são exatamente os quatro query params que `useFidelidade` envia (T9).

**Varredura de placeholders.** Nenhum "TBD"/"TODO"/"implementar depois", nenhum passo que diz o que fazer sem mostrar como. Todo helper citado por um teste existe: `_ambiente`/`_circuito` (`test_circuits_service.py`), `_ambiente`/`_com_config`/`_com_texto`/`_propostas` (`test_discovery.py`), `_ambiente`/`_proposta`/`_revisao` (`test_adocao.py`), `_snapshot_encontrado` (`test_changes.py`), `_estado_do_bloco`/`_re_diff`/`_verifica_aplicados`/`_estado_subif_presenca` (`test_runner_change.py`), `parse_config_vrp` (`test_config_vrp.py`), `_snapshot_encontrado` e o `render.render_desejado`. Os dois helpers novos que o plano cria (`_recursos_com_subif` na Task 5, os dois testes da Task 7) vêm com o corpo escrito.

**Testes que esta frente quebra, e onde cada um é consertado.** Nenhum deles aparece na spec como "vai quebrar" — foram levantados lendo os arquivos, e é por isso que estão aqui.

| Teste | Por que quebra | Onde é consertado |
|---|---|---|
| `test_changes.py::_snapshot_encontrado` (helper) | escreve `BlocoRender.texto`, que é plano; `linhas_da_interface` não acha bloco nenhum e o plano para de pular | Task 4 Step 4 |
| `test_templates.py::test_subinterface_v4_descricao_sem_ipv6` | o `descricao="Cliente A"` deixa de ser o que o §4 produz | Task 3 Step 1 |
| `test_discovery.py` (os três da descrição/ciente/mtu) | a descrição sai do grupo que não gateia | Task 6 Step 1 |
| `test_adocao.py::_CONFIG_FIEL` (constante) | o render passa a emitir `description`, e o texto dizia reproduzi-lo "linha a linha" | Task 7 Step 1b |
| `test_adocao.py::_revisao` (helper) | precisa carregar a velocidade | Task 7 Step 1a |
| `test_adocao.py::test_ensaio_fiel_aceita_sem_ciente` | a conferência direta ia sem identidade e passa a acusar descrição | Task 7 Step 1c |
| `test_adocao.py::test_a_auditoria_leva_todas_as_diferencas` | prende a descrição no `nao_gerenciado` | Task 7 Step 1d |
| `test_runner_change.py::_SUB_BLOCO` (os três F1) | **não** quebram: o bloco não tem `description` nem `qos car`, e `conteudo_conforme` devolve `True` | — |
| `test_runner_change.py::test_run_change_bloco_ja_presente_marca_step_pulado` | o `_fakes_de_mudanca` devolvia `arquivos = {}`: sem texto de backup a `description` nova não se confirma e o bloco vira `atualizar` em vez de `consta` | Task 5 (helper `_backup_do_render` e o parâmetro `backups`) |
| `test_runner_change.py::test_run_change_create_misto_consta_ausente_aborta` | idem — o mesmo fixture, e o abort de plano velho depende de o bloco constar | Task 5 |
| `test_discovery.py::test_fidelidade_ignora_comentario_dentro_da_interface` | o ensaio passa a emitir `description`, que o texto da fixture não tem | Task 6 |
| `test_discovery.py::test_fidelidade_nao_acusa_as_duas_formas_da_mesma_linha` | idem: a linha nova sobra de um lado só | Task 6 |
| `test_adocao.py::test_a_conferencia_usa_o_trunk_da_revisao` | idem, e aqui **não basta** o conserto da fonte: o teste chama `conferir_fidelidade` sem identidade, então o ensaio continua com o `ENSAIO-…` falso. O teste passa a mandar a identidade da revisão | Task 7 |
| `tests/api/test_discovery_adopt_api.py::test_fidelidade_sob_demanda` | idem, pelo endpoint | Task 7 (arquivo que **entra** nos Files da Task 7) |

> **Ruling do pré-voo, 4.** Quatro dos dez testes que a Task 3 quebra não estavam nesta tabela — as quatro linhas acima. Elas foram levantadas pela execução da Task 3, não pela leitura do plano, e a diferença é a de sempre: ler o código acha a maioria, rodar acha o resto. Três são variações do mesmo mecanismo já previsto (a descrição que o ensaio passa a emitir), mas uma delas não se conserta só no código: `test_a_conferencia_usa_o_trunk_da_revisao` chama `conferir_fidelidade` **sem** identidade, e mesmo depois da Task 7 esse caminho continua caindo no `ENSAIO-…` de placeholder — o teste precisa passar a identidade, senão segue vermelho depois do conserto da fonte. A quarta mora em `tests/api/test_discovery_adopt_api.py`, um arquivo que nenhum `Files` de tarefa listava: a Task 7 passa a listá-lo, porque é ela que mexe nos quatro query params que o endpoint expõe. — **Custo se errado:** se as quatro não forem consertadas nas tarefas indicadas, a suíte fecha a frente vermelha em dez testes, e a causa (uma descrição que o ensaio inventa) não é óbvia para quem só vê o nome do teste.

> **Ruling do pré-voo, 6 — a tabela estava incompleta de novo, e desta vez mais
> fundo.** Duas linhas foram acrescentadas acima, e elas têm uma diferença que
> as quatro do Ruling 4 não têm: **quebram na Task 5, não nas tarefas 1–3**. O
> motivo é que as tarefas 1–3 mudaram o *render* e a Task 4 mudou o *plano*;
> só a Task 5 mexeu na *execução*, que é o que o `run_change` destes dois
> testes exercita de ponta a ponta. A tabela foi escrita prevendo a quebra pelo
> lado do render e não previu a quebra pelo lado do executor — o mesmo
> conteúdo, mas chegando por outro caminho e com um commit de atraso. E elas
> ficam na Task 5 porque é a **única** tarefa do plano com
> `test_runner_change.py` no `Files:` (`grep` no plano: linha 848, e mais
> nenhuma); uma linha apontando para outra tarefa mandaria o implementer
> procurar um conserto que ninguém faria. — **Custo se errado:** os dois testes
> ficariam vermelhos sem dono, e como eles exercitam o pular-e-o-abort do plano,
> a frente fecharia com o caminho de execução quebrado e a suíte apontando para
> o lado errado (o render) em vez do certo (o fixture sem backup).

**Ordem de execução.** As tarefas 1 e 2 são independentes entre si e podem sair em qualquer ordem. A 3 depende das duas. A 4 depende da 3 (é o conteúdo dela que a `conteudo_conforme` confere). A 5 depende da 4. A 6 depende da 3. A 7 depende da 2 e da 6. As tarefas 8 e 9 dependem da 2 e da 7, e a 10 e a 11 fecham.

**Uma emenda à Task 6, por causa da ordem.** Dois testes dela (`test_a_conferencia_casa_quando_a_revisao_traz_a_identidade` e `test_mtu_da_subinterface_tambem_sai_do_que_gateia`) chamam `conferir_fidelidade` com a identidade da revisão, que só existe depois do Step 3 da Task 7. Rodando 6 antes de 7, os dois falham com `TypeError: conferir_fidelidade() got an unexpected keyword argument`. **Eles entram no commit da Task 7**, não no da 6 — a Task 6 entrega o resto da sua suíte verde, e o Step 1 da Task 6 já diz isso. Nenhuma linha de produção fica fora de lugar: são dois testes, e a assinatura que eles exercitam chega no commit seguinte.

**Riscos que sobraram, e o que os fecha.** Três coisas o plano não consegue verificar sozinho, e as três estão no runbook da Task 10: o limite real do `description` nesta versão do VRP (o orçamento de 80 é adoção desta frente, e `LIMITE_DESCRICAO` desce se ele for menor), que reaplicar o bloco inteiro numa subinterface de pé não derruba o serviço, e que reemitir `ip address` com o mesmo valor é inócuo — o §10 da spec lista os três como risco, e todos pedem equipamento, não teste.
