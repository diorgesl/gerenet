# Design — Fim da colisão de linha: mais de uma sessão BGP por equipamento

> A §14.1 era lida como "uma sessão ativa por equipamento, VRF/VS e família", e
> essa leitura derrubou em 2026-09-16 a adoção de dois enlaces de operadoras
> diferentes no mesmo NE8000. A regra da linha sai e a colisão passa a ser o
> **peer repetido na mesma VRF do equipamento**. Documentos-fonte: spec §6.3
> (sessão BGP), §14.1 (regras de banco), §10 (descoberta e reconciliação),
> §12.2 (pré-checks); designs da descoberta e adoção (2026-09-14, 2026-09-15) e
> da adoção de upstream e políticas importadas (2026-09-16).

## 1. Objetivo e escopo

Uma entrega: trocar a chave da colisão de linha. O que decide a colisão deixa de
ser "quantas sessões o equipamento carrega" e passa a ser o peer: outra sessão
ativa com o **mesmo endereço remoto, no mesmo equipamento e na mesma VRF**. A
função muda de nome, `_colidente_linha` para `_colidente_peer`, e os dois
chamadores ficam com a chave nova. O `_colidente_par` continua como está.

Fora de escopo:

- o escopo do `_colidente_par`, que continua global e com o par invertido
  incluído;
- a recusa de política com o mesmo nome no mesmo equipamento (§4.4 do design de
  2026-09-16), que tem modelo próprio e segue valendo;
- a reserva de VLAN e do par p2p do circuito, que não muda.

## 2. Contexto

### 2.1 O incidente

Conferência somente leitura no banco do servidor onde o sistema vai rodar, em
2026-09-16, com o alembic em `a3d1c7e5b9f2` (a migração da frente anterior está
aplicada).

| Objeto | Estado |
| --- | --- |
| `devices` id 1 | `NE8K TECMAIS`, ASN 61785 |
| `circuits` id 13 | `ADOC-269394-625`, VRF nula (pública), edge device 1 |
| organização 13 | MITAS INTERNET, `downstream`, ASN 269394 |
| organização 15 | BrDigital, `operadora`, ASN 14840 |
| `bgp_sessions` id 25 | ipv4, ativa, device 1, 100.110.0.1 ↔ 100.110.0.2 |
| `bgp_sessions` id 26 | ipv6, ativa, device 1, 2804:194c:1000::1100:0:1 ↔ 2804:194c:1000::1100:0:2 |

O usuário enviou uma adoção com `device_id` 1, subinterface `Eth-Trunk127.2670`,
código do circuito `ADOC-14840-2670`, organização 15, o upstream "20 Gbps"
(`transito`, `produto_import` full, papel principal) e as duas famílias. A
resposta foi 409:

```json
{"detail": "Já existe sessão ipv4 ativa no equipamento NE8K TECMAIS (VRF pública)."}
```

O mesmo teste com outra operadora deu o mesmo erro.

**Mecanismo.** `adotar_proposta` grava a adoção inteira numa transação e chama
`create_session` por família. A primeira chamada (ipv4, VRF pública, device 1)
encontrou a sessão 25, que está no mesmo equipamento, na mesma VRF e na mesma
família, com outro peer. A adoção não chegou a escrever nada: a transação
voltou inteira. A recusa é do equipamento, não da operadora, e é por isso que
as duas falharam igual.

### 2.2 A regra, em código

`_colidente_linha` (`domain/services/bgp_sessions.py:56`) lista as sessões
ativas do equipamento naquela família, junta o circuito de cada uma e devolve a
primeira cujo `circuit.vrf` é igual ao VRF informado. Não olha o peer. Os dois
chamadores passam o device do payload e o VRF do circuito: `create_session:184`
e `update_session:324`. A mensagem usa `_vrf_texto` (`:52`), que troca VRF nulo
por `pública`.

`_colidente_par` (`:77`) compara o conjunto de dois endereços de cada sessão
ativa com o da sessão em causa, sem filtro de equipamento nem de VRF, e o par
invertido também colide. Mensagem: `Já existe sessão ativa entre {local} e
{remote}.`

### 2.3 O parecer

O número de sessões por equipamento, VRF ou família não é propriedade que a SoT
possa afirmar. Clientes e upstreams têm mais de uma sessão BGP: um cliente do
parque tem três, cada uma por uma rota e por um roteador, e o incidente acima é
a segunda sessão da mesma operadora no mesmo roteador.

O que não pode existir é o **peer repetido na mesma VRF do equipamento**. No VRP
o peer é o endereço do vizinho dentro da instância, e a instância é a VRF: dois
blocos `peer <ip>` no mesmo contexto viram um peer só, configurado pelo bloco
que chegar por último. A família não entra na chave porque o endereço já a
carrega, um IPv4 não é configurado na família IPv6.

A §14.1 é lida assim desde 2026-09-02, quando a regra entrou. A leitura estava
errada, e o texto da spec passa a dizer a regra certa.

## 3. A decisão

### 3.1 O que muda

- `_colidente_linha` vira `_colidente_peer`. A consulta continua a mesma (as
  sessões ativas do equipamento, com o circuito para chegar ao VRF do payload),
  e a chave da comparação passa do "qualquer sessão na linha" para o endereço
  remoto.
- `_vrf_texto` fica, porque a mensagem continua dizendo a VRF.
- A mensagem de 409 passa a ser `Já existe sessão ativa no equipamento {device}
  para o peer {endereço remoto} (VRF {vrf}).`
- `_colidente_par` fica como está.

Nenhuma migração: a regra sempre foi de serviço, e `bgp_sessions` não tem
constraint de unicidade. Nenhuma linha de dado muda de estado, e a adoção que
travou passa a entrar.

### 3.2 A comparação do endereço

O `remote_address` é comparado pela forma canônica, com
`int(ipaddress.ip_address(...))`, do mesmo jeito que o `_colidente_par` já faz.
É o que faz `2001:db8::1` e `2001:0db8::1` colidirem, e a SoT grava o texto como
veio (dívida registrada desde a descoberta).

### 3.3 O escopo da chave

Equipamento e VRF, nessa ordem. Duas instâncias de VRF diferentes no mesmo
roteador são contextos diferentes para o VRP, e o mesmo endereço remoto pode
existir nas duas. O mesmo endereço em outro equipamento também convive: são
instâncias distintas, e o par reservado por circuito impede que o caso venha do
alocador.

O `_colidente_par` continua mais largo de propósito: sessão duplicada é o mesmo
par local/remoto ativo em qualquer lugar, com o par invertido colidindo.

### 3.4 O que já trabalha por peer

Nada mais no código contava sessões por linha:

- a reconciliação casa sessão da SoT e peer encontrado por `(afi,
  remote_address)`, e a lista de órfãos é um conjunto de pares por equipamento
  (`automation/reconcile.py`);
- o pré-check de upstream percorre as sessões do próprio upstream naquele
  equipamento e confere o ASN coletado de cada peer (`valida_pre_upstream`,
  `automation/upstream.py`);
- o render emite um bloco por sessão, com o peer como identidade.

## 4. Superfícies

| Superfície | O que muda |
| --- | --- |
| `domain/services/bgp_sessions.py` | `_colidente_linha` vira `_colidente_peer` (chave no endereço remoto); as duas chamadas e a mensagem; `_vrf_texto` e `_colidente_par` ficam |
| `tests/domain/test_bgp_sessions_service.py` | §5 |
| `ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md` | linha 625 do §14.1 com a redação nova |
| `docs/wiki/roteamento.md` | o bullet de duplicidade da sessão |
| `web/src/help.ts` | o texto da chave `bgp.afi`, que fala em não duplicar device+VRF+família |
| `CLAUDE.md` | a nota do seed dos e2e, que justifica o equipamento próprio com a regra antiga |

A redação nova da §14.1, linha 625, e os três textos que acompanham a regra.

```markdown
- uma sessão BGP não poderá ser duplicada: o mesmo peer (endereço remoto) não
  pode estar ativo duas vezes na mesma VRF de um equipamento, nem o par
  local/remoto ativo em dois lugares; mais de uma sessão no mesmo equipamento e
  família é legítima, o que as distingue é o peer;
```

`docs/wiki/roteamento.md`, substituindo o bullet `Uma sessão por equipamento +
família + VRF`:

```markdown
- **O peer não se repete na mesma VRF do equipamento** (a duplicidade é barrada:
  "Já existe sessão ativa no equipamento X para o peer Y (VRF …)"), e o par
  local/remoto também não pode estar ativo em dois lugares. Mais de uma sessão
  no mesmo equipamento e família é legítima: cada enlace chega por um peer
  próprio.
```

`web/src/help.ts`, a chave `bgp.afi`:

```ts
"bgp.afi": "Família da sessão: ipv4 ou ipv6, uma sessão por família. Várias sessões podem conviver no mesmo equipamento e VRF; o que não se repete é o peer (o endereço remoto) na mesma VRF.",
```

`CLAUDE.md`, o parêntese da nota do seed dos e2e:

```markdown
  equipamento próprio (`ne8000-disco-01`, só do seed: o `ne8000-01` tem sessão
  ativa e a rodada desativa as sessões do equipamento da descoberta), e desativa
  as sessões desse equipamento antes de cada rodada.
```

## 5. Testes

Na `tests/domain/test_bgp_sessions_service.py`:

- entra `test_varias_sessoes_no_mesmo_device_vrf_familia`: dois circuitos
  distintos no mesmo equipamento, mesma VRF e mesma família, com peers
  diferentes, criam as duas sessões. É o caso do incidente e o teste de
  regressão da frente;
- `test_duplicidade_mesmo_device_vrf_afi` (`:177`) passa a pinar o peer
  repetido: outro circuito no mesmo equipamento e VRF com o mesmo endereço
  remoto é 409, e o par diferente convive;
- `test_duplicidade_mensagem_vrf_publica` (`:199`) continua, com o gatilho novo:
  o mesmo peer em outro circuito da VRF pública;
- entra `test_mesmo_peer_em_vrf_diferente_convive`: mesmo endereço remoto, mesmo
  equipamento, VRF diferente, as duas sessões criam;
- `test_update_colide_com_outra_sessao` (`:416`) muda de gatilho: a colisão vem
  de atualizar o endereço remoto da sessão B para o da sessão A;
- `test_update_mantem_a_propria_linha_fora_da_colisao` (`:434`) continua
  valendo, agora para o `ignorar_id` do peer, e perde a menção à linha no nome;
- `test_duplicidade_do_par_e_global_inclusive_invertido` (`:208`),
  `test_vrfs_diferentes_convivem_no_mesmo_device` (`:187`) e
  `test_afi_diferente_nao_colide` (`:225`) ficam como estão.

Verificação da frente: `uv run pytest -q`, `uv run ruff check src tests` e
`cd web && npm run build && npm run test`. Depois da correção, a adoção do
enlace BrDigital no NE8K TECMAIS pode ser repetida: as sessões 25 e 26 ficam
intactas e as duas famílias do enlace novo entram.

## 6. Riscos

- A leitura antiga pode ter virado dado. Se algum operador cadastrou a segunda
  sessão de um enlace em outro circuito ou com outro peer só para contornar o
  409, a SoT guarda uma intenção que não é a da rede. A conferência é a
  reconciliação do equipamento, que compara peer a peer e mostra a sobra.
- O nome de política repetido é a próxima barreira. O §4.4 do design de
  2026-09-16 recusa dois peers do mesmo equipamento sob o mesmo nome de
  route-policy, e o índice é por equipamento, não por família. Multi-sessão por
  equipamento aumenta a chance de o caso aparecer numa adoção: quando a
  operadora reusa o nome em dois enlaces, a revisão acusa
  `politica_compartilhada`. As saídas são adotar sem importar o nome, que faz o
  render emitir o nome do §25.4, ou cadastrar a política compartilhada à mão,
  que ainda não tem modelo.

## 7. Dívidas registradas

- A política compartilhada continua sem modelo (§6). A adoção recusa e o render
  emite os dois blocos sob o mesmo nome quando o caso chega por outro caminho.
- A comparação do peer é por endereço remoto, sem olhar o `asn_remote`. Duas
  sessões para o mesmo vizinho com ASNs diferentes na mesma VRF colidem (é o
  efeito desejado: o VRP também as trataria como um peer só), mas a mensagem não
  diz qual ASN está lá.
