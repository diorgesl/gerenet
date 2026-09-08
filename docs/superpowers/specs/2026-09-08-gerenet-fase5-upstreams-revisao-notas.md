# Notas de revisão — Fase 5 (upstreams): spec principal × planos × implementação

> Revisão feita em 2026-09-08 depois do início da implementação na worktree
> `worktree-gerenet-fase5-upstreams` (branch `worktree-worktree-gerenet-fase5-upstreams`,
> commits até `571e393`). Confronta a spec principal (`ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md`,
> referida como §), o [design da fase 5](2026-09-08-gerenet-fase5-upstreams-design.md)
> e o [plano da fase 5](../plans/2026-09-08-gerenet-fase5-upstreams.md).
> Objetivo: corrigir desvios antes que as tasks seguintes os commitem, sem retrabalho.

## Já resolvido na implementação (nada a fazer)

Estes pontos estavam descritos errado no plano, mas a implementação fez igual ao design:

- `up-parcial` determinístico: info-community de "parcial" (purpose=info, direcao=import)
  usada no render; sem ela, comentário-dívida. `render.py` `_bloco_import_upstream`
  (linhas ~455-509).
- Regra ≥ 1 circuito principal: validada no serviço (`_valida_conjunto_sem_principal`,
  R-01, `services/upstreams.py` linhas ~129-161).
- Repropagação ao editar: `update_upstream` chama `propagar_defaults`.
- Região no export: passada ao template (`render.py` ~591), não rebaixada a comentário.
- Fail-safe de import sem perfil/proteção vazia (commit `571e393`).

## A corrigir/incorporar nas tasks seguintes

1. **Rotas próprias via AS-PATH no import up-full (design §4.1, spec §7.1).**
   Ausente no código já commitado: o `route_policy_import.j2` tem nós deny por
   prefix-list e community-filter, mas nenhum as-path-filter. A spec §7.1 pede
   "validação do primeiro ASN quando aplicável" e o design §4.1 pede rejeição de
   rotas próprias (AS-PATH contendo ASN próprio) e more-specifics de prefixos
   próprios/clientes. Passos: as-path-filter de ASNs próprios + nó deny no
   template, e passar `asn_local`/asns próprios no contexto do render.
   Sugestão de nome: `AS-PATH-<ASN>-OWN` (derivando do ASN local do device).
2. **B5 (variação anormal): seguir o design §5, não o plano B5.**
   Design: no job de coleta, histórico das últimas K coletas (default K configurável),
   threshold default 50% configurável, registrado no job e exposto em divergência.
   Plano B5: na reconciliação, K=2 fixo e 50% constante. O histórico de coleta é o
   sinal útil; da reconciliação ele não aparece. (Reconcile pode continuar como
   superfície de exibição, mas a conta tem que ser no coletor.)
3. **C1 (plano e checks de upstream): três itens do design §5/§8 que o plano não tem.**
   - Remoção (`plan_remocao_upstream`) deve setar `upstreams.admin_status=false`
     ao final da CR aprovada (circuitos e sessões permanecem, §14.1).
   - Gravar `prefixos_antes`/`prefixos_depois` nos `details` dos steps da CR
     (backup no pré, contagem no pós-check).
   - Pós-check usa `max_prefix_margin_pct` do upstream para a tolerância; o plano
     hardcoda 20% (`esperado * 0.2`).
4. **Golden parsers (design §13):** adicionar caso de contagem de prefixos por
   peer ausente/alta nos testes de parser existentes. Nenhuma task do plano tem.
5. **documentação (design §12):** adaptar `web/e2e/README.md` se necessário
   (estágio E, junto do runbook `docs/runbook-validacao-upstream.md`).
6. **Nomenclatura `IP-PFX-INTERNAS-<AFI>`:** o plano usa nome global sem ASN,
   diferente do design §4.2 (`IP-PFX-<ASN>-EXPORT-<AFI>`) e do padrão §25.4
   (deriva do ASN do par). Se mantido, registrar como decisão (padrão §25.x) em
   vez de desvio silencioso.

## Roadmap: itens com menção mas sem dono (assistente e VSI)

Os dois itens abaixo **estão no texto do roadmap** (§22), mas nenhuma fase os
assumiu. Precisam de dono ou de retirada explícita da promessa.

- **Assistente de downstream (§16.2, §22 F3).** O roadmap F3 diz "assistente de
  provisionamento" e a decisão §25.16 reservou um "ciclo do assistente" pós-C
  (a interface web entrou como CRUD + dashboard no C2). Nenhum plano web
  implementou o fluxo de 10 passos (§16.2) e nenhum ciclo futuro o reivindica.
  Correção: aprovar explicitamente a ausência (a web atual faz cadastro por
  tela + "Solicitar mudança" por objeto) ou planejar um ciclo web dedicado.
- **VSI multiponto (§9.3, §22 F4).** O roadmap F4 promete "provisionamento VSI;
  múltiplos endpoints; validação de LDP, pseudowire, MTU e MAC". A fase 4
  entregou L2VC ponto a ponto e, para VSI, apenas modelo + cadastro + consulta
  ("provisionamento multiponto em fase posterior", sem nomear a fase). O design
  F5 declara VSI multiponto fora de escopo. Configuração de todos os PEs na
  mesma mudança lógica e status por pseudowire/AC (§9.3) também ficaram sem
  dono. Correção: nomear a fase dona (ex. fase própria entre F5 e F6, pois o
  fluxo de CR e o runner escopo-aware já existem) ou ajustar a promessa no
  texto do §22.

## Pendências de roadmap levantadas em 2026-09-08 (análise adiada)

Itens da spec que nenhuma fase do roadmap menciona: dupla aprovação por
criticidade (§25.10, o design F5 adiou para "F6" sem a F6 o listar), endpoint
Prometheus `/metrics` (§25.15), TACACS+ (§20.2, §25.9), autenticação
OIDC/LDAP (§4.2), XPL (§25.2), coleta de alarmes (§10), "membros" em upstream
(§7) e NETCONF (§4.1). Deixados para análise futura por decisão de 2026-09-08;
não são obrigação da worktree F5.
