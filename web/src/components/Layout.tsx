import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";

const ITENS_NAV: { para: string; rotulo: string; admin?: boolean }[] = [
  { para: "/", rotulo: "Dashboard" },
  { para: "/devices", rotulo: "Equipamentos" },
  { para: "/sites", rotulo: "Sites" },
  { para: "/organizations", rotulo: "Organizações" },
  { para: "/contacts", rotulo: "Contatos" },
  { para: "/circuits", rotulo: "Circuitos" },
  { para: "/bgp-sessions", rotulo: "Sessões BGP" },
  { para: "/prefix-authorizations", rotulo: "Prefixos autorizados" },
  { para: "/policy-profiles", rotulo: "Perfis de política" },
  { para: "/communities", rotulo: "Communities" },
  { para: "/snapshots", rotulo: "Snapshots" },
  { para: "/desired-config", rotulo: "Config desejada" },
  { para: "/reconcile", rotulo: "Reconciliação" },
  { para: "/jobs", rotulo: "Jobs" },
  { para: "/audit-events", rotulo: "Auditoria" },
  { para: "/users", rotulo: "Usuários", admin: true },
];

export function Layout() {
  const { usuario, ehAdmin, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="app-titulo">
          Gerenet
        </Link>
        <span className="app-usuario">{usuario?.username}</span>
        <button type="button" onClick={() => void logout().then(() => navigate("/login"))}>
          Sair
        </button>
      </header>
      <div className="app-corpo">
        <nav className="app-nav" aria-label="Navegação principal">
          {ITENS_NAV.filter((i) => !i.admin || ehAdmin).map((i) => (
            <NavLink key={i.para} to={i.para} end={i.para === "/"}>
              {i.rotulo}
            </NavLink>
          ))}
        </nav>
        <div className="app-conteudo">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
