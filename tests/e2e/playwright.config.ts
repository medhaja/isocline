import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./specs",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: process.env.E2E_BASE_URL || "http://localhost:3000", viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
  webServer: process.env.E2E_BASE_URL ? undefined : {
    command: "bash ../../scripts/dev-stack.sh", url: "http://localhost:3000/login", timeout: 240_000, reuseExistingServer: true,
  },
});
