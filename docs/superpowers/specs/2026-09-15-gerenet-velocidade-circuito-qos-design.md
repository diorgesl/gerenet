# Design — Velocidade do circuito, descrição da subinterface e QoS (`qos car`)

> Entrega a velocidade contratada como dado do circuito, passa a `description`
> da subinterface a carregá-la, e emite o limitador de taxa (`qos car`) que a
> operação já configura à mão. Inclui fazer os circuitos **já provisionados**
> convergirem sem remoção e reprovisionamento.
> Documentos-fonte: spec §6.2 (circuitos), §8 (nomenclatura), §10 (descoberta),
> §12 (fluxo de mudança), §21 (testes); design da descoberta/adoção
> (2026-09-14 e parte 2); `docs/runbook-validacao-ne8000.md`.

## 1. Objetivo e escopo

Hoje o circuito tem `bandwidth`, texto livre ("1G", "10 Gbps"), que serve de
nota contratual. Não há valor numérico, então o QoS da subinterface é digitado
à mão no equipamento, e a `description` da subinterface é `None` no render: o
template tem o slot e nada o preenche.

Entregas:

1. **`circuits.velocidade_mbps`** — inteiro, em Mbps, a fonte da verdade da
   taxa contratada.
2. **Descrição da subinterface** — `description <CÓDIGO> <NOME DA ORG> [<VEL>]`,
   derivada do circuito.
3. **`qos car`** — limitador de taxa nas duas direções, derivado da velocidade.
4. **Atualizar subinterface existente** — o plano passa a aplicar o bloco numa
   subinterface que já existe mas está sem descrição/QoS.
5. **Descoberta e adoção** — a descrição passa a ser linha gerenciada; a
   revisão da adoção ganha a velocidade, sugerida a partir do equipamento.

Fora de escopo: QoS com classes, marcação ou perfil por classe (só o `car`
simples); `cbs` explícito (o VRP completa); o prefixo `Cust:`, que existia para
o parse do Observium e sai junto com ele; `bandwidth` continua texto livre.

## 2. Contexto: o que o equipamento faz hoje (capturado em 2026-09-15)

Configuração real de uma subinterface de downstream num NE8000, VRP8
(`V800R024C00SPC500`):

```
interface Eth-Trunk127.626
 vlan-type dot1q 626
 description Cust: Rodrigo NETMAC
 ipv6 enable
 ip address 100.110.0.13 255.255.255.252
 ip address 172.16.100.157 255.255.255.252 sub
 ipv6 address 2804:194C:1000::155:157:1/126
 statistic enable
 qos car cir 1024000 cbs 18700000 green pass red discard inbound
 qos car cir 1024000 cbs 18700000 green pass red discard outbound
#
```

O que a captura fixa para o desenho:

- **`cir` é kbps.** `1024000` é 1 Gbps na convenção da operação, ou seja
  **1 Gbps = 1024 Mbps** — daí `velocidade_mbps × 1000`.
- **A direção vem por último**, e o VRP escreve a palavra completa
  (`inbound`/`outbound`). Emitir `in`/`out` faria a comparação SoT × coletado
  acusar divergência em toda subinterface, porque o running-config traz a
  forma longa.
- **`cbs`, `green pass` e `red discard` saem do render.** A operação emite a
  forma curta (`qos car cir <cir> inbound`) e o VRP completa o resto.
- **`statistic enable`** fecha o bloco, e o template já o emite.
- A `description` real (`Cust: <nome>`) é ASCII e é o que o Observium parseava
  para classificar a interface. Com a saída dele, o prefixo não tem mais razão
  de existir.

## 3. O campo `velocidade_mbps`

Coluna nova em `circuits`: `velocidade_mbps`, `Integer`, nullable.

- Unidade **Mbps**, inteiro. `1024` = 1 Gbps, pela convenção do §2.
- Nula significa "não sei a velocidade", e nula é o estado de todo circuito
  que já existe. Nula não é zero.

O `cir` do render sai como `velocidade_mbps × 1000` kbps, então `1024` produz
`cir 1024000`, idêntico ao que o equipamento já tem.

Validação: `> 0` e no máximo `100000` (100 Gbps). Um valor fora disso é erro de
digitação, não uma taxa.

`bandwidth` fica como está. São campos com papéis distintos: um é a nota que o
humano lê, o outro é o número que a máquina usa.

## 4. A descrição da subinterface

Formato:

```
<CÓDIGO> <NOME DA ORGANIZAÇÃO> [<VELOCIDADE>]
```

Exemplos, com o código `CIRC-626` e a organização `NETMAC`:

| Velocidade | Linha |
|---|---|
| 1024 | `description CIRC-626 NETMAC [1G]` |
| 100 | `description CIRC-500 ACME TELECOMUNICACOES [100M]` |
| nula | `description CIRC-500 ACME TELECOMUNICACOES` |

Regras:

- **Nome da organização**: maiúsculas, acentos removidos (dobra ASCII), espaços
  preservados. A dobra existe porque a convenção observada no equipamento é
  ASCII e o VRP não tem tratamento validado para não-ASCII em `description`; um
  acento que chegasse torto viraria divergência permanente contra a coleta.
- **Velocidade**: múltiplo de 1024 vira `[<n>G]`, qualquer outro valor vira
  `[<n>M]`. `1024` → `[1G]`, `100` → `[100M]`, `3000` → `[3000M]`.
- **Orçamento de 80 caracteres**, adotado nesta frente. Quem cede é o nome da
  organização, cortado seco; com código de até 64 e cauda de até 8, código e
  velocidade sempre cabem (64 + 1 + 8 = 73). O limite real do `description`
  nesta versão do VRP entra no checklist do runbook, e se for menor que 80 o
  orçamento desce junto.
- **Nome cortado até não sobrar nada**: se o orçamento do nome for menor que
  um caractere, a linha é `<CÓDIGO> [<VELOCIDADE>]`, sem espaço dobrado. Pelo
  teto do código isso não acontece na prática, mas o helper não pode produzir
  `CIRC-01  [1G]`.
- **Sem velocidade**, a linha sai sem os colchetes: a ausência do dado é
  visível, e não vira `[?]` nem `[0]`.
- **Sem organização** (não acontece: `organization_id` é NOT NULL) a descrição
  não é emitida.

Nasce em `naming.py`, junto do `subinterface()`, como função pura
`descricao_subinterface(code, nome_organizacao, velocidade_mbps)`: entradas
fixas, sem banco, e é onde o corte e a dobra são testados sozinhos.

Vale para todo circuito com subinterface no render, downstream e upstream. O
nome da organização é o que identifica a ponta nos dois casos.

## 5. O QoS

Depois do `statistic enable`, uma linha por direção, e só quando
`velocidade_mbps` não é nulo:

```
qos car cir <velocidade_mbps × 1000> inbound
qos car cir <velocidade_mbps × 1000> outbound
```

A ordem casa com a do equipamento (§2), o que mantém o bloco comparável linha
a linha com o que a coleta traz.

**A remoção não muda.** O plano de remoção já é `undo interface <nome>`
(`removal.py`), que leva descrição e QoS junto. Não existe `undo qos car` a
gerar, e por isso não existe forma nova de errar a remoção.

## 6. Atualizar subinterface que já existe

É a parte que mexe no motor de mudança, e não só no template. Sem ela, uma CR
num circuito já provisionado sairia "nada a aplicar" e o parque não converge.

**Por que hoje não converge.** O plano pula o bloco inteiro quando o nome da
subinterface aparece no `display interface brief` (`_ja_existe`, em
`changes.py`). O nome está lá, então o bloco sai do plano, e a descrição e o
QoS nunca chegam ao equipamento.

**O que muda, em três pontos:**

1. **Plano** (`changes.py`). O `_ja_existe` da subinterface deixa de olhar só o
   nome: passa a exigir que a descrição e as duas linhas de `qos car` do bloco
   constem do texto da configuração coletada. Faltando qualquer uma, o bloco
   entra no plano. O texto já está à mão: `config_backup` está em
   `snapshot.raw_files` e o `removal.texto_backup` já sabe lê-lo. Não há
   recurso de coleta novo.

2. **Execução** (`runner.py`, `_estado_do_bloco`). Hoje, nome e endereços
   batendo, o estado é `consta`, e `consta` vira "pula". Entra um estado
   **`atualizar`**, para "nome e endereços batem, mas falta descrição ou QoS".

3. **Re-diff** (`runner.py`, `_re_diff`). `atualizar` vai para `a_aplicar` e
   **não conta como evidência de plano velho**. O abort de "apenas parte do
   plano consta" continua olhando só os creates que constam. Sem esse cuidado,
   um plano com dois circuitos, um completo e um para atualizar, abortaria em
   falso — o completo seria `consta` e o outro `ausente`, os dois creates.

**O que vai ao equipamento é o bloco inteiro**, não só as linhas que faltam.
Reemitir `vlan-type dot1q vid`, `ip address`, `description`, `qos car` e
`statistic enable` com os valores desejados é idempotente no VRP, e mantém o
bloco como "o estado desejado deste pedaço", que é o que o operador aprova e a
auditoria registra. A alternativa (mandar só as linhas faltantes) evita
reescrever endereço, mas quebra o bloco em comandos parciais e complica o
pós-check, que hoje confere presença por bloco.

**O pós-check de provisionamento não confere o conteúdo.** O caminho de
provisionamento fecha pela comparação desejado × encontrado
(`reconciliar_device`), que não lê o texto da configuração: nome e endereços
presentes continuam bastando. Se o VRP recusar a `description` ou o `qos car`,
a CR fecha **`aplicado` sem item nenhum** — não há alarme.

A conferência de conteúdo existe no código (`subinterface.conteudo`, severidade
`atencao`, em `_verifica_aplicados`), mas só o caminho de **remoção** a chama, e
lá o bloco da subinterface é um `delete`, que resolve como "consta" antes da
conferência: hoje ela não acontece em mudança nenhuma.

A convergência não se perde: o `_ja_existe` da CR seguinte compara o texto
coletado, encontra a descrição ou o QoS fora do que o bloco pede e reemite o
bloco. Quem fecha o ciclo é o re-planejamento, um plano depois — o que falta no
meio é o alarme, não a convergência.

## 7. Descoberta e adoção

**A descrição passa a ser gerenciada.** `_NAO_GERENCIADAS_SUBINTERFACE`
(`discovery.py`) hoje é `("description ", "mtu ")` e existe porque o render não
emite nem uma nem outra. Passa a `("mtu ",)`: a `description` sai do grupo que
não gateia e entra na comparação. Uma descrição diferente no equipamento vira
diferença e exige `ciente` na adoção.

É o comportamento certo — a SoT passa a gerenciar a linha — mas muda a
operação num ponto visível: adotar um enlace cujo `description` fuja do formato
do §4 passa a pedir aceite explícito. O grupo "a SoT não gerencia" continua
existindo para o `mtu`.

**A revisão da adoção ganha a velocidade.** `AdocaoIn.velocidade_mbps`, opcional,
gravado no circuito que a adoção cria.

**O parser passa a ler o `qos car`.** `config_vrp.py` já lê o bloco da interface
e o `description`; passa a ler também `qos car cir <n>`, e a revisão sugere
`velocidade_mbps = cir / 1000`. É o mesmo espírito do resto da adoção: o
equipamento é lido, o operador corrige. Num enlace que já tem QoS, ninguém
digita a taxa à mão.

O divisor é inteiro: um `cir` que não seja múltiplo de 1000 é sinal de captura
estranha, e a sugestão fica vazia em vez de arredondar.

## 8. Superfícies

**API** — `velocidade_mbps` em `CircuitCreate`, `CircuitUpdate` e `CircuitOut`;
`AdocaoIn.velocidade_mbps`.

**CLI** — `gerenet circuits add --velocidade-mbps`, e o mesmo no `update`.

**Web** — campo "Velocidade (Mbps)" no cadastro e na edição de circuito (com o
texto de ajuda em `help.ts`), e na revisão da adoção. `types.ts` e `hooks.ts`
acompanham.

**Wiki** — `/wiki/circuitos` ganha a velocidade, o formato da descrição e o que
o QoS faz na subinterface.

**Migração** — Alembic, uma coluna nullable, com downgrade.

## 9. Testes

- **Unidade** — `descricao_subinterface`: corte no limite, `G` × `M`, dobra de
  acento, sem velocidade, nome curto e nome que não cabe.
- **Golden de template** — subinterface com e sem velocidade, e a ordem das
  linhas do bloco.
- **Idempotência** (§3.2) — a mesma entrada produz o mesmo texto, e um bloco
  já conforme não entra no plano.
- **Plano** — subinterface completa é pulada, subinterface sem descrição e sem
  QoS entra, subinterface só sem QoS entra.
- **Re-diff** — `atualizar` é aplicado; um plano com um bloco completo e outro
  para atualizar **não** aborta.
- **Descoberta** — descrição divergente deixa de ser "não gerenciado" e passa a
  exigir `ciente`; `mtu` continua fora do gate.
- **Parser** — `qos car cir` lido, e `cir` não múltiplo de 1000 não sugere.
- **Migração** — upgrade e downgrade.
- **Web** — Vitest no formulário e na revisão.

A fixture `ne8000_display_current_configuration.txt` é derivada dos templates do
projeto; as linhas novas do render entram nela, e as expectativas que dependem
do texto dela acompanham.

## 10. Riscos

**Reaplicar o bloco inteiro reescreve o endereço.** É idempotente no VRP com
valores iguais, mas é escrita a mais numa subinterface que já está de pé. A
validação num equipamento não crítico, antes de soltar no parque, é o que
fecha isso — e é o `docs/runbook-validacao-ne8000.md` que já existe.

**O primeiro provisionamento depois desta frente muda muitas linhas** em
subinterfaces que estavam conformes para os padrões antigos. O operador vê o
bloco inteiro no diff, e é o desejado.

**A descrição muda quando o nome da organização muda.** É derivada, então
renomear a organização reescreve a descrição de todas as subinterfaces dela no
próximo provisionamento. Fica registrado; não há cache nem histórico.

## 11. Dívidas registradas

- **QoS com classes e marcação.** Esta frente entrega o limitador de taxa
  simples. Fila por classe, marcação e perfil de QoS são frente própria, com o
  dado já no lugar.
- **`cbs` e `pir` fora da SoT.** O VRP completa o `cbs` e a operação não usa
  `pir` — quem quiser um `cbs` calculado precisa de campo novo. A consequência
  está na comparação: o `equivalencia_vrp` dobra a linha longa do equipamento na
  curta olhando só a taxa e a direção, então um CAR de duas taxas
  (`... cir 1024000 cbs ... pir 2000000 pbs ...`) também conta como conforme, e o
  `pir` fica invisível ao plano e à conferência de fidelidade. A dobra fica como
  está de propósito: sem ela a divergência apareceria e o bloco seria reemitido,
  devolvendo `cbs` e `pir` ao default do VRP num enlace vivo.
- **A velocidade apagada deixa o `qos car` no equipamento.** Um PATCH com
  `velocidade_mbps: null` limpa o campo e o render deixa de emitir a taxa. A
  `description` converge — sem o colchete ela difere da que está no equipamento e
  o bloco vira `atualizar` —, mas o limitador não: as linhas de `qos car` não
  estão entre as que o render emite, a `conteudo_conforme` só confere as que o
  bloco emite, e não existe caminho que mande remover a taxa. O circuito segue
  limitado na velocidade antiga enquanto a SoT diz que não há velocidade — o
  cliente tem o tráfego cortado por um valor que ninguém contratou mais. Tirar a
  velocidade de um circuito provisionado é caso de remoção e reprovisionamento do
  bloco (`undo interface` leva o limitador junto).
- **O bloco reemitido leva o `vlan-type` junto.** Quando a `description` ou o
  QoS divergem, o §6 reemite o bloco inteiro — inclusive o `vlan-type` da SoT.
  Uma subinterface cujo encapsulamento divirja do cadastro é reescrita com o da
  SoT, e essa divergência de encapsulamento não aparecia como diferença em
  superfície nenhuma antes disso.
- **Flake do Redis.** Seis testes de `tests/worker/` falham com o worker da
  stack varrendo o mesmo Redis DB 0. Não é desta frente; `GERENET_REDIS_URL`
  apontando para outro DB resolve, e foi assim que o baseline foi conferido.
