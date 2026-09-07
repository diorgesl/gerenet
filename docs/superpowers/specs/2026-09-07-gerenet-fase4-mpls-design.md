# Design — Fase 4: MPLS nos switches (gerenet)

> Especificação da **fase 4** do gerenet — domínios MPLS/LDP, serviço **L2VC**
> (ponto a ponto entre 2 switches, com provisionamento via fluxo de mudança
> controlada) e serviço **VSI** (multiponto — somente modelo + consulta de
> estado neste ciclo, §23). Documentos-fonte: spec §9.1–9.4, §10, §12–13,
> §14–16, §21, §23–24; decisões do brainstorming 2026-09-07 (registradas na
> §11); designs do ciclo D (mudança controlada) e B1/B2 (parsers/render).

## 1. Objetivo e escopo

Fechar os itens MPLS pendentes do MVP (§23): criar/editar **domínio MPLS/LDP**,
**serviço L2VC** (duas pontas, reservas de VC-ID/VLAN, validações §9.2),
**gerar e executar** o provisionamento e a remoção do L2VC nos dois switches
por meio de **uma única change request** (mesma mudança lógica, §9.3), com
pós-validação; e **consultar** VSI (modelo + coleta/estado, sem gerar config).

Fora do escopo desta fase (notas de YAGNI na §10): provisionamento de VSI;
upstreams; encapsulamento `ethernet` (raw) se não for usado no ambiente
(ficou como opcional ao encap `vlan`/`vlan-vpls`); NetBox; métricas
Prometheus; reconciliação automática; dupla aprovação por criticidade.

## 2. Contexto (verificado em 2026-09-07)

- **Não existe nenhum modelo MPLS**: `models.py` vai até `Approval`; §14
  prevê `mpls_domains`, `l2vc_services`, `vsi_services`, `service_endpoints`,
  `allocations` — nenhum materializado.
- **`ChangeRequest` é preso a `circuit_id`** (`nullable=False`, models.py) e o
  fluxo do ciclo D (estados, steps por device, aprovação única, rollback
  inverso, `reconciliar` para `erro|parcial`) é circuitocêntrico. `ChangeStep`
  já é por device — é a base para a CR de L2VC com 2 steps.
- **Reserva de recursos**: `ipam.reservar_circuito` aloca `Vlan`/`IpPrefix`
  com constraints UNIQUE (vlans: `(site_id, vid)`, kind `vlan`|`s_vlan`);
  sem tabela `allocations` genérica.
- **Coleta/parsers**: `COLLECTORS` (allowlist read-only + dinâmicos) e parsers
  TextFSM em `parsers/huawei_vrp/textfsm/` + `merge.py`; snapshot por device
  com `resources`; `display bgp peer` já parseado.
- **Render**: `render_desejado` orquestra blocos (`BlocoRender{tipo, objeto,
  objeto_id, comandos}`) via templates Jinja2 em `automation/templates/
  huawei_vrp/`; `changes.py` faz diff bloco × snapshot e `removal.py` o
  inverso; `plan_provision(circ)` → `PlanoDevice` por device.
- **Worker**: fila `gerenet-change`, lock por device, backup pré-mudança,
  re-diff na execução, pós-cheque `reconciliar_device`, classificação
  `aplicado|com_divergencia|parcial|erro`; sempre interrompe em erro do VRP.
- **Web**: páginas por entidade; `Modal`/`ConfirmDialog`; "Solicitar mudança"
  em circuito/sessão; CLI Typer por entidade.

## 3. Modelo de dados

Tabelas novas (uma migração Alembic):

**`mpls_domains`** — `name` (unique), `description?`, `admin_status` (default
true), `created_at`, `updated_at`. Slável de estado: §9.1 pede PE, loopbacks
LDP e interfaces de core — o domínio não guarda esses campos; ficam na
associação de membros.

**`mpls_domain_members`** — `domain_id` FK, `device_id` FK, `loopback_address`
(peer LDP / remote do L2VC; obrigatório), `role` enum (`pe`|`core`, default
`pe`), UNIQUE(domain_id, device_id). O `Device` atual não tem loopback/domínio
MPLS — essa associação carrega os dados sem tocar no model de devices.

**`l2vc_services`** — `domain_id` FK, `vc_id` int, `name` (lógico, unique por
domínio), `organization_id?` FK (cliente/finalidade), `mtu` (default 1500),
`control_word` bool (default false), `flow_label` bool (default false),
`redundancy` text opcional (§9.2), `description?`, `admin_status`,
`operational_status` enum (`unknown|up|down|partial`, default `unknown`),
`last_collected_at?`, timestamps; **UNIQUE(domain_id, vc_id)** e
UNIQUE(domain_id, name).

**`service_endpoints`** — genérico (§14): `kind` enum (`l2vc`|`vsi`),
`l2vc_id?` FK, `vsi_id?` FK (exatamente um dos dois, validado no serviço),
`device_id` FK, `interface` (string — interfaces vêm da coleta; sem FK),
`encapsulation` enum (`dot1q`|`qinq`|`ethernet_raw` — `ethernet_raw` existe no
enum por extensibilidade, mas o serviço deste ciclo **só aceita** `dot1q`/`qinq`;
ver §11), `vlan_id?` FK `vlans`,
`inner_vlan?` int (QinQ — espaço do cliente, não reservado), `mtu?`,
`operational_status` enum (default `unknown`), timestamps.

**`vsi_services`** — `domain_id` FK, `vsi_id` int, `name` lógico, `vrp_name`
(derivado via naming, único — identidade VRP), `signaling` enum default `ldp`,
`mtu`, `split_horizon` bool, `mac_learning` bool default true, `mac_limit?` int,
`admin_status`, `operational_status` enum, `last_collected_at?`, timestamps;
UNIQUE(domain_id, vsi_id) e UNIQUE(domain_id, vrp_name).

**`vsi_members`** — `vsi_id` FK, `device_id` FK, UNIQUE(vsi_id, device_id).
Status por pseudowire/AC na fase atual: campo agregado no VSI
(`operational_status` + `last_collected_at`) — sem tabela de estados por PW
(YAGNI até o provisionamento).

**VLANs de AC** (Q2): reuso da tabela `vlans` existente com **novo valor
`mpls_ac`** no enum `vlan_kind` (ALTER TYPE ADD VALUE) — `site_id` = site do
device da ponta, `device_id` = switch da ponta, `circuit_id` NULL,
`status='reservada'`. **Escopo é por device** (a VLAN do switch é local ao
equipamento, não ao POP): `device_id` nullable na tabela; a UNIQUE existente
passa a ser **índice parcial** `(site_id, vid) WHERE device_id IS NULL`
(linhas de circuito, inalterada de fato) + **índice parcial**
`(device_id, vid) WHERE device_id IS NOT NULL` (linhas MPLS). Mesmo VID é
permitido em devices diferentes do mesmo POP; dois serviços no **mesmo**
switch com o mesmo VID é bloqueado (correto). VSI multiponto com o mesmo VID
nas pontas = duas linhas (uma por device), cada uma referenciada pelo seu
endpoint. Ajuste correlato: validadores de circuito (`_primeiro_vid` e afins)
passam a filtrar somente linhas sem `device_id`, preservando o escopo de site
atual.

## 4. Alocação (IDAM simples)

Sem tabela genérica (Q2): helpers no serviço de domínio/MPLS:

- `proximo_vc_id(session, domain_id)` — próximo livre no intervalo
  (máx +1, com busca sequencial). A duplicidade é garantida pela UNIQUE do
  banco; o helper é conveniência/UX.
- `proximo_vsi_id(session, domain_id)` — idem.
- `reservar_vlan_ac(session, service_endpoint)` — padrão `reservar_circuito`:
  cria a linha `vlans` (`kind='mpls_ac'`, site e device da ponta, vid livre no
  device), idempotente (ponta já com VLAN ⇒ no-op auditado); outra linha
  `mpls_ac` no mesmo device com o mesmo vid ⇒ ConflictError.

## 5. ChangeRequest generalizado (Q1)

- `circuit_id` vira **nullable**; novos campos: `escopo` enum
  (`circuito`|`l2vc`|`vsi` — `vsi` reservado, sem CR neste ciclo) default
  `circuito`, `l2vc_id?` FK. Migração: backfill `escopo='circuito'` nas
  linhas existentes (circuit_id inalterado).
- `ChangeRequestCreate`: `escopo` opcional default `circuito`; `circuit_id`
  ou `l2vc_id` conforme o escopo. API `POST /change-requests` e CLI
  `gerenet change-requests add [--escopo l2vc --l2vc-id N]`.
- **Máquina de estados e runner intocados**: CR de L2VC nasce com 2 steps
  (A/B); lock por device, backup, re-diff e pós-check são por step; o status
  `parcial` da CR já significa §9.3 ("uma ponta falhou ⇒ parcialmente
  provisionado"). `rollback`/`reconciliar` não mudam.
- Validações de criação: CR `circuito` exige circuito ativo (como hoje); CR
  `l2vc` exige serviço com `admin_status` ativo, domínio ativo e pelo menos
  um plano não vazio (`PlanoVazio` com mensagem específica, padrão atual).

Regressão garantida: testes do ciclo D continuam passando com `escopo`
default; `circuit_id` nullable não altera o caminho existente.

## 6. Render, plano e códigos L2VC

Templates novos em `automation/templates/huawei_vrp/`:

- `l2vc_ac.j2` — subinterface/AC: `interface <if>.<vid>` + `mpls l2vc
  <vc-id> encapsulation vlan remote <loopback-do-par> [control-word]
  [mtu <n>]`; QinQ vira `... encapsulation vlan-vpls` com `inner-vlan` (a
  forma exata do comando por versão VRP é validada em lab — §9.2 exige
  capacidade por equipamento, ver §7).
- `vsi_...` — **nenhum** neste ciclo (só consulta).

`automation/l2vc.py` (novo):

- `naming.vsi_nome(name_logico, vsi_id)` → `VSI-<SIGLA>-<ID>` (≤ 63 chars,
  maiúsculas, separador `-`, sigla do nome lógico sanitizada — padrão
  `naming.pfx_produto`); é o `vrp_name` único do VSI. L2VC não tem nome VRP
  (identidade é o VC-ID; nome lógico só na UI).
- `render_l2vc(session, service)` → blocos por device (A e B) derivados da
  SoT via templates, idempotente por construção (padrão do `render.py`).
- `plan_provision_l2vc(session, service)` → `list[PlanoDevice]` (2 steps),
  diff contra o snapshot da última coleta (maquinário de `changes.py`:
  bloco presente ⇒ skip; sem snapshot/pre-checks ⇒ regra atual).
- `plan_remocao_l2vc(session, service)` → render inverso (padrão
  `removal.py`), com os blocos de remoção por ponta.

Pré-checks de execução (§12.2 "peer alcançável" + §9.2):
`valida_pre_checks_l2vc(service, snapshot_por_device)` — peer LDP do par
presente/UP na coleta, sem binding conflitante no `display l2vc` coletado,
MTU/encap simétricos entre pontas (regra de negócio já imposta na criação,
re-verificada na execução). Falha ⇒ step `erro` sem tocar o device
(mesmo padrão de bloqueio do ciclo D).

Pós-check: `display l2vc` pós-aplicação ⇒ estado `up` e simetria ⇒
`aplicado`; divergência ⇒ `com_divergencia`; senão `parcial`/`erro`
(padrão `reconciliar_device` do ciclo D).

## 7. Capacidades e versões

Regra §5: não gerar comandos incompatíveis com família/versão. Para o MVP:
`flow_label` renderizado **somente** se a capacidade do equipamento
indicar suporte (campo `capabilities` do Device — mecanismo do ciclo B2) e
`control-word` se marcado. A validação de lab (runbook) confirma os comandos
contra os switches alvo (família S, VRP V2xx). Se o comportamento divergir
por versão, a solução é nova template por versão (padrão já existente).

## 8. Coleta e parsers

`collectors.py` (novas entradas read-only, tolerantes a vazio — shape vazio
não falha a coleta, padrão atual):

- `mpls_ldp_peer` → `display mpls ldp peer` (comandos das sessões do domínio).
- `l2vc` → `display l2vc` (estado por VC-ID/interface).
- `vsi` → `display vsi` (nome, ID, estado por VSI).

Parsers TextFSM novos em `parsers/huawei_vrp/textfsm/` + `merge.py` (funções
de merge por recurso), com fixtures dos outputs reais (obtidas no lab — §10).
Os recursos alimentam: diff do plano L2VC (encontrado), pré-checks e a
**consulta de VSI** (estado por serviço, último `last_collected_at`).

## 9. Web e CLI

- **Nav**: grupo novo **"MPLS"** → `Domínios` (`/mpls/domains`), `Serviços
  L2VC` (`/mpls/l2vc`), `VSIs` (`/mpls/vsi`).
- **Domínios**: CRUD + membros (device + loopback + role) em `Modal`
  (padrão C3); detalhe com recursos usados (VC-IDs/VSI-IDs tomados).
- **L2VC**: lista com badges admin/operacional; detalhe com pontas (device,
  interface, encap, VLAN + inner) e diff da última coleta; botão
  **"Solicitar mudança"** → CR `rascunho` (tela de CR existente reutilizada,
  sem mudança de UI).
- **VSI**: lista + detalhe somente leitura (PEs, ACs, estado coletado).
- **Dashboard**: card "Serviços MPLS" (contagem L2VC/VSI por estado) —
  endereça o §20 sem métricas completas.
- **CLI**: `gerenet mpls domain add|list|add-member|remove-member`,
  `l2vc add|list|show|set-status`, `vsi list|show` (criar VSI por web/CLI;
  sem provisionar). `gerenet change-requests add --escopo l2vc --l2vc-id N`.

## 10. Testes e validação em lab

Automatizados (padrão do repo — pytest/ruff/vitest/e2e):

- **Domínio/validações**: VC-ID duplicado no domínio (409), VLAN ocupada no
  site, simetria encap/MTU entre pontas (ValidationError), pontas no mesmo
  domínio e devices distintos, loopback obrigatório, VSI nome VRP único,
  ponta `mpls_ac` com `site_id` do device.
- **Render**: dot1q e QinQ, ambos os lados, idempotência (segunda chamada =
  zero diffs), `flow_label` condicionado a capacidade.
- **Parsers**: fixtures `display mpls ldp peer` / `display l2vc` /
  `display vsi` (vazio, cheio, estado up/down).
- **Fluxo CR**: criar L2VC ⇒ CR com 2 steps; execução A ok + B falha ⇒
  `parcial`; remoção inversa; `reconciliar` reabre só steps pendentes;
  rollback CR inversa; idempotência (reexecução ⇒ skip).
- **API/CLI/web**: CRUD + 409 + `--escopo l2vc`; Vitest das 3 páginas e nav;
  fumo e2e: criar domínio + L2VC e "Solicitar mudança" (sem execução).

**Validação em equipamento real — produção, sem lab** (decisão do usuário em
2026-09-07: há switches de produção disponíveis; nada impede subir L2VC/VSI
de teste neles — segue a implantação gradual do §21):
1. Task **read-only** contra switches reais (família S): comandos MPLS/L2VC
   e outputs de `display` — ajusta templates/parsers e documenta no
   `docs/runbook-validacao-switch-mpls.md`.
2. Geração sem execução, revisada pelo usuário (diff por bloco na CR em
   `rascunho`), antes de qualquer execução.
3. Execução de teste: **serviço L2VC de teste** (cliente/finalidade "teste"),
   em **switch não crítico**, via CR aprovada no fluxo normal (backup
   pré-mudança, pós-check, rollback disponível) — registrado em ledger que a
   validação é em produção com escolha consciente do escopo; nada de execução
   automática sem aprovação (regra §3.3 inegociável).

## 11. Decisões registradas (brainstorming 2026-09-07)

1. **Q1 — CR generalizado** (não CR por device nem fluxo paralelo): uma CR
   por serviço; `circuit_id` nullable + `escopo` + `l2vc_id`; máquina de
   estados e runner reutilizados; `parcial` = §9.3.
2. **Q2 — IDAM simples**: UNIQUEs + helpers (`proximo_vc_id`,
   `proximo_vsi_id`); VLAN de AC na tabela `vlans` existente com kind
   `mpls_ac` e **escopo por device** (índices parciais: site×vid sem
   device_id para circuitos, device×vid para MPLS — revisão do usuário em
   2026-09-07: mesmo VID é legítimo em switches diferentes do mesmo POP);
   sem tabela `allocations` genérica.
3. **Q3 — VSI modelo + consulta**: parsers/estado no ciclo; sem render e sem
   CR de VSI (pós-estabilização L2VC, §23).
4. YAGNI: sem tabela de estados por pseudowire; sem `ethernet_raw` como
   requisito (opcional); sem card de métricas avançado; sem NetBox.
5. **Validação sem lab**: equipamento real de produção como banco de testes
   (read-only → geração + diff → um L2VC de teste em switch não crítico via
   CR aprovada); decisão do usuário 2026-09-07.
