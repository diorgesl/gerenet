# Design — Ciclo C3: edição e reativação de entidades (gerenet)

> Especificação do **ciclo C3** do gerenet — fechar o ciclo de vida completo das
> entidades na web (listagem com desativados, edição e reativação) e liquidar as
> dívidas registradas na revisão final do ciclo C2 (2026-09-04).
> Documentos-fonte: [ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md](../../../ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md)
> (spec §4.3/§16.1/§17–19), especificação do ciclo C2 (2026-09-04, web UI — concluído;
> §12, critério 5: "listagem + criação + edição + desativação; catálogos somente
> leitura") e plan do C2 (cortes registrados na revisão final, T13).

## 1. Objetivo e escopo

Entregar na web o ciclo de vida completo das entidades cadastrais — **listagem +
criação (já existe) + edição + desativação (já existe) + reativação** — além de
liquidar os follow-ups registrados na revisão final do C2:

1. **Edição/reativação** de todas as entidades com página web: users, devices,
   sites, organizations, contacts, circuits, bgp-sessions, prefix-authorizations
   e os catálogos **communities** e **policy-profiles** (estes ganham também o
   backend de update/PATCH, hoje inexistente — ver §2.1).
2. **`include_disabled` nos GETs** no que falta (só contacts) e **"ver desativados"
   + reativar** nas páginas web (o PATCH já cobre a reativação).
3. **Cards do dashboard** com `by_comm_status` e `snapshot_age_seconds` (spec
   §16.1; a API já devolve os dois — é render no front).
4. **Follow-ups de qualidade web**: `.catch` de mutações por página (rejeições não
   tratadas em ConfirmDialog/logout); a11y de dialog (foco/escape/backdrop).
5. **Guard de falha dura no webServer do Playwright** (hoje `reuseExistingServer`
   com aviso).
6. **Rate limit de login** (o `autenticar` gasta ~50ms de scrypt por tentativa) e
   **remoção de sessões ao desativar usuário** (hoje reativação "ressuscita"
   sessões antigas; §4.3 checa `is_active` no `require_actor`).
7. **Limpezas**: alias `--include-disabled` para `gerenet users list --all` e
   remoção do `DIST` morto em `tests/api/test_static_spa.py:9`.

Fora do escopo do C3: assistentes web §16.2/§16.3 (downstream/MPLS); motor de
mudanças/change requests §12 (ciclo D); criação de novos catálogos por CLI/web (os
catálogos continuam seedados — ver §1.1); i18n; gráficos avançados.

### 1.1 Correção de premissa sobre catálogos

O corte do C2 assumia "CLI cria/desativa" para communities/policy-profiles. Ao
verificar o código: **o CLI desses dois só tem `list`**, a API só tem `GET` (com
`include_disabled`) e as páginas web são read-only. Os catálogos são **seedados**
(dados-base via seed do ciclo A). No C3 os catálogos ganham: service `update_*`
+ evento de auditoria, PATCH nos routers (com ruling 1: desativação pura →
`*.disable`; resto → `*.update`; repetição idempotente), comando `update` no CLI e
edição/desativação/reativação na web. **Criação de novos catálogos permanece fora
do escopo** (seed + eventual CLI de criação num ciclo futuro).

**Nota de decisão**: o critério §12 (item 5) do C2 dizia "catálogos
(policy-profiles, communities) são somente leitura". A decisão do operador em
2026-09-05 (opção "todas, incluindo catálogos") **revisa esse critério**: no C3 os
catálogos passam a ter edição/desativação na web (a criação segue fora — permanece
via seed).

## 2. Contexto (o que já existe, verificado em 2026-09-05)

### 2.1 Backend/API

- **PATCH de edição já existe** para: devices, sites, organizations, contacts,
  circuits, bgp-sessions, prefix-authorizations e users — todos com padrão
  `exclude_unset`, erros 404/400 (NotFoundError/ValidationError) e auditoria
  `registrar(...)` com `antes`/`depois`.
- **`include_disabled` nos GET** já existe em: users, sites, devices, organizations,
  circuits, bgp-sessions, prefix-authorizations, communities e policy-profiles.
  **Falta apenas contacts** (routers/contacts.py + service `list_contacts`).
- **Desativação** por PATCH puro (`admin_status`/`is_active` → `false`) vira evento
  dedicado `*.disable` (ruling 1) e é idempotente (repetição → sem transição, sem
  evento — ruling 5). `devices` ainda zera `comm_status` ao desativar.
- **Reativação**: `svc.enable_device` (evento `device.enable`, idempotente) existe
  desde o commit `9d2962e` (2026-09-05) e é usado **só pelo CLI**; o PATCH do router
  de devices não roteia para ele — hoje reativação via API vira `device.update`.
  As demais entidades **não têm** `enable_*` (reativação vira `*.update` genérico).
- **Catálogos**: communities (modelo `CommunityOut`: id, name, notes) e
  policy-profiles (`PolicyProfileOut`: id, name, label, direction, kind, prefixes)
  — seedados, sem create/update/disable em nenhuma via.
- **Dashboard** (`GET /api/v1/dashboard`): já retorna `by_comm_status: dict[str,int]`
  (ok/fail/unknown) e `PerDeviceOut.snapshot_age_seconds` (+ `latest_snapshot` e
  `active_job`). O front não os usa ainda.
- **Users**: `disable_user` não remove sessões; `reset_password` sim (padrão a
  replicar).
- **Auth**: `POST /api/v1/auth/login` (em api/auth.py) com hash scrypt (~50ms),
  sem qualquer limitação de tentativas.
- **Redis** já é dependência da stack (RQ + locks `gerenet:lock:device:{id}`).

### 2.2 Web

- Páginas em `web/src/pages/`: todas seguem o padrão **form de criação inline no
  topo + DataTable + ConfirmDialog de desativação** (`useXxxCriar`/`useXxxAtualizar`
  via `api/hooks.ts`). Nenhuma tem edição nem "ver desativados".
- `ConfirmDialog` é o único dialog com foco simples e sempre forçado; o dialog de
  reset de senha em `Users.tsx` é um `<div role="dialog">` cru (sem a11y).
- `Users.tsx`: `alternarAtivo` inverte `is_active` mas o botão rotula sempre
  "Desativar" (não mostra "Reativar" no estado inativo; guard `u.id !== usuario.id`
  já existe).
- Dashboard (`Dashboard.tsx`): cards atuais não usam `by_comm_status` nem
  `snapshot_age_seconds`.
- Varias mutações usam `void mut.mutate(...)` sem `.catch` (unhandled rejection).

### 2.3 Infra/testes

- e2e (`web/e2e`): `reuseExistingServer` ligado com aviso no run-book (item
  registrado como follow-up para virar falha dura).
- `tests/api/test_static_spa.py:9`: `DIST = Path("/tmp/gerenet-spa-fake")` morto.
- CLI `gerenet users list --all` (o restante do CLI já usa `--include-disabled`).

## 3. Decisões de design (aprovadas em 2026-09-05 no brainstorm)

1. **Abordagem A — delta mínimo**. O backend de edição já existe; o C3 adiciona o
   que falta (contacts `include_disabled`, catálogos update/PATCH/CLI, rate limit,
   sessões na desativação) e concentra o trabalho no front, seguindo os padrões de
   página explícita do repo. Sem motor de CRUD genérico (over-engineering — páginas
   têm ações específicas: reserve, collect, password, communities).
2. **Escopo de edição: todas as entidades** com página web — as 8 operacionais
   (users, devices, sites, organizations, contacts, circuits, bgp-sessions,
   prefix-authorizations) **e os 2 catálogos** (communities, policy-profiles).
3. **UX de edição: dialog/modal** reutilizando os campos do form de criação,
   inicializado com os valores atuais, submit → PATCH, erro dentro do dialog,
   sucesso fecha e refetch.
4. **Componente `Modal` compartilhado com a11y**: foco inicial no abrir, `Escape`
   fecha, clique no backdrop fecha, `aria-modal` + `aria-labelledby`, focus trap no
   `Tab`, retorno de foco ao fechar. O `ConfirmDialog` passa a ser implementado
   sobre ele **sem mudar a API atual**; o dialog de reset de senha do Users migra.
5. **"Ver desativados" + Reativar** em todas as páginas: default lista apenas
   ativas; o toggle liga `include_disabled` na consulta; inativos com badge
   `StatusBadge`; ação Reativar com `ConfirmDialog` no mesmo fluxo do Desativar.
6. **Reativação roteada onde existe service dedicado**: PATCH `{admin_status: true}`
   puro em devices → `svc.enable_device` (evento `device.enable`). Demais entidades:
   reativação vira `*.update` (sem criar 10 services — YAGNI; documentado).
7. **Rate limit de login em Redis** (fixed window): conta **apenas falhas**,
   chave `gerenet:login:fail:{ip}:{username}`, 5 falhas → bloqueio de 5 min com
   `429 + Retry-After`; sucesso zera a chave. Módulo próprio
   (`src/gerenet/api/rate_limit.py`) com funções testáveis e fake nos testes;
   **fail-open documentado**: Redis fora → login não é bloqueado (disponibilidade),
   registrado no código e na spec como decisão reversível.
8. **Sessões na desativação**: `disable_user` deleta as sessões do usuário
   (mesmo padrão de `reset_password`).
9. **Cards do dashboard §16.1**: bloco "Equipamentos" (total + contagem por
   `by_comm_status`) e card "Coleta" com a idade da última coleta **mais antiga**
   (máx de `snapshot_age_seconds`), alerta visual acima de 24h (constante no
   componente).
10. **Playwright**: `reuseExistingServer: false` (falha dura se a porta :8000
    estiver ocupada; nunca reusa o uvicorn de dev com banco errado) + run-book
    ajustado.
11. **CLI**: alias `--include-disabled` para `gerenet users list --all` (sem
    remover `--all`); remover `DIST` morto em `test_static_spa.py:9`.

## 4. Backend/API (S1)

**S1.1 — contacts `include_disabled`**: adicionar o param `include_disabled: bool =
False` no `GET /api/v1/contacts` (routers/contacts.py) e a assinatura correspondente
em `list_contacts` no service (mesmo padrão dos demais: filtro `admin_status ==
True` por default).

**S1.2 — catálogos com update/PATCH**:
- Services (`domain/services/communities.py` e `policy_profiles.py`): `update_*`
  com validação (nome não vazio; unicidade de nome nos ativos), `registrar` com
  `antes`/`depois`, `session.commit()` e refresh; e `disable_*` no mesmo padrão do
  ruling 1 (idempotente, sem evento em repetição).
- Routers (`api/routers/communities.py`, `policy_profiles.py`): `PATCH /{id}` com
  `Update` schemas (`exclude_unset`), 404/400 padrão, e o desmembramento governado
  pelo ruling 1: mudança pura `admin_status: false` → `disable_*`; senão `update_*`;
  repetição → sem transição (ruling 5). Requerem `require_actor` (já têm como
  dependency).
- CLI (`cli/communities.py`, `cli/policy_profiles.py`): comando `update`.
- Schemas: `CommunityUpdate` (name?, notes?), `PolicyProfileUpdate` (name?,
  label?, direction?, kind?, prefixes?).

**S1.3 — reativação com evento dedicado (devices)**: no PATCH de devices, quando a
mudança pura for `admin_status: true` (e o device estiver desativado), chamar
`svc.enable_device` (evento `device.enable`, idempotente) em vez do caminho
genérico `device.update`. Nas demais entidades, manter `*.update` (documentado no
§3.6). A web usa o PATCH — sem endpoints novos.

**S1.4 — rate limit de login**: novo `src/gerenet/api/rate_limit.py`:
- `permitir(redis, ip, username) -> bool` (conta falhas ativas < 5);
- `registrar_falha(redis, ip, username)` (INCR + EXPIRE 300);
- `limpar_redes(redis, ip, username)` (sucesso zera).
- Em `api/auth.py` no fluxo de login: consulta antes do scrypt; falha → registrar
  e `HTTPException 429` com header `Retry-After`; sucesso → limpar.
- Falha de Redis → log de aviso e seguir (fail-open), com teste documentando.

**S1.5 — sessões na desativação de usuário**: `disable_user` (services/users.py)
deleta as linhas de `user_sessions` do usuário antes de persistir a desativação.

## 5. Web/UI (S2)

**S2.1 — `web/src/components/Modal.tsx`**: componente controlado
(`aberto`, `titulo`, `onFechar`, `children`, opcional `ariaLabel`) com: foco no
first focusable ao abrir (ou no container), focus trap no `Tab`/`Shift+Tab`,
`Escape` fecha, clique no backdrop fecha, `role="dialog"` + `aria-modal="true"` +
`aria-labelledby`, retorno de foco ao fechar, e scroll interno para forms altos.
Estilos no `global.css` (tokens existentes). `ConfirmDialog` refatorado para usá-lo
mantendo props atuais (`aberto`, `titulo`, `mensagem`, `onConfirmar`, `onCancelar`,
`confirmando`); dialog de reset de senha do Users migra para o Modal.

**S2.2 — toggle "Ver desativados" + Reativar**: hooks (`api/hooks.ts`) das páginas
com lista ganham opção (`useXxx({ includeDisabled })`) — a default continua sem
desativados (compatível). Por página: `<label>`/checkbox "Ver desativados" acima
da tabela; coluna/badge de status para inativos; botão **Reativar** nas linhas
inativas (mesmo `ConfirmDialog` do Desativar, texto inverte). Em `Users.tsx`:
corrigir `alternarAtivo` para rotular Desativar/Reativar conforme `is_active`.

**S2.3 — dialog de edição por página**: botão `Editar` na linha (quando
`podeEscrever`), `<Modal>` com os mesmos campos do form de criação preenchidos com
os valores atuais (mesmas `FormField`), submit → `mutateAsync` do hook
`useXxxAtualizar` (existente), `isPending` desabilita, erro renderizado dentro do
dialog (`role="alert"`), sucesso fecha + refetch (invalidates do react-query). Em
bgp-sessions, o modal edita os campos do PATCH — as ações especiais (communities,
password) permanecem onde estão hoje.

**S2.4 — cards do dashboard**: usando o retorno já existente de
`GET /api/v1/dashboard`: card/bloco "Equipamentos" com total e
ok/falha/desconhecido (`by_comm_status`; total = soma) e card "Coleta" com a maior
`snapshot_age_seconds` formatada (e aviso visual se > 24h).

**S2.5 — `.catch` de mutações**: em todas as páginas, a mão do `void mutate(...)`
em ações confirmadas (Desativar/Reativar/Editar, reset de senha, logout) ganha
`.catch`/estado de erro visível no padrão `role="alert"` existente — sem
unhandled rejection.

## 6. Polish, segurança e infra (S3)

**S3.1 — Playwright**: `web/e2e/playwright.config.ts` com `reuseExistingServer:
false` para o webServer; run-book e2e (web/e2e/README.md) atualizado (se a porta
8000 estiver ocupada o smoke falha já no boot).
**S3.2 — CLI**: alias `--include-disabled` em `cli/users.py` (`list --all` e
`--include-disabled` equivalentes); remover `DIST` morto em
`tests/api/test_static_spa.py:9`.
**S3.3 — docs**: seção "Estado do repositório" do CLAUDE.md atualizada (ciclo C3
concluído; follow-ups liquidados).

## 7. Testes e verificação

- **pytest**: contacts `include_disabled`; catálogos — service update (validação,
  unicidade, evento, idempotência do disable), PATCH (ruling 1, 404/400), CLI
  update (smoke); roteamento `enable_device` no PATCH de devices; rate limit
  (permitir/registrar/limpar com fake, 429 + Retry-After, fail-open); sessões
  removidas na desativação de usuário.
- **Vitest**: `Modal` (abrir/fechar: Escape, backdrop, foco inicial e retorno); uma
  página representativa (Sites): editar (chama PATCH, fecha, refetch), ver
  desativados + reativar; cards do dashboard com hook mockado (by_comm_status e
  snapshot_age_seconds, alerta > 24h).
- **e2e**: se o fluxo de edição entrar no smoke, roteiro no plan; banco dedicado
  `gerenet_e2e` (nunca o `gerenet`) — regras já em run-book.
- **Suíte completa**: `uv run pytest -q`, `uv run ruff check`, `npm run build`,
  `npm run test` e `npm run test:e2e` com o guard novo.

## 8. Riscos e cuidados

- **Protocolo de execução**: ciclo em worktree (branch de trabalho), merge no main
  executado pelo usuário (protocolo do projeto). Nenhum ciclo toca `gerenet_test`
  enquanto outro ciclo estiver em voo.
- **Convenções**: handlers de routers em PT-BR (`listar`/`atualizar`); identificadores
  de classes/colunas/serviços em EN; idioma dos artefatos PT-BR.
- **Segredos**: nenhum segredo novo no front — `credentials: "include"` apenas;
  senhas continuam fora de state persistente; rate limit não vaza informações de
  existência de usuário (mensagem 429 genérica).
- **Comportamento existente preservado**: `include_disabled` default `false` não
  muda o que as páginas consomem hoje; hooks mantêm assinatura mais permissiva
  (opcional) para não quebrar páginas/testes existentes.
