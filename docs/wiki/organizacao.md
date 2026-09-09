---
title: Organizações e contatos
secao: Cadastro
secao_order: 2
order: 1
---

# Organizações e contatos

## Organizações

Uma organização é o seu cliente ou parceiro de rede. O cadastro tem:

| Campo | Regra |
|---|---|
| Nome de exibição | 1–128 caracteres, **único**. |
| Razão social | Opcional. |
| Tipo | `downstream` (cliente) ou `parceiro`. |
| ASN | **Único por organização**; válido de 32 bits (1–4294967295) e fora das faixas reservadas (0, AS_TRANS 23456, documentação RFC 5398, 65535 e afins). O sistema barra com "ASN inválido ou reservado" e duplicado com "Já existe organização com ASN X". |
| AS-SET (IRR) | Opcional, ex.: `AS64500:AS-CLIENTE`. Hoje é só referência — a consulta ao IRR vem nas políticas avançadas (em breve). |
| Observações | Livres. |

O ASN da organização é o `asn_remote` padrão das [sessões BGP](/wiki/roteamento)
dos circuitos dela (a sessão recusa um ASN remoto que difira do ASN da
organização).

## Contatos

Cada contato pertence a uma organização e tem tipo `tecnico`, `noc` ou `admin`,
com nome obrigatório, e-mail e telefone opcionais. Hoje os contatos são apenas
cadastro de referência; o uso em **notificações** (alarmes, mudanças, prazos de
[planos de mudança](/wiki/mudancas-controladas)) é planejado.

## Desativação, nunca exclusão

Objetos em uso são **desativados** (`admin_status = false`), nunca excluídos
fisicamente. As consequências práticas no sistema:

- Organização desativada não recebe novas autorizações de prefixo.
- Circuito desativado não recebe reservas nem novas sessões BGP.
- De forma geral, a desativação preserva o histórico de auditoria e as
  referências; telas com "ver desativados" mostram o registro ainda.

O mesmo padrão vale para equipamentos, sites e demais entidades do gerenet.
