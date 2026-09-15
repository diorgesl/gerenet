# Design — Organização a partir do ASN (registro → SoT)

## 1. Objetivo e escopo

A descoberta encontra um peer cujo ASN não tem organização na SoT, e a revisão
da adoção pede que o operador digite o cadastro inteiro. Esta frente preenche
esse cadastro a partir do ASN, com duas consultas whois: a identidade (nome,
razão social, documento, AS-SET) e os blocos alocados ao AS, que entram como
autorizações de prefixo da organização nova.

Entra: a leitura do registro, a coluna `organizations.document`, o valor
`registro` em `AUTH_ORIGIN`, a lista de autorizações dentro da transação da
adoção, o conflito por bloco na proposta e o botão na tela de revisão.

Não entra: CLI (decisão do usuário em 2026-09-15, esta parte fica só na web), a
página de organizações, enriquecer organização já cadastrada, e qualquer
comando ao equipamento — mudar o roteador continua exigindo change request.

## 2. Contexto verificado (2026-09-15)

**A escrita já existe.** A parte 2 da descoberta está mergeada (PR #10,
`d5a2432`) e resolve a pendência da organização digitando: `AdocaoIn` aceita
`organizacao_id` ou `organizacao_nova: OrganizationCreate`, e
`adotar_proposta` chama `create_organization(..., commit=False)` dentro da
transação da adoção (`domain/services/discovery.py`). Não há caminho de escrita
novo a criar: o botão é um preenchimento do formulário que já está lá, e as
autorizações entram na mesma transação do `POST /adopt`.

**O dado existe.** Sondagem ao vivo dos dois servidores, AS264289
(PROVEINTER LTDA):

| Campo da SoT | Fonte | Valor devolvido |
|---|---|---|
| `name` | RADB `as-name` | `PROVEINTERLTDA-AS` |
| `legal_name` | registro.br `owner`, RADB `descr` | `PROVEINTER LTDA` |
| `asn` | a própria consulta | 264289 |
| `irr_as_set` | RADB `member-of` | `AS-264289` |
| `document` (novo) | registro.br `ownerid` | `13.172.064/0001-11` |
| blocos | registro.br `inetnum` | `138.121.28.0/22`, `2804:2594::/32` |

Dois detalhes de transporte que a sondagem fixou. O RADB responde o objeto
`aut-num` na consulta direta (`whois -h whois.radb.net AS264289`), que é um
caminho que `automation/irr.py` hoje não usa: ele só faz a inversa
`-i origin as<asn>` e descarta o `aut-num`. E o `whois.lacnic.net` delega os
ASNs brasileiros ao nic.br: a resposta para AS22548 veio com o rodapé do
registro.br e com `owner`, `ownerid` e `inetnum`, então um servidor só resolve
o caso nacional.

## 3. O que o registro devolve, e o que ele não devolve

Quatro limites que mudam o desenho e ficam registrados.

**`inetnum` é bloco alocado, não anunciado.** É o que o registro afirma ser do
AS. O RADB `-i origin` devolve os objetos `route:` registrados como anunciados,
que é outra coisa. No AS264289 o RADB não devolveu rota nenhuma, então as duas
fontes não se cobrem. A escolha desta frente é só o `inetnum`, e o efeito é
conhecido: um cliente que anuncia more-specifics dentro do bloco alocado está
coberto pela autorização do bloco maior, e um bloco anunciado que não está
alocado ao AS (transferência, reuso) não aparece.

**Fora do Brasil a sugestão fica pela metade.** O LACNIC delega ao ARIN, e para
AS13335 não veio `owner` nem `inetnum`: sobra o RADB com `as-name` e `descr`. A
leitura tem de dizer o que não encontrou em vez de devolver um cadastro pela
metade sem aviso.

**`member-of` pode vir múltiplo e auto-referente.** AS22548 declara `AS-NIC-BR`
e `AS-DNS-BR`; AS264289 declara `AS-264289`, o conjunto do próprio ASN. Qual
deles vira `irr_as_set` é decisão do operador, não do parser: o primeiro vira
sugestão e os demais ficam visíveis para troca.

**A resposta do nic.br é latin-1, e hoje ela derruba a chamada.** A sondagem
devolveu `N?cleo de Inf. e Coord. do Ponto BR`, e repetir a mesma consulta com
`subprocess.run(..., text=True)`, como `_executa_whois` faz, levanta
`UnicodeDecodeError` no byte `0xfa`. Não é mojibake no nome: a exceção sobe de
dentro do `run` e não é pega pelo `except (OSError, SubprocessError)` do
módulo, então ela escaparia como 500 em vez de virar `_FalhaRede` tratada. O
conserto é do `_executa_whois` inteiro, e não só da consulta nova: o RADB
também pode devolver `descr` acentuado em algum objeto.

## 4. A leitura

`identificar_asn(asn)` entra em `automation/irr.py`, que já é o módulo de
consulta whois com cache: a função reusa `_executa_whois`, `_FalhaRede` e o
cache `irr_cache`. O docstring do módulo passa a dizer que ele cobre as duas
consultas, porque a sigla IRR ficou mais estreita que o conteúdo.

- duas chamadas: RADB para `as-name`, `descr` e `member-of`; LACNIC para
  `owner`, `ownerid`, `country` e `inetnum`;
- `_executa_whois` passa a capturar bytes e decodificar com queda (UTF-8 e,
  falhando, latin-1), em vez de `text=True`; todas as consultas whois do módulo
  herdam o conserto;
- cache em `irr_cache` com `source="registro"` e `key=str(asn)`, TTL de 24h,
  com a mesma política fail-soft do resto do módulo (falha de rede devolve o
  payload vivo como refúgio, e sem refúgio sobe `IrrError`);
- campo que não veio volta ausente, com o motivo em `avisos`, em vez de virar
  string vazia.

**Resposta parcial é estado normal, não erro.** Um ASN estrangeiro devolve
identidade sem blocos; um ASN sem objeto no RADB devolve blocos sem nome. Isso
segue o princípio que a própria descoberta já usa: lista vazia e "não consegui
consultar" são estados diferentes, e confundir os dois faz o operador concluir
que o ASN não tem dado nenhum.

Forma da resposta: `{"nome", "razao_social", "documento", "pais",
"as_set_sugerido", "as_sets", "blocos": [{"prefix", "family", "conflito"}],
"fontes", "avisos"}`. `as_set_sugerido` é o primeiro `member-of` e `as_sets`
traz todos, para a tela oferecer troca. `conflito` traz o nome da outra
organização quando o bloco sobrepõe uma autorização ativa dela (seção 7), e é
nulo no caso comum.

## 5. O modelo

- `organizations.document`, `String(32)` opcional. Genérico, e não `cnpj`,
  porque organização de operadora estrangeira não tem CNPJ e o campo recebe o
  `ownerid` do registro. `OrganizationCreate` e `OrganizationUpdate` ganham o
  campo, então ele fica editável na página de organizações sem trabalho extra.
- `AUTH_ORIGIN` ganha `"registro"`. A migração segue o precedente de
  `alembic/versions/767551f719ba_upstreams_f5.py:33`
  (`ALTER TYPE auth_origin ADD VALUE IF NOT EXISTS`), e o downgrade derruba a
  coluna e deixa o valor no tipo, como o precedente da F5 já faz.
- A revalidação **não muda de código**: `revalidar_autorizacoes` já filtra
  `origin.in_(("irr", "rpki"))`, e `create_authorization` já só marca
  `validacao = "nao_verificada"` para essas duas origens. O valor novo nasce
  fora dos dois caminhos sem nenhuma linha nova, e é exatamente por isso que
  ele existe: marcar o bloco do registro como `irr` faria a revalidação
  consultar `-i origin` no RADB, não achar rota nenhuma no caso comum (o
  AS264289 não tem) e marcar tudo `diverge` para sempre. Dois testes pinam os
  dois comportamentos, para que ninguém os "conserte" depois.

## 6. A escrita

- `create_authorization` ganha `commit: bool = True`, como
  `create_organization` e `reservar_adocao`, para a adoção encadear na
  transação dela.
- `AdocaoIn` ganha `autorizacoes`, uma lista de `{prefix, family}`. A lista só
  vale com `organizacao_nova`; com organização existente ela tem de vir vazia.
- Autorização só nasce para organização `downstream` ou `parceiro`. A guarda de
  `create_authorization` para `operadora` continua valendo sem alteração, e o
  diálogo explica o motivo em vez de oferecer o que a API vai recusar:
  autorização de prefixo é de cliente, e o operador tem `expected_prefixes_v4`
  e `expected_prefixes_v6` no upstream, que são outra coisa.
- Idempotência (§3.2): prefixo que já tem autorização ativa da mesma
  organização não é criado de novo. Hoje `_organizacao_conflitante` ignora a
  própria organização, então a duplicata passaria calada.
- Procedência gravada: cada autorização nasce com `origin="registro"` e uma
  nota com a fonte e o ASN consultado. É o que deixa uma auditoria futura saber
  quais autorizações foram preenchidas pela máquina, já que a lista nasce toda
  marcada.

## 7. O conflito por bloco

Um bloco que sobrepõe autorização ativa de **outra** organização não vira
conflito da proposta, e o veredito não muda por causa dele. Ele é um estado do
próprio item: a lista marca aquele bloco com o nome da outra organização, a
tela o mostra desmarcado e desabilitado, e a API recusa um `AdocaoIn` que o
inclua. Assim o operador vê antes do clique em vez de receber um 409 depois, e
a adoção segue com os demais blocos.

Transformar isso em conflito da proposta seria forte demais: conflito hoje
significa `nao_adotavel`, e o operador não teria como resolver pela revisão um
bloco que ele pode simplesmente não marcar.

`adotar_proposta` mantém a guarda de defesa em profundidade: se um bloco
conflitante chegar pela API, `create_authorization` levanta `ConflictError` com
o nome das duas organizações e a transação inteira desfaz, no mesmo estilo das
quatro guardas que a adoção já tem.

## 8. A superfície

**API.** `GET /api/v1/organizations/prefill?asn=N`, de leitura e autenticada,
no router de organizações. Fica lá e não em discovery porque o que ela devolve
é preenchimento de organização, e a página de organizações pode usar o mesmo
endpoint quando ganhar o botão. Status: `200` com o que as fontes devolveram
(parcial é normal), `404` quando não há nada em nenhuma das duas, e `503`
quando as duas falharam sem cache vivo, que é falha de consulta e não ausência
de dado. ASN inválido ou reservado segue a validação de `asn_valido` e devolve
`422`.

**Contrato.** `AdocaoIn.autorizacoes` e `AdocaoIn.organizacao_nova.document`.
O `POST /api/v1/discovery/adopt` grava organização, autorizações, circuito,
reservas e sessões numa transação, como já faz.

**Web.** `DiscoveryAdopt.tsx` ganha o botão "Buscar no registro" no bloco de
organização nova. Ele preenche `name`, `legal_name`, `document`, `irr_as_set` e
`asn`, lista os blocos com a fonte de cada um, e deixa todos marcados, com a
caixa para desmarcar e o campo de prefixo editável. O que o registro não
devolver fica como está, e o aviso da leitura aparece no bloco. Os tipos em
`web/src/api/types.ts` acompanham.

## 9. Testes

- **Leitura** (`tests/automation/test_irr.py`): `_executa_whois` sobre uma
  resposta latin-1 não levanta, e o `descr` acentuado do RADB também não; parser
  sobre uma resposta latin-1 real (o nome acentuado volta inteiro); ASN
  estrangeiro devolve
  identidade sem blocos e com aviso; ASN sem `member-of` devolve `as_set` nulo;
  `member-of` múltiplo devolve o primeiro como sugestão e todos em `as_sets`;
  cache com `source="registro"` não refaz o whois dentro do TTL e serve de
  refúgio na falha de rede; falha sem cache vivo sobe `IrrError`.
- **Modelo** (`tests/domain/test_prefix_authorizations_irr_rpki.py`):
  `create_authorization` com `origin="registro"` deixa `validacao` nula, e
  `revalidar_autorizacoes` não a toca nem conta no retorno.
- **Adoção** (`tests/domain/test_discovery_service.py`): a lista de
  autorizações cria os registros na mesma transação, com `origin` e nota; um
  bloco conflitante devolve 409 nomeando as duas organizações e não deixa nada
  gravado; organização `operadora` com lista não vazia é recusada com o motivo;
  `autorizacoes` com `organizacao_id` (existente) é recusada; prefixo já
  autorizado não duplica; adotar duas vezes não cria nada na segunda.
- **API** (`tests/api/test_organizations_api.py`) com o whois stubado:
  `200` parcial, `404` sem dado, `503` sem rede e sem cache, `422` para ASN
  inválido; e o `AdocaoIn` recusando um bloco marcado como conflitante.
- **Web** (`web/src/pages/Discovery.test.tsx` e um teste do
  `DiscoveryAdopt.tsx`): o botão preenche os campos, a lista nasce toda marcada,
  desmarcar remove do payload e o bloco conflitante fica desabilitado.
- **e2e**: o fumo de adoção passa a mandar a lista de autorizações e confere
  que elas nascem no circuito. O botão de prefill não entra no e2e porque o
  whois não é chamável de forma determinística no CI, e a leitura fica coberta
  pelos testes de unidade e de API com o servidor stubado.

## 10. Documentação e registro

- **Wiki**: a página `/wiki/descoberta` ganha a seção do botão, dizendo o que o
  registro dá (identidade e blocos alocados), o que ele não dá (anúncio real,
  ASN estrangeiro) e que a lista nasce marcada por decisão do operador.
- **Runbook**: a seção da descoberta em `docs/runbook-validacao-ne8000.md`
  ganha a conferência da consulta ao registro num ASN real.
- **CLAUDE.md**: bullet do estado do repositório para esta frente.
- **README**: nada. A dependência é o binário `whois`, que o projeto já usa
  desde a F5.

## 11. Decisões desta frente

1. **Grava organização e autorizações de uma vez** (escolha do operador em
   2026-09-15), com a lista visível antes do clique e a procedência gravada em
   cada autorização. É a aprovação humana do §6.4: o operador vê o que vai ser
   autorizado e o clique é o aceite.
2. **Só o `inetnum` do registro** como fonte de blocos, nem `route:` do IRR nem
   ROA do RPKI. Fonte única, sem procedência misturada.
3. **Sem CLI.** A parte visual de importar e migrar um peer fica só na web.
4. **`origin="registro"` é valor novo do enum**, e a revalidação já o ignora
   sem mudança de código.
5. **Conflito de sobreposição é por bloco**, não da proposta, para não tornar
   a proposta `nao_adotavel` por um item que o operador pode não marcar.
6. **O prefill é leitura e não persiste nada.** Quem grava é a adoção.
7. **`create_authorization` ganha `commit=False`** para encadear na transação
   da adoção, no padrão que `create_organization` e `reservar_adocao` já usam.

## 12. Dívidas registradas

- **More-specifics anunciados fora do bloco alocado não entram.** Cobre-los
  exigiria cruzar com `-i origin` ou com os ROAs, que esta frente deixou de
  fora por decisão.
- **ASN estrangeiro não recebe blocos.** Fora do LACNIC a consulta não traz
  `inetnum`, e a organização nasce com a identidade do RADB e mais nada.
- **A página de organizações não ganha o botão.** O mesmo endpoint serve, mas a
  superfície fica para quando houver demanda.
- **Enriquecer organização já cadastrada fica fora.** Preencher `legal_name` e
  AS-SET de uma organização existente é a evolução natural e não é esta frente.
- **`validacao` fica nula para origem `registro`.** Não há contra o que validar
  sem uma fonte de anúncio, e inventar uma comparação contra o próprio
  `inetnum` seria validar a fonte contra ela mesma.

## 13. Ordem de implementação

1. `identificar_asn` em `automation/irr.py`, com cache e decodificação, e os
   testes do parser.
2. Coluna `organizations.document` e o valor `registro` no enum, com a
   migração.
3. `create_authorization(commit=False)` e os dois testes que pinam a
   revalidação.
4. `GET /api/v1/organizations/prefill`.
5. `AdocaoIn.autorizacoes`, as guardas na adoção e o conflito por bloco na
   proposta.
6. O botão e a lista na tela de revisão, com os tipos.
7. Wiki, runbook e o bullet do CLAUDE.md.

A ordem põe a leitura antes da escrita pelo mesmo motivo da parte 1 da
descoberta: é a leitura que produz a evidência de que o dado do registro está
certo, e gravar antes disso seria gravar a partir de uma interpretação não
conferida.
