# Descoberta e adoção de peers BGP — parte 1 (leitura) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ler o `display current-configuration` que já está salvo no snapshot de um equipamento e propor, sem escrever nada na Source of Truth, quais peers BGP daquele equipamento poderiam ser adotados na SoT, cada um com veredito, pendências e conflitos.

**Architecture:** Um parser novo lê a árvore da configuração e devolve objetos tipados. Um motor de descoberta, somente leitura, cruza o que a configuração tem com o que a SoT já conhece e monta, para cada peer desconhecido, a proposta da cadeia que nasceria (organização, site, circuito, reservas, sessão) junto com o que impede ou atrapalha a adoção. Uma conferência de fidelidade renderiza o que nasceria e compara com o bloco da configuração que o originou. As superfícies (API, CLI e página web) só mostram; a escrita é a parte 2.

**Tech Stack:** Python 3.13, SQLAlchemy 2 + Alembic, FastAPI, Typer, pytest; React + Vite + TypeScript com Vitest para a página.

**Spec:** `docs/superpowers/specs/2026-09-14-gerenet-descoberta-adocao-design.md`

## Global Constraints

- Idioma dos artefatos: **português (PT-BR)**. Comentários, docstrings, mensagens de erro, nomes de função de serviço e rótulos de UI em PT-BR; nomes de tabela, de rota HTTP e de tipo seguem o inglês do resto do repo.
- Toda escrita em objeto de rede passa pelos serviços de domínio existentes, que já auditam. A parte 1 não escreve em objeto de rede nenhum.
- Segredos nunca são lidos, gravados, logados ou exibidos. O valor de `password cipher` não entra em nenhuma estrutura, e qualquer linha de senha que apareça numa diferença de fidelidade sai mascarada.
- Nada é enviado ao equipamento. A descoberta lê apenas o que a coleta já gravou.
- Comandos de teste: `uv run pytest -q`, `uv run ruff check src tests`, `cd web && npm run build && npm run test`.
- A suíte completa leva cerca de 11 minutos. Durante o trabalho rode os módulos tocados; a suíte completa é para o checkpoint final.
- Baseline conhecido: `tests/api/test_actor_b2_routes.py::test_communities_aceita_cookie` e `tests/api/test_actor_sessao.py::test_visualizador_nao_escreve` falham na suíte completa e passam isolados. É pré-existente na main, não é regressão desta frente.
- Toda tabela nova entra na lista do `TRUNCATE` de `tests/conftest.py`, senão a suíte vaza estado entre testes.

## File Structure

**Criados:**

| Arquivo | Responsabilidade |
|---|---|
| `src/gerenet/automation/snapshots.py` | Ler o texto da configuração salva num snapshot |
| `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py` | Parser da árvore do `current-configuration` |
| `src/gerenet/automation/discovery.py` | Motor de descoberta: candidatos, classificação, proposta, conflitos, fidelidade |
| `src/gerenet/domain/services/discovery.py` | Ignorados (a única escrita da parte 1) |
| `src/gerenet/api/routers/discovery.py` | Endpoints de leitura e de ignorados |
| `src/gerenet/cli/discovery.py` | Grupo `gerenet discovery` |
| `web/src/pages/Discovery.tsx` | Página `/discovery` |
| `tests/automation/test_snapshots.py` | Testes do leitor de snapshot |
| `tests/automation/test_config_vrp.py` | Golden do parser e mascaramento |
| `tests/automation/test_discovery.py` | Motor, proposta e fidelidade |
| `tests/api/test_discovery_api.py` | Endpoints |
| `tests/cli/test_discovery_cli.py` | CLI |
| `web/src/pages/Discovery.test.tsx` | Página |

**Modificados:**

| Arquivo | Mudança |
|---|---|
| `src/gerenet/automation/removal.py` | Passa a importar `texto_backup` do módulo novo |
| `src/gerenet/domain/models.py` | `PONTA_LOCAL` e a coluna `ip_prefixes.ponta_local`; modelo de `discovery_ignored_peers` |
| `src/gerenet/domain/services/ipam.py` | `pontas_v4`/`pontas_v6` com orientação |
| `src/gerenet/automation/render.py` | Passa a orientação da linha reservada |
| `src/gerenet/api/routers/circuits.py` | Idem, na exposição das pontas |
| `src/gerenet/api/main.py` | Registra o router novo |
| `src/gerenet/cli/main.py` | Registra o grupo novo |
| `src/gerenet/domain/schemas.py` | Schemas de resposta da descoberta |
| `tests/conftest.py` | Tabela nova no `TRUNCATE` |
| `web/src/App.tsx`, `web/src/components/Layout.tsx`, `web/src/components/Icons.tsx`, `web/src/api/types.ts`, `web/src/api/hooks.ts` | Rota, item de menu, ícone, tipos e hooks |
| `docs/wiki/`, `docs/runbook-validacao-ne8000.md`, `CLAUDE.md`, `README.md` | Documentação |

**Fora deste plano (parte 2):** a reserva por valores reais no IPAM, a adoção transacional, o botão de adotar, o `adopt` do CLI, a sugestão por LLM e o fumo e2e.

---

### Task 1: Mover o leitor do texto da configuração

O `texto_backup` hoje mora em `automation/removal.py`, que o usa para decidir o que remover. A descoberta precisa do mesmo leitor, e importar de `removal` criaria uma dependência esquisita entre dois módulos que não têm relação. Ele sai para um módulo próprio e o `removal` passa a importar de lá.

**Files:**
- Create: `src/gerenet/automation/snapshots.py`
- Create: `tests/automation/test_snapshots.py`
- Modify: `src/gerenet/automation/removal.py` (o `texto_backup` local sai; entra o import)

**Interfaces:**
- Consumes: `gerenet.domain.models.DeviceSnapshot`
- Produces: `gerenet.automation.snapshots.texto_backup(snapshot: models.DeviceSnapshot | None) -> str`

- [ ] **Step 1: Write the failing test**

Crie `tests/automation/test_snapshots.py`:

```python
"""Leitura do texto da configuração salva num snapshot (spec §10)."""
from pathlib import Path

from gerenet.automation.snapshots import texto_backup
from gerenet.domain import models


def _snapshot(db_session, device, raw_files) -> models.DeviceSnapshot:
    snap = models.DeviceSnapshot(device_id=device.id, status="success", raw_files=raw_files)
    db_session.add(snap)
    db_session.commit()
    return snap


def test_snapshot_nulo_devolve_vazio() -> None:
    assert texto_backup(None) == ""


def test_sem_recurso_de_backup_devolve_vazio(db_session, edge_device) -> None:
    snap = _snapshot(db_session, edge_device, {"interfaces": []})
    assert texto_backup(snap) == ""


def test_arquivo_ausente_devolve_vazio(db_session, edge_device, tmp_path: Path) -> None:
    snap = _snapshot(db_session, edge_device, {"config_backup": [str(tmp_path / "nao-existe.txt")]})
    assert texto_backup(snap) == ""


def test_le_o_conteudo_do_arquivo(db_session, edge_device, tmp_path: Path) -> None:
    arquivo = tmp_path / "current.txt"
    arquivo.write_text("sysname NE8000\n#\n", encoding="utf-8")
    snap = _snapshot(db_session, edge_device, {"config_backup": [str(arquivo)]})
    assert texto_backup(snap) == "sysname NE8000\n#\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_snapshots.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'gerenet.automation.snapshots'`

- [ ] **Step 3: Write minimal implementation**

Crie `src/gerenet/automation/snapshots.py` movendo o corpo exato da função que hoje está em `removal.py`:

```python
"""Leitura do texto da configuração salva num snapshot (spec §10).

O coletor `config_backup` grava o `display current-configuration` como arquivo
em disco e anota o caminho em `device_snapshots.raw_files`. Este módulo é o
único lugar que sabe abrir isso, para não haver duas versões do mesmo leitor.
"""
from pathlib import Path

from gerenet.domain import models


def texto_backup(snapshot: models.DeviceSnapshot | None) -> str:
    """Texto do `display current-configuration` salvo no snapshot (ou "")."""
    if snapshot is None:
        return ""
    arquivos = (snapshot.raw_files or {}).get("config_backup", [])
    if not arquivos:
        return ""
    try:
        return Path(str(arquivos[0])).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
```

Em `src/gerenet/automation/removal.py`, apague a função `texto_backup` e o que ela deixou de precisar (`Path` sai do import se não for usado em outro ponto do arquivo), e acrescente o import:

```python
from gerenet.automation.snapshots import texto_backup
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_snapshots.py tests/automation/test_removal.py -q`
Expected: PASS nos dois arquivos

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`
Expected: sem erro

```bash
git add src/gerenet/automation/snapshots.py src/gerenet/automation/removal.py tests/automation/test_snapshots.py
git commit -m "refactor(discovery): leitor do texto da config sai para módulo próprio"
```

---

### Task 2: A orientação da ponta no modelo e nas funções de ponta

As pontas do par p2p não são armazenadas: a SoT guarda a rede e `pontas_v4`/`pontas_v6` decidem qual endereço é o local pela convenção do alocador. Um circuito legado cujo roteador está no endereço de cima não é representável, e é isso que esta tarefa resolve, com uma coluna que diz qual ponta é a local.

**Files:**
- Modify: `src/gerenet/domain/models.py` (a tupla `PONTA_LOCAL` e a coluna em `IpPrefix`)
- Modify: `src/gerenet/domain/services/ipam.py:81-100` (`pontas_v4` e `pontas_v6`)
- Create: `alembic/versions/<hash>_ponta_local_ip_prefixes.py`
- Test: `tests/domain/test_ipam.py` (acrescentar casos)

**Interfaces:**
- Consumes: `IpPrefix.ponta_local`
- Produces: `pontas_v4(network: str, ponta_local: str = "inferior") -> tuple[str, str]` e `pontas_v6(network: str, ponta_local: str = "inferior") -> tuple[str, str]`, ambos devolvendo `(local, remota)` na ordem que a orientação mandar

- [ ] **Step 1: Write the failing test**

Acrescente ao final de `tests/domain/test_ipam.py`:

```python
def test_pontas_v4_respeitam_ponta_superior() -> None:
    # /31: inferior .0, superior .1 — o circuito adotado pode ter o roteador em cima.
    assert pontas_v4("100.64.0.0/31", "superior") == ("100.64.0.1", "100.64.0.0")
    # /30: inferior .1, superior .2
    assert pontas_v4("100.64.0.0/30", "superior") == ("100.64.0.2", "100.64.0.1")


def test_pontas_v4_default_e_inferior() -> None:
    assert pontas_v4("100.64.0.0/31") == pontas_v4("100.64.0.0/31", "inferior")


def test_pontas_v6_respeitam_ponta_superior() -> None:
    rede = "2804:194C:1000::1100:73:0/126"
    inferior, superior = pontas_v6(rede, "inferior")[0], pontas_v6(rede, "superior")[0]
    assert inferior.endswith("::1100:73:1/126")
    assert superior.endswith("::1100:73:2/126")


def test_pontas_recusam_orientacao_invalida() -> None:
    with pytest.raises(ValidationError):
        pontas_v4("100.64.0.0/31", "lateral")
    with pytest.raises(ValidationError):
        pontas_v6("2804:194C:1000::1100:73:0/126", "lateral")
```

Confirme que `ValidationError` já está importado em `tests/domain/test_ipam.py`; se não estiver, acrescente `from gerenet.domain.services.errors import ValidationError`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_ipam.py -q -k ponta`
Expected: FAIL com `TypeError: pontas_v4() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Write minimal implementation**

Em `src/gerenet/domain/models.py`, junto das outras tuplas de domínio:

```python
# Orientação da ponta do par p2p (spec §7): qual dos dois endereços é o do
# roteador. `inferior` é a convenção do alocador; `superior` existe para o
# circuito adotado cujo lado local é o endereço de cima.
PONTA_LOCAL = ("inferior", "superior")
```

E em `IpPrefix`, depois de `kind`:

```python
    ponta_local: Mapped[str] = mapped_column(
        Enum(*PONTA_LOCAL, name="ponta_local"), default="inferior", nullable=False
    )
```

Em `src/gerenet/domain/services/ipam.py`, substitua as duas funções:

```python
def _valida_orientacao(ponta_local: str) -> None:
    if ponta_local not in PONTA_LOCAL:
        raise ValidationError(
            f"Orientação de ponta deve ser uma de {PONTA_LOCAL}: {ponta_local}."
        )


def pontas_v4(network: str, ponta_local: str = "inferior") -> tuple[str, str]:
    """Pontas local/remota de um enlace v4 (/31: .0/.1; /30: .1/.2).

    `ponta_local` diz qual das duas é a do roteador: `inferior` é a convenção do
    alocador e `superior` atende o circuito adotado cujo lado local é o
    endereço de cima.
    """
    _valida_orientacao(ponta_local)
    rede = ipaddress.ip_network(network, strict=True)
    base = int(rede.network_address)
    if rede.prefixlen == 31:
        inferior = str(ipaddress.IPv4Address(base))
        superior = str(ipaddress.IPv4Address(base + 1))
    elif rede.prefixlen == 30:
        inferior = str(ipaddress.IPv4Address(base + 1))
        superior = str(ipaddress.IPv4Address(base + 2))
    else:
        raise ValidationError(f"Enlace p2p v4 deve ser /30 ou /31: {network}.")
    return (inferior, superior) if ponta_local == "inferior" else (superior, inferior)


def pontas_v6(network: str, ponta_local: str = "inferior") -> tuple[str, str]:
    """Pontas local/remota de um /126 (rede +1/+2), com prefixo no retorno."""
    _valida_orientacao(ponta_local)
    rede = ipaddress.ip_network(network, strict=True)
    if rede.prefixlen != 126:
        raise ValidationError(f"Enlace p2p v6 deve ser /126: {network}.")
    base = int(rede.network_address)
    inferior = _preserva_caixa(network, str(ipaddress.IPv6Address(base + 1)))
    superior = _preserva_caixa(network, str(ipaddress.IPv6Address(base + 2)))
    local, remota = (inferior, superior) if ponta_local == "inferior" else (superior, inferior)
    return (f"{local}/126", f"{remota}/126")
```

Ajuste o import de `models` em `ipam.py` se `PONTA_LOCAL` não estiver acessível (o arquivo já importa `from gerenet.domain import models`; use `models.PONTA_LOCAL`).

- [ ] **Step 4: Gere a migration**

Run: `uv run alembic revision -m "ponta local do par p2p" --autogenerate`
Expected: arquivo novo em `alembic/versions/` com `op.add_column("ip_prefixes", ...)`.

Confira que o corpo ficou assim (ajuste se o autogenerate variar):

```python
def upgrade() -> None:
    """Orientação da ponta do par p2p (spec §7): default preserva o
    comportamento do alocador, que sempre escolhe o par com o local embaixo."""
    op.add_column(
        "ip_prefixes",
        sa.Column("ponta_local", sa.Enum("inferior", "superior", name="ponta_local"),
                  nullable=False, server_default="inferior"),
    )


def downgrade() -> None:
    op.drop_column("ip_prefixes", "ponta_local")
```

Aplique: `uv run alembic upgrade head`
Expected: sem erro

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_ipam.py tests/automation/test_rendering.py tests/api/test_circuits_api.py -q`
Expected: PASS (as chamadas existentes de uma posição continuam valendo pelo default)

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/domain/models.py src/gerenet/domain/services/ipam.py alembic/versions tests/domain/test_ipam.py
git commit -m "feat(discovery): orientação da ponta do par p2p no modelo e no ipam"
```

---

### Task 3: A orientação no render e na API de circuito

A coluna existe mas ninguém a lê, então um circuito com a ponta superior ainda renderiza o endereço errado. Esta tarefa faz os dois leitores das pontas respeitarem a linha.

**Files:**
- Modify: `src/gerenet/automation/render.py:91-107` (`_reserva`)
- Modify: `src/gerenet/api/routers/circuits.py:39-49`
- Test: `tests/automation/test_rendering.py`, `tests/api/test_circuits_api.py`

**Interfaces:**
- Consumes: `pontas_v4`/`pontas_v6` com orientação (Task 2)
- Produces: nada público novo; o comportamento passa a respeitar `IpPrefix.ponta_local`

- [ ] **Step 1: Write the failing tests**

Acrescente a `tests/automation/test_rendering.py` um teste que reserva um circuito e depois força a orientação para `superior`, conferindo que o endereço emitido é o de cima:

```python
def test_subinterface_usa_a_ponta_superior_quando_a_linha_diz(db_session) -> None:
    """Circuito adotado com o roteador no endereço de cima (spec §7)."""
    ambiente = _ambiente(db_session)          # helper já existente no arquivo
    circ = _circuito(db_session, ambiente)    # helper já existente no arquivo
    db_session.execute(
        update(models.IpPrefix).where(models.IpPrefix.circuit_id == circ.id).values(
            ponta_local="superior"
        )
    )
    db_session.commit()
    resultado = render_desejado(db_session, ambiente["dev"].id)
    linhas = [linha for bloco in resultado.blocos for linha in bloco.comandos]
    assert any(linha.startswith("ip address 10.0.0.1 ") for linha in linhas)
    assert not any(linha.startswith("ip address 10.0.0.0 ") for linha in linhas)
```

O bloco p2p do `_ambiente` de `test_rendering.py` é o que decide o endereço esperado; confira o valor real lendo o helper antes de escrever o assert, e use o endereço de cima do bloco que ele cria. Acrescente `from sqlalchemy import update` se faltar.

Acrescente a `tests/api/test_circuits_api.py`:

```python
def test_detail_expoe_pontas_na_orientacao_da_linha(client, db_session) -> None:
    ambiente = _ambiente_dual(db_session)     # helper já existente no arquivo
    db_session.execute(
        update(models.IpPrefix).where(models.IpPrefix.circuit_id == ambiente["circ_id"]).values(
            ponta_local="superior"
        )
    )
    db_session.commit()
    corpo = client.get(f"/api/v1/circuits/{ambiente['circ_id']}", headers=_auth()).json()
    assert corpo["ipv4_local"] == pontas_v4(ambiente["rede_v4"], "superior")[0]
    assert corpo["ipv6_local"] == pontas_v6(ambiente["rede_v6"], "superior")[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/automation/test_rendering.py::test_subinterface_usa_a_ponta_superior_quando_a_linha_diz tests/api/test_circuits_api.py::test_detail_expoe_pontas_na_orientacao_da_linha -q`
Expected: FAIL nos dois (o endereço emitido é o de baixo)

- [ ] **Step 3: Write minimal implementation**

Em `src/gerenet/automation/render.py`, dentro de `_reserva`, troque o mapa por versão para carregar também a orientação:

```python
    por_versao: dict[int, tuple[str, str]] = {
        ipaddress.ip_network(p.network).version: (p.network, p.ponta_local)
        for p in prefixos
    }
```

e ajuste os dois usos:

```python
    if 4 in por_versao and circuito.stack != "ipv6":
        rede_texto, orientacao = por_versao[4]
        rede = ipaddress.ip_network(rede_texto)
        ponta_local, _ = pontas_v4(rede_texto, orientacao)
        local_v4 = (ponta_local, str(rede.netmask))
    if 6 in por_versao:
        rede_texto, orientacao = por_versao[6]
        local_v6 = pontas_v6(rede_texto, orientacao)[0]  # "address/126" (ponta local)
```

Em `src/gerenet/api/routers/circuits.py`, o mesmo tratamento:

```python
    por_versao = {
        ipaddress.ip_network(linha.network).version: (linha.network, linha.ponta_local)
        for linha in linhas
    }
    pontas: dict[str, str | None] = {          # inalterado
        "ipv4_local": None,
        "ipv4_remote": None,
        "ipv6_local": None,
        "ipv6_remote": None,
    }
    if circ.stack in ("ipv4", "dual") and 4 in por_versao:
        rede, orientacao = por_versao[4]
        pontas["ipv4_local"], pontas["ipv4_remote"] = pontas_v4(rede, orientacao)
    if circ.stack in ("ipv6", "dual") and 6 in por_versao:
        rede, orientacao = por_versao[6]
        pontas["ipv6_local"], pontas["ipv6_remote"] = pontas_v6(rede, orientacao)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_rendering.py tests/api/test_circuits_api.py tests/automation/test_reconcile.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/automation/render.py src/gerenet/api/routers/circuits.py tests/automation/test_rendering.py tests/api/test_circuits_api.py
git commit -m "feat(discovery): render e API de circuito respeitam a orientação da ponta"
```

---

### Task 4: O parser da configuração

A configuração do VRP é uma árvore: o bloco `bgp <asn>` contém seções de família, e é dentro delas que vivem os peers; a interface é outro bloco, com `vlan-type` e os endereços dentro. TextFSM é orientado a linha e trata isso por transições de estado, o que aqui sai ilegível. Este parser lê linha a linha mantendo o contexto do bloco e devolve objetos tipados.

**A fixture é derivada.** O conteúdo abaixo foi montado a partir dos templates do próprio render (que é a forma exata que este sistema gera) mais as formas do §6, e está marcado como derivado, seguindo o precedente de `test_parse_interface_brief_standby_derivado`. Se você tiver um `display current-configuration` de um NE8000 real sanitizado, **use-o no lugar**: salve em `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt`, rode o parser, e ajuste o parser e os asserts do golden ao que o equipamento realmente emite. A validação contra o equipamento de verdade é o objetivo da §15 do spec, e quanto antes ela acontecer, melhor.

**Files:**
- Create: `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py`
- Create: `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt`
- Create: `tests/automation/test_config_vrp.py`

**Interfaces:**
- Consumes: nada
- Produces: `parse_config_vrp(texto: str) -> ConfigVrp`, com `ConfigVrp.peers: tuple[PeerConfig, ...]` e `ConfigVrp.subinterfaces: tuple[Subinterface, ...]`; `PeerConfig` com `address, afi, vrf, asn_local, asn_remote, descricao, tem_password, import_route_policy, export_route_policy, import_prefix_list, maximum_prefix, maximum_prefix_threshold, keepalive, holdtime, bfd, graceful_restart, shutdown, habilitado`; `Subinterface` com `nome, vid, qinq, descricao, mtu, enderecos_v4, enderecos_v6`

- [ ] **Step 1: Crie a fixture**

Crie `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt`:

```txt
#
sysname NE8000-SPO
#
interface Eth-Trunk127
 description CORE-SPO
 undo portswitch
#
interface Eth-Trunk127.1001
 vlan-type dot1q 1001
 description CLIENTE-ALFA
 ip address 100.64.10.0 255.255.255.254
 ipv6 enable
 ipv6 address 2804:194C:1000::1100:73:1 126
#
interface Eth-Trunk127.2001
 vlan-type dot1q 2001
 description CLIENTE-BETA
 ip address 100.64.10.5 255.255.255.254
#
interface Eth-Trunk127.3001
 vlan-type dot1q 3001
 description TRANSITO-GAMA
 ip address 100.64.10.2 255.255.255.254
#
interface LoopBack0
 ip address 10.0.0.1 255.255.255.255
#
bgp 65001
 router-id 10.0.0.1
 peer 10.0.0.9 as-number 65001
 peer 10.0.0.9 description RR-INTERNO
 peer 100.64.10.1 as-number 64512
 peer 100.64.10.1 description CLIENTE-ALFA
 peer 100.64.10.1 password cipher %^%#Kd8sLpQ2xR%^%#
 peer 100.64.10.1 timer keepalive 30 hold 90
 peer 100.64.10.1 route-policy RP-64512-IMPORT-V4 import
 peer 100.64.10.1 ip-prefix IP-PFX-64512-IN-V4 import
 peer 100.64.10.1 export route-policy IP-PFX-64512-EXPORT-V4
 peer 100.64.10.4 as-number 64514
 peer 100.64.10.4 description CLIENTE-BETA
 peer 100.64.10.4 shutdown
 peer 100.64.10.3 as-number 64501
 peer 100.64.10.3 description TRANSITO-GAMA
 peer 100.64.10.3 bfd enable
 peer 100.64.10.3 graceful-restart
 peer 2804:194C:1000::1100:73:2 as-number 64512
 peer 2804:194C:1000::1100:73:2 description CLIENTE-ALFA-V6
 ipv4-family unicast
  undo synchronization
  peer 10.0.0.9 enable
  peer 100.64.10.1 enable
  peer 100.64.10.1 maximum-prefix 100 80
  peer 100.64.10.4 enable
  peer 100.64.10.3 enable
 ipv6-family unicast
  peer 2804:194C:1000::1100:73:2 enable
  peer 2804:194C:1000::1100:73:2 maximum-prefix 50 80
 ipv4-family vpn-instance VPNA
  peer 10.99.0.1 as-number 64513
  peer 10.99.0.1 description CLIENTE-VRF
  peer 10.99.0.1 enable
#
return
```

Crie também uma fixture mínima para o mascaramento, `tests/fixtures/` não precisa dela: ela vai inline no teste, como o precedente de `test_parse_interface_brief_standby_derivado`.

- [ ] **Step 2: Write the failing test**

Crie `tests/automation/test_config_vrp.py`:

```python
"""Parser da árvore do `display current-configuration` do VRP."""
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.config_vrp import parse_config_vrp

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _por_endereco(config, endereco: str):
    return next(p for p in config.peers if p.address == endereco)


def test_golden_da_captura_derivada() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    assert len(config.peers) == 6
    assert {p.address for p in config.peers} == {
        "10.0.0.9", "100.64.10.1", "100.64.10.4", "100.64.10.3",
        "2804:194C:1000::1100:73:2", "10.99.0.1",
    }


def test_peer_do_downstream_completo() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    alfa = _por_endereco(config, "100.64.10.1")
    assert alfa.afi == "ipv4"
    assert alfa.vrf is None
    assert alfa.asn_local == 65001
    assert alfa.asn_remote == 64512
    assert alfa.descricao == "CLIENTE-ALFA"
    assert alfa.tem_password is True
    assert alfa.import_route_policy == "RP-64512-IMPORT-V4"
    assert alfa.export_route_policy == "IP-PFX-64512-EXPORT-V4"
    assert alfa.import_prefix_list == "IP-PFX-64512-IN-V4"
    assert alfa.keepalive == 30
    assert alfa.holdtime == 90
    assert alfa.maximum_prefix == 100
    assert alfa.maximum_prefix_threshold == 80
    assert alfa.habilitado is True


def test_peer_ipv6_tem_afi_do_endereco() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    alfa_v6 = _por_endereco(config, "2804:194C:1000::1100:73:2")
    assert alfa_v6.afi == "ipv6"
    assert alfa_v6.asn_remote == 64512
    assert alfa_v6.maximum_prefix == 50


def test_peer_interno_e_peer_desligado() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    assert _por_endereco(config, "10.0.0.9").asn_remote == 65001
    beta = _por_endereco(config, "100.64.10.4")
    assert beta.shutdown is True
    assert beta.habilitado is True


def test_peer_de_upstream_com_bfd_e_graceful_restart() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    gama = _por_endereco(config, "100.64.10.3")
    assert gama.bfd is True
    assert gama.graceful_restart is True


def test_peer_de_vrf_carrega_o_nome_da_vrf() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    vrf = _por_endereco(config, "10.99.0.1")
    assert vrf.vrf == "VPNA"
    assert vrf.asn_remote == 64513
    assert vrf.habilitado is True


def test_subinterfaces_com_vlan_e_enderecos() -> None:
    config = parse_config_vrp(FIXTURE.read_text(encoding="utf-8"))
    por_nome = {s.nome: s for s in config.subinterfaces}
    alfa = por_nome["Eth-Trunk127.1001"]
    assert alfa.vid == 1001
    assert alfa.qinq is False
    assert alfa.descricao == "CLIENTE-ALFA"
    assert alfa.enderecos_v4 == (("100.64.10.0", "255.255.255.254"),)
    assert alfa.enderecos_v6 == (("2804:194C:1000::1100:73:1", 126),)
    # A interface principal aparece, mas sem VLAN.
    assert por_nome["Eth-Trunk127"].vid is None
    assert por_nome["Eth-Trunk127"].enderecos_v4 == ()


def test_qinq_e_mtu() -> None:
    texto = (
        "interface Eth-Trunk127.3001\n"
        " vlan-type qinq 3001\n"
        " mtu 9214\n"
        " ip address 100.64.10.2 255.255.255.254\n"
    )
    (sub,) = parse_config_vrp(texto).subinterfaces
    assert sub.qinq is True
    assert sub.mtu == 9214


def test_o_valor_da_senha_nunca_aparece_no_resultado() -> None:
    """Mascaramento (§19): o parser registra que há senha, nunca o valor."""
    texto = "bgp 65001\n peer 100.64.10.1 as-number 64512\n peer 100.64.10.1 password cipher SEGREDO-XYZ\n"
    config = parse_config_vrp(texto)
    (peer,) = config.peers
    assert peer.tem_password is True
    assert "SEGREDO-XYZ" not in repr(config)


def test_config_vazia_nao_quebra() -> None:
    config = parse_config_vrp("")
    assert config.peers == ()
    assert config.subinterfaces == ()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_config_vrp.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'gerenet.automation.parsers.huawei_vrp.config_vrp'`

- [ ] **Step 4: Write the parser**

Crie `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py`:

```python
"""Parser do `display current-configuration` do VRP (spec §3).

Diferente dos parsers de `display`, que leem saída tabular em TextFSM, a
configuração é uma árvore: o bloco `bgp <asn>` contém seções de família e é
dentro delas que vivem os peers, e a interface carrega `vlan-type` e endereços.
Ler isso com TextFSM produz um template ilegível, então aqui a leitura é linha a
linha mantendo o contexto do bloco.

O valor de `password cipher` NUNCA é lido: o parser registra que existe senha e
segue (§19).
"""
import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class PeerConfig:
    address: str
    afi: str                      # do endereço: "ipv4" | "ipv6"
    vrf: str | None               # None = instância pública
    asn_local: int
    asn_remote: int | None
    descricao: str | None
    tem_password: bool
    import_route_policy: str | None
    export_route_policy: str | None
    import_prefix_list: str | None
    maximum_prefix: int | None
    maximum_prefix_threshold: int | None
    keepalive: int | None
    holdtime: int | None
    bfd: bool
    graceful_restart: bool
    shutdown: bool
    habilitado: bool


@dataclass(frozen=True)
class Subinterface:
    nome: str
    vid: int | None               # None na interface principal
    qinq: bool
    descricao: str | None
    mtu: int | None
    enderecos_v4: tuple[tuple[str, str], ...]
    enderecos_v6: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ConfigVrp:
    peers: tuple[PeerConfig, ...] = ()
    subinterfaces: tuple[Subinterface, ...] = ()


def _novo_peer(endereco: str, vrf: str | None, asn_local: int) -> dict:
    return {
        "address": endereco,
        "afi": "ipv6" if ":" in endereco else "ipv4",
        "vrf": vrf,
        "asn_local": asn_local,
        "asn_remote": None,
        "descricao": None,
        "tem_password": False,
        "import_route_policy": None,
        "export_route_policy": None,
        "import_prefix_list": None,
        "maximum_prefix": None,
        "maximum_prefix_threshold": None,
        "keepalive": None,
        "holdtime": None,
        "bfd": False,
        "graceful_restart": False,
        "shutdown": False,
        "habilitado": False,
    }


def _aplica_peer(reg: dict, resto: list[str], linha: str) -> None:
    """Aplica uma linha `peer <endereço> ...` ao registro acumulado."""
    if not resto:
        return
    if resto[0] == "as-number" and len(resto) >= 2:
        reg["asn_remote"] = int(resto[1])
    elif resto[0] == "description":
        reg["descricao"] = linha.split("description", 1)[1].strip()
    elif resto[0] == "password":
        # O valor (cipher) não é lido: só a presença interessa (§19).
        reg["tem_password"] = True
    elif resto[:2] == ["timer", "keepalive"] and len(resto) >= 3:
        reg["keepalive"] = int(resto[2])
        if "hold" in resto:
            reg["holdtime"] = int(resto[resto.index("hold") + 1])
    elif "route-policy" in resto and resto.index("route-policy") + 1 < len(resto):
        nome = resto[resto.index("route-policy") + 1]
        if "export" in resto:
            reg["export_route_policy"] = nome
        else:
            reg["import_route_policy"] = nome
    elif "ip-prefix" in resto and resto.index("ip-prefix") + 1 < len(resto):
        reg["import_prefix_list"] = resto[resto.index("ip-prefix") + 1]
    elif resto[0] == "maximum-prefix" and len(resto) >= 2:
        reg["maximum_prefix"] = int(resto[1])
        if len(resto) >= 3:
            reg["maximum_prefix_threshold"] = int(resto[2])
    elif resto[:2] == ["bfd", "enable"]:
        reg["bfd"] = True
    elif resto[0] == "graceful-restart":
        reg["graceful_restart"] = True
    elif resto[0] == "shutdown":
        reg["shutdown"] = True
    elif resto[0] == "enable":
        reg["habilitado"] = True


def _aplica_sub(reg: dict, linha: str) -> None:
    if linha.startswith("vlan-type dot1q "):
        reg["vid"] = int(linha.split()[-1])
    elif linha.startswith("vlan-type qinq "):
        reg["vid"] = int(linha.split()[-1])
        reg["qinq"] = True
    elif linha.startswith("description "):
        reg["descricao"] = linha.split(" ", 1)[1].strip()
    elif linha.startswith("mtu "):
        reg["mtu"] = int(linha.split()[1])
    elif linha.startswith("ip address ") and not linha.startswith("ip address 0.0.0.0"):
        partes = linha.split()
        reg["v4"].append((partes[2], partes[3]))
    elif linha.startswith("ipv6 address "):
        partes = linha.split()
        if "/" in partes[2]:
            endereco, prefixo = partes[2].split("/", 1)
            reg["v6"].append((endereco, int(prefixo)))


def _monta_sub(reg: dict) -> Subinterface:
    return Subinterface(
        nome=reg["nome"], vid=reg["vid"], qinq=reg["qinq"], descricao=reg["descricao"],
        mtu=reg["mtu"], enderecos_v4=tuple(reg["v4"]), enderecos_v6=tuple(reg["v6"]),
    )


def _monta_peer(reg: dict) -> PeerConfig:
    return PeerConfig(**reg)


def parse_config_vrp(texto: str) -> ConfigVrp:
    """Leem a configuração inteira e devolve peers e subinterfaces tipados.

    Regras de contexto: linha sem indentação abre bloco novo; dentro de
    `interface`, as linhas indentadas são sub-comandos; dentro de `bgp`, uma
    seção `ipvN-family unicast` traz os ajustes por família da instância pública
    e uma seção `ipvN-family vpn-instance <nome>` traz os peers daquela VRF.
    """
    peers: dict[tuple[str, str | None], dict] = {}
    subs: list[Subinterface] = []
    asn_bloco: int | None = None
    vrf_atual: str | None = None
    iface: dict | None = None

    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha == "#":
            continue
        indentado = bruta[:1] in (" ", "\t")

        if not indentado:
            if iface is not None:
                subs.append(_monta_sub(iface))
                iface = None
            asn_bloco = None
            vrf_atual = None
            if linha.startswith("interface "):
                iface = {"nome": linha.split(" ", 1)[1], "vid": None, "qinq": False,
                         "descricao": None, "mtu": None, "v4": [], "v6": []}
            elif linha.startswith("bgp "):
                asn_bloco = int(linha.split(" ", 1)[1].split()[0])
            continue

        if iface is not None:
            _aplica_sub(iface, linha)
            continue
        if asn_bloco is None:
            continue

        if linha.startswith(("ipv4-family vpn-instance ", "ipv6-family vpn-instance ")):
            vrf_atual = linha.split(" ", 2)[2].strip()
            continue
        if linha.endswith("-family unicast"):
            vrf_atual = None
            continue
        if linha.startswith("peer "):
            _, endereco, *resto = linha.split()
            try:
                ipaddress.ip_address(endereco)
            except ValueError:
                continue  # `peer <nome-de-grupo>` não é endereço: fora do escopo
            reg = peers.setdefault((endereco, vrf_atual), _novo_peer(endereco, vrf_atual, asn_bloco))
            _aplica_peer(reg, resto, linha)

    if iface is not None:
        subs.append(_monta_sub(iface))
    return ConfigVrp(peers=tuple(_monta_peer(r) for r in peers.values()), subinterfaces=tuple(subs))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_config_vrp.py -q`
Expected: PASS nos nove testes. Se algum assert do golden não bater, **não** ajuste o teste para o que o parser devolveu sem conferir contra a fixture: a fixture é a verdade, e o divergente é o parser.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/automation/parsers/huawei_vrp/config_vrp.py tests/automation/test_config_vrp.py tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt
git commit -m "feat(discovery): parser da árvore do current-configuration"
```

---

### Task 5: A lista de ignorados

O peer que o operador nunca vai adotar (iBGP com route reflector, peering de gerência) precisa de um lugar para ficar, senão a lista fica poluída e o operador aprende a não olhar para ela. Esta é a única tabela nova da frente, e a única escrita da parte 1.

**Files:**
- Modify: `src/gerenet/domain/models.py` (classe `DiscoveryIgnoredPeer`)
- Create: `alembic/versions/<hash>_discovery_ignorados.py`
- Create: `src/gerenet/domain/services/discovery.py`
- Modify: `tests/conftest.py` (a tabela nova no `TRUNCATE`)
- Test: `tests/domain/test_discovery_service.py`

**Interfaces:**
- Consumes: `models.Device`, `models.DiscoveryIgnoredPeer`
- Produces: `listar_ignorados(session, device_id: int) -> list[models.DiscoveryIgnoredPeer]`; `ignorar_candidato(session, *, device_id: int, vrf: str | None, afi: str, remote_address: str, motivo: str | None, actor: str) -> models.DiscoveryIgnoredPeer` (idempotente); `esquecer_ignorado(session, *, device_id: int, vrf: str | None, afi: str, remote_address: str, actor: str) -> None`

- [ ] **Step 1: Write the failing test**

Crie `tests/domain/test_discovery_service.py`:

```python
"""Lista de ignorados da descoberta (spec §11) — a única escrita da parte 1."""
import pytest

from gerenet.domain import models
from gerenet.domain.services.discovery import (
    esquecer_ignorado,
    ignorar_candidato,
    listar_ignorados,
)


def test_ignora_e_lista(db_session, edge_device) -> None:
    ignorar_candidato(
        db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
        remote_address="10.0.0.9", motivo="iBGP com route reflector", actor="cli",
    )
    linhas = listar_ignorados(db_session, edge_device.id)
    assert len(linhas) == 1
    assert linhas[0].remote_address == "10.0.0.9"
    assert linhas[0].motivo == "iBGP com route reflector"
    assert linhas[0].autor == "cli"


def test_ignorar_de_novo_e_idempotente(db_session, edge_device) -> None:
    for _ in range(2):
        ignorar_candidato(
            db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
            remote_address="10.0.0.9", motivo=None, actor="cli",
        )
    assert len(listar_ignorados(db_session, edge_device.id)) == 1


def test_ignorado_na_instancia_publica_e_distinto_do_da_vrf(db_session, edge_device) -> None:
    """NULL não colide em índice único no Postgres: a exclusividade da
    instância pública precisa de índice parcial próprio."""
    ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", motivo=None, actor="cli")
    ignorar_candidato(db_session, device_id=edge_device.id, vrf="VPNA", afi="ipv4",
                      remote_address="10.0.0.9", motivo=None, actor="cli")
    assert len(listar_ignorados(db_session, edge_device.id)) == 2


def test_esquecer_remove(db_session, edge_device) -> None:
    ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", motivo=None, actor="cli")
    esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", actor="cli")
    assert listar_ignorados(db_session, edge_device.id) == []


def test_esquecer_o_que_nao_existe_e_no_op(db_session, edge_device) -> None:
    esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", actor="cli")
    assert listar_ignorados(db_session, edge_device.id) == []


def test_audita_ignorar_e_esquecer(db_session, edge_device) -> None:
    ignorar_candidato(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", motivo="interno", actor="cli")
    esquecer_ignorado(db_session, device_id=edge_device.id, vrf=None, afi="ipv4",
                      remote_address="10.0.0.9", actor="cli")
    tipos = [e.tipo for e in db_session.scalars(
        __import__("sqlalchemy").select(models.AuditEvent).order_by(models.AuditEvent.id)
    )]
    assert "discovery.ignore" in tipos
    assert "discovery.unignore" in tipos
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_discovery_service.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'gerenet.domain.services.discovery'`

- [ ] **Step 3: Add the model**

Em `src/gerenet/domain/models.py`, no fim do arquivo:

```python
class DiscoveryIgnoredPeer(Base):
    """Peer que o operador decidiu não adotar (spec §11).

    A quádrupla é a mesma de `bgp_sessions` (device, VRF, família, endereço
    remoto). `vrf` NULL é a instância pública, e NULL não colide em índice
    único no Postgres, então a exclusividade da instância pública precisa de
    índice parcial próprio.
    """

    __tablename__ = "discovery_ignored_peers"

    __table_args__ = (
        Index("uq_discovery_ignored_vrf", "device_id", "vrf", "afi", "remote_address",
              unique=True, postgresql_where=text("vrf IS NOT NULL")),
        Index("uq_discovery_ignored_publico", "device_id", "afi", "remote_address",
              unique=True, postgresql_where=text("vrf IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    vrf: Mapped[str | None] = mapped_column(String(64))
    afi: Mapped[str] = mapped_column(Enum(*FAMILY, name="family"), nullable=False)
    remote_address: Mapped[str] = mapped_column(String(64), nullable=False)
    motivo: Mapped[str | None] = mapped_column(Text())
    autor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: Write the migration**

Run: `uv run alembic revision -m "descoberta: peers ignorados"`

Preencha:

```python
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    """Lista de ignorados (§11). O tipo `family` já existe (bgp_sessions.afi),
    por isso create_type=False."""
    op.create_table(
        "discovery_ignored_peers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("vrf", sa.String(length=64), nullable=True),
        sa.Column("afi", postgresql.ENUM("ipv4", "ipv6", name="family", create_type=False),
                  nullable=False),
        sa.Column("remote_address", sa.String(length=64), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("autor", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_discovery_ignored_vrf", "discovery_ignored_peers",
                    ["device_id", "vrf", "afi", "remote_address"], unique=True,
                    postgresql_where=sa.text("vrf IS NOT NULL"))
    op.create_index("uq_discovery_ignored_publico", "discovery_ignored_peers",
                    ["device_id", "afi", "remote_address"], unique=True,
                    postgresql_where=sa.text("vrf IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_discovery_ignored_publico", table_name="discovery_ignored_peers")
    op.drop_index("uq_discovery_ignored_vrf", table_name="discovery_ignored_peers")
    op.drop_table("discovery_ignored_peers")
```

Aplique: `uv run alembic upgrade head`

- [ ] **Step 5: Add the table to the test truncate**

Em `tests/conftest.py`, o `TRUNCATE` de `_limpa_tabelas` ganha `discovery_ignored_peers` logo depois de `bgp_prefix_authorizations`:

```python
            "TRUNCATE approvals, change_steps, change_requests, audit_events, user_sessions, users, job_runs, device_snapshots, vlans, ip_prefixes, circuits, contacts, organizations, sites, devices, credential_groups, bgp_sessions, bgp_session_communities, bgp_prefix_authorizations, discovery_ignored_peers, vsi_members, vsi_services, service_endpoints, l2vc_services, mpls_domain_members, mpls_domains, upstreams, upstream_circuits, upstream_communities, roas, irr_cache RESTART IDENTITY CASCADE"
```

- [ ] **Step 6: Write the service**

Crie `src/gerenet/domain/services/discovery.py`:

```python
"""Peers ignorados da descoberta (spec §11).

A lista guarda a quádrupla (device, VRF, família, endereço remoto) do peer que o
operador decidiu não adotar. O candidato adotado não precisa de linha aqui: ele
entra na SoT e sai da lista por consequência.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.domain import models
from gerenet.domain.audit import registrar


def listar_ignorados(session: Session, device_id: int) -> list[models.DiscoveryIgnoredPeer]:
    return list(session.scalars(
        select(models.DiscoveryIgnoredPeer)
        .where(models.DiscoveryIgnoredPeer.device_id == device_id)
        .order_by(models.DiscoveryIgnoredPeer.id)
    ))


def _busca(session: Session, *, device_id: int, vrf: str | None, afi: str, remote_address: str):
    stmt = select(models.DiscoveryIgnoredPeer).where(
        models.DiscoveryIgnoredPeer.device_id == device_id,
        models.DiscoveryIgnoredPeer.afi == afi,
        models.DiscoveryIgnoredPeer.remote_address == remote_address,
    )
    stmt = stmt.where(
        models.DiscoveryIgnoredPeer.vrf.is_(None) if vrf is None
        else models.DiscoveryIgnoredPeer.vrf == vrf
    )
    return session.scalars(stmt).first()


def ignorar_candidato(
    session: Session, *, device_id: int, vrf: str | None, afi: str,
    remote_address: str, motivo: str | None, actor: str,
) -> models.DiscoveryIgnoredPeer:
    """Marca o candidato como não adotar. Idempotente (§3.2)."""
    existente = _busca(session, device_id=device_id, vrf=vrf, afi=afi,
                       remote_address=remote_address)
    if existente is not None:
        return existente
    linha = models.DiscoveryIgnoredPeer(
        device_id=device_id, vrf=vrf, afi=afi, remote_address=remote_address,
        motivo=motivo, autor=actor,
    )
    session.add(linha)
    session.flush()
    registrar(session, tipo="discovery.ignore", ator=actor, objeto="discovery_ignored_peer",
              objeto_id=linha.id, antes=None,
              depois={"device_id": device_id, "vrf": vrf, "afi": afi,
                      "remote_address": remote_address, "motivo": motivo})
    session.commit()
    session.refresh(linha)
    return linha


def esquecer_ignorado(
    session: Session, *, device_id: int, vrf: str | None, afi: str,
    remote_address: str, actor: str,
) -> None:
    """Tira o candidato da lista. No-op quando não está lá."""
    existente = _busca(session, device_id=device_id, vrf=vrf, afi=afi,
                       remote_address=remote_address)
    if existente is None:
        return
    antes = {"device_id": device_id, "vrf": vrf, "afi": afi, "remote_address": remote_address,
             "motivo": existente.motivo}
    objeto_id = existente.id
    session.delete(existente)
    registrar(session, tipo="discovery.unignore", ator=actor,
              objeto="discovery_ignored_peer", objeto_id=objeto_id, antes=antes, depois=None)
    session.commit()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_discovery_service.py -q`
Expected: PASS nos seis testes

- [ ] **Step 8: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/domain/models.py src/gerenet/domain/services/discovery.py alembic/versions tests/conftest.py tests/domain/test_discovery_service.py
git commit -m "feat(discovery): lista de peers ignorados"
```

---

### Task 6: O motor de descoberta

O motor lê a configuração do snapshot mais recente, cruza com o que a SoT já conhece e devolve os candidatos com o palpite de classificação e o motivo. É somente leitura: nada aqui escreve em objeto de rede.

**Files:**
- Create: `src/gerenet/automation/discovery.py`
- Test: `tests/automation/test_discovery.py`

**Interfaces:**
- Consumes: `parse_config_vrp` (Task 4), `texto_backup` (Task 1), `listar_ignorados` (Task 5), `list_sessions`
- Produces: `listar_candidatos(session, device_id: int) -> ResultadoDescoberta`, onde `ResultadoDescoberta` tem `device_id: int`, `snapshot_id: int | None`, `aviso: str | None`, `candidatos: list[Candidato]` e `internos: list[Candidato]`; e `Candidato` tem `device_id, vrf, afi, remote_address, asn_remote, descricao, snapshot_id, classificacao, motivo`

- [ ] **Step 1: Write the failing test**

Crie `tests/automation/test_discovery.py`:

```python
"""Motor de descoberta: candidatos e classificação (spec §4–§5). Read-only."""
from pathlib import Path

from sqlalchemy import select

from gerenet.automation.discovery import listar_candidatos
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, OrganizationCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.discovery import ignorar_candidato
from gerenet.domain.services.organizations import create_organization
from gerenet.domain.services.sites import create_site, link_device

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _ambiente(db_session, *, asn=65001):
    """Equipamento com site e a configuração da fixture salva em disco."""
    site = create_site(db_session, SiteCreate(name="pop-desc", p2p_ipv4_block="100.64.10.0/24"),
                       actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc",
                                                 management_address="10.0.0.1", asn=asn),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    return dev


def _com_config(db_session, dev, tmp_path: Path):
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    snap = models.DeviceSnapshot(device_id=dev.id, status="success",
                                 raw_files={"config_backup": [str(arquivo)]})
    db_session.add(snap)
    db_session.commit()
    return snap


def test_sem_snapshot_avisa_e_nao_devolve_lista_vazia_muda(db_session) -> None:
    dev = _ambiente(db_session)
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.candidatos == []
    assert resultado.snapshot_id is None
    assert resultado.aviso is not None
    assert "configuração" in resultado.aviso


def test_todos_os_peers_desconhecidos_sao_candidatos(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert {p.remote_address for p in resultado.candidatos} == {
        "100.64.10.1", "100.64.10.4", "100.64.10.3",
        "2804:194c:1000::1100:73:2", "10.99.0.1",
    }


def test_peer_interno_vai_para_a_lista_separada(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert [p.remote_address for p in resultado.internos] == ["10.0.0.9"]
    assert resultado.internos[0].classificacao == "interno"
    assert "65001" in resultado.internos[0].motivo


def test_peer_que_casa_com_sessao_da_sot_nao_e_candidato(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-001", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.1" not in {p.remote_address for p in resultado.candidatos}


def test_sessao_desativada_conta_como_conhecida(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    circ = create_circuit(db_session, CircuitCreate(
        code="CIRC-DESC-002", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.BgpSession(
        circuit_id=circ.id, device_id=dev.id, afi="ipv4",
        local_address="100.64.10.0", remote_address="100.64.10.1",
        asn_local=65001, asn_remote=64512, admin_status=False,
    ))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.1" not in {p.remote_address for p in resultado.candidatos}


def test_ignorado_nao_e_candidato(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    ignorar_candidato(db_session, device_id=dev.id, vrf=None, afi="ipv4",
                      remote_address="100.64.10.4", motivo="cliente saiu", actor="cli")
    resultado = listar_candidatos(db_session, dev.id)
    assert "100.64.10.4" not in {p.remote_address for p in resultado.candidatos}


def test_classificacao_por_organizacao(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    create_organization(db_session, OrganizationCreate(name="Operadora Gama", asn=64501,
                                                       kind="operadora"), actor="cli")
    create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                        actor="cli")
    _com_config(db_session, dev, tmp_path)
    por_endereco = {p.remote_address: p for p in listar_candidatos(db_session, dev.id).candidatos}
    assert por_endereco["100.64.10.3"].classificacao == "upstream"
    assert "Operadora Gama" in por_endereco["100.64.10.3"].motivo
    assert por_endereco["100.64.10.1"].classificacao == "downstream"
    assert "Cliente Alfa" in por_endereco["100.64.10.1"].motivo


def test_sem_organizacao_fica_nao_confirmada(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    por_endereco = {p.remote_address: p for p in listar_candidatos(db_session, dev.id).candidatos}
    beta = por_endereco["100.64.10.4"]
    assert beta.classificacao == "downstream"
    assert "não confirmada" in beta.motivo


def test_snapshot_sem_config_devolve_aviso(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"interfaces": []}))
    db_session.commit()
    resultado = listar_candidatos(db_session, dev.id)
    assert resultado.candidatos == []
    assert resultado.aviso is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/automation/test_discovery.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'gerenet.automation.discovery'`

- [ ] **Step 3: Write the engine**

Crie `src/gerenet/automation/discovery.py`:

```python
"""Descoberta de peers: o que o equipamento tem e a SoT não conhece (spec §4–§5).

Somente leitura. O motor lê o `display current-configuration` já gravado no
snapshot, cruza com as sessões da SoT e a lista de ignorados, e devolve cada
peer desconhecido com o palpite de classificação e o motivo que o sustenta.
"""
import ipaddress
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from gerenet.automation.parsers.huawei_vrp.config_vrp import PeerConfig, parse_config_vrp
from gerenet.automation.snapshots import texto_backup
from gerenet.domain import models
from gerenet.domain.services.bgp_sessions import list_sessions
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.discovery import listar_ignorados

AVISO_SEM_CONFIG = (
    "O equipamento não tem coleta com a configuração salva. Colete antes de descobrir."
)


@dataclass(frozen=True)
class Candidato:
    device_id: int
    vrf: str | None
    afi: str
    remote_address: str
    asn_remote: int | None
    descricao: str | None
    snapshot_id: int
    classificacao: str          # "downstream" | "upstream"
    motivo: str


@dataclass
class ResultadoDescoberta:
    device_id: int
    snapshot_id: int | None
    aviso: str | None = None
    candidatos: list[Candidato] = field(default_factory=list)
    internos: list[Candidato] = field(default_factory=list)


def _normaliza(endereco: str) -> str:
    """Forma canônica do endereço: a config e a SoT podem escrever IPv6 em
    caixas diferentes, e a comparação da quádrupla não pode depender disso."""
    try:
        return str(ipaddress.ip_address(endereco))
    except ValueError:
        return endereco


def _snapshot_com_config(session: Session, device_id: int) -> models.DeviceSnapshot | None:
    """Snapshot mais recente que ainda tenha a configuração em disco.

    Uma coleta anterior a esta frente pode não trazer o recurso, então olhar só
    o último snapshot daria "sem configuração" com a configuração existindo.
    """
    snaps = session.scalars(
        select(models.DeviceSnapshot)
        .where(models.DeviceSnapshot.device_id == device_id)
        .order_by(models.DeviceSnapshot.id.desc())
        .limit(5)
    ).all()
    for snap in snaps:
        if texto_backup(snap).strip():
            return snap
    return None


def _conhecidos(session: Session, device_id: int) -> set[tuple[str | None, str, str]]:
    """Quádruplas (VRF, família, endereço remoto) que a SoT já tem (§4).

    Sessão desativada conta como conhecida: desativar é o único caminho, e
    tratar a desativada como descoberta faria a lista ressuscitar sozinha.
    """
    sessoes = list_sessions(session, device_id=device_id, include_disabled=True)
    if not sessoes:
        return set()
    vrf_do_circuito = {
        c.id: c.vrf
        for c in session.scalars(
            select(models.Circuit).where(
                models.Circuit.id.in_([s.circuit_id for s in sessoes])
            )
        )
    }
    return {
        (vrf_do_circuito.get(s.circuit_id), s.afi, _normaliza(s.remote_address))
        for s in sessoes
    }


def _organizacao_por_asn(session: Session, asn: int | None) -> models.Organization | None:
    if asn is None:
        return None
    return session.scalars(
        select(models.Organization).where(models.Organization.asn == asn)
    ).first()


def _classificar(
    session: Session, device: models.Device, peer: PeerConfig,
) -> tuple[str, str]:
    """Palpite de classificação e o motivo que o sustenta (spec §5).

    Só dois sinais existem. O texto da linha do peer não distingue downstream de
    upstream: `naming.rp_import`/`rp_export` dependem apenas do ASN do par e da
    família, e o render usa as mesmas funções nos dois casos. O que separa os
    dois vive dentro do bloco da route-policy, que este parser não lê.
    """
    if peer.asn_remote is not None and device.asn is not None and peer.asn_remote == device.asn:
        return ("interno", f"ASN remoto {peer.asn_remote} é o mesmo do equipamento: iBGP.")
    org = _organizacao_por_asn(session, peer.asn_remote)
    if org is not None:
        if org.kind == "operadora":
            return ("upstream", f"Organização {org.name} tem o ASN {peer.asn_remote} e é operadora.")
        return ("downstream", f"Organização {org.name} tem o ASN {peer.asn_remote}.")
    return ("downstream", "Sem organização cadastrada para o ASN: classificação não confirmada.")


def listar_candidatos(session: Session, device_id: int) -> ResultadoDescoberta:
    """Peers da configuração que a SoT não conhece (spec §4)."""
    device = get_device(session, device_id)
    snap = _snapshot_com_config(session, device.id)
    if snap is None:
        return ResultadoDescoberta(device_id=device.id, snapshot_id=None, aviso=AVISO_SEM_CONFIG)

    config = parse_config_vrp(texto_backup(snap))
    conhecidos = _conhecidos(session, device.id)
    ignorados = {
        (i.vrf, i.afi, _normaliza(i.remote_address))
        for i in listar_ignorados(session, device.id)
    }

    resultado = ResultadoDescoberta(device_id=device.id, snapshot_id=snap.id)
    for peer in config.peers:
        chave = (peer.vrf, peer.afi, _normaliza(peer.address))
        if chave in conhecidos or chave in ignorados:
            continue
        classificacao, motivo = _classificar(session, device, peer)
        candidato = Candidato(
            device_id=device.id, vrf=peer.vrf, afi=peer.afi,
            remote_address=_normaliza(peer.address), asn_remote=peer.asn_remote,
            descricao=peer.descricao, snapshot_id=snap.id,
            classificacao=classificacao, motivo=motivo,
        )
        if classificacao == "interno":
            resultado.internos.append(candidato)
        else:
            resultado.candidatos.append(candidato)
    return resultado
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_discovery.py -q`
Expected: PASS nos nove testes

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/automation/discovery.py tests/automation/test_discovery.py
git commit -m "feat(discovery): motor de descoberta com candidatos e classificação"
```

---

### Task 7: A proposta de adoção

Aqui os candidatos viram a cadeia que nasceria, agrupada por enlace, com o veredito e as listas de pendência e conflito. Pendência é o que depende de decisão humana e se resolve na revisão; conflito é o que impede e precisa ser resolvido fora.

**Files:**
- Modify: `src/gerenet/automation/discovery.py` (acrescenta a proposta)
- Test: `tests/automation/test_discovery.py` (acrescenta casos no fim)

**Interfaces:**
- Consumes: `listar_candidatos` (Task 6), `pontas_v4`/`pontas_v6`, `naming.rp_import`/`rp_export`, `list_policy_profiles`
- Produces: `listar_propostas(session, device_id) -> ResultadoPropostas` com `device_id`, `snapshot_id`, `aviso`, `propostas: list[Proposta]`; `Proposta` com `device_id, vrf, subinterface, vid, stack, vlan_mode, p2p_v4_len, organizacao_id, organizacao_sugerida, site_id, circuit_code_sugerido, vlans, prefixos, sessoes, candidatos, pendencias, conflitos` e a property `veredito`; `Pendencia` e `Conflito` com `tipo` e `descricao`

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/automation/test_discovery.py`:

```python
from gerenet.automation.discovery import listar_propostas


def _propostas(db_session, dev):
    return {p.vid: p for p in listar_propostas(db_session, dev.id).propostas}


def test_proposta_do_downstream_dual_monta_a_cadeia(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                        actor="cli")
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert alfa.stack == "dual"
    assert alfa.p2p_v4_len == 31
    assert alfa.vid == 1001
    assert alfa.vlans == [{"vid": 1001, "kind": "vlan", "family": None}]
    assert alfa.prefixos == [
        {"network": "100.64.10.0/31", "ponta_local": "inferior"},
        {"network": "2804:194C:1000::1100:73:0/126", "ponta_local": "inferior"},
    ]
    assert {s["afi"] for s in alfa.sessoes} == {"ipv4", "ipv6"}
    assert alfa.site_id is not None


def test_ponta_superior_do_cliente_beta(db_session, tmp_path) -> None:
    """`100.64.10.5` é a ponta de cima do /31 `100.64.10.4/31` (spec §7)."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    beta = _propostas(db_session, dev)[2001]
    assert beta.stack == "ipv4"
    assert beta.prefixos[0]["ponta_local"] == "superior"


def test_pendencias_obrigatorias_do_downstream(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    tipos = {p.tipo for p in alfa.pendencias}
    assert "organizacao_ausente" in tipos
    assert "acesso_desconhecido" in tipos
    assert "senha_nao_legivel" in tipos
    assert "perfil_indeterminado" in tipos
    assert alfa.organizacao_id is None
    assert alfa.organizacao_sugerida == "CLIENTE-ALFA"


def test_com_organizacao_cadastrada_a_pendencia_some(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Cliente Alfa", asn=64512),
                              actor="cli")
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert alfa.organizacao_id == org.id
    assert "organizacao_ausente" not in {p.tipo for p in alfa.pendencias}


def test_veredito_com_pendencia_e_nao_adotavel_com_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert alfa.veredito == "adotavel_com_pendencias"


def test_vlan_tomada_e_conflito(db_session, tmp_path) -> None:
    from gerenet.domain.schemas import CircuitCreate
    from gerenet.domain.services.circuits import create_circuit

    dev = _ambiente(db_session)
    org = create_organization(db_session, OrganizationCreate(name="Outro Cliente", asn=64999),
                              actor="cli")
    site = db_session.scalar(select(models.Site))
    outro = create_circuit(db_session, CircuitCreate(
        code="CIRC-TOMADO", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/9", edge_device_id=dev.id,
    ), actor="cli")
    db_session.add(models.Vlan(site_id=site.id, vid=1001, kind="vlan", circuit_id=outro.id))
    db_session.commit()
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "vlan_tomada" in {c.tipo for c in alfa.conflitos}
    assert alfa.veredito == "nao_adotavel"


def test_endereco_fora_de_par_p2p_e_conflito(db_session, tmp_path) -> None:
    """IX com sub-rede compartilhada não cabe no IPAM, que só conhece p2p."""
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.4001\n"
        " vlan-type dot1q 4001\n"
        " ip address 200.219.0.1 255.255.255.240\n"
        "#\n"
        "bgp 65001\n"
        " peer 200.219.0.2 as-number 64999\n"
        " peer 200.219.0.2 description PEER-IX\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert "enlace_nao_p2p" in {c.tipo for c in prop.conflitos}


def test_endereco_sem_subinterface_e_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "bgp 65001\n peer 100.64.99.1 as-number 64999\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    (prop,) = listar_propostas(db_session, dev.id).propostas
    assert "endereco_sem_subinterface" in {c.tipo for c in prop.conflitos}


def test_asn_divergente_do_cadastro_vira_pendencia(db_session, tmp_path) -> None:
    """A configuração diz `bgp 65001` e o cadastro do equipamento diz outro ASN."""
    dev = _ambiente(db_session, asn=65002)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    assert "asn_do_equipamento" in {p.tipo for p in alfa.pendencias}


def test_mesmo_asn_em_enlaces_diferentes_vira_pendencia(db_session, tmp_path) -> None:
    """Dois enlaces com o mesmo ASN podem ser um dual stack com VLAN separada
    (um circuito) ou dois circuitos: o sistema não decide, ele avisa."""
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.5001\n"
        " vlan-type dot1q 5001\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "interface Eth-Trunk127.5002\n"
        " vlan-type dot1q 5002\n"
        " ipv6 address 2804:194C:1000::1100:73:1 126\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " peer 2804:194C:1000::1100:73:2 as-number 64512\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    por_vid = _propostas(db_session, dev)
    assert "mesmo_asn_em_outro_enlace" in {p.tipo for p in por_vid[5001].pendencias}
    assert "mesmo_asn_em_outro_enlace" in {p.tipo for p in por_vid[5002].pendencias}
```

A conferência cruzada com a coleta, no mesmo arquivo:

```python
def _com_config_e_interfaces(db_session, dev, tmp_path: Path, *, vpn: str | None = None):
    """Snapshot com a config da fixture e o recurso `interfaces` correspondente.

    O `display ip interface brief` já vai em toda coleta (collectors.py) e é a
    única fonte da VRF a que o endereço pertence.
    """
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    snap = models.DeviceSnapshot(
        device_id=dev.id, status="success",
        raw_files={"config_backup": [str(arquivo)]},
        resources={"interfaces": [
            {"nome": "Eth-Trunk127.1001", "phy": "up", "protocolo": "up",
             "enderecos_v4": ["100.64.10.0/31"],
             "enderecos_v6": ["2804:194C:1000::1100:73:1/126"], "vpn": vpn},
            {"nome": "Eth-Trunk127.2001", "phy": "up", "protocolo": "up",
             "enderecos_v4": ["100.64.10.5/31"], "enderecos_v6": [], "vpn": vpn},
            {"nome": "Eth-Trunk127.3001", "phy": "up", "protocolo": "up",
             "enderecos_v4": ["100.64.10.2/31"], "enderecos_v6": [], "vpn": vpn},
        ]},
    )
    db_session.add(snap)
    db_session.commit()
    return snap


def test_coleta_concordando_nao_gera_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config_e_interfaces(db_session, dev, tmp_path)
    tipos = {c.tipo for p in listar_propostas(db_session, dev.id).propostas
             for c in p.conflitos}
    assert "endereco_fora_da_coleta" not in tipos
    assert "vrf_do_enlace_divergente" not in tipos


def test_vrf_divergente_entre_config_e_coleta_e_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config_e_interfaces(db_session, dev, tmp_path, vpn="VPNA")
    alfa = _propostas(db_session, dev)[1001]
    assert "vrf_do_enlace_divergente" in {c.tipo for c in alfa.conflitos}


def test_sem_o_recurso_de_interfaces_nada_e_conferido(db_session, tmp_path) -> None:
    """Ausência de dado não é divergência: coleta antiga sem o recurso passa."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    tipos = {c.tipo for p in listar_propostas(db_session, dev.id).propostas
             for c in p.conflitos}
    assert "interface_ausente_na_coleta" not in tipos


def test_interface_ausente_na_coleta_e_conflito(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(
        device_id=dev.id, status="success",
        raw_files={"config_backup": [str(arquivo)]},
        resources={"interfaces": [{"nome": "LoopBack0", "phy": "up", "protocolo": "up",
                                   "enderecos_v4": ["10.0.0.1/32"],
                                   "enderecos_v6": [], "vpn": None}]},
    ))
    db_session.commit()
    tipos = {c.tipo for p in listar_propostas(db_session, dev.id).propostas
             for c in p.conflitos}
    assert "interface_ausente_na_coleta" in tipos
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/automation/test_discovery.py -q`
Expected: FAIL com `ImportError: cannot import name 'listar_propostas'`

- [ ] **Step 3: Write the proposal**

Primeiro, acrescente estes dois imports ao topo de `src/gerenet/automation/discovery.py`, junto dos que já estão lá:

```python
from gerenet.automation import naming
from gerenet.domain.services.ipam import pontas_v4, pontas_v6
```

Depois acrescente o resto ao fim do módulo:

```python
_ENLACES_V4 = (30, 31)


@dataclass(frozen=True)
class Pendencia:
    tipo: str
    descricao: str


@dataclass(frozen=True)
class Conflito:
    tipo: str
    descricao: str


@dataclass
class Proposta:
    """A cadeia que nasceria para um enlace (spec §6)."""

    device_id: int
    vrf: str | None
    subinterface: str | None
    vid: int | None
    stack: str
    vlan_mode: str
    p2p_v4_len: int | None
    organizacao_id: int | None = None
    organizacao_sugerida: str | None = None
    site_id: int | None = None
    circuit_code_sugerido: str | None = None
    vlans: list[dict] = field(default_factory=list)
    prefixos: list[dict] = field(default_factory=list)
    sessoes: list[dict] = field(default_factory=list)
    candidatos: list[Candidato] = field(default_factory=list)
    pendencias: list[Pendencia] = field(default_factory=list)
    conflitos: list[Conflito] = field(default_factory=list)

    @property
    def veredito(self) -> str:
        if self.conflitos:
            return "nao_adotavel"
        if self.pendencias:
            return "adotavel_com_pendencias"
        return "adotavel"


@dataclass
class ResultadoPropostas:
    device_id: int
    snapshot_id: int | None
    aviso: str | None = None
    propostas: list[Proposta] = field(default_factory=list)


def _enlace(subs, afi: str, endereco_remoto: str):
    """(subinterface, rede, endereço local) do enlace que contém o peer.

    Só par p2p serve: v4 em /30 ou /31 e v6 em /126. Uma sub-rede compartilhada
    (IX, por exemplo) não tem representação no IPAM, que só conhece `p2p`.
    """
    alvo = ipaddress.ip_address(endereco_remoto)
    for sub in subs:
        if afi == "ipv4":
            candidatos = [(e, m) for e, m in sub.enderecos_v4]
        else:
            candidatos = [(e, p) for e, p in sub.enderecos_v6]
        for endereco, comprimento in candidatos:
            rede = ipaddress.ip_network(f"{endereco}/{comprimento}", strict=False)
            if afi == "ipv4" and rede.prefixlen not in _ENLACES_V4:
                continue
            if afi == "ipv6" and rede.prefixlen != 126:
                continue
            if alvo in rede:
                return sub, rede, endereco
    return None


def _orientacao(rede, endereco_local: str) -> str:
    """Qual ponta do par é o roteador (spec §7)."""
    if rede.version == 4:
        inferior = pontas_v4(str(rede), "inferior")[0]
    else:
        inferior = pontas_v6(str(rede), "inferior")[0].split("/")[0]
    return "inferior" if endereco_local == inferior else "superior"


def _sessao_de(peer: PeerConfig, candidato: Candidato, rede, orientacao: str) -> dict:
    """Campos da `bgp_sessions` que a configuração entrega."""
    if rede.version == 4:
        local = pontas_v4(str(rede), orientacao)[0]
    else:
        local = pontas_v6(str(rede), orientacao)[0].split("/")[0]
    return {
        "afi": candidato.afi,
        "local_address": local,
        "remote_address": candidato.remote_address,
        "asn_local": peer.asn_local,
        "asn_remote": peer.asn_remote,
        "descricao": peer.descricao,
        "maximum_prefix": peer.maximum_prefix,
        "maximum_prefix_threshold": peer.maximum_prefix_threshold,
        "keepalive": peer.keepalive,
        "holdtime": peer.holdtime,
        "bfd_enabled": peer.bfd,
        "graceful_restart": peer.graceful_restart,
        "shutdown": peer.shutdown,
    }
```

O resto do módulo, com as pendências, os conflitos e a montagem:

```python
def _acrescenta(destino: list, novas: list) -> None:
    """Sem repetir o mesmo item: o enlace dual tem dois candidatos, e nem o mesmo
    aviso nem o mesmo conflito fazem sentido duas vezes."""
    vistos = {(i.tipo, i.descricao) for i in destino}
    for item in novas:
        if (item.tipo, item.descricao) not in vistos:
            destino.append(item)
            vistos.add((item.tipo, item.descricao))


def _pendencia_de_politica(peer: PeerConfig, afi: str) -> Pendencia:
    """O produto (full, parcial, default) não sai do nome da route-policy.

    `naming.rp_import` e `naming.rp_export` dependem só do ASN do par e da
    família, então dois produtos diferentes geram o mesmo nome. O que o texto
    diz é se a política segue o padrão deste sistema, não qual produto aplica.
    """
    nomes = {n for n in (peer.import_route_policy, peer.export_route_policy) if n}
    padrao = (
        {naming.rp_import(peer.asn_remote, afi), naming.rp_export(peer.asn_remote, afi)}
        if peer.asn_remote is not None else set()
    )
    if nomes & padrao:
        return Pendencia(
            "perfil_indeterminado",
            "As route-policies seguem o padrão de nome deste sistema, mas o produto "
            "(full, parcial, default) não é recuperável do nome: escolha os perfis de "
            "importação e exportação na revisão.",
        )
    return Pendencia(
        "politica_fora_do_padrao",
        f"A política {sorted(nomes)[0]} não segue o padrão de nome deste sistema: "
        "escolha os perfis na revisão, sabendo que o render emitirá nomes novos.",
    )


def _pendencias_de(
    session: Session, device: models.Device, peer: PeerConfig, candidato: Candidato,
    *, vid: int | None,
) -> list[Pendencia]:
    """O que depende de decisão humana e se resolve na revisão (spec §6)."""
    pendencias: list[Pendencia] = []
    if _organizacao_por_asn(session, peer.asn_remote) is None:
        descricao = f"Cadastre a organização do ASN {peer.asn_remote}"
        if peer.descricao:
            descricao += f" (descrição no equipamento: {peer.descricao})"
        pendencias.append(Pendencia("organizacao_ausente", descricao + "."))
        pendencias.append(Pendencia(
            "classificacao_nao_confirmada",
            "Sem organização cadastrada para este ASN: confirme se é downstream ou upstream.",
        ))
    if candidato.classificacao == "downstream":
        pendencias.append(Pendencia(
            "acesso_desconhecido",
            "A configuração do edge não diz de que switch e porta o cliente chega: "
            "preencha o acesso na revisão.",
        ))
    if vid is not None and peer.asn_remote is not None:
        codigo = f"ADOC-{peer.asn_remote}-{vid}"
        if session.scalar(select(models.Circuit.id).where(models.Circuit.code == codigo)):
            pendencias.append(Pendencia(
                "codigo_em_uso",
                f"O código sugerido {codigo} já existe: escolha outro na revisão.",
            ))
    if peer.tem_password:
        pendencias.append(Pendencia(
            "senha_nao_legivel",
            "O equipamento tem senha de peer configurada e o valor não é legível "
            "(cipher do VRP). Cadastre o segredo no Vault e informe o caminho, ou "
            "aceite que a SoT não conhece a senha.",
        ))
    if peer.import_route_policy or peer.export_route_policy:
        pendencias.append(_pendencia_de_politica(peer, candidato.afi))
    if device.asn is not None and peer.asn_local != device.asn:
        pendencias.append(Pendencia(
            "asn_do_equipamento",
            f"O bloco `bgp {peer.asn_local}` difere do ASN {device.asn} cadastrado para "
            "o equipamento: confirme qual está certo.",
        ))
    return pendencias


def _conflitos_de(session, *, site_id, vid, rede, local, remoto) -> list[Conflito]:
    conflitos: list[Conflito] = []
    if site_id is None:
        conflitos.append(Conflito(
            "sem_site", "O equipamento não está vinculado a um site: o IPAM é por site."))
        return conflitos
    if vid is not None:
        tomada = session.scalar(
            select(models.Vlan.id).where(
                models.Vlan.site_id == site_id, models.Vlan.device_id.is_(None),
                models.Vlan.vid == vid, models.Vlan.status == "reservada",
            )
        )
        if tomada:
            conflitos.append(Conflito(
                "vlan_tomada",
                f"A VLAN {vid} já está reservada para outro circuito neste site.",
            ))
    if rede is not None:
        prefixo_tomado = session.scalar(
            select(models.IpPrefix.id).where(
                models.IpPrefix.site_id == site_id,
                models.IpPrefix.network == str(rede),
                models.IpPrefix.status == "reservada",
            )
        )
        if prefixo_tomado:
            conflitos.append(Conflito(
                "prefixo_tomado",
                f"O prefixo {rede} já está reservado para outro circuito neste site.",
            ))
    em_uso = session.scalar(
        select(models.BgpSession.id).where(
            models.BgpSession.local_address == local,
            models.BgpSession.remote_address == remoto,
            models.BgpSession.admin_status.is_(True),
        )
    )
    if em_uso:
        conflitos.append(Conflito(
            "par_em_uso",
            f"Já existe sessão ativa entre {local} e {remoto}.",
        ))
    return conflitos


def _conflitos_de_coleta(
    snap: models.DeviceSnapshot, sub, local: str, vrf: str | None,
) -> list[Conflito]:
    """Conferência cruzada com o `display ip interface brief` da mesma coleta.

    A configuração é a fonte primária, porque só ela tem a VLAN, o MTU e a
    relação de peer. A interface brief confirma o endereço e traz a VRF a que o
    endereço pertence, que o parser da configuração não lê. Ausência do recurso
    não é divergência: coleta antiga simplesmente não é conferida.
    """
    recursos = (snap.resources or {}).get("interfaces")
    if not recursos:
        return []
    linha = next((i for i in recursos if i.get("nome") == sub.nome), None)
    if linha is None:
        return [Conflito(
            "interface_ausente_na_coleta",
            f"A coleta não tem a interface {sub.nome}: confira se a configuração "
            "salva corresponde ao equipamento.",
        )]
    conflitos: list[Conflito] = []
    enderecos = {
        endereco.split("/")[0].lower()
        for endereco in (linha.get("enderecos_v4") or []) + (linha.get("enderecos_v6") or [])
    }
    if local.lower() not in enderecos:
        conflitos.append(Conflito(
            "endereco_fora_da_coleta",
            f"O endereço {local} que a configuração mostra em {sub.nome} não aparece "
            "no `display ip interface brief` da mesma coleta.",
        ))
    if (linha.get("vpn") or None) != (vrf or None):
        conflitos.append(Conflito(
            "vrf_do_enlace_divergente",
            f"A interface {sub.nome} está na VRF {linha.get('vpn') or 'pública'} e o "
            f"peer está em {vrf or 'instância pública'}: confirme qual é a certa.",
        ))
    return conflitos


def _marca_mesmo_asn(por_enlace: dict) -> None:
    """Dois enlaces com o mesmo ASN no mesmo equipamento: o sistema não decide se
    são um dual stack com VLAN separada (um circuito) ou dois circuitos; ele avisa
    para o operador escolher (spec §6)."""
    por_asn: dict[tuple[str | None, int | None], list[Proposta]] = {}
    for proposta in por_enlace.values():
        if not proposta.candidatos:
            continue
        asn = proposta.candidatos[0].asn_remote
        por_asn.setdefault((proposta.vrf, asn), []).append(proposta)
    for propostas in por_asn.values():
        if len(propostas) < 2:
            continue
        for proposta in propostas:
            _acrescenta(proposta.pendencias, [Pendencia(
                "mesmo_asn_em_outro_enlace",
                "Outro enlace deste equipamento tem o mesmo ASN remoto: confirme se são "
                "um dual stack com VLAN separada (um circuito) ou dois circuitos.",
            )])


def listar_propostas(session: Session, device_id: int) -> ResultadoPropostas:
    """A cadeia que nasceria para cada enlace com peer desconhecido (spec §6).

    O agrupamento é por enlace, ou seja por (VRF, VLAN): os peers v4 e v6 que
    dividem a mesma subinterface são **um** circuito dual stack, e não dois.
    Candidato sem enlace resolvido vira proposta órfã, com o conflito que explica
    o motivo: ele aparece para o operador, não some da tela.
    """
    descoberta = listar_candidatos(session, device_id)
    resultado = ResultadoPropostas(
        device_id=descoberta.device_id, snapshot_id=descoberta.snapshot_id,
        aviso=descoberta.aviso,
    )
    if descoberta.aviso is not None:
        return resultado

    device = get_device(session, descoberta.device_id)
    snap = session.get(models.DeviceSnapshot, descoberta.snapshot_id)
    config = parse_config_vrp(texto_backup(snap))

    por_enlace: dict[tuple[str | None, int | None], Proposta] = {}
    orfas: list[Proposta] = []

    for candidato in descoberta.candidatos:
        peer = next(
            p for p in config.peers
            if _normaliza(p.address) == candidato.remote_address and p.vrf == candidato.vrf
        )
        enlace = _enlace(config.subinterfaces, candidato.afi, candidato.remote_address)
        if enlace is None:
            proposta = Proposta(
                device_id=device.id, vrf=candidato.vrf, subinterface=None, vid=None,
                stack=candidato.afi, vlan_mode="unica", p2p_v4_len=None,
                site_id=device.site_id,
            )
            _acrescenta(proposta.conflitos, [Conflito(
                "endereco_sem_subinterface",
                f"Nenhuma subinterface do equipamento tem {candidato.remote_address} em "
                "um par p2p: sem o enlace não há VLAN nem prefixo a reservar.",
            )])
            orfas.append(proposta)
        else:
            sub, rede, local = enlace
            proposta = por_enlace.get((candidato.vrf, sub.vid))
            if proposta is None:
                proposta = Proposta(
                    device_id=device.id, vrf=candidato.vrf, subinterface=sub.nome,
                    vid=sub.vid, stack=candidato.afi, vlan_mode="unica",
                    p2p_v4_len=rede.prefixlen if rede.version == 4 else None,
                    site_id=device.site_id,
                    circuit_code_sugerido=f"ADOC-{candidato.asn_remote}-{sub.vid}",
                )
                if sub.vid is not None:
                    proposta.vlans.append({"vid": sub.vid, "kind": "vlan", "family": None})
                por_enlace[(candidato.vrf, sub.vid)] = proposta
            elif proposta.stack != candidato.afi:
                proposta.stack = "dual"
            orientacao = _orientacao(rede, local)
            proposta.prefixos.append({"network": str(rede), "ponta_local": orientacao})
            sessao = _sessao_de(peer, candidato, rede, orientacao)
            proposta.sessoes.append(sessao)
            _acrescenta(proposta.conflitos, _conflitos_de(
                session, site_id=device.site_id, vid=sub.vid, rede=rede,
                local=sessao["local_address"], remoto=candidato.remote_address,
            ))
            _acrescenta(proposta.conflitos, _conflitos_de_coleta(
                snap, sub, sessao["local_address"], candidato.vrf,
            ))

        proposta.candidatos.append(candidato)
        _acrescenta(proposta.pendencias, _pendencias_de(
            session, device, peer, candidato, vid=proposta.vid,
        ))
        org = _organizacao_por_asn(session, candidato.asn_remote)
        if org is not None:
            proposta.organizacao_id = org.id
        elif proposta.organizacao_sugerida is None:
            proposta.organizacao_sugerida = peer.descricao

    _marca_mesmo_asn(por_enlace)
    resultado.propostas = list(por_enlace.values()) + orfas
    return resultado

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_discovery.py -q`
Expected: PASS em todos (o arquivo acumula os testes das Tasks 6 e 7; devem passar vinte e dois)

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/automation/discovery.py tests/automation/test_discovery.py
git commit -m "feat(discovery): proposta de adoção com veredito, pendências e conflitos"
```

---

### Task 8: A conferência de fidelidade

A proposta só é segura se o que a SoT vai reproduzir for comparável com o que o equipamento já tem. Sem isso, adotar um peer cujo perfil ficou pendente cria um circuito que, na renderização seguinte, manda o equipamento mudar para um estado que ninguém pediu. Esta etapa roda o render de verdade sobre objetos transitórios e mostra a diferença.

**O ensaio é em transação desfeita, e isso é de propósito.** Os objetos são montados direto como modelos (sem passar pelos serviços, que commitam) e a transação é sempre desfeita no fim. Rodar o `render_desejado` de verdade, em vez de reimplementar a montagem dos comandos aqui, é o que garante que a conferência não divirja do que a adoção produziria: é o mesmo código de render.

**Files:**
- Modify: `src/gerenet/automation/discovery.py`
- Test: `tests/automation/test_discovery.py` (acrescenta casos no fim)

**Interfaces:**
- Consumes: `render_desejado`, `Proposta` (Task 7)
- Produces: `conferir_fidelidade(session, proposta: Proposta) -> list[Diferenca]`, com `Diferenca` tendo `contexto: str`, `sobrando: tuple[str, ...]` (o render produz e a configuração não tem) e `faltando: tuple[str, ...]` (a configuração tem e o render não produz)

- [ ] **Step 1: Write the failing tests**

```python
from gerenet.automation.discovery import conferir_fidelidade


def _texto_do_snapshot(db_session, dev) -> str:
    from gerenet.automation.snapshots import texto_backup
    from gerenet.domain import models

    snap = db_session.scalars(
        select(models.DeviceSnapshot).where(models.DeviceSnapshot.device_id == dev.id)
        .order_by(models.DeviceSnapshot.id.desc())
    ).first()
    return texto_backup(snap)


def test_fidelidade_aponta_a_politica_que_o_render_nao_reproduz(db_session, tmp_path) -> None:
    """O peer tem route-policy no equipamento e o perfil ficou pendente: o render
    não emite essa linha, e a conferência diz exatamente isso."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    diferencas = conferir_fidelidade(db_session, alfa)
    peer = next(d for d in diferencas if d.contexto == "peer")
    assert peer.sobrando == ()
    assert any("route-policy RP-64512-IMPORT-V4" in linha for linha in peer.faltando)


def test_fidelidade_do_peer_que_casa_com_o_render(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(
        "interface Eth-Trunk127.6001\n"
        " vlan-type dot1q 6001\n"
        " ip address 100.64.10.0 255.255.255.254\n"
        "#\n"
        "bgp 65001\n"
        " peer 100.64.10.1 as-number 64512\n"
        " ipv4-family unicast\n"
        "  peer 100.64.10.1 enable\n",
        encoding="utf-8",
    )
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    (prop,) = listar_propostas(db_session, dev.id).propostas
    peer = next(d for d in conferir_fidelidade(db_session, prop) if d.contexto == "peer")
    assert peer.sobrando == ()
    assert peer.faltando == ()


def test_fidelidade_mascara_a_linha_da_senha(db_session, tmp_path) -> None:
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    diferencas = conferir_fidelidade(db_session, alfa)
    linhas = [linha for d in diferencas for linha in d.faltando + d.sobrando]
    senha = [linha for linha in linhas if "password" in linha]
    assert senha, "a linha da senha deveria aparecer como diferença"
    assert all("cipher" not in linha for linha in senha)


def test_fidelidade_nao_grava_nada(db_session, tmp_path) -> None:
    """O ensaio cria objetos transitórios e desfaz: o banco fica como estava."""
    dev = _ambiente(db_session)
    _com_config(db_session, dev, tmp_path)
    alfa = _propostas(db_session, dev)[1001]
    antes = (
        db_session.query(models.Circuit).count(),
        db_session.query(models.BgpSession).count(),
        db_session.query(models.Vlan).count(),
        db_session.query(models.IpPrefix).count(),
    )
    conferir_fidelidade(db_session, alfa)
    depois = (
        db_session.query(models.Circuit).count(),
        db_session.query(models.BgpSession).count(),
        db_session.query(models.Vlan).count(),
        db_session.query(models.IpPrefix).count(),
    )
    assert antes == depois
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/automation/test_discovery.py -q -k fidelidade`
Expected: FAIL com `ImportError: cannot import name 'conferir_fidelidade'`

- [ ] **Step 3: Write the fidelity check**

Acrescente ao fim de `src/gerenet/automation/discovery.py`, com `from gerenet.automation.render import render_desejado` no topo:

```python
@dataclass(frozen=True)
class Diferenca:
    contexto: str                  # "peer" | "subinterface"
    sobrando: tuple[str, ...]      # o render produz e a configuração não tem
    faltando: tuple[str, ...]      # a configuração tem e o render não produz


def _contexto_interface(texto: str, nome: str) -> set[str]:
    linhas: set[str] = set()
    dentro = False
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or linha == "#":
            continue
        if not bruta[:1].isspace():
            dentro = linha == f"interface {nome}"
            continue
        if dentro:
            linhas.add(linha)
    return linhas


def _contexto_peer(texto: str, endereco: str) -> set[str]:
    """Todas as linhas `peer <endereço> ...`, venham do bloco do bgp ou da seção
    de família (a indentação do contexto não interessa à comparação)."""
    prefixo = f"peer {endereco} "
    linhas = {bruta.strip() for bruta in texto.splitlines() if bruta.strip().startswith(prefixo)}
    return {_mascara_senha(linha, endereco) for linha in linhas}


def _mascara_senha(linha: str, endereco: str) -> str:
    """A senha do VRP nunca é exibida, nem numa diferença (§19)."""
    if "password" in linha:
        return f"peer {endereco} password cipher <mascarado>"
    return linha


def _normaliza_linhas(linhas: list[str]) -> set[str]:
    """Compara por conjunto dentro do contexto: a ordem do render e a da
    configuração não é a mesma, e `undo ...` é negação de default, não ajuste."""
    saida: set[str] = set()
    for linha in linhas:
        texto = " ".join(linha.split())
        if not texto or texto.startswith("#") or texto.startswith("undo "):
            continue
        saida.add(texto)
    return saida


def _ensaio(session: Session, proposta: Proposta) -> dict:
    """Objetos transitórios com a forma do que a adoção criaria.

    Sem passar pelos serviços, que commitam: aqui nada pode virar escrito. O
    chamador desfaz a transação.
    """
    device = get_device(session, proposta.device_id)
    org_id = proposta.organizacao_id
    if org_id is None:
        org = models.Organization(
            name=f"ENSAIO-{device.name}-{proposta.vid}",
            asn=proposta.candidatos[0].asn_remote if proposta.candidatos else None,
        )
        session.add(org)
        session.flush()
        org_id = org.id
    circ = models.Circuit(
        code=f"ENSAIO-{device.name}-{proposta.vid}", organization_id=org_id,
        site_id=proposta.site_id or device.site_id, access_port="ensaio",
        edge_device_id=device.id, stack=proposta.stack, vlan_mode=proposta.vlan_mode,
        p2p_v4_len=proposta.p2p_v4_len or 31,
    )
    session.add(circ)
    session.flush()
    for vlan in proposta.vlans:
        session.add(models.Vlan(site_id=circ.site_id, vid=vlan["vid"], kind=vlan["kind"],
                                family=vlan["family"], circuit_id=circ.id))
    for prefixo in proposta.prefixos:
        session.add(models.IpPrefix(site_id=circ.site_id, network=prefixo["network"],
                                    kind="p2p", circuit_id=circ.id,
                                    ponta_local=prefixo["ponta_local"]))
    session.flush()
    sessoes = []
    for dados in proposta.sessoes:
        sessao = models.BgpSession(circuit_id=circ.id, device_id=device.id, **dados)
        session.add(sessao)
        sessoes.append(sessao)
    session.flush()
    return {"circuito": circ, "sessoes": sessoes}


def conferir_fidelidade(session: Session, proposta: Proposta) -> list[Diferenca]:
    """O que a SoT reproduziria × o que a configuração tem (spec §9).

    O ensaio roda o render de verdade e é desfeito no fim; conferir com uma
    reimplementação da montagem de comandos deixaria a conferência divergir do
    que a adoção produz.
    """
    sugestao = next((p for p in _candidatos_da(proposta)), None)
    if sugestao is None or proposta.site_id is None:
        return []
    snap = session.get(models.DeviceSnapshot, sugestao.snapshot_id)
    texto = texto_backup(snap)
    resultado: list[Diferenca] = []
    try:
        criados = _ensaio(session, proposta)
        render = render_desejado(session, proposta.device_id)
        ids_circuito = criados["circuito"].id
        ids_sessoes = {s.id for s in criados["sessoes"]}

        comando_peer = [
            linha for bloco in render.blocos
            if bloco.objeto == "session" and bloco.objeto_id in ids_sessoes
            for linha in bloco.comandos
        ]
        comando_sub = [
            linha for bloco in render.blocos
            if bloco.objeto == "circuit" and bloco.objeto_id == ids_circuito
            for linha in bloco.comandos
        ]
        for endereco in sorted(_enderecos_da(proposta)):
            esperado = _normaliza_linhas(
                [linha for linha in comando_peer if f"peer {endereco} " in f" {linha} "]
                or comando_peer
            )
            encontrado = _contexto_peer(texto, endereco)
            resultado.append(Diferenca(
                contexto="peer",
                sobrando=tuple(sorted(esperado - encontrado)),
                faltando=tuple(sorted(encontrado - esperado)),
            ))
        if proposta.subinterface is not None:
            esperado = _normaliza_linhas(comando_sub)
            encontrado = _contexto_interface(texto, proposta.subinterface)
            resultado.append(Diferenca(
                contexto="subinterface",
                sobrando=tuple(sorted(esperado - encontrado)),
                faltando=tuple(sorted(encontrado - esperado)),
            ))
    finally:
        session.rollback()
    return resultado


def _candidatos_da(proposta: Proposta) -> list[Candidato]:
    return list(proposta.candidatos)


def _enderecos_da(proposta: Proposta) -> set[str]:
    return {c.remote_address for c in proposta.candidatos}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/automation/test_discovery.py -q -k fidelidade`
Expected: PASS nos quatro testes

- [ ] **Step 5: Run the whole discovery module and lint**

Run: `uv run pytest tests/automation/test_discovery.py tests/automation/test_rendering.py -q`
Run: `uv run ruff check src tests`
Expected: PASS e sem erro de lint

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/discovery.py tests/automation/test_discovery.py
git commit -m "feat(discovery): conferência de fidelidade em ensaio de transação desfeita"
```

---

### Task 9: A API

**Files:**
- Modify: `src/gerenet/domain/schemas.py` (schemas no fim do arquivo)
- Create: `src/gerenet/api/routers/discovery.py`
- Modify: `src/gerenet/api/main.py` (registro do router)
- Test: `tests/api/test_discovery_api.py`

**Interfaces:**
- Consumes: `listar_propostas` e `conferir_fidelidade` (Tasks 7 e 8), `listar_ignorados`/`ignorar_candidato`/`esquecer_ignorado` (Task 5)
- Produces: `GET /api/v1/discovery?device_id=N`, `GET /api/v1/discovery/ignore?device_id=N`, `POST /api/v1/discovery/ignore`, `DELETE /api/v1/discovery/ignore`

- [ ] **Step 1: Write the failing test**

Crie `tests/api/test_discovery_api.py`:

```python
"""API da descoberta (spec §13). Somente leitura, mais a lista de ignorados."""
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
    site = create_site(db_session, SiteCreate(name="pop-desc-api",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc-api",
                                                 management_address="10.0.0.1", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return {"dev": dev, "site": site}


def test_lista_propostas(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    resposta = client.get(f"/api/v1/discovery?device_id={ambiente['dev'].id}", headers=_auth())
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["device_id"] == ambiente["dev"].id
    assert corpo["aviso"] is None
    por_vid = {p["vid"]: p for p in corpo["propostas"]}
    assert set(por_vid) == {1001, 2001, 3001}
    alfa = por_vid[1001]
    assert alfa["veredito"] == "adotavel_com_pendencias"
    assert alfa["stack"] == "dual"
    assert {p["tipo"] for p in alfa["pendencias"]} >= {
        "organizacao_ausente", "acesso_desconhecido", "senha_nao_legivel",
    }
    assert alfa["organizacao_sugerida"] == "CLIENTE-ALFA"


def test_device_sem_coleta_devolve_aviso(client, db_session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-sem-coleta"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-sem-coleta",
                                                 management_address="10.0.0.9", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    resposta = client.get(f"/api/v1/discovery?device_id={dev.id}", headers=_auth())
    assert resposta.status_code == 200
    assert resposta.json()["aviso"] is not None
    assert resposta.json()["propostas"] == []


def test_device_inexistente_e_404(client) -> None:
    assert client.get("/api/v1/discovery?device_id=9999", headers=_auth()).status_code == 404


def test_sem_autenticacao_e_401(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    assert client.get(f"/api/v1/discovery?device_id={ambiente['dev'].id}").status_code == 401


def test_ignorar_esquecer_e_relistar(client, db_session, tmp_path) -> None:
    ambiente = _ambiente(db_session, tmp_path)
    dev_id = ambiente["dev"].id
    corpo = {"device_id": dev_id, "afi": "ipv4", "remote_address": "100.64.10.3",
             "motivo": "trânsito já cadastrado"}
    criado = client.post("/api/v1/discovery/ignore", json=corpo, headers=_auth())
    assert criado.status_code == 201
    assert criado.json()["autor"] == "api"

    listados = client.get(f"/api/v1/discovery/ignore?device_id={dev_id}", headers=_auth()).json()
    assert [i["remote_address"] for i in listados] == ["100.64.10.3"]

    sem_ele = client.get(f"/api/v1/discovery?device_id={dev_id}", headers=_auth()).json()
    assert "100.64.10.3" not in {s["remote_address"] for p in sem_ele["propostas"]
                                 for s in p["candidatos"]}

    apagado = client.delete(
        f"/api/v1/discovery/ignore?device_id={dev_id}&afi=ipv4&remote_address=100.64.10.3",
        headers=_auth(),
    )
    assert apagado.status_code == 204
    assert client.get(f"/api/v1/discovery/ignore?device_id={dev_id}",
                      headers=_auth()).json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_discovery_api.py -q`
Expected: FAIL com 404 nas rotas novas

- [ ] **Step 3: Add the schemas**

No fim de `src/gerenet/domain/schemas.py`:

```python
class CandidatoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: int
    vrf: str | None
    afi: str
    remote_address: str
    asn_remote: int | None
    descricao: str | None
    snapshot_id: int
    classificacao: str
    motivo: str


class PendenciaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tipo: str
    descricao: str


class ConflitoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tipo: str
    descricao: str


class PropostaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: int
    vrf: str | None
    subinterface: str | None
    vid: int | None
    stack: str
    vlan_mode: str
    p2p_v4_len: int | None
    organizacao_id: int | None
    organizacao_sugerida: str | None
    site_id: int | None
    circuit_code_sugerido: str | None
    vlans: list[dict]
    prefixos: list[dict]
    sessoes: list[dict]
    candidatos: list[CandidatoOut]
    pendencias: list[PendenciaOut]
    conflitos: list[ConflitoOut]
    veredito: str


class DiscoveryOut(BaseModel):
    device_id: int
    snapshot_id: int | None
    aviso: str | None
    gerado_em: datetime
    propostas: list[PropostaOut]


class IgnorarIn(BaseModel):
    device_id: int
    vrf: str | None = None
    afi: str
    remote_address: str = Field(min_length=1, max_length=64)
    motivo: str | None = Field(default=None, max_length=255)


class IgnoradoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    vrf: str | None
    afi: str
    remote_address: str
    motivo: str | None
    autor: str
```

- [ ] **Step 4: Write the router**

Crie `src/gerenet/api/routers/discovery.py`:

```python
"""Descoberta de peers (spec §13): leitura da proposta e lista de ignorados.

O único caminho de escrita da parte 1 é a lista de ignorados; a adoção é a
parte 2 e mora no mesmo prefixo quando chegar.
"""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gerenet.api.deps import Actor, require_actor
from gerenet.automation.discovery import listar_propostas
from gerenet.db import get_db
from gerenet.domain import schemas
from gerenet.domain.services.devices import get_device
from gerenet.domain.services.discovery import (
    esquecer_ignorado,
    ignorar_candidato,
    listar_ignorados,
)
from gerenet.domain.services.errors import NotFoundError

router = APIRouter(
    prefix="/api/v1/discovery", tags=["discovery"],
    dependencies=[Depends(require_actor)],
)

SessionDep = Annotated[Session, Depends(get_db)]
ActorDep = Annotated[Actor, Depends(require_actor)]


@router.get("", response_model=schemas.DiscoveryOut)
def listar(session: SessionDep, device_id: int) -> schemas.DiscoveryOut:
    """Propostas de adoção dos peers que a SoT não conhece."""
    try:
        resultado = listar_propostas(session, device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return schemas.DiscoveryOut(
        device_id=resultado.device_id,
        snapshot_id=resultado.snapshot_id,
        aviso=resultado.aviso,
        gerado_em=datetime.now(UTC),
        propostas=[schemas.PropostaOut.model_validate(p) for p in resultado.propostas],
    )


@router.get("/ignore", response_model=list[schemas.IgnoradoOut])
def listar_os_ignorados(session: SessionDep, device_id: int) -> list:
    return [schemas.IgnoradoOut.model_validate(i) for i in listar_ignorados(session, device_id)]


@router.post("/ignore", response_model=schemas.IgnoradoOut, status_code=201)
def ignorar(payload: schemas.IgnorarIn, session: SessionDep, actor: ActorDep):
    """Marca o peer como não adotar. Idempotente."""
    get_device(session, payload.device_id)  # 404 antes de qualquer escrita
    return ignorar_candidato(
        session, device_id=payload.device_id, vrf=payload.vrf, afi=payload.afi,
        remote_address=payload.remote_address, motivo=payload.motivo, actor=actor.nome,
    )


@router.delete("/ignore", status_code=204)
def esquecer(
    session: SessionDep, actor: ActorDep, device_id: int, afi: str, remote_address: str,
    vrf: str | None = None,
) -> None:
    get_device(session, device_id)
    esquecer_ignorado(
        session, device_id=device_id, vrf=vrf, afi=afi, remote_address=remote_address,
        actor=actor.nome,
    )
```

Em `src/gerenet/api/main.py`, junto dos outros imports e registros:

```python
    app.include_router(discovery.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_discovery_api.py -q`
Expected: PASS nos cinco testes

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/api/routers/discovery.py src/gerenet/api/main.py src/gerenet/domain/schemas.py tests/api/test_discovery_api.py
git commit -m "feat(discovery): API de leitura da proposta e da lista de ignorados"
```

---

### Task 10: O CLI

**Files:**
- Create: `src/gerenet/cli/discovery.py`
- Modify: `src/gerenet/cli/main.py` (registro do grupo)
- Test: `tests/cli/test_discovery_cli.py`

**Interfaces:**
- Consumes: os mesmos serviços da Task 9
- Produces: `gerenet discovery list|show|ignore|unignore`

- [ ] **Step 1: Write the failing test**

Crie `tests/cli/test_discovery_cli.py`:

```python
"""CLI da descoberta (§13 do design)."""
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from gerenet.cli.main import app as cli_app
from gerenet.domain import models
from gerenet.domain.schemas import DeviceCreate, SiteCreate
from gerenet.domain.services.devices import create_device
from gerenet.domain.services.sites import create_site, link_device

runner = CliRunner()
FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt")


def _ambiente(db_session, tmp_path: Path) -> models.Device:
    site = create_site(db_session, SiteCreate(name="pop-desc-cli",
                                              p2p_ipv4_block="100.64.10.0/24"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne8000-desc-cli",
                                                 management_address="10.0.0.1", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    arquivo = tmp_path / "current.txt"
    arquivo.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    db_session.add(models.DeviceSnapshot(device_id=dev.id, status="success",
                                        raw_files={"config_backup": [str(arquivo)]}))
    db_session.commit()
    return dev


def test_list_mostra_veredito_e_classificacao(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "1001" in r.output
    assert "adotavel_com_pendencias" in r.output
    assert "100.64.10.1" in r.output
    assert "interno" in r.output  # o peer com o próprio ASN aparece na lista separada


def test_show_detalha_pendencias_e_conflitos(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, ["discovery", "show", dev.name, "100.64.10.1"])
    assert r.exit_code == 0, r.output
    assert "organizacao_ausente" in r.output
    assert "senha_nao_legivel" in r.output


def test_ignore_e_unignore(db_session, tmp_path) -> None:
    dev = _ambiente(db_session, tmp_path)
    r = runner.invoke(cli_app, [
        "discovery", "ignore", dev.name, "100.64.10.4", "--motivo", "cliente saiu",
    ])
    assert r.exit_code == 0, r.output
    assert "100.64.10.4" not in runner.invoke(cli_app, ["discovery", "list", dev.name]).output

    r = runner.invoke(cli_app, ["discovery", "unignore", dev.name, "100.64.10.4"])
    assert r.exit_code == 0, r.output
    assert "100.64.10.4" in runner.invoke(cli_app, ["discovery", "list", dev.name]).output


def test_device_sem_coleta_avisa(db_session) -> None:
    site = create_site(db_session, SiteCreate(name="pop-cli-sem-coleta"), actor="cli")
    dev = create_device(db_session, DeviceCreate(name="ne-cli-sem-coleta",
                                                 management_address="10.0.0.9", asn=65001),
                        actor="cli")
    link_device(db_session, site.id, dev.id, actor="cli")
    r = runner.invoke(cli_app, ["discovery", "list", dev.name])
    assert r.exit_code == 0, r.output
    assert "Colete antes" in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_discovery_cli.py -q`
Expected: FAIL com `Error: No such command 'discovery'`

- [ ] **Step 3: Write the CLI**

Crie `src/gerenet/cli/discovery.py`:

```python
"""Descoberta de peers: o que o equipamento tem e a SoT não conhece (§13).

Somente leitura, mais a lista de ignorados. A adoção é a parte 2.
"""
import typer

from gerenet.automation.discovery import conferir_fidelidade, listar_propostas
from gerenet.db import get_session
from gerenet.domain.services import devices as dev_svc
from gerenet.domain.services.discovery import (
    esquecer_ignorado,
    ignorar_candidato,
    listar_ignorados,
)
from gerenet.domain.services.errors import GerenetError, NotFoundError

app = typer.Typer(help="Descoberta de peers na configuração do equipamento.")


def _device(session, device: str):
    if device.isdigit():
        try:
            return dev_svc.get_device(session, int(device))
        except NotFoundError:
            return None
    return next(
        (d for d in dev_svc.list_devices(session, include_disabled=True) if d.name == device),
        None,
    )


def _resolve(session, device: str):
    encontrado = _device(session, device)
    if encontrado is None:
        typer.echo("Equipamento não encontrado.", err=True)
        raise typer.Exit(1)
    return encontrado


def _imprime_propostas(propostas) -> None:
    for proposta in propostas:
        alvo = proposta.subinterface or "sem enlace"
        typer.echo(
            f"[{proposta.veredito}] VLAN {proposta.vid or '-'} ({alvo}) "
            f"stack {proposta.stack} código sugerido {proposta.circuit_code_sugerido or '-'}"
        )
        for candidato in proposta.candidatos:
            typer.echo(
                f"  peer {candidato.remote_address} AS{candidato.asn_remote} "
                f"({candidato.classificacao}) — {candidato.motivo}"
            )
        for pendencia in proposta.pendencias:
            typer.echo(f"  pendência: {pendencia.tipo} — {pendencia.descricao}")
        for conflito in proposta.conflitos:
            typer.echo(f"  conflito: {conflito.tipo} — {conflito.descricao}")


@app.command("list")
def listar(device: str = typer.Argument(..., help="ID ou nome do equipamento.")) -> None:
    """Mostra as propostas de adoção do equipamento."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = listar_propostas(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        if resultado.aviso:
            typer.echo(f"Aviso: {resultado.aviso}")
        _imprime_propostas(resultado.propostas)
        if not resultado.propostas:
            typer.echo("Nenhum peer fora da SoT.")
        ignorados = listar_ignorados(session, encontrado.id)
    if ignorados:
        typer.echo(f"Ignorados ({len(ignorados)}): " + ", ".join(i.remote_address for i in ignorados))


@app.command("show")
def mostrar(
    device: str = typer.Argument(..., help="ID ou nome do equipamento."),
    peer: str = typer.Argument(..., help="Endereço remoto do peer."),
) -> None:
    """Detalha uma proposta, com a conferência de fidelidade."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        try:
            resultado = listar_propostas(session, encontrado.id)
        except GerenetError as exc:
            typer.echo(f"Erro: {exc}", err=True)
            raise typer.Exit(1) from exc
        proposta = next(
            (p for p in resultado.propostas
             if any(c.remote_address == peer for c in p.candidatos)),
            None,
        )
        if proposta is None:
            typer.echo("Peer não está entre os candidatos.", err=True)
            raise typer.Exit(1)
        _imprime_propostas([proposta])
        for diferenca in conferir_fidelidade(session, proposta):
            typer.echo(f"  fidelidade {diferenca.contexto}:")
            for linha in diferenca.sobrando:
                typer.echo(f"    sobra no render: {linha}")
            for linha in diferenca.faltando:
                typer.echo(f"    falta no render: {linha}")


@app.command("ignore")
def ignorar(
    device: str = typer.Argument(...),
    peer: str = typer.Argument(..., help="Endereço remoto do peer."),
    motivo: str | None = typer.Option(None, "--motivo", help="Por que não adotar."),
    afi: str = typer.Option("ipv4", "--afi", help="ipv4 ou ipv6."),
    vrf: str | None = typer.Option(None, "--vrf", help="VRF; vazio é a instância pública."),
) -> None:
    """Marca o peer como não adotar."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        ignorar_candidato(
            session, device_id=encontrado.id, vrf=vrf, afi=afi, remote_address=peer,
            motivo=motivo, actor="cli",
        )
    typer.echo(f"{peer} marcado como ignorado.")


@app.command("unignore")
def designorar(
    device: str = typer.Argument(...),
    peer: str = typer.Argument(...),
    afi: str = typer.Option("ipv4", "--afi"),
    vrf: str | None = typer.Option(None, "--vrf"),
) -> None:
    """Tira o peer da lista de ignorados."""
    with get_session() as session:
        encontrado = _resolve(session, device)
        esquecer_ignorado(
            session, device_id=encontrado.id, vrf=vrf, afi=afi, remote_address=peer,
            actor="cli",
        )
    typer.echo(f"{peer} voltou a ser candidato.")
```

Em `src/gerenet/cli/main.py`, no bloco de imports `from gerenet.cli import (...)` acrescente `discovery`, e junto dos outros registros:

```python
app.add_typer(discovery.app, name="discovery", help="Descoberta de peers (migração de borda).")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/cli/test_discovery_cli.py -q`
Expected: PASS nos quatro testes

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src tests`

```bash
git add src/gerenet/cli/discovery.py src/gerenet/cli/main.py tests/cli/test_discovery_cli.py
git commit -m "feat(discovery): grupo discovery no CLI"
```

---

### Task 11: A página web

A página nasce do equipamento, como você pediu: o botão "Migrar" no detalhe do equipamento e na página de Reconciliar, com o `device_id` na URL.

**Files:**
- Create: `web/src/pages/Discovery.tsx`
- Create: `web/src/pages/Discovery.test.tsx`
- Modify: `web/src/App.tsx` (rota), `web/src/components/Layout.tsx` (item), `web/src/components/Icons.tsx` (ícone), `web/src/api/types.ts` (tipos), `web/src/api/hooks.ts` (hooks), `web/src/help.ts` (textos), `web/src/pages/DeviceDetail.tsx` e `web/src/pages/Reconcile.tsx` (botões)

**Interfaces:**
- Consumes: `GET/POST/DELETE /api/v1/discovery`
- Produces: rota `/discovery`

- [ ] **Step 1: Add the types**

No fim de `web/src/api/types.ts`:

```ts
export interface DiscoveryCandidatoOut {
  device_id: number;
  vrf: string | null;
  afi: string;
  remote_address: string;
  asn_remote: number | null;
  descricao: string | null;
  snapshot_id: number;
  classificacao: string;
  motivo: string;
}

export interface DiscoveryPendenciaOut {
  tipo: string;
  descricao: string;
}

export interface DiscoveryConflitoOut {
  tipo: string;
  descricao: string;
}

export interface DiscoveryPropostaOut {
  device_id: number;
  vrf: string | null;
  subinterface: string | null;
  vid: number | null;
  stack: string;
  vlan_mode: string;
  p2p_v4_len: number | null;
  organizacao_id: number | null;
  organizacao_sugerida: string | null;
  site_id: number | null;
  circuit_code_sugerido: string | null;
  vlans: { vid: number; kind: string; family: string | null }[];
  prefixos: { network: string; ponta_local: string }[];
  sessoes: Record<string, unknown>[];
  candidatos: DiscoveryCandidatoOut[];
  pendencias: DiscoveryPendenciaOut[];
  conflitos: DiscoveryConflitoOut[];
  veredito: string;
}

export interface DiscoveryOut {
  device_id: number;
  snapshot_id: number | null;
  aviso: string | null;
  gerado_em: string;
  propostas: DiscoveryPropostaOut[];
}

export interface DiscoveryIgnoradoOut {
  id: number;
  device_id: number;
  vrf: string | null;
  afi: string;
  remote_address: string;
  motivo: string | null;
  autor: string;
}
```

- [ ] **Step 2: Add the hooks**

Em `web/src/api/hooks.ts`, junto dos outros hooks, com `import type { DiscoveryOut, DiscoveryIgnoradoOut } from "@/api/types";` no bloco de imports que já existe:

```ts
export function useDiscovery(deviceId: number) {
  return useQuery({
    queryKey: ["discovery", deviceId],
    queryFn: () => apiFetch<DiscoveryOut>(`/api/v1/discovery?device_id=${deviceId}`),
    enabled: deviceId > 0,
    retry: false,
  });
}

export const useDiscoveryIgnorados = (deviceId: number) =>
  useQuery({
    queryKey: ["discovery-ignorados", deviceId],
    queryFn: () =>
      apiFetch<DiscoveryIgnoradoOut[]>(`/api/v1/discovery/ignore?device_id=${deviceId}`),
    enabled: deviceId > 0,
  });

export function useDiscoveryIgnorar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { device_id: number; vrf: string | null; afi: string; remote_address: string; motivo: string | null }) =>
      apiFetch<DiscoveryIgnoradoOut>("/api/v1/discovery/ignore", { method: "POST", body }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["discovery", v.device_id] });
      void qc.invalidateQueries({ queryKey: ["discovery-ignorados", v.device_id] });
    },
  });
}

export function useDiscoveryDesdesignorar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ device_id, vrf, afi, remote_address }: { device_id: number; vrf: string | null; afi: string; remote_address: string }) => {
      const qs = new URLSearchParams({ device_id: String(device_id), afi, remote_address });
      if (vrf) qs.set("vrf", vrf);
      return apiFetch<void>(`/api/v1/discovery/ignore?${qs.toString()}`, { method: "DELETE" });
    },
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["discovery", v.device_id] });
      void qc.invalidateQueries({ queryKey: ["discovery-ignorados", v.device_id] });
    },
  });
}
```

- [ ] **Step 3: Write the failing test**

Crie `web/src/pages/Discovery.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Discovery from "./Discovery";

const DEVICES = [{ id: 1, name: "ne8000-01" }];
const DISCOVERY = {
  device_id: 1,
  snapshot_id: 12,
  aviso: null,
  gerado_em: "2026-09-14T00:00:00Z",
  propostas: [
    {
      device_id: 1,
      vrf: null,
      subinterface: "Eth-Trunk127.1001",
      vid: 1001,
      stack: "dual",
      vlan_mode: "unica",
      p2p_v4_len: 31,
      organizacao_id: null,
      organizacao_sugerida: "CLIENTE-ALFA",
      site_id: 1,
      circuit_code_sugerido: "ADOC-64512-1001",
      vlans: [{ vid: 1001, kind: "vlan", family: null }],
      prefixos: [{ network: "100.64.10.0/31", ponta_local: "inferior" }],
      sessoes: [{ afi: "ipv4", remote_address: "100.64.10.1" }],
      candidatos: [
        {
          device_id: 1, vrf: null, afi: "ipv4", remote_address: "100.64.10.1",
          asn_remote: 64512, descricao: "CLIENTE-ALFA", snapshot_id: 12,
          classificacao: "downstream", motivo: "Sem organização cadastrada para o ASN: classificação não confirmada.",
        },
      ],
      pendencias: [{ tipo: "organizacao_ausente", descricao: "Cadastre a organização do ASN 64512." }],
      conflitos: [],
      veredito: "adotavel_com_pendencias",
    },
  ],
};

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const json = (corpo: unknown) =>
        new Response(JSON.stringify(corpo), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/devices") return json(DEVICES);
      if (url.startsWith("/api/v1/discovery/ignore")) return json([]);
      if (url.startsWith("/api/v1/discovery")) return json(DISCOVERY);
      return new Response(JSON.stringify({ detail: "Não encontrado." }), { status: 404 });
    }),
  );
}

function renderDiscovery(entrada: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entrada]}>
        <Discovery />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Discovery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("mostra a proposta com veredito, pendência e o peer", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    expect(await screen.findByText("adotavel_com_pendencias")).toBeInTheDocument();
    expect(screen.getByText("100.64.10.1")).toBeInTheDocument();
    expect(screen.getByText(/Cadastre a organização/)).toBeInTheDocument();
    expect(screen.getByText("ADOC-64512-1001")).toBeInTheDocument();
  });

  it("sem device_id pede para escolher um equipamento", async () => {
    mockFetch();
    renderDiscovery("/discovery");
    expect(await screen.findByText("Selecione um equipamento.")).toBeInTheDocument();
  });

  it("botão de não adotar chama a API", async () => {
    mockFetch();
    renderDiscovery("/discovery?device_id=1");
    await userEvent.click(await screen.findByRole("button", { name: "Não adotar" }));
    await userEvent.type(screen.getByLabelText("Motivo"), "cliente saiu");
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    const chamadas = vi.mocked(fetch).mock.calls as unknown as [string, RequestInit][];
    expect(chamadas.some((c) => c[1]?.method === "POST" && String(c[1]?.body).includes("100.64.10.1"))).toBe(true);
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd web && npm run test -- Discovery`
Expected: FAIL, o módulo `./Discovery` não existe

- [ ] **Step 5: Write the page**

Crie `web/src/pages/Discovery.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import {
  useDevices,
  useDiscovery,
  useDiscoveryIgnorados,
  useDiscoveryIgnorar,
  useDiscoveryDesdesignorar,
} from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import type { DiscoveryPropostaOut } from "@/api/types";

export default function Discovery() {
  const [params, setParams] = useSearchParams();
  const { data: devices } = useDevices();
  const deviceParam = Number(params.get("device_id") ?? 0);
  const [deviceSel, setDeviceSel] = useState<number>(deviceParam);
  const [detalhe, setDetalhe] = useState<DiscoveryPropostaOut | null>(null);
  const [ignorando, setIgnorando] = useState<DiscoveryPropostaOut | null>(null);
  const [motivo, setMotivo] = useState("");

  useEffect(() => {
    setDeviceSel(deviceParam);
  }, [deviceParam]);

  const { data, isLoading, error } = useDiscovery(deviceSel);
  const { data: ignorados } = useDiscoveryIgnorados(deviceSel);
  const ignorar = useDiscoveryIgnorar();
  const desdesignorar = useDiscoveryDesdesignorar();
  const propostas = data?.propostas ?? [];

  return (
    <main>
      <PageHeader
        titulo="Migrar"
        sub="O que a configuração do equipamento tem e a SoT ainda não conhece."
      />
      <FormField label="Equipamento" help="A leitura sai do snapshot mais recente com a configuração salva.">
        <select
          value={deviceSel}
          onChange={(e) => {
            const v = Number(e.target.value);
            setDeviceSel(v);
            setParams(v > 0 ? { device_id: String(v) } : {});
          }}
        >
          <option value={0}>Selecione…</option>
          {(devices ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </FormField>

      {deviceSel === 0 && <p>Selecione um equipamento.</p>}
      {data?.aviso && <p role="status">{data.aviso}</p>}
      {error && (
        <p role="alert">
          {error instanceof ApiError ? error.message : "Falha ao ler a configuração."}
        </p>
      )}

      <DataTable<DiscoveryPropostaOut>
        colunas={[
          { key: "vid", title: "VLAN", render: (p) => (p.vid === null ? "sem enlace" : p.vid) },
          { key: "subinterface", title: "Subinterface", render: (p) => p.subinterface ?? "—" },
          { key: "stack", title: "Stack", render: (p) => p.stack },
          {
            key: "peers",
            title: "Peers",
            render: (p) => p.candidatos.map((c) => c.remote_address).join(", "),
          },
          { key: "circuit_code_sugerido", title: "Código sugerido", render: (p) => p.circuit_code_sugerido ?? "—" },
          { key: "veredito", title: "Veredito", render: (p) => <StatusBadge estado={p.veredito} /> },
        ]}
        linhas={propostas}
        carregando={isLoading}
        vazio="Nenhum peer fora da SoT neste equipamento."
        acoes={(p) => (
          <div className="row-actions">
            <button onClick={() => setDetalhe(p)}>Detalhes</button>
            <button onClick={() => { setIgnorando(p); setMotivo(""); }}>Não adotar</button>
          </div>
        )}
      />

      {ignorados && ignorados.length > 0 && (
        <>
          <h2>Ignorados</h2>
          <ul>
            {ignorados.map((i) => (
              <li key={i.id}>
                {i.remote_address} — {i.motivo ?? "sem motivo"}{" "}
                <button
                  onClick={() =>
                    desdesignorar.mutate({
                      device_id: i.device_id, vrf: i.vrf, afi: i.afi,
                      remote_address: i.remote_address,
                    })
                  }
                >
                  Voltar a considerar
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <Modal
        aberto={detalhe !== null}
        titulo={detalhe ? `VLAN ${detalhe.vid} (${detalhe.subinterface})` : "Proposta"}
        onFechar={() => setDetalhe(null)}
      >
        {detalhe && (
          <div>
            {detalhe.candidatos.map((c) => (
              <p key={c.remote_address}>
                <strong>{c.remote_address}</strong> AS{c.asn_remote} ({c.classificacao}) — {c.motivo}
              </p>
            ))}
            <h3>Reservas</h3>
            <ul>
              {detalhe.prefixos.map((p) => (
                <li key={p.network}>
                  {p.network} (ponta {p.ponta_local})
                </li>
              ))}
            </ul>
            <h3>Pendências</h3>
            <ul>
              {detalhe.pendencias.map((p) => (
                <li key={p.tipo}>
                  {p.tipo}: {p.descricao}
                </li>
              ))}
            </ul>
            <h3>Conflitos</h3>
            <ul>
              {detalhe.conflitos.map((c) => (
                <li key={c.tipo}>
                  {c.tipo}: {c.descricao}
                </li>
              ))}
            </ul>
            <p>
              <Link to={`/devices/${detalhe.device_id}`}>Ver o equipamento</Link>
            </p>
          </div>
        )}
      </Modal>

      <Modal
        aberto={ignorando !== null}
        titulo="Não adotar este peer"
        onFechar={() => setIgnorando(null)}
      >
        <FormField label="Motivo">
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </FormField>
        <div className="dialog-actions">
          <button onClick={() => setIgnorando(null)}>Cancelar</button>
          <button
            className="danger"
            disabled={ignorar.isPending}
            onClick={() => {
              if (ignorando === null) return;
              const primeiro = ignorando.candidatos[0];
              ignorar.mutate(
                {
                  device_id: ignorando.device_id, vrf: primeiro.vrf, afi: primeiro.afi,
                  remote_address: primeiro.remote_address, motivo: motivo || null,
                },
                { onSuccess: () => setIgnorando(null) },
              );
            }}
          >
            Confirmar
          </button>
        </div>
      </Modal>
    </main>
  );
}
```

- [ ] **Step 6: Wire the route, the menu, the icon and the entry points**

Em `web/src/App.tsx`: acrescente `import Discovery from "@/pages/Discovery";` e, junto das outras rotas autenticadas:

```tsx
        <Route path="/discovery" element={<Discovery />} />
```

Em `web/src/components/Layout.tsx`, no grupo `operacao`, logo depois do item de Reconciliação:

```tsx
      { para: "/discovery", rotulo: "Migrar" },
```

Em `web/src/components/Icons.tsx`, acrescente a chave nova ao `ICONES_NAV`, depois de `"/reconcile"` (uma seta entrando numa caixa, no mesmo traço 1.8):

```tsx
  "/discovery": (
    <Svg>
      {R("M12 3v12")}
      {R("m7 10 5 5 5-5")}
      {R("M5 21h14")}
    </Svg>
  ),
```

Em `web/src/pages/DeviceDetail.tsx`, na seção "Inspeção", ao lado do link de Reconciliar:

```tsx
        <Link to={`/discovery?device_id=${device.id}`}>Migrar</Link>
```

Em `web/src/pages/Reconcile.tsx`, no topo, junto do link existente para o equipamento:

```tsx
      {deviceSel > 0 && <Link to={`/discovery?device_id=${deviceSel}`}>Migrar</Link>}
```

e acrescente `Link` ao import de `react-router-dom` se ainda não estiver lá (o arquivo importa `useSearchParams` de lá).

Em `web/src/help.ts`, um bloco novo com as chaves da página:

```ts
  // Discovery
  "discovery.equipamento": "A leitura sai do snapshot mais recente que tenha a configuração salva.",
  "discovery.veredito": "adotavel, adotavel_com_pendencias ou nao_adotavel — sempre com o motivo ao lado.",
```

- [ ] **Step 7: Run the tests and the build**

Run: `cd web && npm run test -- Discovery`
Expected: PASS nos três testes

Run: `cd web && npm run build`
Expected: sem erro de tipo (o `tsc -b` valida as chaves do `help`)

- [ ] **Step 8: Commit**

```bash
git add web/src
git commit -m "feat(web): página Migrar com as propostas de adoção"
```

---

### Task 12: Documentação e registro

**Files:**
- Create: `docs/wiki/descoberta.md`
- Modify: `docs/runbook-validacao-ne8000.md`, `CLAUDE.md`, `README.md`

- [ ] **Step 1: Write the wiki page**

Crie `docs/wiki/descoberta.md`:

```markdown
---
title: Migrar — descoberta de peers na configuração
secao: Operação
secao_order: 5
order: 4
---

# Migrar — descoberta de peers na configuração

Todo equipamento já coletado tem a configuração inteira guardada no snapshot. A
página **Migrar** lê essa configuração e mostra o que o equipamento tem e a SoT
ainda não conhece, para você decidir o que cadastrar.

## O que ela lê, e o que ela nunca lê

Ela lê só o que a coleta já trouxe: o `display current-configuration` e o
`display ip interface brief` do snapshot mais recente. Nenhum comando novo é
enviado ao equipamento, em nenhum momento.

O valor da senha de um peer (`password cipher`) nunca é lido. O parser registra
apenas que existe uma senha configurada, e isso aparece como pendência, porque o
`cipher` do VRP não é decifrável e a SoT guarda o caminho no Vault, não o valor.

## Veredito, pendência e conflito

Cada linha da lista é um **enlace**, não um peer: os peers IPv4 e IPv6 que
dividem a mesma subinterface viram uma proposta só, de circuito dual stack.

O **veredito** tem três valores. `adotavel` quando não falta nada.
`adotavel_com_pendencias` quando há decisão humana a tomar, como cadastrar a
organização ou escolher o perfil de política. `nao_adotavel` quando há conflito,
que precisa ser resolvido fora da tela, e a proposta se recalcula sozinha na
próxima abertura.

**Pendência** é o que você preenche. **Conflito** é o que impede, e vem sempre com
o que fazer: VLAN já reservada para outro circuito, prefixo já reservado, par de
endereços já em uso, endereço que não está em um par p2p (sub-rede compartilhada de
IX, por exemplo, que o IPAM não representa), subinterface ausente na coleta e VRF
do enlace divergente do peer.

## As duas conferências

A **conferência de fidelidade** renderiza o que nasceria com esta proposta e
compara com o bloco da configuração que a originou, mostrando o que sobra no
render e o que falta nele. É o que impede a SoT de nascer mentindo: se o perfil de
política ainda não foi escolhido, o render não emite a route-policy, e a
conferência diz isso em vez de deixar passar.

A **conferência cruzada** compara com o `display ip interface brief` da mesma
coleta, que é a única fonte da VRF a que o endereço pertence. Sem esse recurso na
coleta, nada é conferido: ausência de dado não é divergência.

## O que ainda não existe

A adoção em si. Esta frente entrega a leitura e a lista de ignorados; cadastrar a
partir da proposta é a parte seguinte. O peer que você não quer adotar vai para a
lista de ignorados e para de aparecer, e você pode trazê-lo de volta quando
quiser.
```

- [ ] **Step 2: Add the runbook section**

Em `docs/runbook-validacao-ne8000.md`, uma seção nova: coletar um NE8000 de produção, abrir a página Migrar, conferir as propostas contra a configuração real do equipamento (VLAN, endereços, ASN, políticas), e registrar o que a leitura errou. **Nenhum comando é enviado ao equipamento em nenhum passo.**

- [ ] **Step 3: Update the repo state**

Em `CLAUDE.md`, um bullet no "Estado do repositório" descrevendo a frente: parser da config, motor de descoberta, proposta com veredito, as duas conferências, a coluna `ponta_local` em `ip_prefixes` e a lista de ignorados; e que a parte 2 (adoção) ainda não existe.

Em `README.md`, se houver seção de comandos, o grupo `gerenet discovery`.

- [ ] **Step 4: Commit**

```bash
git add docs/wiki/descoberta.md docs/runbook-validacao-ne8000.md CLAUDE.md README.md
git commit -m "docs(discovery): wiki, runbook e estado do repositório"
```

---

## Verificação final

- [ ] **Suíte completa:** `uv run pytest -q` — devem passar todos menos os dois de actor que já falhavam antes desta frente.
- [ ] **Lint:** `uv run ruff check src tests` sem erro.
- [ ] **Web:** `cd web && npm run build && npm run test` sem erro.
- [ ] **Migrações:** `uv run alembic upgrade head` e `uv run alembic downgrade -1` seguido de `upgrade head` para provar que a nova migration desce.
- [ ] **Sem segredo:** `grep -ri cipher` no diff não devolve valor de senha nenhum.
