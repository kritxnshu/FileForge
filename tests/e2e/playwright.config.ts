import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const ROOT = path.resolve(__dirname, "../..");
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:8080";

export default defineConfig({
  testDir: ".",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  outputDir: path.join(ROOT, ".data/e2e-results"),
  globalSetup: "./global-setup.ts",
  use: { baseURL: BASE, trace: "retain-on-failure", acceptDownloads: true },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `${ROOT}/scripts/dev.sh`,
        url: `${BASE}/api/health`,
        reuseExistingServer: true,
        timeout: 180_000,
        env: { WEB_MODE: process.env.WEB_MODE ?? "dev", STORAGE_DIR: `${ROOT}/.data/e2e-storage` },
      },
});
