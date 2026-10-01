import { spawn, type ChildProcess } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { createServer } from "node:net";
import { expect, test } from "@playwright/test";

const repo = resolve(process.cwd(), "..");
const literal = JSON.parse(await readFile(join(repo, "tests/fixtures/ai/explicit-plan-literal-source-v3.json"), "utf8"));
let base: string; let server: ChildProcess | undefined; let serverLog = "";
const headers = { "X-Monitor-Contract-Version": "2" };

interface PresentationObservation { at: number; path: string; riskPresent: boolean; riskActionable: boolean; withdrawalMessage: boolean }
interface ReadFailureDiagnostic {
  path: string; method: string; status: number; requestId: string; monitorContractVersion: string;
  cause: string; causeType?: string; causeMessage?: string;
}
interface FailedResponseObservation {
  at: number; phase: string; url: string; method: string; status: number;
  monitorContractVersion: string | undefined; requestIdHeader: string | undefined;
  body: unknown; presentation: PresentationObservation[]; diagnostic: ReadFailureDiagnostic | null;
}

test.beforeAll(async ({ request }) => {
  const listener = createServer();
  await new Promise<void>(done => listener.listen(0, "127.0.0.1", done));
  const address = listener.address(); if (!address || typeof address === "string") throw new Error("No isolated port");
  base = `http://127.0.0.1:${address.port}`;
  await new Promise<void>(done => listener.close(() => done()));
  server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.explicit_server", "--port", String(address.port), "--monitor-contract-version", "2", "--persistent-risk-tape"], { cwd: repo, windowsHide: true });
  server.stdout?.on("data", value => { serverLog += String(value); }); server.stderr?.on("data", value => { serverLog += String(value); });
  await expect.poll(async () => { try { return (await request.get(`${base}/_test/isolation`)).status(); } catch { return 0; } }, { timeout: 30_000 }).toBe(200);
});

test.afterAll(async ({ request }) => {
  if (server?.exitCode === null) {
    await request.post(`${base}/_test/shutdown`).catch(() => null);
    await Promise.race([new Promise<void>(done => server?.once("exit", () => done())), new Promise<void>(done => setTimeout(done, 10_000))]);
    if (server.exitCode === null) server.kill();
  }
  if (serverLog) console.log(serverLog);
});

test("v2 UI uses real owned runtime and SQLite, preserves source dates and observes an actual stall", async ({ page, request }) => {
  test.setTimeout(240_000); page.setDefaultTimeout(15_000);
  const isolation = await (await request.get(`${base}/_test/isolation`)).json();
  expect(isolation.database).toContain("tpm-r12-browser-"); expect(isolation.provider).toBe("IN_PROCESS_FAKE");
  const evidence = isolation.root;
  const consoleErrors: string[] = []; const pageErrors: string[] = []; const external: string[] = []; const records: unknown[] = []; const sockets: string[] = [];
  let phase = "initial";
  const consoleObservations: { at: number; phase: string; text: string; location: ReturnType<import("@playwright/test").ConsoleMessage["location"]> }[] = [];
  const failedResponses: FailedResponseObservation[] = [];
  const pendingResponses = new Set<Promise<void>>(); const diagnosticErrors: string[] = [];
  await page.addInitScript(() => {
    const trace: PresentationObservation[] = [];
    (window as unknown as { s4PresentationTrace: PresentationObservation[] }).s4PresentationTrace = trace;
    const observe = () => {
      const riskRow = document.querySelector('[data-rule-id="risk-950"]');
      const entry = { at: performance.timeOrigin + performance.now(), path: location.pathname,
        riskPresent: riskRow !== null, riskActionable: riskRow?.getAttribute("data-actionable") === "true",
        withdrawalMessage: document.body?.textContent?.includes("监控快照暂不可用，已撤销当前提醒展示。") ?? false };
      const previous = trace.at(-1);
      if (!previous || previous.path !== entry.path || previous.riskPresent !== entry.riskPresent || previous.riskActionable !== entry.riskActionable || previous.withdrawalMessage !== entry.withdrawalMessage) trace.push(entry);
    };
    new MutationObserver(observe).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-actionable"] });
  });
  const presentationTrace = () => page.evaluate(() => (window as unknown as { s4PresentationTrace: PresentationObservation[] }).s4PresentationTrace);
  page.on("console", msg => { if (["warning", "error"].includes(msg.type())) {
    consoleErrors.push(msg.text()); consoleObservations.push({ at: Date.now(), phase, text: msg.text(), location: msg.location() });
  } });
  page.on("pageerror", err => pageErrors.push(err.message));
  page.on("request", req => { if (new URL(req.url()).origin !== base) external.push(req.url()); });
  page.on("websocket", socket => { sockets.push(socket.url()); });
  page.on("response", response => {
    if (response.status() < 400) return;
    const failure: FailedResponseObservation = { at: Date.now(), phase, url: response.url(), method: response.request().method(), status: response.status(),
      monitorContractVersion: response.headers()["x-monitor-contract-version"], requestIdHeader: response.headers()["x-request-id"], body: null, presentation: [], diagnostic: null };
    failedResponses.push(failure);
    const pending = (async () => {
      failure.body = await response.json();
      const diagnostics = await request.get(`${base}/_test/read-diagnostics`);
      expect(diagnostics.status()).toBe(200);
      failure.diagnostic = ((await diagnostics.json()) as ReadFailureDiagnostic[])
        .find(entry => entry.requestId === failure.requestIdHeader) ?? null;
      // Observe the actual UI after the failed read. This diagnostic records
      // DOM changes only; it does not alter requests, time, or application state.
      await expect.poll(async () => (await presentationTrace()).some(entry => entry.at >= failure.at - 50 && (entry.withdrawalMessage || entry.riskPresent && !entry.riskActionable)), { timeout: 5_000 }).toBe(true);
      failure.presentation = await presentationTrace();
    })().catch(error => { diagnosticErrors.push(String(error)); }).finally(() => { pendingResponses.delete(pending); });
    pendingResponses.add(pending);
  });
  const dashboard = async () => (await request.get(`${base}/api/v1/dashboard`, { headers })).json();
  const runtime = async () => (await request.get(`${base}/api/v1/explicit-plan-runtime/003043.SZ`, { headers })).json();
  try {
    await page.goto(base);
    await expect(page.getByText("没有活动计划。可前往计划工作台核对并启用计划。")).toBeVisible();
    const initial = await dashboard(); records.push({ initial });
    expect(initial.symbols).toHaveLength(0); expect(Object.values(initial.counts)).toEqual([0, 0, 0, 0, 0, 0]);
    expect(initial.runtimeStatus.lifecycle).toBe("RUNNING"); expect(initial.runtimeStatus.coordinator.state).toBe("SCHEDULED");
    await expect(page.getByRole("heading", { name: "部分范围受影响", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "监控状态", exact: true })).toContainText("数据格式不符合监控要求");
    await page.getByRole("link", { name: "查看系统详情", exact: true }).click();
    await expect(page.locator(".runtime-scopes")).toContainText("SEMANTICS_INCOMPATIBLE");
    await page.goto(`${base}/plans`);
    await page.getByLabel("粘贴中文计划原文").fill(literal.sourceText);
    await page.getByRole("button", { name: "生成计划草稿" }).click();
    await page.getByRole("button", { name: "保存并进入逐项复核" }).click();
    const fields = ["启用方式", "启用交易日", "成交量历史范围", "买入重复策略", "卖出重复策略", "风险重复策略", "买卖冲突策略", "风险冲突策略"];
    for (const [index, label] of fields.entries()) await page.getByLabel(label, { exact: true }).fill((Object.values(literal.humanTestSupplements) as string[])[index]!);
    await page.getByRole("button", { name: "保存补充并重新审核" }).click();
    const review = page.locator(".explicit-review");
    await expect(review.getByText("人工补充", { exact: true })).toBeVisible();
    await expect(review.locator('input[type="checkbox"]').first()).toBeVisible();
    for (const check of await review.locator('input[type="checkbox"]').all()) await check.check();
    await page.getByRole("button", { name: "提交当前版本逐项复核" }).click();
    await page.getByTestId("request-activation").click(); await page.locator("#confirm-plan-action").check();
    const activation = page.waitForResponse(response => response.url().endsWith("/plan-activations") && response.request().method() === "POST");
    await page.getByTestId("confirm-plan-action").click();
    const activated = await activation; expect(activated.status()).toBe(200); expect(activated.request().headers()["x-monitor-contract-version"]).toBe("2");
    // Re-enter from committed state before the independent inventory command;
    // activation invalidates the monitor epoch and cancels a concurrent preflight.
    const activePlan = (await dashboard()).symbols.find((row: { symbol: string }) => row.symbol === "003043.SZ");
    await page.goto(`${base}/plans/${activePlan.planVersionId}`);
    await expect(page.getByTestId("request-deactivation")).toBeVisible();
    await expect(page.getByText("● 传输连接正常", { exact: true })).toBeVisible();
    await page.getByLabel("库存登记交易日", { exact: true }).fill("2026-09-14");
    await page.getByLabel("总股数", { exact: true }).fill("100"); await page.getByLabel("可卖股数", { exact: true }).fill("100");
    await page.getByLabel("我确认已完整登记该股票的当前库存").check();
    const inventoryResponse = page.waitForResponse(response => response.url().endsWith("/position-inventory-confirmations") && response.request().method() === "POST");
    await page.getByRole("button", { name: "保存独立库存登记" }).click();
    const inventory = await inventoryResponse; expect(inventory.status()).toBe(200);
    records.push({ inventory: await inventory.json() });
    for (const time of ["10:05", "10:10", "10:15", "10:20", "10:25"]) {
      phase = `market-duty-${time}`;
      expect((await request.post(`${base}/_test/advance`, { data: { now: `2026-09-14T${time}:15+08:00` } })).status()).toBe(200);
      records.push({ checkpoint: `${time}:before-poll`, runtime: await runtime(), dashboard: await dashboard(),
        health: await (await request.get(`${base}/api/v1/health`, { headers })).json() });
      await expect.poll(async () => (await runtime()).summary?.explicitRuntime?.targetBucketEnd, { timeout: 30_000 }).toContain(`${time}:00`);
      records.push({ time, runtime: await runtime(), dashboard: await dashboard() });
    }
    const latest = await runtime();
    const risk = latest.summary.ruleEligibility.find((rule: { action: string }) => rule.action === "RISK_ALERT");
    expect(risk.currentActionable).toBe(true); expect(risk.sourceAlert.evaluatedAt).toContain("10:20:15");
    expect(risk.sourceAlert.resultHash).not.toBe(latest.summary.resultHash);
    phase = "mixed-plan-installation";
    expect((await request.post(`${base}/_test/legacy-sibling`)).status()).toBe(200);
    phase = "market-duty-10:30";
    expect((await request.post(`${base}/_test/advance`, { data: { now: "2026-09-14T10:30:15+08:00" } })).status()).toBe(200);
    await expect.poll(async () => (await dashboard()).symbols.length, { timeout: 30_000 }).toBe(2);
    const mixed = await dashboard(); records.push({ mixed });
    const explicit = mixed.symbols.find((row: { symbol: string }) => row.symbol === "003043.SZ");
    const legacy = mixed.symbols.find((row: { symbol: string }) => row.symbol === "600000.SH");
    expect(explicit.planFamily).toBe("EXPLICIT_RULES"); expect(explicit.availability).toBe("CURRENT");
    expect(legacy.planFamily).toBe("LEGACY_LOW_BUY"); expect(legacy.availability).toBe("UNAVAILABLE");
    expect(legacy.currentActionable).toBe(false);
    await page.goto(base);
    await expect(page.locator('[data-rule-id="risk-950"]')).toHaveAttribute("data-actionable", "true");
    await expect(page.locator('[data-rule-id="risk-950"]')).toContainText("2026-09-14 10:20:15");
    await expect(page.locator('[data-symbol="600000.SH"]')).toContainText("暂无判断");
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: join(evidence, `s4-v2-${width}.png`), fullPage: true });
    }
    await page.evaluate(await readFile(resolve("node_modules/axe-core/axe.min.js"), "utf8"));
    const violations = await page.evaluate(async () => {
      const axe = (window as unknown as { axe: { run(options: unknown): Promise<{ violations: unknown[] }> } }).axe;
      return (await axe.run({ runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } })).violations;
    });
    expect(violations).toEqual([]);
    await page.goto(`${base}/stocks/003043.SZ`);
    await expect(page.getByRole("heading", { name: "历史 K 线与事件" })).toBeVisible();
    await expect(page.locator('[data-rule-id="risk-950"]')).toContainText("2026-09-14 10:20:15");
    await expect.poll(async () => page.locator(".runtime-table tbody tr").count()).toBeGreaterThan(0);
    await page.getByLabel("K线周期", { exact: true }).selectOption("ONE_MINUTE");
    await expect.poll(async () => page.locator(".runtime-table tbody tr").count()).toBeGreaterThan(0);
    await expect(page.getByRole("list", { name: "已提交事件", exact: true })).toContainText("2026-09-14 10:20:15");
    phase = "minute-cutoff-held-35";
    expect((await request.post(`${base}/_test/hold-minute-cutoff`)).status()).toBe(200);
    expect((await request.post(`${base}/_test/advance`, { data: { now: "2026-09-14T10:35:15+08:00" } })).status()).toBe(200);
    await expect.poll(async () => (await runtime()).summary?.availability, { timeout: 30_000 }).toBe("CACHED");
    const cached = await runtime(); records.push({ cached });
    expect(["WAITING", "RECOVERING"]).toContain(cached.summary.scope.status);
    if (cached.summary.scope.progress.requiredCount === null) expect(cached.summary.scope.progress.completedCount).toBeNull();
    else expect(cached.summary.scope.progress.completedCount).toBeLessThan(cached.summary.scope.progress.requiredCount);
    expect(cached.summary.explicitRuntime.targetBucketEnd).toContain("10:30:00");
    expect(cached.summary.ruleEligibility.find((rule: { action: string }) => rule.action === "RISK_ALERT").sourceAlert.dataCutoff).toContain("10:20:00");
    expect(cached.summary.currentActionable).toBe(false);
    await expect(page.getByText("历史缓存；以下结果保留原始周期，不具备当前提醒资格。")).toBeVisible();
    await expect(page.locator('[data-rule-id="risk-950"]')).not.toHaveAttribute("data-actionable", "true");
    await expect(page.locator('[data-rule-id="risk-950"]')).toContainText("2026-09-14 10:20:15");
    await page.screenshot({ path: join(evidence, "s4-v2-cached.png"), fullPage: true });
    phase = "minute-recovery-36";
    expect((await request.post(`${base}/_test/release-minute-cutoff`)).status()).toBe(200);
    expect((await request.post(`${base}/_test/advance`, { data: { now: "2026-09-14T10:36:15+08:00" } })).status()).toBe(200);
    const afterCutoffRelease = await runtime(); records.push({ afterCutoffRelease });
    expect(afterCutoffRelease.summary.availability).toBe("CACHED");
    expect(afterCutoffRelease.summary.explicitRuntime.targetBucketEnd).toContain("10:30:00");
    // The pipeline evaluates completed five-minute deadlines; restored minute
    // collection alone cannot upgrade the previous committed result.
    phase = "recovery-next-market-duty-40";
    expect((await request.post(`${base}/_test/advance`, { data: { now: "2026-09-14T10:40:15+08:00" } })).status()).toBe(200);
    await expect.poll(async () => (await runtime()).summary?.availability, { timeout: 30_000 }).toBe("CURRENT");
    const recovered = await runtime(); records.push({ recoveredAfterFiveMinuteDeadline: recovered });
    expect(recovered.summary.explicitRuntime.targetBucketEnd).toContain("10:40:00");
    await page.goto(`${base}/system`); await expect(page.getByRole("heading", { name: "资源状态" })).toBeVisible();
    phase = "owned-maintenance-stall";
    const stalled = await request.post(`${base}/_test/stall`); expect(stalled.status()).toBe(200);
    await expect(page.getByText("协调器进展已逾期。传输心跳不能恢复当前提醒资格。")).toBeVisible();
    const stalledObservation = await dashboard();
    expect(stalledObservation.runtimeStatus.coordinator.state).toBe("STALLED"); expect(stalledObservation.runtimeStatus.lifecycle).toBe("RUNNING");
    await page.goto(base); await expect(page.locator('[data-rule-id="risk-950"]')).not.toHaveAttribute("data-actionable", "true");
    await expect(page.getByRole("region", { name: "监控状态", exact: true })).toContainText("监控进度未按时更新，当前结果暂不能作为有效提醒。");
    await expect(page.getByRole("region", { name: "监控状态", exact: true })).not.toContainText("资源生命周期");
    await expect(page.getByText("● 传输连接正常", { exact: true })).toBeVisible();
    await page.screenshot({ path: join(evidence, "s4-v2-stalled.png"), fullPage: true });
    await page.waitForTimeout(1000);
    expect((await dashboard()).runtimeStatus.lastProgressAt).toBe(stalledObservation.runtimeStatus.lastProgressAt);
    records.push({ stalled: stalledObservation, later: await dashboard() });
    phase = "owned-maintenance-release-41";
    expect((await request.post(`${base}/_test/release`)).status()).toBe(200);
    await expect.poll(async () => (await dashboard()).runtimeStatus.coordinator.state, { timeout: 30_000 }).toBe("SCHEDULED");
    const afterMaintenanceRelease = await runtime(); records.push({ afterMaintenanceRelease, dashboard: await dashboard() });
    expect(afterMaintenanceRelease.summary.availability).toBe("CACHED");
    expect(afterMaintenanceRelease.summary.explicitRuntime.targetBucketEnd).toContain("10:40:00");
    expect(afterMaintenanceRelease.summary.ruleEligibility.find((rule: { action: string }) => rule.action === "RISK_ALERT").currentActionable).toBe(false);
    await expect(page.locator('[data-rule-id="risk-950"]')).not.toHaveAttribute("data-actionable", "true");
    // The stalled task moved the fixture clock to 41:01. Resume the actual
    // 41:12 minute duty before using minute-sized advances: the latest-minute
    // SDK tape must correspond to the selected duty, not a future minute.
    phase = "post-stall-minute-duty-41";
    expect((await request.post(`${base}/_test/advance`, { data: { now: "2026-09-14T10:41:15+08:00" } })).status()).toBe(200);
    records.push({ afterFirstResumedMinute: await runtime(), dashboard: await dashboard() });
    phase = "next-market-duty-45";
    expect((await request.post(`${base}/_test/advance`, { data: { now: "2026-09-14T10:45:15+08:00" } })).status()).toBe(200);
    await expect.poll(async () => (await runtime()).summary?.availability, { timeout: 30_000 }).toBe("CURRENT");
    const finalCurrent = await runtime(); records.push({ finalCurrent, dashboard: await dashboard() });
    expect(finalCurrent.summary.explicitRuntime.targetBucketEnd).toContain("10:45:00");
    const finalRisk = finalCurrent.summary.ruleEligibility.find((rule: { action: string }) => rule.action === "RISK_ALERT");
    expect(finalRisk.currentActionable).toBe(true); expect(finalRisk.sourceAlert).toEqual(risk.sourceAlert);
    await expect(page.locator('[data-rule-id="risk-950"]')).toHaveAttribute("data-actionable", "true");
    await expect(page.locator('[data-rule-id="risk-950"]')).toContainText("2026-09-14 10:20:15");
    expect(sockets.length).toBeGreaterThan(0); expect(sockets.every(url => new URL(url).searchParams.get("monitorContractVersion") === "2")).toBe(true);
    await Promise.all([...pendingResponses]);
    const permittedBoundaryPhases = ["market-duty-10:05", "market-duty-10:10", "market-duty-10:15", "market-duty-10:20", "market-duty-10:25", "market-duty-10:30", "minute-cutoff-held-35", "minute-recovery-36", "recovery-next-market-duty-40", "owned-maintenance-stall", "owned-maintenance-release-41", "post-stall-minute-duty-41", "next-market-duty-45"];
    for (const failure of failedResponses) {
      expect(failure.status).toBe(503); expect(failure.method).toBe("GET");
      expect(new URL(failure.url).pathname).toBe("/api/v1/dashboard");
      expect(permittedBoundaryPhases).toContain(failure.phase);
      expect(failure.monitorContractVersion).toBe("2"); expect(failure.requestIdHeader).toMatch(/^[0-9a-f]{32}$/);
      expect(failure.body).toEqual({ error: { code: "SERVICE_UNAVAILABLE", message: "Service unavailable", details: [], requestId: failure.requestIdHeader } });
      expect(failure.diagnostic).toEqual({ path: "/api/v1/dashboard", method: "GET", status: 503,
        requestId: failure.requestIdHeader, monitorContractVersion: "2", cause: "BOUNDED_AUTHORITY_RACE",
        causeType: "ProjectionError", causeMessage: "Runtime authority changed during projection" });
      expect(failure.presentation.some(entry => entry.at >= failure.at - 50 && (entry.withdrawalMessage || entry.riskPresent && !entry.riskActionable))).toBe(true);
    }
    const expectedResourceErrors = consoleObservations.filter(entry => entry.text === "Failed to load resource: the server responded with a status of 503 (Service Unavailable)" && failedResponses.some(failure => entry.location.url === failure.url && Math.abs(entry.at - failure.at) < 1_000));
    expect(expectedResourceErrors).toHaveLength(failedResponses.length);
    const unexpectedConsole = consoleObservations.filter(entry => !expectedResourceErrors.includes(entry));
    records.push({ finalPresentation: await presentationTrace(), browserErrorClassification: { expectedResource503: expectedResourceErrors.length, unexpectedConsole } });
    expect(diagnosticErrors).toEqual([]); expect(unexpectedConsole).toEqual([]); expect(pageErrors).toEqual([]); expect(external).toEqual([]);
  } finally {
    await Promise.all([...pendingResponses]);
    records.push({ finalDashboard: await dashboard(), finalRuntime: await runtime(),
      finalHealth: await (await request.get(`${base}/api/v1/health`, { headers })).json() });
    await page.screenshot({ path: join(evidence, "s4-v2-last-page.png"), fullPage: true });
    const finalIsolation = await (await request.get(`${base}/_test/isolation`)).json();
    const readDiagnostics = await (await request.get(`${base}/_test/read-diagnostics`)).json();
    await writeFile(join(evidence, "s4-v2-browser-evidence.json"), JSON.stringify({ isolation, finalIsolation, records, sockets, consoleErrors, consoleObservations, failedResponses, readDiagnostics, diagnosticErrors, pageErrors, external, serverLog }, null, 2));
    console.log(`S4 v2 browser evidence: ${evidence}`);
  }
});
