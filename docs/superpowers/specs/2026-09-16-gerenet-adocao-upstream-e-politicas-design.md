# Design — Default route do cliente, adoção de upstream e política com o nome do equipamento

> Corrige o sentido do `Default Route` da sessão BGP (hoje aceita a default que o
> downstream manda; passa a anunciá-la a ele), dá ao modal de adoção o `kind` da
> organização e a cadeia do upstream, leva o acesso e o tipo de policy ao cadastro
> do upstream, e permite importar o nome da route-policy lida no equipamento.
> Documentos-fonte: spec §6.3 (sessão BGP), §6.4 (filtros de entrada), §7
> (upstreams), §10 (descoberta), §14 (modelo), §25.4 (nomenclatura); design da
> descoberta (2026-09-14), da adoção (2026-09-15) e da organização por ASN
> (2026-09-15); `2026-09-08-gerenet-fase5-upstreams-revisao-notas.md`.

## 1. Objetivo e escopo

Cinco entregas:

1. **`bgp_sessions.default_route_advertise`** — coluna nova, o pedido de
   `peer <ip> default-route-advertise`. `allow_default_route` fica com o sentido
   que ela sempre teve na sessão de upstream: aceitar a default do provedor.
2. **`kind` na adoção** — o diálogo de migração escolhe a organização
   (`downstream`, `parceiro` ou `operadora`), e a cadeia gravada segue o caso.
3. **Enlace de upstream na adoção** — a revisão pode vincular um upstream
   existente ou criar o upstream junto, com o circuito principal vinculado na
   mesma transação.
4. **Acesso e circuito no cadastro do upstream** — equipamento de acesso, porta
   e o circuito principal criado e vinculado na mesma chamada; e a coluna
   `produto_import` (full, parcial, default) registrando o tipo de rota que a
   operadora envia.
5. **Política com o nome do equipamento** — `bgp_sessions.import_route_policy` e
   `export_route_policy` guardam o nome lido na adoção, e o render emite a
   definição e a referência sob esse nome.

Fora de escopo: o parâmetro opcional `peer X default-route-advertise route-policy
<nome>` (a linha é lida e o nome acoplado vira aviso, não é gerenciado), a
prefix-list de importação do upstream (`peer X ip-prefix <lista> import`, lida
pelo parser e nunca usada pelo render) e o compartilhamento de uma route-policy
entre dois peers do mesmo equipamento (a adoção recusa; não há modelo para
isso).

## 2. Contexto: o que o código faz hoje (2026-09-16)

**O checkbox.** `_bloco_import` (render.py:247) insere a default na prefix-list
de importação da sessão de cliente quando `allow_default_route` está marcado:

```python
if sessao.allow_default_route:
    entradas.append({"index": 5, "prefixo": "0.0.0.0/0" if afi == "ipv4" else "::/0"})
```

O efeito é aceitar do downstream a default que ele mandar. Na sessão de upstream
o mesmo campo tem o sentido certo e é usado assim: `_bloco_import_upstream`
(render.py:524) deixa a default FORA da lista de proteção do up-full quando
`allow_default_route` é verdadeiro, porque trânsito e IX anunciam a default e
quem decide aceitá-la é o operador. O comando do outro lado não existe: nem
coluna, nem template, nem parser conhecem `default-route-advertise`.

**A política.** Os quatro construtores de política chamam o naming direto para
tirar o nome do ASN do par (`naming.rp_import`/`rp_export` em render.py:245, 314,
499 e 634), e o template recebe o nome por parâmetro. A configuração lida traz
`import route-policy`/`export route-policy` por peer (`PeerConfig`) e a adoção
descarta os dois: o nome que o serviço usa hoje no equipamento não tem onde ser
gravado. `_pendencia_de_politica` (discovery.py:392) transforma o caso em
`politica_fora_do_padrao`, com o texto "o render emitirá nomes novos".

Vale registrar por que importar só a referência não serve. A reconciliação tira o
nome esperado do **bloco definido**, e não da linha do peer: `rp_por_sessao`
(reconcile.py:223) lê a primeira linha de cada bloco `route-policy`/`prefix-list`
e o `peer.filtros` (reconcile.py:302) só compara quando o tipo está nesse mapa.
Referenciar um nome sem emitir a definição desligaria a conferência de filtros em
silêncio, e as autorizações de prefixo virariam decoração. Importar o nome tem de
significar gerenciar o corpo sob ele.

**A adoção.** O diálogo grava a organização nova sempre com `kind="downstream"`
(`DiscoveryAdopt.tsx`), cria o circuito sem vínculo de upstream e segue. Num
enlace de operadora isso produz uma sessão que o render trata como cliente: o
despacho é pelo vínculo (`_eh_upstream`, render.py:406, via
`upstream_do_circuito`), não pelo `kind`. Pior, `_autorizadas_clientes`
(render.py:461) exclui as autorizações das organizações operadora, então a sessão
ficaria no caminho de cliente com o conjunto de autorizações de outro caminho.

## 3. O default route: duas colunas, dois sentidos

### 3.1 As colunas

`bgp_sessions.default_route_advertise`, `Boolean`, `NOT NULL`, default `False`.
Marcada, pede `peer <ip> default-route-advertise` ao peer, na família de
endereço. `allow_default_route` fica onde está e com o sentido de sempre, agora
restrito ao que ele descreve: a sessão de upstream aceitar a default do
provedor.

O nome da coluna antiga não muda. Ela continua verdadeira onde vale, e renomear
custaria migração de dados e de todo chamador sem trocar o que o campo faz.

### 3.2 Migração dos dados

As sessões sem vínculo de upstream copiam o valor para a coluna nova e zeram a
antiga; as sessões de upstream ficam como estão. A cópia preserva a intenção: o
operador marcou "Default Route" esperando anunciar a default ao downstream, e era
o efeito do render que estava errado.

```sql
UPDATE bgp_sessions
   SET default_route_advertise = allow_default_route,
       allow_default_route = false
 WHERE circuit_id NOT IN (SELECT circuit_id FROM upstream_circuits);
```

O `downgrade` devolve o valor às sessões sem vínculo e zera a coluna nova. A
volta perde o que foi marcado em `default_route_advertise` depois da migração,
que é o esperado para uma coluna recém-criada.

### 3.3 O render e o template

`_bloco_import` perde as linhas 247-248. A sessão de cliente deixa de ter
qualquer caminho que insira prefixo na lista por causa desse campo.

`_bloco_peer` (render.py:673) passa `default_route_advertise` ao contexto, e
`bgp_peer.j2` emite a linha dentro da família, logo depois de
`peer {{ peer }} enable`:

```
 ipv4-family unicast
  peer 10.0.0.1 enable
  peer 10.0.0.1 default-route-advertise
  peer 10.0.0.1 import route-policy RP-65001-IMPORT-V4
```

A posição dentro do bloco não afeta a conferência de fidelidade, que compara as
linhas como conjunto (`_normaliza_linhas`, discovery.py:971).

O comando é emitido sempre que o campo está marcado, em qualquer um dos dois
caminhos. A web só oferece o checkbox na sessão de cliente; a guarda contra marcar
numa sessão de upstream fica no serviço (3.5).

### 3.4 O parser

`_novo_peer` (config_vrp.py:67) ganha a chave `default_route_advertise: False`, e
`_aplica_peer` (config_vrp.py:104) ganha um ramo para `default-route-advertise`.

O ramo entra **antes** do `elif "route-policy" in resto` (config_vrp.py:125). O
VRP aceita `peer X default-route-advertise route-policy <nome>`, e esse `resto`
tem `route-policy` na lista: na ordem atual ele cairia no ramo da política de
importação e gravaria como import uma política que não é a de importação. O nome
acoplado não é modelado, e a linha vira `avisos` para o operador saber que aquele
trecho não é gerenciado.

### 3.5 A guarda de escopo

`create_session` e `update_session` recusam `default_route_advertise=True` quando
o circuito está vinculado a um upstream, com `ValidationError` (422 na API). O
`upstream_do_circuito` entra por import tardio dentro da função, como
`adotar_proposta` já faz com `automation.discovery`: `upstreams.py` importa
`bgp_sessions`, e no topo o ciclo derruba quem importa primeiro.

### 3.6 A web e o escopo da sessão

Hoje o formulário decide o rótulo do checkbox por `organization_kind ==
"operadora"` (o único proxy disponível no payload). O proxy erra: o render
despacha pelo vínculo, não pelo `kind`, e uma organização operadora sem vínculo
cai no caminho de cliente. O `BgpSessionOut` ganha `upstream_id` (o vínculo do
circuito, nulo quando não há), e a página passa a escolher por ele.

Com o escopo correto, cada formulário mostra o checkbox do seu caso:

- sessão de cliente: **"Anunciar rota default ao cliente"** →
  `default_route_advertise`;
- sessão de upstream: **"Aceitar rota default do provedor"** →
  `allow_default_route` (rótulo e comportamento atuais).

`web/src/help.ts:88` passa a ter as duas chaves, e o texto de
`bgp.allow_default_route` sai de "Aceita rota default (0.0.0.0/0 ou ::/0) do peer
— entra antes das autorizações na prefix-list" para a versão de upstream.

## 4. A política com o nome do equipamento

### 4.1 As colunas e a resolução do nome

`bgp_sessions.import_route_policy` e `bgp_sessions.export_route_policy`,
`String(63)`, nullable. Nula, o nome segue vindo do naming (§25.4); preenchida,
ela é o nome efetivo.

O render resolve o nome num lugar só. Nascem dois helpers de módulo,
`_nome_rp_import(sessao)` e `_nome_rp_export(sessao)`, e os quatro construtores
passam a chamá-los em vez de `naming.rp_*`. O resto do corpo não muda: a
prefix-list interna continua com o nome do gerenet
(`IP-PFX-<ASN>-IN-<AFI>`, `naming.pfx_in`), o produto e a lista continuam saindo
da SoT, e nenhum template muda.

Exceção registrada ao §25.4: o nome da route-policy pode deixar de derivar do ASN
do par. As demais regras de nomenclatura seguem valendo, incluindo o limite de 63
caracteres.

### 4.2 O que a importação significa

Com o nome importado, o gerenet passa a ser dono daquele nome no equipamento. A
primeira CR que provisionar a sessão emite `route-policy <nome lido>` com o corpo
da SoT, e se o corpo divergir do que está lá o serviço muda. Duas coisas seguram
isso:

- a conferência de fidelidade já compara o corpo das definições que a sessão
  referencia (contexto `definicao`), e a diferença exige o `ciente`;
- o texto de `politica_fora_do_padrao` (discovery.py:392) passa a dizer o que
  acontece: o nome será importado e o gerenet passará a gerenciar o corpo sob
  ele.

A escolha dos perfis de importação e exportação continua obrigatória na revisão,
pelas mesmas razões de hoje: o produto (full, parcial, default) não é recuperável
do nome.

### 4.3 A revisão da adoção

`AdocaoSessaoIn` (schemas.py:1121) ganha `import_route_policy` e
`export_route_policy`, ambos `str | None` com o padrão de nome validado. Os dois
entram em `_DO_OPERADOR`: o valor da proposta é a sugestão, e quem decide entre
manter e limpar é o operador. Limpar os dois devolve os nomes do §25.4.

`_sessao_de` (discovery.py:328) passa a devolver `default_route_advertise`,
`import_route_policy` e `export_route_policy` do `PeerConfig`; `BgpSessionCreate`
e `BgpSessionUpdate` ganham os três campos.

O diálogo mostra o nome lido em cada família, com o botão de limpar. O diff da
fidelidade é o mesmo caminho de hoje.

### 4.4 Nome repetido no mesmo equipamento

Dois peers do mesmo equipamento com o mesmo nome de política e corpos diferentes
conviveriam sob um cabeçalho só: `_apensa_definicao` (render.py:199) deduplica
por (tipo, nome) e guarda um conjunto de textos, então os dois blocos sairiam
com o mesmo cabeçalho (dívida do ciclo C, registrada em §25.4/§25.5).

A adoção recusa em vez de conviver. Se o nome lido (import ou export) já está em
uso por outra sessão ativa do mesmo equipamento, ou por outro enlace da mesma
proposta, a proposta recebe o conflito `politica_compartilhada` e fica
`nao_adotavel`. A checagem roda nos dois lados: na montagem da proposta
(`automation/discovery.py`) e na escrita (`adotar_proposta`, que já importa o
módulo da descoberta tardiamente).

O caminho de saída é renomear: adotar sem importar o nome, ou cadastrar a
política compartilhada à mão. Modelar o compartilhamento fica fora desta frente.

### 4.5 Validação do nome

`^[A-Za-z0-9_.\-]{1,63}$`, com mensagem em português. O limite é o do VRP; o
conjunto de caracteres é o que o parser lê de volta sem ambiguidade.

## 5. O kind e a cadeia do upstream na adoção

### 5.1 A regra de coerência

O `kind` da organização e o bloco de upstream andam juntos:

- `kind="operadora"` exige o bloco `upstream` na revisão;
- bloco `upstream` presente exige organização operadora, nova ou existente.

A razão é a de §2: o render despacha pelo vínculo, mas `_autorizadas_clientes`
filtra pelo `kind`. Organização operadora sem vínculo é o único estado em que os
dois critérios discordam, e ele não deve nascer pela adoção. Sem o bloco, a
recusa é `ValidationError` (422).

### 5.2 O bloco novo em `AdocaoIn`

`AdocaoUpstreamIn`, com `extra="forbid"` como os irmãos, e duas formas:

- `upstream_id`: vincula a um upstream existente (precisa ser da organização
  operadora da revisão, e ativo);
- criação: `name`, `tipo`, `capacity`, `priority`, `cost`, `expected_prefixes_v4`,
  `expected_prefixes_v6`, `max_prefix_margin_pct`, `entrada_local_preference`,
  `rpki_enabled` — os campos de `UpstreamCreate` menos `organization_id`, que vem
  da organização da adoção.

Nos dois casos, `papel` (`principal`|`contingencia`, padrão `principal`) e
`ordem` (padrão 1). Cada adoção cria um vínculo, e o padrão `principal` mantém a
regra R-01 satisfeita desde o primeiro momento.

### 5.3 A ordem da transação

`adotar_proposta` (discovery.py:173) passa a gravar, na transação única de hoje:

1. organização (nova, se for o caso);
2. autorizações do registro;
3. upstream (novo, se a revisão não deu um id);
4. circuito;
5. reserva (`reservar_adocao`);
6. vínculo (`vincular_circuito`);
7. sessões (`create_session`);
8. `propagar_defaults`.

`vincular_circuito` e `propagar_defaults` ganham `commit=False`, e
`create_upstream` também (upstreams.py:80, 200, 201). A propagação roda depois das
sessões porque é ela que preenche `import_profile_id` pelo produto do tipo quando
a revisão não escolheu perfil, e que recalcula o `maximum_prefix` quando há
prefixos esperados. Sem `expected_prefixes`, o `maximum_prefix` lido do
equipamento fica de pé.

O evento `discovery.adopt` passa a registrar o bloco do upstream (id, papel,
ordem e, na criação, o tipo e o produto), ao lado do que ele já registra.

### 5.4 A conferência de fidelidade do enlace de upstream

O ensaio precisa montar o mesmo caminho que a escrita vai gravar, e hoje ele cria
a organização descartável com `kind="downstream"` e um circuito de ensaio. Sem o
vínculo, o ensaio de um enlace de operadora renderiza pelo caminho de cliente e
acusa diferença em tudo.

`conferir_fidelidade` ganha o bloco do upstream (tipo, produto e papel), monta o
upstream descartável e vincula o circuito de ensaio antes de renderizar. O
`kind` da organização do ensaio sai do `kind` da revisão.

### 5.5 A classificação e as pendências

`_classificar` (discovery.py:133) classifica por `org.kind == "operadora"`. Com o
select no diálogo, quem decide é o operador, e a classificação da proposta segue
a escolha. A pendência `acesso_desconhecido` continua restrita ao downstream: no
enlace de upstream o acesso entra pelos campos que a revisão já pede
(`access_device_id`, `access_port`) e pelo cadastro do upstream (§6).

## 6. Acesso e circuito no cadastro do upstream

`POST /api/v1/upstreams` passa a aceitar um bloco `circuito` opcional, e o
formulário de novo upstream ganha a seção **Acesso**. Preenchida, ela cria o
circuito e o vincula como principal na mesma chamada, com `commit=False` nos
três serviços (`create_upstream`, `create_circuit`, `vincular_circuito`).

Campos do bloco: `code`, `site_id`, `edge_device_id`, `edge_trunk`,
`access_device_id`, `access_port` e `velocidade_mbps`. A reserva de VLAN e de
endereços continua na página do circuito, que já tem o assistente: repeti-lo aqui
duplicaria o formulário sem necessidade, e o vínculo não exige reserva.

O CLI acompanha com as mesmas opções em `gerenet upstreams add`
(`--circuito-codigo`, `--site`, `--edge-device`, `--edge-trunk`,
`--access-device`, `--access-port`, `--velocidade-mbps`).

## 7. O tipo de policy da operadora

`upstreams.produto_import`, `String(16)`, nullable, com `full`, `parcial` e
`default`. É o registro do tipo de rota que a operadora envia, e existe porque a
operadora não tem prefix-list própria: o que a descreve é o produto.

O campo é a fonte quando preenchido. Nulo, o produto continua saindo de
`PRODUTO_IMPORT_POR_TIPO` (upstreams.py:14), que é o comportamento dos upstreams
já cadastrados. `propagar_defaults` (upstreams.py:271) troca

```python
perfil = _perfil_import(session, PRODUTO_IMPORT_POR_TIPO[up.tipo])
```

por `up.produto_import or PRODUTO_IMPORT_POR_TIPO[up.tipo]`.

`produto_import` entra em `_CAMPOS_PROPAGACAO` (mudou o produto, as sessões
repropagam) e em `UpstreamCreate`/`UpstreamUpdate`, no diálogo do upstream e no
CLI. Os `expected_prefixes_v4/v6` seguem sendo a contagem esperada de rotas, para
o `maximum-prefix` e a anomalia do §7, e não uma lista de prefixos autorizados.

## 8. Superfícies

| Superfície | O que muda |
| --- | --- |
| `domain/models.py` | `BgpSession.default_route_advertise`, `.import_route_policy`, `.export_route_policy`; `Upstream.produto_import` |
| `alembic/versions/` | migração com as quatro colunas e o `UPDATE` de §3.2 |
| `automation/naming.py` | sem mudança; a exceção ao §25.4 mora no render |
| `automation/render.py` | `_nome_rp_import`/`_nome_rp_export`; `_bloco_import` sem a default; `_bloco_peer` com o campo novo |
| `automation/templates/huawei_vrp/bgp_peer.j2` | `peer {{ peer }} default-route-advertise` na família |
| `automation/parsers/huawei_vrp/config_vrp.py` | chave nova em `_novo_peer`, ramo novo antes do de `route-policy` em `_aplica_peer` |
| `automation/discovery.py` | `_sessao_de` com os três campos; conflito `politica_compartilhada`; texto de `politica_fora_do_padrao`; `conferir_fidelidade` com o upstream |
| `domain/services/discovery.py` | `AdocaoUpstreamIn` no fluxo, ordem de §5.3, `_DO_OPERADOR` com os dois nomes |
| `domain/services/upstreams.py` | `produto_import` na propagação e em `_CAMPOS_PROPAGACAO`; `commit=False` em `create_upstream`/`vincular_circuito`/`propagar_defaults` |
| `domain/services/bgp_sessions.py` | guarda de escopo de §3.5 em `create_session`/`update_session` |
| `domain/schemas.py` | `BgpSessionCreate`/`Update` e `BgpSessionOut` (`default_route_advertise`, os dois nomes, `upstream_id`); `AdocaoSessaoIn` e `AdocaoUpstreamIn`; `UpstreamCreate`/`Update` |
| `api/routers/` | `bgp_sessions` com `upstream_id`; `upstreams` com o bloco `circuito`; `discovery` sem mudança de rota |
| CLI | `bgp-sessions add/update --default-route-advertise --import-route-policy --export-route-policy`; `upstreams add` com o bloco de circuito e `--produto-import` |
| `web/src/pages/BgpSessions.tsx` | checkbox por escopo (§3.6) |
| `web/src/pages/DiscoveryAdopt.tsx` | select de `kind`, bloco do upstream, nomes de política por família |
| `web/src/pages/Upstreams.tsx` / `UpstreamDetail.tsx` | seção de acesso no cadastro, `produto_import` no detalhe e na edição |
| `web/src/help.ts` | duas chaves de default route, `produto_import`, os nomes de política |
| `docs/wiki/` | `/wiki/descoberta` (kind, upstream, nomes importados) e `/wiki/upstreams` (acesso, produto) |
| `CLAUDE.md` | bullet da frente, como nas anteriores |

## 9. Testes

Render e template:

- `default_route_advertise=True` numa sessão de cliente emite
  `peer <ip> default-route-advertise` na família certa, e não emite nada na
  outra;
- a prefix-list de importação do cliente não tem mais a entrada de índice 5,
  com o campo marcado ou não;
- `allow_default_route` continua decidindo a proteção do up-full (index 5
  ausente da lista de proteção) e não toca mais no caminho de cliente;
- nome importado: o cabeçalho do bloco `route-policy` e a linha do peer usam o
  nome da coluna; com a coluna nula, o nome do §25.4 (golden);
- o corpo sob o nome importado continua o da SoT.

Parser:

- `peer 10.0.0.1 default-route-advertise` marca a chave;
- `peer 10.0.0.1 default-route-advertise route-policy RP-X` marca a chave, não
  grava `import_route_policy` e gera aviso;
- `peer 10.0.0.1 import route-policy RP-Y` continua no ramo da importação
  (regressão da ordem dos ramos);
- a fixture do parser ganha as linhas, e o teste de idempotência do render
  (render × parse × render) continua fechando.

Serviços:

- `create_session`/`update_session` recusam `default_route_advertise=True` em
  circuito vinculado a upstream (422);
- `create_upstream` com bloco de circuito cria os dois e o vínculo principal numa
  transação, e um erro no vínculo não deixa upstream nem circuito gravados;
- `propagar_defaults` escolhe o perfil por `produto_import` quando a coluna está
  preenchida e pelo tipo quando é nula;
- mudar `produto_import` re-propaga.

Adoção:

- revisão com `kind="operadora"` sem bloco de upstream é 422; bloco de upstream
  com organização `downstream` também;
- adoção de upstream cria organização, upstream, circuito, vínculo e sessões numa
  transação, e a sessão nasce com o perfil do produto;
- o `maximum_prefix` lido do equipamento sobrevive quando não há
  `expected_prefixes` (a propagação não inventa número);
- nome de política repetido em outro enlace do mesmo equipamento vira conflito
  `politica_compartilhada` e a adoção recusa;
- limpar os dois nomes na revisão grava nulo e o render volta ao §25.4;
- `conferir_fidelidade` de um enlace de operadora não acusa diferença nos filtros
  quando a SoT reproduz a configuração (o ensaio monta o vínculo);
- o evento `discovery.adopt` carrega o bloco do upstream.

Migração:

- as sessões de cliente com `allow_default_route=True` saem com
  `default_route_advertise=True` e `allow_default_route=False`; as de upstream
  ficam intactas.

## 10. Riscos

- **A cópia da migração** (§3.2) parte da intenção de quem marcou o campo. Se
  algum operador o marcou para aceitar a default do cliente, a sessão passa a
  anunciar em vez de aceitar. A consulta de conferência é de uma linha
  (`SELECT id FROM bgp_sessions WHERE default_route_advertise`) e o anúncio só
  chega ao equipamento numa CR.
- **O corpo sob o nome importado** (§4.2) é o risco maior da frente. A adoção não
  escreve nada no equipamento, mas a primeira CR de provisionamento da sessão
  passa a emitir a política inteira. O `ciente` cobre a diferença de corpo, e o
  operador que não quer assumir o corpo limpa o nome na revisão.
- **O ensaio do upstream** (§5.4) muda o que a conferência compara. Um ensaio que
  monte o vínculo errado (papel, produto) acusa diferença que não existe e o
  `ciente` vira ruído; o teste da conferência com a configuração reproduzida
  cobre o caminho.
- **A guarda de escopo** (§3.5) precisa do vínculo no momento da escrita, e o
  serviço de sessões passa a conhecer o de upstreams por import tardio. É a mesma
  forma já usada em `adotar_proposta`.

## 11. Dívidas registradas

- `peer X ip-prefix <lista> import` é lido pelo parser (`import_prefix_list`) e
  não é usado por render, adoção nem reconciliação. Fica como está.
- `peer X default-route-advertise route-policy <nome>` é lido como aviso e não é
  modelado.
- Não há modelo para uma route-policy compartilhada por dois peers do mesmo
  equipamento. A adoção recusa (§4.4) e o render continua emitindo os dois blocos
  sob o mesmo nome quando o caso chega por outro caminho.
- A prefix-list interna da política importada continua com o nome do gerenet. O
  nome importado é só o da route-policy.
- `conferir_fidelidade` não confere `default-route-advertise` na reconciliação
  contínua: o `display bgp peer verbose` não traz o campo, e a conferência de
  configuração do `discovery show` é quem o vê.
