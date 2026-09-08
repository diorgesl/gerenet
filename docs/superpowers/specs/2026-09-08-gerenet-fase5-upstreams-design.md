# Design — Fase 5: Upstreams e políticas avançadas (gerenet)

> Especificação da **fase 5** do gerenet — conectividade própria de
> trânsito/IX/PNI como entidade do sistema (**upstream**), reutilizando o
> modelo de circuitos e sessões BGP; render de importação full/parcial/default,
> anúncio de internas e clientes ao trânsito, communities de engenharia de
> tráfego (por operadora), proteções §7.1, validação IRR/RPKI consultiva e
> política de contingência. Documentos-fonte: spec §7, §7.1, §8, §10, §12–13,
> §14–16, §21, §22–24 e §25 (decisões 4, 6, 7, 8, 10, 12); decisões do
> brainstorming 2026-09-08 (registradas na §10); designs do ciclo B
> (render/divergência), D (mudança controlada) e da fase 4 (MPLS).

## 1. Objetivo e escopo

Cobrir os itens da **Fase 5** do roadmap (§22), em um único ciclo, por estágios:

1. **Upstream como entidade**: cadastro de operadora e upstream, vínculo com
   N circuitos (papel principal/contingência, ordem) e sessões BGP
   associadas (V4/V6/dual stack), reutilizando `circuits`/`bgp_sessions`.
2. **Políticas**: produtos de importação (full/parcial/default do provedor),
   anúncio ao upstream (internas + clientes autorizados), aplicação de
   communities de engenharia de tráfego com valores reais por operadora.
3. **Proteções §7.1**: maximum-prefix com margem, rejeição de bogons e rotas
   próprias, bloqueio padrão sem política vinculada, alerta de variação
   anormal de rotas, registro de contagem antes/depois.
4. **IRR/RPKI**: autorizações de prefixo com origem `irr`/`rpki` (com
   aprovação humana), consulta IRR com cache e ROAs de validador local.
5. **Contingência**: papel/ordem por circuito e atributos de contingência
   (LP/prepend) propagados às sessões de backup — **sem troca automática**.
6. **Fluxo de mudança controlada** com escopo `upstream` (plano, aprovação,
   execução, pós-validação; remoção), CLI, API e páginas web.

Fora do escopo (notas de YAGNI na §11): aplicação dura de validação RPKI no
roteador (exige RTR — fase posterior), seleção de clientes por upstream no
anúncio (YAGNI — anuncia todos os autorizados ativos), NetBox, alertas
externos (Zabbix/Grafana na F6), troca automática de contingência (§2.2),
VSI multiponto.

## 2. Contexto (verificado em 2026-09-08)

- **Não existe upstream**: nenhum modelo `upstreams`/operadora; `ORG_KIND =
  ("downstream", "parceiro")` (`models.py:25`); `Circuit` é "acesso de um
  downstream no POP" com `access_device_id` NOT NULL; `BgpSession` já cobre
  quase todo §6.3/§7 por-sessão (import/export profiles, maximum_prefix +
  threshold, local_preference, med, prepend, bfd, comunidades N:N,
  allow_default_route).
- **Catálogo de políticas**: 6 produtos de **exportação** §25.5
  (`default`, `default_internas`, `parcial`, `full`, `cdn`,
  `personalizado`) + 1 de **importação** (`somente-autorizadas`, spec §3.6).
  No render, `default_internas`/`parcial` são **dívida documentada**
  (`render.py:_bloco_export`: "rotas internas ainda não renderizáveis
  (ciclo C/F5)") — a F5 paga essa dívida com o helper de rotas internas.
- **Communities**: catálogo lógico (nome, nota, admin_status; valor concreto
  definido no render — comunidade lógica `blackhole` etc.), seeds = 3
  (`blackhole`, `no-export`, `no-advertise`); criação seed-only (ciclo C3
  criou update/PATCH). `bgp_session_communities` associa N:N sessão↔comunidade.
- **Autorizações**: `bgp_prefix_authorizations` por organização, com
  `origin` enum `manual` somente ("IRR/RPKI = F5" no docstring).
- **Fluxo de mudança**: CR com `escopo` (`circuito`|`l2vc`|`vsi`,
  `circuit_id` nullable desde a fase 4), máquina de estados D, worker
  `gerenet-change`, backup pré-mudança, re-diff na execução, pós-cheque
  `reconciliar_device`, classificação final. `plan_provision(circ)` gera
  plano por device (blocos; diff por bloco × snapshot).
- **Coleta**: coletores de `display bgp peer` (parse de estado + contagem de
  prefixos por peer — base para "variação anormal"); `peer.orfaos` já alerta
  peer coletado sem sessão cadastrada; snapshots com `resources` por device.
- **Nomenclatura (§25.4)**: nomes derivam do **ASN do par** — `RP-<ASN>-IMPORT-
  <AFI>`, `RP-<ASN>-EXPORT-<AFI>`, `IP-PFX-<CLIENTE>-IN-<AFI>`; prefixo de
  peer `PEER-DOWN-<ASN>-<AFI>` (confirmar no `naming` ao implementar).

## 3. Modelo de dados

Uma migração Alembic (idempotente, padrão das anteriores):

**Alter em tabelas existentes**

- `organizations.kind` — enum ganha **`operadora`** (migração de ENUM pg).
  Regras: organização `operadora` pode ter circuitos do tipo upstream e
  contatos; **não** pode ter autorizações de prefixo como cliente
  (validação no serviço: autorização exige org `downstream`/`parceiro`).
- `circuits` — `access_device_id` passa a **nullable** (circuito de upstream
  não tem switch de acesso); `vlan_mode` ganha valor **`none`** (handoff
  físico no edge — render de subinterface é omitido).
- `devices` — nova coluna **`loopback`** (String, nullable): loopback do
  roteador, fonte das "rotas internas" no anúncio ao trânsito (hoje só
  `mpls_domain_members.loopback_address` carrega loopback, e escopado).
- `bgp_policy_profiles` — seeds de **importação** `up-full` (label "Full —
  trânsito/IX"), `up-parcial` ("Parcial — trânsito/IX"), `up-default`
  ("Somente default"); criação continua seed-only (catálogo).
- `communities` — nova coluna **`tipo`** (enum: `padrao`, `acao_blackhole`,
  `acao_prepend`, `acao_lp`, `informacao`, `tag_produto`; default
  `padrao`; seeds existentes → `padrao`). **Cadastro passa a ser permitido**
  via API/CLI/web para comunidades novas (criação era seed-only) — é onde o
  usuário registra "communities de informação" e de ação globais; as
  **por-operadora** ficam em `upstream_communities` (abaixo).
- `bgp_prefix_authorizations.origin` — enum ganha **`irr`** e **`rpki`**;
  nova coluna **`validacao`** (String nullable: `ok`|`diverge`|`desconhecida`
  |`nao_verificada`) reavaliada pelo job de sincronização de ROAs/IRR.
- `change_requests` — `escopo` ganha **`upstream`**; nova coluna
  **`upstream_id`** (FK, nullable). Guardas da fase 4 que citam só `l2vc`
  (`change_requests.py:259,293`) ganham mensagem genérica por escopo
  (item parkado S3 da formatação → requisito aqui).

**Tabelas novas**

- **`upstreams`** — `id`; `name` (String 128, unique; nome lógico); `tipo`
  enum (`transito`|`ix`|`pni`|`contingencia`); `capacity` (String 32);
  `priority` (int nullable); `cost` (String 32 nullable); `organization_id`
  FK → organizations (validar `kind == "operadora"`); `expected_prefixes_v4`
  e `expected_prefixes_v6` (int nullable); `max_prefix_margin_pct` (int,
  default 20); `rpki_enabled` (bool default true); `contingencia_notes`
  (Text nullable); `entrada_local_preference`, `contingencia_local_preference`
  (int nullable), `contingencia_prepend` (int 0–10 nullable);
  `admin_status` (bool default true); `created_at`, `updated_at`.
  Campos credenciais/sensíveis: nenhum (senha BGP já é `password_ref` na
  sessão, path Vault).
- **`upstream_circuits`** — `id`; `upstream_id` FK; `circuit_id` FK;
  `papel` enum (`principal`|`contingencia`, default `principal`); `ordem`
  (int, default 1). UNIQUE (upstream_id, circuit_id). Regra: no mínimo 1
  circuito `principal` por upstream ativo.
- **`upstream_communities`** — `id`; `upstream_id` FK; `purpose` enum
  (`blackhole`|`prepend`|`lp`|`info`); `value` (String 64 — valor concreto,
  ex.: `65530:20:0`); `direcao` enum (`import`|`export`|`ambos`);
  `regiao` (String 64 nullable); `bloquear` (bool default false — só
  significativo para `purpose=info` no import); `notes` (Text nullable);
  `admin_status` (bool default true); timestamps. UNIQUE
  (upstream_id, purpose, value, regiao).
- **`roas`** — `id`; `prefix` (String 64); `origin_asn` (BigInteger);
  `max_length` (int nullable); `source` (String 32, default `rpki-client`);
  `valid_until` (DateTime nullable); `imported_at`; UNIQUE
  (prefix, origin_asn, max_length). Rows apenas de dados externos — sem
  soft-delete (a sincronização regrava o conjunto; a trilha fica no job).
- **`irr_cache`** — `id`; `source` (String 32 — `radb`|`altdb`|`lacnic`/
  `arin`/etc.); `key` (String 128 — AS-SET ou ASN); `payload` (JSON);
  `queried_at`; `expires_at`. UNIQUE (source, key).

**Regras §14.1 aplicadas**: ASN único global (já garantido); objetos em uso
só são desativados (upstream `admin_status=false`; circuitos e sessões
permanecem); segredos nunca em logs/snapshots (sessão já usa `password_ref`).

### 3.1 Propagação upstream → sessões (dívida de UI mantida por edição)

Ao criar/editar um upstream (ou re-sincronizar ao trocar de papel), o serviço
**propaga para as sessões dos circuitos vinculados** os defaults de política,
salvando na própria sessão (campo explícito da sessão sempre vence — assim a
sessão continua editável individualmente):

- `import_profile_id` ← `up-full`/`up-parcial`/`up-default` (escolha no
  upstream, por família? **uma escolha por upstream**; por família só se
  necessário — deixar como escolha única para não inflar o form);
- `export_profile_id` ← NULL (o anúncio ao trânsito NÃO usa o catálogo de
  produtos do cliente — ver §4.2);
- `local_preference` ← `entrada_local_preference` (se definido; se a sessão
  é de circuito com `papel=contingencia` ← `contingencia_local_preference`),
  e `prepend` ← `contingencia_prepend` quando contingência;
- `maximum_prefix` ← `expected_prefixes_<afi>*  (1 + margem/100)`;
  `maximum_prefix_threshold` ← 80 (default, sessão vence);
- **communities de ação/informação do upstream** não passam por
  `bgp_session_communities` (que liga comunidades lógicas do catálogo): o
  render da sessão de upstream lê diretamente `upstream_communities`
  (valores concretos, por propósito/região/direção) — sem associação
  intermediária;

## 4. Políticas e render

### 4.1 Importação (o que o provedor anuncia)

Novo caminho no `_bloco_import` quando a sessão pertence a circuito de
upstream (org do circuito é `operadora`):

- Produtos `up-full`: accept-all do provedor **exceto**: bogons/martians
  (reutilizar conjunto existente §6.4 — preferir deny via as-path-filters
  e prefix-lists já gerados), rotas próprias (AS-PATH contendo ASN próprio +
  more-specifics de prefixos próprios/clientes — helper de internas §4.3),
  rotas com info-community marcada `bloquear` (via `community-filter` novo,
  valor concreto de `upstream_communities`), default quando
  `allow_default_route=false` na sessão, max-prefix-limiar da sessão.
- `up-parcial`: **default + rotas portadoras da community de "parcial" do
  provedor** — definição determinística e parametrizável: a community é
  cadastrada em `upstream_communities` com `purpose=info` (direção
  `import`/`ambos`) e `bloquear=False` — é por purpose+bloquear que o render
  identifica (a nota "parcial" é opcional, para leitura humana); o render
  gera `if-match community-filter <value>` + permit (e default). Sem essa
  community cadastrada para o upstream ⇒ **comentário-dívida** (padrão da
  casa, como hoje em `default_internas`).
- `up-default`: somente `0.0.0.0/0`/`::/0` permitidos (prefix-list de
  default; como já existe para export `default`).
- **Fail-safe**: sessão de upstream sem `import_profile_id` ⇒ render
  `route_policy_import` default-deny (`comment` + apenas `deny`); NUNCA
  accept-all.
- Nomes: `RP-<ASN>-IMPORT-<AFI>` (§25.4) e `IP-PFX-<ASN>-IN-<AFI>` para a
  lista de clientes/primeiros-ASN; dedup idêntico ao atual.

### 4.2 Exportação (o que anunciamos ao trânsito)

Correção de rota no desenho (aprovado em 2026-09-08, porém o catálogo de 6
produtos é **do ponto de vista do cliente** — anúncio *para ele*): para o
upstream, o anúncio NÃO é produto. A "política de anúncio de saída" (§7) é:

- **Rotas internas** (+ loopbacks `devices.loopback` + p2p alocados ativos
  de `ip_prefixes`) — helper novo **`internas_prefixos()`**;
- **Clientes**: prefixos de `bgp_prefix_authorizations` ativas de todas as
  organizações `downstream`/`parceiro` (o próprio fato de estar autorizado
  e ativo = anunciar; desativar a autorização remove o anúncio — sem
  catálogo paralelo e sem seletor por cliente na F5);
- **Aplicações**: communities de ação do upstream (`prepend` por região via
  `if-match` na tabela → `apply community <value>`; `blackhole` com valor
  por região; `lp` em rotas de contingência) e `no-export` para rotas
  marcadas (já existente).
- Render: `_bloco_export` para upstream gera prefix-list
  `IP-PFX-<ASN>-EXPORT-<AFI>` (internas + autorizadas) e
  `RP-<ASN>-EXPORT-<AFI>`; o dedup atual se aplica.
- A dívida `default_internas`/`parcial` (produtos de CLIENTE) é paga pelo
  `internas_prefixos()` (fonte das rotas internas no render do cliente).

### 4.3 Templates

- Novo **`community_filter.j2`** (`ip community-filter <name> permit <value>`,
  padrão da nomenclatura: `CF-<ASN>-IN-...`);
- `route_policy_import.j2` — suportar os padrões up-full/up-parcial/up-default
  com os blocos da §4.1 (parametrizado por produto);
- `route_policy_export.j2` — variante upstream (anúncia de internas+clientes
  com aplicação de communities); reutilização dos blocos existentes onde
  couber.
- `bgp_peer.j2` — sem mudanças previstas (peer sem subinterface: `local_address`
  na interface física; confirmar no runbook de validação §12).

## 5. Proteções (§7.1) e variação anormal

- **Max-prefix com margem**: propagado §3.1; a sessão final carrega
  `maximum_prefix` e `maximum_prefix_threshold` (VRP já limita por peer).
- **Bogons/rotas próprias/excessivamente específicos**: no render de import
  (§4.1) — reusar objetos do §8 (conjunto de bogons, prefix-list de próprias/
  autorizados).
- **Bloqueio padrão sem política**: fail-safe §4.1 (deny); além do render,
  `reconciliar`/coleta já acusa peers sem sessão e perfis ausentes
  (`peer.orfaos`, filtros divergentes).
- **Variação anormal**: na coleta (job), o contador de prefixos por peer é
  comparado com `maximum_prefix` × margem da sessão e com o **histórico**
  (guardar no snapshot/`resources`, comparar com as últimas K coletas;
  variação acima do default configurável de 50% ⇒ **severidade
  `alerta`** em `divergencia`/métricas; sem notificação externa (F6)).
  Registro no job de coleta e exposto no dashboard de divergências.
- **Contagem antes/depois**: no worker, antes de aplicar a CR (backup/
  snapshot) e no pós-check, gravar `prefixos_antes`/`prefixos_depois` no
  step/nota da CR (campos existentes: `details` de steps).

## 6. IRR/RPKI

- **IRR** — serviço `automation/irr.py`: consulta whois (`subprocess
  “whois -h whois.radb.net”`; fonte e timeout configuráveis via settings)
  com **cache** em `irr_cache` (TTL 24h). Casos: ASN concreto (origem de um
  prefixo) e AS-SET (expandir ASNs/prefixos para conferência).
- **RPKI** — serviço `automation/rpki.py`: sincronização (job padrão
  `collect`/novo kind `rpki-sync`) de ROAs a partir de **arquivo local do
  validador** (`rpki-client` JSON: `{roas:[{prefix,maxLength,asn}]}`;
  caminho via settings/GERENET_RPKI_ROAS_FILE; nunca em git), upsert em
  `roas`; `validar(prefixo, asn)` ⇒ `ok|diverge|desconhecida`.
- **Autorizações**: `origin=irr|rpki` exigem **`confirmacao_humana`**: campo
  novo `confirmed_by`? — Decisão (§10.4): a confirmação humana é o próprio
  ato de cadastrar (usuário autenticado + trilha de auditoria §18) e o fluxo
  de mudança já exige aprovação; a validação é **consultiva**:
  `validacao` (ok|diverge|desconhecida|nao_verificada) reavaliada a cada sync
  e exibida (plano/divergência) **sem nunca bloquear o render**.
- **Aplicação duta no roteador**: fora de escopo (exige RTR/vRP RPKI nativo) —
  YAGNI §11.

## 7. Contingência

- Circuito com `papel=contingencia` + `ordem` define a ordem de preferência
  (1 = principal; contingências depois).
- Propagação §3.1 aplica LP/prepend de contingência às sessões de backup.
- `contingencia_notes` documenta o procedimento (ticket, janela etc.).
- **Troca de tráfego é manual** (§2.2, §25.12): nada muda sozinho; a
  configuração da contingência (atributos piores + política documentada)
  é pré-instalada.
- Web/CLI: matriz principal × contingência no detalhe do upstream.

## 8. Fluxo de mudança — CR escopo `upstream`

- `ChangeRequest(escopo="upstream", upstream_id=...)` — **mesma máquina de
  estados do ciclo D**; validação: upstream ativo, ≥1 circuito `principal`,
  circuitos/sessões resolvidos.
- **Plano de provision** (`automation/upstream.py` + `plano_upstream()`):
  agregação dos planos por circuito (reusa `plan_provision`) na ordem
  `ordem`, dando os blocos por device (dedup entre circuitos do mesmo
  device — ex.: duas sessões no mesmo edge): políticas (import por produto
  + export + prefix-lists/community-filters), peer por sessão. Idempotente
  (diff × snapshot; só diferença — máquina existente).
- **Pré-checks** (§12.2): para cada device/circuito: acessibilidade,
  privilégio, config inalterada desde o plano, sem outra CR ativa no device
  (lock existente), template compatível; o gate de escopo (`!= circuito`)
  hoje restrito a l2vc ganha mensagem por escopo (upstream incluso).
- **Execução**: lock por device (existente), backup, re-diff na execução,
  parada em erro do VRP (existente).
- **Pós-validação (§13)**: por sessão do upstream — peer Established, rotas
  dentro de `expected_prefixes` × margem (valores antes/depois), sem novos
  peers caídos (variação anormal), logs limpos; classificação
  `aplicado|com_divergencia|parcial|erro` (existente).
- **Remoção** (`--acao remove`): CR inversa — remove sessões BGP/políticas
  dos circuitos do upstream e **desativa** `upstreams.admin_status=false`
  (circuitos e sessões continuam; sem exclusão física §14.1). Reutiliza
  `removal.py` (inverso dos blocos).
- **Rollback** (§12.4/§25.13): comandos inversos (mesma classe de mudança
  das CRs de circuito — classificadas como seguras); a CR de remoção
  rollback = CR de provision inversa. Comportamento idêntico ao do ciclo D/F4
  (mudança por escopo continua circuitocêntrica para rollback de l2vc/vsi
  — fase 4; upstream não sofre a guarda truncada: entra como escopo
  próprio desde o início).

## 9. API, CLI e web

- **API** `/api/v1/upstreams` — CRUD + detalhe (circuitos/papel/ordem,
  sessões, `upstream_communities`, autorizações de prefixo da operação em
  si — autorizações de clientes ficam em `/prefix-authorizations`);
  PATCH/desativar; validações do serviço (org operadora, ≥1 principal,
  UNIQUEs, marge 0–100, prepend 0–10). `POST`/`PUT` de upstream **não
  executa no roteador** (regra §15) — fluxo via CR.
- **CLI** — `gerenet upstreams` (add/list/show/update/set-status) +
  `gerenet upstream-communities` (add/list/remove) + `gerenet irr query
  <as-set|asn>` + `gerenet rpki sync` (job local). `change-requests` já
  genérico; `--escopo upstream` e `--upstream-id`.
- **Web** — página `/upstreams` (lista com operadora/tipo/POPs; detalhe com
  matriz principal × contingência, sessões, communities por operadora com
  propósito/valor/região/direção/bloquear, autorizações); "Solicitar
  mudança" no detalhe do upstream e por circuito/sessão de upstream;
  card **Upstreams** no dashboard (nº de upstreams ativos × estado,
  variação anormal recente); badges em circuito/sessão quando org é
  `operadora` (label "upstream"); `web/src/help.ts` com tooltips dos novos
  campos.

## 10. Decisões registradas (brainstorming 2026-09-08)

1. **Operadora** = `organizations` com `kind="operadora"` (ASN único global,
   contatos/status/IRR já modelados); validação: autorizações de prefixo
   continuam para orgs `downstream`/`parceiro`.
2. **Upstream ↔ N circuitos** (M2M `upstream_circuits` com papel/ordem):
   cobre o caso real da operação (operadora única com **2 circuitos** hoje,
   1 POP; multi-POP futuro) e o caso simples (1 circuito = caso degenerado).
3. **Communities de TE** = dois lugares: catálogo global (`communities.tipo`
   + criação habilitada) para lógicas/informação; `upstream_communities`
   (valores concretos por operadora, propósito, região, direção, bloquear)
   para as da operadora.
4. **IRR/RPKI**: validador local (rpki-client JSON → `roas`) + consulta IRR
   (whois com cache); **consultiva** (sem RTR, sem aplicar no roteador); a
   "aprovação humana" §25.7 é o cadastro autenticado + aprovação da CR.
5. **Exportação para o trânsito ≠ produto do catálogo** (correção do
   desenho §4.2): anúncio = internas + autorizados ativos + aplicação de
   communities; catálogo (6 produtos) permanece para anúncio a clientes.
6. **Contingência** = pré-configurada (atributos piores + doc), troca manual.
7. **Circuito de upstream**: `access_device_id` nullable + `vlan_mode=none`
   (handoff físico no edge, sem subinterface).

## 11. YAGNI / follow-ups (não incluídos)

- aplicação dura de RPKI (RTR) — próxima fase com infraestrutura;
- seletor de clientes por upstream (anúncio seletivo) — evolução da
  autorização;
- dupla aprovação por criticidade (§25.10) — o fluxo mantém aprovação única
  (ciclo D); item da fase 6;
- cadastro de capilaridade de operadora (ligação/geração de circuito por
  provedor — spec §7 "capacidade contratada" como texto por ora);
- `allocations` genérica — continua IDAM simples (como fase 4).

## 12. Validação em equipamento real

Seguir o padrão da fase 4 (docs/runbook): **sem lab** (decisão 2026-09-07) —
somente leitura → geração sem execução → switch/edge não crítico com
aprovação manual; novo **`docs/runbook-validacao-upstream.md`** no estágio E
(handoff físico, `bgp_peer` sem subinterface, contagem de rotas antes/depois,
variação anormal). Adaptar o `web/e2e/README.md` de diffs caso necessário.

## 13. Testes

- **Unit (Pytest)**: modelos (UNIQUEs, enums novos, propagação sessão
  vencida por campo); serviços upstream (validação org operadora, ≥1
  principal, margem 0–100); render import (up-full com proteções,
  up-parcial com lista vazia ⇒ dívida, up-default, fail-safe deny sem
  profile, info-community bloqueadora, rotas próprias); render export
  (internas + autorizados; `internas_prefixos` com loopbacks/p2p; apply de
  communities por região); `irr.py` (cache/TTL, parse whois, falha saudável)
  e `rpki.py` (parse rpki-client JSON, upsert idempotente, validar origem);
  autorizações origem `irr`/`rpki` + `validacao`; CR escopo upstream
  (plano agrega, re-diff, remoção desativa upstream, pós-cheque contagens).
- **Golden parsers**: contagem de prefixos por peer coberta (parsers
  existentes — adicionar caso de contagem ausente/alta).
- **E2E (Playwright, banco `gerenet_e2e`)**: fumo `web/e2e/upstream.spec.ts`
  — criar operadora (org kind), upstream com 2 circuitos (1 principal + 1
  contingência), communities por operadora, solicitar CR como admin e
  aprovar como `e2e-aprovador` (papel existente do seed), verificar detalhe
  e matriz.

## 14. Estágios do plano

1. **A — Fundamentos**: migração (modelos/enums/seeds), serviço upstream +
  propagação, CLI/API básico, ajudas/UI de badge; testes de modelos.
2. **B — Render e proteções**: `internas_prefixos`, produtos de importação,
  export ao trânsito, community_filter, fail-safe; testes de render.
3. **C — CR escopo upstream**: `automation/upstream.py`, plano/remoção/
  pós-check, gates por escopo, CLI `change-requests`, worker; testes.
4. **D — Communities TE + web completa**: `upstream_communities` (API/CLI/
  páginas), tipos no catálogo com criação, dashboard, help.ts; testes/e2e.
5. **E — IRR/RPKI + docs**: `irr.py`/`rpki.py` + jobs, `validacao`, CLI
  `irr`/`rpki`, autorizações origem irr/rpki, runbook, e2e fumo.
