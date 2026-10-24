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
  server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.condition_server", "--port", String(address.port), "--linked"], { cwd: repo, windowsHide: true });
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

test("linked plan review, frozen full quantity, P1 block and independent reminder", async ({ page, request }, testInfo) => {
  test.setTimeout(120_000);
  await page.clock.install({ time: new Date("2026-09-22T10:00:00+08:00") });
  const setup = await (await request.post(`${base}/_test/setup`)).json();
  const external: string[] = [];
  page.on("request", req => { if (new URL(req.url()).origin !== base) external.push(req.url()); });
  await page.goto(`${base}/plans`);
  await page.getByLabel("粘贴中文计划原文", { exact: true }).fill(setup.source);
  await page.getByRole("button", { name: "生成计划草稿", exact: true }).click();
  await expect(page.getByRole("heading", { name: "编辑规则、周期与执行窗口" })).toBeVisible();
  await expect(page.locator('[id="daily-.ordinary_rules[0].quantity_policy.base_quantity"]')).toHaveValue("300");
  await expect(page.locator('[id="daily-.ordinary_rules[0].quantity"]')).toHaveCount(0);
  for (const paths of await page.getByLabel("本句实际对应的技术参数路径（逗号分隔）", { exact: true }).all())
    await paths.fill("ordinary_rules[0].quantity_policy.base_quantity");
  for (const textarea of await page.locator(".daily-review textarea").all())
    await textarea.fill("Synthetic independent human verification of every displayed linked policy and expanded condition, Q0 300 and full-capacity blocking; no holdings or trades inferred.");
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "人工补充已独立登记" })).toBeVisible();
  const saving = page.waitForResponse(r => r.url().endsWith("/plan-drafts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  const response = await saving;
  expect(response.status(), await response.text()).toBe(200);
  const saved = await response.json();
  expect(JSON.parse(saved.planJson).schema_version).toBe(6);
  await page.getByRole("button", { name: "确认当前完整审核" }).click();
  await expect(page.getByRole("button", { name: "启用当前审核绑定" })).toBeEnabled();
  await page.getByRole("button", { name: "启用当前审核绑定" }).click();
  await expect(page.getByRole("status").filter({ hasText: "计划已启用" })).toBeVisible();
  const operations = page.locator(".daily-operations");
  await operations.getByLabel("选择独立操作").selectOption("POSITION");
  await operations.getByLabel("期初模拟CORE（股）", { exact: true }).fill("100");
  await operations.getByLabel("期初模拟TACTICAL（股）", { exact: true }).fill("0");
  await operations.getByRole("button", { name: "确认登记期初模拟仓位" }).click();
  await expect(operations.getByRole("status").filter({ hasText: "已记录并更新当前状态" })).toBeVisible();
  const closed = await request.post(`${base}/_test/confirm-close`);
  expect(closed.status(), await closed.text()).toBe(200);
  expect((await closed.json()).snapshot.signals[0].planned_qty).toBe(300);
  await request.post(`${base}/_test/live`);
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(operations.getByRole("region", { name: "大盘联动判断" })).toContainText("正常或过渡");
  await expect(operations.getByText("300 × 1 → 300 股")).toBeVisible();
  await expect(operations.getByRole("button", { name: "确认一次模拟买入300股", exact: true })).toBeEnabled();
  await operations.getByRole("button", { name: "确认一次模拟买入300股", exact: true }).click();
  await expect(operations.getByRole("status").filter({ hasText: "已一次完成模拟买入300股" })).toBeVisible();
  await expect(operations.getByRole("button", { name: "确认一次模拟买入300股", exact: true })).toHaveCount(0);
  const broken = await request.post(`${base}/_test/linked-broken`);
  expect(broken.status(), await broken.text()).toBe(200);
  expect((await broken.json()).snapshot.market_linkage[0].selection.blocker).toBe("P1_EXCEPTION_REQUIRED");
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(operations.getByRole("region", { name: "大盘联动判断" })).toContainText("需要例外授权；当前阶段保持阻断");
  const screenshot = testInfo.outputPath("market-linkage-blocked.png");
  await operations.screenshot({ path: screenshot });
  await testInfo.attach("market-linkage-blocked", { path: screenshot, contentType: "image/png" });
  const reminder = await request.post(`${base}/_test/risk-reminder`);
  expect(reminder.status(), await reminder.text()).toBe(200);
  expect((await reminder.json()).snapshot.alerts[0].outcome).toBe("SATISFIED");
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(operations.getByRole("heading", { name: /风险提醒 five-minute-low-risk/ })).toBeVisible();
  const inventory = await (await request.get(`${base}/api/v1/simulation-position-inventory?symbol=601021.SH&asOfTradeDate=2026-09-22`)).json();
  expect(inventory.snapshot.totalQty).toBe(400);
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  expect(external).toEqual([]);
});
