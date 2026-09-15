# Design — Descoberta e adoção de peers BGP (parte 2): a adoção

> Fecha a frente: a parte 1 leu a configuração do equipamento e passou a propor o
> cadastro, sem escrever nada; esta parte é a escrita. Ela é o delta sobre o
> design da parte 1, que é a base e a autoridade para tudo o que não for
> redefinido aqui. Documentos-fonte: design da parte 1 (§8, §10, §12, §17.1 e
> §18, que já desenharam esta parte), a spec do produto (§3, §6, §12, §14.1,
> §21) e o que o NE8000 real mostrou.
>
> Depende da parte 1, mergeada em `d00a445..16b1865` (PR #8), e do mount de
> `data/backups` nos containers `api` e `worker` (PR #9), sem o qual a API não lê
> o que o worker coletou.

## 1. Objetivo e escopo

A parte 1 deixou tudo pronto e nada gravado: o operador abre a página Migrar,
vê as propostas com veredito, pendências e conflitos, e não tem o que fazer com
elas. Esta parte é o botão. Ela cria a reserva **por valores reais**, monta a
cadeia (organização, site, circuito, VLAN, prefixo, sessões) numa transação só,
exige que o operador assuma as diferenças de fidelidade, e grava.

Entregas:

1. **`reservar_adocao`**, a irmã do `reservar_circuito` que reserva os valores
   que já estão no equipamento em vez de escolhê-los.
2. **`commit=False` nos serviços de cadastro**, para a adoção inteira caber numa
   transação.
3. **A adoção transacional**, orquestrando os serviços existentes.
4. **A revisão na página**, com os campos que só o operador sabe, a conferência
   de fidelidade em diff e o `ciente`.
5. **A conferência estendida** ao corpo das definições, e a separação entre o
   que a SoT vai mudar no equipamento e o que ela apenas não gerencia (§17.1).
6. **API e CLI** de adoção.
7. **As dívidas da parte 1 que pertencem a esta parte** (seção 8).

Fora de escopo, com o motivo: a sugestão por LLM (frente própria, e o valor
dela é preencher um campo de texto); representar peer em sub-rede compartilhada
(frente própria, porque mexe em código que gera configuração para todo mundo);
unificar dual stack com VLAN separada (não há caso conhecido na frota); e
canonicalizar o endereço na escrita de `bgp_sessions` (muda dado de todos os
cadastros).

## 2. Contexto verificado (2026-09-14)

**O que a parte 1 entregou e o que o equipamento real mostrou.**

- Rodando contra o NE8000 de produção (ASN 61785): **103 candidatos, 9 internos
  e 69 propostas**, sendo 34 `adotavel_com_pendencias` e 35 `nao_adotavel`. O
  agrupamento por enlace funcionou no caso real (o peer dual stack virou uma
  proposta só), e a classificação veio do cadastro (o ASN casou com a
  organização existente) em vez de palpite.
- O parser relatou com honestidade duas seções de família que não conhece,
  `ipv4-family flow` e `l2vpn-family evpn`. São seções reais do VRP, e o
  mecanismo de `avisos` existe para isso: o que não foi lido aparece.
- Conflitos reais: **28 `endereco_sem_subinterface`** e **6 `enlace_nao_p2p`**,
  peers em sub-rede compartilhada ou alcançados por rota, que o IPAM não
  representa. Eles ficam fora desta parte (decisão de 2026-09-14).
- As políticas do equipamento não seguem a convenção do sistema
  (`rm-MitasInternet-v4-in`, `rm-CUSTOMER-AS269394-V6-IN`), e é isso que a
  pendência `politica_fora_do_padrao` diz.

**O que já existe e é reaproveitado.**

- `conferir_fidelidade(session, proposta)` devolve `Diferenca(contexto,
  sobrando, faltando)` por contexto, roda o render de verdade num SAVEPOINT e
  devolve uma diferença de contexto `ensaio` quando a comparação não pôde ser
  feita. Nada é escrito por ela.
- `pontas_v4`/`pontas_v6` com orientação, `IpPrefix.ponta_local`, e o modelo de
  `Proposta` com `vlans`, `prefixos` (cada um com `network` e `ponta_local`),
  `sessoes` (nomes de coluna de `bgp_sessions`), `qinq` e `veredito`.
- `create_organization`, `create_circuit` e `create_session` validam, gravam e
  auditam. **Os três commitam** (`organizations.py:42`, `circuits.py:39`,
  `bgp_sessions.py:158`), e é por isso que a seção 3 existe.

**O que a parte 1 prometeu e não podia cumprir sozinha.**

O design da parte 1 dizia que a adoção chamaria os serviços existentes e que
"qualquer recusa no meio desfaz a transação inteira". Com serviços que commitam,
isso não é verdade: uma recusa na terceira chamada deixaria as duas primeiras
gravadas, que é exatamente o circuito órfão que o desenho queria evitar.

## 3. Uma transação só: `commit=False` nos serviços de cadastro

`create_organization`, `create_circuit` e `create_session` ganham
`commit: bool = True`. Com o default, nada muda para quem chama hoje. A adoção
passa `commit=False` em todas e faz um `commit` no fim.

Cada serviço já faz `add` → `flush` → `registrar` → `commit` → `refresh`; a
mudança é envolver o `commit` e o `refresh` na condição, sem tocar em validação
nem em auditoria. Os eventos de auditoria continuam acontecendo dentro da
transação, que é o que o §18 quer: eles são a trilha da mudança, e a mudança só
existe se a transação fechar.

A alternativa (a adoção montar os modelos direto, como o ensaio da conferência
faz) foi descartada: perderia a validação e a auditoria dos serviços, e a adoção
é justamente o caminho que mais precisa das duas.

## 4. A reserva por valores reais

`reservar_adocao(session, circuit_id, *, vlans, prefixos, actor,
origem_snapshot_id, commit=True)` em `domain/services/ipam.py`, irmã de
`reservar_circuito`:

- **Não escolhe nada.** Recebe os VID e as redes que o operador confirmou, na
  forma em que estão no equipamento, e grava. O `reservar_circuito` é first-fit e
  deriva o `/126` do v4 pela regra do §25.8; um circuito legado não segue
  nenhuma das duas, e o valor do equipamento é o que precisa ser preservado.
- **Grava a orientação da ponta** que a proposta apurou (`ponta_local`), que é
  o que faz o render devolver o endereço que o roteador realmente tem.
- **Valida o que recebe**: VID na faixa, CIDR canônico e alinhado, `/30` ou
  `/31` no v4 e `/126` no v6. O que não for isso é `ValidationError`, e a
  proposta não deveria ter chegado aqui (a parte 1 marca `enlace_nao_p2p`).
- **Converte violação de unicidade em `ConflictError`** com o recurso nomeado,
  como o `reservar_circuito` faz: o operador precisa ler qual recurso está
  tomado, não um erro de banco.
- **Audita `circuit.reserve` com a origem `adocao`** e o `snapshot_id` de onde a
  proposta veio, para que a reserva feita por adoção seja distinguível da feita
  por provisionamento no histórico.
- **É idempotente** como a irmã: circuito já reservado devolve o estado atual e
  audita como repetida.

## 5. A adoção

`adotar_proposta(session, *, proposta, revisao, actor) -> int` em
`domain/services/discovery.py`, uma transação por proposta:

1. **A organização**: a que o operador escolheu, ou uma nova com o ASN da
   configuração e o nome que ele digitou ou aceitou.
2. **O circuito**: `code` (o sugerido, editado se colidir), site do equipamento,
   edge, `access_device_id` e `access_port` que o operador informou,
   `edge_trunk`, `stack`, `vlan_mode`, `qinq`, `p2p_v4_len`, `vrf`.
3. **As reservas reais**, por `reservar_adocao`.
4. **As sessões**, uma por candidato do enlace, com os perfis que o operador
   escolheu e `password_ref` quando ele tiver cadastrado o segredo.
5. **O commit** e um evento `discovery.adopt` amarrando o resultado ao snapshot
   de origem, com o `ciente` e as diferenças que ele assumiu.

**A ordem importa** porque as FKs importam: organização antes do circuito,
circuito antes das reservas e das sessões.

**Qualquer recusa desfaz tudo.** Como nada commitou antes do fim, um
`ConflictError` na reserva deixa o banco como estava, e é por isso que a seção 3
vem antes desta. A recusa chega à superfície como 409, com o conflito nomeado.

**A corrida entre dois operadores** não precisa de lock novo: a unicidade de
sessão e os índices de `vlans` e `ip_prefixes` já existem no banco e é a
constraint que barra o segundo.

**Nada vai ao equipamento.** A adoção escreve na SoT; mudar o roteador continua
exigindo uma change request, como sempre.

## 6. A revisão e o `ciente`

**A tela.** A proposta abre num formulário com dois blocos. O que o operador
decide: o código do circuito, o equipamento e a porta de acesso, o `edge_trunk`,
a organização (escolher ou criar), os perfis de importação e exportação de cada
família, e o caminho do segredo no Vault quando o equipamento tem senha. O que é
informativo e não se edita: as reservas que serão gravadas (VID, rede e ponta), os
endereços e ASNs das sessões, a classificação com o motivo, e as pendências e
conflitos que a parte 1 levantou.

**As pendências viram campos.** Cada uma aponta para o campo que a resolve, e é
aqui que a mensagem "preencha o acesso na revisão" da parte 1 passa a ter uma
revisão de verdade. Enquanto o campo obrigatório não estiver preenchido, o aceite
fica desabilitado, com o motivo escrito ao lado.

**A conferência de fidelidade vira diff com dois grupos, e só um bloqueia.** A
parte 1 comparava o peer e o bloco da interface e devolvia o que sobra e o que
falta. Esta parte aplica as duas decisões do §17.1:

- **O corpo das definições passa a ser comparado.** Os blocos que o render emite
  para uma sessão (prefix-list, corpo das route-policies de import e export,
  community-filter, as-path-filter) já estão em `render.blocos` com o id da
  sessão, então entram na comparação. Sem isso, escolher o produto errado na
  revisão produz linhas de peer idênticas byte a byte com um corpo de política
  completamente diferente, que é o modo de falha que a conferência existe para
  impedir.
- **Descrição e MTU da subinterface não gateiam.** O render não emite `description`
  de subinterface nem `mtu`, e o equipamento tem os dois. Numa borda real isso
  significa diferença em toda proposta, e "diferença exige `ciente`" degeneraria
  em "marque sempre". Eles aparecem num grupo separado, o do que a SoT **não
  gerencia**, visível e sem bloquear.

**O `ciente` só é exigido quando a SoT vai mudar o equipamento.** Se o grupo que
muda está vazio, o aceite é direto. Se não está, o operador marca que sabe, e as
diferenças marcadas ficam na auditoria do evento `discovery.adopt`, porque "eu
sabia" é uma decisão que precisa de dono.

**O que a conferência não vê continua valendo.** Um `contexto == "ensaio"`
significa que a comparação não pôde ser feita (proposta em VRF, ou uma unicidade
que recusou o ensaio). Nesse caso não há `ciente` que valha: a adoção fica
bloqueada, e o conflito já está na proposta.

## 7. API e CLI

**API.** `POST /api/v1/discovery/adopt` recebe a identidade da proposta
(`device_id`, `vrf`, e a subinterface ou o endereço que a identifica) mais a
revisão: código, acesso, `edge_trunk`, organização (id existente ou os dados da
nova), perfis por sessão, `password_ref`, e `ciente: bool`. Devolve o
`circuit_id` criado. Erros: 404 quando a proposta não existe mais (alguém adotou
antes, e a lista se cura), 409 quando uma unicidade recusou, 422 quando falta
campo obrigatório ou o `ciente` era exigido e não veio.

**A conferência sai sob demanda, num endpoint próprio.**
`GET /api/v1/discovery/fidelidade?device_id=&vrf=&subinterface=` devolve o diff
daquela proposta. Ela **não** vai embutida na lista: cada conferência roda
`render_desejado` do equipamento inteiro dentro de um ensaio, e embutir isso
faria a página pagar 69 renders a cada abertura. A tela chama quando o operador
abre a revisão de uma proposta, que é uma por vez.

**CLI.** `gerenet discovery adopt <device> <peer> --json <arquivo>` com a revisão
completa, mais `--ciente` para o caso em que há diferença. O `--json` é o caminho
de quem prefere resolver as pendências num arquivo a abrir a tela.

## 8. As dívidas da parte 1 que entram aqui

- **`internos` passa a vir em `ResultadoPropostas`**, e o `list` do CLI deixa de
  parsear a configuração duas vezes por chamada.
- **A idade da coleta usada aparece.** Hoje a descoberta recua para um snapshot
  mais antigo quando os recentes não têm a configuração, em silêncio; a resposta
  passa a trazer a idade daquele texto, e a tela e o `list` a mostram, porque uma
  resposta de dez minutos atrás e uma de três dias atrás não valem o mesmo.
- **O `contexto == "ensaio"` para de sobrecarregar `faltando`**: a `Diferenca`
  ganha um campo próprio para a explicação, e o `sobrando` vazio deixa de poder
  ser lido como fidelidade.
- **Proposta sem site deixa de devolver lista vazia** e passa a devolver a
  diferença de `ensaio` que explica, pelo mesmo padrão que a reserva já segue.
- **A configuração é lida uma vez por chamada**, não duas.

## 9. Testes

- **`reservar_adocao`**: grava os valores reais, inclusive o v6 que **não** segue
  a derivação do §25.8, e a renderização seguinte reproduz o endereço do
  equipamento; violação de unicidade vira `ConflictError` nomeado; é idempotente;
  valor fora de faixa é `ValidationError`.
- **`commit=False`**: cada serviço, chamado assim, não grava nada antes do commit
  do chamador, e mantém o comportamento de hoje no default. Um teste por serviço.
- **A adoção ponta a ponta**: cria organização, circuito, reservas e sessões numa
  transação, com os eventos de auditoria; conflito de VLAN devolve 409 **sem
  deixar nada gravado** (a asserção que a parte 1 não podia fazer); organização
  sem ASN bloqueia; uma recusa do `create_session` desfaz a adoção inteira.
- **A conferência estendida**: uma proposta cujo perfil escolhido gera corpo de
  política diferente do equipamento aparece no grupo que muda; descrição e MTU
  aparecem no grupo que não gateia e não exigem `ciente`.
- **O `ciente`**: aceitar com diferença no grupo que muda e sem `ciente` é
  recusado; com o grupo vazio, aceitar sem `ciente` funciona.
- **Idempotência**: adotar duas vezes encontra a lista vazia na segunda, porque o
  objeto passou a existir na SoT.
- **API e CLI**: os erros 404/409/422, e o `adopt` por JSON.
- **e2e**: `web/e2e/discovery.spec.ts` adotando um candidato no banco de e2e e
  vendo o circuito aparecer.

## 10. Documentação e registro

- **Wiki** `/wiki/descoberta`: sai o aviso de que a adoção não existe; entram o
  fluxo de revisão, o que cada grupo da conferência significa, quando o `ciente`
  é exigido e o que a adoção grava.
- **Runbook do NE8000**: a validação passa a ter a adoção, num equipamento não
  crítico, com o rollback ao lado (uma CR de remoção do circuito adotado).
- **CLAUDE.md e README**: o bullet da frente passa a dizer parte 1 e 2
  entregues, e a parte 2 sai da lista de "não existe".

## 11. Decisões desta frente

1. **`commit=False` nos três serviços de cadastro** em vez de a adoção montar os
   modelos direto: sem isso a transação única não existe, e sem os serviços a
   adoção perde validação e auditoria.
2. **A reserva por valores reais não reusa o alocador**, e o `ponta_local` real é
   gravado, porque o que a SoT precisa reproduzir é o que está no equipamento.
3. **A conferência passa a comparar o corpo das definições**, e o que a SoT não
   gerencia (descrição, MTU) aparece separado e não gateia. É a aplicação das
   decisões registradas no §17.1 da parte 1.
4. **`ciente` só para o que muda o equipamento**, e as diferenças assumidas vão
   para a auditoria: "eu sabia" precisa de dono.
5. **Peer em sub-rede compartilhada não é adotável nesta parte.** O conflito
   explica, e representar isso é frente própria.
6. **A sugestão por LLM fica para uma frente própria.** O ganho é um campo de
   texto, e o custo é uma dependência e um provedor fora do perímetro.
7. **Nenhuma aprovação além do operador.** A adoção escreve na SoT, que é
   cadastro; mudar equipamento continua passando por change request.

## 12. Dívidas registradas

- **A topologia de acesso segue não descoberta**, agora com um lugar onde o
  operador informa em vez de um aviso que não levava a nada.
- **Peer em sub-rede compartilhada e alcançado por rota** ficam de fora, com o
  conflito visível. Na frota do NE8000 isso é 28 + 6 das 69 propostas.
- **A caixa do endereço em `bgp_sessions`**: a escrita segue guardando o texto
  como veio, e a comparação que decide alguma coisa é canônica. Canonicalizar na
  escrita muda dado de todos os cadastros e é frente própria.
- **As duas seções de família que o parser não conhece** (`ipv4-family flow` e
  `l2vpn-family evpn`) estão declaradas nos `avisos` e são candidatas a entrar no
  parser quando alguém precisar do que há dentro delas.
- **O dual stack com VLAN separada** continua virando duas propostas, com a
  pendência que pergunta ao operador se são um circuito só. Se o caso aparecer, a
  ação de unificar é o próximo passo.
