import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { baseURL: "http://localhost:8000", trace: "retain-on-failure" },
  // A stack (postgres + redis + uvicorn + web/dist) sobe manualmente — ver
  // e2e/README.md (Task 12). O webServer só sobe o uvicorn se nada já estiver
  // na porta; o run-book manda rodar `npm run build` antes do `test:e2e`.
  webServer: {
    command: "uv run uvicorn gerenet.api.main:create_app --factory --port 8000",
    url: "http://localhost:8000/api/v1/dashboard",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
