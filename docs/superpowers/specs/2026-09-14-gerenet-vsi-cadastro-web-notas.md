# Cadastro de VSI na web + MTU da ponta no AC — notas (2026-09-14)

Registro da frente curta que fechou uma lacuna da Fase 4, parte 3: a página `/mpls/vsi`
listava os VSIs e **não oferecia como criar um**. A criação existia só na API
(`POST /api/v1/mpls/vsi`) e no CLI (`gerenet mpls vsi add`), o hook `useVsiCriar` estava
em `web/src/api/hooks.ts` sem nenhum consumidor, e a wiki documentava o cadastro como se
estivesse na página.

Não há plano em `docs/superpowers/plans/`: a mudança foi classificada como **bounded** (fluxo
já existente no repo, o "Novo L2VC") e implementada por TDD, sem documento de plano. Este
arquivo guarda o que as outras frentes guardariam no ledger do SDD — as decisões e o que
ficou de fora.

## Decisões

**Campos expostos: só os que viram comando, mais a descrição.** Entram domínio, nome,
VSI-ID, MTU do serviço, descrição, flow-label e a lista de PEs (equipamento, VID e MTU por
ponta). `split_horizon`, `mac_learning` e `mac_limit` existem na SoT e o CLI `show` os
imprime, mas o `vsi.j2` **não os emite** — não viram comando no equipamento. Expor os três no
formulário faria o operador configurar valores que nunca chegam ao switch, que é o mesmo tipo
de mentira que o cadastro pela web veio corrigir. Continuam aceitos na API para uso futuro.

**O MTU da ponta passou a valer de verdade.** O formulário expõe o MTU por ponta porque o
`VsiEndpointIn` o aceita e o `_create_vsi` o grava (`mtu=ep.mtu or data.mtu`), mas o
`vsi_ac.j2` não o emitia: a ponta ficava com o default da Vlanif, em silêncio. O render agora
passa `mtu=ep.mtu or service.mtu` e o template emite ` mtu <valor>` na Vlanif, como o L2VC já
fazia no AC dele. Decisão do usuário: **emitir sempre** (e não só quando difere do serviço),
aceitando a consequência abaixo.

**Consequência aceita:** o re-diff identifica o AC pela `Vlanif<vid>`, não pelo conteúdo
(`estado_bloco_vsi`), então serviços **já provisionados** aparecem como "consta" e não são
re-renderizados — eles só ganham a linha ` mtu` num re-provisionamento (remoção + provisionamento).
Até lá, a SoT mostra uma linha que o switch não tem. O runbook registra a conferência manual.

**Erro da API vira alerta dentro do modal**, e o modal continua aberto para correção. O
"Novo L2VC" tem um alerta extra fora do modal, atrás do backdrop; aqui há só um.

**Sem change request automática** ao criar: o serviço nasce sem provisionamento e a mudança
vai pelo "Solicitar mudança" do detalhe, como no L2VC e no docstring do CLI `vsi add`.

## Fatos medidos que orientaram o desenho

- O `display vsi verbose` (fixture real do S6730) traz `MTU` no nível do **VSI** e, no nível do
  AC, apenas `Interface Name` e `State` — **não há MTU por AC**. Conferir o MTU do AC exigiria
  coletar a config da Vlanif: frente separada.
- O bloco de remoção do AC é montado à mão (`bloco.comandos[1]` + `undo l2 binding vsi`), não
  derivado do bloco de criação — a linha ` mtu` nova **não** vaza para o `undo`, e a remoção
  segue sem `undo mtu`, como o L2VC nunca desfaz a interface.
- O `bloco.comandos[1]` é a linha `interface Vlanif<vid>` por posição: a linha nova entrou
  depois dela, então o índice continua válido (mas segue frágil a inserções antes).

## Revisão

Revisão independente do diff (`5c82f2f..2132d2a`), com prova por mutação. Veredito "with
fixes": 3 Important e 5 minors. Corrigidos nesta frente:

- **I1** — o alerta de erro da tentativa anterior reaparecia ao reabrir o modal (o `onClick` do
  botão não limpava o `erro`). Bug real, medido com teste que falhava antes.
- **I3** — o critério "ao criar, reseta e fecha" não tinha teste: apagar as duas linhas deixava
  a suíte verde. Agora tem, com o vermelho medido por mutação.
- **I2** — o MTU por ponta inerte (acima).
- **m4** — o `className="aviso"` não existia no CSS e o aviso caía numa coluna estreita da
  grade, parecendo um campo.
- **m5** — `min`/`max` nos inputs de VID e MTU e `maxLength` no nome, seguindo o front mais
  recente do repo; a faixa entrou no help do VID.
- **m7** — `aria-label` por linha nos botões de remover (o nome acessível era o mesmo).

Parkados (registrados, sem correção agora):

- **Pós-check do MTU do AC** — exige coletar a config da Vlanif (o `display vsi verbose` não o
  traz); hoje a conferência é manual, pelo runbook.
- **`key={idx}` nas linhas repetíveis de PE** — inofensivo hoje (inputs controlados; remover a
  primeira ponta preserva a segunda, medido), mas amarra a identidade à posição.
- **Filtrar o mesmo equipamento em duas linhas** — hoje o backend devolve 400 e o alerta mostra.
- **e2e** — nenhum fumo Playwright cobre `/mpls/vsi` (o `mpls.spec.ts` é do L2VC).
- **`numOrNull` duplicado** em `MplsVsi.tsx` e `MplsL2vc.tsx` — duas cópias de uma linha não
  justificam abstração; na terceira, extrair.

## Verificação

- `uv run pytest -q`: **865 passed** (a base era 863; +2 testes de render do MTU)
- `uv run ruff check src tests`: limpo
- `cd web && npm run test`: **136** (a base era 126; o arquivo do VSI foi de 1 para 11 testes)
- `cd web && npm run build` e `npm run lint`: limpos

## Re-revisão da onda de correção

Segunda rodada independente (diff `ad1e075..edf2adc`), com as suítes remedidas do zero:
**ADDRESSED** — os 3 Important e os 5 minors endereçados, render do AC correto (os quatro casos
do template conferidos com o `_env` real, sem linha em branco e com a indentação certa), ausência
de `undo mtu` na remoção provada pela via real (`plan_remocao_vsi`), fallback do MTU provado com
`ep.mtu = None` gravado no banco, e idempotência preservada (o regex da `Vlanif` não é afetado).
Nenhum achado novo Critical ou Important; 5 minors novos, todos corrigidos em seguida:

- o comentário do teste prometia medir o reset do `onSubmit`, que é inobservável por aquele
  caminho (quem limpa na reabertura é o `onClick`) — comentário corrigido para dizer o que mede;
- a contagem de testes web na nota estava 135 e é 136;
- o `CLAUDE.md` dizia "até um re-provisionamento", que se lê como "emitir nova CR" — e uma nova
  CR de provisionamento só produz step **pulado** com 0 blocos; passou a "re-provisionamento
  (remoção + provisionamento)";
- a linha de contexto da remoção saiu do índice fixo `comandos[1]` para âncora de conteúdo
  (`startswith("interface ")`): inserir um comando antes da `interface` deslocaria o índice em
  silêncio e o `undo` iria para a visão de sistema;
- formatação acidental num `it(...)`.
