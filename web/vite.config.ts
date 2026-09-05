/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    proxy: { "/api": process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    passWithNoTests: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
  },
});
