import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { createServer as createSocketServer } from "node:net";
import { createServer, type ViteDevServer } from "vite";
import vue from "@vitejs/plugin-vue";
import { expect, test, type Page } from "@playwright/test";
import fixture from "../fixtures/monitor-loop.json" with { type: "json" };
import axe from "axe-core";

const root = resolve(import.meta.dirname, "../../..");
let backend: ChildProcess;
let vite: ViteDevServer;
let url: string;
let temporary: string;
let output: string;
let preparationReads: object[];

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
  preparationReads = [];
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

test.afterEach(async ({ page }, testInfo) => {
  try {
    if (testInfo.status !== testInfo.expectedStatus) {
      const readsPath = testInfo.outputPath("preparation-reads.json");
      await writeFile(readsPath, JSON.stringify(preparationReads, null, 2));
      await testInfo.attach("preparation-reads", { path: readsPath, contentType: "application/json" });
      await testInfo.attach("page-state", { body: await page.locator("body").innerText(), contentType: "text/plain" });
      await testInfo.attach("backend-output", { body: output, contentType: "text/plain" });
    }
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
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveCount(0);
  await page.getByTestId("new-plan-timeline").click();
  await expect(page.getByRole("heading", { name: "准备计划原文", exact: true })).toBeFocused();
  await page.getByTestId("close-preparation-workspace").click();
  await expect(page.getByTestId("new-plan-timeline")).toBeFocused();
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveCount(0);
  await page.getByTestId("new-plan-timeline").click();
  await page.getByLabel("从文件读取（UTF-8 的 .txt 或 .md）").setInputFiles({ name: "one.txt", mimeType: "text/plain", buffer: Buffer.from(fixture.source.text) });
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveValue(fixture.source.text);
  await expect(page.getByTestId("close-preparation-workspace")).toBeDisabled();
  await expect(page.locator('input[type="datetime-local"]')).toHaveCount(0);
  await page.getByLabel("生效交易日（留空自动识别，必要时确认）", { exact: true }).fill("2026-08-20");
}

async function candidate(page: Page) {
  await page.getByTestId("extract-preparation").click();
  await expect(page.getByText("待审核", { exact: true })).toBeVisible({ timeout: 10000 });
  await expect(page.getByLabel("完整原文", { exact: true })).toBeEnabled();
}

test("real upload/retry/edit/review/run journey retains original 503 intent and causal results", async ({ page }, testInfo) => {
  test.setTimeout(120000); await start("retry", true);
  page.on("response", async response => {
    if (response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/v1/backtest-preparations/")) {
      preparationReads.push({ url: response.url(), status: response.status(), headers: response.headers(), body: await response.text().catch(() => "aborted") });
    }
  });
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const legacyCommand = { headers: { Origin: url, "Idempotency-Key": "legacy-original" }, data: { input: { preparation_id: "legacy-one", sources: [fixture.source] } } };
  expect((await page.request.post(url+"/api/v1/backtest-preparations",legacyCommand)).status()).toBe(503);
  await page.goto(url+"/backtests/new");
  await page.getByRole("button", { name: "刷新服务状态", exact: true }).click();
  await page.getByRole("button", { name: "重新准备回测服务", exact: true }).click();
  await expect(page.getByText("回测历史可读取", { exact: true })).toBeVisible({ timeout: 10000 });
  expect((await (await page.request.get(url + "/fixture/counters")).json()).monitorStopped).toBe(false);
  expect((await page.request.post(url+"/api/v1/backtest-preparations",legacyCommand)).status()).toBe(201);
  await page.goto(url+"/backtests/new?preparationId=legacy-one");
  await expect(page.getByLabel("完整原文",{exact:true})).toHaveValue(fixture.source.text);
  await expect(page).toHaveURL(/preparationId=/);
  await page.getByTestId("extract-preparation").click(); await expect(page.getByText("提取失败", { exact: true })).toBeVisible({ timeout: 10000 });
  await candidate(page);
  await page.getByLabel("完整原文", { exact: true }).fill(fixture.source.text + "\n");
  await page.getByLabel("生效交易日（留空自动识别，必要时确认）", { exact: true }).fill("2026-08-20");
  await page.getByRole("button", { name: "保存原文", exact: true }).click(); await expect(page.getByText("待提取", { exact: true })).toBeVisible();
  await candidate(page);
  const supplements = page.locator('[data-testid^="review-supplement-"]');
  for (let index = 0; index < await supplements.count(); index++) await supplements.nth(index).fill("已逐字段核验该默认/补充字段与完整原文的含义。");
  const unknown = page.getByTestId("review-unknown-confirmation"); if (await unknown.count()) await unknown.check();
  await page.getByTestId("review-evidence").fill("已核对原文、现金、核心持仓、成本、取得日期及完整条件规则；接受明确列出的限制。");
  await page.getByTestId("review-confirmation").check(); await page.getByTestId("review-submit").click();
  await expect(page.getByRole("region", { name: "回测设置", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "回测设置", exact: true })).toBeFocused();
  await expect(page.locator("#end-date")).toHaveValue(new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10));
  for (const [id, value] of Object.entries({ "commission-rate": "0.0001", "minimum-commission-fen": "500", "stamp-duty-rate": "0.0005", "transfer-fee-rate": "0.00001", "buy-slippage-fen": "0", "sell-slippage-fen": "0" }))
    await expect(page.locator("#" + id)).toHaveValue(value);
  for (const [id, value] of Object.entries({ "commission-rate": "0.0003", "minimum-commission-fen": "500", "stamp-duty-rate": "0.0005", "transfer-fee-rate": "0.00001", "buy-slippage-fen": "1", "sell-slippage-fen": "1", "end-date": fixture.cutoff.slice(0, 10) })) await page.locator("#" + id).fill(value);
  const acceptedPromise = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/backtest-runs");
  await page.getByTestId("submit-backtest-run").click();
  const accepted = await acceptedPromise; expect(accepted.status(), await accepted.text()).toBe(202);
  const receipt = JSON.parse(await accepted.text());
  let job: Record<string, unknown> = {};
  await expect.poll(async () => { const response = await page.request.get(url + "/api/v1/backtest-jobs/" + receipt.jobId); job = await response.json(); expect(response.status(), JSON.stringify(job) + output).toBe(200); return job.status; }, { timeout: 10000 }).toBe("COMPLETED");
  await expect(page.getByTestId("backtest-overview"), JSON.stringify(job) + output).toBeVisible({ timeout: 15000 });
  const runId = new URL(page.url()).pathname.split("/").at(-1)!;
  const run = await (await page.request.get(url + "/api/v1/backtest-runs/" + runId)).json();
  expect(run.report.cycle.fills).toBe(fixture.expected.fills);
  expect(run.report.final_account.cash).toEqual({ kind: "POSITION_LIMIT_ONLY" });
  expect(run.report.metrics.paid_fees_fen).toBe(fixture.expected.paid_fees_fen);
  // Exact source lot cost + causal buy/slippage/fees, valued at the final 40.20 mark.
  expect(run.report.metrics.cost_pnl_fen).toBe(200 * 4020 - 401050 - 100 * 3971 - fixture.expected.paid_fees_fen);
  expect(run.report.metrics.realized_pnl_fen).toBe(0);
  expect(run.report.metrics.unrealized_pnl_fen).toBe(5346);
  expect(run.report.metrics.interval_return).toBeNull();
  expect(run.report.final_inventory.total_qty).toBe(fixture.expected.inventory_qty);
  expect(run.report.boundary.evidence_cutoff).toBe(fixture.cutoff);
  expect(run.provenance.sourceRevision).toBe(2);
  await expect(page.getByTestId("backtest-overview")).toContainText("不限制现金");
  await page.getByText("查看模拟费用设置", { exact: true }).click();
  const savedCosts = page.getByRole("region", { name: "本次回测费用参数", exact: true });
  await expect(savedCosts).toContainText("0.03%");
  await expect(savedCosts).toContainText("5.00 元/笔");
  await expect(savedCosts).toContainText("0.05%");
  await expect(savedCosts).toContainText("0.001%");
  await expect(savedCosts).toContainText("0.01 元/股");
  await expect(savedCosts.locator("input,select,button")).toHaveCount(0);
  await expect(page.getByTestId("backtest-profit-summary")).toContainText("+53.46 元");
  await page.getByTestId("result-tab-details").click(); await expect(page.getByTestId("monitor-loop-timeline")).toBeVisible();
  expect(await page.locator("li[data-event-id]").count()).toBe(run.report.event_count);
  await page.getByTestId("result-tab-fills").click(); await expect(page.getByRole("table")).toContainText("39.71");
  const contextReads: string[] = [];
  page.on("request", request => { if (request.url().includes("/review-context?")) contextReads.push(request.url()); });
  await page.getByTestId("review-fill").first().click();
  const evidence = page.getByTestId("backtest-evidence-panel");
  await expect(evidence.getByTestId("review-outcome")).toContainText("已模拟成交");
  await expect(page).toHaveURL(/fillId=/);
  await expect(page.locator("#review-evidence-title")).toBeFocused();
  await expect(evidence).toContainText("计划要求与实际依据");
  await expect(evidence).toContainText("结果持仓");
  expect(contextReads).toHaveLength(1);
  await evidence.getByRole("button", { name: "后续直接事件", exact: true }).click();
  await expect(evidence.getByRole("button", { name: "后续直接事件", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.goBack();
  await expect(evidence.getByRole("button", { name: "追溯原因", exact: true })).toHaveAttribute("aria-pressed", "true");
  for (const width of [1440, 1024, 768, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(evidence.getByRole("button", { name: "关闭原因", exact: true })).toBeVisible();
    if (width === 1440 || width === 320) {
      const path = testInfo.outputPath(`review-${width}.png`);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path, fullPage: true });
      await testInfo.attach(`review-${width}`, { path, contentType: "image/png" });
    }
  }
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => {
    const result = await (window as unknown as { axe: typeof axe }).axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } });
    return result.violations.filter(item => item.impact === "serious" || item.impact === "critical");
  });
  expect(violations).toEqual([]);
  await evidence.getByRole("button", { name: "关闭原因", exact: true }).click();
  await expect(evidence).toHaveCount(0);
  await page.getByTestId("result-tab-reasons").click();
  await expect(page.getByTestId("plan-execution-diagnostics")).toBeVisible();
  const diagnostic = page.getByTestId("review-diagnostic").first();
  await diagnostic.focus(); await page.keyboard.press("Enter");
  await expect(evidence).toBeVisible();
  await expect(page).toHaveURL(/sequence=/);
  await expect(page.locator("#review-evidence-title")).toBeFocused();
  await evidence.getByRole("button", { name: "关闭原因", exact: true }).click();
  await expect(diagnostic).toBeFocused();
  expect((await (await page.request.get(url + "/fixture/counters")).json()).extractions).toBe(3);
  const serviceManagement = page.getByTestId("backtest-service-management-toggle");
  if (await serviceManagement.getAttribute("aria-expanded") === "false") await serviceManagement.click();
  await page.getByText("高级服务管理", { exact: true }).click();
  await page.getByRole("button", { name: "停止回测服务", exact: true }).click();
  await page.getByRole("button", { name: "确认停止服务", exact: true }).click();
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
  await page.getByTestId("cancel-preparation").click(); await expect(page.getByText("等待提取结束", { exact: true }).first()).toBeVisible();
  await expect(page.getByLabel("完整原文", { exact: true })).toBeDisabled();
  const create = await page.request.post(url + "/api/v1/backtest-preparations", { headers: { Origin: url, "Idempotency-Key": "other" }, data: { input: { preparation_id: "other", sources: [fixture.source] } } });
  expect(create.status()).toBe(409);
  await page.getByRole("link", { name: "监控总览", exact: true }).click(); await expect(page.getByRole("heading", { name: "监控测试页面" })).toBeVisible();
  expect((await (await page.request.get(url + "/fixture/counters")).json()).monitorStopped).toBe(false);
  await page.goto(preparedUrl); await expect(page.getByText("等待提取结束", { exact: true }).first()).toBeVisible();
  const recover = page.getByTestId("recover-preparation"); expect(await recover.isDisabled()).toBe(true);
  await page.getByLabel("我已核实此前提取已结束").check(); await recover.click();
  await expect(page.getByText("已取消", { exact: true }).first()).toBeVisible();
  expect((await (await page.request.get(url + "/fixture/counters")).json()).extractions).toBe(1);
});

test("start automatically fills missing history with the real worker and then replays", async ({ page }, testInfo) => {
  test.setTimeout(180000); await start("auto-data");
  const errors: string[] = [], commands: string[] = [], checks: boolean[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.method() === "POST") commands.push(new URL(request.url()).pathname); });
  page.on("response", response => {
    if (new URL(response.url()).pathname === "/api/v1/backtest-run-data" && response.status() === 200) {
      response.json().then(body => checks.push(body.ready));
    }
  });
  const created = await page.request.post(url + "/api/v1/backtest-preparations", {
    headers: { Origin: url, "Idempotency-Key": "auto-data-source" },
    data: { input: { preparation_id: "auto-one", sources: [fixture.source] } },
  });
  expect(created.status(), await created.text()).toBe(201);
  await page.goto(url + "/backtests/new?preparationId=auto-one");
  await candidate(page);
  const supplements = page.locator('[data-testid^="review-supplement-"]');
  for (let index = 0; index < await supplements.count(); index++) await supplements.nth(index).fill("核对合成原文的参数与来源绑定。");
  const unknown = page.getByTestId("review-unknown-confirmation"); if (await unknown.count()) await unknown.check();
  await page.getByTestId("review-evidence").fill("核对原文计划、期初持仓和规则，接受明确的研究限制。");
  await page.getByTestId("review-confirmation").check(); await page.getByTestId("review-submit").click();
  await expect(page.getByRole("region", { name: "回测设置", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "回测设置", exact: true })).toBeFocused();
  expect((await (await page.request.get(url + "/fixture/counters")).json()).dataCalls).toEqual([]);
  for (const [id, value] of Object.entries({ "commission-rate": "0", "minimum-commission-fen": "0", "stamp-duty-rate": "0", "transfer-fee-rate": "0", "buy-slippage-fen": "0", "sell-slippage-fen": "0", "end-date": "2026-08-20" })) await page.locator("#" + id).fill(value);
  const sync = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/backtest-data-syncs");
  const accepted = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/backtest-runs");
  await page.getByTestId("submit-backtest-run").click();
  expect((await sync).status()).toBe(202);
  await expect(page.getByText("正在自动补齐历史数据", { exact: true })).toBeVisible();
  await expect(page.getByTestId("cancel-automatic-data")).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("automatic-preparation.png"), fullPage: true });
  const response = await accepted; expect(response.status(), await response.text()).toBe(202);
  await expect(page.getByTestId("backtest-overview")).toBeVisible({ timeout: 120000 });
  expect(checks).toEqual([false, true]);
  expect(commands.filter(path => path === "/api/v1/backtest-data-syncs")).toHaveLength(1);
  expect(commands.filter(path => path === "/api/v1/backtest-runs")).toHaveLength(1);
  expect(commands).not.toContain("/api/v1/backtest-dataset-verifications");
  expect((await (await page.request.get(url + "/fixture/counters")).json()).dataCalls).toContain("minutes");
  expect(errors).toEqual([]);
});

test("four complete plans produce one continuous account and one run in real Chrome", async ({ page }, testInfo) => {
  test.setTimeout(600000); await start("continuity-retry");
  // This regression deliberately retains the historical KNOWN funding contract.
  // New ordinary preparations default to POSITION_LIMIT_ONLY; no production default changes here.
  await page.route(`${url}/api/v1/backtest-preparations/*/reviews`, async route => {
    const body = route.request().postDataJSON();
    if (body.kind === "CHAIN_REVIEW" && body.review.items.length === 1) {
      body.review.account = { snapshot_at: "2026-08-20T09:00:00+08:00", inventory_known: true,
        cash: { kind: "KNOWN", balance_fen: 1000000 }, lots: [], opening_mark: null,
        evidence: "Historical funded fixture: original explicitly states 10000 yuan and zero holdings." };
      await route.continue({ postData: JSON.stringify(body) });
    } else await route.continue();
  });
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const consoleErrors: { text: string; url: string }[] = [];
  const revisionConflicts = new Set<string>();
  const startingReads = new Set<string>();
  const responseChecks: Promise<void>[] = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push({ text: message.text(), url: message.location().url }); });
  page.on("response", response => {
    if (response.status() === 503 && response.request().method() === "GET" &&
        (new URL(response.url()).pathname === "/api/v1/backtest-plan-library" ||
         /^\/api\/v1\/backtest-preparations\/[^/]+$/.test(new URL(response.url()).pathname))) {
      responseChecks.push((async () => {
        expect((await response.json()).error.code).toBe("SERVICE_UNAVAILABLE");
        startingReads.add(response.url());
      })());
    }
    // Serial extraction can advance the revision between progress and item reads.
    // Allow only this verified read conflict; all other console errors still fail.
    if (response.status() === 409 && response.request().method() === "GET" &&
        /^\/api\/v1\/backtest-preparations\/[^/]+\/items$/.test(new URL(response.url()).pathname)) {
      responseChecks.push((async () => {
        const body = await response.json();
        expect(body.error.code).toBe("CONFLICT");
        expect(body.error.details.map((detail: { code: string }) => detail.code)).toEqual(["PREPARATION_REVISION_CONFLICT"]);
        revisionConflicts.add(response.url());
      })());
    }
  });
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
  inputs.sources.forEach(source => { source.text += `\n生效交易日：${source.effective_trade_date}`; });
  await page.goto(url + "/backtests/new"); await page.getByTestId("choose-prepared-plan").click();
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveCount(0);
  await page.getByTestId("new-plan-timeline").click();
  let previousId = "";
  for (const [index, source] of inputs.sources.entries()) {
    if (index) {
      await page.getByTestId("prepare-next-source").click();
      await expect(page.getByRole("status").filter({ hasText: "正在更新" })).toContainText("前序生效日");
    }
    await page.getByLabel("从文件读取（UTF-8 的 .txt 或 .md）").setInputFiles({ name: `day-${index+1}.txt`, mimeType: "text/plain", buffer: Buffer.from(source.text) });
    const saved = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/backtest-plan-library/preparations");
    await page.getByRole("button", { name: "保存原文", exact: true }).click();
    const response = await saved; expect(response.status(), await response.text()).toBe(201);
    const record = await response.json(); previousId = record.preparationId;
    expect(record.itemCount).toBe(index+1);
    expect(record.items.at(-1).effectiveTradeDate).toBe(source.effective_trade_date);
    await page.getByTestId("extract-preparation").click();
    if (index === 1) {
      await expect(page.getByText("提取失败", { exact: true }).first()).toBeVisible({ timeout: 20000 });
      await page.getByTestId("extract-preparation").click();
      await expect.poll(async () => (await (await page.request.get(url + "/fixture/counters")).json()).retryEntered).toBe(true);
      await page.request.post(url + "/fixture/release-retry");
    }
    await expect(page.getByLabel("本份核对说明", { exact: true })).toBeEnabled({ timeout: 20000 });
    await page.getByLabel("本份核对说明", { exact: true }).fill("核对本份完整规则、生效日期和已审核前序；保留连续账户与真实模拟成交。");
    await page.getByTestId("review-confirmation").check();
    await page.getByRole("button", { name: "审核并保存这一份计划", exact: true }).click();
    await expect(page.getByRole("region", { name: "回测设置", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "回测设置", exact: true })).toBeFocused();
    await expect(page.getByRole("region", { name: "已审核计划库" }).locator(".plan-library__record")).toHaveCount(index+1);
    await expect(page.getByTestId("prepare-next-source")).toBeVisible();
    await expect(page.getByLabel("完整原文", { exact: true })).toHaveCount(0);
  }
  expect((await (await page.request.get(url + "/fixture/counters")).json()).sourceCalls).toEqual([0,1,1,2,3]);
  await page.reload();
  await expect(page.getByRole("region", { name: "已审核计划库" }).locator(".plan-library__record")).toHaveCount(4);
  await expect(page.getByTestId("open-plan-timeline")).toHaveCount(1);
  await expect(page.locator('[data-endpoint-id="' + previousId + '"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("region", { name: "已审核计划库" }).getByRole("checkbox")).toHaveCount(0);
  for (const width of [320,768,1024,1440]) {
    await page.setViewportSize({width,height:900});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath(`single-library-${width}.png`),fullPage:true});
  }
  await expect(page.getByTestId("prepared-run-versions").locator("li")).toHaveCount(4);
  await expect(page.getByTestId("prepared-run-account")).toContainText("10000.00");
  await expect(page.locator("#end-date")).toHaveValue(new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10));
  for (const [id, value] of Object.entries({ "commission-rate": "0.0001", "minimum-commission-fen": "500", "stamp-duty-rate": "0.0005", "transfer-fee-rate": "0.00001", "buy-slippage-fen": "0", "sell-slippage-fen": "0" }))
    await expect(page.locator("#" + id)).toHaveValue(value);
  for (const [id, value] of Object.entries({ "commission-rate": "0", "minimum-commission-fen": "500", "stamp-duty-rate": "0", "transfer-fee-rate": "0", "buy-slippage-fen": "0", "sell-slippage-fen": "0", "end-date": "2026-08-25" })) await page.locator("#" + id).fill(value);
  await page.getByTestId("timeline-updates").first().getByText("查看更新记录（4）", { exact: true }).click();
  await page.getByText("查看计划及本次调整", { exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "本次建立的交易条件", exact: true })).toBeVisible();
  const inspectionOpened = page.waitForEvent("popup");
  await page.getByRole("link", { name: "查看已审核原文与交易条件（只读，新页面）", exact: true }).first().click();
  const inspection = await inspectionOpened;
  const inspectionWrites: string[] = [], inspectionFailures: string[] = [];
  inspection.on("request", request => { if (!["GET", "HEAD"].includes(request.method())) inspectionWrites.push(request.url()); });
  inspection.on("requestfailed", request => inspectionFailures.push(request.url()));
  await expect(inspection.getByRole("heading", { name: "只读查看历史计划", exact: true })).toBeVisible();
  await expect(inspection.getByTestId("submit-backtest-run")).toHaveCount(0);
  await expect(inspection.getByTestId("new-plan-timeline")).toHaveCount(0);
  await inspection.waitForLoadState("networkidle");
  expect(inspectionWrites).toEqual([]); expect(inspectionFailures).toEqual([]);
  await inspection.close();
  await expect(page.locator('[data-endpoint-id="' + previousId + '"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#end-date")).toHaveValue("2026-08-25");
  const composed = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/backtest-plan-library/compositions");
  const acceptedPromise = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/backtest-runs");
  await page.getByTestId("submit-backtest-run").click();
  const composition = await composed; expect(composition.status(), await composition.text()).toBe(201);
  const preparationId = (await composition.json()).preparationId;
  const accepted = await acceptedPromise;
  expect(accepted.status(), await accepted.text()).toBe(202);
  const receipt = await accepted.json();
  expect(submissions).toHaveLength(1); expect(submissions[0]).toMatchObject({ schemaVersion: "prepared-loop-plan-v2", preparationId });
  await expect.poll(async () => (await (await page.request.get(url + "/api/v1/backtest-jobs/" + receipt.jobId)).json()).status,
    { timeout: 540000, intervals: [500, 1000, 2000] }).toBe("COMPLETED");
  await expect(page.getByTestId("backtest-overview")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("result-tab-provenance").click();
  const run = await (await page.request.get(url + "/api/v1/backtest-runs/" + receipt.runId)).json();
  expect(run.schemaVersion).toBe("monitor-loop-result-v2"); expect(run.versions).toHaveLength(4);
  expect(run.report.cycle.fills).toBe(2); expect(run.report.final_account.cash.balance_fen).toBe(1019000);
  expect(run.report.final_inventory.total_qty).toBe(0); expect(run.report.metrics.paid_fees_fen).toBe(1000);
  expect(run.report.metrics.realized_pnl_fen).toBe(19000);
  await expect(page.getByRole("group", { name: "选择生效版本", exact: true }).getByRole("button")).toHaveCount(4);
  const contextIndex = run.versions.findIndex((version: { accountContext?: { tactical_qty?: number } | null }) => version.accountContext?.tactical_qty === 200);
  expect(contextIndex).toBeGreaterThanOrEqual(0);
  await page.getByRole("group", { name: "选择生效版本", exact: true }).getByRole("button").nth(contextIndex).click();
  await expect(page.getByRole("region", { name: "冻结版本日历", exact: true })).toContainText("机动 200 股");
  await expect(page.getByTestId("monitor-loop-summary")).toContainText("10190.00 元");
  await page.getByText("账户与运行设置", { exact: true }).click();
  const savedCosts = page.getByRole("region", { name: "本次回测费用参数", exact: true });
  await expect(savedCosts.locator("dd")).toHaveText(["0%", "5.00 元/笔", "0%", "0%", "0.00 元/股", "0.00 元/股"]);
  const historyWrites: string[] = [];
  const auditHistory = (request: import("@playwright/test").Request) => {
    if (!["GET", "HEAD"].includes(request.method())) historyWrites.push(request.url());
  };
  page.on("request", auditHistory);
  await page.reload();
  await page.getByText("账户与运行设置", { exact: true }).click();
  await expect(savedCosts.locator("dd")).toHaveText(["0%", "5.00 元/笔", "0%", "0%", "0.00 元/股", "0.00 元/股"]);
  expect(await (await page.request.get(url + "/api/v1/backtest-runs/" + receipt.runId)).json()).toEqual(run);
  expect(historyWrites).toEqual([]);
  page.off("request", auditHistory);
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
  await page.getByText("查看完整精确数值表", { exact: true }).click();
  await expect(page.getByRole("table").locator("tbody tr")).toHaveCount(7);
  await expect(page.getByRole("table")).toContainText("10190.00");
  await expect(page.getByTestId("backtest-equity-chart").locator("canvas")).toBeVisible();
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("heading", { name: "完整权益序列", exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`continuity-equity-${width}.png`) });
  }
  await Promise.all(responseChecks);
  expect(consoleErrors.filter(error => !(revisionConflicts.has(error.url) &&
    error.text === "Failed to load resource: the server responded with a status of 409 (Conflict)") &&
    !(startingReads.has(error.url) && error.text === "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"))).toEqual([]);
  expect(errors).toEqual([]);
});


test("actual originals are prepared individually and require date confirmation before AI", async ({ page }, testInfo) => {
  test.setTimeout(60000); await start("retry");
  const filenames = ["01-20260924-104506.txt", "02-20260928-092555.txt", "03-20260930-095728.txt", "04-20261009-091956.txt"];
  const dates = ["2026-09-24","2026-09-28","2026-09-30","2026-10-09"];
  await page.goto(url + "/backtests/new"); await page.getByTestId("choose-prepared-plan").click();
  await expect(page.getByLabel("完整原文", { exact: true })).toHaveCount(0);
  await page.getByTestId("new-plan-timeline").click();
  for (const [index,name] of filenames.entries()) {
    if (index) await page.getByTestId("new-plan-timeline").click();
    await page.getByLabel("从文件读取（UTF-8 的 .txt 或 .md）").setInputFiles({name,mimeType:"text/plain",buffer:await readFile(join(root,"tests/fixtures/shengxin_sources",name))});
    const created = page.waitForResponse(r => r.request().method()==="POST" && new URL(r.url()).pathname==="/api/v1/backtest-plan-library/preparations");
    await page.getByRole("button",{name:"保存原文",exact:true}).click();
    const response = await created; expect(response.status()).toBe(201); const record = await response.json();
    expect(record.itemCount).toBe(1);
    await expect(page.getByRole("region",{name:"准备进度"})).toContainText("请先确认日期并保存");
    await expect(page.getByTestId("extract-preparation")).toHaveCount(0);
    expect((await (await page.request.get(url+"/fixture/counters")).json()).extractions).toBe(0);
    const denied = await page.request.post(url+`/api/v1/backtest-preparations/${record.preparationId}/extractions`,{
      headers:{Origin:url,"Idempotency-Key":`missing-${index}`},data:{schemaVersion:"backtest-preparation-v2",expectedRevision:record.revision,sourceId:record.items[0].sourceId,expectedSourceRevision:1,expectedBaseHash:null}});
    expect(denied.status()).toBe(409); expect((await denied.json()).error.details[0].code).toBe("SOURCE_DATE_REQUIRED");
    await page.getByLabel("生效交易日（留空自动识别，必要时确认）",{exact:true}).fill(dates[index]!);
    const saved = page.waitForResponse(r => r.request().method()==="PUT" && new URL(r.url()).pathname.endsWith("/source"));
    await page.getByRole("button",{name:"保存原文",exact:true}).click(); expect((await saved).status()).toBe(200);
    await expect(page.getByTestId("extract-preparation")).toBeEnabled();
  }
  await page.getByTestId("extract-preparation").click();
  await expect(page.getByRole("region",{name:"准备进度"})).toContainText("AI 服务限流",{timeout:15000});
  expect((await (await page.request.get(url+"/fixture/counters")).json()).extractions).toBe(1);
  for (const width of [320,1440]) { await page.setViewportSize({width,height:900}); expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true); await page.screenshot({path:testInfo.outputPath(`actual-single-${width}.png`),fullPage:true}); }
});
