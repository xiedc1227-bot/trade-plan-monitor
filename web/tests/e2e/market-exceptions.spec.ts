import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { expect, test } from "./fixtures";

const repo = resolve(process.cwd(), "..");
let base: string;
let server: ChildProcess | undefined;
let log = "";

for (const route of ["WEAK_MINIMUM", "BROKEN_STRONG"] as const) {
for (const scenario of ["consume", "revoke", "reject", "correction"] as const) {
test.describe(`${route} ${scenario}`, () => {
test.beforeAll(async ({ request }) => {
  const listener = createServer();
  await new Promise<void>(done => listener.listen(0, "127.0.0.1", done));
  const address = listener.address();
  if (!address || typeof address === "string") throw new Error("Missing isolated port");
  await new Promise<void>(done => listener.close(() => done()));
  base = `http://127.0.0.1:${address.port}`;
  server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.condition_server", "--port", String(address.port), "--exception", route], { cwd: repo, windowsHide: true });
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

test("source review, explicit occurrence approval and separate whole execution", async ({ page, request }, testInfo) => {
  test.setTimeout(120_000);
  await page.clock.install({ time: new Date("2026-09-22T10:00:00+08:00") });
  const setup = await (await request.post(`${base}/_test/setup`)).json();
  const external: string[] = [];
  page.on("request", req => { if (new URL(req.url()).origin !== base) external.push(req.url()); });
  await page.goto(`${base}/plans`);
  await expect(page.getByLabel("粘贴中文计划原文", { exact: true })).toBeEnabled();
  page.on("response", async response => {
    if (response.url().includes("/plan-extractions/")) {
      const body = await response.json();
      if (body.status === "INVALID_OUTPUT") console.log("Invalid synthetic extraction", JSON.stringify(body));
    }
  });
  await page.getByLabel("粘贴中文计划原文", { exact: true }).fill(setup.source);
  await page.getByRole("button", { name: "生成计划草稿", exact: true }).click();
  await expect(page.getByRole("heading", { name: "编辑规则、周期与执行窗口" })).toBeVisible();
  await expect(page.getByRole("region", { name: "例外路径的计划许可" })).toContainText("批准不执行模拟交易");
  for (const paths of await page.getByLabel("本句实际对应的技术参数路径（逗号分隔）", { exact: true }).all())
    await paths.fill("ordinary_rules[0].quantity_policy.base_quantity");
  for (const textarea of await page.locator(".daily-review textarea").all())
    await textarea.fill(`Synthetic independent human verification: ${setup.source}`);
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "人工补充已独立登记" })).toBeVisible();
  const saving = page.waitForResponse(r => r.url().endsWith("/plan-drafts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  const response = await saving;
  expect(response.status(), await response.text()).toBe(200);
  const saved = await response.json();
  expect(JSON.parse(saved.planJson).schema_version).toBe(7);
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
  const pending = await closed.json();
  expect(pending.snapshot.signals).toEqual([]);
  expect(pending.snapshot.exception_candidates[0].candidate.state).toBe("PENDING");
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  const candidate = page.locator(".exception-approval");
  await expect(candidate).toContainText("等待逐次审核");
  if (scenario === "reject") {
    await candidate.getByLabel("本次决定的具体理由（必填）").fill("明确拒绝本次申请");
    await candidate.getByRole("button", { name: "拒绝本次申请" }).click();
    await expect(candidate).toContainText("已拒绝");
    await page.goto(`${base}/plans/${saved.id}`);
    await expect(candidate).toContainText("不能重新批准");
    await expect(candidate.getByRole("button")).toHaveCount(0);
    return;
  }
  if (route === "BROKEN_STRONG") {
    await expect(candidate.getByRole("spinbutton")).toHaveValue("");
    await expect(candidate.getByRole("button", { name: "生成本次精确预览" })).toBeDisabled();
    await candidate.getByRole("spinbutton").fill("300");
  } else {
    await expect(candidate.getByRole("spinbutton")).toHaveCount(0);
    await expect(candidate).toContainText("固定申请量：100 股");
  }
  await candidate.getByRole("button", { name: "生成本次精确预览" }).click();
  const quantity = route === "WEAK_MINIMUM" ? 100 : 300;
  await expect(candidate).toContainText(`本次精确批准量：${quantity} 股`);
  if (scenario === "correction") {
    const corrected = await request.post(`${base}/_test/exception-correction`);
    expect(corrected.status(), await corrected.text()).toBe(200);
    await operations.getByRole("button", { name: "刷新当前状态" }).click();
    await expect(candidate).toContainText("依据已失效");
    await expect(candidate.getByRole("button")).toHaveCount(0);
    await expect(operations.getByRole("button", { name: `确认一次模拟买入${quantity}股` })).toHaveCount(0);
    return;
  }
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(candidate.getByRole("button", { name: `批准本次${quantity}股` })).toHaveCount(0);
  await candidate.getByRole("button", { name: "生成本次精确预览" }).click();
  await expect(candidate).toContainText(`本次精确批准量：${quantity} 股`);
  await candidate.getByLabel("本次决定的具体理由（必填）").fill("已逐项核对本次市场、相对强势、确认组和整笔容量");
  await candidate.getByRole("button", { name: `批准本次${quantity}股` }).focus();
  await page.keyboard.press("Enter");
  await expect(candidate).toContainText("已批准，数量已冻结");
  const inventory = () => request.get(`${base}/api/v1/simulation-position-inventory?symbol=601021.SH&asOfTradeDate=2026-09-22`).then(r => r.json());
  expect((await inventory()).snapshot.totalQty).toBe(100);
  if (scenario === "revoke") {
    await candidate.getByLabel("本次决定的具体理由（必填）").fill("撤销本次批准，不执行模拟交易");
    await candidate.getByRole("button", { name: "撤销本次批准" }).click();
    await expect(candidate).toContainText("已撤销");
    await page.goto(`${base}/plans/${saved.id}`);
    await expect(candidate).toContainText("不能重新批准");
    await expect(candidate.getByRole("button")).toHaveCount(0);
    expect((await inventory()).snapshot.totalQty).toBe(100);
    return;
  }
  await page.goto(`${base}/plans/${saved.id}`);
  await expect(page.locator(".exception-approval")).toContainText(`已冻结：${quantity} 股`);
  await request.post(`${base}/_test/live`);
  await operations.getByRole("button", { name: "刷新当前状态" }).click();
  await expect(operations.getByRole("button", { name: `确认一次模拟买入${quantity}股`, exact: true })).toBeEnabled();
  const screenshot = testInfo.outputPath(`exception-${route}.png`);
  await operations.screenshot({ path: screenshot });
  await testInfo.attach("exception-approved", { path: screenshot, contentType: "image/png" });
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    const overflow = await page.evaluate(() => Array.from(document.querySelectorAll("body *"))
      .filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 12).map(e => `${e.tagName}.${e.className}: ${e.getBoundingClientRect().right}`));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${width}: ${overflow.join('; ')}`).toBe(true);
  }
  await operations.getByRole("button", { name: `确认一次模拟买入${quantity}股`, exact: true }).click();
  await expect(operations.getByRole("status").filter({ hasText: `已一次完成模拟买入${quantity}股` })).toBeVisible();
  expect((await inventory()).snapshot.totalQty).toBe(100 + quantity);
  await expect(candidate).toContainText("已消耗");
  await expect(candidate.getByRole("button")).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".exception-approval")).toContainText("不能重新批准");
  expect((await inventory()).snapshot.totalQty).toBe(100 + quantity);
  expect(external).toEqual([]);
});

});
}
}
