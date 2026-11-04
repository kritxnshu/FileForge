import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "src"), "next/font/google": path.resolve(__dirname, "src/lib/__tests__/next-font-stub.ts") } },
  test: { include: ["src/**/*.test.ts"], environment: "node", reporters: ["default", "json"], outputFile: { json: "../../.data/vitest-results.json" } },
});
