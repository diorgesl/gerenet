---
title: Mudanças controladas nos equipamentos
secao: Em breve
order: 1
em_breve: true
---

# Mudanças controladas nos equipamentos

> **Em breve** — esta página descreve o fluxo **planejado** de mudanças. Hoje
> **nenhuma mudança em equipamento é executada pela plataforma**: a coleta é
> read-only e a interface só cadastra e consulta a intenção.

## O que está previsto

O fluxo de mudança controlada segue os 10 passos do §12 da spec:
validar dados → coletar estado → verificar conflitos → gerar plano → mostrar
diff e comandos → aprovar conforme política → backup/checkpoint → aplicar →
validar resultado → registrar auditoria.

Elementos previstos:

- **Change request**: motivo, ticket e criticidade (`baixa`/`media`/`alta`),
  sobre um circuito, com ação de **provisionar** ou **remover**.
- **Passos por equipamento**: cada device afetado recebe seu passo com plano
  (config atual × desejada), comandos previstos e de rollback.
- **Aprovação**: 1 aprovador para downstream novo em borda; **2 aprovadores**
  para upstream/core, remoção de serviço em produção e alteração de filtros de
  produção; a mesma pessoa não solicita, aprova e executa quando a regra de
  separação for exigida (§25.10).
- **Execução com lock**: lock por equipamento (uma mudança de cada vez no
  device) + limite de execuções simultâneas por POP (default 2–4, §25.14);
  comandos em blocos pequenos, parada em erro crítico do VRP, saída registrada
  de forma segura.
- **Backup/checkpoint** antes da mudança (baseline) e **pós-validação** (peer
  Established, filtros corretos, prefixos no esperado).
- **Rollback conservador e dirigido por capacidade**: comandos inversos
  automáticos só para classes seguras; checkpoint/rollback nativo ou
  restauração controlada onde o VRP suportar; caso contrário, procedimento
  manual documentado (§25.13).

## Onde já existe base

O fluxo está **em construção** no backend: o serviço e a API de change
requests já existem (criar, enviar, aprovar, cancelar, executar e rollback),
mas a **execução real em equipamento** (fila + worker que aplica comandos)
**ainda não** — o `executar` atual apenas marca o estado da solicitação. O que
já é consultável hoje:

- A [configuração desejada](/wiki/operacao) (render da intenção em comandos VRP
  por equipamento).
- A [reconciliação](/wiki/operacao) desejado × encontrado.
- A [auditoria](/wiki/operacao) de toda a atividade de cadastro e coleta.

## Estados previstos

Rascunho → aguardando aprovação → aprovado → executando → aplicado /
com divergência / parcial / erro — além de rejeitado e cancelado.
