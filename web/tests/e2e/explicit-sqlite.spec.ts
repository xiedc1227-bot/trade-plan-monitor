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

test("literal v3 ordinary UI reaches real SQLite and production scheduler", async ({ page, request }) => {
  test.setTimeout(180000);
  page.setDefaultTimeout(15000);
  const isolation = await (await request.get(`${base}/_test/isolation`)).json();
  expect(isolation.database).toContain("tpm-r12-browser-");
  expect(isolation.provider).toBe("IN_PROCESS_FAKE");
  const evidence = isolation.root;
  const consoleErrors: string[] = [];
  const network: unknown[] = [];
  const external: string[] = [];
  page.on("console", (message) => { if (["warning", "error"].includes(message.type())) consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("request", (req) => { if (new URL(req.url()).origin !== base) external.push(req.url()); });
  page.on("response", async (response) => {
    if (response.url().includes("/api/")) {
      network.push({ method: response.request().method(), url: response.url(), status: response.status(), body: await response.json().catch(() => null) });
    }
  });
  try {
    const inventory = async () => (await request.get(`${base}/api/v1/position-inventory?symbol=003043.SZ&asOfTradeDate=2026-09-14`)).json();
    expect((await inventory()).status).toBe("UNKNOWN");
    expect(await (await request.get(`${base}/api/v1/plan-capabilities`)).json()).toMatchObject({
      publicActivationAvailable: true, isolatedTrustedReviewOnly: false, pendingRequirements: [],
    });
    await page.goto(`${base}/plans`);
    await page.getByLabel("粘贴中文计划原文").fill(literal.sourceText);
    await page.getByRole("button", { name: "生成计划草稿" }).click();
    await page.getByRole("button", { name: "保存并进入逐项复核" }).click();
    await expect(page.getByRole("heading", { name: "当前内容逐项复核" })).toBeVisible();
    const review = page.locator(".explicit-review");
    await expect(review.locator("pre")).toHaveText(literal.sourceText);
    expect((await inventory()).status).toBe("UNKNOWN");
    const fields = ["启用方式", "启用交易日", "成交量历史范围", "买入重复策略", "卖出重复策略", "风险重复策略", "买卖冲突策略", "风险冲突策略"];
    const values = Object.values(literal.humanTestSupplements) as string[];
    for (const [index, label] of fields.entries()) await page.getByLabel(label, { exact: true }).fill(values[index]!);
    await page.getByRole("button", { name: "保存补充并重新审核" }).click();
    await expect(review.getByText("人工补充", { exact: true })).toBeVisible();
    const currentPage = await (await request.get(`${base}/api/v1/plan-versions?offset=0&limit=100`)).json();
    expect(currentPage.total).toBe(2);
    const selected = currentPage.items.find((item: { version: number }) => item.version === 2);
    const detail = await (await request.get(`${base}/api/v1/plan-versions/${selected.id}`)).json();
    expect(detail.sourceText).toBe(literal.sourceText);
    const document = JSON.parse(detail.planJson);
    for (const [path, expected] of Object.entries(literal.independentExpectedValues)) {
      if (expected !== null) expect(pathValue(document, path), path).toEqual(expected);
    }
    for (const [path, clauseIndex] of Object.entries(literal.expectedSourceClauses)) {
      const binding = detail.mapping.fieldBindings.find((item: { path: string }) => item.path === path);
      const clause = detail.mapping.sourceClauses[Number(clauseIndex)];
      expect(binding.origin).toBe("SOURCE");
      expect(binding.clauseIds).toEqual([clause.clauseId]);
      expect(binding.unit).toBe(literal.expectedSourceUnits[path] ?? "NONE");
      expect(clause.excerpt).toBe(literal.sourceText.slice(clause.start, clause.end));
    }
    expect(Object.fromEntries(detail.mapping.userSupplements.map((item: { path: string; value: unknown }) => [item.path, item.value]))).toEqual(literal.humanTestSupplements);
    for (const binding of detail.mapping.fieldBindings) {
      await expect(review.locator("li code").filter({ hasText: `${binding.path} = ${binding.value}` }).first()).toBeVisible();
    }
    await page.screenshot({ path: join(evidence, "01-review.png"), fullPage: true });
    const checks = review.locator('input[type="checkbox"]');
    for (const check of await checks.all()) await check.check();
    await page.getByRole("button", { name: "提交当前版本逐项复核" }).click();
    await expect(page.getByTestId("request-activation")).toBeEnabled();
    expect((await inventory()).status).toBe("UNKNOWN");
    await page.getByTestId("request-activation").click();
    await page.locator("#confirm-plan-action").check();
    await page.getByTestId("confirm-plan-action").click();
    await expect(page.getByTestId("request-deactivation")).toBeVisible();
    await page.getByLabel("库存登记交易日", { exact: true }).fill("2026-09-14");
    await page.getByLabel("总股数", { exact: true }).fill("100");
    await page.getByLabel("可卖股数", { exact: true }).fill("100");
    await page.getByLabel("我确认已完整登记该股票的当前库存").check();
    await page.getByRole("button", { name: "保存独立库存登记" }).click();
    await expect.poll(async () => (await inventory()).totalQuantity).toBe(100);
    const runtime = async () => (await request.get(`${base}/api/v1/explicit-plan-runtime/003043.SZ`)).json();
    for (const [time, expectedAction] of [["10:05", null], ["10:10", "BUY"], ["10:15", "SELL"], ["10:20", "RISK_ALERT"]] as const) {
      const now = `2026-09-14T${time}:15+08:00`;
      await request.post(`${base}/_test/advance`, { data: { now } });
      await expect.poll(async () => (await runtime()).targetBucketEnd, { timeout: 30000 }).toContain(`${time}:00`);
      await page.getByRole("button", { name: "刷新当前结果" }).click();
      await expect(page.locator(".explicit-runtime")).toContainText(`${time}:00`);
      for (const summary of await page.locator(".explicit-runtime summary").all()) await summary.click();
      const alerts = await (await request.get(`${base}/api/v1/alerts?offset=0&limit=100`)).json();
      network.push({ checkpoint: time, runtime: await runtime(), inventory: await inventory(), alerts });
      if (expectedAction === null) expect(alerts.total).toBe(0);
      else expect(alerts.items.some((item: { signalType: string }) => item.signalType === expectedAction)).toBe(true);
      if (time === "10:05" || time === "10:10") {
        await expect(page.locator(".explicit-runtime")).toContainText("mean_volume_shares");
        await expect(page.locator(".explicit-runtime")).toContainText(time === "10:05" ? "299" : "300");
      }
      expect((await inventory()).totalQuantity).toBe(100);
      await page.locator(".explicit-runtime").screenshot({ path: join(evidence, `runtime-${time.replace(":", "")}.png`) });
    }
    await page.goto(`${base}/`);
    await expect(page.locator(".explicit-runtime-dashboard")).toContainText("risk-950");
    await page.screenshot({ path: join(evidence, "02-dashboard.png"), fullPage: true });
    await page.goto(`${base}/alerts`);
    await expect(page.locator("body")).toContainText("RISK_ALERT");
    await page.screenshot({ path: join(evidence, "03-alerts.png"), fullPage: true });
    const allAlerts = await (await request.get(`${base}/api/v1/alerts?offset=0&limit=100`)).json();
    expect(allAlerts.total).toBe(3);
    const risk = allAlerts.items.find((item: { signalType: string }) => item.signalType === "RISK_ALERT");
    expect(risk.quantity).toBeNull();
    for (const alert of allAlerts.items) {
      expect(alert.planVersion).toBe(2);
      expect(alert.planHash).toBe((await runtime()).planHash);
      await page.locator(`[data-acknowledge="${alert.eventId}"]`).click();
      await expect(page.locator(`[data-acknowledge="${alert.eventId}"]`)).toContainText("已确认");
      expect((await inventory()).totalQuantity).toBe(100);
    }
    network.push({ checkpoint: "acknowledged", inventory: await inventory() });
    await page.goto(`${base}/plans/${selected.id}`);
    await page.getByLabel("库存登记交易日", { exact: true }).fill("2026-09-14");
    await page.getByLabel("实际成交股数", { exact: true }).fill("100");
    await page.getByRole("button", { name: "登记成交减记" }).click();
    await expect.poll(async () => (await inventory()).totalQuantity).toBe(0);
    await page.getByTestId("request-deactivation").click();
    await page.locator("#confirm-plan-action").check();
    await page.getByTestId("confirm-plan-action").click();
    await expect.poll(async () => (await (await request.get(`${base}/api/v1/plan-activation-states/003043.SZ`)).json()).active).toBe(false);
    await request.post(`${base}/_test/advance`, { data: { now: "2026-09-14T10:25:15+08:00" } });
    const after = await (await request.get(`${base}/api/v1/alerts?offset=0&limit=100`)).json();
    expect(after.total).toBe(3);
    expect(after.items.every((item: { currentActionable: boolean }) => !item.currentActionable)).toBe(true);
    network.push({ checkpoint: "closed-and-deactivated", inventory: await inventory(), alerts: after });
    await page.screenshot({ path: join(evidence, "04-deactivated.png"), fullPage: true });
    expect(consoleErrors).toEqual([]);
    expect(external).toEqual([]);
  } finally {
    await page.screenshot({ path: join(evidence, "last-page.png"), fullPage: true });
    await writeFile(join(evidence, "browser-evidence.json"), JSON.stringify({ isolation: await (await request.get(`${base}/_test/isolation`)).json(), network, consoleErrors, external, serverLog }, null, 2));
    console.log(`R12 browser evidence: ${evidence}`);
  }
});

function pathValue(document: unknown, path: string): unknown {
  return path.replace(/\[(\d+)\]/g, ".$1").split(".").reduce<unknown>((value, key) => (value as Record<string, unknown>)[key], document);
}
