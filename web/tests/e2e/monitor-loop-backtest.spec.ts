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
  await writeFile(join(directory, "ml-t27-browser.html"), `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><body><div id="app"></div><script type="module">
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
  await page.getByRole("button", { name: "只准备一份原文", exact: true }).click();
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

test("four complete plans produce one continuous account and one run in real Chrome", async ({ page }, testInfo) => {
  test.setTimeout(600000); await start("continuity-retry");
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  const creates: unknown[] = [], submissions: unknown[] = [];
  page.on("request", request => {
    if (request.method() !== "POST") return;
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/backtest-preparations") creates.push(request.postDataJSON());
    if (path === "/api/v1/backtest-runs") submissions.push(request.postDataJSON());
  });
  const inputs = await (await page.request.get(url + "/fixture/continuity-sources")).json() as {
    sources: { source_id: string; text: string; authored_at: string; available_at: string; effective_trade_date: string }[];
  };
  await page.goto(url + "/backtests/new"); await page.getByTestId("choose-prepared-plan").click();
  await page.getByLabel("一次选择多份文本文件（每份保留独立边界）").setInputFiles(inputs.sources.map((source, index) => ({
    name: `day-${index + 1}.txt`, mimeType: "text/plain", buffer: Buffer.from(source.text),
  })));
  const rows = page.locator('[data-testid^="source-item-"]'); await expect(rows).toHaveCount(4);
  for (const [index, source] of inputs.sources.entries()) {
    const row = rows.nth(index);
    await expect(row.locator("textarea")).toHaveValue(source.text);
    await row.getByLabel("原文成文时间（上海时间）").fill(source.authored_at.slice(0, 16));
    await row.getByLabel("历史可用时间（上海时间）").fill(source.available_at.slice(0, 16));
    await row.getByLabel("生效交易日").fill(source.effective_trade_date);
  }
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`continuity-input-${width}.png`), fullPage: true });
  }
  await page.getByRole("button", { name: "保存全部原文", exact: true }).click();
  await expect(page).toHaveURL(/preparationId=/);
  expect(creates).toHaveLength(1);
  expect(creates[0]).toMatchObject({ input: { schema_version: "backtest-preparation-v2" } });
  const createdSources = (creates[0] as { input: { sources: { text: string }[] } }).input.sources;
  expect(createdSources.map(source => source.text)).toEqual(inputs.sources.map(source => source.text));
  const preparationId = new URL(page.url()).searchParams.get("preparationId")!;
  await page.getByTestId("extract-preparation").click();
  await expect.poll(async () => {
    const response = await page.request.get(url + "/api/v1/backtest-preparations/" + preparationId);
    return response.status() === 200 ? (await response.json()).status : null;
  }, { timeout: 20000 }).toBe("FAILED");
  expect((await (await page.request.get(url + "/fixture/counters")).json()).sourceCalls).toEqual([0, 1]);
  await expect(page.getByTestId("extract-preparation")).toBeEnabled({ timeout: 10000 });
  await page.getByTestId("extract-preparation").click();
  await expect.poll(async () => (await (await page.request.get(url + "/fixture/counters")).json()).retryEntered).toBe(true);
  const competing = await page.request.post(url + "/api/v1/backtest-preparations", {
    headers: { Origin: url, "Idempotency-Key": "competing-four-chain" },
    data: { input: { schema_version: "backtest-preparation-v2", preparation_id: "competing", sources: inputs.sources } },
  });
  expect(competing.status(), await competing.text()).toBe(409);
  await page.request.post(url + "/fixture/release-retry");
  await expect.poll(async () => {
    const response = await page.request.get(url + "/api/v1/backtest-preparations/" + preparationId);
    const value = await response.json();
    if (response.status() === 503) return [];
    expect(response.status(), JSON.stringify(value)).toBe(200);
    return value.items.map((item: { validation: string; status: string }) => ({ validation: item.validation, status: item.status }));
  }, { timeout: 20000 }).toEqual(Array(4).fill({ validation: "VALID", status: "CANDIDATE" }));
  await expect(page.getByLabel("整链核对说明"), output).toBeEnabled({ timeout: 20000 });
  const progress = await (await page.request.get(url + "/api/v1/backtest-preparations/" + preparationId)).json();
  expect(progress.items.map((item: { validation: string }) => item.validation)).toEqual(["VALID", "VALID", "VALID", "VALID"]);
  expect((await (await page.request.get(url + "/fixture/counters")).json()).sourceCalls).toEqual([0, 1, 1, 2, 3]);
  await page.getByRole("button", { name: /^第 3 份 ·/ }).click();
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveValue(inputs.sources[2]!.text);
  await page.getByLabel("完整原文", { exact: true }).fill(inputs.sources[2]!.text + "\n");
  const editedPromise = page.waitForResponse(response => response.request().method() === "PUT" && new URL(response.url()).pathname.endsWith("/source"));
  await page.getByRole("button", { name: "保存原文", exact: true }).click();
  const edited = await editedPromise; expect(edited.status(), await edited.text()).toBe(200);
  const changed = await edited.json();
  expect(changed.items.slice(0, 2).map((item: { candidateHash: string }) => item.candidateHash)).toEqual(progress.items.slice(0, 2).map((item: { candidateHash: string }) => item.candidateHash));
  expect(changed.items.slice(2).map((item: { candidateHash: string | null }) => item.candidateHash)).toEqual([null, null]);
  await expect(page.getByLabel("整链核对说明")).toBeDisabled();
  const resumedPromise = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/extractions"));
  await page.getByTestId("extract-preparation").click();
  const resumed = await resumedPromise;
  expect(resumed.status(), JSON.stringify({ request: resumed.request().postDataJSON(), response: await resumed.json() })).toBe(202);
  await expect(page.getByLabel("整链核对说明")).toBeEnabled({ timeout: 20000 });
  expect((await (await page.request.get(url + "/fixture/counters")).json()).sourceCalls).toEqual([0, 1, 1, 2, 3, 2, 3]);
  await page.getByLabel("整链核对说明").fill("逐份核对四个完整计划、日期、持仓声明与唯一期初账户；以后仅按真实模拟成交延续账户。");
  await page.getByTestId("review-confirmation").check();
  const reviewedPromise = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === `/api/v1/backtest-preparations/${preparationId}/reviews`);
  await page.getByRole("button", { name: "审核并冻结整条计划链", exact: true }).click();
  const reviewed = await reviewedPromise; expect(reviewed.status(), await reviewed.text()).toBe(200);
  await expect(page.getByTestId("prepared-run-versions").locator("li")).toHaveCount(4);
  await expect(page.getByTestId("prepared-run-account")).toContainText("10000.00");
  for (const [id, value] of Object.entries({ "commission-rate": "0", "minimum-commission-fen": "500", "stamp-duty-rate": "0", "transfer-fee-rate": "0", "buy-slippage-fen": "0", "sell-slippage-fen": "0", "end-date": "2026-08-25" })) await page.locator("#" + id).fill(value);
  const acceptedPromise = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/backtest-runs");
  await page.getByTestId("submit-backtest-run").click(); const accepted = await acceptedPromise;
  expect(accepted.status(), await accepted.text()).toBe(202);
  const receipt = await accepted.json();
  expect(submissions).toHaveLength(1); expect(submissions[0]).toMatchObject({ schemaVersion: "prepared-loop-plan-v2", preparationId });
  await expect.poll(async () => (await (await page.request.get(url + "/api/v1/backtest-jobs/" + receipt.jobId)).json()).status,
    { timeout: 540000, intervals: [500, 1000, 2000] }).toBe("COMPLETED");
  await expect(page.getByTestId("monitor-loop-summary")).toBeVisible({ timeout: 15000 });
  const run = await (await page.request.get(url + "/api/v1/backtest-runs/" + receipt.runId)).json();
  expect(run.schemaVersion).toBe("monitor-loop-result-v2"); expect(run.versions).toHaveLength(4);
  expect(run.report.cycle.fills).toBe(2); expect(run.report.final_account.cash.balance_fen).toBe(1019000);
  expect(run.report.final_inventory.total_qty).toBe(0); expect(run.report.metrics.paid_fees_fen).toBe(1000);
  expect(run.report.metrics.realized_pnl_fen).toBe(19000);
  await expect(page.getByRole("region", { name: "冻结版本日历", exact: true }).locator("li")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "冻结版本日历", exact: true })).toContainText("机动 200 股");
  await expect(page.getByTestId("monitor-loop-summary")).toContainText("10190.00 元");
  const equity = await (await page.request.get(url + "/api/v1/backtest-runs/" + receipt.runId + "/equity-series")).json();
  expect(equity.availability).toBe("AVAILABLE"); expect(equity.items).toHaveLength(7);
  expect(equity.items.map((point: { cashFen: string }) => point.cashFen)).toEqual(["1000000", "899500", "899500", "899500", "899500", "1019000", "1019000"]);
  expect(equity.items.map((point: { markedAt: string }) => point.markedAt.slice(0, 10))).toEqual(["2026-08-20", "2026-08-20", "2026-08-21", "2026-08-22", "2026-08-23", "2026-08-24", "2026-08-25"]);
  expect(equity.items.map((point: { positionQuantity: number }) => point.positionQuantity)).toEqual([0, 100, 100, 100, 100, 0, 0]);
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`continuity-result-${width}.png`), fullPage: true });
    await page.getByTestId("monitor-loop-summary").scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`continuity-result-viewport-${width}.png`) });
  }
  await page.getByTestId("result-tab-equity").click();
  await expect(page.getByRole("heading", { name: "完整权益序列", exact: true })).toBeVisible();
  await expect(page.getByRole("table").locator("tbody tr")).toHaveCount(7);
  await expect(page.getByRole("table")).toContainText("10190.00");
  await expect(page.getByTestId("backtest-equity-chart").locator("canvas")).toBeVisible();
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("heading", { name: "完整权益序列", exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`continuity-equity-${width}.png`) });
  }
  expect(errors).toEqual([]);
});
