// Textos de ajuda dos campos (help()) — ciclo E.
// Fonte das regras: src/gerenet/domain/schemas.py, mensagens dos services e
// ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md §5–§8 e §25 (nomenclatura VRP).
export const HELP = {
  // Sites
  "site.nome": "Nome único do site/POP (1–64 caracteres).",
  "site.city": "Cidade do POP (opcional).",
  "site.uf": "Sigla da UF com 2 letras (ex.: SP).",
  "site.p2p_ipv4_block": "Bloco privado de enlaces p2p do site; default 100.64.0.0/10.",
  "site.p2p_ipv6_base": "Base v6 do site (ex.: 2804:194C:1000::/48) — /126 derivados dos enlaces.",

  // Devices
  "device.name": "Nome único do equipamento (1–64); identifica o registro no gerenet.",
  "device.management_address": "Endereço IP de gestão acessível pela rede de gerência dedicada.",
  "device.ssh_port": "Porta SSH de acesso (1–65535; default 22).",
  "device.model": "Modelo do equipamento (ex.: NE8000 M8, S6730-H24X6C).",
  "device.family": "Família/plataforma (NE8000, NE40, S6730…) — referência de capacidades; a seleção de templates por família/versão é evolução do produto.",
  "device.role": "Função do equipamento (borda de downstream, core MPLS, upstream…).",
  "device.asn": "ASN local (1–4294967295, reservados barrados) — vira o asn_local default das sessões BGP do equipamento.",
  "device.site": "Site/POP onde o equipamento está instalado.",
  "device.tags": "Etiquetas livres, separadas por vírgula (ex.: BGP, MPLS, contingência).",
  "device.credential_group": "Grupo de credencial usado para acessar o equipamento — o segredo fica no Vault; aqui fica só o vínculo.",

  // Credential groups
  "credential_group.name": "Nome único do grupo (1–64); identificador referenciado pelo equipamento.",
  "credential_group.vault_path": "Caminho lógico no Vault onde o segredo do grupo é armazenado (ex.: gerenet/credential-groups/automacao).",
  "credential_group.kind": "Tipo de credencial do grupo (default: tacacs_password).",

  // Organizations
  "organization.name": "Nome de exibição da organização (1–128 caracteres).",
  "organization.legal_name": "Razão social completa (opcional).",
  "organization.kind": "Tipo: downstream (cliente), parceiro ou operadora.",
  "organization.asn": "ASN do cliente (1–4294967295, reservados barrados) — único por organização.",
  "organization.irr_as_set": "AS-SET registrado no IRR (ex.: AS64500:AS-CLIENTE), opcional.",
  "organization.notes": "Observações livres.",

  // Contacts
  "contact.organization_id": "Organização à qual o contato pertence.",
  "contact.name": "Nome do contato (1–128).",
  "contact.email": "E-mail para notificações (opcional).",
  "contact.phone": "Telefone de contato (opcional).",
  "contact.kind": "Tipo do contato: técnico, NOC ou admin.",

  // Circuits
  "circuit.code": "Código único do circuito (1–64), padrão da operadora/team (ex.: CIRC-000123).",
  "circuit.organization_id": "Cliente dono do circuito.",
  "circuit.site_id": "Site/POP de instalação do circuito.",
  "circuit.access_device_id": "Equipamento de acesso do cliente (switch de borda).",
  "circuit.access_port": "Porta física ou Eth-Trunk de acesso (letras, números, / e -, ex.: GE0/0/1 ou Eth-Trunk1).",
  "circuit.edge_device_id": "Roteador de borda (NE8000) que concentra o circuito.",
  "circuit.backup_edge_device_id": "Roteador de contingência (opcional) para o plano B do circuito.",
  "circuit.stack": "Famílias do circuito: ipv4, ipv6 ou dual (ambas).",
  "circuit.vlan_mode": "Única: uma VLAN para as duas famílias; Separada: uma VLAN por família.",
  "circuit.qinq": "QinQ quando o acesso usa VLAN interna do cliente (dot1q + tag da borda).",
  "circuit.vrf": "Nome do VRF/VS do circuito; vazio = instância pública/global.",
  "circuit.mtu": "MTU do enlace (576–9600); coerente fim a fim no caminho do serviço.",
  "circuit.bandwidth": "Banda contratada (ex.: 1G, 10G, 500M).",
  "circuit.bfd": "BFD de intenção do enlace; no MVP o BFD efetivo vem da sessão BGP (bfd_enabled).",
  "circuit.p2p_v4_len": "Tamanho do enlace v4: /31 (padrão) ou /30, no bloco privado do site.",
  "circuit.edge_trunk": "Eth-Trunk de borda (opcional) que agrega o acesso do cliente.",
  "circuit.description": "Descrição livre (1–255).",
  "circuit.notes": "Observações livres.",

  // BGP sessions
  "bgp.circuit_id": "Circuito/serviço atendido pela sessão. Ao selecionar, o formulário preenche automaticamente o equipamento edge, os ASNs local/remoto e as pontas do enlace reservado (conforme a família — sem máscara).",
  "bgp.device_id": "Equipamento onde o peering é configurado (instância pública).",
  "bgp.afi": "Família da sessão: ipv4 ou ipv6 — uma sessão por família; sem duplicar device+VRF+família.",
  "bgp.local_address": "Endereço local do enlace p2p, sem máscara (v4 e v6) — a máscara identifica o enlace reservado; na sessão informe apenas o endereço da ponta.",
  "bgp.remote_address": "Endereço do peer no enlace p2p, sem máscara (v4 e v6) — a máscara identifica o enlace reservado; na sessão informe apenas o endereço da ponta.",
  "bgp.source_address": "Endereço usado como source do peering quando difere do endereço do enlace (opcional).",
  "bgp.asn_local": "ASN do lado gerenet; default = ASN do equipamento.",
  "bgp.asn_remote": "ASN do peer; default = ASN da organização do circuito.",
  "bgp.description": "Descrição da sessão (1–255).",
  "bgp.import_profile_id": "Perfil de importação (direction=import) — a route-policy é gerada a partir das autorizações do cliente.",
  "bgp.export_profile_id": "Perfil de exportação (direction=export) — produto do catálogo (default, default + internas, parcial, full, CDN ou personalizado).",
  "bgp.maximum_prefix": "Limite de prefixos recebidos (maximum-prefix) — acima disso o VRP derruba a sessão; use margem nos upstreams.",
  "bgp.maximum_prefix_threshold": "Percentual do limite (0–100) que dispara o aviso.",
  "bgp.local_preference": "local-preference aplicado na importação (maior = preferido).",
  "bgp.med": "MED aplicado na exportação (menor = preferido pelo vizinho).",
  "bgp.prepend": "Prepend no AS-PATH (0–10) — repete o ASN local para desvalorizar rotas anunciadas.",
  "bgp.keepalive": "Timer keepalive em segundos; só é aplicado junto com o holdtime (senão, default do VRP).",
  "bgp.holdtime": "Timer holdtime em segundos; só é aplicado junto com o keepalive (senão, default do VRP).",
  "bgp.bfd_enabled": "BFD sobre a sessão BGP — detecção rápida de queda do peer.",
  "bgp.graceful_restart": "Habilita graceful restart (reinício sem queda de rotas).",
  "bgp.shutdown": "Sessão provisionada mas desligada (shutdown) — não estabelece peering.",
  "bgp.allow_default_route": "Aceita rota default (0.0.0.0/0 ou ::/0) do peer — entra antes das autorizações na prefix-list.",
  "bgp.password": "Senha MD5 do peering — segredo: nunca exibida em texto claro (espelha apenas has_password).",

  // Policy profiles
  "policy.name": "Nome único do perfil (1–64; catálogo pode ter nomes fixos seedados).",
  "policy.product": "Produto de roteamento do catálogo: Somente default, Default + internas, Tabela parcial, Full routing, CDN ou Personalizado — a route-policy de exportação é construída a partir do produto (Default + internas e Tabela parcial ainda viram comentário de dívida no MVP).",
  "policy.direction": "Direção do perfil: import (entrada) ou export (saída) — a sessão só aceita o perfil da direção correspondente.",
  "policy.kind": "Tipo do perfil: produto (catálogo) — route-policy clássico; XPL é evolução do produto e a seleção de sintaxe por capacidade é recurso futuro.",
  "policy.prefixes": "Prefixos do produto (CDN/personalizado), um por linha (CIDR) — montam a prefix-list de anúncio; sem prefixos, o produto renderiza um comentário de dívida.",
  "policy.notes": "Observações livres.",

  // Communities
  "community.name": "Nome/valor da community no catálogo (1–64 caracteres; ex.: no-export ou 64500:100) — a aplicação do valor concreto na configuração é fase futura.",
  "community.tipo": "Categoria da community (§7/§25.6): padrao (valor direto), acao_blackhole/acao_prepend/acao_lp (ação de tráfego), informacao (marcação informativa) ou tag_produto (tag de produto/serviço).",
  "community.notes": "Observações livres.",

  // Prefix authorizations
  "prefix.organization_id": "Organização dona da autorização (o filtro de entrada é derivado das autorizações ativas).",
  "prefix.family": "Família: ipv4 ou ipv6.",
  "prefix.prefix": "Prefixo autorizado em CIDR (ex.: 10.0.0.0/24; 2001:db8::/48) — só autorizações ativas viram IP-PFX-<ASN>-IN-<AFI>.",
  "prefix.notes": "Observações livres.",

  // Upstreams
  "upstream.name": "Nome único do upstream (2–128 caracteres; ex.: transito-telco-01).",
  "upstream.tipo": "trânsito, IX, PNI ou contingência.",
  "upstream.organization_id": "Organização dona da conectividade — somente organizações do tipo operadora.",
  "upstream.capacity": "Capacidade contratada (ex.: 10 Gbps).",
  "upstream.priority": "Prioridade da conectividade (1 = maior), para seleção de rota preferida.",
  "upstream.cost": "Custo da conectividade (ex.: R$/Mbps) — informativo no MVP.",
  "upstream.expected_prefixes_v4": "Total de prefixos IPv4 esperados do upstream — base da faixa de normalidade.",
  "upstream.expected_prefixes_v6": "Total de prefixos IPv6 esperados do upstream — base da faixa de normalidade.",
  "upstream.max_prefix_margin_pct": "Margem percentual sobre o esperado de prefixos (0-100) com uso duplo: serve à faixa de normalidade da validação (esperado ± margem) e ao maximum-prefix repropagado nas sessões (esperado × (1+margem), limiar de proteção do VRP fixado em 80% quando ausente).",
  "upstream.rpki_enabled": "Validação RPKI consultiva (§10.4): o hook apenas marca a validação (ok/diverge/desconhecida) nas autorizações de prefixo — sem RTR e sem bloqueio/rejeição; a aprovação continua humana.",
  "upstream.entrada_local_preference": "Local-preference aplicado na importação das rotas deste upstream (maior = preferida).",
  "upstream.contingencia_local_preference": "Local-preference aplicado quando o upstream é contingência (tipicamente menor que a da conectividade principal).",
  "upstream.contingencia_prepend": "Prepend no AS-PATH quando o upstream é contingência (0–10) — desvaloriza os anúncios.",
  "upstream.contingencia_notes": "Observações livres sobre o contexto de contingência.",

  // Users
  "user.username": "Nome de login (1–64), único.",
  "user.password": "Senha com mínimo de 8 caracteres — jamais registrada em log ou auditoria.",
  "user.role": "Perfil de permissão: visualizador, operador, aprovador, executor ou administrador.",
} as const;

export type HelpKey = keyof typeof HELP;

export function help(chave: HelpKey): string {
  return HELP[chave];
}
