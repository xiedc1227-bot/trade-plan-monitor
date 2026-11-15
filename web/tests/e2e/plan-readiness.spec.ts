import { spawn, type ChildProcess } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import type { APIRequestContext, Locator, Page, Request, Response } from "@playwright/test";
import type { ReadinessAssessment } from "../../src/api/generated-runtime-status";
import type { PlanReviewConfirmationCommand, PlanVersionView } from "../../src/api/generated";
import { expect, test as auditedTest } from "./fixtures";

const repo = resolve(process.cwd(), "..");
const prefix = "/_test/plan-readiness";
const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");
interface Inspection {
  temporary: boolean; root: string; database: string; planVersionId: string; planUrl: string;
  now: string; runtimeGeneration: string; completionResultHash: string; cycles: number;
  completionRecordId: string | null;
  sdkCalls: number; externalAttempts: string[];
  storage: Record<string, unknown> & { dailyKinds: Record<string, number> };
  pbs?: { activeVersionId: string; sources: string[]; statement: string; aiCalls: unknown[];
    guardCurrent: boolean;
    guards: { id: string; revision: number; payload: { owner_plan_version_id: string;
      source_hash: string; content_hash: string; review_id: string; birth_activation_revision: number;
      target: string; definition: { effective_from: string };
      coverage?: { through: string } | null; trigger?: { bar_end: string; close_fen: number } | null } }[];
    simulations: unknown[] };
}
interface Fixture {
  base: string; initial: Inspection;
  inspect(): Promise<Inspection>;
  read(): Promise<ReadinessAssessment>;
  next(): Promise<Inspection>;
}

async function freePort() {
  const listener = createServer();
  await new Promise<void>((done) => listener.listen(0, "127.0.0.1", done));
  const address = listener.address();
  if (!address || typeof address === "string") throw new Error("Missing isolated fixture port");
  await new Promise<void>((done) => listener.close(() => done()));
  return address.port;
}
async function stop(server: ChildProcess, request: APIRequestContext, base: string) {
  if (server.exitCode === null) {
    const exited = new Promise<void>((done) => server.once("exit", () => done()));
    await request.post(base + prefix + "/shutdown").catch(() => null);
    await Promise.race([exited, new Promise<void>((done) => setTimeout(done, 8000))]);
    if (server.exitCode === null) {
      server.kill();
      await Promise.race([exited, new Promise<void>((done) => setTimeout(done, 5000))]);
    }
  }
  expect(server.exitCode, "native composition exited cleanly").toBe(0);
  expect(server.signalCode, "no forced termination").toBeNull();
}

const test = auditedTest.extend<{ readinessFixture: Fixture; manualLeaves: boolean; notificationJourney: boolean; officialJourney: boolean; riskJourney: boolean; suspensionJourney: boolean }>({
  manualLeaves: [false, { option: true }],
  notificationJourney: [false, { option: true }],
  officialJourney: [false, { option: true }],
  riskJourney: [false, { option: true }],
  suspensionJourney: [false, { option: true }],
  readinessFixture: async ({ page, context, request, manualLeaves, notificationJourney, officialJourney, riskJourney, suspensionJourney }, use, testInfo) => {
    const port = await freePort(), base = `http://127.0.0.1:${port}`;
    // Playwright's normal outputDir is OS temp. SQLite stays in an independently
    // fresh project-local directory regardless of reporter/output overrides.
    const databaseParent = join(repo, suspensionJourney ? ".pytest_cache/pbs/t12/a11" : ".pytest_cache/pma/t21a/browser-databases");
    await mkdir(databaseParent, { recursive: true });
    const root = await mkdtemp(join(databaseParent, "case-"));
    const pbsBuild = suspensionJourney ? JSON.parse(await readFile(join(repo, "build/pbs/t12/a11/build.json"), "utf8")) : null;
    const server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-X", "utf8", "-m",
      "tests.browser.plan_readiness_server", "--port", String(port), "--root", root,
      ...(suspensionJourney ? ["--scenario", "buy-suspension", "--static-directory",
        pbsBuild.dist] : manualLeaves ? ["--scenario", "manual-leaves"] : notificationJourney ? ["--scenario", "notifications"] : officialJourney ? ["--scenario", "official-wait"] : riskJourney ? ["--scenario", "independent-risk"] : [])],
    { cwd: repo, windowsHide: true, env: { ...process.env, PYTHONUTF8: "1" } });
    let log = "", phase = "RUNNING";
    const record = (value: unknown) => { log = (log + String(value)).slice(-65536); };
    server.stdout?.on("data", record); server.stderr?.on("data", record);
    const external: string[] = [], afterClose: string[] = [];
    const lifecycle: string[] = [];
    const sockets = { opened: 0, serverOpenBeforeStop: null as number | null };
    context.on("request", (req) => {
      const url = new URL(req.url());
      if (url.origin !== base) external.push(req.url());
      if (phase.startsWith("BACKEND_")) afterClose.push(req.url());
    });
    page.on("websocket", (socket) => {
      sockets.opened++;
      if (new URL(socket.url()).host !== new URL(base).host) external.push(socket.url());
    });
    await context.route("**/*", async (route) => {
      if (new URL(route.request().url()).origin !== base) {
        await route.abort("blockedbyclient");
      } else await route.continue();
    });
    try {
      await expect.poll(async () => {
        if (server.exitCode !== null) throw new Error(`Isolated readiness fixture exited: ${log}`);
        try { return (await request.get(base + prefix + "/inspect")).status(); } catch { return 0; }
      }, { timeout: 30000 }).toBe(200);
      const inspect = async (): Promise<Inspection> => {
        const response = await request.get(base + prefix + "/inspect");
        expect(response.status(), await response.text()).toBe(200);
        return response.json();
      };
      const initial = await inspect();
      expect(initial.temporary).toBe(true);
      expect(resolve(initial.root)).toBe(resolve(root));
      expect(resolve(initial.database)).toBe(join(resolve(root), "monitor.sqlite3"));
      expect(initial.cycles).toBe(1);
      expect(initial.externalAttempts).toEqual([]);
      // Preserve real server timestamps/expiry. Only the browser clock is aligned.
      await page.clock.install({ time: new Date(initial.now) });
      await page.clock.pauseAt(new Date(initial.now));
      await use({ base, initial, inspect,
        async read() {
          const response = await request.get(`${base}/api/v1/plan-versions/${initial.planVersionId}/monitor-readiness`);
          expect(response.status(), await response.text()).toBe(200);
          const body: ReadinessAssessment = await response.json();
          expect(body.authorityGranted).toBe(false);
          expect(body.snapshot.context.planVersionId).toBe(initial.planVersionId);
          return body;
        },
        async next() {
          const response = await request.post(base + prefix + "/next-target", { data: {} });
          expect(response.status(), await response.text()).toBe(200);
          return response.json();
        },
      });
      expect((await inspect()).externalAttempts).toEqual([]);
    } finally {
      try {
        lifecycle.push("PAGE_CLOSING");
        if (suspensionJourney && !page.isClosed()) {
          await page.goto("about:blank");
          await expect.poll(async () => {
            const response = await request.get(base + prefix + "/inspect");
            sockets.serverOpenBeforeStop = (await response.json()).browserSockets;
            return sockets.serverOpenBeforeStop;
          }).toBe(0);
          lifecycle.push("SPA_TRANSPORTS_CLOSED");
        }
        await page.close();
        lifecycle.push("PAGE_CLOSED");
      } finally {
        phase = "BACKEND_STOPPING"; lifecycle.push(phase);
        try { await stop(server, request, base); }
        finally {
          phase = "BACKEND_STOPPED"; lifecycle.push(phase);
          await writeFile(testInfo.outputPath("readiness-fixture.log"), log, "utf8");
          await writeFile(testInfo.outputPath("readiness-lifecycle.json"), JSON.stringify({ lifecycle,
            backendExitCode: server.exitCode, backendSignalCode: server.signalCode,
            databaseRoot: root, external, afterClose, sockets }, null, 2), "utf8");
        }
      }
      expect(external, "zero external browser requests including attempted ones").toEqual([]);
      expect(afterClose, "no browser consumers after backend shutdown begins").toEqual([]);
      expect(log).not.toContain("Traceback");
      expect(log).not.toContain("ERROR");
      expect(log).toContain('"lifespanClosed": true, "readOwnerOutstanding": 0, "runtimeState": "STOPPED"');
    }
  },
});

interface ManualEvidence {
  evaluationId: string; nativeCompletionRecordId: string | null;
  evaluation: { signals: unknown[]; ordinary_evaluations: { rule_id: string;
    evidence: { outcome: string; children: { outcome: string; fact_ids: string[] }[] } }[] };
  facts: { id: string; payload: { kind: string; satisfied: boolean;
    reviewed_fact_target?: { condition_path: string } } }[];
  sourceAlignment: { consumedClosedDays: number; sessionsMatchOnlyOpenDays: boolean;
    calendarFingerprintMatches: boolean };
}
const manualTest = test.extend({ manualLeaves: true });
manualTest("H04 actual UI registers separate same-kind leaves and publishes native TRUE/FALSE evidence", async ({ page, request, readinessFixture: fixture }, testInfo) => {
  const saved = await version(request, fixture, fixture.initial.planVersionId);
  const raw = JSON.parse(saved.planJson!);
  expect(raw.schema_version).toBe(5);
  const owner = raw.ordinary_rules[0].rule_id as string;
  const evidence = async (): Promise<ManualEvidence> => {
    const response = await request.get(fixture.base + prefix + "/manual-evidence");
    expect(response.status(), await response.text()).toBe(200);
    return response.json();
  };
  const baseline = await fixture.inspect();
  await page.goto(fixture.base + fixture.initial.planUrl);
  const panel = page.locator(".daily-operations"), form = panel.locator("form.daily-operation");
  const selection = panel.getByLabel("选择本次实际核验的准确条件", { exact: true });
  await expect(selection).toBeEnabled();
  await expect(selection).toHaveValue("");
  const choices = await selection.locator("option").evaluateAll(elements => elements.map(element => ({
    value: (element as HTMLOptionElement).value, text: element.textContent ?? "",
  })));
  expect(choices).toHaveLength(3);
  expect(choices[1]!.text).toContain("成交不异常放大");
  expect(choices[2]!.text).toContain("明显下影");
  const input = form.locator('[id="operation-FACT-.evidence"]');
  const truth = form.locator('[id="operation-FACT-.satisfied"]');
  const submit = form.getByRole("button", { name: "确认登记人工核验证据", exact: true });
  await selection.selectOption(choices[1]!.value);
  await expect(input).toHaveValue("");
  await expect(submit).toBeDisabled();
  await expect(form.locator('input[type="checkbox"]')).toHaveCount(0);
  const firstText = "Synthetic human observation: the exact first volume requirement was checked and satisfied.";
  await input.fill(firstText); await truth.selectOption("0");
  const aResponse = page.waitForResponse(response => response.url().endsWith("/plan-facts") && response.request().method() === "POST");
  await submit.click();
  const a = await aResponse;
  expect(a.status(), await a.text()).toBe(200);
  const aCommand = a.request().postDataJSON(), aReceipt = await a.json();
  expect(aCommand).toMatchObject({ planVersionId: saved.id, contentHash: saved.contentHash,
    kind: "VOLUME_OR_CANDLE", satisfied: true, evidence: firstText,
    conditionSelection: { ownerKind: "ORDINARY_RULE", ownerId: owner, conditionPath: "condition.conditions[0]" } });
  expect(aCommand).not.toHaveProperty("verified");
  await expect(panel).toContainText("已记录并更新当前状态。");
  const nativeA = await evidence();
  expect(nativeA.nativeCompletionRecordId).toBe(nativeA.evaluationId);
  expect(nativeA.evaluation.ordinary_evaluations[0]!.evidence.children.map(leaf => leaf.outcome))
    .toEqual(["SATISFIED", "MISSING_INPUT"]);
  await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
  await expect(pane(page).getByText("condition.conditions[0]", { exact: true }).locator("..")).toContainText("条件已成立");
  await expect(pane(page)).toContainText("缺少必需输入");

  // Fill an unsubmitted A observation, then switch. B must not inherit it.
  await input.fill("Unsubmitted first-leaf observation must be cleared on selection change.");
  await truth.selectOption("0");
  await selection.selectOption(choices[2]!.value);
  await expect(input).toHaveValue("");
  await expect(submit).toBeDisabled();
  await expect(panel.locator(".reviewed-fact-selection blockquote")).toHaveText("明显下影");
  const selectImage = testInfo.outputPath("h04-second-leaf-empty-evidence.png");
  await panel.locator(".reviewed-fact-selection").screenshot({ path: selectImage });
  await testInfo.attach("h04-second-leaf-empty-evidence", { path: selectImage, contentType: "image/png" });
  const secondText = "Synthetic human observation: the exact second candle requirement was checked and NOT satisfied.";
  await input.fill(secondText); await truth.selectOption("1");
  const bResponse = page.waitForResponse(response => response.url().endsWith("/plan-facts") && response.request().method() === "POST");
  await submit.click();
  const b = await bResponse;
  expect(b.status(), await b.text()).toBe(200);
  const bCommand = b.request().postDataJSON(), bReceipt = await b.json();
  expect(bCommand).toMatchObject({ planVersionId: saved.id, contentHash: saved.contentHash,
    kind: "VOLUME_OR_CANDLE", satisfied: false, evidence: secondText,
    conditionSelection: { ownerKind: "ORDINARY_RULE", ownerId: owner, conditionPath: "condition.conditions[1]" } });
  expect(bCommand.factId).not.toBe(aCommand.factId);
  expect(bCommand).not.toHaveProperty("verified");
  await expect(panel).toContainText("已记录并更新当前状态。");
  const nativeB = await evidence();
  expect(nativeB.nativeCompletionRecordId).toBe(nativeB.evaluationId);
  expect(nativeB.evaluationId).not.toBe(nativeA.evaluationId);
  const root = nativeB.evaluation.ordinary_evaluations[0]!.evidence;
  expect(root.outcome).toBe("UNSATISFIED");
  expect(root.children.map(leaf => leaf.outcome)).toEqual(["SATISFIED", "UNSATISFIED"]);
  expect(root.children.map(leaf => leaf.fact_ids)).toEqual([[aReceipt.id], [bReceipt.id]]);
  expect(nativeB.evaluation.signals).toEqual([]);
  expect(nativeB.facts.find(fact => fact.id === bReceipt.id)?.payload.satisfied).toBe(false);
  expect(nativeB.sourceAlignment).toMatchObject({ sessionsMatchOnlyOpenDays: true, calendarFingerprintMatches: true });
  expect(nativeB.sourceAlignment.consumedClosedDays).toBeGreaterThan(0);
  await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
  await expect(pane(page)).toContainText("条件未成立（已完成检查）");
  const current = await fixture.read();
  expect(current.rules[0]!.facts.leaves.map(leaf => leaf.state)).toEqual(["CONDITION_TRUE", "CONDITION_FALSE"]);
  for (const leaf of current.rules[0]!.facts.leaves) expect(leaf.evidenceRefs).toEqual([nativeB.evaluationId]);
  const beforeRejected = await fixture.inspect();
  const rejected = await command(request, fixture, "/api/v1/plan-facts", { ...bCommand,
    factId: "must-not-create-" + randomUUID(), conditionSelection: { ...bCommand.conditionSelection, conditionPath: "condition.conditions[99]" } });
  expect([404, 409, 422]).toContain(rejected.status());
  expect((await fixture.inspect()).storage).toEqual(beforeRejected.storage);
  expect(beforeRejected.storage.dailyKinds.FACT).toBe((baseline.storage.dailyKinds.FACT ?? 0) + 2);
  expect(beforeRejected.storage.source_coverage_review).toEqual(baseline.storage.source_coverage_review);
  await page.setViewportSize({ width: 1280, height: 2600 });
  const heading = pane(page).getByRole("heading", { name: "逐规则监控就绪", exact: true });
  await heading.click();
  await heading.evaluate(element => { element.scrollIntoView({ block: "start" }); window.scrollBy(0, -96); });
  await page.clock.runFor(64);
  const image = testInfo.outputPath("h04-native-separate-true-false.png");
  await pane(page).screenshot({ path: image });
  await testInfo.attach("h04-native-separate-true-false", { path: image, contentType: "image/png" });
  await testInfo.attach("h04-actual-public-native-evidence", { contentType: "application/json", body: JSON.stringify({
    aCommand, aReceipt, bCommand, bReceipt, nativeA, nativeB, current, rejected: await rejected.json(),
    baseline, after: beforeRejected, scope: "schema5 ordinary REVIEWED_FACT/TRADE_DATE only; two explicit human observations; no simulated trade or automatic human confirmation",
  }, null, 2) });
});

function pane(page: Page) { return page.getByRole("region", { name: "逐规则监控就绪", exact: true }); }
async function open(page: Page, fixture: Fixture) {
  const response = page.waitForResponse(result => result.url().endsWith("/monitor-readiness"));
  await page.goto(fixture.base + fixture.initial.planUrl);
  const actual: ReadinessAssessment = await (await response).json();
  expect(Date.parse(actual.freshUntil!), `original server expiry ${actual.freshUntil}, computed ${actual.snapshot.computedAt}, fixture ${fixture.initial.now}`)
    .toBeGreaterThan(await page.evaluate(() => Date.now()));
  await expect(pane(page)).toContainText("监控已就绪");
  await expect(pane(page)).toContainText("条件未成立（已完成检查）");
}

test("native FALSE is shown by the actual workbench and survives refresh/reload", async ({ page, readinessFixture: fixture }, testInfo) => {
  const before = await fixture.inspect(), native = await fixture.read();
  await testInfo.attach("original-before-navigation", { contentType: "application/json", body: JSON.stringify({ before, native }, null, 2) });
  expect(native.summary).toBe("READY_FOR_MONITORING");
  await open(page, fixture);
  await expect(pane(page).getByLabel("监控依赖").locator("li")).toHaveCount(6);
  await expect(pane(page)).toContainText("未要求库存或金额输入");
  await expect(pane(page)).toContainText("当前发送资格：未验证");
  const read = page.waitForResponse((response) => response.url().endsWith("/monitor-readiness"));
  await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
  expect(await (await read).json()).toEqual(native);
  await expect(pane(page)).toContainText("监控已就绪");
  await page.reload();
  await expect(pane(page)).toContainText("监控已就绪");
  expect((await fixture.inspect()).storage).toEqual(before.storage);
  expect((await fixture.inspect()).sdkCalls).toBe(before.sdkCalls);
  await testInfo.attach("actual-public-readiness", { contentType: "application/json", body: JSON.stringify(native, null, 2) });
});

test("two native scheduled targets evaluate an unchanged reviewed rule without new manual facts", async ({ page, readinessFixture: fixture }, testInfo) => {
  const before = await fixture.inspect(), first = await fixture.read();
  await open(page, fixture);
  // Detach document-owned pollers before this fixture's virtual five-minute
  // scheduler drive. Reads racing an intentionally advanced clock belong to
  // the separate context-race slice; no response or diagnostic is suppressed.
  await page.goto("about:blank");
  const after = await fixture.next();
  await page.clock.setSystemTime(new Date(after.now));
  const second = await fixture.read();
  expect(second.summary).toBe("READY_FOR_MONITORING");
  expect(second.snapshot.context).toEqual(first.snapshot.context);
  expect(second.rules[0]!.facts.evaluatedTarget).not.toEqual(first.rules[0]!.facts.evaluatedTarget);
  expect(second.rules[0]!.facts.evaluatedAt).not.toBe(first.rules[0]!.facts.evaluatedAt);
  expect(after.completionResultHash).not.toBe(before.completionResultHash);
  expect(after.storage.dailyKinds.EVALUATION).toBeGreaterThan(before.storage.dailyKinds.EVALUATION!);
  expect(after.storage.dailyKinds.FACT ?? 0).toBe(before.storage.dailyKinds.FACT ?? 0);
  for (const table of ["source_coverage_review", "plan_review_provenance", "plan_version"])
    expect(after.storage[table]).toEqual(before.storage[table]);
  await open(page, fixture);
  const target = second.rules[0]!.facts.evaluatedTarget;
  expect(target?.kind).toBe("INTRADAY");
  if (target?.kind === "INTRADAY") await expect(pane(page)).toContainText(target.bucket_end.replace("T", " "));
  await testInfo.attach("automatic-evaluation-evidence", { contentType: "application/json", body: JSON.stringify({ before, after, first, second,
    scope: "one automatic alert condition; fixture initial review retained; zero additional FACT/review" }, null, 2) });
});

// This recovery case retains every real dashboard 503 and requires a later
// successful native read. The unchanged journeys keep the strict zero-error audit.
const recoveryTest = test.extend<{ calendarTransition: { open: boolean } }>({
  calendarTransition: async ({}, use) => { await use({ open: false }); },
  browserAudit: async ({ page, calendarTransition }, use, testInfo) => {
    const messages: { type: string; text: string; url: string }[] = [];
    const failures: string[] = [], pageErrors: string[] = [];
    const responses: { url: string; status: number; body: unknown; transition: boolean; sameOrigin: boolean; method: string }[] = [];
    const pending: Promise<void>[] = [];
    page.on("console", message => {
      if (["error", "warning"].includes(message.type())) messages.push({
        type: message.type(), text: message.text(), url: message.location().url,
      });
    });
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("requestfailed", request => {
      if (request.failure()?.errorText !== "net::ERR_ABORTED") failures.push(`${request.url()}: ${request.failure()?.errorText}`);
    });
    page.on("response", response => {
      if (new URL(response.url()).pathname === "/api/v1/dashboard") {
        const row = { url: response.url(), status: response.status(), body: null as unknown,
          transition: calendarTransition.open, method: response.request().method(),
          sameOrigin: new URL(response.url()).origin === new URL(page.url()).origin };
        responses.push(row);
        pending.push(response.json().then(body => { row.body = body; }));
      }
    });
    await use();
    await Promise.all(pending);
    await testInfo.attach("native-recovery-browser-audit", { contentType: "application/json",
      body: JSON.stringify({ messages, failures, pageErrors, responses }, null, 2) });
    expect(failures).toEqual([]); expect(pageErrors).toEqual([]);
    for (const [index, response] of responses.entries()) {
      expect([200, 503]).toContain(response.status);
      if (response.status === 503) {
        expect(response.transition, "503 limited to the actual next-duty/reconnect window").toBe(true);
        expect(response.sameOrigin).toBe(true); expect(response.method).toBe("GET");
        expect(response.body).toMatchObject({ error: { code: "SERVICE_UNAVAILABLE" } });
        expect(responses.slice(index + 1).some(next => next.url === response.url && next.status === 200),
          "every actual temporary dashboard 503 is followed by successful application recovery").toBe(true);
      }
    }
    for (const message of messages) {
      expect(message.type).toBe("error");
      expect(message.text).toBe("Failed to load resource: the server responded with a status of 503 (Service Unavailable)");
      expect(responses.some(response => response.status === 503 && response.url === message.url)).toBe(true);
    }
  },
});
recoveryTest("native calendar loss and next-cycle recovery update the same open page", async ({ page, request, calendarTransition, readinessFixture: fixture }, testInfo) => {
  const initial = await fixture.inspect(), first = await fixture.read();
  const observations: { phase: string; status: number; body: unknown }[] = [];
  const pending: Promise<void>[] = [];
  let phase = "INITIAL", navigations = 0;
  page.on("request", request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations++; });
  page.on("response", response => {
    if (response.url().endsWith("/monitor-readiness")) {
      const captured = phase;
      pending.push(response.json().then(body => {
        observations.push({ phase: captured, status: response.status(), body });
      }));
    }
  });
  const refresh = async () => {
    const read = page.waitForResponse(response => response.url().endsWith("/monitor-readiness"));
    await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
    const response = await read;
    expect(response.status(), await response.text()).toBe(200);
    return await response.json() as ReadinessAssessment;
  };
  const snapshots: Record<string, unknown> = { initial, first };
  try {
    await open(page, fixture);
    const originalPane = await pane(page).elementHandle();
    const documentIdentity = await page.evaluate(() => performance.timeOrigin);
    phase = "MISSING_CALENDAR_ROW";
    const loss = await command(request, fixture, prefix + "/calendar-loss", {});
    expect(loss.status(), await loss.text()).toBe(200);
    snapshots.removed = await loss.json();
    const lost = await refresh(); snapshots.lost = lost;
    expect(lost.summary).toBe("UNKNOWN");
    expect(lost.rules[0]!.state).toBe("UNKNOWN");
    await expect(pane(page)).not.toContainText("监控已就绪");
    await expect(pane(page)).toContainText("当前运行依据不可用");
    expect((await fixture.inspect()).completionRecordId).toBe(initial.completionRecordId);
    await page.setViewportSize({ width: 1280, height: 2600 });
    for (const label of ["missing", "recovered"]) {
      if (label === "recovered") {
        phase = "EXACT_ROW_RESTORED";
        const restore = await command(request, fixture, prefix + "/calendar-restore", {});
        expect(restore.status(), await restore.text()).toBe(200);
        snapshots.restored = await restore.json();
        const interim = await refresh(); snapshots.interim = interim;
        expect(interim.snapshot.computedAt).toBe(first.snapshot.computedAt);
        expect(interim.summary).toBe("READY_FOR_MONITORING");
        expect(interim.rules[0]!.state).toBe("CONDITION_FALSE");
        expect(interim.freshUntil).toBe(first.freshUntil);
        await expect(pane(page)).toContainText("监控已就绪");
        expect((await fixture.inspect()).completionRecordId).toBe(initial.completionRecordId);
        expect((await fixture.inspect()).storage).toEqual(initial.storage);
        phase = "REAL_NEXT_CYCLE";
        calendarTransition.open = true;
        const after = await fixture.next(); snapshots.after = after;
        await page.clock.setSystemTime(new Date(after.now));
        const current = await refresh(); snapshots.current = current;
        expect(current.summary).toBe("READY_FOR_MONITORING");
        expect(current.rules[0]!.state).toBe("CONDITION_FALSE");
        expect(after.completionRecordId).not.toBe(initial.completionRecordId);
        expect(current.rules[0]!.facts.leaves[0]!.evidenceRefs).toEqual([after.completionRecordId]);
        expect(current.rules[0]!.facts.evaluatedTarget).not.toEqual(first.rules[0]!.facts.evaluatedTarget);
        for (const table of ["plan_version", "source_coverage_review", "plan_review_provenance", "plan_activation_state", "active_plan"])
          expect(after.storage[table]).toEqual(initial.storage[table]);
        expect(after.storage.dailyKinds.FACT ?? 0).toBe(initial.storage.dailyKinds.FACT ?? 0);
        expect(after.externalAttempts).toEqual([]);
        await expect(pane(page)).toContainText("监控已就绪");
        await expect(pane(page)).toContainText("条件未成立（已完成检查）");
        // Permit the unchanged application's own bounded reconnect timer to run;
        // this advances only browser time, never server proofs or fixture duties.
        await page.clock.runFor(2000);
        calendarTransition.open = false;
      }
      await pane(page).getByRole("heading", { name: "逐规则监控就绪", exact: true }).scrollIntoViewIfNeeded();
      await page.clock.runFor(64);
      const image = testInfo.outputPath(`calendar-${label}.png`);
      await pane(page).screenshot({ path: image });
      await testInfo.attach(`calendar-${label}`, { path: image, contentType: "image/png" });
    }
    expect(navigations, "one original navigation; page never leaves or reloads").toBe(1);
    expect(await originalPane!.evaluate(element => element.isConnected)).toBe(true);
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentIdentity);
    expect(page.url()).toBe(fixture.base + fixture.initial.planUrl);
  } finally {
    await Promise.all(pending);
    await testInfo.attach("native-calendar-recovery", { contentType: "application/json", body: JSON.stringify({
      snapshots, observations, navigations, scope: "fixed automatic alert; exact temporary calendar row; same document; real next duty",
    }, null, 2) });
  }
});

const notificationTest = recoveryTest.extend({ notificationJourney: true });
for (const loss of ["closed", "expired"] as const) {
  notificationTest(`native two-alert receipts remain historical when notification service is ${loss}`, async ({ page, request, readinessFixture: fixture, calendarTransition }, testInfo) => {
    const snapshots: Record<string, unknown> = {};
    const channel = (rule: ReadinessAssessment["rules"][number]) => rule.facts.notification!.channels!.find(row => row.channel === "IN_APP")!;
    const axis = (value: ReadinessAssessment) => value.axes.find(row => row.axis === "NOTIFICATION_DELIVERY")!;
    const refresh = async () => {
      const read = page.waitForResponse(response => response.url().endsWith("/monitor-readiness"));
      await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
      const response = await read;
      expect(response.status(), await response.text()).toBe(200);
      return await response.json() as ReadinessAssessment;
    };
    const screenshot = async (label: string) => {
      await page.setViewportSize({ width: 1280, height: 2800 });
      await pane(page).getByRole("heading", { name: "逐规则监控就绪", exact: true }).scrollIntoViewIfNeeded();
      await page.clock.runFor(64);
      const image = testInfo.outputPath(`notification-${label}.png`);
      await pane(page).screenshot({ path: image });
      await testInfo.attach(`notification-${label}`, { path: image, contentType: "image/png" });
    };
    try {
      const opening = page.waitForResponse(response => response.url().endsWith("/monitor-readiness"));
      await page.goto(fixture.base + fixture.initial.planUrl);
      const partial: ReadinessAssessment = await (await opening).json(); snapshots.partial = partial;
      const originalPane = await pane(page).elementHandle();
      const documentIdentity = await page.evaluate(() => performance.timeOrigin);
      expect(partial.rules).toHaveLength(2);
      expect(partial.rules.every(row => row.state === "CONDITION_TRUE")).toBe(true);
      expect(partial.rules.filter(row => channel(row).latestAttempt?.status === "DELIVERED")).toHaveLength(1);
      expect(axis(partial).state).toBe("UNKNOWN");
      await expect(pane(page)).not.toContainText("监控已就绪");
      for (const row of partial.rules) {
        const rendered = pane(page).getByRole("heading", { name: `提醒规则 · ${row.facts.ownerId}`, exact: true }).locator("..");
        await expect(rendered).toContainText(channel(row).latestAttempt ? "历史发送结果：已送达" : "历史发送结果：未验证");
      }
      await screenshot("partial");
      calendarTransition.open = true;
      const check = await command(request, fixture, prefix + "/notification-next-check", {});
      expect(check.status(), await check.text()).toBe(200);
      const after: Inspection = await check.json(); snapshots.after = after;
      await page.clock.setSystemTime(new Date(after.now));
      const complete = await refresh(); snapshots.complete = complete;
      expect(axis(complete).state).toBe("PASS");
      expect(complete.summary).toBe("READY_FOR_MONITORING");
      const attempts = complete.rules.map(row => channel(row).latestAttempt!);
      expect(new Set(attempts.map(row => row.id)).size).toBe(2);
      expect(new Set(attempts.map(row => row.eventId)).size).toBe(2);
      for (const row of complete.rules) {
        expect(channel(row).latestAttempt).toMatchObject({ status: "DELIVERED", eventId: row.facts.notification!.eventId });
        expect(channel(row).eligible == null).toBe(true);
        const prior = partial.rules.find(old => old.facts.ownerId === row.facts.ownerId)!;
        if (channel(prior).latestAttempt) expect(channel(row).latestAttempt).toEqual(channel(prior).latestAttempt);
      }
      await page.clock.runFor(2000);
      calendarTransition.open = false;
      await expect(pane(page)).toContainText("监控已就绪");
      await screenshot("complete");
      const ending = await command(request, fixture, prefix + (loss === "closed" ? "/notification-close" : "/notification-expire"), {});
      expect(ending.status(), await ending.text()).toBe(200);
      const ended: Inspection = await ending.json(); snapshots.ended = ended;
      await page.clock.setSystemTime(new Date(ended.now));
      const lost = await refresh(); snapshots.lost = lost;
      expect(lost.summary).toBe("UNKNOWN"); expect(lost.freshUntil).toBeNull();
      expect(axis(lost).state).toBe("UNKNOWN");
      for (const row of lost.rules) {
        const prior = complete.rules.find(old => old.facts.ownerId === row.facts.ownerId)!;
        expect(channel(row).latestAttempt).toEqual(channel(prior).latestAttempt);
        expect(channel(row).eligible == null).toBe(true);
        expect(row.facts.notification!.createdAt).toBe(prior.facts.notification!.createdAt);
        expect(row.facts.notification!.target).toEqual(prior.facts.notification!.target);
        const rendered = pane(page).getByRole("heading", { name: `提醒规则 · ${row.facts.ownerId}`, exact: true }).locator("..");
        await expect(rendered).toContainText("历史发送结果：已送达");
        await expect(rendered).toContainText("当前发送资格：未验证");
      }
      await expect(pane(page)).not.toContainText("监控已就绪");
      expect(await refresh()).toEqual(lost);
      expect((await fixture.inspect()).storage).toEqual(after.storage);
      for (const table of ["plan_version", "source_coverage_review", "plan_review_provenance", "active_plan", "plan_activation_state"])
        expect(after.storage[table]).toEqual(fixture.initial.storage[table]);
      expect(after.storage.dailyKinds.FACT ?? 0).toBe(0);
      expect(after.storage.delivery_attempt).toMatchObject({ count: 2 });
      expect(await originalPane!.evaluate(element => element.isConnected)).toBe(true);
      expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentIdentity);
      await screenshot(`history-${loss}`);
    } finally {
      await testInfo.attach("native-notification-history", { contentType: "application/json", body: JSON.stringify({ loss, initial: fixture.initial, snapshots }, null, 2) });
    }
  });
}

const officialTest = recoveryTest.extend({ officialJourney: true });
officialTest("native official-close waiting preserves prior proof and rejects missing prior input", async ({ page, request, readinessFixture: fixture, calendarTransition }, testInfo) => {
  const snapshots: Record<string, unknown> = {};
  const daily = (value: ReadinessAssessment) => value.rules.find(row => row.facts.ownerKind === "ORDINARY_RULE")!;
  const refresh = async () => {
    const response = page.waitForResponse(result => result.url().endsWith("/monitor-readiness"));
    await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
    const actual = await response;
    expect(actual.status(), await actual.text()).toBe(200);
    return await actual.json() as ReadinessAssessment;
  };
  const screenshot = async (label: string) => {
    await page.setViewportSize({ width: 1280, height: 2800 });
    await pane(page).getByRole("heading", { name: "逐规则监控就绪", exact: true }).scrollIntoViewIfNeeded();
    await page.clock.runFor(64);
    const image = testInfo.outputPath(`official-${label}.png`);
    await pane(page).screenshot({ path: image });
    await testInfo.attach(`official-${label}`, { path: image, contentType: "image/png" });
  };
  try {
    const initialRead = page.waitForResponse(result => result.url().endsWith("/monitor-readiness"));
    await page.goto(fixture.base + fixture.initial.planUrl);
    const initialResponse = await initialRead;
    expect(initialResponse.status()).toBe(200);
    const initial: ReadinessAssessment = await initialResponse.json(); snapshots.initial = initial;
    const row = daily(initial), facts = row.facts;
    expect(row.state).toBe("WAITING_OFFICIAL_CONFIRMATION");
    expect(facts.rootOutcome).toBe("UNSATISFIED");
    expect(facts.evaluatedTarget).toEqual({ kind: "OFFICIAL_CLOSE", trade_date: "2026-09-07" });
    expect(facts.expectedTarget).toEqual({ kind: "OFFICIAL_CLOSE", trade_date: "2026-09-08" });
    expect(facts.expectedConfirmation).toMatchObject({
      target: facts.expectedTarget, expectedAt: "2026-09-08T15:00:00+08:00", priorInputsComplete: true,
    });
    expect(facts.leaves[0]!.evidenceRefs).toEqual([fixture.initial.completionRecordId]);
    expect(initial.authorityGranted).toBe(false);
    const rendered = pane(page).getByRole("heading", { name: `普通规则 · ${facts.ownerId}`, exact: true }).locator("..");
    const originalPane = await pane(page).elementHandle();
    const documentIdentity = await page.evaluate(() => performance.timeOrigin);
    await expect(rendered).toContainText("正常等待官方确认");
    await expect(rendered).toContainText("预期目标：官方收盘 · 交易日期 2026-09-08");
    await expect(rendered).toContainText("实际已评估目标：官方收盘 · 交易日期 2026-09-07");
    await expect(rendered).toContainText("2026-09-08 15:00:00+08:00");
    expect(await refresh()).toEqual(initial);
    expect(await fixture.inspect()).toEqual(fixture.initial);
    await screenshot("waiting");
    calendarTransition.open = true;
    const loss = await command(request, fixture, prefix + "/official-history-loss", {});
    expect(loss.status(), await loss.text()).toBe(200);
    const missing = await loss.json(); snapshots.loss = missing;
    expect(missing).toMatchObject({ removedTradeDate: "2026-09-07", preparedOfficialTradeDate: "2026-09-07",
      preparedSeriesLastDate: "2026-09-04", nativeDailyAdmissionPresent: false, blockers: [],
      providerRows: { request: { ts_code: "003043.SZ", end_date: "20260907" } } });
    expect(missing.providerRows.before - missing.providerRows.after).toBe(1);
    const lost = await refresh(); snapshots.lost = lost;
    expect(daily(lost).state).toBe("UNKNOWN");
    expect(daily(lost).reason).toBe("AUTHORITY_UNAVAILABLE");
    expect(daily(lost).facts.expectedConfirmation).toBeNull();
    expect(lost.rules.find(row => row.facts.ownerKind === "ALERT_RULE")!.state).toBe("CONDITION_FALSE");
    expect(lost.summary).not.toBe("READY_FOR_MONITORING");
    await expect(rendered).not.toContainText("正常等待官方确认");
    await expect(rendered).toContainText("尚未确定");
    expect(await refresh()).toEqual(lost);
    const after = await fixture.inspect(); snapshots.after = after;
    expect(after.completionRecordId).toBe(fixture.initial.completionRecordId);
    expect(after.storage).toEqual(fixture.initial.storage);
    await page.clock.runFor(2000); calendarTransition.open = false;
    expect(await originalPane!.evaluate(element => element.isConnected)).toBe(true);
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentIdentity);
    await screenshot("missing-history");
  } finally {
    await testInfo.attach("native-official-wait-evidence", { contentType: "application/json", body: JSON.stringify({ initialInspection: fixture.initial, snapshots }, null, 2) });
  }
});

const riskTest = recoveryTest.extend({ riskJourney: true });
riskTest("native independent risk keeps the confirmed obligation and original source after current FALSE", async ({ page, request, readinessFixture: fixture, calendarTransition }, testInfo) => {
  const evidence: unknown[] = [];
  let origin: NonNullable<NonNullable<ReadinessAssessment["rules"][number]["facts"]["risk"]>["origin"]> | null = null;
  try {
    const initialRead = page.waitForResponse(response => response.url().endsWith("/monitor-readiness"));
    await page.goto(fixture.base + fixture.initial.planUrl); await initialRead;
    const originalPane = await pane(page).elementHandle();
    const documentIdentity = await page.evaluate(() => performance.timeOrigin);
    for (const [index, outcome] of ["SATISFIED", "UNSATISFIED"].entries()) {
      calendarTransition.open = true;
      const commandResult = await command(request, fixture, prefix + "/risk-next-close", {});
      expect(commandResult.status(), await commandResult.text()).toBe(200);
      const step: { inspection: Inspection; tradeDate: string; observedAt: string;
        nativeRiskAction: { status: string; tactical_qty: number; unavailable_tactical_qty: number; blockers: string[] } } = await commandResult.json();
      await page.clock.setSystemTime(new Date(step.inspection.now));
      const read = page.waitForResponse(response => response.url().endsWith("/monitor-readiness"));
      await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
      const response = await read; expect(response.status(), await response.text()).toBe(200);
      const value: ReadinessAssessment = await response.json(); evidence.push({ step, value });
      const buy = value.rules.find(row => row.facts.side === "BUY")!;
      expect(buy.facts.requirements.costBasis).toBe(true);
      expect(buy.facts.money!.inputs.state).toBe("UNKNOWN");
      expect(buy.facts.money!.capital == null).toBe(true);
      expect(value.snapshot.context.bookRevision).toBeNull();
      const risk = value.rules.find(row => row.facts.ownerId === "independent-risk")!;
      const facts = risk.facts.risk!;
      expect(facts.current!.evidence!.outcome).toBe(outcome);
      expect(facts.current!.target).toEqual({ kind: "OFFICIAL_CLOSE", trade_date: step.tradeDate });
      expect(facts.current!.evaluated_at).toBe(`${step.tradeDate}T15:20:00+08:00`);
      expect(facts.obligation!.status).toBe("CONFIRMED");
      expect(facts.maintenance.state).toBe("PASS");
      expect(facts.origin).toBeTruthy();
      if (index === 0) {
        origin = facts.origin!;
        expect(origin).toMatchObject({ evaluationId: step.inspection.completionRecordId,
          planVersionId: fixture.initial.planVersionId, contentHash: value.snapshot.context.contentHash });
        expect(step.nativeRiskAction.status).toBe("WAITING");
      } else {
        expect(facts.origin).toEqual(origin);
        expect(step.inspection.completionRecordId).not.toBe(origin!.evaluationId);
        expect(step.nativeRiskAction).toMatchObject({ status: "RISK_EXIT", tactical_qty: 0,
          unavailable_tactical_qty: 100, blockers: ["WAIT_FOR_CERTIFIED_TRADABILITY"] });
      }
      expect(step.nativeRiskAction.tactical_qty).toBe(0);
      expect(value.summary).not.toBe("READY_FOR_MONITORING");
      const riskRow = pane(page).getByRole("heading", { name: "独立风险 · independent-risk", exact: true }).locator("..");
      const buyRow = pane(page).getByRole("heading", { name: `普通规则 · ${buy.facts.ownerId}`, exact: true }).locator("..");
      await expect(buyRow).toContainText("持仓成本");
      await expect(buyRow).toContainText("金额所需输入：尚未确定");
      await expect(riskRow).toContainText(index === 0 ? "条件已成立" : "条件未成立（已完成检查）");
      await expect(riskRow).toContainText("风险义务：已确认");
      await expect(riskRow).toContainText("风险义务维护：通过");
      await expect(riskRow).toContainText(`原属版本：${origin!.planVersionId}`);
      await expect(riskRow).toContainText(`原确认依据时间：${origin!.evaluatedAt.replace("T", " ")}`);
      await expect(riskRow).not.toContainText("交易资格：符合");
      await page.clock.runFor(2000); calendarTransition.open = false;
      await page.setViewportSize({ width: 1280, height: 2800 });
      await pane(page).getByRole("heading", { name: "逐规则监控就绪", exact: true }).scrollIntoViewIfNeeded();
      await page.clock.runFor(64);
      const image = testInfo.outputPath(`risk-${index === 0 ? "confirmed" : "current-false"}.png`);
      await pane(page).screenshot({ path: image });
      await testInfo.attach(`risk-${index}`, { path: image, contentType: "image/png" });
    }
    expect(await originalPane!.evaluate(element => element.isConnected)).toBe(true);
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(documentIdentity);
    const after = await fixture.inspect();
    for (const table of ["plan_version", "source_coverage_review", "plan_review_provenance", "active_plan", "plan_activation_state"])
      expect(after.storage[table]).toEqual(fixture.initial.storage[table]);
    expect(after.storage.dailyKinds.FACT ?? 0).toBe(0);
  } finally {
    await testInfo.attach("native-independent-risk-evidence", { contentType: "application/json", body: JSON.stringify({ initial: fixture.initial, evidence }, null, 2) });
  }
});

test("readiness fits four widths and exposes native keyboard focus and local WCAG evidence", async ({ page, readinessFixture: fixture }, testInfo) => {
  await open(page, fixture);
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(async () => { await document.fonts.ready; });
    await page.clock.runFor(64);
    await pane(page).getByRole("heading", { name: "逐规则监控就绪", exact: true }).scrollIntoViewIfNeeded();
    const settled = await pane(page).boundingBox();
    await page.clock.runFor(64);
    expect(await pane(page).boundingBox(), `layout settled at ${width}`).toEqual(settled);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`).toBe(true);
    const heights = await pane(page).getByRole("button").evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height));
    expect(heights.length).toBeGreaterThan(0);
    expect(heights.every(height => height >= 44), `44px controls at ${width}`).toBe(true);
    const path = testInfo.outputPath(`readiness-${width}.png`);
    await page.screenshot({ path });
    await testInfo.attach(`readiness-${width}`, { path, contentType: "image/png" });
    if (width === 320 || width === 1440) {
      const regionPath = testInfo.outputPath(`readiness-region-${width}.png`);
      await pane(page).screenshot({ path: regionPath });
      await testInfo.attach(`readiness-region-${width}`, { path: regionPath, contentType: "image/png" });
    }
  }
  const locate = pane(page).getByRole("button", { name: "定位规则来源字段", exact: true });
  const refresh = pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true });
  await refresh.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(locate).toBeFocused();
  await page.keyboard.press("Enter");
  const field = page.locator('[id="daily-.alert_rules[0].rule_id"]');
  await expect(field).toBeFocused();
  expect(await field.evaluate(element => getComputedStyle(element).outlineStyle)).not.toBe("none");
  await refresh.focus(); await page.keyboard.press("Enter");
  await expect(pane(page)).toContainText("监控已就绪");
  const axeUrl = fixture.base + prefix + "/axe-core.js";
  const script = await readFile(axePath, "utf8");
  await page.route(axeUrl, route => route.fulfill({ contentType: "application/javascript; charset=utf-8", body: script }));
  await page.addScriptTag({ url: axeUrl });
  // axe chains timer-based work. Resume this aligned clock for the scan;
  // the original server deadline and all freshness checks remain in force.
  await page.clock.resume();
  const violations = await pane(page).evaluate(async element => {
    const axe = (globalThis as typeof globalThis & { axe: { run(root: Element, options: object): Promise<{ violations: unknown[] }> } }).axe;
    return (await axe.run(element, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] })).violations;
  });
  expect(violations).toEqual([]);
  await testInfo.attach("local-axe-results", { contentType: "application/json", body: JSON.stringify({
    scope: "逐规则监控就绪 region only", runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"], violations,
  }) });
});

test("the original public expiry removes current readiness without renewing backend evidence", async ({ page, readinessFixture: fixture }, testInfo) => {
  const before = await fixture.inspect(), actual = await fixture.read();
  expect(actual.freshUntil).not.toBeNull();
  await open(page, fixture);
  const budget = Date.parse(actual.freshUntil!) - Date.parse(fixture.initial.now);
  expect(budget).toBeGreaterThan(0);
  await page.clock.runFor(budget + 1);
  await expect(pane(page)).toContainText("本次监控依据已过期，请重新读取。");
  await expect(pane(page)).not.toContainText("监控已就绪");
  expect(await fixture.read()).toEqual(actual);
  expect(await fixture.inspect()).toEqual(before);
  await testInfo.attach("original-expiry", { contentType: "application/json", body: JSON.stringify({
    serverComputedAt: actual.snapshot.computedAt, originalFreshUntil: actual.freshUntil,
    browserAdvancedMilliseconds: budget + 1, serverEvidenceUnchanged: true,
  }, null, 2) });
});

interface SourceCase {
  versionIds: string[]; repairPath: string; clauseId: string; requirement: string;
}
async function command(request: APIRequestContext, fixture: Fixture, path: string, body: unknown) {
  return request.post(fixture.base + path, { data: body, headers: {
    "Idempotency-Key": randomUUID(), "X-Monitor-Contract-Version": "2",
  } });
}
async function sourceCase(request: APIRequestContext, fixture: Fixture, scenario: "repair" | "contexts"): Promise<SourceCase> {
  const response = await command(request, fixture, prefix + "/source-case", { scenario });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}
async function version(request: APIRequestContext, fixture: Fixture, id: string): Promise<PlanVersionView> {
  const response = await request.get(`${fixture.base}/api/v1/plan-versions/${id}`);
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}
function reviewBody(saved: PlanVersionView): PlanReviewConfirmationCommand {
  return { planVersionId: saved.id, sourceHash: saved.sourceHash!, contentHash: saved.contentHash!,
    reviewEvidenceHash: saved.reviewEvidenceHash!, expectedRevision: saved.reviewRevision!,
    coverageEvidenceHash: saved.sourceCoverage!.coverageEvidenceHash!,
    coverageRulesVersion: saved.sourceCoverage!.rulesVersion! };
}
function activationBody(saved: PlanVersionView, expectedRevision: number) {
  return { planVersionId: saved.id, sourceHash: saved.sourceHash, contentHash: saved.contentHash,
    reviewEvidenceHash: saved.reviewEvidenceHash, reviewId: saved.reviewId,
    reviewRevision: saved.reviewRevision, expectedRevision };
}
async function deniedWithoutWrites(request: APIRequestContext, fixture: Fixture, path: string, body: unknown) {
  const before = (await fixture.inspect()).storage;
  const response = await command(request, fixture, path, body);
  expect(response.status(), await response.text()).toBe(409);
  const error = await response.json();
  expect(error.error.details).not.toContainEqual(expect.objectContaining({ code: "MONITOR_CONTRACT_MISMATCH" }));
  expect((await fixture.inspect()).storage).toEqual(before);
  return error;
}
const coveragePane = (page: Page) => page.getByRole("region", { name: "原文条件核对", exact: true });

test("source repair preserves a mislabelled mandatory condition and explicitly re-reviews the exact saved version", async ({ page, request, readinessFixture: fixture }, testInfo) => {
  const setup = await sourceCase(request, fixture, "repair");
  const saved = await version(request, fixture, setup.versionIds[0]!);
  const originalReview = await version(request, fixture, fixture.initial.planVersionId);
  expect(saved.sourceCoverage?.coverageComplete).toBe(false);
  expect(saved.sourceText).toContain(setup.requirement);
  const rejected = [
    await deniedWithoutWrites(request, fixture, "/api/v1/plan-review-confirmations", reviewBody(saved)),
    await deniedWithoutWrites(request, fixture, "/api/v1/plan-activations", activationBody(saved, 1)),
  ];
  await page.goto(`${fixture.base}/plans/${saved.id}`);
  await expect(coveragePane(page)).toContainText("原文条件仍有待解决项");
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "启用当前审核绑定", exact: true })).toBeDisabled();
  const row = page.locator(".daily-review__row").filter({ has: page.locator("blockquote").filter({ hasText: setup.requirement }) });
  await expect(row).toContainText("CONTEXT");
  await row.scrollIntoViewIfNeeded();
  const blockedImage = testInfo.outputPath("source-repair-blocked-clause.png");
  await row.screenshot({ path: blockedImage });
  await testInfo.attach("source-repair-blocked-clause", { path: blockedImage, contentType: "image/png" });
  const reason = "Explicitly retain the original 4000-fen condition and its exact alert owner; no requirement or permission is waived.";
  await page.locator(`[id="paths-${setup.clauseId}"]`).fill(setup.repairPath);
  await page.locator(`[id="clause-${setup.clauseId}"]`).fill(reason);
  await page.locator(`[id="reason-${setup.repairPath}"]`).fill(reason);
  const registration = page.waitForResponse(result => result.url().endsWith("/plan-review-supplements") && result.request().method() === "POST");
  const policyCheck = page.waitForResponse(result => {
    if (!result.url().endsWith("/plan-review-previews") || result.request().method() !== "POST") return false;
    const mapping = result.request().postDataJSON().mapping;
    return mapping?.clauses.some((clause: { clause_id: string; disposition: string }) => clause.clause_id === setup.clauseId && clause.disposition === "POLICY");
  });
  await page.getByRole("button", { name: "单独登记上述人工补充", exact: true }).click();
  const registered = await registration;
  expect(registered.status(), await registered.text()).toBe(200);
  expect(registered.request().postDataJSON().supplements).toEqual([expect.objectContaining({ path: setup.repairPath, value: 4000, reason })]);
  const checked = await policyCheck;
  expect(checked.status(), await checked.text()).toBe(200);
  const saving = page.waitForResponse(result => result.url().endsWith("/plan-drafts") && result.request().method() === "POST");
  await page.getByRole("button", { name: "保存待审核版本", exact: true }).click();
  const saveResponse = await saving;
  expect(saveResponse.status(), await saveResponse.text()).toBe(200);
  const repaired: PlanVersionView = await saveResponse.json();
  expect(repaired.id).not.toBe(saved.id);
  expect(repaired.sourceText).toBe(saved.sourceText);
  expect(repaired.sourceHash).toBe(saved.sourceHash);
  expect(JSON.parse(repaired.planJson!).alert_rules[0].condition.price_fen).toBe(4000);
  expect(repaired.sourceCoverage?.coverageComplete).toBe(true);
  expect(repaired.sourceCoverage?.currentReviewBound).toBe(false);
  expect(repaired.sourceCoverage?.automaticFidelityVerified).toBe(false);
  await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeEnabled();
  const reviewing = page.waitForResponse(result => result.url().endsWith("/plan-review-confirmations") && result.request().method() === "POST");
  await page.getByRole("button", { name: "确认当前完整审核", exact: true }).click();
  const reviewed = await reviewing;
  expect(reviewed.status(), await reviewed.text()).toBe(200);
  expect(reviewed.request().postDataJSON()).toMatchObject(reviewBody(repaired));
  await expect(coveragePane(page)).toContainText("本次证明已完成审核");
  const current = await version(request, fixture, repaired.id);
  expect(current.sourceCoverage?.coverageReviewReceiptHash).not.toBeNull();
  expect(current.sourceCoverage?.currentReviewBound).toBe(true);
  rejected.push(
    await deniedWithoutWrites(request, fixture, "/api/v1/plan-review-confirmations", { ...reviewBody(repaired), sourceHash: "0".repeat(64) }),
    await deniedWithoutWrites(request, fixture, "/api/v1/plan-review-confirmations", { ...reviewBody(repaired), planVersionId: saved.id }),
    await deniedWithoutWrites(request, fixture, "/api/v1/plan-activations", { ...activationBody(current, 1), reviewId: originalReview.reviewId, reviewRevision: originalReview.reviewRevision }),
  );
  const old = await version(request, fixture, saved.id);
  expect(old.sourceText).toBe(saved.sourceText);
  expect(old.sourceCoverage?.coverageComplete).toBe(false);
  expect(old.reviewId).toBeNull();
  await expect(row).toContainText("POLICY");
  const completeImage = testInfo.outputPath("source-repair-complete-review.png");
  await coveragePane(page).getByRole("heading", { name: "原文条件核对", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: completeImage });
  await testInfo.attach("source-repair-complete-review", { path: completeImage, contentType: "image/png" });
  await testInfo.attach("actual-assisted-source-repair", { contentType: "application/json", body: JSON.stringify({
    setup, saved, repaired, current, originalBlockedVersion: old, rejected,
    scope: "explicit assisted source binding/classification repair; not raw automatic extraction acceptance",
  }, null, 2) });
});

test("real A-B-A delayed GET cannot replace the new exact review and activation context", async ({ page, request, readinessFixture: fixture }, testInfo) => {
  const setup = await sourceCase(request, fixture, "contexts");
  const a = await version(request, fixture, setup.versionIds[0]!);
  const b = await version(request, fixture, setup.versionIds[1]!);
  expect(a.sourceHash).not.toBe(b.sourceHash);
  let captured = false, oldBody: ReadinessAssessment | null = null, oldHash = "";
  let oldRaw: Buffer | null = null;
  const transport = { fulfillCallReturned: false, requestFailure: null as string | null,
    browserResponseObserved: false };
  let delayedRequest: Request | null = null;
  const observeOriginal = (response: Response) => {
    if (response.request() === delayedRequest) transport.browserResponseObserved = true;
  };
  page.on("response", observeOriginal);
  let release!: () => void, completed!: () => void;
  const released = new Promise<void>(done => { release = done; });
  const finished = new Promise<void>(done => { completed = done; });
  const aPath = `/api/v1/plan-versions/${a.id}/monitor-readiness`;
  await page.route(`**${aPath}`, async route => {
    if (captured) { await route.continue(); return; }
    captured = true;
    delayedRequest = route.request();
    const actual = await route.fetch();
    expect(actual.status(), await actual.text()).toBe(200);
    oldRaw = await actual.body();
    oldHash = createHash("sha256").update(oldRaw).digest("hex");
    oldBody = await actual.json();
    await released;
    try { await route.fulfill({ response: actual }); transport.fulfillCallReturned = true; }
    catch (error) {
      if (route.request().failure()?.errorText !== "net::ERR_ABORTED") throw error;
    }
    finally { transport.requestFailure = route.request().failure()?.errorText ?? null; completed(); }
  });
  try {
    await page.goto(`${fixture.base}/plans/${a.id}`);
    await expect.poll(() => oldBody !== null).toBe(true);
    expect(oldBody).toMatchObject({ summary: "NEEDS_REVIEW", snapshot: { context: { planVersionId: a.id, reviewReceiptHash: null } } });
    const navigation = page.getByRole("navigation", { name: "计划版本", exact: true });
    const bRead = page.waitForResponse(response => response.url().endsWith(`/plan-versions/${b.id}/monitor-readiness`));
    await navigation.getByRole("button", { name: new RegExp(`^v${b.version} ·`) }).click();
    expect((await (await bRead).json()).snapshot.context.planVersionId).toBe(b.id);
    await expect(coveragePane(page)).toContainText(b.sourceHash!);
    const reviewed = await command(request, fixture, "/api/v1/plan-review-confirmations", reviewBody(a));
    expect(reviewed.status(), await reviewed.text()).toBe(200);
    const current = await version(request, fixture, a.id);
    const activated = await command(request, fixture, "/api/v1/plan-activations", activationBody(current, 1));
    expect(activated.status(), await activated.text()).toBe(200);
    const aRead = page.waitForResponse(response => response.url().endsWith(aPath));
    await navigation.getByRole("button", { name: new RegExp(`^v${a.version} ·`) }).click();
    const fresh: ReadinessAssessment = await (await aRead).json();
    expect(fresh.summary).toBe("UNKNOWN");
    expect(fresh.snapshot.context.reviewReceiptHash).toBe(current.sourceCoverage!.coverageReviewReceiptHash);
    expect(fresh.axes.find(axis => axis.axis === "REVIEW_ACTIVATION")?.state).toBe("PASS");
    await expect(pane(page)).toContainText("尚未确定");
    await expect(pane(page)).toContainText("审核与启用：通过");
    await expect(coveragePane(page)).toContainText("本次证明已完成审核");
    const frozen = (await fixture.inspect()).storage;
    release(); await finished;
    await page.clock.runFor(64);
    await expect(pane(page)).toContainText("尚未确定");
    await expect(pane(page)).toContainText("审核与启用：通过");
    await expect(pane(page).getByRole("alert")).toHaveCount(0);
    await expect(pane(page)).not.toContainText("需要核对来源与审核");
    expect((await fixture.inspect()).storage).toEqual(frozen);
    const path = testInfo.outputPath("aba-new-reviewed-context.png");
    // Fit this single-rule evidence region without the locator screenshot's
    // temporary viewport expansion painting the fixed site header mid-image.
    await page.setViewportSize({ width: 1280, height: 2600 });
    await page.clock.runFor(64);
    const heading = pane(page).getByRole("heading", { name: "逐规则监控就绪", exact: true });
    await heading.click();
    await heading.evaluate(element => { element.scrollIntoView({ block: "start" }); window.scrollBy(0, -96); });
    await page.clock.runFor(64);
    await pane(page).screenshot({ path });
    await testInfo.attach("aba-new-reviewed-context", { path, contentType: "image/png" });
    await testInfo.attach("original-delayed-response-bytes", { contentType: "application/json", body: oldRaw! });
    await testInfo.attach("actual-delayed-readiness-response", { contentType: "application/json", body: JSON.stringify({
      oldBody, originalResponseSha256: oldHash, fresh, reviewedVersion: current,
      transport: { ...transport, originalRequestOutcome: transport.requestFailure === "net::ERR_ABORTED" ? "CANCELLED"
          : transport.browserResponseObserved ? "BROWSER_RESPONSE_OBSERVED" : "FULFILL_ATTEMPT_ONLY" },
      release: "route.fulfill attempted with the original fetched response; returning does not establish page delivery",
      scope: "new exact review/activation context; missing native evaluation remains UNKNOWN",
    }, null, 2) });
  } finally { release(); page.off("response", observeOriginal); }
});


const pbsTest = test.extend({ suspensionJourney: true });
pbsTest.use({ trace: "on" });
pbsTest("PBS real extraction review activation breach rebound SELL and replacement", async ({ page, request, readinessFixture: fixture }, testInfo) => {
  pbsTest.setTimeout(180_000);
  const evidence: Record<string, unknown> = { initial: fixture.initial };
  const pageErrors: string[] = []; page.on("pageerror", error => pageErrors.push(error.message));
  const writes: { path: string; body: unknown; status: number }[] = [];
  page.on("response", response => {
    if (response.request().method() === "POST") writes.push({ path: new URL(response.url()).pathname,
      body: response.request().postDataJSON(), status: response.status() });
  });
  await page.clock.resume();
  async function clickPost(label: string, path: string) {
    const pending = page.waitForResponse(r => r.url().endsWith(path) && r.request().method() === "POST");
    await page.getByRole("button", { name: label, exact: true }).click();
    const response = await pending;
    expect(response.status(), await response.text()).toBe(200); return response.json();
  }
  async function extract(source: string) {
    await page.clock.resume();
    await page.goto(fixture.base + "/plans");
    await page.getByLabel("粘贴中文计划原文", { exact: true }).fill(source);
    await page.getByRole("button", { name: "生成计划草稿", exact: true }).click();
    await expect(page.getByRole("heading", { name: "编辑规则、周期与执行窗口", exact: true })).toBeVisible({ timeout: 20000 });
    await expect(page.locator('[id="daily-.buy_suspension.condition.price_fen"]')).toHaveValue("2420");
    await page.clock.pauseAt(await page.evaluate(() => Date.now() + 100));
    return clickPost("保存待审核版本", "/plan-drafts");
  }
  async function loadGuard() {
    await page.getByRole("button", { name: "读取本原文全部禁买义务与当前启用依据", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "已读取完整原文义务" })).toBeVisible();
    const select = page.locator('[data-pbs="obligation"]');
    const id = await select.locator('option').nth(1).getAttribute("value");
    expect(id).toMatch(/^[a-f0-9]{64}$/); await select.selectOption(id!);
    await page.locator('[data-pbs="reason"]').fill("Explicit independent clarification of this exact source guard and reviewed checking interval.");
    await clickPost("独立登记本原文禁买澄清", "/plan-review-supplements");
    await expect(page.getByRole("status").filter({ hasText: "禁买依据已独立登记" })).toBeVisible();
    return clickPost("保存待审核版本", "/plan-drafts");
  }
  async function reviewActivate(saved: PlanVersionView, oldActive: string) {
    expect((await fixture.inspect()).pbs!.activeVersionId).toBe(oldActive);
    await expect(page.getByRole("button", { name: "确认当前完整审核", exact: true })).toBeEnabled();
    const reviewed = await clickPost("确认当前完整审核", "/plan-review-confirmations");
    expect(writes.filter(w => w.path.endsWith("/plan-review-confirmations")).at(-1)!.body).toMatchObject({
      planVersionId: saved.id, contentHash: saved.contentHash, sourceHash: saved.sourceHash,
      reviewEvidenceHash: saved.reviewEvidenceHash, expectedRevision: saved.reviewRevision,
      coverageEvidenceHash: saved.sourceCoverage!.coverageEvidenceHash,
      coverageRulesVersion: saved.sourceCoverage!.rulesVersion });
    expect((await fixture.inspect()).pbs!.activeVersionId).toBe(oldActive);
    await expect(page.locator(".daily-review")).toContainText("本候选尚未启用");
    const activated = await clickPost("启用当前审核绑定", "/plan-activations");
    expect(writes.filter(w => w.path.endsWith("/plan-activations")).at(-1)!.body).toMatchObject({
      planVersionId: saved.id, contentHash: saved.contentHash, sourceHash: saved.sourceHash,
      reviewEvidenceHash: saved.reviewEvidenceHash, reviewId: reviewed.reviewId,
      reviewRevision: reviewed.revision });
    expect(activated.planVersionId).toBe(saved.id);
    expect((await fixture.inspect()).pbs!.activeVersionId).toBe(saved.id);
    return { reviewed, activated };
  }
  async function nextAndRefresh() {
    const active = (await fixture.inspect()).pbs!.activeVersionId;
    // Detach real consumers while the fixed fixture clock traverses several
    // scheduled duties, then reopen the exact persisted version for inspection.
    await page.goto("about:blank");
    const inspection = await fixture.next(); await page.clock.pauseAt(new Date(inspection.now));
    await page.goto(fixture.base + "/plans/" + active);
    await page.locator(".daily-operations").getByRole("button", { name: "刷新当前状态", exact: true }).click();
    await pane(page).getByRole("button", { name: "重新读取监控就绪状态", exact: true }).click();
    return inspection;
  }
  async function auditRegion(region: Locator, stage: string) {
    const results: unknown[] = [];
    const axeUrl = fixture.base + prefix + "/axe-core.js";
    await page.route(axeUrl, route => route.fulfill({ contentType: "application/javascript", path: axePath }));
    await page.addScriptTag({ url: axeUrl });
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(async () => { await document.fonts.ready; });
      await page.clock.runFor(128); await region.scrollIntoViewIfNeeded();
      const box = await region.boundingBox(); await page.clock.runFor(64);
      expect(await region.boundingBox()).toEqual(box);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), stage + " overflow " + width).toBe(true);
      const controls = await region.locator('button,input:not([type="checkbox"]),select,textarea,label:has(input[type="checkbox"])')
        .evaluateAll(elements => elements.map(element => ({ tag: element.tagName,
          text: element.textContent?.slice(0, 40), height: element.getBoundingClientRect().height }))
          .filter(element => element.height > 0));
      expect(controls.every(c => c.height >= 44), JSON.stringify({ stage, width, controls })).toBe(true);
      const control = region.locator("button:enabled, input:enabled, select:enabled, textarea:enabled").first();
      await control.focus(); await expect(control).toBeFocused(); await page.keyboard.press("Tab");
      if (await region.locator("button:enabled, input:enabled, select:enabled, textarea:enabled").count() > 1)
        expect(await region.evaluate(element => element.contains(document.activeElement))).toBe(true);
      else {
        await expect(control).not.toBeFocused(); await page.keyboard.press("Shift+Tab");
        await expect(control).toBeFocused();
      }
      const retire = region.locator('[data-pbs="retire"]');
      if (await retire.count()) {
        const before = writes.length;
        await retire.focus(); await page.keyboard.press("Space"); await expect(retire).toBeChecked();
        await page.keyboard.press("Space"); await expect(retire).not.toBeChecked();
        const label = retire.locator(".."); const bounds = await label.boundingBox();
        await label.click({ position: { x: bounds!.width - 4, y: bounds!.height / 2 } });
        await expect(retire).toBeChecked();
        await retire.focus(); await page.keyboard.press("Space"); await expect(retire).not.toBeChecked();
        const acknowledge = region.locator('[data-pbs="acknowledge"]');
        await expect(acknowledge).toBeDisabled();
        await acknowledge.locator("..").scrollIntoViewIfNeeded();
        const disabledLabel = await acknowledge.locator("..").boundingBox();
        await page.mouse.click(disabledLabel!.x + disabledLabel!.width - 4,
          disabledLabel!.y + disabledLabel!.height / 2);
        await expect(acknowledge).not.toBeChecked(); expect(writes).toHaveLength(before);
      }
      await page.clock.resume();
      const violations = await region.evaluate(async element => {
        const axe = (window as any).axe;
        return (await axe.run(element, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] })).violations;
      });
      await page.clock.pauseAt(await page.evaluate(() => Date.now() + 100));
      expect(violations).toEqual([]);
      const path = testInfo.outputPath("pbs-" + stage + "-" + width + ".png");
      const banner = await page.getByRole("banner").boundingBox();
      await region.evaluate((element, headerHeight) => window.scrollTo(0, Math.max(0,
        window.scrollY + element.getBoundingClientRect().top - headerHeight - 16)), banner?.height ?? 0);
      await page.screenshot({ path }); await testInfo.attach(stage + "-" + width, { path, contentType: "image/png" });
      if (await region.locator("form").count()) {
        await region.locator("form").last().scrollIntoViewIfNeeded();
        const focusTarget = region.locator('[data-pbs="start"]');
        await focusTarget.focus();
        await focusTarget.evaluate((element, headerHeight) => window.scrollTo(0, Math.max(0,
          window.scrollY + element.getBoundingClientRect().top - Math.max(headerHeight + 16, 240))), banner?.height ?? 0);
        const focused = await focusTarget.boundingBox();
        expect(focused!.y).toBeGreaterThanOrEqual((banner?.height ?? 0) + 16);
        expect(focused!.y + focused!.height).toBeLessThanOrEqual(900);
        expect(await focusTarget.evaluate(element => {
          const r = element.getBoundingClientRect();
          const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return top === element || top !== null && element.contains(top);
        }), "focused replacement control is not covered by the fixed header").toBe(true);
        await expect(focusTarget).toBeFocused();
        const bottom = testInfo.outputPath("pbs-" + stage + "-bottom-" + width + ".png");
        await page.screenshot({ path: bottom });
        await testInfo.attach(stage + "-bottom-" + width, { path: bottom, contentType: "image/png" });
        results.push({ width, focusedControl: "strategyStart", focused, banner, unobscured: true, bottom });
      }
      results.push({ width, height: 900, controls, violations, path });
    }
    evidence[stage + "Audit"] = results;
  }
  try {
    const initial = await extract(fixture.initial.pbs!.sources[0]!);
    expect(initial.canActivate).toBe(false); expect(initial.reviewId).toBeNull();
    await auditRegion(page.getByRole("region", { name: "禁买澄清与接替登记", exact: true }), "clarification");
    const clarified = await loadGuard();
    evidence.first = { initial, clarified, ...await reviewActivate(clarified, fixture.initial.pbs!.activeVersionId) };
    const breached = await nextAndRefresh(); evidence.breached = breached;
    await expect(page.getByRole("region", { name: "持续禁买保护", exact: true })).toContainText("本计划禁止全部后续买入");
    expect(breached.pbs!.guards.some(g => g.payload.trigger?.close_fen === 2419)).toBe(true);
    const oldTrigger = breached.pbs!.guards.find(g => g.payload.trigger)!.payload.trigger;
    const rebound = await nextAndRefresh(); evidence.rebound = rebound;
    expect(rebound.pbs!.guards.find(g => g.payload.trigger)!.payload.trigger).toEqual(oldTrigger);
    await expect(page.getByRole("region", { name: "持续禁买保护", exact: true })).toContainText("本计划禁止全部后续买入");
    await expect(page.locator(".daily-operations").getByRole("button", { name: "确认一次模拟卖出100股", exact: true })).toBeEnabled();
    evidence.sell = await clickPost("确认一次模拟卖出100股", "/simulated-trades");
    expect((evidence.sell as { side: string }).side).toBe("SELL");
    const guard = page.getByRole("region", { name: "持续禁买保护", exact: true });
    await auditRegion(guard, "latched");
    const sourceButton = guard.getByRole("button", { name: "查看原文核对与接替要求", exact: true });
    await sourceButton.focus(); await expect(sourceButton).toBeFocused(); await page.keyboard.press("Enter");
    const replacementSetup = await command(request, fixture, prefix + "/source-case",
      { scenario: "buy-suspension-replacement" });
    expect(replacementSetup.status(), await replacementSetup.text()).toBe(200);
    const setup = await replacementSetup.json();
    expect(setup.origin).toBe("HUMAN_SYNTHETIC");
    await page.goto(fixture.base + "/plans/" + setup.versionIds[0]);
    await expect(page.getByRole("heading", { name: "编辑规则、周期与执行窗口", exact: true })).toBeVisible();
    const replacementInitial = setup;
    const replacement = await loadGuard();
    await page.getByRole("button", { name: "读取本原文全部禁买义务与当前启用依据", exact: true }).click();
    await expect(page.locator('[data-pbs="obligation"] option').nth(1)).toHaveCount(1);
    await page.locator('[data-pbs="reason"]').fill("Explicit replacement by the new exact source without erasing the original observed breach.");
    await page.locator('[data-pbs="excerpt"]').fill(fixture.initial.pbs!.statement);
    await page.locator('[data-pbs="start"]').fill("2026-09-08T09:50:00+08:00");
    await auditRegion(page.getByRole("region", { name: "禁买澄清与接替登记", exact: true }), "replacement");
    evidence.intent = await clickPost("独立登记新原文接替意图", "/plan-review-supplements");
    await expect(page.getByRole("status").filter({ hasText: "禁买依据已独立登记" })).toBeVisible();
    const finalSaved = await clickPost("保存待审核版本", "/plan-drafts");
    await auditRegion(page.locator(".daily-review__actions"), "review-activation");
    expect(finalSaved.sourceText).toBe(setup.source);
    expect(finalSaved.sourceHash).toBe(createHash("sha256").update(setup.source, "utf8").digest("hex"));
    const replacementBinding = await reviewActivate(finalSaved, clarified.id);
    evidence.replacement = { replacementInitial, replacement, finalSaved, ...replacementBinding };
    const beforeStart = await fixture.inspect(); evidence.beforeStart = beforeStart;
    expect(beforeStart.pbs!.guardCurrent).toBe(false);
    expect(beforeStart.pbs!.guards.some(g => g.payload.owner_plan_version_id === finalSaved.id)).toBe(false);
    const beforeRead = await request.get(fixture.base + "/api/v1/plan-versions/" + finalSaved.id + "/monitor-readiness");
    expect(beforeRead.status()).toBe(200);
    const beforeAssessment: ReadinessAssessment = await beforeRead.json();
    expect(beforeAssessment.snapshot.buySuspension!.state).toBeNull();
    expect(beforeAssessment.snapshot.buySuspension!.outcome).toBe("UNVERIFIED");
    await nextAndRefresh();
    const final = await fixture.inspect(); evidence.final = final;
    expect(final.pbs!.guards.find(g => g.payload.trigger)!.payload.trigger).toEqual(oldTrigger);
    expect(final.pbs!.aiCalls).toHaveLength(1);
    const newGuard = final.pbs!.guards.find(g => g.payload.owner_plan_version_id === finalSaved.id)!;
    expect(newGuard.revision).toBeGreaterThan(0);
    expect(newGuard.payload.birth_activation_revision).toBe(replacementBinding.activated.revision);
    expect(newGuard.payload.source_hash).toBe(finalSaved.sourceHash);
    expect(newGuard.payload.content_hash).toBe(finalSaved.contentHash);
    expect(newGuard.payload.review_id).toBe(replacementBinding.reviewed.reviewId);
    expect(newGuard.payload.definition).toEqual(JSON.parse(finalSaved.planJson).buy_suspension);
    expect(newGuard.payload.target).toBe("2026-09-08T09:50:00+08:00");
    expect(newGuard.payload.trigger).toBeNull();
    expect(newGuard.payload.definition.effective_from).toBe("2026-09-08T09:45:00+08:00");
    expect(newGuard.payload.coverage!.through).toBe("2026-09-08T09:50:00+08:00");
    expect(final.pbs!.guardCurrent).toBe(true);
    const actualRuntime = await request.get(fixture.base + "/api/v1/plan-runtime/003043.SZ");
    expect(actualRuntime.status()).toBe(200); const runtimeView = await actualRuntime.json();
    expect(runtimeView.snapshot.signals.filter((s: { side: string }) => s.side === "BUY"))
      .toEqual([expect.objectContaining({ executableQty: 100, state: "READY" })]);
    evidence.newGuardRuntime = runtimeView;
    expect(pageErrors).toEqual([]); expect(writes.every(w => w.status < 400)).toBe(true);
  } finally {
    await testInfo.attach("pbs-public-journey", { contentType: "application/json", body: JSON.stringify({ evidence, writes, pageErrors }, null, 2) });
  }
});
