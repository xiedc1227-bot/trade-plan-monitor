import { expect, test } from "./fixtures";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createServer, type ViteDevServer } from "vite";
import vue from "@vitejs/plugin-vue";
import fixture from "../fixtures/monitor-loop-results.json" with { type: "json" };
import { emptyDashboard } from "../fixtures/runtimeStatus";

let server: ViteDevServer, base: string;

test.beforeAll(async () => {
  const cache = join(process.cwd(), ".pytest_cache");
  await mkdir(cache, { recursive: true });
  await writeFile(join(cache, "result-read-concurrency.html"), `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="icon" href="data:,"><title>结果读取验证</title></head><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue'; import {createPinia} from 'pinia'; import {createRouter,createWebHistory} from 'vue-router';
import App from '/src/runtime-status/App.vue'; import Runs from '/src/views/BacktestRunsView.vue'; import Data from '/src/views/BacktestDataView.vue'; import Result from '/src/views/BacktestRunDetailView.vue';
class Socket extends EventTarget { readyState=0; close(){} }
const router=createRouter({history:createWebHistory(),routes:[{path:'/',component:{render:()=>h('h1','监控验证')}},...['plans','alerts','system'].map(name=>({path:'/'+name,component:{render:()=>h('h1','其他页面')}})),{path:'/backtests',component:Runs,meta:{section:'backtests'}},{path:'/backtests/data',component:Data,meta:{section:'backtests'}},{path:'/backtests/new',component:{render:()=>h('h1','新建回测')},meta:{section:'backtests'}},{path:'/backtests/:runId',component:Result,meta:{section:'backtests'}}]});
createApp(App,{createSocket:()=>new Socket()}).use(createPinia()).use(router).mount('#app');
</script></body></html>`);
  server = await createServer({ configFile: false, root: process.cwd(), logLevel: "silent", plugins: [vue(), {
    name: "result-read-runtime-root", configureServer(s) {
      s.middlewares.use((req, _res, next) => {
        if (req.url === "/" || req.url?.startsWith("/backtests")) req.url = "/.pytest_cache/result-read-concurrency.html";
        next();
      });
    },
  }], server: { host: "127.0.0.1", port: 0, hmr: false } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === "string") throw new Error("missing server");
  base = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => { await server?.close(); });

test("runtime root keeps one monitor read through backtest navigation and refreshes on monitor entry", async ({ page }) => {
  let dashboards = 0, results = 0;
  const writes: string[] = [], errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    let body: unknown;
    if (path === "/api/v1/dashboard") { dashboards++; body = emptyDashboard(); }
    else if (path === "/api/v1/backtest-service") body = { epoch: "f".repeat(32), revision: 1, generation: 1, state: "READ_READY", canRead: true, canSubmit: false, canCancel: true, canExport: true, physicallyDrained: true, authorizedJobIds: [], reason: null };
    else if (path === "/api/v1/backtest-runs") body = { ...fixture.runs, items: url.searchParams.get("symbol") ? [] : [fixture.runs.items[0]], filters: { ...fixture.runs.filters, symbol: url.searchParams.get("symbol") }, hasMore: false, nextCursor: null };
    else if (path === `/api/v1/backtest-runs/${fixture.run.runId}`) { results++; body = fixture.run; }
    else if (path === "/api/v1/backtest-jobs") body = { items: [], limit: Number(url.searchParams.get("limit")), highWatermark: "jobs.signature", nextCursor: null, hasMore: false, filters: { createdFrom: null, createdTo: null, datasetHash: null, kind: url.searchParams.has("kind") ? url.searchParams.getAll("kind") : null, runId: null, status: url.searchParams.has("status") ? url.searchParams.getAll("status") : null } };
    else if (path === "/api/v1/backtest-datasets") body = { filters: { symbol: null, startOnOrAfter: null, endOnOrBefore: null, historicalProfile: null, adjustmentPolicy: null }, items: [], limit: 20, highWatermark: "dataset.signature", nextCursor: null, hasMore: false };
    else throw new Error(`unexpected runtime-root request ${path}`);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body), headers: { "Cache-Control": "no-store", "X-Monitor-Contract-Version": "2" } });
  });
  await page.goto(`${base}/backtests`);
  await expect(page.getByTestId("backtest-run-row")).toHaveCount(1);
  await expect.poll(() => dashboards).toBe(1);
  await page.getByTestId("run-detail-link").first().click();
  await expect(page.getByTestId("result-tab-summary")).toBeVisible();
  await page.getByTestId("result-tab-provenance").click();
  await expect(page).toHaveURL(/tab=provenance/);
  await page.getByTestId("result-tab-summary").click();
  await page.goBack(); await expect(page).toHaveURL(/tab=provenance/);
  await page.goForward(); await expect(page.getByTestId("result-tab-summary")).toHaveAttribute("aria-current", "page");
  expect(results).toBe(1);
  await page.getByTestId("return-to-run-list").click();
  await page.locator("#run-filter-symbol").fill("600000.SH");
  await page.locator("#run-filter-symbol").press("Enter");
  await expect(page.getByTestId("backtest-run-row")).toHaveCount(0);
  await page.getByTestId("clear-run-filters").click();
  await expect(page.getByTestId("backtest-run-row")).toHaveCount(1);
  await page.getByRole("link", { name: "历史行情数据", exact: true }).click();
  await expect(page.getByTestId("dataset-empty")).toBeVisible();
  expect(dashboards).toBe(1);
  await page.getByRole("link", { name: "监控总览", exact: true }).click();
  await expect(page.getByRole("heading", { name: "监控验证" })).toBeVisible();
  await expect.poll(() => dashboards).toBe(2);
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});
