import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  expect: { timeout: 5_000 },
  fullyParallel: false,
  outputDir: join(tmpdir(), "trade-plan-monitor-playwright-results"),
  projects: [
    {
      name: "chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
  reporter: "line",
  retries: 0,
  testDir: "./tests/e2e",
  use: {
    locale: "zh-CN",
    screenshot: "off",
    timezoneId: "Asia/Shanghai",
    trace: "off",
    video: "off",
  },
  workers: 1,
});
