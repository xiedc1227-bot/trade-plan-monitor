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

test("R13 substantive ordinary corrections require current review and remain editable", async ({ page, request }) => {
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
    const original = await latest();
    await page.getByTestId('request-activation').click();
    await page.locator('#confirm-plan-action').check();
    await page.getByTestId('confirm-plan-action').click();
    await expect(page.getByTestId('request-deactivation')).toBeVisible();

    for (const [path, input, expected] of [
      ['rules[0].condition.conditions[0].low_fen', '9.81', 981],
      ['rules[0].action.quantity', '200', 200],
      ['rules[0].condition', 'ANY', 'ANY'],
    ] as const) {
      const before = await latest();
      console.log(`R13 correcting ${path} on version ${before.version}`);
      await page.locator('.explicit-supplement select').selectOption(path);
      await page.getByLabel(`${path} 新值`, {exact: true}).fill(input);
      const savedResponse = page.waitForResponse(r => r.url().endsWith('/plan-drafts') && r.request().method() === 'POST');
      await page.getByRole('button', {name: '保存字段修订并重新审核'}).click();
      const saved = await savedResponse;
      records.push({path, saveStatus: saved.status(), body: await saved.json()});
      expect(saved.status(), path).toBe(200);
      await expect.poll(async () => (await latest()).version).toBe(before.version + 1);
      const after = await latest();
      expect(after.sourceText).toBe(literal.sourceText);
      expect(after.contentHash).not.toBe(before.contentHash);
      expect(after.reviewId).toBeNull();
      expect(after.canActivate).toBe(false);
      expect(after.mapping.fieldBindings.find((b: {path: string}) => b.path === path)).toMatchObject({origin: 'USER_SUPPLEMENT', value: expected});
      const activation = await (await request.get(`${base}/api/v1/plan-activation-states/003043.SZ`)).json();
      const stale = await request.post(`${base}/api/v1/plan-activations`, {
        headers: {'Idempotency-Key': `r13-stale-${after.version}`},
        data: {planVersionId: after.id, reviewId: original.reviewId, contentHash: original.contentHash, expectedRevision: activation.revision},
      });
      records.push({path, staleStatus: stale.status(), after, activation});
      expect(stale.status()).toBe(409);
      expect(activation.planVersionId).toBe(original.id);
      await page.goto(`${base}/plans/${after.id}`);
      await approve();
    }
    await page.locator('.explicit-supplement').screenshot({path: join(isolation.root, 'r13-corrections.png')});
    // A corrected field must be correctable again through the ordinary form.
    const options = await page.locator('.explicit-supplement select option').evaluateAll(nodes => nodes.map(n => (n as HTMLOptionElement).value));
    records.push({editablePathsAfterCorrections: options});
    expect.soft(options).toContain('rules[0].condition.conditions[0].low_fen');
    expect.soft(options).toContain('rules[0].action.quantity');
    expect.soft(options).toContain('rules[0].condition');
  } finally {
    await writeFile(join(isolation.root, 'r13-corrections.json'), JSON.stringify({isolation, records}, null, 2));
    console.log(`R13 correction evidence: ${isolation.root}`);
    await page.screenshot({path: join(isolation.root, 'r13-corrections-final.png'), fullPage: true}).catch(() => null);
  }
});
