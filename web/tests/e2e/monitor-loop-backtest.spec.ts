import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { createServer as createSocketServer } from "node:net";
import { createServer, type ViteDevServer } from "vite";
import vue from "@vitejs/plugin-vue";
import { expect, test, type Page } from "@playwright/test";
import fixture from "../fixtures/monitor-loop.json" with { type: "json" };

const root = resolve(import.meta.dirname, "../../..");
let backend: ChildProcess;
let vite: ViteDevServer;
let url: string;
let temporary: string;
let output: string;

async function freePort(): Promise<number> {
  const server = createSocketServer();
  await new Promise<void>(done => server.listen(19000 + Math.floor(Math.random() * 10000), "127.0.0.1", done));
  const address = server.address();
  if (address === null || typeof address === "string") throw new Error("missing port");
  const port = address.port; await new Promise<void>(done => server.close(() => done())); return port;
}

async function start(mode = "retry", fail = false) {
  const webPort = await freePort(), apiPort = await freePort();
  temporary = await mkdtemp(join(tmpdir(), "monitor-loop-browser-"));
  output = "";
  backend = spawn(join(root, ".venv/Scripts/python.exe"), ["-X", "utf8", "-m", "tests.integration.test_monitor_loop_production_composition",
    "--root", temporary, "--port", String(apiPort), "--web-port", String(webPort), "--mode", mode, ...(fail ? ["--fail-first"] : [])],
    { cwd: root, env: { ...process.env, PYTHONPATH: root }, windowsHide: true });
  backend.stdout?.on("data", value => { output += String(value); });
  backend.stderr?.on("data", value => { output += String(value); });
  await expect.poll(async () => {
    if (backend.exitCode !== null) throw new Error(output);
    try { return (await fetch(`http://127.0.0.1:${apiPort}/fixture/counters`)).status; } catch { return 0; }
  }, { timeout: 10000 }).toBe(200);
  const directory = join(root, "web/.pytest_cache"); await mkdir(directory, { recursive: true });
  await writeFile(join(directory, "ml-t27-browser.html"), `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body><div id="app"></div><script type="module">
import {createApp,ref,h} from 'vue';import {createRouter,createWebHistory} from 'vue-router';import AppShell from '../src/layouts/AppShell.vue';import {shellConnectionKey} from '../src/layouts/connection';import {routes} from '../src/router';import '../src/assets/tokens.css';
const monitor={render:()=>h('section',[h('h1','监控测试页面'),h('p','监控页面可访问')])};
const router=createRouter({history:createWebHistory(),routes:routes.map(r=>r.path==='/'?{...r,component:monitor}:r)});
await router.push(window.location.pathname+window.location.search);await router.isReady();const app=createApp(AppShell);app.use(router);app.provide(shellConnectionKey,ref({code:'LIVE',label:'测试连接',marker:'●'}));app.mount('#app');
</script></body></html>`);
  vite = await createServer({ root: join(root, "web"), configFile: false,
    server: { host: "127.0.0.1", port: webPort, strictPort: true,
      proxy: { "/api": { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true }, "/fixture": { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true } } },
    plugins: [vue(), { name: "loop-test-entry", configureServer(server) { server.middlewares.use((request, _response, next) => { if (request.url?.startsWith("/backtests") || request.url === "/") request.url = "/.pytest_cache/ml-t27-browser.html"; next(); }); } }],
  });
  await vite.listen(); url = `http://127.0.0.1:${webPort}`;
}

test.afterEach(async () => {
  try {
    if (vite && backend && backend.exitCode === null) {
      await fetch(url + "/fixture/shutdown", { method: "POST", headers: { Origin: url } });
      await expect.poll(() => backend.exitCode, { timeout: 10000 }).toBe(0);
      expect(JSON.parse(await readFile(join(temporary, "terminal.json"), "utf8"))).toEqual({ monitorStopped: true });
    }
  } finally { if (backend?.exitCode === null) backend.kill(); await vite?.close(); }
});

async function source(page: Page) {
  await page.goto(url + "/backtests/new");
  await page.getByTestId("choose-prepared-plan").click();
  await page.getByLabel("从文件读取（UTF-8 的 .txt 或 .md）").setInputFiles({ name: "one.txt", mimeType: "text/plain", buffer: Buffer.from(fixture.source.text) });
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveValue(fixture.source.text);
  await page.getByText("补充原文日期（可选）", { exact: true }).click();
  await page.getByLabel("原文成文时间", { exact: true }).fill("2026-08-20T09:00");
  await page.getByLabel("原文可用时间", { exact: true }).fill("2026-08-20T09:00");
  await page.getByLabel("计划交易日", { exact: true }).fill("2026-08-20");
}

async function candidate(page: Page) {
  await page.getByTestId("extract-preparation").click();
  await expect(page.getByText("待审核", { exact: true })).toBeVisible({ timeout: 10000 });
}

test("real upload/retry/edit/review/run journey retains original 503 intent and causal results", async ({ page }) => {
  test.setTimeout(60000); await start("retry", true);
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const creates: { body: string | null; key: string | undefined }[] = [];
  page.on("request", request => { if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/backtest-preparations") creates.push({ body: request.postData(), key: request.headers()["idempotency-key"] }); });
  await source(page); await page.getByRole("button", { name: "保存原文", exact: true }).click();
  await expect(page.getByTestId("retry-preparation-mutation")).toBeVisible();
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveValue(fixture.source.text);
  await page.getByRole("button", { name: "刷新服务状态", exact: true }).click();
  await page.getByRole("button", { name: "重新准备回测服务", exact: true }).click();
  await expect(page.getByText("回测历史可读取", { exact: true })).toBeVisible({ timeout: 10000 });
  expect((await (await page.request.get(url + "/fixture/counters")).json()).monitorStopped).toBe(false);
  await page.getByTestId("retry-preparation-mutation").click(); await expect(page.getByText("待提取", { exact: true })).toBeVisible();
  expect(creates).toHaveLength(2); expect(creates[1]).toEqual(creates[0]);
  await expect(page).toHaveURL(/preparationId=/);
  await page.getByTestId("extract-preparation").click(); await expect(page.getByText("提取失败", { exact: true })).toBeVisible({ timeout: 10000 });
  await candidate(page);
  await page.getByLabel("完整原文", { exact: true }).fill(fixture.source.text + "\n");
  await page.getByRole("button", { name: "保存原文", exact: true }).click(); await expect(page.getByText("待提取", { exact: true })).toBeVisible();
  await candidate(page);
  const supplements = page.locator('[data-testid^="review-supplement-"]');
  for (let index = 0; index < await supplements.count(); index++) await supplements.nth(index).fill("已逐字段核验该默认/补充字段与完整原文的含义。");
  const unknown = page.getByTestId("review-unknown-confirmation"); if (await unknown.count()) await unknown.check();
  await page.getByTestId("review-evidence").fill("已核对原文、现金、核心持仓、成本、取得日期及完整条件规则；接受明确列出的限制。");
  await page.getByTestId("review-confirmation").check(); await page.getByTestId("review-submit").click();
  await expect(page.getByText("已审核冻结", { exact: true })).toBeVisible();
  for (const [id, value] of Object.entries({ "commission-rate": "0.0003", "minimum-commission-fen": "500", "stamp-duty-rate": "0.0005", "transfer-fee-rate": "0.00001", "buy-slippage-fen": "1", "sell-slippage-fen": "1" })) await page.locator("#" + id).fill(value);
  const acceptedPromise = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/backtest-runs");
  await page.getByTestId("submit-backtest-run").click();
  const accepted = await acceptedPromise; expect(accepted.status(), await accepted.text()).toBe(202);
  const receipt = JSON.parse(await accepted.text());
  let job: Record<string, unknown> = {};
  await expect.poll(async () => { const response = await page.request.get(url + "/api/v1/backtest-jobs/" + receipt.jobId); job = await response.json(); expect(response.status(), JSON.stringify(job) + output).toBe(200); return job.status; }, { timeout: 10000 }).toBe("COMPLETED");
  await expect(page.getByTestId("monitor-loop-summary"), JSON.stringify(job) + output).toBeVisible({ timeout: 15000 });
  const runId = new URL(page.url()).pathname.split("/").at(-1)!;
  const run = await (await page.request.get(url + "/api/v1/backtest-runs/" + runId)).json();
  expect(run.report.cycle.fills).toBe(fixture.expected.fills);
  expect(run.report.final_account.cash.balance_fen).toBe(fixture.expected.cash_fen);
  expect(run.report.final_inventory.total_qty).toBe(fixture.expected.inventory_qty);
  expect(run.report.boundary.evidence_cutoff).toBe(fixture.cutoff);
  expect(run.provenance.sourceRevision).toBe(2);
  await expect(page.getByTestId("monitor-loop-summary")).toContainText("1023.96 元");
  await page.getByTestId("result-tab-details").click(); await expect(page.getByTestId("monitor-loop-timeline")).toBeVisible();
  expect(await page.locator("li[data-event-id]").count()).toBe(run.report.event_count);
  await page.getByTestId("result-tab-fills").click(); await expect(page.getByRole("table")).toContainText("39.71");
  for (const width of [1440, 390]) { await page.setViewportSize({ width, height: 900 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); }
  expect((await (await page.request.get(url + "/fixture/counters")).json()).extractions).toBe(3);
  await page.getByRole("button", { name: "停止回测服务", exact: true }).click();
  await expect(page.getByText("回测服务已停止", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "返回监控总览", exact: true }).click();
  await expect(page.getByRole("heading", { name: "监控测试页面" })).toBeVisible();
  expect((await (await page.request.get(url + "/fixture/counters")).json()).monitorStopped).toBe(false);
  expect(errors).toEqual([]);
});

test("unknown extraction cancellation survives navigation and requires explicit ended confirmation", async ({ page }) => {
  test.setTimeout(45000); await start("unknown");
  await source(page); await page.getByRole("button", { name: "保存原文", exact: true }).click();
  await expect(page.getByText("待提取", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/preparationId=/); const preparedUrl = page.url();
  await page.getByTestId("extract-preparation").click(); await expect(page.getByTestId("recover-preparation")).toBeVisible({ timeout: 10000 });
  await page.getByTestId("cancel-preparation").click(); await expect(page.getByText("等待提取结束", { exact: true })).toBeVisible();
  expect(await page.getByLabel("完整原文", { exact: true }).isDisabled()).toBe(true);
  const create = await page.request.post(url + "/api/v1/backtest-preparations", { headers: { Origin: url, "Idempotency-Key": "other" }, data: { input: { preparation_id: "other", sources: [fixture.source] } } });
  expect(create.status()).toBe(409);
  await page.getByRole("link", { name: "监控总览", exact: true }).click(); await expect(page.getByRole("heading", { name: "监控测试页面" })).toBeVisible();
  expect((await (await page.request.get(url + "/fixture/counters")).json()).monitorStopped).toBe(false);
  await page.goto(preparedUrl); await expect(page.getByText("等待提取结束", { exact: true })).toBeVisible();
  const recover = page.getByTestId("recover-preparation"); expect(await recover.isDisabled()).toBe(true);
  await page.getByLabel("我已核实此前提取已结束").check(); await recover.click();
  await expect(page.getByText("已取消", { exact: true })).toBeVisible();
  expect((await (await page.request.get(url + "/fixture/counters")).json()).extractions).toBe(1);
});
