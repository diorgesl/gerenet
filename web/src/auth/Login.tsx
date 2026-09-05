import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./auth-context";
import { ApiError } from "@/api/client";

export default function Login() {
  const { usuario, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const destino = location.state?.from as { pathname?: string; search?: string } | undefined;

  if (usuario) return <Navigate to={`${destino?.pathname ?? "/"}${destino?.search ?? ""}`} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await login(username, password);
      navigate(`${destino?.pathname ?? "/"}${destino?.search ?? ""}`, { replace: true });
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Usuário ou senha inválidos.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="login">
      <h1>gerenet</h1>
      {erro && <p role="alert">{erro}</p>}
      <form onSubmit={onSubmit}>
        <label>
          Usuário
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Senha
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <button className="primary" type="submit" disabled={enviando}>
          Entrar
        </button>
      </form>
    </main>
  );
}
