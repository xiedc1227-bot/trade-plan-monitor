import { defineConfig } from "../../../web/node_modules/@playwright/test";
import base from "../../../web/playwright.config";

export default defineConfig({
  ...base,
  testDir: "../../../web/tests/e2e",
  outputDir: "./recheck-browser",
  use: { ...base.use, screenshot: "on" },
});
