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
- Web (nav, 2026-09-09): **menu lateral sanfonado** — os 9 grupos/23 itens
  viraram 5 grupos sanfonados (Infraestrutura, Roteamento, MPLS, Operação,
  Gestão) com Dashboard fixo no topo e Wiki fixo no rodapé (fora das
  sanfonas); o grupo do item atual abre sozinho na navegação, os demais
  começam recolhidos; o rótulo de grupo é um cabeçalho clicável
  (`aria-expanded`/`aria-controls`) e a escolha fica em `localStorage`
  (`gerenet.nav.abertos` — o grupo ativo só reabre ao navegar de novo).
  Ícones SVG inline por item em `web/src/components/Icons.tsx` (traço 1.8,
  17px, estilo Lucide, `aria-hidden` — sem dependência nova); breadcrumb
  "grupo / item"; labels de grupo com peso 700 uppercase e hover; item ativo
  = fundo âmbar + ícone LED âmbar; sidebar com superfície própria e labels
  longos com ellipsis. Testes: `Layout.test.tsx` cobre a sanfona e os fumos
  expandem o grupo antes de clicar o item (`change`/`smoke`/`upstream`).
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
  (provisionamento multiponto em fase posterior — entregue na Fase 4, parte 3,
  bullet adiante). Modelos novos:
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
  `display mpls ldp session`, coletado na Fase 4, parte 2) + sincronização
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
  ficava `None` ("desconhecido") sem `display mpls ldp session` — evidência
  pendente na ocasião: sessão LDP (estado do par, coletada na Fase 4, parte 2) e
  confirmação do `display l2vc` sem `mpls`. Atenção: nessa fase o rollback e a
  reconciliação de CR de escopo `l2vc` ainda não existiam
  (`gerar_rollback`/`reconciliar` eram circuitocêntricos — 400 guardado na API)
  — reversão/recomposição via CR de remoção aprovada (`--acao remove`) ou CR de
  provision nova (o re-diff aplica só a ponta ausente), conforme o runbook;
  ambas passaram a existir na Fase 4, parte 2 (bullet seguinte).
- Fase 4, parte 2 (pendências do L2VC, 2026-09-13): a coleta do recurso
  `mpls_ldp_peer` passou a rodar também `display mpls ldp session` (parser
  `mpls_ldp_session`, merge cruzando por `PeerID` sem o `:0`), o que destrava o
  pré-check do L2VC que antes parava em "estado desconhecido"; o rollback e a
  reconciliação de CR de escopo `l2vc` passaram a existir (`gerar_rollback`
  deriva o plano da **coleta atual** e o `_replaneja` aceita a ação como
  parâmetro), e a web mostra os botões para esse escopo; o parser de L2VC passou
  a extrair `AC status` e MTU local/remoto e o pós-check a validá-los
  (`l2vc.ac`, `l2vc.mtu`, `l2vc.mtu_simetria`, todos `atencao`, com o MTU só
  conferido com o VC de pé). Corrigido de passagem: o rollback de CR de remoção
  (circuito e upstream) planejava o filho com a ação do pai e recebia blocos
  `delete`. O provisionamento VSI multiponto segue como frente seguinte
  (rollback/reconciliação de `vsi` continuam indisponíveis) — entregue na
  Fase 4, parte 3, bullet seguinte.
- Fase 4, parte 3 (VSI multiponto, 2026-09-13): fecha a fase — o VSI passou a
  ser **provisionável**, com um **AC por PE** (`service_endpoints` com
  `kind='vsi'`, VLAN de AC de `vlans.kind='mpls_ac'` reservada por device e a
  interface **derivada do VID** como `Vlanif<vid>` — nunca campo livre; VID
  omitido assume o `vsi_id`, a convenção da operação) e os campos novos
  `vsi_services.flow_label`/`description` (migração
  `alembic/versions/9b1f7c4e2a05_vsi_multiponto.py`, com `change_requests.vsi_id`
  e os dois campos em `vsi_services`). Templates `vsi.j2` (bloco do
  serviço: `vsi <nome> static`, `description`, `pwsignal ldp` com `vsi-id`,
  `flow-label` só com a capability `mpls_flow_label` e uma linha `peer` por
  membro restante, e `mtu`) e `vsi_ac.j2` (`vlan` + `interface Vlanif<vid>` +
  `description`, ` mtu` (o da ponta, ou o do serviço quando ela não tem) e
  ` l2 binding vsi <vrp_name>`, indentados por serem sub-comandos); dois blocos por
  PE e **um step por PE** na CR de **escopo `vsi`** (o provisionamento exige 2+
  endpoints; o cadastro aceita um). Pré-check `valida_pre_checks_vsi` (simetria
  de membros, par LDP **UP** de cada peer e Vlanif sem binding alheio — `None`,
  `down` ou coleta sem `mpls_ldp_peer` bloqueiam), pós-check `valida_pos_vsi`
  (`vsi.ausente`/`vsi.estado`/`vsi.peer` críticos; `vsi.ac`/`vsi.mtu` de
  atenção), gate de coleta `("interfaces", "vsi", "config_backup")`, e
  **rollback e reconciliação** de escopo `vsi` disponíveis (os dois dicionários
  de indisponível ficaram vazios; o filho deriva da coleta atual, como o
  `l2vc`) — uma ponta que falha deixa a CR em `parcial`. O parser `vsi` passou
  a ler os **três níveis** do `display vsi verbose` (nome/estado/ID/MTU do VSI,
  `Peer Router ID`/`Session` por peer, `Interface Name`/`State` por AC; a seção
  `**PW Information` não é parseada — aparece em poucos VSIs e repete o
  `Session`) e o `sincronizar_mpls` atualiza o `operational_status` de cada AC,
  sem rebaixar o VSI (o estado do serviço segue vindo do `VSI State`). A
  remoção desfaz **só** o binding e o VSI (`undo l2 binding vsi <nome>` no
  contexto da Vlanif e depois `undo vsi <nome>`, nessa ordem porque o VRP
  recusa remover VSI com AC ligado): a `Vlanif` e a `vlan` **ficam** no
  equipamento. Web: `/mpls/vsi` com "Novo VSI" (domínio, nome, VSI-ID, MTU,
  descrição, flow-label e uma linha por PE com VID/MTU) e `/mpls/vsi/:id` com
  ACs, "Solicitar mudança" e desativar/reativar; CLI
  `gerenet mpls vsi add --endpoint DEVICE:VID`
  (repetível, `--flow-label`) e `change-requests add --escopo vsi --vsi-id`.
  `split_horizon`/`mac_learning`/`mac_limit` ficam de fora do formulário e do
  CLI: existem na SoT mas o template não os emite.
  Dívidas registradas (design §12): aprendizado de MAC (exige
  `display mac-address` e item de pós-check próprios), `tnl-policy` fora do
  modelo e do render, e a limpeza da `Vlanif`/`vlan` na remoção (a sobra é
  decisão registrada, visível na divergência). O cadastro de VSI pela web
  (2026-09-14) expôs o MTU por ponta e o render passou a emiti-lo no AC;
  como o re-diff identifica o AC pela `Vlanif`, serviços já provisionados
  **não** ganham a linha até um re-provisionamento (remoção + provisionamento)
  — uma CR de provisionamento nova apenas pula o bloco, sem aplicar nada —, e
  conferi-la exige a config da Vlanif (o `display vsi verbose` não traz MTU
  por AC) — o pós-check do AC fica como dívida.
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
  **disponíveis** para upstream (ao contrário do `l2vc`/`vsi` naquele ciclo —
  o `l2vc` ganhou os dois na Fase 4, parte 2, e o `vsi` na parte 3); desfazer
  uma remoção já **aplicada** exige reativar o upstream antes — a remoção
  aplicada o desativa na SoT e a API responde 409 ("reative antes de planejar
  a mudança") até a reativação, manual de propósito (sem reativação
  automática). Web: `/upstreams`
  + `/upstreams/:id` (detalhe com a matriz principal × contingência e
  "Solicitar mudança") e fumo `web/e2e/upstream.spec.ts` (org operadora pela
  UI, upstream, community, vínculo e CR aprovada pelo `e2e-aprovador`;
  rerun-safe por `Date.now()`). Validação em equipamento real segue
  `docs/runbook-validacao-upstream.md` (somente leitura → geração sem
  execução → teste em circuito/edge não crítico → IRR/RPKI consultivo →
  rollback aprovado antes; **sem lab** — decisão registrada).
- Liberação de recursos do circuito (frente pós-F5, 2026-09-11): o inverso da
  reserva. `liberar_circuito` (`domain/services/ipam.py`) marca as linhas de
  `vlans`/`ip_prefixes` do circuito como `liberada` (§14.1 — nada é excluído
  fisicamente) e audita `circuit.unreserve`; idempotente e bloqueado com 409
  apenas por sessão BGP **ativa** (desativada não bloqueia — desativar é o
  único caminho, não existe remoção de sessão). As UNIQUEs de `vlans`
  (`uq_vlans_site_vid`) e `ip_prefixes` viraram índices únicos **parciais** por
  `status = 'reservada'` (migração `e48a9c6b2d71_liberar_recursos_circuito`),
  então o alocador first-fit reusa o VID e o par p2p liberados. Todo leitor de
  `vlans`/`ip_prefixes` por `circuit_id` filtra `status == 'reservada'` (render,
  plano de remoção e reconciliação foram corrigidos na revisão); ficam fora,
  de propósito, `create_session` (não valida reserva — dívida registrada) e a
  liberação de VLAN de AC de MPLS (`uq_vlans_device_vid` segue estrito).
  API
  `POST /api/v1/circuits/{id}/unreserve`, CLI `gerenet circuits unreserve`,
  botão "Remover recursos" com `ConfirmDialog` no detalhe do circuito (wiki
  `/wiki/circuitos`).
- Fase 6, parte 1 (automação contínua, 2026-09-14): **coleta periódica** —
  `GERENET_COLLECT_INTERVAL_MINUTES` (0 = desligado) liga a varredura no worker
  (`with_scheduler=True`, arm na subida e rearm ao fim de cada execução), que
  enfileira os equipamentos ativos com credencial reusando `enqueue_collect`
  (lock/dedupe/recusas valem como na coleta manual), pula quem foi coletado
  dentro do intervalo (pior caso ~2×) e audita `collect.sweep` com os números;
  mudar o intervalo pede restart do worker. Cada coleta passou a gravar
  `resources["divergencias"]` (contagem por severidade + `parcial`/`motivo`) e
  falha do reconcile **não** derruba a coleta (`collect.reconcile_failed`).
  **`/metrics`** na API (`gerenet.api.metrics`, `CollectorRegistry` por app,
  sem auth como o `/healthz`, token opcional `GERENET_METRICS_TOKEN`), com os
  nove itens do §20.1 derivados do banco/Redis (jobs por tipo/status/equipamento
  e p50/p95 de duração em SQL) — o worker **não** expõe endpoint (fork por job;
  emenda registrada ao §25.15); **Prometheus e Grafana** no compose de dev
  (`docker/observability/`, dashboard `gerenet — operação`) e card de
  divergências no dashboard (lê o resumo, linka `/reconcile?device_id=N`).
  Dependência nova: `prometheus-client`. Runbook em
  `docs/runbook-observabilidade.md`.
- Descoberta na configuração — parte 1 (2026-09-14): a página **Migrar**
  (`/discovery`, grupo Operação) e o grupo `gerenet discovery` leem o
  `display current-configuration` **já coletado** e propõem o que a SoT não
  conhece; nenhum comando novo vai ao equipamento em nenhum caminho (o único
  caminho de escrita é a lista de ignorados, na SoT). Parser novo
  `automation/parsers/huawei_vrp/config_vrp.py` (linha a linha com contexto de
  bloco; senha `cipher` nunca lida, só o flag `tem_password`; valores tortos
  viram `avisos` em vez de estourar) e motor `automation/discovery.py`: candidato
  = peer da config fora da SoT (sessão desativada conta como conhecida) e fora
  dos ignorados, classificado por ASN (interno sai em lista separada, só no CLI);
  proposta agrupada por **enlace** (VRF + subinterface — v4+v6 viram um dual
  stack) com `veredito` (`adotavel` / `adotavel_com_pendencias` /
  `nao_adotavel`), pendências (organização, `classificacao_nao_confirmada`,
  acesso, código, senha, perfil de política, ASN do equipamento,
  `peer_nao_habilitado`, mesmo ASN em outro enlace) e conflitos
  (VLAN/prefixo reservados, par em uso, `enlace_nao_p2p`, `ponta_incoerente`,
  `endereco_sem_subinterface`, `sem_site`, os três da conferência cruzada com a
  interface brief e os dois da leitura: `vrf_nao_renderizavel` — esta versão do
  render emite toda sessão na instância pública — e `asn_remoto_ausente`).
  `conferir_fidelidade` (só no `discovery show`) ensaia o **render de verdade**
  num SAVEPOINT desfeito e devolve o que sobra/falta por contexto (`peer`,
  `subinterface`, ou `ensaio` quando a comparação não pôde ser feita). Coluna
  nova `ip_prefixes.ponta_local` (migração `b2339435be24`, `inferior`/
  `superior` — qual endereço do par é o do roteador) e `aviso` com dois estados
  (sem coleta × leitura parcial), que a página e o CLI distinguem. Endereços são
  comparados na forma canônica (`endereco_canonico`); `bgp_sessions` ainda grava
  o texto como veio (dívida registrada). API `GET /api/v1/discovery?device_id=` +
  `GET/POST/DELETE /api/v1/discovery/ignore` (o POST audita `discovery.ignore`, o
  DELETE `discovery.unignore`); CLI `gerenet discovery
  list|show|ignore|unignore` (`ignore` pega **um** peer, com `--afi`/`--vrf`/
  `--motivo`; o "Não adotar" da página retira o **enlace inteiro**). A **parte 2
  (adoção)** veio no bullet seguinte. Docs: wiki `/wiki/descoberta` e a seção da
  descoberta em `docs/runbook-validacao-ne8000.md` (checklist das 21 assunções do
  parser — a fixture é derivada dos templates do próprio projeto, **não** uma
  captura real).
- Descoberta na configuração — parte 2 (adoção, 2026-09-15): a proposta lida da
  configuração vira circuito na SoT pela revisão da página **Migrar** (diálogo da
  linha: código, acesso, trunk, organização — escolher uma da lista ou criar a
  nova com o ASN do peer —, perfil de import/export e caminho do segredo no Vault
  por família) ou pelo `gerenet discovery adopt <device> <peer> --json <arquivo>
  [--ciente]`; API `POST /api/v1/discovery/adopt` (201 com o `circuit_id`, 404
  quando a proposta já não existe, 409 de unicidade, 422 de campo/ciente) e
  `GET /api/v1/discovery/fidelidade?device_id=&vrf=&subinterface=` — o diff sob
  demanda, porque cada conferência roda um render do equipamento inteiro e
  embuti-la na lista faria a página pagar um render por proposta. A escrita é
  **uma transação só** (`commit=False` em `create_organization`/
  `create_circuit`/`reservar_adocao`/`create_session`, audit `discovery.adopt`
  com o snapshot de origem, o `ciente` e o diff inteiro; qualquer recusa desfaz
  tudo — não existe adoção parcial) e **nada vai ao equipamento**: mudar o
  roteador continua sendo change request. `reservar_adocao` grava os **valores
  reais** da proposta (o VID e o par p2p da configuração, com
  `origem_snapshot_id`), e não o que o alocador first-fit daria. A conferência de
  fidelidade passou a comparar também o **corpo das definições** que a sessão do
  ensaio referencia (contexto `definicao`), recebe os perfis e o trunk da
  revisão — e o **nome da interface** entra na conta, dos dois lados (o
  `<trunk>.<vid>` que o render monta com o trunk informado contra o nome do bloco
  lido: o `discard` antigo só dispensava o cabeçalho do render quando ele
  coincidia com o nome lido, então um trunk errado sobrava de um lado só, e o
  nome que o equipamento tem — o que diz qual campo corrigir — não aparecia) —, e
  `Diferenca` ganhou
  `explicacao` (o `ensaio` parou de sobrecarregar
  `faltando`); o que a SoT **não gerencia** (`description` e MTU da subinterface)
  aparece num grupo próprio e **não gateia** — só o grupo que mudaria o
  equipamento exige o `ciente`, e o aceite caduca quando a conferência é
  refeita. Fumo `web/e2e/discovery.spec.ts`: o seed (`web/e2e/setup.ts`) passou a
  escrever o snapshot com a configuração sintética de um enlace por rodada, num
  equipamento próprio (`ne8000-disco-01` — o `ne8000-01` já tem sessão ativa e a
  §14.1 admite uma por device/VRF/família), e desativa as sessões desse
  equipamento antes de cada rodada. Docs: wiki `/wiki/descoberta` (o fluxo de
  revisão, os dois grupos do diff, quando o `ciente` é exigido e o que a adoção
  grava) e a Etapa 3 do runbook do NE8000 (adoção num equipamento não crítico,
  com a CR de remoção do circuito como rollback).
- Organização por ASN (2026-09-15): a revisão da adoção ganha o botão **Buscar
  no registro** (`GET /api/v1/organizations/prefill?asn=N`, no router de
  organizações e declarado ANTES de `/{organization_id}` — o FastAPI casa as
  rotas na ordem de declaração). `identificar_asn` (`automation/irr.py`) faz
  duas consultas whois: o `aut-num` do RADB
  (`as-name`/`descr`/`member-of`) e a consulta direta no LACNIC, que delega os
  ASNs brasileiros ao registro.br (`owner`/`ownerid`/`country`/`inetnum`), com
  cache de 24h em `irr_cache` sob `source="registro"`; falha de uma fonte vira
  aviso, das duas sem cache vivo vira `IrrError` (503 na API), e resposta
  parcial é 200. O `conflito` de cada bloco é recalculado **fora** do cache —
  é estado da SoT.
  `_executa_whois` passou a capturar bytes e decodificar com queda para latin-1
  (a resposta do nic.br derrubava a chamada com `UnicodeDecodeError`, que não é
  `OSError` nem `SubprocessError`: um 500 no lugar da falha tratada). Coluna
  nova `organizations.document` (o `ownerid`, genérica e não `cnpj`) e valor
  novo `auth_origin.registro` — que nasce fora dos dois caminhos da revalidação
  sem código novo, e existe para o bloco alocado não ser marcado `diverge`
  eterno (dois testes pinam isso). `AdocaoIn.autorizacoes` só vale com
  `organizacao_nova`, e cada bloco vira autorização `origin="registro"` com a
  nota do ASN, na transação do `POST /adopt`; `create_authorization` ganhou
  `commit=False` e idempotência por prefixo (§3.2). Migração
  `alembic/versions/c4a8e1f0b7d3_organizacao_document_e_registro.py`. Sem CLI
  nesta frente — decisão do usuário em 2026-09-15: a parte visual de importar e
  migrar um peer fica só na web. Dívidas: more-specifics anunciados fora do
  bloco alocado, blocos de ASN estrangeiro, o botão na página de organizações e
  enriquecer organização já cadastrada.
- Default route, adoção de upstream e políticas importadas (2026-09-16): a
  sessão BGP ganhou a coluna `default_route_advertise` — o `peer X
  default-route-advertise` (escopo de cliente, com a guarda no serviço pelo
  `upstream_do_circuito`), ficando o `allow_default_route` com o sentido de
  sempre (aceitar a default do provedor, escopo de upstream) —, e a migração
  `alembic/versions/a3d1c7e5b9f2_adocao_upstream_e_politicas.py` copia a
  intenção do campo antigo para a coluna nova nas sessões sem vínculo de
  upstream e zera o antigo (as de upstream ficam intactas); o `upstream_id`
  entrou no `BgpSessionOut` e é por ele que a web escolhe o checkbox do escopo
  ("Anunciar rota default ao cliente" × "Aceitar rota default do provedor"), e
  não pelo `kind` da organização. A adoção ganhou o select de **`kind`**
  (`downstream`/`parceiro`/`operadora`) com a regra de coerência do §5.1
  (operadora exige o bloco de upstream, e o bloco exige operadora — o render
  despacha o enlace pelo vínculo e `_autorizadas_clientes` filtra pelo `kind`)
  e o bloco `AdocaoUpstreamIn` (vincula um existente ou cria o novo, com tipo,
  `produto_import` e papel), gravados na transação única do `adotar_proposta`
  na ordem do design §5.3 (upstream → circuito → reserva → vínculo → sessões →
  `propagar_defaults`), com o ensaio da conferência montando o vínculo. Os
  nomes de política lidos no equipamento (`bgp_sessions.import_route_policy` e
  `.export_route_policy`, por sessão) são a **exceção ao §25.4**: preenchidos,
  o render emite o corpo sob aquele nome (`_nome_rp_import`/`_nome_rp_export`);
  a revisão da adoção importa o nome lido e o botão de limpar devolve o padrão
  (`RP-<ASN>-IMPORT-<AFI>`/`RP-<ASN>-EXPORT-<AFI>`). O nome repetido é
  recusado: `politica_compartilhada` na proposta e
  `_recusa_nome_de_politica_repetido` na escrita (outra sessão ativa ou outro
  enlace da leitura), mais a guarda do mesmo nome nas duas direções no
  `create_session`. No upstream, o `produto_import` (tipo de policy) vence o
  `tipo` pelo `PERFIL_DO_PRODUTO` no produto da importação e entra em
  `_CAMPOS_PROPAGACAO`; o `POST /api/v1/upstreams` aceita o bloco de **acesso**
  que cria o circuito vinculado como principal na mesma chamada
  (`criar_com_circuito`, `commit=False` nos três serviços — a reserva de VLAN e
  de endereços segue na página do circuito). Web: `/discovery` (o `kind`, o
  bloco do upstream e os nomes de política por família, com o limpar),
  `/upstreams` e o detalhe (tipo de policy e a seção de acesso do cadastro).
  Desvios registrados do spec: o `propagar_defaults` **não** ganha `commit` (ele
  propaga no meio do `update_upstream`, que commita no fim), e as três flags
  novas da sessão (`--default-route-advertise`, `--import-route-policy`,
  `--export-route-policy`) entram só no `bgp-sessions add` — não existe
  `update` no CLI, e criar um não é desta frente. Dívida do §11 que fica: não
  há modelo para uma route-policy compartilhada, nem por dois peers do mesmo
  equipamento, nem pelas duas direções de um só — a adoção recusa (a transação
  volta inteira) e a saída é o botão de limpar, e o render continua emitindo os
  dois blocos sob o mesmo nome quando o caso chega por outro caminho.
- Convenções previstas no `.gitignore`: Python com venv e pytest (`.venv/`, `.pytest_cache/`), deploy via Docker Compose (`compose.yaml` na raiz) com `.env` ignorado (o `.gitignore` ainda prevê `deploy/docker/.env`), `config.yaml` local com segredos **fora do repositório**, logs em `logs/` ignorados.
- `.claude/settings.local.json` contém token e aponta o harness para uma API externa: é arquivo local — não versionar nem alterar.
