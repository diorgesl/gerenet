# Design — Fase 4 (parte 3): VSI multiponto no gerenet

> Fecha o último item da Fase 4 do gerenet: provisionamento de **VSI multiponto**
> (§9.3), com ACs por PE, render por equipamento, change request de escopo `vsi`
> com N steps, pré-check de LDP, pós-check por pseudowire e por AC, e rollback e
> reconciliação do escopo. Documentos-fonte: spec §9.1, §9.3, §9.4, §10, §12–13,
> §21, §23–24; designs da Fase 4 (2026-09-07) e das pendências do L2VC
> (2026-09-13); `docs/runbook-validacao-switch-mpls.md`.

## 1. Objetivo e escopo

Provisionar VSI multiponto de ponta a ponta, do cadastro à validação, em uma
mudança lógica só. Os itens da Fase 4 que ficaram para trás (§22) são
exatamente estes: provisionamento VSI, múltiplos endpoints e validação de LDP,
pseudowire, MTU e MAC.

Entregas:

1. **Modelo dos ACs** — cada PE participante ganha uma ponta com VLAN reservada
   por equipamento, e a interface do AC é derivada do VID.
2. **Render e plano por PE** — bloco do VSI e bloco do AC, com N steps na CR.
3. **Change request de escopo `vsi`** — criação, rollback e reconciliação, com
   `parcial` cobrindo "uma ponta falhou" do §9.3.
4. **Pré-check** — par LDP de cada peer UP e AC sem binding conflitante.
5. **Pós-check** — estado do VSI, de cada pseudowire e de cada AC.
6. **Web e CLI** — detalhe do VSI com ACs e divergência, e o "Solicitar mudança".

Fora de escopo: checagem de aprendizado de MAC (fica registrada na §12, exige
comando de coleta novo); `tnl-policy`, `statistic enable` e os comandos de MAC
no render; SR-MPLS (§22, Fase 7).

## 2. Contexto (verificado em 2026-09-13)

**Captura real do equipamento.** O switch `sw-6730-aggr-tecmais-01` foi
consultado em modo leitura e a configuração de VSI e do AC é esta:

```
vsi IntechCDN static
 pwsignal ldp
  vsi-id 2827
  flow-label both
  peer 100.127.90.255
 tnl-policy LOAD_BALANCE_CDN
#
interface Vlanif2827
 description Intech-VSI-CDN
 l2 binding vsi IntechCDN
 statistic enable both
#
```

O que a captura fixa para o desenho:

- o cabeçalho é `vsi <nome> static`, e `vsi-id`, `flow-label` e `peer` ficam
  **dentro de `pwsignal ldp`**, com uma linha `peer` por membro (é o ponto de
  extensão multiponto);
- `mtu` e `tnl-policy` são do VSI, irmãos do `pwsignal`;
- `flow-label both` é opcional por VSI (dois dos nove VSIs do switch não têm);
- o AC é uma `Vlanif` com `l2 binding vsi <nome>` e uma `description`;
- na operação o VID do AC coincide com o `vsi-id` (Vlanif2827 com `vsi-id`
  2827, e o mesmo nos demais);
- dos dez blocos `vsi` do switch, nove têm peer e cada um deles tem **um** peer
  só (o décimo é o bloco quebrado `vsi VLAN653_INTECH]`, sem `pwsignal` e sem
  ID). A forma aceita N linhas `peer` sem mudança.

**O que já existe no código.** `vsi_services`, `vsi_members` e
`service_endpoints` (com `kind` incluindo `vsi` e a FK `vsi_id`) estão
materializados desde a Fase 4, junto com `naming.vsi_nome`,
`proximo_vsi_id`, `reservar_vlan_ac` (VLAN de AC com escopo por device) e a
coleta de `display vsi verbose`. O enum `CHANGE_ESCOPO` já lista `vsi`.

**O que falta.**

- `create_vsi` recebe apenas `members` (lista de devices) e **não cria AC
  nenhum**: a tabela existe, mas ninguém escreve nela para VSI.
- `change_requests` **não tem a FK `vsi_id`** (tem `circuit_id`, `l2vc_id` e
  `upstream_id`): precisa de migração.
- O validador de `ChangeRequestCreate` bloqueia o escopo de propósito
  ("Escopo 'vsi' não está disponível neste ciclo").
- `vsi` está nos dois dicionários de indisponível do serviço de CR, então
  rollback e reconciliação estão barrados.
- O `vsi.template` lê só o nível do VSI (`VSI Name`, `VSI State`, `VSI ID`); os
  blocos aninhados de peer e de AC que a fixture real traz são descartados.
- `valida_pre_checks_vsi` e `valida_pos_vsi` não existem.

## 3. Modelo e alocação

**`vsi_services`** ganha:

- `flow_label: bool` (default `false`), renderizado só quando marcado e quando o
  equipamento declarar a capability `mpls_flow_label` em `devices.capabilities`,
  a mesma regra do L2VC;
- `description: str | None`, usada no render quando preenchida.

**ACs como `service_endpoints`.** Uma linha por PE participante, com
`kind='vsi'`, `vsi_id`, `device_id`, `vlan_id` (linha `mpls_ac` da tabela
`vlans`, escopo por device, via `reservar_vlan_ac`), `mtu` opcional e
`encapsulation='dot1q'`. A interface **não é campo livre**: é derivada do VID
como `Vlanif<vid>`, o que elimina a chance de o cadastro apontar para uma
Vlanif que não é a do serviço.

**`VsiCreate`** troca `members: list[int]` por `endpoints: list[VsiEndpointIn]`,
com `VsiEndpointIn = {device_id, vid: int | None, mtu: int | None}`. O VID
omitido assume o `vsi_id`, que é a convenção da operação; um VID já ocupado no
mesmo equipamento levanta `ConflictError` na reserva, como no L2VC.

**Membros.** O cadastro aceita um endpoint (consulta, estado, preparação de
migração), mas a **criação da CR de provisionamento** exige pelo menos dois, já
que um VSI de um membro só não tem peer para configurar. A regra vive no serviço
(`_create_vsi`), como as demais validações de CR, e não no schema de cadastro.

**Migração Alembic** (uma só): `change_requests.vsi_id` (FK `vsi_services`,
nullable, espelhando `l2vc_id`), `vsi_services.flow_label` e
`vsi_services.description`.

**Regras de unicidade** que a operação mantém: `vsi_id` e `vrp_name` únicos por
domínio (já existem no banco) e VID de AC único por equipamento (índice parcial
de `vlans`, já existe). Um endpoint por equipamento por VSI é validado no
serviço, na criação e na atualização, sem constraint nova no banco.

## 4. Render e plano, por PE

**Bloco do VSI**, uma vez em cada PE participante do serviço:

```
vsi {{ vrp_name }} static
{% if description %} description {{ description }}
{% endif %} pwsignal ldp
  vsi-id {{ vsi_id }}
{% if flow_label %}  flow-label both
{% endif %}{% for peer in peers %}  peer {{ peer }}
{% endfor %}{% if mtu %} mtu {{ mtu }}
{% endif %}
```

`peers` é a lista de loopbacks LDP dos outros membros, derivada de
`mpls_domain_members` (§9.1). Um VSI de dois PEs gera uma linha `peer` em cada
lado; um de quatro gera três.

**Bloco do AC**, por ponta:

```
vlan {{ vid }}
interface Vlanif{{ vid }}
{% if description %} description {{ description }}
{% endif %} l2 binding vsi {{ vrp_name }}
```

**Blocos fora do render, de propósito.** `tnl-policy`, `statistic enable` e os
comandos de MAC learning e limite de MAC ficam de fora: os VSIs medidos usam o
default do VRP, os campos correspondentes seguem no modelo para consulta, e
cada comando emitido a mais é superfície de erro sem contrapartida.

**Plano.** `plan_provision_vsi` e `plan_remocao_vsi` seguem o L2VC: render por
device, diff bloco × snapshot da última coleta (`bloco presente ⇒ skip`, sem
snapshot confiável ⇒ aviso), um `PlanoDevice` por PE. A identidade do bloco do
VSI é o nome VRP; a do AC é a `Vlanif<vid>`, e não o par (Vlanif, `l2 binding
vsi <nome>`): o snapshot não carrega o nome do VSI ligado ao AC (o `display`
não o mostra), então o par não é avaliável. Daí `estado_bloco_vsi` nunca
devolver `"conflito"` e um binding de outro serviço na mesma Vlanif aparecer
como `consta` — quem barra esse caso é o pré-check (§6).

**Remoção** (decisão do usuário em 2026-09-13): por PE, `undo l2 binding vsi
<nome>` no contexto da Vlanif e depois `undo vsi <nome>`, nessa ordem, porque o
VRP recusa remover um VSI que ainda tem AC ligado. A `Vlanif` e a `vlan` ficam
no equipamento, exatamente como o L2VC nunca dá `undo interface`. A sobra é
visível na divergência e o re-provisionamento a reaproveita (o create é
idempotente).

## 5. Change request de escopo `vsi`

- `change_requests.vsi_id` (migração da §3) e o ramo de validação no
  `ChangeRequestCreate`, substituindo o bloqueio atual.
- `_create_vsi` no serviço de CR, espelho do `_create_l2vc`: exige serviço e
  domínio ativos (o guard de estado extraído para o L2VC é generalizado para os
  dois escopos MPLS), exige dois endpoints ou mais, gera os N steps com o plano
  e nasce em `rascunho`.
- `_replaneja` ganha o ramo `vsi`, com `plan_provision_vsi`/`plan_remocao_vsi`.
- `"vsi"` sai de `_RECONCILIA_INDISPONIVEL` e de `_ROLLBACK_INDISPONIVEL`. O
  rollback do VSI deriva da **coleta atual**, como o do L2VC e pelo mesmo
  motivo: o baseline pré-mudança não contém um VSI novo. Ponta sem bloco não
  gera step; sem nenhum bloco, vale o `PlanoRollbackVazio`.
- O gate de recursos do runner ganha a tupla do escopo `vsi`:
  `("interfaces", "vsi", "config_backup")`.
- `parcial` da CR significa o que o §9.3 pede: uma ponta falhou e o serviço está
  parcialmente provisionado, exigindo reconciliação.

## 6. Pré-check

`valida_pre_checks_vsi(session, service, device, recursos)`, chamado pelo runner
quando o escopo é `vsi`:

- o recurso `mpls_ldp_peer` precisa estar na coleta, e o par LDP de **cada**
  peer do serviço (loopback do outro PE) precisa estar listado com `estado ==
  "up"`. Estado `None` continua sendo "desconhecido" e bloqueia, como no L2VC;
- a Vlanif da ponta não pode ter `l2 binding vsi` de outro serviço: se o
  encontrado mostrar binding para nome VRP diferente, o step falha antes de
  tocar o equipamento;
- a simetria do serviço é conferida na SoT e revalidada na execução, como no
  L2VC: todo membro do serviço tem a sua ponta, e são pelo menos dois. O MTU
  não entra na conferência: no VSI ele é campo do serviço (um só, não um por
  ponta) e o AC não o renderiza, então não há o par de MTUs do L2VC para
  comparar — quem compara com o coletado é o pós-check.

## 7. Coleta, parser e pós-check

**Parser.** O `vsi.template` passa a percorrer os três níveis do
`display vsi verbose`, com o nome e o ID do VSI preenchidos ao longo do bloco:

- nível do VSI: `VSI Name`, `VSI State`, `VSI ID` e `MTU`;
- nível do peer: `Peer Router ID` (o destino do pseudowire) e `Session`, que é
  o estado do pseudowire que interessa;
- nível do AC: `Interface Name` e `State`.

A seção `**PW Information` (`Peer Ip Address` + `PW State`) **não é parseada**:
medida na fixture real, ela aparece em apenas três dos nove VSIs e, quando
aparece, repete o estado que o `Session` do bloco de peer já traz. Um campo a
mais que às vezes falta seria ruído na divergência.

O merge agrupa as linhas pelo nome do VSI, que é o único valor preenchido ao
longo do bloco. O grupo sem `VSI ID` próprio é descartado, o que mantém o
comportamento atual com o bloco quebrado da fixture (nome sem ID) e fecha o caso
de um bloco truncado que trouxesse AC: sem ID, o AC não é atribuído ao VSI
anterior.

O merge devolve por VSI `{name, vsi_id, estado, mtu, peers: [{peer, estado}],
acs: [{interface, estado}]}`, com `mtu` inteiro ou `None` e as listas vazias
quando o bloco não as trouxer. O VSI órfão da fixture real (nome quebrado, sem
ID) continua sendo descartado, e o teste do parser fixa esse comportamento.

**Sincronização.** `sincronizar_mpls` mantém o match de VSI por `(vsi_id,
membro)` e passa a atualizar o `operational_status` de cada `ServiceEndpoint` do
tipo AC pelo estado do `Interface Name` correspondente. O estado do **serviço**
continua vindo do `VSI State` do equipamento, que é a visão do próprio VRP, e um
AC caído não rebaixa o VSI na SoT: as duas informações convivem, uma no serviço
e outra por ponta.

**Pós-check** `valida_pos_vsi`:

| Condição | Severidade | Ação sugerida |
|---|---|---|
| VSI ausente na coleta | `critica` | conferir a config do VSI (`display vsi verbose`) |
| `VSI State` diferente de `up` | `critica` | verificar LDP, peer e MTU |
| Sessão com um peer fora de `up` | `critica` | conferir o peer e o pseudowire com o outro PE (§9.3) |
| AC de uma ponta fora de `up` | `atencao` | conferir o `l2 binding` e a Vlanif |
| MTU do VSI diferente do configurado | `atencao` | conferir o `mtu` do serviço e reaplicar |

O item de MTU roda **sempre**, e não só com o VSI de pé: o `MTU` do `display`
é o configurado do VSI, e a fixture real mostra VSI `down` ainda imprimindo o
dele (diferente do `local VC MTU` do L2VC, que vem `0` com o VC caído).

## 8. Web e CLI

- **Detalhe do VSI** (`/mpls/vsi/:id`): lista de ACs com equipamento, Vlanif,
  VLAN e estado, a divergência por pseudowire e por AC da última coleta, e o
  botão "Solicitar mudança" (a página de CR já trata o escopo `vsi` depois da
  §5).
- **Lista de VSIs**: badge de estado operacional e a contagem de PEs.
- **`escopoComFluxo`** na página de CR passa a incluir `vsi`, que era o último
  escopo bloqueado.
- **CLI**: `gerenet mpls vsi add` aceita `--endpoint DEVICE:VID` repetível e
  `--flow-label`; `gerenet change-requests add --escopo vsi --vsi-id N`.
- **Wiki**: a página `docs/wiki/em-breve/mpls.md` deixa de dizer que o
  provisionamento multiponto vem depois.

## 9. Testes

Automatizados (padrão do repo):

- **Modelo e validações**: `vsi_id` e `vrp_name` únicos por domínio; VID de AC
  ocupado no mesmo equipamento (409); endpoint duplicado no mesmo VSI; criação
  de CR de provisionamento com menos de dois endpoints (erro do serviço, 400);
  VID default igual ao `vsi_id`.
- **Render**: VSI de dois e de quatro PEs (contagem de linhas `peer`), `mtu` e
  `description` opcionais, `flow-label` só com a capability e o flag, AC com
  `vlan`, `Vlanif<vid>` e binding; idempotência (segunda chamada, zero diffs).
- **Parser**: fixture real nos três níveis, VSI órfão descartado, saída vazia,
  peer sem `Session` e AC sem `State` sem inventar valor.
- **Fluxo de CR**: criação com N steps; execução com uma ponta falhando ⇒
  `parcial`; reconciliação recomputando só as pontas pendentes; rollback de um
  VSI aplicado gerando o filho de remoção; rollback de remoção gerando
  provisionamento; `PlanoRollbackVazio` quando nada consta.
- **Pré-check**: peer LDP up libera, `down` bloqueia, `None` bloqueia com a
  mensagem de coleta, binding de outro VSI na mesma Vlanif bloqueia, e membro
  sem ponta bloqueia com o "revalide o serviço".
- **Pós-check**: os cinco itens da tabela da §7, com o MTU conferido também
  com o VSI fora de `up` (o `display` imprime o MTU configurado do VSI nos
  dois casos).
- **Web**: Vitest do detalhe do VSI com ACs e do botão numa CR de escopo `vsi`.
- **API e CLI**: criação de CR `--escopo vsi`, 409 nos conflitos e o
  `--endpoint` repetível.

## 10. Validação em equipamento real

Segue o `docs/runbook-validacao-switch-mpls.md`, sem lab (decisão de
2026-09-07). A etapa 1 read-only ganha a conferência do `display vsi verbose`
nos três níveis e do `display current-configuration configuration vsi`, que já
foi capturado nesta sessão. A etapa 3 provisiona um **VSI de teste** com dois
PEs em switch não crítico, com o VID igual ao `vsi_id` para seguir a convenção
da operação, e verifica o estado por pseudowire e por AC depois da execução.

## 11. Decisões registradas (brainstorming 2026-09-13)

1. **Remoção do AC só desfaz o binding e o VSI** (usuário): a `Vlanif` e a
   `vlan` ficam no equipamento, como o L2VC nunca dá `undo interface`. A
   limpeza da Vlanif, se for desejada um dia, é decisão separada.
2. **Pós-check em três níveis** (usuário): VSI, pseudowire e AC. O aprendizado
   de MAC fica fora e é registrado na §12, porque exige um comando de coleta
   novo.
3. **Interface do AC derivada do VID** (`Vlanif<vid>`), em vez de campo livre,
   para não permitir cadastro apontando para uma Vlanif alheia ao serviço.
4. **VID default igual ao `vsi_id`**, seguindo a convenção medida no switch,
   com override pelo operador.
5. **Mínimo de dois endpoints para provisionar**; cadastro com um membro
   continua permitido.
6. **Render enxuto**: `tnl-policy`, `statistic enable` e comandos de MAC ficam
   de fora, porque os VSIs medidos usam default do VRP.

## 12. Dívidas registradas

- **Aprendizado de MAC** (§13.2, "quando aplicável"): exige `display mac-address`
  ou equivalente, com parser e item de pós-check próprios. Fica para uma frente
  curta depois desta.
- **Limpeza da `Vlanif` e da `vlan`** na remoção: decisão do usuário em manter,
  registrada aqui para não virar surpresa quando a divergência apontar a sobra.
- **`tnl-policy`**: alguns VSIs da operação usam `LOAD_BALANCE_CDN`; o gerenet
  não modela o campo e o render não o emite. Se a operação quiser padronizar
  política de túnel por serviço, é um campo novo com o seu próprio gate de
  capacidade.
