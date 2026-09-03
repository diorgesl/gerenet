# Ciclo B1 — Parsers TextFSM e snapshot estruturado (coleta) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ampliar a coleta read-only da F1 com 5 parsers TextFSM novos (validados contra a captura real do NE8000 de 2026-09-03), merge no shape estruturado de `device_snapshots.resources` (§4.3 da spec) e os coletores `interfaces`, `bgp_peers` e `bgp_peers_verbose` (este parametrizado pelas sessões ativas do SoT, com cap).

**Architecture:** Parser por comando em `automation/parsers/huawei_vrp/textfsm/<nome>.template` (padrão F1), acionado por `parse_template`. O runner passa a tratar três formatos de spec de coletor: legado (`parser` simples → primeiro registro), multicomando (`parsers` por comando + `merge` que combina e normaliza tipos no shape do recurso) e dinâmico (`alvo_sessoes` → comandos montados a partir do banco). O merge vive num módulo próprio testável por unidade; nomes canônicos de interface (sem sufixo cosmético de velocidade) são a chave entre os três comandos de interfaces.

**Tech Stack:** Python + TextFSM 3.x (já no venv), SQLAlchemy (leitura do SoT), pytest (golden por fixture sanitizada). Sem novas dependências.

**Spec:** [docs/superpowers/specs/2026-09-03-gerenet-ciclo-b-render-divergencia-design.md](../specs/2026-09-03-gerenet-ciclo-b-render-divergencia-design.md) — seções §2, §3 (itens 9–10), §4 (na íntegra), §9, §10, §12. O plano argumenta a partir da spec; o executor lê os dois.

## Global Constraints

Todo requisito de tarefa inclui implicitamente esta seção. Valores exatos verbatim:

1. **Idioma**: artefatos (specs, planos, mensagens de commit, nomes de teste) em PT-BR; identificadores de código, comentários e docstrings em inglês (convenção do repo).
2. **Sem segredos** (spec §9): nenhuma saída de `display current-configuration` ou credencial entra em fixtures, testes ou git; fixtures = versões **sanitizadas** da captura; a captura bruta (`data/capturas-ne8000/`) é git-ignored e não é referenciada por teste algum.
3. **Parse devolve strings**: o TextFSM só produz strings; conversão de tipo (`asn`, `pref_rcv` → int) e normalização de vazio acontecem **exclusivamente** na camada de merge (`automation/parsers/huawei_vrp/merge.py`).
4. **Banco**: testes rodam somente contra `gerenet_test` (conftest cuida; nada de apontar para banco dev). `tests/conftest.py`, os catálogos seedados e `alembic/` **não** são alterados neste plano (B1 não tem migration).
5. **Fixtures**: arquivos novos em `tests/fixtures/huawei_vrp/`; o conteúdo de cada fixture no plano é byte-exato da captura sanitizada — preserve quebras de linha; espaços ao fim de linha são tolerados pelos templates (regras terminam em `\s*$$`) e não precisam ser recriados à mão.
6. **TextFSM** (regras validadas empiricamente, não alterar sem revalidar): âncoras de fim de linha em regras são escritas `$$` no arquivo (o motor faz `string.Template`); no fim do texto o TextFSM emite um registro residual (flush de EOF) quando valores `Filldown` persistem — contrato documentado e coberto por teste; o merge descarta o residual (`endereco_v6 == ""`).
7. **Hook mandatório**: subagentes que explorem código executam `graphify query "<assunto>"` antes de ler arquivos-fonte (vale para todo prompt de subagente deste plano). Após mudanças de código, rodar `graphify update .` na raiz do repo.
8. **Commits**: um commit por tarefa, ao final dela, com trailer `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
9. **Gates**: `uv run ruff check` limpo e os testes focados verdes ao fim de cada tarefa; suíte completa (`GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q` — redis local necessário, padrão dos testes atuais) verde ao fim da última.
10. **Legado preservado**: nada do que a F1 grava muda de nome/forma — `resources["version"]` e `resources["config_backup"]`, os arquivos brutos no volume e o padrão de diretórios `backups_dir/<device>/<timestamp>/<coletor>/`. O shape do B **adiciona** `interfaces`, `bgp_peers`, `bgp_peers_detalhes` (§4.3).
11. **afi vem do comando, nunca do endereço** (spec §3.9): `display bgp peer` = `ipv4`; `display bgp ipv6 peer` = `ipv6`.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Tarefa |
|---|---|---|
| `tests/fixtures/huawei_vrp/ne8000_display_interface_brief.txt` | fixture golden (30 linhas de tabela) | T1 |
| `src/gerenet/automation/parsers/huawei_vrp/textfsm/int_brief.template` | parser `display interface brief` | T1 |
| `tests/fixtures/huawei_vrp/ne8000_display_ip_interface_brief.txt` | fixture golden (19 linhas) | T2 |
| `src/gerenet/automation/parsers/huawei_vrp/textfsm/ip_int_brief.template` | parser `display ip interface brief` | T2 |
| `tests/fixtures/huawei_vrp/ne8000_display_ipv6_interface_brief.txt` | fixture golden (13 grupos) | T3 |
| `src/gerenet/automation/parsers/huawei_vrp/textfsm/ipv6_int_brief.template` | parser `display ipv6 interface brief` (agrupado) | T3 |
| `tests/fixtures/huawei_vrp/ne8000_display_bgp_peer.txt` + `ne8000_display_bgp_ipv6_peer.txt` | fixtures golden v4 (12) / v6 (10) | T4 |
| `src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer.template` | parser das duas tabelas BGP | T4 |
| `tests/fixtures/huawei_vrp/ne8000_display_bgp_peer_verbose.txt` + `ne8000_display_bgp_ipv6_peer_verbose.txt` | fixtures golden verbose v4/v6 | T5 |
| `src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer_verbose.template` | parser `display bgp [ipv6] peer <ip> verbose` | T5 |
| `src/gerenet/automation/parsers/huawei_vrp/merge.py` | normalização + merge por recurso (shape §4.3) | T6 |
| `tests/automation/test_merge.py` | testes de unidade do merge | T6 |
| `src/gerenet/automation/runner.py` | suporte a spec multicomando/merge + slug de arquivo | T7 |
| `tests/automation/test_runner.py` | testes do runner (nomes de arquivo, wiring, integração) | T7–T9 |
| `src/gerenet/automation/collectors.py` | coletores `interfaces`/`bgp_peers`; depois `comandos_verbose()` | T8/T9 |
| `tests/automation/test_parsers_golden.py` | goldens de todos os parsers + casos derivados | T1–T5 |

---

### Task 1: Parser e fixture golden — `display interface brief`

**Files:**
- Create: `tests/fixtures/huawei_vrp/ne8000_display_interface_brief.txt`
- Create: `src/gerenet/automation/parsers/huawei_vrp/textfsm/int_brief.template`
- Modify: `tests/automation/test_parsers_golden.py` (adicionar const `FIXTURES` e a função de teste)

**Interfaces:**
- Consumes: `parse_template(nome: str, texto: str) -> list[dict]` de `gerenet.automation.parsers.huawei_vrp.registry` (lê `<nome>.template` em `.../textfsm/`); `tests/fixtures/huawei_vrp/ne8000_display_version.txt` (padrão existente).
- Produces: parser registrado pelo nome `"int_brief"` e a fixture `ne8000_display_interface_brief.txt` — consumidos pelo merge (T6) e pelo coletor `interfaces` (T8).

Formato real (spec §4.2): legenda e cabeçalho `Interface PHY Protocol InUti OutUti inErrors outErrors`; sufixo de velocidade dentro do nome (`100GE0/1/53(100M)`); marcadores `*down` prefixados na coluna PHY; membros de Eth-Trunk indentados; `up(s)` (spoofing); `--` em InUti/OutUti (`Nve1`, `Vbdif1004`); subinterfaces `Eth-Trunk127.<vid>`.

- [ ] **Step 1: Escrever a fixture golden** (30 linhas de tabela, conteúdo sanitizado byte-exato da captura)

Criar `tests/fixtures/huawei_vrp/ne8000_display_interface_brief.txt` com:

```text
PHY: Physical
*down: administratively down
^down: standby
(l): loopback
(s): spoofing
(E): E-Trunk down
(b): BFD down
(B): Bit-error-detection down
(e): ETHOAM down
(d): Dampening Suppressed
(p): port alarm down
(ld): loop-detect trigger down
(td): transceiver unmatch down
(mf): mac-flapping blocked
(c): CFM down
(sd): STP instance discarding
(D): DF backup down
InUti/OutUti: input utility/output utility
Interface                   PHY   Protocol  InUti OutUti   inErrors  outErrors
100GE0/1/53(100M)           up    down      0.01%  0.01%          0          0
40GE0/1/52                  down  down         0%     0%          0          0
Eth-Trunk0                  down  down         0%     0%          0          0
  GigabitEthernet0/1/2(10G) down  down         0%     0%          0          0
  GigabitEthernet0/1/4(10G) down  down         0%     0%          0          0
Eth-Trunk127                up    down     29.78% 29.78%          0          0
  40GE0/1/48                up    up       29.45% 28.81%          0          0
  40GE0/1/49                up    up       30.71% 29.79%          0          0
  40GE0/1/50                up    up       29.26% 30.10%          0          0
  40GE0/1/51                up    up       29.70% 30.43%          0          0
Eth-Trunk127.400            up    up        0.16%  1.00%          0          0
Eth-Trunk127.401            up    down      0.03%  0.33%          0          0
Eth-Trunk127.582            *down down         0%     0%          0          0
Eth-Trunk127.625            up    up        0.07%  0.72%          0          0
Eth-Trunk127.642            *down down         0%     0%          0          0
Eth-Trunk127.1500           up    up        2.99%  0.22%          0          0
Eth-Trunk127.4024           up    up        0.02%     0%          0          0
Eth-Trunk127.97653          up    down         0%     0%          0          0
Eth-Trunk127.389998         up    up           0%     0%          0          0
GigabitEthernet0/0/0        down  down         0%     0%          0          0
GigabitEthernet0/1/0.1003(10G) down  down         0%     0%          0          0
GigabitEthernet0/1/1.3009(10G) down  down         0%     0%          0          0
GigabitEthernet0/1/9(10G)   *down down         0%     0%          0          0
LoopBack0                   up    up(s)        0%     0%          0          0
NULL0                       up    up(s)        0%     0%          0          0
Nve1                        up    up           --     --          0          0
Vbdif1004                   up    down         --     --          0          0
Virtual-Ethernet0/1/100     up    down         0%     0%          0          0
Virtual-Ethernet0/1/100.100 up    up           0%     0%          0          0
Virtual-Template0           up    up(s)        0%     0%          0          0
```

- [ ] **Step 2: Escrever o teste golden (vermelho)**

Em `tests/automation/test_parsers_golden.py`, adicionar após a linha `FIXTURE = Path(...)`:

```python
FIXTURES = Path("tests/fixtures/huawei_vrp")
```

e ao final do arquivo:

```python
def test_parse_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("int_brief", saida)
    assert len(linhas) == 30
    assert linhas[0] == {"nome": "100GE0/1/53(100M)", "phy": "up", "protocolo": "down"}
    por_nome = {linha["nome"]: linha for linha in linhas}
    assert por_nome["Eth-Trunk127"]["phy"] == "up"
    assert por_nome["Eth-Trunk127"]["protocolo"] == "down"
    assert por_nome["40GE0/1/48"] == {"nome": "40GE0/1/48", "phy": "up", "protocolo": "up"}
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["LoopBack0"]["protocolo"] == "up(s)"
    assert por_nome["Nve1"]["phy"] == "up"
    assert "GigabitEthernet0/1/0.1003(10G)" in por_nome


def test_parse_interface_brief_standby_derivado() -> None:
    # Derivado (sintético, spec §10): variante ^down (standby) ausente da captura real.
    saida = (
        "Interface                   PHY   Protocol  InUti OutUti   inErrors  outErrors\n"
        "Eth-Trunk127.900            ^down down         0%     0%          0          0\n"
    )
    assert parse_template("int_brief", saida) == [
        {"nome": "Eth-Trunk127.900", "phy": "^down", "protocolo": "down"},
    ]
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_parsers_golden.py::test_parse_interface_brief_contra_captura_real -q`
Expected: FAIL — template `int_brief` não existe (FileNotFoundError no registry).

- [ ] **Step 4: Escrever o template**

Criar `src/gerenet/automation/parsers/huawei_vrp/textfsm/int_brief.template` com (nota: os `$$` ao fim de cada regra são obrigatórios — o motor interpreta a regra como `string.Template`; escrever `$` sozinho antes da quebra de linha quebra com `ValueError: Invalid placeholder`):

```text
Value Required nome (\S+)
Value Required phy (\S+)
Value Required protocolo (\S+)

Start
  ^\s*Interface\s+PHY\s+Protocol\s+InUti\s+OutUti\s+inErrors\s+outErrors\s*$$
  ^\s*${nome}\s+${phy}\s+${protocolo}\s+\S+\s+\S+\s+\d+\s+\d+\s*$$ -> Record
```

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_parsers_golden.py -q`
Expected: PASS (o teste legado de `version` continua verde).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/huawei_vrp/ne8000_display_interface_brief.txt src/gerenet/automation/parsers/huawei_vrp/textfsm/int_brief.template tests/automation/test_parsers_golden.py
git commit -m "feat(automation): parser textfsm int_brief com fixture golden (display interface brief)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Parser e fixture golden — `display ip interface brief`

**Files:**
- Create: `tests/fixtures/huawei_vrp/ne8000_display_ip_interface_brief.txt`
- Create: `src/gerenet/automation/parsers/huawei_vrp/textfsm/ip_int_brief.template`
- Modify: `tests/automation/test_parsers_golden.py`

**Interfaces:**
- Consumes: T1 (`FIXTURES`, `parse_template`, padrão de template).
- Produces: parser `"ip_int_brief"` + fixture — consumidos por T6 (merge) e T8.

Formato real (spec §4.2): linhas de resumo `The number of interface that is UP in Physical is …`; cabeçalho `Interface IP Address/Mask Physical Protocol VPN`; endereço `unassigned`; VPN `--` ou nome de VRF (`l3vpn`); `*down` na coluna Physical; `up(s)` em LoopBack; sufixo de velocidade no nome.

- [ ] **Step 1: Escrever a fixture golden** (19 linhas de tabela; contagens do resumo conferem: 14 up/5 down físicas, 11 up/8 down de protocolo)

Criar `tests/fixtures/huawei_vrp/ne8000_display_ip_interface_brief.txt`:

```text
*down: administratively down
!down: FIB overload down
^down: standby
(l): loopback
(s): spoofing
(d): Dampening Suppressed
(E): E-Trunk down
(td): transceiver unmatch down
(D): DF backup down
The number of interface that is UP in Physical is 14
The number of interface that is DOWN in Physical is 5
The number of interface that is UP in Protocol is 11
The number of interface that is DOWN in Protocol is 8
Interface                         IP Address/Mask      Physical   Protocol VPN
100GE0/1/53(100M)                 unassigned           up         down     --
40GE0/1/52                        unassigned           down       down     --
Eth-Trunk127                      unassigned           up         down     --
Eth-Trunk127.400                  172.17.0.253/30      up         up       --
Eth-Trunk127.401                  unassigned           up         down     --
Eth-Trunk127.529                  100.110.0.57/30      up         up       --
Eth-Trunk127.582                  172.25.2.69/31       *down      down     --
Eth-Trunk127.625                  100.110.0.1/30       up         up       --
Eth-Trunk127.642                  100.110.0.33/30      *down      down     --
Eth-Trunk127.1500                 198.51.100.17/31      up         up       --
Eth-Trunk127.4024                 100.110.0.73/30      up         up       --
Eth-Trunk127.4027                 100.110.0.77/30      up         up       --
Eth-Trunk127.389998               100.89.255.1/24      up         up       --
GigabitEthernet0/0/0              192.168.0.1/24       down       down     l3vpn
GigabitEthernet0/1/0.1003(10G)    10.254.101.29/30     down       down     --
LoopBack0                         203.0.113.1/32     up         up(s)    --
LoopBack1                         unassigned           up         up(s)    --
Virtual-Ethernet0/1/101.100       100.127.190.1/30     up         up       --
Virtual-Template0                 unassigned           up         up(s)    --
```

- [ ] **Step 2: Escrever o teste golden (vermelho)**

Adicionar ao final de `tests/automation/test_parsers_golden.py`:

```python
def test_parse_ip_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_ip_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("ip_int_brief", saida)
    assert len(linhas) == 19
    por_nome = {linha["nome"]: linha for linha in linhas}
    assert por_nome["Eth-Trunk127.4024"] == {
        "nome": "Eth-Trunk127.4024", "endereco": "100.110.0.73/30",
        "phy": "up", "protocolo": "up", "vpn": "--",
    }
    assert por_nome["LoopBack0"]["endereco"] == "203.0.113.1/32"
    assert por_nome["GigabitEthernet0/0/0"]["vpn"] == "l3vpn"
    assert por_nome["GigabitEthernet0/0/0"]["endereco"] == "192.168.0.1/24"
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["100GE0/1/53(100M)"]["endereco"] == "unassigned"
    assert por_nome["Eth-Trunk127.1500"]["endereco"] == "198.51.100.17/31"
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_parsers_golden.py::test_parse_ip_interface_brief_contra_captura_real -q`
Expected: FAIL — template `ip_int_brief` inexistente.

- [ ] **Step 4: Escrever o template**

Criar `src/gerenet/automation/parsers/huawei_vrp/textfsm/ip_int_brief.template`:

```text
Value Required nome (\S+)
Value endereco (\S+)
Value phy (\S+)
Value protocolo (\S+)
Value vpn (\S+)

Start
  ^\s*The number of interface .*$$
  ^\s*Interface\s+IP Address\/Mask\s+Physical\s+Protocol\s+VPN\s*$$
  ^\s*${nome}\s+${endereco}\s+${phy}\s+${protocolo}\s+${vpn}\s*$$ -> Record
```

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_parsers_golden.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/huawei_vrp/ne8000_display_ip_interface_brief.txt src/gerenet/automation/parsers/huawei_vrp/textfsm/ip_int_brief.template tests/automation/test_parsers_golden.py
git commit -m "feat(automation): parser textfsm ip_int_brief com fixture golden (display ip interface brief)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Parser e fixture golden — `display ipv6 interface brief` (agrupado)

**Files:**
- Create: `tests/fixtures/huawei_vrp/ne8000_display_ipv6_interface_brief.txt`
- Create: `src/gerenet/automation/parsers/huawei_vrp/textfsm/ipv6_int_brief.template`
- Modify: `tests/automation/test_parsers_golden.py`

**Interfaces:**
- Consumes: T1 (padrões). Não consome T2.
- Produces: parser `"ipv6_int_brief"` + fixture — consumidos por T6 (merge) e T8.

Formato real (spec §4.2): **agrupado** — linha de interface (`Interface Physical Protocol VPN`) seguida de uma ou mais linhas `[IPv6 Address/Prefix Length] <end>/<len>`, com sufixos `[TENTATIVE]` (removido do valor) ou a sentinela `Unassigned`. O template usa `Value Filldown` para a interface e `Record` por linha de endereço.

**Contrato de flush de EOF (constraint 6):** `Filldown` persiste após o último `Record`; o TextFSM emite no fim do texto um registro residual com o nome da última interface e `endereco_v6 == ""`. A fixture tem 13 grupos → o golden espera **14 registros**, e o residual é o 14º (o merge o descarta — T6).

- [ ] **Step 1: Escrever a fixture golden** (13 grupos; contém variantes `*down`, `up(s)`, `[TENTATIVE]`, `Unassigned`)

Criar `tests/fixtures/huawei_vrp/ne8000_display_ipv6_interface_brief.txt`:

```text
*down: administratively down
!down: FIB overload down
(l): loopback
(s): spoofing
Interface                    Physical              Protocol VPN
Eth-Trunk127.401             up                    up       --
[IPv6 Address/Prefix Length] 2001:DB8:1000::155:F0CA:A/127
Eth-Trunk127.582             *down                 down     --
[IPv6 Address/Prefix Length] FC00::2B7/127  [TENTATIVE]
Eth-Trunk127.624             up                    down     --
[IPv6 Address/Prefix Length] Unassigned
Eth-Trunk127.625             up                    up       --
[IPv6 Address/Prefix Length] 2001:DB8:1000::1100:0:1/126
Eth-Trunk127.629             *down                 down     --
[IPv6 Address/Prefix Length] 2001:DB8:1000::1100:1:1/126  [TENTATIVE]
Eth-Trunk127.642             *down                 down     --
[IPv6 Address/Prefix Length] Unassigned
Eth-Trunk127.2003            up                    up       --
[IPv6 Address/Prefix Length] 2001:DB8:F247:FFF3::2/64
Eth-Trunk127.3899            up                    up       --
[IPv6 Address/Prefix Length] 2001:DB8:1111::A/126
Eth-Trunk127.4024            up                    up       --
[IPv6 Address/Prefix Length] 2001:DB8:1000::1100:73:1/126
GigabitEthernet0/1/0.1003    down                  down     --
[IPv6 Address/Prefix Length] 2001:DB8:1111::51/126  [TENTATIVE]
LoopBack0                    up                    up(s)    --
[IPv6 Address/Prefix Length] 2001:DB8::1/128
LoopBack1                    up                    up(s)    --
[IPv6 Address/Prefix Length] Unassigned
Virtual-Ethernet0/1/101.100  up                    up       --
[IPv6 Address/Prefix Length] 2001:DB8:F190::1/126
```

- [ ] **Step 2: Escrever o teste golden (vermelho)**

Adicionar ao final de `tests/automation/test_parsers_golden.py`:

```python
def test_parse_ipv6_interface_brief_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_ipv6_interface_brief.txt").read_text(encoding="utf-8")
    linhas = parse_template("ipv6_int_brief", saida)
    # 14 registros: 13 interfaces reais + 1 residual do flush de EOF (Filldown persiste
    # e o TextFSM emite o último grupo com endereco_v6 vazio). O merge descarta o residual.
    assert len(linhas) == 14
    esperados = {
        "Eth-Trunk127.401": "2001:DB8:1000::155:F0CA:A/127",
        "Eth-Trunk127.582": "FC00::2B7/127",
        "Eth-Trunk127.624": "Unassigned",
        "Eth-Trunk127.625": "2001:DB8:1000::1100:0:1/126",
        "Eth-Trunk127.629": "2001:DB8:1000::1100:1:1/126",
        "Eth-Trunk127.642": "Unassigned",
        "Eth-Trunk127.2003": "2001:DB8:F247:FFF3::2/64",
        "Eth-Trunk127.3899": "2001:DB8:1111::A/126",
        "Eth-Trunk127.4024": "2001:DB8:1000::1100:73:1/126",
        "GigabitEthernet0/1/0.1003": "2001:DB8:1111::51/126",
        "LoopBack0": "2001:DB8::1/128",
        "LoopBack1": "Unassigned",
        "Virtual-Ethernet0/1/101.100": "2001:DB8:F190::1/126",
    }
    por_nome: dict[str, list[dict]] = {}
    for linha in linhas:
        por_nome.setdefault(linha["nome"], []).append(linha)
    assert set(por_nome) == set(esperados)
    for nome, endereco in esperados.items():
        assert endereco in [linha["endereco_v6"] for linha in por_nome[nome]]
    assert por_nome["Eth-Trunk127.582"][0]["phy"] == "*down"
    assert linhas[-1] == {
        "nome": "Virtual-Ethernet0/1/101.100", "phy": "up", "protocolo": "up",
        "vpn": "--", "endereco_v6": "",
    }
    assert len([linha for linha in linhas if linha["endereco_v6"]]) == 13


def test_parse_ipv6_interface_brief_multiplos_enderecos_derivado() -> None:
    # Derivado (sintético, spec §10): mais de um endereço por interface — a captura
    # real traz um por grupo. ([TENTATIVE] é variante real, presente na fixture.)
    saida = (
        "Interface                    Physical              Protocol VPN\n"
        "Eth-Trunk127.625             up                    up       --\n"
        "[IPv6 Address/Prefix Length] 2001:DB8:1000::1100:0:1/126\n"
        "[IPv6 Address/Prefix Length] 2001:DB8:1000::1100:0:2/126  [TENTATIVE]\n"
        "LoopBack0                    up                    up(s)    --\n"
        "[IPv6 Address/Prefix Length] 2001:DB8::1/128\n"
    )
    linhas = parse_template("ipv6_int_brief", saida)
    assert [linha["endereco_v6"] for linha in linhas if linha["nome"] == "Eth-Trunk127.625"] == [
        "2001:DB8:1000::1100:0:1/126", "2001:DB8:1000::1100:0:2/126",
    ]
    assert linhas[-1] == {"nome": "LoopBack0", "phy": "up", "protocolo": "up(s)",
                          "vpn": "--", "endereco_v6": ""}  # flush de EOF
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_parsers_golden.py::test_parse_ipv6_interface_brief_contra_captura_real -q`
Expected: FAIL — template `ipv6_int_brief` inexistente.

- [ ] **Step 4: Escrever o template**

Criar `src/gerenet/automation/parsers/huawei_vrp/textfsm/ipv6_int_brief.template`. Ordem das regras em `Grupo` importa: a regra de endereço **antes** da regra de interface (uma linha `[IPv6 …]` também casaria o prefixo da regra de interface; a primeira regra que casa vence).

```text
Value Filldown nome (\S+)
Value Filldown phy (\S+)
Value Filldown protocolo (\S+)
Value Filldown vpn (\S+)
Value endereco_v6 (\S+)

Start
  ^\s*Interface\s+Physical\s+Protocol\s+VPN\s*$$ -> Grupo

Grupo
  ^\s*\[IPv6 Address\/Prefix Length\]\s+${endereco_v6}(\s+\[TENTATIVE\])?\s*$$ -> Record
  ^\s*${nome}\s+${phy}\s+${protocolo}\s+${vpn}\s*$$ -> Continue
```

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_parsers_golden.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/huawei_vrp/ne8000_display_ipv6_interface_brief.txt src/gerenet/automation/parsers/huawei_vrp/textfsm/ipv6_int_brief.template tests/automation/test_parsers_golden.py
git commit -m "feat(automation): parser textfsm ipv6_int_brief agrupado com fixture golden

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Parser e fixtures golden — `display bgp peer` (v4) e `display bgp ipv6 peer` (v6)

**Files:**
- Create: `tests/fixtures/huawei_vrp/ne8000_display_bgp_peer.txt`
- Create: `tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer.txt`
- Create: `src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer.template`
- Modify: `tests/automation/test_parsers_golden.py`

**Interfaces:**
- Consumes: T1 (padrões).
- Produces: parser único `"bgp_peer"` (as duas famílias têm o mesmo formato de tabela) + 2 fixtures — consumidos por T6 (merge) e T8.

Formato real (spec §4.2): cabeçalho `BGP local router ID` / `Local AS number` / `Total number of peers : N Peers in established state : M`; colunas `Peer V AS MsgRcvd MsgSent OutQ Up/Down State PrefRcv`; `Up/Down` em dois formatos (`0655h07m`, `21:48:20`); estados `Established/Idle/Idle(Admin)/Connect/Active`; `PrefRcv` até 7 dígitos; endereços v6 na coluna Peer.

Sanitização aplicada (determinística, documentada na spec): AS local 61785→64512, router-id 201.131.152.1→203.0.113.1, mapa de ASNs de par (262675→64526, 61589→64515, 65332→64533, 270620→64520, 53153→64535, 269702→64525, 271253→64544, 53062→64531, 61622→64522, 65401→64540, 28287→64528), peers/p2p públicos → documentação/benchmark, `2804:*` → `2001:DB8:*`, faixas privadas/CGNAT/doc/ULA mantidas.

- [ ] **Step 1: Escrever as fixtures golden**

Criar `tests/fixtures/huawei_vrp/ne8000_display_bgp_peer.txt` (12 linhas; o cabeçalho real diz 62 peers/32 established — a fixture recorta a tabela e mantém o cabeçalho original):

```text
 BGP local router ID : 203.0.113.1
 Local AS number : 64512
 Total number of peers : 62                 Peers in established state : 32

  Peer                             V          AS  MsgRcvd  MsgSent  OutQ  Up/Down       State  PrefRcv
  10.30.70.1                       4      64526        0        0     0 0655h07m Idle(Admin)        0
  10.247.3.1                       4       64515   103073   103251     0 0490h58m Established       37
  10.255.255.0                     4       64512   138117 19747721     0 0655h06m Established        3
  38.229.6.20                      4       64533        0        0     0 0655h07m     Connect        0
  100.110.0.14                     4      64520        0        0     0 0655h07m      Active        0
  100.110.0.66                     4       64535        0        0     0 21:48:20        Idle        0
  100.110.0.74                     4      64520   810327  1155925     0 0655h06m Established        1
  100.110.0.78                     4      64520   810311  1155941     0 0655h06m Established        6
  100.110.0.82                     4      64525   785841  1156008     0 0655h06m Established        2
  172.25.2.68                      4      64544        0        0     0 0655h07m Idle(Admin)        0
  198.51.100.254                   4       64531 18850534    74947     0 0356h52m Established  1090707
  198.19.255.250                   4       64522 10377172    51420     0 0244h53m Established  1093942
```

Criar `tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer.txt` (10 linhas; a tabela IPv6 lista também peers de transporte v4 — spec §3.9):

```text
 BGP local router ID : 203.0.113.1
 Local AS number : 64512
 Total number of peers : 52                 Peers in established state : 27

  Peer                             V          AS  MsgRcvd  MsgSent  OutQ  Up/Down       State  PrefRcv
  100.110.0.110                    4       64540        0        0     0 0655h07m     Connect        0
  2001:DB8:F247:FFF3::1            4       64515   104321   103159     0 0490h58m Established        0
  2001:DB8:8000:0:198:51:100:254   4       64531 23787944    74957     0 0356h44m Established   253052
  2001:DB8::3                     4       64512    46537 19612063     0 0655h06m Established       13
  2001:DB8:1000::155:177:2        4      64525   785844  1155088     0 0655h06m Established        9
  2001:DB8:1000::1100:73:2        4      64520   810346  1155318     0 0655h06m Established        1
  2001:DB8:1000::1100:77:2        4      64520   810373  1154974     0 0655h06m Established        2
  2001:DB8::250                   4       64522 10667740    46554     0 0221h45m Established   254697
  FC00::2B6                        4      64544        0        0     0 0655h07m Idle(Admin)        0
  FDFF::198:18:255:0               4       64528        0        0     0 0655h07m      Active        0
```

- [ ] **Step 2: Escrever os testes golden (vermelho)**

Adicionar ao final de `tests/automation/test_parsers_golden.py`:

```python
def test_parse_bgp_peer_v4_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_bgp_peer.txt").read_text(encoding="utf-8")
    linhas = parse_template("bgp_peer", saida)
    assert [(l["peer"], l["asn"], l["estado"], l["pref_rcv"], l["up_down"]) for l in linhas] == [
        ("10.30.70.1", "64526", "Idle(Admin)", "0", "0655h07m"),
        ("10.247.3.1", "64515", "Established", "37", "0490h58m"),
        ("10.255.255.0", "64512", "Established", "3", "0655h06m"),
        ("38.229.6.20", "64533", "Connect", "0", "0655h07m"),
        ("100.110.0.14", "64520", "Active", "0", "0655h07m"),
        ("100.110.0.66", "64535", "Idle", "0", "21:48:20"),
        ("100.110.0.74", "64520", "Established", "1", "0655h06m"),
        ("100.110.0.78", "64520", "Established", "6", "0655h06m"),
        ("100.110.0.82", "64525", "Established", "2", "0655h06m"),
        ("172.25.2.68", "64544", "Idle(Admin)", "0", "0655h07m"),
        ("198.51.100.254", "64531", "Established", "1090707", "0356h52m"),
        ("198.19.255.250", "64522", "Established", "1093942", "0244h53m"),
    ]


def test_parse_bgp_peer_v6_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_bgp_ipv6_peer.txt").read_text(encoding="utf-8")
    linhas = parse_template("bgp_peer", saida)
    assert [(l["peer"], l["asn"], l["estado"]) for l in linhas] == [
        ("100.110.0.110", "64540", "Connect"),
        ("2001:DB8:F247:FFF3::1", "64515", "Established"),
        ("2001:DB8:8000:0:198:51:100:254", "64531", "Established"),
        ("2001:DB8::3", "64512", "Established"),
        ("2001:DB8:1000::155:177:2", "64525", "Established"),
        ("2001:DB8:1000::1100:73:2", "64520", "Established"),
        ("2001:DB8:1000::1100:77:2", "64520", "Established"),
        ("2001:DB8::250", "64522", "Established"),
        ("FC00::2B6", "64544", "Idle(Admin)"),
        ("FDFF::198:18:255:0", "64528", "Active"),
    ]
    assert linhas[2]["pref_rcv"] == "253052"  # contagem larga (6 dígitos; v4 chega a 7)


def test_parse_bgp_peer_estado_transitorio_openconfirm_derivado() -> None:
    # Derivado (sintético, spec §10): a captura real só tem os estados estáveis.
    saida = (
        " BGP local router ID : 203.0.113.1\n"
        " Local AS number : 64512\n"
        "\n"
        "  Peer                             V          AS  MsgRcvd  MsgSent  OutQ  Up/Down       State  PrefRcv\n"
        "  10.99.0.1                       4      64530      101      102     0 0655h07m   OpenConfirm        0\n"
    )
    assert parse_template("bgp_peer", saida) == [
        {"peer": "10.99.0.1", "asn": "64530", "estado": "OpenConfirm",
         "pref_rcv": "0", "up_down": "0655h07m"},
    ]
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_parsers_golden.py::test_parse_bgp_peer_v4_contra_captura_real -q`
Expected: FAIL — template `bgp_peer` inexistente.

- [ ] **Step 4: Escrever o template**

Criar `src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer.template`:

```text
Value Required peer (\S+)
Value asn (\d+)
Value estado (\S+)
Value pref_rcv (\d+)
Value up_down (\S+)

Start
  ^\s*BGP local router ID .*$$
  ^\s*Local AS number .*$$
  ^\s*Total number of peers .*$$
  ^\s*Peer\s+V\s+AS\s+MsgRcvd\s+MsgSent\s+OutQ\s+Up\/Down\s+State\s+PrefRcv\s*$$ -> Tabela

Tabela
  ^\s+${peer}\s+\d+\s+${asn}\s+\d+\s+\d+\s+\d+\s+${up_down}\s+${estado}\s+${pref_rcv}\s*$$ -> Record
```

- [ ] **Step 5: Rodar para ver passar (as duas famílias)**

Run: `uv run pytest tests/automation/test_parsers_golden.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/huawei_vrp/ne8000_display_bgp_peer.txt tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer.txt src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer.template tests/automation/test_parsers_golden.py
git commit -m "feat(automation): parser textfsm bgp_peer (v4/v6) com fixtures golden

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Parser e fixtures golden — `display bgp [ipv6] peer <ip> verbose`

**Files:**
- Create: `tests/fixtures/huawei_vrp/ne8000_display_bgp_peer_verbose.txt`
- Create: `tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer_verbose.txt`
- Create: `src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer_verbose.template`
- Modify: `tests/automation/test_parsers_golden.py`

**Interfaces:**
- Consumes: T1 (padrões).
- Produces: parser `"bgp_peer_verbose"` + 2 fixtures — consumidos por T6 (detalhes) e T9 (coletor parametrizado). O coletor emite **um comando por peer**; cada parse devolve 1 registro (flush de EOF — sem `-> Record` no template).

Formato real (spec §4.2): `BGP Peer is <ip>,  remote AS <n>`; `Peer's description: "<texto>"` (linha pode não existir); `BGP current state: <estado>, Up for <duração>`; bloco `Routing policy configured:` com `Import route filter is: <nome>(N)` / `Export route filter is: <nome>(N)` — a contagem `(N)` é **opcional** (a captura v6 traz o import sem contagem). Nada de senha na saída.

**Regra de estado com fallback:** peers admin-down mostram `BGP current state: Idle(Admin)` **sem** `Up for`. A primeira regra de estado exige `, Up for`; a segunda (logo abaixo) casa qualquer estado sem duração — ordem importa (Established casa na primeira).

- [ ] **Step 1: Escrever as fixtures golden**

Criar `tests/fixtures/huawei_vrp/ne8000_display_bgp_peer_verbose.txt` (bloco completo de um peer v4 estabelecido, com descrição e filtros com contagem):

```text
         BGP Peer is 198.51.100.254,  remote AS 64531
         Type: EBGP link
         Peer's description: "UPSTREAM-FNA"
         BGP version 4, Remote router ID 198.51.100.247
         Update-group ID: 42
         BGP current state: Established, Up for 14d20h52m53s
         BGP current event: RecvUpdate
         BGP last state: OpenConfirm
         BGP Peer Up count: 3
         Received total routes: 1090717
         Received active routes total: 3467
         Advertised total routes: 62
         Port: Local - 179        Remote - 43371
         Configured: Connect-retry Time: 32 sec
         Configured: Min Hold Time: 0 sec
         Configured: Active Hold Time: 60 sec   Keepalive Time:20 sec
         Received  : Active Hold Time: 240 sec
         Negotiated: Active Hold Time: 60 sec   Keepalive Time:20 sec
         Peer optional capabilities:
         Peer supports bgp multi-protocol extension
         Peer supports bgp route refresh capability
         Peer supports bgp 4-byte-as capability
         Graceful Restart Capability: advertised and received
             Restart Timer Value received from Peer: 0 seconds
             Address families preserved for peer in GR:
         Address family IPv4 Unicast: advertised and received
 Received: Total 18850988 messages
                  Update messages                18777557
                  Open messages                  1
                  KeepAlive messages             73430
                  Notification messages          0
                  Refresh messages               0
                  Capability messages            0
 Sent: Total 74949 messages
                  Update messages                44
                  Open messages                  7
                  KeepAlive messages             74898
                  Notification messages          0
                  Refresh messages               0
                  Capability messages            0
 Authentication type configured: None
 Last keepalive received: 2026-09-03 16:00:29-04:00
 Last keepalive sent    : 2026-09-03 16:00:31-04:00
 Last update    received: 2026-09-03 16:00:42-04:00
 Last update    sent    : 2026-09-01 16:28:23-04:00
 No refresh received since peer has been configured
 No refresh sent since peer has been configured
 No capability received since peer has been configured
 No capability sent since peer has been configured
 Minimum route advertisement interval is 30 seconds
 Optional capabilities:
 Route refresh capability has been enabled
 4-byte-as capability has been enabled
 Soft-Reconfiguration has been enabled
 Send community has been configured
 Multi-hop ebgp has been enabled
 Peer Preferred Value: 0
 Routing policy configured:
 No import update filter list
 No export update filter list
 No import prefix list
 No export prefix list
 No import route policy
 No export route policy
 No import distribute policy
 No export distribute policy
 Import route filter is: ASN64531-V4-IMPORT(200)
 Export route filter is: XPL-UPSTREAM-AS64531-V4-EXPORT(1)
```

Criar `tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer_verbose.txt` (mesmo peer na família v6; o import **não** traz contagem nesta captura):

```text
         BGP Peer is 2001:DB8:8000:0:198:51:100:254,  remote AS 64531
         Type: EBGP link
         Peer's description: "UPSTREAM-v6"
         BGP version 4, Remote router ID 198.51.100.247
         Update-group ID: 7
         BGP current state: Established, Up for 14d20h45m57s
         BGP current event: RecvUpdate
         BGP last state: OpenConfirm
         BGP Peer Up count: 3
         Received total routes: 252993
         Received active routes total: 23
         Advertised total routes: 32
         Port: Local - 56337        Remote - 179
         Configured: Connect-retry Time: 32 sec
         Configured: Min Hold Time: 0 sec
         Configured: Active Hold Time: 60 sec   Keepalive Time:20 sec
         Received  : Active Hold Time: 240 sec
         Negotiated: Active Hold Time: 60 sec   Keepalive Time:20 sec
         Peer optional capabilities:
         Peer supports bgp multi-protocol extension
         Peer supports bgp route refresh capability
         Peer supports bgp 4-byte-as capability
         Graceful Restart Capability: advertised and received
             Restart Timer Value received from Peer: 0 seconds
             Address families preserved for peer in GR:
         Address family IPv6 Unicast: advertised and received
 Received: Total 23788694 messages
                  Update messages                23715333
                  Open messages                  1
                  KeepAlive messages             73360
                  Notification messages          0
                  Refresh messages               0
                  Capability messages            0
 Sent: Total 74962 messages
                  Update messages                46
                  Open messages                  10
                  KeepAlive messages             74906
                  Notification messages          0
                  Refresh messages               0
                  Capability messages            0
 Authentication type configured: None
 Last keepalive received: 2026-09-03 16:01:32-04:00
 Last keepalive sent    : 2026-09-03 16:01:41-04:00
 Last update    received: 2026-09-03 16:01:42-04:00
 Last update    sent    : 2026-09-01 16:28:21-04:00
 No refresh received since peer has been configured
 No refresh sent since peer has been configured
 No capability received since peer has been configured
 No capability sent since peer has been configured
 Minimum route advertisement interval is 30 seconds
 Optional capabilities:
 Route refresh capability has been enabled
 4-byte-as capability has been enabled
 Send community has been configured
 Multi-hop ebgp has been enabled
 Peer Preferred Value: 0
 Routing policy configured:
 No import update filter list
 No export update filter list
 No import prefix list
 No export prefix list
 No import route policy
 No export route policy
 No import distribute policy
 No export distribute policy
 Import route filter is: ASN64531-V6-IMPORT
 Export route filter is: XPL-UPSTREAM-AS64531-V6-EXPORT(1)
```

- [ ] **Step 2: Escrever os testes golden (vermelho)**

Adicionar ao final de `tests/automation/test_parsers_golden.py`:

```python
def test_parse_bgp_peer_verbose_v4_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_bgp_peer_verbose.txt").read_text(encoding="utf-8")
    linhas = parse_template("bgp_peer_verbose", saida)
    assert linhas == [{
        "peer": "198.51.100.254", "asn": "64531", "descricao": "UPSTREAM-FNA",
        "estado": "Established", "filtro_import": "ASN64531-V4-IMPORT",
        "filtro_export": "XPL-UPSTREAM-AS64531-V4-EXPORT",
    }]


def test_parse_bgp_peer_verbose_v6_contra_captura_real() -> None:
    saida = (FIXTURES / "ne8000_display_bgp_ipv6_peer_verbose.txt").read_text(encoding="utf-8")
    linhas = parse_template("bgp_peer_verbose", saida)
    assert linhas == [{
        "peer": "2001:DB8:8000:0:198:51:100:254", "asn": "64531", "descricao": "UPSTREAM-v6",
        "estado": "Established", "filtro_import": "ASN64531-V6-IMPORT",
        "filtro_export": "XPL-UPSTREAM-AS64531-V6-EXPORT",
    }]


def test_parse_bgp_peer_verbose_idle_admin_sem_up_for_derivado() -> None:
    # Derivado (sintético, spec §10): admin-down não traz 'Up for' nem descrição/filtros
    # — a segunda regra de estado (sem duração) precisa casar o Idle(Admin).
    saida = (
        "         BGP Peer is 10.99.0.1,  remote AS 64530\n"
        "         BGP current state: Idle(Admin)\n"
    )
    assert parse_template("bgp_peer_verbose", saida) == [{
        "peer": "10.99.0.1", "asn": "64530", "descricao": "", "estado": "Idle(Admin)",
        "filtro_import": "", "filtro_export": "",
    }]
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_parsers_golden.py::test_parse_bgp_peer_verbose_v4_contra_captura_real -q`
Expected: FAIL — template `bgp_peer_verbose` inexistente.

- [ ] **Step 4: Escrever o template**

Criar `src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer_verbose.template` (sem `-> Record`: o registro único nasce do flush de EOF):

```text
Value Required peer (\S+)
Value Required asn (\d+)
Value descricao (.+)
Value estado (\S+)
Value filtro_import ([A-Za-z0-9_-]+)
Value filtro_export ([A-Za-z0-9_-]+)

Start
  ^\s*BGP Peer is ${peer},\s+remote AS ${asn}\s*$$
  ^\s*Peer's description: "${descricao}"\s*$$
  ^\s*BGP current state: ${estado}, Up for .*$$
  ^\s*BGP current state: ${estado}\s*$$
  ^\s*Import route filter is: ${filtro_import}(\(\d+\))?\s*$$
  ^\s*Export route filter is: ${filtro_export}(\(\d+\))?\s*$$
```

- [ ] **Step 5: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_parsers_golden.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/huawei_vrp/ne8000_display_bgp_peer_verbose.txt tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer_verbose.txt src/gerenet/automation/parsers/huawei_vrp/textfsm/bgp_peer_verbose.template tests/automation/test_parsers_golden.py
git commit -m "feat(automation): parser textfsm bgp_peer_verbose com fixtures golden

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: Merge por recurso (`merge.py`) — shape §4.3 com tipos normalizados

**Files:**
- Create: `src/gerenet/automation/parsers/huawei_vrp/merge.py`
- Create: `tests/automation/test_merge.py`

**Interfaces:**
- Consumes: contratos de saída dos parsers T1–T5 (dicts com chaves de cada `Value`; valores sempre strings; `""` para linha ausente em verbose; `Unassigned`/`unassigned` como sentinelas literais).
- Produces (assinaturas consumidas por T7/T8/T9 e pelo B2):
  - `merge_interfaces(por_comando: dict[str, list[dict]]) -> list[dict]`
  - `merge_bgp_peers(por_comando: dict[str, list[dict]]) -> list[dict]`
  - `merge_bgp_peers_detalhes(por_comando: dict[str, list[dict]]) -> list[dict]`
  - `merge_parsed(nome: str, por_comando: dict[str, list[dict]]) -> list[dict]` (KeyError para nome desconhecido)

Regras de merge (validadas contra as fixtures reais — não alterar sem revalidar):
- **Nome canônico de interface**: remove o sufixo cosmético de velocidade (`(10G)`, `(100M)`) do fim do nome (`GE0/1/0.1003(10G)` → `GE0/1/0.1003`) — o `display ipv6 interface brief` omite o sufixo que o `interface brief` traz; sem a remoção a mesma subinterface viraria duas entradas.
- **phy/protocolo**: primeira fonte na ordem de iteração do dict (o coletor entrega `interface brief` → `ip interface brief` → `ipv6 interface brief`). Marcadores `*down`/`^down` seguem verbatim (a divergência do B2 normaliza).
- **vpn**: `"--"` → `None`; nome de VRF (`l3vpn`) preservado.
- **enderecos_v4**: valores diferentes de `"unassigned"`. **enderecos_v6**: valores diferentes de `"Unassigned"` e `""` (o residual do flush de EOF é descartado aqui).
- Saída ordenada por nome canônico; chaves exatas: `{nome, phy, protocolo, enderecos_v4, enderecos_v6, vpn}`.
- **afi vem do comando** (spec §3.9): `"ipv6" in comando` → `ipv6`, senão `ipv4`. **bgp_peers**: `asn`/`pref_rcv` → int; ordem = comandos na ordem do dict (v4 antes de v6), linhas na ordem da tabela; chaves `{afi, peer, asn, estado, pref_rcv, up_down}`.
- **bgp_peers_detalhes**: campos ausentes (`""`) → `None`; chaves `{afi, peer, descricao, filtro_import, filtro_export}`.

- [ ] **Step 1: Escrever os testes de unidade (vermelho)**

Criar `tests/automation/test_merge.py`:

```python
from gerenet.automation.parsers.huawei_vrp.merge import (
    merge_bgp_peers,
    merge_bgp_peers_detalhes,
    merge_interfaces,
    merge_parsed,
)

LINHA_INT = {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up"}
LINHA_IP = {
    "nome": "Eth-Trunk127.4024", "endereco": "100.110.0.73/30",
    "phy": "up", "protocolo": "up", "vpn": "--",
}


def test_interfaces_combina_tres_comandos_por_nome() -> None:
    por_comando = {
        "display interface brief": [LINHA_INT],
        "display ip interface brief": [LINHA_IP],
        "display ipv6 interface brief": [
            {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
             "vpn": "--", "endereco_v6": "2001:DB8:1000::1100:73:1/126"},
            # residual do flush de EOF (Filldown persiste): endereco vazio -> descartado
            {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
             "vpn": "--", "endereco_v6": ""},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
        "enderecos_v4": ["100.110.0.73/30"],
        "enderecos_v6": ["2001:DB8:1000::1100:73:1/126"],
        "vpn": None,
    }]


def test_interfaces_remove_sufixo_de_velocidade_do_nome() -> None:
    # O ipv6 interface brief omite o sufixo (10G) que o interface brief traz:
    # sem o nome canônico a mesma subinterface viraria duas entradas.
    por_comando = {
        "display interface brief": [
            {"nome": "GigabitEthernet0/1/0.1003(10G)", "phy": "down", "protocolo": "down"},
        ],
        "display ip interface brief": [
            {"nome": "GigabitEthernet0/1/0.1003(10G)", "endereco": "10.254.101.29/30",
             "phy": "down", "protocolo": "down", "vpn": "--"},
        ],
        "display ipv6 interface brief": [
            {"nome": "GigabitEthernet0/1/0.1003", "phy": "down", "protocolo": "down",
             "vpn": "--", "endereco_v6": "2001:DB8:1111::51/126"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "GigabitEthernet0/1/0.1003", "phy": "down", "protocolo": "down",
        "enderecos_v4": ["10.254.101.29/30"], "enderecos_v6": ["2001:DB8:1111::51/126"],
        "vpn": None,
    }]


def test_interfaces_descarta_sentinelas_de_vazio() -> None:
    por_comando = {
        "display interface brief": [LINHA_INT],
        "display ip interface brief": [
            {"nome": "Eth-Trunk127.4024", "endereco": "unassigned",
             "phy": "up", "protocolo": "down", "vpn": "--"},
        ],
        "display ipv6 interface brief": [
            {"nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "down",
             "vpn": "--", "endereco_v6": "Unassigned"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
        "enderecos_v4": [], "enderecos_v6": [], "vpn": None,
    }]


def test_interfaces_prioriza_interface_brief_e_vpn_nomeada() -> None:
    # phy/protocolo da primeira fonte na ordem dos comandos; vpn nomeada preservada.
    por_comando = {
        "display interface brief": [LINHA_INT],
        "display ip interface brief": [
            {"nome": "Eth-Trunk127.4024", "endereco": "unassigned",
             "phy": "down", "protocolo": "down", "vpn": "l3vpn"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
        "enderecos_v4": [], "enderecos_v6": [], "vpn": "l3vpn",
    }]


def test_interfaces_interface_so_no_ipv6_usa_dados_do_grupo() -> None:
    por_comando = {
        "display ipv6 interface brief": [
            {"nome": "Virtual-Ethernet0/1/101.100", "phy": "up", "protocolo": "up",
             "vpn": "--", "endereco_v6": "2001:DB8:F190::1/126"},
        ],
    }
    assert merge_interfaces(por_comando) == [{
        "nome": "Virtual-Ethernet0/1/101.100", "phy": "up", "protocolo": "up",
        "enderecos_v4": [], "enderecos_v6": ["2001:DB8:F190::1/126"], "vpn": None,
    }]


def test_bgp_peers_combina_familias_com_afi_e_tipos() -> None:
    por_comando = {
        "display bgp peer": [
            {"peer": "10.30.70.1", "asn": "64526", "estado": "Idle(Admin)",
             "pref_rcv": "0", "up_down": "0655h07m"},
        ],
        "display bgp ipv6 peer": [
            {"peer": "2001:DB8::3", "asn": "64512", "estado": "Established",
             "pref_rcv": "13", "up_down": "0655h06m"},
        ],
    }
    assert merge_bgp_peers(por_comando) == [
        {"afi": "ipv4", "peer": "10.30.70.1", "asn": 64526, "estado": "Idle(Admin)",
         "pref_rcv": 0, "up_down": "0655h07m"},
        {"afi": "ipv6", "peer": "2001:DB8::3", "asn": 64512, "estado": "Established",
         "pref_rcv": 13, "up_down": "0655h06m"},
    ]


def test_bgp_peers_vazio_devolve_lista_vazia() -> None:
    assert merge_bgp_peers({}) == []
    assert merge_bgp_peers({"display bgp peer": []}) == []


def test_detalhes_none_para_campos_ausentes_e_afi_do_comando() -> None:
    por_comando = {
        "display bgp peer 198.51.100.254 verbose": [
            {"peer": "198.51.100.254", "asn": "64531", "descricao": "UPSTREAM-FNA",
             "estado": "Established", "filtro_import": "ASN64531-V4-IMPORT",
             "filtro_export": "XPL-UPSTREAM-AS64531-V4-EXPORT"},
        ],
        "display bgp ipv6 peer 10.99.0.1 verbose": [
            {"peer": "10.99.0.1", "asn": "64530", "descricao": "",
             "estado": "Idle(Admin)", "filtro_import": "", "filtro_export": ""},
        ],
    }
    assert merge_bgp_peers_detalhes(por_comando) == [
        {"afi": "ipv4", "peer": "198.51.100.254", "descricao": "UPSTREAM-FNA",
         "filtro_import": "ASN64531-V4-IMPORT", "filtro_export": "XPL-UPSTREAM-AS64531-V4-EXPORT"},
        {"afi": "ipv6", "peer": "10.99.0.1", "descricao": None,
         "filtro_import": None, "filtro_export": None},
    ]


def test_merge_parsed_despacha_e_rejeita_desconhecido() -> None:
    import pytest

    assert merge_parsed("bgp_peers", {"display bgp peer": []}) == []
    with pytest.raises(KeyError, match="nao-existe"):
        merge_parsed("nao-existe", {})
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/automation/test_merge.py -q`
Expected: FAIL — `ModuleNotFoundError` (merge não existe).

- [ ] **Step 3: Escrever a implementação mínima**

Criar `src/gerenet/automation/parsers/huawei_vrp/merge.py`:

```python
"""Merge of parsed TextFSM rows per collection resource (spec §4.3 shape).

Parsers return strings only (contract); this module normalizes types, drops
VRP emptiness sentinels and combines the commands of one resource into the
structured `device_snapshots.resources` shape. Interface name (canonical, i.e.
without the cosmetic speed suffix) is the merge key between the three
interface-brief commands.
"""
import re

_SUFIXO_VELOCIDADE = re.compile(r"\(\d+(?:[GM])?\)$")
_SEM_ENDERECO_V4 = ("unassigned",)
_SEM_ENDERECO_V6 = ("Unassigned", "")


def _afi_de_comando(comando: str) -> str:
    """afi comes from the command (spec §3.9): `display bgp peer` is IPv4 and the
    ipv6 variants carry the word."""
    return "ipv6" if "ipv6" in comando else "ipv4"


def _nome_canonico(nome: str) -> str:
    """Interface name without the cosmetic speed suffix (`GE0/1/0.1003(10G)` ->
    `GE0/1/0.1003`); the ipv6 brief omits the suffix the interface brief shows."""
    return _SUFIXO_VELOCIDADE.sub("", nome)


def merge_interfaces(por_comando: dict[str, list[dict]]) -> list[dict]:
    """Combine interface brief, ip interface brief and ipv6 interface brief.

    phy/protocolo come from the first source in dict order (the collector sends
    interface brief first, then ip, then ipv6). `vpn` `--` becomes None; named
    VRFs are kept. Addresses drop the VRP emptiness sentinels (unassigned /
    Unassigned / the EOF-flush phantom row with endereco_v6 == "").
    Output sorted by canonical name, keys exactly:
    {nome, phy, protocolo, enderecos_v4, enderecos_v6, vpn}.
    """
    merged: dict[str, dict] = {}
    for linhas in por_comando.values():
        for linha in linhas:
            nome = _nome_canonico(linha["nome"])
            registro = merged.setdefault(
                nome,
                {"nome": nome, "phy": None, "protocolo": None,
                 "enderecos_v4": [], "enderecos_v6": [], "vpn": None},
            )
            if registro["phy"] is None:
                registro["phy"] = linha["phy"]
                registro["protocolo"] = linha["protocolo"]
            if "vpn" in linha and registro["vpn"] is None:
                registro["vpn"] = None if linha["vpn"] == "--" else linha["vpn"]
            if "endereco" in linha and linha["endereco"] not in _SEM_ENDERECO_V4:
                registro["enderecos_v4"].append(linha["endereco"])
            if "endereco_v6" in linha and linha["endereco_v6"] not in _SEM_ENDERECO_V6:
                registro["enderecos_v6"].append(linha["endereco_v6"])
    return [merged[k] for k in sorted(merged)]


def merge_bgp_peers(por_comando: dict[str, list[dict]]) -> list[dict]:
    """Combine the v4 and v6 peer tables into one list with afi and typed values.

    Order: commands in dict order (v4 before v6 in the collector), rows in table
    order. Keys: {afi, peer, asn, estado, pref_rcv, up_down} with asn/pref_rcv
    cast to int.
    """
    return [
        {
            "afi": _afi_de_comando(comando),
            "peer": linha["peer"],
            "asn": int(linha["asn"]),
            "estado": linha["estado"],
            "pref_rcv": int(linha["pref_rcv"]),
            "up_down": linha["up_down"],
        }
        for comando, linhas in por_comando.items()
        for linha in linhas
    ]


def merge_bgp_peers_detalhes(por_comando: dict[str, list[dict]]) -> list[dict]:
    """Verbose rows (one command per peer) -> details with None for missing fields.

    Keys: {afi, peer, descricao, filtro_import, filtro_export}; descricao and
    filters are None when absent from the output.
    """
    return [
        {
            "afi": _afi_de_comando(comando),
            "peer": linha["peer"],
            "descricao": linha["descricao"] or None,
            "filtro_import": linha["filtro_import"] or None,
            "filtro_export": linha["filtro_export"] or None,
        }
        for comando, linhas in por_comando.items()
        for linha in linhas
    ]


_MERGES = {
    "interfaces": merge_interfaces,
    "bgp_peers": merge_bgp_peers,
    "bgp_peers_detalhes": merge_bgp_peers_detalhes,
}


def merge_parsed(nome: str, por_comando: dict[str, list[dict]]) -> list[dict]:
    """Dispatch the merge by the resource name declared in the collector spec."""
    if nome not in _MERGES:
        raise KeyError(f"Merge desconhecido: {nome!r}")
    return _MERGES[nome](por_comando)
```

- [ ] **Step 4: Rodar para ver passar**

Run: `uv run pytest tests/automation/test_merge.py -q`
Expected: PASS (7 testes).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/parsers/huawei_vrp/merge.py tests/automation/test_merge.py
git commit -m "feat(automation): merge por recurso com shape estruturado e tipos normalizados

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Runner — spec multicomando/merge e slug de arquivo sem colisão

**Files:**
- Modify: `src/gerenet/automation/runner.py` (imports L1–14; `_nome_do_arquivo` L21–23; laço de coletores L90–106)
- Modify: `tests/automation/test_runner.py`

**Interfaces:**
- Consumes: `merge_parsed(nome, por_comando)` (T6); parsers T1–T4 via `parse_template`; `SAIDAS` (dict de saídas do fake de conexão).
- Produces: runner capaz de tratar specs `{"commands", "parsers": {comando: parser}, "merge"}`; `_nome_do_arquivo` novo (slug sem colisão entre `display bgp peer` e `display bgp ipv6 peer`); recursos `interfaces`/`bgp_peers` no snapshot quando o coletor existir (T8 ativa com os coletores reais).

O `_nome_do_arquivo` atual (`comando.split()[1]`) colide: `display bgp peer` e `display bgp ipv6 peer` viram ambos `bgp.txt`. Novo contrato (nomes legados preservados): remove o prefixo `display `, troca espaços por `-`, e qualquer caractere fora de `[0-9A-Za-z._-]` por `-` (`display current-configuration` → `current-configuration`, `display interface brief` → `interface-brief`, `display bgp ipv6 peer` → `bgp-ipv6-peer`, `display bgp peer 198.51.100.254 verbose` → `bgp-peer-198.51.100.254-verbose`).

- [ ] **Step 1: Escrever os testes (vermelho)**

Adicionar ao final de `tests/automation/test_runner.py`:

```python
def test_nome_do_arquivo_desambigua_comandos() -> None:
    from gerenet.automation.runner import _nome_do_arquivo

    assert _nome_do_arquivo("display version") == "version"
    assert _nome_do_arquivo("display current-configuration") == "current-configuration"
    assert _nome_do_arquivo("display interface brief") == "interface-brief"
    assert _nome_do_arquivo("display bgp peer") == "bgp-peer"
    assert _nome_do_arquivo("display bgp ipv6 peer") == "bgp-ipv6-peer"
    assert _nome_do_arquivo("display bgp peer 198.51.100.254 verbose") == "bgp-peer-198.51.100.254-verbose"


def test_coleta_multicomando_mergeia_no_snapshot(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gerenet.domain.models import DeviceSnapshot

    dev = _dev_com_grupo(db_session, "r6", "10.0.0.6")
    settings = Settings(_env_file=None, backups_dir=tmp_path)
    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    # Runner genérico: substitui o catálogo real por um coletor multicomando só.
    monkeypatch.setattr("gerenet.automation.runner.COLLECTORS", {"bgp_peers": {
        "commands": ["display bgp peer", "display bgp ipv6 peer"],
        "parsers": {"display bgp peer": "bgp_peer", "display bgp ipv6 peer": "bgp_peer"},
        "merge": "bgp_peers",
    }})
    monkeypatch.setitem(SAIDAS, "display bgp peer",
                        Path("tests/fixtures/huawei_vrp/ne8000_display_bgp_peer.txt").read_text(encoding="utf-8"))
    monkeypatch.setitem(SAIDAS, "display bgp ipv6 peer",
                        Path("tests/fixtures/huawei_vrp/ne8000_display_bgp_ipv6_peer.txt").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    peers = snap.resources["bgp_peers"]
    assert len(peers) == 22  # 12 v4 + 10 v6
    assert peers[0] == {"afi": "ipv4", "peer": "10.30.70.1", "asn": 64526,
                        "estado": "Idle(Admin)", "pref_rcv": 0, "up_down": "0655h07m"}
    assert peers[-1]["afi"] == "ipv6"
    assert peers[-1]["asn"] == 64528
    assert sorted(Path(p).name for p in snap.raw_files["bgp_peers"]) == [
        "bgp-ipv6-peer.txt", "bgp-peer.txt",
    ]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest tests/automation/test_runner.py -q`
Expected: FAIL — `test_nome_do_arquivo` (slug atual devolve `bgp`/`peer`) e o teste multicomando (o runner ignora `parsers`/`merge` e grava `{"backup": True}` em `resources["bgp_peers"]` — ou falha com o legado `spec["parser"]` ausente → KeyError capturado como erro do coletor, status `error`).

- [ ] **Step 3: Implementar o runner**

Em `src/gerenet/automation/runner.py`:

1. Imports — trocar:

```python
import secrets
```

por:

```python
import re
import secrets
```

e trocar a linha do import do registry por (ordem alfabética — merge antes de registry):

```python
from gerenet.automation.parsers.huawei_vrp.merge import merge_parsed
from gerenet.automation.parsers.huawei_vrp.registry import parse_template
```

2. `_nome_do_arquivo` — trocar o corpo atual (L21–23) por:

```python
def _nome_do_arquivo(comando: str) -> str:
    """Stable file slug for the collected command (ex.: `bgp-ipv6-peer.txt`)."""
    nome = comando.removeprefix("display ").replace(" ", "-")
    return re.sub(r"[^0-9A-Za-z._-]+", "-", nome) or "output"
```

3. Laço de coletores — trocar o bloco atual (L90–106, que começa em `for nome, spec in COLLECTORS.items():` e termina no `except Exception as exc:  # noqa: BLE001 — falha de recurso vira erro no dict`) por:

```python
            for nome, spec in COLLECTORS.items():
                try:
                    saidas = _conectar_e_executar(dev, cred["username"], cred["password"], spec["commands"], settings)
                    lista_arquivos: list[str] = []
                    for comando, saida in saidas.items():
                        caminho = base / nome / f"{_nome_do_arquivo(comando)}.txt"
                        caminho.parent.mkdir(parents=True, exist_ok=True)
                        caminho.write_text(saida, encoding="utf-8")
                        lista_arquivos.append(str(caminho))
                    arquivos_brutos[nome] = lista_arquivos
                    if spec.get("parser"):
                        # Simple resource: one command, one parse, first record as dict.
                        linhas = parse_template(spec["parser"], saidas[spec["commands"][0]])
                        recursos[nome] = linhas[0] if linhas else {"erro": "Saída sem registros parseáveis."}
                    elif spec.get("parsers"):
                        # Multi-command resource: per-command parser + merge into the shape.
                        por_comando = {
                            comando: parse_template(spec["parsers"][comando], saidas[comando])
                            for comando in spec["commands"]
                        }
                        recursos[nome] = merge_parsed(spec["merge"], por_comando)
                    else:
                        recursos[nome] = {"backup": True}
                except Exception as exc:  # noqa: BLE001 — falha de recurso vira erro no dict
                    erros[nome] = str(exc)
```

- [ ] **Step 4: Rodar para ver passar**

Run: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest tests/automation/test_runner.py -q`
Expected: PASS — os dois novos testes e os legados (a troca `spec["parser"]` → `spec.get("parser")` preserva `version`/`config_backup`).

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/runner.py tests/automation/test_runner.py
git commit -m "feat(automation): runner com specs multicomando/merge e slug de arquivo sem colisao

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Coletores reais `interfaces` e `bgp_peers` + integração do snapshot estruturado

**Files:**
- Modify: `src/gerenet/automation/collectors.py` (arquivo inteiro)
- Modify: `tests/automation/test_runner.py` (`SAIDAS` estendido + teste de integração + teste de status parcial)

**Interfaces:**
- Consumes: parsers `int_brief`/`ip_int_brief`/`ipv6_int_brief` (T1–T3) e `bgp_peer` (T4); merges `interfaces`/`bgp_peers` (T6); runner multicomando (T7).
- Produces: entradas `COLLECTORS["interfaces"]` e `COLLECTORS["bgp_peers"]` (spec §4.1) → `resources["interfaces"]` (38 interfaces canônicas nas fixtures) e `resources["bgp_peers"]` (22 peers com tipos), consumidos pela divergência (B2). A extensão de `SAIDAS` no mesmo commit é obrigatória: os testes legados de runner rodam a coleta completa e o fake de conexão devolve `{cmd: SAIDAS[cmd]}` — sem as novas chaves, `KeyError`.

Comando no coletor: a spec §4.1 escreve a abreviatura `display ipv6 int brief`; o comando real enviado ao equipamento é a forma completa `display ipv6 interface brief` (o parser se chama `ipv6_int_brief` — o slug do arquivo bruto fica `ipv6-interface-brief.txt`).

- [ ] **Step 1: Escrever o teste de integração (vermelho)**

Substituir em `tests/automation/test_runner.py` o bloco `SAIDAS` atual (L20–25) por (o helper lê as fixtures — uma fonte única; as chaves novas são as dos comandos dos coletores novos):

```python
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "huawei_vrp"


def _texto_fixture(nome: str) -> str:
    return (_FIXTURES / nome).read_text(encoding="utf-8")


# Saídas que o fake de conexão devolve, por comando — como o connect_and_run real,
# que só devolve o que recebeu na lista `commands`.
SAIDAS = {
    "display version": VERSION_SAIDA,
    "display current-configuration": "sysname r1\n#\n",
    "display interface brief": _texto_fixture("ne8000_display_interface_brief.txt"),
    "display ip interface brief": _texto_fixture("ne8000_display_ip_interface_brief.txt"),
    "display ipv6 interface brief": _texto_fixture("ne8000_display_ipv6_interface_brief.txt"),
    "display bgp peer": _texto_fixture("ne8000_display_bgp_peer.txt"),
    "display bgp ipv6 peer": _texto_fixture("ne8000_display_bgp_ipv6_peer.txt"),
}
```

Adicionar ao final de `tests/automation/test_runner.py`:

```python
def test_coleta_completa_registra_snapshot_estruturado(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = _dev_com_grupo(db_session, "r7", "10.0.0.7")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    # version/config_backup legados preservados; novos recursos adicionados.
    assert snap.resources["version"]["version"] == "8.210"
    assert snap.resources["config_backup"]["backup"] is True
    # O coletor dirigido pelo SoT (bgp_peers_verbose) chega na T9, junto com o
    # ramo alvo_sessoes do runner; sem sessões ativas o recurso é pulado (§4.1/§12).
    assert "bgp_peers_detalhes" not in snap.resources
    assert set(snap.raw_files) == {"version", "config_backup", "interfaces", "bgp_peers"}

    interfaces = snap.resources["interfaces"]
    assert len(interfaces) == 38  # união canônica das três tabelas das fixtures
    assert interfaces[0]["nome"] == "100GE0/1/53"  # ordenada por nome canônico
    por_nome = {interface["nome"]: interface for interface in interfaces}
    assert por_nome["LoopBack0"] == {
        "nome": "LoopBack0", "phy": "up", "protocolo": "up(s)",
        "enderecos_v4": ["203.0.113.1/32"], "enderecos_v6": ["2001:DB8::1/128"], "vpn": None,
    }
    assert por_nome["GigabitEthernet0/1/0.1003"] == {
        "nome": "GigabitEthernet0/1/0.1003", "phy": "down", "protocolo": "down",
        "enderecos_v4": ["10.254.101.29/30"], "enderecos_v6": ["2001:DB8:1111::51/126"],
        "vpn": None,
    }  # sufixo (10G) do interface brief não duplica a entrada
    assert por_nome["Eth-Trunk127.582"]["phy"] == "*down"
    assert por_nome["Eth-Trunk127.582"]["enderecos_v4"] == ["172.25.2.69/31"]
    assert por_nome["Eth-Trunk127.582"]["enderecos_v6"] == ["FC00::2B7/127"]
    assert por_nome["Eth-Trunk127.97653"]["enderecos_v4"] == []  # só no interface brief
    assert por_nome["Eth-Trunk127.97653"]["enderecos_v6"] == []

    peers = snap.resources["bgp_peers"]
    assert len(peers) == 22  # 12 v4 + 10 v6
    assert peers[0]["afi"] == "ipv4"
    assert peers[-1] == {"afi": "ipv6", "peer": "FDFF::198:18:255:0", "asn": 64528,
                         "estado": "Active", "pref_rcv": 0, "up_down": "0655h07m"}

    assert sorted(Path(p).name for p in snap.raw_files["interfaces"]) == [
        "interface-brief.txt", "ip-interface-brief.txt", "ipv6-interface-brief.txt",
    ]
    assert sorted(Path(p).name for p in snap.raw_files["bgp_peers"]) == [
        "bgp-ipv6-peer.txt", "bgp-peer.txt",
    ]


def test_coleta_recurso_falho_vira_status_parcial(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falha de parse num recurso não derruba a coleta: status parcial + erro por recurso (§4.3)."""
    dev = _dev_com_grupo(db_session, "r8", "10.0.0.8")
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr("gerenet.automation.runner._conectar_e_executar",
                        lambda device, username, password, commands, settings: {
                            cmd: SAIDAS[cmd] for cmd in commands
                        })
    # Comando ausente do fake: o KeyError vira erro só do coletor bgp_peers.
    monkeypatch.delitem(SAIDAS, "display bgp ipv6 peer")

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "partial"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    assert "bgp_peers" in snap.errors
    assert snap.resources["interfaces"]  # os demais recursos sobreviveram
    assert "bgp_peers" not in snap.resources
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest tests/automation/test_runner.py -q`
Expected: FAIL — os dois testes novos: o catálogo real ainda não tem `interfaces`/`bgp_peers`, então `resources` não tem as chaves e `raw_files` não tem os diretórios (asserts de conjunto e de conteúdo falham). Os testes legados seguem verdes: o fake de conexão só devolve as chaves que os coletores existentes pedem — com o SAIDAS estendido mas o catálogo ainda com 2 entradas, nada muda no caminho legado.

- [ ] **Step 3: Ampliar o catálogo de coletores**

Substituir o conteúdo de `src/gerenet/automation/collectors.py` (hoje 5 linhas) por (o coletor `bgp_peers_verbose`, dirigido pelo SoT, entra na T9 **junto com** o ramo `alvo_sessoes` do runner — um único passo atômico, sem estado intermediário quebrado):

```python
"""Read-only collector catalog (allowlist).

Each entry declares the commands to run and how to parse/merge them:
- `parser` (legacy): single command, single parse, first record as dict.
- `parsers` + `merge`: one parser per command; `merge_parsed` combines rows
  into the resource shape (spec §4.3).
"""

COLLECTORS = {
    "version": {"commands": ["display version"], "parser": "version", "backup": False},
    "config_backup": {"commands": ["display current-configuration"], "parser": None, "backup": True},
    "interfaces": {
        "commands": [
            "display interface brief",
            "display ip interface brief",
            "display ipv6 interface brief",
        ],
        "parsers": {
            "display interface brief": "int_brief",
            "display ip interface brief": "ip_int_brief",
            "display ipv6 interface brief": "ipv6_int_brief",
        },
        "merge": "interfaces",
    },
    "bgp_peers": {
        "commands": ["display bgp peer", "display bgp ipv6 peer"],
        "parsers": {"display bgp peer": "bgp_peer", "display bgp ipv6 peer": "bgp_peer"},
        "merge": "bgp_peers",
    },
}
```

- [ ] **Step 4: Rodar para ver passar**

Run: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest tests/automation -q`
Expected: PASS — legados + T7 + integração (38 interfaces canônicas, 22 peers) + recurso-falho-parcial.

- [ ] **Step 5: Commit**

```bash
git add src/gerenet/automation/collectors.py tests/automation/test_runner.py
git commit -m "feat(automation): coletores interfaces e bgp_peers (snapshot estruturado 38 interfaces/22 peers)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: Coletor `bgp_peers_verbose` dirigido pelo SoT (cap 50) + ramo dinâmico no runner

**Files:**
- Modify: `src/gerenet/automation/collectors.py` (docstring + entrada `bgp_peers_verbose` + função `comandos_verbose`)
- Modify: `src/gerenet/automation/runner.py` (import de `comandos_verbose`; laço L90–106 com comandos dinâmicos)
- Modify: `tests/automation/test_runner.py` (teste de integração com sessões BGP seedadas no SoT)

**Interfaces:**
- Consumes: parser `bgp_peer_verbose` (T5); `merge_parsed`/`merge_bgp_peers_detalhes` (T6); runner multicomando (T7); catálogo com `interfaces`/`bgp_peers` (T8); modelos `BgpSession`/`Circuit`/`Organization`/`Site` (SoT); helpers `_dev_com_grupo`, `SAIDAS`, `_texto_fixture`.
- Produces: `comandos_verbose(spec: dict, device_id: int, session: Session) -> list[str]` e `resources["bgp_peers_detalhes"]` no snapshot — chaves `{afi, peer, descricao, filtro_import, filtro_export}` com `None` para ausentes — consumidos pela divergência BGP (B2) e pela visão de sessões do ciclo C.

Spec §4.1: o recurso consulta `display bgp [ipv6] peer <ip> verbose` **só dos peers de sessões ativas do device** (SoT), com cap 50. Spec §12: sem sessões ativas o recurso é **pulado** (a coleta não falha). A consulta ordena por afi depois endereço remoto e limita com `cap`, tornando o custo proporcional às sessões, nunca à tabela de peers.

- [ ] **Step 1: Escrever o teste de integração (vermelho)**

Adicionar ao final de `tests/automation/test_runner.py`:

```python
def test_bgp_peers_verbose_so_sessoes_ativas_do_device(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O comando verbose nasce do SoT: 1 por sessão ativa (afi, endereço remoto),
    excluindo shutdown, em ordem ipv4 -> ipv6 (spec §4.1/§12)."""
    from gerenet.domain.models import BgpSession, Circuit, DeviceSnapshot, Organization, Site

    dev = _dev_com_grupo(db_session, "edge-t9", "10.0.0.99")
    site = Site(name="site-t9")
    org = Organization(name="org-t9", asn=64531)
    db_session.add_all([site, org])
    db_session.commit()
    # Circuito mínimo: só os NOT NULL do modelo; os demais campos têm default.
    circuito = Circuit(
        code="C-T9", organization_id=org.id, site_id=site.id,
        access_device_id=dev.id, access_port="GE0/0/1", edge_device_id=dev.id,
    )
    db_session.add(circuito)
    db_session.commit()

    def sessao(afi: str, remoto: str, shutdown: bool = False) -> BgpSession:
        # Só os NOT NULL de BgpSession (L349-353/356); asn_local fica None e o
        # serviço o resolveria pelo device — aqui o filtro não o consulta.
        return BgpSession(
            circuit_id=circuito.id, device_id=dev.id, afi=afi,
            local_address="203.0.113.1", remote_address=remoto,
            asn_remote=64531, shutdown=shutdown,
        )

    # 2 ativas (v4 e v6 — mesmos peers das fixtures verbose) + 1 em shutdown.
    db_session.add_all([
        sessao("ipv4", "198.51.100.254"),
        sessao("ipv6", "2001:DB8:8000:0:198:51:100:254"),
        sessao("ipv6", "2001:DB8::99", shutdown=True),
    ])
    db_session.commit()
    settings = Settings(_env_file=None, backups_dir=tmp_path)

    monkeypatch.setattr("gerenet.automation.runner.VaultSecretStore", VaultFake)
    monkeypatch.setattr(
        "gerenet.automation.runner._conectar_e_executar",
        lambda device, username, password, commands, settings: {cmd: SAIDAS[cmd] for cmd in commands},
    )
    monkeypatch.setitem(SAIDAS, "display bgp peer 198.51.100.254 verbose",
                        _texto_fixture("ne8000_display_bgp_peer_verbose.txt"))
    monkeypatch.setitem(SAIDAS, "display bgp ipv6 peer 2001:DB8:8000:0:198:51:100:254 verbose",
                        _texto_fixture("ne8000_display_bgp_ipv6_peer_verbose.txt"))

    resultado = run_collection(dev.id, settings=settings, session_override=db_session)
    assert resultado["status"] == "success"

    snap = db_session.query(DeviceSnapshot).filter_by(device_id=dev.id).first()
    assert snap.resources["bgp_peers_detalhes"] == [
        {"afi": "ipv4", "peer": "198.51.100.254", "descricao": "UPSTREAM-FNA",
         "filtro_import": "ASN64531-V4-IMPORT", "filtro_export": "XPL-UPSTREAM-AS64531-V4-EXPORT"},
        {"afi": "ipv6", "peer": "2001:DB8:8000:0:198:51:100:254", "descricao": "UPSTREAM-v6",
         "filtro_import": "ASN64531-V6-IMPORT", "filtro_export": "XPL-UPSTREAM-AS64531-V6-EXPORT"},
    ]  # ordem do SoT: afi ipv4 antes de ipv6
    assert sorted(Path(p).name for p in snap.raw_files["bgp_peers_verbose"]) == [
        "bgp-ipv6-peer-2001-DB8-8000-0-198-51-100-254-verbose.txt",
        "bgp-peer-198.51.100.254-verbose.txt",
    ]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest tests/automation/test_runner.py::test_bgp_peers_verbose_so_sessoes_ativas_do_device -q`
Expected: FAIL — o catálogo e o runner ainda não conhecem `bgp_peers_verbose`: `snap.raw_files["bgp_peers_verbose"]` levanta KeyError.

- [ ] **Step 3: Implementar coletor dinâmico + ramo no runner**

**3a. `src/gerenet/automation/collectors.py`** — trocar a docstring e o fim do arquivo: a docstring ganha o bullet `alvo_sessoes`, o catálogo ganha a entrada `bgp_peers_verbose` e o arquivo ganha a função:

```python
"""Read-only collector catalog (allowlist) and SoT-driven dynamic commands.

Each entry declares the commands to run and how to parse/merge them:
- `parser` (legacy): single command, single parse, first record as dict.
- `parsers` + `merge`: one parser per command; `merge_parsed` combines rows
  into the resource shape (spec §4.3).
- `alvo_sessoes`: dynamic target — `comandos_verbose` derives the commands
  from the device's active BGP sessions in the Source of Truth.
"""
from sqlalchemy.orm import Session

from gerenet.domain.models import BgpSession

COLLECTORS = {
    "version": {"commands": ["display version"], "parser": "version", "backup": False},
    "config_backup": {"commands": ["display current-configuration"], "parser": None, "backup": True},
    "interfaces": {
        "commands": [
            "display interface brief",
            "display ip interface brief",
            "display ipv6 interface brief",
        ],
        "parsers": {
            "display interface brief": "int_brief",
            "display ip interface brief": "ip_int_brief",
            "display ipv6 interface brief": "ipv6_int_brief",
        },
        "merge": "interfaces",
    },
    "bgp_peers": {
        "commands": ["display bgp peer", "display bgp ipv6 peer"],
        "parsers": {"display bgp peer": "bgp_peer", "display bgp ipv6 peer": "bgp_peer"},
        "merge": "bgp_peers",
    },
    "bgp_peers_verbose": {
        "alvo_sessoes": True,
        "cap": 50,
        "parser_alvo": "bgp_peer_verbose",
        "merge": "bgp_peers_detalhes",
    },
}


def comandos_verbose(spec: dict, device_id: int, session: Session) -> list[str]:
    """One verbose command per active SoT session of the device (spec §4.1/§12).

    Sessions with admin_status on and shutdown off, ordered by afi then remote
    address, capped (the cap bounds cost per device). No sessions -> empty
    list: the runner skips the resource instead of failing the collection.
    """
    linhas = (
        session.query(BgpSession.afi, BgpSession.remote_address)
        .filter(
            BgpSession.device_id == device_id,
            BgpSession.admin_status.is_(True),
            BgpSession.shutdown.is_(False),
        )
        .distinct()
        .order_by(BgpSession.afi, BgpSession.remote_address)
        .limit(spec.get("cap", 50))
        .all()
    )
    return [
        f"display bgp {'ipv6 ' if afi == 'ipv6' else ''}peer {remoto} verbose"
        for afi, remoto in linhas
    ]
```

**3b. `src/gerenet/automation/runner.py`** — trocar a linha do import dos coletores:

```python
from gerenet.automation.collectors import COLLECTORS, comandos_verbose
```

e trocar o laço de coletores (bloco da T7, que começa em `for nome, spec in COLLECTORS.items():` e termina no `except Exception as exc:  # noqa: BLE001 — falha de recurso vira erro no dict`) por:

```python
            for nome, spec in COLLECTORS.items():
                try:
                    if spec.get("alvo_sessoes"):
                        # SoT-driven commands: one verbose command per active BGP
                        # session of the device (spec §4.1); no sessions -> the
                        # resource is skipped, the collection does not fail (§12).
                        comandos = comandos_verbose(spec, dev.id, session)
                        if not comandos:
                            continue
                    else:
                        comandos = spec["commands"]
                    saidas = _conectar_e_executar(dev, cred["username"], cred["password"], comandos, settings)
                    lista_arquivos: list[str] = []
                    for comando, saida in saidas.items():
                        caminho = base / nome / f"{_nome_do_arquivo(comando)}.txt"
                        caminho.parent.mkdir(parents=True, exist_ok=True)
                        caminho.write_text(saida, encoding="utf-8")
                        lista_arquivos.append(str(caminho))
                    arquivos_brutos[nome] = lista_arquivos
                    if spec.get("parser"):
                        # Simple resource: one command, one parse, first record as dict.
                        linhas = parse_template(spec["parser"], saidas[spec["commands"][0]])
                        recursos[nome] = linhas[0] if linhas else {"erro": "Saída sem registros parseáveis."}
                    elif spec.get("parsers"):
                        # Multi-command resource: per-command parser + merge into the shape.
                        por_comando = {
                            comando: parse_template(spec["parsers"][comando], saidas[comando])
                            for comando in comandos
                        }
                        recursos[nome] = merge_parsed(spec["merge"], por_comando)
                    elif spec.get("alvo_sessoes"):
                        # SoT-targeted resource: the same parser for every session command.
                        por_comando = {
                            comando: parse_template(spec["parser_alvo"], saidas[comando])
                            for comando in comandos
                        }
                        recursos[nome] = merge_parsed(spec["merge"], por_comando)
                    else:
                        recursos[nome] = {"backup": True}
                except Exception as exc:  # noqa: BLE001 — falha de recurso vira erro no dict
                    erros[nome] = str(exc)
```

- [ ] **Step 4: Rodar para ver passar**

Run: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest tests/automation/test_runner.py -q`
Expected: PASS — o novo teste e todos os legados (r1–r8). Nos legados não há sessões BGP no SoT → o ramo pula `bgp_peers_verbose` **antes** de conectar; nenhuma chave nova de SAIDAS é necessária e o assert de `raw_files` do teste de integração da T8 (4 chaves) segue válido.

- [ ] **Step 5: Verificação final (suíte completa + ruff)**

Run: `GERENET_REDIS_URL=redis://localhost:6379/15 uv run pytest -q` e `uv run ruff check`
Expected: suíte completa verde (todos os testes do repo contra `gerenet_test`) e ruff limpo.

- [ ] **Step 6: Commit**

```bash
git add src/gerenet/automation/collectors.py src/gerenet/automation/runner.py tests/automation/test_runner.py
git commit -m "feat(automation): coletor bgp_peers_verbose dirigido pelas sessoes ativas do SoT (cap 50)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Encerramento

Após a T9: rodar `graphify update .` na raiz do repo (hook — manter o grafo atualizado após mudanças de código) e reportar o fim do plano B1. A execução do ciclo B continua no plano B2 (renderização de nomes §25.4 + templates Jinja2 + divergência + migration `circuits.edge_trunk` + import de seed + API/CLI), dependente deste plano (os shapes de `resources` e os merges são consumidos pela divergência).
