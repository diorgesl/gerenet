# Design — Fase 4 (parte 2): pendências do L2VC no gerenet

> Fecha o que a Fase 4 deixou em aberto no L2VC: a coleta do estado do par LDP
> (que hoje trava o pré-check), o rollback e a reconciliação da CR de escopo
> `l2vc`, e o pós-check de MTU e AC do §13.2. O provisionamento VSI multiponto
> fica para a Frente B. Documentos-fonte: spec §9.1–9.2, §10, §12.2–12.4, §13.2,
> §21; design da Fase 4 (2026-09-07); design do ciclo D (2026-09-05);
> `docs/runbook-validacao-switch-mpls.md`.

## 1. Objetivo e escopo

Três entregas, na ordem em que destravam uma à outra:

1. **Coleta e merge do estado do peer LDP** — `display mpls ldp session` entra no
   recurso `mpls_ldp_peer`, e o `estado` deixa de ser `None` nos switches reais.
   Sem isso o `valida_pre_checks_l2vc` bloqueia toda execução de L2VC.
2. **Rollback e reconciliação da CR de escopo `l2vc`** — as duas operações saem
   da lista de indisponíveis e ganham o ramo de L2VC no replanejamento.
3. **Pós-check de MTU fim a fim e do AC** — o `display mpls l2vc` já entrega
   `AC status`, `local VC MTU` e `remote VC MTU`; o parser passa a extrair e o
   pós-check a validar (§13.2).

Fora de escopo: provisionamento VSI multiponto e o rollback/reconciliação de
escopo `vsi` (Frente B); correção da derivação por baseline no rollback do escopo
`circuito`, que é dívida do ciclo D registrada na §9; mudanças de UI no fluxo de
CR além do portão de `escopoComFluxo` (§4.6).

## 2. Contexto (verificado em 2026-09-13)

- **A sessão LDP não é coletada.** `display mpls ldp peer` na família S não tem
  coluna de estado, e o `normaliza_ldp` monta `{peer_id, estado}` com
  `estado=None`. O `valida_pre_checks_l2vc` trata `None` como desconhecido e
  devolve erro, então uma execução de L2VC em switch real para no pré-check.
- **Captura real disponível.** O usuário rodou `display mpls ldp session` no
  `sw-6730-aggr-tecmais-01`; a saída virou a fixture
  `tests/fixtures/huawei_vrp/s6730_display_mpls_ldp_session.txt`. Ela casa 1:1
  com os 8 PeerIDs de `s6730_display_mpls_ldp_peer.txt`, o que permite testar o
  merge ponta a ponta com dados reais.
- **Rollback e reconciliação bloqueados no serviço.**
  `_RECONCILIA_INDISPONIVEL` e `_ROLLBACK_INDISPONIVEL`
  (`domain/services/change_requests.py`) impedem os dois escopos MPLS. A API e a
  CLI não portejam por escopo: quem barra é o serviço. A web barra antes, por
  `escopoComFluxo` (`web/src/pages/ChangeRequestDetail.tsx`), que só libera
  `circuito` e `upstream`.
- **O replanejamento não conhece L2VC.** `_replaneja` cobre `upstream` e
  `circuito`; falta o ramo `l2vc`.
- **O parser de L2VC extrai pouco.** `l2vc.template` lê `client interface`,
  `VC state` e `VC ID`. O `normaliza_l2vc` descarta o resto, inclusive
  `AC status`, `local VC MTU` e `remote VC MTU`, que a fixture real traz.
- **Pós-check parcial.** `valida_pos_l2vc` confere presença do VC e estado `up`;
  não olha AC nem MTU, ambos exigidos pelo §13.2.
- **Step sem blocos não é erro.** O runner fecha como `pulado` quando não há
  bloco a aplicar (`runner.py:731`), e `_classifica` trata `pulado` como
  aplicado. Isso é o que permite o rollback tocar só a ponta que aplicou.

## 3. Coleta e merge do estado LDP

**Abordagem escolhida: estender o recurso `mpls_ldp_peer`** com um segundo
comando e um parser por comando. O gate de recursos do runner
(`_chaves_incompletas` exige `mpls_ldp_peer` no escopo l2vc) e o pré-check
continuam lendo o mesmo recurso, sem mudança.

`collectors.py`:

```python
"mpls_ldp_peer": {
    "commands": ["display mpls ldp peer", "display mpls ldp session"],
    "parsers": {
        "display mpls ldp peer": "mpls_ldp_peer",
        "display mpls ldp session": "mpls_ldp_session",
    },
    "merge": "mpls_ldp_peer",
},
```

**Parser novo** `textfsm/mpls_ldp_session.template`, escrito contra a fixture
real. Campos: `peer_id` (com o sufixo `:0` do LDP ID) e `status`. O `*` de sessão
em remoção entra na expressão de início e é descartado. Cabeçalho, linhas de
`Codes:` e o rodapé `TOTAL:` não casam.

**Merge** em `normaliza_ldp`, que passa a receber os dois comandos:

- peer listado no `peer` **e** sessão `Operational` ⇒ `estado="up"`;
- peer listado **e** sessão com qualquer outro status ⇒ `estado="down"` (a linha
  é uma observação positiva: a sessão existe e não está operacional);
- peer sem linha de sessão ⇒ `estado=None`. Nunca `down` por omissão, regra que
  a função já documenta e que o pré-check usa para separar "desconhecido" de
  "não está UP";
- o sufixo `:0` é removido dos dois lados antes do casamento (`peer_id` do peer e
  da sessão), preservando o formato que o snapshot guarda hoje;
- peer que aparece na sessão e não na tabela de peer é ignorado (a identidade do
  recurso continua sendo o peer).

**Efeito**: `valida_pre_checks_l2vc` passa a ver `up` e libera a execução. O
comportamento antigo de bloqueio continua valendo para coleta sem a sessão, o que
é o correto para uma coleta antiga ou parcial.

**Alternativas descartadas**: recurso novo `mpls_ldp_session` (o gate e o
pré-check passariam a juntar duas listas, e a coleta ficaria com dois recursos
para manter coerentes); trocar o comando de peer pelo de sessão (perde
`TransportAddress` e `DiscoverySource`, que o snapshot guarda, e invalida a
fixture e o runbook).

## 4. Rollback e reconciliação da CR de escopo `l2vc`

### 4.1 Replanejamento

`_replaneja` ganha o ramo `l2vc`, no mesmo formato dos outros:

```python
if cr.escopo == "l2vc":
    svc = get_l2vc(session, cr.l2vc_id)
    plano = (l2vc_auto.plan_provision_l2vc(session, svc) if cr.acao == "provision"
             else l2vc_auto.plan_remocao_l2vc(session, svc))
```

Achado o item do device, ele é devolvido; device sem item no plano devolve
`PlanoDevice(blocos=[], baseline_snapshot_id=None)`, como os demais escopos.

### 4.2 Reconciliação

`"l2vc"` sai de `_RECONCILIA_INDISPONIVEL`. O resto do `reconciliar` não muda:
exige status `erro` ou `parcial`, recomputa só os steps `pendente`/`falhou`,
limpa o erro de cada um e transita para `aguardando_aprovacao`. `"vsi"` continua
indisponível, com a mensagem apontando a Frente B.

### 4.3 Rollback

`"l2vc"` sai de `_ROLLBACK_INDISPONIVEL`. A CR filha nasce com `escopo="l2vc"`,
`l2vc_id` do pai, `circuit_id=None`, ação inversa, `motivo="Rollback do CR #N"`,
`rollback_de` e status `aguardando_aprovacao`.

**O plano do filho deriva do encontrado atual**, e não do baseline de cada step
como no circuito. Motivo: no caso comum (L2VC novo) o baseline pré-mudança não
contém o VC, então a derivação pelo baseline produziria plano vazio e o
`PlanoRollbackVazio`, sem criar CR nenhuma. Derivando do encontrado atual:

- `provision` aplicado ⇒ filho `remove` com `plan_remocao_l2vc`, que só emite
  bloco para a ponta cujo VC consta no snapshot;
- `remove` aplicado ⇒ filho `provision` com `plan_provision_l2vc`;
- ponta que não aplicou não gera bloco e não ganha step no filho;
- o re-diff de execução continua sendo a rede de segurança, e a idempotência vem
  dele.

A divergência em relação ao circuito fica registrada aqui de propósito. A dívida
do escopo `circuito` (derivação por baseline) está na §9 e não é tocada nesta
frente.

Duas guardas valem para o rollback do L2VC:

- sem nenhum step aplicado no pai, a regra atual continua: `ValidationError` e
  nada persiste;
- se nenhum step aplicado gerar bloco (nada do serviço consta no encontrado
  atual), vale o `PlanoRollbackVazio`: nada persiste e a mensagem manda fazer
  manualmente.

O `plan_remocao_l2vc` exige snapshot com o recurso `l2vc` e devolve
`ValidationError` quando não há, então o rollback de uma CR de provision também
depende da coleta estar em dia. É o mesmo requisito da CR de remoção explícita, e
a mensagem já orienta a coletar antes.

### 4.4 Correção do rollback de CR de remoção (circuito e upstream)

Defeito encontrado na leitura do código em 2026-09-13 e corrigido nesta frente,
por decisão do usuário. Em `gerar_rollback`, o ramo de CR pai com `acao="remove"`
monta os steps do filho com `_replaneja(cr_pai)`, que devolve o plano da ação do
**pai** (`plan_remocao`, blocos `acao="delete"` com comandos `undo ...`). O filho
nasce com `acao="provision"` e executa remoção outra vez, o que contradiz a
docstring da própria função ("remove → provision re-renderizado do desejado") e
o §12.4.

Correção: o filho é planejado com a ação inversa à do pai, nos três escopos. Para
isso o `_replaneja` passa a aceitar a ação como parâmetro opcional (`acao=None`
mantém o comportamento atual, usado pelo `reconciliar`), e o `gerar_rollback`
chama com a ação do filho. O rollback de `provision` não muda: continua derivando
da evidência do baseline no circuito e do encontrado atual no L2VC.

Testes: rollback de uma CR de remoção aplicada gera filho `provision` cujos
blocos são de criação, em circuito e em upstream.

### 4.5 Permissões e aprovação

Nada muda. O filho nasce em `aguardando_aprovacao` e obedece à mesma regra de
aprovador diferente do solicitante do filho. Papel `operator` cria, `aprovador`
aprova, `executor` executa.

### 4.6 Web

`escopoComFluxo` (`web/src/pages/ChangeRequestDetail.tsx`) passa a devolver
`true` para `l2vc`, o que libera os botões "Reconciliar" e "Gerar rollback". O
comentário acima da função, que hoje explica a ausência de l2vc/vsi, é ajustado
para mencionar só `vsi`. Um teste de Vitest cobre o botão visível numa CR de
escopo `l2vc` em `erro` e em `aplicado`.

## 5. Pós-check de MTU e AC

**Parser.** `l2vc.template` ganha `ac_status`, `mtu_local` e `mtu_remoto`, e o
`normaliza_l2vc` passa a devolver `ac_status`, `mtu_local` e `mtu_remoto` além do
que já devolve. Linhas ausentes viram `None` em cada campo, sem inventar valor.

**Validação.** `valida_pos_l2vc` mantém os dois itens críticos de hoje (VC ausente,
VC sem `up`) e acrescenta:

| Condição | Severidade | Ação sugerida |
|---|---|---|
| `ac_status` diferente de `up` | `atencao` | conferir o AC na ponta (`display mpls l2vc`) |
| `mtu_local` diferente do MTU configurado da ponta | `atencao` | conferir o `mtu` do AC e reaplicar se preciso |
| `mtu_local` diferente de `mtu_remoto` | `atencao` | conferir simetria de MTU entre as pontas (§9.2) |

O MTU configurado da ponta é `endpoint.mtu or service.mtu`. O template sempre
renderiza `mtu`, porque `l2vc_services.mtu` tem default 1500 e não é nulo, então
o valor esperado é sempre conhecido.

**Ressalva de campo.** Se no equipamento real o `local VC MTU` refletir o MTU
físico da interface em vez do `mtu` configurado no AC, a comparação contra o
configurado vira falso positivo e o check cai para a simetria local contra
remoto. A etapa 1 do runbook decide qual das duas vale, e a decisão é registrada
no próprio runbook.

## 6. Testes

Automatizados (padrão do repo):

- **Parser da sessão**: fixture real (8 peers, todos `Operational`), variação com
  `*` de sessão em remoção, status diferente de `Operational`, saída vazia.
- **Merge**: peer com sessão `up`; peer com sessão `down`; peer sem linha de
  sessão ⇒ `None`; sufixo `:0` removido dos dois lados; peer da sessão fora da
  tabela de peer é ignorado.
- **Pré-check destravado**: com a fixture nova, `valida_pre_checks_l2vc` devolve
  `None` no caminho feliz; com sessão `down`, devolve erro citando o peer; com
  recursos sem a chave, mantém a mensagem de coleta pendente.
- **Parser de L2VC**: `AC status`, `mtu_local` e `mtu_remoto` extraídos da
  fixture real.
- **Pós-check**: MTU divergente do configurado ⇒ `atencao`; MTU assimétrico ⇒
  `atencao`; AC não-up ⇒ `atencao`; VC ausente e VC down seguem `critica`.
- **Rollback**: CR de provision aplicada com as duas pontas ⇒ filho `remove` com
  blocos nas duas; CR em `parcial` com só a ponta A aplicada ⇒ filho com bloco
  apenas em A e step de B sem bloco; CR de remove aplicada ⇒ filho `provision`;
  CR sem step aplicado ⇒ erro e nada persistido.
- **Reconciliação**: CR `l2vc` em `erro` recomputa só as pontas pendentes e volta
  a `aguardando_aprovacao`; `vsi` continua barrado com a mensagem da Frente B.
- **Rollback de remoção (§4.4)**: CR de circuito e CR de upstream com
  `acao="remove"` aplicadas geram filho `provision` com blocos de criação, não
  com os `undo` do pai.
- **Web**: Vitest do botão de rollback e do de reconciliação numa CR de escopo
  `l2vc`.

## 7. Validação em produção

Segue o `docs/runbook-validacao-switch-mpls.md`, sem lab (decisão de
2026-09-07). A etapa 1 read-only ganha dois pontos de conferência:

1. o `display mpls ldp session` coletado bate com o da fixture e o `estado` do
   peer deixa de ser `None` no snapshot;
2. o `local VC MTU` de um VC existente diz se o campo reflete o configurado no AC
   ou o MTU físico (o que decide a forma do check da §5).

Com isso a etapa 2 (geração sem execução) passa a poder chegar na etapa 3
(execução do L2VC de teste em switch não crítico), que antes parava no pré-check.
O roteiro de rollback e reconciliação com esse L2VC de teste entra no runbook.

## 8. Decisões registradas (brainstorming 2026-09-13)

1. **Duas frentes, L2VC primeiro** (usuário): a Frente A fecha a dívida do L2VC
   (sessão LDP, rollback/reconciliação, pós-check) e a Frente B faz o VSI
   multiponto depois. Duas specs, dois planos.
2. **Captura real antes do parser** (usuário): o `display mpls ldp session` foi
   capturado no switch antes de escrever o parser, como na fase 4 (parsers
   ajustados em 2026-09-08). A saída virou fixture.
3. **Recurso `mpls_ldp_peer` estendido** (§3), em vez de recurso novo ou de troca
   de comando.
4. **Rollback derivado do encontrado atual** (§4.3), com a divergência em relação
   ao escopo `circuito` registrada e a dívida deste último mantida na §9.
5. **MTU comparado com o configurado**, com a ressalva de campo da §5 e a decisão
   final tomada na etapa 1 do runbook.
6. **Correção do rollback de CR de remoção entra nesta frente** (usuário,
   2026-09-13): em vez de virar dívida, o defeito do §4.4 é corrigido junto, já
   que o `gerar_rollback` é tocado de qualquer forma e o rollback do L2VC precisa
   nascer com a semântica certa.

## 9. Dívidas registradas

- **Rollback do escopo `circuito`**: deriva o plano do baseline pré-mudança e no
  caso comum (circuito novo) o plano sai vazio, caindo no `PlanoRollbackVazio`.
  Não é tocado nesta frente; a Frente A adota a derivação pelo encontrado atual
  só no `l2vc`.
- **VSI multiponto** (Frente B): ACs por ponta, render, CR de escopo `vsi` com N
  steps, pós-check por pseudowire e AC, MAC learning. O rollback e a
  reconciliação de `vsi` continuam indisponíveis até lá.
- **Rollback de `remove` em circuito e upstream**: o defeito do plano invertido
  foi corrigido nesta frente (§4.4). O que fica de fora é a derivação por
  baseline do rollback de `provision`, descrita no item acima.
- **Evidência pendente do runbook**: o `display l2vc` sem o prefixo `mpls` e o
  comportamento do `display mpls ldp session` em outras versões de VRP.
