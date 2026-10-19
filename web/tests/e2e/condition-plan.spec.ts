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
  await new Promise<void>(done => listener.close(() => done()));
  base = `http://127.0.0.1:${address.port}`;
  server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.condition_server", "--port", String(address.port)], { cwd: repo, windowsHide: true });
  server.stdout?.on("data", value => { log += String(value); });
  server.stderr?.on("data", value => { log += String(value); });
  await expect.poll(async () => { try { return (await request.get(`${base}/_test/isolation`)).status(); } catch { return 0; } },
    { timeout: 30_000, message: "Offline condition fixture readiness" }).toBe(200);
});

test.afterAll(async ({ request }) => {
  if (server?.exitCode === null) {
    await request.post(`${base}/_test/shutdown`).catch(() => null);
    await Promise.race([new Promise<void>(done => server?.once("exit", () => done())), new Promise<void>(done => setTimeout(done, 5000))]);
    if (server.exitCode === null) server.kill();
  }
  if (log.includes("Traceback")) console.log(log);
});

test("one production workspace extracts, edits mixed periods, reviews, explicitly enables and simulates once in SQLite", async ({ page, request }, testInfo) => {
  test.setTimeout(120_000);
  await page.clock.install({ time: new Date("2026-09-22T10:00:00+08:00") });
  const setup = await (await request.post(`${base}/_test/setup`)).json();
  const external: string[] = [];
  page.on("request", req => { if (new URL(req.url()).origin !== base) external.push(req.url()); });
  await page.goto(`${base}/plans`);
  await expect(page.getByRole("heading", { name: "计划工作台", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "日线计划", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toHaveCount(0);
  await page.getByLabel("粘贴中文计划原文", { exact: true }).fill(setup.source);
  await page.getByRole("region", { name: "交易计划原文" }).screenshot({ path: testInfo.outputPath("condition-plan-raw-source.png") });
  await page.getByRole("button", { name: "生成计划草稿", exact: true }).click();
  await expect(page.getByRole("heading", { name: "编辑规则、周期与执行窗口" })).toBeVisible();
  await expect(page.locator(".daily-review")).toContainText("基本面由用户在生成计划时审核");
  // Both period leaves are edited through the generated structured form.
  await page.locator('[id="daily-.ordinary_rules[0].condition.conditions[1].price_fen"]').fill("4001");
  await page.locator('[id="daily-.ordinary_rules[0].condition.conditions[0].reference.value"]').fill("4001");
  await page.getByRole("button", { name: "检查当前参数与来源", exact: true }).click();
  await expect(page.getByRole("button", { name: "检查当前参数与来源", exact: true })).toBeEnabled();
  for (const paths of await page.getByLabel("本句实际对应的技术参数路径（逗号分隔）", { exact: true }).all())
    await paths.fill("ordinary_rules[0].condition.conditions[0].reference.value,ordinary_rules[0].condition.conditions[1].price_fen");
  for (const textarea of await page.locator(".daily-review textarea").all())
    await textarea.fill("Synthetic explicit human policy for this exact mixed condition candidate; independently confirm the displayed daily and five-minute definitions without asserting holdings or fills.");
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "人工补充已独立登记" })).toBeVisible();
  await page.locator(".daily-review").screenshot({ path: testInfo.outputPath("condition-plan-source-review.png") });
  const savePost = page.waitForResponse(r => r.url().endsWith("/plan-drafts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  const savedResponse = await savePost;
  expect(savedResponse.status(), await savedResponse.text()).toBe(200);
  const saved = await savedResponse.json();
  expect(saved.canActivate).toBe(false);
  const document = JSON.parse(saved.planJson);
  expect(document.schema_version).toBe(5);
  expect(document.ordinary_rules[0].validity).toEqual({ mode: "PLAN_ACTIVE" });
  await expect(page.locator('[id="daily-.ordinary_rules[0].validity"]')).toHaveValue("0");
  await expect(page.locator('[id="daily-.ordinary_rules[0].validity.end_date"]')).toHaveCount(0);
  expect(document.ordinary_rules[0].condition.conditions.map((leaf: { type: string }) => leaf.type)).toEqual(["DAILY_PRICE_COMPARE", "MINUTE_CLOSE_BELOW"]);
  expect(document.alert_rules).toMatchObject([{ kind: "RISK_ALERT", rule_id: "five-minute-low-risk",
    condition: { type: "MINUTE_CLOSE_BELOW", price_fen: 950 } }]);
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toBeDisabled();
  await page.getByRole("link", { name: "打开此版本继续审核（可刷新恢复）" }).click();
  await expect(page).toHaveURL(`${base}/plans/${saved.id}`);
  await page.reload();
  await expect(page.getByRole("button", { name: "确认当前完整审核" })).toBeEnabled();
  await page.getByRole("button", { name: "确认当前完整审核" }).click();
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toBeEnabled();
  expect((await (await request.get(`${base}/api/v1/plan-activation-states/601021.SH`)).json()).active).toBe(false);
  await page.getByRole("button", { name: "启用当前审核绑定" }).click();
  await expect(page.getByRole("status").filter({ hasText: "计划已启用" })).toBeVisible();
  const operations = page.locator(".daily-operations");
  await operations.getByLabel("选择独立操作").selectOption("POSITION");
  const form = operations.locator("form");
  await form.getByLabel("期初模拟CORE（股）", { exact: true }).fill("100");
  await form.getByLabel("期初模拟TACTICAL（股）", { exact: true }).fill("0");
  const openingPost = page.waitForResponse(r => r.url().endsWith("/simulation-position-confirmations") && r.request().method() === "POST");
  await form.getByRole("button", { name: "确认登记期初模拟仓位" }).click();
  const opening = await openingPost;
  expect(opening.status(), await opening.text()).toBe(200);
  await expect(operations.getByRole("status").filter({ hasText: "已记录并更新当前状态" })).toBeVisible();
  const evaluated = await request.post(`${base}/_test/live`);
  expect(evaluated.status(), await evaluated.text()).toBe(200);
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  const inventory = async () => (await (await request.get(`${base}/api/v1/simulation-position-inventory?symbol=601021.SH&asOfTradeDate=2026-09-22`)).json()).snapshot;
  expect((await inventory()).totalQty).toBe(100);
  await expect(operations.getByRole("heading", { name: /风险提醒 five-minute-low-risk/ })).toBeVisible();
  await expect(operations.getByText("这些规则只产生提醒，不创建模拟交易，也不改变模拟仓位。")).toBeVisible();
  await expect(operations.getByRole("button", { name: "确认一次模拟买入100股", exact: true })).toBeEnabled();
  const simulation = page.waitForResponse(r => r.url().endsWith("/simulated-trades") && r.request().method() === "POST");
  await operations.getByRole("button", { name: "确认一次模拟买入100股", exact: true }).click();
  const traded = await simulation;
  expect(traded.status(), await traded.text()).toBe(200);
  const receipt = await traded.json();
  expect(receipt).toMatchObject({ side: "BUY", quantity: 100, priceFen: 3970 });
  await expect(operations.getByRole("button", { name: "确认一次模拟买入100股", exact: true })).toHaveCount(0);
  expect(await inventory()).toMatchObject({ totalQty: 200, coreQty: 100, tacticalQty: 100, sellableTactical: 0 });
  const replay = await request.post(`${base}/api/v1/simulated-trades`, { data: traded.request().postDataJSON(), headers: { "Idempotency-Key": traded.request().headers()["idempotency-key"]! } });
  expect(replay.status(), await replay.text()).toBe(200);
  expect((await replay.json()).simulationId).toBe(receipt.simulationId);
  expect((await inventory()).totalQty).toBe(200);
  await operations.screenshot({ path: testInfo.outputPath("condition-plan-simulation.png") });
  const reminderResponse = await request.post(`${base}/_test/risk-reminder`);
  expect(reminderResponse.status(), await reminderResponse.text()).toBe(200);
  const reminderCycle = await reminderResponse.json();
  expect(reminderCycle.snapshot.alerts).toMatchObject([{ rule_id: "five-minute-low-risk", alert_kind: "RISK_ALERT", outcome: "SATISFIED" }]);
  expect(reminderCycle.event_ids).toHaveLength(1);
  await page.goto(`${base}/alerts`);
  await expect(page.getByRole("heading", { name: "提醒历史" })).toBeVisible();
  await expect(page.locator("[data-risk-reminder]")).toBeVisible();
  await page.getByLabel("信号类型").selectOption("RISK_ALERT");
  const filteredResponse = page.waitForResponse(r => r.url().includes("/api/v1/alerts?") && r.url().includes("signalType=RISK_ALERT"));
  await page.getByRole("button", { name: "查询" }).click();
  const filtered = await filteredResponse;
  expect(filtered.status(), await filtered.text()).toBe(200);
  const filteredPage = await filtered.json();
  expect(filteredPage.items).toHaveLength(1);
  expect(filteredPage.items[0]).toMatchObject({ signalType: "REMINDER", alertKind: "RISK_ALERT", quantity: null,
    simulatedQty: 0, riskScope: null, executionDate: null, nextStep: "REVIEW_ALERT", severity: "RISK" });
  const reminderRow = page.locator(`[data-alert-id="${filteredPage.items[0].eventId}"]`);
  await expect(reminderRow.locator("[data-risk-reminder]")).toContainText("不改变模拟仓位");
  await expect(reminderRow.locator("[data-trade-registration]")).toHaveCount(0);
  await reminderRow.getByRole("button", { name: "查看证据" }).click();
  await expect(page.getByRole("heading", { name: "仅提醒的风险条件" })).toBeVisible();
  await expect(page.getByText("生成提醒时数量")).toHaveCount(0);
  const acknowledgement = page.waitForResponse(r => r.url().endsWith("/alert-acknowledgements") && r.request().method() === "POST");
  await reminderRow.getByRole("button", { name: "确认已查看（不代表成交）" }).click();
  const acknowledged = await acknowledgement;
  expect(acknowledged.status(), await acknowledged.text()).toBe(200);
  await expect(reminderRow).toContainText("已确认；确认提醒不代表成交");
  expect((await inventory()).totalQty).toBe(200);
  await reminderRow.locator("[data-daily-plan]").click();
  await expect(page).toHaveURL(`${base}/plans/${saved.id}`);
  await page.getByRole("button", { name: "停用当前计划", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "当前计划已停用" })).toBeVisible();
  expect((await (await request.get(`${base}/api/v1/plan-activation-states/601021.SH`)).json()).active).toBe(false);
  await page.getByLabel("粘贴中文计划原文", { exact: true }).fill("Edited source requires a fresh exact review.");
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toBeDisabled();
  await expect(operations).toHaveCount(0);
  expect(external).toEqual([]);
});
