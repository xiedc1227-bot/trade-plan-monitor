import { spawn, type ChildProcess } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const repo = resolve(process.cwd(), "..");
const literal = JSON.parse(await readFile(join(repo, "tests/fixtures/ai/explicit-plan-literal-source-v3.json"), "utf8"));
const headers = { "X-Monitor-Contract-Version": "2" };

test("normal installed entry preserves reminder source through restart and restores only a new target", async ({ context, request }) => {
  test.setTimeout(150_000);
  const listener = createServer();
  await new Promise<void>(done => listener.listen(0, "127.0.0.1", done));
  const address = listener.address();
  if (!address || typeof address === "string") throw new Error("No isolated loopback port");
  await new Promise<void>(done => listener.close(() => done()));
  const base = `http://127.0.0.1:${address.port}`;
  let child: ChildProcess | undefined;
  let ownedServerPid: number | undefined;
  let page: Page | undefined;
  let root = "";
  let log = "";
  const observations: unknown[] = [];
  const errors: string[] = [];
  const navigationCancellations: { url: string; method: string; error: string }[] = [];
  const external: string[] = [];
  const streams: { type: string; runtimeGeneration?: string; monitorContractVersion?: number; runtimeStatus?: { lifecycle: string; coordinator: { state: string } } }[] = [];
  const read = async (path: string) => {
    const response = await request.get(`${base}${path}`, { headers });
    expect(response.status(), path).toBe(200);
    return response.json();
  };
  const runtime = () => read("/api/v1/explicit-plan-runtime/003043.SZ");
  const start = async (resume = false) => {
    const args = ["-m", "tests.browser.explicit_server", "--port", String(address.port), "--normal-entry"];
    if (resume) args.push("--resume-root", root, "--initial-now", "2026-09-14T10:11:15+08:00");
    child = spawn(join(repo, ".venv/Scripts/python.exe"), args, { cwd: repo, windowsHide: true });
    child.stdout?.on("data", value => { log += String(value); });
    child.stderr?.on("data", value => { log += String(value); });
    await expect.poll(async () => { try { return (await request.get(`${base}/_test/isolation`)).status(); } catch { return 0; } }, { timeout: 30_000 }).toBe(200);
    const isolation = await read("/_test/isolation");
    expect(isolation.entry).toBe("NORMAL_PRODUCTION");
    expect(isolation.provider).toBe("IN_PROCESS_FAKE");
    root = isolation.root;
    ownedServerPid = isolation.pid;
    observations.push({ isolation });
    return isolation;
  };
  const stop = async () => {
    if (!child || child.exitCode !== null) return;
    expect((await request.post(`${base}/_test/shutdown`)).status()).toBe(200);
    // Closed production WebSockets can still await their normal 20s cadence.
    // Keep a bounded drain allowance without changing transport or owner timeouts.
    await expect.poll(() => child?.exitCode, { timeout: 30_000 }).toBe(0);
    ownedServerPid = undefined;
  };
  const open = async (path: string) => {
    page = await context.newPage();
    page.setDefaultTimeout(15_000);
    page.on("console", message => { if (["warning", "error"].includes(message.type())) errors.push(message.text()); });
    page.on("pageerror", error => errors.push(error.message));
    page.on("requestfailed", failure => {
      const error = failure.failure()?.errorText ?? "request failed";
      if (error === "net::ERR_ABORTED" && failure.method() === "GET" && new URL(failure.url()).origin === base && new URL(failure.url()).pathname.startsWith("/api/v1/")) {
        navigationCancellations.push({ url: failure.url(), method: failure.method(), error });
      } else errors.push(`${failure.url()}: ${error}`);
    });
    page.on("request", req => { if (new URL(req.url()).origin !== base) external.push(req.url()); });
    page.on("websocket", socket => {
      expect(new URL(socket.url()).searchParams.get("monitorContractVersion")).toBe("2");
      socket.on("framereceived", frame => { streams.push(JSON.parse(String(frame.payload))); });
    });
    await page.goto(`${base}${path}`);
    return page;
  };
  try {
    const firstProcess = await start();
    const before = await open("/");
    await expect(before.getByRole("region", { name: "监控状态", exact: true })).toBeVisible();
    await expect(before.getByText("没有活动计划。可前往计划工作台核对并启用计划。", { exact: true })).toBeVisible();
    // An idle first entry becomes LIVE on the existing 20s heartbeat cadence.
    await expect(before.getByText("● 传输连接正常", { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(before.getByTestId("market-index-trend-card").locator(".market-index-trend-card__high")).toHaveText("1000.00");
    await before.screenshot({ path: join(root, "normal-overview-no-plans.png"), fullPage: true });
    await before.goto(`${base}/plans`);
    await before.getByLabel("粘贴中文计划原文").fill(literal.sourceText);
    await before.getByRole("button", { name: "提交提取审核" }).click();
    await before.getByRole("button", { name: "保存并进入逐项复核" }).click();
    const labels = ["启用方式", "启用交易日", "成交量历史范围", "买入重复策略", "卖出重复策略", "风险重复策略", "买卖冲突策略", "风险冲突策略"];
    for (const [index, label] of labels.entries()) await before.getByLabel(label, { exact: true }).fill((Object.values(literal.humanTestSupplements) as string[])[index]!);
    await before.getByRole("button", { name: "保存补充并重新审核" }).click();
    const latestPlan = async () => {
      const versions = await read("/api/v1/plan-versions?offset=0&limit=100");
      return versions.items.sort((left: { version: number }, right: { version: number }) => right.version - left.version)[0];
    };
    await expect.poll(async () => (await latestPlan()).version).toBe(2);
    await before.goto(`${base}/plans/${(await latestPlan()).id}`);
    await expect(before.locator('.explicit-review input[type="checkbox"]').first()).toBeVisible();
    for (const check of await before.locator('.explicit-review input[type="checkbox"]').all()) await check.check();
    await before.getByRole("button", { name: "提交当前版本逐项复核" }).click();
    await before.getByTestId("request-activation").click();
    await before.locator("#confirm-plan-action").check();
    await before.getByTestId("confirm-plan-action").click();
    await expect(before.getByTestId("request-deactivation")).toBeVisible();
    await before.goto(`${base}/plans/${(await latestPlan()).id}`);
    await expect(before.getByTestId("request-deactivation")).toBeVisible();
    await before.getByLabel("库存登记交易日", { exact: true }).fill("2026-09-14");
    await before.getByLabel("总股数", { exact: true }).fill("100");
    await before.getByLabel("可卖股数", { exact: true }).fill("100");
    await before.getByLabel("我确认已完整登记该股票的当前库存").check();
    await before.getByRole("button", { name: "保存独立库存登记" }).click();
    await expect.poll(async () => (await read("/api/v1/position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14")).totalQuantity).toBe(100);
    const advance = async (time: string) => {
      expect((await request.post(`${base}/_test/advance`, { data: { now: `2026-09-14T${time}:15+08:00` } })).status()).toBe(200);
    };
    await advance("10:05");
    await advance("10:10");
    observations.push({ firstCommit: await runtime(), health: await read("/api/v1/health") });
    await expect.poll(async () => (await runtime()).summary.availability, { timeout: 30_000 }).toBe("CURRENT");
    const original = await runtime();
    expect(original.summary.explicitRuntime.targetBucketEnd).toContain("10:10:00");
    const alerts = await read("/api/v1/alerts?offset=0&limit=100");
    expect(alerts.total).toBe(1);
    const source = alerts.items[0];
    expect(source.signalType).toBe("BUY");
    const sourceAlert = original.summary.ruleEligibility.find((rule: { ruleId: string }) => rule.ruleId === "buy-100").sourceAlert;
    expect(sourceAlert.eventId).toBe(source.eventId);
    expect(sourceAlert.dataCutoff).toContain("10:10:00");
    const truth = await read("/_test/source-truth");
    const oldGeneration = (await read("/api/v1/dashboard")).runtimeGeneration;
    await before.close();
    await stop();
    const secondProcess = await start(true);
    expect(secondProcess.pid).not.toBe(firstProcess.pid);
    expect(secondProcess.database).toBe(firstProcess.database);
    expect(await read("/_test/source-truth")).toEqual(truth);
    const after = await open("/");
    await expect(after.getByRole("heading", { name: "监控总览" })).toBeVisible();
    await expect(after.getByRole("heading", { name: "主要指数走势 · 当日" })).toBeVisible();
    await expect(after.getByTestId("market-index-selector")).toHaveCount(4);
    await expect(after.getByTestId("market-index-sparkline").locator("canvas")).toBeVisible();
    await after.getByRole("button", { name: /科创50/ }).click();
    await expect(after.getByTestId("market-index-trend-card")).toContainText("000688.SH");
    await expect(after.getByTestId("market-index-health")).toContainText("阻断");
    await expect(after.getByTestId("market-index-sparkline").locator("canvas")).toBeVisible();
    const recovered = await runtime();
    expect(recovered.summary.availability).toBe("CACHED");
    expect(recovered.summary.currentActionable).toBe(false);
    expect(recovered.summary.explicitRuntime.targetBucketEnd).toContain("10:10:00");
    expect(recovered.summary.planHash).toBe(original.summary.planHash);
    expect(recovered.summary.ruleEligibility.find((rule: { ruleId: string }) => rule.ruleId === "buy-100").sourceAlert).toEqual(sourceAlert);
    const newGeneration = (await read("/api/v1/dashboard")).runtimeGeneration;
    expect(newGeneration).not.toBe(oldGeneration);
    await expect(after.getByText("历史缓存；以下结果保留原始周期，不具备当前提醒资格。")).toBeVisible();
    await expect.poll(() => streams.some(frame => frame.type === "heartbeat" && frame.runtimeGeneration === newGeneration && frame.monitorContractVersion === 2 && frame.runtimeStatus?.lifecycle === "RUNNING" && frame.runtimeStatus.coordinator.state === "SCHEDULED"), { timeout: 30_000 }).toBe(true);
    await expect(after.getByTestId("market-index-trend-card").locator(".market-index-trend-card__high")).toHaveText("1000.00");
    const overview = after.getByRole("region", { name: "监控状态", exact: true });
    await expect(overview).toBeVisible();
    await expect(overview).not.toContainText("资源生命周期");
    await expect(overview.locator("details")).toHaveCount(0);
    await after.getByRole("link", { name: "查看系统详情", exact: true }).click();
    await expect(after.getByRole("heading", { name: "系统健康", exact: true })).toBeVisible();
    await expect(after.getByRole("region", { name: "后端运行状态", exact: true })).toContainText("资源生命周期");
    await after.goto(base);
    await expect(after.getByRole("region", { name: "监控状态", exact: true })).toBeVisible();
    for (const width of [320, 768, 1024, 1440]) {
      await after.setViewportSize({ width, height: 900 });
      const overflow = await after.getByRole("region", { name: "监控状态", exact: true }).evaluate(element => element.scrollWidth > element.clientWidth);
      expect(overflow, `overview horizontal overflow at ${width}px`).toBe(false);
    }
    await after.screenshot({ path: join(root, "normal-dashboard-trends.png"), fullPage: true });
    await advance("10:15");
    observations.push({ nextTarget: await runtime(), health: await read("/api/v1/health"), isolation: await read("/_test/isolation") });
    await expect.poll(async () => (await runtime()).summary.availability, { timeout: 30_000 }).toBe("CURRENT");
    const current = await runtime();
    expect(current.summary.explicitRuntime.targetBucketEnd).toContain("10:15:00");
    const finalTruth = await read("/_test/source-truth");
    for (const table of ["active_plan", "plan_activation_state", "plan_version"]) expect(finalTruth[table]).toEqual(truth[table]);
    for (const row of truth.alert_event) expect(finalTruth.alert_event).toContainEqual(row);
    const retained = (await read("/api/v1/alerts?offset=0&limit=100")).items.find((item: { eventId: string }) => item.eventId === source.eventId);
    for (const field of ["eventId", "planHash", "evaluatedAt", "createdAt", "messageText"]) expect(retained[field]).toEqual(source[field]);
    await expect(after.locator('[data-symbol="003043.SZ"]')).toContainText("2026-09-14 10:15");
    observations.push({ original, recovered, current, truth, finalTruth, streams, navigationCancellations });
    expect(errors).toEqual([]);
    expect(external).toEqual([]);
  } catch (error) {
    observations.push({ failure: String(error) });
    throw error;
  } finally {
    await page?.close().catch(() => null);
    try { await stop(); } finally {
      if (ownedServerPid !== undefined) {
        try { process.kill(ownedServerPid, "SIGKILL"); }
        catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
      }
      if (child?.exitCode === null) child.kill();
      if (root) await writeFile(join(root, "normal-runtime-recovery.json"), JSON.stringify({ observations, errors, external, log }, null, 2));
      console.log(`normal runtime recovery evidence: ${root}; server log: ${log.slice(-4000)}`);
    }
  }
});
