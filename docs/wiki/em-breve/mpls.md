---
title: Serviços MPLS (L2VC e VSI)
secao: Em breve
order: 2
em_breve: true
---

# Serviços MPLS (L2VC e VSI)

> **Em breve** — nesta fase, **nada disso existe no código**: não há cadastro
> de domínio MPLS, L2VC ou VSI, nem reserva de VC-ID/VSI-ID. Os dois mundos
> têm um ponto comum: o tráfego de downstreams.

## O que está previsto (Fase 4 do roadmap, §22)

O objetivo é gerenciar serviços MPLS em switches (S6730…):

- **Domínio MPLS**: PE participantes, loopbacks LDP, interfaces de core,
  estado de MPLS/LDP, peers LDP, MTU e recursos ocupados (IDs/VLANs/portas).
- **L2VC** (ponto a ponto): pontas A/B, interfaces/VLANs de acesso,
  dot1q/QinQ, peer LDP, **VC-ID único no domínio**, MTU, control-word,
  flow-label e redundância. Validações previstas: VC-ID único, VLAN livre,
  peer alcançável, MPLS/LDP operacional, MTU fim a fim, ausência de binding
  conflitante e **simetria entre as pontas**.
- **VSI** (multiponto): sinalização LDP, PEs participantes, attachment
  circuits, split-horizon, limite de MAC aprendido, status por pseudowire e
  AC. A configuração de **todos** os equipamentos sai na mesma mudança
  lógica — se uma ponta falha, o serviço fica "parcialmente provisionado" e
  exige reconciliação.

Também entra na fase: a **validação** de LDP operacional, L2VC/VSI Up,
pseudowires e ACs Up, MAC aprendendo, MTU consistente e ausência de alarmes
novos.

## O que você pode fazer hoje

No estado atual, o gerenet cobre **downstreams BGP** (clientes com circuitos,
sessões BGP e autorizações) e a **coleta read-only** de equipamentos — sem
gerenciamento de serviços MPLS. A lista de valores que já existe e servirá de
base:

- [Circuitos, VLANs e IPAM](/wiki/circuitos) — base das reservas VLAN/IDs.
- [Equipamentos, coleta e snapshots](/wiki/equipamentos) — inventário dos
  switches de acesso (POS).
- [Mudanças controladas](/wiki/mudancas-controladas) — o fluxo de aplicação
  com aprovação que carregará as configurações MPLS.
