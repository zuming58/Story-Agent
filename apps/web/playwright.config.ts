import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const e2eDataDir = resolve(process.cwd(), ".e2e-data");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv run --project ../api uvicorn story_agent_api.main:app --host 127.0.0.1 --port 8765",
      url: "http://127.0.0.1:8765/api/v1/health",
      env: { STORY_AGENT_DATA_DIR: e2eDataDir },
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4174 --strictPort",
      url: "http://127.0.0.1:4174",
      reuseExistingServer: false,
    },
  ],
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1024 } } },
    { name: "desktop-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
  ],
});
