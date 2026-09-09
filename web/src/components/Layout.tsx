import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ICONES_NAV } from "./Icons";

type ItemNav = { para: string; rotulo: string; admin?: boolean };
type GrupoNav = { id: string; rotulo: string; itens: ItemNav[] };

/* Dashboard (topo) e Wiki (rodapé) ficam sempre visíveis, fora das sanfonas. */
const PIN_TOP: ItemNav[] = [{ para: "/", rotulo: "Dashboard" }];
const PIN_BOTTOM: ItemNav[] = [{ para: "/wiki", rotulo: "Wiki" }];

/* Grupos sanfonados: o do item atual abre sozinho; o resto começa fechado */
const GRUPOS_NAV: GrupoNav[] = [
  {
    id: "infra",
    rotulo: "Infraestrutura",
    itens: [
      { para: "/devices", rotulo: "Equipamentos" },
      { para: "/sites", rotulo: "Sites" },
      { para: "/circuits", rotulo: "Circuitos" },
    ],
  },
  {
    id: "roteamento",
    rotulo: "Roteamento",
    itens: [
      { para: "/upstreams", rotulo: "Upstreams" },
      { para: "/bgp-sessions", rotulo: "Sessões BGP" },
      { para: "/prefix-authorizations", rotulo: "Prefixos autorizados" },
      { para: "/policy-profiles", rotulo: "Perfis de política" },
      { para: "/communities", rotulo: "Communities" },
    ],
  },
  {
    id: "mpls",
    rotulo: "MPLS",
    itens: [
      { para: "/mpls/domains", rotulo: "Domínios" },
      { para: "/mpls/l2vc", rotulo: "Serviços L2VC" },
      { para: "/mpls/vsi", rotulo: "VSIs" },
    ],
  },
  {
    id: "operacao",
    rotulo: "Operação",
    itens: [
      { para: "/change-requests", rotulo: "Change requests" },
      { para: "/snapshots", rotulo: "Snapshots" },
      { para: "/desired-config", rotulo: "Config desejada" },
      { para: "/reconcile", rotulo: "Reconciliação" },
      { para: "/jobs", rotulo: "Jobs" },
    ],
  },
  {
    id: "gestao",
    rotulo: "Gestão",
    itens: [
      { para: "/organizations", rotulo: "Organizações" },
      { para: "/contacts", rotulo: "Contatos" },
      { para: "/audit-events", rotulo: "Auditoria" },
      { para: "/users", rotulo: "Usuários", admin: true },
    ],
  },
];

const TODOS_NAV: ItemNav[] = [...PIN_TOP, ...PIN_BOTTOM, ...GRUPOS_NAV.flatMap((g) => g.itens)];
const CHAVE_ABERTOS = "gerenet.nav.abertos";

function ehAtivo(para: string, pathname: string) {
  return para === "/" ? pathname === "/" : pathname.startsWith(para);
}

function ItemNav({ item }: { item: ItemNav }) {
  return (
    <NavLink to={item.para} end={item.para === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
      {ICONES_NAV[item.para]}
      <span>{item.rotulo}</span>
    </NavLink>
  );
}

export function Layout() {
  const { usuario, ehAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const atual = TODOS_NAV.find((i) => ehAtivo(i.para, pathname));
  const grupoAtual = GRUPOS_NAV.find((g) => g.itens.some((i) => i.para === atual?.para));

  const [abertos, setAbertos] = useState<Set<string>>(() => {
    const inicial = new Set<string>();
    try {
      const salvos: unknown = JSON.parse(localStorage.getItem(CHAVE_ABERTOS) ?? "[]");
      if (Array.isArray(salvos)) {
        for (const id of salvos) if (typeof id === "string") inicial.add(id);
      }
    } catch {
      /* sem localStorage a sanfona funciona, apenas não memoriza */
    }
    return inicial;
  });

  /* O grupo do item atual sempre abre (usuário pode fechá-lo; só reabre ao
     navegar para outro item do mesmo grupo ou de outro grupo ativo). */
  const idGrupoAtual = grupoAtual?.id;
  useEffect(() => {
    if (!idGrupoAtual) return;
    setAbertos((prev) => (prev.has(idGrupoAtual) ? prev : new Set(prev).add(idGrupoAtual)));
  }, [idGrupoAtual]);

  useEffect(() => {
    try {
      localStorage.setItem(CHAVE_ABERTOS, JSON.stringify([...abertos]));
    } catch {
      /* armazenamento indisponível — sem efeito visível */
    }
  }, [abertos]);

  const alternar = (id: string) =>
    setAbertos((prev) => {
      const novo = new Set(prev);
      if (novo.has(id)) novo.delete(id);
      else novo.add(id);
      return novo;
    });

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="app-marca">
          <span className="led" aria-hidden="true" />
          gerenet
        </Link>
        {atual && (
          <span className="app-breadcrumb">
            {grupoAtual ? `${grupoAtual.rotulo} / ` : ""}
            {atual.rotulo}
          </span>
        )}
        <span className="app-usuario">{usuario?.username}</span>
        <button
          type="button"
          onClick={() => void logout().then(() => navigate("/login")).catch(() => undefined)}
        >
          Sair
        </button>
      </header>
      <div className="app-corpo">
        <nav className="app-nav" aria-label="Navegação principal">
          <div className="nav-pin">
            {PIN_TOP.map((i) => (
              <ItemNav key={i.para} item={i} />
            ))}
          </div>
          {GRUPOS_NAV.map((grupo) => {
            const itens = grupo.itens.filter((i) => !i.admin || ehAdmin);
            if (itens.length === 0) return null;
            const aberto = abertos.has(grupo.id);
            return (
              <section key={grupo.id} className="nav-grupo">
                <button
                  type="button"
                  className="nav-label"
                  aria-expanded={aberto}
                  aria-controls={`nav-${grupo.id}`}
                  onClick={() => alternar(grupo.id)}
                >
                  <span>{grupo.rotulo}</span>
                  <svg
                    className="nav-caret"
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2.4}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                    focusable="false"
                  >
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
                <div id={`nav-${grupo.id}`} className="nav-itens" hidden={!aberto}>
                  {itens.map((i) => (
                    <ItemNav key={i.para} item={i} />
                  ))}
                </div>
              </section>
            );
          })}
          <div className="nav-pin nav-pin-fim">
            {PIN_BOTTOM.map((i) => (
              <ItemNav key={i.para} item={i} />
            ))}
          </div>
        </nav>
        <div className="app-conteudo">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
