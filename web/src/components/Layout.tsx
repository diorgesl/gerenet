import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";

const GRUPOS_NAV: { rotulo: string; itens: { para: string; rotulo: string; admin?: boolean }[] }[] = [
  {
    rotulo: "Visão",
    itens: [{ para: "/", rotulo: "Dashboard" }],
  },
  {
    rotulo: "Ativos",
    itens: [
      { para: "/devices", rotulo: "Equipamentos" },
      { para: "/sites", rotulo: "Sites" },
      { para: "/circuits", rotulo: "Circuitos" },
    ],
  },
  {
    rotulo: "Roteamento",
    itens: [
      { para: "/bgp-sessions", rotulo: "Sessões BGP" },
      { para: "/prefix-authorizations", rotulo: "Prefixos autorizados" },
      { para: "/policy-profiles", rotulo: "Perfis de política" },
      { para: "/communities", rotulo: "Communities" },
    ],
  },
  {
    rotulo: "Organização",
    itens: [
      { para: "/organizations", rotulo: "Organizações" },
      { para: "/contacts", rotulo: "Contatos" },
    ],
  },
  {
    rotulo: "Coleta",
    itens: [
      { para: "/snapshots", rotulo: "Snapshots" },
      { para: "/desired-config", rotulo: "Config desejada" },
      { para: "/reconcile", rotulo: "Reconciliação" },
      { para: "/jobs", rotulo: "Jobs" },
    ],
  },
  {
    rotulo: "Mudanças",
    itens: [{ para: "/change-requests", rotulo: "Change requests" }],
  },
  {
    rotulo: "Governança",
    itens: [
      { para: "/audit-events", rotulo: "Auditoria" },
      { para: "/users", rotulo: "Usuários", admin: true },
    ],
  },
  {
    rotulo: "Ajuda",
    itens: [{ para: "/wiki", rotulo: "Wiki" }],
  },
];

const TODOS = GRUPOS_NAV.flatMap((g) => g.itens);

export function Layout() {
  const { usuario, ehAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const atual = TODOS.find((i) => i.para === "/" ? location.pathname === "/" : location.pathname.startsWith(i.para));

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="app-marca">
          <span className="led" aria-hidden="true" />
          gerenet
        </Link>
        {atual && <span className="app-breadcrumb">/ {atual.rotulo}</span>}
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
          {GRUPOS_NAV.map((grupo) => {
            const itens = grupo.itens.filter((i) => !i.admin || ehAdmin);
            if (itens.length === 0) return null;
            return (
              <div key={grupo.rotulo}>
                <span className="nav-label">{grupo.rotulo}</span>
                {itens.map((i) => (
                  <NavLink key={i.para} to={i.para} end={i.para === "/"}>
                    {i.rotulo}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="app-conteudo">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
