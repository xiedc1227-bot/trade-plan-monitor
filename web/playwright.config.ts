import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";
import browserPin from "./test-browser.json" with { type: "json" };

const platform = `${process.platform}-${process.arch}`;
const browserPackage = browserPin.platforms[platform as keyof typeof browserPin.platforms];
if (!browserPackage) throw new Error(`No pinned Chrome for Testing package for ${platform}`);
const executablePath = fileURLToPath(new URL(
  `./.test-browsers/${browserPin.version}/${browserPackage.executable}`, import.meta.url,
));
// Keep strict request audits on a browser containing Chromium fix 568852319.
const readyPath = fileURLToPath(new URL(
  `./.test-browsers/${browserPin.version}/${browserPackage.archive}.ready`, import.meta.url,
));
if (!existsSync(executablePath) || !existsSync(readyPath)) {
  throw new Error("Pinned test Chrome is missing. Run npm run setup:test-browser in web/.");
}

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
    launchOptions: { executablePath },
    locale: "zh-CN",
    screenshot: "off",
    timezoneId: "Asia/Shanghai",
    trace: "off",
    video: "off",
  },
  workers: 1,
});
