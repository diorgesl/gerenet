---
title: Sessões BGP, autorizações, perfis e communities
secao: Roteamento
order: 1
---

# Sessões BGP, autorizações, perfis e communities

## Sessão BGP

Uma sessão é cadastrada **por família** (`ipv4` ou `ipv6`), sobre um circuito.
Regras de negócio:

- **Uma sessão por equipamento + família + VRF** (a duplicidade é barrada:
  "Já existe sessão ipv4 ativa no equipamento X (VRF …)"). O par
  local/remoto também não pode se repetir.
- O equipamento da sessão tem que ser o **edge** (ou o contingência) do
  circuito.
- **Peers na instância pública**: use o VRF do circuito; vazio = pública/global.
- `asn_local` padrão = ASN do equipamento; `asn_remote` padrão = ASN da
  organização; ambos podem ser informados explicitamente (o remoto não pode
  divergir do ASN da organização).
- Endereços: v4 sem máscara; v6 com `/126` — use as pontas do
  [enlace reservado](/wiki/circuitos).

Campos de política da sessão: `import_profile_id` / `export_profile_id`,
`maximum_prefix` + limiar (0–100 %), `local_preference`, `med`, `prepend`
(0–10), `keepalive`/`holdtime` (aplicados em conjunto; senão o VRP usa os
defaults), `bfd_enabled`, `graceful_restart`, `shutdown` e
`allow_default_route`.

A **senha** do peering é um segredo: definida por CLI
(`gerenet bgp-sessions password set <sessão>`), guardada no Vault e **nunca**
trafegada na API — os dados de saída mostram apenas `has_password`.

## Autorizações de prefixos

As autorizações definem o que o cliente pode anunciar, por família. Regras:

- Prefixo em CIDR, da **organização** dona; a organização desativada não recebe
  autorizações.
- Sem sobreposição entre autorizações **ativas** da mesma família.
- Hoje a origem é `manual`; IRR/RPKI entram na Fase 5 (políticas avançadas).

A **prefix-list de entrada** é derivada das autorizações **ativas** somente:
`IP-PFX-<ASN>-IN-<AFI>`, com uma entrada por prefixo a partir do índice 10
(10, 20, 30…). Se a sessão tiver `allow_default_route`, a default
(`0.0.0.0/0` ou `::/0`) entra no **índice 5**, antes das autorizações.

## Perfis de política

O perfil declarado na sessão (**import** ou **export**) é o que o render
transforma em route-policy — nunca se digita nome de política.

| Perfil | O que o render produz |
|---|---|
| Importação | `RP-<ASN>-IMPORT-<AFI>` referenciando a prefix-list de autorizações, com o `local_preference` da sessão. Sem autorização ativa, não há filtro de importação a renderizar. |
| Exportação — `default` (Somente default) | Prefix-list `IP-PFX-DEFAULT-<AFI>` (default na entrada 10) + `RP-<ASN>-EXPORT-<AFI>`. |
| Exportação — `full` (Full routing) | Somente `RP-<ASN>-EXPORT-<AFI>` (anuncia o que o VRP tem). |
| Exportação — `cdn` / `personalizado` | Prefix-list `IP-PFX-<PRODUTO>-<AFI>` com os prefixos cadastrados no perfil + `RP-<ASN>-EXPORT-<AFI>`. Sem prefixos, o render emite um comentário de dívida. |
| `default_internas` (Default + internas) / `parcial` (Tabela parcial) | **Comentário de dívida** no render: rotas internas ainda não renderizáveis — a route-policy correspondente não é definida hoje. |

**Nomes derivados (§25.4)**: base = **ASN do par** (remoto), maiúsculas,
separador `-`, até 63 caracteres — ex. `RP-64500-IMPORT-V4`,
`RP-64500-EXPORT-V6` e `IP-PFX-64500-IN-V4`. O mesmo ASN + família resulta no
mesmo nome, e definições idênticas são deduplicadas no render.

## Communities

O catálogo é **seedado** (migração) com `blackhole`, `no-export` e
`no-advertise`, e novas entradas continuam sendo criadas (criação via seed;
edição pelo CLI/API). As communities são **associadas à sessão**
(`gerenet bgp-sessions community add <sessão> <community>` / `remove`). A
aplicação do valor concreto na configuração do VRP é fase futura.

## Proteções e divergências

Use `maximum_prefix` com **margem** (acima do limite o VRP derruba a sessão) e
limiar percentual para aviso — essencial nos upstreams. Reforço importante de
operação: **a importação de políticas existentes do roteador não existe ainda**;
o que está no equipamento com nome fora do padrão (ou conteúdo divergente)
aparece na [reconciliação](/wiki/operacao) como divergência (`peer.filtros`) —
não há varredura que aproprie a política manual do equipamento.
