---
title: Upstreams e políticas avançadas
secao: Em breve
order: 3
em_breve: true
---

# Upstreams e políticas avançadas

> **Em breve** — o fluxo de **upstream** (sua própria conectividade de
> trânsito/IX) ainda não existe como entidade do sistema. Esta página descreve
> o planejado (Fase 5 do roadmap, §22).

## O que está previsto

- **Perfis de upstream**: trânsito, IX (pontos de troca), PNI e contingência,
  com capacidade, prioridade/custo, políticas de entrada e anúncio, e limiar
  de prefixos com margem.
- **Full routes**: anúncio de tabela completa sobre sessões com perfis
  específicos (compare com os [produtos de exportação](/wiki/roteamento) que já
  existem para downstreams).
- **Communities de engenharia de tráfego**: local-preference e prepend por
  região, blackhole e prepend por região — o catálogo de communities já tem o
  conjunto mínimo (`blackhole`, `no-export`, `no-advertise`).
- **Validação RPKI e IRR**: autorizações de prefixo com origem IRR/RPKI
  somente com **aprovação humana** (hoje a origem é manual).
- **Proteções**: máximo de prefixos com margem, rejeição de bogons e de rotas
  próprias, bloqueio padrão sem política vinculada, alerta de variação anormal
  do número de rotas e registro do número de rotas antes/depois.

## O que já existe e serve de base hoje

O gerenet já implementa a parte de **consumidor**: a lógica de
[sessões BGP](/wiki/roteamento) (um peer por família), autorizações de
prefixos, políticas de import/export com nomes derivados `RP-<ASN>-…` e a
[comparação de divergências](/wiki/operacao) — tudo para os clientes
(downstreams). O render de `full` já é capaz de emitir a route-policy para uma
sessão de upstream (parte do catálogo de produtos, §25.5).

A [reconciliação](/wiki/operacao) também já alerta peers coletados sem sessão
ativa cadastrada (`peer.orfaos`) e filtros divergentes — úteis quando o
upstream existir como conceito. Fluxo de execução: [mudanças
controladas](/wiki/mudancas-controladas).
