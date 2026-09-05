---
title: Circuitos, VLANs e IPAM
secao: Cadastro
order: 2
---

# Circuitos, VLANs e IPAM

## O cadastro de circuito

O circuito amarra cliente → POP → equipamentos → recursos. Campos:

| Campo | Regra |
|---|---|
| Código | **Único** (1–64), padrão da operadora/team (ex.: `CIRC-000123`). |
| Organização | Dono do circuito. |
| Site/POP | Onde o circuito está instalado. |
| Equipamento de acesso | Switch do cliente (S6730…); a **porta** de acesso segue o padrão letras/números/`/`/`-` (ex.: `GE0/0/1`, `Eth-Trunk1`). |
| Roteador de borda | NE8000 que concentra o circuito (edge). |
| Roteador de contingência | Opcional — plano B do circuito. |
| Trunk de borda | Eth-Trunk do edge que agrega o acesso (ex.: `Eth-Trunk127`); sem ele, o render da subinterface não acontece. |
| Famílias (`stack`) | `ipv4`, `ipv6` ou `dual` (padrão dual). |
| VLAN (`vlan_mode`) | `unica` (uma VLAN para as famílias) ou `separada` (uma por família). |
| QinQ | Ativa quando o acesso usa VLAN interna do cliente (dot1q + tag na borda). |
| VRF | Nome do VRF/VS; **vazio = instância pública/global** (peers BGP na pública, §25.3). |
| MTU | 576–9600 — coerente fim a fim no caminho do serviço. |
| Banda | Texto (ex.: 1G, 10G, 500M). |
| BFD | Intenção do enlace; o BFD efetivo no MVP vem da sessão BGP (`bfd_enabled`). |
| Comprimento p2p v4 | `/31` (padrão) ou `/30`. |

O sistema valida ainda que os equipamentos do circuito (acesso, edge, backup)
pertencem ao site, e o código não pode duplicar.

## Endereçamento p2p derivado (IPAM)

Os endereços do enlace são **derivados** pelo alocador, não digitados. O site
define os blocos: `p2p_ipv4_block` (padrão `100.64.0.0/10`) e `p2p_ipv6_base`
(ex.: `2804:194C:1000::/48`).

- **IPv4**: `/31` por padrão (pontas `.0`/`.1`) ou `/30` (pontas `.1`/`.2`), no
  bloco privado do site, sempre sem sobreposição com os enlaces já reservados.
- **IPv6**: `/126` por enlace, com sufixo derivado dos **dígitos decimais dos
  octetos 2–4 do IPv4 do enlace, relidos como dígitos hex** e agrupados em
  hextets (4 primeiros dígitos + o restante). Ponta local `:1`, remota `:2`.

Exemplo (spec §25.8): IPv4 `100.110.0.73` → octetos 2–4 `110.0.73` → dígitos
`110073` → hextets `1100:73` → local `2804:194C:1000::1100:73:1/126`, remota
`2804:194C:1000::1100:73:2/126`.

Em circuito `ipv6` puro, o alocador também reserva um par IPv4 interno (só para
derivar o sufixo — não vai para a interface).

## Reservar recursos

Após cadastrar o circuito, clique em **Reservar** (ou
`gerenet circuits reserve <circuito>`). O alocador reserva, por site/POP:

1. **VLAN**: o menor VID livre entre 2–4094 do site (uma linha para `unica`;
   duas, uma por família, para `separada`; `kind` s_vlan no QinQ).
2. **Enlace IPv4**: primeiro prefixo livre do bloco do site, sem sobreposição.
3. **Enlace IPv6**: `/126` derivado (quando `dual` ou `ipv6`).

A reserva é **idempotente**: repetir a operação devolve o estado atual e grava
apenas um evento de auditoria de retry. Falhas de validação (VLANs esgotadas,
bloco esgotado, `/126` derivado já reservado no site) não deixam linhas parciais.

As reservas alimentam o render da [configuração desejada](/wiki/operacao):
subinterface `<trunk>.<vid>`, prefix-lists e sessões BGP. Para o passo
seguinte, veja [Sessões BGP, autorizações, perfis e communities](/wiki/roteamento).
