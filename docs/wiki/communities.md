---
title: Plano de communities
secao: Roteamento
secao_order: 3
order: 3
em_breve: false
---

# Plano de communities

O plano é o vocabulário de communities da rede como dado na SoT: as classes com
o valor de cada família, as instruções (o que fazer com a rota), os alvos (quem
recebe) e os portões (o filtro que decide o que sai para cada papel). Ele existe
porque o destino do export é a classificação: o filtro de saída deixa de
perguntar de que prefixo a rota veio e passa a perguntar que classe ela carrega.
Enquanto essa troca não chega ao render (veja "O que esta frente não faz"), o
plano já responde o que se pergunta no dia a dia — qual community eu uso para
isto, e se alguém a está testando?

## O que o plano tem

| Bloco | O que é |
|---|---|
| Classes | O valor de 2 bytes por família, a banda e o nome no namespace clássico (ex.: `com-TECMAIS-v4`, `3001`/`3101`). |
| Instruções | A large-community `61785:<código>:<alvo>`: proveniência, blackhole, cliente marcado, marca ERTEL e prepend. |
| Alvos | O grupo de peer (ou a sessão) que recebe a classe, com o papel, o código v4/v6 e o portão que o atende. |
| Portões | O filtro `RouteExportCheck*` que testa as classes, com o papel (`upstream`, `cdn`, `parceiro`, `ix`), o AFI e o que cada um aceita e recusa. |
| Regras de importação | Qual classe cada papel aplica na entrada (`cliente`, `parceiro`, `transito`). |

Classes e instruções dividem a mesma tabela (`communities`): a linha de classe
tem valor, a de instrução tem código, e a banda `instrucao` separa as duas. Os
quatro blocos restantes vivem em tabelas próprias do plano, e o plano ativo é
**um só**: o ASN principal é o cabeçalho dele.

## De onde ele vem

Da configuração **já coletada** — o snapshot mais recente do equipamento. Nada
vai ao equipamento em nenhum caminho desta página: nenhum comando novo é
enviado, e mudar o roteador continua sendo
[mudança controlada](/wiki/mudancas-controladas).

| Onde | Comando |
|---|---|
| CLI | `gerenet communities plan adotar <id-do-equipamento>` (o argumento é o **id**, não o nome) |
| API | `POST /api/v1/communities/plan/adopt` |

O que a adoção lê da configuração: as definições
(`community-filter`, `large-community-filter`, prefix-list e as-path-list), quem
aplica cada valor, quem testa, o que é citado sem definição e os grupos de peer —
exatamente o que o leitor da [descoberta](/wiki/descoberta) descarta de
propósito. Dali saem as classes, as instruções, os alvos e os portões.

Seis divergências nascem na proposta, para o operador decidir:

- o código de instrução ambíguo entre a borda e o virtual system (o `3` é marca
  ERTEL numa e prepend nível 3 na outra);
- o nome de definição que discorda da faixa que o valor ocupa;
- o papel do alvo duvidoso (o grupo com nome de CDN cujo papel real é trânsito);
- o portão cujo papel o nome não diz e a lista do que ele aceita não decide;
- o bloco de exceção que aplica community sob condição e não diz a que alvo
  pertence;
- a definição numerada que define um valor de classe sem nomear a classe (o
  número é o índice da lista, não um nome).

Um sétimo achado, o **membro de portão sem classe**, também é do operador: a
lista do portão guarda ids de `communities`, e um valor testado que não tem linha
de classe não teria id para gravar — ele sairia do portão adotado em silêncio. Ele
aparece na saída do `adotar` e no corpo do `201` da adoção, no `validar` do CLI e
na resposta de `GET /api/v1/communities/plan/validacao`, que é o mesmo que o painel
de divergências da página mostra.

A poda também é regra: sessão que não está Established não vira alvo, e vai para
uma lista de "configurado e parado" que o `adotar` imprime. E a adoção é
**idempotente por ASN principal**: adotar de novo com o mesmo ASN devolve o plano
em vigor e diz que nada foi gravado; um plano ativo de outro ASN principal é
recusado (409 na API), porque o plano é um só e trocar de ASN é decisão
explícita. Sem coleta legível a adoção não começa — o `adotar` sai 1 com a
mensagem do serviço, e a API responde 404.

## A partição

A partição é o contrato que faz um valor novo não precisar de reunião para ser
atribuído, e que deixa a validação reprovar um valor no lugar errado.

| Faixa | Banda | Uso |
|---|---|---|
| 1 a 99 | local | marcadores locais (o PTT-SP e os IX locais) |
| 1xxx | trânsito | trânsito full |
| 3xxx | cliente | a classe do cliente (`3001` v4, `3101` v6) |
| 4xxx | parceiro | a classe do parceiro (`4001`, `4101`) |
| 5xxx | conjunto | listas de clientes e parceiros (`5001`) |
| 7xxx | tamanho | as marcas de tamanho (`70xx` v4, `71xx` v6) |
| 9xx | especial | só CDN (`991`), troca v4/v6 (`992`/`993`) |

O padrão de quatro dígitos é `[classe][família][item]`, com `0` para v4 e `1`
para v6. As exceções têm nome próprio, e a validação as conhece:

- `1010` é família-agnóstico — a família viaja na large-community
  (`61785:4:1010` e `61785:6:1010`);
- `992` e `993` põem a família no último dígito;
- `666` é o código de blackhole e não pertence a faixa nenhuma;
- `11`, `90` e `91` são marcadores locais herdados.

Quem recusa na escrita é só a família trocada, que é sempre erro de digitação.
Valor fora de faixa é exceção legítima: ele entra no plano e a validação o aponta
como exceção a registrar.

## As duas grafias

O mesmo valor de 2 bytes aparece de duas formas, uma por namespace: `65000:3001`
no clássico, dos filtros de borda, e `61785:3001` no XPL, que é onde o caminho
novo de cliente escreve. As duas são a mesma classe.

A comparação, porém, é pelo **valor literal** — `61785:3001` não é
`65000:3001` —, e o portão precisa testar a grafia que o filtro aplica. Na
primeira leitura da configuração real, o filtro de cliente aplicava as classes no
namespace do XPL e nenhum portão testava esses valores: o caminho de cliente
seria recusado pelo upstream em silêncio. É o achado mais grave daquela leitura e
a razão de a validação existir. Na página, ele aparece no painel de divergências,
como classe aplicada e não testada. O selo *aplicada e não testada* da tabela de
classes é o mesmo uso lido por **código**, e no caso desta leitura ele não acende:
por código, a classe tem quem a aplique e quem a teste.

## O que a validação cobra

As oito checagens rodam sobre o plano e as leituras da configuração coletada:

1. **Quem aplica contra quem testa.** Classe aplicada e não testada (crítico),
   classe testada e não aplicada, instrução aplicada e não testada.
2. **Conformidade com a partição.** Valor fora da faixa da banda, dígito de
   família incoerente com o filtro, valor repetido em duas classes.
3. **Instrução órfã.** Código de large-community usado nos filtros sem linha no
   vocabulário, e código de alvo sem `community_targets`.
4. **Ordem da large-community.** O vocabulário fixa `61785:<código>:<alvo>`; o
   valor que só aparece na ordem invertida é apontado.
5. **Colisão entre namespaces.** O mesmo 2 bytes definido com dois nomes de
   significados diferentes.
6. **`apply community` sem `additive`** numa regra de import, que apaga as
   communities que o par mandou.
7. **Alvo sem sessão.** O alvo do plano cujo peer não está Established.
8. **Nome citado e não definido.** Filtro, lista ou prefix-list referenciado na
   configuração e sem definição em lugar nenhum.

No terminal, `gerenet communities plan validar [--device <id>]`; na API,
`GET /api/v1/communities/plan/validacao`. O `validar` só atesta alinhamento
quando **leu** alguma configuração: com `--device` sem coleta legível ele sai 1
com a mensagem do serviço, e sem `--device` sai 1 quando nenhum equipamento tem
coleta legível. Sem plano adotado ele sai 0 avisando que não há o que validar, e
sai 1 quando encontra achado crítico — é o código de saída que autoriza (ou
barra) a automação.

## Onde consultar e operar

| Onde | O que faz |
|---|---|
| Página **Comunidades · Plano** (`/communities/plan`, grupo Roteamento) | O plano em vigor: cabeçalho (ASN principal, ASNs anunciados e a origem), classes e instruções com quem aplica e quem testa (e o selo de situação), matriz classe × papel, alvos com o estado da sessão e o painel de divergências. |
| `gerenet communities plan show` | O plano em vigor no terminal, com quem aplica e quem testa. |
| `gerenet communities plan validar [--device <id>]` | As oito checagens contra a configuração coletada. |
| `gerenet communities plan adotar <id-do-equipamento>` | Lê a coleta e grava o plano na SoT. |
| `gerenet communities list` | O catálogo, agora com o valor v4/v6 e a banda de cada linha. |
| `GET /api/v1/communities/plan` · `GET .../plan/validacao` · `POST .../plan/adopt` | As mesmas operações na API. |

O painel de divergências da página mostra os achados da validação com a
severidade, o filtro, a linha no equipamento e a ação sugerida, e ele distingue
"está carregando" de "não foi possível ler": sem a resposta da validação ele não
afirma que o plano está alinhado. A tabela de classes e a matriz contam o uso por
**código** (a definição citada entra pelo corpo dela), enquanto o painel aponta a
linha pelo **valor literal** — a mesma classe pode aparecer com quem a testa numa
e vir de lá como aplicada e não testada, sem que nenhuma das duas leituras esteja
errada.

## O que esta frente não faz

- **O render não mudou.** O export continua saindo como saía. Consumir o plano —
  o import classificando por papel, os produtos como conjunto de classes e os
  filtros por alvo — são as fatias seguintes.
- **A edição do plano é da frente seguinte.** Em F1 o plano é adotado, não
  autoral: a página consulta, e a adoção passa pelo CLI e pela API. Editar à mão
  sem que nada consuma o dado criaria uma segunda fonte para a mesma coisa.
- **Mudar o roteador continua sendo change request.** Os valores fora da
  partição, os nomes citados sem definição e a ordem invertida da
  large-community são achados para corrigir no equipamento, e a correção vai pelo
  [fluxo de mudanças](/wiki/mudancas-controladas), com plano e aprovação.

## Ponto de partida

- [Sessões BGP, autorizações, perfis e communities](/wiki/roteamento) — o
  catálogo de communities e os conceitos de sessão que o plano classifica.
- [Upstreams e políticas avançadas](/wiki/upstreams) — as communities de
  operadora, que a F1 deixa como estão.
- [Migrar — descoberta de peers na configuração](/wiki/descoberta) — a outra
  leitura do mesmo arquivo de configuração.
- [Mudanças controladas](/wiki/mudancas-controladas) — como uma correção no
  equipamento é aplicada.
