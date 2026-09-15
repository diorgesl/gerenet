# Runbook — Task 13: validação fim a fim contra NE8000 real (read-only)

> Fase 1 (cortes 0–2) está implementada e testada (26 tests). Esta é a **validação manual**
> contra um NE8000 real ou de homologação, executada por você — o código não será alterado
> por esta task, exceto o fixture golden e o template TextFSM **se a saída real divergir**.
> Tudo aqui é **read-only no equipamento**: a allowlist do gerenet só aceita comandos `display`.

**Pré-requisitos:** compose dev de pé (`docker compose up -d` — postgres/redis/vault), acesso SSH
read-only ao NE8000 com conta de automação identificável (§19 da spec), e o NE8000 alcançável
pela máquina onde o worker vai rodar.

---

## Passo 1 — Capturar a saída real de `display version` (manual, no equipamento)

Conecte no NE8000 e execute:

```
display version
```

Salve a saída exata em `tests/fixtures/huawei_vrp/ne8000_display_version.txt`.
**Revise o conteúdo antes de versionar** — `display version` não traz configuração, mas confira
mesmo assim (nada de IPs de gerência, hostnames sensíveis etc.). É a única saída do equipamento
que entra no git, e sanitizada.

## Passo 2 — Teste golden com a captura real

Crie `tests/automation/test_parsers_golden.py`:

```python
from pathlib import Path

from gerenet.automation.parsers.huawei_vrp.registry import parse_template

FIXTURE = Path("tests/fixtures/huawei_vrp/ne8000_display_version.txt")


def test_parse_version_contra_captura_real() -> None:
    saida = FIXTURE.read_text(encoding="utf-8")
    linhas = parse_template("version", saida)
    assert len(linhas) == 1
    assert linhas[0]["version"]  # versão VRP identificada
    assert linhas[0]["uptime"]
```

Rode:

```bash
uv run pytest tests/automation/test_parsers_golden.py -v
```

Se o template não capturar a versão/uptime da saída real (formato diferente, ex.: NE40/VRP5),
ajuste `src/gerenet/automation/parsers/huawei_vrp/textfsm/version.template`, atualize o fixture
e re-rode. Registre no commit o padrão real observado.

## Passo 3 — Registrar device, host key e credencial no gerenet

**3a. Descobrir o fingerprint real (formato OpenSSH `sha256:`)** — troque `<porta>` pela
porta SSH real (ex.: `-p 61341`; `ssh-keygen -lf` lê do stdin com `-f -`, não `-` solto):

```bash
ssh-keyscan -p <porta> -t rsa <ip-mgmt> 2>/dev/null | ssh-keygen -lf -E sha256 -f -   # anotar "SHA256:..."
```

**3b. Cadastrar o device** (nomes VRP derivam do ASN em fases futuras; aqui use um nome de lab):

```bash
uv run gerenet devices add --name <nome> --address <ip-mgmt> --ssh-port <porta> --family ne8000 --role borda
```

**3c. Registrar o fingerprint** (é validado em TODA conexão — fail-closed; erro de digitação
bloqueia a coleta de propósito, e é o comportamento correto):

```bash
uv run gerenet hostkey register <nome> SHA256:<fingerprint-real>
```

**3d. Semear a credencial no Vault** (nunca em banco/arquivo/git — só Vault):

```bash
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet vault seed --username gerenet-auto --password '<senha-da-conta>'
```

> O path no Vault é `gerenet/credential-groups/automacao`. Se este seed já foi feito na Fase 1,
> ele é idempotente — pode rodar de novo sem duplicar.

**3e. Associar o device ao grupo de credencial no banco** (o CLI `devices add` ainda não expõe
`--credential-group` — gap conhecido, anotado no ledger; o SQL abaixo resolve):

```bash
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "insert into credential_groups (name, kind, vault_path) values ('automacao','tacacs_password','gerenet/credential-groups/automacao') on conflict do nothing;"
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "update devices set credential_group_id = (select id from credential_groups where name='automacao') where name='<nome>';"
```

Confira o cadastro:

```bash
uv run gerenet devices list
```

## Passo 4 — Coleta fim a fim (read-only)

**Terminal A — worker:**

```bash
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet-worker
```

**Terminal B — disparar e conferir:**

```bash
uv run gerenet collect run --device <nome>
```

Aguarde o worker processar (log do RQ no Terminal A) e confira:

```bash
uv run gerenet snapshot show <id-do-snapshot>
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "select id, device_id, status from job_runs order by id desc limit 5;"
docker compose exec -T db psql -U gerenet -d gerenet -c \
  "select name, comm_status, vrp_version, uptime, last_collected_at from devices;"
```

**Esperado:**
- snapshot com `status=success` (ou `partial` se um recurso falhar);
- device com `comm_status=ok`, `vrp_version` e `uptime` preenchidos, `last_collected_at` atualizado;
- `job_runs` com `status=success` e `snapshot_id` apontando para o snapshot;
- 2 arquivos brutos em `data/backups/<nome>/<timestamp>/version/version.txt` e
  `data/backups/<nome>/<timestamp>/config_backup/current-configuration.txt`
  (a config bruta **nunca** é versionada nem exibida em logs — `data/` é gitignored).

## Passo 5 — Se algo falhar

- **`HostKeyMismatch`**: o fingerprint registrado não confere com o do servidor — refaça o
  passo 3a/3c. É fail-closed: nenhum comando roda com host key não validada.
- **`CommandNotAllowed`**: algum comando fora da allowlist `^display` — não acontece com os
  coletores atuais; se ocorrer, é bug — reporte.
- **Falha de conexão/timeout**: confira alcance, porta 22 e conta; nada é escrito no equipamento.
- **Snapshot `error`/`partial`**: `snapshot show <id>` exibe `resources`/`errors`; o erro por
  recurso fica no `AuditEvent` (`type='collect.errors'`).

## Passo 6 — Commit

```bash
git add -A
git commit -m "feat: validação fim a fim da coleta contra NE8000 real

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

**Regras inegociáveis:** nenhuma credencial em git/banco/logs; nenhum comando fora da allowlist;
nenhum backup/config bruto versionado; nada de escrita no equipamento (esta fase é read-only).

---

## Critérios de aceite (cortes 0–2, do plano)

Executada em 2026-09-02 contra NE8000 real (VRP 8.240, gerência na porta 61341).

- [x] `uv run pytest` verde com o compose de pé (32 tests, golden real incluso)
- [x] CLI: `devices add|list`, `hostkey register`, `vault seed`, `collect run`, `snapshot show` funcionando
- [ ] API: `/healthz`, CRUD de devices autenticado, `POST /devices/{id}/collect` (202/409/404), snapshots
      — coberta pela suíte (32 passed); sem chamada manual via curl nesta execução
- [x] Coleta real read-only de 1 NE8000: snapshot `success` com `version` parseado (8.240 + uptime),
      backup em `data/backups/ne8k-lab/` (config 172.6K, gitignored), device atualizado
      (`comm_status=ok`, `vrp_version=8.240`, `last_collected_at`), `job_runs`/`audit_events` íntegros
- [x] Nenhuma credencial em git/banco/logs; host key validada antes de toda conexão (fail-closed
      demonstrado ao vivo: fingerprint errado ⇒ coleta recusada sem executar comando);
      nenhum comando fora da allowlist

Observações da execução: worker no macOS precisa de `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`
(crash do fork do RQ × runtime ObjC — não afeta container Linux); `ssh-keyscan -t rsa` não basta
se o servidor negocia outra chave — registrar a que o paramiko recebe (o erro de host key mostra).

---

# Runbook — validação da descoberta (`Migrar`) contra NE8000 real (leitura do equipamento, escrita na SoT)

> A descoberta (spec §13) lê o `display current-configuration` **já coletado**, propõe o que
> cadastrar e — na parte 2 — grava a proposta adotada **na SoT**. Nenhuma etapa da leitura
> abre sessão SSH no equipamento: nem abrir a página, nem rodar o CLI, nem mexer na lista de
> ignorados, nem adotar. Quem fala com o equipamento é só a coleta (Passos 1 a 4 acima), e
> ela executa apenas comandos `display`. A **única** etapa que escreve no equipamento é o
> rollback da Etapa 3, e é por isso que a adoção é validada num equipamento não crítico.
>
> O que esta validação procura é **onde a leitura da configuração errou** e o que a adoção
> grava. O parser é novo, e a fixture que o testa é derivada, não capturada (o checklist no
> fim lista o que conferir contra a captura do equipamento).

## Etapa 1 — Coletar e abrir a página

Com o worker de pé (Passo 4), colete o NE8000 de produção/homologação. A descoberta sai do
snapshot mais recente **que tenha a configuração salva**, então confira que o recurso veio:

```bash
uv run gerenet snapshot show <id-do-snapshot>      # config_backup e interfaces presentes
uv run gerenet discovery list <equipamento>        # a lista no terminal
```

Na web, a página **Migrar** (grupo Operação) faz a mesma leitura: escolha o equipamento e
confira o veredito de cada proposta. O aviso no topo da lista, quando aparece, diz o que a
leitura não entendeu — **leia-o primeiro**, porque ele já aponta onde a captura divergiu do
que o parser espera (e lista parcial é uma das duas leituras possíveis dele).

## Etapa 2 — Conferir as propostas contra a configuração real

Para cada proposta, abra a configuração do equipamento ao lado e confira, campo a campo:

- **VLAN** — o `vid` da proposta é o da linha `vlan-type` da subinterface citada? Em QinQ
  (coluna `QinQ` = "sim"), aparece a VLAN empilhada, não só a externa?
- **Subinterface** — o nome é o da configuração (`Eth-Trunk127.1001`), e é nele que o peer
  aparece? Duas subinterfaces com o mesmo VID são dois enlaces, e não um.
- **Endereços** — os prefixos da proposta são o par (`/30`, `/31` ou `/126`) em que o peer
  está, com a **ponta** certa (qual dos dois endereços é o do roteador)? Um endereço de
  rede compartilhada (IX) precisa sair como conflito `enlace_nao_p2p`, não como proposta
  adotável; um endereço do par que **não** é nenhuma das duas pontas (o `/30` com o
  roteador no `.3`, cujas pontas são `.1` e `.2`) sai como `ponta_incoerente`, sem reserva
  e sem sessão.
- **ASN** — o ASN remoto é o do `as-number` do peer, e o local é o do bloco `bgp`? Peer sem
  `as-number` lido tem de sair como `asn_remoto_ausente`.
- **Políticas** — a route-policy que a configuração aplica vira pendência de perfil (o
  produto não é recuperável do nome), e a linha dela aparece na conferência de fidelidade.
  Peer em VRF sai como `vrf_nao_renderizavel`, e não como proposta adotável.
- **Peer sem `enable`** — peer declarado e sem `peer ... enable` em nenhuma família sai como
  pendência `peer_nao_habilitado`, e não como sessão limpa: adotá-lo ativaria um resto de
  configuração (a assunção 11 do checklist é o outro lado disso).
- **Stack e classificações** — enlace com peer v4 e v6 na mesma subinterface sai como `dual`,
  e cada peer com a classificação (downstream/upstream) que o ASN sugere.

O detalhe (pendências, conflitos, reservas com a ponta) e a conferência de fidelidade saem
no terminal:

```bash
uv run gerenet discovery show <equipamento> <endereço-do-peer>
```

A conferência de fidelidade é a que mais rende nesta validação: ela mostra, linha a linha, o
que o render emitiria e a configuração não tem, e o que a configuração tem e o render não
emitiria. Diferença de fidelidade não é necessariamente erro: o equipamento pode ter uma
política que o sistema ainda não conhece. Linha estranha é onde o parser errou.

Confirme também que, **até aqui**, a descoberta não mexeu em nada: nenhuma sessão, circuito
ou VLAN nova na SoT (a lista de ignorados é a única escrita desta etapa, e é só na SoT).

## Etapa 3 — Adotar num equipamento não crítico, com o rollback ao lado

As Etapas 1 e 2 conferiram a leitura. Esta é a única que **escreve**, e escreve em dois
lugares: na SoT (a adoção) e, se o rollback for executado, no equipamento. Por isso ela é
feita num equipamento e num enlace **não críticos** — um circuito de teste/homologação, ou o
enlace menos sensível da borda —, nunca num cliente em produção.

**Prepare o rollback antes de adotar.** É uma CR de remoção do circuito que vai nascer: como
o enlace existe no equipamento (foi isso que a descoberta acabou de ler), tirar o circuito da
SoT não desfaz nada lá — quem desfaz é a remoção, com o `undo peer` e o `undo interface` que
o plano dela mostra. Aprove a CR **antes** da adoção (a regra de sempre: rollback aprovado
antes da mudança) e deixe-a parada. Só a execute se a decisão for desfazer: ela é a única
etapa deste runbook que manda comando ao equipamento.

**Adote pela revisão.** Na página **Migrar**, abra a proposta do enlace e confira antes de
aceitar:

- o grupo **Diferenças que mudariam o equipamento** tem de estar vazio, ou ter só linha que
  você sabe explicar — é o que o `ciente` assume, e ele fica registrado na auditoria;
- o grupo **O que a SoT não gerencia** (o `description` e o MTU da subinterface) é o
  esperado, e não gateia nada;
- o trunk derivado do nome da subinterface, o equipamento/porta de acesso e a organização
  estão certos;
- os perfis de importação e exportação são os deste enlace: é o produto deles que o render
  emite, e é o corpo dessas políticas que a conferência de fidelidade compara.

**Confira o que nasceu.** O circuito na lista de **Circuitos**, com a VLAN e o par p2p
reservados **nos valores reais** do equipamento (não nos que o alocador daria) e a sessão no
**Roteamento**, com o ASN local do equipamento e o remoto lido da configuração. Em
`gerenet discovery list <equipamento>`, a proposta adotada tem de ter saído da lista. E na
auditoria, o evento `discovery.adopt` com o snapshot de origem, o `ciente` e o diff inteiro,
com os dois grupos: o que não estiver lá não foi decidido por ninguém.

Duas notas desta etapa:

**O nome da subinterface.** O projeto assume que ele **termina no VID** (`Eth-Trunk127.1001`)
— é assim que o render o monta (`<trunk>.<vid>`), e é desse sufixo que a revisão deriva o
trunk. Num nome fora da convenção o campo do trunk nasce **em branco**, para ser digitado à
mão, e o diff mostra a linha `interface <trunk>.<vid>` que o render emitiria e o equipamento
não tem: diferença que exige `ciente`. Não é erro da leitura — é o que a adoção assumiria —,
e vale registrar quantos enlaces deste equipamento estão fora da convenção.

**O VID.** Os IDs de VLAN da SoT vão de **2 a 4094**. Um número maior que apareça na
configuração (o TPID em decimal — `34984`, assunção 14 do checklist —, ou um ID de serviço
lido como VLAN) não é uma VLAN: se ele virar o VID de uma proposta, a adoção recusa na
reserva com `VID fora do intervalo permitido (2–4094)`. É caso para o registro da Etapa 2, e
não para o `ciente`.

## Etapa 4 — Registrar o que a leitura errou

Para cada divergência, anote a linha exata da configuração, o que a leitura devolveu e o que
era o certo, e o item do checklist abaixo a que ela corresponde. É esse registro que vira
correção do parser (`src/gerenet/automation/parsers/huawei_vrp/config_vrp.py`, com teste em
`tests/automation/test_config_vrp.py`) — nada além disso.

**A configuração real não vira fixture sem sanitização.** Config crua tem endereço de
gerência, descrições de cliente e linha de senha: ela fica em `data/backups/` (gitignored),
como as outras. Para virar fixture, sanitize (endereços, descrições, `password`, `sysname`)
— e o valor de senha nunca entra, nem mascarado de forma reversível.

## Checklist — o que o parser assume sobre o VRP

A fixture `tests/fixtures/huawei_vrp/ne8000_display_current_configuration.txt` é
**derivada, não capturada**: foi escrita a partir dos templates deste projeto
(`bgp_peer.j2`, `subinterface.j2`) e das formas de linha do §6 da spec, e nunca foi
comparada com um equipamento de verdade. As linhas que **não** vêm do render e portanto não
têm nenhuma evidência interna no repositório são: `peer X route-policy N import`,
`peer X ip-prefix N import`, `peer X password cipher ...`, `vlan-type dot1q <vid>` (sem a
palavra `vid`), `ipv6 address <endereço> <comprimento>` e `vlan-type qinq <vid>`. É aí que
a captura real tem mais chance de contradizer o parser.

Cada linha abaixo é uma assunção da leitura; marque conforme conferir na captura.

| # | O que a leitura assume | O que conferir na captura real |
|---|---|---|
| 1 | Linha sem espaço nem tabulação à esquerda abre bloco (`interface`/`bgp`) e qualquer indentação é sub-comando — a profundidade não é contada. | A captura não indenta tudo nem embrulha a config em um nível: indentação uniforme faz o parser perder o bloco inteiro. |
| 2 | Comentário — qualquer linha começando com `#`, e não só a linha `#` sozinha — é ignorado antes da regra de contexto; `sysname`, `return` e blocos de topo que não são `interface`/`bgp` não interferem. | As linhas `#` estão lá, e nenhum bloco de topo vem indentado. Confira também se a captura traz **`# texto` dentro de um bloco** (o render deste projeto emite, ex.: `# password no Vault ...` no `bgp` e `# second-dot1q ...` na `interface`): tratada como bloco de topo, ela fechava o bloco ali mesmo e os peers e endereços escritos depois dela saíam da leitura — é o que a regra de hoje evita. |
| 3 | As seções de família são `ipv4-family unicast`, `ipv6-family unicast` e `ipvN-family vpn-instance <nome>` — e a VRF é **tudo o que resta da linha** depois de `vpn-instance`. | O VRP não escreve nada depois do nome da VRF (um `... vpn-instance VPNA unicast` faria a VRF sair como `"VPNA unicast"`). |
| 4 | Existe um bloco `bgp` só, e o ASN local de todos os peers vem dele. | A captura tem um bloco `bgp`; com dois, o ASN que vale para um peer é o do bloco onde ele apareceu primeiro. |
| 5 | A config vem do `display current-configuration` inteiro. | A captura não está truncada nem tem cabeçalho/paginador do terminal no meio. |
| 6 | As linhas são `peer <endereço> <atributo> ...`, e as globais e as da seção de família caem no mesmo registro, com **um valor por atributo**. | Um mesmo endereço em duas famílias com `maximum-prefix` diferente: fica o último lido. |
| 7 | A direção da route-policy é decidida pelo token `export` na linha: `peer X export route-policy N` e `peer X route-policy N export` são a mesma coisa. | **Qual das duas grafias o `display` emite** (o render escreve a primeira, a forma clássica é a segunda). |
| 8 | `peer X ip-prefix <nome> import` é a grafia da prefix-list de import. | O render não emite essa linha: é a forma a confirmar, sem evidência interna. |
| 9 | Os timers vêm numa linha só, `timer keepalive H hold T`, com `hold` depois de `keepalive`. | A forma da captura; uma linha só com `hold` não é lida, e a assimetria com `keepalive` é do parser. |
| 10 | `password cipher <valor>`: só a palavra `password` é lida (qualquer algoritmo) e o valor nunca é guardado. | Que o `display` mostra a senha nessa forma (`password simple` também marcaria presença) — e que a captura seja sanitizada antes de virar fixture. |
| 11 | `habilitado` sai de `peer X enable` na seção de família; o `undo peer X ... enable` não casa com nenhum ramo. | Se o equipamento emite a linha `enable` para os peers ativos: **sem ela, todo peer descoberto vem desabilitado**. |
| 12 | `shutdown` tem um flag só, no nível do peer. | Onde o `shutdown` aparece: no nível global (como o render escreve) ou dentro da seção de família (hoje marcaria o peer inteiro como desligado). |
| 13 | Nome de grupo no lugar do endereço (`peer IBGP enable`) é descartado. | Se a captura cadastra peer por **grupo** — ele não aparece na descoberta, por decisão. |
| 14 | O VID é o primeiro número depois de `dot1q`, e o QinQ é marcado pelo TPID `0x88a8`. | Se o TPID aparece em **decimal** (`34984`): o primeiro número da linha viraria o TPID, e tanto o VID quanto o QinQ sairiam errados. |
| 15 | `vlan-type qinq <vid>` também marca QinQ. | A marcação do QinQ neste equipamento é `vlan-type qinq` ou `vlan-type dot1q 0x88a8 vid`? A primeira grafia só existe no teste. |
| 16 | `mtu <n>` dentro do bloco da interface, sem unidade; o MTU herdado da interface principal não é propagado. | O MTU da subinterface aparece no bloco dela, e com o valor que o cadastro espera. |
| 17 | `ip address <endereço> <máscara decimal pontuada>`; o secundário vem em outra linha, com `sub` no fim. | A forma do secundário; com comprimento no lugar da máscara (`... 31`) o par sai como está e continua servindo. |
| 18 | `ipv6 address` com comprimento separado por espaço (`... 126`) ou com barra (`.../126`). | Qual das duas o NE8000 emite — as duas têm teste hoje. |
| 19 | A interface principal (`Eth-Trunk127`) entra no resultado sem VLAN e sem endereços. | Ela não vem com `vlan-type` nem endereço, senão a proposta pode pegar o enlace errado. |
| 20 | `ipv6 address auto link-local` / `eui-64` e `ip address unnumbered` / `dhcp-alloc` são descartados. | Se os enlaces deste produto usam `eui-64` no IPv6: esses endereços não aparecem na descoberta. |
| 21 | `as-number` em asdot (`65535.100`) não converte para inteiro. | Se a captura traz o ASN em asdot: hoje isso vira aviso e o peer fica sem ASN, o que o torna não adotável (`asn_remoto_ausente`). |

Quando a leitura não entende um cabeçalho de seção ou um valor (VID, MTU, ASN, timers,
`maximum-prefix`), ela devolve **aviso** em vez de estourar, e o aviso chega à página e ao
CLI. Aviso na tela e configuração aparentemente certa é sinal de que o item correspondente
deste checklist precisa de ajuste.

## Critérios de aceite

- [ ] Coleta real de 1 NE8000 com `config_backup` e `interfaces` presentes no snapshot
- [ ] `gerenet discovery list` e a página Migrar concordam nas propostas e nos vereditos (o
      CLI mostra ainda os peers internos, numa seção que a página não tem)
- [ ] Cada proposta conferida contra a configuração real (VLAN, subinterface, endereços,
      ASN, políticas) — divergências registradas com a linha da captura
- [ ] Conferência de fidelidade rodada em pelo menos uma proposta (`discovery show`)
- [ ] Um enlace **adotado** num equipamento não crítico, com o rollback (a CR de remoção do
      circuito) aprovado antes da adoção
- [ ] O circuito adotado confere com a configuração lida: VLAN e par p2p nos valores reais
      do equipamento, sessão com o ASN remoto lido, e a proposta fora da lista depois
- [ ] Auditoria do `discovery.adopt` com o snapshot de origem, o `ciente` e o diff inteiro
      (os dois grupos)
- [ ] Nenhuma linha do checklist acima sem conferência (ou marcada como não observável na
      captura)
- [ ] Comando ao equipamento só na CR de rollback, e só se ela for executada; fora as
      reservas do enlace adotado (e a lista de ignorados, se usada), nenhuma linha nova na
      SoT
- [ ] Config crua fora do git (`data/backups/`); nenhum valor de senha em log, resposta ou
      fixture
