import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { expect, test } from "./fixtures";

const repo = resolve(process.cwd(), "..");
const evidence = "Synthetic explicit human policy supplement for this exact candidate; independently define and review the displayed value without claiming actual inventory or fills.";
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
  server = spawn(join(repo, ".venv/Scripts/python.exe"),
    ["-m", "tests.browser.daily_server", "--port", String(port)], { cwd: repo, windowsHide: true });
  server.stdout?.on("data", v => { log += String(v); });
  server.stderr?.on("data", v => { log += String(v); });
  await expect.poll(async () => {
    try { return (await request.get(`${base}/_test/isolation`)).status(); } catch { return 0; }
  }, { timeout: 30000, message: "Offline daily fixture readiness" }).toBe(200);
});

test.afterAll(async ({ request }) => {
  if (server?.exitCode === null) {
    await request.post(`${base}/_test/shutdown`).catch(() => null);
    await Promise.race([new Promise<void>(done => server?.once("exit", () => done())),
      new Promise<void>(done => setTimeout(done, 5000))]);
    if (server.exitCode === null) server.kill();
  }
  if (log.includes("Traceback")) console.log(log);
});

test("two human batches survive a saved-version page reload and activate only the completed review", async ({ page, request }) => {
  test.setTimeout(120000);
  const setup = await (await request.post(`${base}/_test/setup`)).json();
  await page.goto(`${base}/daily-plans`);
  await page.getByLabel("交易计划原文", { exact: true }).fill(setup.source);
  await page.getByRole("button", { name: "提取日线候选", exact: true }).click();
  await expect(page.locator(".daily-review")).toContainText("technical");
  const technical = page.locator("label[for='daily-.ordinary_rules[0].technical']").locator("..");
  await technical.locator(":scope > select").selectOption({ label: "人工核验条件" });
  await technical.getByLabel("核验事实类型", { exact: true }).selectOption({ label: "技术条件核验" });
  await technical.getByLabel("人工证据的明确判定要求", { exact: true }).fill("Synthetic reviewer checks complete official technical evidence");
  await technical.getByLabel("事实适用范围", { exact: true }).selectOption({ label: "TRADE_DATE" });
  await page.getByRole("button", { name: "检查当前参数与来源", exact: true }).click();
  await expect(page.getByRole("button", { name: "检查当前参数与来源", exact: true })).toBeEnabled();

  const reasons = page.locator("textarea[id^='reason-']");
  const total = await reasons.count();
  expect(total).toBeGreaterThan(2);
  const firstCount = Math.floor(total / 2);
  for (let i = 0; i < firstCount; i++) await reasons.nth(i).fill(evidence);
  for (const paths of await page.getByLabel("本句实际对应的技术参数路径（逗号分隔）", { exact: true }).all())
    await paths.fill("ordinary_rules[0].technical.evidence_requirement");
  for (const reason of await page.locator("textarea[id^='clause-']").all()) await reason.fill(evidence);
  const firstPost = page.waitForResponse(r => r.url().endsWith("/daily-plan-review-supplements") && r.request().method() === "POST");
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  const first = await firstPost;
  expect(first.status(), await first.text()).toBe(200);
  expect((await first.json()).revision).toBe(1);
  expect(first.request().postDataJSON().supplements).toHaveLength(firstCount);
  await expect(reasons).toHaveCount(total - firstCount);

  // A saved partial version has a real, user-visible route that survives full page reload.
  const saveResponse = page.waitForResponse(r => r.url().endsWith("/plan-drafts") && r.request().method() === "POST");
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  const partialSave = await saveResponse;
  expect(partialSave.status(), await partialSave.text()).toBe(200);
  const partialVersion = await partialSave.json();
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeDisabled();
  await page.getByRole("link", { name: "打开此版本继续审核（可刷新恢复）", exact: true }).click();
  await expect(page).toHaveURL(`${base}/daily-plans/${partialVersion.id}`);
  await page.reload();
  await expect(page.locator(".daily-review")).toContainText(`已登记人工补充 ${firstCount} 项`);
  await expect(reasons).toHaveCount(total - firstCount);
  for (const reason of await reasons.all()) await reason.fill(evidence);
  const secondPost = page.waitForResponse(r => r.url().endsWith("/daily-plan-review-supplements") && r.request().method() === "POST");
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  const second = await secondPost;
  expect(second.status(), await second.text()).toBe(200);
  expect((await second.json()).revision).toBe(2);
  expect(second.request().postDataJSON().expectedRevision).toBe(1);
  expect(second.request().postDataJSON().supplements).toHaveLength(total);
  await expect(reasons).toHaveCount(0);
  await page.getByRole("button", { name: "检查当前参数与来源", exact: true }).click();
  await expect(page.locator(".daily-review")).toContainText(`已登记人工补充 ${total} 项`);
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "确认当前完整审核", exact: true }).click();
  await expect(page.getByRole("button", { name: "启用当前审核绑定", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "启用当前审核绑定", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "日线计划已启用" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
