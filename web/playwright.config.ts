import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  // Default: Chromium do Playwright (`playwright install chromium`).
  // GERENET_E2E_CHANNEL=chrome executa o Google Chrome do sistema — para
  // máquinas sem download do Chromium (CDN do Playwright inacessível);
  // ver e2e/README.md, seção "Erros comuns".
  use: {
    baseURL: "http://localhost:8000",
    trace: "retain-on-failure",
    ...(process.env.GERENET_E2E_CHANNEL === "chrome" ? { channel: "chrome" } : {}),
  },
  // Seed idempotente (usuário admin + site/device/org/circuito/autorização)
  // antes dos specs — run-book em e2e/README.md (Task 12).
  globalSetup: "./e2e/setup.ts",
  // O webServer sobe o build da SPA + o uvicorn; porta 8000 ocupada é falha
  // dura no boot (reuseExistingServer: false) — ver e2e/README.md.
  webServer: {
    command:
      'bash -c "npm run build && cd .. && uv run uvicorn gerenet.api.main:create_app --factory --port 8000"',
    url: "http://localhost:8000/api/v1/dashboard",
    // Falha dura: se a porta 8000 já estiver ocupada, o smoke morre no boot —
    // nunca reusa o uvicorn de dev (que apontaria para o banco default).
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
