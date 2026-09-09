import re
from pathlib import Path

import markdown
import nh3
from fastapi import APIRouter, Depends, HTTPException

from gerenet.api.deps import require_actor
from gerenet.config import get_settings

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


def _order(meta: dict[str, str]) -> int:
    try:
        return int(meta.get("order", "999"))
    except (TypeError, ValueError):
        return 999


def _secao_order(meta: dict[str, str]) -> int:
    try:
        return int(meta.get("secao_order", "999"))
    except (TypeError, ValueError):
        return 999


def _renderizar(texto_md: str) -> str:
    html = markdown.markdown(texto_md, extensions=["tables", "fenced_code"])
    return nh3.clean(html, tags=_TAGS, attributes=_ATRIBUTOS, url_schemes={"http", "https", "mailto"})


def listar_wiki(wiki_dir: Path) -> list[dict]:
    paginas = []
    # Ordem da seção = menor `secao_order` declarado entre suas páginas; seção
    # sem declaração vai para o fim (999). Sem isso, a posição de uma seção
    # dependia do título da primeira página de order 1, que era puro acaso.
    ordem_secao: dict[str, int] = {}
    for arquivo in sorted(wiki_dir.rglob("*.md")):
        if arquivo.name.startswith("_"):
            continue
        texto = arquivo.read_text(encoding="utf-8")
        meta, corpo = _frontmatter(texto)
        secao = meta.get("secao", "Geral")
        ordem_secao[secao] = min(ordem_secao.get(secao, 999), _secao_order(meta))
        paginas.append(
            {
                "slug": _slug(arquivo),
                "titulo": _titulo(meta, corpo),
                "secao": secao,
                "order": _order(meta),
                "em_breve": meta.get("em_breve", "").lower() in ("true", "1", "sim"),
            }
        )
    paginas.sort(key=lambda p: (ordem_secao[p["secao"]], p["order"], p["titulo"]))
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
    return listar_wiki(get_settings().wiki_dir)


@router.get("/{slug}")
def wikipagina(slug: str) -> dict:
    pagina = pagina_wiki(slug, get_settings().wiki_dir)
    if pagina is None:
        raise HTTPException(status_code=404, detail="Página do wiki não encontrada.")
    return pagina
