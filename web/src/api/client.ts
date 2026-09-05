// Camada única de acesso à API: cookie de sessão, erros tipados PT-BR e
// redirecionamento para /login em 401 (§6.2 da spec).
export class ApiError extends Error {
  readonly status: number;
  /** mensagem única, ex.: "Usuário ou senha inválidos." */
  readonly message: string;
  /** erros por campo do 422: {campo: mensagem} */
  readonly fieldErrors: Record<string, string>;
  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.message = message;
    this.fieldErrors = fieldErrors;
  }
}

let onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(fn: () => void) {
  onUnauthorized = fn;
}

function mensagemDeDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // [{loc: ["body","password"], msg: "..."}] → concat das mensagens de campo
    const msgs = detail
      .map((e) => (typeof e === "object" && e !== null && "msg" in e ? String(e.msg) : ""))
      .filter((m) => m !== "");
    if (msgs.length > 0) return msgs.join("; ");
  }
  return null;
}

function fieldErrorsDoDetail(detail: unknown): Record<string, string> {
  if (!Array.isArray(detail)) return {};
  const out: Record<string, string> = {};
  for (const e of detail) {
    const loc = e?.loc as (string | number)[] | undefined;
    const campo = loc?.slice(1).join(".") ?? "geral";
    out[campo] = e?.msg ?? "Inválido.";
  }
  return out;
}

export async function apiFetch<T>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const { method = "GET", body } = opts;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Servidor indisponível. Tente novamente.");
  }

  if (res.status === 401 && !path.startsWith("/api/v1/auth/login") && !path.startsWith("/api/v1/auth/me")) {
    onUnauthorized?.();
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      const data = await res.json();
      detail = data?.detail ?? null;
    } catch {
      /* sem corpo — usa status */
    }
    const fieldErrors = fieldErrorsDoDetail(detail);
    const message = fieldErrors["geral"] ?? mensagemDeDetail(detail) ?? mensagemPorStatus(res.status);
    throw new ApiError(res.status, message, fieldErrors);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function mensagemPorStatus(status: number): string {
  if (status === 401) return "Chave de API ausente ou inválida.";
  if (status === 403) return "Permissão negada.";
  if (status === 404) return "Não encontrado.";
  if (status === 409) return "Conflito com registro existente.";
  return `Erro do servidor (${status}).`;
}
