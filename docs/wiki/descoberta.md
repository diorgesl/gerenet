---
title: Migrar — descoberta de peers na configuração
secao: Operação
secao_order: 5
order: 4
---

# Migrar — descoberta de peers na configuração

Todo equipamento já coletado tem a configuração inteira guardada no snapshot. A
página **Migrar** (rota `/discovery`, grupo Operação) lê essa configuração e
mostra o que o equipamento tem e a SoT ainda não conhece, para você decidir o
que cadastrar.

## O que ela lê, e o que ela nunca lê

Lê só o que a coleta já trouxe: o `display current-configuration` e o recurso
`interfaces` (as três saídas `display ... interface brief`) do snapshot mais
recente **que tenha a configuração salva** — coleta anterior a este recurso não
serve de fonte. Todo o trabalho é leitura de texto já gravado. **Nenhum comando
é enviado ao equipamento em nenhum momento**: nem ao abrir a página, nem ao
rodar o CLI, nem ao mexer na lista de ignorados. Quem fala com o equipamento
continua sendo só a [coleta](/wiki/operacao).

O valor da senha de um peer (`password cipher`) nunca é lido. O parser registra
apenas que existe uma senha configurada, e isso aparece como pendência: o
`cipher` do VRP não é decifrável, e a SoT guarda o caminho no Vault, não o valor.

## Veredito, pendência e conflito

Cada linha da lista é um **enlace**, não um peer: os peers IPv4 e IPv6 que
dividem a mesma subinterface viram uma proposta só, de circuito dual stack (a
coluna Stack mostra `dual`). O agrupamento é por subinterface — duas
subinterfaces com o mesmo VID, em portas diferentes, são dois enlaces.

O **veredito** tem três valores. `adotavel` quando não falta nada.
`adotavel_com_pendencias` quando há decisão humana a tomar. `nao_adotavel`
quando há conflito, que precisa ser resolvido fora da tela; a proposta se
recalcula sozinha na próxima abertura, porque nada dela fica gravado.

**Pendência** é o que você preenche na revisão:

| Tipo | O que falta |
|---|---|
| `organizacao_ausente`, `classificacao_nao_confirmada` | Não há organização cadastrada com o ASN do peer: cadastre e confirme se é downstream ou upstream. |
| `acesso_desconhecido` | A configuração do edge não diz de que switch e porta o cliente chega. |
| `codigo_em_uso` | O código de circuito sugerido (`ADOC-<ASN>-<VID>`) já existe: escolha outro. |
| `senha_nao_legivel` | O equipamento tem senha de peer e o valor não é legível: cadastre o segredo no Vault e informe o caminho. |
| `perfil_indeterminado`, `politica_fora_do_padrao` | A política aplicada na configuração: o produto (full, parcial, default) não é recuperável do nome dela. |
| `asn_do_equipamento` | O `bgp <asn>` do bloco difere do ASN cadastrado no equipamento. |
| `peer_nao_habilitado` | O equipamento declara o peer mas não o habilita em nenhuma família (`peer ... enable`): adotar transforma um resto de configuração em sessão ativa, e o render emite `peer ... enable` em toda sessão. |
| `mesmo_asn_em_outro_enlace` | Outro enlace deste equipamento tem o mesmo ASN remoto: é um dual stack com VLAN separada (um circuito) ou dois circuitos? |

**Conflito** é o que impede a adoção, e vem sempre com o que fazer:

| Tipo | O que impede |
|---|---|
| `vlan_tomada`, `prefixo_tomado` | A VLAN ou o prefixo já está reservado para outro circuito no mesmo site. |
| `par_em_uso` | Este equipamento já tem, na SoT, uma sessão entre os dois endereços do enlace. |
| `enlace_nao_p2p` | O endereço está numa rede que não é `/30`, `/31` ou `/126` — a sub-rede compartilhada de um IX, por exemplo, que o IPAM não representa. A VLAN continua na proposta; o que não há é prefixo a reservar. |
| `ponta_incoerente` | O endereço está dentro de um par, mas não é nenhuma das duas pontas que o IPAM representa — o `/30` com o roteador no `.3`, por exemplo, cujas pontas são `.1` e `.2`. A VLAN continua na proposta; sem ponta não há reserva nem sessão. |
| `endereco_sem_subinterface` | Nenhuma subinterface do equipamento contém o endereço do peer: sem enlace não há VLAN nem prefixo. A proposta aparece assim mesmo, com o motivo. |
| `interface_ausente_na_coleta`, `endereco_fora_da_coleta`, `vrf_do_enlace_divergente` | A conferência cruzada com a interface brief da mesma coleta não bate (veja abaixo). |
| `sem_site` | O equipamento não está vinculado a um site — o IPAM é por site. |
| `vrf_nao_renderizavel` | O peer está numa VRF e esta versão do render emite toda sessão na instância pública: a sessão não é reproduzível, e adotá-la faria a renderização seguinte mudar a instância do peer no equipamento. |
| `asn_remoto_ausente` | A leitura pegou o peer sem a definição de `as-number`, e a sessão na SoT exige o ASN remoto: resolva no equipamento e colete de novo. |

## As duas conferências

A **conferência cruzada** compara com a interface brief da mesma coleta, que é a
única fonte da VRF a que o endereço pertence. Sem esse recurso na coleta, nada é
conferido: ausência de dado não é divergência, e coleta antiga simplesmente não
passa por aqui.

A **conferência de fidelidade** renderiza o que nasceria com a proposta e
compara com o bloco da configuração que a originou, mostrando o que sobra no
render e o que falta nele, em dois contextos: as linhas do peer e as da
subinterface. É o que impede a SoT de nascer mentindo — se o perfil de política
ainda não foi escolhido, o render não emite a route-policy, e a conferência diz
isso em vez de deixar passar. Ela roda o render de verdade (o mesmo código que a
adoção usaria) sobre um ensaio que é desfeito em seguida, então nada fica
gravado. Quando a comparação não pôde ser feita — peer em VRF, ou uma restrição
de unicidade que recusou o ensaio — ela devolve uma diferença de contexto
`ensaio` dizendo isso, em vez de sair como fiel. Ela aparece no
`gerenet discovery show`.

O limite dela, dito sem rodeios: a comparação cobre as linhas do peer e o bloco
da interface, e **não** o corpo das definições que o render emite junto com a
sessão (prefix-list, route-policies de importação e exportação, community-filter,
as-path-filter). Como o nome da route-policy deriva do ASN do par, escolher o
produto errado na revisão produz linhas de peer idênticas byte a byte com um
corpo de política completamente diferente, e a conferência não acusa diferença
nenhuma. Uma conferência limpa não é, por si só, prova de que o produto
escolhido é o certo.

## Página e CLI

| Onde | O que faz |
|---|---|
| Página **Migrar** | Lista as propostas (VLAN, subinterface, stack, QinQ, peers, código sugerido, veredito), abre o detalhe com reservas, pendências e conflitos, e mantém a lista de ignorados do equipamento. |
| `gerenet discovery list <equipamento>` | A mesma lista no terminal, mais os peers **internos (iBGP)**, que saem numa seção separada com a sugestão de ignorar — a página não os mostra. |
| `gerenet discovery show <equipamento> <peer>` | Uma proposta, com a conferência de fidelidade. |
| `gerenet discovery ignore <equipamento> <peer> [--afi] [--vrf] [--motivo]` | Tira **um peer** da lista. |
| `gerenet discovery unignore <equipamento> <peer> [--afi] [--vrf]` | Traz o peer de volta. |

O `--afi` e o `--vrf` existem porque a identidade do peer é a quádrupla
(equipamento, VRF, família, endereço). O botão **Não adotar** da página é mais
grosso: ele retira o **enlace inteiro** — num dual stack saem os dois peers,
IPv4 e IPv6. Para ignorar só um deles, use o CLI. O endereço é comparado na
forma canônica, então a caixa do IPv6 (`2804:194C:...` ou minúsculo) não decide
nada.

## O que ainda não existe

A adoção em si. Esta parte entrega a leitura e a lista de ignorados; cadastrar a
partir da proposta é a parte seguinte, e a lista de ignorados é o único caminho
de escrita. A leitura também não afirma mais do que leu: sem coleta com a
configuração a página diz que não há o que comparar, e se a leitura não entendeu
algum trecho da configuração ela diz isso — são dois avisos diferentes, e o
segundo pode significar lista incompleta.
