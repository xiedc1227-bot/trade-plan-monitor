import { spawn, type ChildProcess } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { join, resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const repo = resolve(process.cwd(), '..');
const literal = JSON.parse(await readFile(join(repo, 'tests/fixtures/ai/explicit-plan-literal-source-v3.json'), 'utf8'));

for (const transition of ['active', 'replace', 'disable', 'expire'] as const) {
  test(`R13 real OS restart retains ${transition} plan and durable reminder identity`, async ({ context, request }) => {
    test.setTimeout(180000);
    const listener = createServer();
    await new Promise<void>(done => listener.listen(0, '127.0.0.1', done));
    const address = listener.address();
    if (!address || typeof address === 'string') throw new Error('No isolated port');
    const port = address.port;
    await new Promise<void>(done => listener.close(() => done()));
    const base = `http://127.0.0.1:${port}`;
    let server: ChildProcess | undefined;
    let serverPid: number | undefined;
    let root = '';
    let log = '';
    let page: Page | undefined;
    const records: unknown[] = [];
    const consoleErrors: string[] = [];
    const externalRequests: string[] = [];
    const read = async (path: string) => {
      const response = await request.get(`${base}${path}`);
      expect(response.status(), path).toBe(200);
      return response.json();
    };
    const inventory = () => read('/api/v1/position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14');
    const alerts = () => read('/api/v1/alerts?offset=0&limit=100');
    const activation = () => read('/api/v1/plan-activation-states/003043.SZ');
    const latest = async () => {
      const list = await read('/api/v1/plan-versions?offset=0&limit=100');
      const item = list.items.sort((a: {version: number}, b: {version: number}) => b.version - a.version)[0];
      return read(`/api/v1/plan-versions/${item.id}`);
    };
    const start = async (now?: string) => {
      const args = ['-m', 'tests.browser.explicit_server', '--port', String(port), '--repeat-probe-tape'];
      if (now) args.push('--resume-root', root, '--initial-now', now);
      server = spawn(join(repo, '.venv/Scripts/python.exe'), args, { cwd: repo, windowsHide: true });
      server.stdout?.on('data', value => { log += String(value); });
      server.stderr?.on('data', value => { log += String(value); });
      await expect.poll(async () => {
        try { return (await request.get(`${base}/_test/isolation`)).status(); }
        catch { return 0; }
      }, { timeout: 30000 }).toBe(200);
      const isolation = await read('/_test/isolation');
      serverPid = isolation.pid;
      root = isolation.root;
      expect(isolation.provider).toBe('IN_PROCESS_FAKE');
      records.push({ process: isolation });
      return isolation;
    };
    const stop = async () => {
      if (serverPid !== undefined) {
        const ownedPid = serverPid;
        // Windows venv Python has a launcher and a separate Uvicorn process.
        // Terminate the server PID reported by our own isolated endpoint.
        try { process.kill(ownedPid, 'SIGKILL'); }
        catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error; }
        await expect.poll(() => {
          try { process.kill(ownedPid, 0); return false; }
          catch (error) { if ((error as NodeJS.ErrnoException).code === 'ESRCH') return true; throw error; }
        }, {timeout: 5000}).toBe(true);
        await expect.poll(() => server?.exitCode !== null || server?.signalCode !== null, {timeout: 5000}).toBe(true);
        records.push({terminatedOwnedPid: ownedPid, serverExited: true, launcherExitCode: server?.exitCode, launcherSignalCode: server?.signalCode});
        serverPid = undefined;
      }
    };
    const open = async (path: string) => {
      page = await context.newPage();
      page.setDefaultTimeout(15000);
      page.on('console', message => { if (['warning', 'error'].includes(message.type())) consoleErrors.push(message.text()); });
      page.on('pageerror', error => consoleErrors.push(error.message));
      page.on('request', req => { if (new URL(req.url()).origin !== base) externalRequests.push(req.url()); });
      await page.goto(`${base}${path}`);
      return page;
    };
    const advance = async (time: string) => {
      const now = `2026-09-14T${time}:15+08:00`;
      expect((await request.post(`${base}/_test/advance`, { data: { now } })).status()).toBe(200);
      const runtime = await request.get(`${base}/api/v1/explicit-plan-runtime/003043.SZ`);
      expect(runtime.status()).toBe(transition === 'disable' && time !== '10:10' ? 404 : 200);
      records.push({ checkpoint: time, runtimeStatus: runtime.status(), runtime: await runtime.json(), alerts: await alerts(), inventory: await inventory() });
    };
    try {
      const firstProcess = await start();
      expect(firstProcess.resumed).toBe(false);
      expect((await read('/api/v1/plan-versions?offset=0&limit=100')).total).toBe(0);
      expect((await inventory()).status).toBe('UNKNOWN');
      const before = await open('/plans');
      await before.getByLabel('粘贴中文计划原文').fill(literal.sourceText);
      await before.getByRole('button', {name: '生成计划草稿'}).click();
      await before.getByRole('button', {name: '保存并进入逐项复核'}).click();
      const labels = ['启用方式', '启用交易日', '成交量历史范围', '买入重复策略', '卖出重复策略', '风险重复策略', '买卖冲突策略', '风险冲突策略'];
      const values = Object.values(literal.humanTestSupplements) as string[];
      for (const [index, label] of labels.entries()) {
        // Deliberately independent user choice: each qualifying bar can remind.
        await before.getByLabel(label, {exact: true}).fill(index >= 3 && index <= 5 ? 'EACH_QUALIFYING_BAR' : values[index]!);
      }
      await before.getByRole('button', {name: '保存补充并重新审核'}).click();
      await expect.poll(async () => (await latest()).version).toBe(2);
      await before.goto(`${base}/plans/${(await latest()).id}`);
      await approveAndActivate(before);
      const original = await latest();
      expect(original.sourceText).toBe(literal.sourceText);
      expect(JSON.parse(original.planJson).rules.map((r: {repeat_policy: {mode: string}}) => r.repeat_policy.mode)).toEqual(Array(3).fill('EACH_QUALIFYING_BAR'));
      expect((await inventory()).status).toBe('UNKNOWN');
      await before.getByLabel('库存登记交易日', {exact: true}).fill('2026-09-14');
      await before.getByLabel('总股数', {exact: true}).fill('100');
      await before.getByLabel('可卖股数', {exact: true}).fill('100');
      await before.getByLabel('我确认已完整登记该股票的当前库存').check();
      await before.getByRole('button', {name: '保存独立库存登记'}).click();
      await expect.poll(async () => (await inventory()).totalQuantity).toBe(100);
      await advance('10:10');
      await expect.poll(async () => (await alerts()).total).toBe(1);
      const initialEvent = (await alerts()).items[0];
      expect(initialEvent).toMatchObject({signalType: 'BUY', quantity: 100, planVersion: 2});
      await before.goto(`${base}/alerts`);
      await expect(before.locator(`[data-acknowledge="${initialEvent.eventId}"]`)).toBeVisible();
      await before.locator(`[data-acknowledge="${initialEvent.eventId}"]`).click();
      await expect(before.locator(`[data-acknowledge="${initialEvent.eventId}"]`)).toContainText('已确认');
      await before.screenshot({path: join(root, 'restart-before.png'), fullPage: true});
      const inventoryBefore = await inventory();
      if (transition === 'replace' || transition === 'disable') {
        await before.goto(`${base}/plans/${original.id}`);
        if (transition === 'replace') {
          await before.locator('.explicit-supplement select').selectOption('rules[0].condition.conditions[0].low_fen');
          await before.getByLabel('rules[0].condition.conditions[0].low_fen 新值', {exact: true}).fill('9.81');
          await before.getByRole('button', {name: '保存字段修订并重新审核'}).click();
          await expect.poll(async () => (await latest()).version).toBe(3);
          await before.goto(`${base}/plans/${(await latest()).id}`);
          await approveAndActivate(before);
        } else {
          await before.getByTestId('request-deactivation').click();
          await before.locator('#confirm-plan-action').check();
          await before.getByTestId('confirm-plan-action').click();
          await expect.poll(async () => (await activation()).planVersionId).toBeNull();
        }
      }
      const stateBefore = await activation();
      records.push({original, inventoryBefore, stateBefore, initialEvent});
      await before.close();
      await stop();
      const offlineError = await fetch(`${base}/api/v1/health`).then(() => null, (error: unknown) => error);
      expect((offlineError as {cause?: NodeJS.ErrnoException}).cause?.code).toBe('ECONNREFUSED');
      records.push({oldProcessExited: true, offlineProbe: 'ECONNREFUSED'});
      const secondProcess = await start(transition === 'expire' ? '2026-09-15T10:10:15+08:00' : '2026-09-14T10:10:15+08:00');
      expect(secondProcess.pid).not.toBe(firstProcess.pid);
      expect(secondProcess.resumed).toBe(true);
      expect(secondProcess.database).toBe(firstProcess.database);
      expect(await activation()).toEqual(stateBefore);
      expect(inventoryLedger(await inventory())).toEqual(inventoryLedger(inventoryBefore));
      const after = await open('/alerts');
      await expect(after.locator(`[data-acknowledge="${initialEvent.eventId}"]`)).toContainText('已确认');
      expect((await alerts()).total).toBe(1);
      expect((await alerts()).items[0]).toMatchObject({eventId: initialEvent.eventId, planHash: initialEvent.planHash, activationRevision: initialEvent.activationRevision, currentActionable: transition === 'active'});
      if (transition !== 'expire') {
        // Startup recovery consumes the same completed tape; next deadline must
        // not resurrect its old target. A later valid occurrence remains enabled.
        await advance('10:11');
        expect((await alerts()).total).toBe(1);
        await advance('10:15');
        expect((await alerts()).total).toBe(transition === 'disable' ? 1 : 2);
        if (transition !== 'disable') {
          const sell = (await alerts()).items.find((e: {signalType: string}) => e.signalType === 'SELL');
          expect(sell.planVersion).toBe(transition === 'replace' ? 3 : 2);
          await expect(after.locator(`[data-acknowledge="${sell.eventId}"]`)).toBeVisible();
        }
        if (transition === 'active') {
          await advance('10:30');
          await expect.poll(async () => (await alerts()).total).toBe(4);
          const buys = (await alerts()).items.filter((e: {signalType: string}) => e.signalType === 'BUY');
          expect(buys).toHaveLength(2);
          expect(new Set(buys.map((e: {eventId: string}) => e.eventId)).size).toBe(2);
          expect(buys.every((e: {planHash: string}) => e.planHash === original.planHash)).toBe(true);
          for (const event of (await alerts()).items) {
            const acknowledgement = after.locator(`[data-acknowledge="${event.eventId}"]`);
            await expect(acknowledgement).toBeVisible();
            if (event.eventId !== initialEvent.eventId) await acknowledgement.click();
            await expect(acknowledgement).toContainText('已确认');
          }
        }
      } else {
        expect((await request.post(`${base}/_test/advance`, {data: {now: '2026-09-15T10:15:15+08:00'}})).status()).toBe(200);
        expect((await alerts()).total).toBe(1);
        expect((await alerts()).items[0].currentActionable).toBe(false);
      }
      expect(inventoryLedger(await inventory())).toEqual(inventoryLedger(inventoryBefore));
      await after.screenshot({path: join(root, 'restart-after.png'), fullPage: true});
      records.push({finalAlerts: await alerts(), finalInventory: await inventory(), finalActivation: await activation(), finalIsolation: await read('/_test/isolation')});
      await after.close();
      expect(consoleErrors).toEqual([]);
      expect(externalRequests).toEqual([]);
    } finally {
      await page?.close().catch(() => null);
      let cleanupError: unknown;
      await stop().catch(error => { cleanupError = error; log += String(error); server?.kill(); });
      if (root) await writeFile(join(root, `restart-${transition}.json`), JSON.stringify({transition, root, records, consoleErrors, externalRequests, log}, null, 2));
      console.log(`R13 OS ${transition} evidence: ${root}`);
      if (cleanupError !== undefined) throw cleanupError;
    }
  });
}

async function approveAndActivate(page: Page) {
  await expect(page.locator('.explicit-review input[type="checkbox"]').first()).toBeVisible();
  for (const check of await page.locator('.explicit-review input[type="checkbox"]').all()) await check.check();
  await page.getByRole('button', {name: '提交当前版本逐项复核'}).click();
  await expect(page.getByTestId('request-activation')).toBeEnabled();
  await page.getByTestId('request-activation').click();
  await page.locator('#confirm-plan-action').check();
  await page.getByTestId('confirm-plan-action').click();
  await expect(page.getByTestId('request-deactivation')).toBeVisible();
}

function inventoryLedger(snapshot: Record<string, unknown>) {
  // Read cutoff advances with the clock; every durable quantity, lot, balance,
  // confirmation and revision must remain identical.
  const { cutoff, ...ledger } = snapshot;
  expect(Number.isFinite(Date.parse(String(cutoff)))).toBe(true);
  return ledger;
}
