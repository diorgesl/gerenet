# Design — Fase 6 (parte 1): automação contínua no gerenet

> Abre a Fase 6 (§22) com a coleta periódica agendada, o resumo da divergência
> gravado em cada coleta, o endpoint Prometheus `/metrics` e o Grafana no compose
> de dev com os painéis do §20.1, mais o card de divergências no dashboard.
> Documentos-fonte: spec §10, §12–13, §16.1, §19–20, §22, §25 (itens 12, 15 e 17);
> designs da Fase 5 (2026-09-08) e das fases 4 (2026-09-13); decisão R-28 do
> dashboard; `docs/wiki/operacao.md`.

## 1. Objetivo e escopo

Fechar o primeiro bloco da Fase 6 (§22: "reconciliação agendada", "Grafana",
"métricas do §20.1"). Hoje a plataforma só compara intenção × estado real quando
alguém pede: a coleta é sob demanda pela API, pelo CLI e pelo botão do
equipamento, e a divergência é calculada na hora em que a página de
Reconciliação abre. Nada avisa que um equipamento derivou, e nada expõe o estado
operacional para um sistema de monitoração.

Entregas:

1. **Coleta periódica agendada** — varredura que enfileira a coleta dos
   equipamentos ativos com credencial, no intervalo configurado, disparada pelo
   próprio worker.
2. **Resumo da divergência gravado na coleta** — cada coleta passa a registrar a
   contagem por severidade do desejado × encontrado, junto ao snapshot.
3. **`/metrics` Prometheus na API** — os nove itens do §20.1 derivados do banco
   e do Redis, sem estado em memória.
4. **Prometheus e Grafana no compose de dev** — dois serviços novos com
   configuração versionada e um dashboard com os painéis do §20.1.
5. **Card de divergências no dashboard** — contagem por severidade lendo o
   resumo da coleta, com o detalhe permanecendo na página de Reconciliação
   (R-28).

Fora de escopo: notificações (n8n, Telegram, e-mail), API de ativação por
sistemas externos e relatórios operacionais, que seguem na Fase 6 para frentes
próprias; servidor MCP (§25.17); modo multiprocesso de métricas no worker;
separação das filas em dois workers; Zabbix e NetBox.

## 2. Contexto verificado (2026-09-14)

**O que já existe e é reaproveitado.**

- `enqueue_collect` (worker/tasks.py) valida o equipamento antes da fila
  (existência, `admin_status`, grupo de credencial), respeita o lock
  `gerenet:lock:device:<id>`, não duplica coleta pendente ou já iniciada e
  enfileira na fila `gerenet-collect` com `meta={"actor", "origin"}`. Uma
  varredura periódica pode chamá-la dispositivo a dispositivo sem reimplementar
  nenhuma dessas regras.
- `run_collection` (automation/runner.py) grava o `JobRun` (kind, status,
  `duration_ms`, `snapshot_id`, `error`), o `DeviceSnapshot` com `resources`,
  `errors` e `raw_files`, atualiza o equipamento (`comm_status`,
  `consecutive_failures`, `last_collected_at` via `touch_collection`), audita
  `collect.errors`, `collect.failed` e `collect.skipped` e roda
  `sincronizar_mpls` depois do commit. O precedente de dado calculado na coleta
  já existe: `resources["anomalias_prefixos"]` (§25/RP, Fase 5).
- `reconciliar_device(session, device_id, *, snapshot_id=None)` devolve
  `ReconcileResult` com `aviso` e `items` de `severidade` em
  `critica | atencao | aviso | alerta`. É chamado sob demanda pela API
  (routers/reconciliation.py) e no pós-check do runner de mudanças
  (runner.py, `run_change`).
- O `job_runs` é durável e guarda duração, status, tipo e equipamento de cada
  execução. O dashboard já lê o snapshot mais recente por equipamento para a
  idade da coleta e não chama reconcile, por contrato explícito ("read-only
  barato").

**O que não existe.**

- Nenhuma menção a `metrics`, `prometheus` ou `grafana` no código, no
  `pyproject.toml` ou no `compose.yaml`: o `/metrics` do §25.15 nunca foi
  implementado, e `prometheus-client` não é dependência.
- Nenhum agendamento: `worker_main` roda `Worker(["gerenet-collect",
  "gerenet-change"]).work()` sem scheduler, e o compose sobe um worker só, de
  concorrência 1. A coleta só acontece por ação humana.
- Nenhum resumo de divergência persistido: a contagem por severidade é
  recalculada a cada abertura da página.
- O `bgp_sessions` não guarda estado operacional (só cadastro); o estado dos
  peers vive no snapshot (`bgp_peers`, linhas com `afi`, `peer`, `asn`, `estado`,
  `pref_rcv`, `up_down`). L2VC, AC de VSI e VSI guardam `operational_status`
  (`unknown | up | down | partial`), sincronizado pela coleta.

**Capacidades do RQ instalado (2.12.0).** `Queue.enqueue_in` e
`Worker.work(with_scheduler=True)` existem, então agendar não pede dependência
nem serviço novo. Cada job, porém, roda num processo filho criado por
`os.fork()` (`Worker.fork_work_horse`): contador em memória incrementado dentro
do job morre com o filho, o que decide o desenho do item 3 (seção 5).

## 3. Coleta periódica agendada

**Config.** `collect_interval_minutes: int = 0` em `Settings`, lido do ambiente
como `GERENET_COLLECT_INTERVAL_MINUTES`. Zero significa desligado e é o default:
ligar coleta SSH periódica em produção é decisão explícita de quem instala. O
compose de dev passa um valor (60) para o recurso existir de verdade ali.

**Arm.** `worker_main` passa a rodar com `with_scheduler=True` e, antes de entrar
no loop, chama `armar_varredura(r)`: com intervalo maior que zero e nenhuma
varredura agendada na fila `gerenet-collect`, enfileira a primeira com
`enqueue_in(timedelta(minutes=intervalo), varredura_coletas)`. A checagem de
"já agendada" percorre o `ScheduledJobRegistry` da fila comparando o
`func_name`, então um boot de worker conserta uma agenda perdida no Redis e não
cria uma segunda.

**Varredura.** `varredura_coletas(agora=None) -> dict` em worker/tasks.py:

1. Toma o lock `gerenet:lock:sweep` (SET NX com o `lock_ttl_seconds` do
   Settings, 300 s por default). Se já está tomado,
   devolve `{"status": "skipped"}` sem fazer nada: uma varredura duplicada não
   multiplica coletas.
2. Seleciona equipamentos com `admin_status` verdadeiro e `credential_group_id`
   não nulo.
3. Para cada um, olha o snapshot mais recente e **pula quem foi coletado dentro
   do intervalo** (limite inferior do mesmo período que ela agenda), contando em
   `pulados_idade`. Sem snapshot nenhum, enfileira.
4. Chama `enqueue_collect(device_id, actor="scheduler", origin="scheduler")`.
   `queued: True` conta em `enfileirados`; recusa (lock ativo ou coleta
   pendente, e também o equipamento desativado ou sem credencial desde a
   consulta) conta em `recusados`, com o motivo, e não é erro da varredura.
5. Audita um evento `collect.sweep` com os três números e o motivo de cada
   recusa. É a única trilha da coleta automática, já que ela não tem solicitante.
6. Lê o intervalo de novo e, se ainda for maior que zero, reagenda a próxima
   varredura com `enqueue_in`. Um agendamento em voo é retomado pelo arm no
   próximo boot; desligar o intervalo vale já na execução seguinte.

`origin="scheduler"` é um valor novo no campo `origin` do `JobRun` (que tem 16
caracteres) e é o que deixa a coleta automática distinguível da manual na lista
de jobs e na auditoria.

**Duas consequências registradas.**

- A regra de idade tem limite superior de ~2× o intervalo: um equipamento
  coletado à mão um minuto antes da varredura é pulado e só volta na varredura
  seguinte. Fica na wiki, e apertar isso (margem de tolerância, sweep em metade
  do intervalo) é ajuste de uma linha quando incomodar.
- Com um worker só, e `gerenet-collect` listada antes de `gerenet-change`,
  coletas passam na frente de uma execução de mudança já aprovada. Com a frota
  atual o atraso é pequeno. Separar as filas em dois workers resolve e fica
  registrado como frente futura, não como trabalho desta.

## 4. Resumo da divergência gravado na coleta

`run_collection`, depois do commit do snapshot e do `sincronizar_mpls`, passa a
chamar `reconciliar_device(session, dev.id, snapshot_id=snapshot.id)` e a gravar
o resumo no próprio snapshot, em `resources["divergencias"]`:

```json
{
  "total": 4,
  "critica": 1,
  "atencao": 2,
  "aviso": 0,
  "alerta": 1,
  "parcial": false,
  "motivo": null
}
```

- `parcial` é verdadeiro quando o reconcile avisou que faltou recurso no
  snapshot (`ReconcileResult.aviso`), e `motivo` carrega esse aviso. É o mesmo
  sinal que a página de Reconciliação mostra ao operador.
- O resumo vai para `resources`, e não para colunas novas nem para uma tabela,
  pelo mesmo motivo de `anomalias_prefixos`: é dado derivado de uma coleta
  específica, e a leitura é sempre "o resumo do snapshot mais recente".
- **A falha do reconcile não derruba a coleta.** Diferente do `sincronizar_mpls`,
  que hoje propaga e marca a coleta como falha, aqui um `except` audita
  `collect.reconcile_failed` com o erro e segue. O que a coleta trouxe do
  equipamento já está gravado; marcar `job_runs` como `error` por causa de um
  cálculo derivado seria mentira no histórico. O snapshot fica sem o resumo, e
  quem lê trata a ausência (seções 5 e 7).
- Custo: um render do desejado por coleta, na mesma ordem de grandeza do que a
  página já faz ao abrir. Aceitável na frota atual e no intervalo de dezenas de
  minutos; se a coleta ficar cara, o item é medido antes de otimizado.

Coleta antiga (anterior a esta frente) não tem resumo, e isso é diferente de
"zero divergências". Todo leitor desta frente distingue os dois casos.

## 5. Métricas Prometheus na API

**Dependência.** `prometheus-client`, fixada no `pyproject.toml` com o
`uv.lock` atualizado.

**Implementação.** `src/gerenet/api/metrics.py` expõe `montar_metrics(app,
settings)`, chamado por `create_app()` antes de `montar_spa` (o catch-all da SPA
responde qualquer GET, então a rota precisa existir primeiro). O módulo cria um
`CollectorRegistry` próprio por aplicação e registra um `Collector` do gerenet
que, a cada scrape, abre sessão e monta as amostras. Registry por app, e não o
default global, porque a suíte chama `create_app()` em dezenas de testes e o
registro global duplicaria séries na segunda chamada.

Um `Collector` que calcula no scrape, em vez de gauges mantidos em memória por
um job de atualização, mantém a exposição sempre igual ao banco: não existe
série velha nem processo de sincronização para morrer em silêncio.

A rota é `GET /metrics`, sem autenticação de sessão, como o `/healthz`. Com
`metrics_token` preenchido (Settings, env `GERENET_METRICS_TOKEN`, default
`None`), exige `Authorization: Bearer <token>`. O endpoint pertence à rede de
gerência (§19), e isso fica escrito no runbook.

**Séries, cobrindo os nove itens do §20.1.**

| Série | Tipo | Labels | Fonte | Item do §20.1 |
|---|---|---|---|---|
| `gerenet_devices_comm_status` | gauge | `status` | `devices.comm_status` | equipamentos inalcançáveis |
| `gerenet_devices_active` | gauge | — | `devices.admin_status` | — |
| `gerenet_device_consecutive_failures` | gauge | `device` | `devices.consecutive_failures` | equipamentos inalcançáveis |
| `gerenet_snapshot_age_seconds` | gauge | `device` | snapshot mais recente (`started_at`) | idade da última coleta |
| `gerenet_divergencias` | gauge | `severidade` | `resources["divergencias"]` do snapshot mais recente | divergências por severidade |
| `gerenet_devices_sem_resumo` | gauge | — | snapshots sem `divergencias` | divergências por severidade |
| `gerenet_peers_bgp` | gauge | `estado` | `resources["bgp_peers"]` do snapshot mais recente | peers BGP por estado |
| `gerenet_l2vc_oper_status` | gauge | `status` | `l2vc_services.operational_status` | L2VCs por estado |
| `gerenet_vsi_oper_status` | gauge | `status` | `vsi_services.operational_status` | VSIs por estado |
| `gerenet_change_requests` | gauge | `status` | `change_requests.status` | mudanças pendentes |
| `gerenet_queue_jobs` | gauge | `queue` | RQ (`gerenet-collect`, `gerenet-change`) | tamanho da fila |
| `gerenet_queue_started` | gauge | `queue` | registry de jobs iniciados | tamanho da fila |
| `gerenet_job_runs` | gauge | `kind`, `status`, `device` | contagem acumulada em `job_runs` | sucesso/falha por equipamento e tipo |
| `gerenet_job_duration_seconds` | gauge | `kind`, `quantil` | p50 e p95 por `kind` sobre os últimos 200 `job_runs` | duração de cada tarefa |

Duas notas de honestidade:

- `gerenet_job_runs` e `gerenet_job_duration_seconds` são **gauges** calculados
  em SQL, não contadores nem histograma do cliente. O `job_runs` é durável e
  monotônico (nada é apagado), então a série serve para `rate`, mas nomeá-la
  `_total` seria mentira sobre o tipo. A duração vira p50/p95 por tipo em vez de
  histograma porque não há onde guardar os buckets: os dados brutos por job
  estão no banco, e um histograma do cliente exigiria o modo multiprocesso no
  worker, que ficou fora de escopo.
- Séries com label de equipamento emitem apenas os equipamentos existentes. Um
  equipamento sem snapshot não emite `gerenet_snapshot_age_seconds` (ausência de
  série é diferente de zero), e o mesmo vale para quem não tem resumo de
  divergência, que aparece na contagem de `gerenet_devices_sem_resumo`.
- Emenda (revisão de branch): `gerenet_devices_sem_resumo` conta **só** quem tem
  snapshot, então equipamento **nunca coletado** não aparece em contagem nenhuma
  do `/metrics` — nem nessa, nem nas de severidade. E o campo `parcial` do resumo
  **não** é publicado como série: o card do dashboard o mostra, e o porquê de não
  virar painel está no runbook de observabilidade.

**Custo por scrape.** N consultas de snapshot mais recente (uma por
equipamento), três agregações e as duas consultas de fila no Redis, no mesmo
padrão que o dashboard já faz. Com scrape de 30 s e a frota atual, irrelevante;
se a frota crescer, o item é otimizado com um resumo materializado na coleta.

**Emenda ao §25.15.** A decisão registrada em 2026-09-02 prometia `/metrics` "na
API e no worker". O worker não ganha endpoint nesta frente, porque cada job roda
num processo filho (`os.fork`) e um contador em memória criado lá dentro morre
com o filho; sustentar isso exigiria o modo multiprocesso do `prometheus_client`
(diretório compartilhado, semântica de gauge própria, mais setup e mais
superfície de falha) em troca de séries que o `job_runs` já entrega de forma
durável e que sobrevivem a restart. A spec ganha uma emenda ao item 15 com esse
motivo, e o modo multiprocesso fica registrado como caminho se e quando houver
razão (por exemplo, métricas de worker interno, hoje sem dado real).

## 6. Prometheus e Grafana no compose

Dois serviços novos no `compose.yaml`, ambos de dev:

- `prometheus` (`prom/prometheus`, porta 9090) com `docker/observability/prometheus.yml`:
  um job raspando `api:8000/metrics` a cada 30 s, com `authorization` quando
  `GERENET_METRICS_TOKEN` estiver preenchido.
- `grafana` (`grafana/grafana`, porta 3000) com provisionamento versionado em
  `docker/observability/grafana/provisioning/`: datasource apontando para o
  Prometheus e provider de dashboards. No dev o acesso é anônimo como viewer,
  registrado no README; senha e usuário são assunto de quem instala.

O dashboard `docker/observability/grafana/dashboards/gerenet.json` traz os
painéis do §20.1: equipamentos por `comm_status`, idade da coleta por
equipamento, divergências por severidade, peers BGP por estado, L2VC e VSI por
estado, mudanças aguardando aprovação, tamanho da fila e p50/p95 da duração da
coleta. É ponto de partida, não produto: em produção o Prometheus e o Grafana
são os de quem instala, e a plataforma entrega o `/metrics`.

## 7. Card de divergências no dashboard

O §16.1 já prevê divergências no dashboard, e a decisão R-28 manda o detalhe
para a página de Reconciliação. O card respeita as duas: contagem aqui, itens
lá.

- **API.** `PerDeviceOut` ganha `divergencias` (o resumo do snapshot mais
  recente, com o mesmo shape da seção 4, ou `null` quando não há resumo) e
  `DashboardOut` ganha um agregado
  com `total`, `critica`, `atencao`, `aviso`, `alerta`, `devices_com_critica`,
  `devices_sem_resumo` e a idade do resumo mais antigo usado. A leitura continua
  sendo do banco, sem chamar reconcile: o contrato "read-only barato" do
  dashboard fica de pé.
- **Web.** Um bloco novo na faixa de saúde com LED (vermelho com alguma
  divergência crítica, âmbar com atenção, cinza quando não há resumo) e a
  contagem de equipamentos divergentes. Abaixo, um card com as contagens por
  severidade usando o `SeverityBadge` que já existe, a idade do dado e a lista
  dos equipamentos com divergência crítica, cada um linkando para
  `/reconcile?device_id=N`, parâmetro que a página de Reconciliação já lê da URL.
  A tabela por equipamento ganha uma coluna com o resumo do próprio equipamento.
- **Sem resumo não é zero.** Equipamento coletado antes desta frente entra em
  `devices_sem_resumo` e o card diz "N sem resumo" em vez de somar zero, que
  afirmaria uma rede sem divergências onde ninguém olhou.
- **Nunca coletado também não é zero** (emenda da revisão de branch). O LED do
  bloco fica âmbar não só com divergência de atenção/aviso, snapshot sem resumo
  ou comparação parcial: também quando `devices.with_snapshot < devices.total`,
  que é o caso da instalação nova — equipamentos cadastrados e nenhum coletado,
  que sem isso leria "0 divergências" verde. A nota do card traz essa contagem
  ("N equipamento(s) sem coleta"), junto das de parcial e sem resumo.

## 8. Testes

- **Varredura** (tests/worker, com Redis real no padrão de `test_tasks.py`):
  seleciona só ativos com grupo de credencial; pula quem foi coletado dentro do
  intervalo e enfileira quem está fora ou nunca foi coletado; recusa do enqueue
  vira `recusados` com motivo e não interrompe os demais; audita
  `collect.sweep` com os números; lock tomado devolve `skipped` sem enfileirar.
- **Arm**: com intervalo zero não agenda nada; armar duas vezes deixa uma
  varredura agendada; a varredura reagenda a si mesma quando o intervalo segue
  maior que zero e não reagenda quando voltou a zero.
- **Resumo na coleta** (tests/automation/test_runner.py): a coleta grava
  `resources["divergencias"]` com a contagem por severidade e `parcial`
  verdadeiro quando falta recurso; com o reconcile levantando, a coleta termina
  `success`, o snapshot fica sem o resumo e existe o evento
  `collect.reconcile_failed`.
- **`/metrics`** (tests/api/test_metrics.py): a exposição contém as séries com os
  labels esperados e os valores vêm das fixtures (inclusive
  `gerenet_devices_sem_resumo` com snapshot sem resumo); com token configurado,
  sem bearer é 401 e com bearer é 200; sem token, é 200; e o endpoint responde
  200 com `static_dir` apontando para um build de fixture, provando que o
  catch-all da SPA não o engole.
- **Dashboard** (tests/api/test_dashboard_api.py e Vitest): agregado por
  severidade, degradação com equipamento sem resumo, e o card com os casos de
  crítica, atenção e sem resumo.
- **e2e**: o `smoke.spec.ts`, que já abre o dashboard, ganha uma asserção do
  card. Sem arquivo novo, e o run-book do `web/e2e/README.md` não muda.

## 9. Documentação e registro

- **Wiki**: `docs/wiki/equipamentos.md` (a página de coleta) ganha a coleta
  periódica: como ligar pelo env, o intervalo, a regra de idade e o limite de
  2×, e como ler o evento `collect.sweep`. `docs/wiki/operacao.md` ganha o
  resumo da divergência gravado na coleta e o card como porta de entrada, com o
  detalhe permanecendo na página de Reconciliação.
- **Runbook novo** `docs/runbook-observabilidade.md`: como subir o Prometheus e
  o Grafana do compose, o que cada painel mostra, como apontar para o
  Prometheus de produção e a nota de que `/metrics` pertence à rede de gerência,
  com o token opcional.
- **Spec**: emenda ao item 15 do §25 (métricas na API, não no worker, com o
  motivo do fork) e o §22 da Fase 6 anotado com o que esta parte entregou.
- **CLAUDE.md**: bullet do estado do repositório para esta frente.
- **README**: os serviços novos do compose, as portas e o `.env` do token.

## 10. Decisões desta frente

1. **Agendamento no próprio worker** (`with_scheduler=True`), com arm no boot e
   rearm ao fim de cada varredura. Um serviço `RQScheduler` separado foi
   descartado por não eliminar a lógica de arm nem o estado no Redis; o cron
   externo foi descartado por tirar a periodicidade do produto.
2. **Intervalo global** (`GERENET_COLLECT_INTERVAL_MINUTES`, default 0) em vez
   de coluna por equipamento: uma migration e um campo a mais por um caso de uso
   que a frota atual não tem.
3. **Resumo no `snapshot.resources`**, seguindo o precedente de
   `anomalias_prefixos`, sem tabela nova.
4. **Falha do reconcile não derruba a coleta**, com evento próprio; divergência
   consciente da convenção do `sincronizar_mpls`, registrada aqui.
5. **`/metrics` só na API**, com emenda ao §25.15 pelo fork do RQ por job.
6. **Sem autenticação por padrão**, com token bearer opcional; o endpoint vive
   na rede de gerência.
7. **Registry por aplicação** no `prometheus_client`, para a suíte poder criar o
   app quantas vezes quiser sem duplicar séries.
8. **Notificações fora desta frente**: o alerta do Grafana cobre o primeiro caso
   de uso, e notificação de verdade (canal, destinatário, anti-spam) é frente
   própria.

## 11. Dívidas registradas

- **Modo multiprocesso no worker** (métricas de processo), adiado com o motivo
  do item 5 acima.
- **Separação das filas em dois workers**, se a varredura passar a atrasar
  mudanças aprovadas.
- **Margem da regra de idade da varredura**, hoje com limite de 2× o intervalo.
- **Pós-check do MTU do AC de VSI** e as demais dívidas já registradas nas fases
  4 e 5 seguem como estavam.
