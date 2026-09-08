# Runbook — validação em equipamento real da fase 5 (upstreams)

> A fase 5 está implementada e testada (upstreams §7 com organização
> `operadora`, communities da operadora com valor concreto, autorizações com
> origem IRR/RPKI consultiva, change request de escopo `upstream` no fluxo do
> ciclo D, páginas web `/upstreams`). Esta é a **validação manual contra os
> roteadores reais de borda** (NE8000), executada por você — o código só é
> alterado se a saída real divergir (ajuste de TextFSM/templates, único desvio
> previsto). A validação é **em produção, sem laboratório** — decisão
> consciente do usuário (2026-09-07, mesmo posicionamento da fase 4); o máximo
> de segurança é um **circuito de teste / edge não crítico**, e a mudança
> segue a implantação gradual do §21 da spec. **Nada executa mudança sem
> aprovação (§3.3 inegociável).** São 5 etapas: (1) somente leitura;
> (2) geração sem execução; (3) execução de teste em circuito/edge não
> crítico com aprovação; (4) IRR/RPKI consultivo; (5) contingência — com
> plano de rollback aprovado antes da execução.

**Pré-requisitos:** compose dev de pé (`docker compose up -d` —
postgres/redis/vault), worker com credenciais no Vault e host keys
registradas para os roteadores de borda, equipamentos alcançáveis pela
máquina do worker, contas de usuário com papéis de operador e aprovador.
Nada aqui funciona sem o worker para a Etapa 3 (a fila `gerenet-change`
executa a mudança).

---

## Referência rápida — o que a CR de escopo `upstream` gera

Fonte: `src/gerenet/automation/upstream.py` (plano agregado por device) e
templates em `src/gerenet/automation/templates/huawei_vrp/`. O plano junta,
por device, os blocos das sessões e dos circuitos vinculados:

```
bgp <asn-local>
peer <remoto> as-number <asn-remoto>
peer <remoto> description <descricao>
peer <remoto> timer keepalive <k> hold <h>       # quando keepalive+holdtime na sessão
peer <remoto> graceful-restart                   # quando habilitado
peer <remoto> bfd enable                         # quando habilitado
ipv4-family unicast (ou ipv6-family unicast)
  peer <remoto> enable
  peer <remoto> import route-policy RP-<ASN>-IMPORT-<AFI>
  peer <remoto> export route-policy RP-<ASN>-EXPORT-<AFI>
  peer <remoto> maximum-prefix <esperado×(1+margem)> [<limiar %>]

ip ip-prefix IP-PFX-<ASN>-IN-<AFI> index N permit <prefixo>     # proteção do up-full: deny node 10 (internas + autorizações)
ip ip-prefix IP-PFX-<ASN>-EXPORT-<AFI> index N permit <prefixo> # export: rotas internas + autorizações de clientes
ip as-path-filter AS-PATH-<ASN>-OWN permit _<ASN-local>_        # rotas próprias: deny no import do up-full (nó próprio)
route-policy RP-<ASN>-IMPORT-<AFI> ...                          # up-full: nós deny + permit 100
route-policy RP-<ASN>-EXPORT-<AFI> ...                          # apply community <valores da operadora>
ip community-filter CF-<ASN>-BLK-<n> permit <valor>             # communities info+bloquear (deny no import)
ip community-filter CF-<ASN>-PART-<n> permit <valor>            # community de "parcial" (up-parcial)
```

- **Produto por tipo**: `transito`/`ix` → `up-full` (aceita tudo do
  provedor, exceto prefix-list de proteção, communities `bloquear`, rotas
  com o ASN próprio no AS-PATH — `AS-PATH-<ASN>-OWN`, nó deny, quando o edge
  tem `asn` cadastrado — e a default quando `allow_default_route=false`);
  `pni` → `up-parcial` (default
  + rotas com a community de "parcial", identificada por `purpose=info` +
  `bloquear=False`); `contingencia` → `up-default` (só a default). Sem
  community de "parcial" cadastrada, o `up-parcial` sai como comentário-dívida
  no plano.
- **Fail-safe**: sessão de upstream sem perfil de importação renderiza
  `route-policy RP-<ASN>-IMPORT-<AFI> deny node 10` (comentário) — nunca
  accept-all.
- **Remoção**: a CR inversa gera os `undo` correspondentes (peer, route-policy
  e prefix-list) — use o plano da CR, nunca remova à mão. Ao final, CR de
  remoção classificada `aplicado` **desativa o upstream** na SoT
  (`upstreams.admin_status=false` — §14.1: objeto em uso é desativado, nunca
  excluído; circuitos e sessões permanecem; evento `upstream.disable` na
  auditoria). Reative o upstream antes de reprovisionar;
  `com_divergencia`/`parcial`/`erro` não desativam.

## Etapa 1 — Somente leitura (§21.3 itens 1–2)

Coleta contra os roteadores reais de borda, **sem escrita** (a allowlist do
gerenet só aceita `display`). Nesta etapa também se ajustam parsers/templates
se o VRP real divergir do esperado.

### 1.1 Coletar os outputs reais

Em cada edge (via plataforma, já coletando os circuitos vinculados) ou
diretamente no equipamento:

```
display bgp peer
display bgp ipv6 peer
display current-configuration
```

Na plataforma: `uv run gerenet collect run --device <id|nome>` (a coleta roda
`display bgp peer` e `display bgp ipv6 peer`). Salve a saída exata
(sanitizada: nenhum IP de gerência/hostname sensível) em fixtures, ex.
`tests/fixtures/huawei_vrp/<edge>_display_bgp_peer.txt` — é a única saída de
equipamento que entra no git, e revisada antes de versionar.

### 1.2 Conferir o formato contra os TextFSM

Formato esperado do `display bgp peer` (espelho de
`tests/automation/test_parsers_golden.py`):

```
BGP local router ID : 10.0.0.1
Local AS number : 64512
Total number of peers : 1
Peer   V  AS        MsgRcvd  MsgSent  OutQ  Up/Down  State       PrefRcv
10.0.0.2  4  64513   100      100      0     01:23:45 Established  950
```

| Campo | Origem no parser | Uso |
|---|---|---|
| `peer`/`asn`/`estado`/`pref_rcv` | linha da tabela | pré-check de ASN conflitante e pós-check (Established + contagem) |
| `pref_rcv` | coluna PrefRcv | compara com esperado × (1 ± margem) do upstream |

Peer sem rota recebida mostra `-` no PrefRcv — o parser converte para `None`
(linha não derruba o merge; a contagem simplesmente não soma).

**Se o output real divergir**, ajuste o `.template` em
`src/gerenet/automation/parsers/huawei_vrp/textfsm/` (`bgp_peer`,
`bgp_peer_verbose`) e o fixture — o parser é tolerante, linha fora do shape é
ignorada, nunca erro —, depois valide:

```bash
uv run pytest tests/automation/test_parsers_golden.py -q
uv run ruff check src tests && uv run pytest -q
```

### 1.3 Conferir a configuração atual da borda

O plano nasce da SoT × última coleta — antes de quadrar o desejado, entenda o
encontrado no `display current-configuration` do edge: sessões BGP existentes
(v4 e v6), route-policies/prefix-lists nomes no padrão do gerenet
(`RP-<ASN>-…`, `IP-PFX-<ASN>-EXPORT-…`), communities já aplicadas. Um peer ou
policy manual fora do padrão aparece na [reconciliação](/wiki/operacao) como
divergência, e não será apropriado pelo gerenet.

**Checklist Etapa 1** — critérios de "ok":

- [ ] `display bgp peer`/`display bgp ipv6 peer`: linha por peer com
      Peer/AS/MsgRcvd/MsgSent/Up-Down/State/PrefRcv (linhas fora do shape
      ausentes).
- [ ] Fixture salva e `test_parsers_golden.py` verde (ou parser ajustado).
- [ ] Config atual revisada: peers/policies existentes na borda anotados
      (divergências previstas vs. não previstas).
- [ ] Borda de teste identificada (circuito/edge não crítico) e janela de
      manutenção acordada com o setor.

## Etapa 2 — Geração sem execução (§21.3 item 3)

Cadastre a intenção **sem executar nada**: a SoT é a fonte da verdade; a CR
nasce em `rascunho` com o plano congelado (diff por bloco × última coleta).

### 2.1 Cadastrar a operadora e o upstream

```bash
# organização operadora (ASN e IRR AS-SET opcionais)
uv run gerenet organizations add --name <operadora> --kind operadora \
  --asn <asn-remoto> [--irr-as-set <as-set>]

uv run gerenet upstreams add --name <upstream> --tipo transito \
  --organization-id <id-org> --expected-prefixes-v4 <n> \
  --expected-prefixes-v6 <n> --max-prefix-margin-pct 20 [--rpki-enabled]
uv run gerenet upstreams list && uv run gerenet upstreams show <upstream>
```

Vincule o circuito (matriz principal × contingência) e confira se as sessões
ganharam o perfil certo (transito/ix → `up-full`; pni → `up-parcial`;
contingencia → `up-default`) e o maximum-prefix esperado × (1 + margem):

```bash
uv run gerenet upstreams circuit-add <upstream> <circuito> --papel principal
uv run gerenet upstreams circuit-add <upstream> <circuito2> --papel contingencia --ordem 2
uv run gerenet bgp-sessions list          # conferir perfil/maximum-prefix por sessão
```

### 2.2 Communities da operadora (valor concreto)

```bash
# "parcial" (purpose=info, sem bloquear) — necessária para o produto up-parcial
uv run gerenet upstreams communities add --upstream-id <id> --purpose info \
  --value <valor> --direcao import --regiao <regiao>
# bloqueio de rotas (info + bloquear) — viram deny no import da up-full
uv run gerenet upstreams communities add --upstream-id <id> --purpose info \
  --value <valor> --direcao import --bloquear
# ações no export: prepend/lp/blackhole
uv run gerenet upstreams communities add --upstream-id <id> --purpose prepend \
  --value <valor> --direcao export --regiao <regiao>
uv run gerenet upstreams show <upstream>
```

### 2.3 Criar a CR e revisar o diff (NÃO executar)

```bash
uv run gerenet change-requests add --escopo upstream --upstream-id <id> \
  --motivo "Teste de upstream (circuito não crítico)"
uv run gerenet change-requests show <cr-id>
```

Na web, a página da CR (`/change-requests/<id>`) mostra o diff por bloco
(desejado × encontrado da última coleta de cada device). **Confira contra o
`display` real da Etapa 1:**

- máximo de prefixos na faixa do esperado × (1 + margem) — compara com o
  `PrefRcv` atual e com o que a operadora espera;
- `IP-PFX-<ASN>-EXPORT-<AFI>` com as rotas internas e clientes certos (um
  prefixo errado aqui vaza anúncio para o trânsito — ou nega o que deveria
  anunciar);
- communities: `bloquear` como nó deny no import (community-filter
  `CF-<ASN>-BLK-…`), "parcial" como nó permit (up-parcial), e os valores das
  ações no `apply community` do export;
- sessão sem perfil ⇒ bloco deny-all do fail-safe (nunca aceite um plano
  assim por engano: é o modo seguro, mas significa que falta o perfil).

Se algo divergir: cancele a CR em rascunho (`uv run gerenet change-requests
cancel <cr-id>`), ajuste a SoT e recrie a CR. **Nesta etapa nenhum comando é
enviado ao roteador.**

**Checklist Etapa 2**:

- [ ] Operadora `kind operadora` e upstream com esperados/margem corretos.
- [ ] Circuitos vinculados com papel/ordem certos; sessões com produto e
      maximum-prefix repropagados.
- [ ] Communities da operadora cadastradas (parcial/bloquear/ações) e
      conferidas no `show`.
- [ ] CR de escopo `upstream` em `rascunho`; diff por bloco revisado por
      device (max-prefix, INTERNAS, communities, fail-safe).
- [ ] CR **não** enviada/executada (permanece rascunho neste ponto).

## Etapa 3 — Execução de teste (§21.3 item 5)

Execução em **circuito/edge não crítico**, com upstream de teste
(`teste-...`), via CR aprovada no fluxo normal — o aprovador não é o
solicitante (papel `aprovador`/`administrador`, `require_papel`).

### 3.1 Fluxo

```bash
uv run gerenet change-requests send <cr-id>          # rascunho → aguardando_aprovacao
uv run gerenet change-requests approve <cr-id> --aprovador <usuario-aprovador>
# worker ativo (Terminal A):
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet-worker
uv run gerenet change-requests execute <cr-id>       # enfileira + status executando
uv run gerenet change-requests list --status executando # (ou acompanhe no dashboard)
```

Na execução o worker, por step (device) e automaticamente:

1. **Backup pré-mudança**: coleta fresca salva em `data/backups/change-<cr>/<ts>/pre/`
   (snapshot `backup_snapshot_id` no step; `data/` é gitignored);
2. **Gate de coleta** (§5.3): recursos `interfaces`, `bgp_peers` e
   `config_backup` obrigatórios;
3. **Pré-check do escopo upstream**: coleta com `bgp_peers`, peer sem ASN
   conflitante (a rota *já* cadastrada com ASN diferente é config
   conflitante — falha antes de tocar), ao menos uma sessão do upstream
   naquele device — **não passa ⇒ a CR vira `erro`** (sem aplicar nada às
   cegas);
4. **Re-diff** do plano congelado × encontrado fresco (idempotência: bloco já
   presente = pulado);
5. **Aplicação bloco a bloco** com detecção de erro do VRP — erro ⇒ step
   `falhou`, parada;
6. **Pós-check** (`valida_pos_upstream`): peer listado, `Established` e
   contagem de rotas dentro de esperado × (1 ± margem) — uma contagem fora
   da faixa ou peer sem sessão vira item de divergência (severidade
   conforme) e a CR é classificada; ver também o §13 (sem quedas
   inesperadas de outros peers, logs limpos);
7. **Registro antes/depois** (escopo upstream): o step grava
   `prefixos_antes`/`prefixos_depois` no resultado do pós-check (soma
   `pref_rcv` por família do encontrado pré e pós); na **remoção** as
   sessões desativadas também contam — confira que a soma bate com o
   `display bgp peer` da Etapa 1.

Somente a aplicação manda comandos de configuração (`bgp ...`, `peer ...`,
`route-policy ...`, `ip ip-prefix ...`); a allowlist `^display` vale para a
coleta — nenhum comando fora do plano é enviado.

### 3.2 Verificação manual pós-execução (na borda)

```
display bgp peer
display bgp ipv6 peer
display ip routing-table statistics
display alarm                       # nada de alarmes novos
```

Critérios de "ok": peer `Established` nas famílias planejadas; `PrefRcv`
dentro do esperado × (1 ± margem) (abaixo de 80 % do maximum-prefix de
aviso); rotas da operadora chegando nas famílias planejadas; rota default
presente/ausente conforme o produto; nenhum outro peer caiu durante a
aplicação; `display alarm` sem nada novo.

**Checklist Etapa 3**:

- [ ] Upstream com nome/finalidade `teste-...`; circuito/edge não crítico e
      janela acordados com o setor.
- [ ] Aprovador ≠ solicitante; aprovação registrada; CR executando com worker
      ativo.
- [ ] Backup pré-mudança salvo em `data/backups/change-<cr>/` (gitignored).
- [ ] Pós-check: `display bgp peer` ⇒ `Established`; `PrefRcv` dentro da
      faixa esperada × (1 ± margem); sem quedas de outros peers; sem alarmes
      novos.
- [ ] Resultado registrado no **ledger**: `data`, `equipamento`, `motivo`,
      `janela`, `resultado` (ledger SDD do plano —
      `.superpowers/sdd/2026-09-08-gerenet-fase5-upstreams/progress.md`).
- [ ] Antes da Etapa 5: desativação do circuito/edge de teste e reversão da
      mudança conforme planejado.

### 3.3 Variação anormal de prefixos (B5, §7)

O alerta de variação é calculado no **job de coleta** — o histórico das
coletas só existe lá, não na reconciliação (que apenas exibe). A cada coleta
do device, por sessão de upstream:

- peer `Established` com `pref_rcv` coletado; base = `expected_prefixes_v4/v6`
  × margem (`max_prefix_margin_pct`) do upstream e, **sem esperado
  cadastrado**, o histórico das últimas K coletas válidas do mesmo peer
  (K = `GERENET_BGP_ANOMALIA_JANELA`, default 2; variação acima de
  `GERENET_BGP_ANOMALIA_PCT` %, default 50, dispara).
- O resultado vai no snapshot (`resources["anomalias_prefixos"]`: afi, peer,
  contagem, base, `variacao_pct`, `base_tipo` `esperado`/`historico`,
  upstream) e aparece como item `bgp.anomalia_prefixos` (severidade `alerta`)
  na [reconciliação](/wiki/operacao) do device.

Verificação: `uv run gerenet collect run --device <id>` e depois
`uv run gerenet reconcile <device>` — com o esperado cadastrado direito, uma
coleta após a mudança não deve gerar item de anomalia. Variação real de
dimensão do trânsito se resolve nos esperados do upstream, não no threshold:
o item é alerta ao operador, nunca um gate.

## Etapa 4 — IRR/RPKI consultivo (§7.5, §10.4 — nunca um gate)

Rode as consultas **antes** de aprovar qualquer autorização de prefixo da
operadora. A validação registra (`origin` e `validacao` na autorização) e é
**informação para o aprovador humano — nenhum valor bloqueia ou desbloqueia o
fluxo**.

```bash
# IRR: resolve ASN/AS-SET com cache (TTL padrão 24h; --ttl-horas para ajustar)
uv run gerenet irr query <asn-org>
uv run gerenet irr query <as-set> --source radb      # radb, altdb ou lacnic

# RPKI: espelha o lote JSON do rpki-client ({"roas": [...]})
uv run gerenet rpki sync --file /caminho/roas.json
# sem --file, usa GERENET_RPKI_ROAS_FILE; o sync revalida automaticamente
# as autorizações de origem irr/rpki ao final (§10.4)
```

Depois, **na autorização**: crie-a com a origem certa (`manual`, `irr` ou
`rpki`) e confira o campo `validacao` (`ok`, `diverge`, `desconhecida` ou
`nao_verificada`). O que observar:

- `ok` — a fonte confirma o prefixo para o ASN; a aprovação humana continua
  obrigatória;
- `diverge` — a fonte diz outra coisa (ASN ou prefixo diferente): a
  autorização não é bloqueada, mas o aprovador deve ver a queixa na tela
  antes de assinar;
- `desconhecida`/`nao_verificada` — sem informação ou ainda não verificada:
  nada impede a aprovação, e o registro garante quem decidiu sabendo disso;
- o sync do RPKI roda a revalidação sozinho; para IRR, a revalidação de cada
  autorização decorre da consulta ao AS-SET/ASN com cache (consulte antes de
  decidir, não depois).

**Checklist Etapa 4**:

- [ ] `gerenet irr query` rodado para o ASN e o AS-SET da operadora, com
      resultado conferido contra o que a operadora afirma anunciar.
- [ ] `gerenet rpki sync` rodado (com `--file` ou `GERENET_RPKI_ROAS_FILE`);
      `roas` com o lote do rpki-client e autorizações irr/rpki revalidadas.
- [ ] Autorizações criadas com `origin` correta e `validacao` registrada.
- [ ] Aprovação humana em qualquer origem — validacao é consulta, não gate.

## Etapa 5 — Contingência: plano de rollback aprovado ANTES

A reversão em equipamento real é uma CR como qualquer outra, e o
**rollback automático está disponível para o escopo `upstream`**: aprove o
plano de retorno **antes** de executar a mudança, para que a reversão não
dependa de quem está acordado às 3 da manhã.

```bash
# CR aplicada → a CR inversa nasce em aguardando_aprovacao (com rollback_de)
uv run gerenet change-requests rollback <cr-id>
uv run gerenet change-requests show <cr-inversa>    # conferir undo por device
# aprovação ANTES da execução da mudança principal, ou no máximo em standby:
uv run gerenet change-requests approve <cr-inversa> --aprovador <usuario-aprovador>
```

- A CR inversa do provision vira **remoção** (undo a partir do baseline do
  step aplicado — sem baseline, não inventa: o step é pulado e a diferença
  aparece na reconciliação); se a CR original era remoção, a inversa é
  provision re-renderizada da SoT atual.
- Se a execução deu `parcial`, `gerenet change-requests reconcile <cr-id>`
  recomputa os steps não aplicados e reabre a aprovação deles (também vale
  para o escopo upstream).
- Nenhum dos dois caminhos precisa de rollback manual: evite `undo` solto na
  borda, o plano da CR é a fonte do que deve sair.

**Checklist Etapa 5**:

- [ ] CR inversa de rollback criada e **aprovada** antes da execução da
      mudança principal (ou já aprovada em standby).
- [ ] Saída esperada da reversão definida por escrito (peer removido,
      policies fora, prefixos deixando de ser anunciados).
- [ ] Pós-reversão: `display bgp peer` sem o peer; nenhuma rota da operadora
      recebida; reconciliação sem divergência nova.

---

## O que NUNCA fazer

- **Blind execution**: executar CR sem coletar/validar, ou re-executar
  confiando no plano antigo — re-diff, gate de coleta e pré-check existem de
  propósito.
- **Mudança em produção sem aprovação**: nenhum comando fora do plano + CR
  aprovada por usuário distinto (§3.3); crítica no upstream,
  aprovação do aprovador do setor.
- **Tratar a validacao `rpki`/`irr` como gate**: ela nunca bloqueia nem
  desbloqueia; bloquear o fluxo por causa de `diverge` é decisão humana
  registrada na autorização, não regra da plataforma.
- **Aprovar o plano só depois do pior caso**: na troca de trânsito, a
  contingência testada (Etapa 5) é que define a janela de execução.
- **Remover à mão** (`undo peer`, `undo route-policy ...` soltos) o que a
  CR/plano cobre — a remoção também é CR aprovada.
- **Anunciar com a prefix-list de proteção vazia** (export): o template manda
  o VRP falhar com objeto inexistente de propósito (evita vazar rotas para o
  trânsito); se aparecer erro de if-match, corrija o desejado, não remova a
  referência.

## Regras inegociáveis

- Nenhuma credencial em git/banco/logs/templates; host keys validadas antes
  de cada conexão (fail-closed — fingerprint errado bloqueia a coleta de
  propósito).
- Nenhuma execução sem aprovação (§3.3); CR aprovada com aprovador ≠
  solicitante.
- Nenhum comando fora do plano/allowlist; backup bruto (`data/`) nunca
  versionado.
- Upstream de validação sempre com nome/finalidade `teste-...`; reversão
  documentada e aprovada.
- validacao IRR/RPKI é consultiva (§10.4): registro para decisão humana,
  nunca substitui a aprovação.

## Critérios de aceite (da fase, a validar aqui)

- [ ] Parser `bgp_peer` cria dados úteis contra o output real do NE8000
      (ou foi ajustado).
- [ ] CR de escopo `upstream`: criação → aprovação → execução (`aplicado`)
      e remoção, com pós-check de peer/Established/contagem — em circuito/edge
      não crítico.
- [ ] communities da operadora (parcial/bloquear/ações) renderizadas e
      validadas na borda de teste.
- [ ] IRR/RPKI rodados e lidos: autorizações com `origin`/`validacao` e
      aprovação humana sem qualquer valor de validacao bloqueando.
- [ ] Rollback (CR inversa) aprovado antes da execução e testado na reversão.
- [ ] Nenhuma credencial vazada; nenhum backup versionado; nenhum comando
      sem aprovação.
