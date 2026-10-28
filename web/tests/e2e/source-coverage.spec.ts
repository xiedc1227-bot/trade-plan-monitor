import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import type { APIRequestContext, Locator, Page, Request, TestInfo } from "@playwright/test";
import type { PlanReviewConfirmationCommand, PlanVersionView, SourceCoveragePage } from "../../src/api/generated";
import { expect, test as auditedTest } from "./fixtures";

const repo = resolve(process.cwd(), "..");
const prefix = "/_test/source-coverage";
const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const turnover = "Only buy when turnover exceeds 3 percent.";
const markup = 'Only buy when <img src=x onerror="window.__sourceFixtureXss=1"> 😀 confirms the signal.';
type Scenario = "complete" | "mislabelled" | "missing-cap" | "xss-emoji" | "source-version";
interface SetupReceipt { planVersionId: string; planUrl: string; scenario: Scenario; generation: number }
interface Inspection { storage: Record<string, unknown>; externalAttempts: string[] }
interface SourceFixture {
  readonly base: string;
  readonly pageRequests: { method: string; path: string }[];
  setup(scenario: Scenario, generation?: 1 | 2): Promise<SetupReceipt>;
  inspect(): Promise<Inspection>;
}

async function port() {
  const listener = createServer();
  await new Promise<void>((done) => listener.listen(0, "127.0.0.1", done));
  const address = listener.address();
  if (!address || typeof address === "string") throw new Error("Missing isolated source fixture port");
  await new Promise<void>((done) => listener.close(() => done()));
  return address.port;
}

async function stop(server: ChildProcess, request: APIRequestContext, base: string) {
  if (server.exitCode !== null) {
    expect(server.exitCode, "fixture had already exited cleanly").toBe(0);
    expect(server.signalCode).toBeNull();
    return;
  }
  const exited = new Promise<void>((done) => server.once("exit", () => done()));
  await request.post(base + prefix + "/shutdown").catch(() => null);
  await Promise.race([exited, new Promise<void>((done) => setTimeout(done, 5000))]);
  if (server.exitCode === null) {
    server.kill();
    await Promise.race([exited, new Promise<void>((done) => setTimeout(done, 5000))]);
  }
  expect(server.exitCode, "isolated fixture process exited cleanly").toBe(0);
  expect(server.signalCode, "fixture was not force-terminated").toBeNull();
}

// One Python TemporaryDirectory and actual SQLite owner per test. No shared
// reviewed scenario, provider, data acquisition or notification capability.
const test = auditedTest.extend<{ sourceFixture: SourceFixture }>({
  sourceFixture: async ({ request, page }, use, testInfo) => {
    const isolatedPort = await port();
    const base = `http://127.0.0.1:${isolatedPort}`;
    const server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-X", "utf8", "-m",
      "tests.browser.source_coverage_server", "--port", String(isolatedPort)],
    { cwd: repo, windowsHide: true, env: { ...process.env, PYTHONUTF8: "1" } });
    let log = "";
    const record = (value: unknown) => { log = (log + String(value)).slice(-65536); };
    server.stdout?.on("data", record); server.stderr?.on("data", record);
    const external: string[] = [];
    const pageRequests: { method: string; path: string }[] = [];
    const inFlight = new Map<Request, { method: string; path: string; resourceType: string; startedAt: number; phase: string }>();
    let phase = "RUNNING";
    const lifecycle: { event: string; at: number }[] = [];
    const dashboards: { phase: string; at: number }[] = [];
    const navigations: { url: string; at: number }[] = [];
    let pendingAtClose: { method: string; path: string; resourceType: string; startedAt: number;
      phase: string; failureAtClose: string | null }[] = [];
    page.on("request", (req) => {
      const url = new URL(req.url());
      if (url.host !== new URL(base).host || !["http:", "ws:"].includes(url.protocol)) external.push(req.url());
      pageRequests.push({ method: req.method(), path: url.pathname });
      if (url.protocol === "http:") inFlight.set(req, { method: req.method(), path: url.pathname,
        resourceType: req.resourceType(), startedAt: Date.now(), phase });
      if (url.pathname === "/api/v1/dashboard") dashboards.push({ phase, at: Date.now() });
    });
    page.on("requestfinished", (req) => inFlight.delete(req));
    page.on("requestfailed", (req) => inFlight.delete(req));
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) navigations.push({ url: frame.url(), at: Date.now() });
    });
    try {
      await expect.poll(async () => {
        if (server.exitCode !== null) throw new Error(`Isolated source fixture exited: ${log}`);
        try { return (await request.get(base + prefix + "/isolation")).status(); } catch { return 0; }
      }, { timeout: 30000, message: "Temporary offline source fixture is available" }).toBe(200);
      const isolation = await (await request.get(base + prefix + "/isolation")).json();
      expect(isolation.temporary).toBe(true);
      expect(isolation.provider).toBe("DISABLED_NO_IO");
      expect(isolation.createdVersionIds).toEqual([]);
      expect(resolve(isolation.database)).toBe(join(resolve(isolation.root), "source-coverage.sqlite3"));
      await use({ base, pageRequests,
        async setup(scenario, generation = 1) {
          const result = await request.post(base + prefix + "/setup", { data: { scenario, generation },
            headers: { "Idempotency-Key": randomUUID() } });
          expect(result.status(), await result.text()).toBe(200);
          return result.json();
        },
        async inspect() {
          const result = await request.get(base + prefix + "/inspect");
          expect(result.status(), await result.text()).toBe(200);
          return result.json();
        },
      });
      expect((await (await request.get(base + prefix + "/inspect")).json()).externalAttempts).toEqual([]);
    } finally {
      try {
        // Reload can discard an old document's request without a terminal page
        // event. This bookkeeping is diagnostic, not a physical ownership token.
        pendingAtClose = [...inFlight.entries()].map(([request, value]) => ({ ...value,
          failureAtClose: request.failure()?.errorText ?? null }));
        phase = "PAGE_CLOSING"; lifecycle.push({ event: phase, at: Date.now() });
        await page.close();
        phase = "PAGE_CLOSED"; lifecycle.push({ event: phase, at: Date.now() });
      } finally {
        phase = "BACKEND_STOPPING"; lifecycle.push({ event: phase, at: Date.now() });
        try { await stop(server, request, base); }
        finally {
          phase = server.exitCode !== null || server.signalCode !== null ? "BACKEND_STOPPED" : "BACKEND_STOP_FAILED";
          lifecycle.push({ event: phase, at: Date.now() });
          await writeFile(testInfo.outputPath("source-fixture.log"), log, "utf8");
          await writeFile(testInfo.outputPath("source-lifecycle-audit.json"), JSON.stringify({ lifecycle, dashboards,
            navigations, pendingAtClose, backendExitCode: server.exitCode, backendSignalCode: server.signalCode }, null, 2), "utf8");
        }
      }
      expect(dashboards.filter((item) => item.phase.startsWith("BACKEND_")), "no live consumer requests after backend disposal starts").toEqual([]);
      expect(external, "zero external browser requests").toEqual([]);
      expect(log).not.toContain("Traceback");
    }
  },
});

// This one negative journey intentionally produces one native Chrome diagnostic.
// Its exact actual response URL is captured by the test. No generic ignore flag
// or shared audit change is introduced; every other warning/error still fails.
const staleCursorTest = test.extend<{ nativeCursorConflict: { url: string | null } }>({
  nativeCursorConflict: async ({}, use) => { await use({ url: null }); },
  // Playwright inherits the original fixture's automatic registration when an
  // override has no metadata (installed lib/common/index.js FixturePool).
  browserAudit: async ({ context, nativeCursorConflict }, use, testInfo) => {
    const messages: { type: string; text: string; url: string }[] = [];
    const failedRequests: string[] = [];
    const pageErrors: string[] = [];
    const attach = (page: Page) => {
      page.on("console", (message) => {
        if (message.type() === "error" || message.type() === "warning")
          messages.push({ type: message.type(), text: message.text(), url: message.location().url });
      });
      page.on("requestfailed", (request) => failedRequests.push(
        `${request.method()} ${request.url()} (${request.failure()?.errorText ?? "unknown"})`));
      page.on("pageerror", (error) => pageErrors.push(error.message));
    };
    for (const page of context.pages()) attach(page);
    context.on("page", attach);
    await use();
    expect(nativeCursorConflict.url, "actual stale-cursor409 response captured").not.toBeNull();
    expect(messages, "only this bound native409 diagnostic is expected").toEqual([{
      type: "error", text: "Failed to load resource: the server responded with a status of 409 (Conflict)",
      url: nativeCursorConflict.url,
    }]);
    expect(failedRequests, "no failed browser requests, including aborts, in this negative journey").toEqual([]);
    expect(pageErrors, "no uncaught page exceptions").toEqual([]);
    await testInfo.attach("bound-native-cursor409-diagnostic", { contentType: "application/json",
      body: Buffer.from(JSON.stringify({ expectedNativeDiagnosticCount: 1, messages, failedRequests, pageErrors }, null, 2)) });
  },
});

function pane(page: Page) { return page.getByRole("region", { name: "原文条件核对", exact: true }); }
async function savedVersion(request: APIRequestContext, fixture: SourceFixture, id: string): Promise<PlanVersionView> {
  const response = await request.get(`${fixture.base}/api/v1/plan-versions/${id}`);
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}
async function coverage(request: APIRequestContext, fixture: SourceFixture, id: string, cursor?: string): Promise<SourceCoveragePage> {
  const response = await request.get(`${fixture.base}/api/v1/plan-versions/${id}/source-coverage`,
    { params: { limit: 50, ...(cursor === undefined ? {} : { cursor }) } });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  expect(body.planVersionId).toBe(id); expect(body.authorityGranted).toBe(false);
  return body;
}
function count(inspect: Inspection, table: string): number {
  const value = inspect.storage[table] as { count: number };
  expect(Number.isSafeInteger(value.count)).toBe(true); return value.count;
}
function noTradeEffects(inspect: Inspection) {
  for (const table of ["position_lot", "evaluation_ledger", "alert_event", "delivery_attempt"])
    expect(count(inspect, table), `${table} remains empty`).toBe(0);
  expect(inspect.externalAttempts).toEqual([]);
}
function reviewCommand(saved: PlanVersionView): PlanReviewConfirmationCommand {
  expect(saved.sourceCoverage?.coverageComplete).toBe(true);
  return { planVersionId: saved.id, contentHash: saved.contentHash!, sourceHash: saved.sourceHash!,
    reviewEvidenceHash: saved.reviewEvidenceHash!, expectedRevision: saved.reviewRevision!,
    coverageEvidenceHash: saved.sourceCoverage!.coverageEvidenceHash!,
    coverageRulesVersion: saved.sourceCoverage!.rulesVersion! };
}
async function open(page: Page, fixture: SourceFixture, saved: SetupReceipt) {
  await page.goto(fixture.base + saved.planUrl);
  await expect(page.getByRole("heading", { name: "编辑规则、周期与执行窗口", exact: true })).toBeVisible();
  await expect(pane(page)).toBeVisible();
  await expect(pane(page)).not.toHaveAttribute("aria-busy", "true");
}
async function untilMarker(page: Page, marker: string, totalRows: number): Promise<Locator> {
  const area = pane(page);
  let visited = 0;
  while (visited < totalRows) {
    const row = area.locator(".source-coverage-row").filter({ has: page.locator("blockquote").filter({ hasText: marker }) });
    if (await row.count()) return row;
    const next = area.getByRole("button", { name: "读取下一页", exact: true });
    await expect(next).toBeVisible();
    const response = page.waitForResponse((result) => new URL(result.url()).pathname.endsWith("/source-coverage") && result.request().method() === "GET");
    await next.click();
    const result = await response; expect(result.status(), await result.text()).toBe(200);
    const body: SourceCoveragePage = await result.json();
    expect(body.returnedCount).toBeGreaterThan(0); visited += body.returnedCount;
    await expect(area).not.toHaveAttribute("aria-busy", "true");
  }
  throw new Error("Marker missing from complete bounded fixture coverage");
}
async function screenshot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(name + ".png");
  await page.screenshot({ path });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

test("current saved HUMAN source renders a read-only coverage pane", async ({ page, sourceFixture }, testInfo) => {
  expect(testInfo.project.name).toBe("chrome");
  expect(page.context().browser()?.version()).toBe("157.0.8103.6");
  const saved = await sourceFixture.setup("complete");
  const before = await sourceFixture.inspect();
  await page.goto(sourceFixture.base + saved.planUrl);
  await expect(page.getByRole("heading", { name: "计划工作台", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "编辑规则、周期与执行窗口", exact: true })).toBeVisible();
  const pane = page.getByRole("region", { name: "原文条件核对", exact: true });
  if (await pane.count() === 0) await page.screenshot({ path: testInfo.outputPath("missing-source-pane.png") });
  await expect(pane).toBeVisible();
  await expect(pane).toContainText("人工整理，审核状态另列");
  await expect(pane).toContainText("本次证明待审核");
  expect((await sourceFixture.inspect()).storage).toEqual(before.storage);
  expect(sourceFixture.pageRequests.filter((item) => item.method === "POST").map((item) => item.path))
    .toEqual(["/api/v1/plan-review-previews"]);
});

test("explicit review sends exact coverage fields, activation is separate, and reload preserves the real receipt", async ({ page, request, sourceFixture }) => {
  const setup = await sourceFixture.setup("complete");
  const saved = await savedVersion(request, sourceFixture, setup.planVersionId);
  const before = await sourceFixture.inspect();
  expect(count(before, "source_coverage_review")).toBe(0); expect(count(before, "active_plan")).toBe(0);
  await open(page, sourceFixture, setup);
  await expect(pane(page)).toContainText("本次证明待审核");
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeEnabled();
  expect((await sourceFixture.inspect()).storage).toEqual(before.storage);
  const reviewing = page.waitForResponse((result) => result.url().endsWith("/plan-review-confirmations") && result.request().method() === "POST");
  await page.getByRole("button", { name: "确认当前完整审核", exact: true }).click();
  const reviewed = await reviewing; expect(reviewed.status(), await reviewed.text()).toBe(200);
  expect(reviewed.request().postDataJSON()).toMatchObject({ coverageEvidenceHash: saved.sourceCoverage!.coverageEvidenceHash,
    coverageRulesVersion: saved.sourceCoverage!.rulesVersion, sourceHash: saved.sourceHash, planVersionId: saved.id });
  await expect(pane(page)).toContainText("本次证明已完成审核");
  const afterReview = await sourceFixture.inspect();
  expect(count(afterReview, "source_coverage_review")).toBe(1); expect(count(afterReview, "active_plan")).toBe(0);
  noTradeEffects(afterReview);
  const activation = page.waitForResponse((result) => result.url().endsWith("/plan-activations") && result.request().method() === "POST");
  await page.getByRole("button", { name: "启用当前审核绑定", exact: true }).click();
  const active = await activation; expect(active.status(), await active.text()).toBe(200);
  expect((await active.json()).active).toBe(true);
  expect(count(await sourceFixture.inspect(), "active_plan")).toBe(1);
  noTradeEffects(await sourceFixture.inspect());
  await page.reload();
  await expect(pane(page)).toContainText("本次证明已完成审核");
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeDisabled();
  expect(count(await sourceFixture.inspect(), "source_coverage_review")).toBe(1);
});

test("mislabelled mandatory turnover stays globally blocked before its page and remains savable", async ({ page, request, sourceFixture }) => {
  const setup = await sourceFixture.setup("mislabelled");
  const saved = await savedVersion(request, sourceFixture, setup.planVersionId);
  expect(saved.dailyIssues).toEqual([]);
  const first = await coverage(request, sourceFixture, saved.id);
  expect(first.summary.issueCount).toBeGreaterThan(0);
  expect(first.items.every((item) => item.kind === "OBLIGATION" && item.obligation.serverState === "MAPPED")).toBe(true);
  const before = await sourceFixture.inspect();
  await open(page, sourceFixture, setup);
  await expect(pane(page)).toContainText(`整份计划仍有 ${first.summary.issueCount} 项待解决`);
  await expect(pane(page).getByText(turnover, { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "保存待审核版本", exact: true })).toBeEnabled();
  const row = await untilMarker(page, turnover, first.totalRows);
  await expect(row.getByRole("region", { name: "保存的映射建议", exact: true })).toContainText("上下文（建议）");
  await expect(row.getByRole("region", { name: "服务端核对结果", exact: true })).toContainText("阻断：尚未明确对应规则");
  expect((await sourceFixture.inspect()).storage).toEqual(before.storage);
  const saving = page.waitForResponse((result) => result.url().endsWith("/plan-drafts") && result.request().method() === "POST");
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  const response = await saving; expect(response.status(), await response.text()).toBe(200);
  const newer: PlanVersionView = await response.json();
  expect(newer.id).not.toBe(saved.id); expect(newer.sourceText).toBe(saved.sourceText);
  expect(newer.sourceCoverage?.coverageComplete).toBe(false);
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeDisabled();
  expect(count(await sourceFixture.inspect(), "source_coverage_review")).toBe(0);
  noTradeEffects(await sourceFixture.inspect());
});

test("source pane fits four viewports with native keyboard focus and local WCAG evidence", async ({ page, request, sourceFixture }, testInfo) => {
  const setup = await sourceFixture.setup("mislabelled");
  await open(page, sourceFixture, setup);
  await expect(pane(page)).toContainText("整份计划仍有");
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await pane(page).getByRole("heading", { name: "原文条件核对", exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `horizontal overflow at ${width}`).toBe(true);
    const sizes = await pane(page).getByRole("button").evaluateAll((elements) => elements.map((element) => ({
      text: element.textContent, height: element.getBoundingClientRect().height,
    })));
    expect(sizes.length).toBeGreaterThan(0);
    expect(sizes.every((item) => item.height >= 44), `44px coverage controls at ${width}`).toBe(true);
    await screenshot(page, testInfo, `source-global-blocker-${width}`);
  }
  const locate = pane(page).getByRole("button", { name: "定位原文第 1 项", exact: true });
  await locate.focus(); await page.keyboard.press("Enter");
  const mark = pane(page).locator('mark[aria-label="已定位的原文片段"]');
  await expect(mark).toBeFocused();
  expect(await mark.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe("none");
  await page.keyboard.press("Shift+Tab");
  const originalText = pane(page).getByLabel("原文及定位片段", { exact: true });
  await expect(originalText).toBeFocused();
  expect(await originalText.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe("none");
  // Serve the pinned local package as a same-origin script. Production CSP stays
  // enabled; inline injection is intentionally forbidden by script-src 'self'.
  const axeUrl = sourceFixture.base + prefix + "/axe-core.js";
  const axeScript = await readFile(axePath, "utf8");
  await page.route(axeUrl, (route) => route.fulfill({ contentType: "application/javascript; charset=utf-8", body: axeScript }));
  await page.addScriptTag({ url: axeUrl });
  const violations = await pane(page).evaluate(async (element) => {
    const axe = (globalThis as typeof globalThis & { axe: { run(root: Element, options: object): Promise<{ violations: unknown[] }> } }).axe;
    return (await axe.run(element, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] })).violations;
  });
  expect(violations).toEqual([]);
  expect((await (await request.get(sourceFixture.base + prefix + "/inspect")).json()).externalAttempts).toEqual([]);
});

test("an explicit missing maximum is entered and registered, saved as a new version, then independently reviewed", async ({ page, request, sourceFixture }) => {
  const setup = await sourceFixture.setup("missing-cap");
  const original = await savedVersion(request, sourceFixture, setup.planVersionId);
  const oldDocument = JSON.parse(original.planJson!);
  expect(oldDocument.position.max_qty).toBeNull(); expect(original.sourceText).toContain("position.max_qty = null");
  await open(page, sourceFixture, setup);
  await expect(pane(page)).toContainText("原文条件仍有待解决项");
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeDisabled();
  await page.locator('[id="daily-.position.max_qty"]').fill("300");
  await page.getByRole("button", { name: "检查当前参数与来源", exact: true }).click();
  const reason = "Human explicitly defines the missing maximum as300 shares; all original conditions remain required and no omission is waived.";
  await page.locator('[id="reason-position.max_qty"]').fill(reason);
  const registration = page.waitForResponse((result) => result.url().endsWith("/plan-review-supplements") && result.request().method() === "POST");
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  const registered = await registration; expect(registered.status(), await registered.text()).toBe(200);
  expect(registered.request().postDataJSON().supplements).toEqual([expect.objectContaining({ path: "position.max_qty", value: 300, reason })]);
  const saving = page.waitForResponse((result) => result.url().endsWith("/plan-drafts") && result.request().method() === "POST");
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  const response = await saving; expect(response.status(), await response.text()).toBe(200);
  const saved: PlanVersionView = await response.json(); const document = JSON.parse(saved.planJson!);
  expect(saved.id).not.toBe(original.id); expect(saved.sourceText).toBe(original.sourceText);
  expect(document.position.max_qty).toBe(300);
  for (const key of ["ordinary_rules", "risk_branches", "alert_rules", "activation"])
    expect(document[key]).toEqual(oldDocument[key]);
  const complete = await coverage(request, sourceFixture, saved.id);
  expect(complete.summary.coverageComplete).toBe(true); expect(complete.summary.currentReviewBound).toBe(false);
  let inspected = complete; let links = 0;
  for (;;) {
    links += inspected.items.filter((item) => item.kind === "OBLIGATION" &&
      item.obligation.humanSupplements.some((link) => link.path === "position.max_qty" && link.candidateContentHash === saved.contentHash)).length;
    if (inspected.nextCursor === null) break;
    inspected = await coverage(request, sourceFixture, saved.id, inspected.nextCursor);
  }
  expect(links).toBeGreaterThan(0);
  expect(count(await sourceFixture.inspect(), "source_coverage_review")).toBe(0);
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeEnabled();
  const confirming = page.waitForResponse((result) => result.url().endsWith("/plan-review-confirmations") && result.request().method() === "POST");
  await page.getByRole("button", { name: "确认当前完整审核", exact: true }).click();
  const confirmed = await confirming; expect(confirmed.status(), await confirmed.text()).toBe(200);
  expect(confirmed.request().postDataJSON()).toMatchObject({ coverageEvidenceHash: complete.summary.coverageEvidenceHash,
    coverageRulesVersion: complete.summary.rulesVersion });
  expect(count(await sourceFixture.inspect(), "active_plan")).toBe(0);
  expect((await savedVersion(request, sourceFixture, original.id)).planJson).toBe(original.planJson);
  noTradeEffects(await sourceFixture.inspect());
});

test("XSS and emoji source remains escaped and exact in the readonly locator", async ({ page, request, sourceFixture }, testInfo) => {
  const setup = await sourceFixture.setup("xss-emoji");
  const saved = await savedVersion(request, sourceFixture, setup.planVersionId);
  const first = await coverage(request, sourceFixture, saved.id);
  const before = await sourceFixture.inspect();
  await open(page, sourceFixture, setup);
  const row = await untilMarker(page, markup, first.totalRows);
  await expect(row.getByRole("region", { name: "服务端核对结果", exact: true })).toContainText("阻断：尚未明确对应规则");
  await row.getByRole("button", { name: /^定位原文第 \d+ 项$/ }).focus();
  await page.keyboard.press("Enter");
  const mark = pane(page).locator('mark[aria-label="已定位的原文片段"]');
  await expect(mark).toBeFocused(); await expect(mark).toHaveText(markup);
  expect(await pane(page).getByLabel("原文及定位片段", { exact: true }).textContent()).toBe(saved.sourceText);
  await expect(pane(page).locator("img, script")).toHaveCount(0);
  expect(await page.evaluate(() => "__sourceFixtureXss" in window)).toBe(false);
  await page.setViewportSize({ width: 1440, height: 900 });
  await mark.scrollIntoViewIfNeeded(); await screenshot(page, testInfo, "source-xss-emoji-exact-span");
  expect((await sourceFixture.inspect()).storage).toEqual(before.storage);
});

test("old source bindings return409 and a late A-B-A GET cannot replace the current proof revision", async ({ page, request, sourceFixture }) => {
  const first = await sourceFixture.setup("source-version", 1);
  const second = await sourceFixture.setup("source-version", 2);
  const a = await savedVersion(request, sourceFixture, first.planVersionId);
  const b = await savedVersion(request, sourceFixture, second.planVersionId);
  expect(a.sourceHash).not.toBe(b.sourceHash);
  const staleCommand = { ...reviewCommand(a), planVersionId: b.id };
  const beforeConflict = await sourceFixture.inspect();
  const stale = await request.post(sourceFixture.base + "/api/v1/plan-review-confirmations",
    { data: staleCommand, headers: { "Idempotency-Key": randomUUID() } });
  expect(stale.status(), await stale.text()).toBe(409);
  expect((await stale.json()).error.details).toContainEqual(expect.objectContaining({ code: "SOURCE_COVERAGE_STALE" }));
  expect((await sourceFixture.inspect()).storage).toEqual(beforeConflict.storage);

  let firstBody: SourceCoveragePage | null = null;
  let captured = false;
  let release!: () => void;
  let completed!: () => void;
  const releaseOld = new Promise<void>((done) => { release = done; });
  const oldCompleted = new Promise<void>((done) => { completed = done; });
  await page.route("**/api/v1/plan-versions/*/source-coverage?*", async (route) => {
    if (!captured && new URL(route.request().url()).pathname.includes(a.id)) {
      captured = true;
      const actual = await route.fetch();
      expect(actual.status(), await actual.text()).toBe(200);
      firstBody = await actual.json();
      await releaseOld;
      try { await route.fulfill({ response: actual }); }
      catch (error) { if (route.request().failure()?.errorText !== "net::ERR_ABORTED") throw error; }
      finally { completed(); }
    } else await route.continue();
  });
  try {
    await page.goto(sourceFixture.base + first.planUrl);
    await expect.poll(() => firstBody !== null).toBe(true);
    expect(firstBody).toMatchObject({ summary: { coverageRevision: a.sourceCoverage!.coverageRevision } });
    const reassess = await request.post(`${sourceFixture.base}${prefix}/reassess/${a.id}`,
      { data: { expected_revision: a.sourceCoverage!.coverageRevision } });
    expect(reassess.status(), await reassess.text()).toBe(200);
    const revision = (await reassess.json()).coverageRevision;
    expect(revision).toBe(a.sourceCoverage!.coverageRevision! + 1);
    const versions = page.getByRole("navigation", { name: "计划版本", exact: true });
    await versions.getByRole("button", { name: /^v2 ·/ }).click();
    await expect(pane(page)).toContainText(b.sourceHash!);
    await expect(pane(page)).not.toHaveAttribute("aria-busy", "true");
    await versions.getByRole("button", { name: /^v1 ·/ }).click();
    await expect(pane(page)).toContainText(a.sourceHash!);
    const shownRevision = pane(page).locator("dt").filter({ hasText: /^覆盖修订$/ }).locator("xpath=following-sibling::dd[1]");
    await expect(shownRevision).toHaveText(String(revision));
    release(); await oldCompleted;
    await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => done())));
    await expect(shownRevision).toHaveText(String(revision));
    await expect(pane(page)).toContainText("原文条件已完整核对");
    expect(count(await sourceFixture.inspect(), "source_coverage_review")).toBe(0);
    noTradeEffects(await sourceFixture.inspect());
  } finally { release(); }
});

staleCursorTest("actual reassessment invalidates a cursor and explicit first-page reload refreshes the exact native seed", async ({ page, request, sourceFixture, nativeCursorConflict }) => {
  const setup = await sourceFixture.setup("complete");
  const first = await coverage(request, sourceFixture, setup.planVersionId);
  expect(first.nextCursor).not.toBeNull();
  await open(page, sourceFixture, setup);
  await expect(pane(page)).toContainText("原文条件已完整核对");
  await expect(pane(page).getByRole("button", { name: "读取下一页", exact: true })).toBeEnabled();
  const changed = await request.post(`${sourceFixture.base}${prefix}/reassess/${setup.planVersionId}`,
    { data: { expected_revision: first.summary.coverageRevision } });
  expect(changed.status(), await changed.text()).toBe(200);
  const revision = (await changed.json()).coverageRevision;
  expect(revision).toBe(first.summary.coverageRevision! + 1);
  const before = await sourceFixture.inspect();
  const oldCursor = await request.get(`${sourceFixture.base}/api/v1/plan-versions/${setup.planVersionId}/source-coverage`,
    { params: { limit: 50, cursor: first.nextCursor! } });
  expect(oldCursor.status(), await oldCursor.text()).toBe(409);
  expect((await oldCursor.json()).error.details).toContainEqual(expect.objectContaining({ code: "SOURCE_COVERAGE_STALE" }));
  expect((await sourceFixture.inspect()).storage).toEqual(before.storage);

  const failedRead = page.waitForResponse((result) => result.url().includes("/source-coverage?") && new URL(result.url()).searchParams.has("cursor"));
  await pane(page).getByRole("button", { name: "读取下一页", exact: true }).click();
  const rejected = await failedRead;
  expect(rejected.status()).toBe(409);
  expect(new URL(rejected.url()).pathname).toBe(`/api/v1/plan-versions/${setup.planVersionId}/source-coverage`);
  expect(new URL(rejected.url()).searchParams.get("cursor")).toBe(first.nextCursor);
  expect((await rejected.json()).error.details).toContainEqual(expect.objectContaining({ code: "SOURCE_COVERAGE_STALE" }));
  nativeCursorConflict.url = rejected.url();
  await expect(pane(page)).not.toContainText("原文条件已完整核对");
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeDisabled();
  await pane(page).getByRole("button", { name: "从第一页重新读取", exact: true }).click();
  await expect(pane(page)).toContainText("原文条件已完整核对");
  await expect(pane(page).locator("dt").filter({ hasText: /^覆盖修订$/ }).locator("xpath=following-sibling::dd[1]"))
    .toHaveText(String(revision));
  expect((await sourceFixture.inspect()).storage).toEqual(before.storage);
});
