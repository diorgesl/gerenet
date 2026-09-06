# Design — Ciclo D: fluxo de mudança controlada (gerenet)

> Especificação do **ciclo D** do gerenet — o fluxo de mudança controlada do §12 da
> [spec](../ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md): change request a partir de
> objeto da SoT, geração de plano (criação e remoção), visualização do diff,
> aprovação registrada, execução com lock/pre-checks/backup, pós-validação e
> rollback conservador por comandos inversos. Documentos-fonte: spec §6.6, §10,
> §12–13, §14, §15, §17–18, §21, §23–24; decisões da revisão final do C3
> (2026-09-05); design do ciclo B2 (render/divergência, concluído).

## 1. Objetivo e escopo

Entregar o ciclo de vida completo de uma mudança de rede sobre a infraestrutura
já existente — **criação + remoção + rollback** de downstreams BGP (circuitos e
sessões, IPv4/IPv6):

1. **Modelos** `change_requests`, `change_steps`, `approvals` (spec §14) +
   migração Alembic.
2. **Geração de plano**: diff do render existente vs. snapshot (provision) e
   **render inverso** por tipo de bloco (remove), com baseline congelado.
3. **API + CLI** completos (`/api/v1/change-requests`, `gerenet change-requests`).
4. **Execução no worker** (fila `gerenet-change`): pré-checks §12.2 (subconjunto),
   snapshot fresco = backup pré-mudança, aplicação bloco a bloco com parada em
   erro do VRP, pós-validação §13, auditoria.
5. **Web**: páginas de change requests (lista + detalhe com diff/approvals),
   botões contextuais por papel, link "Solicitar mudança" nas páginas de
   circuito/sessão, card "aprovações pendentes" no dashboard.
6. **Rollback conservador**: novo CR inverso (nunca comandos às cegas), rastreado
   por `rollback_de`.

Fora do escopo do D (notas no ledger): MPLS/L2VC/VSI (fase 4 do roadmap §22 —
modelos de domínio nem existem ainda); assistentes web §16.2/§16.3 (ciclo E);
dupla aprovação por criticidade (ruling §25 — campo criado, regra futura);
rollback nativo/reload de backup automatizado; pré-checks avançados (CPU/memória/
alarmes — §12.2 completo); upstreams; TACACS+/NetBox; auto-classificação de
criticidade.

## 2. Contexto (o que já existe, verificado em 2026-09-05)

### 2.1 Render e divergência

- `render_desejado(session, device_id)` → `RenderResult{blocos, texto}`:
  `BlocoRender{tipo, objeto, objeto_id, comandos}` com nomes derivados do ASN do
  par (§25.4), ordem estável `TIPO_ORDEM` (subinterface → filtros → RPs → peer),
  idempotente; **só gera comandos de criação**.
- `reconciliar_device(...)` — itens tipados desejado × encontrado (read-only),
  expostos em `GET /api/v1/reconciliation` e `GET /api/v1/devices/{id}/desired-config`.
- `render.py` já filtra por circuito via `objeto_id` de cada bloco (base do diff
  por escopo do CR).

### 2.2 Coleta/execução

- `run_collection` (runner.py): lock por device `gerenet:lock:device:{id}` com
  token + TTL (libera por compare-and-delete), `JobRun` (kind `collect`),
  `DeviceSnapshot` com `resources`/`raw_files` (inclui `current-configuration`),
  eventos `collect.skipped/failed/errors`.
- Fila RQ `gerenet-collect`; `worker_main` escuta uma fila só.
- `netmiko_conn.connect_and_run` (SSH; hostkeys validados) + parsers TextFSM do
  ciclo B1 (`display bgp peer` incluso).
- Vault para credenciais; nenhuma credencial em YAML/Git.

### 2.3 API/CLI/web

- Rotas por entidade no padrão `require_actor` + schemas `*Out`; serviço puro por
  domínio em `domain/services/`; erros 404/400 via `NotFoundError`/`ValidationError`.
- CLI Typer por entidade (padrão "CLI como cidadão de primeira").
- Web: páginas por entidade + `Reconcile.tsx`/`DesiredConfig.tsx`/`Jobs.tsx`/
  `AuditEvents.tsx`; `ConfirmDialog`/`Modal` (C3); dashboard com
  `by_comm_status`, `snapshot_age_seconds`, `pending` (jobs ativos) e eventos de
  auditoria.
- Papéis: `visualizador | operador | aprovador | executor | administrador`
  (models.py:34) — gate de papel já existe em `require_actor`/deps.

### 2.4 Lacunas (o que o D cria)

- Sem `ChangeRequest`/`ChangeStep`/`Approval` (models.py vai até `UserSession`).
- Sem render inverso; sem fila de mudança; sem APIs/CLI/web de CR; sem
  pós-validação após execução (reconcile é read-only); sem relação
  CR → JobRun; sem "aprovações pendentes" no dashboard.

## 3. Decisões de design (aprovadas em 2026-09-05 no brainstorm)

1. **Abordagem A — estender padrões existentes** (não engine de patch genérica —
   YAGNI; o ponto natural de extensão é o render por tipo de bloco; o `kind`/
   `tipo` nos modelos deixa L2VC plugar depois).
2. **Escopo de comandos: criação + remoção + rollback por inversos** — fecha os
   critérios §24 ("geração de remoção", "teste de idempotência").
3. **Aprovação: exatamente 1**, perfil `aprovador` (ou `administrador`);
   **solicitante não pode aprovar**; campo `criticidade` (baixa|media|alta,
   manual na criação, default `media`) criado agora — **dupla aprovação fica
   registrada como regra futura** (ruling §25).
4. **Origem da mudança: objeto SoT** (circuit/sessão). O sistema deriva os
   equipamentos afetados, renderiza e mostra o diff. Assistente §16 → ciclo E.
5. **Plano com baseline congelado + re-checagem na execução**: a execução re-coleta
   e recomputa o diff; config alterada em relação ao baseline ⇒ aborta (§12.2
   "config inalterada"); bloco já presente ⇒ `pulado` (idempotência §21).
6. **Rollback conservador**: rollback = novo CR inverso em `aguardando_aprovacao`,
   com `rollback_de`; sem execução automática (§12.4).
7. **Falha em uma das pontas ⇒ CR `parcial`** com ação "reconciliar" que recomputa
   os steps não aplicados (§9.3).

## 4. Modelos e estados (S1)

### 4.1 `change_requests`

`id` · `circuit_id` FK (not null) · `acao` enum(`provision|remove`) ·
`criticidade` enum(`baixa|media|alta`, default `media`) · `motivo` Text ·
`ticket` String(64) nullable · `solicitante_id` FK users · `rollback_de` FK
change_requests nullable (auto) · `status` enum · `created_at/updated_at`.

Status (transições válidas — máquina de estados no service; qualquer transição
inválida = ValidationError):

```
rascunho → aguardando_aprovacao → aprovado → executando → aplicado
                                                       ├→ com_divergencia
                                                       ├→ parcial
                                                       └→ erro
terminais: rejeitado (de aguardando_aprovacao), cancelado (de rascunho/
aguardando_aprovacao/aprovado)
```

- Criar já valida (circuito ativo para `provision`; com sessões para `remove`) e
  gera o plano — CR nasce em `rascunho` com steps e diff prontos.
- `reconciliar`: somente de `erro|parcial`; recomputa o plano dos steps não
  aplicados e devolve o CR a `aguardando_aprovacao` (nova aprovação — o diff pode
  mudou; conservador).

### 4.2 `change_steps` (um por equipamento afetado)

`id` · `change_request_id` FK · `device_id` FK · `status`
enum(`pendente|aplicado|pulado|falhou|rollback`) · `plano_json` JSON —
`[{tipo, objeto, objeto_id, acao: create|delete, comandos: [str]}]` na ordem de
aplicação (criação: ordem do render; remoção: ordem inversa) · `baseline_snapshot_id`
FK device_snapshots nullable · `backup_snapshot_id` FK nullable · `post_check_json`
JSON · `erro` Text · timestamps.

Derivação dos devices: distinct `bgp_sessions.device_id` do circuito (todas as
sessões do circuito, incluindo as em `shutdown` — remover circuito exige remover a
config que existe; `provision` só considera sessões ativas, como o render já faz).

### 4.3 `approvals`

`id` · `change_request_id` FK · `user_id` FK · `decisao` enum(`aprovar|rejeitar`)
· `comentario` Text nullable · `created_at`. Regra: 1 aprovação; papel
`aprovador`/`administrador`; `user_id != solicitante_id`; duplica
`approve`/`rejeitar` do mesmo CR ⇒ ValidationError (já decidido).

### 4.4 Auditoria

Eventos no padrão `AuditEvent` (`change.created`, `change.sent_for_approval`,
`change.approved`, `change.rejected`, `change.cancelled`, `change.executing`,
`change.step_applied|step_skipped|step_failed`, `change.applied`,
`change.com_divergencia`, `change.parcial`, `change.rollback_created`) com
`details` sem segredos/comunidades (mascaramento padrão já existente).

## 5. Geração do plano (S2)

### 5.1 Provision

`plan_provision(session, circuito)` por device:
1. `render_desejado(device)` → blocos do circuito (`objeto_id` = circuito ou
   sessões dele).
2. Snapshot mais recente (default) — recursos `interfaces`/`bgp_peers`/
   `bgp_peers_verbose`; se ausentes ⇒ `baseline_snapshot_id = null` + `aviso` no
   step (o diff de skip fica vazio; a execução re-coleta antes do re-diff §6).
   Para `remove` essa situação **não** gera plano — exige coleta fresca (§5.2).
3. Diff por bloco: bloco cujos comandos já constam do encontrado ⇒ marca
   `pulado` (idempotência por diff, não por tentativa).
4. `plano_json` = blocos a aplicar (`acao=create`), ordem do render.

### 5.2 Remove

`render_remocao(session, circuito)` por device — inversos **a partir do
encontrado** (não do desejado): `undo ip address`/`undo interface` · `undo
route-policy`/`undo ip-prefix-list`/`undo as-path-filter`/`undo community-filter`
· `undo peer`/`undo `peer` (endereço)`. Ordem inversa à criação: peer → RPs →
filtros → subinterface. Sem snapshot com os recursos ⇒ não gera (exige coleta
fresca primeiro). Sessões do circuito que ainda existem no equipamento geram os
blocos `delete`; o que não existe no encontrado não entra no plano (não inventa).

### 5.3 Baseline

- `baseline_snapshot_id` = snapshot usado no diff de cada step + `plano_json`
  congelado (o diff da web/CLI mostra exatamente esse plano).
- Na execução, o worker re-coleta e **recomputa**: se um bloco planejado `create`
  já existe ⇒ pula; `delete` que já não existe ⇒ pula; estado intermediário
  divergente (ex.: subinterface existe sem o endereço esperado, peer com ASN
  diferente) ⇒ aborta com `erro` e motivo (config inalterada, §12.2).

## 6. Execução no worker (S3)

Nova fila `gerenet-change`; `worker_main` escuta `["gerenet-collect",
"gerenet-change"]` (mesmo processo de worker).

`run_change(change_request_id, *, actor, origin)`:
1. **Pré-checks** por step: `get_device` acessível + grupo de credencial + lock
   (`gerenet:lock:device:{id}`, mesmos helpers do runner — TTL/timeout).
2. **Coleta fresca** (reuso dos collectors) → grava como
   `backup_snapshot_id` (backup pré-mudança, §12.3) e base do re-diff.
3. **Re-diff** vs. baseline (5.3). Aborto ⇒ step `falhou`, CR `erro`, motivo claro.
4. **Aplicação bloco a bloco** (uma conexão por bloco, não por linha):
   - Padrões de erro VRP em constante única (conjunto inicial:
     `% Error:`, `^`, `Incomplete command`, `Ambiguous command`,
     `Unrecognized command`) testado nos testes do runner;
   - erro ⇒ **interrompe só aquele device** (os blocos restantes dele ficam
     `pendente`); os demais steps continuam (§9.3 — pontas independentes);
   - sucesso ⇒ step `aplicado` (ou `pulado`).
5. **Pós-validação** (§13): `reconciliar_device` do device + parse
   `display bgp peer` das sessões afetadas; resultados em `post_check_json`.
   Classificação final do CR: todos aplicados e sem item `critica` ⇒ `aplicado`;
   todos aplicados com item `critica` ⇒ `com_divergencia`; ≥1 falhou e ≥1
   aplicado ⇒ `parcial`; todos falharam ⇒ `erro`.
6. `JobRun` **por step** (kind=`change`, `device_id`, meta
   `{change_request_id, change_step_id, actor, origin}`) — trilha por equipamento.
7. Eventos de auditoria por transição (§4.4).

Rejeição enqueue de CR: não aprovado ⇒ "queixa na origem" (padrão do collect);
CR que não tolera execução concorrente: lock por CR no Redis
(`gerenet:lock:change:{id}`) além do lock por device.

## 7. Rollback (S4)

- `rollback` só de `aplicado|com_divergencia|parcial` (com steps aplicados).
- Gera **novo CR** com `rollback_de`: `provision` → CR `remove` com plano
  derivado do **snapshot baseline** (o que a mudança adicionou — o plano do CR
  filho usa o encontrado do snapshot pré-mudança); `remove` → CR `provision`
  re-renderizado do desejado.
- Filho nasce em `aguardando_aprovacao` (mesma regra: aprovador ≠ solicitante do
  filho), `motivo` preenchido ("rollback do CR #N") e `acao` inversa. Papel
  `executor` executa.
- Segredos/comunities do plano do filho nunca vazam (padrão de mascaramento).
- Restaurar backup por reload/rollback nativo: fora de escopo (nota §21 lab).

## 8. API e CLI (S5)

API `/api/v1/change-requests` (router próprio, `require_actor`, schemas
`*Out` com `steps`/`approvals`):
- `POST /` criar (valida + plano) → `ChangeRequestOut` com diff por step.
- `GET /` (filtros `status`, `solicitante`, `circuit_id`, `per_page` padrão
  repo) · `GET /{id}` (steps + approvals).
- `POST /{id}/enviar` (solicitante/operador) · `POST /{id}/approve`
  (`decisao`, `comentario`; papel aprovador/admin; ≠ solicitante) ·
  `POST /{id}/cancelar` · `POST /{id}/executar` (papel executor/admin;
  enfileira) · `POST /{id}/rollback` (gera filho) · `POST /{id}/reconciliar`
  (de `erro|parcial`).

CLI `gerenet change-requests` — `create --circuit ID --acao provision|remove
[--criticidade media] --motivo ... [--ticket ...]`, `list`, `show ID`, `enviar`,
`approve ID --decisao ... [--comentario ...]`, `execute ID`, `cancelar ID`,
`rollback ID`, `reconcile ID` — mesmo fluxo sem web.

## 9. Web (S6)

- `ChangeRequests.tsx` (lista + filtros por status) e `ChangeRequestDetail.tsx`
  (steps: diff por bloco "o que será aplicado", baseline/backup, approvals,
  pós-check) no padrão C2/C3 (DataTable, `ConfirmDialog`, `Modal`, hooks de
  mutação com `.catch`).
- Botões por papel: operador (solicitar/enviar/cancelar), aprovador
  (aprovar/rejeitar — o próprio pedido não aparece), executor
  (executar/reconciliar/rollback).
- Botão "Solicitar mudança" em `CircuitDetail.tsx` e `BgpSessionDetail.tsx`
  (dialog com acao, criticidade, motivo, ticket → POST → navega ao detalhe).
- Dashboard: card "Aprovações pendentes" (`GET /api/v1/change-requests?status=
  aguardando_aprovacao` contagem) — padrão dos cards existentes.

## 10. Testes e verificação (S7)

- **Unit (domain)**: máquina de estados (transições válidas/inválidas); regra de
  aprovação (papel/≠solicitante/duplicada); plano provision (diferenciar
  presente → `pulado`); plano remove (a partir do encontrado; ordem inversa;
  sem snapshot → recusa); render inverso round-trip (create→remove→create
  reproduz blocos); rollback (inverso direto e re-provisionamento; `rollback_de`).
- **Runner** (fake Netmiko, padrão `test_runner.py`): sucesso bloco a bloco; erro
  VRP no meio ⇒ CR `erro` + steps restantes `pendente` + trilha no JobRun; bloco
  já presente ⇒ `pulado`; re-diff divergente ⇒ aborta; post-check com item
  `critica` ⇒ `com_divergencia`; lock por device/CR.
- **API**: pytest em `tests/api/` — contratos, papéis (403/404/400), filtros,
  transições; **CLI**: `tests/cli/` no padrão do repo.
- **Web**: Vitest das páginas novas (lista/detalhe/botões por papel); e2e: 1 fumo
  novo (criar circuito → solicitar → aprovar → executar com jobs fake) no padrão
  `web/e2e` + guard `reuseExistingServer: false` já existente.
- **Verificação final**: `uv run ruff check src tests`, `uv run pytest -q`,
  `npm run build`, `npm run test`, e2e com banco `gerenet_e2e`.

## 11. Riscos e cuidados

- **Erros do VRP por versão/família**: constantes de erro + tests com fixtures de
  saída real (padrão B1); laboratório §21 continua sendo o gate de variação.
- **Idempotência real**: o "pula se já existe" é otimista — se o bloco falhar por
  outro motivo (ex.: prefix-list já usada por outra RP), o CR dá `erro` com a
  saída mascarada e a trilha completa; sem retry automático.
- **Fila/worker**: dois queues no mesmo `worker_main` — worker de produção roda o
  novo comando; docs do deploy (compose/RQ) atualizadas.
- **Concorrência**: locks por device (existente) + por CR (novo) — duas mudanças
  simultâneas no mesmo equipamento se bloqueiam na origem (enqueue rejeitado com
  mensagem clara, como o collect).
- **Mascaramento**: `details`/`plano_json`/`post_check_json` nunca guardam
  password/community (comunidades: mascarar como no padrão repo).
