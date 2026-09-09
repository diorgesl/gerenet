---
title: Upstreams e políticas avançadas
secao: Roteamento
secao_order: 3
order: 2
em_breve: false
---

# Upstreams e políticas avançadas

Upstream é a conectividade de saída da própria rede: trânsito, IX, PNI ou a
contingência. Na fase 5 ele virou entidade do sistema: a operadora é uma
organização (`kind operadora`), os circuitos vinculados formam a matriz
principal × contingência e as sessões BGP entram no mesmo [fluxo de mudanças
controladas](/wiki/mudancas-controladas) dos downstreams. Duas novidades
práticas: as communities agora têm valor concreto por operadora, e a origem
das autorizações de prefixo pode ser checada contra IRR e RPKI antes da
aprovação humana.

## Organização operadora

O provedor de trânsito ou o ponto de troca é uma organização com `kind`
`operadora` (`gerenet organizations add --name <nome> --kind operadora
--asn <asn> [--irr-as-set <as-set>]`). Ela não tem autorizações de prefixo
próprias, isso é de cliente; o que se vincula a ela é o upstream, os
circuitos e as sessões.

## Upstream

O cadastro (`gerenet upstreams add`, página `/upstreams`) tem nome único,
`tipo` (`transito`, `ix`, `pni`, `contingencia`), capacidade, prioridade,
custo, a organização operadora, os esperados de prefixos v4/v6 e a margem do
maximum-prefix. O `tipo` escolhe o produto de importação por padrão:
`transito`/`ix` → `up-full`, `pni` → `up-parcial`, `contingencia` →
`up-default`.

- **Margem**: com `--expected-prefixes-v4/6` e `--max-prefix-margin-pct`
  (default 20 %), o maximum-prefix das sessões é calculado como
  esperado × (1 + margem), e o limiar de aviso assume 80 % quando não
  informado. Mudou o upstream, esses defaults são repropagados às sessões dos
  circuitos vinculados (tipo, esperados, margem, LP de entrada, LP e prepend
  da contingência).
- **Vínculos de circuito**: `gerenet upstreams circuit-add <upstream>
  <circuito> --papel principal|contingencia --ordem <n>` — um circuito
  pertence a no máximo um upstream, e a ordem do vínculo é a preferência. É
  daí que sai a matriz principal × contingência mostrada na UI.
- **Importação**: `up-full` aceita tudo do provedor exceto o que a
  prefix-list de proteção (rotas internas + autorizações ativas de clientes)
  e as communities com `bloquear` negam; sem `allow_default_route`, a default
  não entra. `up-parcial` aceita a default e as rotas portadoras da community
  de "parcial". `up-default` é só a default. Sessão sem perfil de importação
  renderiza deny-all (fail-safe, nunca accept-all).
- **Exportação**: o anúncio não é produto. Sai `IP-PFX-<ASN>-EXPORT-<AFI>`
  (rotas internas + autorizações ativas de clientes; nome derivado do ASN do
  par — lista própria de cada upstream) e a route-policy de export com as
  communities de ação da operadora (`prepend`, `lp`, `blackhole`) no
  `apply community`.

## Communities de operadora

Além do catálogo geral (só cadastro, ver [roteamento](/wiki/roteamento)),
o upstream tem communities próprias com **valor concreto**:

```
gerenet upstreams communities add --upstream-id <id> --purpose <purpose>
  --value <valor> [--direcao import|export|ambos] [--regiao <regiao>]
  [--bloquear]
```

- `purpose`: `blackhole`, `prepend`, `lp` ou `info`.
- `prepend`/`lp`/`blackhole` são as aplicações no export: o render junta os
  valores na linha `apply community` da route-policy (nada de associação
  intermediária). O valor é concreto da operadora, ex. `65530:20:0`.
- `info` é identificação no import: com `bloquear`, as rotas portadoras
  entram no deny da `up-full` (via community-filter); sem `bloquear` é a
  community de "parcial" — o render identifica por `purpose=info` +
  `bloquear=False`, a nota "parcial" é opcional e só ajuda o olho humano. Sem
  essa community cadastrada, o produto `up-parcial` sai como comentário-dívida
  no plano.
- `regiao` entra como comentário no plano de export; o if-match por região
  ainda não é gerado.

## Autorizações com IRR e RPKI (consultiva)

As autorizações de prefixo ganharam `origin` (`manual`, `irr` ou `rpki`) e
`validacao` (`ok`, `diverge`, `desconhecida`, `nao_verificada`). A validação
é **consultiva** (§10.4): registra o que a fonte externa disse sobre o
prefixo e não bloqueia nada. A autorização continua sendo proposta por
pessoa e aprovada por pessoa, com qualquer origem.

- **IRR**: `gerenet irr query <asn|as-set> [--source radb|altdb|lacnic]
  [--ttl-horas 24]` resolve ASNs e prefixos do AS-SET, com cache
  (`irr_cache`); a rede só é consultada quando o cache vence.
- **RPKI**: `gerenet rpki sync [--file <arquivo.json>]` espelha o lote do
  rpki-client (`{"roas": [...]}`) na tabela `roas` — idempotente e com
  limpeza de órfãs; sem `--file`, usa `GERENET_RPKI_ROAS_FILE`. Ao final do
  sync as autorizações de origem `irr`/`rpki` são **revalidadas
  automaticamente**; nenhuma revalidação altera o fluxo de aprovação.

## Mudança controlada

A CR de escopo `upstream` segue o ciclo D: o plano nasce em `rascunho`
agregando por device os blocos das sessões e dos circuitos vinculados
(diff por bloco × última coleta, só a diferença); remoção é a CR inversa. Na
execução, o worker pré-checa coleta com `bgp_peers`, conflito de ASN do peer
e ao menos uma sessão do upstream no equipamento, e no pós-check confere peer
presente, Established e contagem de rotas dentro de esperado × (1 ± margem)
(§13). O escopo **tem** rollback e reconciliação automáticos: `gerenet
change-requests rollback <cr>` cria a CR inversa em `aguardando_aprovacao`, e
`reconcile` reabre a aprovação dos steps não aplicados.

*Validação em equipamento real: ver o runbook
`docs/runbook-validacao-upstream.md` — somente leitura → geração sem
execução → teste em circuito/edge não crítico; sem lab (decisão de
2026-09-07).*

## Ponto de partida

- [Circuitos, VLANs e IPAM](/wiki/circuitos) — a base dos circuitos vinculados.
- [Sessões BGP, autorizações, perfis e communities](/wiki/roteamento) — os
  conceitos de sessão por família que o upstream reusa.
- [Mudanças controladas](/wiki/mudancas-controladas) — o fluxo que carrega a
  configuração.
