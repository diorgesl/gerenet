# Design — Ciclo E: wiki operacional in-app e tooltips de campos (gerenet)

> Especificação do **ciclo E** do gerenet. Ciclo D (mudança controlada — change requests,
> aprovação, execução, rollback) está **apenas na forma de plano** (`docs/superpowers/plans/
> 2026-09-05-gerenet-ciclo-d-mudanca.md`) — fora do escopo deste ciclo.
> Documentos-fonte: [ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md](../../../ESPECIFICACAO_GERENCIADOR_REDE_HUAWEI.md)
> (§3.1, §3.4, §5–§8, §10, §14, §25.4, §25.8), designs dos ciclos A–C3.

## 1. Objetivo e escopo

Os operadores da plataforma precisam saber **usar** o sistema lendo apenas uma fonte, sem ler a
spec do produto nem os planos de ciclos. O ciclo E entrega:

1. **Wiki operacional** servido pelo próprio FastAPI (`/wiki`, autenticado): páginas em
   Markdown versionadas no repo, renderizadas para HTML **sanitizado no servidor**, com índice
   navegável dentro da SPA. Cobre tudo o que está implementado (ciclos A–C3) **e** páginas
   marcadas "em breve" (mudança controlada, MPLS, upstreams).
2. **Tooltips de campo**: ícone ⓘ ao lado do label em **todos** os campos de **todos** os
   formulários (telas e dialogs de edição do C3), com 1–2 frases de referência — regras de
   nomenclatura, faixas válidas, o que o campo dispara.

Fora de escopo (destino): editor de wiki no app (edição é por PR no repo), documentação da API
REST para desenvolvedores (o operador usa a web), i18n, histórico/versões de páginas do wiki,
importação assistida de config existente do roteador (decisão de produto ainda não tomada —
o wiki documenta apenas o fluxo top-down atual), qualquer mudança no fluxo de mudanças (ciclo D).

## 2. Contexto (o que já existe)

- **Web (C2/C3)**: SPA React + Vite + react-router v7 + react-query; `Layout` com navegação
  lateral por grupos (`GRUPOS_NAV` em `web/src/components/Layout.tsx`); CSS único em
  `web/src/styles/global.css`; `FormField({label, erro, children})` em
  `web/src/components/FormField.tsx` — **sem suporte a help**.
- **API (A–C3)**: routers por recurso em `src/gerenet/api/routers/` com
  `APIRouter(prefix="/api/v1/...", dependencies=[Depends(require_actor)])`; `create_app` em
  `src/gerenet/api/main.py` monta os routers e o fallback SPA (`montar_spa`).
- **Settings**: `src/gerenet/config.py` (pydantic-settings, env prefix `GERENET_`); já tem
  `static_dir: Path = Path("web/dist")` — o wiki_dir segue o mesmo padrão.
- **Sem lib de markdown em nenhum dos lados**: `pyproject.toml` não tem `markdown`/`nh3`/`bleach`;
  `web/package.json` não tem `react-markdown` nem sanitizers — deps novas são necessárias.
- **Sem dívida de segurança relacionada**: não há renderização de HTML de usuário hoje.

## 3. Decisões de design (aprovadas em 2026-09-05 no brainstorm)

1. **Renderização no servidor (abordagem A)**: `markdown` (extras `tables` e `fenced_code`) +
   `nh3` no Python; a API devolve HTML **já sanitizado**; o React apenas injeta. Motivo: casa com
   "o FastAPI serve os markdowns renderizados", conteúdo fora do bundle da SPA, sanitização única
   e testável no backend (pytest).
2. **Páginas em `docs/wiki/*.md`** no repo (PT-BR), cada uma com bloco `---` no topo contendo
   apenas `title:`, `secao:`, `order:`, `em_breve:` — parser próprio de ~20 linhas, **sem
   dependência de YAML**. A seção "Em breve" é definida por `secao: Em breve` no frontmatter +
   `em_breve: true` (o flag controla o aviso na UI); a pasta `em-breve/` é apenas organizacional.
3. **API** `GET /api/v1/wiki` (índice) e `GET /api/v1/wiki/{slug}` (página) atrás de
   `require_actor` (qualquer perfil logado; wiki não é admin-only). **Path traversal**: slugs
   flat `^[a-z0-9][a-z0-9-]*$` resolvidos por lookup no índice (dict slug → caminho relativo),
   nunca com path derivado do usuário; slug inexistente → 404.
4. **Sem cache** dos markdowns: leitura a cada request (páginas pequenas; evita dado obsoleto
   após edição/merge).
5. **Wiki como página da SPA**: rota `/wiki/:slug?` autenticada; novo grupo "Ajuda → Wiki" no
   `GRUPOS_NAV`; links internos entre páginas (escritos nos MD como `/wiki/<slug>`) interceptados
   no container para navegação SPA sem reload.
6. **Tooltips**: textos centralizados em `web/src/help.ts` (`const HELP = {...} as const` +
   `help(chave)` tipado com `keyof typeof HELP` — chave errada derruba o `tsc -b`); `FormField`
   ganha `help?: string` e renderiza o ícone com popover em hover/foco (CSS puro em
   `global.css`); textos derivados da spec §5–§8 e das **validações reais** dos services.
7. **Wiki e tooltips se complementam**: cada página de wiki e cada help citam a mesma regra
   (ex.: `RP-<ASN>-IMPORT-V4`), sem duplicar redações — o help dá a regra curta; o wiki dá o
   passo a passo.

## 4. Backend — API do wiki

Novo módulo `src/gerenet/api/wiki.py` (+ router em `main.py`), `SECAO_EM_BREVE = "Em breve"`.

### 4.1 Contratos

`GET /api/v1/wiki` → `200`, lista ordenada por `(order, titulo)`:

```json
[{"slug": "index", "titulo": "Visão geral", "secao": "Começando", "order": 1, "em_breve": false}]
```

`GET /api/v1/wiki/{slug}` → `200`:

```json
{"slug": "index", "titulo": "Visão geral", "em_breve": false, "html": "<h1>Visão geral</h1>…"}
```

- `401` sem login (padrão `require_actor`); `404` para slug inválido ou inexistente.
- `docs/wiki` ausente (ou vazio) → índice `[]`; a SPA mostra estado "wiki vazio" (dir não
  versionado? documentado — o repo sempre terá os MDs) — **não** é erro de servidor.
- Campo `em_breve` repetido no payload da página para o banner na UI.

### 4.2 Indexação e frontmatter

`_ler_indice(wiki_dir) -> list[Pagina]` caminha recursivamente por `*.md` (ignora `_`),
parseia o bloco inicial `---\n<chave: valor>\n---`:

- `title:` (obrigatório na prática; fallback: nome do arquivo);
- `secao:` (default `"Geral"`; `em-breve/` não implica `secao` — o autor marka as duas coisas);
- `order:` (int, default 999);
- `em_breve:` (`true`/`false`, default `false`).

Slug: nome do arquivo sem `.md`, normalizado (`[^a-z0-9-]` → `-`, lowercase). Índice = dict
`{slug: Pagina}` para lookup; a lista ordenada vai na resposta.

`_renderizar(md_texto) -> html`:
`markdown.markdown(texto, extensions=["tables", "fenced_code"])` → `nh3.clean`:

- tags: `h1`–`h6`, `p`, `br`, `hr`, `strong`, `em`, `del`, `code`, `pre`, `blockquote`, `ul`,
  `ol`, `li`, `a`, `table`, `thead`, `tbody`, `tr`, `th`, `td`;
- attributes: `a: {href, title}`, `th/td: {align}`, `code: {class}` (linguagem dos fences;
  sem highlight — CSS simples em `global.css`);
- `url_schemes={"http", "https", "mailto"}` — `javascript:` e afins caem no sanitizador;
- `link_rel` não necessário (não usamos `target=_blank`).

### 4.3 Settings e dependências

- `pyproject.toml`: `"markdown>=3.6"`, `"nh3>=0.2.17"` em `dependencies`.
- `config.py`: `wiki_dir: Path = Path("docs/wiki")` (env `GERENET_WIKI_DIR`), comentário no
  padrão do `static_dir`.
- Assinaturas: funções puras `listar_wiki(session, dir_)` / `pagina_wiki(slug, dir_)` separadas
  dos handlers (testáveis sem HTTP, padrão do repo); `Depends(require_actor)` no router e o
  diretório lido de `get_settings()`.

## 5. Frontend — página Wiki

- `web/src/api/hooks.ts`: `useWikiIndice()` e `useWikiPagina(slug)` no padrão dos hooks
  existentes (react-query, `apiFetch`).
- `web/src/pages/Wiki.tsx`:
  - `useParams<{slug?: string}>`; sem slug → `docs/wiki/index.md` renderizada.
  - Sidebar interna (`.wiki-nav`): itens agrupados por `secao` na ordem do índice; item ativo
    destacado; itens `em_breve` com badge.
  - Conteúdo: `<div className="wiki-conteudo" dangerouslySetInnerHTML={{__html: page.html}} />`
    (HTML **já** sanitizado no servidor — nunca renderizar MD cru no client).
  - Banner (`.wiki-badge`) quando `em_breve: true`: "Recurso planejado — não disponível ainda".
  - Interceptação: `onClick` no container — se `closest("a[href^='/wiki/']")`, `preventDefault` +
    `navigate(href)`.
  - Página `404` (slug inválido): estado "Página não encontrada" com link para o índice; estado
    de erro de rede e carregamento no padrão das páginas existentes.
- `App.tsx`: `<Route path="/wiki/:slug?" element={<Wiki />} />` dentro do `RequireAuth`.
- `Layout.tsx`: novo grupo `{ rotulo: "Ajuda", itens: [{ para: "/wiki", rotulo: "Wiki" }] }`.
- CSS em `global.css`: `.wiki-*` (nav, conteúdo, tabelas, code/pre, badge) no tom do tema
  existente; links internos sem `text-decoration` no nav.

## 6. Tooltips de campo

- `FormField`:
  - nova prop `help?: string`; quando presente, renderiza após o label:
    `<span className="field-help" data-help={help} tabIndex={0} aria-label={help}>?</span>`
  - CSS: `.field-help` (círculo discreto junto ao label); `.field-help::after` com
    `content: attr(data-help)`, `position: absolute`, `white-space: pre-line`, `max-width` e
    `z-index`; visível em `:hover`, `:focus-visible` e `:focus-within` do container.
- `web/src/help.ts`:
  ```ts
  export const HELP = {
    "site.nome": "…",
    "circuit.dot1q": "…",
    // …
  } as const;
  export type HelpKey = keyof typeof HELP;
  export function help(chave: HelpKey): string { return HELP[chave]; }
  ```
- Aplicação: **todos** os `FormField` de todos os formulários — páginas e dialogs de edição:
  `Sites`, `Devices` (+ detail), `Organizations`, `Contacts`, `Circuits` (+ detail/inline),
  `BgpSessions` (+ detail), `PolicyProfiles`, `Communities`, `PrefixAuthorizations`, `Users` —
  incluindo selects com escolha (ex.: `role`, `type`, `afi`, `product`) e os campos opcionais
  ambíguos (`admin_status` × `shutdown`).
- Fonte dos textos (não inventar regra): mensagens de validação dos services
  (`src/gerenet/domain/services/`), schemas, `automation/naming.py`, IPAM `ipam.py` e spec
  §5–§8/§25. Exemplos de chave → regra: `bgp.afi` (por família; session não duplicada por
  device+VRF+família), `circuit.mtu` (fim a fim MPLS), `bgp.max_prefix` (+ limiar de aviso),
  `circuit.ipv6_p2p` (`/126` derivado dos octetos 2–4 do IPv4 relidos como hex, local `:1`),
  `device.asn` (ASN local / router-id), `policy.product` (política construída a partir do
  produto — sem edição manual por cliente).

## 7. Conteúdo: páginas do wiki

Em `docs/wiki/` (o índice abaixo é o esqueleto; o texto completo é escrito no ciclo):

| arquivo (slug) | título | secao | em_breve |
|---|---|---|---|
| `index` | Visão geral e conceitos | Começando | não |
| `comecar` | Primeiros passos: login, perfis e primeiro equipamento | Começando | não |
| `equipamentos` | Equipamentos, coleta e snapshots | Começando | não |
| `organizacao` | Organizações e contatos | Cadastro | não |
| `circuitos` | Circuitos, VLANs e IPAM | Cadastro | não |
| `roteamento` | Sessões BGP, autorizações, perfis e communities | Roteamento | não |
| `operacao` | Reconciliação, config desejada, jobs e auditoria | Operação | não |
| `em-breve/mudancas-controladas.md` (`mudancas-controladas`) | Mudança controlada (ciclo D) | Em breve | sim |
| `em-breve/mpls.md` (`mpls`) | Serviços MPLS (L2VC e VSI) | Em breve | sim |
| `em-breve/upstreams.md` (`upstreams`) | Upstreams, IRR/RPKI e blackhole | Em breve | sim |

Conteúdo de cada página, no estilo "guia do operador": o que cadastrar (com telas), regras e
validações que o sistema aplica (as mesmas dos services), o que acontece depois (coleta,
divergência, próxima ação) e "em breve" onde aplicável — com links entre páginas
(`/wiki/<slug>`). Páginas **não** documentam o ciclo D nem MPLS/upstreams como recurso pronto —
apenas o que virá e o que o operador **não** consegue fazer ainda.

## 8. Tratamento de erros e casos-limite

- `docs/wiki` ausente/vazio → índice `[]`, SPA mostra "Nenhuma página ainda" (não quebra login).
- MD malformado (sem frontmatter) → título = nome do arquivo, sem erro.
- Fence de código com linguagem desconhecida → `code[class]` preservado como texto, sem
  highlight (não há lib de highlight no ciclo).
- Slug com acento/maíscula → normalizado no índice; request com slug raw → 404 (não normaliza
  na request).
- Link externo nos MDs → abre na mesma aba (sem `target=_blank`).

## 9. Testes

- **pytest** `tests/api/test_wiki.py` (com `wiki_dir` temporário via `set_settings`):
  - índice: ordenação, campos, `em_breve` no índice; dir vazio → `[]`;
  - página: HTML renderizado contém `h1` do título, tabela/fence preservados;
  - `require_actor`: 401 sem sessão (padrão das rotas);
  - `404` slug inválido (`../../etc/passwd`, slug inexistente);
  - **sanitização**: MD contendo `<script>alert(1)</script>` e `[x](javascript:alert(1))` →
    neutro no HTML;
  - título fallback (sem frontmatter).
- **Vitest**:
  - `Wiki.test.tsx`: rendereiza índice agrupado por seção; clique em link interno navega sem
    recarregar (MemoryRouter); página 404 mostra link ao índice;
  - `componentes.test.tsx`: `FormField` com `help` renderiza o ícone; hover/focus torna o
    tooltip visível (`aria-label`/`data-help`); sem `help` não renderiza nada extra.
- **Playwright (fumo)**: login → `/wiki` carrega com "Visão geral" e seções visíveis; uma tela
  com `FormField`+help mostra o tooltip no hover.
- Qualidade: `uv run ruff check`, `uv run pytest -q`, `npm run test`, `npm run build`
  (o `tsc -b` é quem verifica as chaves de `help()`), `npm run test:e2e`.

## 10. Impacto em arquivos

| Arquivo | Ação |
|---|---|
| `pyproject.toml` | deps `markdown>=3.6`, `nh3>=0.2.17` |
| `src/gerenet/config.py` | `wiki_dir: Path` |
| `src/gerenet/api/wiki.py` | novo — índice/página + sanitização |
| `src/gerenet/api/main.py` | incluir `wiki.router` |
| `web/src/api/hooks.ts` | hooks `useWikiIndice`/`useWikiPagina` |
| `web/src/pages/Wiki.tsx` | novo |
| `web/src/App.tsx`, `web/src/components/Layout.tsx` | rota + grupo Ajuda |
| `web/src/components/FormField.tsx`, `web/src/styles/global.css` | prop `help` + estilos |
| `web/src/help.ts` | novo — textos de todos os campos |
| telas/formulários (`web/src/pages/*.tsx`) | `help={help("...")}` em todos os campos (item maior) |
| `docs/wiki/*.md` | novo — 10 páginas |
| `tests/api/test_wiki.py`, `web/src/pages/Wiki.test.tsx`, `web/src/components/componentes.test.tsx`, `web/e2e/*` | novos/ajustes |
| `CLAUDE.md`, `README.md` | estado do repo + wiki |
