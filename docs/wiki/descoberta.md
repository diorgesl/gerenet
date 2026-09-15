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
que cadastrar — e cadastra dali mesmo, na revisão de cada proposta.

## O que ela lê, e o que ela nunca lê

Lê só o que a coleta já trouxe: o `display current-configuration` e o recurso
`interfaces` (as três saídas `display ... interface brief`) do snapshot mais
recente **que tenha a configuração salva** — coleta anterior a este recurso não
serve de fonte. Todo o trabalho é leitura de texto já gravado. **Nenhum comando
é enviado ao equipamento em nenhum momento**: nem ao abrir a página, nem ao
rodar o CLI, nem ao mexer na lista de ignorados, nem ao adotar uma proposta.
Quem fala com o equipamento continua sendo só a [coleta](/wiki/operacao).

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
render e o que falta nele. Ela cobre o que a proposta tocaria, em três
contextos de comparação — as linhas do peer (`peer`), o bloco da subinterface
(`subinterface`) e o corpo das definições que a sessão referencia (`definicao`:
o que o peer nomeia e o que essas definições nomeiam) — e devolve um quarto, o
`ensaio`, que não é comparação e sim o registro de que ela não pôde ser feita.
É o que impede a SoT de nascer mentindo: escolher o produto errado na revisão
muda o corpo das route-policies, e é isso que a conferência acusa.

Ela roda o render de verdade (o mesmo código que a adoção usaria) sobre um
ensaio que é desfeito em seguida, então nada fica gravado. Na revisão da página,
o ensaio recebe o que o operador escolheu — os perfis de cada família e o trunk
—, porque ele tem de ter a forma do que a adoção **vai** gravar; no
`gerenet discovery show`, sem essas escolhas, a comparação é a da proposta como
ela está na lista. Quando a comparação não pôde ser feita — peer em VRF,
proposta sem site ou sem candidato, ou uma restrição de unicidade que recusou o
ensaio — ela devolve a diferença de contexto `ensaio` dizendo isso, em vez de
sair como fiel.

O limite dela, dito sem rodeios: a comparação cobre o que **esta proposta**
tocaria. O resto da configuração do equipamento não entra, e a conferência não
afirma nada sobre ele — uma conferência limpa diz que o enlace da proposta é
reproduzível, não que o equipamento inteiro esteja. O grupo que a SoT não
gerencia (veja abaixo) também aparece sem bloquear: ele é leitura, não gate.

## Página e CLI

| Onde | O que faz |
|---|---|
| Página **Migrar** | Lista as propostas (VLAN, subinterface, stack, QinQ, peers, código sugerido, veredito), abre o detalhe com reservas, pendências e conflitos, mantém a lista de ignorados do equipamento e adota pela revisão. |
| Revisão **Adotar** (na linha da lista) | Os campos que só o operador sabe e o diff da conferência, com o aceite. É a única superfície **da página** onde o `ciente` aparece. |
| `gerenet discovery list <equipamento>` | A mesma lista no terminal, mais os peers **internos (iBGP)**, que saem numa seção separada com a sugestão de ignorar — a página não os mostra. |
| `gerenet discovery show <equipamento> <peer>` | Uma proposta, com a conferência de fidelidade. |
| `gerenet discovery adopt <equipamento> <peer> --json <arquivo> [--ciente]` | Adota a proposta a partir de um arquivo de revisão (`AdocaoIn`), sem passar pela tela; o `--ciente` é o mesmo aceite da caixa. |
| `gerenet discovery ignore <equipamento> <peer> [--afi] [--vrf] [--motivo]` | Tira **um peer** da lista. |
| `gerenet discovery unignore <equipamento> <peer> [--afi] [--vrf]` | Traz o peer de volta. |

O `--afi` e o `--vrf` existem porque a identidade do peer é a quádrupla
(equipamento, VRF, família, endereço). O botão **Não adotar** da página é mais
grosso: ele retira o **enlace inteiro** — num dual stack saem os dois peers,
IPv4 e IPv6. Para ignorar só um deles, use o CLI. O endereço é comparado na
forma canônica, então a caixa do IPv6 (`2804:194C:...` ou minúsculo) não decide
nada.

## A revisão

Cada linha da lista abre a revisão pelo botão **Adotar**: um formulário com o
que o operador decide e, ao lado, o diff da conferência. Nada é gravado enquanto
ele não aceitar.

| Campo | De onde vem |
|---|---|
| Código do circuito | Sugerido da proposta (`ADOC-<ASN>-<VID>`), livre para trocar. |
| Equipamento e porta de acesso | Em branco: a configuração do edge não diz de que switch e porta o cliente chega. |
| Trunk do edge | Derivado do nome da subinterface (`Eth-Trunk127.<vid>`) — é com ele que o render monta `<trunk>.<vid>`. |
| Organização | De uma lista (as desativadas aparecem com o rótulo) ou **Criar a nova**, com o nome digitado e o ASN do peer. |
| Perfil de importação e de exportação | Por família: é o produto da política que o render emite. |
| Caminho do segredo no Vault | Por família, quando o peer tem senha — o valor do segredo nunca passa pela tela. |

O que a revisão mostra e não se edita: as reservas que serão gravadas (VID, rede
e ponta) e os endereços e ASNs das sessões. A classificação do peer **com o
motivo**, as pendências e os conflitos que a leitura levantou são do **Detalhes**
da linha — outra janela, não a revisão. O aceite fica **desabilitado** enquanto um
obrigatório estiver vazio, fora da forma ou acima do tamanho do schema — com o
motivo escrito ao lado do campo.

O aceite vale para o diff que está na tela: mexer num campo que entra na
comparação (o perfil, o trunk) refaz a conferência e desmarca a caixa sozinho.

## O diff, em dois grupos — e só um bloqueia

- **Diferenças que mudariam o equipamento**: linha que o render emitiria e o
  equipamento não tem, ou o contrário. É o que a configuração mudaria se fosse
  aplicada, e é este grupo que exige o `ciente`.
- **O que a SoT não gerencia**: linha que o equipamento tem e o render não emite
  de propósito — hoje o `description` e o `mtu` da subinterface. Numa borda real
  elas estão em toda proposta, e "diferença exige `ciente`" degeneraria em
  "marque sempre". Ficam visíveis, para leitura, e não gateiam nada.

O `ciente` é a caixa **Estou ciente destas diferenças**, e só aparece quando o
primeiro grupo tem alguma linha — o que a SoT não gerencia não é assumido por
ninguém. Sem ele, a adoção recusa com 422; com ele, as diferenças que a
conferência viu, dos dois grupos, vão para a auditoria do evento
`discovery.adopt`: "eu sabia" é uma decisão, e decisão precisa de dono.

Se a comparação não pôde ser feita — a diferença de contexto `ensaio` —, a
adoção fica bloqueada, e não há `ciente` que a libere.

## O que a adoção grava

Uma transação só, e nada é enviado ao equipamento:

1. a organização, quando a revisão pede uma nova (o ASN é o do peer);
2. o circuito, com o acesso e o trunk da revisão e a stack derivada das sessões
   que nascem;
3. as reservas **pelos valores reais** da proposta — o VID e o par p2p que o
   equipamento já usa, e não o que o alocador daria: aqui quem manda é a
   configuração lida, e o snapshot de origem fica gravado na reserva;
4. uma sessão por família, com o ASN local do equipamento e o remoto lido da
   configuração;
5. o evento `discovery.adopt`, com o snapshot, o `ciente` e o diff inteiro.

Se qualquer passo recusar, tudo é desfeito: não existe adoção parcial. A
proposta adotada sai da lista sozinha, porque a lista é recalculada do que a SoT
já conhece. E a adoção grava a **intenção**: quem escreve na configuração do
equipamento é a [mudança controlada](/wiki/mudancas-controladas), com aprovação
— a adoção não manda um comando sequer.

## O que a leitura não afirma

A leitura não afirma mais do que leu: sem coleta com a configuração a página diz
que não há o que comparar, e se ela não entendeu algum trecho da configuração
ela diz isso — são dois avisos diferentes, e o segundo pode significar lista
incompleta. O `gerenet discovery adopt` imprime o aviso antes de gravar, mesmo
tendo achado a proposta: a escrita vai para a SoT, e gravar a partir de uma
leitura que a ferramenta marca não pode acontecer em silêncio.
