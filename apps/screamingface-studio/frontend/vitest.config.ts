import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text"],
      // WHY this narrow scope: the rest of the Studio frontend is still the mock (OME-1308 un-mocks
      // it feature by feature). Each un-mocked feature joins the threshold as it lands.
      include: [
        "src/lib/engine/**",
        "src/lib/runtime.ts",
        "src/lib/tauri.ts",
        "src/lib/provider-presentation.ts",
        "src/lib/model-store.ts",
        "src/lib/benchmark-*.ts",
        "src/lib/recipe.ts",
        "src/app/*/models/**",
      ],
      exclude: ["**/*.test.{ts,tsx}"],
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
    },
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
