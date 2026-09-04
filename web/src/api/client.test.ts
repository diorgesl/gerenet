import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ApiError, setOnUnauthorized } from "./client";

function responder(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("envia cookie e JSON no corpo", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(responder(200, { id: 1 }));
    await apiFetch("/api/v1/auth/me");
    const [url, init] = vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/me");
    expect(init.credentials).toBe("include");
    expect(init.body).toBeUndefined();
  });

  it("402/409 → ApiError com a mensagem do detail", async () => {
    vi.mocked(fetch).mockImplementation(async () => responder(409, { detail: "Registro duplicado." }));
    await expect(apiFetch("/api/v1/sites", { method: "POST", body: {} })).rejects.toThrow(ApiError);
    await expect(apiFetch("/api/v1/sites", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 409,
      message: "Registro duplicado.",
    });
  });

  it("401 fora do login chama onUnauthorized", async () => {
    const spy = vi.fn();
    setOnUnauthorized(spy);
    vi.mocked(fetch).mockResolvedValueOnce(responder(401, { detail: "Chave de API ausente ou inválida." }));
    await expect(apiFetch("/api/v1/devices")).rejects.toThrow(ApiError);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("401 no login não redireciona (erro exibido na tela)", async () => {
    const spy = vi.fn();
    setOnUnauthorized(spy);
    vi.mocked(fetch).mockResolvedValueOnce(responder(401, { detail: "Usuário ou senha inválidos." }));
    await expect(apiFetch("/api/v1/auth/login", { method: "POST", body: {} })).rejects.toThrow(ApiError);
    expect(spy).not.toHaveBeenCalled();
  });

  it("422 vira erros por campo", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      responder(422, { detail: [{ loc: ["body", "password"], msg: "String should have at least 1 character" }] }),
    );
    await expect(apiFetch("/api/v1/auth/login", { method: "POST", body: { password: "" } })).rejects.toMatchObject({
      status: 422,
      fieldErrors: { password: "String should have at least 1 character" },
    });
  });

  it("falha de rede → mensagem amigável", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(apiFetch("/api/v1/devices")).rejects.toThrow("Servidor indisponível. Tente novamente.");
  });

  it("204 → undefined", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(apiFetch("/api/v1/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });
});
