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
    server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.ai_fault_server", "--port", String(port)], { cwd: repo, windowsHide: true });
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

test("R13 failed AI HTTP responses preserve the previously reviewed active version", async ({ page, request }) => {
  test.setTimeout(180000);
  page.setDefaultTimeout(15000);
  const isolation = await (await request.get(`${base}/_test/isolation`)).json();
  const records: unknown[] = [];
  let command: Record<string, unknown> | undefined;
  page.on('request', r => {
    if (r.method() === 'POST' && r.url().endsWith('/plan-extractions')) command = r.postDataJSON();
  });
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
    await page.getByRole('button', {name: '生成计划草稿'}).click();
    await page.getByRole('button', {name: '保存并进入逐项复核'}).click();
    for (const [index, label] of ['启用方式', '启用交易日', '成交量历史范围', '买入重复策略', '卖出重复策略', '风险重复策略', '买卖冲突策略', '风险冲突策略'].entries()) {
      await page.getByLabel(label, {exact: true}).fill((Object.values(literal.humanTestSupplements) as string[])[index]!);
    }
    await page.getByRole('button', {name: '保存补充并重新审核'}).click();
    await expect.poll(async () => (await latest()).version).toBe(2);
    await page.goto(`${base}/plans/${(await latest()).id}`);
    await approve();
    const original = await latest();
    await page.getByTestId('request-activation').click();
    await page.locator('#confirm-plan-action').check();
    await page.getByTestId('confirm-plan-action').click();
    await expect(page.getByTestId('request-deactivation')).toBeVisible();

    const beforeState = await (await request.get(`${base}/api/v1/plan-activation-states/003043.SZ`)).json();
    const beforeInventory = await (await request.get(`${base}/api/v1/position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14`)).json();
    expect(command).toBeDefined();
    for (const [index, label] of ['invalid-json', 'duplicate-key', 'missing-draft', 'provider-503', 'truncated', 'omitted-risk-rule'].entries()) {
      const submitted = await request.post(`${base}/api/v1/plan-extractions`, {
        headers: {'Idempotency-Key': `r13-failure-${index}`}, data: command,
      });
      expect(submitted.status()).toBe(202);
      const receipt = await submitted.json();
      let result: Record<string, unknown> = {};
      await expect.poll(async () => {
        result = await (await request.get(`${base}/api/v1/plan-extractions/${receipt.operationId}`)).json();
        return result.status;
      }).not.toMatch(/^(QUEUED|RUNNING)$/);
      records.push({label, result});
      expect(result.status).toBe(index === 3 ? 'PROVIDER_ERROR' : 'INVALID_OUTPUT');
      expect(result.draftPlanJson).toBeNull();
      expect(await (await request.get(`${base}/api/v1/plan-activation-states/003043.SZ`)).json()).toEqual(beforeState);
      expect(await (await request.get(`${base}/api/v1/position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14`)).json()).toEqual(beforeInventory);
      expect((await latest()).id).toBe(original.id);
      expect((await latest()).planJson).toBe(original.planJson);
    }
  } finally {
    await writeFile(join(isolation.root, 'r13-faults.json'), JSON.stringify({isolation, records}, null, 2));
    console.log(`R13 fault evidence: ${isolation.root}`);
  }
});
