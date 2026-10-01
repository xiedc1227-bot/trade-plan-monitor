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
  const consoleErrors: string[] = [];
  const externalRequests: string[] = [];
  page.on('console', message => { if (['warning', 'error'].includes(message.type())) consoleErrors.push(message.text()); });
  page.on('pageerror', error => consoleErrors.push(error.message));
  page.on('request', req => { if (new URL(req.url()).origin !== base) externalRequests.push(req.url()); });
  const activationState = async () => (await request.get(`${base}/api/v1/plan-activation-states/003043.SZ`)).json();
  const inventory = async () => (await request.get(`${base}/api/v1/position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14`)).json();
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
  const activate = async () => {
    const response = page.waitForResponse(r => r.url().endsWith('/plan-activations') && r.request().method() === 'POST');
    await page.getByTestId('request-activation').click();
    await page.locator('#confirm-plan-action').check();
    await page.getByTestId('confirm-plan-action').click();
    const result = await response;
    records.push({ publicActivationStatus: result.status(), body: await result.json() });
    expect(result.status()).toBe(200);
    await expect(page.getByTestId('request-deactivation')).toBeVisible();
  };
  try {
    expect((await inventory()).status).toBe('UNKNOWN');
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
    await activate();
    let active = original;
    // Separate ordinary inventory registration; source text and activation do not seed it.
    expect((await inventory()).status).toBe('UNKNOWN');
    await page.getByLabel('库存登记交易日', {exact: true}).fill('2026-09-14');
    await page.getByLabel('总股数', {exact: true}).fill('100');
    await page.getByLabel('可卖股数', {exact: true}).fill('100');
    await page.getByLabel('我确认已完整登记该股票的当前库存').check();
    await page.getByRole('button', {name: '保存独立库存登记'}).click();
    await expect.poll(async () => (await inventory()).totalQuantity).toBe(100);

    for (const [path, input, expected] of [
      ['rules[0].condition.conditions[0].low_fen', '9.81', 981],
      ['rules[0].action.quantity', '200', 200],
      ['rules[0].condition', 'ANY', 'ANY'],
      ['rules[0].condition.conditions[0].low_fen', '9.82', 982],
      ['rules[0].action.quantity', '100', 100],
      ['rules[0].condition', 'ALL', 'ALL'],
    ] as const) {
      const before = await latest();
      console.log(`R13 correcting ${path} on version ${before.version}`);
      await page.locator('.explicit-supplement select').selectOption(path);
      await page.getByLabel(`${path} 新值`, {exact: true}).fill(input);
      await expect(page.locator('.explicit-supplement [aria-live="polite"]')).toContainText(`新值 ${input}（人工补充 USER_SUPPLEMENT）`);
      const savedResponse = page.waitForResponse(r => r.url().endsWith('/plan-drafts') && r.request().method() === 'POST');
      await page.getByRole('button', {name: '保存字段修订并重新审核'}).click();
      const saved = await savedResponse;
      records.push({path, saveStatus: saved.status(), body: await saved.json()});
      expect(saved.status(), path).toBe(200);
      await expect.poll(async () => (await latest()).version).toBe(before.version + 1);
      const after = await latest();
      expect(after.sourceText).toBe(literal.sourceText);
      expect(after.sourceHash).toBe(original.sourceHash);
      expect(after.planHash).not.toBe(before.planHash);
      expect(after.contentHash).not.toBe(before.contentHash);
      expect(after.reviewId).toBeNull();
      expect(after.canActivate).toBe(false);
      expect(after.mapping.fieldBindings.find((b: {path: string}) => b.path === path)).toMatchObject({origin: 'USER_SUPPLEMENT', value: expected});
      if (path === 'rules[0].condition') {
        expect(after.mapping.fieldBindings.find((b: {path: string}) => b.path === `${path}.type`)).toMatchObject({origin: 'USER_SUPPLEMENT', value: expected});
        expect(JSON.parse(after.planJson).rules[0].condition.conditions).toEqual(JSON.parse(before.planJson).rules[0].condition.conditions);
      }
      const activation = await activationState();
      const stale = await request.post(`${base}/api/v1/plan-activations`, {
        headers: {'Idempotency-Key': `r13-stale-${after.version}`},
        data: {planVersionId: after.id, reviewId: original.reviewId, contentHash: original.contentHash, expectedRevision: activation.revision},
      });
      records.push({path, staleStatus: stale.status(), after, activation});
      expect(stale.status()).toBe(409);
      expect(activation.planVersionId).toBe(active.id);
      expect(await activationState()).toEqual(activation);
      await page.goto(`${base}/plans/${after.id}`);
      await approve();
      const reviewed = await latest();
      expect(reviewed.reviewId).toBeTruthy();
      expect(reviewed.reviewId).not.toBe(before.reviewId);
      expect(reviewed.contentHash).toBe(after.contentHash);
      expect(reviewed.reviewEvidenceHash).toBe(after.reviewEvidenceHash);
      expect(reviewed.canActivate).toBe(true);
      // Isolate each concurrency/provenance guard while the other two are current.
      for (const [kind, overrides] of [
        ['old-review', {reviewId: before.reviewId}],
        ['old-content', {contentHash: before.contentHash}],
        ['old-revision', {expectedRevision: activation.revision - 1}],
      ] as const) {
        const denied = await request.post(`${base}/api/v1/plan-activations`, {
          headers: {'Idempotency-Key': `r13-${kind}-${after.version}`},
          data: {planVersionId: after.id, reviewId: reviewed.reviewId, contentHash: reviewed.contentHash, expectedRevision: activation.revision, ...overrides},
        });
        records.push({version: after.version, rejectedGuard: kind, status: denied.status()});
        expect(denied.status(), kind).toBe(409);
        expect(await activationState()).toEqual(activation);
      }
      records.push({reviewed});
      if (path === 'rules[0].condition') {
        // ANY is a deliberate replacement of the user's original ALL intent.
        // Its separate runtime result must never satisfy the original literal oracle.
        await activate();
        active = reviewed;
        const activated = await activationState();
        expect(activated.planVersionId).toBe(reviewed.id);
        expect(activated.revision).toBe(activation.revision + 1);
        const time = expected === 'ANY' ? '10:05' : '10:10';
        const quantity = expected === 'ANY' ? 200 : 100;
        const advanced = await request.post(`${base}/_test/advance`, {data: {now: `2026-09-14T${time}:15+08:00`}});
        expect(advanced.status()).toBe(200);
        const runtime = async () => (await request.get(`${base}/api/v1/explicit-plan-runtime/003043.SZ`)).json();
        await expect.poll(async () => (await runtime()).targetBucketEnd, {timeout: 30000}).toContain(`${time}:00`);
        const current = await runtime();
        expect(current.planHash).toBe(reviewed.planHash);
        expect(current.planVersionId).toBe(reviewed.id);
        expect(current.activationRevision).toBe(activated.revision);
        const buy = current.ruleOutcomes.find((rule: {action: string}) => rule.action === 'BUY');
        expect(buy).toMatchObject({conditionCode: expected, outcome: 'SATISFIED'});
        const [price, volume] = buy.conditionEvidence.children;
        expect(price.outcome).toBe('SATISFIED');
        expect(price.facts).toContainEqual({key: 'low_fen', value: expected === 'ANY' ? 981 : 982, unit: 'FEN'});
        expect(volume.outcome).toBe(expected === 'ANY' ? 'UNSATISFIED' : 'SATISFIED');
        expect(volume.facts).toContainEqual({key: 'current_volume_shares', value: expected === 'ANY' ? 299 : 300, unit: 'SHARES'});
        expect(volume.facts).toContainEqual({key: 'sum_volume_shares', value: 1000, unit: 'SHARES'});
        expect(volume.facts).toContainEqual({key: 'mean_volume_shares', value: '200', unit: 'SHARES'});
        await page.getByRole('button', {name: '刷新当前结果'}).click();
        await expect(page.locator('.explicit-runtime')).toContainText(`${time}:00`);
        for (const summary of await page.locator('.explicit-runtime summary').all()) await summary.click();
        const alerts = await (await request.get(`${base}/api/v1/alerts?offset=0&limit=100`)).json();
        const event = alerts.items.find((item: {planVersion: number}) => item.planVersion === reviewed.version);
        expect(event).toMatchObject({signalType: 'BUY', quantity, planHash: reviewed.planHash});
        expect(event.activationRevision).toBe(activated.revision);
        expect(alerts.total).toBe(expected === 'ANY' ? 1 : 2);
        expect((await inventory()).totalQuantity).toBe(100);
        records.push({userChangedOperator: expected, runtime: current, activated, alerts, inventory: await inventory()});
        await page.locator('.explicit-runtime').screenshot({path: join(isolation.root, `r13-runtime-${expected}.png`)});
      }
    }
    await page.locator('.explicit-supplement').screenshot({path: join(isolation.root, 'r13-corrections.png')});
    // A corrected field must be correctable again through the ordinary form.
    const options = await page.locator('.explicit-supplement select option').evaluateAll(nodes => nodes.map(n => (n as HTMLOptionElement).value));
    records.push({editablePathsAfterCorrections: options});
    expect.soft(options).toContain('rules[0].condition.conditions[0].low_fen');
    expect.soft(options).toContain('rules[0].action.quantity');
    expect.soft(options).toContain('rules[0].condition');
    const completed = await latest();
    await page.goto(`${base}/alerts`);
    await expect(page.locator('body')).toContainText('200股');
    await expect(page.locator('body')).toContainText('100股');
    const reminders = await (await request.get(`${base}/api/v1/alerts?offset=0&limit=100`)).json();
    for (const reminder of reminders.items) {
      await page.locator(`[data-acknowledge="${reminder.eventId}"]`).click();
      await expect(page.locator(`[data-acknowledge="${reminder.eventId}"]`)).toContainText('已确认');
    }
    expect((await inventory()).totalQuantity).toBe(100);
    await page.screenshot({path: join(isolation.root, 'r13-correction-alerts.png'), fullPage: true});
    await page.goto(`${base}/plans/${completed.id}`);
    await page.locator('.explicit-supplement select').selectOption('rules[0].condition');
    await page.getByLabel('rules[0].condition 新值', {exact: true}).fill('NOT');
    await page.getByRole('button', {name: '保存字段修订并重新审核'}).click();
    await expect(page.locator('.explicit-supplement [role="alert"]')).toContainText('类型一致');
    expect((await latest()).id).toBe(completed.id);
    expect((await activationState()).planVersionId).toBe(completed.id);
    records.push({unsupportedStructure: 'NOT', rejectedWithoutSuccessor: true, afterAcknowledgement: await inventory()});
    expect(consoleErrors).toEqual([]);
    expect(externalRequests).toEqual([]);
  } finally {
    await writeFile(join(isolation.root, 'r13-corrections.json'), JSON.stringify({isolation: await (await request.get(`${base}/_test/isolation`)).json(), records, consoleErrors, externalRequests}, null, 2));
    console.log(`R13 correction evidence: ${isolation.root}`);
    await page.screenshot({path: join(isolation.root, 'r13-corrections-final.png'), fullPage: true}).catch(() => null);
  }
});
