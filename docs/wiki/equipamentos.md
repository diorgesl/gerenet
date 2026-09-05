---
title: Equipamentos, coleta e snapshots
secao: Começando
order: 3
---

# Equipamentos, coleta e snapshots

## O cadastro de equipamento

Cada equipamento tem um nome **único** (1–64 caracteres) e um endereço de
gerência. Os campos principais:

| Campo | O que é / o que dispara |
|---|---|
| Nome | Identifica o registro; único. |
| Endereço de gerência | IP acessível pela rede de gerência dedicada. |
| Porta SSH | 1–65535; vazio = 22. |
| Fabricante / modelo | `huawei` por padrão; modelo ex.: NE8000 M8, S6730-H24X6C. |
| Família | NE8000, NE40, S6730… — **referência de capacidades** do equipamento; hoje o conjunto de templates é genérico Huawei VRP e a seleção automática por família/versão é evolução do produto. |
| Função | Ex.: borda de downstream, core MPLS, upstream. |
| Site/POP | Onde o equipamento está instalado. |
| ASN local | 1–4294967295 (reservados barrados); vira o `asn_local` padrão das [sessões BGP](/wiki/roteamento) do equipamento. |
| Grupo de credenciais | Referência ao segredo no Vault — **nunca** a senha em si. |
| Tags | Etiquetas livres (ex.: contingência, IRU). |

Há ainda: status administrativo (`admin_status`), status de comunicação
(`comm_status`), data da última coleta, versão VRP/uptime (preenchidos pela
coleta) e fingerprint da host key SSH (registrada por
`gerenet hostkey register <equipamento> <fingerprint>`).

## Status de comunicação

| `comm_status` | Significado |
|---|---|
| `unknown` | Nunca coletado (valor inicial). |
| `ok` | A última coleta trouxe recursos (mesmo que alguns tenham falhado). |
| `fail` | A última coleta não trouxe nenhum recurso — fração entre falhas consecutivas (`consecutive_failures`). |

A última coleta com sucesso atualiza `last_collected_at`, `vrp_version` e
`uptime`.

## O que a coleta faz hoje

A coleta é **read-only** e segue um catálogo fixo de comandos, todos executados
por SSH via Netmiko contra o Huawei VRP:

| Recurso | Comandos | O que fica no snapshot |
|---|---|---|
| `version` | `display version` | versão e uptime (vão para o equipamento) |
| `config_backup` | `display current-configuration` | **backup bruto** (sem parse) — salvo também em arquivo |
| `interfaces` | `display interface brief` + `display ip interface brief` + `display ipv6 interface brief` | interfaces e endereços V4/V6 |
| `bgp_peers` | `display bgp peer` + `display bgp ipv6 peer` | peers e seu estado |
| `bgp_peers_verbose` | `display bgp peer <remoto> verbose` para **cada sessão ativa** no Source of Truth (limite de 50) | detalhe por peer, inclusive filtros aplicados |

**O que ainda não é coletado de forma estruturada**: políticas
(route-policy/prefix-list/AS-PATH/communities) aparecem apenas dentro do backup
cru da configuração. Por isso, a reconciliação baseada em conteúdo de política
é parcial — veja a seção de [reconciliação](/wiki/operacao).

Os backups brutos de cada comando são gravados por coleta (por equipamento,
carimbo de tempo e recurso), mantendo o histórico fora do banco.

## Jobs: a fila de coleta

A coleta é enfileirada (um job por equipamento, com lock por equipamento):
"Coletar agora" na lista de equipamentos dispara `POST /devices/{id}/collect`
(resposta 202) e a CLI `gerenet collect run --device <id|nome>` ou `--all`.
A validação acontece antes da fila: equipamento inexistente, desativado ou sem
grupo de credencial retorna aviso na hora, sem criar job.

Estados de job:

| Estado | Significado | O que fazer |
|---|---|---|
| `queued` | Na fila aguardando o worker. | Aguardar. |
| `running` | Executando no equipamento. | Aguardar. |
| `success` | Todos os recursos coletados. | Conferir snapshot. |
| `partial` | Parte dos recursos falhou (o snapshot tem `errors` por recurso). | Ver `JobDetail`/snapshot → `errors`. |
| `error` | Falha antes do snapshot ou sem nenhum recurso; motivo em `error` do job. | Ver motivo; conferir acessibilidade, credenciais/permissões e template. |

Falhas comuns: equipamento inalcançável (timeout/porta), credencial do grupo
inválida (Vault), saída fora do esperado para o parser, e lock ativo (outra
coleta do mesmo equipamento em andamento — auditado como `collect.skipped`).

Veja também [Reconciliação, config desejada, jobs e auditoria](/wiki/operacao)
para o que fazer com o resultado de cada coleta.
