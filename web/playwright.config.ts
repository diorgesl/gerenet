import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  // channel "chrome": usa o Google Chrome do sistema (o CDN do Playwright
  // está inacessível nesta máquina — ver e2e/README.md, seção "Erros comuns").
  use: { baseURL: "http://localhost:8000", trace: "retain-on-failure", channel: "chrome" },
  // Seed idempotente (usuário admin + site/device/org/circuito/autorização)
  // antes dos specs — run-book em e2e/README.md (Task 12).
  globalSetup: "./e2e/setup.ts",
  // O webServer sobe o build da SPA + o uvicorn se a porta estiver livre
  // (reuseExistingServer) — ver e2e/README.md (Task 12).
  webServer: {
    command:
      'bash -c "npm run build && cd .. && uv run uvicorn gerenet.api.main:create_app --factory --port 8000"',
    url: "http://localhost:8000/api/v1/dashboard",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
