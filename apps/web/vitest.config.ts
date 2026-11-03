import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: { include: ["src/**/*.test.ts"], environment: "node", reporters: ["default", "json"], outputFile: { json: "../../.data/vitest-results.json" } },
});
