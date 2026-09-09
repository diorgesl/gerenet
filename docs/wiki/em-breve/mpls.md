---
title: Serviços MPLS (L2VC e VSI)
secao: MPLS
secao_order: 4
order: 2
---

# Serviços MPLS (L2VC e VSI)

O gerenet gerencia serviços MPLS em switches da família S (S6730…): o **domínio MPLS** é
cadastrável com seus membros e loopbacks LDP, e o **L2VC** (ponto a ponto) sai como mudança
controlada — com pré-check de LDP, execução aprovada e pós-validação. **VSI é apenas cadastro
e consulta** nesta fase (o provisionamento multiponto vem em fase posterior). Os dois mundos
têm um ponto comum: o tráfego de downstreams.

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
- **Coleta e estado**: o worker coleta `display mpls ldp peer` e `display l2vc` e a
  plataforma mostra o desejado × encontrado e a divergência, por objeto e severidade —
  com a última coleta e a ação recomendada.

## VSI (multiponto)

- **Cadastro e consulta** (página `/mpls/vsi`): PEs participantes, attachment circuits,
  split-horizon, limite de MAC aprendido e status por pseudowire/AC (coleta do
  `display vsi`).
- **Sem provisionamento neste ciclo**: a configuração de "todos os equipamentos na mesma
  mudança lógica" (e o estado "parcialmente provisionado" com reconciliação) é de fase
  posterior.

## Recursos e validações previstas

Entra também na fase: a **validação** de LDP operacional, L2VC Up, MTU consistente e ausência
de alarmes novos — e a **reserva interna de recursos** (VLAN de AC por device, VC-ID/VSI-ID
por domínio), com conflitos detectados antes de qualquer mudança.

*Validação em equipamento real: ver o runbook `docs/runbook-validacao-switch-mpls.md` —
somente leitura → geração sem execução → execução de teste em switch não crítico.*

## Ponto de partida

- [Circuitos, VLANs e IPAM](/wiki/circuitos) — base das reservas VLAN/ID.
- [Equipamentos, coleta e snapshots](/wiki/equipamentos) — inventário dos switches de acesso.
- [Mudanças controladas](/wiki/mudancas-controladas) — o fluxo de aplicação com aprovação
  que carrega as configurações MPLS.
