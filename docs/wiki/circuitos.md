---
title: Circuitos, VLANs e IPAM
secao: Cadastro
secao_order: 2
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
| Banda | Texto (ex.: 1G, 10G, 500M) — a nota que o humano lê. |
| Velocidade (Mbps) | A taxa contratada, em Mbps, que a máquina usa (ex.: `1024` = 1 Gbps). Vazio = "não sei a velocidade", e é o estado de todo circuito anterior a este campo. |
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
`2804:194C:1000::1100:73:2/126`. O `/126` identifica o enlace no gerenet: na
[sessão BGP](/wiki/roteamento) informe apenas o endereço da ponta, sem o `/126`
(no v4, idem, sem `/31`/`/30`).

Em circuito `ipv6` puro, o alocador também reserva um par IPv4 interno (só para
derivar o sufixo — não vai para a interface).

## A descrição e o QoS da subinterface

A `description` da subinterface deriva do circuito:

```
description <CÓDIGO> <NOME DA ORGANIZAÇÃO> [<VELOCIDADE>]
```

| Velocidade | Linha |
|---|---|
| 1024 | `description CIRC-626 NETMAC [1G]` |
| 100 | `description CIRC-500 ACME TELECOMUNICACOES [100M]` |
| vazia | `description CIRC-500 ACME TELECOMUNICACOES` |

O nome da organização vai em maiúsculas e sem acento, e cede no orçamento de 80
caracteres se não couber — cortado seco. Os 80 são a premissa do sistema hoje;
o limite real desta versão do VRP é o que a Etapa 3 do runbook de validação
confere. Velocidade múltipla de 1024 sai em `G`; qualquer outra sai em `M`.

Com a velocidade preenchida, o render emite também o limitador de taxa nas duas
direções, depois do `statistic enable`:

```
qos car cir <velocidade_mbps × 1000> inbound
qos car cir <velocidade_mbps × 1000> outbound
```

O `cir` é em kbps: `1024` Mbps produzem `cir 1024000`. O `cbs`, o `green pass`
e o `red discard` **não** são emitidos — o VRP os completa ao aplicar.

**Circuito que já está provisionado converge numa mudança nova.** Até esta
frente, o plano pulava a subinterface inteira pelo nome; agora ele confere
também a descrição e o QoS, e o bloco entra no plano como qualquer outro, um
`create`. Na execução, o re-diff o encontra já lá e fora de conformidade e
marca aquele passo como "atualizar": reemitir, não pular. O bloco vai inteiro
ao equipamento (reemitir endereço com o mesmo valor é inócuo no VRP), e o que
a mudança registra é o estado desejado daquele pedaço.

A descrição é **derivada**: renomear a organização não varre o parque — cada
circuito pega o nome novo na sua próxima mudança, planejada e aprovada por si.

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

## Liberar recursos

Para devolver os recursos ao site, clique em **Remover recursos** no detalhe do
circuito (ou `gerenet circuits unreserve <circuito>`). A liberação marca as
linhas como `liberada` em vez de apagá-las (o histórico fica) e o alocador
volta a oferecer o VID e o par p2p ao próximo circuito do site.

A operação também é idempotente: repetir grava apenas um evento de auditoria de
retry. Circuito com sessão BGP **ativa** não pode ser liberado (409) — desative
as sessões antes; sessão desativada já está fora da configuração desejada e não
bloqueia.

A liberação não mexe nas sessões: desativar não desvincula, então um circuito
liberado pode continuar com sessões apontando para endereços que voltaram ao
pool, e criar sessão nova não exige reserva. O render de um circuito nesse
estado traz só o peer, sem subinterface.

As reservas alimentam o render da [configuração desejada](/wiki/operacao):
subinterface `<trunk>.<vid>`, prefix-lists e sessões BGP. Para o passo
seguinte, veja [Sessões BGP, autorizações, perfis e communities](/wiki/roteamento).
