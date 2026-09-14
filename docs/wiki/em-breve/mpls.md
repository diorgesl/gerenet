---
title: Serviços MPLS (L2VC e VSI)
secao: MPLS
secao_order: 4
order: 2
---

# Serviços MPLS (L2VC e VSI)

O gerenet gerencia serviços MPLS em switches da família S (S6730…): o **domínio MPLS** é
cadastrável com seus membros e loopbacks LDP, e tanto o **L2VC** (ponto a ponto) quanto o
**VSI** (multiponto) saem como mudança controlada — com pré-check de LDP, execução aprovada e
pós-validação. Os dois mundos têm um ponto comum: o tráfego de downstreams.

## Domínio MPLS e L2VC

- **Domínio MPLS** (página `/mpls/domains`): PE participantes com **loopback LDP**,
  interfaces de core, estado MPLS/LDP, peers e recursos ocupados (IDs/VLANs/portas).
- **L2VC** (página `/mpls/l2vc`): pontas A/B com interface de acesso, VLAN reservada
  (por device), **VC-ID único no domínio**, MTU, control-word e flow-label (requer a
  capability `mpls_flow_label` no equipamento). Validações: VC-ID único, VLAN livre,
  peer alcançável e LDP operacional, MTU fim a fim e **simetria entre as pontas**.
- **Mudança controlada**: criar um L2VC abre uma change request de escopo `l2vc` — o plano
  (diff por bloco desejado × encontrado) já nasce com a CR, que segue o fluxo normal
  (rascunho → aprovação → execução no worker com **pré-check do peer LDP** e **pós-check**
  do `display l2vc` ⇒ `Up`). A remoção é uma CR inversa, também aprovada.
- **Coleta e estado**: o worker coleta `display mpls ldp peer` (com a sessão LDP), `display
  mpls l2vc` e `display vsi verbose`, e a plataforma mostra o desejado × encontrado e a
  divergência, por objeto e severidade — com a última coleta e a ação recomendada.

## VSI (multiponto)

- **Cadastro** (página `/mpls/vsi`, botão "Novo VSI"): domínio, nome, VSI-ID (vazio assume o
  próximo livre), MTU, descrição e flow-label (requer a capability `mpls_flow_label` no
  equipamento), mais um **AC por PE participante** — VLAN reservada por equipamento e a
  interface derivada do VID (`Vlanif<vid>` — o VID omitido assume o VSI-ID, que é a convenção
  da operação), com MTU opcional por ponta. O formulário aceita um PE; o provisionamento exige
  dois ou mais. O equivalente na CLI é `gerenet mpls vsi add --endpoint DEVICE:VID`. Os campos
  `split_horizon`, `mac_learning` e `mac_limit` existem na SoT mas **não entram no render** (o
  template não os emite), então ficam fora do formulário e do CLI.
- **Mudança controlada**: o provisionamento é uma change request de **escopo `vsi`**, com
  um step por PE — o bloco do VSI (com uma linha `peer` por membro) e o do AC —, **pré-check**
  do par LDP de cada peer e da Vlanif sem binding alheio, **pós-check nos três níveis**
  (estado do VSI, de cada pseudowire e de cada AC) e **rollback e reconciliação** disponíveis.
  Uma ponta que falha deixa a CR em `parcial`: o serviço fica parcialmente provisionado e a
  recomposição passa pela reconciliação.
- **Remoção**: desfaz só o `l2 binding` e o VSI. A **`Vlanif` e a `vlan` ficam no
  equipamento** — sobra esperada, visível na divergência e reaproveitada por um
  re-provisionamento, como o L2VC nunca remove a interface.
- **Estado na página** (`/mpls/vsi/:id`): o estado do VSI e o de cada AC, atualizados pela
  coleta; o estado por pseudowire aparece no pós-check da change request (`vsi.peer`) e no
  snapshot cru.

## Recursos e validações previstas

Entra também na fase: a **validação** de LDP operacional, L2VC Up, VSI Up com os
pseudowires e ACs, MTU consistente e ausência de alarmes novos — e a **reserva interna de
recursos** (VLAN de AC por device, VC-ID/VSI-ID por domínio), com conflitos detectados antes
de qualquer mudança.

*Validação em equipamento real: ver o runbook `docs/runbook-validacao-switch-mpls.md` —
somente leitura → geração sem execução → execução de teste em switch não crítico.*

## Ponto de partida

- [Circuitos, VLANs e IPAM](/wiki/circuitos) — base das reservas VLAN/ID.
- [Equipamentos, coleta e snapshots](/wiki/equipamentos) — inventário dos switches de acesso.
- [Mudanças controladas](/wiki/mudancas-controladas) — o fluxo de aplicação com aprovação
  que carrega as configurações MPLS.
