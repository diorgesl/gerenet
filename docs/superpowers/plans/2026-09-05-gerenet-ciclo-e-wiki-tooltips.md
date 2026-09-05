# Ciclo E — Wiki operacional in-app e tooltips de campos — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) ou superpowers:executing-plans para implementar este plano task-by-task. Passos usam checkbox (`- [ ]`) para rastreio.

**Goal:** Entregar um wiki operacional servido pelo próprio FastAPI (`/wiki`, autenticado) com páginas Markdown versionadas em `docs/wiki/` renderizadas no servidor, e tooltips ⓘ com descrição em todos os campos de todos os formulários da web.

**Architecture:** Backend: módulo `src/gerenet/api/wiki.py` (índice + página, markdown → HTML sanitizado com `nh3`), settings `wiki_dir`, `require_actor` no router. Frontend: página `/wiki/:slug?` na SPA (React) consumindo os endpoints com react-query; tooltips via prop `help` no `FormField` com textos centralizados em `web/src/help.ts` (tipados com `keyof typeof HELP`).

**Tech Stack:** Python 3.12 + FastAPI + markdown>=3.6 + nh3>=0.2.17; React 18 + Vite + react-router v7 + @tanstack/react-query; Vitest; Playwright; pytest.

**Spec:** [docs/superpowers/specs/2026-09-05-gerenet-ciclo-e-wiki-tooltips-design.md](../specs/2026-09-05-gerenet-ciclo-e-wiki-tooltips-design.md)

## Global Constraints

- Idioma de TODOS os artefatos (código, mensagens, textos de help, wiki, commits): **PT-BR**.
- Dependências novas mínimas: `markdown>=3.6`, `nh3>=0.2.17` (Python). Nada de YAML; frontmatter com parser próprio.
- Sanitização SEMPRE no servidor (`nh3.clean`); o React injeta HTML já sanitizado — nunca renderizar MD cru no client.
- Slugs do wiki: `^[a-z0-9][a-z0-9-]*$`; lookup por índice (nunca abrir path do usuário).
- Rotas de API seguem o padrão: `APIRouter(prefix="/api/v1/...", dependencies=[Depends(require_actor)])`.
- Textos de help: fonte das regras = `src/gerenet/domain/schemas.py`, mensagens dos services e spec §5–§8/§25; nunca inventar regra.
- `help()` tipado: chave errada deve quebrar `npm run build` (`tsc -b`).
- Commits pequenos, um por task, mensagem no padrão do repo (`feat(...)`, `docs(...)`, `test(...)`).
- Verificação obrigatória ao final de cada task: `uv run ruff check` (Python) ou `npm run test` / `npm run build` (web).

---

### Task 1: Backend do wiki — settings, índice, renderização e endpoints

**Files:**
- Modify: `pyproject.toml` (deps), `src/gerenet/config.py` (wiki_dir), `src/gerenet/api/main.py` (router)
- Create: `src/gerenet/api/wiki.py`, `tests/api/test_wiki.py`

**Interfaces:**
- Consumes: `gerenet.api.deps.require_actor`; `gerenet.config.get_settings()`.
- Produces (tasks seguintes usam):
  - `listar_wiki(wiki_dir: Path) -> list[dict]` — cada item `{slug, titulo, secao, order, em_breve}`; ordenado por `(order, titulo)`.
  - `pagina_wiki(slug: str, wiki_dir: Path) -> dict | None` — `{slug, titulo, em_breve, html}`; `None` se slug inválido/inexistente.
  - Router `wiki.router` com `GET /api/v1/wiki` → `200 list[...]` e `GET /api/v1/wiki/{slug}` → `200 {...}` | `404`.

- [ ] **Step 1: Escrever os testes que falham**

Create `tests/api/test_wiki.py`:

```python
import pytest
from fastapi.testclient import TestClient

from gerenet.api.main import create_app
from gerenet.config import Settings, set_settings


@pytest.fixture()
def client(tmp_path) -> TestClient:
    (tmp_path / "index.md").write_text(
        "---\ntitle: Visão geral\nsecao: Começando\norder: 1\n---\n# Visão geral\n\nOlá, operador.\n"
    )
    em_breve = tmp_path / "em-breve"
    em_breve.mkdir()
    (em_breve / "mpls.md").write_text(
        "---\ntitle: Serviços MPLS\nsecao: Em breve\norder: 2\nem_breve: true\n---\n# Serviços MPLS\n\nPlanejado.\n"
    )
    set_settings(Settings(wiki_dir=tmp_path, api_key="teste-key", _env_file=None))
    return TestClient(create_app())


def _auth() -> dict[str, str]:
    return {"X-API-Key": "teste-key"}


def test_indice_ordena_por_order_e_traz_em_breve(client: TestClient) -> None:
    resp = client.get("/api/v1/wiki", headers=_auth())
    assert resp.status_code == 200
    paginas = resp.json()
    assert [p["slug"] for p in paginas] == ["index", "mpls"]
    assert paginas[0]["secao"] == "Começando"
    assert paginas[1]["em_breve"] is True


def test_pagina_retorna_html_renderizado(client: TestClient) -> None:
    corpo = client.get("/api/v1/wiki/index", headers=_auth()).json()
    assert corpo["titulo"] == "Visão geral"
    assert "<h1>Visão geral</h1>" in corpo["html"]
    assert "<p>Olá, operador.</p>" in corpo["html"]


def test_rota_requer_autenticacao(client: TestClient) -> None:
    assert client.get("/api/v1/wiki").status_code == 401
    assert client.get("/api/v1/wiki/index").status_code == 401


def test_slug_invalido_da_404(client: TestClient) -> None:
    assert client.get("/api/v1/wiki/nao-existe", headers=_auth()).status_code == 404
    assert client.get("/api/v1/wiki/..%2F..%2Fetc", headers=_auth()).status_code == 404


def test_script_e_javascript_url_neutralizados(client: TestClient, tmp_path) -> None:
    (tmp_path / "index.md").write_text(
        "# Título\n\n<script>alert(1)</script>\n\n[clique](javascript:alert(1))\n"
    )
    corpo = client.get("/api/v1/wiki/index", headers=_auth()).json()
    assert "<script>" not in corpo["html"]
    assert "javascript:" not in corpo["html"]


def test_titulo_fallback_sem_frontmatter(client: TestClient, tmp_path) -> None:
    (tmp_path / "index.md").write_text("# Só título\n\ncorpo.\n")
    corpo = client.get("/api/v1/wiki/index", headers=_auth()).json()
    assert corpo["titulo"] == "Só título"


def test_docs_wiki_ausente_lista_vazia(client: TestClient, tmp_path) -> None:
    set_settings(Settings(wiki_dir=tmp_path / "sem-wiki", api_key="teste-key", _env_file=None))
    assert client.get("/api/v1/wiki", headers=_auth()).json() == []
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `uv run pytest tests/api/test_wiki.py -v`
Expected: FAIL — `ModuleNotFoundError: gerenet.api.wiki` (router não existe ainda).

- [ ] **Step 3: Adicionar dependências**

Run: `uv add "markdown>=3.6" "nh3>=0.2.17"`

- [ ] **Step 4: Adicionar `wiki_dir` aos settings**

Modify `src/gerenet/config.py` — junto de `static_dir` (linha 20):

```python
    static_dir: Path = Path("web/dist")  # build da SPA (ciclo C2)
    wiki_dir: Path = Path("docs/wiki")  # páginas do wiki operacional (ciclo E)
```

- [ ] **Step 5: Implementar `src/gerenet/api/wiki.py`**

```python
import re
from pathlib import Path

import markdown
import nh3
from fastapi import APIRouter, Depends, HTTPException

from gerenet.api.deps import require_actor

router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"], dependencies=[Depends(require_actor)])

_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "strong", "em", "del",
    "code", "pre", "blockquote", "ul", "ol", "li", "a", "table", "thead", "tbody",
    "tr", "th", "td",
}
_ATRIBUTOS = {"a": {"href", "title"}, "th": {"align"}, "td": {"align"}, "code": {"class"}}


def _frontmatter(texto: str) -> tuple[dict[str, str], str]:
    """Extrai `---\nchave: valor...\n---` do topo (parser próprio, sem YAML)."""
    if not texto.startswith("---\n"):
        return {}, texto
    fim = texto.find("\n---", 4)
    if fim == -1:
        return {}, texto
    meta: dict[str, str] = {}
    for linha in texto[4:fim].strip().splitlines():
        if ":" in linha:
            chave, valor = linha.split(":", 1)
            meta[chave.strip()] = valor.strip()
    return meta, texto[fim + 4 :].lstrip("\n")


def _slug(arquivo: Path) -> str:
    bruto = arquivo.stem.lower()
    return re.sub(r"[^a-z0-9]+", "-", bruto).strip("-")


def _titulo(meta: dict[str, str], texto_md: str) -> str:
    if meta.get("title"):
        return meta["title"]
    for linha in texto_md.splitlines():
        if linha.startswith("# "):
            return linha[2:].strip()
    return "Sem título"


def _renderizar(texto_md: str) -> str:
    html = markdown.markdown(texto_md, extensions=["tables", "fenced_code"])
    return nh3.clean(html, tags=_TAGS, attributes=_ATRIBUTOS, url_schemes={"http", "https", "mailto"})


def listar_wiki(wiki_dir: Path) -> list[dict]:
    paginas = []
    for arquivo in sorted(wiki_dir.rglob("*.md")):
        if arquivo.name.startswith("_"):
            continue
        texto = arquivo.read_text(encoding="utf-8")
        meta, corpo = _frontmatter(texto)
        paginas.append(
            {
                "slug": _slug(arquivo),
                "titulo": _titulo(meta, corpo),
                "secao": meta.get("secao", "Geral"),
                "order": int(meta.get("order", "999")),
                "em_breve": meta.get("em_breve", "").lower() in ("true", "1", "sim"),
            }
        )
    paginas.sort(key=lambda p: (p["order"], p["titulo"]))
    return paginas


def pagina_wiki(slug: str, wiki_dir: Path) -> dict | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        return None
    for arquivo in sorted(wiki_dir.rglob("*.md")):
        if arquivo.name.startswith("_") or _slug(arquivo) != slug:
            continue
        texto = arquivo.read_text(encoding="utf-8")
        meta, corpo = _frontmatter(texto)
        return {
            "slug": slug,
            "titulo": _titulo(meta, corpo),
            "em_breve": meta.get("em_breve", "").lower() in ("true", "1", "sim"),
            "html": _renderizar(corpo),
        }
    return None


@router.get("")
def wikilist() -> list[dict]:
    from gerenet.config import get_settings

    return listar_wiki(get_settings().wiki_dir)


@router.get("/{slug}")
def wikipagina(slug: str) -> dict:
    from gerenet.config import get_settings

    pagina = pagina_wiki(slug, get_settings().wiki_dir)
    if pagina is None:
        raise HTTPException(status_code=404, detail="Página do wiki não encontrada.")
    return pagina
```

> Nota: o import local de `get_settings` evita o ciclo de import (config não importa api; import no topo do módulo funcionaria, mas o import local segue o padrão de outros módulos que leem settings em runtime).

- [ ] **Step 6: Registrar o router em `main.py`**

Modify `src/gerenet/api/main.py` — import e include:

```python
from gerenet.api import auth, dashboard, jobs, users, wiki
...
    app.include_router(wiki.router)
```

- [ ] **Step 7: Rodar a suíte do wiki e a geral**

Run: `uv run pytest tests/api/test_wiki.py -v`
Expected: PASS (7 testes).

Run: `uv run pytest -q`
Expected: PASS (sem regressão — `test_actor_b2_routes.py` etc. seguem passando).

Run: `uv run ruff check`
Expected: limpo.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/gerenet/config.py src/gerenet/api/wiki.py src/gerenet/api/main.py tests/api/test_wiki.py
git commit -m "feat(api): wiki operacional — índice e página renderizados no servidor (ciclo E)
```
```

(Lembre de fechar a mensagem com a linha Co-Authored-By: Claude Code <noreply@anthropic.com>)

---

### Task 2: Frontend do wiki — types, hooks, página, rota, navegação e estilos

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/hooks.ts`, `web/src/App.tsx`, `web/src/components/Layout.tsx`, `web/src/styles/global.css`
- Create: `web/src/pages/Wiki.tsx`, `web/src/pages/Wiki.test.tsx`

**Interfaces:**
- Consumes: `listar_wiki`/`pagina_wiki` da Task 1 (contratos JSON acima); padrões de `apiFetch` e hooks existentes.
- Produces: `useWikiIndice()`, `useWikiPagina(slug: string | undefined)`; rota `/wiki/:slug?`; item de menu "Ajuda → Wiki".

- [ ] **Step 1: Escrever o teste que falha**

Create `web/src/pages/Wiki.test.tsx` — siga o padrão de mocks dos testes existentes (ex.: `web/src/pages/BgpSessions.test.tsx` usa `vi.mock`/MemoryRouter; verifique antes). Estrutura:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Wiki from "./Wiki";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn((path: string) => {
    if (path === "/api/v1/wiki")
      return Promise.resolve([
        { slug: "index", titulo: "Visão geral", secao: "Começando", order: 1, em_breve: false },
        { slug: "mpls", titulo: "Serviços MPLS", secao: "Em breve", order: 2, em_breve: true },
      ]);
    if (path === "/api/v1/wiki/index")
      return Promise.resolve({ slug: "index", titulo: "Visão geral", em_breve: false, html: "<h1>Visão geral</h1><p>Olá.</p>" });
    if (path === "/api/v1/wiki/mpls")
      return Promise.resolve({ slug: "mpls", titulo: "Serviços MPLS", em_breve: true, html: "<h1>Serviços MPLS</h1>" });
    return Promise.reject(new Error("not found"));
  }),
}));

describe("Wiki", () => {
  it("renderiza o índice (Visão geral) sem slug", async () => {
    render(
      <MemoryRouter initialEntries={["/wiki"]}>
        <Routes><Route path="/wiki/:slug?" element={<Wiki />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Visão geral" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Serviços MPLS" })).toBeInTheDocument();
  });

  it("navega por link interno sem reload", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/wiki"]}>
        <Routes>
          <Route path="/wiki/:slug?" element={<Wiki />} />
          <Route path="/outra" element={<div>outra</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole("link", { name: "Serviços MPLS" }));
    expect(await screen.findByRole("heading", { name: "Serviços MPLS" })).toBeInTheDocument();
  });

  it("mostra estado de página não encontrada", async () => {
    render(
      <MemoryRouter initialEntries={["/wiki/nao-existe"]}>
        <Routes><Route path="/wiki/:slug?" element={<Wiki />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Página não encontrada")).toBeInTheDocument();
  });
});
```

> Nota: ajuste os mocks/imports ao padrão REAL dos testes vizinhos (painel de BgpSessions/DeviceDetail: como eles fazem `vi.mock` do client e do QueryClientProvider). Os nomes/roles acima são intenção — o teste deve prender-se a: heading do índice, navegação por clique, e o estado 404.

- [ ] **Step 2: Rodar e verificar que falha**

Run: `cd web && npm run test -- --run src/pages/Wiki.test.tsx` (ou `npx vitest run src/pages/Wiki.test.tsx`)
Expected: FAIL — `Wiki.tsx` não existe.

- [ ] **Step 3: Types e hooks**

Modify `web/src/api/types.ts` (no final):

```ts
export type WikiIndiceItem = {
  slug: string;
  titulo: string;
  secao: string;
  order: number;
  em_breve: boolean;
};

export type WikiPagina = {
  slug: string;
  titulo: string;
  em_breve: boolean;
  html: string;
};
```

Modify `web/src/api/hooks.ts` (no final, padrão das demais):

```ts
import type { WikiIndiceItem, WikiPagina } from "./types"; // no topo, junto dos imports de tipo

export function useWikiIndice() {
  return useQuery({ queryKey: ["wiki-indice"], queryFn: () => apiFetch<WikiIndiceItem[]>("/api/v1/wiki") });
}

export function useWikiPagina(slug: string | undefined) {
  return useQuery({
    queryKey: ["wiki-pagina", slug],
    queryFn: () => apiFetch<WikiPagina>(`/api/v1/wiki/${slug}`),
    enabled: Boolean(slug),
  });
}
```

- [ ] **Step 4: Implementar `web/src/pages/Wiki.tsx`**

```tsx
import { Link, useNavigate, useParams } from "react-router-dom";
import { useWikiIndice, useWikiPagina } from "@/api/hooks";
import type { WikiIndiceItem } from "@/api/types";

export default function Wiki() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const indice = useWikiIndice();
  const pagina = useWikiPagina(slug ?? "index");

  const aoClicar = (e: React.MouseEvent<HTMLDivElement>) => {
    const alvo = (e.target as HTMLElement).closest("a");
    if (alvo?.getAttribute("href")?.startsWith("/wiki")) {
      e.preventDefault();
      navigate(alvo.getAttribute("href")!);
    }
  };

  if (indice.isError) return <p role="alert">Falha ao carregar o índice do wiki.</p>;
  if (indice.isLoading) return <p role="status">Carregando wiki…</p>;

  const grupos = new Map<string, WikiIndiceItem[]>();
  for (const item of indice.data ?? []) {
    const lista = grupos.get(item.secao) ?? [];
    lista.push(item);
    grupos.set(item.secao, lista);
  }

  return (
    <section className="wiki">
      <aside className="wiki-nav">
        <h2 className="wiki-titulo-nav">Documentação</h2>
        {[...grupos.entries()].map(([secao, itens]) => (
          <div key={secao}>
            <span className="wiki-secao">{secao}</span>
            {itens.map((item) => (
              <Link key={item.slug} to={`/wiki/${item.slug}`} className={item.slug === (slug ?? "index") ? "ativo" : ""}>
                {item.titulo}
                {item.em_breve && <em> (em breve)</em>}
              </Link>
            ))}
          </div>
        ))}
      </aside>
      <article className="wiki-conteudo" onClick={aoClicar}>
        {pagina.isError && (
          <p role="status">
            Página não encontrada. <Link to="/wiki">Voltar ao índice</Link>.
          </p>
        )}
        {pagina.data && (
          <>
            {pagina.data.em_breve && <p className="wiki-badge">Recurso planejado — não disponível ainda.</p>}
            <div dangerouslySetInnerHTML={{ __html: pagina.data.html }} />
          </>
        )}
      </article>
    </section>
  );
}
```

> Nota: `pagina.isError` cobre o 404 (e também falhas de rede); o estado de rede pura é aceitável como mesma mensagem neste ciclo (a spec não os distingue).

- [ ] **Step 5: Rota e navegação**

Modify `web/src/App.tsx` — import `Wiki` e rota dentro do `RequireAuth`:

```tsx
import Wiki from "@/pages/Wiki";
...
        <Route path="/wiki/:slug?" element={<Wiki />} />
```

Modify `web/src/components/Layout.tsx` — após o grupo "Governança":

```tsx
  {
    rotulo: "Ajuda",
    itens: [{ para: "/wiki", rotulo: "Wiki" }],
  },
```

- [ ] **Step 6: Estilos**

Modify `web/src/styles/global.css` — ao final (siga o tom e linhas existentes; use variáveis/paleta do arquivo):

```css
/* Wiki operacional (ciclo E) */
.wiki { display: flex; gap: 1.5rem; }
.wiki-nav { flex: 0 0 220px; }
.wiki-nav .wiki-secao { display: block; margin: 0.75rem 0 0.25rem; font-size: 0.8rem; font-weight: 600; color: var(--cor-2); }
.wiki-nav a { display: block; padding: 0.2rem 0; text-decoration: none; }
.wiki-nav a.ativo { font-weight: 600; }
.wiki-conteudo { flex: 1; min-width: 0; }
.wiki-conteudo table { border-collapse: collapse; }
.wiki-conteudo th, .wiki-conteudo td { border: 1px solid var(--cor-2); padding: 0.35rem 0.6rem; text-align: left; }
.wiki-conteudo pre { overflow-x: auto; padding: 0.75rem; }
.wiki-badge { padding: 0.4rem 0.75rem; background: var(--cor-2); border-radius: 4px; font-weight: 600; }
```

Ajuste os tokens de cor aos existentes em `global.css` (procure `--cor-` ou as variáveis do tema e use as mesmas).

- [ ] **Step 7: Rodar testes e build**

Run: `cd web && npx vitest run src/pages/Wiki.test.tsx`
Expected: PASS.

Run: `cd web && npm run test`
Expected: PASS (sem regressão).

Run: `cd web && npm run build`
Expected: build OK (`tsc -b && vite build`).

- [ ] **Step 8: Commit**

```bash
git add web/src/api/types.ts web/src/api/hooks.ts web/src/pages/Wiki.tsx web/src/pages/Wiki.test.tsx web/src/App.tsx web/src/components/Layout.tsx web/src/styles/global.css
git commit -m "feat(web): página /wiki com índice navegável e grupo Ajuda (ciclo E)"
```

---

### Task 3: `help.ts` + prop `help` no FormField + estilos do tooltip

**Files:**
- Create: `web/src/help.ts`
- Modify: `web/src/components/FormField.tsx`, `web/src/components/componentes.test.tsx`, `web/src/styles/global.css`

**Interfaces:**
- Consumes: nada (primeiro uso de `help()` nas Tasks 4–7).
- Produces: `HELP` (`Record` const), `type HelpKey`, `help(chave: HelpKey): string`; `FormField` com prop opcional `help?: string` que renderiza `<span className="field-help" tabIndex={0}>?</span>` com `<span className="field-help-dica" role="tooltip">{help}</span>`.

- [ ] **Step 1: Escrever o teste que falha**

Append a `web/src/components/componentes.test.tsx`:

```tsx
import { FormField } from "./FormField"; // ajuste aos imports do arquivo

describe("FormField help", () => {
  it("renderiza o ícone e o texto de ajuda quando help é passado", () => {
    render(<FormField label="Nome" help="Nome único (1–64 caracteres)."><input /></FormField>);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Nome único (1–64 caracteres).");
    expect(screen.getByText("?")).toBeInTheDocument();
  });

  it("não renderiza nada extra sem help", () => {
    render(<FormField label="Nome"><input /></FormField>);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
```

(Use os mesmos helpers de render/screen já importados no arquivo de testes de componentes.)

- [ ] **Step 2: Rodar e verificar que falha**

Run: `cd web && npx vitest run src/components/componentes.test.tsx`
Expected: FAIL — prop `help` não existe no FormField.

- [ ] **Step 3: Implementar `FormField`**

Modify `web/src/components/FormField.tsx`:

```tsx
import type { ReactNode } from "react";

interface Props {
  label: string;
  erro?: string;
  help?: string;
  children: ReactNode;
}

export function FormField({ label, erro, help, children }: Props) {
  return (
    <label className="field">
      <span>
        {label}
        {help && (
          <span className="field-help" tabIndex={0} aria-label={help}>
            <span className="field-help-dica" role="tooltip">
              {help}
            </span>
            ?
          </span>
        )}
      </span>
      {children}
      {erro && <em role="alert">{erro}</em>}
    </label>
  );
}
```

- [ ] **Step 4: Criar `web/src/help.ts` com TODOS os textos**

Os textos abaixo são a fonte das regras: faixas/nomes exatos de `src/gerenet/domain/schemas.py`, mensagens dos services (ASN, conflitos) e spec §25.4 (§ nomes VRP derivados) — confira cada um contra o código ao digitar.

```ts
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
  "device.name": "Nome único do equipamento (1–64). Identifica o registro e o hostname VRP.",
  "device.management_address": "Endereço IP de gestão acessível pela rede de gerência dedicada.",
  "device.ssh_port": "Porta SSH de acesso (1–65535; default 22).",
  "device.model": "Modelo do equipamento (ex.: NE8000 M8, S6730-H24X6C).",
  "device.family": "Família/plataforma (NE8000, NE40, S6730…) — define capacidades e templates usados.",
  "device.role": "Função do equipamento (borda de downstream, core MPLS, upstream…).",
  "device.asn": "ASN local (1–4294967295, reservados barrados). Vira ASN default das sessões e dá origem aos nomes RP-<ASN>-….",
  "device.site": "Site/POP onde o equipamento está instalado.",
  "device.tags": "Etiquetas livres, separadas por vírgula (ex.: BGP, MPLS, contingência).",

  // Organizations
  "organization.name": "Nome de exibição da organização (1–128 caracteres).",
  "organization.legal_name": "Razão social completa (opcional).",
  "organization.kind": "Tipo: downstream (cliente) ou parceiro.",
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
  "circuit.bfd": "Habilita BFD no enlace — detecção de falha em sub-segundos.",
  "circuit.p2p_v4_len": "Tamanho do enlace v4: /31 (padrão) ou /30, no bloco privado do site.",
  "circuit.edge_trunk": "Eth-Trunk de borda (opcional) que agrega o acesso do cliente.",
  "circuit.description": "Descrição livre (1–255).",
  "circuit.notes": "Observações livres.",
  "circuit.ip_p2p_nota": "Endereços v4/v6 do enlace são derivados pelo IPAM: v6 = /126 com sufixo dos octetos 2–4 do IPv4 relidos como hex; local :1, remoto :2.",

  // BGP sessions
  "bgp.circuit_id": "Circuito/serviço atendido pela sessão.",
  "bgp.device_id": "Equipamento onde o peering é configurado (instância pública).",
  "bgp.afi": "Família da sessão: ipv4 ou ipv6 — uma sessão por família; sem duplicar device+VRF+família.",
  "bgp.local_address": "Endereço local do enlace p2p (v4 sem máscara; v6 com /126).",
  "bgp.remote_address": "Endereço do peer no enlace p2p (v4 sem máscara; v6 com /126).",
  "bgp.source_address": "Endereço usado como source do peering quando difere do endereço do enlace (opcional).",
  "bgp.asn_local": "ASN do lado gerenet; default = ASN do equipamento.",
  "bgp.asn_remote": "ASN do peer; default = ASN da organização do circuito.",
  "bgp.description": "Descrição da sessão (1–255).",
  "bgp.import_profile_id": "Perfil de importação (direction=import) — a route-policy é gerada a partir das autorizações do cliente.",
  "bgp.export_profile_id": "Perfil de exportação (direction=export) — produto (default, parcial, full, CDN, personalizado).",
  "bgp.maximum_prefix": "Limite de prefixos recebidos (maximum-prefix) — acima disso o VRP derruba a sessão; use margem nos upstreams.",
  "bgp.maximum_prefix_threshold": "Percentual do limite (0–100) que dispara o aviso.",
  "bgp.local_preference": "local-preference aplicado na importação (maior = preferido).",
  "bgp.med": "MED aplicado na exportação (menor = preferido pelo vizinho).",
  "bgp.prepend": "Prepend no AS-PATH (0–10) — repete o ASN local para desvalorizar rotas anunciadas.",
  "bgp.keepalive": "Timer keepalive em segundos; default do VRP se vazio.",
  "bgp.holdtime": "Timer holdtime em segundos; default do VRP se vazio.",
  "bgp.bfd_enabled": "BFD sobre a sessão BGP — detecção rápida de queda do peer.",
  "bgp.graceful_restart": "Habilita gracefull restart (reinício sem queda de rotas).",
  "bgp.shutdown": "Sessão provisionada mas desligada (shutdown) — não estabelece peering.",
  "bgp.allow_default_route": "Aceita rota default (0.0.0.0/0 ou ::/0) do peer — entra antes das autorizações na prefix-list.",
  "bgp.password": "Senha MD5 do peering — segredo: nunca exibida em texto claro (espelha apenas has_password).",

  // Policy profiles
  "policy.name": "Nome único do perfil (1–64; catálogo pode ter nomes fixos seedados).",
  "policy.label": "Rótulo exibido (1–64) — nome lógico × efetivo.",
  "policy.product": "Produto de roteamento: default, default + internas, parcial, full, CDN ou personalizado — a route-policy é construída a partir do produto.",
  "policy.direction": "Direção do perfil: import (entrada) ou export (saída) — a sessão só aceita o perfil da direção correspondente.",
  "policy.kind": "Tipo de política do catálogo (route-policy clássico ou XPL — a sintaxe segue a capacidade do equipamento).",
  "policy.prefixes": "Prefixos do produto personalizado, um por linha (CIDR).",
  "policy.notes": "Observações livres.",

  // Communities
  "community.name": "Nome/valor da community (ex.: 64500:100) — 1–64 caracteres.",
  "community.notes": "Observações livres.",

  // Prefix authorizations
  "prefix.organization_id": "Organização dona da autorização (o filtro de entrada é derivado das autorizações ativas).",
  "prefix.family": "Família: ipv4 ou ipv6.",
  "prefix.prefix": "Prefixo autorizado em CIDR (ex.: 10.0.0.0/24; 2001:db8::/48) — só autorizações ativas viram IP-PFX-<ASN>-IN-<AFI>.",
  "prefix.notes": "Observações livres.",

  // Users
  "user.username": "Nome de login (1–64), único.",
  "user.password": "Senha com mínimo de 8 caracteres — jamais registrada em log ou auditoria.",
  "user.role": "Perfil de permissão: visualizador, operador, aprovador, executor ou administrador.",
} as const;

export type HelpKey = keyof typeof HELP;

export function help(chave: HelpKey): string {
  return HELP[chave];
}
```

- [ ] **Step 5: Estilos do tooltip**

Modify `web/src/styles/global.css` (ao final):

```css
/* Tooltip de campo (ciclo E) */
.field-help { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 1.1rem; height: 1.1rem; margin-left: 0.4rem; border-radius: 50%; background: var(--cor-2); color: var(--cor-1, #fff); font-size: 0.7rem; cursor: help; }
.field-help-dica { display: none; position: absolute; bottom: 130%; left: 0; z-index: 10; width: max-content; max-width: 280px; padding: 0.4rem 0.6rem; background: var(--cor-fundo-2, #222); color: var(--cor-texto, #fff); border-radius: 4px; font-size: 0.78rem; font-weight: 400; white-space: pre-line; }
.field-help:hover .field-help-dica, .field-help:focus-visible .field-help-dica { display: block; }
```

Ajuste os nomes das variáveis de cor às realmente existentes em `global.css` (use as mesmas do tema; se o projeto usa hex, use hex do fundo/texto do tema).

- [ ] **Step 6: Rodar testes e build**

Run: `cd web && npx vitest run src/components/componentes.test.tsx`
Expected: PASS (os 2 testes novos + existentes).

Run: `cd web && npm run build`
Expected: OK — o `tsc -b` compila `help.ts`.

- [ ] **Step 7: Commit**

```bash
git add web/src/help.ts web/src/components/FormField.tsx web/src/components/componentes.test.tsx web/src/styles/global.css
git commit -m "feat(web): help() centralizado e tooltips de campo no FormField (ciclo E)"
```

---

### Task 4: Aplicar help — Sites e Devices

**Files:**
- Modify: `web/src/pages/Sites.tsx`, `web/src/pages/Devices.tsx` (formulários de cadastro e dialogs de edição)

**Interfaces:**
- Consumes: `help()` da Task 3.

- [ ] **Step 1: Mapear os campos de Sites**

Em `web/src/pages/Sites.tsx`, cada `<FormField label="...">` recebe `help={help("site....")}`:

| label | chave |
|---|---|
| Nome * | `site.nome` |
| Cidade | `site.city` |
| UF | `site.uf` |
| Bloco p2p v4 | `site.p2p_ipv4_block` |
| Base p2p v6 | `site.p2p_ipv6_base` |

(Se algum label divergir no arquivo, ajuste o label da tabela — a chave é a que vale.)

- [ ] **Step 2: Aplicar nos dois formulários de Sites (cadastro + dialog de edição)**

Adicione `import { help } from "@/help";` no topo e a prop `help={help("site.nome")}` etc. em cada `FormField` (os dois blocos — o dialog de editar repete os mesmos campos).

- [ ] **Step 3: Mapear e aplicar em Devices**

Em `web/src/pages/Devices.tsx` (formulário de cadastro — campos listados abaixo — e dialog de edição, que repete porta/modelo/família/função/site/ASN/tags):

| label | chave |
|---|---|
| Nome * | `device.name` |
| IP de gestão * | `device.management_address` |
| Porta SSH | `device.ssh_port` |
| Modelo | `device.model` |
| Família | `device.family` |
| Função | `device.role` |
| ASN | `device.asn` |
| Site | `device.site` |
| Tags (separadas por vírgula) | `device.tags` |

- [ ] **Step 4: Verificar**

Run: `cd web && npm run build` (a chave de qualquer `help()` errada quebra aqui).
Run: `cd web && npm run test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Sites.tsx web/src/pages/Devices.tsx
git commit -m "feat(web): tooltips de campo em Sites e Equipamentos (ciclo E)"
```

---

### Task 5: Aplicar help — Organizações e Contatos

**Files:**
- Modify: `web/src/pages/Organizations.tsx`, `web/src/pages/Contacts.tsx`

- [ ] **Step 1: Aplicar em Organizations**

Chaves por label (confira no arquivo; o dialog de edição repete):

| label | chave |
|---|---|
| Nome * | `organization.name` |
| Razão social | `organization.legal_name` |
| Tipo | `organization.kind` |
| ASN | `organization.asn` |
| AS-SET (IRR) | `organization.irr_as_set` |
| Observações | `organization.notes` |

- [ ] **Step 2: Aplicar em Contacts**

| label | chave |
|---|---|
| Organização * | `contact.organization_id` |
| Nome * | `contact.name` |
| E-mail | `contact.email` |
| Telefone | `contact.phone` |
| Tipo | `contact.kind` |

- [ ] **Step 3: Verificar**

Run: `cd web && npm run build` e `cd web && npm run test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Organizations.tsx web/src/pages/Contacts.tsx
git commit -m "feat(web): tooltips de campo em Organizações e Contatos (ciclo E)"
```

---

### Task 6: Aplicar help — Circuitos e Sessões BGP

**Files:**
- Modify: `web/src/pages/Circuits.tsx`, `web/src/pages/BgpSessions.tsx` (formulário e dialogs — CircuitDetail/BgpSessionDetail não têm formulário; apenas exibição)

- [ ] **Step 1: Aplicar em Circuits**

| label | chave |
|---|---|
| Código * | `circuit.code` |
| Organização * | `circuit.organization_id` |
| Site * | `circuit.site_id` |
| Equipamento de acesso * | `circuit.access_device_id` |
| Porta de acesso * | `circuit.access_port` |
| Equipamento de borda * | `circuit.edge_device_id` |
| Equipamento de contingência | `circuit.backup_edge_device_id` |
| Stack | `circuit.stack` |
| Modo de VLAN | `circuit.vlan_mode` |
| QinQ | `circuit.qinq` |
| VRF | `circuit.vrf` |
| MTU | `circuit.mtu` |
| Banda | `circuit.bandwidth` |
| BFD | `circuit.bfd` |
| Comprimento p2p v4 | `circuit.p2p_v4_len` |
| Eth-Trunk de borda | `circuit.edge_trunk` |
| Descrição | `circuit.description` |
| Observações | `circuit.notes` |
| (bloco de endereços derivados, se houver texto explicativo na tela) | `circuit.ip_p2p_nota` |

> Se na tela existir um texto/parágrafo sobre os endereços derivados (pontas v4/v6), substitua-o/complete com `help={help("circuit.ip_p2p_nota")}` onde fizer sentido — senão, adicione o help ao campo de comprimento/default dos endereços.

- [ ] **Step 2: Aplicar em BgpSessions**

| label | chave |
|---|---|
| Circuito * | `bgp.circuit_id` |
| Equipamento * | `bgp.device_id` |
| Família (AFI) * | `bgp.afi` |
| Endereço local * | `bgp.local_address` |
| Endereço remoto * | `bgp.remote_address` |
| Endereço de origem | `bgp.source_address` |
| ASN local | `bgp.asn_local` |
| ASN remoto | `bgp.asn_remote` |
| Descrição | `bgp.description` |
| Perfil de importação | `bgp.import_profile_id` |
| Perfil de exportação | `bgp.export_profile_id` |
| Prefixos máximos | `bgp.maximum_prefix` |
| Limiar (%) | `bgp.maximum_prefix_threshold` |
| Local preference | `bgp.local_preference` |
| MED | `bgp.med` |
| Prepend | `bgp.prepend` |
| Keepalive | `bgp.keepalive` |
| Holdtime | `bgp.holdtime` |
| BFD | `bgp.bfd_enabled` |
| Graceful restart | `bgp.graceful_restart` |
| Shutdown | `bgp.shutdown` |
| Rota default | `bgp.allow_default_route` |
| Senha | `bgp.password` |

- [ ] **Step 3: Verificar**

Run: `cd web && npm run build` e `cd web && npm run test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Circuits.tsx web/src/pages/BgpSessions.tsx
git commit -m "feat(web): tooltips de campo em Circuitos e Sessões BGP (ciclo E)"
```

---

### Task 7: Aplicar help — catálogos, autorizações e usuários

**Files:**
- Modify: `web/src/pages/PolicyProfiles.tsx`, `web/src/pages/Communities.tsx`, `web/src/pages/PrefixAuthorizations.tsx`, `web/src/pages/Users.tsx`

- [ ] **Step 1: Aplicar em PolicyProfiles**

| label | chave |
|---|---|
| Nome * | `policy.name` |
| Produto | `policy.product` |
| Direção | `policy.direction` |
| Tipo | `policy.kind` |
| Prefixos | `policy.prefixes` |
| Observações | `policy.notes` |

(Use `policy.label` se houver campo de rótulo na tela.)

- [ ] **Step 2: Aplicar em Communities**

| label | chave |
|---|---|
| Nome * | `community.name` |
| Observações | `community.notes` |

- [ ] **Step 3: Aplicar em PrefixAuthorizations**

| label | chave |
|---|---|
| Organização * | `prefix.organization_id` |
| Família * | `prefix.family` |
| Prefixo * | `prefix.prefix` |
| Observações | `prefix.notes` |

- [ ] **Step 4: Aplicar em Users**

| label | chave |
|---|---|
| Usuário * | `user.username` |
| Senha * | `user.password` |
| Papel | `user.role` |

- [ ] **Step 5: Verificar**

Run: `cd web && npm run build` e `cd web && npm run test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/PolicyProfiles.tsx web/src/pages/Communities.tsx web/src/pages/PrefixAuthorizations.tsx web/src/pages/Users.tsx
git commit -m "feat(web): tooltips de campo em catálogos, autorizações e usuários (ciclo E)"
```

---

### Task 8: Conteúdo do wiki (10 páginas em `docs/wiki/`)

**Files:**
- Create: `docs/wiki/index.md`, `docs/wiki/comecar.md`, `docs/wiki/equipamentos.md`, `docs/wiki/organizacao.md`, `docs/wiki/circuitos.md`, `docs/wiki/roteamento.md`, `docs/wiki/operacao.md`, `docs/wiki/em-breve/mudancas-controladas.md`, `docs/wiki/em-breve/mpls.md`, `docs/wiki/em-breve/upstreams.md`

**Interfaces:**
- Consumes: Task 1 (frontmatter `title`/`secao`/`order`/`em_breve`); as páginas linkam entre si com `[texto](/wiki/<slug>)`.

- [ ] **Step 1: Escrever `index.md` — modelo de estilo (guia do operador)**

```markdown
---
title: Visão geral e conceitos
secao: Começando
order: 1
---

# Visão geral e conceitos

O gerenet é o gerenciador de rede Huawei VRP: ele guarda a **intenção** da rede
(clientes, equipamentos, circuitos, sessões BGP) e compara com o **estado real**
coletado dos roteadores e switches.

## Conceitos que você precisa conhecer

- **Source of Truth**: o banco é a fonte da intenção. O que você cadastra aqui é o
  que a rede *deve* ter — nunca o que ela *tem* (isso vem da coleta).
- **Intenção × implementação**: você cadastra dados estruturados (ASN, prefixos,
  produto); os nomes VRP são derivados automaticamente
  (ex.: `RP-64500-IMPORT-V4`) — não há campo para digitar nome de política.
- **Mudança segura**: nenhuma alteração toca o roteador sem validação, plano,
  aprovação e auditoria (§3.3 da spec). No estado atual, a aplicação em
  equipamento chega com o fluxo de mudanças (em breve).

## Navegação rápida

| O que você quer fazer | Página |
|---|---|
| Primeiro acesso e cadastro do primeiro equipamento | [Primeiros passos](/wiki/comecar) |
| Cadastrar circuito e sessão BGP | [Circuitos](/wiki/circuitos), [Roteamento](/wiki/roteamento) |
| Ver o que a coleta encontrou | [Operação](/wiki/operacao) |
```

- [ ] **Step 2: Escrever `comecar.md`**

`title: Primeiros passos: login, perfis e primeiro equipamento`, `secao: Começando`, `order: 2`. Conteúdo exigido (escreva em prosa de passo a passo, com tabelas onde ajudar):

1. Login com usuário/senha; o primeiro usuário é criado no admin (bootstrap — veja `README.md`).
2. Perfis e o que cada um pode fazer (`operador` cadastra; `aprovador` aprovador; `executor` executa; `administrador` administra usuários; `visualizador` só lê).
3. Passo a passo: cadastrar um **Site** → um **Equipamento** → rodar a primeira **coleta** (Jobs) → ver o **Snapshot**.
4. Aviso: credenciais do equipamento vêm do grupo de credenciais (Vault) — nunca cadastrar senha no formulário de equipamento.

- [ ] **Step 3: Escrever `equipamentos.md`**

`title: Equipamentos, coleta e snapshots`, `secao: Começando`, `order: 3`. Conteúdo:

- Campos do cadastro (com o que cada um dispara: família define capacidades/templates).
- `comm_status` e o que significa (alcançável/inalcançável, última coleta).
- Coleta: o que é coletado hoje (version, backup `display current-configuration`, interfaces, peers BGP) e o que ainda não é (policies/communities estruturados — ainda dentro do backup cru).
- Jobs: fila, estados (`queued`, `running`, `success`, `partial`, `error`), e o que fazer com `partial`/`error` (ver `JobDetail`, logs; verificar acessibilidade/permissões).

- [ ] **Step 4: Escrever `organizacao.md`**

`title: Organizações e contatos`, `secao: Cadastro`, `order: 1`. Conteúdo:

- Organização: tipos (downstream/parceiro), ASN único e regras (32 bits, reservados barrados), AS-SET IRR.
- Contatos: tipos técnico/NOC/admin e onde são usados (notificações — em breve).
- Desativação: objetos em uso são desativados, nunca excluídos.

- [ ] **Step 5: Escrever `circuitos.md`**

`title: Circuitos, VLANs e IPAM`, `secao: Cadastro`, `order: 2`. Conteúdo (fonte: spec §6.2 e §25.8):

- Circuito: código único; pontas (acesso/borda/contingência); stack (ipv4/ipv6/dual); VLAN única × separada; QinQ; VRF (vazio = pública); MTU (576–9600); BFD; banda.
- **Endereçamento p2p derivado**: v4 `/31` (opção `/30`) no bloco privado do site; v6 `/126` com sufixo derivado dos octetos 2–4 do IPv4 em hex (local `:1`, remoto `:2`) — mostre um exemplo numérico.
- Validações do sistema: VLAN/endereços em uso no domínio, duplicidade de circuito.

- [ ] **Step 6: Escrever `roteamento.md`**

`title: Sessões BGP, autorizações, perfis e communities`, `secao: Roteamento`, `order: 1`. Conteúdo (fonte: spec §6.3–6.5, §7, §8, §25.4):

- Sessão BGP por família; uma sessão por device+VRF+família; peers na instância pública.
- Autorizações de prefixos: só autorizações ativas viram `IP-PFX-<ASN>-IN-<AFI>`; `allow_default_route` adiciona `0.0.0.0/0`/`::/0` no índice 5.
- Perfis de política: direção import/export; produtos (default, parcial, full, CDN, personalizado); nomes derivados `RP-<ASN>-IMPORT-<AFI>` / `-EXPORT-`.
- Communities: catálogo seedado; associação à sessão.
- Proteções: maximum-prefix + limiar; note que **importação de políticas existentes do roteador não existe ainda** — o que está no roteador com nome fora do padrão aparece como divergência.

- [ ] **Step 7: Escrever `operacao.md`**

`title: Reconciliação, config desejada, jobs e auditoria`, `secao: Operação`, `order: 1`. Conteúdo (fonte: spec §10, §13, §18):

- Snapshot × config desejada × reconciliação: o que cada tela mostra (desejado × encontrado × severidade × ação recomendada).
- A reconciliação **não altera produção**: gera plano (no ciclo atual apenas leitura; o fluxo de mudança é "em breve").
- Jobs de coleta e erros comuns (acessibilidade, credenciais, template).
- Auditoria: o que é registrado, quem, quando; valores sensíveis mascarados.

- [ ] **Step 8: Escrever as 3 páginas "em breve"**

Cada uma com `secao: Em breve`, `em_breve: true`, e estrutura:

- `mudancas-controladas.md` (`order: 1`): o que está previsto (change request, plano, aprovação, execução com lock, backup, rollback) — e aviso: **nenhuma mudança em equipamento é executada pela plataforma hoje**.
- `mpls.md` (`order: 2`): L2VC (VC-ID único, pontas A/B) e VSI (peers LDP, ACs) — planejado; consulte o item do roadmap §22 F4.
- `upstreams.md` (`order: 3`): trânsito/IX/PNI, full routes, communities de TE, prepend/blackhole, IRR/RPKI — planejado.

- [ ] **Step 9: Validar renderização e remoção no índice**

Run:
```bash
uv run pytest tests/api/test_wiki.py -v
uv run uvicorn gerenet.api.main:create_app --factory --port 8000
```
Em outra aba: `curl -s localhost:8000/api/v1/wiki | python -m json.tool` — deve listar as 10 páginas (7 com `em_breve: false`, 3 com `true`). Verifique também `curl -s localhost:8000/api/v1/wiki/mpls`.

- [ ] **Step 10: Commit**

```bash
git add docs/wiki/
git commit -m "docs(wiki): conteúdo operacional do wiki (10 páginas, PT-BR) (ciclo E)"
```

---

### Task 9: Fumo e2e + README + CLAUDE.md

**Files:**
- Modify: `web/e2e/smoke.spec.ts`, `README.md`, `CLAUDE.md`
- Create: (nenhum)

- [ ] **Step 1: Adicionar fumo do wiki e do tooltip ao `web/e2e/smoke.spec.ts`**

Anexe ao arquivo (reutilize o helper `entrar` já existente):

```ts
test("wiki abre pelo menu Ajuda e tooltip aparece em campo de formulário", async ({ page }) => {
  await entrar(page);

  // Wiki: menu Ajuda → índice renderiza a página "Visão geral"
  await page.getByRole("link", { name: "Wiki" }).click();
  await expect(page).toHaveURL(/\/wiki/);
  await expect(page.getByRole("heading", { name: "Visão geral e conceitos" })).toBeVisible();

  // Navega pela sidebar para uma página "em breve" e vê o badge de aviso
  await page.getByRole("link", { name: /Serviços MPLS/ }).click();
  await expect(page.getByText("Recurso planejado — não disponível ainda.")).toBeVisible();

  // Tooltip: o ícone de ajuda do campo "Nome *" mostra a dica no hover
  await page.goto("/sites");
  await page.locator("label.field").first().locator(".field-help").hover();
  await expect(page.locator(".field-help-dica").first()).toBeVisible();
});
```

- [ ] **Step 2: Rodar o fumo**

```bash
cd web && npm run test:e2e
```
(Os e2e exigem o banco `gerenet_e2e` criado/migrado e `reuseExistingServer: false` — porta 8000 ocupada é falha dura; veja `web/e2e/README.md`.)

Expected: PASS (3 fumos: site, reconcile, wiki/tooltip).

- [ ] **Step 3: Atualizar README**

Adicione seção curta "Wiki operacional": após o build da SPA, o operador acessa `/wiki` autenticado; o conteúdo vive em `docs/wiki/` (edição via PR; frontmatter `title`/`secao`/`order`/`em_breve`).

- [ ] **Step 4: Atualizar CLAUDE.md (estado do repositório)**

Adicione ao estado atual: ciclo E — wiki operacional (`/wiki`, API `/api/v1/wiki`, `docs/wiki/`, renderização servidor com `markdown`+`nh3`) e tooltips de campos (prop `help` no FormField, textos em `web/src/help.ts` — `npm run build` valida chaves).

- [ ] **Step 5: Commit**

```bash
git add web/e2e/smoke.spec.ts README.md CLAUDE.md
git commit -m "docs(chore): fumo e2e do wiki/tooltips + README e CLAUDE.md do ciclo E"
```

---

## Self-review (a ser feito após escrever o plano — checar se cada requisito da spec tem task)

- [x] Spec §3.1 render no servidor → Task 1 (`_renderizar` + `nh3`)
- [x] Spec §4.1 contratos/401/404 → Task 1 (testes + router)
- [x] Spec §4.2 frontmatter/slug/ordenação → Task 1 (`_frontmatter`, `_slug`, sort)
- [x] Spec §4.3 settings/deps → Task 1 step 3–4
- [x] Spec §5 SPA/rota/nav/CSS → Task 2
- [x] Spec §6 FormField/help.ts/todos os formulários → Tasks 3–7
- [x] Spec §7 conteúdo/wiki → Task 8
- [x] Spec §8 casos-limite (dir ausente, fallback título, 404) → Task 1 testes
- [x] Spec §9 testes (pytest, Vitest, fumo e2e) → Tasks 1, 2, 3, 9
- [x] Spec §10 README/CLAUDE.md → Task 9
