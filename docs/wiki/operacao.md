---
title: Reconciliação, config desejada, jobs e auditoria
secao: Operação
order: 1
---

# Reconciliação, config desejada, jobs e auditoria

## Três camadas: snapshot, config desejada e reconciliação

1. **Snapshot** — o que a coleta encontrou de verdade, por recurso
   (`version`, `config_backup`, `interfaces`, `bgp_peers`, `bgp_peers_verbose`),
   com duração, status (`success`/`partial`/`error`) e o mapa de erros por
   recurso. Veja na página Snapshots (por equipamento) ou via CLI
   (`gerenet snapshot show <snapshot_id>`).
2. **Configuração desejada** — a renderização da intenção do Source of Truth
   em comandos VRP para o equipamento: blocos de subinterface, prefix-lists,
   route-policies de import/export, bloco de peer BGP e comentários de dívida,
   na ordem em que devem ser aplicados. Tudo derivado — nada é editado à mão.
3. **Reconciliação** — a comparação **desejado × encontrado** do equipamento
   (ou de um snapshot específico).

## O que a reconciliação mostra

Cada item é tipado com **severidade** (`critica` / `atencao` / `aviso`) e traz
`esperado`, `encontrado` e **ação recomendada**:

| Tipo de item | Severidade | Exemplo de ação recomendada |
|---|---|---|
| `subinterface.ausente` | crítica | Subinterface esperada não listada — recriar/verificar no equipamento. |
| `subinterface.estado` | atenção | Estado físico/protocolo abaixo de `up` — verificar. |
| `ponta.v4` / `ponta.v6` | crítica | Endereço local ausente na subinterface. |
| `peer.ausente` | crítica | Sessão ativa no SoT sem peer configurado/estabelecido. |
| `peer.asn` | crítica | ASN do peer diverge do cadastrado. |
| `peer.estado` | atenção | Peer fora de `Established` — conferir se é transitório. |
| `peer.filtros` | crítica | Filtro aplicado diverge do renderizado (nomes §25.4). |
| `peer.shutdown_admin` | atenção | Sessão em shutdown admin não deveria estar `Established`. |
| `peer.orfaos` | atenção | Peer coletado sem sessão ativa cadastrada. |
| `circuito.sem_trunk` | aviso | Cadastrar `edge_trunk` do circuito para comparar a subinterface. |

A justificativa dos itens (ex.: `peer.filtros` acusa nomes fora do padrão)
depende do recurso estar presente no snapshot — sem o recurso, a página mostra
um aviso de comparação parcial, e não uma divergência inventada.

**Importante**: a reconciliação **não altera produção**. No estado atual ela é
somente leitura — o plano de correção com aprovação e execução chega com as
[mudanças controladas](/wiki/mudancas-controladas) (em breve).

## Jobs de coleta e erros comuns

A página Jobs lista as execuções (equipamento, tipo, autor, status, motivo e
duração). Origem do job: `api` (botão na web) ou `cli` (`gerenet collect run`).
Erros comuns e onde olhar:

| Sintoma | Onde ver / o que fazer |
|---|---|
| Job `error` logo após o enqueue | Motivo em `JobDetail` → Motivo: equipamento desativado, sem grupo de credencial, ou coleta em andamento (lock). |
| Job `error` durante a execução | Mensagem de exceção (conexão, permissão, Vault). Conferir acessibilidade e credenciais do grupo. |
| Job `partial` | Snapshot → `errors` mostra o recurso que falhou (ex.: parser da saída de um comando). |
| `comm_status = fail` | Última coleta não trouxe recurso nenhum; `consecutive_failures` cresce a cada tentativa. |
| Filtro de política divergente | Veja acima: `peer.filtros` — a coleta `bgp_peers_verbose` é que alimenta essa comparação. |

## Auditoria

Cada operação gera um **evento de auditoria** (`<objeto>.<acao>`, ex.:
`circuit.create`, `device.disable`, `circuit.reserve`, `collect.failed`),
registrando autor, data/hora e os valores **antes/depois** apenas dos campos
alterados. A página Auditoria permite filtrar por tipo e objeto.

Garantias:

- A trilha é **imutável**: não há caminho de código com `UPDATE`/`DELETE` em
  `audit_events`.
- **Segredos são mascarados**: senha, segredo, token e afins nunca são gravados
  — em `depois` viram `[mascarado]` (exceção: flags booleanas, como
  `has_password`, atravessam — bool não carrega o segredo em si).
- Falhas de coleta também deixam trilha (`collect.failed`, `collect.errors`,
  `collect.skipped` com o motivo: lock/credential).

Para entender a origem de cada valor, [volte ao índice](/wiki/index) ou
comece pelo passo a passo do [primeiro equipamento](/wiki/comecar).
