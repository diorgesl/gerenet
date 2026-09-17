# Plano de communities central do gerenet

Data: 2026-09-17
Status: desenho aprovado em quatro partes; aguardando revisão da spec

## 1. Contexto

O gerenet gera route-policy de import e de export a partir da SoT, mas o **plano de
communities não existe como dado**. Hoje as communities vivem em três lugares soltos:
nas route-policies clássicas escritas à mão nos equipamentos, nos filtros XPL também
escritos à mão, e em três linhas da tabela `communities` (blackhole, no-export,
no-advertise) que não guardam valor nenhum.

A consequência está no anúncio ao upstream. O render decide o que sai para cada trânsito
por **prefixo**, montando a prefix-list `IP-PFX-<ASN>-EXPORT-<AFI>`
(`render.py:631`, `_bloco_export_upstream`), o que obriga a tocar a política de cada
trânsito a cada cliente novo. A operação real, feita à mão nos roteadores, já usa o
caminho inverso: classifica na entrada do cliente e decide na saída por classe. Esta
spec traz esse plano para dentro da SoT e alinha o gerenet ao que já roda.

O objetivo declarado pelo operador: uma config central que sirva para tudo, com o ASN
principal, os CDNs, as regras de import e export por papel, as proibições de anúncio, as
políticas de prepend e as communities de informação, e que a partir dela o gerenet gere o
desired config, gere a route-policy do downstream pelas communities e faça o export ao
upstream por community em vez de por prefixo.

### 1.1 Evidências

Duas configurações reais, obtidas por `display current-configuration` já coletado. Nenhum
comando novo foi enviado a equipamento para produzir esta spec.

| Arquivo | Equipamento | Linhas | sha256 |
|---|---|---|---|
| `current-configuration.txt` | `rt-tecmais-ne8k-bgp-ddos`, `bgp 61785`, router-id 201.131.152.1 | 5438 | `30f7363b440ab4d6276a149e492ee32673008420c580e2d7e04e2d926dfd8258` |
| `current-configuration-cdn.txt` | `rt-tecmais-ne8k-bgp-ddos-vs2-cdn` (virtual system `vs2-cdn`), AS 61785 | 1826 | `7e37c9cb2d078bd5561c9dc6615a47a228308ae6ba03b7d6db0bfec93c108355` |

Os dois arquivos ficam fora do repositório (contêm segredo de peer e hash de usuário
local) e as referências de linha desta spec apontam para essas coletas locais.

Do lado da SoT foram lidos `src/gerenet/automation/render.py`,
`src/gerenet/automation/naming.py`, `src/gerenet/domain/models.py`, o parser
`automation/parsers/huawei_vrp/config_vrp.py`, o motor `automation/discovery.py` e as
migrações `b1a71e5e129b_bgp_sot.py` e `767551f719ba_upstreams_f5.py`.

## 2. Objetivo

1. O plano de communities como dado na SoT: ASN principal, ASNs anunciados, bandas,
   classes, instruções, alvos e portões.
2. A partição como contrato verificável, com validação automática de conformidade.
3. A adoção do plano a partir da configuração já coletada, sem escrever em equipamento.
4. A validação que compara **quem aplica** contra **quem testa**, e as demais
   divergências da leitura.
5. A consulta do plano no frontend.
6. A base para as fatias seguintes: classificação no import (F2), produtos e export por
   classe (F3) e a saída XPL (F4).

## 3. Fora de escopo

- **Bogons, `RefuseFilter`, RPKI e as exceções.** Continuam manuais e referenciados por
  nome. O plano não os gera, e a validação só confere que o nome citado existe.
- **O render.** Nesta fatia ele não muda. Nenhum objeto da SoT passa a alimentar o desired
  config por causa desta frente.
- **O virtual system `vs2-cdn`.** O plano conhece os alvos de CDN, mas o render continua
  emitindo uma instância só (a pendência `vrf_nao_renderizavel` da descoberta já registra
  a limitação). Gerar para o VS é frente própria e depende do plano já estar na SoT.
- **A migração dos clientes do clássico para o XPL.** A adoção preserva o nome que está no
  equipamento por `bgp_sessions.import_route_policy` / `export_route_policy`, a exceção ao
  §25.4 criada para isso. Nada muda no roteador nesta fatia.
- **Mudança em equipamento.** Renomear valor de classe, corrigir ordem de campo e
  aposentar o `IP-PFX-<ASN>-EXPORT-<AFI>` são change requests, depois.
- **A unificação de `upstream_communities`.** A tabela continua como está em F1. A
  unificação com a tabela de instruções do plano é F3.

## 4. O plano como dado

Quatro objetos novos e um estendido. Cada um é mínimo de propósito, e a spec diz o que
cada um **não** faz.

### 4.1 `communities` (estendida)

É o vocabulário do plano. A tabela já tem `name`, `tipo` e `admin_status`, e o `tipo` já
carrega o eixo certo: `tag_produto` para classe, `acao_blackhole`, `acao_prepend` e
`acao_lp` para instrução, `informacao` para informativa. O que falta é o valor.

Colunas novas:

- `valor_v4` (int, nulo), `valor_v6` (int, nulo): o community de 2 bytes por família.
- `codigo` (int, nulo): o código da instrução, que ocupa o meio da large-community
  `61785:<código>:<alvo>`.
- `banda` (enum, nulo): `local`, `transito`, `cliente`, `parceiro`, `conjunto`,
  `tamanho`, `especial` ou `instrucao`. É o que torna a partição verificável.
- `origem` (enum `manual`|`adotado`) e `origem_snapshot_id` (FK `device_snapshots`,
  nula), que é o par que a adoção já grava em `vlans` e `ip_prefixes`.

Índices únicos parciais em `valor_v4` e em `valor_v6` (nulos não colidem) e em `codigo`
para as linhas de instrução.

O que ela **não** faz: não guarda por alvo. Uma linha é o vocabulário, e quem usa aquilo é
o alvo (`community_targets`) ou a regra (`community_gates`).

### 4.2 `community_plans` (nova, linha única ativa)

- `asn_principal` (int, obrigatório), `asns_anunciados` (JSON: lista de ASN e papel, para
  os casos em que o grupo anuncia mais de um ASN).
- `origem` (`manual`|`adotado`) e `origem_snapshot_id`.
- `observacoes`, `admin_status`, timestamps.
- Índice único parcial garantindo uma linha ativa.

O que ela **não** faz: não guarda classe, instrução nem alvo. É o cabeçalho.

### 4.3 `community_targets` (nova)

Um alvo é "para quem eu anuncio e sob qual código". Para o lado dos trânsitos ele aponta
para uma linha de `upstreams`, que continua sendo a fonte de verdade de quem é o peer, do
tipo e dos parâmetros de `$preference` e `$prepend`.

- `nome` (o nome do grupo de peer no equipamento: `MSD-CDN-v4`, `IX-CG`, `VIAMS-v4`,
  `PARCEIROS_CDN`), `papel` (`transito`, `ix`, `pni`, `cdn`, `parceiro`).
- `codigo_v4` e `codigo_v6` (int, nulos): o código do alvo na large-community, e a razão
  de o GGC ser `901` em v4 e `911` em v6.
- `organization_id` (FK nula), `upstream_id` (FK nula): a identidade do peer.
- `classe_import_id` (FK `communities`, nula): a classe que este alvo aplica na entrada.
  Deriva do papel e é editável quando o caso fugir da regra.
- `gate_nome` (o nome do portão de saída no equipamento), `parametros` (JSON: tamanho
  máximo anunciado, bloco de exceção, o que mais for específico do alvo).
- `origem`, `origem_snapshot_id`, `admin_status`.

O que ela **não** faz: não guarda instrução. O que eu faço com a rota deste alvo fica na
instrução, e nesta fatia as instruções por upstream continuam em `upstream_communities`.

### 4.4 `community_gates` (nova)

O portão é "quais classes podem sair por este papel". É a matriz classe × papel.

- `nome` (`RouteExportCheck`, `RouteExportCheckV6`, `RouteExportCheck-PARCEIROS`),
  `papel` (`upstream`, `cdn`, `parceiro`, `ix`), `afi`.
- `padrao` (`recusar` ou `permitir`).
- `aceitas` e `recusadas` (JSON: lista de ids de `communities`).
- `origem`, `origem_snapshot_id`.

As duas listas existem porque a produção usa as duas. O portão da borda é
`if not community matches-any {61785:7002, 61785:7102, 65000:3001, 65000:4001} or
community matches-any {65000:991} then refuse` (linha 4664): o `not ... matches-any` é a
lista de aceitas com padrão recusar, e o `or ... matches-any {65000:991}` é a lista de
recusadas, que sobrepõe.

### 4.5 `community_import_rules` (nova)

A classificação na entrada, por papel, com a condição que a produção usa.

- `papel` (`cliente`, `parceiro`, `transito`), `afi`, `classe_id` (FK `communities`).
- `condicao` (JSON: tamanho, prefix-list, community de entrada, ou vazio para todos).
- `notas`, `origem`, `origem_snapshot_id`.

Nasce em F1 para a adoção e a consulta, e o render a consome em F2.

## 5. A partição

A partição é o contrato. Ela existe para que um valor novo não precise de reunião para ser
atribuído, e para que a validação consiga reprovar um valor fora do lugar.

| Faixa | Significado |
|---|---|
| 1 a 99 | marcadores locais (11 = PTT-SP, 90 = IX local v4, 91 = IX local v6) |
| 1xxx | trânsito (1010 = trânsito full) |
| 3xxx | cliente (3001 = v4, 3101 = v6) |
| 4xxx | parceiro (4001 = v4, 4101 = v6) |
| 5xxx | conjunto (5001 = clientes e parceiros) |
| 7xxx | tamanho (70xx = v4, 71xx = v6, último dígito = faixa de tamanho) |
| 9xx | especial (991 = só CDN, 992 = troca v4, 993 = troca v6) |

O padrão de quatro dígitos é `[classe][família][item]`, com família `0` para v4 e `1` para
v6. É o padrão que a produção já segue em `3001`/`3101` e `4001`/`4101`.

As exceções ficam nomeadas, e não escondidas:

- `1010` é família-agnóstico. A família viaja na large-community (`61785:4:1010` e
  `61785:6:1010`).
- `992` e `993` põem a família no último dígito.
- `666` é o código de blackhole e não pertence a faixa nenhuma.
- `11`, `90` e `91` são marcadores locais herdados.

## 6. O vocabulário

### 6.1 Classes

| Classe | v4 | v6 | Namespace clássico | Namespace XPL | Alvo hoje |
|---|---|---|---|---|---|
| cliente | 3001 | 3101 | `com-TECMAIS-v4` / `-v6` | `com-EXPORT-UPSTREAM-v4` (61785:3001) | 4665, 4677, 4700, 1709 (VS) |
| parceiro | 4001 | 4101 | `com-PARCEIROS_CDN-v4` / `-v6` | `com-EXPORT-CDN-v4` (61785:4001) | 4665, 4671, 4677, 1709 (VS) |
| trânsito full | 1010 | 1010 | `com-TRANSITO-FULL` | usa large `61785:4:1010` | 3486 |
| só CDN | 991 | 991 | `com-ONLY-CDN` | — | 1101, 4621, 4665, 1709 (VS) |
| troca | 992 | 993 | `com-TROCA-v4` / `-v6` | — | nenhum |
| conjunto | 5001 | — | `com-CLIENTES_PARCEIROS-CDN` | — | 3863 e quatro no VS |
| IX local | 90 | 91 | `com-IX-LOCAL-TECMAIS-v4` / `-v6` (61785:90/91) | — | seis no edge, um no VS |
| PTT-SP | 11 | — | `com-PTT_SP` | — | quatro no edge, um no VS |
| tamanho | 7001 / 7002 / 7003 | 7101 / 7102 / 7103 | — | — | 4665, 4677 |

Os valores de `tamanho` são hoje inconsistentes e a partição os arruma, sem trocar o
significado de nenhum número em uso ao mesmo tempo. O `7103` que a produção aplica em bloco
v4 `/24` passa a `7003`, e é esse deslocamento que libera a faixa `71xx` inteira para v6:
os valores `7011`, `7012`, `7111` e `7112` que aparecem nos filtros v6 migram para `7101`,
`7102` e `7103`, na mesma ordem das faixas do v4. Os comprimentos v6 correspondentes a cada
faixa se confirmam na adoção. O `65000:7001`, que significa tamanho na borda e
`com-CUSTOMER-CLIENTE-v4` no VS, é uma colisão a resolver na adoção, e a spec não decide
sozinha qual dos dois sentidos fica.

### 6.2 Instruções

A instrução é uma large-community no formato `61785:<código>:<alvo>`, e é o que diz o que
fazer com a rota.

| Código | Significado | Exemplo |
|---|---|---|
| 4 / 6 | proveniência v4 / v6 (de quem eu recebi) | `61785:4:14840`, `61785:6:1010` |
| 666 | não anunciar / blackhole para este alvo | `61785:666:14840`, `61785:666:901` |
| 100 | cliente marcado (mitigação) | `61785:100:267702` |
| 3 | marca ERTEL | `61785:3:14840`, `61785:3:53065` |
| 6662 | blackhole (segunda geração) | `61785:6662:14840` |
| 1 / 2 / 3 | prepend 1, 2 ou 3 no virtual system | `61785:1:901` |
| 11 / 22 / 33 | prepend 1, 2 ou 3 na borda | `61785:11:14840` |

Os códigos de prepend diferem por alvo (`11/22/33` na borda, `1/2/3` no VS) porque a
posição onde o prepend é aplicado muda. O plano guarda **nível** (1, 2, 3) e o render
resolve o código pela posição do alvo, o que elimina a chance de trocar os dois.

O alvo do código pode ser um ASN (`14840`), um papel (`1010`) ou um alvo nomeado
(`901` para o GGC, `902` para o Netflix em v4, `911` e `912` em v6, `53062` para o ALT).

### 6.3 Alvos

Os alvos desta leitura, com o código e o portão que cada um usa:

| Alvo | Papel | Código v4 / v6 | Portão | Estado |
|---|---|---|---|---|
| Br.Digital (AS14840) | trânsito | 14840 | `RouteExportCheck` | 2 sessões Established |
| ALT (AS53062) | trânsito | 53062 | `RouteExportCheck` | 2 sessões Established |
| IX-CG (AS26162) | ix | 26162 | `RouteExportCheck` | Established |
| VIAMS (AS61622) | trânsito | 61622 | `RouteExportCheck` | 3 sessões Established |
| GGC (`PNI Google`) | cdn | 901 / 911 | `RouteExportCheck` (VS) | Established |
| Netflix (`OCA Netflix`) | cdn | 902 / 912 | `RouteExportCheck` (VS) | 2 sessões Established |
| HOKINET (AS61587) | parceiro | 61587 | `RouteExportCheck` (VS) | Established |
| `PARCEIROS_CDN` | parceiro | — | `RouteExportCheck-PARCEIROS` | grupo |
| `MSD-CDN-v4` | cdn | 53062 | — | 2 sessões Established, papel migrou para trânsito |

O caso do `MSD-CDN-v4` fica registrado: o grupo mantém o nome antigo de CDN enquanto o
papel real é trânsito, e a sessão parada não está em uso.

## 7. Import e export: a forma híbrida

A decisão já tomada, e que a produção confirma: a regra é **híbrida**.

**No import, a regra é por papel do par.** Cada papel aplica a sua classe. O cliente recebe
`3001` e `3101`, o parceiro recebe `4001` e `4101`, e o trânsito não é classificado: ele
carrega a proveniência na large-community (`61785:4:<ASN>`).

O caso de produção mais claro é o `CUSTOMER-BGP-v4` (linha 4579), que aplica a classe do
parceiro (`com-EXPORT-CDN-v4`, que é `61785:4001`) para prefixo de até `/24` e a classe do
cliente (`com-EXPORT-UPSTREAM-v4`, que é `61785:3001`) para até `/23`. A decisão de para
onde a rota pode ir é tomada **na entrada**, e é isso que faz o export por community
funcionar.

**No export, a regra é por classe × papel do alvo.** O filtro de saída não olha prefixo:
pergunta se a rota carrega alguma classe que aquele papel aceita.

O `RouteExportCheck` do VS (linha 1708) é a prova de que a matriz é real:
`{61785:7002, 61785:7102, 65000:3001, 65000:4001, 65000:991}`. Comparado com o da borda
(4664), a diferença é o `65000:991`. Ou seja, a classe "só CDN" passa no portão do CDN e é
recusada no portão do upstream. A mesma classe com veredito diferente por papel é
exatamente a matriz que esta spec formaliza.

**Os produtos deixam de ser prefixo.** O `PolicyProfile.prefixes` (lista de prefixos em
JSON) dá lugar a um conjunto de classes. Os seis nomes semeados em `b1a71e5e129b`
(`default`, `default_internas`, `parcial`, `full`, `cdn`, `personalizado`) continuam os
mesmos, e a sessão continua apontando para um deles por `export_profile_id`.

## 8. A validação

A validação é a parte que dá valor imediato à adoção, porque ela lê os dois equipamentos e
compara **quem aplica** com **quem testa**. Toda classe aplicada por um filtro e não
testada por nenhum portão é um problema, e o inverso também.

Ela verifica:

1. **Quem aplica contra quem testa.** Classe aplicada e não testada, classe testada e não
   aplicada, instrução aplicada e não testada.
2. **Conformidade com a partição.** Valor fora da banda declarada, dígito de família
   incoerente com o `afi`, valor duplicado entre classes diferentes.
3. **Instrução órfã.** Código de large-community usado nos filtros sem linha no
   vocabulário, e código de alvo sem `community_targets`.
4. **Ordem da large-community.** O vocabulário diz `61785:<código>:<alvo>`; valores que só
   aparecem na ordem inversa são apontados.
5. **Colisão entre namespaces.** O mesmo 2 bytes com significados diferentes.
6. **Operador composto.** `apply community` sem `additive` numa regra de import, que apaga
   as communities que o par mandou.
7. **Alvo sem sessão.** `community_targets` cujo peer não está Established.
8. **Nome citado e não definido.** Filtro, lista ou prefix-list referenciado na
   configuração e sem definição.

### 8.1 Achados desta leitura

Estes são os achados reais, e cada um é uma linha esperada na saída da validação.

**O portão testa o que ninguém aplica, e o filtro aplica o que o portão não testa.**
O `CUSTOMER-BGP-v4` (4586, 4592) aplica `61785:3001` e `61785:4001`. Os dois portões da
borda (4664, 4676) testam `61785:7002`, `61785:7102`, `61785:7012` e `61785:7112` mais os
`65000:3001` e `65000:4001`. As classes novas não estão em nenhum dos dois. Na prática, se
o caminho XPL de cliente fosse vinculado hoje, o upstream recusaria toda rota de cliente em
silêncio. É o achado mais grave da leitura e a razão de a validação existir.

**A ordem da large-community está invertida entre o import e o export do mesmo alvo.** O
import do AS14840 aplica `61785:4:14840` (linha 4264 em diante, ordem `código:alvo`) e o
export testa `if not large-community matches-any {61785:14840:4}` (4735, 4768, ordem
`alvo:código`). Como o teste procura um valor que aquele filtro nunca aplicou, o ramo de
prepend cai no `else` e o prepend só acontece pelo valor que o VS aplica. As duas ordens
aparecem **na mesma linha** do VS, em `rm-CUSTOMER-AS268061-V4-IN` (1207):
`apply large-community 61785:14840:4 61785:666:14840 additive`. Não há leitura que salve os
dois, e é por isso que o plano fixa uma ordem só.

**`MEU-PREFIXOS` é citado e não existe.** `UPSTREAM-V4-IMPORT($asn)` (4686) faz
`if ip route-destination in MEU-PREFIXOS then refuse`, e o nome não tem definição em
nenhum dos dois arquivos. Uma prefix-list vazia nessa posição não recusa nada, então a
proteção de rejeitar as rotas próprias no import genérico de upstream não está de pé.

**As marcas de tamanho do cliente estão em cascata, e uma delas é do outro AFI.**
`BGP-IPV4-CUSTOMER` (4484) escreve três blocos `if/else` com `approve` em todos os ramos.
O `else` do bloco de `/22` aplica `65000:7101` e o `else` do bloco de `/23` aplica
`65000:7102` em rotas **v4**, que são valores v6. O portão v4 da borda testa `61785:7102`,
o que sugere que o teste foi escrito para casar com o defeito. A semântica exata do
`approve` dentro do XPL precisa de confirmação no equipamento antes de a fatia F2 mexer
nesse filtro.

**Classe aplicada e nunca testada.** `com-TRANSITO-FULL` (`65000:1010`) é aplicada por
`ASN6762-V4-IMPORT` (4478) e casada por um nó de policy clássica (3486), mas nenhum portão
a considera. `com-TROCA-v4` e `com-TROCA-v6` (`65000:992`, `65000:993`) estão definidas e
não aparecem em lugar nenhum.

**`apply community` sem `additive` apaga o que o par mandou.** O par mais claro está no VS:
o import de parceiro v4 aplica a classe com `additive` (1343,
`apply community 65000:4001 additive`) e o v6 equivalente aplica sem (1354,
`apply community 65000:4101`), na mesma regra e para o mesmo par. O mesmo acontece nas
seis linhas de import de cliente do VS (1143 a 1215) e em `rm-Preference_1000-in` (1588).
A classe entra, e as communities que o par mandou somem no caminho.

**O prefixo do Google é anunciado com community da própria Google no CDN errado.** Os
filtros de GGC e de Netflix são idênticos exceto por quatro coisas, e uma delas é o bloco
`100.64.0.0 10 le 24` que leva `15169:12000` (1727). Isso é parâmetro de alvo, e no plano
ele fica em `community_targets.parametros`.

## 9. A adoção

A adoção lê o plano da configuração **já coletada** e reaproveita o motor que existe. O
`automation/discovery.py` e o parser `config_vrp.py` já leem o `display
current-configuration`, propõem o que a SoT não conhece com veredito, pendências e
conflitos, e gravam numa transação só com auditoria. A adoção do plano é um leitor novo no
mesmo motor: em vez de propor peer, propõe classe, instrução, alvo e portão.

O fluxo:

1. Lê da coleta as classes (as `community-filter` nomeadas e os valores aplicados), as
   instruções (os valores de large-community), os alvos (os grupos de peer e as sessões) e
   os portões (os filtros `RouteExportCheck*` com o conjunto que cada um testa).
2. Extrai também **quem aplica** e **quem testa** cada classe, que é o insumo da validação.
3. Poda: só sessão em Established vira alvo proposto. O resto sai numa lista de
   "configurado e parado" para o operador decidir.
4. A revisão mostra as divergências lado a lado com a proposta.
5. A escrita é uma transação com auditoria, e nada vai ao equipamento.

A adoção não renomeia nada no roteador, não adota peer parado e não decide as colisões
sozinha. O `65000:7001` que é tamanho na borda e cliente no VS, e o `MEU-PREFIXOS`, saem
como divergência para o operador resolver, com a proposta de qual sentido fica.

### 9.1 O que se reaproveita

| Objeto existente | Como entra |
|---|---|
| `automation/discovery.py` + `parsers/huawei_vrp/config_vrp.py` | o leitor, a proposta, a revisão e a transação única |
| `communities` | vira o vocabulário, ganhando valor, código, banda e origem |
| `upstreams.tipo`, `entrada_local_preference`, `contingencia_prepend` | o papel do alvo e os parâmetros `$preference` e `$prepend` |
| `upstream_communities` | já é uma tabela de instrução por alvo; fica como está em F1 e unifica em F3 |
| `bgp_policy_profiles` | os seis produtos continuam, com o conteúdo trocado de prefixos por classes |
| `bgp_sessions.import_route_policy` / `export_route_policy` | a exceção ao §25.4 que deixa a sessão adotada manter o nome do equipamento |
| `bgp_prefix_authorizations.origem` | o padrão de `origem` + `origem_snapshot_id` que as tabelas novas seguem |

### 9.2 O que é novo

A linha do plano com o ASN principal, os alvos que não são upstream, com o nome do grupo de
peer e os códigos, e a matriz de portões. E, do lado do render, o ajuste do
`_autorizadas_clientes` (`render.py:467`), que hoje filtra por `kind != "operadora"` e por
isso vazaria um `kind='cdn'` novo para dentro do anúncio aos trânsitos. Esse ajuste entra
com a fatia F3.

## 10. O render

Esta fatia não muda o render. O que ele vai consumir, nas fatias seguintes:

1. **O portão por papel.** O `RouteExportCheck` deixa de ser um filtro fixo por equipamento
   e passa a ser derivado da matriz de `community_gates`.
2. **O corpo do export por alvo.** Os filtros `XPL-GGC-V4-EXPORT` (1720) e
   `XPL-NFLX-V4-EXPORT` (1774) são o mesmo esqueleto: recusa por blackhole, default com
   `med 0`, chamada ao portão, e três níveis de prepend. O que muda entre eles é o código
   do alvo, o tamanho máximo aceito (`/24` contra `/25`), o bloco de exceção e o nome. Vira
   template com parâmetros do alvo.
3. **O produto como conjunto de classes.** O `PolicyProfile.prefixes` sai.
4. **As instruções viram ramos.** Blackhole aplica next-hop e community, prepend aplica
   as-path, deny recusa.
5. **A classificação no import.** Cada papel aplica a sua classe, com a família.

## 11. O frontend

O operador precisa conseguir responder "qual community eu uso para isto" sem abrir o
roteador. A consulta entra nesta fatia, junto com a adoção, porque o plano passa a existir
como dado e a leitura é o que dá sentido a ele.

**Página nova, `Comunidades · Plano`** (grupo Roteamento, ao lado de `Communities`), com
quatro blocos:

1. **Cabeçalho.** ASN principal, os ASNs anunciados, a origem (de qual equipamento e qual
   coleta o plano veio) e a data da adoção.
2. **Classes e instruções.** Uma tabela com nome, valor v4, valor v6, banda, e duas
   colunas de uso: **quem aplica** e **quem testa**, cada uma com a contagem e um link para
   os filtros que fazem aquilo. Uma classe aplicada e não testada leva um selo visível, e o
   inverso também. É a mesma informação da validação, apresentada onde ela é consultada.
3. **A matriz classe × papel.** Linha por classe, coluna por papel (`upstream`, `cdn`,
   `parceiro`, `ix`), e a célula diz anunciada, recusada ou não mencionada. O rodapé da
   matriz lista os portões de onde ela foi derivada.
4. **Alvos.** Nome do grupo de peer, papel, ASN, código v4 e v6, portão e estado da sessão
   no equipamento.

**Painel de divergências** na mesma página: os achados da seção 8.1, cada um com o valor, o
filtro, a linha no equipamento e a ação sugerida.

A página de `Communities` que já existe ganha as colunas de valor e de banda, porque a
partir desta frente ela é a tabela do vocabulário. O padrão de edição segue o das outras
páginas de catálogo (update por PATCH e por CLI, criação pela adoção).

Editar o plano pela web fica **fora** desta fatia, e a razão é que em F1 o plano é adotado e
não autoral. Editar à mão criaria uma segunda fonte para o mesmo dado sem que nada o
consumisse. A edição entra em F2, quando o import passa a ser gerado a partir dele e mexer
no plano tem consequência observável.

Nas páginas de objeto, a informação do plano aparece nas fatias seguintes: o detalhe da
sessão mostra a classe aplicada e o portão que a usa em F2, e o produto mostra o conjunto
de classes em F3.

## 12. Fatias

Cada fatia se sustenta sozinha e tem valor observável.

| Fatia | Entrega | O render |
|---|---|---|
| **F1** (esta) | o plano como dado, a validação, a adoção e a página de consulta | não muda |
| **F2** | o import classifica por papel, com a edição do plano liberada | blocos de import |
| **F3** | os produtos e o export por classe, a unificação das tabelas de instrução e o ajuste do `_autorizadas_clientes` | filtros de export, sem a prefix-list por ASN |
| **F4** | a saída XPL a partir do plano, incluindo os filtros por alvo | os filtros por alvo |

## 13. Testes

- **Partição:** valores conformes e não conformes, com o dígito de família trocado, e a
  exceção do `1010`, do `666`, do `992` e do `993`.
- **Validação:** uma fixture com os achados da seção 8.1 e a checagem de que cada um sai na
  saída, mais o caso limpo. A fixture é derivada dos dois arquivos reais, sem segredo.
- **Adoção:** idempotência (adotar duas vezes não duplica), a transação única (uma recusa
  desfaz tudo), e a poda de sessão não Established.
- **Parser:** os trechos das duas configurações, incluindo a linha 1207 do VS com as duas
  ordens de large-community, e o `apply community` sem `additive`.
- **API:** os endpoints da consulta e o `POST` da adoção, com os mesmos códigos de erro da
  adoção de peer (404 quando a proposta já não existe, 409 de unicidade, 422 de campo).
- **Web:** a matriz, o selo de classe aplicada e não testada, e o painel de divergências.

## 14. Dívidas e decisões abertas

1. **A semântica do `approve` no XPL** precisa de confirmação no equipamento antes de a F2
   mexer no `BGP-IPV4-CUSTOMER`. Se o `approve` encerra o filtro, só a marca do primeiro
   ramo que casa fica aplicada, e a leitura atual do filtro muda.
2. **A colisão do `65000:7001`** (tamanho na borda contra cliente no VS) é decisão do
   operador. A spec propõe que o VS migre para o vocabulário do plano e a borda mantenha o
   sentido de tamanho, mas não decide.
3. **O `MEU-PREFIXOS`** precisa de definição ou de remoção da referência. É mudança de
   equipamento e vai por change request.
4. **Os valores fora da partição** (`61785:53062`, `61785:8167`, `65000:0:262611`,
   `26162:0:271253`) ficam registrados como exceção até a adoção propor o destino de cada
   um.
5. **A ordem canônica da large-community** é `61785:<código>:<alvo>`. A migração dos
   valores invertidos é change request, e a validação aponta cada um.
6. **`com-TROCA-v4/v6`** estão definidas e sem uso. A adoção as lista como candidatas a
   desativação, e desativar é decisão do operador.
