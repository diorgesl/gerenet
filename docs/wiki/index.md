---
title: Visão geral e conceitos
secao: Começando
order: 1
---

# Visão geral e conceitos

O gerenet é o gerenciador de rede Huawei VRP: ele guarda a **intenção** da rede
(clientes, equipamentos, circuitos, sessões BGP) e compara com o **estado real**
coletado dos roteadores e switches.

## Conceitos que você precisa conhecer

- **Source of Truth**: o banco é a fonte da intenção. O que você cadastra aqui é
  o que a rede *deve* ter — nunca o que ela *tem* (isso vem da coleta).
- **Intenção × implementação**: você cadastra dados estruturados (ASN, prefixos,
  produto); os nomes VRP são derivados automaticamente
  (ex.: `RP-64500-IMPORT-V4`) — não há campo para digitar nome de política.
- **Mudança segura**: nenhuma alteração toca o roteador sem validação, plano,
  aprovação e auditoria (§3.3 da spec). No estado atual, a aplicação em
  equipamento chega com o fluxo de mudanças (em breve).
- **Tudo é auditado**: cada criação, alteração, desativação e coleta gera um
  evento de auditoria; a trilha não é editável e segredos são mascarados.

## Navegação rápida

| O que você quer fazer | Página |
|---|---|
| Primeiro acesso, perfis e primeiro equipamento | [Primeiros passos](/wiki/comecar) |
| Cadastrar equipamento e entender coleta/snapshots | [Equipamentos, coleta e snapshots](/wiki/equipamentos) |
| Cadastrar organização e contatos | [Organizações e contatos](/wiki/organizacao) |
| Cadastrar circuito e reservar VLAN/endereços p2p | [Circuitos, VLANs e IPAM](/wiki/circuitos) |
| Cadastrar sessão BGP, autorizações, perfis e communities | [Sessões BGP, autorizações, perfis e communities](/wiki/roteamento) |
| Ver desejado × encontrado, jobs e auditoria | [Reconciliação, config desejada, jobs e auditoria](/wiki/operacao) |
| Gerenciar serviços MPLS em switches (domínio, L2VC, VSI) | [Serviços MPLS (L2VC e VSI)](/wiki/mpls) |
| Gerenciar upstreams de trânsito/IX (operadora, communities, IRR/RPKI) | [Upstreams e políticas avançadas](/wiki/upstreams) |
| Entender o que ainda não é executado | [Mudanças controladas](/wiki/mudancas-controladas) |
