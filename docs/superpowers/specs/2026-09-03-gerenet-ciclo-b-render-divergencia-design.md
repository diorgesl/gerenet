# Design — Ciclo B: render da intenção e divergência desejado × encontrado (gerenet)

> Especificação do **ciclo B** do gerenet (fase 2 do roadmap — "Source of Truth e validação").
> Ciclo A concluído em 2026-09-03 (P1 núcleo → P2 sessões BGP → P3 API/CLI, 216 testes).
> Documentos-fonte: [ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md](../../../ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md)
> (§6.3–6.5, §8, §10, §14, §25.4, §25.8), spec do ciclo A (2026-09-02), spec da F1 (2026-09-02).

## 1. Objetivo e escopo

Entregar o lado de **validação** da fase 2: o Source of Truth passa a (a) **renderizar a
configuração desejada** — nomes VRP e comandos derivados dos objetos de negócio (§25.4) — e
(b) **comparar desejado × encontrado** (divergência read-only, §10 — o MVP não corrige
produção). O ciclo absorve o **corte 3 da F1** (parsers de `interfaces` e `bgp_peers` com
snapshot completo), expõe na API/CLI o que o ciclo A deixou de fora (communities e associações
sessão ↔ community; perfis de importação) e fecha as dívidas triadas da F1 (shape de
`device_snapshots.resources`).

Fora do ciclo B (destino): execução de mudanças/aprovação/estados §6.6 (ciclo C), usuários e
perfis §17 (C), UI web (ciclo do assistente), IRR/RPKI e upstreams (F5), MPLS L2VC/VSI (ciclo
próprio), servidor MCP sobre as ferramentas (arco de integrações, após C).

## 2. Contexto (o que já existe)

- **F1 cortes 0–2**: devices + Vault + host keys; coleta `version` + backup de config via
  fila/lock (`automation/collectors.py`, `runner.py`, `netmiko_conn.py`, worker RQ).
  Parsers **ainda vazios** (`automation/parsers/`); `device_snapshots.resources` sem shape.
- **Ciclo A (P1–P3)**: tabelas `sites/organizations/contacts/circuits/vlans/ip_prefixes/
  bgp_sessions/communities/bgp_session_communities/bgp_policy_profiles/
  bgp_prefix_authorizations`; alocador IPAM §25.8 (p2p `/30`+`/31`, `/126` derivado dos octetos
  decimais do IPv4 relidos como hex, local `:1`); auditoria `audit_events`; catálogos seedados
  (6 produtos de exportação em `bgp_policy_profiles`); serviços + API `/api/v1` + CLI Typer.
  `BgpSession.import_profile_id` exige perfil `direction='import'` (serviço valida) — **hoje não
  existe nenhum perfil de importação**: o campo é inutilizável até o seed do ciclo B.
- **Captura real do NE8000** (2026-09-03, `data/capturas-ne8000/saida-2026-09-03.txt`,
  git-ignored; AS local 61785, 62 peers v4/52 v6): confirma o §25.8 em produção
  (`Eth-Trunk127.4024` = `100.110.0.73/30` ↔ `2804:194C:1000::1100:73:1/126`), os formatos de
  saída dos comandos-alvo e os limites práticos (tabelas com 62+ linhas, contagens de 7 dígitos).

## 3. Decisões de design (aprovadas em 2026-09-03 no brainstorm)

1. **B completo**: parsers (corte 3 da F1) + render + divergência num mesmo ciclo, executado em
   1–2 planos no padrão SDD (P1–P3 do ciclo A).
2. **Fixtures reais**: o operador capturou a saída do NE8000; os arquivos sanitizados e
   versionados em `tests/fixtures/` são a base dos parsers (golden). Nenhum parser é escrito
   contra saída inventada.
3. **Render = orquestrador Python + templates Jinja2 atômicos**: a composição (quais blocos,
   com quais nomes, por device/capacidades) vive em código testável por unidade; os templates
   são pequenos, um por bloco (subinterface, prefix-list, route-policy in/out, peer BGP), com
   variantes por família/versão quando necessário. Nomes derivados do **ASN do par** em funções
   puras com testes golden (§25.4). Senha **nunca** é renderizada (só `password_ref`/comentário).
4. **Divergência on-demand, sem tabela nova**: serviço que renderiza o desejado do device e
   compara com o último snapshot. Persistência/agendamento ficam para a F6 (reconciliação
   agendada). Comparação automática cobre o que o corte 3 alcança — peers, subinterfaces de
   circuito, endereços de ponta e **nomes de filtros aplicados** (do verbose) —; o conteúdo
   interno de route-policies/prefix-lists **não** é comparado (exigiria parser de
   `current-configuration`, fora do corte 3). O render completo fica disponível para diff
   manual e para o ciclo C executar.
5. **Route-policy clássico** no render; XPL registrado como capacidade (a captura real mostra
   export filters XPL nos upstreams — fora do escopo de downstream deste ciclo).
6. **Seeds de importação mínimos**: um perfil `somente-autorizadas` (`direction='import'`,
   mesmo mecanismo de seed dos catálogos do ciclo A) destrava `import_profile_id`; sem ele a
   sessão renderiza o RP de importação a partir das autorizações do cliente diretamente. Mais
   perfis de importação nascem quando upstreams/IRR (F5) definirem semântica.
7. **Communities expostos na API/CLI** (serviços de associação do P2 já existem); `policy-profiles`
   listável por `direction` inclusive `import` (filtro já validado no P3).
8. **Ordem do roadmap mantida**: B → C (motor de mudanças) → UI web (ciclo do assistente);
   servidor MCP das ferramentas no arco de integrações (após C). Registrar como ciclos futuros.
9. **Afi vem do comando, nunca do endereço**: `display bgp peer` = IPv4 por padrão; IPv6 exige
   `display bgp ipv6 peer` — e a tabela ipv6 lista peers de transporte v4. A allowlist da F1
   ganha as duas variantes.
10. **Coletor de verbose parametrizado pelo SoT**: `display bgp peer <ip> verbose` é caro demais
    para todos os peers (62+); o coletor `bgp_peers_verbose` monta comandos **apenas para os
    peers de sessões ativas do device** (com cap). É a primeira coleta cujo alvo vem do banco.

## 4. Parsers e snapshot (corte 3 da F1)

### 4.1 Coletores (allowlist ampliada)

| Recurso | Comando(s) | Observação |
|---|---|---|
| version | `display version` | existente (F1 corte 2) |
| config_backup | `display current-configuration` | existente; bruto no volume |
| interfaces | `display interface brief` | tabela achatada |
| interfaces | `display ip interface brief` | tabela com endereços v4/VPN |
| interfaces | `display ipv6 interface brief` | **agrupado**, não tabela |
| bgp_peers | `display bgp peer` | tabela IPv4 (padrão do VRP) |
| bgp_peers | `display bgp ipv6 peer` | tabela IPv6 |
| bgp_peers_verbose | `display bgp peer <ip> verbose` | só peers de sessões ativas do device; cap 50 |

### 4.2 Formatos reais que os parsers devem tratar (registrados da captura)

- **`display interface brief`**: bloco de legenda antes da tabela; colunas
  `Interface PHY Protocol InUti OutUti inErrors outErrors`; sufixo de velocidade **dentro** do
  nome (`100GE0/1/53(100M)`, `GigabitEthernet0/1/0(10G)`); marcadores de estado prefixados
  (`*down`, `^down`); membros de Eth-Trunk indentados sob o trunk; `up(s)` (spoofing); linhas
  `Eth-Trunk127.<vid>` = subinterfaces dot1q.
- **`display ip interface brief`**: linhas de resumo no topo ("The number of interface that is
  UP in Physical is 72…"); colunas `Interface IP Address/Mask Physical Protocol VPN`; endereço
  `unassigned`; VPN `--` ou nome de VRF (`l3vpn` na captura).
- **`display ipv6 interface brief`**: **agrupado** — linha da interface
  (`Interface Physical Protocol VPN`) e, nas linhas seguintes,
  `[IPv6 Address/Prefix Length] <end>/<len>` com sufixos `[TENTATIVE]`/`Unassigned`; pode haver
  múltiplas entradas por interface.
- **`display bgp peer` / `display bgp ipv6 peer`**: cabeçalho
  (`BGP local router ID`, `Local AS number`, `Total number of peers : N Peers in established
  state : M`); colunas `Peer V AS MsgRcvd MsgSent OutQ Up/Down State PrefRcv`; `Up/Down` em dois
  formatos (`0655h07m` e `21:48:20`); estados `Established/Idle/Idle(Admin)/Connect/Active`;
  contagens largas (até 7 dígitos); endereços v6 na coluna Peer.
- **`display bgp peer <ip> verbose`**: `BGP Peer is <ip>, remote AS <n>`; descrição entre aspas;
  estado com duração (`Up for 14d20h52m53s`); bloco `Routing policy configured:` com
  `No import/export …` e/ou `Import route filter is: <nome>(N)` /
  `Export route filter is: <nome>(N)` (XPL ou clássico colapsam aqui); nada de senha na saída.

### 4.3 Shape de `device_snapshots.resources` (dívida F1 — contrato do ciclo B)

JSONB com o parse estruturado; o bruto de config continua **no volume**, nunca no banco:

```json
{
  "version": { "<chaves existentes da F1, preservadas>" },
  "interfaces": [
    { "nome": "Eth-Trunk127.4024", "phy": "up", "protocolo": "up",
      "enderecos_v4": ["100.110.0.73/30"], "enderecos_v6": ["2804:194C:1000::1100:73:1/126"],
      "vpn": null }
  ],
  "bgp_peers": [
    { "afi": "ipv4", "peer": "100.110.0.74", "asn": 270620,
      "estado": "Established", "pref_rcv": 1, "up_down": "0655h06m" }
  ],
  "bgp_peers_verbose": [
    { "afi": "ipv4", "peer": "100.110.0.74",
      "filtro_import": "ASN270620-V4-IMPORT", "filtro_export": "RP-270620-EXPORT-V4" }
  ]
}
```

Falha/parse incompleto de um recurso não derruba a coleta: status **parcial** com erro por
recurso no snapshot (padrão F1 §6.1). Nome de interface é a chave de merge entre os três
comandos de interfaces. O shape do B **adiciona** `interfaces`/`bgp_peers`/`bgp_peers_verbose`
(a chave do recurso é sempre o nome do coletor; `bgp_peers_detalhes` é só o nome interno do
merge) e não remove nem duplica o que a F1 já grava (version; referência do backup de config — o
bruto segue no volume, nunca no banco).

## 5. Nomenclatura e render

### 5.1 Derivador de nomes (funções puras, §25.4/§8)

Regra: nomes ≤ 63 chars (VRP), maiúsculas, separador `-`, base = **ASN do par em decimal, sem
padding** (§25.4). Funções por objeto (exemplos com ASN remoto 64500):

| Objeto | Função | Exemplo |
|---|---|---|
| route-policy importação | `rp_import(afi)` | `RP-64500-IMPORT-V4` |
| route-policy exportação | `rp_export(afi)` | `RP-64500-EXPORT-V4` |
| prefix-list de entrada | `pfx_in(afi)` | `IP-PFX-64500-IN-V4` |
| peer-group | — | fora do escopo: peer individual |

`description` do peer: só quando a sessão tiver campo de texto próprio preenchido (conferir o
model no plano B2; sem campo, o template não emite `description`). Tabela completa + casos de
borda (ASN de 32 bits, limite de chars, colisões) definidos no plano com testes golden por
função.

### 5.2 Orquestrador e templates

- Entrada: `Device` + `circuits` reservados (incl. `edge_trunk`, §7) + `bgp_sessions` ativas
  (admin_status) + `prefix_authorizations` da org + produto de exportação da sessão +
  capacidades do device (família/versão; `route_policy` clássico exercitado; XPL registrado
  apenas).
- Saída: blocos de comandos VRP **por device**, ordenados para aplicação (interface →
  filtros → políticas → peer/afi), cada bloco anotado com o objeto SoT que o originou
  (para o ciclo C mapear diff/rollback).
- Templates Jinja2 em `automation/templates/huawei_vrp/` (versionados no git, padrão F1 dos
  parsers): `subinterface.j2` (dot1q/QinQ/endereços §25.8), `prefix_list.j2`,
  `route_policy_import.j2`, `route_policy_export.j2` (produto §6.5/§25.5), `bgp_peer.j2`
  (peer + af + max-prefix/limiar + timers + BFD + shutdown admin + description).
- `password` nunca é emitida; quando `password_ref` existe, o bloco traz um comentário
  `# password no Vault (gerenet/bgp-sessions/<id>/password)`.
- Render idempotente por construção (deriva sempre do SoT; sem estado).

## 6. Divergência (desejado × encontrado, read-only)

Serviço `reconciliar_device(session, device_id)` — **sem tabela nova**:

1. Renderiza o desejado (seção 5) para o device.
2. Lê o snapshot mais recente (`device_snapshots` do device) e o parse de `resources`.
3. Compara e devolve itens tipados:

| Tipo | Esperado (SoT) | Encontrado (snapshot) | Severidade |
|---|---|---|---|
| `peer.ausente` | sessão ativa (admin e shutdown ok) | peer não está na tabela da afi | crítica |
| `peer.shutdown_admin` | sessão `shutdown=true` → peer **não** Established | peer Established | atenção (peer deveria estar admin-down) |
| `peer.estado` | sessão ativa (`shutdown=false`) | estado do peer | atenção — transitório; down ≠ erro (pós-validação estável é do ciclo C) |
| `peer.asn` | `asn_remote` da sessão | AS da tabela | crítica |
| `peer.filtros` | nomes renderizados (in/out) | `filtro_import`/`filtro_export` do verbose | crítica |
| `peer.orfaos` | — | peer presente sem sessão ativa no SoT | atenção |
| `subinterface.ausente` | circuito reservado do device (com `edge_trunk`, §7) | subinterface `<trunk>.<vid>` não listada | crítica |
| `subinterface.estado` | circuito ativo | phy/protocolo down | atenção |
| `circuito.sem_trunk` | circuito reservado do device **sem** `edge_trunk` | — | aviso — SoT incompleta: cadastrar o trunk para comparar subinterface |
| `ponta.v4` / `ponta.v6` | endereço alocado (IPAM §25.8) | endereço no snapshot | crítica |

Cada item: `{tipo, severidade, esperado, encontrado, acao}` em PT-BR. Snapshot ausente →
`snapshot_id: null` + campo `aviso`, sem erro (a UI/CLI orientam a coletar).

## 7. Modelo de dados

Sem tabela nova, sem migration de schema **exceto**:

1. Seed de `bgp_policy_profiles` (`direction='import'`, name `somente-autorizadas`, mesmo
   mecanismo dos seeds do ciclo A).
2. Migration de schema **única, aprovada em 2026-09-03** (complemento §25.18 da spec
   principal): coluna `circuits.edge_trunk` `String(64)` **nullable** — nome do trunk no edge
   device que carrega as subinterfaces do downstream (ex.: `Eth-Trunk127`). O render (5.2) e a
   divergência de subinterface (seção 6) consomem o campo; circuito sem `edge_trunk` não gera
   bloco de subinterface e a divergência devolve aviso `circuito.sem_trunk`. Aceito
   opcionalmente no cadastro e na atualização do circuito (schemas/serviço/API/CLI do padrão
   P3, estendidos no plano B2).

## 8. API e CLI (adições ao padrão do P3)

- `GET /api/v1/reconciliation?device_id=` (ou `?snapshot_id=`) → items + `gerado_em` +
  `snapshot_id`. Erros: device inexistente 404; filters inválidos 400 (padrão P3).
- `GET /api/v1/devices/{device_id}/desired-config` → blocos renderizados (texto + anotação por
  objeto). 404 se o device não existe; 200 com blocos vazios se nada a renderizar.
- `communities`: catálogo **read-only** no B (padrão de catálogos do P3) — só `GET
  /api/v1/communities`; criar/desativar community volta no ciclo C, junto das mudanças com
  aprovação. Associações mudam: `POST /api/v1/bgp-sessions/{id}/communities`
  `{community_id}` (associa) · `DELETE …/communities/{community_id}` (desassocia).
- `policy-profiles`: já filtra `direction=import` (P3) — documentar no OpenAPI.
- `circuits`: cadastro e atualização aceitam `edge_trunk` opcional (String ≤ 64; ex.
  `Eth-Trunk127`) — PATCH `POST/PATCH /api/v1/circuits` e CLI equivalente, padrão P3.
- CLI: `gerenet reconcile <device>` (id|nome), `gerenet render-config <device>`,
  `gerenet communities list`, `gerenet bgp-sessions community add|remove <session> <community>`.

## 9. Segredos

Sem novos caminhos de segredo. Fixtures sanitizadas **antes** de versionar (nenhuma saída com
`display current-configuration` entra em fixtures; a captura atual não contém segredos).
Auditoria/mascaramento inalterados (regras do ciclo A). Render nunca emite senha (5.2).

## 10. Testes

- **Golden — parsers**: cada comando da 4.1 com fixture real sanitizada (captura de 2026-09-03,
  + verbose de peers downstream quando o operador entregar); casos sintéticos para as variantes
  não presentes na captura (ex.: `^down`, `[TENTATIVE]`) marcados como derivados.
- **Unit — nomes**: golden §25.4 por função (ASN 64500, 4 dígitos, 32 bits, borda de tamanho).
- **Unit — render**: golden por template (subinterface v4/v6/dual/QinQ; prefix-list; RP
  import/export com produto; peer com max-prefix/timers/BFD/shutdown) + orquestrador (device
  com N circuitos/sessões → blocos completos; idempotência: render 2× = mesmo texto).
- **Unit — divergência**: snapshot sintético → cada item da tabela da seção 6 (ausente/estado/
  asn/filtros/órfãos/subinterface/pontas/`circuito.sem_trunk`); sem snapshot → aviso; sessão
  desativada não gera `peer.ausente`.
- **API**: reconciliation (200 com itens/aviso; 404), desired-config (200/404), communities
  (list; associação add/remove com 404/409; `has_password` nunca presente), policy-profiles
  `direction=import` (seed visível); **sessão com `import_profile_id` = perfil de importação
  agora funciona** (validação de direção do P2 destravada pelo seed).
- **CLI**: smoke dos novos comandos (padrão P3, ids "1" via truncagem).
- **Migração**: upgrade/downgrade limpos em `gerenet_test`.
- **Validação operacional (manual, read-only)**: coleta completa contra o NE8000 real via
  runbook F1; conferir shape do snapshot e a divergência de um circuito real cadastrado.

## 11. Fronteiras e débitos herdados

- Execução/aprovação/estados §6.6 e usuários §17 → **ciclo C** (motor de mudanças, §12 da
  especificação principal).
- Comparação do conteúdo interno de route-policies/prefix-lists (parser de
  `current-configuration`) → ciclo C (pré-requisito da execução) ou F6.
- XPL: capacidade registrada no device; render clássico no B. Divergência de `filtro_export`
  contra produção XPL divergirá até o suporte (documentar como esperado no golden do cenário
  real).
- UI web (dashboard/assistente) → ciclo próprio após C; **MCP server** das ferramentas → arco
  de integrações (após C), consultas primeiro, mutações pelo fluxo de aprovação.
- Múltiplas host keys por device (dívida F1): permanece para um ciclo de segurança dedicado.
- Validação em laboratório da álgebra `/126` (§12 do ciclo A): coberta pela captura real
  (§25.8 confirmado em produção — item registrado como **encerrado por evidência**).

## 12. Riscos

- **Variação de saída VRP entre versões** → golden por captura; novo template por variação
  (padrão F1 §12).
- **Verbose por peer não escala** → coletor parametrizado por sessões do SoT com cap (4.1);
  sem sessões ativas o recurso é pulado.
- **Divergência com snapshot velho** → resposta carrega `snapshot_id`/data; C e a UI orientam
  idade da coleta (métrica já prevista na F1).
- **Nomes gerados ≠ convenção XPL existente na produção** → divergência acusa até a migração
  das políticas; decisão consciente (route-policy clássico é o alvo do MVP §23).
- **Tamanho do ciclo** → mitigado por planos em cortes no padrão SDD (provável: B1 parsers +
  snapshot; B2 nomes/render + divergência + API/CLI + seeds).
