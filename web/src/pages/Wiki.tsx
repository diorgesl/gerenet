import type { MouseEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useWikiIndice, useWikiPagina } from "@/api/hooks";
import type { WikiIndiceItem } from "@/api/types";

export default function Wiki() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const indice = useWikiIndice();
  const pagina = useWikiPagina(slug ?? "index");

  // Links internos do HTML sanitizado (ex.: /wiki/outra-pagina) devem navegar
  // na SPA, sem reload — o servidor é a fonte das páginas, não o GitHub.
  const aoClicar = (e: MouseEvent<HTMLDivElement>) => {
    // cmd/ctrl+click (abrir em nova aba) e botões diferentes de esquerdo não são interceptados
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    const alvo = (e.target as HTMLElement).closest("a[href^='/wiki/']");
    if (alvo) {
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
        <h2>Documentação</h2>
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
          <p role="alert">
            Página não encontrada. <Link to="/wiki">Voltar ao índice</Link>.
          </p>
        )}
        {pagina.data && (
          <>
            {pagina.data.em_breve && <p className="wiki-badge">Recurso planejado — não disponível ainda.</p>}
            {/* O html vem sanitizado do servidor (backend) — nunca renderizar markdown cru no client */}
            <div dangerouslySetInnerHTML={{ __html: pagina.data.html }} />
          </>
        )}
      </article>
    </section>
  );
}
