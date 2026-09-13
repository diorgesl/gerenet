# Runbook — validação em equipamento real da fase 4 (MPLS em switches)

> A fase 4 está implementada e testada (domínios MPLS, serviço L2VC com change request de
> escopo `l2vc`, coletores/parsers LDP/L2VC/VSI, páginas web `/mpls/*`). Esta é a **validação
> manual contra os switches reais da família S** (S6730…), executada por você — o código só é
> alterado se a saída real divergir (ajuste de TextFSM/templates, único desvio previsto).
> A validação é **em produção, sem laboratório** — decisão consciente do usuário em
> 2026-09-07 (há switches de produção disponíveis; um serviço de teste em switch não crítico
> segue a implantação gradual do §21 da spec, registrada no spec e no design da fase 4).
> **Nada executa mudança sem aprovação (§3.3 inegociável).** São 3 etapas:
> (1) somente leitura; (2) geração sem execução; (3) execução de teste em switch não crítico.

**Pré-requisitos:** compose dev de pé (`docker compose up -d` — postgres/redis/vault), worker
com credenciais no Vault e host keys registradas para os switches da família S, switches
alcançáveis pela máquina do worker, contas de usuário com papéis de operador e aprovador.
Nada aqui funciona sem o worker para a Etapa 3 (a fila `gerenet-change` executa a mudança).

---

## Referência rápida — sintaxe do AC (fonte: `src/gerenet/automation/templates/huawei_vrp/l2vc_ac.j2`)

O AC é **untag na interface principal** (correção do produto aplicada na fase 4) — física ou
Eth-Trunk, em modo L3:

```
interface <trunk>
undo portswitch                # switch em modo L3 (necessário só na 1ª vez)
mtu <mtu>                      # apenas quando definido (padrão 1500 — pode ser omitido)
mpls l2vc <peer-loopback> <vc-id>[ control-word]
mpls l2vpn flow-label both     # linha separada, apenas com flow_label + capability
```

- **Remoção**: `undo mpls l2vc <peer-loopback> <vc-id>` no contexto da interface. **Nunca**
  `undo interface`, `undo portswitch` nem `undo mpls l2vpn flow-label` — outro VC pode estar
  na mesma interface (é esse o propósito do AC untag compartilhado).
- **VSI** (somente referência futura): o AC de VSI usa `l2 binding vsi <VSI-name>` — nenhuma
  ponta VSI é provisionada neste ciclo.
- **flow-label/control-word**: confirmar suporte na família/versão alvo. `flow_label` é gerado
  apenas se o device tiver a capability `mpls_flow_label` em `devices.capabilities` (string
  exata `"mpls_flow_label"` se suportado) — sem a capability, a linha é omitida. Se o switch
  rejeitar o comando, remova a capability do device e a bandeira do serviço.

## Etapa 1 — Somente leitura (§21.3 itens 1–2)

Coleta contra os switches reais, **sem escrita** (a allowlist do gerenet só aceita `display`).
Nesta etapa também se ajustam parsers/templates se o VRP real divergir do esperado.

### 1.1 Coletar os outputs reais

Em cada switch alvo (ou via plataforma, se já coletado):

```
display mpls ldp peer
display mpls l2vc
display vsi verbose
display alarm active
```

Salve a saída exata (sanitizada: nenhum IP de gerência/hostname sensível) em fixtures, por
exemplo `tests/fixtures/huawei_vrp/<sw>_display_mpls_ldp_peer.txt`,
`<sw>_display_mpls_l2vc.txt` e `<sw>_display_vsi_verbose.txt` — é a única saída de equipamento
que entra no git, e revisada antes de versionar.

### 1.2 Conferir o formato contra os TextFSM

Formato esperado (espelho dos testes em `tests/automation/test_parsers_mpls.py`; validado em
S6730 real em 2026-09-08 — a família S imprime em formatos diferentes dos assumidos na fase 4):

| Comando | Formato real da família S (validado) | Normalizado no merge |
|---|---|---|
| `display mpls ldp peer` | tabela `PeerID  TransportAddress  DiscoverySource` — **sem coluna de estado** | `peer_id` sem `:0`; `estado` `None` (desconhecido, nunca `down` por omissão) |
| `display mpls l2vc` | um bloco por VC: `client interface : Vlanif21 is up`, `VC state : up`, `VC ID : 21` | `vc_id` int; `interface`; `estado` `up`/`down` |
| `display vsi verbose` | um bloco por VSI: `***VSI Name : X` → `VSI State : up` → `VSI ID : 2827` | `name`; `vsi_id` int (`None` se o VSI não tem ID); `estado` `up`/`down` |

Notas da validação real:
- O L2VC é **obrigatoriamente** `display mpls l2vc` — `display l2vc` sem `mpls` é um comando
  diferente (não confirmado no switch alvo); o coletor usa o primeiro.
- A VSI é **obrigatoriamente** `display vsi verbose` — a tabela do `display vsi` não imprime
  o `VSI ID`, necessário para casar com a SoT na sincronização (`vsi_id`).
- O estado do par LDP **não existe** no `display mpls ldp peer` da família S (nem no verbose
  até então coletado): o pré-check §9.2 fica "desconhecido" até coletar `display mpls ldp
  session` (ou `display mpls ldp peer verbose`) — nunca afirma `down` sem evidência.
- `display alarm` sem argumento emite um comando inválido na família S (`display alarm ?`;
  `display alarm ac` vazio); o correto é `display alarm active`.
- VSI órfão sem VSI ID (ex.: `VLAN653_INTECH]` no switch real, sem ID nem peer) é **descartado**
  pelo parser (não casa com `vsi_id` da SoT) e deve ser tratado como higiene de rede.

**Se o output real divergir**, ajuste o `.template` correspondente em
`src/gerenet/automation/parsers/huawei_vrp/textfsm/` (`mpls_ldp_peer`, `l2vc` ou `vsi`) e o
fixture, o parser é tolerante — linha fora do shape é ignorada, nunca erro —, depois valide:

```bash
uv run pytest tests/automation/test_parsers_mpls.py -q
uv run ruff check src tests && uv run pytest -q
```

### 1.3 Validar a sintaxe do AC em modo display (switch de teste)

Em **uma interface de teste não conectada** (sem tráfego) do switch, em sessão de despacho
(`system-view` → `interface <if>`), confirme no `display this` / `display current-configuration`
que os comandos da referência acima (`undo portswitch`, `mtu`, `mpls l2vc ...`) são aceitos e
aparecem como o template gera. **Se o VRP divergir, o ajuste é no `l2vc_ac.j2`** — e anote
família/modelo/versão VRP validada num comentário no topo do template (padrão de versionamento
por plataforma). Ações comuns de divergência: ordem das linhas, nome do comando
(`mpls l2vc ...`/`mpls l2vpn flow-label`), exigência de `mtu` ou rejeição do `control-word`.

### 1.4 flow-label/control-word na família S

Teste na mesma interface de display: `mpls l2vpn flow-label both` e o sufixo `control-word` —
se não suportados na versão alvo, deixá-los desligados no serviço (nada garante que a família S
aceite; a capability `mpls_flow_label` é o gate do template, mas o gate vale na SoT).

**Checklist Etapa 1** — critérios de "ok":

- [ ] `display mpls ldp peer`: tabela `PeerID/TransportAddress/DiscoverySource` parseável (sem coluna de estado — estado fica `None` até haver `display mpls ldp session`).
- [ ] `display mpls ldp session`: a tabela `PeerID/Status` casa com os peers do comando anterior e o `estado` do peer no snapshot deixa de ser `None` (parser `mpls_ldp_session`).
- [ ] `local VC MTU` de um VC existente diz se o campo reflete o `mtu` configurado no AC ou o MTU físico — decisão registrada no design de 2026-09-13 (se for o físico, o check de MTU do pós-check vira só simetria entre pontas).
- [ ] Todo bloco de `display mpls l2vc` (incluindo VC `down`) imprime a linha `local VC MTU`/`remote VC MTU`: é a linha em que o parser fecha o registro. Bloco sem ela não entra no snapshot e o VC aparece como ausente na divergência — se isso acontecer, o parser precisa de outra âncora de registro.
- [ ] `display mpls l2vc`: um bloco por VC com `client interface`/`VC state`/`VC ID`.
- [ ] `display vsi verbose`: um bloco por VSI com `VSI Name`/`VSI State`/`VSI ID` (vazio é ok — VSI só consulta neste ciclo; VSI sem ID é descartado).
- [ ] Templates TextFSM e fixtures atualizados e `test_parsers_mpls.py` verde.
- [ ] Sintaxe do AC confirmada no `display this` da interface de teste (não conectada).
- [ ] Suporte a flow-label/control-word confirmado (ou flags desligadas na SoT).

## Etapa 2 — Geração sem execução (§21.3 item 3)

Cadastre a intenção **sem executar nada**: a SoT é a fonte da verdade; a CR nasce em
`rascunho` com o plano congelado (diff por bloco × última coleta).

### 2.1 Criar domínio MPLS e pontas na SoT

```bash
# domínio
uv run gerenet mpls domain add --name <dominio>
uv run gerenet mpls domain add-member --domain-id <id> --device-id <id> --loopback <loopback-ldp>
uv run gerenet mpls domain list

# serviço L2VC (nome/finalidade de teste: teste-...)
uv run gerenet mpls l2vc add --domain-id <id> --name teste-<finalidade> \
  --device-a <id-sw-a> --interface-a GE0/0/1 --vid-a <vid-a> \
  --device-b <id-sw-b> --interface-b GE0/0/2 --vid-b <vid-b> \
  [--vc-id <id>] [--organization-id <id>] [--mtu 1500] [--control-word] [--flow-label]
uv run gerenet mpls l2vc list && uv run gerenet mpls l2vc show <id>
```

(Equivalente na web: `/mpls/domains` e `/mpls/l2vc`.)

### 2.2 Criar a CR e revisar o diff (NÃO executar)

```bash
uv run gerenet change-requests add --escopo l2vc --l2vc-id <id> --motivo "Teste L2VC fase 4"
uv run gerenet change-requests show <cr-id>
```

Na web, a página da CR (`/change-requests/<id>`) mostra o diff por bloco (desejado ×
encontrado da última coleta de cada switch). **Confira contra o `display` real da Etapa 1:**

- loopback LDP do **par** de cada ponta (o template usa o loopback do outro switch);
- VC-ID único no domínio; VLANs de AC reservadas por device (`kind=mpls_ac`, VID livre nos
  dois switches do POP); encap (dot1q) e MTU iguais nas duas pontas (simetria §9.2);
- MTU fim a fim coerente com o link core.

Se algo divergir: cancele a CR em rascunho (`uv run gerenet change-requests cancel <cr-id>`),
ajuste a SoT e recrie a CR. **Nesta etapa nenhum comando é enviado ao switch.**

**Checklist Etapa 2**:

- [ ] Domínio com os 2 switches e loopbacks LDP que batem com o `display mpls ldp peer` real.
- [ ] L2VC `teste-...` com VC-ID e VLANs corretos; CR de escopo `l2vc` criada em `rascunho`.
- [ ] Diff por bloco conferido nas 2 pontas (loopbacks, VC-ID, encap, mtu) — nada a revisar.
- [ ] CR **não** enviada/executada (permanece rascunho neste ponto).

## Etapa 3 — Execução de teste (§21.3 item 5)

Execução em **switch não crítico**, com serviço de teste (`teste-...`), via CR aprovada no
fluxo normal — o aprovador não é o solicitante (papel `aprovador`/`administrador`,
`require_papel`).

### 3.1 Fluxo

```bash
uv run gerenet change-requests send <cr-id>          # rascunho → aguardando_aprovacao
uv run gerenet change-requests approve <cr-id> --aprovador <usuario-aprovador>
# worker ativo (Terminal A):
GERENET_VAULT_TOKEN=gerenet-dev-root uv run gerenet-worker
uv run gerenet change-requests execute <cr-id>       # enfileira + status executando
uv run gerenet change-requests list --status executando # (ou acompanhe no dashboard)
```

Na execução o worker, por step (ponta) e automaticamente:

1. **Backup pré-mudança**: coleta fresca salva em `data/backups/change-<cr>/<ts>/pre/`
   (snapshot `backup_snapshot_id` no step; `data/` é gitignored);
2. **Gate de coleta** (§5.3): recursos `interfaces`, `l2vc`, `config_backup` obrigatórios;
3. **Pré-check do escopo L2VC** (§9.2): peer LDP do par **UP**, sem binding conflitante
   (VC na interface errada), simetria de encap/MTU na SoT — **não UP ⇒ passo falha e a CR
   vira `erro`** (sem aplicar nada às cegas);
4. **Re-diff** do plano congelado × encontrado fresco (idempotência: bloco já presente =
   pulado);
5. **Aplicação bloco a bloco** com detecção de erro do VRP — erro ⇒ step `falhou`, parada;
6. **Pós-check**: nova coleta + `display l2vc` — **VC presente e `State Up`** nas duas pontas
   ⇒ CR `aplicado`; VC `down`/ausente ⇒ itens `l2vc.estado`/`l2vc.ausente` (severidade
   crítica) e CR `com_divergencia`. Entraram também os itens de `atencao`: `l2vc.ac` (AC fora
   de `up`), `l2vc.mtu` (MTU local diferente do configurado no AC) e `l2vc.mtu_simetria`
   (MTU diferente entre as pontas) — o MTU só é conferido com o VC de pé, porque o VRP
   imprime `0` no remoto de um VC `down`.

Somente a aplicação manda comandos de configuração (`interface`, `undo portswitch`, `mtu`,
`mpls l2vc`…); a allowlist `^display` vale para a coleta — nenhum comando fora do plano é
enviado.

### 3.2 Verificação manual pós-execução (no switch)

```
display mpls l2vc
display mpls ldp peer
display alarm active   # nada de alarmes novos
```

Critérios de "ok": `VC state : up` no VC das duas pontas; peer LDP `Up` (ou sessão LDP
`display mpls ldp session`); MTU fim a fim consistente; sem alarmes novos no
`display alarm active`; tráfego de teste passando (validação funcional do serviço).

### 3.3 Rollback e reconciliação nesta fase

O rollback e a reconciliação de CR de escopo `l2vc` **estão implementados**:
`gerenet change-requests rollback <cr>` cria a CR inversa em `aguardando_aprovacao`
com os blocos derivados da **coleta atual** (o filho remove as pontas onde o VC
consta no snapshot e não gera step para ponta ausente), e
`gerenet change-requests reconcile <cr>` recomputa as pontas pendentes de uma CR
em `erro`/`parcial`. A derivação por coleta atual (em vez do baseline pré-mudança,
como no circuito) é decisão registrada no design de 2026-09-13: num L2VC novo o
baseline não contém o VC e o plano sairia vazio.

Roteiro (a CR filha nasce em `aguardando_aprovacao` e **não executa sozinha**):

```bash
# 1. cria a CR inversa (na web: botão "Gerar rollback")
uv run gerenet change-requests rollback <cr>
# 2. aprovação do filho (aprovador ≠ solicitante do filho)
uv run gerenet change-requests approve <id> --aprovador <usuario>
# 3. worker aplica e roda o pós-check (§3.1)
uv run gerenet change-requests execute <id>
# 4. confira steps e pós-check
uv run gerenet change-requests show <id>
# 5. só quando a CR mãe ficou em erro/parcial — recomputa as pontas pendentes
uv run gerenet change-requests reconcile <cr>
```

O rollback remove as pontas cujo VC consta na **coleta atual**: ponta sem o VC no snapshot não
gera step no filho.

No l2vc o `PlanoRollbackVazio` tem mensagem própria — "Nada do serviço consta na coleta atual":
nenhuma ponta lista o VC no encontrado, então não há o que desfazer (se o VC existe no switch,
colete as pontas antes; o baseline pré-mudança não entra nesta conta).

Escopos com semântica própria, para não confundir o operador: no `upstream`, desfazer uma
remoção já **aplicada** exige reativar o upstream antes — a remoção aplicada o desativa na SoT e
a API responde **409** ("reative antes de planejar a mudança") até a reativação, que é manual de
propósito (sem reativação automática).

Quando o caminho automático não se aplica (o `PlanoRollbackVazio` acima é o caso típico), a
reversão segue pelos caminhos manuais documentados (§12.4 permite estratégia documentada por
tipo — rollback manual documentado é aceitável neste ciclo), **validados com a equipe**:

1. **Via plataforma (preferido)**: remova o serviço da intenção com uma CR de remoção —
   exige coleta fresca com `l2vc` no switch (`uv run gerenet collect run --device <sw>`
   antes) e o mesmo fluxo aprovado:

   ```bash
   uv run gerenet change-requests add --escopo l2vc --l2vc-id <id> --acao remove --motivo "Rollback L2VC"
   uv run gerenet change-requests send <cr> && uv run gerenet change-requests approve <cr> --aprovador <usuario>
   uv run gerenet change-requests execute <cr>   # pós-check por ausência (§5.2)
   ```

2. **Manual no switch** (documentado, para emergência): no contexto da interface apenas o
   `undo` do VC — `system-view` → `interface <if>` → `undo mpls l2vc <peer-loopback> <vc-id>`
   → conferir `display mpls l2vc`. Nunca `undo interface`, `undo portswitch` nem
   `undo mpls l2vpn flow-label` (outros VCs podem usar a mesma interface). Se o switch
   apresentar erro do VRP, parar e abrir CR/plano de remoção em vez de insistir.

**Nota de coleta**: as duas tabelas dividem um único recurso (`mpls_ldp_peer`). Se o comando de
sessão falhar — timeout, queda de conexão —, a chave vai para `erros`, o snapshot fica
`partial` e os peers deixam de aparecer (antes chegavam com `estado=None`); se o VRP apenas
responder com erro ao comando, os peers voltam todos com `estado=None`. O pré-check bloqueia a
execução nos dois casos: se ela parar no check do par LDP, olhe primeiro os erros da coleta.

Depois da reversão, desative o serviço de teste na SoT (`uv run gerenet mpls l2vc set-status
<id> --inativo`), mantendo o histórico.

**Checklist Etapa 3**:

- [ ] Serviço com nome/finalidade `teste-...`; switch não crítico e janela acordados com o setor.
- [ ] Aprovador ≠ solicitante; aprovação registrada; CR executando com worker ativo.
- [ ] Backup pré-mudança salvo em `data/backups/change-<cr>/` (gitignored).
- [ ] Pós-check: `display mpls l2vc` ⇒ `VC state : up` nas duas pontas; LDP `Up`; sem alarmes novos; sem item de `atencao` de AC/MTU (`l2vc.ac`, `l2vc.mtu`, `l2vc.mtu_simetria` — o MTU só é conferido com o VC de pé).
- [ ] Resultado registrado no **ledger**: `data`, `equipamento`, `motivo`, `janela`, `resultado`
      (ledger SDD do plano — `.superpowers/sdd/2026-09-07-gerenet-fase4-mpls/progress.md`).
- [ ] Reversão documentada (rollback da CR, plataforma ou manual) e, se executada, conferida no `display mpls l2vc`.

---

## Regras inegociáveis

- Nenhuma credencial em git/banco/logs/templates; host keys validadas antes de cada conexão
  (fail-closed — fingerprint errado bloqueia a coleta de propósito).
- Nenhuma execução sem aprovação (§3.3); CR aprovada com aprovador ≠ solicitante.
- Nenhum comando fora do plano/allowlist; backup bruto (`data/`) nunca versionado.
- Interfaces com AC untag são **compartilhadas**: só o VC sai, nunca a interface inteira.
- Serviços de validação sempre com nome/finalidade `teste-...`; reversão documentada.

## Critérios de aceite (da fase, a validar aqui)

- [ ] Parsers LDP/L2VC/VSI criam dados úteis contra o output real (ou foram ajustados).
- [ ] `l2vc_ac.j2` validado no switch real (comentário de versão no template se ajustado).
- [ ] CR de escopo `l2vc`: criação → aprovação → execução (`aplicado`) e remoção, com pós-check.
- [ ] `display mpls ldp peer`/`display mpls l2vc`/`display vsi verbose` coletados pelo worker e
      sincronizados na SoT (estado operacional do serviço/pontas atualizado).
- [ ] Nenhuma credencial vazada; nenhum backup versionado; nenhum comando sem aprovação.
