import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { expect, test } from "./fixtures";

const repo = resolve(process.cwd(), "..");
let base: string;
let server: ChildProcess | undefined;
let log = "";

test.beforeAll(async ({ request }) => {
  const listener = createServer();
  await new Promise<void>(done => listener.listen(0, "127.0.0.1", done));
  const address = listener.address();
  if (!address || typeof address === "string") throw new Error("Missing isolated port");
  const port = address.port;
  await new Promise<void>(done => listener.close(() => done()));
  base = `http://127.0.0.1:${port}`;
  server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.daily_server", "--port", String(port)], { cwd: repo, windowsHide: true });
  server.stdout?.on("data", v => { log += String(v); });
  server.stderr?.on("data", v => { log += String(v); });
  await expect.poll(async () => {
    try { return (await request.get(`${base}/_test/isolation`)).status(); } catch { return 0; }
  }, { timeout: 30000, message: "Offline daily fixture readiness" }).toBe(200);
});

test.afterAll(async ({ request }) => {
  if (server?.exitCode === null) {
    await request.post(`${base}/_test/shutdown`).catch(() => null);
    await Promise.race([new Promise<void>(done => server?.once("exit", () => done())), new Promise<void>(done => setTimeout(done, 5000))]);
    if (server.exitCode === null) server.kill();
  }
  if (log.includes("Traceback")) console.log(log);
});

test("daily review and full simulation preserve T+1, risk timing and one-time consumption in real SQLite", async ({ page, request }, testInfo) => {
  test.setTimeout(120000);
  await page.clock.install({ time: new Date("2026-09-22T10:00:00+08:00") });
  const setup = await (await request.post(`${base}/_test/setup`)).json();
  await page.goto(`${base}/daily-plans`);
  await expect(page.getByRole("heading", { name: "日线交易计划", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toHaveCount(0);
  await page.getByLabel("交易计划原文", { exact: true }).fill(setup.source);
  await page.getByRole("button", { name: "提取日线候选", exact: true }).click();
  await expect(page.locator(".daily-review")).toContainText("technical");
  await expect(page.getByRole("button", { name: "确认当前完整审核" })).toBeDisabled();
  const technical = page.locator("label[for='daily-.ordinary_rules[0].technical']").locator("..");
  await technical.locator(":scope > select").selectOption({ label: "人工核验条件" });
  await technical.getByLabel("核验事实类型", { exact: true }).selectOption({ label: "技术条件核验" });
  await technical.getByLabel("人工证据的明确判定要求", { exact: true }).fill("Synthetic reviewer checks complete official technical evidence");
  await technical.getByLabel("事实适用范围", { exact: true }).selectOption({ label: "TRADE_DATE" });
  await page.getByRole("button", { name: "检查当前参数与来源", exact: true }).click();
  await expect(page.getByRole("button", { name: "检查当前参数与来源", exact: true })).toBeEnabled();
  for (const paths of await page.getByLabel("本句实际对应的技术参数路径（逗号分隔）", { exact: true }).all()) {
    await paths.fill("ordinary_rules[0].technical.evidence_requirement");
  }
  for (const reason of await page.locator(".daily-review textarea").all()) {
    await reason.fill("Synthetic explicit human policy supplement for this exact candidate; independently define and review the displayed value without claiming actual inventory or fills.");
  }
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "人工补充已独立登记" })).toBeVisible();
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  await expect(page.getByRole("button", { name: "确认当前完整审核" })).toBeEnabled();
  await page.getByRole("button", { name: "确认当前完整审核" }).click();
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toBeEnabled();
  await page.locator(".daily-review").screenshot({ path: testInfo.outputPath("daily-review.png") });
  await page.getByRole("button", { name: "启用当前审核绑定" }).click();
  await expect(page.getByRole("status").filter({ hasText: "日线计划已启用" })).toBeVisible();
  await request.post(`${base}/_test/confirm-close`);
  await request.post(`${base}/_test/live`);
  const operations = page.locator(".daily-operations");
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(operations.locator(".daily-signal")).toContainText("2026-09-18");
  await expect(operations.locator(".daily-signal")).toContainText("2026-09-22（当天收盘过期）");
  await operations.getByLabel("选择独立操作").selectOption("POSITION");
  const form = operations.locator("form");
  await form.getByLabel("期初模拟CORE（股）", { exact: true }).fill("100");
  await form.getByLabel("期初模拟TACTICAL（股）", { exact: true }).fill("0");
  const setupResponse = page.waitForResponse(r => r.url().endsWith("/daily-position-confirmations") && r.request().method() === "POST");
  await form.getByRole("button", { name: "确认登记期初模拟仓位", exact: true }).click();
  const initialized = await setupResponse;
  expect(initialized.status(), await initialized.text()).toBe(200);
  expect(Object.keys(initialized.request().postDataJSON()).sort()).toEqual(["coreQty", "expectedRevision", "symbol", "tacticalQty"]);
  await expect(operations.getByRole("status")).toContainText("已记录");
  await request.post(`${base}/_test/live`);
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(operations.locator(".daily-signal")).toContainText("可以模拟交易");
  const readInventory = async () => (await (await request.get(`${base}/api/v1/daily-position-inventory?symbol=601021.SH&asOfTradeDate=2026-09-22`)).json()).snapshot;
  expect((await readInventory()).totalQty).toBe(100); // Reminders alone never buy.
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  expect((await readInventory()).totalQty).toBe(100);
  await expect(operations.getByLabel("选择独立操作").locator("option[value='REPORT']")).toHaveCount(0);
  await expect(operations).not.toContainText("未知占额");
  await expect(operations).not.toContainText("内部扣账");
  await expect(operations.getByLabel("同一外部订单编号", { exact: true })).toHaveCount(0);

  const simulatedPost = page.waitForResponse(r => r.url().endsWith("/daily-simulated-trades") && r.request().method() === "POST");
  await operations.getByRole("button", { name: "确认一次模拟买入100股", exact: true }).click();
  const bought = await simulatedPost;
  expect(bought.status(), await bought.text()).toBe(200);
  const buyReceipt = await bought.json();
  const buyCommand = bought.request().postDataJSON();
  expect(Object.keys(buyCommand).sort()).toEqual(["causeId", "expectedCauseRevision", "expectedInventoryRevision", "planVersionId", "quantity"]);
  expect(buyCommand.quantity).toBe(100);
  expect(buyReceipt.quantity).toBe(100);
  expect(buyReceipt.priceFen).toBe(3970);
  await expect(operations.getByRole("status")).toContainText("已一次完成模拟买入100股");
  await expect(operations.locator(".daily-signal")).toContainText("已完成模拟");
  await expect(operations.locator(".daily-signal")).toContainText("100 / 100股");
  await expect(operations.getByRole("button", { name: "确认一次模拟买入100股", exact: true })).toHaveCount(0);
  const afterBuy = await readInventory();
  expect(afterBuy).toMatchObject({ totalQty: 200, coreQty: 100, tacticalQty: 100, sellableCore: 100, sellableTactical: 0 });
  for (const field of ["orders", "lots", "openingAllocations", "openingBalances", "reservedBuyQty", "unknownQty", "outstandingComplete"]) expect(afterBuy).not.toHaveProperty(field);
  const retry = await request.post(`${base}/api/v1/daily-simulated-trades`, {
    data: buyCommand, headers: { "Idempotency-Key": bought.request().headers()["idempotency-key"]! },
  });
  expect(retry.status(), await retry.text()).toBe(200);
  expect((await retry.json()).simulationId).toBe(buyReceipt.simulationId);
  expect((await readInventory()).totalQty).toBe(200);
  const duplicate = await request.post(`${base}/api/v1/daily-simulated-trades`, { data: buyCommand, headers: { "Idempotency-Key": "different-simulation-retry" } });
  expect(duplicate.status(), await duplicate.text()).toBe(409);
  const odd = await request.post(`${base}/api/v1/daily-simulated-trades`, { data: { ...buyCommand, quantity: 40 }, headers: { "Idempotency-Key": "invalid-odd-simulation" } });
  expect(odd.status(), await odd.text()).toBe(422);
  expect((await readInventory()).totalQty).toBe(200);
  await operations.screenshot({ path: testInfo.outputPath("daily-simulated-buy.png") });

  await operations.getByLabel("选择独立操作").selectOption("FACT");
  await expect(form.getByLabel("核验事实类型", { exact: true }).locator("option")).not.toContainText(["官方基本面证伪"]);
  await request.post(`${base}/_test/risk-close`);
  await page.clock.setFixedTime(new Date("2026-09-22T16:00:00+08:00"));
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  for (const kind of ["严重结构失效", "严重价格量能恶化"]) {
    await form.getByLabel("核验事实类型", { exact: true }).selectOption({ label: kind });
    await form.getByLabel("事实适用交易日", { exact: true }).fill("2026-09-22");
    await form.getByLabel("具体核验证据", { exact: true }).fill("Synthetic complete daily technical failure independently reviewed for this exact simulation");
    await form.getByRole("button", { name: "确认登记人工核验证据", exact: true }).click();
    await expect(form.getByRole("button", { name: "确认登记人工核验证据", exact: true })).toBeEnabled();
  }
  await expect(operations.locator(".daily-runtime")).toContainText("严重技术风险 · 已确认");
  await expect(operations.locator(".daily-runtime")).toContainText("2026-09-23");
  const currentRuntime = async () => (await (await request.get(`${base}/api/v1/daily-plan-runtime/601021.SH`)).json()).snapshot;
  expect((await currentRuntime()).riskAction.status).toBe("WAITING");
  await expect(operations.getByRole("button", { name: /确认一次模拟风险减仓/ })).toHaveCount(0);
  await request.post(`${base}/_test/risk-next-session`);
  await page.clock.setFixedTime(new Date("2026-09-23T10:00:00+08:00"));
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await form.getByLabel("核验事实类型", { exact: true }).selectOption({ label: "当前可交易核验" });
  await form.getByLabel("事实适用交易日", { exact: true }).fill("2026-09-23");
  await form.getByLabel("具体核验证据", { exact: true }).fill("Synthetic next-session official exchange tradability independently reviewed");
  await form.getByRole("button", { name: "填写官方资料核验", exact: true }).click();
  await form.getByLabel("发布机构", { exact: true }).fill("Synthetic official exchange");
  await form.getByLabel("官方资料标题", { exact: true }).fill("Synthetic next-session tradability verification");
  await form.getByLabel("官方资料链接（仅记录，不自动读取）", { exact: true }).fill("https://example.invalid/official-next-session");
  await form.getByLabel("官方发布时间（上海时间）", { exact: true }).fill("2026-09-23T09:58");
  await form.getByLabel("人工核验时间（上海时间）", { exact: true }).fill("2026-09-23T09:59");
  await form.getByLabel("适用于本计划的具体证伪或可交易事实", { exact: true }).fill("Synthetic exchange information verifies current stock tradability without full-session suspension");
  await form.getByRole("button", { name: "确认登记人工核验证据", exact: true }).click();
  await expect(form.getByRole("button", { name: "确认登记人工核验证据", exact: true })).toBeEnabled();
  const nextRiskState = await currentRuntime();
  expect(nextRiskState.riskAction, JSON.stringify({ action: nextRiskState.riskAction, inventory: nextRiskState.inventory, quote: nextRiskState.quote })).toMatchObject({ coreQty: 100, tacticalQty: 100 });
  await expect(operations.locator(".daily-runtime")).toContainText("当前可模拟风险减仓：CORE 100股 / TACTICAL 100股");
  expect((await currentRuntime()).inventory.sellableTactical).toBe(100); // System settles the previous buy on the next exchange session.
  await operations.screenshot({ path: testInfo.outputPath("daily-simulated-risk.png") });
  const riskPost = page.waitForResponse(r => r.url().endsWith("/daily-simulated-trades") && r.request().method() === "POST");
  await operations.getByRole("button", { name: "确认一次模拟风险减仓200股", exact: true }).click();
  const sold = await riskPost;
  expect(sold.status(), await sold.text()).toBe(200);
  expect((await sold.json())).toMatchObject({ side: "SELL", quantity: 200, signalId: null });
  await expect(operations.getByRole("status")).toContainText("已一次完成模拟卖出200股");
  expect((await currentRuntime()).inventory.totalQty).toBe(0);
  await expect(operations.locator(".daily-risk").filter({ hasText: "严重技术风险" })).toContainText("风险退出已完成");
  await request.post(`${base}/_test/expiry`);
  await page.clock.setFixedTime(new Date("2026-09-23T15:00:00+08:00"));
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(operations.locator(".daily-signal")).toContainText("本笔模拟已完成");
  expect((await currentRuntime()).inventory.totalQty).toBe(0);
  await page.getByLabel("交易计划原文", { exact: true }).fill("Edited synthetic source requires a new current source review.");
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toBeDisabled();
  await expect(page.locator(".daily-operations")).toHaveCount(0);
});
