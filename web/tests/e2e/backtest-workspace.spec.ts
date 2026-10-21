import { expect, test } from "./fixtures";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createServer, type ViteDevServer } from "vite";
import vue from "@vitejs/plugin-vue";
import axe from "axe-core";
import type { Page } from "@playwright/test";
import fixture from "../fixtures/monitor-loop-results.json" with { type: "json" };
import scheduled from "../fixtures/four-plan-diagnostics.json" with { type: "json" };

let server: ViteDevServer, base: string;
const time = "2026-08-30T10:00:00.000000+08:00";
const rows = [fixture.runs.items[0]!, ...Array.from({ length: 29 }, (_, i) => ({ ...fixture.runs.items[0]!, runId: (29 - i).toString(16).padStart(64, "0") }))];
const coverage = { blockers: [], calendarRowCount: 20, dailyBarRowCount: 20, dailyLimitRowCount: 20, minuteBarCount: 4800, minuteDayCount: 20, symbolCount: 1, tradingDayCount: 20 };
const datasets = Array.from({ length: 30 }, (_, i) => ({ datasetHash: (30 - i).toString(16).padStart(64, "0"), schemaVersion: "backtest-dataset-v1", createdAt: time, verifiedAt: time, scope: { symbols: ["002240.SZ"], start: "2026-08-01", end: "2026-08-28", warmupStart: "2026-07-01", adjustmentPolicy: "NONE", historicalProfile: "TUSHARE_STK_MINS_241_END_V1" }, coverage }));
const job = { jobId: "accepted-failed-data", status: "FAILED", kind: "DATA_SYNC", attempt: 1, cancelRequestedAt: null, createdAt: time, updatedAt: time, startedAt: time, finishedAt: time, datasetHash: null, runId: null, errorCode: "DATA_PERMISSION_DENIED", errorMessage: "The job failed.", requestHash: "a".repeat(64), result: null, reused: false, revision: 1, progress: { phase: "TERMINAL", completedUnits: 1, totalUnits: null, unit: "SYMBOL_DAYS", updatedAt: time } };

test.beforeAll(async () => {
  const cache = join(process.cwd(), ".pytest_cache"); await mkdir(cache, { recursive: true });
  await writeFile(join(cache, "backtest-workspace.html"), `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>回测工作区</title></head><body><div id="app"></div><script type="module">
import {createApp,computed} from 'vue'; import {createRouter,createWebHistory} from 'vue-router';
import Shell from '/src/layouts/AppShell.vue'; import Runs from '/src/views/BacktestRunsView.vue'; import Data from '/src/views/BacktestDataView.vue'; import Result from '/src/views/BacktestRunDetailView.vue'; import {shellConnectionKey} from '/src/layouts/connection'; import '/src/assets/tokens.css';
const router=createRouter({history:createWebHistory(),routes:[{path:'/',component:{template:'<h1>监控</h1>'}},{path:'/plans',component:{template:'<h1>计划</h1>'}},{path:'/alerts',component:{template:'<h1>提醒</h1>'}},{path:'/system',component:{template:'<h1>系统</h1>'}},{path:'/backtests',component:Runs,meta:{section:'backtests'}},{path:'/backtests/data',component:Data,meta:{section:'backtests'}},{path:'/backtests/new',component:{template:'<h1>创建回测</h1>'},meta:{section:'backtests'}},{path:'/backtests/:runId',component:Result,meta:{section:'backtests'}}]});
const app=createApp(Shell);app.use(router);app.provide(shellConnectionKey,computed(()=>({code:'LIVE',label:'连接正常',marker:'●'})));app.mount('#app');
</script></body></html>`);
  server = await createServer({ configFile: false, root: process.cwd(), logLevel: "silent", plugins: [vue(), { name: "workspace-harness", configureServer(s) { s.middlewares.use((req, _res, next) => { if (req.url?.startsWith("/backtests")) req.url = "/.pytest_cache/backtest-workspace.html"; next(); }); } }], server: { host: "127.0.0.1", port: 0, hmr: false } });
  await server.listen(); const address = server.httpServer!.address(); if (!address || typeof address === "string") throw new Error("missing server"); base = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => { await server?.close(); });

async function install(page: Page, options: { emptyDatasets?: boolean; slow?: boolean; hangOnce?: boolean; equity?: boolean } = {}) {
  const writes: string[] = [];
  let resultReads = 0;
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    const scalar = (name: string) => url.searchParams.get(name);
    let body: unknown;
    if (path === "/api/v1/backtest-service") body = { epoch: "f".repeat(32), revision: 1, generation: 1, state: "READ_READY", canRead: true, canSubmit: false, canCancel: true, canExport: true, physicallyDrained: true, authorizedJobIds: [], reason: null };
    else if (path === "/api/v1/backtest-runs") {
      const offset = scalar("cursor") ? 20 : 0;
      const filtered = scalar("symbol") && scalar("symbol") !== fixture.run.symbol ? [] : rows;
      body = { ...fixture.runs, filters: { ...fixture.runs.filters, symbol: scalar("symbol"), pinned: scalar("pinned") === null ? null : scalar("pinned") === "true", ...(scalar("eventEndFrom") ? { eventEndFrom: scalar("eventEndFrom") } : {}), ...(scalar("eventEndTo") ? { eventEndTo: scalar("eventEndTo") } : {}) }, items: filtered.slice(offset, offset + 20), limit: 20, hasMore: filtered.length > offset + 20, nextCursor: filtered.length > offset + 20 ? "nextpage.signature" : null };
    } else if (path === "/api/v1/backtest-datasets") {
      const offset = scalar("cursor") ? 20 : 0;
      const filtered = options.emptyDatasets || scalar("symbol") && scalar("symbol") !== "002240.SZ" ? [] : datasets;
      body = { filters: { symbol: scalar("symbol"), startOnOrAfter: scalar("startOnOrAfter"), endOnOrBefore: scalar("endOnOrBefore"), historicalProfile: null, adjustmentPolicy: null }, items: filtered.slice(offset, offset + 20), limit: 20, highWatermark: "dataset.signature", nextCursor: filtered.length > offset + 20 ? "nextpage.signature" : null, hasMore: filtered.length > offset + 20 };
    } else if (path === "/api/v1/backtest-jobs") {
      const selected = scalar("limit") === "20" && (!scalar("status") || scalar("status") === job.status) ? [job] : [];
      body = { items: selected, limit: Number(scalar("limit")), highWatermark: "jobs.signature", nextCursor: null, hasMore: false, filters: { createdFrom: null, createdTo: null, datasetHash: null, kind: url.searchParams.has("kind") ? url.searchParams.getAll("kind") : null, runId: null, status: url.searchParams.has("status") ? url.searchParams.getAll("status") : null } };
    } else if (path === `/api/v1/backtest-jobs/${job.jobId}`) body = job;
    else if (path.endsWith("/equity-series")) body = { availability: "AVAILABLE", items: [1, 2, 3].map(index => ({ schemaVersion: "unified-research-equity-v1", runId: fixture.run.runId, snapshotId: String(index).repeat(64), markedAt: `2026-08-${20 + index}T15:00:00.000000+08:00`, cashFen: "500000", equityFen: String(500000 + 100 * index), marketValueFen: String(100 * index), markPriceFen: "1000", positionQuantity: 100, valuationValid: true, blockers: [] })) };
    else if (path === `/api/v1/backtest-runs/${scheduled.runId}`) body = scheduled;
    else if (path === `/api/v1/backtest-runs/${fixture.run.runId}`) {
      if (options.hangOnce && resultReads++ === 0) return;
      if (options.slow) await new Promise(resolve => setTimeout(resolve, 11000));
      body = options.equity ? { ...fixture.run, availability: { ...fixture.run.availability, equitySeries: "AVAILABLE" } } : fixture.run;
    } else throw new Error(`unexpected workspace request ${request.method()} ${url.pathname}`);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body), headers: { "Cache-Control": "no-store" } });
  });
  return writes;
}

async function accessible(page: Page) {
  await page.evaluate(axe.source);
  const violations = await page.evaluate(async () => (await (window as any).axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21aa"] })).violations.map((v: any) => ({ id: v.id, impact: v.impact })));
  expect(violations).toEqual([]);
}

test("30 run records paginate, clear filters and return to the selected result with focus", async ({ page }) => {
  const writes = await install(page); await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/backtests`); await expect(page.getByTestId("backtest-run-row")).toHaveCount(20);
  const first = page.getByTestId("backtest-run-row").first(); const box = await first.boundingBox(); expect(box!.y).toBeLessThan(900);
  await page.getByTestId("next-run-page").click(); await expect(page.getByTestId("backtest-run-row")).toHaveCount(10);
  await page.getByTestId("previous-run-page").click(); await expect(page.getByTestId("backtest-run-row")).toHaveCount(20);
  await page.locator("#run-filter-symbol").fill("600000.SH"); await page.locator("#run-filter-symbol").press("Enter"); await expect(page.getByTestId("run-list-state")).toContainText("没有符合");
  await page.getByTestId("clear-run-filters").click(); await expect(page.getByTestId("backtest-run-row")).toHaveCount(20);
  const result = page.getByTestId("run-detail-link").first(); await result.click(); await expect(page.getByTestId("result-tab-summary")).toBeVisible();
  await page.getByTestId("return-to-run-list").click(); await expect(page.getByTestId("backtest-run-row")).toHaveCount(20); await expect(page.getByTestId("run-detail-link").first()).toBeFocused();
  await accessible(page); expect(writes).toEqual([]);
});

test("catalog has labelled dates, 30-record paging, evidence disclosure and truthful empty state", async ({ page }) => {
  const writes = await install(page); await page.goto(`${base}/backtests/data`);
  await expect(page.getByTestId("dataset-card")).toHaveCount(20);
  await expect(page.locator('input[type="date"]')).toHaveCount(2);
  const first = page.getByTestId("dataset-card").first(); await expect(first.locator("details")).not.toHaveAttribute("open");
  await first.locator("summary").focus(); await first.locator("summary").press("Enter"); await expect(first.locator("details")).toHaveAttribute("open", "");
  await page.getByTestId("next-dataset-page").click(); await expect(page.getByTestId("dataset-card")).toHaveCount(10);
  await page.getByRole("button", { name: "上一页", exact: true }).click(); await expect(page.getByTestId("dataset-card")).toHaveCount(20);
  await accessible(page); expect(writes).toEqual([]);
});

test("empty catalog does not imply lost history; accepted failed task opens without execution", async ({ page }) => {
  const writes = await install(page, { emptyDatasets: true }); await page.goto(`${base}/backtests/data`);
  await expect(page.getByTestId("dataset-empty")).toContainText("不代表之前的回测或计划记录被删除");
  await page.goto(`${base}/backtests?view=tasks`); await expect(page.getByTestId("task-row")).toHaveCount(1);
  await page.getByRole("button", { name: "查看任务", exact: true }).click(); await expect(page.getByTestId("backtest-job-status")).toHaveAttribute("data-status", "FAILED");
  await expect(page.getByTestId("job-diagnostic")).toContainText("数据源权限不足");
  await expect(page.getByRole("link", { name: "查看结果", exact: true })).toHaveCount(0);
  await page.getByTestId("task-status-filter").selectOption("CANCELLED"); await expect(page.getByTestId("task-row")).toHaveCount(0);
  await accessible(page); expect(writes).toEqual([]);
});

test("version selection and responsive workspaces keep evidence available", async ({ page }) => {
  const writes = await install(page); await page.goto(`${base}/backtests/${scheduled.runId}?tab=provenance`);
  const choices = page.getByRole("group", { name: "选择生效版本" }); await expect(choices.getByRole("button")).toHaveCount(4);
  await choices.getByRole("button").nth(2).click(); await expect(choices.getByRole("button").nth(2)).toHaveAttribute("aria-pressed", "true");
  await accessible(page);
  for (const route of ["/backtests", "/backtests/data", "/backtests?view=tasks", `/backtests/${scheduled.runId}?tab=provenance`]) {
    await page.goto(base + route);
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 }); await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }
  expect(writes).toEqual([]);
});

test("a slow result read explains waiting and offers a return path", async ({ page }) => {
  const writes = await install(page, { slow: true }); await page.goto(`${base}/backtests/${fixture.run.runId}`);
  await expect(page.getByText("读取所需时间较长", { exact: false })).toBeVisible({ timeout: 13000 });
  await expect(page.getByTestId("result-tab-summary")).toBeVisible({ timeout: 5000 }); expect(writes).toEqual([]);
});


test("timed-out result reading can be retried without submitting another task", async ({ page }) => {
  const writes = await install(page, { hangOnce: true }); await page.clock.install();
  await page.goto(`${base}/backtests/${fixture.run.runId}`);
  await expect(page.getByText("正在读取已物化回测结果…", { exact: true })).toBeVisible();
  await page.clock.fastForward(31000);
  await expect(page.getByText("本次读取超时。可重新读取，回测任务状态不受影响。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByTestId("result-tab-summary")).toBeVisible(); expect(writes).toEqual([]);
});


test("equity layer and range controls preserve the expandable exact table", async ({ page }) => {
  const writes = await install(page, { equity: true }); await page.goto(`${base}/backtests/${fixture.run.runId}?tab=equity`);
  await expect(page.getByTestId("backtest-equity-chart").locator("canvas")).toHaveCount(1);
  await page.getByRole("checkbox", { name: "现金", exact: true }).focus(); await page.keyboard.press("Space");
  await expect(page.getByRole("checkbox", { name: "现金", exact: true })).not.toBeChecked();
  await page.getByRole("combobox", { name: "展示范围" }).selectOption("25");
  const disclosure = page.locator("details").filter({ has: page.getByText("查看完整精确数值表", { exact: true }) });
  await expect(disclosure).not.toHaveAttribute("open"); await disclosure.locator("summary").focus(); await page.keyboard.press("Enter");
  await expect(disclosure).toHaveAttribute("open", ""); await expect(disclosure.locator("tbody tr")).toHaveCount(3);
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await accessible(page); expect(writes).toEqual([]);
});
