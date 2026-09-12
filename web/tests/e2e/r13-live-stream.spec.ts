import { spawn, type ChildProcess } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { createServer } from "node:net";
import { expect, test } from "@playwright/test";

let base: string;
const repo = resolve(process.cwd(), "..");
const literal = JSON.parse(await readFile(join(repo, "tests/fixtures/ai/explicit-plan-literal-source-v3.json"), "utf8"));
let server: ChildProcess | undefined;
let serverLog = "";

test.beforeAll(async ({ request }) => {
    const listener = createServer();
    await new Promise<void>((done) => listener.listen(0, "127.0.0.1", done));
    const address = listener.address();
    if (address === null || typeof address === "string") throw new Error("No isolated port");
    const port = address.port;
    await new Promise<void>((done) => listener.close(() => done()));
    base = `http://127.0.0.1:${port}`;
    server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.explicit_server", "--port", String(port)], { cwd: repo, windowsHide: true });
    server.stdout?.on("data", (value) => { serverLog += String(value); });
    server.stderr?.on("data", (value) => { serverLog += String(value); });
  await expect.poll(async () => {
    try { return (await request.get(`${base}/_test/isolation`)).status(); }
    catch { return 0; }
  }, { timeout: 30000, message: "isolated server readiness" }).toBe(200);
});

test.afterAll(async ({ request }) => {
  if (server?.exitCode === null) {
    await request.post(`${base}/_test/shutdown`).catch(() => null);
    await Promise.race([new Promise<void>((done) => server?.once("exit", () => done())), new Promise<void>((done) => setTimeout(done, 10000))]);
    if (server.exitCode === null) server.kill();
  }
  console.log(serverLog);
});

test("R13 real explicit reminders refresh automatically across browser disconnect", async ({ page, request }) => {
  test.setTimeout(180000);
  page.setDefaultTimeout(15000);
  const isolation = await (await request.get(`${base}/_test/isolation`)).json();
  const records: unknown[] = [];
  const latest = async () => {
    const listing = await (await request.get(`${base}/api/v1/plan-versions?offset=0&limit=100`)).json();
    const selected = listing.items.sort((a: {version: number}, b: {version: number}) => b.version - a.version)[0];
    return (await request.get(`${base}/api/v1/plan-versions/${selected.id}`)).json();
  };
  const approve = async () => {
    console.log('R13 approve starting');
    await expect(page.locator('.explicit-review input[type="checkbox"]').first()).toBeVisible();
    const blockedChecks = page.locator('.explicit-review input[type="checkbox"]:disabled');
    records.push({blockedReviewChecks: await blockedChecks.count()});
    expect.soft(await blockedChecks.count(), 'ordinary correction must remain reviewable').toBe(0);
    if (await blockedChecks.count() > 0) return;
    for (const check of await page.locator('.explicit-review input[type="checkbox"]').all()) await check.check();
    const response = page.waitForResponse(r => r.url().endsWith('/plan-review-confirmations') && r.request().method() === 'POST');
    await page.getByRole('button', {name: '提交当前版本逐项复核'}).click();
    const result = await response;
    records.push({reviewStatus: result.status(), body: await result.json()});
    expect(result.status()).toBe(200);
    await expect(page.getByTestId('request-activation')).toBeEnabled();
  };
  try {
    await page.goto(`${base}/plans`);
    await page.getByLabel('粘贴中文计划原文').fill(literal.sourceText);
    await page.getByRole('button', {name: '提交提取审核'}).click();
    await page.getByRole('button', {name: '保存并进入逐项复核'}).click();
    for (const [index, label] of ['启用方式', '启用交易日', '成交量历史范围', '买入重复策略', '卖出重复策略', '风险重复策略', '买卖冲突策略', '风险冲突策略'].entries()) {
      await page.getByLabel(label, {exact: true}).fill((Object.values(literal.humanTestSupplements) as string[])[index]!);
    }
    await page.getByRole('button', {name: '保存补充并重新审核'}).click();
    await expect.poll(async () => (await latest()).version).toBe(2);
    await page.goto(`${base}/plans/${(await latest()).id}`);
    await approve();
    await page.getByTestId('request-activation').click();
    await page.locator('#confirm-plan-action').check();
    await page.getByTestId('confirm-plan-action').click();
    await expect(page.getByTestId('request-deactivation')).toBeVisible();

    await page.getByLabel('库存登记交易日', {exact:true}).fill('2026-09-14');
    await page.getByLabel('总股数', {exact:true}).fill('100');
    await page.getByLabel('可卖股数', {exact:true}).fill('100');
    await page.getByLabel('我确认已完整登记该股票的当前库存').check();
    await page.getByRole('button', {name:'保存独立库存登记'}).click();
    const inventory = async () => (await request.get(`${base}/api/v1/position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14`)).json();
    await expect.poll(async () => (await inventory()).totalQuantity).toBe(100);
    await page.goto(`${base}/alerts`);
    await expect(page.getByRole('heading', {name:'文字提醒中心'})).toBeVisible();
    const visible = page.locator('[data-acknowledge]');
    for (const [time,count] of [['10:05',0],['10:10',1],['10:15',2],['10:20',3]] as const) {
      if (time === '10:15') await page.context().setOffline(true);
      await request.post(`${base}/_test/advance`, {data:{now:`2026-09-14T${time}:15+08:00`}});
      if (time === '10:15') await page.context().setOffline(false);
      const alerts = await (await request.get(`${base}/api/v1/alerts?offset=0&limit=100`)).json();
      records.push({time, alerts});
      expect(alerts.total).toBe(count);
      await expect(visible, `automatic alert visibility at ${time}`).toHaveCount(count, {timeout:20000});
    }
    for (const button of await visible.all()) {
      await button.click();
      await expect(button).toContainText('已确认');
    }
    expect((await inventory()).totalQuantity).toBe(100);
    await page.screenshot({path:join(isolation.root,'r13-stream.png'),fullPage:true});
  } finally {
    await page.context().setOffline(false).catch(() => null);
    await writeFile(join(isolation.root,'r13-stream.json'),JSON.stringify({isolation,records},null,2));
    console.log(`R13 stream evidence: ${isolation.root}`);
    await page.screenshot({path:join(isolation.root,'r13-stream-final.png'),fullPage:true}).catch(() => null);
  }
});
