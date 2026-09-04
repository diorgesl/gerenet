import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { apiFetch } from "@/api/client";
import type { UserOut } from "@/api/types";

interface AuthState {
  usuario: UserOut | null;
  carregando: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  podeEscrever: boolean;
  ehAdmin: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<UserOut | null>(null);
  const [carregando, setCarregando] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUsuario(await apiFetch<UserOut>("/api/v1/auth/me"));
    } catch {
      setUsuario(null);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const u = await apiFetch<UserOut>("/api/v1/auth/login", {
      method: "POST",
      body: { username, password },
    });
    setUsuario(u);
  }, []);

  const logout = useCallback(async () => {
    await apiFetch<void>("/api/v1/auth/logout", { method: "POST" });
    setUsuario(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      usuario,
      carregando,
      login,
      logout,
      refresh,
      podeEscrever: usuario !== null && usuario.role !== "visualizador",
      ehAdmin: usuario?.role === "administrador",
    }),
    [usuario, carregando, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth fora do AuthProvider");
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { usuario, carregando } = useAuth();
  const location = useLocation();
  if (carregando) return <p aria-live="polite">Carregando…</p>;
  if (!usuario) return <Navigate to="/login" state={{ from: location }} replace />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { ehAdmin } = useAuth();
  if (!ehAdmin) return <p>Somente administradores.</p>;
  return <>{children}</>;
}
