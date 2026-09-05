import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { useUserAtualizar, useUserCriar, useUserSenha, useUsers } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { FormField } from "@/components/FormField";
import { StatusBadge } from "@/components/StatusBadge";
import { PageHeader } from "@/components/PageHeader";
import type { UserOut } from "@/api/types";

const ROLES = ["visualizador", "operador", "aprovador", "executor", "administrador"] as const;

export default function Users() {
  const { usuario } = useAuth();
  const { data, isLoading } = useUsers();
  const criar = useUserCriar();
  const atualizar = useUserAtualizar();
  const senha = useUserSenha();
  const [username, setUsername] = useState("");
  const [senhaNova, setSenhaNova] = useState("");
  const [role, setRole] = useState<string>("operador");
  const [erro, setErro] = useState<string | null>(null);
  const [resetando, setResetando] = useState<UserOut | null>(null); // alvo do diálogo de redefinição
  const [senhaReset, setSenhaReset] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    try {
      await criar.mutateAsync({ username, password: senhaNova, role });
      setUsername(""); setSenhaNova("");
    } catch (err) {
      setErro(err instanceof ApiError ? err.message : "Falha ao criar usuário.");
    }
  }

  function alternarAtivo(u: UserOut) {
    if (u.id === usuario?.id) return;
    void atualizar.mutate({ id: u.id, is_active: !u.is_active });
  }

  return (
    <main>
      <PageHeader titulo="Usuários" />
      <form onSubmit={onSubmit} className="form-inline">
        <FormField label="Usuário">
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </FormField>
        <FormField label="Senha">
          <input type="password" value={senhaNova} onChange={(e) => setSenhaNova(e.target.value)} required />
        </FormField>
        <FormField label="Perfil">
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </FormField>
        <button className="primary" type="submit" disabled={criar.isPending}>
          Criar
        </button>
      </form>
      {erro && <p role="alert">{erro}</p>}
      <DataTable<UserOut>
        colunas={[
          { key: "username", title: "Usuário" },
          { key: "role", title: "Perfil" },
          { key: "is_active", title: "Situação", render: (u) => <StatusBadge estado={u.is_active ? "ativo" : "inativo"} /> },
          { key: "last_login_at", title: "Último login" },
        ]}
        linhas={data ?? []}
        carregando={isLoading}
        acoes={(u) => (
          <>
            <button
              type="button"
              onClick={() => {
                setResetando(u);
                setSenhaReset("");
              }}
            >
              Resetar senha
            </button>
            {u.id !== usuario?.id && (
              <button type="button" onClick={() => alternarAtivo(u)}>
                Desativar
              </button>
            )}
          </>
        )}
      />
      {atualizar.error && <p role="alert">{String(atualizar.error?.message ?? "Falha ao atualizar.")}</p>}
      {resetando && (
        <div role="dialog" aria-modal="true" aria-label={`Redefinir senha de ${resetando.username}`}>
          <h2>Redefinir senha de {resetando.username}</h2>
          <FormField label="Nova senha">
            <input
              type="password"
              value={senhaReset}
              onChange={(e) => setSenhaReset(e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
          {senha.error && <p role="alert">{String(senha.error.message ?? "Falha ao redefinir.")}</p>}
          <button
            className="danger"
            disabled={senha.isPending || senhaReset.length === 0}
            onClick={() =>
              void senha.mutateAsync({ id: resetando.id, password: senhaReset }).then(() => setResetando(null))
            }
          >
            Redefinir
          </button>
          <button onClick={() => setResetando(null)}>Cancelar</button>
        </div>
      )}
    </main>
  );
}
