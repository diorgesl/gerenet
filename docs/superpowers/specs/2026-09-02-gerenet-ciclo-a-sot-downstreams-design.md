# Design — Ciclo A: Source of Truth de downstreams (gerenet)

**Data:** 2026-09-02
**Escopo:** Fase 2 do roadmap (§22) — cadastro e validação da intenção de downstreams: sites/POPs, organizações e contatos, circuitos, VLANs, IPAM p2p (IPv4 `/31` e IPv6 `/126` derivado, §25.8), sessões BGP (modelo completo §6.3), prefixos autorizados, produtos de roteamento (catálogo §25.5) e auditoria de CRUD. **Sem** geração de configuração, sem mudança/execução, sem divergência — estes são os ciclos B e C.
**Referências:** [ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md](../../ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md) — princípios §3, inventário §5, downstreams §6, nomenclatura §8, modelo §14, API §15, auditoria §18, fases §22, MVP §23, aceite §24, **decisões registradas §25**, fluxo exemplo §26. Antecede a [spec da Fase 1](2026-09-02-gerenet-fase1-inventario-coleta-design.md), já implementada (cortes 0–2).

## 1. Objetivo e escopo

Entregar a **fonte de verdade da intenção de downstreams**: o operador cadastra cliente, contatos, POP, circuito dual stack com reservas de VLAN/endereços, sessões BGP por família com produto de roteamento e prefixos autorizados — e o banco **garante** as regras de unicidade §14.1, com trilha de auditoria imutável (antes/depois, sem segredos). Nada é enviado a equipamento; nenhum template é renderizado (ciclo B); nenhuma mudança controlada existe ainda (ciclo C).

Critérios de aceite deste ciclo (§24 na medida em que o ciclo A os cobre):
- cadastrar organização (downstream) com ASN válido, contatos, site/POP e devices vinculados;
- cadastrar circuito dual stack e **reservar** VLAN (`2–4094`, única por site) + enlace p2p IPv4 `/31` (opção `/30`) + IPv6 `/126` derivado do IPv4 (§25.8), com pontas local/remota deriváveis;
- detecção de duplicidade: VLAN no site, enlace p2p no site, sessão BGP no mesmo equipamento+VRF+família, ASN de organização, sobreposição de prefixos autorizados entre organizações distintas;
- sessão BGP com o modelo completo §6.3 e seleção de produto do **catálogo completo §25.5** (nunca edição manual de route-policy);
- prefixos autorizados cadastrados manualmente (origem `manual`; IRR/RPKI = Fase 5);
- toda operação de CRUD/reserva com **auditoria imutável** (ator/origem, objeto, antes/depois) e nenhum segredo (password BGP) fora do Vault;
- CLI e API REST funcionando contra o compose dev; suíte automatizada verde (unit + API).

## 2. Contexto operacional (referência)

Topologia da operação, registrada na sessão de design de 2026-09-02: **o MPLS roda apenas nos switches S6730/S5730** — o switch de acesso entrega a VLAN L2 direto ao roteador; o **NE8000 de borda termina o acesso em subinterface (dot1q/QinQ)** e hospeda as sessões BGP na **instância pública/global** (§25.3). VRF apenas quando um cliente exigir isolamento explícito; Virtual System fora de escopo. Consequência para o modelo: um circuito referencia um `access_device` (switch, dono da VLAN) e um `edge_device` (NE8000, dono da subinterface e dos peers), com `backup_edge_device` opcional (contingência).

## 3. Decisões de design (aprovadas em 2026-09-02)

1. **`sites` vira entidade com FK em `devices`**: tabela nova; migração da string `site` da F1 (dado existente vira um site homônimo; depois a coluna string é removida); comando para vincular devices (`sites link-device`), inclusive o device de lab já cadastrado.
2. **Unicidade por site/POP** como escopo padrão do "domínio" do §14.1: VLAN e enlace p2p não se repetem dentro do mesmo site. (Regra única e simples; POPs com muitos switches podem evoluir para escopo por equipamento no futuro, sem mudar a regra no código — é decisão de dado.)
3. **Modelo de sessão BGP completo (§6.3)** já no cadastro: campos opcionais com defaults de operação; evita migrações em cascata quando a renderização (ciclo B) consumir.
4. **Catálogo completo de produtos desde já (§25.5)** como *seed versionado* (migration de dados) em `bgp_policy_profiles`; o operador escolhe produto, nunca edita route-policy manualmente (§6.5).
5. **IPAM no PostgreSQL (§25.8)**: sem tabela `allocations` neste ciclo — VLANs e enlaces p2p são linhas próprias (`vlans`, `ip_prefixes`) que carregam `circuit_id`. `allocations` só nasce no MPLS (VC-ID/VSI-ID).
6. **Fonte única para prefixos autorizados**: `bgp_prefix_authorizations` (por organização). A tabela `ip_prefixes` guarda **enlaces p2p e blocos internos**, não blocos autorizados de cliente — evita duas tabelas com a mesma regra de sobreposição.
7. **Auditoria de CRUD nova** (fecha dívida da F1, onde o CRUD de devices pela API não audita): helper em `domain/audit.py`, com mascaramento de campos sensíveis e sem UPDATE/DELETE em `audit_events`; aplicado aos serviços da SoT e **retrofit** no CRUD de devices. Ator = origem (`api`/`cli`); usuários e perfis §17 entram no ciclo C (execução/mudança).
8. **Password de sessão BGP no Vault** (§6.3 "armazenada como segredo"): valor nunca no banco — coluna guarda apenas o path (`gerenet/bgp-sessions/<id>/password`, padrão SecretStore da F1); exposições mostram só `has_password`.
9. **ASN local do roteador entra no cadastro de devices** (`devices.asn`, migração; dado do §5 que a F1 não modelou); a sessão usa `asn_local` default do device com override explícito.
10. **Sem máquina de estados §6.6 neste ciclo**: só `admin_status` (ativo/desativado, padrão F1; desativar nunca exclui — §14.1). A máquina completa (rascunho → … → desativado) nasce no ciclo C junto das mudanças; desativar circuito **preserva** reservas (histórico), liberação explícita para reuso fica para a remoção de serviço (ciclo C).

## 4. Modelo de dados

Padrão da F1: tabelas e colunas em inglês (`snake_case`), mensagens de erro em PT-BR, soft-delete via `admin_status`, timestamps `created_at`/`updated_at` com `server_default=func.now()`. Enums declarados como tuplas Python e `Enum(name=...)` (padrão F1).

### `sites`
| coluna | tipo | notas |
|---|---|---|
| `id` | int PK | |
| `name` | str(64) **unique** | nome do POP/local |
| `city` / `uf` | str(128) / str(2) nullable | |
| `p2p_ipv4_block` | str(64) nullable | bloco de enlace do site; default settings `100.64.0.0/10` |
| `p2p_ipv6_base` | str(64) nullable | base de enlace v6 do site; default settings `2804:194C:1000::/48` |
| `admin_status` | bool | soft-delete |
| `created_at`/`updated_at` | datetime | |

### `devices` (modificação da F1)
- `site_id` FK opcional para `sites.id` (migração: valor da coluna string `site` vira site homônimo quando presente; coluna string removida).
- `asn` int nullable (ASN local do roteador — §5; validado 32 bits e não reservado; `devices.asn` é o default de `bgp_sessions.asn_local`).

### `organizations`
`id`, `name` str(128) **unique** (nome de exibição), `legal_name` str(255) nullable (razão social), `kind` Enum(`downstream`, `parceiro`) default `downstream`, `asn` int nullable **unique**, `irr_as_set` str(64) nullable, `commercial_status`/`operational_status` str(16) default `"ativo"`, `notes` text nullable, `admin_status`, timestamps.
- Regras de serviço: ASN obrigatório para criar sessão BGP; ASN único (mesmo desativado — histórico §14.1); ASN válido de 32 bits fora dos reservados (§14.1: 0, 23456, 64496–64511, 65535–65551 e 4200000000–4294967294).

### `contacts`
`id`, `organization_id` FK **not null**, `name` str(128), `email` str(255) nullable (validado), `phone` str(32) nullable, `kind` Enum(`tecnico`, `noc`, `admin`) default `tecnico`, timestamps.

### `circuits`
| coluna | tipo | notas |
|---|---|---|
| `id` | int PK | |
| `code` | str(64) **unique** | identificador interno do circuito (§6.1) |
| `organization_id` | FK not null | |
| `site_id` | FK not null | POP de atendimento |
| `access_device_id` | FK devices not null | switch (dono da VLAN) |
| `access_port` | str(64) not null | validação leve (chars `[A-Za-z0-9/-]`); parse formal com o inventário no ciclo B |
| `edge_device_id` | FK devices not null | NE8000 principal (subinterface + peers) |
| `backup_edge_device_id` | FK devices nullable | contingência |
| `stack` | Enum(`ipv4`,`ipv6`,`dual`) default `dual` | |
| `vlan_mode` | Enum(`unica`,`separada`) default `unica` | separada = VLAN própria por família |
| `qinq` | bool default false | true ⇒ reserva S-VLAN; C-VLAN é do cliente |
| `vrf` | str(64) nullable | null = instância pública (§25.3) |
| `mtu` | int nullable | |
| `bandwidth` | str(32) nullable | banda contratada (texto curto) |
| `bfd` | bool default false | BFD do circuito |
| `p2p_v4_len` | int default 31 | `/31` padrão, `/30` por circuito (§25.8); validado em (30, 31) |
| `description` | str(255) nullable | descrição padronizada |
| `notes` | text nullable | |
| `admin_status` | bool | soft-delete |
| timestamps | | |

- Reservas (VLAN/enlaces) são linhas em `vlans`/`ip_prefixes` apontando para o circuito; os endereços das pontas são **derivados** dos prefixos por função pura (seção 6), nunca duplicados no circuito.
- Regra de serviço: `access_device`, `edge_device` e `backup_edge_device` devem pertencer ao `site` do circuito.

### `vlans`
`id`, `site_id` FK not null, `vid` int not null, `kind` Enum(`vlan`, `s_vlan`) default `vlan`, `family` Enum(`ipv4`,`ipv6`) nullable (preenchida quando o circuito usa VLAN separada por família ou QinQ por família — o render do ciclo B precisa saber qual vid serve cada família), `circuit_id` FK nullable, `status` Enum(`reservada`, `liberada`) default `reservada`, `notes` nullable, timestamps.
- `UNIQUE(site_id, vid)` — S-VLAN e VLAN partilham o mesmo espaço de VID no switch.
- `vid` validado em 2–4094 (1 é a nativa; 0/4095 reservados).
- `circuit_id` nullable permite reservas de operação/infra sem circuito.

### `ip_prefixes`
`id`, `network` str(64) not null (CIDR **alinhado** ao prefixo — validado), `kind` Enum(`p2p`) — apenas p2p neste ciclo (blocos internos/infra entram quando houver uso), `site_id` FK not null, `circuit_id` FK nullable, `status` Enum(`reservada`,`liberada`) default `reservada`, `notes` nullable, timestamps.
- Regra de serviço: nenhum p2p sobrepõe outro p2p **do mesmo site** (v4 privado `100.64/10` e blocos públicos não se comparam — disjuntos por construção).

### `bgp_sessions`
| coluna | tipo | notas |
|---|---|---|
| `id` | int PK | |
| `circuit_id` | FK not null | |
| `device_id` | FK devices not null | deve ser `edge_device` ou `backup_edge_device` do circuito |
| `afi` | Enum(`ipv4`,`ipv6`) | dual stack = 2 registros |
| `local_address` / `remote_address` | str(64) not null | IP válido; família compatível com `afi` |
| `source_address` | str(64) nullable | |
| `asn_local` | int nullable | default `device.asn` na criação; se o device não tiver ASN e `asn_local` for omitido ⇒ erro |
| `asn_remote` | int not null | default `organization.asn`; quando `organization.asn` existe, **deve** ser igual |
| `description` | str(255) nullable | |
| `import_profile_id` / `export_profile_id` | FK `bgp_policy_profiles` nullable | |
| `maximum_prefix` | int nullable | |
| `maximum_prefix_threshold` | int nullable | 0–100 (%) |
| `local_preference` | int nullable | |
| `med` | int nullable | |
| `prepend` | int nullable | 0–10 |
| `keepalive` / `holdtime` | int nullable | segundos |
| `bfd_enabled` | bool default false | (detalhes de BFD seguem o circuito) |
| `graceful_restart` | bool default false | |
| `shutdown` | bool default false | shutdown administrativo |
| `allow_default_route` | bool default false | §6.4: aceitar default do downstream é exceção explícita |
| `password_ref` | str(255) nullable | path no Vault; valor nunca no banco |
| `admin_status` | bool | soft-delete |
| timestamps | | |

- Regras de serviço (o "não duplicada" do §14.1): não existe outra sessão **ativa** com (mesmo `device_id`, mesmo VRF do circuito — circuito sem VRF é "pública" —, mesmo `afi`); nem com o mesmo par (local, remoto) ativo; `asn_remote` igual ao da organização quando preenchido; endereços com família do `afi`; `import_profile_id` só aceita perfil `direction=import` e `export_profile_id` só `direction=export`.
- `has_password` é derivado de `password_ref` presente — nunca o valor.

### `communities` + `bgp_session_communities`
- `communities`: `id`, `name` str(64) **unique**, `notes`, `admin_status`. Seed §25.6 (migration de dados): `blackhole`, `no-export`, `no-advertise`. (O "tag de produto" e os valores concretos — ex. `NO_EXPORT` vs `ASN:tag` — são definidos na renderização do ciclo B conforme template e ASN local.)
- `bgp_session_communities`: `session_id` FK, `community_id` FK, `UNIQUE(session_id, community_id)`.

### `bgp_policy_profiles`
`id`, `name` str(64) **unique** (slug EN), `label` str(64) not null (PT-BR), `direction` Enum(`import`,`export`), `kind` Enum(`produto`) — extensível, `prefixes` JSON nullable (lista de CIDR; usada por `cdn`/`personalizado`), `notes`, `admin_status`, timestamps.
- Seed (migration de dados) do **catálogo completo de exportação §25.5**: `default`, `default_internas`, `parcial`, `full`, `cdn`, `personalizado` (labels PT: "Somente default", "Default + internas", "Tabela parcial", "Full routing", "CDN", "Personalizado").
- Perfis de importação e outros objetos reutilizáveis (§8) nascem no ciclo B, junto da renderização.

### `bgp_prefix_authorizations`
`id`, `organization_id` FK not null, `family` Enum(`ipv4`,`ipv6`), `prefix` str(64) not null (CIDR alinhado), `origin` Enum(`manual`) default `manual` (IRR/RPKI = F5, §25.7), `notes`, `admin_status`, timestamps.
- Regra de serviço: nenhum prefixo autorizado sobrepõe outro de **organização distinta** (a mesma organização pode listar blocos contíguos/sobrepostos).

### `audit_events` (uso novo; sem migration de schema)
A tabela da F1 (`type`, `actor`, `details` JSON, `created_at`) passa a receber CRUD com `details`: `{origem, objeto, objeto_id, antes, depois}` — `antes`/`depois` = apenas campos alterados, serializados; campos de segredo (`password`, `senha`, `secret`, `token`) removidos antes de gravar. **Nenhuma rota de UPDATE/DELETE** (teste de imutabilidade).

## 5. Regras de domínio (resumo executável)

| Regra (§14.1) | Onde vive | Erro PT-BR |
|---|---|---|
| VLAN única no escopo (site) | `UNIQUE(site_id, vid)` | "VLAN {vid} já está reservada neste site." |
| p2p sem sobreposição no site | serviço `ipam`/`prefixos` | "Enlace {cidr} sobrepõe {existente} neste site." |
| Bloco autorizado sem sobreposição entre organizações | serviço `autorizacoes` | "Prefixo {p} sobrepõe autorização de {org}." |
| Sessão não duplicada (device+VRF+família) | serviço `sessoes` | "Já existe sessão {afi} ativa no equipamento {device} (VRF {vrf})." |
| ASN válido, não reservado | serviço `organizacoes`/`sessoes` | "ASN inválido ou reservado: {asn}." |
| ASN de organização único | `UNIQUE(asn)` | "Já existe organização com ASN {asn}." |
| Objetos em uso nunca excluídos | soft-delete em todos os CRUD | — |

Sobreposição de prefixos é regra de **serviço** (não dá para expressar bem em constraint); as demais unicidades têm constraint + mensagem de conflito amigável por cima (padrão F1: `IntegrityError` → `ConflictError`).

## 6. Alocador de enlace (IPAM, §25.8)

`domain/services/ipam.py`, com funções **puras** testáveis e um serviço transacional:

- `primeiro_livre(session, site_id, comprimento)` → próximo prefixo livre no bloco do site (settings → `site.p2p_ipv4_block`, default `100.64.0.0/10`): varre o bloco por `/31`s (`/30` se `circuit.p2p_v4_len == 30`), pulando os já reservados (ou liberados); erro claro "Bloco p2p do site esgotado." se não couber.
- `derivar_v6(ipv4: str) -> str`: **regra do sufixo §25.8** — octetos 2–4 do IPv4 concatenados sem zero-padding, relidos como dígitos hex e agrupados em hextets: grupo 1 = os 4 primeiros dígitos, grupo 2 = o restante; grupo vazio é omitido (implícito zero). Ex. golden (verbatim da spec): IPv4 `100.110.0.73` → `110.0.73` → dígitos `110073` → hextets `1100:73`.
- `pontas_v4(prefixo)` / `pontas_v6(prefixo, site_base)`: v4 `/31` → local `.0`, remota `.1`; `/30` → local `.1`, remota `.2`. v6 → endereço = base do site + hextets do sufixo + hextet de host: local `…<sufixo>:1`, remota `…<sufixo>:2` dentro do `/126` — ex. golden: `2804:194C:1000::1100:73:1/126` (local) e `…:2/126` (remota), derivados de `100.110.0.73`.
- `reservar_circuito(session, circuit_id, *, origin, actor)`: valida circuito ativo e site; em transação, grava:
  - `vlans`: 1 linha (`vlan_mode=unica`, `family=NULL`) ou 2 (`separada`, `family=ipv4`/`ipv6`); `qinq=true` ⇒ `kind=s_vlan`;
  - `ip_prefixes`: p2p v4 `/31` (ou `/30`) + p2p v6 `/126` derivado do v4 escolhido — um par por família ativa do `stack`;
  - **idempotente** (§3.2): circuito já reservado ⇒ devolve o estado atual e audita como no-op, sem duplicar;
  - auditoria de reserva (antes/depois com os valores alocados).
- Conferência formal do `/126` (alinhamento de enlace aceito pelo VRP) com equipamento real fica para o ciclo B; o golden textual §25.8 é a régua do alocador desde já.

## 7. Auditoria de CRUD

`domain/audit.py`:
- `CAMPO_SENSIVEL = ("password", "senha", "secret", "token")` — campos que casam (substring, minúsculas) são removidos de `antes`/`depois` e marcados `"[mascarado]"` quando alterados.
- `registrar(session, *, tipo, ator, objeto, objeto_id, antes=None, depois=None)` → grava `AuditEvent` (actor=`api`|`cli` por ora — sem usuários até o ciclo C; `details` = `{objeto, objeto_id, antes, depois}` com só os campos alterados entre `antes` e `depois`).
- Chamado nos serviços da SoT (create/update/disable de sites, organizations, contacts, circuits, bgp_sessions, prefix_authorizations; reserva de circuito) e no **retrofit** do CRUD de devices da F1 (hoje `criar`/`atualizar` no router não auditam; `disable` registra evento avulso no CLI — unifica-se no serviço com o novo formato). Eventos antigos da F1 (collect, hostkey) permanecem como estão.
- Imutabilidade: nenhum endpoint/caminho de código faz UPDATE/DELETE em `audit_events` — coberto por teste.

## 8. Segredos

- Password BGP: `gerenet bgp-sessions password set <id>` (CLI) e rota equivalente na API gravam o valor no Vault (`gerenet/bgp-sessions/<id>/password`) via `SecretStore` da F1 e preenchem só `password_ref`; nada de valor em schemas de saída, logs, snapshots ou auditoria (§18/§19). `GET`/`list` expõem `has_password`.

## 9. API e CLI

**API `/api/v1`** (auth `X-API-Key`, padrão F1; erros 201/404/409 com `ConflictError`/`NotFoundError`):
- `sites`: GET list · POST · GET `/{id}` · PATCH · DELETE`/…/disable` (rota de desativação explícita, padrão F1: PATCH `admin_status`).
- `organizations`: GET · POST · GET `/{id}` · PATCH · disable. `downstreams`: GET list (kind=downstream) · POST (cria com kind fixo `downstream`).
- `contacts`: GET · POST · GET `/{id}` · PATCH · disable.
- `circuits`: GET (filtros: organization, site) · POST · GET `/{id}` · PATCH · disable · **POST `/{id}/reserve`** (200 com o circuito reservado; idempotente — 2ª chamada devolve o mesmo; 409/400 com o motivo do conflito) · GET `/{id}` devolve pontas derivadas (`ipv4_local`/`ipv4_remote`/`ipv6_local`/`ipv6_remote`) quando reservado.
- `bgp-sessions`: GET · POST · GET `/{id}` · PATCH · disable.
- `prefix-authorizations`: GET · POST · DELETE administrativa não existe — desativação via PATCH.
- `policy-profiles`: GET list (catálogo).
- `audit-events`: GET list com filtros (`tipo`, `objeto`, `objeto_id`) — nunca retorna segredos.

**CLI (Typer, padrão F1)** — espelha o essencial da operação:
`gerenet sites add|list|disable|link-device` · `gerenet organizations add|list|disable` · `gerenet contacts add` · `gerenet circuits add|list|reserve|disable` · `gerenet bgp-sessions add|list|disable|password set` · `gerenet prefix-authorizations add|list` · `gerenet policy-profiles list`.

## 10. Testes

- **Unit — regras**: ASN (inválido/reservado/duplicado), VLAN duplicada no site, sobreposição p2p no site, sobreposição de autorização entre organizações, sessão duplicada (device+VRF+afi e par de endereços), `asn_remote` ≠ `organization.asn` rejeitado, `device_id` fora do circuito rejeitado.
- **Unit — alocador puro**: golden §25.8 (`100.110.0.73` → `…1100:73` → pontas `…:1`/`…:2`), sufixo com ≤4 dígitos, zero-padding de octeto (`10.0.5` → `1005`), `/31`→`/30`, esgotamento de bloco, pontas v4 (`/31`: `.0/.1`; `/30`: `.1/.2`).
- **Unit — reserva**: idempotência (2ª reserva = no-op auditado), 2 VLANs em `vlan_mode=separada`, `qinq` grava `s_vlan`, dual stack cria v4+v6, v6 derivado do v4 escolhido.
- **Unit — auditoria**: antes/depois só com campos alterados; `password`/`secret` mascarados; imutabilidade (nenhum UPDATE/DELETE).
- **API**: CRUD feliz + 404/409; `POST /circuits/{id}/reserve` (200 idempotente/409 conflito); `downstreams` filtra `kind`; sessão expõe `has_password` e nunca o valor; `audit-events` filtra.
- **CLI**: smoke dos comandos essenciais contra banco de teste (padrão F1).
- **Migração**: upgrade/downgrade limpos em `gerenet_test`; dados da coluna `site` (string) preservados para `sites`.

## 11. Fronteiras e débitos herdados

- **Não entra no ciclo A** (destino entre parênteses): renderização/templates/nomes VRP derivados do ASN (B), parsers `interfaces`/`bgp_peers` pendentes da F1 (B), divergência desejado×encontrado (B), change requests/aprovação/estados §6.6/execução (C), usuários e perfis §17 (C), IRR/RPKI e upstreams (F5), MPLS L2VC/VSI (ciclo próprio), UI web (ciclo do assistente), shape de `device_snapshots.resources` e múltiplas host keys por device (dívidas da F1 triadas — B).
- **Retrofit neste ciclo**: auditoria de CRUD de devices; `devices.site` → `sites`; `devices.asn`.
- A **especificação §5** ganha o campo "porta SSH" (dívida da T13, já implementada no código — atualização do documento).

## 12. Riscos

- **Álgebra do `/126`**: o exemplo §25.8 é textual e a forma exata aceita pelo VRP só se confirma no ciclo B — mitigado por teste golden e pela função pura isolada.
- **Tamanho do ciclo** (8 tabelas novas + migrações + alocador + auditoria + API/CLI): mitigado pelo padrão SDD com planos em cortes pequenos, revisão por task e suíte verde contínua.
- **Regra de sobreposição em serviço** (não em constraint) pode furar por caminho não usado: mitigado concentrando escrita em serviços (padrão F1 já é esse) e testes por regra.
