# Design — Descoberta e adoção de peers BGP (equipamento → SoT)

> Abre a frente que inverte o sentido do fluxo: em vez de gerar configuração a
> partir da intenção, lê a configuração que o equipamento já tem e propõe o
> cadastro na SoT. O operador decide o que adotar, um objeto por vez.
> Documentos-fonte: spec §3, §6, §10 (no sentido inverso), §14, §21, §25.4,
> §25.8; designs das fases 4 (2026-09-13) e 5 (2026-09-08); design da Fase 6
> parte 1 (2026-09-14), com quem esta frente convive.
>
> Esta frente **não está prevista no §22**. O que o §10 descreve é a
> reconciliação da intenção contra o estado real; aqui o caminho é o oposto,
> do estado real para dentro da SoT.

## 1. Objetivo e escopo

O sistema só sabe ir da SoT para o equipamento. `reconciliar_device` itera as
sessões cadastradas e procura cada uma no snapshot, então um peer que existe no
roteador e não existe na SoT é **invisível**: não aparece em divergência, não
conta em métrica e não aparece em lugar nenhum. Quem tem uma borda em produção
que nunca foi cadastrada não tem por onde começar, a não ser digitar dezenas de
sessões à mão lendo o `display current-configuration`.

O material bruto para resolver isso já está no banco desde a Fase 1: o coletor
`config_backup` guarda o `display current-configuration` inteiro em
`device_snapshots.raw_files`. Falta interpretar.

Entregas:

1. **Parser da config do VRP** — blocos `bgp`, peers e subinterfaces, com
   fixture real sanitizada e teste golden, no feitio dos outros parsers.
2. **Motor de descoberta read-only** — os candidatos são os peers que a config
   tem e a SoT não, cada um com classificação, pendências e conflitos.
3. **Proposta de adoção** — a cadeia que nasceria (organização, site, circuito,
   reservas, sessão), com veredito por candidato.
4. **Conferência de fidelidade** — o render do que nasceria comparado com o
   bloco da config que o originou.
5. **Reserva por valores reais** — função nova no IPAM, irmã do
   `reservar_circuito`, mais a orientação da ponta do par p2p no modelo.
6. **Adoção transacional** — chamando os serviços que já existem, para herdar a
   auditoria sem criar caminho paralelo de escrita.
7. **Lista de ignorados** — para o peer que nunca vai ser adotado.
8. **Sugestão por LLM no resíduo** — opcional, desligada por padrão, restrita a
   texto de descrição.
9. **Superfícies** — API, CLI e o botão "Migrar" na web.

Fora de escopo: adoção sem revisão humana; adoção de L2VC, VSI ou de qualquer
objeto de MPLS; descobrir a topologia de acesso por LLDP ou tabela MAC; rodar
comando novo no equipamento (a descoberta lê apenas o que já foi coletado);
deixar o LLM decidir o que é gravado; alterar o equipamento em qualquer
hipótese.

## 2. Contexto verificado (2026-09-14)

**O que já existe e é reaproveitado.**

- `config_backup` é coletado com `backup: True` e gravado em
  `device_snapshots.raw_files`, como **lista de caminhos de arquivo** em disco
  (`automation/runner.py`), não como texto no JSON do snapshot.
- `texto_backup(snapshot)` em `automation/removal.py` já lê esse texto, com o
  caso de não haver coleta tratado (devolve `""`). O `removal.py` também já
  inspeciona o texto por busca de string (`_tem_prefix_list`,
  `_tem_route_policy`), o que mostra que ler a config salva é precedente aceito.
- `create_session` exige que a organização do circuito tenha o mesmo ASN que o
  `asn_remote` da sessão, e exige que o device seja edge ou backup_edge do
  circuito.
- `reservar_circuito` é first-fit: escolhe o primeiro VID livre
  (`_primeiro_vid`) e o primeiro prefixo livre (`_primeiro_livre`), e deriva o
  `/126` do par v4 pela regra do §25.8. **Não existe caminho para reservar um
  VID ou um prefixo específico.**
- O render lê as linhas reservadas e decide o endereço da subinterface por
  `pontas_v4`/`pontas_v6` (`automation/render.py`), que fixam a ponta local pela
  convenção: num `/31` é o endereço de baixo, num `/30` é o do meio, num `/126`
  é o `+1`. `bgp_sessions.local_address` não é lido em lugar nenhum da
  automação.
- `has_password` é property derivada de `password_ref` (não é coluna), e a
  palavra `password` **não aparece** em `automation/removal.py`; o template
  `bgp_peer.j2` só emite um comentário apontando o caminho no Vault.
  `password_ref` é o caminho do segredo, nunca o valor.
- Os índices únicos de `vlans` e `ip_prefixes` são **parciais** por
  `status = 'reservada'`, o que faz da violação de unicidade a forma natural de
  detectar conflito de reserva.

**O que não existe.**

- Nenhum parser de configuração. Os parsers existentes leem saída de `display`,
  que é tabular, e nenhum lê a árvore do `current-configuration`.
- Nenhuma noção de "objeto no equipamento que a SoT não conhece".
- Nenhuma reserva por valor específico no IPAM.
- Nenhuma forma de representar qual ponta do par é a local.

**Convivência com a Fase 6 parte 1.** Aquela frente passa a gravar a contagem de
divergência por severidade dentro do snapshot (`resources["divergencias"]`) e a
alimentar com ela o dashboard e as séries do `/metrics`. Um peer fora da SoT
**não pode** entrar em `reconcile.items`: não há desejado contra encontrado, não
é divergência, e contá-lo inflaria o alarme do painel afirmando um problema que
não existe. A lista de candidatos é um conjunto à parte, com endpoint próprio e
seção própria na página de Reconciliar.

## 3. O parser da config

**Por que um parser dedicado, e não TextFSM.** A config do VRP é uma árvore: o
bloco `bgp <asn>` contém seções de família (`ipv4-family unicast`,
`ipv6-family unicast`, `ipv4-family vpn-instance <nome>`) e é dentro delas que
vivem os peers; a interface é outro bloco, com `vlan-type dot1q` e `ip address`
dentro. TextFSM é orientado a linha e trata aninhamento por indentação com
transições de estado, o que aqui produz um template ilegível e frágil. A §4.2
prevê "TextFSM/TTP ou parsers próprios testados", então parser próprio está
dentro do que foi especificado. TextFSM continua sendo o certo para os
`display`, e nada do que existe hoje muda.

**Onde fica.** `src/gerenet/automation/parsers/huawei_vrp/config_vrp.py`, dentro
do pacote de parsers, com as fixtures em `tests/fixtures/huawei_vrp/` e o mesmo
rigor dos outros: saída real de equipamento, sanitizada, e um teste golden
cobrindo o documento inteiro.

**O que devolve.** Uma estrutura tipada com blocos de BGP (por ASN local e por
VRF), os peers de cada bloco com seus atributos, e as subinterfaces com VLAN e
endereços. Nada de dicionário solto atravessando camada: o motor de descoberta
consome objetos.

**O que lê.** Do peer: o endereço, o ASN remoto, a descrição, a route-policy de
import e de export, os prefix-lists, `maximum-prefix` com o limiar, os timers,
BFD, graceful restart, shutdown, e a **presença** de `password`. Da
subinterface: o VID do `vlan-type dot1q` (simples ou QinQ), o MTU quando
declarado, e os endereços v4 e v6 com as máscaras. Do bloco: o ASN local.

**O que nunca lê.** O valor do `password cipher`. O parser registra que existe
uma senha configurada e segue; o valor não é lido, não é guardado e não
atravessa camada nenhuma.

**A leitura do texto.** `texto_backup` sai de `removal.py` e passa a morar em
`src/gerenet/automation/snapshots.py`, com o `removal.py` importando de lá. Um
leitor só, para não haver duas versões da mesma coisa divergindo.

## 4. Identidade do candidato

A identidade é `(device_id, vrf, afi, remote_address)`, a mesma quádrupla que
`create_session` usa para decidir colisão (`_colidente_linha` sobre device, afi e
VRF; `_colidente_par` sobre o par de endereços). Usar a mesma noção de
duplicidade que o cadastro manual evita ter duas definições de "já existe" que
podem discordar com o tempo.

Um peer da config deixa de ser candidato quando:

- já existe uma `bgp_session` no mesmo device, na mesma VRF e família, com
  aquele endereço remoto. Vale para sessão ativa e para desativada: sessão
  desativada é objeto conhecido, não descoberta. Como não existe remoção de
  sessão no sistema, desativar é o caminho, e tratar a desativada como
  desconhecida faria a lista ressuscitar sozinha;
- o peer está na lista de ignorados.

**A coleta de origem.** O motor lê o snapshot mais recente do equipamento que
tenha o recurso `config_backup`. Sem snapshot, ou com snapshot sem a config, a
resposta não é lista vazia: é o aviso de que falta coletar, com o link para
coletar. Lista vazia e "nunca coletei" são estados diferentes, e confundir os
dois faz o operador achar que a borda não tem peer nenhum.

## 5. Classificação downstream × upstream

Um peer na config pode ser downstream ou upstream, e a SoT guarda cada um de um
jeito. O motor dá um palpite e **sempre** mostra o motivo, porque palpite sem
motivo não é revisável. Os sinais, do mais forte para o mais fraco:

1. **ASN remoto igual ao `devices.asn` do próprio equipamento.** É iBGP. Não
   vira proposta: entra numa lista separada de "internos", com sugestão de
   ignorar. Sessão interna de POP ou com route reflector não tem lugar na SoT
   como downstream nem como upstream, e é o ruído mais comum de uma borda real.
2. **Existe organização com aquele ASN.** O `kind` dela decide: `operadora` dá
   upstream, `downstream` dá downstream. É o sinal mais forte porque é
   informação que o operador já afirmou no cadastro.
3. **Nome de route-policy reconhecível.** Os produtos de upstream que o próprio
   sistema gera (`up-full`, `up-parcial`, `up-default`) e o export
   `IP-PFX-<ASN>-EXPORT-<AFI>` são reversíveis. Reconhecer um deles no import ou
   no export indica trânsito, mesmo sem organização cadastrada.
4. **Nada disso.** Downstream, com o motivo escrito como não confirmado. É o
   caso mais comum numa borda legada e o mais fraco dos sinais, então a
   proposta nasce marcada.

O operador corrige a classificação na revisão. Como nada é gravado sem aceite,
um palpite errado custa um clique, e não um registro errado.

## 6. A proposta de adoção

**Downstream.** A cadeia inteira que a SoT exige:

| Objeto | De onde vem |
|---|---|
| Organização | `organizations.asn` igual ao ASN do peer; ausente, vira pendência |
| Site | `devices.site_id` do equipamento |
| Circuito (edge) | o próprio equipamento |
| Circuito (acesso) | **pendência**: a config do edge não diz de que switch e porta o cliente chega |
| `circuits.code` | sugerido a partir do ASN e da VLAN, editável; se já existir, pendência |
| `stack` | v4 e v6 presentes dão `dual`; só um deles dá aquele |
| `vlan_mode` | uma subinterface para as duas famílias dá `unica`; uma por família dá `separada` |
| `p2p_v4_len` | a máscara que estiver na subinterface, `/31` ou `/30` |
| `vrf` | o bloco de BGP de onde o peer veio; instância pública quando for o bloco raiz |
| VLANs a reservar | o VID da subinterface, com `kind` `s_vlan` quando for QinQ |
| Prefixos a reservar | o par v4 real e o `/126` real, com a orientação da ponta |
| Sessão | afi, endereço local e remoto, ASN local e remoto, descrição, `maximum-prefix` e limiar, timers, BFD, graceful restart, shutdown |
| Perfis | cada nome de route-policy mapeado para um `bgp_policy_profiles.id`; o que não mapear vira pendência |

**Upstream.** A mesma cadeia, com o vínculo em `upstream_circuits` e o tipo
(`transito`, `ix`, `pni`, `contingencia`) saindo do palpite da seção 5, que o
operador confirma.

**Pendências.** O que a adoção não resolve sozinha e depende de decisão humana.
Sempre presentes em downstream: o switch e a porta de acesso, e o `code` quando
o sugerido colide. As demais: organização ausente, nome de route-policy sem
perfil correspondente, e divergência entre o ASN do bloco `bgp` e o
`devices.asn` cadastrado (que vira a oferta de corrigir o cadastro do
equipamento).

**A senha.** Um peer da config com `password cipher` entra como pendência
registrada: o equipamento tem senha, a SoT não tem como ler o valor, e
`password_ref` é caminho no Vault, não valor. O operador cadastra o segredo no
Vault e informa o caminho, ou aceita conscientemente que a SoT não sabe da
senha. Nos dois casos nada é emitido contra o equipamento: a palavra `password`
não aparece em nenhum template de remoção, e `bgp_peer.j2` só emite comentário.
A conferência de fidelidade mostra a linha da senha como diferença, que é a
verdade.

**Conflitos.** O que impede tecnicamente, com o caminho de conserto escrito ao
lado. VLAN já reservada para outro circuito no site, prefixo já reservado,
par de endereços já usado por outra sessão, e o endereço local do peer que não
corresponde à ponta que a orientação da reserva implica (inconsistência interna
que hoje passaria batido). Conflito não escondido, conflito com instrução.

**O veredito.** Três estados, e todos vêm com o motivo escrito:
`adotavel`, sem pendência nem conflito; `adotavel_com_pendencias`, quando só há
pendência, que o operador preenche na própria revisão; e `nao_adotavel`, quando
há conflito, que precisa ser resolvido fora da revisão, com a proposta sendo
recalculada sozinha na próxima abertura.

## 7. A orientação da ponta do par p2p

**O problema.** As pontas não são armazenadas: a SoT guarda a rede e
`pontas_v4`/`pontas_v6` decidem quem é o local pela convenção. Isso funciona
para o que o sistema provisionou, porque o alocador escolhe a rede e a
convenção carimba o lado local. Num circuito legado o roteador estar no
endereço de cima é igualmente comum, e nesse caso não há como a SoT representar
o circuito: a reserva grava a rede certa, e o render emite o endereço de baixo
na subinterface, que não é o do equipamento. Sem conserto do lado do
equipamento nem do lado da SoT, seria um conflito sem ação possível, que é
exatamente o que esta frente não quer produzir.

**A mudança.** `ip_prefixes` ganha `ponta_local`, com valores `inferior`
(default) e `superior`. `pontas_v4` e `pontas_v6` passam a receber a orientação
e a respeitá-la, interpretando por comprimento de prefixo: num `/31` o inferior
é o `+0`, num `/30` é o `+1`, num `/126` é o `+1`. Os chamadores passam a
informar a orientação da linha: dois pontos em `automation/render.py` e dois em
`api/routers/circuits.py`.

**O que não muda.** O alocador first-fit continua criando circuitos com
`inferior`, então todo circuito provisionado pelo sistema segue idêntico e a
migration tem default. O v6 continua sendo derivado do v4 quando é o alocador
que escolhe, porque ali não há valor real a preservar.

**Uma migration**, com default na coluna, seguindo o padrão das anteriores.

## 8. A reserva por valores reais

`reservar_circuito` não serve para adoção: ela escolhe os valores em vez de
recebê-los, e derivaria um v6 que não é o que está no roteador. A função irmã
`reservar_adocao(session, circuit_id, *, vlans, prefixos, actor,
origem_snapshot_id)` em `domain/services/ipam.py`:

- valida cada valor recebido (VID na faixa, CIDR canônico e alinhado,
  `/30` ou `/31` no v4, `/126` no v6);
- insere as linhas com os valores **reais**, incluindo `ponta_local`;
- converte violação de índice único em `ConflictError` com o recurso nomeado,
  que é como o conflito chega ao operador em vez de estourar como erro de banco;
- audita `circuit.reserve` com a origem `adocao` e o snapshot de onde veio,
  para que a reserva feita por adoção seja distinguível da feita por
  provisionamento no histórico;
- é idempotente como a irmã: circuito já reservado devolve o estado atual e
  audita como repetida.

## 9. Conferência de fidelidade

Antes de qualquer aceite, o sistema renderiza o que nasceria para aquele
circuito naquele equipamento e compara com o bloco da config que originou o
candidato. A comparação é por conjunto de linhas normalizadas dentro de cada
contexto (o render e a config não têm a mesma ordem), e o resultado é a lista do
que o render produz e a config não tem, e do que a config tem e o render não
produz.

É esta etapa que impede a SoT de nascer mentindo. Sem ela, adotar um peer cujo
route-policy não mapeou para perfil nenhum criaria um circuito que, na
renderização seguinte, mandaria o equipamento mudar para um estado que ninguém
pediu. Com ela, o operador vê a diferença antes de gravar e precisa marcar
`ciente` para prosseguir.

## 10. A adoção

Uma transação por candidato, chamando os serviços que já existem para herdar a
auditoria e a validação: resolve a organização (usa a existente ou cria uma com
o ASN da config), cria o circuito, chama `reservar_adocao`, cria a sessão, e
registra um evento `discovery.adopt` amarrando o resultado ao snapshot de
origem. Qualquer recusa no meio desfaz a transação inteira, incluindo as
reservas, para não deixar circuito órfão.

Recusa por conflito devolve 409 com o conflito identificado. A corrida entre
dois operadores adotando o mesmo peer não precisa de lock novo: a unicidade de
sessão já existe no banco e é ela que barra o segundo.

Nada é enviado ao equipamento em nenhum momento. A adoção escreve na SoT, e
mudar o equipamento continua exigindo uma change request como sempre.

## 11. Ignorados

`discovery_ignored_peers` com `device_id`, `vrf`, `afi`, `remote_address`,
`motivo`, `autor` e data, e índice único sobre a quádrupla. Serve para o peer
que nunca vai virar cadastro: iBGP com route reflector, peering de gerência,
sessão interna de POP. Sem isso a lista fica poluída e o operador aprende a não
olhar para ela.

O candidato adotado não precisa de linha nenhuma: entra na SoT e sai da lista
por consequência. A lista se cura sozinha conforme a SoT cresce, e é por isso
que a proposta não é persistida em lugar nenhum.

## 12. A sugestão por LLM

**Quando.** Só quando o ASN do peer não casa com nenhuma organização e existe
descrição no peer. É o resíduo: o parser resolve o resto, e o nome da
organização é o único campo da proposta que vem de texto livre.

**O que sai.** O ASN e a string de descrição, nada mais. Não sai config, não sai
endereço, não sai nome de equipamento, não sai topologia. A chamada é por botão
explícito na revisão, nunca automática, e a descoberta inteira funciona sem ela.

**Como.** Provedor DeepSeek, cliente compatível com OpenAI, com
`GERENET_LLM_ENABLED` (default falso), `GERENET_LLM_BASE_URL`,
`GERENET_LLM_API_KEY`, `GERENET_LLM_MODEL` (default `deepseek-flash`) e
`GERENET_LLM_TIMEOUT_SECONDS` curto. A resposta é pedida em JSON
(`response_format` de objeto, com a palavra "json" e um exemplo do formato no
prompt), validada por schema, e descartada sem drama quando não bate. A
sugestão aparece como texto na tela e **nunca** vira campo do banco sozinha:
quem decide usar é o operador.

## 13. Superfícies

**API.** Router novo `api/routers/discovery.py`, registrado em `api/main.py`.
`GET /api/v1/discovery/candidates?device_id=N` devolve os candidatos já com a
proposta, o veredito e as listas de pendências e conflitos (separar em duas
chamadas não pagaria, o cálculo é o mesmo). `POST /api/v1/discovery/adopt`
recebe a proposta revisada mais `ciente`, e é o único caminho de escrita.
`POST /api/v1/discovery/ignore` e `DELETE` para desfazer. `POST
/api/v1/discovery/sugestao` existe apenas com o provedor ligado e devolve
texto.

**CLI.** Grupo novo em `cli/discovery.py`, registrado em `cli/main.py`, com
`list`, `show`, `adopt`, `ignore`, `unignore` e `sugerir`. O `adopt` aceita um
arquivo JSON com a proposta editada, que é como se resolve uma pendência sem
abrir a web.

**Web.** Página de rota `/discovery` no grupo Operação, ao lado de Reconciliar,
com o rótulo "Migrar" no botão que leva até ela, seguindo o padrão do repo
(rota em inglês, rótulo em português, como `/reconcile` e "Reconciliar"). A
entrada é por equipamento: botão no detalhe do equipamento e na página de
Reconciliar, com o `device_id` na URL. Sem snapshot com a config, a página manda
coletar em vez de mostrar lista vazia. Cada candidato mostra o palpite de
classificação com o motivo, o veredito, as pendências e os conflitos com o que
fazer em cada um. A revisão abre com os campos editáveis, a conferência de
fidelidade em diff e o `ciente` quando há diferença. Na página de Reconciliar
entra a seção "fora da SoT", com link para a nova página já filtrada.

## 14. Testes

- **Parser** (`tests/automation/`): golden do documento inteiro sobre fixture
  real sanitizada, cobrindo downstream v4 e dual, upstream, iBGP, peer em VRF e
  peer com `password`. E um teste de mascaramento provando que o valor da senha
  não aparece no resultado do parse.
- **Motor** (`tests/automation/test_discovery.py`): peer que casa com sessão da
  SoT (ativa e desativada) não é candidato; ignorado não é candidato;
  classificação muda conforme a organização exista, seja `operadora` ou
  `downstream`; iBGP cai na lista de internos; sem snapshot com config, o
  resultado é o aviso, não lista vazia.
- **Proposta**: as inferências de `stack`, `vlan_mode` e `p2p_v4_len` a partir
  do que a config mostra; pendências obrigatórias presentes em downstream; o
  ASN divergente do cadastro do equipamento vira pendência.
- **Fidelidade**: o caso em que o render bate e o caso em que diverge por
  route-policy não mapeada, com as diferenças listadas nos dois sentidos;
  aceitar com diferença sem `ciente` é recusado.
- **Orientação da ponta** (`tests/domain/test_ipam.py`): as funções respeitam
  `superior` nos três comprimentos de prefixo; o alocador continua criando
  `inferior`; a API de circuito expõe as pontas na orientação da linha.
- **Reserva por adoção**: grava os valores reais, inclusive o v6 que **não**
  segue a derivação do §25.8, e a renderização seguinte reproduz o endereço do
  equipamento; violação de unicidade vira `ConflictError` nomeado; é
  idempotente.
- **Adoção ponta a ponta**: cria organização, circuito, reservas e sessão numa
  transação, com os eventos de auditoria; conflito de VLAN devolve 409 sem
  deixar nada gravado; organização sem ASN bloqueia; e uma recusa do
  `create_session` desfaz a adoção inteira.
- **Idempotência**: adotar duas vezes encontra a lista vazia na segunda.
- **Privacidade do LLM**: um teste que captura o payload enviado e prova que ele
  contém apenas o ASN e a descrição, sem endereço, sem nome de equipamento e sem
  config. Com o provedor desligado, a descoberta funciona igual e o endpoint de
  sugestão não é oferecido; com resposta inválida, cai no "sem sugestão".
- **e2e**: `web/e2e/discovery.spec.ts` com um snapshot de fixture contendo um
  peer fora da SoT, abrindo a página pelo equipamento, adotando e vendo o
  circuito aparecer.

## 15. Documentação e registro

- **Wiki**: página nova em `docs/wiki/` para o fluxo de migração, ligada a
  partir da página de equipamentos e da de circuitos, explicando o que a
  descoberta lê, o que ela nunca lê, o que é palpite e o que é conflito.
- **Runbook**: seção nova em `docs/runbook-validacao-ne8000.md` para a validação
  em equipamento real, que aqui é ler um snapshot de produção e conferir as
  propostas, sem escrever nada no roteador.
- **CLAUDE.md**: bullet do estado do repositório para esta frente.
- **README**: a dependência nova e as variáveis do provedor de LLM.

## 16. Decisões desta frente

1. **Nada é automático.** A descoberta propõe, o operador decide candidato a
   candidato. Não existe modo de adoção em lote sem revisão.
2. **Proposta não é persistida.** Ela é recalculada a partir do snapshot, da SoT
   e dos ignorados, como a reconciliação. A lista se cura sozinha quando o
   operador resolve uma pendência ou adota um candidato, sem estado guardado
   para ficar velho.
3. **Uma tabela nova só**, `discovery_ignored_peers`, para o resíduo que nunca
   vai ser adotado.
4. **Parser próprio em vez de TextFSM**, porque a config é árvore e o resto dos
   parsers lê saída tabular. A §4.2 permite.
5. **A orientação da ponta entra no modelo** nesta frente, com default que
   preserva o comportamento atual. Sem ela o circuito legado com o roteador na
   ponta superior seria um conflito sem ação possível.
6. **Reserva por valores reais**, com função irmã no IPAM em vez de reuso do
   first-fit, porque o v6 real não segue a derivação e o valor do equipamento é
   o que precisa ser preservado.
7. **Conferência de fidelidade antes do aceite**, com `ciente` obrigatório para
   diferença. É o que impede a SoT de nascer divergente e de mandar o
   equipamento para um estado que ninguém pediu.
8. **Peer fora da SoT não entra em divergência**, para não inflar a contagem que
   a Fase 6 parte 1 passa a gravar e a expor.
9. **LLM restrito ao resíduo, por botão e desligado por padrão**, com o payload
   reduzido ao ASN e à descrição. A descoberta não depende dele.
10. **Adoção escreve apenas na SoT.** Mudar equipamento continua exigindo change
    request.

## 17. Dívidas registradas

- **A topologia de acesso não é descoberta.** Qual switch e qual porta o cliente
  usa não está na config do edge. Resolver isso exigiria LLDP ou tabela MAC, e
  seria uma coleta nova. Fica pendência preenchida à mão.
- **A senha do peer não é recuperável.** O `cipher` do VRP não é decifrável, e o
  modelo guarda caminho no Vault, não valor. O operador cadastra o segredo ou
  aceita a diferença.
- **MPLS fica fora.** L2VC e VSI têm configuração no mesmo arquivo e poderiam
  ser descobertos, mas já têm cadastro e reconciliação próprios desde a Fase 4.
- **Sem adoção em lote.** Numa borda grande a revisão é candidato a candidato.
  Se incomodar, um aceite múltiplo com revisão diff-por-candidato é a evolução
  natural.
- **Índices de route-policy não são descobertos.** O parser lê o nome, não o
  conteúdo da policy. Mapear nome para perfil é o alcance desta frente.

## 18. Ordem de implementação

A frente é grande para um plano só, e as duas metades têm valor próprio. Sugiro
dois planos, na ordem:

**Parte 1, leitura.** O parser da config, o motor de descoberta, a proposta com
o veredito, as pendências e os conflitos, a conferência de fidelidade, os
ignorados, a coluna da orientação da ponta com o render e a API respeitando, e
as superfícies de leitura (o `GET` de candidatos, o `list`/`show`/`ignore` do
CLI e a página web mostrando tudo, sem o botão de adotar). Esta metade roda
contra o snapshot de um equipamento de produção e mostra o que dá e o que não
dá para adotar, sem escrever uma linha na SoT. É onde está quase todo o risco de
interpretação, e é o que permite validar o parser contra a realidade antes de
existir qualquer caminho de escrita.

**Parte 2, escrita.** A reserva por valores reais, a adoção transacional, o
botão de adotar e o `adopt` do CLI, a sugestão por LLM e o fumo e2e.

A ordem não é só de conveniência: a parte 1 é a que produz a evidência de que a
leitura está certa, e escrever antes disso seria gravar a partir de uma
interpretação não conferida.
