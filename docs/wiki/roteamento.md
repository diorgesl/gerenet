---
title: Sessões BGP, autorizações, perfis e communities
secao: Roteamento
secao_order: 3
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
- Endereços: **v4 e v6 sem máscara** — use as pontas do
  [enlace reservado](/wiki/circuitos) informando apenas o endereço da ponta: a
  máscara identifica o enlace reservado, e na sessão BGP o endereço entra
  sozinho (no v6, sem o `/126`; no v4, sem o `/31`/`/30`).

Campos de política da sessão: `import_profile_id` / `export_profile_id`,
`maximum_prefix` + limiar (0–100 %), `local_preference`, `med`, `prepend`
(0–10), `keepalive`/`holdtime` (aplicados em conjunto; senão o VRP usa os
defaults), `bfd_enabled`, `graceful_restart`, `shutdown` e os dois flags da
default, um por escopo: `allow_default_route`, da sessão de **upstream**, aceita
a default que o provedor anuncia; `default_route_advertise`, da sessão de
**cliente**, anuncia a nossa default ao peer (`peer <peer>
default-route-advertise`, no bloco da família). O anúncio é recusado quando o
circuito está vinculado a um upstream, porque ali quem aceita a default do
provedor é o `allow_default_route`.

A **senha** do peering é um segredo: definida por CLI
(`gerenet bgp-sessions password set <sessão>`), guardada no Vault e **nunca**
trafegada na API — os dados de saída mostram apenas `has_password`.

## Autorizações de prefixos

As autorizações definem o que o cliente pode anunciar, por família. Regras:

- Prefixo em CIDR, da **organização** dona; a organização desativada não recebe
  autorizações.
- Sem sobreposição entre autorizações **ativas** da mesma família de
  **organizações diferentes** (a mesma organização pode listar blocos
  contíguos/sobrepostos — a regra protege um cliente contra o outro).
- Hoje a origem é `manual`; IRR/RPKI entram na Fase 5 (políticas avançadas).

A **prefix-list de entrada** da sessão de cliente é derivada das autorizações
**ativas** somente: `IP-PFX-<ASN>-IN-<AFI>`, com uma entrada por prefixo a
partir do índice 10 (10, 20, 30…). A default não entra nela: quem a anuncia ao
cliente é o `default_route_advertise`.

O **índice 5** existe do outro lado: na prefix-list de proteção que a sessão de
upstream usa no `up-full`, `IP-PFX-<ASN>-IN-<AFI>`. Quando a sessão está sem
`allow_default_route`, a default (`0.0.0.0/0` ou `::/0`) entra nessa lista no
índice 5, antes das proteções do índice 10 (rotas internas e autorizações ativas
de clientes). A lista é toda de `permit`; quem nega é a route-policy, no `deny
node 10` que casa com ela, e o resto das rotas do provedor entra pelo node
final. Sem essa entrada, a default entraria junto com o full mesmo com o flag
desligado.

## Perfis de política

O perfil declarado na sessão (**import** ou **export**) é o caminho normal: é
ele que o render transforma em route-policy. A exceção, que a regra do §4.1 logo
abaixo detalha, é o nome lido do equipamento e importado na
[adoção](/wiki/descoberta): quando a sessão o tem, o render emite a definição
sob esse nome.

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

A exceção (§4.1): quando a sessão tem o nome da política de importação ou de
exportação preenchido — o caso que a [adoção](/wiki/descoberta) cria ao ler a
configuração do equipamento —, é esse nome que o render emite para a
route-policy, no lugar do derivado do ASN, com o corpo que a SoT monta. O nome
também pode vir do cadastro da sessão; a prefix-list do import continua saindo do
ASN do par.

## Communities

O catálogo é **seedado** (migração) com `blackhole`, `no-export` e
`no-advertise`, e novas entradas continuam sendo criadas (criação via seed;
edição pelo CLI/API). As communities são **associadas à sessão**
(`gerenet bgp-sessions community add <sessão> <community>` / `remove`). A
aplicação do valor concreto na configuração do VRP é fase futura.

## Proteções e divergências

Use `maximum_prefix` com **margem** (acima do limite o VRP derruba a sessão) e
limiar percentual para aviso — essencial nos upstreams. Reforço importante de
operação: o nome da política aplicada no equipamento é lido na configuração e
pode ser importado na revisão da [adoção](/wiki/descoberta); o cadastro da
sessão também aceita um nome. Daí em diante, é sob esse nome que o render emite
a definição, com o corpo que a SoT monta. Nada vai ao equipamento nesse momento:
mudar a política continua sendo
[mudança controlada](/wiki/mudancas-controladas). O filtro aplicado no
equipamento que não coincide com o que o render emite aparece na
[reconciliação](/wiki/operacao) como divergência (`peer.filtros`).

Dois limites ficam de pé (§11): a prefix-list interna da política importada
continua com o nome do gerenet, e uma route-policy compartilhada por dois peers
do mesmo equipamento não tem modelo — a adoção recusa, e, quando o caso chega
por outro caminho, o render emite os dois blocos sob o mesmo nome.
