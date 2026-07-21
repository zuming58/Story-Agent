import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

// Every invocation gets an isolated catalog/project root. A timed-out Windows
// migration must never poison the next Playwright run.
const e2eRunId = process.env.STORY_AGENT_E2E_RUN_ID ?? `${Date.now()}-${process.pid}`;
const e2eDataDir = resolve(process.cwd(), ".e2e-data", e2eRunId);
const apiPython = process.platform === "win32" ? "..\\api\\.venv\\Scripts\\python.exe" : "../api/.venv/bin/python";
const apiPort = process.env.STORY_AGENT_E2E_API_PORT ?? "8765";
const webPort = process.env.STORY_AGENT_E2E_WEB_PORT ?? "4174";

export default defineConfig({
  testDir: "./e2e",
  // Project creation performs an isolated Alembic migration. On Windows a
  // cold filesystem or antivirus scan can push a full UI flow past the
  // Playwright default of 30 seconds even though the application is healthy.
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `"${apiPython}" -m uvicorn story_agent_api.main:app --host 127.0.0.1 --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/api/v1/health`,
      env: { STORY_AGENT_DATA_DIR: e2eDataDir },
      reuseExistingServer: false,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: false,
    },
  ],
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1024 } } },
    { name: "desktop-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
  ],
});
