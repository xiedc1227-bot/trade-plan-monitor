import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { createServer, type ViteDevServer } from "vite";
import vue from "@vitejs/plugin-vue";
import { expect, test } from "@playwright/test";

const root = resolve(import.meta.dirname, "../../..");
const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");
let vite: ViteDevServer;
let url: string;
const run = JSON.parse(await readFile(join(root, "web/tests/fixtures/four-plan-diagnostics.json"), "utf8"));

test.beforeAll(async () => {
  await mkdir(join(root, "web/.pytest_cache"), { recursive: true });
  await writeFile(join(root, "web/.pytest_cache/result-diagnostics.html"), `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>回测结果验证</title><body><main id="app"></main><script type="module">
import {createApp} from 'vue';import {createRouter,createWebHistory} from 'vue-router';
import View from '../src/views/BacktestRunDetailView.vue';import '../src/assets/tokens.css';
const router=createRouter({history:createWebHistory(),routes:[{path:'/backtests/:runId',component:View}]});
await router.push(window.location.pathname+window.location.search);await router.isReady();createApp(View).use(router).mount('#app');
</script></body></html>`);
  vite = await createServer({ root: join(root, "web"), configFile: false, plugins: [vue(), {
    name: "result-diagnostics-fixture", configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.url === `/api/v1/backtest-runs/${run.runId}`) {
          response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(run)); return;
        }
        if (request.url?.startsWith("/backtests/")) request.url = "/.pytest_cache/result-diagnostics.html";
        next();
      });
    },
  }], server: { host: "127.0.0.1", port: 0 } });
  await vite.listen(); url = vite.resolvedUrls!.local[0]!.replace(/\/$/, "");
});
test.afterAll(async () => { await vite?.close(); });

test("actual four-source result shows automatic diagnosis at desktop and mobile widths", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`${url}/backtests/${run.runId}?tab=summary`);
  const panel = page.getByTestId("plan-execution-diagnostics");
  await expect(panel).toBeVisible();
  await expect(panel.locator('[data-testid^="plan-diagnostic-"]')).toHaveCount(4);
  await expect(page.getByTestId("plan-diagnostic-1")).toContainText("25.69 元");
  await expect(page.getByTestId("plan-diagnostic-1")).toContainText("高于 26.70 元");
  await expect(page.getByTestId("plan-diagnostic-2")).toContainText("未授权直接买入");
  await expect(page.getByTestId("plan-diagnostic-3")).toContainText("25.14 元");
  await expect(page.getByTestId("plan-diagnostic-4")).toContainText("25.35 元");
  await expect(panel.locator("input,textarea,select")).toHaveCount(0);
  for (const width of [1440, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await panel.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`plan-diagnostics-${width}.png`), fullPage: true });
    await page.getByTestId("plan-diagnostic-1").screenshot({ path: testInfo.outputPath(`first-plan-${width}.png`) });
  }
  await page.addScriptTag({ path: axePath });
  const violations = await page.evaluate(async () => {
    const axe = (globalThis as typeof globalThis & {
      axe: { run: (root: Element, options: object) => Promise<{ violations: unknown[] }> };
    }).axe;
    return (await axe.run(document.querySelector('[data-testid="plan-execution-diagnostics"]')!, {
      runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    })).violations;
  });
  expect(violations).toEqual([]);
  await page.getByTestId("plan-diagnostic-4").getByText("查看核对标识", { exact: true }).click();
  await expect(page.getByTestId("plan-diagnostic-4")).toContainText("审计序号");
  expect(errors).toEqual([]);
});
