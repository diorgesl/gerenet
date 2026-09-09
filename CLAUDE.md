# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral do projeto

**Gerenciador de Rede Huawei VRP** — plataforma web para cadastrar, provisionar, validar, auditar e manter serviços de rede em equipamentos Huawei VRP (roteadores NE8000 para BGP; switches para MPLS). O repositório **ainda não contém código**: a fonte de verdade do produto é [ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md](ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md) (referenciada abaixo como §). Os nomes de seção/parágrafo deste arquivo apontam para ela — leia a seção completa antes de modelar ou implementar qualquer parte.

Escopo inicial: downstreams e upstreams BGP (IPv4, IPv6 e dual stack), VLANs/subinterfaces, filtros e políticas BGP, serviços MPLS (L2VC e VSI), coleta de estado operacional, comparação intenção × configuração real e mudanças controladas com pré-validação, aprovação, auditoria e pós-validação.

**Fora de escopo** (§2.2): substituir NMS/Zabbix, configuração multi-fabricante, mudanças automáticas sem aprovação, gerenciamento de OLT/BNG/CGNAT.

Idioma dos artefatos: **português (PT-BR)**.

## Princípios de arquitetura (inegociáveis) — §3

1. **Source of Truth**: o PostgreSQL guarda a *intenção* da rede (clientes, equipamentos, interfaces, VLANs, ASNs, políticas, sessões BGP, serviços MPLS). O estado do equipamento é o *estado real*. Nunca assumir que o banco reflete o equipamento — antes de aplicar uma mudança, coletar e comparar desejado × encontrado.
2. **Mudanças idempotentes**: reexecutar a mesma operação não duplica regras, peers, interfaces ou serviços; reconhecer objetos existentes e gerar somente a diferença.
3. **Segurança por padrão**: toda alteração segue 10 passos — validar dados → coletar estado → verificar conflitos → gerar plano → mostrar diff e comandos → exigir aprovação conforme política → backup/checkpoint → aplicar → validar resultado → registrar auditoria.
4. **Intenção ≠ implementação**: objetos de negócio são estruturados (nunca blocos soltos de CLI como dado principal); templates por plataforma/versão transformam os dados em configuração.

## Arquitetura proposta — §4

Componentes (§4.1): interface web (cadastro, aprovação, auditoria, tarefas) · API (regras de negócio, validação, autenticação) · PostgreSQL · worker assíncrono (coleta/validação/provisionamento) · Nornir (inventário em runtime, filtros, concorrência) · Netmiko (SSH/CLI Huawei VRP) · NETCONF opcional · Jinja2 (templates versionados) · Redis (fila/locks) · Vault (credenciais) · Git (templates, parsers, políticas).

Stack sugerida (§4.2): Python + FastAPI · SQLAlchemy + Alembic · PostgreSQL · Nornir + Netmiko + Jinja2 · TextFSM/TTP ou parsers próprios testados · Celery ou RQ + Redis · React/Next.js ou interface server-side no MVP · autenticação local no MVP (evoluir p/ OIDC/LDAP) · Docker Compose · logs estruturados + Prometheus, integração Zabbix/Grafana.

Fluxo lógico (§4.3): operador → web/API → (Source of Truth e fila de tarefas) → motor de automação → Huawei VRP, com retorno ao banco.

## Inventário e capacidades — §5

Equipamento: nome único, endereço de gerenciamento, fabricante/modelo/família (NE8000, NE40, S6730…), versão VRP, função, site/POP, loopback/router-id, ASN local, domínio MPLS, grupo de credencial, método de acesso (SSH/NETCONF), status admin e de comunicação, última coleta, tags.

- Credenciais **nunca** no registro do equipamento: referenciar grupo de credenciais em armazenamento seguro.
- Manter **capacidades por equipamento** (IPv6, NETCONF, commit/rollback, configuration replace, route-policy vs. XPL, MPLS LDP, limites de nomes/regras) para não gerar comandos incompatíveis com família/versão.

## Domínios do sistema

### Downstreams — §6
- Cliente: razão social, ASN, IRR AS-SET, prefixos autorizados V4/V6, máximo de prefixos, POP, roteador de borda, switch de acesso, porta/Eth-Trunk, tipo de serviço, observações.
- Circuitos (§6.2): VLAN única ou separada por família, QinQ, subinterface/Eth-Trunk, MTU, banda, endereços e prefixos locais/remotos (V4 `/30`/`/31`, V6 `/64`), VRF/VS, roteador principal e de contingência, BFD, status. Validar VLANs/endereços em uso no mesmo domínio.
- Sessão BGP (§6.3): por família — endereços local/remoto, ASNs, source-address, AFI/SAFI, route-policies in/out, prefix-lists, AS-PATH filter, communities, local-preference, MED, prepend, maximum-prefix + limiar, timers, BFD, password (segredo), graceful restart, shutdown admin, política de default/full/parcial.
- Filtros de entrada (§6.4): prefixos não autorizados, bogons/martians, default não autorizada, more-specifics além do limite, ASN de origem errado, trânsito indevido no AS-PATH, excesso de prefixos, rotas próprias recebidas, communities não autorizadas. Prefixos autorizados: manual ou IRR/RPKI, sempre com aprovação humana.
- Políticas de saída (§6.5): produtos (default; default + internas; parcial; full; CDN; conjunto personalizado) — construir a route-policy a partir do produto, sem edição manual por cliente.
- Estados de provisionamento (§6.6): rascunho → aguardando validação → pronto → aguardando aprovação → provisionando → ativo e sincronizado / ativo com divergência / degradado / suspenso / em desativação / desativado / erro.

### Upstreams — §7
Reusa circuito/sessão BGP + operadora, tipo (trânsito/IX/PNI/contingência), capacidade, prioridade/custo, política de entrada e anúncio, communities aceitas, blackhole e prepend por região, limite de prefixos, validação RPKI, política de contingência. Proteções: maximum-prefix com margem, rejeição de bogons e rotas próprias, bloqueio padrão sem política vinculada, alerta de variação anormal de rotas, registro do nº de rotas antes/depois.

### Políticas e nomenclatura — §8
Objetos reutilizáveis (políticas de importação/exportação, conjuntos de bogons/prefixos próprios/do cliente, communities, local-preference, prepend, blackhole, RPKI, perfis de timer/BFD). Nomes normalizados respeitando limites do VRP, mostrando nome lógico × nome efetivo. Ex.: `RP-<CLIENTE>-IMPORT-V4`, `IP-PFX-<CLIENTE>-IN-V6`, `PEER-DOWN-<CLIENTE>-V4`.

### MPLS em switches — §9
- Domínio MPLS: PEs, loopbacks LDP, interfaces de core, estado MPLS/LDP, peers, MTU, IDs/VLANs/portas ocupadas.
- L2VC (§9.2): pontas A/B, interfaces/VLANs de acesso, dot1q/QinQ, peer LDP, VC-ID, MTU, control-word, flow-label, redundância. Validações: VC-ID único no domínio, VLAN livre, peer alcançável, MPLS/LDP operacional, MTU fim a fim, sem binding conflitante, simetria entre pontas.
- VSI (§9.3): sinalização LDP inicialmente, PEs participantes, attachment circuits, split-horizon, MAC learning/limite, status por pseudowire e AC. Gerar configuração de **todos** os equipamentos na mesma mudança lógica; falha de uma ponta ⇒ "parcialmente provisionado" exigindo reconciliação.
- Alocação interna de recursos (§9.4): VLAN por POP/porta/domínio, VC-ID, VSI-ID, IPv4, IPv6, índices de route-policy, regras de ACL. NetBox apenas como integração futura.

### Descoberta e reconciliação — §10
Coleta periódica: configuração relevante, interfaces, VLANs, peers BGP + estado + nº de prefixos, policies/prefix-lists/AS-PATH/communities, LDP, L2VCs, VSIs/pseudowires, alarmes, versão/uptime. Cada objeto apresenta desejado × encontrado × última coleta × diferenças × severidade × ação recomendada. **No MVP a reconciliação não corrige produção**: gera plano para aprovação.

## Modelo de dados inicial — §14

Entidades: `sites`, `devices`, `device_interfaces`, `credential_groups`, `organizations`, `contacts`, `circuits`, `vlans`, `ip_prefixes`, `bgp_sessions`, `bgp_policy_profiles`, `bgp_prefix_authorizations`, `communities`, `mpls_domains`, `l2vc_services`, `vsi_services`, `service_endpoints`, `allocations`, `device_snapshots`, `change_requests`, `change_steps`, `approvals`, `job_runs`, `audit_events`.

Regras de banco (§14.1): ASN válido de 32 bits (respeitando reservados); sem sobreposição de prefixos no mesmo domínio; VLAN única no escopo; VC-ID/VSI-ID únicos por domínio; sessão BGP não duplicada no mesmo equipamento+VRF/VS+família; objetos em uso **desativados, nunca excluídos fisicamente**; segredos nunca em logs, snapshots ou auditoria.

## Fluxo de mudança — §12

- **Change Plan** (§12.1): motivo, solicitante, objetos/equipamentos afetados, dependências, config atual × desejada, comandos previstos e de rollback, testes antes/depois, estimativa de impacto, janela.
- **Pré-checks** (§12.2): acessibilidade, privilégio, config inalterada desde o plano, CPU/memória, sem alarmes críticos, recursos disponíveis, peer alcançável, template compatível com a versão, sem outra mudança ativa no equipamento.
- **Aplicação** (§12.3): lock por equipamento → salvar config/evidências anteriores → comandos em blocos pequenos → identificar erros do VRP → interromper em erro crítico → registrar saída de forma segura → pós-checks → liberar lock → atualizar status.
- **Rollback** (§12.4): estratégia explícita por tipo (comandos inversos gerados, rollback nativo/checkpoint, restauração controlada, ou manual documentado). Automático só quando classificado como seguro; perda de conectividade **não** dispara comandos às cegas.

Pós-validação (§13): BGP — peer Established, ASNs, address-family, políticas vinculadas, prefixos dentro do esperado, sem quedas inesperadas de outros peers, logs limpos. MPLS — LDP operacional, L2VC/VSI Up, pseudowires e ACs Up, MAC aprendendo, MTU consistente, sem alarmes novos.

## API e interface web — §15–16

API REST `/api/v1/...`: devices, sites, organizations, downstreams, upstreams, circuits, bgp-sessions, policy-profiles, mpls/l2vc, mpls/vsi, allocations, change-requests, jobs, audit-events, reconciliation. Operações que alteram dispositivos **criam change request**; POST de cadastro não executa no roteador.

Web: dashboard (estado de equipamentos, peers, divergências, aprovações pendentes, falhas, uso de recursos) e assistentes de downstream (cliente → ASN/prefixos → POP/equipamentos → stack → reservas → perfil de roteamento → revisão → plano → aprovação) e de MPLS (L2VC/VSI → domínio → equipamentos → reservas → validação → config de todas as pontas → provisionar).

## Acesso, auditoria e segurança — §17–19

Perfis: Visualizador / Operador / Aprovador / Executor / Administrador; opcional impedir mesma pessoa solicitar+aprovar+executar mudança crítica.

Auditoria (§18): usuário, data/hora, origem, objeto, valores antes/depois, ticket, aprovação, equipamentos, comandos gerados × enviados, respostas, testes, rollback — trilha não editável; passwords/communities/tokens mascarados.

Segurança (§19): conta de automação identificável, SSH com host keys validadas, rede de gerenciamento dedicada, TACACS quando possível, dados sensíveis criptografados em repouso, **nunca credenciais em YAML/Git/templates**, limite de concorrência por site/equipamento, locks, timeout e circuit breaker, mascaramento de logs, backups periódicos.

Observabilidade (§20): duração/sucesso por tarefa e equipamento, inalcançáveis, mudanças pendentes, divergências por severidade, peers por estado, L2VCs/VSIs por estado, idade da coleta, tamanho da fila.

## Estratégia de testes — §21

Automatizados: modelos/regras de negócio, renderização de templates, parsing de `display`, geração de config de criação/remoção, detecção de conflitos, idempotência, mascaramento de segredos, permissões, rollback. Laboratório: variações de versão, erros do CLI, tempo de execução, quebra de SSH, config parcial, perda de comunicação, remoção, rollback, concorrência. Implantação gradual: somente leitura → backup → geração sem execução → laboratório → switch não crítico → MPLS com aprovação manual → downstream de teste → produção controlada → upstreams por último.

## Roadmap e MVP — §22–24

Fases: 1) inventário e coleta (Nornir/Netmiko, backup, auditoria básica) → 2) Source of Truth e validação (organizações, circuitos, VLAN/IPAM, sessões BGP, divergência, templates) → 3) downstreams (assistente, dual stack, filtros, planos, execução aprovada, pós-validação BGP) → 4) MPLS (L2VC e VSI) → 5) upstreams e políticas avançadas (full routes, communities de TE, prepend, blackhole, IRR/RPKI) → 6) integrações (Zabbix/Grafana/n8n, NetBox opcional, reconciliação agendada, notificações, ativação externa, relatórios).

**MVP** (§23): inventário Huawei + cadastro de downstreams/circuitos dual stack + reserva de VLAN/endereços + prefixos autorizados + geração de subinterface/filtros/peer BGP no NE8000 + mostrar comandos/diff sem executar por padrão + aplicar após aprovação + validar `display bgp peer` + backup/auditoria + L2VC entre dois switches + consulta de VSI (sem provisionamento automático). Upstreams e VSI multiponto somente após estabilizar o fluxo de downstream/L2VC.

Critérios de aceite do MVP (§24): sem segredo em texto puro; cadastro de 1 NE8000 + 2 switches; coleta paralela controlada; inventário de interfaces/peers; detecção de duplicidade de VLAN/endereço; geração correta V4/V6/dual stack; políticas BGP explícitas sempre; visualização antes da aplicação; aprovação registrada; backup pré-mudança; parada em erro do VRP; pós-check BGP/L2VC; histórico completo; geração de remoção; teste de idempotência aprovado.

## Decisões registradas — §25

As decisões de implementação do §25 foram **registradas em 2026-09-02** na própria spec (mantendo a numeração original). Destaques que alteram o restante do documento:

- Nomes VRP derivam do **ASN** do par (`RP-<ASN>-IMPORT-V4`), não de código de cliente (§25.4);
- Catálogo completo de produtos de roteamento desde o MVP (§25.5);
- IPAM no PostgreSQL; IPv4 p2p `/31` (opção `/30`) em bloco privado; IPv6 p2p **`/126` com sufixo derivado dos dígitos decimais dos octetos 2–4 do IPv4 relidos como hex** (local `:1`, remoto `:2`) (§25.8);
- Peers na instância pública; route-policy clássico + XPL por capacidade; acesso via TACACS+;
- Dupla aprovação por criticidade; rollback conservador por capacidade; lock 1/equipamento + limite por POP; métricas via Prometheus/Grafana (Zabbix na F6).

## Estado do repositório

- Já há código (ciclo A/C1): SoT + API FastAPI `/api/v1` + CLI Typer + worker RQ + pytest/ruff.
  Comandos: `uv run pytest -q`, `uv run ruff check`, `uv run alembic upgrade head`,
  `uv run uvicorn gerenet.api.main:create_app --factory` (dev). A interface web (ciclo C)
  nasce no `web/` (C2) e é servida pelo próprio FastAPI.
- Web (ciclo C2): `web/` é React + Vite (`/api` proxyado para :8000 no dev).
  Scripts: `npm run dev` (Vite), `npm run build` (`tsc -b && vite build` → `web/dist`,
  servido pelo FastAPI — sem build, a SPA não é atendida), `npm run test` (Vitest),
  `npm run test:e2e` (fumos Playwright: webServer sobe build + uvicorn em :8000
  — o uvicorn do webServer é iniciado na raiz do repo, pois `static_dir` `web/dist`
  é relativo ao CWD; e o globalSetup `web/e2e/setup.ts` roda o seed idempotente;
  run-book em `web/e2e/README.md`). Os e2e exigem o banco **dedicado**
  `gerenet_e2e` (criado e migrado à parte — nunca o default `gerenet`); com
  `reuseExistingServer: false` (desde o C3), porta 8000 ocupada = **falha dura no
  boot** — nunca reusa o uvicorn de dev.
- Web (ciclo C3): edição/reativação de todas as entidades com página web
  (ver desativados + Editar/Reativar em dialogs acessíveis — `Modal`); catálogos
  (communities, policy-profiles) passaram a ter update/PATCH/CLI `update` (criação
  continua apenas via seed); login tem rate limit por IP+username no Redis
  (5 falhas → 429 + Retry-After; fail-open se o Redis cair) e desativar usuário
  revoga as sessões; dashboard usa `by_comm_status` e `snapshot_age_seconds`;
  `npm run test:e2e` tem guard com `reuseExistingServer: false` (porta 8000
  ocupada = falha dura).
- Web (ciclo E): **wiki operacional** — página `/wiki` (grupo de nav "Ajuda",
  rota na SPA), API `/api/v1/wiki` (router `gerenet.api.wiki`, renderização
  server-side com `markdown` + sanitização `nh3` — a SPA nunca renderiza
  markdown cru); conteúdo em `docs/wiki/` (10 páginas PT-BR, frontmatter
  `title`/`secao`/`order`/`em_breve`, `em_breve: true` = badge "(em breve)" na
  sidebar + aviso na página); **tooltips de campo** — prop `help` no `FormField`
  (`.field-help` + `.field-help-dica` no hover/foco), textos centralizados em
  `web/src/help.ts` (o `npm run build` valida as chaves).
- Ciclo D (fluxo de mudança controlada): mudanças em **equipamento** (a SoT
  permanece a intenção — é a configuração real que muda) passam pelo fluxo de
  change requests — máquina de estados (rascunho →
  aguardando_aprovacao → aprovado → executando → aplicado/com_divergencia/parcial/
  erro; rejeitado/cancelado), planos de provision/remoção gerados da SoT × última
  coleta já na criação (diff por bloco, `automation/changes.py`), aprovação
  única com papel `aprovador`/`administrador` e aprovador ≠ solicitante (`require_papel`),
  **worker com fila `gerenet-change`** — `POST /{cr_id}/executar` enfileira antes
  de transitar (202 + `enqueue_change`; com o worker parado a CR fica
  `executando` = "jobs fake" do spec §10), lock por CR e device, backup
  pré-mudança, re-diff na execução, pós-check `reconciliar_device` e classificação
  ao final —, rollback como nova CR inversa em `aguardando_aprovacao` (422 sem
  steps aplicados), e reconciliar reabre ciclo de aprovação só para steps não
  aplicados. CLI: grupo `gerenet change-requests`
  (add/list/show/send/approve/cancel/execute/rollback/reconcile). Web: páginas
  `/change-requests` (lista/detalhe com diff por bloco e ações por papel),
  "Solicitar mudança" nos detalhes de circuito e de sessão BGP, e card
  "mudanças aguardando aprovação" no dashboard; e2e `web/e2e/change.spec.ts`
  (fumo solicitando como `admin` e aprovando como o `e2e-aprovador` — papel
  `aprovador` — seedado no globalSetup, único usuário novo do seed).
- Fase 4 (MPLS em switches): domínios MPLS/LDP + L2VC ponto a ponto com
  provisionamento/remoção via fluxo de CR; VSI é só cadastro e consulta
  (provisionamento multiponto em fase posterior). Modelos novos:
  `mpls_domains` + `mpls_domain_members` (membro = PE com `loopback_address`, o
  remote do VC), `l2vc_services` + `service_endpoints` (pontas com interface e
  VLAN de AC reservada por device — `vlans.kind='mpls_ac'`, escopo por device:
  mesmo VID é legítimo em switches diferentes do mesmo POP) e `vsi_services`;
  IDAM simples (UNIQUE + helpers `proximo_vc_id`/`proximo_vsi_id`/
  `reservar_vlan_ac`, sem tabela `allocations`). `devices.capabilities` (JSON,
  ex.: `"mpls_flow_label"`) gateia o flow-label do template. CR generalizada:
  `circuit_id` nullable + `escopo` (`circuito`|`l2vc`|`vsi`) + `l2vc_id`,
  máquina de estados intacta; render/plano/pré-pós-check em `automation/l2vc.py`
  — template `l2vc_ac.j2` com **AC untag na interface principal** (`undo
  portswitch` + `mtu` quando definido + `mpls l2vc <peer-loopback> <vc-id>[
  control-word]` + `mpls l2vpn flow-label both` em linha separada; remoção =
  `undo mpls l2vc ...` no contexto da interface, nunca `undo interface`/`undo
  portswitch`/`undo mpls l2vpn flow-label`) e runner escopo-aware (gate de
  re-diff, setup e pré-check LDP por `escopo`). Coletores/parsers
  TextFSM de `display mpls ldp peer`/`display mpls l2vc`/`display vsi verbose`
  (formatos validados em S6730 real — família S: peers em tabela SEM estado,
  L2VC em blocos por VC, VSI só com ID no verbose; o estado do par LDP vem de
  `display mpls ldp session`, ainda não coletado) + sincronização
  na SoT pós-coleta (`sincronizar_mpls`); web `/mpls/domains`,
  `/mpls/l2vc`, `/mpls/vsi` (lista/detalhe com "Solicitar mudança") e fumo
  `web/e2e/mpls.spec.ts`. Comandos de teste: `uv run pytest -q`,
  `uv run ruff check src tests`, `cd web && npm run build && npm run test`
  (e2e idem ciclo D, banco `gerenet_e2e`). A validação em equipamento real segue
  `docs/runbook-validacao-switch-mpls.md` (somente leitura → geração sem
  execução → teste em switch não crítico; **sem lab** — decisão do usuário
  2026-09-07). Etapa 1 validada em S6730 real em 2026-09-08: parsers ajustados
  aos formatos reais (fixtures `tests/fixtures/huawei_vrp/s6730_*`), coletor
  passou a usar `display mpls l2vc` e `display vsi verbose`, estado do par LDP
  fica `None` ("desconhecido") sem `display mpls ldp session` — evidência ainda
  pendente: sessão LDP (estado do par) e confirmação do `display l2vc` sem
  `mpls`. Atenção: rollback e reconciliação de CR de escopo `l2vc` ainda
  não são automatizados (`gerar_rollback`/`reconciliar` são circuitocêntricos
  — 400 guardado na API) — reversão/recomposição via CR de remoção aprovada
  (`--acao remove`) ou CR de provision nova (o re-diff aplica só a ponta
  ausente), conforme o runbook.
- Fase 5 (upstreams): organizações com `kind='operadora'` (ASN + IRR AS-SET)
  e upstreams com tipo (`transito`/`ix`/`pni`/`contingencia`), capacidade,
  prioridade/custo, prefixos esperados v4/v6 e margem do maximum-prefix;
  modelos `upstreams` + `upstream_circuits` (vínculo com papel
  `principal`/`contingencia` + `ordem`; um circuito pertence a no máximo um
  upstream — UNIQUE em `circuit_id`, BR-1 §7), `upstream_communities`
  (valor concreto, `purpose` blackhole/prepend/lp/info, `direcao`, `regiao`,
  `bloquear`: info+bloquear = deny no import via community-filter; info sem
  bloquear = community de "parcial" do `up-parcial`; prepend/lp/blackhole =
  aplicações no export via `apply community`), `roas` (lote do rpki-client)
  e `irr_cache` (consultas IRR com TTL) — migrações
  `alembic/versions/767551f719ba_upstreams_f5.py` (tabelas) e
  `alembic/versions/7dd3d6db4796_upstream_circuits_circuito_unico.py`
  (fix R-07: UNIQUE em `circuit_id`). Produtos de import por
  tipo (transito/ix → `up-full`, pni → `up-parcial`, contingencia →
  `up-default`; sessão sem perfil ⇒ deny-all fail-safe) e export
  `IP-PFX-<ASN>-EXPORT-<AFI>` (`naming.pfx_export` — deriva do ASN do par,
  §25.4, nunca global) + communities de ação; `maximum_prefix` das sessões
  é repropagado = esperado × (1 + margem), limiar padrão 80 %. Revisão fina
  2026-09-08 (notas em `docs/superpowers/specs/
  2026-09-08-gerenet-fase5-upstreams-revisao-notas.md`): rotas próprias
  rejeitadas no import do up-full via as-path-filter `AS-PATH-<ASN>-OWN`
  (nó deny; depende de `devices.asn`); B5 calculado no COLETOR
  (`bgp_anomalia_janela`/`bgp_anomalia_pct` em `config.py`; gravado em
  `snapshots.resources["anomalias_prefixos"]` — a reconciliação só exibe);
  `PreRcv` `-` (peer sem rotas) vira `None` no merge do parser; CR de
  upstream `remove` terminada `aplicado` desativa o upstream via
  `disable_upstream` (audit `upstream.disable`; circuitos/sessões
  permanecem) e `prefixos_antes`/`prefixos_depois` contam sessões
  desativadas (`include_disabled`, só na remoção).
  Autorizações de prefixo: `origin` (`manual`|`irr`|`rpki`) + `validacao`
  (`ok`|`diverge`|`desconhecida`|`nao_verificada`) — **consultiva §10.4,
  nunca bloqueia** (a aprovação continua humana). CLI: `gerenet irr query
  <asn|as-set> [--source radb|altdb|lacnic] [--ttl-horas 24]` (cache
  `irr_cache`) e `gerenet rpki sync [--file <caminho>]` (default
  `GERENET_RPKI_ROAS_FILE`; ao final revalida as autorizações irr/rpki).
  CR de escopo `upstream` no fluxo do ciclo D: plano agregado por device em
  `automation/upstream.py` (sessões + circuitos vinculados; diff por bloco já
  na criação), pré-check (`bgp_peers`, ASN conflitante, sessão no device) e
  pós-check (peer + Established + contagem dentro de esperado × (1 ± margem))
  — rollback (`gerenet change-requests rollback`) e reconciliar
  **disponíveis** para upstream (ao contrário do l2vc/vsi). Web: `/upstreams`
  + `/upstreams/:id` (detalhe com a matriz principal × contingência e
  "Solicitar mudança") e fumo `web/e2e/upstream.spec.ts` (org operadora pela
  UI, upstream, community, vínculo e CR aprovada pelo `e2e-aprovador`;
  rerun-safe por `Date.now()`). Validação em equipamento real segue
  `docs/runbook-validacao-upstream.md` (somente leitura → geração sem
  execução → teste em circuito/edge não crítico → IRR/RPKI consultivo →
  rollback aprovado antes; **sem lab** — decisão registrada).
- Convenções previstas no `.gitignore`: Python com venv e pytest (`.venv/`, `.pytest_cache/`), deploy via Docker Compose (`compose.yaml` na raiz) com `.env` ignorado (o `.gitignore` ainda prevê `deploy/docker/.env`), `config.yaml` local com segredos **fora do repositório**, logs em `logs/` ignorados.
- `.claude/settings.local.json` contém token e aponta o harness para uma API externa: é arquivo local — não versionar nem alterar.
