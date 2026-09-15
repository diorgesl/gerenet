# Descoberta e adoção de peers BGP — parte 2 (a escrita) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar a frente: a parte 1 leu a configuração do equipamento e passou a propor o cadastro sem escrever nada; esta parte grava a cadeia que a proposta descreve, numa transação só, com o operador assumindo as diferenças de fidelidade que sobraram.

**Architecture:** Uma reserva nova no IPAM grava os valores que já estão no equipamento em vez de escolhê-los. Os três serviços de cadastro ganham `commit=False` para que a adoção inteira caiba numa transação. A conferência de fidelidade passa a comparar também o corpo das definições e a separar o que a Source of Truth não gerencia, e só o primeiro grupo exige aceite. A tela de revisão é onde as pendências da parte 1 viram campos.

**Tech Stack:** Python 3.13, SQLAlchemy 2, FastAPI, Typer, pytest; React + Vite + TypeScript com Vitest e Playwright.

**Spec:** `docs/superpowers/specs/2026-09-14-gerenet-descoberta-adocao-parte2-design.md`
**Design da parte 1 (base e autoridade para o que não for redefinido):** `docs/superpowers/specs/2026-09-14-gerenet-descoberta-adocao-design.md`

## Global Constraints

- Idioma dos artefatos: **português (PT-BR)**. Comentários, docstrings, mensagens de erro, nomes de função de serviço e rótulos de UI em PT-BR; nomes de tabela, de rota HTTP e de tipo seguem o inglês do resto do repo.
- Toda escrita em objeto de rede passa pelos serviços de domínio, que auditam. A adoção é a exceção controlada: ela **orquestra** esses serviços numa transação, e é por isso que eles ganham `commit=False`.
- Segredos nunca são lidos, gravados, logados ou exibidos. O valor de `password cipher` não entra em nenhuma estrutura em momento nenhum; a adoção grava só o caminho no Vault.
- Nada é enviado ao equipamento. A adoção escreve na SoT; mudar o roteador continua exigindo change request.
- Comandos de teste: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build && npm run test`.
- A suíte completa leva cerca de 75 segundos. Durante o trabalho rode os módulos tocados; a suíte completa é para o checkpoint final.
- Toda tabela nova entra na lista do `TRUNCATE` de `tests/conftest.py`. **Esta parte não cria tabela nem migration**: ela grava nas tabelas que já existem, e o único evento novo é de auditoria.
- Baseline conhecido: `tests/worker/test_tasks.py::test_nao_duplica_job_pendente` cai de vez em quando por estado compartilhado do Redis, e passa isolado. Não é regressão.
- Testes de e2e exigem o banco dedicado `gerenet_e2e`, nunca o `gerenet`.

## File Structure

**Criados:**

| Arquivo | Responsabilidade |
|---|---|
| `tests/domain/test_ipam_adocao.py` | A reserva por valores reais |
| `tests/domain/test_services_commit.py` | O `commit=False` dos três serviços de cadastro |
| `tests/domain/test_adocao.py` | A adoção transacional ponta a ponta |
| `tests/api/test_discovery_adopt_api.py` | O `POST /adopt` e o endpoint da conferência |
| `web/src/pages/DiscoveryAdopt.tsx` | O formulário de revisão (componente da página) |
| `web/e2e/discovery.spec.ts` | O fumo de adoção |

**Modificados:**

| Arquivo | Mudança |
|---|---|
| `src/gerenet/domain/services/organizations.py` | `create_organization(..., commit: bool = True)` |
| `src/gerenet/domain/services/circuits.py` | `create_circuit(..., commit: bool = True)` |
| `src/gerenet/domain/services/bgp_sessions.py` | `create_session(..., commit: bool = True)` |
| `src/gerenet/domain/services/ipam.py` | `reservar_adocao` |
| `src/gerenet/domain/services/discovery.py` | `adotar_proposta` |
| `src/gerenet/automation/discovery.py` | `Diferenca` com `nao_gerenciado` e `explicacao`; `internos` e a idade no resultado; a conferência do corpo das definições; as dívidas da seção 8 |
| `src/gerenet/domain/schemas.py` | `AdocaoIn`, `DiferencaOut`, `FidelidadeOut`, e `internos`/`snapshot_age_seconds` no `DiscoveryOut` |
| `src/gerenet/api/routers/discovery.py` | `POST /adopt` e `GET /fidelidade` |
| `src/gerenet/cli/discovery.py` | `adopt` |
| `web/src/pages/Discovery.tsx` | O botão Adotar e o formulário de revisão |
| `web/src/api/hooks.ts`, `web/src/api/types.ts` | Os hooks e tipos da adoção |
| `web/src/help.ts` | Os textos dos campos novos |
| `docs/wiki/descoberta.md`, `docs/runbook-validacao-ne8000.md`, `CLAUDE.md`, `README.md` | Documentação |

**Fora deste plano, com o motivo:** sugestão por LLM (frente própria); peer em sub-rede compartilhada (frente própria); unificação de dual stack com VLAN separada; canonicalização na escrita de `bgp_sessions`.

---

### Task 1: `commit=False` nos três serviços de cadastro

A adoção precisa gravar organização, circuito, reservas e sessões numa transação só. Os três serviços de cadastro commitam no meio do caminho, então encadear chamadas deixa as anteriores gravadas se uma posterior recusar. Esta tarefa abre a porta sem mudar nada para quem chama hoje.

**Files:**
- Modify: `src/gerenet/domain/services/organizations.py:28-46`
- Modify: `src/gerenet/domain/services/circuits.py:27-43`
- Modify: `src/gerenet/domain/services/bgp_sessions.py:96-162`
- Create: `tests/domain/test_services_commit.py`

**Interfaces:**
- Consumes: nada
- Produces: `create_organization(session, data, *, actor: str, commit: bool = True) -> models.Organization`; `create_circuit(session, data, *, actor: str, commit: bool = True) -> models.Circuit`; `create_session(session, data, *, actor: str, commit: bool = True) -> models.BgpSession`

- [ ] **Step 1: Write the failing test**

Crie `tests/domain/test_services_commit.py`:

```python
"""O `commit=False` que a adoção usa para caber numa transação só (design §3)."""
from sqlalchemy import select

from gerenet.domain import models
from gerenet.domain.schemas import (
    BgpSessionCreate,
    CircuitCreate,
    DeviceCreate,
    OrganizationCreate,
    SiteCreate,
)
from gerenet.domain.services.bgp_sessions import create_session
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


def test_organizacao_com_commit_false_nao_grava_antes_do_commit(db_session) -> None:
    create_organization(
        db_session, OrganizationCreate(name="Cliente Sem Commit"), actor="cli", commit=False
    )
    db_session.rollback()
    assert db_session.scalar(
        select(models.Organization).where(models.Organization.name == "Cliente Sem Commit")
    ) is None


def test_organizacao_no_default_grava_como_sempre(db_session) -> None:
    create_organization(db_session, OrganizationCreate(name="Cliente Com Commit"), actor="cli")
    db_session.expire_all()
    assert db_session.scalar(
        select(models.Organization).where(models.Organization.name == "Cliente Com Commit")
    ) is not None


def _ambiente(db_session):
    """Site, organização e equipamento: `CircuitCreate` exige device de acesso e edge."""
    site = create_site(db_session, SiteCreate(name="pop-commit"), actor="cli")
    org = create_organization(db_session, OrganizationCreate(name="Org Commit", asn=64700), actor="cli")
    dev = create_device(
        db_session,
        DeviceCreate(name="ne-commit", management_address="10.9.9.9", asn=65001),
        actor="cli",
    )
    return site, org, dev


def test_circuito_com_commit_false_nao_grava_antes_do_commit(db_session) -> None:
    site, org, dev = _ambiente(db_session)
    create_circuit(
        db_session,
        CircuitCreate(code="CIRC-SEM-COMMIT", organization_id=org.id, site_id=site.id,
                      access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id),
        actor="cli", commit=False,
    )
    db_session.rollback()
    assert db_session.scalar(
        select(models.Circuit).where(models.Circuit.code == "CIRC-SEM-COMMIT")
    ) is None


def test_sessao_com_commit_false_nao_grava_antes_do_commit(db_session) -> None:
    site, org, dev = _ambiente(db_session)
    circuito = create_circuit(
        db_session,
        CircuitCreate(code="CIRC-SESSAO", organization_id=org.id, site_id=site.id,
                      access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id),
        actor="cli",
    )
    create_session(
        db_session,
        BgpSessionCreate(circuit_id=circuito.id, device_id=dev.id, afi="ipv4",
                         local_address="100.64.90.0", remote_address="100.64.90.1",
                         asn_remote=64700),
        actor="cli", commit=False,
    )
    db_session.rollback()
    assert db_session.scalar(
        select(models.BgpSession).where(models.BgpSession.remote_address == "100.64.90.1")
    ) is None
```

Ajuste os campos obrigatórios de `CircuitCreate`/`BgpSessionCreate` conforme os schemas reais se algum faltar, e diga no relatório o que mudou.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_services_commit.py -q`
Expected: FAIL com `TypeError: create_organization() got an unexpected keyword argument 'commit'`

- [ ] **Step 3: Implement in the three services**

Nos três arquivos a mudança é a mesma forma: a assinatura ganha `commit: bool = True`, e o `commit`/`refresh` ficam sob a condição. O `flush`, o `registrar` e o `except IntegrityError` ficam intactos, porque a validação de unicidade e o evento de auditoria têm que acontecer mesmo na transação do chamador.

Em `organizations.py`:

```python
def create_organization(
    session: Session, data: OrganizationCreate, *, actor: str, commit: bool = True
) -> models.Organization:
```

e, no fim:

```python
    try:
        session.flush()  # valida unicidade antes da auditoria
        registrar(
            session, tipo="organization.create", ator=actor, objeto="organization",
            objeto_id=org.id, antes=None, depois=dump,
        )
        if commit:
            session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"Já existe organização com o nome {data.name}.") from exc
    if commit:
        session.refresh(org)
    return org
```

O mesmo em `circuits.py` (`create_circuit`, `commit: bool = True`, `ConflictError` do código) e em `bgp_sessions.py` (`create_session`, `commit: bool = True`). **Confira cada arquivo antes de editar**: a estrutura do `try` é a mesma nos três, mas as mensagens de conflito e o que vem depois do `refresh` diferem, e um `return` a mais não pode ser engolido.

Acrescente à docstring de cada uma, em uma linha, por que o parâmetro existe: a adoção da descoberta encadeia os três e precisa de uma transação única (design §3).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_services_commit.py -q`
Expected: PASS nos cinco testes

Run: `uv run pytest tests/domain tests/api -q`
Expected: PASS (o default preserva o comportamento, e é aqui que isso se prova)

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/domain/services/organizations.py src/gerenet/domain/services/circuits.py src/gerenet/domain/services/bgp_sessions.py tests/domain/test_services_commit.py
git commit -m "feat(adocao): commit=False nos serviços de cadastro para a adoção caber numa transação"
```

---

### Task 2: A reserva por valores reais

`reservar_circuito` escolhe os valores (first-fit) e deriva o `/126` do v4 pela regra do §25.8. Um circuito legado não segue nenhuma das duas coisas: o VID e os endereços que estão no roteador foram escolhidos por alguém, anos atrás. Esta tarefa acrescenta a irmã que grava o que existe.

**Files:**
- Modify: `src/gerenet/domain/services/ipam.py` (acrescenta ao fim)
- Create: `tests/domain/test_ipam_adocao.py`

**Interfaces:**
- Consumes: `pontas_v4`/`pontas_v6` com orientação, `validar_vid`, `PONTA_LOCAL`, `registrar`
- Produces: `reservar_adocao(session, circuit_id: int, *, vlans: list[dict], prefixos: list[dict], actor: str, origem_snapshot_id: int | None = None, commit: bool = True) -> models.Circuit`, com `vlans` em `{"vid": int, "kind": str, "family": str | None}` e `prefixos` em `{"network": str, "ponta_local": str}`

- [ ] **Step 1: Write the failing test**

Crie `tests/domain/test_ipam_adocao.py`:

```python
"""A reserva por valores reais (design §4): grava o que o equipamento tem."""
import pytest

from gerenet.domain import models
from gerenet.domain.schemas import CircuitCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.circuits import create_circuit
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.ipam import pontas_v4, pontas_v6, reservar_adocao
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site


def _circuito(db_session, *, code="CIRC-ADOC"):
    site = create_site(db_session, SiteCreate(name=f"pop-{code}", p2p_ipv4_block="100.64.70.0/24"),
                       actor="cli")
    org = create_organization(db_session, OrganizationCreate(name=f"Org {code}", asn=64701), actor="cli")
    return create_circuit(
        db_session,
        CircuitCreate(code=code, organization_id=org.id, site_id=site.id,
                      access_device_id=None, access_port="GE0/0/1", edge_device_id=None),
        actor="cli",
    )


def test_grava_os_valores_reais_inclusive_o_v6_nao_derivado(db_session) -> None:
    """O v6 legado não segue a derivação do §25.8, e é o valor do equipamento
    que precisa ser preservado."""
    circ = _circuito(db_session)
    reservar_adocao(
        db_session, circ.id,
        vlans=[{"vid": 625, "kind": "vlan", "family": None}],
        prefixos=[{"network": "100.110.0.0/30", "ponta_local": "inferior"},
                  {"network": "2804:194C:1000::1100:0:0/126", "ponta_local": "inferior"}],
        actor="cli", origem_snapshot_id=7,
    )
    vlan = db_session.scalar(select(models.Vlan).where(models.Vlan.circuit_id == circ.id))
    assert vlan.vid == 625
    prefixos = list(db_session.scalars(
        select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ.id)
    ))
    assert {p.network for p in prefixos} == {"100.110.0.0/30", "2804:194C:1000::1100:0:0/126"}
    assert all(p.ponta_local == "inferior" for p in prefixos)


def test_grava_a_ponta_superior_quando_e_a_do_equipamento(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-SUP")
    reservar_adocao(
        db_session, circ.id,
        vlans=[{"vid": 626, "kind": "vlan", "family": None}],
        prefixos=[{"network": "100.64.70.0/31", "ponta_local": "superior"}],
        actor="cli",
    )
    prefixo = db_session.scalar(select(models.IpPrefix).where(models.IpPrefix.circuit_id == circ.id))
    assert prefixo.ponta_local == "superior"
    assert pontas_v4(prefixo.network, prefixo.ponta_local)[0] == "100.64.70.1"


def test_conflito_de_vlan_vira_conflict_error_nomeado(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-A")
    reservar_adocao(db_session, circ.id, vlans=[{"vid": 627, "kind": "vlan", "family": None}],
                    prefixos=[], actor="cli")
    outro = _circuito(db_session, code="CIRC-ADOC-B")
    with pytest.raises(ConflictError) as exc:
        reservar_adocao(db_session, outro.id, vlans=[{"vid": 627, "kind": "vlan", "family": None}],
                        prefixos=[], actor="cli")
    assert "627" in str(exc.value)


def test_valor_fora_de_faixa_e_validation_error(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-V")
    with pytest.raises(ValidationError):
        reservar_adocao(db_session, circ.id, vlans=[{"vid": 1, "kind": "vlan", "family": None}],
                        prefixos=[], actor="cli")
    with pytest.raises(ValidationError):
        reservar_adocao(db_session, circ.id,
                        vlans=[],
                        prefixos=[{"network": "100.64.70.0/24", "ponta_local": "inferior"}],
                        actor="cli")


def test_e_idempotente(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-IDEM")
    for _ in range(2):
        reservar_adocao(db_session, circ.id, vlans=[{"vid": 628, "kind": "vlan", "family": None}],
                        prefixos=[{"network": "100.64.70.0/31", "ponta_local": "inferior"}],
                        actor="cli")
    vlan = list(db_session.scalars(select(models.Vlan).where(models.Vlan.circuit_id == circ.id)))
    assert len(vlan) == 1


def test_audita_com_origem_adocao_e_o_snapshot(db_session) -> None:
    circ = _circuito(db_session, code="CIRC-ADOC-AUD")
    reservar_adocao(db_session, circ.id, vlans=[{"vid": 629, "kind": "vlan", "family": None}],
                    prefixos=[], actor="cli", origem_snapshot_id=42)
    evento = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.type == "circuit.reserve")
        .order_by(models.AuditEvent.id.desc())
    ).first()
    assert evento is not None
    assert evento.payload.get("origem") == "adocao" or "42" in str(evento.payload)
```

Acrescente `from sqlalchemy import select` ao topo. **Confira o nome real da coluna do payload de auditoria** em `domain/models.py` antes de escrever a asserção do último teste, e ajuste.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_ipam_adocao.py -q`
Expected: FAIL com `ImportError: cannot import name 'reservar_adocao'`

- [ ] **Step 3: Write the reservation**

Acrescente ao fim de `src/gerenet/domain/services/ipam.py`:

```python
def _valida_prefixo_adocao(prefixo: dict) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """CIDR canônico e alinhado, v4 em /30 ou /31 e v6 em /126 (design §4)."""
    try:
        rede = ipaddress.ip_network(prefixo["network"], strict=True)
    except ValueError as exc:
        raise ValidationError(f"Rede inválida para reserva: {prefixo.get('network')}.") from exc
    if rede.version == 4 and rede.prefixlen not in _ENLACES_V4:
        raise ValidationError(f"Enlace p2p v4 deve ser /30 ou /31: {rede}.")
    if rede.version == 6 and rede.prefixlen != 126:
        raise ValidationError(f"Enlace p2p v6 deve ser /126: {rede}.")
    if prefixo.get("ponta_local", "inferior") not in PONTA_LOCAL:
        raise ValidationError(f"Orientação de ponta inválida: {prefixo.get('ponta_local')}.")
    return rede


def reservar_adocao(
    session: Session, circuit_id: int, *, vlans: list[dict], prefixos: list[dict],
    actor: str, origem_snapshot_id: int | None = None, commit: bool = True,
) -> models.Circuit:
    """Reserva VLAN(s) e enlace(s) com os valores REAIS do equipamento (design §4).

    Diferente da `reservar_circuito`, que escolhe em first-fit e deriva o /126 do
    par v4 (§25.8): aqui os valores vêm do que está configurado no roteador, e um
    circuito legado não segue nem a escolha nem a derivação. A orientação da
    ponta é gravada porque é ela que faz o render devolver o endereço correto.
    Idempotente: circuito já reservado devolve o estado atual.
    """
    circ = get_circuit(session, circuit_id)
    if circ.admin_status is False:
        raise ConflictError(f"Circuito {circ.code} desativado não recebe reservas.")
    ja_reservado = session.scalars(
        select(models.Vlan.id).where(
            models.Vlan.circuit_id == circ.id, models.Vlan.status == "reservada"
        ).limit(1)
    ).first() is not None
    if ja_reservado:
        registrar(session, tipo="circuit.reserve", ator=actor, objeto="circuit",
                  objeto_id=circ.id, antes=None, depois={"repetida": True})
        if commit:
            session.commit()
        return circ

    for vlan in vlans:
        validar_vid(vlan["vid"])
    redes = [_valida_prefixo_adocao(p) for p in prefixos]

    linhas_vlan = [
        models.Vlan(site_id=circ.site_id, vid=v["vid"], kind=v["kind"],
                    family=v.get("family"), circuit_id=circ.id, status="reservada")
        for v in vlans
    ]
    linhas_prefixo = [
        models.IpPrefix(site_id=circ.site_id, network=str(rede), kind="p2p",
                        circuit_id=circ.id, ponta_local=prefixos[i].get("ponta_local", "inferior"))
        for i, rede in enumerate(redes)
    ]
    session.add_all(linhas_vlan + linhas_prefixo)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "Reserva recusada por unicidade: a VLAN ou o prefixo já está reservado "
            "neste site para outro circuito."
        ) from exc
    registrar(
        session, tipo="circuit.reserve", ator=actor, objeto="circuit", objeto_id=circ.id,
        antes=None,
        depois={
            "origem": "adocao",
            "snapshot_id": origem_snapshot_id,
            "vlans": [{"vid": v.vid, "kind": v.kind} for v in linhas_vlan],
            "ip_prefixes": [{"network": p.network, "ponta_local": p.ponta_local}
                            for p in linhas_prefixo],
        },
    )
    if commit:
        session.commit()
        session.refresh(circ)
    return circ
```

Acrescente aos imports do módulo `IntegrityError` (de `sqlalchemy.exc`) e `PONTA_LOCAL` não é necessário (já se usa `models.PONTA_LOCAL`); ajuste para `models.PONTA_LOCAL` se preferir. `_ENLACES_V4` já existe no módulo.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_ipam_adocao.py tests/domain/test_ipam.py -q`
Expected: PASS em todos

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/domain/services/ipam.py tests/domain/test_ipam_adocao.py
git commit -m "feat(adocao): reserva por valores reais, com a orientação da ponta"
```

---

### Task 3: As dívidas da parte 1 que entram aqui

Cinco ajustes no motor, todos do mesmo feitio: tirar uma promessa que a parte 1 não podia cumprir, ou tirar um silêncio. Cada um tem o seu teste.

**Files:**
- Modify: `src/gerenet/automation/discovery.py`
- Modify: `tests/automation/test_discovery.py`
- Modify: `src/gerenet/cli/discovery.py` (o `list` usa os internos do resultado)

**Interfaces:**
- Consumes: o motor da parte 1
- Produces: `Diferenca(contexto, sobrando, faltando, nao_gerenciado=(), explicacao=None)` com a property `exige_ciente`; `ResultadoPropostas` com `internos: list[Candidato]` e `snapshot_age_seconds: float | None`

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/automation/test_discovery.py`:

```python
def test_o_resultado_traz_os_internos_e_a_idade_da_coleta(db_session, tmp_path) -> None:
    """O `list` do CLI parava de parsear a config duas vezes só por causa disto."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_propostas(db_session, dev.id)
    assert [c.remote_address for c in resultado.internos] == ["10.0.0.9"]
    assert resultado.snapshot_age_seconds is not None
    assert resultado.snapshot_age_seconds >= 0


def test_diferenca_separa_o_que_a_sot_nao_gerencia(db_session, tmp_path) -> None:
    """Descrição e MTU da subinterface saem do que exige ciente (design §6)."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    diferencas = conferir_fidelidade(db_session, alfa)
    sub = next(d for d in diferencas if d.contexto == "subinterface")
    assert any("description" in linha for linha in sub.nao_gerenciado)
    assert not any("description" in linha for linha in sub.faltando + sub.sobrando)


def test_exige_ciente_so_quando_o_render_mudaria_o_equipamento(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    sub = next(d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "subinterface")
    assert sub.exige_ciente is False  # só descrição sobra, que não é gerenciada


def test_o_ensaio_nao_usa_faltando_para_explicar(db_session, tmp_path) -> None:
    """A explicação do ensaio vai no campo dela: `sobrando` e `faltando` vazios
    num contexto `ensaio` leriam como fidelidade."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    vpn = next(p for p in listar_propostas(db_session, dev.id).propostas if p.vrf == "VPNA")
    (diferenca,) = conferir_fidelidade(db_session, vpn)
    assert diferenca.contexto == "ensaio"
    assert diferenca.explicacao is not None
    assert diferenca.sobrando == ()
    assert diferenca.faltando == ()
```

A proposta em VRF existe porque a fixture tem o bloco `ipv4-family vpn-instance VPNA` com o peer `10.99.0.1`, e a conferência recusa certificar o que o render não reproduz (o `vrf_nao_renderizavel` da parte 1).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/automation/test_discovery.py -q -k "internos or nao_gerencia or exige_ciente or ensaio_nao_usa"`
Expected: FAIL

- [ ] **Step 3: Implement**

Em `src/gerenet/automation/discovery.py`:

1. `Diferenca` ganha dois campos com default e a property:

```python
@dataclass(frozen=True)
class Diferenca:
    contexto: str
    sobrando: tuple[str, ...] = ()
    faltando: tuple[str, ...] = ()
    nao_gerenciado: tuple[str, ...] = ()   # a SoT não emite isto, e não é divergência
    explicacao: str | None = None          # quando a comparação não pôde ser feita

    @property
    def exige_ciente(self) -> bool:
        """Só o que a SoT VAI MUDAR no equipamento gateia o aceite (design §6)."""
        return bool(self.sobrando or self.faltando)
```

2. `_snapshot_com_config` passa a devolver `tuple[models.DeviceSnapshot | None, str]` (o snapshot e o texto já lido), e a leitura acontece uma vez por snapshot. Quem chama usa o texto devolvido em vez de ler de novo.

3. `ResultadoPropostas` ganha `internos: list[Candidato] = field(default_factory=list)` e `snapshot_age_seconds: float | None = None`, preenchidos de `descoberta.internos` e de `snap.started_at`.

4. Em `conferir_fidelidade`, a partição do contexto `subinterface`:

```python
_NAO_GERENCIADAS_SUBINTERFACE = ("description ", "mtu ")

def _particiona_subinterface(linhas: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separa o que a SoT gerencia do que ela só não emite (design §17.1).

    O render não tem `description` de subinterface (o slot existe no template e
    nada o preenche) nem `mtu`, e numa borda real os dois estão em toda
    subinterface. Deixá-los no `faltando` faria "diferença exige ciente"
    degenerar em "marque sempre".
    """
    gerenciadas, nao_gerenciadas = [], []
    for linha in linhas:
        alvo = nao_gerenciadas if linha.startswith(_NAO_GERENCIADAS_SUBINTERFACE) else gerenciadas
        alvo.append(linha)
    return tuple(sorted(gerenciadas)), tuple(sorted(nao_gerenciadas))
```

e o `Diferenca` do contexto `subinterface` passa a usar as duas saídas.

5. O caso de proposta sem site deixa de devolver `[]` e devolve a `Diferenca` de contexto `ensaio` com `explicacao` explicando, e o caso de VRF idem (hoje ele já devolve uma diferença de `ensaio`, mas com a explicação dentro do `faltando`; mova para `explicacao`).

6. Nada mais usa `Diferenca` por posição: ajuste os construtores existentes para os campos nomeados.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_discovery.py tests/cli/test_discovery_cli.py -q`
Expected: PASS em todos

- [ ] **Step 5: Simplify the CLI**

Em `src/gerenet/cli/discovery.py`, o `list` deixa de chamar `listar_candidatos` de novo e usa `resultado.internos`; e passa a imprimir a idade da coleta quando `snapshot_age_seconds` não for nulo.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/automation/discovery.py src/gerenet/cli/discovery.py tests/automation/test_discovery.py
git commit -m "fix(adocao): internos e idade no resultado, e a diferença que não gateia"
```

---

### Task 4: A conferência do corpo das definições

A conferência da parte 1 compara as linhas do peer e o bloco da interface. Os blocos de **definição** que o render emite para aquelas sessões (prefix-list, route-policy de import e export, community-filter, as-path-filter) ficam de fora, porque o filtro por linha de peer os descarta. O efeito é estreito e real: o nome da route-policy deriva do ASN do par, então escolher o produto errado na revisão produz linhas de peer **idênticas byte a byte** com um corpo de política completamente diferente. É o modo de falha que a conferência existe para impedir, e é o que esta tarefa fecha.

**Files:**
- Modify: `src/gerenet/automation/discovery.py`
- Modify: `tests/automation/test_discovery.py`

**Interfaces:**
- Consumes: `render_desejado`, os blocos com `objeto == "session"` e `tipo` de definição
- Produces: `Diferenca` de contexto `"definicao"`, uma por bloco de definição do ensaio

- [ ] **Step 1: Write the failing test**

```python
def test_a_conferencia_compara_o_corpo_das_definicoes(db_session, tmp_path) -> None:
    """Escolher o produto errado rende linhas de peer idênticas com política
    diferente, e é isso que a comparação do corpo pega (design §6)."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    contextos = {d.contexto for d in conferir_fidelidade(db_session, alfa)}
    assert "definicao" in contextos


def test_definicao_ausente_no_equipamento_aparece_como_sobrando(db_session, tmp_path) -> None:
    """O render define `IP-PFX-64512-IN-V4` e a configuração não tem esse bloco:
    ele aparece inteiro como sobra."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    definicoes = [d for d in conferir_fidelidade(db_session, alfa) if d.contexto == "definicao"]
    assert any(d.sobrando for d in definicoes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/automation/test_discovery.py -q -k "corpo_das_definicoes or definicao_ausente"`
Expected: FAIL (nenhum contexto `definicao` hoje)

- [ ] **Step 3: Implement**

Acrescente a `src/gerenet/automation/discovery.py`:

```python
# Blocos de DEFINIÇÃO: o render os emite para a sessão, e o filtro por linha de
# peer os descarta. A chave é o cabeçalho sem o corpo, e as duas pontas usam a
# MESMA regra, porque a premissa da comparação é que o texto é o mesmo comando.
_TIPOS_DEFINICAO = ("prefix_list", "as_path_filter", "community_filter",
                    "route_policy_import", "route_policy_export")


def _chave_definicao(linha: str) -> str | None:
    """Chave do bloco de definição a partir da linha de cabeçalho.

    `route-policy NOME permit|deny node N` → `route-policy NOME`; os demais são
    `ip ip-prefix NOME`, `ip ipv6-prefix NOME`, `ip as-path-filter NOME` e
    `ip community-filter NOME`, todos com o nome no terceiro token.
    """
    partes = linha.split()
    if not partes:
        return None
    if partes[0] == "route-policy" and len(partes) >= 2:
        return f"route-policy {partes[1]}"
    if partes[0] == "ip" and len(partes) >= 3 and partes[1] in (
        "ip-prefix", "ipv6-prefix", "as-path-filter", "community-filter"
    ):
        return f"ip {partes[1]} {partes[2]}"
    return None


def _indice_definicoes(texto: str) -> dict[str, tuple[str, ...]]:
    """Blocos de definição da configuração, indexados pela chave.

    Um bloco começa numa linha sem indentação cujo cabeçalho casa
    `_chave_definicao` e vai até a próxima linha sem indentação. Comentário é
    qualquer linha começando com `#`, e não só o separador sozinho: o render
    deste projeto emite comentário com texto na coluna 0 dentro do bloco, e a
    lição vem da parte 1 (uma linha dessas fechava o bloco e truncava a leitura
    em silêncio).
    """
    indice: dict[str, list[str]] = {}
    chave: str | None = None
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            chave = None
            continue
        if not bruta[:1].isspace():
            chave = _chave_definicao(linha)
            if chave is not None:
                indice.setdefault(chave, []).append(linha)
            continue
        if chave is not None:
            indice[chave].append(linha)
    return {c: tuple(linhas) for c, linhas in indice.items()}
```

E, dentro de `conferir_fidelidade`, depois dos contextos de peer e de subinterface e ainda dentro do `try`:

```python
        indice = _indice_definicoes(texto)
        for bloco in render.blocos:
            if bloco.objeto != "session" or bloco.objeto_id not in ids_sessoes:
                continue
            if bloco.tipo not in _TIPOS_DEFINICAO or not bloco.comandos:
                continue
            chave = _chave_definicao(bloco.comandos[0])
            if chave is None:
                continue
            esperado = _normaliza_linhas(bloco.comandos)
            encontrado = _normaliza_linhas(list(indice.get(chave, ())))
            resultado.append(Diferenca(
                contexto="definicao",
                sobrando=tuple(sorted(esperado - encontrado)),
                faltando=tuple(sorted(encontrado - esperado)),
            ))
```

Cuidado com dois detalhes: o índice tem de ser construído **uma vez** por chamada, não por bloco; e o `_normaliza_linhas` já descarta linha comentada e normaliza espaço, que é o que faz o corpo indentado do VRP comparar com o do render, que sai sem indentação.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_discovery.py -q`
Expected: PASS em todos

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/automation/discovery.py tests/automation/test_discovery.py
git commit -m "feat(adocao): a conferência compara o corpo das definições"
```

---

### Task 5: A adoção

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (a revisão e os overrides de sessão)
- Modify: `src/gerenet/domain/services/discovery.py` (a orquestração)
- Create: `tests/domain/test_adocao.py`

**Interfaces:**
- Consumes: `listar_propostas`, `conferir_fidelidade`, `reservar_adocao` (Task 2), `create_organization`/`create_circuit`/`create_session` com `commit=False` (Task 1), `registrar`
- Produces: `AdocaoIn`, `AdocaoSessaoIn` (schemas) e `adotar_proposta(session, *, proposta, revisao: AdocaoIn, actor: str) -> int` devolvendo o `circuit_id`

- [ ] **Step 1: Write the failing test**

Crie `tests/domain/test_adocao.py`:

```python
"""A adoção transacional (design §5): uma transação por proposta."""
from pathlib import Path

import pytest
from sqlalchemy import select

from gerenet.automation.discovery import listar_propostas
from gerenet.domain import models
from gerenet.domain.schemas import AdocaoIn, AdocaoSessaoIn, DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import adotar_proposta
from gerenet.domain.services.errors import ConflictError, ValidationError
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _ambiente(db_session, tmp_path: Path):
    site = create_site(db_session, SiteCreate(name="pop-adoc", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-adoc", management_address="10.0.0.1",
                                                 asn=65001), actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return site, dev


def _proposta(db_session, dev, *, vid=1001):
    return next(p for p in listar_propostas(db_session, dev.id).propostas if p.vid == vid)


def _revisao(dev, *, code="ADOC-64512-1001", ciente=False):
    return AdocaoIn(
        device_id=dev.id, vrf=None, subinterface="Eth-Trunk127.1001",
        circuit_code=code, access_device_id=dev.id, access_port="GE0/0/1",
        organizacao_nova={"name": "Cliente Alfa", "kind": "downstream", "asn": 64512},
        sessoes=[AdocaoSessaoIn(afi="ipv4"), AdocaoSessaoIn(afi="ipv6")],
        ciente=ciente,
    )


def test_adota_a_cadeia_inteira_numa_transacao(db_session, tmp_path) -> None:
    _site, dev = _ambiente(db_session, tmp_path)
    circ_id = adotar_proposta(db_session, proposta=_proposta(db_session, dev),
                              revisao=_revisao(dev), actor="cli")
    circ = db_session.get(models.Circuit, circ_id)
    assert circ.code == "ADOC-64512-1001"
    assert circ.organization_id is not None
    vlan = db_session.scalar(select(models.Vlan).where(models.Vlan.circuit_id == circ_id))
    assert vlan.vid == 1001
    assert len(list(db_session.scalars(
        select(models.BgpSession).where(models.BgpSession.circuit_id == circ_id)
    ))) == 2
    tipos = [e.type for e in db_session.scalars(select(models.AuditEvent))]
    assert "discovery.adopt" in tipos


def test_conflito_de_reserva_nao_deixa_nada_gravado(db_session, tmp_path) -> None:
    """A asserção que a parte 1 não podia fazer: a transação é uma só."""
    from gerenet.domain.schemas import CircuitCreate, OrganizationCreate
    from gerenet.domain.services.circuits import create_circuit
    from gerenet.domain.services.organizations import create_organization

    site, dev = _ambiente(db_session, tmp_path)
    org = create_organization(db_session, OrganizationCreate(name="Dono da VLAN", asn=64999),
                              actor="cli")
    tomador = create_circuit(db_session, CircuitCreate(
        code="CIRC-TOMADOR", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, vid=1001, kind="vlan", circuit_id=tomador.id))
    db_session.commit()
    antes = db_session.query(models.Circuit).count()
    with pytest.raises(ConflictError):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                        actor="cli")
    assert db_session.query(models.Circuit).count() == antes
    assert db_session.scalar(
        select(models.Organization).where(models.Organization.name == "Cliente Alfa")
    ) is None


def test_sem_organizacao_bloqueia(db_session, tmp_path) -> None:
    _site, dev = _ambiente(db_session, tmp_path)
    revisao = _revisao(dev)
    revisao.organizacao_nova = None
    with pytest.raises(ValidationError):
        adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=revisao,
                        actor="cli")


def test_adotar_de_novo_encontra_a_lista_vazia(db_session, tmp_path) -> None:
    """O objeto passou a existir na SoT, então a proposta sai da lista sozinha."""
    _site, dev = _ambiente(db_session, tmp_path)
    adotar_proposta(db_session, proposta=_proposta(db_session, dev), revisao=_revisao(dev),
                    actor="cli")
    assert 1001 not in {p.vid for p in listar_propostas(db_session, dev.id).propostas}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_adocao.py -q`
Expected: FAIL com `ImportError: cannot import name 'adotar_proposta'`

- [ ] **Step 3: Add the schemas**

No fim de `src/gerenet/domain/schemas.py`:

```python
class AdocaoSessaoIn(BaseModel):
    """O que o operador decide por sessão; o resto vem da proposta."""

    afi: Literal["ipv4", "ipv6"]
    import_profile_id: int | None = None
    export_profile_id: int | None = None
    password_ref: str | None = Field(default=None, max_length=255)


class AdocaoIn(BaseModel):
    """A revisão de uma proposta (design §6)."""

    device_id: int
    vrf: str | None = None
    subinterface: str | None = None
    circuit_code: str = Field(min_length=1, max_length=64)
    access_device_id: int
    access_port: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9/\-]+$")
    edge_trunk: str | None = Field(default=None, max_length=64)
    organizacao_id: int | None = None
    organizacao_nova: OrganizationCreate | None = None
    sessoes: list[AdocaoSessaoIn] = Field(default_factory=list)
    ciente: bool = False
```

`OrganizationCreate` já existe; confirme que ele aceita `kind` e `asn` antes de usar como tipo aninhado (no teste ele é passado como dict, e o Pydantic valida).

**Verifique** se `BgpSessionCreate` tem `password_ref`. Se não tiver, acrescente
`password_ref: str | None = Field(default=None, max_length=255)` a ele: é o **caminho** no
Vault, nunca o valor, e sem ele a adoção não tem como registrar que a sessão tem senha (a
parte 1 levanta `senha_nao_legivel` quando o equipamento tem uma).

- [ ] **Step 4: Write the adoption**

Acrescente ao fim de `src/gerenet/domain/services/discovery.py`:

```python
def _sessao_da_proposta(proposta, overrides: schemas.AdocaoSessaoIn) -> schemas.BgpSessionCreate:
    """Junta o que a proposta leu da configuração com o que o operador decidiu.

    O dict da proposta usa nomes de coluna de `bgp_sessions`; só os campos que o
    schema de criação declara passam, para um nome a mais não estourar o construtor.
    """
    dados = next(s for s in proposta.sessoes if s["afi"] == overrides.afi)
    campos = set(schemas.BgpSessionCreate.model_fields)
    # Os três campos que o operador decide são retirados do que veio da proposta:
    # se algum dia a leitura passar a preenchê-los, o `**base` não pode repetir o
    # argumento e estourar o construtor.
    base = {
        k: v for k, v in dados.items()
        if k in campos and k not in ("import_profile_id", "export_profile_id", "password_ref")
    }
    return schemas.BgpSessionCreate(
        **base,
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
    if organizacao_id is None:
        if revisao.organizacao_nova is None:
            raise ValidationError(
                "Informe a organização: escolha uma existente ou crie a nova com o ASN "
                f"{asn_remoto}."
            )
        org = create_organization(session, revisao.organizacao_nova, actor=actor, commit=False)
        organizacao_id = org.id

    circuito = create_circuit(
        session,
        schemas.CircuitCreate(
            code=revisao.circuit_code, organization_id=organizacao_id, site_id=proposta.site_id,
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
            _sessao_da_proposta(proposta, overrides).model_copy(
                update={"circuit_id": circuito.id, "device_id": proposta.device_id}
            ),
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
    return circuito.id
```

Ajuste os imports do módulo: `schemas`, `create_organization`, `create_circuit`,
`create_session`, `reservar_adocao`, `ConflictError`, `ValidationError`, `registrar` e
`conferir_fidelidade`.

**Confira os nomes reais** dos campos de `CircuitCreate` (o do QinQ é `qinq`? existe `vrf`?) e
de `OrganizationCreate` antes de escrever. Um nome a mais estoura o construtor, e o teste
pega.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_adocao.py -q`
Expected: PASS nos quatro testes

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/domain/schemas.py src/gerenet/domain/services/discovery.py tests/domain/test_adocao.py
git commit -m "feat(adocao): a adoção transacional, com o ciente e a auditoria"
```

---

### Task 6: A API

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (`DiferencaOut`, `FidelidadeOut`, e os dois campos novos no `DiscoveryOut`)
- Modify: `src/gerenet/api/routers/discovery.py`
- Create: `tests/api/test_discovery_adopt_api.py`

**Interfaces:**
- Consumes: `adotar_proposta` (Task 5), `conferir_fidelidade`, `listar_propostas`
- Produces: `POST /api/v1/discovery/adopt` e `GET /api/v1/discovery/fidelidade`

- [ ] **Step 1: Write the failing test**

Crie `tests/api/test_discovery_adopt_api.py`:

```python
"""A API da adoção (design §7)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


@pytest.fixture()
def client() -> TestClient:
    set_settings(Settings(api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def _ambiente(db_session, tmp_path: Path) -> dict:
    site = create_site(db_session, SiteCreate(name="pop-adoc-api", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-adoc-api",
                                                 management_address="10.0.0.1", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return {"dev": dev, "site": site}


def _payload(ambiente) -> dict:
    return {
        "device_id": ambiente["dev"].id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-API-1001", "access_device_id": ambiente["dev"].id,
        "access_port": "GE0/0/1",
        "organizacao_nova": {"name": "Cliente API", "kind": "downstream", "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": True,
    }


def test_fidelidade_sob_demanda(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    resposta = client.get(
        f"/api/v1/discovery/fidelidade?device_id={ambiente['dev'].id}"
        "&subinterface=Eth-Trunk127.1001",
        headers=_auth(),
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert isinstance(corpo["diferencas"], list)
    assert all({"contexto", "sobrando", "faltando", "nao_gerenciado"} <= set(d)
               for d in corpo["diferencas"])


def test_adota_e_devolve_o_circuito(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    resposta = client.post("/api/v1/discovery/adopt", json=_payload(ambiente), headers=_auth())
    assert resposta.status_code == 201, resposta.text
    circ_id = resposta.json()["circuit_id"]
    assert db_session.get(models.Circuit, circ_id).code == "ADOC-API-1001"


def test_proposta_com_conflito_e_409(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["subinterface"] = "Eth-Trunk127.2001"  # a do cliente beta, sem enable por família
    resposta = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert resposta.status_code == 409


def test_sem_ciente_onde_exige_e_422(client, db_session, tmp_path) -> None:
    """A proposta da fixture tem diferença de política, que muda o equipamento."""
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["ciente"] = False
    resposta = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert resposta.status_code == 422


def test_proposta_inexistente_e_404(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    corpo = _payload(ambiente)
    corpo["subinterface"] = "Eth-Trunk127.9999"
    resposta = client.post("/api/v1/discovery/adopt", json=corpo, headers=_auth())
    assert resposta.status_code == 404
```

Se algum desses casos não se sustentar contra a fixture real (por exemplo, se a proposta do
1001 não tiver diferença que exija `ciente`, ou se o 2001 não gerar conflito), ajuste o caso e
**diga no relatório** o que mudou e por quê. O que não pode é o teste passar sem exercitar o
que ele diz exercitar.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_discovery_adopt_api.py -q`
Expected: FAIL com 404 nas rotas novas

- [ ] **Step 3: Add the schemas**

No fim de `src/gerenet/domain/schemas.py`:

```python
class DiferencaOut(BaseModel):
    contexto: str
    sobrando: list[str]
    faltando: list[str]
    nao_gerenciado: list[str]
    explicacao: str | None
    exige_ciente: bool


class FidelidadeOut(BaseModel):
    device_id: int
    subinterface: str | None
    diferencas: list[DiferencaOut]


class AdocaoOut(BaseModel):
    circuit_id: int
```

E em `DiscoveryOut`, acrescente:

```python
    internos: list[CandidatoOut] = []
    snapshot_age_seconds: float | None = None
```

**A rota que já existe precisa preenchê-los.** Em `listar`, a que responde o
`GET /api/v1/discovery`, acrescente ao construtor do `DiscoveryOut`:

```python
        internos=[schemas.CandidatoOut.model_validate(c) for c in resultado.internos],
        snapshot_age_seconds=resultado.snapshot_age_seconds,
```

Sem isso os dois campos existem no schema e chegam sempre vazios, e a idade da coleta, que a
Task 3 fez o motor calcular justamente para o operador ver, não chega a lugar nenhum.

- [ ] **Step 4: Write the router**

Em `src/gerenet/api/routers/discovery.py`, acrescente as duas rotas. A de adoção precisa
achar a proposta pela identidade que veio no payload, e é aí que o 404 nasce: se a proposta
não está mais na lista, alguém adotou antes (a lista se cura sozinha).

```python
@router.get("/fidelidade", response_model=schemas.FidelidadeOut)
def fidelidade(
    session: SessionDep, device_id: int, subinterface: str | None = None, vrf: str | None = None,
    import_ipv4: int | None = None, export_ipv4: int | None = None,
    import_ipv6: int | None = None, export_ipv6: int | None = None,
) -> schemas.FidelidadeOut:
    """O diff de UMA proposta, sob demanda: cada conferência roda o render do
    equipamento inteiro num ensaio, então ela não vai embutida na lista (design §7).

    Os quatro parâmetros de perfil são os que o operador escolheu na revisão: sem
    eles o ensaio não renderiza o corpo da política de exportação, e a conferência
    estaria comparando algo diferente do que a adoção vai gravar.
    """
    try:
        resultado = listar_propostas(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    proposta = next(
        (p for p in resultado.propostas
         if p.subinterface == subinterface and p.vrf == vrf),
        None,
    )
    if proposta is None:
        raise HTTPException(status_code=404, detail="Proposta não encontrada.")
    perfis = {
        "ipv4": {"import_profile_id": import_ipv4, "export_profile_id": export_ipv4},
        "ipv6": {"import_profile_id": import_ipv6, "export_profile_id": export_ipv6},
    }
    return schemas.FidelidadeOut(
        device_id=device_id, subinterface=subinterface,
        diferencas=[
            schemas.DiferencaOut(contexto=d.contexto, sobrando=list(d.sobrando),
                                 faltando=list(d.faltando),
                                 nao_gerenciado=list(d.nao_gerenciado),
                                 explicacao=d.explicacao, exige_ciente=d.exige_ciente)
            for d in conferir_fidelidade(session, proposta, perfis=perfis)
        ],
    )


@router.post("/adopt", response_model=schemas.AdocaoOut, status_code=201)
def adotar(payload: schemas.AdocaoIn, session: SessionDep, actor: ActorDep):
    """Grava a cadeia de uma proposta na SoT. Nada vai ao equipamento."""
    try:
        resultado = listar_propostas(session, payload.device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    proposta = next(
        (p for p in resultado.propostas
         if p.subinterface == payload.subinterface and p.vrf == payload.vrf),
        None,
    )
    if proposta is None:
        raise HTTPException(
            status_code=404,
            detail="Proposta não encontrada: ela pode ter sido adotada por outra pessoa.",
        )
    try:
        circuit_id = adotar_proposta(session, proposta=proposta, revisao=payload, actor=actor.nome)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schemas.AdocaoOut(circuit_id=circuit_id)
```

Acrescente `ConflictError` ao import de `domain.services.errors` (hoje ele importa
`NotFoundError`), e `conferir_fidelidade` e `adotar_proposta` ao import dos serviços.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_discovery_adopt_api.py tests/api/test_discovery_api.py -q`
Expected: PASS em todos

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/api/routers/discovery.py src/gerenet/domain/schemas.py tests/api/test_discovery_adopt_api.py
git commit -m "feat(adocao): POST /adopt e a conferência sob demanda"
```

---

### Task 7: O CLI

**Files:**
- Modify: `src/gerenet/cli/discovery.py`
- Modify: `tests/cli/test_discovery_cli.py`

**Interfaces:**
- Consumes: `adotar_proposta`, `conferir_fidelidade`
- Produces: `gerenet discovery adopt <device> <peer> --json <arquivo> [--ciente]`

- [ ] **Step 1: Write the failing test**

```python
def test_adopt_com_json_grava_o_circuito(db_session, tmp_path) -> None:
    """O caminho de quem prefere resolver as pendências num arquivo a abrir a tela."""
    dev = _ambiente(db_session, tmp_path)  # helper do próprio arquivo
    json_revisao = tmp_path / "revisao.json"
    json_revisao.write_text(json.dumps({
        "device_id": dev.id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-CLI-1001", "access_device_id": dev.id, "access_port": "GE0/0/1",
        "organizacao_nova": {"name": "Cliente CLI", "kind": "downstream", "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": True,
    }), encoding="utf-8")
    r = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                "--json", str(json_revisao)])
    assert r.exit_code == 0, r.output
    assert "ADOC-CLI-1001" in r.output


def test_adopt_sem_ciente_onde_exige_sai_com_erro(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    json_revisao = tmp_path / "revisao.json"
    json_revisao.write_text(json.dumps({
        "device_id": dev.id, "vrf": None, "subinterface": "Eth-Trunk127.1001",
        "circuit_code": "ADOC-CLI-SEM-CIENTE", "access_device_id": dev.id,
        "access_port": "GE0/0/1",
        "organizacao_nova": {"name": "Cliente CLI Sem Ciente", "kind": "downstream",
                             "asn": 64512},
        "sessoes": [{"afi": "ipv4"}, {"afi": "ipv6"}],
        "ciente": False,
    }), encoding="utf-8")
    r = runner.invoke(cli_app, ["discovery", "adopt", dev.name, "100.64.10.1",
                                "--json", str(json_revisao)])
    assert r.exit_code == 1
    assert "ciente" in r.output
```

Acrescente `import json` ao topo do arquivo de teste.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_discovery_cli.py -q -k adopt`
Expected: FAIL com `No such command 'adopt'`

- [ ] **Step 3: Implement**

Acrescente ao grupo em `src/gerenet/cli/discovery.py`:

```python
@app.command("adopt")
def adotar(
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
    peer: str = typer.Argument(..., help="Endereço remoto de um dos peers do enlace."),
    json_revisao: Path = typer.Option(..., "--json", help="Arquivo com a revisão (AdocaoIn)."),
) -> None:
    """Grava a cadeia da proposta na SoT. Nada é enviado ao equipamento."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            revisao = schemas.AdocaoIn.model_validate_json(json_revisao.read_text(encoding="utf-8"))
            resultado = listar_propostas(session, encontrado.id)
            proposta = next(
                (p for p in resultado.propostas
                 if any(c.remote_address == peer for c in p.candidatos)),
                None,
            )
            if proposta is None:
                typer.echo("Peer não está entre os candidatos.", err=True)
                raise typer.Exit(1)
            circuit_id = adotar_proposta(session, proposta=proposta, revisao=revisao, actor="cli")
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        except OSError as exc:
            typer.echo(f"Erro ao ler {json_revisao}: {exc}", err=True)
            raise typer.Exit(1) from exc
    typer.echo(f"Circuito {revisao.circuit_code} criado (id {circuit_id}).")
```

Acrescente `from pathlib import Path`, `from gerenet.domain import schemas`,
`adotar_proposta` e `listar_propostas` aos imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cli/test_discovery_cli.py -q`
Expected: PASS em todos

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/cli/discovery.py tests/cli/test_discovery_cli.py
git commit -m "feat(adocao): discovery adopt no CLI, com a revisão em JSON"
```

---

### Task 8: A tela de revisão

É aqui que as pendências da parte 1 viram campos, e é a única superfície onde o `ciente` aparece.

**Files:**
- Create: `web/src/pages/DiscoveryAdopt.tsx`
- Modify: `web/src/pages/Discovery.tsx` (o botão Adotar, habilitado só para proposta adotável)
- Modify: `web/src/pages/Discovery.test.tsx`
- Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/help.ts`

**Interfaces:**
- Consumes: `GET /api/v1/discovery/fidelidade`, `POST /api/v1/discovery/adopt`, os tipos da parte 1
- Produces: o componente `AdocaoDialog`, montado pela página com `key` por proposta

- [ ] **Step 1: Add the types and hooks**

Em `web/src/api/types.ts`:

```ts
export interface DiscoveryDiferencaOut {
  contexto: string;
  sobrando: string[];
  faltando: string[];
  nao_gerenciado: string[];
  explicacao: string | null;
  exige_ciente: boolean;
}

export interface DiscoveryFidelidadeOut {
  device_id: number;
  subinterface: string | null;
  diferencas: DiscoveryDiferencaOut[];
}

export interface DiscoveryAdocaoIn {
  device_id: number;
  vrf: string | null;
  subinterface: string | null;
  circuit_code: string;
  access_device_id: number;
  access_port: string;
  edge_trunk: string | null;
  organizacao_id: number | null;
  organizacao_nova: { name: string; kind?: string; asn: number } | null;
  sessoes: { afi: string; import_profile_id: number | null; export_profile_id: number | null }[];
  ciente: boolean;
}
```

Em `web/src/api/hooks.ts`:

```ts
/** Os perfis entram na chave de propósito: trocar um `select` de perfil refaz a
 * conferência, porque o corpo da política de exportação muda com ele. */
export const useFidelidade = (
  deviceId: number,
  vrf: string | null,
  subinterface: string | null,
  perfis: Record<string, { import?: number; export?: number }> = {},
) =>
  useQuery({
    queryKey: ["fidelidade", deviceId, vrf, subinterface, perfis],
    queryFn: () => {
      const qs = new URLSearchParams({ device_id: String(deviceId) });
      if (vrf) qs.set("vrf", vrf);
      if (subinterface) qs.set("subinterface", subinterface);
      for (const [afi, p] of Object.entries(perfis)) {
        if (p.import) qs.set(`import_${afi}`, String(p.import));
        if (p.export) qs.set(`export_${afi}`, String(p.export));
      }
      return apiFetch<DiscoveryFidelidadeOut>(`/api/v1/discovery/fidelidade?${qs.toString()}`);
    },
    enabled: deviceId > 0 && subinterface !== null,
    retry: false,
  });

export function useAdotar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DiscoveryAdocaoIn) =>
      apiFetch<{ circuit_id: number }>("/api/v1/discovery/adopt", { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["discovery"] });
      void qc.invalidateQueries({ queryKey: ["circuits"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
```

- [ ] **Step 2: Write the failing test**

Acrescente a `web/src/pages/Discovery.test.tsx`:

```tsx
  it("o botão Adotar só aparece para proposta adotável", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByRole("button", { name: "Adotar" })).toBeInTheDocument();
  });

  it("a revisão pede o aceite quando a diferença muda o equipamento", async () => {
    mockFetchComFidelidade({ exigeCiente: true });
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Adotar" }));
    expect(await screen.findByText(/mudariam o equipamento/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adotar" })).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/ciente/i));
    expect(screen.getByRole("button", { name: "Adotar" })).toBeEnabled();
  });
```

`mockFetchComFidelidade` é um helper novo no arquivo: ele responde o `GET /fidelidade` com um
diff que tem ou não linha no grupo que muda, conforme o parâmetro. Escreva-o por extenso.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npm run test -- Discovery`
Expected: FAIL (botão inexistente)

- [ ] **Step 4: Write the component**

Crie `web/src/pages/DiscoveryAdopt.tsx`:

```tsx
import { useState } from "react";
import { ApiError } from "@/api/client";
import {
  useAdotar,
  useDevices,
  useFidelidade,
  useOrganizations,
  usePolicyProfiles,
} from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { help } from "@/help";
import type { DiscoveryPropostaOut } from "@/api/types";

/** A revisão de uma proposta (design §6). Montada pela página com `key` por
 * proposta, para o estado do formulário não vazar de uma para a outra. */
export function AdocaoDialog({
  proposta,
  onFechar,
}: {
  proposta: DiscoveryPropostaOut;
  onFechar: () => void;
}) {
  const { data: devices } = useDevices();
  const { data: organizacoes } = useOrganizations();
  const { data: policyProfiles } = usePolicyProfiles();
  const adotar = useAdotar();
  const [code, setCode] = useState(proposta.circuit_code_sugerido ?? "");
  const [acesso, setAcesso] = useState<number>(0);
  const [porta, setPorta] = useState("");
  const [trunk, setTrunk] = useState("");
  const [orgId, setOrgId] = useState<number>(proposta.organizacao_id ?? 0);
  const [orgNome, setOrgNome] = useState(proposta.organizacao_sugerida ?? "");
  const [ciente, setCiente] = useState(false);
  // Os perfis vêm ANTES da conferência: ela é refeita quando eles mudam, porque
  // o corpo da política de exportação depende do produto escolhido.
  const [perfis, setPerfis] = useState<Record<string, { import?: number; export?: number }>>({});
  const { data: fidelidade } = useFidelidade(
    proposta.device_id, proposta.vrf, proposta.subinterface, perfis,
  );

  const setPerfil = (afi: string, valores: { import?: number; export?: number }) =>
    setPerfis((atual) => ({ ...atual, [afi]: { ...atual[afi], ...valores } }));

  const diferencas = fidelidade?.diferencas ?? [];
  const mudam = diferencas.filter((d) => d.exige_ciente);
  const naoGerenciadas = diferencas.filter((d) => !d.exige_ciente && d.nao_gerenciado.length > 0);
  const faltaPreencher = code === "" || acesso === 0 || porta === "";
  const podeAdotar =
    !faltaPreencher && (mudam.length === 0 || ciente) && !adotar.isPending;

  return (
    <Modal aberto titulo={`Adotar VLAN ${proposta.vid ?? "—"}`} onFechar={onFechar}>
      <section>
        <h3>O que será gravado</h3>
        <ul>
          {proposta.candidatos.map((c) => (
            <li key={c.remote_address}>
              {c.remote_address} AS{c.asn_remote} ({c.classificacao})
            </li>
          ))}
          {proposta.prefixos.map((p) => (
            <li key={p.network}>
              {p.network} (ponta {p.ponta_local})
            </li>
          ))}
        </ul>
      </section>

      <FormField label="Código do circuito *">
        <input value={code} onChange={(e) => setCode(e.target.value)} />
      </FormField>
      <FormField label="Equipamento de acesso *" help={help("adocao.acesso")}>
        <select value={acesso} onChange={(e) => setAcesso(Number(e.target.value))}>
          <option value={0}>Selecione…</option>
          {(devices ?? []).map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </FormField>
      <FormField label="Porta de acesso *">
        <input value={porta} onChange={(e) => setPorta(e.target.value)} />
      </FormField>
      <FormField label="Trunk do edge">
        <input value={trunk} onChange={(e) => setTrunk(e.target.value)} />
      </FormField>
      <FormField label="Organização" help={help("adocao.organizacao")}>
        <select value={orgId} onChange={(e) => setOrgId(Number(e.target.value))}>
          <option value={0}>Criar a nova: {orgNome || "(informe o nome)"}</option>
          {(organizacoes ?? []).map((o) => (
            <option key={o.id} value={o.id}>{o.name} (AS{o.asn ?? "—"})</option>
          ))}
        </select>
      </FormField>
      {orgId === 0 && (
        <FormField label="Nome da organização nova">
          <input value={orgNome} onChange={(e) => setOrgNome(e.target.value)} />
        </FormField>
      )}

      {proposta.candidatos.map((c) => (
        <div key={c.afi}>
          <FormField label={`Perfil de importação (${c.afi})`}>
            <select
              value={perfis[c.afi]?.import ?? 0}
              onChange={(e) => setPerfil(c.afi, { import: Number(e.target.value) })}
            >
              <option value={0}>—</option>
              {(policyProfiles ?? []).filter((p) => p.direction === "import").map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </FormField>
          <FormField label={`Perfil de exportação (${c.afi})`}>
            <select
              value={perfis[c.afi]?.export ?? 0}
              onChange={(e) => setPerfil(c.afi, { export: Number(e.target.value) })}
            >
              <option value={0}>—</option>
              {(policyProfiles ?? []).filter((p) => p.direction === "export").map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </FormField>
        </div>
      ))}

      {mudam.length > 0 && (
        <section>
          <h3>Diferenças que mudariam o equipamento</h3>
          <ul>{mudam.flatMap((d) => d.sobrando.concat(d.faltando)).map((l) => <li key={l}>{l}</li>)}</ul>
          <label>
            <input type="checkbox" checked={ciente} onChange={(e) => setCiente(e.target.checked)} />
            Estou ciente destas diferenças
          </label>
        </section>
      )}
      {naoGerenciadas.length > 0 && (
        <section>
          <h3>O que a SoT não gerencia</h3>
          <ul>{naoGerenciadas.flatMap((d) => d.nao_gerenciado).map((l) => <li key={l}>{l}</li>)}</ul>
        </section>
      )}
      {diferencas.some((d) => d.contexto === "ensaio") && (
        <p role="alert">
          A comparação não pôde ser feita para esta proposta, e sem ela não há aceite que valha.
        </p>
      )}

      {adotar.error && (
        <p role="alert">
          {adotar.error instanceof ApiError ? adotar.error.message : "Falha ao adotar."}
        </p>
      )}
      <div className="dialog-actions">
        <button onClick={onFechar}>Cancelar</button>
        <button
          disabled={!podeAdotar}
          onClick={() =>
            adotar.mutate({
              device_id: proposta.device_id, vrf: proposta.vrf,
              subinterface: proposta.subinterface, circuit_code: code,
              access_device_id: acesso, access_port: porta,
              edge_trunk: trunk || null,
              organizacao_id: orgId > 0 ? orgId : null,
              organizacao_nova: orgId > 0 ? null : {
                name: orgNome, kind: "downstream",
                asn: proposta.candidatos[0]?.asn_remote ?? 0,
              },
              sessoes: proposta.candidatos.map((c) => ({
                afi: c.afi,
                import_profile_id: perfis[c.afi]?.import || null,
                export_profile_id: perfis[c.afi]?.export || null,
              })),
              ciente,
            })
          }
        >
          Adotar
        </button>
      </div>
    </Modal>
  );
}
```

Acrescente ao `help.ts` as três chaves que o componente usa: `adocao.acesso` ("De que switch e
porta o cliente chega: a configuração do edge não tem isso."), `adocao.organizacao` ("A
organização é casada pelo ASN do par; criar uma nova exige o nome.") e `adocao.ciente` ("As
diferenças listadas fariam o render mudar o equipamento. Marcar aqui registra que você
assumiu, e a decisão fica na auditoria."). O `npm run build` valida as chaves, porque
`HelpKey` é derivado do objeto.

- [ ] **Step 5: Wire it into the page**

Em `web/src/pages/Discovery.tsx`: o botão **Adotar** na coluna de ações, habilitado só quando
`p.veredito !== "nao_adotavel"`; e o dialog montado como
`{revisando && <AdocaoDialog key={revisando.vid ?? revisando.subinterface} proposta={revisando} onFechar={() => setRevisando(null)} />}`.

- [ ] **Step 6: Run the tests and the build**

Run: `cd web && npm run test -- Discovery`
Expected: PASS

Run: `cd web && npm run build && npm run lint`
Expected: sem erro

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "feat(adocao): a tela de revisão, com o diff e o ciente"
```

---

### Task 9: e2e e documentação

**Files:**
- Create: `web/e2e/discovery.spec.ts`
- Modify: `docs/wiki/descoberta.md`, `docs/runbook-validacao-ne8000.md`, `CLAUDE.md`, `README.md`

- [ ] **Step 1: Write the e2e**

Crie `web/e2e/discovery.spec.ts` seguindo o padrão dos outros fumos (o seed do
`web/e2e/setup.ts` e o `reuseExistingServer: false`): abrir `/discovery` pelo equipamento do
seed, conferir que há proposta, abrir a revisão, preencher o acesso, marcar o `ciente` se for
pedido, adotar, e conferir que o circuito aparece na lista de circuitos. Se o seed não tiver
um snapshot com configuração, acrescente-o ao `setup.ts` — e diga no relatório o que mexeu.

Run: `cd web && npm run test:e2e`
Expected: PASS

- [ ] **Step 2: Update the documentation**

Em `docs/wiki/descoberta.md`: sai o aviso de que a adoção não existe; entram o fluxo de
revisão, o que cada grupo do diff significa, quando o `ciente` é exigido e o que a adoção
grava. Em `docs/runbook-validacao-ne8000.md`: a validação passa a ter a adoção num equipamento
não crítico, com o rollback ao lado (uma CR de remoção do circuito adotado). Em `CLAUDE.md` e
no `README.md`: o bullet da frente passa a dizer as duas partes entregues.

- [ ] **Step 3: Commit**

```bash
git add web/e2e docs/wiki/descoberta.md docs/runbook-validacao-ne8000.md CLAUDE.md README.md
git commit -m "docs(adocao): wiki, runbook e estado do repositório da parte 2"
```

---

## Verificação final

- [ ] **Suíte completa:** `uv run pytest -q` sem falha (fora o flake conhecido do worker).
- [ ] **Lint:** `uv run ruff check src tests` sem erro.
- [ ] **Web:** `cd web && npm run build && npm run test` sem erro.
- [ ] **Sem migration:** confirmar que nenhuma migration foi criada nesta parte (ela grava nas tabelas existentes).
- [ ] **Sem segredo:** `grep -ri "cipher" src tests` não devolve valor nenhum.
- [ ] **Nada vai ao equipamento:** `grep -rn "connect_and_run\|netmiko" src/gerenet/domain/services/discovery.py src/gerenet/domain/services/ipam.py` não devolve nada.
- [ ] **A transação é uma só:** o teste do conflito de reserva prova que nada ficou gravado.
